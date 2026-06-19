"""Offline immutable snapshot store for account-NAV net worth history."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.4.2"

NET_WORTH_HISTORY_FIELDNAMES = [
    "snapshot_date",
    "snapshot_id",
    "base_currency",
    "total_account_nav",
    "liquid_net_worth",
    "investable_assets",
    "property_equity",
    "cpf_total",
    "srs_total",
    "liabilities_total",
    "provider_count",
    "account_count",
    "warning_count",
    "review_required",
    "source_confidence",
]

ACCOUNT_NAV_HISTORY_FIELDNAMES = [
    "snapshot_date",
    "snapshot_id",
    "provider",
    "account_id_hash",
    "account_nav",
    "cash_total",
    "securities_market_value",
    "margin_or_debt",
    "base_currency",
    "nav_source",
    "as_of_date",
    "warning_codes",
    "source_confidence",
]

PROVIDER_NAV_HISTORY_FIELDNAMES = [
    "snapshot_date",
    "snapshot_id",
    "provider",
    "account_count",
    "provider_nav_total",
    "import_status",
    "warning_codes",
    "as_of_date_min",
    "as_of_date_max",
]

_ACCOUNT_NAV_LEDGER = "merged_account_nav_ledger.csv"
_ACCOUNT_NAV_SUMMARY = "merged_account_nav_summary.json"
_PROVIDER_SUMMARY = "merged_provider_summary.json"
_ACCOUNT_SOURCE_MAP = "account_source_map.json"
_DASHBOARD_SUMMARY = "dashboard_v040_summary.json"
_DASHBOARD_WARNINGS = "dashboard_warnings.md"


@dataclass
class SnapshotStoreResult:
    merge_dir: Path
    dashboard_dir: Path | None
    output_dir: Path | None
    snapshot_id: str | None = None
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    account_count: int = 0
    provider_count: int = 0
    position_count: int = 0
    generated: bool = False


def record_snapshot(
    *,
    merge_dir: Path,
    out_dir: Path,
    dashboard_dir: Path | None = None,
    snapshot_id: str | None = None,
    generated_at: datetime | None = None,
) -> SnapshotStoreResult:
    """Record an immutable local net-worth snapshot from offline merge outputs."""

    warnings: list[WarningCode] = []
    if not merge_dir.exists():
        warnings.append(WarningCode.SNAPSHOT_INPUT_MISSING)
        return SnapshotStoreResult(
            merge_dir=merge_dir,
            dashboard_dir=dashboard_dir,
            output_dir=None,
            warning_codes=warnings,
        )

    account_path = merge_dir / _ACCOUNT_NAV_LEDGER
    if not account_path.exists():
        warnings.append(WarningCode.SNAPSHOT_ACCOUNT_NAV_LEDGER_MISSING)
        return SnapshotStoreResult(
            merge_dir=merge_dir,
            dashboard_dir=dashboard_dir,
            output_dir=None,
            warning_codes=warnings,
        )

    account_rows = _read_csv(account_path)
    if not account_rows:
        warnings.append(WarningCode.SNAPSHOT_ACCOUNT_NAV_EMPTY)
        return SnapshotStoreResult(
            merge_dir=merge_dir,
            dashboard_dir=dashboard_dir,
            output_dir=None,
            warning_codes=warnings,
        )

    generated_at = generated_at or datetime.now(timezone.utc)
    snapshot_id = snapshot_id or _default_snapshot_id(generated_at)
    existing_ids = _existing_snapshot_ids(out_dir)
    if snapshot_id in existing_ids:
        warnings.append(WarningCode.SNAPSHOT_ID_DUPLICATE)
        return SnapshotStoreResult(
            merge_dir=merge_dir,
            dashboard_dir=dashboard_dir,
            output_dir=None,
            snapshot_id=snapshot_id,
            warning_codes=warnings,
        )

    account_summary = _read_json(merge_dir / _ACCOUNT_NAV_SUMMARY) or {}
    provider_summary = _read_json(merge_dir / _PROVIDER_SUMMARY)
    if provider_summary is None:
        warnings.append(WarningCode.SNAPSHOT_PROVIDER_SUMMARY_MISSING)
        provider_summary = {}
    account_source_map = _read_json(merge_dir / _ACCOUNT_SOURCE_MAP) or {}
    dashboard_summary = None
    dashboard_warning_text = ""
    if dashboard_dir is not None:
        dashboard_summary = _read_json(dashboard_dir / _DASHBOARD_SUMMARY)
        if dashboard_summary is None:
            warnings.append(WarningCode.SNAPSHOT_DASHBOARD_SUMMARY_MISSING)
        dashboard_warning_text = _read_text(dashboard_dir / _DASHBOARD_WARNINGS)
    else:
        warnings.append(WarningCode.SNAPSHOT_DASHBOARD_SUMMARY_MISSING)

    input_warning_values = _input_warning_values(
        account_rows=account_rows,
        account_summary=account_summary,
        provider_summary=provider_summary,
        dashboard_summary=dashboard_summary,
        dashboard_warning_text=dashboard_warning_text,
    )
    if input_warning_values:
        warnings.append(WarningCode.SNAPSHOT_WARNINGS_PRESENT)
    if "MIXED_AS_OF_DATES" in input_warning_values or "DASHBOARD_V2_MIXED_AS_OF_DATES" in input_warning_values:
        warnings.append(WarningCode.SNAPSHOT_MIXED_AS_OF_DATES)
    if _mixed_or_missing_account_nav_currency(account_rows):
        warnings.append(WarningCode.SNAPSHOT_MIXED_CURRENCY_NAV)
    if "STALE_PROVIDER_BUNDLE" in input_warning_values or "DASHBOARD_V2_STALE_DATA_WARNING" in input_warning_values:
        warnings.append(WarningCode.SNAPSHOT_STALE_INPUT_WARNING)

    history_preexists = (out_dir / "net_worth_history.csv").exists()
    history_code = (
        WarningCode.SNAPSHOT_HISTORY_APPENDED
        if history_preexists
        else WarningCode.SNAPSHOT_HISTORY_CREATED
    )
    warnings.append(history_code)
    completion = (
        WarningCode.SNAPSHOT_GENERATED_WITH_WARNINGS
        if _has_warning_beyond_history(warnings)
        else WarningCode.SNAPSHOT_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_date = generated_at.date().isoformat()
    provider_count = _provider_count(account_rows, provider_summary, dashboard_summary)
    account_count = len(account_rows)
    position_count = _position_count(provider_summary, dashboard_summary)
    net_worth_row = _net_worth_history_row(
        snapshot_date=snapshot_date,
        snapshot_id=snapshot_id,
        account_rows=account_rows,
        provider_count=provider_count,
        account_count=account_count,
        warning_count=len(warnings),
        review_required=_review_required(warnings),
    )
    account_history_rows = [
        _account_history_row(snapshot_date, snapshot_id, row) for row in account_rows
    ]
    provider_history_rows = _provider_history_rows(
        snapshot_date,
        snapshot_id,
        account_history_rows,
        provider_summary=provider_summary,
    )
    source_files = _source_files(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        dashboard_summary_present=dashboard_summary is not None,
        dashboard_warning_text=dashboard_warning_text,
    )
    manifest = {
        "snapshot_id": snapshot_id,
        "generated_at": generated_at.isoformat(),
        "input_merge_dir": str(merge_dir),
        "input_dashboard_dir": str(dashboard_dir) if dashboard_dir is not None else "",
        "base_currency": net_worth_row["base_currency"],
        "provider_count": provider_count,
        "account_count": account_count,
        "position_count": position_count,
        "total_account_nav_available": "yes" if net_worth_row["total_account_nav"] else "no",
        "total_account_nav_source": "merged_account_nav_ledger",
        "warning_codes": [code.value for code in warnings],
        "source_files": source_files,
        "schema_version": SCHEMA_VERSION,
    }

    paths = {
        "snapshot_manifest": out_dir / "snapshot_manifest.json",
        "net_worth_history": out_dir / "net_worth_history.csv",
        "account_nav_history": out_dir / "account_nav_history.csv",
        "provider_nav_history": out_dir / "provider_nav_history.csv",
        "snapshot_warnings": out_dir / "snapshot_warnings.md",
        "markdown_report": out_dir / "SNAPSHOT_STORE_V042.md",
    }
    _append_or_create_csv(paths["net_worth_history"], NET_WORTH_HISTORY_FIELDNAMES, [net_worth_row])
    _append_or_create_csv(
        paths["account_nav_history"], ACCOUNT_NAV_HISTORY_FIELDNAMES, account_history_rows
    )
    _append_or_create_csv(
        paths["provider_nav_history"], PROVIDER_NAV_HISTORY_FIELDNAMES, provider_history_rows
    )
    paths["snapshot_manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_warnings(paths["snapshot_warnings"], warnings)
    _write_markdown(paths["markdown_report"], manifest=manifest, warnings=warnings)

    return SnapshotStoreResult(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        output_dir=out_dir,
        snapshot_id=snapshot_id,
        output_paths=paths,
        warning_codes=warnings,
        account_count=account_count,
        provider_count=provider_count,
        position_count=position_count,
        generated=True,
    )


def _default_snapshot_id(generated_at: datetime) -> str:
    return "snapshot_" + generated_at.strftime("%Y%m%dT%H%M%SZ")


def _existing_snapshot_ids(out_dir: Path) -> set[str]:
    ids: set[str] = set()
    manifest = _read_json(out_dir / "snapshot_manifest.json")
    if isinstance(manifest, dict):
        snapshot_id = _clean(manifest.get("snapshot_id"))
        if snapshot_id:
            ids.add(snapshot_id)
    history_path = out_dir / "net_worth_history.csv"
    if history_path.exists():
        for row in _read_csv(history_path):
            snapshot_id = _clean(row.get("snapshot_id"))
            if snapshot_id:
                ids.add(snapshot_id)
    return ids


def _input_warning_values(
    *,
    account_rows: list[dict[str, str]],
    account_summary: dict[str, Any],
    provider_summary: dict[str, Any],
    dashboard_summary: dict[str, Any] | None,
    dashboard_warning_text: str,
) -> set[str]:
    values: set[str] = set()
    for row in account_rows:
        values.update(_split_codes(row.get("warning_codes")))
    for payload in (account_summary, provider_summary, dashboard_summary or {}):
        values.update(str(code) for code in payload.get("warning_codes", []) if code)
    values.update(_warning_codes_from_text(dashboard_warning_text))
    return {value for value in values if value}


def _net_worth_history_row(
    *,
    snapshot_date: str,
    snapshot_id: str,
    account_rows: list[dict[str, str]],
    provider_count: int,
    account_count: int,
    warning_count: int,
    review_required: bool,
) -> dict[str, str]:
    base_currency = _single_account_nav_currency(account_rows)
    total_nav = _sum_field(account_rows, "account_nav") if base_currency else None
    return {
        "snapshot_date": snapshot_date,
        "snapshot_id": snapshot_id,
        "base_currency": base_currency,
        "total_account_nav": _number_to_text(total_nav),
        "liquid_net_worth": "",
        "investable_assets": "",
        "property_equity": "",
        "cpf_total": "",
        "srs_total": "",
        "liabilities_total": "",
        "provider_count": str(provider_count),
        "account_count": str(account_count),
        "warning_count": str(warning_count),
        "review_required": "yes" if review_required else "no",
        "source_confidence": _source_confidence(account_rows),
    }


def _mixed_or_missing_account_nav_currency(account_rows: list[dict[str, str]]) -> bool:
    rows_with_nav = [
        row for row in account_rows if _parse_number(row.get("account_nav")) is not None
    ]
    if not rows_with_nav:
        return False
    currencies = [_clean(row.get("base_currency")) for row in rows_with_nav]
    return any(not currency for currency in currencies) or len(set(currencies)) != 1


def _single_account_nav_currency(account_rows: list[dict[str, str]]) -> str:
    rows_with_nav = [
        row for row in account_rows if _parse_number(row.get("account_nav")) is not None
    ]
    currencies = {_clean(row.get("base_currency")) for row in rows_with_nav}
    if len(currencies) == 1:
        currency = next(iter(currencies))
        return currency
    return ""


def _account_history_row(
    snapshot_date: str, snapshot_id: str, row: dict[str, str]
) -> dict[str, str]:
    return {
        "snapshot_date": snapshot_date,
        "snapshot_id": snapshot_id,
        "provider": _clean(row.get("provider")),
        "account_id_hash": _clean(row.get("account_id_hash")),
        "account_nav": _clean(row.get("account_nav")),
        "cash_total": _clean(row.get("cash_total")),
        "securities_market_value": _clean(row.get("securities_market_value")),
        "margin_or_debt": _clean(row.get("margin_or_debt")),
        "base_currency": _clean(row.get("base_currency")),
        "nav_source": _clean(row.get("nav_source")),
        "as_of_date": _clean(row.get("as_of_date")),
        "warning_codes": _clean(row.get("warning_codes")),
        "source_confidence": _clean(row.get("source_confidence")),
    }


def _provider_history_rows(
    snapshot_date: str,
    snapshot_id: str,
    account_rows: list[dict[str, str]],
    *,
    provider_summary: dict[str, Any],
) -> list[dict[str, str]]:
    import_status = _provider_import_status(provider_summary)
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in account_rows:
        grouped.setdefault(row["provider"] or "unknown", []).append(row)
    rows: list[dict[str, str]] = []
    for provider, provider_rows in sorted(grouped.items()):
        as_of_dates = _sorted_values(row.get("as_of_date") for row in provider_rows)
        warnings = _dedupe_text(
            code
            for row in provider_rows
            for code in _split_codes(row.get("warning_codes"))
        )
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "snapshot_id": snapshot_id,
                "provider": provider,
                "account_count": str(len(provider_rows)),
                "provider_nav_total": _number_to_text(_sum_field(provider_rows, "account_nav")),
                "import_status": import_status.get(provider, ""),
                "warning_codes": ";".join(warnings),
                "as_of_date_min": as_of_dates[0] if as_of_dates else "",
                "as_of_date_max": as_of_dates[-1] if as_of_dates else "",
            }
        )
    return rows


def _provider_import_status(provider_summary: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in provider_summary.get("bundle_results", []):
        if not isinstance(entry, dict):
            continue
        provider = _clean(entry.get("provider"))
        status = _clean(entry.get("status"))
        if provider and status:
            result[provider] = status
    return result


def _source_files(
    *,
    merge_dir: Path,
    dashboard_dir: Path | None,
    dashboard_summary_present: bool,
    dashboard_warning_text: str,
) -> list[str]:
    paths = [
        merge_dir / _ACCOUNT_NAV_LEDGER,
        merge_dir / _ACCOUNT_NAV_SUMMARY,
        merge_dir / _PROVIDER_SUMMARY,
        merge_dir / _ACCOUNT_SOURCE_MAP,
    ]
    if dashboard_dir is not None:
        if dashboard_summary_present:
            paths.append(dashboard_dir / _DASHBOARD_SUMMARY)
        if dashboard_warning_text:
            paths.append(dashboard_dir / _DASHBOARD_WARNINGS)
    return [str(path) for path in paths if path.exists()]


def _position_count(
    provider_summary: dict[str, Any], dashboard_summary: dict[str, Any] | None
) -> int:
    if isinstance(dashboard_summary, dict):
        value = _parse_int(dashboard_summary.get("position_count"))
        if value is not None:
            return value
    value = _parse_int(provider_summary.get("position_row_count"))
    return value or 0


def _provider_count(
    account_rows: list[dict[str, str]],
    provider_summary: dict[str, Any],
    dashboard_summary: dict[str, Any] | None,
) -> int:
    if isinstance(dashboard_summary, dict):
        value = _parse_int(dashboard_summary.get("provider_count"))
        if value is not None:
            return value
    if isinstance(provider_summary.get("provider_counts"), dict):
        return len(provider_summary["provider_counts"])
    return len({row.get("provider") for row in account_rows if row.get("provider")})


def _review_required(warnings: list[WarningCode]) -> bool:
    return any(
        code
        not in {WarningCode.SNAPSHOT_HISTORY_CREATED, WarningCode.SNAPSHOT_GENERATED_OK}
        for code in warnings
    )


def _has_warning_beyond_history(warnings: list[WarningCode]) -> bool:
    return any(
        code
        not in {WarningCode.SNAPSHOT_HISTORY_CREATED, WarningCode.SNAPSHOT_HISTORY_APPENDED}
        for code in warnings
    )


def _append_or_create_csv(
    path: Path, fieldnames: list[str], rows: list[dict[str, str]]
) -> None:
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = [
        "# Snapshot Store Warnings",
        "",
        "Snapshot store is offline only and records historical account-NAV snapshots.",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown(
    path: Path, *, manifest: dict[str, object], warnings: list[WarningCode]
) -> None:
    lines = [
        "# Snapshot Store v0.4.2",
        "",
        "This local snapshot records historical Personal CFO account NAV progress.",
        "It consumes offline merged account NAV and Dashboard v2 outputs only.",
        "It does not connect to brokers, move money, place orders, or produce advice.",
        "",
        "## Snapshot",
        f"- Snapshot ID: {manifest['snapshot_id']}",
        f"- Provider count: {manifest['provider_count']}",
        f"- Account count: {manifest['account_count']}",
        f"- Position count: {manifest['position_count']}",
        f"- Total account NAV available: {manifest['total_account_nav_available']}",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _warning_codes_from_text(text: str) -> set[str]:
    known_codes = {code.value for code in WarningCode}
    tokens = {
        token.strip("`-:,.()[]{} ")
        for line in text.splitlines()
        for token in line.split()
    }
    return {token for token in tokens if token in known_codes}


def _sum_field(rows: list[dict[str, str]], field: str) -> float | None:
    total = 0.0
    found = False
    for row in rows:
        value = _parse_number(row.get(field))
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


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


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number_to_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _source_confidence(rows: list[dict[str, str]]) -> str:
    values = _sorted_values(row.get("source_confidence") for row in rows)
    if len(values) == 1:
        return values[0]
    return "mixed" if values else ""


def _split_codes(value: object) -> list[str]:
    return [code for code in _clean(value).split(";") if code]


def _sorted_values(values) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


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


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
