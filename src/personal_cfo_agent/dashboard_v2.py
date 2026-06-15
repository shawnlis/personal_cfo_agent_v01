"""Offline account-NAV-first dashboard for v0.3.3 merged ledger bundles."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import (
    ACCOUNT_NAV_FIELDNAMES,
    POSITION_LEDGER_FIELDNAMES,
)


DASHBOARD_V2_STATEMENT = (
    "This is an offline account-NAV-first personal finance dashboard, not "
    "investment, tax, estate, insurance, or trading advice."
)

ACCOUNT_NAV_DASHBOARD_FIELDNAMES = [
    "provider",
    "account_id_hash",
    "as_of_date",
    "base_currency",
    "account_nav",
    "nav_source",
    "provider_reported_nav_available",
    "source_confidence",
    "dashboard_status",
    "warning_codes",
]

PROVIDER_NAV_SUMMARY_FIELDNAMES = [
    "provider",
    "account_count",
    "account_nav_total",
    "provider_reported_account_count",
    "derived_account_count",
    "missing_nav_account_count",
    "base_currencies",
    "import_status",
    "warning_codes",
]


@dataclass
class DashboardV2Result:
    input_dir: Path
    output_dir: Path | None
    output_paths: dict[str, Path] = field(default_factory=dict)
    account_count: int = 0
    provider_count: int = 0
    position_count: int = 0
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False


def write_dashboard_v2(input_dir: Path, output_dir: Path) -> DashboardV2Result:
    warnings: list[WarningCode] = []
    if not input_dir.exists():
        warnings.append(WarningCode.DASHBOARD_V2_INPUT_MISSING)
        return DashboardV2Result(input_dir=input_dir, output_dir=None, warning_codes=warnings)

    account_path = input_dir / "merged_account_nav_ledger.csv"
    if not account_path.exists():
        warnings.append(WarningCode.DASHBOARD_V2_ACCOUNT_NAV_LEDGER_MISSING)
        return DashboardV2Result(input_dir=input_dir, output_dir=None, warning_codes=warnings)

    account_rows = _read_csv(account_path)
    if not account_rows:
        warnings.append(WarningCode.DASHBOARD_V2_ACCOUNT_NAV_EMPTY)
        return DashboardV2Result(input_dir=input_dir, output_dir=None, warning_codes=warnings)

    provider_summary_path = input_dir / "merged_provider_summary.json"
    provider_summary = _read_json(provider_summary_path)
    if provider_summary is None:
        warnings.append(WarningCode.DASHBOARD_V2_PROVIDER_SUMMARY_MISSING)

    account_source_map_path = input_dir / "account_source_map.json"
    account_source_map = _read_json(account_source_map_path) or {}
    merge_warning_text = _read_text(input_dir / "merge_warnings.md")
    merge_summary = _read_json(input_dir / "merged_account_nav_summary.json") or {}

    position_path = input_dir / "merged_position_ledger.csv"
    position_rows: list[dict[str, str]] = []
    if position_path.exists():
        position_rows = _read_csv(position_path)
        if position_rows:
            warnings.append(WarningCode.DASHBOARD_V2_POSITION_LEDGER_BEST_EFFORT)
    else:
        warnings.append(WarningCode.DASHBOARD_V2_POSITION_LEDGER_MISSING)

    warnings.extend(
        _input_warning_codes(
            account_rows,
            provider_summary,
            merge_summary,
            merge_warning_text,
        )
    )
    warnings = _dedupe_warning_codes(warnings)

    account_dashboard_rows = [_account_dashboard_row(row) for row in account_rows]
    provider_rows = _provider_nav_rows(
        account_dashboard_rows,
        provider_summary=provider_summary,
    )
    provider_count = len({row["provider"] for row in account_dashboard_rows if row["provider"]})

    completion = (
        WarningCode.DASHBOARD_V2_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.DASHBOARD_V2_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown_report": output_dir / "PERSONAL_CFO_DASHBOARD_V040.md",
        "dashboard_summary": output_dir / "dashboard_v040_summary.json",
        "account_nav_dashboard": output_dir / "account_nav_dashboard.csv",
        "provider_nav_summary": output_dir / "provider_nav_summary.csv",
        "dashboard_warnings": output_dir / "dashboard_warnings.md",
    }
    if position_rows:
        paths["position_drilldown"] = output_dir / "position_drilldown.csv"

    _write_csv(
        paths["account_nav_dashboard"],
        ACCOUNT_NAV_DASHBOARD_FIELDNAMES,
        account_dashboard_rows,
    )
    _write_csv(paths["provider_nav_summary"], PROVIDER_NAV_SUMMARY_FIELDNAMES, provider_rows)
    if position_rows:
        _write_csv(paths["position_drilldown"], POSITION_LEDGER_FIELDNAMES, position_rows)

    summary = {
        "version": "v0.4.0",
        "account_nav_first": True,
        "offline_only": True,
        "broker_connections": "not_used",
        "input_dir": str(input_dir),
        "account_count": len(account_dashboard_rows),
        "provider_count": provider_count,
        "position_count": len(position_rows),
        "base_currencies": _sorted_values(
            row.get("base_currency", "") for row in account_dashboard_rows
        ),
        "provider_nav_totals": {
            row["provider"]: row["account_nav_total"] for row in provider_rows
        },
        "provider_import_status": {
            row["provider"]: row["import_status"] for row in provider_rows
        },
        "position_ledger": "best_effort_drilldown" if position_rows else "missing",
        "account_source_map_present": bool(account_source_map),
        "merge_warnings_present": bool(merge_warning_text.strip()),
        "warning_codes": [code.value for code in warnings],
    }
    paths["dashboard_summary"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_markdown(
        paths["markdown_report"],
        summary=summary,
        provider_rows=provider_rows,
        warnings=warnings,
    )
    _write_warnings(paths["dashboard_warnings"], warnings)

    return DashboardV2Result(
        input_dir=input_dir,
        output_dir=output_dir,
        output_paths=paths,
        account_count=len(account_dashboard_rows),
        provider_count=provider_count,
        position_count=len(position_rows),
        warning_codes=warnings,
        generated=True,
    )


def _account_dashboard_row(row: dict[str, str]) -> dict[str, str]:
    nav_source = _clean(row.get("nav_source"))
    account_nav = _clean(row.get("account_nav"))
    status = "available" if account_nav else "missing_nav"
    if nav_source == "provider_reported":
        status = "provider_reported_nav"
    elif account_nav:
        status = "derived_nav"
    return {
        "provider": _clean(row.get("provider")),
        "account_id_hash": _clean(row.get("account_id_hash")),
        "as_of_date": _clean(row.get("as_of_date")),
        "base_currency": _clean(row.get("base_currency")),
        "account_nav": account_nav,
        "nav_source": nav_source,
        "provider_reported_nav_available": _clean(
            row.get("provider_reported_nav_available")
        ),
        "source_confidence": _clean(row.get("source_confidence")),
        "dashboard_status": status,
        "warning_codes": _clean(row.get("warning_codes")),
    }


def _provider_nav_rows(
    account_rows: list[dict[str, str]], *, provider_summary: dict[str, Any] | None
) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in account_rows:
        grouped.setdefault(row["provider"] or "unknown", []).append(row)
    import_status = _provider_import_status(provider_summary)
    rows: list[dict[str, str]] = []
    for provider, rows_for_provider in sorted(grouped.items()):
        warning_codes = _dedupe_text(
            code
            for row in rows_for_provider
            for code in row.get("warning_codes", "").split(";")
            if code
        )
        rows.append(
            {
                "provider": provider,
                "account_count": str(len(rows_for_provider)),
                "account_nav_total": _number_to_text(
                    sum(
                        _parse_number(row.get("account_nav")) or 0.0
                        for row in rows_for_provider
                    )
                ),
                "provider_reported_account_count": str(
                    sum(
                        1
                        for row in rows_for_provider
                        if row.get("provider_reported_nav_available") == "yes"
                    )
                ),
                "derived_account_count": str(
                    sum(1 for row in rows_for_provider if row.get("nav_source") != "provider_reported")
                ),
                "missing_nav_account_count": str(
                    sum(1 for row in rows_for_provider if not row.get("account_nav"))
                ),
                "base_currencies": ";".join(
                    _sorted_values(row.get("base_currency", "") for row in rows_for_provider)
                ),
                "import_status": import_status.get(provider, ""),
                "warning_codes": ";".join(warning_codes),
            }
        )
    return rows


def _provider_import_status(provider_summary: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(provider_summary, dict):
        return {}
    result: dict[str, str] = {}
    for entry in provider_summary.get("bundle_results", []):
        if not isinstance(entry, dict):
            continue
        provider = _clean(entry.get("provider"))
        status = _clean(entry.get("status"))
        if provider and status:
            result[provider] = status
    return result


def _input_warning_codes(
    account_rows: list[dict[str, str]],
    provider_summary: dict[str, Any] | None,
    merge_summary: dict[str, Any],
    merge_warning_text: str,
) -> list[WarningCode]:
    raw_codes = set()
    for row in account_rows:
        raw_codes.update(code for code in row.get("warning_codes", "").split(";") if code)
    for source in (provider_summary, merge_summary):
        if isinstance(source, dict):
            raw_codes.update(str(code) for code in source.get("warning_codes", []))
    raw_codes.update(_warning_codes_from_text(merge_warning_text))

    warnings: list[WarningCode] = []
    if "ACCOUNT_NAV_RECONCILIATION_MISMATCH" in raw_codes:
        warnings.append(WarningCode.DASHBOARD_V2_NAV_RECONCILIATION_WARNINGS)
    if "STALE_PROVIDER_BUNDLE" in raw_codes:
        warnings.append(WarningCode.DASHBOARD_V2_STALE_DATA_WARNING)
    if "MIXED_AS_OF_DATES" in raw_codes:
        warnings.append(WarningCode.DASHBOARD_V2_MIXED_AS_OF_DATES)
    if any(not _clean(row.get("account_nav")) for row in account_rows):
        warnings.append(WarningCode.DASHBOARD_V2_ACCOUNT_NAV_EMPTY)
    return warnings


def _warning_codes_from_text(text: str) -> set[str]:
    known_codes = {code.value for code in WarningCode}
    tokens = {
        token.strip("`-:,.()[]{} ")
        for line in text.splitlines()
        for token in line.split()
    }
    return {token for token in tokens if token in known_codes}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(
    path: Path,
    *,
    summary: dict[str, Any],
    provider_rows: list[dict[str, str]],
    warnings: list[WarningCode],
) -> None:
    lines = [
        "# Personal CFO Dashboard v0.4.0",
        "",
        DASHBOARD_V2_STATEMENT,
        "",
        "Dashboard v2 consumes the v0.3.3 merged account NAV ledger as the primary source of truth.",
        "Position rows are optional best-effort drilldown data.",
        "No broker connection, account write action, money movement, or recommendation workflow is used.",
        "",
        "## Summary",
        f"- Account count: {summary['account_count']}",
        f"- Provider count: {summary['provider_count']}",
        f"- Position rows: {summary['position_count']}",
        f"- Base currencies: {', '.join(summary['base_currencies']) or 'None'}",
        "",
        "## Provider NAV Summary",
    ]
    for row in provider_rows:
        lines.append(
            f"- {row['provider']}: {row['account_count']} accounts, "
            f"NAV {row['account_nav_total']}, status {row['import_status'] or 'unknown'}"
        )
    lines.extend(["", "## Warning Codes"])
    for code in warnings:
        lines.append(f"- {code.value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = ["# Dashboard v2 Warnings", "", DASHBOARD_V2_STATEMENT, ""]
    if warnings:
        lines.extend(f"- {code.value}" for code in warnings)
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _number_to_text(value: float) -> str:
    return f"{value:.2f}"


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _dedupe_text(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _sorted_values(values) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
