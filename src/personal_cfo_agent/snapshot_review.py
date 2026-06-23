"""Redacted pending snapshot review outputs for local net worth refreshes."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.warning_text import warning_details, warning_lines


SCHEMA_VERSION = "v0.6.6"
SUMMARY_NAME = "snapshot_review_summary.json"
REPORT_NAME = "SNAPSHOT_REVIEW_V066.md"
HTML_NAME = "snapshot_review.html"


@dataclass(frozen=True)
class SnapshotReviewResult:
    refresh_dir: Path
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    ready_to_confirm: bool = False
    generated: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)


def write_snapshot_review(*, refresh_dir: Path, out_dir: Path) -> SnapshotReviewResult:
    """Write a redacted review page before confirmed history is updated."""

    integrity = _read_json(refresh_dir / "integrity_guard" / "net_worth_integrity_summary.json")
    data_quality = _read_json(refresh_dir / "data_quality_summary.json")
    dashboard_summary = _read_json(refresh_dir / "dashboard" / "dashboard_v050_summary.json")
    warnings: list[WarningCode] = []
    ready_to_confirm = bool(integrity.get("ready_to_confirm")) if integrity else False
    if not integrity:
        warnings.append(WarningCode.INTEGRITY_GUARD_BLOCKED)
    elif not ready_to_confirm:
        warnings.append(WarningCode.INTEGRITY_GUARD_BLOCKED)

    blocking_codes = [
        str(code)
        for code in (integrity.get("blocking_warning_codes", []) if integrity else [])
        if str(code)
    ]
    warning_codes = _dedupe_text(
        [
            *[code.value for code in warnings],
            *blocking_codes,
            *[
                str(code)
                for code in (data_quality.get("warning_codes", []) if data_quality else [])
                if str(code)
            ],
        ]
    )
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "redacted": True,
        "refresh_dir": str(refresh_dir),
        "ready_to_confirm_history": ready_to_confirm,
        "confirmed_history_write_allowed": ready_to_confirm,
        "blocking_warning_codes": blocking_codes,
        "provider_checks": integrity.get("provider_checks", {}) if integrity else {},
        "data_quality": _data_quality_snapshot(data_quality),
        "dashboard_generated": bool(dashboard_summary),
        "next_safe_action": (
            "rerun_with_confirm_snapshot_history_write"
            if ready_to_confirm
            else "review_blocking_warning_codes_before_confirming"
        ),
        "warning_codes": warning_codes,
        "warning_details": warning_details(warning_codes),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "report": out_dir / REPORT_NAME,
        "html": out_dir / HTML_NAME,
    }
    output_paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    markdown = _markdown(summary)
    output_paths["report"].write_text(markdown, encoding="utf-8")
    output_paths["html"].write_text(_html(markdown), encoding="utf-8")
    return SnapshotReviewResult(
        refresh_dir=refresh_dir,
        output_dir=out_dir,
        output_paths=output_paths,
        ready_to_confirm=ready_to_confirm,
        generated=True,
        warning_codes=[
            WarningCode.SNAPSHOT_REVIEW_READY_TO_CONFIRM
            if ready_to_confirm
            else WarningCode.SNAPSHOT_REVIEW_BLOCKED
        ],
    )


def _data_quality_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {"generated": False}
    providers = payload.get("providers", {})
    counts = payload.get("counts", {})
    return {
        "generated": True,
        "providers_requested": providers.get("requested", []),
        "providers_succeeded": providers.get("succeeded", []),
        "providers_failed": providers.get("failed", []),
        "account_nav_row_count": counts.get("account_nav_row_count", 0),
        "position_row_count": counts.get("position_row_count", 0),
        "fx_complete": bool(payload.get("fx", {}).get("complete")),
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Snapshot Review v0.6.6",
        "",
        "Local-only redacted review before confirmed history write.",
        "",
        "## Confirmation Gate",
        "",
        f"- Ready to confirm history: {_yes_no(summary['ready_to_confirm_history'])}",
        f"- Confirmed history write allowed: {_yes_no(summary['confirmed_history_write_allowed'])}",
        f"- Next safe action: `{summary['next_safe_action']}`",
        "",
        "## Provider Gate",
        "",
    ]
    provider_checks = summary.get("provider_checks", {})
    if isinstance(provider_checks, dict) and provider_checks:
        for name, check in sorted(provider_checks.items()):
            lines.append(
                f"- {name}: status={check.get('status', 'unknown')}; "
                f"account_nav_rows={check.get('account_nav_rows', 0)}; "
                f"provider_reported_nav_rows={check.get('provider_reported_nav_rows', 0)}"
            )
    else:
        lines.append("- None")
    quality = summary["data_quality"]
    lines.extend(
        [
            "",
            "## Data Quality",
            "",
            f"- Data quality generated: {_yes_no(bool(quality.get('generated')))}",
            f"- Providers requested: {_join(quality.get('providers_requested', []))}",
            f"- Providers succeeded: {_join(quality.get('providers_succeeded', []))}",
            f"- Providers failed: {_join(quality.get('providers_failed', []))}",
            f"- Account NAV rows: {quality.get('account_nav_row_count', 0)}",
            f"- Position rows: {quality.get('position_row_count', 0)}",
            f"- FX complete: {_yes_no(bool(quality.get('fx_complete')))}",
            "",
            "## Blocking Warning Codes",
            "",
            *_warning_code_lines(summary.get("blocking_warning_codes", [])),
            "",
            "## Warning Explanations",
            "",
            *warning_lines(summary.get("warning_codes", [])),
        ]
    )
    return "\n".join(lines) + "\n"


def _html(markdown: str) -> str:
    blocks: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            blocks.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            blocks.append(f"<p class=\"bullet\">{html.escape(line[2:])}</p>")
        elif line:
            blocks.append(f"<p>{html.escape(line)}</p>")
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        "<title>Snapshot Review</title><style>"
        "body{margin:0;background:#fbfaf7;color:#16202a;font-family:Segoe UI,Arial,sans-serif;}"
        "main{max-width:980px;margin:0 auto;padding:42px 28px 68px;}"
        "h1{font-size:34px;margin:0 0 18px;}h2{font-size:20px;margin:30px 0 12px;padding-top:18px;border-top:1px solid #d8dedb;}"
        "p{color:#617080;line-height:1.5}.bullet{background:#fff;border:1px solid #d8dedb;border-radius:8px;padding:10px 12px;color:#16202a;}"
        "</style></head><body><main>"
        + "\n".join(blocks)
        + "</main></body></html>\n"
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _warning_code_lines(codes: object) -> list[str]:
    if not isinstance(codes, list) or not codes:
        return ["- None"]
    return [f"- `{code}`" for code in codes if str(code)]


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _join(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "None"
    return ", ".join(str(item) for item in value if str(item)) or "None"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
