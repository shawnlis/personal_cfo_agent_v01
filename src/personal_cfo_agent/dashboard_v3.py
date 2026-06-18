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


def write_dashboard_v3(
    *,
    merge_dir: Path,
    snapshot_dir: Path,
    out_dir: Path,
    dashboard_dir: Path | None = None,
    property_mortgage_dir: Path | None = None,
    sg_snapshot_dir: Path | None = None,
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

    property_equity = _sum_mapping(property_summary.get("total_equity_by_currency"))
    gross_mortgage_liabilities = _sum_mortgage_ledger(property_mortgage_dir)
    unlinked_mortgage_liabilities = _sum_mapping(
        property_summary.get("unlinked_liability_total_by_currency")
    )
    cpf_rows = _read_optional_csv(sg_snapshot_dir / "cpf_snapshot_ledger.csv") if sg_snapshot_dir else []
    srs_rows = _read_optional_csv(sg_snapshot_dir / "srs_snapshot_ledger.csv") if sg_snapshot_dir else []
    tax_rows = _read_optional_csv(sg_snapshot_dir / "tax_snapshot_ledger.csv") if sg_snapshot_dir else []
    hdb_rows = _read_optional_csv(sg_snapshot_dir / "hdb_loan_snapshot_ledger.csv") if sg_snapshot_dir else []
    cpf_total = _sum_field(cpf_rows, "total")
    srs_total = _sum_field(srs_rows, "total")
    account_nav = _parse_number(latest_snapshot.get("total_account_nav"))
    integrated_net_worth = (
        (account_nav or 0.0)
        + (property_equity or 0.0)
        + (cpf_total or 0.0)
        + (srs_total or 0.0)
        - abs(unlinked_mortgage_liabilities or 0.0)
    )
    base_currency = _clean(latest_snapshot.get("base_currency")) or _first_currency(
        account_rows, cpf_rows, srs_rows
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
            property_equity=property_equity,
            cpf_total=cpf_total,
            srs_total=srs_total,
            mortgage_liabilities=unlinked_mortgage_liabilities,
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
        mortgage_liabilities=unlinked_mortgage_liabilities,
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
        "warning_codes": [code.value for code in warnings],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown_report": out_dir / "PERSONAL_CFO_DASHBOARD_V050.md",
        "html_report": out_dir / "PERSONAL_CFO_DASHBOARD_V050.html",
        "dashboard_summary": out_dir / "dashboard_v050_summary.json",
        "net_worth_progress": out_dir / "net_worth_progress.csv",
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
    paths["markdown_report"].write_text(markdown, encoding="utf-8")
    paths["html_report"].write_text(_html(markdown), encoding="utf-8")
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
        "base_currency": _clean(row.get("base_currency")) or base_currency,
        "total_account_nav": _clean(row.get("total_account_nav")),
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
    warnings: list[WarningCode],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    provider_totals: dict[str, float] = {}
    for row in account_rows:
        provider = _clean(row.get("provider")) or "unknown"
        provider_totals[provider] = provider_totals.get(provider, 0.0) + (
            _parse_number(row.get("account_nav")) or 0.0
        )
    for provider, amount in sorted(provider_totals.items()):
        rows.append(_breakdown_row("account_nav", "provider", provider, amount, base_currency, 1, warnings))
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
        "## Summary",
        f"- Account count: {summary['account_count']}",
        f"- Provider count: {summary['provider_count']}",
        f"- Position rows: {summary['position_count']}",
        f"- Net worth history rows: {summary['net_worth_history_count']}",
        f"- Property rows: {summary['property_count']}",
        f"- Mortgage rows: {summary['mortgage_count']}",
        f"- CPF rows: {summary['cpf_count']}",
        f"- SRS rows: {summary['srs_count']}",
        f"- Tax rows: {summary['tax_count']}",
        f"- HDB loan rows: {summary['hdb_loan_count']}",
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
        "## Layer Breakdown",
    ]
    for row in breakdown_rows:
        lines.append(
            f"- {row['layer']} / {row['item_type']}: {row['item_label']} "
            f"({row['row_count']} rows)"
        )
    lines.extend(["", "## Warning Codes"])
    lines.extend(f"- {code.value}" for code in warnings)
    return "\n".join(lines) + "\n"


def _html(markdown: str) -> str:
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
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        "<title>Personal CFO Dashboard v0.5.0</title></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = ["# Dashboard v3 Warnings", "", DASHBOARD_V3_STATEMENT, "", "## Warning Codes"]
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


def _sum_mortgage_ledger(path: Path | None) -> float | None:
    if path is None:
        return None
    ledger = path / "mortgage_liability_ledger.csv"
    if not ledger.exists():
        return None
    return _sum_field(_read_csv(ledger), "outstanding_balance")


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
