"""Offline account-NAV-first merge layer for provider ledger bundles."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from personal_cfo_agent.models import WarningCode


ACCOUNT_NAV_FIELDNAMES = [
    "provider",
    "account_id_hash",
    "source_bundle_id",
    "source_snapshot_id",
    "as_of_date",
    "base_currency",
    "account_nav",
    "total_assets",
    "cash_total",
    "securities_market_value",
    "margin_or_debt",
    "buying_power",
    "provider_reported_nav_available",
    "nav_source",
    "source_confidence",
    "warning_codes",
]

POSITION_LEDGER_FIELDNAMES = [
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
_NAV_RECONCILIATION_TOLERANCE = 1.0


@dataclass(frozen=True)
class MergeInputBundle:
    provider: str
    bundle_dir: Path
    ledger_path: Path
    summary_path: Path | None


@dataclass(frozen=True)
class BundleImportResult:
    provider: str
    source_bundle_id: str
    status: str
    account_nav_rows: int
    position_rows: int
    summary_present: bool
    warning_codes: list[WarningCode] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "source_bundle_id": self.source_bundle_id,
            "status": self.status,
            "account_nav_rows": self.account_nav_rows,
            "position_rows": self.position_rows,
            "summary_present": self.summary_present,
            "warning_codes": [code.value for code in self.warning_codes],
        }


@dataclass
class MergeResult:
    output_dir: Path
    output_paths: dict[str, Path]
    account_nav_row_count: int
    position_row_count: int
    provider_counts: dict[str, int]
    warning_codes: list[WarningCode] = field(default_factory=list)
    source_bundle_count: int = 0
    bundle_results: list[BundleImportResult] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return self.account_nav_row_count + self.position_row_count


def merge_provider_bundles(
    *,
    input_root: Path | None,
    out_dir: Path,
    fixture_mode: bool = False,
    today: date | None = None,
    nav_tolerance: float = _NAV_RECONCILIATION_TOLERANCE,
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
    account_rows, position_rows, warnings, account_source_map, bundle_results = (
        _read_and_merge_bundles(
            bundles,
            today=today or date.today(),
            nav_tolerance=nav_tolerance,
        )
    )
    if not bundles:
        warnings.append(WarningCode.PROVIDER_BUNDLE_MISSING)
        bundle_results.append(
            BundleImportResult(
                provider="all",
                source_bundle_id="",
                status="missing_bundle",
                account_nav_rows=0,
                position_rows=0,
                summary_present=False,
                warning_codes=[WarningCode.PROVIDER_BUNDLE_MISSING],
            )
        )
    if not account_rows and not position_rows:
        warnings.append(WarningCode.EMPTY_PROVIDER_LEDGER)

    warnings = _dedupe_warning_codes(warnings)
    completion_code = (
        WarningCode.MERGE_COMPLETED_WITH_WARNINGS
        if warnings
        else WarningCode.MERGE_COMPLETED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion_code])
    provider_counts = _provider_counts(account_rows)
    paths = _write_merge_outputs(
        out_dir=out_dir,
        account_rows=account_rows,
        position_rows=position_rows,
        warnings=warnings,
        account_source_map=account_source_map,
        provider_counts=provider_counts,
        source_bundle_count=len(bundles),
        bundle_results=bundle_results,
        fixture_mode=fixture_mode,
    )
    return MergeResult(
        output_dir=out_dir,
        output_paths=paths,
        account_nav_row_count=len(account_rows),
        position_row_count=len(position_rows),
        provider_counts=provider_counts,
        warning_codes=warnings,
        source_bundle_count=len(bundles),
        bundle_results=bundle_results,
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
    bundles: list[MergeInputBundle], *, today: date, nav_tolerance: float
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[WarningCode],
    dict[str, object],
    list[BundleImportResult],
]:
    account_rows: list[dict[str, str]] = []
    position_rows: list[dict[str, str]] = []
    warnings: list[WarningCode] = []
    account_source_map: dict[str, dict[str, object]] = {}
    bundle_results: list[BundleImportResult] = []
    for bundle in bundles:
        bundle_account_rows, bundle_position_rows, bundle_warnings, bundle_result = (
            _read_bundle(bundle, today=today, nav_tolerance=nav_tolerance)
        )
        warnings.extend(bundle_warnings)
        account_rows.extend(bundle_account_rows)
        position_rows.extend(bundle_position_rows)
        bundle_results.append(bundle_result)
        _extend_account_source_map(account_source_map, bundle, bundle_account_rows)

    duplicate_keys = _duplicate_keys(position_rows)
    if duplicate_keys:
        warnings.append(WarningCode.POSSIBLE_DUPLICATE_POSITION)
        for row in position_rows:
            key = _duplicate_key(row)
            if key in duplicate_keys:
                _append_row_warning(row, WarningCode.POSSIBLE_DUPLICATE_POSITION)

    as_of_dates = {
        row["as_of_date"]
        for row in [*account_rows, *position_rows]
        if row.get("as_of_date")
    }
    if len(as_of_dates) > 1:
        warnings.append(WarningCode.MIXED_AS_OF_DATES)
        for row in account_rows:
            _append_warning_text(row, "warning_codes", WarningCode.MIXED_AS_OF_DATES)
        for row in position_rows:
            _append_row_warning(row, WarningCode.MIXED_AS_OF_DATES)
    return (
        account_rows,
        position_rows,
        _dedupe_warning_codes(warnings),
        account_source_map,
        bundle_results,
    )


def _read_bundle(
    bundle: MergeInputBundle, *, today: date, nav_tolerance: float
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[WarningCode],
    BundleImportResult,
]:
    warnings: list[WarningCode] = []
    if bundle.summary_path is None:
        warnings.append(WarningCode.PROVIDER_SUMMARY_MISSING)
    with bundle.ledger_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        if "provider" not in fieldnames or "account_id_hash" not in fieldnames:
            warnings.append(WarningCode.PROVIDER_SCHEMA_MISMATCH)
            warnings = _dedupe_warning_codes(warnings)
            return [], [], warnings, _bundle_result(bundle, "schema_mismatch", 0, 0, warnings)
        source_rows = list(reader)
    if not source_rows:
        warnings = _dedupe_warning_codes([*warnings, WarningCode.EMPTY_PROVIDER_LEDGER])
        return [], [], warnings, _bundle_result(bundle, "empty_ledger", 0, 0, warnings)

    position_rows = [_to_position_row(bundle, source, today=today) for source in source_rows]
    position_rows = [row for row in position_rows if row is not None]
    grouped = _group_source_rows(bundle, source_rows)
    account_rows: list[dict[str, str]] = []
    for key_rows in grouped.values():
        account_row, account_warnings = _to_account_nav_row(
            bundle,
            key_rows,
            today=today,
            nav_tolerance=nav_tolerance,
        )
        warnings.extend(account_warnings)
        account_rows.append(account_row)

    for row in position_rows:
        row_warning_codes = _position_row_warning_codes(row, today=today)
        if not row["symbol"]:
            # Positions without symbols are retained for auditability.
            row_warning_codes.append(WarningCode.SYMBOL_MISSING)
        for code in row_warning_codes:
            _append_row_warning(row, code)
        warnings.extend(row_warning_codes)
    if not position_rows:
        warnings.append(WarningCode.POSITION_ROWS_MISSING)
        warnings.append(WarningCode.POSITION_LEDGER_BEST_EFFORT)

    warnings = _dedupe_warning_codes(warnings)
    status = "imported_with_warnings" if warnings else "imported"
    return (
        account_rows,
        position_rows,
        warnings,
        _bundle_result(bundle, status, len(account_rows), len(position_rows), warnings),
    )


def _to_account_nav_row(
    bundle: MergeInputBundle,
    source_rows: list[dict[str, str]],
    *,
    today: date,
    nav_tolerance: float,
) -> tuple[dict[str, str], list[WarningCode]]:
    first = source_rows[0]
    provider = _clean(first.get("provider")) or bundle.provider
    source_bundle_id, source_snapshot_id = _source_ids(bundle, provider, first)
    as_of_date = _as_of_date(first)
    account_hash = _clean(first.get("account_id_hash"))
    base_currency = _base_currency(source_rows)
    reported_nav = _provider_reported_nav(source_rows)
    reported_nav_currency = _provider_reported_nav_currency(source_rows)
    if reported_nav is not None and reported_nav_currency:
        base_currency = reported_nav_currency
    total_assets = _first_number(source_rows, ["total_assets"])
    cash_total = _sum_market_value(source_rows, asset_types={"cash"})
    securities_market_value = _sum_market_value(
        source_rows,
        exclude_asset_types={"cash", "liability", "debt", "margin", "account_nav"},
    )
    margin_or_debt = _first_number(source_rows, ["margin_or_debt", "debt_total"])
    if margin_or_debt is None:
        margin_or_debt = _sum_market_value(
            source_rows, asset_types={"liability", "debt", "margin"}
        )
    buying_power = _first_number(source_rows, ["buying_power"])
    derived_nav = _derive_nav(cash_total, securities_market_value, margin_or_debt)
    warnings: list[WarningCode] = []
    nav_source = "unavailable"
    account_nav: float | None = None
    provider_reported_available = reported_nav is not None
    if provider_reported_available:
        account_nav = reported_nav
        nav_source = "provider_reported"
        warnings.append(WarningCode.ACCOUNT_NAV_PROVIDER_REPORTED)
        if derived_nav is not None:
            if abs(reported_nav - derived_nav) <= nav_tolerance:
                warnings.append(WarningCode.ACCOUNT_NAV_RECONCILIATION_OK)
            else:
                warnings.append(WarningCode.ACCOUNT_NAV_RECONCILIATION_MISMATCH)
    elif provider == "manual_snapshot" and derived_nav is not None:
        account_nav = derived_nav
        nav_source = "manual_snapshot"
        warnings.append(WarningCode.ACCOUNT_NAV_DERIVED)
    elif derived_nav is not None:
        account_nav = derived_nav
        nav_source = "derived_from_cash_plus_positions"
        warnings.append(WarningCode.ACCOUNT_NAV_DERIVED)
        warnings.append(WarningCode.ACCOUNT_NAV_MISSING)
    else:
        warnings.append(WarningCode.ACCOUNT_NAV_MISSING)
        warnings.append(WarningCode.ACCOUNT_NAV_UNAVAILABLE)

    if not account_hash:
        warnings.append(WarningCode.ACCOUNT_HASH_MISSING)
    if not base_currency:
        warnings.append(WarningCode.CURRENCY_MISSING)
    if not as_of_date:
        warnings.append(WarningCode.AS_OF_DATE_MISSING)
    if _is_stale(as_of_date, today=today):
        warnings.append(WarningCode.STALE_PROVIDER_BUNDLE)

    row = {
        "provider": provider,
        "account_id_hash": account_hash,
        "source_bundle_id": source_bundle_id,
        "source_snapshot_id": source_snapshot_id,
        "as_of_date": as_of_date,
        "base_currency": base_currency,
        "account_nav": _number_to_text(account_nav),
        "total_assets": _number_to_text(
            total_assets
            if total_assets is not None
            else (reported_nav if provider_reported_available else derived_nav)
        ),
        "cash_total": _number_to_text(cash_total),
        "securities_market_value": _number_to_text(securities_market_value),
        "margin_or_debt": _number_to_text(margin_or_debt),
        "buying_power": _number_to_text(buying_power),
        "provider_reported_nav_available": "yes" if provider_reported_available else "no",
        "nav_source": nav_source,
        "source_confidence": _clean(first.get("source_confidence")),
        "warning_codes": "",
    }
    for code in warnings:
        _append_warning_text(row, "warning_codes", code)
    return row, _dedupe_warning_codes(warnings)


def _to_position_row(
    bundle: MergeInputBundle, source: dict[str, str], *, today: date
) -> dict[str, str] | None:
    provider = _clean(source.get("provider")) or bundle.provider
    asset_type = _clean(source.get("asset_type"))
    if asset_type == "account_nav":
        return None
    source_bundle_id, source_snapshot_id = _source_ids(bundle, provider, source)
    return {
        "provider": provider,
        "account_id_hash": _clean(source.get("account_id_hash")),
        "source_bundle_id": source_bundle_id,
        "source_snapshot_id": source_snapshot_id,
        "asset_type": asset_type,
        "symbol": _clean(source.get("symbol")),
        "name": _clean(source.get("name")),
        "currency": _clean(source.get("currency")),
        "quantity": _clean(source.get("quantity")),
        "market_value": _clean(source.get("market_value")),
        "cost_basis": _clean(source.get("cost_basis")),
        "average_cost": _clean(source.get("average_cost")),
        "unrealized_pnl": _clean(source.get("unrealized_pnl")),
        "as_of_date": _as_of_date(source),
        "source_confidence": _clean(source.get("source_confidence")),
        "normalization_warnings": _clean(
            source.get("normalization_warnings") or source.get("warning_codes")
        ),
        "merge_warnings": "",
    }


def _position_row_warning_codes(
    row: dict[str, str], *, today: date
) -> list[WarningCode]:
    warnings = [WarningCode.POSITION_LEDGER_BEST_EFFORT]
    if not row["account_id_hash"]:
        warnings.append(WarningCode.ACCOUNT_HASH_MISSING)
    if not row["currency"]:
        warnings.append(WarningCode.CURRENCY_MISSING)
    if not row["as_of_date"]:
        warnings.append(WarningCode.AS_OF_DATE_MISSING)
    if not row["market_value"]:
        warnings.append(WarningCode.MARKET_VALUE_MISSING)
    if not row["cost_basis"]:
        warnings.append(WarningCode.COST_BASIS_MISSING)
    if _is_stale(row["as_of_date"], today=today):
        warnings.append(WarningCode.STALE_PROVIDER_BUNDLE)
    return _dedupe_warning_codes(warnings)


def _write_merge_outputs(
    *,
    out_dir: Path,
    account_rows: list[dict[str, str]],
    position_rows: list[dict[str, str]],
    warnings: list[WarningCode],
    account_source_map: dict[str, object],
    provider_counts: dict[str, int],
    source_bundle_count: int,
    bundle_results: list[BundleImportResult],
    fixture_mode: bool,
) -> dict[str, Path]:
    paths = {
        "merged_account_nav_ledger": out_dir / "merged_account_nav_ledger.csv",
        "merged_account_nav_summary": out_dir / "merged_account_nav_summary.json",
        "merged_position_ledger": out_dir / "merged_position_ledger.csv",
        "merged_provider_summary": out_dir / "merged_provider_summary.json",
        "account_source_map": out_dir / "account_source_map.json",
        "merge_warnings": out_dir / "merge_warnings.md",
        "markdown_report": out_dir / "MERGED_LEDGER_V033.md",
    }
    _write_csv(paths["merged_account_nav_ledger"], ACCOUNT_NAV_FIELDNAMES, account_rows)
    _write_csv(paths["merged_position_ledger"], POSITION_LEDGER_FIELDNAMES, position_rows)

    nav_summary = {
        "version": "v0.3.3",
        "account_nav_first": True,
        "account_nav_row_count": len(account_rows),
        "provider_counts": provider_counts,
        "warning_codes": [code.value for code in warnings],
    }
    paths["merged_account_nav_summary"].write_text(
        json.dumps(nav_summary, indent=2), encoding="utf-8"
    )

    provider_summary = {
        "version": "v0.3.3",
        "mode": "fixture" if fixture_mode else "offline_merge",
        "offline_merge_only": True,
        "broker_connections": "not_used",
        "account_nav_first": True,
        "position_ledger_best_effort": True,
        "source_bundle_count": source_bundle_count,
        "account_nav_row_count": len(account_rows),
        "position_row_count": len(position_rows),
        "provider_counts": provider_counts,
        "bundle_results": [result.to_dict() for result in bundle_results],
        "warning_codes": [code.value for code in warnings],
        "outputs": {key: str(path) for key, path in paths.items()},
    }
    paths["merged_provider_summary"].write_text(
        json.dumps(provider_summary, indent=2), encoding="utf-8"
    )
    paths["account_source_map"].write_text(
        json.dumps(account_source_map, indent=2), encoding="utf-8"
    )
    _write_warnings_report(paths["merge_warnings"], warnings, provider_counts)
    _write_markdown_report(
        paths["markdown_report"],
        account_rows=account_rows,
        position_rows=position_rows,
        warnings=warnings,
        provider_counts=provider_counts,
        source_bundle_count=source_bundle_count,
        fixture_mode=fixture_mode,
    )
    return paths


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_warnings_report(
    path: Path, warnings: list[WarningCode], provider_counts: dict[str, int]
) -> None:
    lines = [
        "# Multi-provider Merge Warnings",
        "",
        "This report is generated by the offline account-NAV-first merge layer.",
        "",
        "## Provider Account Counts",
    ]
    for provider, count in sorted(provider_counts.items()):
        lines.append(f"- {provider}: {count} accounts")
    lines.extend(["", "## Warning Codes"])
    for code in warnings:
        lines.append(f"- {code.value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown_report(
    path: Path,
    *,
    account_rows: list[dict[str, str]],
    position_rows: list[dict[str, str]],
    warnings: list[WarningCode],
    provider_counts: dict[str, int],
    source_bundle_count: int,
    fixture_mode: bool,
) -> None:
    lines = [
        "# Multi-provider Normalized Ledger v0.3.3",
        "",
        "This is offline account-NAV-first audit and reconciliation infrastructure.",
        "The position ledger is best-effort drilldown data, not the acceptance gate.",
        "No broker API connection, account write action, money movement, or advice workflow is used.",
        "",
        f"- Mode: {'fixture' if fixture_mode else 'offline merge'}",
        f"- Source bundles: {source_bundle_count}",
        f"- Account NAV rows: {len(account_rows)}",
        f"- Position rows: {len(position_rows)}",
        "",
        "## Provider Account Counts",
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
            _fixture_row(
                provider="manual_snapshot",
                account_hash="acct_manual_fixture_001",
                asset_type="cash",
                symbol="SGD",
                market_value="1000.00",
                cost_basis="",
                currency="SGD",
            )
        ],
        "ibkr_fixture": [
            _fixture_row(
                provider="ibkr",
                account_hash="acct_ibkr_fixture_001",
                asset_type="account_nav",
                symbol="NAV",
                market_value="1000.00",
                cost_basis="",
                account_nav="1000.00",
                total_assets="1000.00",
                cash_total="300.00",
                securities_market_value="700.00",
                currency="USD",
            ),
            _fixture_row(
                provider="ibkr",
                account_hash="acct_ibkr_fixture_001",
                asset_type="cash",
                symbol="USD",
                market_value="300.00",
                cost_basis="",
                currency="USD",
            ),
            _fixture_row(
                provider="ibkr",
                account_hash="acct_ibkr_fixture_001",
                asset_type="equity",
                symbol="AAPL",
                market_value="400.00",
                cost_basis="350.00",
                currency="USD",
            ),
            _fixture_row(
                provider="ibkr",
                account_hash="acct_ibkr_fixture_001",
                asset_type="equity",
                symbol="AAPL",
                market_value="300.00",
                cost_basis="250.00",
                currency="USD",
                name="Apple Inc synthetic duplicate",
            ),
        ],
        "tiger_fixture": [
            _fixture_row(
                provider="tiger",
                account_hash="acct_tiger_fixture_001",
                asset_type="equity",
                symbol="AAPL",
                market_value="600.00",
                cost_basis="540.00",
                currency="USD",
            )
        ],
        "moomoo_fixture": [
            _fixture_row(
                provider="moomoo",
                account_hash="acct_moomoo_fixture_001",
                asset_type="cash",
                symbol="HKD",
                market_value="500.00",
                cost_basis="",
                currency="HKD",
            )
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


def _fixture_row(
    *,
    provider: str,
    account_hash: str,
    asset_type: str,
    symbol: str,
    market_value: str,
    cost_basis: str,
    currency: str,
    account_nav: str = "",
    total_assets: str = "",
    cash_total: str = "",
    securities_market_value: str = "",
    name: str = "Synthetic asset",
) -> dict[str, str]:
    return {
        "provider": provider,
        "account_id_hash": account_hash,
        "source_bundle_id": f"{provider}_fixture_bundle",
        "asset_type": asset_type,
        "symbol": symbol,
        "name": name,
        "quantity": "1",
        "currency": currency,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "average_cost": cost_basis,
        "unrealized_pnl": "",
        "account_nav": account_nav,
        "total_assets": total_assets,
        "cash_total": cash_total,
        "securities_market_value": securities_market_value,
        "source_timestamp": "2026-06-15",
        "source_confidence": "synthetic_fixture",
        "warning_codes": "ACCOUNT_ID_HASHED",
    }


def _write_fixture_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "provider",
        "account_id_hash",
        "source_bundle_id",
        "asset_type",
        "symbol",
        "name",
        "quantity",
        "currency",
        "market_value",
        "cost_basis",
        "average_cost",
        "unrealized_pnl",
        "account_nav",
        "total_assets",
        "cash_total",
        "securities_market_value",
        "source_timestamp",
        "source_confidence",
        "warning_codes",
    ]
    _write_csv(path, fieldnames, rows)


def _group_source_rows(
    bundle: MergeInputBundle, rows: list[dict[str, str]]
) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        provider = _clean(row.get("provider")) or bundle.provider
        source_bundle_id, source_snapshot_id = _source_ids(bundle, provider, row)
        key = (
            provider,
            _clean(row.get("account_id_hash")),
            source_bundle_id,
            source_snapshot_id,
        )
        grouped.setdefault(key, []).append(row)
    return grouped


def _source_ids(
    bundle: MergeInputBundle, provider: str, source: dict[str, str]
) -> tuple[str, str]:
    source_bundle_id = _clean(source.get("source_bundle_id")) or bundle.bundle_dir.name
    source_snapshot_id = _clean(source.get("source_snapshot_id"))
    if provider == "manual_snapshot" and not source_snapshot_id:
        source_snapshot_id = source_bundle_id
        source_bundle_id = ""
    return source_bundle_id, source_snapshot_id


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


def _bundle_result(
    bundle: MergeInputBundle,
    status: str,
    account_nav_rows: int,
    position_rows: int,
    warnings: list[WarningCode],
) -> BundleImportResult:
    return BundleImportResult(
        provider=bundle.provider,
        source_bundle_id=bundle.bundle_dir.name,
        status=status,
        account_nav_rows=account_nav_rows,
        position_rows=position_rows,
        summary_present=bundle.summary_path is not None,
        warning_codes=_dedupe_warning_codes(warnings),
    )


def _as_of_date(source: dict[str, str]) -> str:
    return _clean(
        source.get("as_of_date")
        or source.get("source_snapshot_date")
        or source.get("source_timestamp")
    )


def _base_currency(rows: list[dict[str, str]]) -> str:
    explicit = _clean(rows[0].get("base_currency"))
    if explicit:
        return explicit
    currencies = {_clean(row.get("currency")) for row in rows if _clean(row.get("currency"))}
    if len(currencies) == 1:
        return next(iter(currencies))
    return ""


def _first_number(rows: list[dict[str, str]], fields: list[str]) -> float | None:
    for row in rows:
        for field in fields:
            value = _parse_number(row.get(field))
            if value is not None:
                return value
    return None


def _provider_reported_nav(rows: list[dict[str, str]]) -> float | None:
    explicit_nav = _first_number(
        rows,
        [
            "account_nav",
            "provider_reported_nav",
            "net_liquidation",
            "net_asset_value",
            "total_nav",
        ],
    )
    if explicit_nav is not None:
        return explicit_nav
    for row in rows:
        if _clean(row.get("asset_type")) != "account_nav":
            continue
        nav = _parse_number(row.get("market_value"))
        if nav is not None:
            return nav
    return None


def _provider_reported_nav_currency(rows: list[dict[str, str]]) -> str:
    explicit_fields = [
        "account_nav",
        "provider_reported_nav",
        "net_liquidation",
        "net_asset_value",
        "total_nav",
    ]
    for row in rows:
        if any(_parse_number(row.get(field)) is not None for field in explicit_fields):
            return _clean(row.get("base_currency")) or _clean(row.get("currency"))
    for row in rows:
        if _clean(row.get("asset_type")) != "account_nav":
            continue
        if _parse_number(row.get("market_value")) is not None:
            return _clean(row.get("base_currency")) or _clean(row.get("currency"))
    return ""


def _sum_market_value(
    rows: list[dict[str, str]],
    *,
    asset_types: set[str] | None = None,
    exclude_asset_types: set[str] | None = None,
) -> float | None:
    total = 0.0
    found = False
    for row in rows:
        asset_type = _clean(row.get("asset_type")).lower()
        if asset_types is not None and asset_type not in asset_types:
            continue
        if exclude_asset_types is not None and asset_type in exclude_asset_types:
            continue
        value = _parse_number(row.get("market_value"))
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def _derive_nav(
    cash_total: float | None,
    securities_market_value: float | None,
    margin_or_debt: float | None,
) -> float | None:
    if cash_total is None and securities_market_value is None and margin_or_debt is None:
        return None
    return (cash_total or 0.0) + (securities_market_value or 0.0) - abs(margin_or_debt or 0.0)


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
            return datetime.strptime(
                value[:10] if fmt == "%Y-%m-%d" else value[:8], fmt
            ).date()
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
    account_rows: list[dict[str, str]],
) -> None:
    for row in account_rows:
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
    _append_warning_text(row, "merge_warnings", code)


def _append_warning_text(row: dict[str, str], field: str, code: WarningCode) -> None:
    current = [value for value in row.get(field, "").split(";") if value]
    if code.value not in current:
        current.append(code.value)
    row[field] = ";".join(current)


def _provider_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        provider = row.get("provider") or "unknown"
        counts[provider] = counts.get(provider, 0) + 1
    return dict(sorted(counts.items()))


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


def _number_to_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


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
