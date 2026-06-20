"""Offline Dashboard v4 asset bucket visualization."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.6.0"

ASSET_BUCKET_FIELDNAMES = [
    "bucket",
    "bucket_label",
    "amount",
    "currency",
    "percentage",
    "native_totals",
    "source_layer",
    "review_required",
    "warning_codes",
]

LIQUID_WITHDRAWAL_FIELDNAMES = [
    "withdrawal_rate",
    "currency",
    "annual",
    "monthly",
    "daily",
    "source_bucket",
    "fx_mode",
    "warning_codes",
]

BUCKET_HISTORY_FIELDNAMES = [
    "snapshot_date",
    "snapshot_id",
    "currency",
    "fixed_assets",
    "retirement_accounts",
    "liquid_investment_assets",
    "unclassified",
    "total_net_worth",
    "warning_codes",
]

BUCKET_LABELS = {
    "fixed_assets": "固定资产 / Fixed assets",
    "retirement_accounts": "退休账户 / Retirement accounts",
    "liquid_investment_assets": "流动投资资产 / Liquid investment assets",
    "unclassified": "Needs review / unclassified",
}

WITHDRAWAL_RATES = (0.03, 0.035, 0.04)
WITHDRAWAL_CURRENCIES = ("USD", "SGD", "CNY")


@dataclass(frozen=True)
class DashboardV4Result:
    refresh_dir: Path
    output_dir: Path | None
    fx_rates_file: Path | None = None
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False
    bucket_count: int = 0
    history_count: int = 0
    withdrawal_row_count: int = 0


@dataclass(frozen=True)
class _FxContext:
    base_currency: str
    rates_to_base: dict[str, float]


@dataclass(frozen=True)
class _MoneyItem:
    bucket: str
    amount: float | None
    currency: str
    source_layer: str
    warning_codes: tuple[WarningCode, ...] = ()


def write_dashboard_v4(
    *,
    refresh_dir: Path,
    fx_rates_file: Path | None,
    out_dir: Path,
) -> DashboardV4Result:
    """Write Dashboard v4 from a local v0.5.9 refresh directory."""

    warnings: list[WarningCode] = []
    paths = _refresh_paths(refresh_dir)
    required_paths = [
        paths["merged_account_nav"],
        paths["net_worth_history"],
    ]
    if not refresh_dir.exists() or any(not path.exists() for path in required_paths):
        return DashboardV4Result(
            refresh_dir=refresh_dir,
            output_dir=None,
            fx_rates_file=fx_rates_file,
            warning_codes=[WarningCode.DASHBOARD_V4_INPUT_MISSING],
        )

    account_rows = _read_csv(paths["merged_account_nav"])
    net_worth_rows = _read_csv(paths["net_worth_history"])
    progress_rows = (
        _read_csv(paths["net_worth_progress"]) if paths["net_worth_progress"].exists() else []
    )
    property_summary = _read_json(paths["property_summary"]) or {}
    cpf_rows = _read_optional_csv(paths["cpf_ledger"])
    srs_rows = _read_optional_csv(paths["srs_ledger"])

    if not account_rows or not net_worth_rows:
        return DashboardV4Result(
            refresh_dir=refresh_dir,
            output_dir=None,
            fx_rates_file=fx_rates_file,
            warning_codes=[WarningCode.DASHBOARD_V4_INPUT_MISSING],
        )

    fx_context = _load_fx_context(fx_rates_file, warnings)
    items = _money_items(account_rows, property_summary, cpf_rows, srs_rows, warnings)
    if any(item.bucket == "unclassified" for item in items):
        warnings.append(WarningCode.DASHBOARD_V4_UNCLASSIFIED_ASSETS)
    if any(item.warning_codes for item in items):
        warnings.append(WarningCode.DASHBOARD_V4_BUCKET_CLASSIFICATION_WARNING)

    bucket_rows, bucket_amounts, base_currency = _bucket_rows(items, fx_context, warnings)
    history_rows = _history_rows(
        progress_rows or net_worth_rows,
        fx_context=fx_context,
        fallback_base_currency=base_currency,
        warnings=warnings,
    )
    if len(history_rows) < 2:
        warnings.append(WarningCode.DASHBOARD_V4_BUCKET_HISTORY_LIMITED)
    withdrawal_rows = _withdrawal_rows(
        bucket_amounts.get("liquid_investment_assets"),
        base_currency=base_currency,
        fx_context=fx_context,
        warnings=warnings,
    )
    warnings.append(WarningCode.DASHBOARD_V4_WITHDRAWAL_CASHFLOW_GENERATED)
    warnings = _dedupe_warning_codes(warnings)
    completion = (
        WarningCode.DASHBOARD_V4_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.DASHBOARD_V4_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])
    for row in bucket_rows:
        if row["warning_codes"]:
            continue
        row["warning_codes"] = _warning_text(warnings)
    for row in withdrawal_rows:
        if row["warning_codes"]:
            continue
        row["warning_codes"] = _warning_text(warnings)
    for row in history_rows:
        if row["warning_codes"]:
            continue
        row["warning_codes"] = _warning_text(warnings)

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "markdown_report": out_dir / "PERSONAL_CFO_DASHBOARD_V060.md",
        "html_report": out_dir / "PERSONAL_CFO_DASHBOARD_V060.html",
        "dashboard_summary": out_dir / "dashboard_v060_summary.json",
        "asset_bucket_summary": out_dir / "asset_bucket_summary.csv",
        "liquid_withdrawal_cashflow": out_dir / "liquid_withdrawal_cashflow.csv",
        "net_worth_bucket_history": out_dir / "net_worth_bucket_history.csv",
        "dashboard_warnings": out_dir / "dashboard_v060_warnings.md",
        "asset_bucket_chart": out_dir / "asset_bucket_chart.svg",
        "withdrawal_cashflow_chart": out_dir / "withdrawal_cashflow_chart.svg",
        "net_worth_bucket_history_chart": out_dir / "net_worth_bucket_history_chart.svg",
    }
    summary = _summary(
        refresh_dir=refresh_dir,
        fx_rates_file=fx_rates_file,
        base_currency=base_currency,
        bucket_rows=bucket_rows,
        history_rows=history_rows,
        withdrawal_rows=withdrawal_rows,
        warnings=warnings,
    )
    _write_csv(output_paths["asset_bucket_summary"], ASSET_BUCKET_FIELDNAMES, bucket_rows)
    _write_csv(
        output_paths["liquid_withdrawal_cashflow"],
        LIQUID_WITHDRAWAL_FIELDNAMES,
        withdrawal_rows,
    )
    _write_csv(
        output_paths["net_worth_bucket_history"],
        BUCKET_HISTORY_FIELDNAMES,
        history_rows,
    )
    output_paths["dashboard_summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    asset_svg = _asset_bucket_chart_svg(bucket_rows)
    cashflow_svg = _withdrawal_cashflow_chart_svg(withdrawal_rows, base_currency)
    history_svg = _bucket_history_chart_svg(history_rows)
    output_paths["asset_bucket_chart"].write_text(asset_svg, encoding="utf-8")
    output_paths["withdrawal_cashflow_chart"].write_text(cashflow_svg, encoding="utf-8")
    output_paths["net_worth_bucket_history_chart"].write_text(history_svg, encoding="utf-8")
    markdown = _markdown(summary, bucket_rows, withdrawal_rows, history_rows)
    output_paths["markdown_report"].write_text(markdown, encoding="utf-8")
    output_paths["html_report"].write_text(
        _html(markdown, asset_svg, cashflow_svg, history_svg), encoding="utf-8"
    )
    _write_warnings(output_paths["dashboard_warnings"], warnings)

    return DashboardV4Result(
        refresh_dir=refresh_dir,
        output_dir=out_dir,
        fx_rates_file=fx_rates_file,
        output_paths=output_paths,
        warning_codes=warnings,
        generated=True,
        bucket_count=len(bucket_rows),
        history_count=len(history_rows),
        withdrawal_row_count=len(withdrawal_rows),
    )


def _refresh_paths(refresh_dir: Path) -> dict[str, Path]:
    manual_dir = refresh_dir / "manual_layers"
    return {
        "merged_account_nav": refresh_dir / "merged" / "merged_account_nav_ledger.csv",
        "net_worth_history": refresh_dir / "snapshots" / "net_worth_history.csv",
        "net_worth_progress": refresh_dir / "dashboard" / "net_worth_progress.csv",
        "property_summary": manual_dir / "property_mortgage" / "property_equity_summary.json",
        "cpf_ledger": manual_dir / "sg_retirement_tax" / "cpf_snapshot_ledger.csv",
        "srs_ledger": manual_dir / "sg_retirement_tax" / "srs_snapshot_ledger.csv",
    }


def _money_items(
    account_rows: list[dict[str, str]],
    property_summary: dict[str, Any],
    cpf_rows: list[dict[str, str]],
    srs_rows: list[dict[str, str]],
    warnings: list[WarningCode],
) -> list[_MoneyItem]:
    items: list[_MoneyItem] = []
    for row in account_rows:
        amount = _parse_number(row.get("account_nav"))
        currency = _clean(row.get("base_currency"))
        item_warnings: list[WarningCode] = []
        if amount is None or not currency:
            item_warnings.append(WarningCode.DASHBOARD_V4_BUCKET_CLASSIFICATION_WARNING)
        items.append(
            _MoneyItem(
                bucket="liquid_investment_assets" if not item_warnings else "unclassified",
                amount=amount,
                currency=currency,
                source_layer="merged_account_nav",
                warning_codes=tuple(item_warnings),
            )
        )
    for currency, amount in _mapping_amounts(property_summary.get("total_equity_by_currency")):
        items.append(
            _MoneyItem(
                bucket="fixed_assets",
                amount=amount,
                currency=currency,
                source_layer="property_mortgage",
            )
        )
    for row in cpf_rows:
        items.append(
            _MoneyItem(
                bucket="retirement_accounts",
                amount=_parse_number(row.get("total")),
                currency=_clean(row.get("currency")),
                source_layer="cpf",
            )
        )
    for row in srs_rows:
        items.append(
            _MoneyItem(
                bucket="retirement_accounts",
                amount=_parse_number(row.get("total")),
                currency=_clean(row.get("currency")),
                source_layer="srs",
            )
        )
    for item in items:
        warnings.extend(item.warning_codes)
    return items


def _bucket_rows(
    items: list[_MoneyItem],
    fx_context: _FxContext | None,
    warnings: list[WarningCode],
) -> tuple[list[dict[str, str]], dict[str, float | None], str]:
    buckets = ("fixed_assets", "retirement_accounts", "liquid_investment_assets", "unclassified")
    base_currency = _base_currency(items, fx_context)
    bucket_amounts: dict[str, float | None] = {}
    native_totals_by_bucket: dict[str, dict[str, float]] = {}
    bucket_item_counts: dict[str, int] = {}
    for bucket in buckets:
        bucket_items = [item for item in items if item.bucket == bucket]
        bucket_item_counts[bucket] = len(bucket_items)
        native_totals = _native_totals(bucket_items)
        native_totals_by_bucket[bucket] = native_totals
        bucket_amounts[bucket] = _aggregate_amount(bucket_items, fx_context, warnings)
    total = sum(
        amount
        for bucket, amount in bucket_amounts.items()
        if bucket != "unclassified" and amount is not None
    )
    if any(amount is None for bucket, amount in bucket_amounts.items() if bucket != "unclassified"):
        total = 0.0
    rows: list[dict[str, str]] = []
    for bucket in buckets:
        amount = bucket_amounts[bucket]
        native_totals = native_totals_by_bucket[bucket]
        row_currency = base_currency if amount is not None else _native_currency_text(native_totals)
        percentage = ""
        if amount is not None and total:
            percentage = f"{amount / total * 100:.2f}"
        rows.append(
            {
                "bucket": bucket,
                "bucket_label": BUCKET_LABELS[bucket],
                "amount": _number_to_text(amount),
                "currency": row_currency,
                "percentage": percentage,
                "native_totals": _native_totals_text(native_totals),
                "source_layer": _bucket_source_layer(bucket),
                "review_required": "yes" if bucket == "unclassified" and bucket_item_counts[bucket] else "no",
                "warning_codes": "",
            }
        )
    return rows, bucket_amounts, base_currency


def _aggregate_amount(
    items: list[_MoneyItem],
    fx_context: _FxContext | None,
    warnings: list[WarningCode],
) -> float | None:
    valid = [item for item in items if item.amount is not None and item.currency]
    if not valid:
        return 0.0
    currencies = {item.currency for item in valid}
    if fx_context is None:
        if len(currencies) == 1:
            return sum(item.amount or 0.0 for item in valid)
        warnings.extend(
            [
                WarningCode.DASHBOARD_V4_FX_RATES_MISSING,
                WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED,
            ]
        )
        return None
    total = 0.0
    for item in valid:
        rate = fx_context.rates_to_base.get(item.currency)
        if rate is None:
            warnings.extend(
                [
                    WarningCode.DASHBOARD_V4_FX_RATES_MISSING,
                    WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED,
                ]
            )
            return None
        total += (item.amount or 0.0) * rate
    return total


def _history_rows(
    source_rows: list[dict[str, str]],
    *,
    fx_context: _FxContext | None,
    fallback_base_currency: str,
    warnings: list[WarningCode],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in source_rows:
        currency = _clean(row.get("base_currency")) or fallback_base_currency
        liquid = _parse_number(row.get("total_account_nav"))
        fixed = _parse_number(row.get("property_equity"))
        cpf = _parse_number(row.get("cpf_total"))
        srs = _parse_number(row.get("srs_total"))
        retirement = None if cpf is None and srs is None else (cpf or 0.0) + (srs or 0.0)
        unclassified = 0.0
        if fx_context is not None and currency and currency != fx_context.base_currency:
            rate = fx_context.rates_to_base.get(currency)
            if rate is None:
                warnings.extend(
                    [
                        WarningCode.DASHBOARD_V4_FX_RATES_MISSING,
                        WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED,
                    ]
                )
                liquid = fixed = retirement = None
            else:
                liquid = _mul_optional(liquid, rate)
                fixed = _mul_optional(fixed, rate)
                retirement = _mul_optional(retirement, rate)
                currency = fx_context.base_currency
        total = sum(value for value in (liquid, fixed, retirement, unclassified) if value is not None)
        rows.append(
            {
                "snapshot_date": _clean(row.get("snapshot_date")),
                "snapshot_id": _clean(row.get("snapshot_id")),
                "currency": currency,
                "fixed_assets": _number_to_text(fixed),
                "retirement_accounts": _number_to_text(retirement),
                "liquid_investment_assets": _number_to_text(liquid),
                "unclassified": _number_to_text(unclassified),
                "total_net_worth": _number_to_text(total),
                "warning_codes": "",
            }
        )
    return rows


def _withdrawal_rows(
    liquid_amount: float | None,
    *,
    base_currency: str,
    fx_context: _FxContext | None,
    warnings: list[WarningCode],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if liquid_amount is None:
        warnings.extend(
            [
                WarningCode.DASHBOARD_V4_FX_RATES_MISSING,
                WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED,
            ]
        )
        return rows
    currencies = WITHDRAWAL_CURRENCIES if fx_context is not None else (base_currency,)
    for rate in WITHDRAWAL_RATES:
        annual_base = liquid_amount * rate
        for currency in currencies:
            amount = annual_base
            fx_mode = "native"
            if fx_context is not None:
                fx_rate = fx_context.rates_to_base.get(currency)
                if fx_rate is None:
                    warnings.extend(
                        [
                            WarningCode.DASHBOARD_V4_FX_RATES_MISSING,
                            WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED,
                        ]
                    )
                    continue
                amount = annual_base / fx_rate
                fx_mode = f"{fx_context.base_currency}_to_{currency}"
            rows.append(
                {
                    "withdrawal_rate": f"{rate:.3f}",
                    "currency": currency,
                    "annual": _number_to_text(amount),
                    "monthly": _number_to_text(amount / 12.0),
                    "daily": _number_to_text(amount / 365.0),
                    "source_bucket": "liquid_investment_assets",
                    "fx_mode": fx_mode,
                    "warning_codes": "",
                }
            )
    return rows


def _summary(
    *,
    refresh_dir: Path,
    fx_rates_file: Path | None,
    base_currency: str,
    bucket_rows: list[dict[str, str]],
    history_rows: list[dict[str, str]],
    withdrawal_rows: list[dict[str, str]],
    warnings: list[WarningCode],
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "offline_only": True,
        "external_connections": "not_used",
        "broker_connections": "not_used",
        "refresh_dir": str(refresh_dir),
        "input_contract": "v0.5.9_refresh_dir",
        "fx_rates_file": str(fx_rates_file) if fx_rates_file else "",
        "base_currency": base_currency,
        "asset_bucket_count": len(bucket_rows),
        "history_row_count": len(history_rows),
        "withdrawal_cashflow_row_count": len(withdrawal_rows),
        "warning_codes": [code.value for code in warnings],
        "bucket_labels": BUCKET_LABELS,
    }


def _markdown(
    summary: dict[str, Any],
    bucket_rows: list[dict[str, str]],
    withdrawal_rows: list[dict[str, str]],
    history_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# Personal CFO Dashboard v4 v0.6.0",
        "",
        "Offline visual dashboard for local review. No external connection is used.",
        "",
        "## CFO Cockpit",
        f"- Base currency: {summary['base_currency']}",
        f"- Asset buckets: {summary['asset_bucket_count']}",
        f"- History rows: {summary['history_row_count']}",
        f"- Withdrawal ladder rows: {summary['withdrawal_cashflow_row_count']}",
        "",
        "## Asset Buckets",
    ]
    for row in bucket_rows:
        amount = row["amount"] or row["native_totals"] or "review required"
        percentage = f"{row['percentage']}%" if row["percentage"] else "n/a"
        lines.append(
            f"- {row['bucket_label']}: {amount} {row['currency']} ({percentage})"
        )
    lines.extend(
        [
            "",
            "## Liquid Withdrawal Cashflow",
            "- Uses liquid investment assets only.",
            "- Uses explicit local FX rates when multiple display currencies are shown.",
        ]
    )
    for row in withdrawal_rows:
        rate_text = f"{float(row['withdrawal_rate']) * 100:.1f}%"
        lines.append(
            f"- {rate_text} / {row['currency']}: annual {row['annual']}, monthly {row['monthly']}, daily {row['daily']}"
        )
    lines.extend(
        [
            "",
            "## Bucketed Net Worth History",
            f"- Rows: {len(history_rows)}",
            "- Static SVG output: `net_worth_bucket_history_chart.svg`",
            "",
            "## Review Queue",
            "- Unclassified or missing-currency assets are retained for review.",
            "- Missing FX rates skip conversion instead of mixing currencies.",
            "",
            "## Output Files",
            "- `asset_bucket_summary.csv`",
            "- `liquid_withdrawal_cashflow.csv`",
            "- `net_worth_bucket_history.csv`",
            "- `asset_bucket_chart.svg`",
            "- `withdrawal_cashflow_chart.svg`",
            "- `net_worth_bucket_history_chart.svg`",
            "",
            "## Warning Codes",
        ]
    )
    lines.extend(f"- {code}" for code in summary["warning_codes"])
    return "\n".join(lines) + "\n"


def _html(markdown: str, asset_svg: str, cashflow_svg: str, history_svg: str) -> str:
    sections: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            sections.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            sections.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            sections.append(f"<p class=\"bullet\">{html.escape(line[2:])}</p>")
        elif line:
            sections.append(f"<p>{html.escape(line)}</p>")
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        "<title>Personal CFO Dashboard v4</title>"
        "<style>"
        ":root{--ink:#16202a;--muted:#617080;--line:#d8dedb;--paper:#fbfaf7;--panel:#ffffff;--accent:#0f766e;--gold:#9a6a2f;--blue:#315f8c;}"
        "body{margin:0;background:var(--paper);color:var(--ink);font-family:Segoe UI,Arial,sans-serif;}"
        "main{max-width:1180px;margin:0 auto;padding:42px 28px 68px;}"
        "h1{font-size:34px;letter-spacing:0;margin:0 0 18px;}"
        "h2{font-size:20px;margin:30px 0 12px;padding-top:18px;border-top:1px solid var(--line);}"
        "p{color:var(--muted);line-height:1.5;margin:7px 0;}.bullet{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;color:var(--ink);}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:20px;}"
        ".card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;box-shadow:0 12px 28px rgba(22,32,42,.06);}"
        "svg{max-width:100%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px;}"
        "</style></head><body><main>"
        + "\n".join(sections)
        + "<div class=\"grid\"><section class=\"card\">"
        + asset_svg
        + "</section><section class=\"card\">"
        + cashflow_svg
        + "</section><section class=\"card\">"
        + history_svg
        + "</section></div></main></body></html>\n"
    )


def _asset_bucket_chart_svg(rows: list[dict[str, str]]) -> str:
    width, height = 760, 300
    chart_rows = [row for row in rows if _parse_number(row.get("amount")) is not None]
    max_value = max((_parse_number(row.get("amount")) or 0.0 for row in chart_rows), default=1.0)
    bars: list[str] = []
    colors = {
        "fixed_assets": "#9a6a2f",
        "retirement_accounts": "#315f8c",
        "liquid_investment_assets": "#0f766e",
        "unclassified": "#8a8f98",
    }
    for index, row in enumerate(rows):
        value = _parse_number(row.get("amount")) or 0.0
        bar_width = 0 if max_value <= 0 else value / max_value * 440
        y = 76 + index * 46
        label = html.escape(row["bucket_label"])
        bars.append(
            f"<text x=\"30\" y=\"{y + 16}\" font-family=\"Segoe UI,Arial\" font-size=\"13\" fill=\"#16202a\">{label}</text>"
            f"<rect x=\"280\" y=\"{y}\" width=\"{bar_width:.1f}\" height=\"24\" rx=\"4\" fill=\"{colors.get(row['bucket'], '#8a8f98')}\"/>"
            f"<text x=\"{290 + bar_width:.1f}\" y=\"{y + 17}\" font-family=\"Segoe UI,Arial\" font-size=\"12\" fill=\"#617080\">{html.escape(row['percentage'] or 'n/a')}%</text>"
        )
    return (
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Asset bucket chart\">"
        "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>"
        "<text x=\"30\" y=\"34\" font-family=\"Segoe UI,Arial\" font-size=\"20\" font-weight=\"700\" fill=\"#16202a\">Asset Buckets</text>"
        + "".join(bars)
        + "</svg>\n"
    )


def _withdrawal_cashflow_chart_svg(rows: list[dict[str, str]], base_currency: str) -> str:
    width, height = 760, 300
    base_rows = [row for row in rows if row["currency"] == base_currency] or rows[:3]
    max_value = max((_parse_number(row.get("annual")) or 0.0 for row in base_rows), default=1.0)
    bars: list[str] = []
    for index, row in enumerate(base_rows):
        value = _parse_number(row.get("annual")) or 0.0
        bar_width = 0 if max_value <= 0 else value / max_value * 500
        y = 82 + index * 54
        label = f"{float(row['withdrawal_rate']) * 100:.1f}%"
        bars.append(
            f"<text x=\"42\" y=\"{y + 18}\" font-family=\"Segoe UI,Arial\" font-size=\"14\" fill=\"#16202a\">{label}</text>"
            f"<rect x=\"130\" y=\"{y}\" width=\"{bar_width:.1f}\" height=\"28\" rx=\"4\" fill=\"#0f766e\"/>"
            f"<text x=\"{140 + bar_width:.1f}\" y=\"{y + 19}\" font-family=\"Segoe UI,Arial\" font-size=\"12\" fill=\"#617080\">{html.escape(row['annual'])} {html.escape(row['currency'])}</text>"
        )
    return (
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Withdrawal cashflow chart\">"
        "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>"
        "<text x=\"30\" y=\"34\" font-family=\"Segoe UI,Arial\" font-size=\"20\" font-weight=\"700\" fill=\"#16202a\">Withdrawal Ladder</text>"
        + "".join(bars)
        + "</svg>\n"
    )


def _bucket_history_chart_svg(rows: list[dict[str, str]]) -> str:
    width, height = 860, 340
    values = [
        (
            row["snapshot_date"] or row["snapshot_id"] or "snapshot",
            _parse_number(row.get("fixed_assets")) or 0.0,
            _parse_number(row.get("retirement_accounts")) or 0.0,
            _parse_number(row.get("liquid_investment_assets")) or 0.0,
        )
        for row in rows
    ]
    if not values:
        return (
            f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Bucket history chart\">"
            "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>"
            "<text x=\"30\" y=\"48\" font-family=\"Segoe UI,Arial\" font-size=\"18\" fill=\"#16202a\">Bucket history unavailable</text></svg>\n"
        )
    max_total = max(sum(parts) for _, *parts in values) or 1.0
    left, bottom, top = 70, 54, 48
    plot_height = height - top - bottom
    gap = 22
    bar_width = max(26, min(72, (width - left - 40 - gap * (len(values) - 1)) / len(values)))
    bars: list[str] = []
    for index, (label, fixed, retirement, liquid) in enumerate(values):
        x = left + index * (bar_width + gap)
        y_base = height - bottom
        segments = [
            (liquid, "#0f766e"),
            (retirement, "#315f8c"),
            (fixed, "#9a6a2f"),
        ]
        for value, color in segments:
            segment_height = value / max_total * plot_height
            y_base -= segment_height
            bars.append(
                f"<rect x=\"{x:.1f}\" y=\"{y_base:.1f}\" width=\"{bar_width:.1f}\" height=\"{segment_height:.1f}\" fill=\"{color}\"/>"
            )
        bars.append(
            f"<text x=\"{x + bar_width / 2:.1f}\" y=\"{height - 22}\" text-anchor=\"middle\" font-family=\"Segoe UI,Arial\" font-size=\"11\" fill=\"#617080\">{html.escape(label)}</text>"
        )
    return (
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Bucketed net worth history chart\">"
        "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>"
        "<text x=\"30\" y=\"32\" font-family=\"Segoe UI,Arial\" font-size=\"20\" font-weight=\"700\" fill=\"#16202a\">Bucketed Net Worth History</text>"
        f"<line x1=\"{left}\" y1=\"{height - bottom}\" x2=\"{width - 26}\" y2=\"{height - bottom}\" stroke=\"#d8dedb\"/>"
        + "".join(bars)
        + "</svg>\n"
    )


def _load_fx_context(path: Path | None, warnings: list[WarningCode]) -> _FxContext | None:
    if path is None:
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        warnings.append(WarningCode.DASHBOARD_V4_FX_RATES_MISSING)
        return None
    base_currency = _clean(payload.get("base_currency"))
    raw_rates = payload.get("rates_to_base") or payload.get("rates")
    if not base_currency or not isinstance(raw_rates, dict):
        warnings.append(WarningCode.DASHBOARD_V4_FX_RATES_MISSING)
        return None
    rates: dict[str, float] = {}
    for currency, value in raw_rates.items():
        currency_code = _clean(currency)
        rate = _parse_number(value)
        if not currency_code or rate is None or rate <= 0:
            warnings.append(WarningCode.DASHBOARD_V4_FX_RATES_MISSING)
            return None
        rates[currency_code] = rate
    rates.setdefault(base_currency, 1.0)
    return _FxContext(base_currency=base_currency, rates_to_base=rates)


def _mapping_amounts(value: object) -> list[tuple[str, float]]:
    if not isinstance(value, dict):
        return []
    result: list[tuple[str, float]] = []
    for currency, amount in value.items():
        parsed = _parse_number(amount)
        currency_code = _clean(currency)
        if parsed is not None and currency_code:
            result.append((currency_code, parsed))
    return result


def _native_totals(items: list[_MoneyItem]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in items:
        if item.amount is None or not item.currency:
            continue
        totals[item.currency] = totals.get(item.currency, 0.0) + item.amount
    return dict(sorted(totals.items()))


def _native_totals_text(totals: dict[str, float]) -> str:
    return ";".join(f"{currency}:{amount:.2f}" for currency, amount in totals.items())


def _native_currency_text(totals: dict[str, float]) -> str:
    if not totals:
        return ""
    if len(totals) == 1:
        return next(iter(totals))
    return "MIXED"


def _base_currency(items: list[_MoneyItem], fx_context: _FxContext | None) -> str:
    if fx_context is not None:
        return fx_context.base_currency
    currencies = {item.currency for item in items if item.currency and item.amount is not None}
    if len(currencies) == 1:
        return next(iter(currencies))
    return "MIXED"


def _bucket_source_layer(bucket: str) -> str:
    return {
        "fixed_assets": "property_mortgage",
        "retirement_accounts": "cpf_srs",
        "liquid_investment_assets": "merged_account_nav",
        "unclassified": "review_queue",
    }[bucket]


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = [
        "# Dashboard v4 Warnings",
        "",
        "Dashboard v4 is offline and uses local refresh outputs only.",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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


def _warning_text(warnings: list[WarningCode]) -> str:
    return ";".join(code.value for code in warnings)


def _mul_optional(value: float | None, multiplier: float) -> float | None:
    return None if value is None else value * multiplier


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
