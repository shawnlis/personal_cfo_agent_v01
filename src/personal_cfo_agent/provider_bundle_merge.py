"""Offline merge layer for normalized provider ledger bundles."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from personal_cfo_agent.models import WarningCode


MERGED_LEDGER_FIELDNAMES = [
    "provider",
    "account_id_hash",
    "source_bundle_id",
    "source_snapshot_id",
    "asset_type",
    "symbol",
    "name",
    "currency",
    "quantity",
    "market_value",
    "cost_basis",
    "average_cost",
    "unrealized_pnl",
    "as_of_date",
    "source_confidence",
    "normalization_warnings",
    "merge_warnings",
]

_BUNDLE_LEDGER_FILENAME = "normalized_asset_ledger.csv"
_SUMMARY_FILENAME = "provider_sync_summary.json"
_STALE_DAYS = 45


@dataclass(frozen=True)
class MergeInputBundle:
    provider: str
    bundle_dir: Path
    ledger_path: Path
    summary_path: Path | None


@dataclass
class MergeResult:
    output_dir: Path
    output_paths: dict[str, Path]
    row_count: int
    provider_counts: dict[str, int]
    warning_codes: list[WarningCode] = field(default_factory=list)
    source_bundle_count: int = 0


def merge_provider_bundles(
    *,
    input_root: Path | None,
    out_dir: Path,
    fixture_mode: bool = False,
    today: date | None = None,
) -> MergeResult:
    """Merge existing normalized provider bundles without broker connections."""

    out_dir.mkdir(parents=True, exist_ok=True)
    if fixture_mode:
        input_root = _write_fixture_input_bundles(
            out_dir.parent / f"{out_dir.name}_fixture_inputs"
        )
    if input_root is None:
        raise ValueError("input_root is required when fixture_mode is false")

    bundles = discover_provider_bundles(input_root, exclude_dirs=[out_dir])
    rows, warnings, account_source_map = _read_and_merge_bundles(
        bundles, today=today or date.today()
    )
    if not bundles:
        warnings.append(WarningCode.PROVIDER_BUNDLE_MISSING)
    if not rows:
        warnings.append(WarningCode.EMPTY_PROVIDER_LEDGER)

    warnings = _dedupe_warning_codes(warnings)
    completion_code = (
        WarningCode.MERGE_COMPLETED_WITH_WARNINGS
        if warnings
        else WarningCode.MERGE_COMPLETED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion_code])
    provider_counts = _provider_counts(rows)
    paths = _write_merge_outputs(
        out_dir=out_dir,
        rows=rows,
        warnings=warnings,
        account_source_map=account_source_map,
        provider_counts=provider_counts,
        source_bundle_count=len(bundles),
        fixture_mode=fixture_mode,
    )
    return MergeResult(
        output_dir=out_dir,
        output_paths=paths,
        row_count=len(rows),
        provider_counts=provider_counts,
        warning_codes=warnings,
        source_bundle_count=len(bundles),
    )


def discover_provider_bundles(
    input_root: Path, *, exclude_dirs: Iterable[Path] = ()
) -> list[MergeInputBundle]:
    if not input_root.exists():
        return []
    excluded = [path.resolve() for path in exclude_dirs if path.exists()]
    bundles: list[MergeInputBundle] = []
    for ledger_path in sorted(input_root.rglob(_BUNDLE_LEDGER_FILENAME)):
        resolved = ledger_path.resolve()
        if any(_is_relative_to(resolved, excluded_dir) for excluded_dir in excluded):
            continue
        bundle_dir = ledger_path.parent
        summary_path = bundle_dir / _SUMMARY_FILENAME
        provider = _provider_from_bundle(bundle_dir, ledger_path)
        bundles.append(
            MergeInputBundle(
                provider=provider,
                bundle_dir=bundle_dir,
                ledger_path=ledger_path,
                summary_path=summary_path if summary_path.exists() else None,
            )
        )
    return bundles


def _read_and_merge_bundles(
    bundles: list[MergeInputBundle], *, today: date
) -> tuple[list[dict[str, str]], list[WarningCode], dict[str, object]]:
    rows: list[dict[str, str]] = []
    warnings: list[WarningCode] = []
    account_source_map: dict[str, dict[str, object]] = {}
    for bundle in bundles:
        bundle_rows, bundle_warnings = _read_bundle_rows(bundle, today=today)
        warnings.extend(bundle_warnings)
        rows.extend(bundle_rows)
        _extend_account_source_map(account_source_map, bundle, bundle_rows)

    duplicate_keys = _duplicate_keys(rows)
    if duplicate_keys:
        warnings.append(WarningCode.POSSIBLE_DUPLICATE_POSITION)
        for row in rows:
            key = _duplicate_key(row)
            if key in duplicate_keys:
                _append_row_warning(row, WarningCode.POSSIBLE_DUPLICATE_POSITION)

    as_of_dates = {row["as_of_date"] for row in rows if row.get("as_of_date")}
    if len(as_of_dates) > 1:
        warnings.append(WarningCode.MIXED_AS_OF_DATES)
        for row in rows:
            _append_row_warning(row, WarningCode.MIXED_AS_OF_DATES)
    return rows, _dedupe_warning_codes(warnings), account_source_map


def _read_bundle_rows(
    bundle: MergeInputBundle, *, today: date
) -> tuple[list[dict[str, str]], list[WarningCode]]:
    warnings: list[WarningCode] = []
    if bundle.summary_path is None:
        warnings.append(WarningCode.PROVIDER_SUMMARY_MISSING)
    with bundle.ledger_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        if "provider" not in fieldnames or "account_id_hash" not in fieldnames:
            return [], [WarningCode.PROVIDER_SCHEMA_MISMATCH]
        source_rows = list(reader)
    if not source_rows:
        return [], _dedupe_warning_codes([*warnings, WarningCode.EMPTY_PROVIDER_LEDGER])

    merged_rows: list[dict[str, str]] = []
    for source in source_rows:
        row_warnings: list[WarningCode] = []
        provider = _clean(source.get("provider")) or bundle.provider
        source_id = _clean(source.get("source_bundle_id")) or bundle.bundle_dir.name
        source_snapshot_id = _clean(source.get("source_snapshot_id"))
        if provider == "manual_snapshot" and not source_snapshot_id:
            source_snapshot_id = source_id
            source_id = ""
        as_of_date = _as_of_date(source)
        row = {
            "provider": provider,
            "account_id_hash": _clean(source.get("account_id_hash")),
            "source_bundle_id": source_id,
            "source_snapshot_id": source_snapshot_id,
            "asset_type": _clean(source.get("asset_type")),
            "symbol": _clean(source.get("symbol")),
            "name": _clean(source.get("name")),
            "currency": _clean(source.get("currency")),
            "quantity": _clean(source.get("quantity")),
            "market_value": _clean(source.get("market_value")),
            "cost_basis": _clean(source.get("cost_basis")),
            "average_cost": _clean(source.get("average_cost")),
            "unrealized_pnl": _clean(source.get("unrealized_pnl")),
            "as_of_date": as_of_date,
            "source_confidence": _clean(source.get("source_confidence")),
            "normalization_warnings": _clean(
                source.get("normalization_warnings") or source.get("warning_codes")
            ),
            "merge_warnings": "",
        }
        if not row["account_id_hash"]:
            row_warnings.append(WarningCode.ACCOUNT_HASH_MISSING)
        if not row["symbol"]:
            row_warnings.append(WarningCode.SYMBOL_MISSING)
        if not row["currency"]:
            row_warnings.append(WarningCode.CURRENCY_MISSING)
        if not row["as_of_date"]:
            row_warnings.append(WarningCode.AS_OF_DATE_MISSING)
        if not row["market_value"]:
            row_warnings.append(WarningCode.MARKET_VALUE_MISSING)
        if not row["cost_basis"]:
            row_warnings.append(WarningCode.COST_BASIS_MISSING)
        if _is_stale(row["as_of_date"], today=today):
            row_warnings.append(WarningCode.STALE_PROVIDER_BUNDLE)
        for code in row_warnings:
            _append_row_warning(row, code)
        warnings.extend(row_warnings)
        merged_rows.append(row)
    return merged_rows, _dedupe_warning_codes(warnings)


def _write_merge_outputs(
    *,
    out_dir: Path,
    rows: list[dict[str, str]],
    warnings: list[WarningCode],
    account_source_map: dict[str, object],
    provider_counts: dict[str, int],
    source_bundle_count: int,
    fixture_mode: bool,
) -> dict[str, Path]:
    paths = {
        "merged_normalized_ledger": out_dir / "merged_normalized_ledger.csv",
        "merged_provider_summary": out_dir / "merged_provider_summary.json",
        "account_source_map": out_dir / "account_source_map.json",
        "merge_warnings": out_dir / "merge_warnings.md",
        "markdown_report": out_dir / "MERGED_LEDGER_V033.md",
    }
    with paths["merged_normalized_ledger"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MERGED_LEDGER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "version": "v0.3.3",
        "mode": "fixture" if fixture_mode else "offline_merge",
        "offline_merge_only": True,
        "broker_connections": "not_used",
        "source_bundle_count": source_bundle_count,
        "normalized_row_count": len(rows),
        "provider_counts": provider_counts,
        "warning_codes": [code.value for code in warnings],
        "outputs": {key: str(path) for key, path in paths.items()},
    }
    paths["merged_provider_summary"].write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    paths["account_source_map"].write_text(
        json.dumps(account_source_map, indent=2), encoding="utf-8"
    )
    _write_warnings_report(paths["merge_warnings"], warnings, provider_counts)
    _write_markdown_report(
        paths["markdown_report"],
        rows=rows,
        warnings=warnings,
        provider_counts=provider_counts,
        source_bundle_count=source_bundle_count,
        fixture_mode=fixture_mode,
    )
    return paths


def _write_warnings_report(
    path: Path, warnings: list[WarningCode], provider_counts: dict[str, int]
) -> None:
    lines = [
        "# Multi-provider Merge Warnings",
        "",
        "This report is generated by the offline normalized ledger merge layer.",
        "",
        "## Provider Row Counts",
    ]
    for provider, count in sorted(provider_counts.items()):
        lines.append(f"- {provider}: {count} rows")
    lines.extend(["", "## Warning Codes"])
    for code in warnings:
        lines.append(f"- {code.value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown_report(
    path: Path,
    *,
    rows: list[dict[str, str]],
    warnings: list[WarningCode],
    provider_counts: dict[str, int],
    source_bundle_count: int,
    fixture_mode: bool,
) -> None:
    lines = [
        "# Multi-provider Normalized Ledger v0.3.3",
        "",
        "This is offline audit and reconciliation infrastructure.",
        "No broker API connection, account write action, money movement, or advice workflow is used.",
        "",
        f"- Mode: {'fixture' if fixture_mode else 'offline merge'}",
        f"- Source bundles: {source_bundle_count}",
        f"- Merged rows: {len(rows)}",
        "",
        "## Provider Row Counts",
    ]
    for provider, count in sorted(provider_counts.items()):
        lines.append(f"- {provider}: {count}")
    lines.extend(["", "## Warning Codes"])
    for code in warnings:
        lines.append(f"- {code.value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_fixture_input_bundles(input_root: Path) -> Path:
    input_root.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "manual_snapshot_fixture": [
            {
                "provider": "manual_snapshot",
                "account_id_hash": "acct_manual_fixture_001",
                "asset_type": "cash",
                "symbol": "SGD",
                "name": "SGD cash",
                "quantity": "1000.00",
                "currency": "SGD",
                "market_value": "1000.00",
                "cost_basis": "",
                "unrealized_pnl": "",
                "source_timestamp": "2026-06-15",
                "source_confidence": "synthetic_fixture",
                "warning_codes": "ACCOUNT_ID_HASHED",
            }
        ],
        "ibkr_fixture": [
            {
                "provider": "ibkr",
                "account_id_hash": "acct_ibkr_fixture_001",
                "asset_type": "equity",
                "symbol": "AAPL",
                "name": "Apple Inc synthetic",
                "quantity": "2",
                "currency": "USD",
                "market_value": "400.00",
                "cost_basis": "350.00",
                "unrealized_pnl": "50.00",
                "source_timestamp": "2026-06-15",
                "source_confidence": "synthetic_fixture",
                "warning_codes": "ACCOUNT_ID_HASHED",
            },
            {
                "provider": "ibkr",
                "account_id_hash": "acct_ibkr_fixture_001",
                "asset_type": "equity",
                "symbol": "AAPL",
                "name": "Apple Inc synthetic duplicate",
                "quantity": "1",
                "currency": "USD",
                "market_value": "200.00",
                "cost_basis": "175.00",
                "unrealized_pnl": "25.00",
                "source_timestamp": "2026-06-15",
                "source_confidence": "synthetic_fixture",
                "warning_codes": "ACCOUNT_ID_HASHED",
            },
        ],
        "tiger_fixture": [
            {
                "provider": "tiger",
                "account_id_hash": "acct_tiger_fixture_001",
                "asset_type": "equity",
                "symbol": "AAPL",
                "name": "Apple Inc synthetic",
                "quantity": "3",
                "currency": "USD",
                "market_value": "600.00",
                "cost_basis": "540.00",
                "unrealized_pnl": "60.00",
                "source_timestamp": "2026-06-15",
                "source_confidence": "synthetic_fixture",
                "warning_codes": "ACCOUNT_ID_HASHED",
            }
        ],
        "moomoo_fixture": [
            {
                "provider": "moomoo",
                "account_id_hash": "acct_moomoo_fixture_001",
                "asset_type": "cash",
                "symbol": "HKD",
                "name": "HKD cash",
                "quantity": "500.00",
                "currency": "HKD",
                "market_value": "500.00",
                "cost_basis": "",
                "unrealized_pnl": "",
                "source_timestamp": "2026-06-15",
                "source_confidence": "synthetic_fixture",
                "warning_codes": "ACCOUNT_ID_HASHED",
            }
        ],
    }
    for bundle_name, rows in fixtures.items():
        bundle_dir = input_root / bundle_name
        bundle_dir.mkdir(parents=True, exist_ok=True)
        _write_fixture_ledger(bundle_dir / _BUNDLE_LEDGER_FILENAME, rows)
        (bundle_dir / _SUMMARY_FILENAME).write_text(
            json.dumps(
                {
                    "fixture": True,
                    "provider": rows[0]["provider"],
                    "normalized_row_count": len(rows),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return input_root


def _write_fixture_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "provider",
        "account_id_hash",
        "asset_type",
        "symbol",
        "name",
        "quantity",
        "currency",
        "market_value",
        "cost_basis",
        "unrealized_pnl",
        "source_timestamp",
        "source_confidence",
        "warning_codes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _provider_from_bundle(bundle_dir: Path, ledger_path: Path) -> str:
    try:
        with ledger_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            first = next(reader, None)
        if first and first.get("provider"):
            return str(first["provider"]).strip()
    except (OSError, StopIteration):
        pass
    name = bundle_dir.name.lower()
    for provider in ("manual_snapshot", "ibkr", "tiger", "moomoo"):
        if provider in name:
            return provider
    return "unknown"


def _as_of_date(source: dict[str, str]) -> str:
    return _clean(
        source.get("as_of_date")
        or source.get("source_snapshot_date")
        or source.get("source_timestamp")
    )


def _is_stale(raw_date: str, *, today: date) -> bool:
    parsed = _parse_date(raw_date)
    if parsed is None:
        return False
    return (today - parsed).days > _STALE_DAYS


def _parse_date(raw_date: str) -> date | None:
    value = raw_date.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value[:8], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _duplicate_keys(rows: list[dict[str, str]]) -> set[tuple[str, str, str, str]]:
    counts: dict[tuple[str, str, str, str], int] = {}
    for row in rows:
        key = _duplicate_key(row)
        if not key[3]:
            continue
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _duplicate_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    source_id = row.get("source_bundle_id") or row.get("source_snapshot_id") or ""
    return (
        row.get("provider", ""),
        row.get("account_id_hash", ""),
        source_id,
        row.get("symbol", ""),
    )


def _extend_account_source_map(
    account_source_map: dict[str, dict[str, object]],
    bundle: MergeInputBundle,
    rows: list[dict[str, str]],
) -> None:
    for row in rows:
        account_hash = row.get("account_id_hash")
        if not account_hash:
            continue
        entry = account_source_map.setdefault(
            account_hash,
            {
                "providers": [],
                "source_bundle_ids": [],
                "source_snapshot_ids": [],
            },
        )
        _append_unique(entry["providers"], row.get("provider") or bundle.provider)
        if row.get("source_bundle_id"):
            _append_unique(entry["source_bundle_ids"], row["source_bundle_id"])
        if row.get("source_snapshot_id"):
            _append_unique(entry["source_snapshot_ids"], row["source_snapshot_id"])


def _append_unique(values: object, value: str) -> None:
    if not isinstance(values, list) or not value:
        return
    if value not in values:
        values.append(value)


def _append_row_warning(row: dict[str, str], code: WarningCode) -> None:
    current = [value for value in row.get("merge_warnings", "").split(";") if value]
    if code.value not in current:
        current.append(code.value)
    row["merge_warnings"] = ";".join(current)


def _provider_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        provider = row.get("provider") or "unknown"
        counts[provider] = counts.get(provider, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
