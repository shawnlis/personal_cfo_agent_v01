"""Write v0.2.0 dashboard report artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


DASHBOARD_STATEMENT = (
    "This is a personal finance risk dashboard, not investment, tax, estate, "
    "insurance, or trading advice."
)


def write_dashboard_bundle(output_dir: Path, dashboard: dict[str, Any]) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown_report": output_dir / "PERSONAL_CFO_DASHBOARD_V020.md",
        "net_worth_dashboard": output_dir / "net_worth_dashboard.json",
        "asset_allocation": output_dir / "asset_allocation.csv",
        "liquidity_dashboard": output_dir / "liquidity_dashboard.csv",
        "fire_progress": output_dir / "fire_progress.csv",
        "liability_dashboard": output_dir / "liability_dashboard.csv",
        "stress_scenarios": output_dir / "stress_scenarios.csv",
        "dashboard_warnings": output_dir / "dashboard_warnings.md",
    }
    _write_markdown(paths["markdown_report"], dashboard)
    paths["net_worth_dashboard"].write_text(
        json.dumps({"statement": DASHBOARD_STATEMENT, **dashboard}, indent=2),
        encoding="utf-8",
    )
    _write_rows(paths["asset_allocation"], dashboard["asset_allocation"])
    _write_rows(paths["liquidity_dashboard"], _metric_rows(dashboard["liquidity"]))
    _write_rows(paths["fire_progress"], _metric_rows(dashboard["fire"]))
    _write_rows(paths["liability_dashboard"], dashboard["liability_dashboard"])
    _write_rows(paths["stress_scenarios"], dashboard["stress_scenarios"])
    _write_warnings(paths["dashboard_warnings"], dashboard["warnings"])
    return paths


def _write_markdown(path: Path, dashboard: dict[str, Any]) -> None:
    net_worth = dashboard["net_worth"]
    liquidity = dashboard["liquidity"]
    fire = dashboard["fire"]
    assumptions = dashboard["assumptions"]
    lines = [
        "# Personal CFO Dashboard v0.2.0",
        "",
        DASHBOARD_STATEMENT,
        "",
        "## Assumptions",
        "Assumptions are user-provided inputs for deterministic scenarios, not forecasts.",
        f"- current_age: {_stringify(assumptions.get('current_age'))}",
        f"- target_fire_age: {_stringify(assumptions.get('target_fire_age'))}",
        f"- annual_spending_target: {_stringify(assumptions.get('annual_spending_target'))}",
        f"- safe_withdrawal_rate: {_stringify(assumptions.get('safe_withdrawal_rate'))}",
        f"- expected_annual_return: {_stringify(assumptions.get('expected_annual_return'))}",
        f"- inflation_rate: {_stringify(assumptions.get('inflation_rate'))}",
        f"- emergency_buffer_months: {_stringify(assumptions.get('emergency_buffer_months'))}",
        f"- base_currency: {_stringify(assumptions.get('base_currency'))}",
        "",
        "## Net Worth",
        f"- Total assets: {_money(net_worth['total_assets'])}",
        f"- Total liabilities: {_money(net_worth['total_liabilities'])}",
        f"- Net worth: {_money(net_worth['net_worth'])}",
        f"- Provider coverage: {net_worth['provider_coverage']:.4f}",
        f"- Manual asset share: {net_worth['manual_asset_share']:.4f}",
        "",
        "## Liquidity",
        f"- Liquid assets: {_money(liquidity['liquid_assets'])}",
        f"- Investable assets: {_money(liquidity['investable_assets'])}",
        f"- Liquidity runway months: {_optional_number(liquidity['liquidity_runway_months'])}",
        "",
        "## FIRE",
        f"- FIRE number: {_optional_money(fire['fire_number'])}",
        f"- FIRE coverage ratio: {_optional_number(fire['fire_coverage_ratio'], places=4)}",
        f"- Gap to FIRE: {_optional_money(fire['gap_to_fire'])}",
        f"- Estimated years to FIRE: {_optional_number(fire['estimated_years_to_fire'])}",
        "",
        "## Stress Scenarios",
    ]
    for row in dashboard["stress_scenarios"]:
        lines.append(f"- {row['scenario']}: net worth {row['net_worth']}")
    lines.extend(["", "## Warnings"])
    if dashboard["warnings"]:
        for warning in dashboard["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_warnings(path: Path, warnings: list[str]) -> None:
    lines = ["# Dashboard Warnings", "", DASHBOARD_STATEMENT, ""]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _metric_rows(section: dict[str, Any]) -> list[dict[str, str]]:
    return [{"metric": key, "value": _stringify(value)} for key, value in section.items()]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _money(value: float) -> str:
    return f"{float(value):.2f}"


def _optional_money(value: float | None) -> str:
    return "" if value is None else _money(value)


def _optional_number(value: float | None, places: int = 2) -> str:
    return "" if value is None else f"{float(value):.{places}f}"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 1 and value != 0 else f"{value:.2f}"
    return str(value)
