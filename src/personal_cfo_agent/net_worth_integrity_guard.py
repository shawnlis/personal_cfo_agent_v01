"""Local-only integrity guard for confirmed net worth history writes."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.dashboard_v3 import DashboardV3Result
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import MergeResult
from personal_cfo_agent.snapshot_store import SnapshotStoreResult
from personal_cfo_agent.warning_text import warning_details, warning_lines


SCHEMA_VERSION = "v0.6.5"

SUMMARY_NAME = "net_worth_integrity_summary.json"
WARNINGS_NAME = "net_worth_integrity_warnings.md"
REPORT_NAME = "NET_WORTH_INTEGRITY_GUARD_V065.md"

DEFAULT_NAV_CHANGE_PCT_THRESHOLD = 0.10
DEFAULT_NAV_CHANGE_ABS_THRESHOLD = 500_000.0


@dataclass(frozen=True)
class NetWorthIntegrityGuardResult:
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False
    ready_to_confirm: bool = False
    blocking_warning_codes: list[WarningCode] = field(default_factory=list)


def run_net_worth_integrity_guard(
    *,
    refresh_dir: Path,
    out_dir: Path,
    providers_requested: list[str],
    expected_required_providers: list[str] | None = None,
    expected_required_manual_layers: list[str] | None = None,
    manual_layer_status: dict[str, bool] | None = None,
    merge_result: MergeResult | None,
    snapshot_result: SnapshotStoreResult | None,
    dashboard_result: DashboardV3Result | None,
    fx_rates_file: Path | None,
    upstream_warning_codes: list[WarningCode],
    confirmed_history_dir: Path | None = None,
    nav_change_pct_threshold: float = DEFAULT_NAV_CHANGE_PCT_THRESHOLD,
    nav_change_abs_threshold: float = DEFAULT_NAV_CHANGE_ABS_THRESHOLD,
) -> NetWorthIntegrityGuardResult:
    """Write redacted guard outputs and decide whether history may be confirmed."""

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "warnings": out_dir / WARNINGS_NAME,
        "report": out_dir / REPORT_NAME,
    }

    account_rows = _account_nav_rows(refresh_dir, merge_result)
    warnings: list[WarningCode] = []
    blocking: list[WarningCode] = []
    required_providers = _clean_list(expected_required_providers or [])
    required_manual_layers = _clean_list(expected_required_manual_layers or [])
    provider_checks = _provider_checks(
        account_rows,
        providers_requested=providers_requested,
        expected_required_providers=required_providers,
    )
    for check in provider_checks.values():
        if not check["account_nav_rows"]:
            blocking.append(WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING)
            if check.get("expected_required"):
                blocking.append(WarningCode.INTEGRITY_EXPECTED_SOURCE_MISSING)
        elif not check["provider_reported_nav_rows"]:
            blocking.append(WarningCode.INTEGRITY_PROVIDER_NAV_MISSING)
    missing_manual_layers = [
        layer
        for layer in required_manual_layers
        if not (manual_layer_status or {}).get(layer, False)
    ]
    if missing_manual_layers:
        blocking.append(WarningCode.INTEGRITY_EXPECTED_SOURCE_MISSING)

    current_total = _current_total_net_worth(
        refresh_dir=refresh_dir,
        snapshot_result=snapshot_result,
        dashboard_result=dashboard_result,
        account_rows=account_rows,
    )
    if current_total is None:
        blocking.append(WarningCode.INTEGRITY_TOTAL_NAV_UNAVAILABLE)

    account_nav_currencies = _account_nav_currencies(account_rows)
    fx_required = len(account_nav_currencies) > 1
    fx_complete = _fx_complete(
        fx_rates_file=fx_rates_file,
        required_currencies=account_nav_currencies,
    )
    if fx_required and not fx_complete:
        blocking.extend(
            [
                WarningCode.INTEGRITY_MIXED_CURRENCY_BLOCKED,
                WarningCode.INTEGRITY_FX_REQUIRED,
            ]
        )

    if _has_code_fragment(upstream_warning_codes, "MIXED_AS_OF_DATES") or _has_code_fragment(
        upstream_warning_codes, "MIXED_DATE"
    ):
        blocking.append(WarningCode.INTEGRITY_MIXED_AS_OF_DATES)
    if _has_code_fragment(upstream_warning_codes, "STALE"):
        blocking.append(WarningCode.INTEGRITY_STALE_PROVIDER_DATA)
    if WarningCode.NET_WORTH_REFRESH_SNAPSHOT_PENDING_REVIEW in upstream_warning_codes:
        warnings.append(WarningCode.INTEGRITY_SNAPSHOT_PENDING_REVIEW)

    previous_total = _previous_total_net_worth(
        confirmed_history_dir
        if confirmed_history_dir is not None
        else refresh_dir / "snapshots_confirmed"
    )
    nav_change_review_required = False
    if previous_total is None:
        warnings.append(WarningCode.INTEGRITY_CONFIRMED_HISTORY_MISSING)
    elif current_total is not None and _nav_change_needs_review(
        previous_total=previous_total,
        current_total=current_total,
        pct_threshold=nav_change_pct_threshold,
        abs_threshold=nav_change_abs_threshold,
    ):
        nav_change_review_required = True
        blocking.append(WarningCode.INTEGRITY_NAV_CHANGE_REVIEW_REQUIRED)

    blocking = _dedupe_warning_codes(blocking)
    ready_to_confirm = not blocking
    completion = (
        WarningCode.INTEGRITY_GUARD_OK
        if ready_to_confirm
        else WarningCode.INTEGRITY_GUARD_BLOCKED
    )
    warnings = _dedupe_warning_codes([*warnings, *blocking, completion])
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "redacted": True,
        "ready_to_confirm": ready_to_confirm,
        "blocking_warning_codes": [code.value for code in blocking],
        "providers_requested": sorted(providers_requested),
        "expected_sources": {
            "providers_required": required_providers,
            "manual_layers_required": required_manual_layers,
            "manual_layers_missing": missing_manual_layers,
        },
        "provider_checks": provider_checks,
        "account_nav_row_count": len(account_rows),
        "account_nav_currencies": sorted(account_nav_currencies),
        "current_total_net_worth_available": current_total is not None,
        "previous_confirmed_total_available": previous_total is not None,
        "nav_change_review_required": nav_change_review_required,
        "nav_change_thresholds": {
            "pct": nav_change_pct_threshold,
            "absolute": nav_change_abs_threshold,
        },
        "fx": {
            "file_present": bool(fx_rates_file and fx_rates_file.exists()),
            "required": fx_required,
            "complete": fx_complete,
        },
        "snapshot_generated": bool(snapshot_result and snapshot_result.generated),
        "dashboard_generated": bool(dashboard_result and dashboard_result.generated),
        "source_warning_codes": [code.value for code in upstream_warning_codes],
        "warning_codes": [code.value for code in warnings],
        "warning_details": warning_details(warnings),
    }
    output_paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_warnings(output_paths["warnings"], warnings, blocking)
    output_paths["report"].write_text(_report(summary), encoding="utf-8")
    return NetWorthIntegrityGuardResult(
        output_dir=out_dir,
        output_paths=output_paths,
        warning_codes=warnings,
        generated=True,
        ready_to_confirm=ready_to_confirm,
        blocking_warning_codes=blocking,
    )


def _account_nav_rows(
    refresh_dir: Path, merge_result: MergeResult | None
) -> list[dict[str, str]]:
    if merge_result is not None:
        path = merge_result.output_dir / "merged_account_nav_ledger.csv"
    else:
        path = refresh_dir / "merged" / "merged_account_nav_ledger.csv"
    return _read_csv(path)


def _provider_checks(
    rows: list[dict[str, str]],
    *,
    providers_requested: list[str],
    expected_required_providers: list[str],
) -> dict[str, dict[str, int | str]]:
    checks: dict[str, dict[str, int | str]] = {}
    requested = {provider.strip().lower() for provider in providers_requested if provider}
    expected_required = set(expected_required_providers)
    for provider in sorted({*requested, *expected_required}):
        provider_rows = [
            row for row in rows if str(row.get("provider", "")).strip().lower() == provider
        ]
        provider_reported_rows = [
            row for row in provider_rows if _is_provider_reported_nav(row)
        ]
        status = "ok"
        if not provider_rows:
            status = "missing"
        elif not provider_reported_rows:
            status = "provider_nav_missing"
        checks[provider] = {
            "status": status,
            "requested": provider in requested,
            "expected_required": provider in expected_required,
            "account_nav_rows": len(provider_rows),
            "provider_reported_nav_rows": len(provider_reported_rows),
        }
    return checks


def _is_provider_reported_nav(row: dict[str, str]) -> bool:
    provider_available = str(row.get("provider_reported_nav_available", "")).strip().lower()
    nav_source = str(row.get("nav_source", "")).strip().lower()
    return (
        _parse_number(row.get("account_nav")) is not None
        and (provider_available == "yes" or nav_source == "provider_reported")
    )


def _current_total_net_worth(
    *,
    refresh_dir: Path,
    snapshot_result: SnapshotStoreResult | None,
    dashboard_result: DashboardV3Result | None,
    account_rows: list[dict[str, str]],
) -> float | None:
    dashboard_path = None
    if dashboard_result is not None:
        dashboard_path = dashboard_result.output_paths.get("net_worth_progress")
    for path, field in (
        (dashboard_path, "integrated_net_worth"),
        (
            snapshot_result.output_paths.get("net_worth_history")
            if snapshot_result is not None
            else None,
            "total_account_nav",
        ),
        (refresh_dir / "dashboard" / "net_worth_progress.csv", "integrated_net_worth"),
        (refresh_dir / "snapshots" / "net_worth_history.csv", "total_account_nav"),
    ):
        value = _latest_numeric_field(path, field) if path is not None else None
        if value is not None:
            return value
    currencies = _account_nav_currencies(account_rows)
    if len(currencies) != 1:
        return None
    values = [_parse_number(row.get("account_nav")) for row in account_rows]
    numeric_values = [value for value in values if value is not None]
    return sum(numeric_values) if numeric_values else None


def _previous_total_net_worth(confirmed_dir: Path) -> float | None:
    candidates = (
        ("confirmed_net_worth_history.csv", "total_net_worth"),
        ("net_worth_bucket_history.csv", "total_net_worth"),
        ("net_worth_history.csv", "total_account_nav"),
    )
    for filename, field in candidates:
        value = _latest_numeric_field(confirmed_dir / filename, field)
        if value is not None:
            return value
    return None


def _latest_numeric_field(path: Path | None, field: str) -> float | None:
    if path is None or not path.exists():
        return None
    rows = _read_csv(path)
    for row in reversed(rows):
        value = _parse_number(row.get(field))
        if value is not None:
            return value
    return None


def _nav_change_needs_review(
    *,
    previous_total: float,
    current_total: float,
    pct_threshold: float,
    abs_threshold: float,
) -> bool:
    delta = abs(current_total - previous_total)
    if delta > abs_threshold:
        return True
    if previous_total == 0:
        return delta > 0
    return delta / abs(previous_total) > pct_threshold


def _account_nav_currencies(rows: list[dict[str, str]]) -> set[str]:
    currencies: set[str] = set()
    for row in rows:
        if _parse_number(row.get("account_nav")) is None:
            continue
        currency = str(row.get("base_currency", "")).strip().upper()
        if currency:
            currencies.add(currency)
    return currencies


def _fx_complete(*, fx_rates_file: Path | None, required_currencies: set[str]) -> bool:
    if len(required_currencies) <= 1:
        return True
    if fx_rates_file is None or not fx_rates_file.exists():
        return False
    try:
        payload = json.loads(fx_rates_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    base_currency = str(payload.get("base_currency", "")).strip().upper()
    rates = payload.get("rates_to_base")
    if not base_currency or not isinstance(rates, dict):
        return False
    covered = {
        str(currency).strip().upper()
        for currency, value in rates.items()
        if str(currency).strip()
        and (rate_value := _parse_number(value)) is not None
        and rate_value > 0
    }
    covered.add(base_currency)
    return required_currencies <= covered


def _has_code_fragment(codes: list[WarningCode], fragment: str) -> bool:
    return any(fragment in code.value for code in codes)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


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


def _write_warnings(
    path: Path, warnings: list[WarningCode], blocking: list[WarningCode]
) -> None:
    lines = ["# Net Worth Integrity Warnings", ""]
    lines.append("## Blocking")
    lines.append("")
    if blocking:
        lines.extend(f"- `{code.value}`" for code in blocking)
    else:
        lines.append("- None")
    lines.extend(["", "## All Warning Codes", ""])
    lines.extend(warning_lines(warnings))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(summary: dict[str, Any]) -> str:
    providers = summary["providers_requested"]
    expected_sources = summary.get("expected_sources", {})
    blocking = summary["blocking_warning_codes"]
    lines = [
        "# Net Worth Integrity Guard v0.6.5",
        "",
        "Local-only redacted guard for confirmed net worth history writes.",
        "",
        "## Confirmation Gate",
        "",
        f"- Ready to confirm history: {_yes_no(summary['ready_to_confirm'])}",
        f"- Blocking warning codes: {', '.join(blocking) if blocking else 'None'}",
        "",
        "## Provider Coverage",
        "",
        f"- Providers requested: {', '.join(providers) if providers else 'None'}",
        (
            "- Required expected providers: "
            + (
                ", ".join(expected_sources.get("providers_required", []))
                if expected_sources.get("providers_required")
                else "None"
            )
        ),
        (
            "- Missing required manual layers: "
            + (
                ", ".join(expected_sources.get("manual_layers_missing", []))
                if expected_sources.get("manual_layers_missing")
                else "None"
            )
        ),
        f"- Account NAV rows: {summary['account_nav_row_count']}",
        "",
        "## FX And Dates",
        "",
        f"- FX required: {_yes_no(summary['fx']['required'])}",
        f"- FX complete: {_yes_no(summary['fx']['complete'])}",
        f"- Current total available: {_yes_no(summary['current_total_net_worth_available'])}",
        f"- Previous confirmed total available: {_yes_no(summary['previous_confirmed_total_available'])}",
        f"- NAV change review required: {_yes_no(summary['nav_change_review_required'])}",
        "",
        "## Warning Codes",
        "",
        *warning_lines(summary["warning_codes"]),
    ]
    return "\n".join(lines) + "\n"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _clean_list(values: list[str]) -> list[str]:
    return sorted({str(value).strip().lower() for value in values if str(value).strip()})


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result
