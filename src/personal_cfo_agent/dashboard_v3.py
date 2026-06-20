"""Integrated offline net worth dashboard for v0.5.0."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.5.0"

DASHBOARD_V3_STATEMENT = (
    "This is an offline Personal CFO dashboard for review only. It is not "
    "an instruction to invest, take market action, insure, file taxes, or move cash."
)

NET_WORTH_PROGRESS_FIELDNAMES = [
    "snapshot_date",
    "snapshot_id",
    "base_currency",
    "total_account_nav",
    "property_equity",
    "cpf_total",
    "srs_total",
    "mortgage_liabilities",
    "integrated_net_worth",
    "provider_count",
    "account_count",
    "review_required",
    "warning_codes",
]

BALANCE_SHEET_SUMMARY_FIELDNAMES = [
    "category",
    "amount",
    "currency",
    "source_layer",
    "review_required",
    "warning_codes",
]

ASSET_LIABILITY_BREAKDOWN_FIELDNAMES = [
    "layer",
    "item_type",
    "item_label",
    "amount",
    "currency",
    "row_count",
    "review_required",
    "warning_codes",
]


@dataclass
class DashboardV3Result:
    merge_dir: Path
    snapshot_dir: Path
    dashboard_dir: Path | None
    property_mortgage_dir: Path | None
    sg_snapshot_dir: Path | None
    output_dir: Path | None
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    account_count: int = 0
    provider_count: int = 0
    position_count: int = 0
    net_worth_history_count: int = 0
    property_count: int = 0
    mortgage_count: int = 0
    cpf_count: int = 0
    srs_count: int = 0
    tax_count: int = 0
    hdb_loan_count: int = 0
    generated: bool = False


@dataclass(frozen=True)
class _FxContext:
    base_currency: str
    rates_to_base: dict[str, float]


def write_dashboard_v3(
    *,
    merge_dir: Path,
    snapshot_dir: Path,
    out_dir: Path,
    dashboard_dir: Path | None = None,
    property_mortgage_dir: Path | None = None,
    sg_snapshot_dir: Path | None = None,
    fx_rates_input: Path | None = None,
) -> DashboardV3Result:
    """Write an integrated offline dashboard from existing local report bundles."""

    warnings: list[WarningCode] = []
    account_path = merge_dir / "merged_account_nav_ledger.csv"
    position_path = merge_dir / "merged_position_ledger.csv"
    net_worth_path = snapshot_dir / "net_worth_history.csv"
    account_history_path = snapshot_dir / "account_nav_history.csv"
    provider_history_path = snapshot_dir / "provider_nav_history.csv"

    if not merge_dir.exists() or not snapshot_dir.exists():
        warnings.append(WarningCode.DASHBOARD_V3_INPUT_MISSING)
        return _failed_result(
            merge_dir, snapshot_dir, dashboard_dir, property_mortgage_dir, sg_snapshot_dir, warnings
        )
    if not account_path.exists():
        warnings.append(WarningCode.DASHBOARD_V3_MERGE_LEDGER_MISSING)
        return _failed_result(
            merge_dir, snapshot_dir, dashboard_dir, property_mortgage_dir, sg_snapshot_dir, warnings
        )
    if not net_worth_path.exists():
        warnings.append(WarningCode.DASHBOARD_V3_SNAPSHOT_HISTORY_MISSING)
        return _failed_result(
            merge_dir, snapshot_dir, dashboard_dir, property_mortgage_dir, sg_snapshot_dir, warnings
        )

    account_rows = _read_csv(account_path)
    position_rows = _read_csv(position_path) if position_path.exists() else []
    net_worth_rows = _read_csv(net_worth_path)
    if not net_worth_rows:
        warnings.append(WarningCode.DASHBOARD_V3_SNAPSHOT_HISTORY_EMPTY)
        return _failed_result(
            merge_dir, snapshot_dir, dashboard_dir, property_mortgage_dir, sg_snapshot_dir, warnings
        )

    account_history_rows = _read_csv(account_history_path) if account_history_path.exists() else []
    provider_history_rows = _read_csv(provider_history_path) if provider_history_path.exists() else []
    dashboard_summary, dashboard_warning_text = _load_dashboard_v2_inputs(
        dashboard_dir, snapshot_dir, warnings
    )
    fx_context = _load_fx_context(fx_rates_input, warnings)
    latest_snapshot = net_worth_rows[-1]
    input_warning_values = _input_warning_values(
        account_rows,
        net_worth_rows,
        account_history_rows,
        provider_history_rows,
        _dashboard_warning_rows(dashboard_summary),
        text=_read_text(snapshot_dir / "snapshot_warnings.md"),
    )
    input_warning_values.update(_warning_codes_from_text(dashboard_warning_text))

    property_summary = _load_property_summary(property_mortgage_dir, warnings)
    sg_summary = _load_sg_summary(sg_snapshot_dir, warnings)

    cpf_rows = _read_optional_csv(sg_snapshot_dir / "cpf_snapshot_ledger.csv") if sg_snapshot_dir else []
    srs_rows = _read_optional_csv(sg_snapshot_dir / "srs_snapshot_ledger.csv") if sg_snapshot_dir else []
    tax_rows = _read_optional_csv(sg_snapshot_dir / "tax_snapshot_ledger.csv") if sg_snapshot_dir else []
    hdb_rows = _read_optional_csv(sg_snapshot_dir / "hdb_loan_snapshot_ledger.csv") if sg_snapshot_dir else []
    mixed_currency_nav = (
        "SNAPSHOT_MIXED_CURRENCY_NAV" in input_warning_values
        or _mixed_or_missing_account_nav_currency(account_rows)
    )
    if mixed_currency_nav:
        warnings.append(WarningCode.DASHBOARD_V3_MIXED_CURRENCY_NAV)
    base_currency = _clean(latest_snapshot.get("base_currency")) or _single_account_nav_currency(
        account_rows
    ) or _first_currency(
        account_rows, cpf_rows, srs_rows
    )
    fx_required = _fx_required_for_top_level(
        account_rows=account_rows,
        property_summary=property_summary,
        cpf_rows=cpf_rows,
        srs_rows=srs_rows,
        base_currency=base_currency,
    )
    if fx_context is not None:
        base_currency = fx_context.base_currency
        warnings.append(WarningCode.DASHBOARD_V3_FX_NORMALIZATION_APPLIED)
        account_nav = _sum_rows_converted(
            account_rows, "account_nav", "base_currency", fx_context, warnings
        )
        property_equity = _sum_mapping_converted(
            property_summary.get("total_equity_by_currency"), fx_context, warnings
        )
        gross_mortgage_liabilities = _sum_mortgage_ledger(
            property_mortgage_dir, fx_context=fx_context, warnings=warnings
        )
        unlinked_mortgage_liabilities = _sum_mapping_converted(
            property_summary.get("unlinked_liability_total_by_currency"), fx_context, warnings
        )
        cpf_total = _sum_rows_converted(cpf_rows, "total", "currency", fx_context, warnings)
        srs_total = _sum_rows_converted(srs_rows, "total", "currency", fx_context, warnings)
    elif fx_required:
        warnings.append(WarningCode.DASHBOARD_V3_FX_RATE_MISSING)
        account_nav = None
        property_equity = None
        gross_mortgage_liabilities = None
        unlinked_mortgage_liabilities = None
        cpf_total = None
        srs_total = None
        base_currency = "MIXED"
    else:
        account_nav = (
            None if mixed_currency_nav else _parse_number(latest_snapshot.get("total_account_nav"))
        )
        property_equity = _sum_mapping(property_summary.get("total_equity_by_currency"))
        gross_mortgage_liabilities = _sum_mortgage_ledger(property_mortgage_dir)
        unlinked_mortgage_liabilities = _sum_mapping(
            property_summary.get("unlinked_liability_total_by_currency")
        )
        cpf_total = _sum_field(cpf_rows, "total")
        srs_total = _sum_field(srs_rows, "total")
    integrated_net_worth = None
    if (
        account_nav is not None
        and property_equity is not None
        and cpf_total is not None
        and srs_total is not None
    ):
        integrated_net_worth = (
            account_nav
            + property_equity
            + cpf_total
            + srs_total
            - abs(unlinked_mortgage_liabilities or 0.0)
        )

    if _review_required(input_warning_values, property_summary, sg_summary):
        warnings.append(WarningCode.DASHBOARD_V3_REVIEW_REQUIRED)
    warnings = _dedupe_warning_codes(warnings)
    completion = (
        WarningCode.DASHBOARD_V3_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.DASHBOARD_V3_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    net_worth_progress_rows = [
        _net_worth_progress_row(
            row,
            base_currency=base_currency,
            account_nav=account_nav if row is latest_snapshot else None,
            override_account_nav=row is latest_snapshot and (fx_context is not None or fx_required),
            property_equity=property_equity,
            cpf_total=cpf_total,
            srs_total=srs_total,
            mortgage_liabilities=gross_mortgage_liabilities,
            integrated_net_worth=integrated_net_worth if row is latest_snapshot else None,
            warnings=warnings,
        )
        for row in net_worth_rows
    ]
    balance_rows = _balance_sheet_rows(
        base_currency=base_currency,
        account_nav=account_nav,
        property_equity=property_equity,
        cpf_total=cpf_total,
        srs_total=srs_total,
        mortgage_liabilities=gross_mortgage_liabilities,
        integrated_net_worth=integrated_net_worth,
        warnings=warnings,
    )
    breakdown_rows = _breakdown_rows(
        account_rows=account_rows,
        position_rows=position_rows,
        property_summary=property_summary,
        gross_mortgage_liabilities=gross_mortgage_liabilities,
        unlinked_mortgage_liabilities=unlinked_mortgage_liabilities,
        cpf_rows=cpf_rows,
        srs_rows=srs_rows,
        tax_rows=tax_rows,
        hdb_rows=hdb_rows,
        base_currency=base_currency,
        fx_context=fx_context,
        warnings=warnings,
    )
    summary = {
        "version": SCHEMA_VERSION,
        "offline_only": True,
        "broker_connections": "not_used",
        "external_connections": "not_used",
        "account_nav_first": True,
        "snapshot_history_primary": True,
        "merge_dir": str(merge_dir),
        "snapshot_dir": str(snapshot_dir),
        "dashboard_dir": str(dashboard_dir) if dashboard_dir else "",
        "dashboard_v2_summary_present": bool(dashboard_summary),
        "dashboard_v2_account_count": _parse_int(dashboard_summary.get("account_count")) or 0,
        "dashboard_v2_provider_count": _parse_int(dashboard_summary.get("provider_count")) or 0,
        "dashboard_v2_position_count": _parse_int(dashboard_summary.get("position_count")) or 0,
        "property_mortgage_dir": str(property_mortgage_dir) if property_mortgage_dir else "",
        "sg_snapshot_dir": str(sg_snapshot_dir) if sg_snapshot_dir else "",
        "fx_rates_input": str(fx_rates_input) if fx_rates_input else "",
        "fx_normalization_applied": "yes" if fx_context is not None else "no",
        "fx_base_currency": fx_context.base_currency if fx_context is not None else "",
        "fx_rate_currencies": (
            sorted(fx_context.rates_to_base) if fx_context is not None else []
        ),
        "account_count": len(account_rows),
        "provider_count": len({row.get("provider") for row in account_rows if row.get("provider")}),
        "position_count": len(position_rows),
        "net_worth_history_count": len(net_worth_rows),
        "property_count": _parse_int(property_summary.get("property_count")) or 0,
        "mortgage_count": _parse_int(property_summary.get("mortgage_count")) or 0,
        "cpf_count": len(cpf_rows),
        "srs_count": len(srs_rows),
        "tax_count": len(tax_rows),
        "hdb_loan_count": len(hdb_rows),
        "total_net_worth_available": "yes" if integrated_net_worth is not None else "no",
        "liquid_investable_assets_available": "yes" if account_nav is not None else "no",
        "property_equity_available": "yes" if property_equity is not None else "no",
        "retirement_assets_available": "yes" if cpf_total is not None or srs_total is not None else "no",
        "liabilities_available": "yes" if gross_mortgage_liabilities is not None or hdb_rows else "no",
        "gross_mortgage_liabilities_available": "yes" if gross_mortgage_liabilities is not None else "no",
        "unlinked_mortgage_liabilities_available": (
            "yes" if unlinked_mortgage_liabilities is not None else "no"
        ),
        "latest_snapshot_date": _clean(latest_snapshot.get("snapshot_date")),
        "latest_snapshot_id": _clean(latest_snapshot.get("snapshot_id")),
        "provider_names": sorted(
            {provider for row in account_rows if (provider := _clean(row.get("provider")))}
        ),
        "layer_status": _layer_status(
            dashboard_summary=dashboard_summary,
            property_summary=property_summary,
            sg_summary=sg_summary,
            summary_counts={
                "account_count": len(account_rows),
                "provider_count": len({row.get("provider") for row in account_rows if row.get("provider")}),
                "net_worth_history_count": len(net_worth_rows),
                "property_count": _parse_int(property_summary.get("property_count")) or 0,
                "mortgage_count": _parse_int(property_summary.get("mortgage_count")) or 0,
                "cpf_count": len(cpf_rows),
                "srs_count": len(srs_rows),
                "tax_count": len(tax_rows),
                "hdb_loan_count": len(hdb_rows),
            },
        ),
        "warning_codes": [code.value for code in warnings],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown_report": out_dir / "PERSONAL_CFO_DASHBOARD_V050.md",
        "html_report": out_dir / "PERSONAL_CFO_DASHBOARD_V050.html",
        "dashboard_summary": out_dir / "dashboard_v050_summary.json",
        "net_worth_progress": out_dir / "net_worth_progress.csv",
        "net_worth_history_chart": out_dir / "net_worth_history_chart.svg",
        "balance_sheet_summary": out_dir / "balance_sheet_summary.csv",
        "asset_liability_breakdown": out_dir / "asset_liability_breakdown.csv",
        "dashboard_warnings": out_dir / "dashboard_v050_warnings.md",
    }
    _write_csv(paths["net_worth_progress"], NET_WORTH_PROGRESS_FIELDNAMES, net_worth_progress_rows)
    _write_csv(paths["balance_sheet_summary"], BALANCE_SHEET_SUMMARY_FIELDNAMES, balance_rows)
    _write_csv(
        paths["asset_liability_breakdown"],
        ASSET_LIABILITY_BREAKDOWN_FIELDNAMES,
        breakdown_rows,
    )
    paths["dashboard_summary"].write_text(json.dumps(summary, indent=2), encoding="utf-8")
    markdown = _markdown(summary=summary, warnings=warnings, breakdown_rows=breakdown_rows)
    chart_svg = _net_worth_history_chart_svg(net_worth_progress_rows)
    paths["net_worth_history_chart"].write_text(chart_svg, encoding="utf-8")
    paths["markdown_report"].write_text(markdown, encoding="utf-8")
    paths["html_report"].write_text(_html(markdown, chart_svg=chart_svg), encoding="utf-8")
    _write_warnings(paths["dashboard_warnings"], warnings)

    return DashboardV3Result(
        merge_dir=merge_dir,
        snapshot_dir=snapshot_dir,
        dashboard_dir=dashboard_dir,
        property_mortgage_dir=property_mortgage_dir,
        sg_snapshot_dir=sg_snapshot_dir,
        output_dir=out_dir,
        output_paths=paths,
        warning_codes=warnings,
        account_count=len(account_rows),
        provider_count=summary["provider_count"],
        position_count=len(position_rows),
        net_worth_history_count=len(net_worth_rows),
        property_count=summary["property_count"],
        mortgage_count=summary["mortgage_count"],
        cpf_count=len(cpf_rows),
        srs_count=len(srs_rows),
        tax_count=len(tax_rows),
        hdb_loan_count=len(hdb_rows),
        generated=True,
    )


def _failed_result(
    merge_dir: Path,
    snapshot_dir: Path,
    dashboard_dir: Path | None,
    property_mortgage_dir: Path | None,
    sg_snapshot_dir: Path | None,
    warnings: list[WarningCode],
) -> DashboardV3Result:
    return DashboardV3Result(
        merge_dir=merge_dir,
        snapshot_dir=snapshot_dir,
        dashboard_dir=dashboard_dir,
        property_mortgage_dir=property_mortgage_dir,
        sg_snapshot_dir=sg_snapshot_dir,
        output_dir=None,
        warning_codes=_dedupe_warning_codes(warnings),
    )


def _load_property_summary(path: Path | None, warnings: list[WarningCode]) -> dict[str, Any]:
    if path is None or not path.exists():
        warnings.append(WarningCode.DASHBOARD_V3_PROPERTY_SNAPSHOT_MISSING)
        return {}
    summary = _read_json(path / "property_equity_summary.json")
    if summary is None:
        warnings.append(WarningCode.DASHBOARD_V3_PROPERTY_SNAPSHOT_MISSING)
        return {}
    return summary


def _load_sg_summary(path: Path | None, warnings: list[WarningCode]) -> dict[str, Any]:
    if path is None or not path.exists():
        warnings.append(WarningCode.DASHBOARD_V3_SG_SNAPSHOT_MISSING)
        return {}
    summary = _read_json(path / "sg_retirement_tax_summary.json")
    if summary is None:
        warnings.append(WarningCode.DASHBOARD_V3_SG_SNAPSHOT_MISSING)
        return {}
    return summary


def _load_dashboard_v2_inputs(
    dashboard_dir: Path | None,
    snapshot_dir: Path,
    warnings: list[WarningCode],
) -> tuple[dict[str, Any], str]:
    candidates: list[Path] = []
    if dashboard_dir is not None:
        candidates.append(dashboard_dir)
    candidates.extend(_dashboard_dirs_from_snapshot_manifest(snapshot_dir))
    for candidate in candidates:
        summary = _read_json(candidate / "dashboard_v040_summary.json")
        if summary is not None:
            return summary, _read_text(candidate / "dashboard_warnings.md")
    warnings.append(WarningCode.DASHBOARD_V3_DASHBOARD_V2_SUMMARY_MISSING)
    return {}, ""


def _dashboard_dirs_from_snapshot_manifest(snapshot_dir: Path) -> list[Path]:
    manifest = _read_json(snapshot_dir / "snapshot_manifest.json")
    if not isinstance(manifest, dict):
        return []
    raw_dir = _clean(manifest.get("input_dashboard_dir"))
    if not raw_dir:
        return []
    return [Path(raw_dir)]


def _dashboard_warning_rows(summary: dict[str, Any]) -> list[dict[str, str]]:
    warnings = summary.get("warning_codes") if isinstance(summary, dict) else []
    if not isinstance(warnings, list):
        return []
    return [{"warning_codes": ";".join(str(code) for code in warnings if code)}]


def _net_worth_progress_row(
    row: dict[str, str],
    *,
    base_currency: str,
    account_nav: float | None,
    override_account_nav: bool,
    property_equity: float | None,
    cpf_total: float | None,
    srs_total: float | None,
    mortgage_liabilities: float | None,
    integrated_net_worth: float | None,
    warnings: list[WarningCode],
) -> dict[str, str]:
    return {
        "snapshot_date": _clean(row.get("snapshot_date")),
        "snapshot_id": _clean(row.get("snapshot_id")),
        "base_currency": (
            base_currency if override_account_nav else _clean(row.get("base_currency")) or base_currency
        ),
        "total_account_nav": (
            _number_to_text(account_nav)
            if override_account_nav
            else _clean(row.get("total_account_nav"))
        ),
        "property_equity": _number_to_text(property_equity),
        "cpf_total": _number_to_text(cpf_total),
        "srs_total": _number_to_text(srs_total),
        "mortgage_liabilities": _number_to_text(mortgage_liabilities),
        "integrated_net_worth": _number_to_text(integrated_net_worth),
        "provider_count": _clean(row.get("provider_count")),
        "account_count": _clean(row.get("account_count")),
        "review_required": "yes" if WarningCode.DASHBOARD_V3_REVIEW_REQUIRED in warnings else "no",
        "warning_codes": _warning_text(warnings),
    }


def _balance_sheet_rows(
    *,
    base_currency: str,
    account_nav: float | None,
    property_equity: float | None,
    cpf_total: float | None,
    srs_total: float | None,
    mortgage_liabilities: float | None,
    integrated_net_worth: float | None,
    warnings: list[WarningCode],
) -> list[dict[str, str]]:
    rows = [
        ("account_nav", account_nav, "v0.3.3_merge_and_v0.4.2_snapshot"),
        ("property_equity", property_equity, "v0.4.3_property_mortgage"),
        ("cpf_retirement_assets", cpf_total, "v0.4.4_sg_manual_snapshot"),
        ("srs_retirement_assets", srs_total, "v0.4.4_sg_manual_snapshot"),
        ("mortgage_liabilities", mortgage_liabilities, "v0.4.3_property_mortgage"),
        ("integrated_net_worth", integrated_net_worth, "v0.5.0_dashboard_v3"),
    ]
    return [
        {
            "category": category,
            "amount": _number_to_text(amount),
            "currency": base_currency,
            "source_layer": source,
            "review_required": "yes" if WarningCode.DASHBOARD_V3_REVIEW_REQUIRED in warnings else "no",
            "warning_codes": _warning_text(warnings),
        }
        for category, amount, source in rows
    ]


def _breakdown_rows(
    *,
    account_rows: list[dict[str, str]],
    position_rows: list[dict[str, str]],
    property_summary: dict[str, Any],
    gross_mortgage_liabilities: float | None,
    unlinked_mortgage_liabilities: float | None,
    cpf_rows: list[dict[str, str]],
    srs_rows: list[dict[str, str]],
    tax_rows: list[dict[str, str]],
    hdb_rows: list[dict[str, str]],
    base_currency: str,
    fx_context: _FxContext | None,
    warnings: list[WarningCode],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    provider_totals: dict[tuple[str, str], float] = {}
    provider_missing_currency: set[tuple[str, str]] = set()
    for row in account_rows:
        provider = _clean(row.get("provider")) or "unknown"
        native_currency = _clean(row.get("base_currency"))
        currency = fx_context.base_currency if fx_context is not None else native_currency
        currency = currency or base_currency
        amount = _parse_number(row.get("account_nav")) or 0.0
        if fx_context is not None:
            rate = _lookup_rate_for_currency(native_currency, fx_context)
            if rate is None:
                provider_missing_currency.add((provider, fx_context.base_currency))
                continue
            amount *= rate
        key = (provider, currency)
        provider_totals[key] = provider_totals.get(key, 0.0) + amount
    for (provider, currency), amount in sorted(provider_totals.items()):
        rows.append(_breakdown_row("account_nav", "provider", provider, amount, currency, 1, warnings))
    for provider, currency in sorted(provider_missing_currency - set(provider_totals)):
        rows.append(_breakdown_row("account_nav", "provider", provider, None, currency, 1, warnings))
    rows.append(_breakdown_row("positions", "drilldown_count", "position_rows", None, base_currency, len(position_rows), warnings))
    for currency, amount in sorted((property_summary.get("total_equity_by_currency") or {}).items()):
        rows.append(_breakdown_row("property", "equity", "property_equity", _parse_number(amount), currency, _parse_int(property_summary.get("property_count")) or 0, warnings))
    if gross_mortgage_liabilities is not None:
        rows.append(_breakdown_row("mortgage", "linked_or_unlinked_liability", "gross_mortgage_liabilities", gross_mortgage_liabilities, base_currency, _parse_int(property_summary.get("mortgage_count")) or 0, warnings))
    if unlinked_mortgage_liabilities is not None:
        rows.append(_breakdown_row("mortgage", "extra_liability", "unlinked_mortgage_liabilities", unlinked_mortgage_liabilities, base_currency, _parse_int(property_summary.get("unlinked_mortgage_count")) or 0, warnings))
    if cpf_rows:
        rows.append(_breakdown_row("cpf", "retirement_assets", "cpf_total", _sum_field(cpf_rows, "total"), _first_currency(cpf_rows), len(cpf_rows), warnings))
    if srs_rows:
        rows.append(_breakdown_row("srs", "tax_wrapper_assets", "srs_total", _sum_field(srs_rows, "total"), _first_currency(srs_rows), len(srs_rows), warnings))
    if tax_rows:
        rows.append(_breakdown_row("tax", "review_only", "tax_records", None, base_currency, len(tax_rows), warnings))
    if hdb_rows:
        rows.append(_breakdown_row("hdb_loan", "availability_flags", "hdb_loan_records", None, _first_currency(hdb_rows), len(hdb_rows), warnings))
    return rows


def _breakdown_row(
    layer: str,
    item_type: str,
    item_label: str,
    amount: float | None,
    currency: str,
    row_count: int,
    warnings: list[WarningCode],
) -> dict[str, str]:
    return {
        "layer": layer,
        "item_type": item_type,
        "item_label": item_label,
        "amount": _number_to_text(amount),
        "currency": currency,
        "row_count": str(row_count),
        "review_required": "yes" if WarningCode.DASHBOARD_V3_REVIEW_REQUIRED in warnings else "no",
        "warning_codes": _warning_text(warnings),
    }


def _layer_status(
    *,
    dashboard_summary: dict[str, Any],
    property_summary: dict[str, Any],
    sg_summary: dict[str, Any],
    summary_counts: dict[str, int],
) -> list[dict[str, str]]:
    return [
        {
            "layer": "merged_account_nav",
            "status": "present" if summary_counts["account_count"] else "missing",
            "role": "primary",
            "row_summary": f"{summary_counts['account_count']} account rows; {summary_counts['provider_count']} providers",
        },
        {
            "layer": "snapshot_history",
            "status": "present" if summary_counts["net_worth_history_count"] else "missing",
            "role": "primary",
            "row_summary": f"{summary_counts['net_worth_history_count']} history rows",
        },
        {
            "layer": "dashboard_v2_summary",
            "status": "present" if dashboard_summary else "missing",
            "role": "supporting",
            "row_summary": f"{_parse_int(dashboard_summary.get('account_count')) or 0} account rows",
        },
        {
            "layer": "property_mortgage",
            "status": _manual_layer_status(property_summary, "property_count", "mortgage_count"),
            "role": "manual/fixture review layer",
            "row_summary": (
                f"{summary_counts['property_count']} property rows; "
                f"{summary_counts['mortgage_count']} mortgage rows"
            ),
        },
        {
            "layer": "sg_manual_snapshot",
            "status": _manual_layer_status(sg_summary, "cpf_count", "srs_count"),
            "role": "manual/fixture review layer",
            "row_summary": (
                f"{summary_counts['cpf_count']} CPF rows; {summary_counts['srs_count']} SRS rows; "
                f"{summary_counts['tax_count']} tax rows; {summary_counts['hdb_loan_count']} HDB loan rows"
            ),
        },
    ]


def _manual_layer_status(summary: dict[str, Any], *count_fields: str) -> str:
    if not summary:
        return "missing"
    if _clean(summary.get("review_required")) == "yes":
        return "review_required"
    for field in count_fields:
        if _parse_int(summary.get(field)):
            return "present"
    return "present"


def _summary_layer_status(summary: dict[str, Any]) -> list[dict[str, str]]:
    rows = summary.get("layer_status")
    return rows if isinstance(rows, list) else []


def _layer_status_text(summary: dict[str, Any], layer: str) -> str:
    for row in _summary_layer_status(summary):
        if row.get("layer") == layer:
            return _clean(row.get("status")) or "unknown"
    return "unknown"


def _provider_text(summary: dict[str, Any]) -> str:
    providers = summary.get("provider_names")
    if not isinstance(providers, list) or not providers:
        return "not available"
    return ", ".join(_clean(provider) for provider in providers if _clean(provider))


def _summary_text(summary: dict[str, Any], field: str) -> str:
    return _clean(summary.get(field)) or "not available"


def _markdown(
    *,
    summary: dict[str, Any],
    warnings: list[WarningCode],
    breakdown_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# Personal CFO Dashboard v0.5.0",
        "",
        DASHBOARD_V3_STATEMENT,
        "",
        "Dashboard v3 integrates offline account NAV, snapshot history, property and mortgage, and Singapore manual snapshot layers.",
        "Account NAV and snapshot history are the primary sources. Dashboard v2 summary is used as supporting context.",
        "Property, CPF, SRS, tax, and HDB layers are manual offline review layers.",
        "No external account connection, browser automation, market execution, filing, or action workflow is used.",
        "",
        "## CFO Cockpit",
        f"- Total net worth available: {summary['total_net_worth_available']}",
        f"- Liquid/investable assets available: {summary['liquid_investable_assets_available']}",
        f"- Property equity available: {summary['property_equity_available']}",
        f"- Retirement assets available: {summary['retirement_assets_available']}",
        f"- Liabilities available: {summary['liabilities_available']}",
        f"- Review required: {'yes' if WarningCode.DASHBOARD_V3_REVIEW_REQUIRED in warnings else 'no'}",
        f"- FX normalization applied: {summary['fx_normalization_applied']}",
        f"- FX base currency: {_summary_text(summary, 'fx_base_currency')}",
        "",
        "## Data Source Layer Status",
        *[
            f"- {row['layer']}: {row['status']} ({row['role']}; {row['row_summary']})"
            for row in _summary_layer_status(summary)
        ],
        "",
        "## Data Freshness",
        f"- Latest snapshot date: {_summary_text(summary, 'latest_snapshot_date')}",
        f"- Latest snapshot id available: {'yes' if _clean(summary.get('latest_snapshot_id')) else 'no'}",
        f"- Net worth history rows: {summary['net_worth_history_count']}",
        f"- Account NAV rows: {summary['account_count']}",
        f"- Provider rows: {summary['provider_count']}",
        "",
        "## Dashboard Sections",
        "- Total net worth",
        "- Liquid and investable assets if available",
        "- Property equity",
        "- CPF/SRS retirement assets",
        "- Liabilities",
        "- Net worth history",
        "- Account/provider NAV history",
        "- Balance sheet breakdown",
        "- Stale, missing, and review-required warnings",
        "- Position, property, CPF, and SRS drilldowns",
        "",
        "## Net Worth Progress",
        f"- History-first output rows: {summary['net_worth_history_count']}",
        "- The CSV output keeps the numeric progression in `net_worth_progress.csv`.",
        "- The static chart output is written to `net_worth_history_chart.svg`.",
        "- Latest integrated row combines account NAV with available manual layers.",
        "- Mixed-currency totals require explicit local FX rates before this section reports a numeric net worth.",
        "",
        "## Balance Sheet Breakdown",
        "- Primary account NAV remains separate from manual property, CPF, SRS, and liability layers.",
        "- Linked mortgage liability is shown as drilldown context and is not double-counted against property equity.",
        "- The CSV output keeps the structured balance sheet in `balance_sheet_summary.csv` and `asset_liability_breakdown.csv`.",
        "",
        "## Provider And Account NAV Summary",
        f"- Providers detected: {_provider_text(summary)}",
        f"- Dashboard v2 summary present: {'yes' if summary.get('dashboard_v2_summary_present') else 'no'}",
        f"- Dashboard v2 account count: {summary['dashboard_v2_account_count']}",
        f"- Dashboard v2 provider count: {summary['dashboard_v2_provider_count']}",
        f"- Dashboard v2 position count: {summary['dashboard_v2_position_count']}",
        "",
        "## Property And Mortgage Review",
        f"- Property rows: {summary['property_count']}",
        f"- Mortgage rows: {summary['mortgage_count']}",
        f"- Property/mortgage layer status: {_layer_status_text(summary, 'property_mortgage')}",
        "",
        "## Singapore Manual Snapshot Review",
        f"- CPF rows: {summary['cpf_count']}",
        f"- SRS rows: {summary['srs_count']}",
        f"- Tax rows: {summary['tax_count']}",
        f"- HDB loan rows: {summary['hdb_loan_count']}",
        f"- Singapore manual layer status: {_layer_status_text(summary, 'sg_manual_snapshot')}",
        "",
        "## Layer Drilldown Counts",
    ]
    for row in breakdown_rows:
        lines.append(
            f"- {row['layer']} / {row['item_type']}: {row['item_label']} "
            f"({row['row_count']} rows)"
        )
    lines.extend(
        [
            "",
            "## Warning Summary",
            f"- Warning count: {len(warnings)}",
            f"- Review required: {'yes' if WarningCode.DASHBOARD_V3_REVIEW_REQUIRED in warnings else 'no'}",
            "- Warning details are also written to `dashboard_v050_warnings.md`.",
            "",
            "## Warning Codes",
        ]
    )
    lines.extend(f"- {code.value}" for code in warnings)
    return "\n".join(lines) + "\n"


def _net_worth_history_chart_svg(rows: list[dict[str, str]]) -> str:
    points: list[tuple[str, float]] = []
    for row in rows:
        value = _parse_number(row.get("integrated_net_worth"))
        if value is None:
            value = _parse_number(row.get("total_account_nav"))
        if value is None:
            continue
        label = _clean(row.get("snapshot_date")) or _clean(row.get("snapshot_id")) or "snapshot"
        points.append((label, value))
    width = 860
    height = 320
    left = 68
    right = 28
    top = 28
    bottom = 54
    plot_width = width - left - right
    plot_height = height - top - bottom
    if not points:
        return (
            f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" "
            f"viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Net worth history chart\">"
            "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>"
            "<text x=\"32\" y=\"48\" font-family=\"Segoe UI, Arial\" font-size=\"18\" fill=\"#17202a\">"
            "Net worth history unavailable</text></svg>\n"
        )
    values = [value for _, value in points]
    low = min(values)
    high = max(values)
    if low == high:
        low -= 1.0
        high += 1.0
    span = high - low

    def x_at(index: int) -> float:
        if len(points) == 1:
            return left + plot_width / 2
        return left + (plot_width * index / (len(points) - 1))

    def y_at(value: float) -> float:
        return top + plot_height - ((value - low) / span * plot_height)

    polyline = " ".join(
        f"{x_at(index):.1f},{y_at(value):.1f}" for index, (_, value) in enumerate(points)
    )
    circles = "\n".join(
        f"<circle cx=\"{x_at(index):.1f}\" cy=\"{y_at(value):.1f}\" r=\"4\" fill=\"#0f766e\"/>"
        for index, (_, value) in enumerate(points)
    )
    labels = _chart_labels(points, x_at, height)
    return (
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" "
        f"viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Net worth history chart\">"
        "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>"
        "<text x=\"32\" y=\"30\" font-family=\"Segoe UI, Arial\" font-size=\"18\" "
        "font-weight=\"700\" fill=\"#17202a\">Net Worth History</text>"
        f"<line x1=\"{left}\" y1=\"{top}\" x2=\"{left}\" y2=\"{height - bottom}\" stroke=\"#d7dce0\"/>"
        f"<line x1=\"{left}\" y1=\"{height - bottom}\" x2=\"{width - right}\" "
        f"y2=\"{height - bottom}\" stroke=\"#d7dce0\"/>"
        f"<polyline points=\"{polyline}\" fill=\"none\" stroke=\"#0f766e\" stroke-width=\"3\"/>"
        f"{circles}{labels}"
        "</svg>\n"
    )


def _chart_labels(
    points: list[tuple[str, float]], x_at, height: int
) -> str:
    if not points:
        return ""
    selected_indexes = {0, len(points) - 1}
    if len(points) > 2:
        selected_indexes.add(len(points) // 2)
    labels: list[str] = []
    for index in sorted(selected_indexes):
        label = html.escape(points[index][0])
        labels.append(
            f"<text x=\"{x_at(index):.1f}\" y=\"{height - 18}\" text-anchor=\"middle\" "
            "font-family=\"Segoe UI, Arial\" font-size=\"12\" fill=\"#5c6670\">"
            f"{label}</text>"
        )
    return "".join(labels)


def _html(markdown: str, *, chart_svg: str = "") -> str:
    lines = markdown.splitlines()
    body: list[str] = []
    for line in lines:
        escaped = html.escape(line)
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            body.append(f"<p>{escaped}</p>")
        elif line:
            body.append(f"<p>{escaped}</p>")
    if chart_svg:
        body.append("<section class=\"chart\"><h2>Net Worth History Chart</h2>")
        body.append(chart_svg)
        body.append("</section>")
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        "<title>Personal CFO Dashboard v0.5.0</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;line-height:1.5;margin:0;background:#f7f7f5;color:#1f2933;}"
        "main{max-width:1040px;margin:0 auto;padding:32px 24px 56px;}"
        "h1{font-size:32px;margin:0 0 16px;}h2{font-size:21px;margin:28px 0 10px;border-top:1px solid #d9ded8;padding-top:18px;}"
        "p{margin:7px 0;}p:nth-child(n+2){max-width:920px;}"
        ".chart svg{max-width:100%;height:auto;border:1px solid #d9ded8;background:#fff;}"
        "</style></head><body><main>\n"
        + "\n".join(body)
        + "\n</main></body></html>\n"
    )


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = [
        "# Dashboard v3 Warnings",
        "",
        DASHBOARD_V3_STATEMENT,
        "",
        "## Warning Summary",
        f"- Warning count: {len(warnings)}",
        f"- Review required: {'yes' if WarningCode.DASHBOARD_V3_REVIEW_REQUIRED in warnings else 'no'}",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _input_warning_values(*groups: list[dict[str, str]], text: str = "") -> set[str]:
    values: set[str] = set()
    for rows in groups:
        for row in rows:
            for field in ("warning_codes", "normalization_warnings", "merge_warnings"):
                values.update(code for code in _clean(row.get(field)).replace(",", ";").split(";") if code)
    values.update(_warning_codes_from_text(text))
    return values


def _review_required(
    warning_values: set[str],
    property_summary: dict[str, Any],
    sg_summary: dict[str, Any],
) -> bool:
    if warning_values:
        return True
    if _clean(property_summary.get("review_required")) == "yes":
        return True
    if _clean(sg_summary.get("review_required")) == "yes":
        return True
    return False


def _load_fx_context(path: Path | None, warnings: list[WarningCode]) -> _FxContext | None:
    if path is None:
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        warnings.append(WarningCode.DASHBOARD_V3_FX_RATE_MISSING)
        return None
    base_currency = _clean(payload.get("base_currency"))
    raw_rates = payload.get("rates_to_base") or payload.get("rates")
    if not base_currency or not isinstance(raw_rates, dict):
        warnings.append(WarningCode.DASHBOARD_V3_FX_RATE_MISSING)
        return None
    rates: dict[str, float] = {}
    for currency, value in raw_rates.items():
        currency_code = _clean(currency)
        rate = _parse_number(value)
        if not currency_code or rate is None or rate <= 0:
            warnings.append(WarningCode.DASHBOARD_V3_FX_RATE_MISSING)
            return None
        rates[currency_code] = rate
    rates.setdefault(base_currency, 1.0)
    return _FxContext(base_currency=base_currency, rates_to_base=rates)


def _fx_required_for_top_level(
    *,
    account_rows: list[dict[str, str]],
    property_summary: dict[str, Any],
    cpf_rows: list[dict[str, str]],
    srs_rows: list[dict[str, str]],
    base_currency: str,
) -> bool:
    currencies: list[str] = []
    missing = False
    for row in account_rows:
        if _parse_number(row.get("account_nav")) is None:
            continue
        currency = _clean(row.get("base_currency"))
        if not currency:
            missing = True
        else:
            currencies.append(currency)
    for mapping_name in ("total_equity_by_currency", "unlinked_liability_total_by_currency"):
        value = property_summary.get(mapping_name)
        if isinstance(value, dict):
            for currency, amount in value.items():
                if _parse_number(amount) is not None:
                    currency_code = _clean(currency)
                    if currency_code:
                        currencies.append(currency_code)
                    else:
                        missing = True
    for rows in (cpf_rows, srs_rows):
        for row in rows:
            if _parse_number(row.get("total")) is None:
                continue
            currency = _clean(row.get("currency"))
            if not currency:
                missing = True
            else:
                currencies.append(currency)
    unique = {currency for currency in currencies if currency}
    if missing:
        return True
    if len(unique) > 1:
        return True
    if unique and base_currency and next(iter(unique)) != base_currency:
        return True
    return False


def _sum_mortgage_ledger(
    path: Path | None,
    *,
    fx_context: _FxContext | None = None,
    warnings: list[WarningCode] | None = None,
) -> float | None:
    if path is None:
        return None
    ledger = path / "mortgage_liability_ledger.csv"
    if not ledger.exists():
        return None
    rows = _read_csv(ledger)
    if fx_context is not None:
        return _sum_rows_converted(
            rows, "outstanding_balance", "currency", fx_context, warnings or []
        )
    return _sum_field(rows, "outstanding_balance")


def _sum_mapping(value: object) -> float | None:
    if not isinstance(value, dict):
        return None
    total = 0.0
    found = False
    for amount in value.values():
        parsed = _parse_number(amount)
        if parsed is None:
            continue
        total += parsed
        found = True
    return total if found else None


def _sum_mapping_converted(
    value: object,
    fx_context: _FxContext,
    warnings: list[WarningCode],
) -> float | None:
    if not isinstance(value, dict):
        return None
    total = 0.0
    found = False
    missing_rate = False
    for currency, amount in value.items():
        parsed = _parse_number(amount)
        if parsed is None:
            continue
        rate = _rate_for_currency(_clean(currency), fx_context, warnings)
        if rate is None:
            missing_rate = True
            continue
        total += parsed * rate
        found = True
    if missing_rate:
        return None
    return total if found else None


def _sum_rows_converted(
    rows: list[dict[str, str]],
    value_field: str,
    currency_field: str,
    fx_context: _FxContext,
    warnings: list[WarningCode],
) -> float | None:
    total = 0.0
    found = False
    missing_rate = False
    for row in rows:
        parsed = _parse_number(row.get(value_field))
        if parsed is None:
            continue
        rate = _rate_for_currency(_clean(row.get(currency_field)), fx_context, warnings)
        if rate is None:
            missing_rate = True
            continue
        total += parsed * rate
        found = True
    if missing_rate:
        return None
    return total if found else None


def _rate_for_currency(
    currency: str,
    fx_context: _FxContext,
    warnings: list[WarningCode],
) -> float | None:
    rate = _lookup_rate_for_currency(currency, fx_context)
    if rate is None:
        warnings.append(WarningCode.DASHBOARD_V3_FX_RATE_MISSING)
    return rate


def _lookup_rate_for_currency(currency: str, fx_context: _FxContext) -> float | None:
    currency = _clean(currency)
    if not currency:
        return None
    return fx_context.rates_to_base.get(currency)


def _sum_field(rows: list[dict[str, str]], field: str) -> float | None:
    total = 0.0
    found = False
    for row in rows:
        parsed = _parse_number(row.get(field))
        if parsed is None:
            continue
        total += parsed
        found = True
    return total if found else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return _read_csv(path)


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


def _warning_codes_from_text(text: str) -> set[str]:
    known_codes = {code.value for code in WarningCode}
    tokens = {
        token.strip("`-:,.()[]{} ")
        for line in text.splitlines()
        for token in line.split()
    }
    return {token for token in tokens if token in known_codes}


def _first_currency(*groups: list[dict[str, str]]) -> str:
    for rows in groups:
        for row in rows:
            currency = _clean(row.get("currency") or row.get("base_currency"))
            if currency:
                return currency
    return ""


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
        return next(iter(currencies))
    return ""


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


def _warning_text(warnings: list[WarningCode]) -> str:
    return ";".join(code.value for code in warnings)


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
