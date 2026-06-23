"""Redacted data quality reporting for local net worth refreshes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.6.4"

SUMMARY_NAME = "data_quality_summary.json"
WARNINGS_NAME = "data_quality_warnings.md"
REPORT_NAME = "DATA_QUALITY_SUMMARY_V064.md"


@dataclass(frozen=True)
class DataQualitySummaryResult:
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False


def write_data_quality_summary(
    *,
    out_dir: Path,
    providers_requested: list[str],
    providers_succeeded: list[str],
    providers_failed: list[str],
    manual_layer_status: dict[str, bool],
    account_nav_row_count: int,
    position_row_count: int,
    snapshot_generated: bool,
    fx_file_present: bool,
    fx_complete: bool,
    stale_or_mixed_date_warning_codes: list[str],
    dashboard_generated: bool,
    upstream_warning_codes: list[WarningCode],
    integrity_guard_generated: bool = False,
    integrity_ready_to_confirm: bool = False,
    integrity_blocking_warning_codes: list[str] | None = None,
) -> DataQualitySummaryResult:
    """Write refresh data-quality outputs without private values."""

    warnings = _data_quality_warning_codes(
        providers_failed=providers_failed,
        snapshot_generated=snapshot_generated,
        dashboard_generated=dashboard_generated,
        fx_file_present=fx_file_present,
        fx_complete=fx_complete,
        stale_or_mixed_date_warning_codes=stale_or_mixed_date_warning_codes,
    )
    completion = (
        WarningCode.DATA_QUALITY_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.DATA_QUALITY_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "warnings": out_dir / WARNINGS_NAME,
        "report": out_dir / REPORT_NAME,
    }
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "redacted": True,
        "providers": {
            "requested": sorted(providers_requested),
            "succeeded": sorted(providers_succeeded),
            "failed": sorted(providers_failed),
        },
        "manual_layers": {
            key: bool(value) for key, value in sorted(manual_layer_status.items())
        },
        "counts": {
            "account_nav_row_count": max(0, int(account_nav_row_count)),
            "position_row_count": max(0, int(position_row_count)),
        },
        "snapshot": {
            "generated": bool(snapshot_generated),
        },
        "fx": {
            "file_present": bool(fx_file_present),
            "complete": bool(fx_complete),
        },
        "dates": {
            "stale_or_mixed_date_warning_codes": sorted(stale_or_mixed_date_warning_codes),
        },
        "dashboard": {
            "generated": bool(dashboard_generated),
        },
        "integrity_guard": {
            "generated": bool(integrity_guard_generated),
            "ready_to_confirm": bool(integrity_ready_to_confirm),
            "blocking_warning_codes": sorted(integrity_blocking_warning_codes or []),
        },
        "source_warning_codes": [code.value for code in upstream_warning_codes],
        "warning_codes": [code.value for code in warnings],
    }
    output_paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_warnings(output_paths["warnings"], warnings)
    output_paths["report"].write_text(_report(summary), encoding="utf-8")

    return DataQualitySummaryResult(
        output_dir=out_dir,
        output_paths=output_paths,
        warning_codes=warnings,
        generated=True,
    )


def _data_quality_warning_codes(
    *,
    providers_failed: list[str],
    snapshot_generated: bool,
    dashboard_generated: bool,
    fx_file_present: bool,
    fx_complete: bool,
    stale_or_mixed_date_warning_codes: list[str],
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if providers_failed:
        warnings.append(WarningCode.DATA_QUALITY_BROKER_FAILURES)
    if not snapshot_generated or not dashboard_generated:
        warnings.append(WarningCode.DATA_QUALITY_REFRESH_INCOMPLETE)
    if not fx_file_present or not fx_complete:
        warnings.append(WarningCode.DATA_QUALITY_FX_INCOMPLETE)
    if stale_or_mixed_date_warning_codes:
        warnings.append(WarningCode.DATA_QUALITY_STALE_OR_MIXED_DATES)
    return warnings


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = ["# Data Quality Warnings", ""]
    if warnings:
        lines.extend(f"- `{code.value}`" for code in warnings)
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(summary: dict[str, Any]) -> str:
    providers = summary["providers"]
    layers = summary["manual_layers"]
    counts = summary["counts"]
    warnings = summary["warning_codes"]
    integrity = summary.get("integrity_guard", {})
    lines = [
        "# Data Quality Summary v0.6.4",
        "",
        "Redacted refresh quality report. It records statuses and row counts only.",
        "",
        "## Providers",
        "",
        f"- Requested: {', '.join(providers['requested']) or 'None'}",
        f"- Succeeded: {', '.join(providers['succeeded']) or 'None'}",
        f"- Failed: {', '.join(providers['failed']) or 'None'}",
        "",
        "## Manual Layers",
        "",
        *[f"- {name}: {_yes_no(value)}" for name, value in sorted(layers.items())],
        "",
        "## Counts",
        "",
        f"- Account NAV rows: {counts['account_nav_row_count']}",
        f"- Position rows: {counts['position_row_count']}",
        "",
        "## Snapshot And Dashboard",
        "",
        f"- Snapshot generated: {_yes_no(summary['snapshot']['generated'])}",
        f"- Dashboard generated: {_yes_no(summary['dashboard']['generated'])}",
        "",
        "## Integrity Guard",
        "",
        f"- Guard generated: {_yes_no(bool(integrity.get('generated')))}",
        f"- Ready to confirm history: {_yes_no(bool(integrity.get('ready_to_confirm')))}",
        (
            "- Blocking warning codes: "
            + (
                ", ".join(integrity.get("blocking_warning_codes", []))
                if integrity.get("blocking_warning_codes")
                else "None"
            )
        ),
        "",
        "## FX",
        "",
        f"- FX file present: {_yes_no(summary['fx']['file_present'])}",
        f"- FX complete: {_yes_no(summary['fx']['complete'])}",
        "",
        "## Warning Codes",
        "",
        *[f"- `{code}`" for code in warnings],
    ]
    return "\n".join(lines) + "\n"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result
