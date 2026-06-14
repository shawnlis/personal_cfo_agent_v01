"""Deterministic dashboard stress scenarios."""

from __future__ import annotations

from personal_cfo_agent.dashboard.fire import DashboardAssumptions
from personal_cfo_agent.models import NormalizedAsset


INVESTMENT_TYPES = {"equity", "etf", "fund", "bond", "fixed_income", "unsupported_broker"}
PROPERTY_TYPES = {"residential_property", "property"}


def build_stress_scenarios(
    rows: list[NormalizedAsset], assumptions: DashboardAssumptions
) -> list[dict[str, str]]:
    scenarios = [
        _scenario(rows, assumptions, "cash_unchanged", "Cash bucket held constant."),
        _scenario(
            rows,
            assumptions,
            "investment_assets_down_30",
            "Investment assets marked down by 30%.",
            investment_multiplier=0.70,
        ),
        _scenario(
            rows,
            assumptions,
            "property_down_20",
            "Property assets marked down by 20%.",
            property_multiplier=0.80,
        ),
        _scenario(
            rows,
            assumptions,
            "mortgage_rate_up_2",
            "Mortgage rate sensitivity adds 2% of mortgage balance as annual debt service.",
            mortgage_rate_delta=0.02,
        ),
        _scenario(
            rows,
            assumptions,
            "expenses_up_20",
            "Annual spending target increased by 20%.",
            spending_multiplier=1.20,
        ),
        _scenario(
            rows,
            assumptions,
            "combined_recession",
            "Investment and property marks plus expense and mortgage-rate stress.",
            investment_multiplier=0.70,
            property_multiplier=0.80,
            spending_multiplier=1.20,
            income_multiplier=0.70 if assumptions.annual_income is not None else None,
            mortgage_rate_delta=0.02,
        ),
    ]
    if assumptions.annual_income is not None:
        scenarios.insert(
            -1,
            _scenario(
                rows,
                assumptions,
                "income_down_30",
                "Annual income reduced by 30%.",
                income_multiplier=0.70,
            ),
        )
    return scenarios


def _scenario(
    rows: list[NormalizedAsset],
    assumptions: DashboardAssumptions,
    name: str,
    notes: str,
    investment_multiplier: float = 1.0,
    property_multiplier: float = 1.0,
    spending_multiplier: float = 1.0,
    income_multiplier: float | None = None,
    mortgage_rate_delta: float = 0.0,
) -> dict[str, str]:
    total_assets = 0.0
    total_liabilities = 0.0
    liquid_assets = 0.0
    mortgage_balance = 0.0
    for row in rows:
        value = _stressed_value(row, investment_multiplier, property_multiplier)
        if value > 0:
            total_assets += value
            if row.liquidity_bucket in {"cash", "near_cash", "liquid"}:
                liquid_assets += value
        if value < 0:
            total_liabilities += abs(value)
            if row.asset_type == "mortgage" or row.risk_bucket == "mortgage":
                mortgage_balance += abs(value)
    annual_spending = (
        assumptions.annual_spending_target * spending_multiplier
        if assumptions.annual_spending_target is not None
        else None
    )
    annual_income = (
        assumptions.annual_income * (income_multiplier if income_multiplier is not None else 1.0)
        if assumptions.annual_income is not None
        else None
    )
    extra_debt_service = mortgage_balance * mortgage_rate_delta
    return {
        "scenario": name,
        "total_assets": f"{total_assets:.2f}",
        "total_liabilities": f"{total_liabilities:.2f}",
        "net_worth": f"{(total_assets - total_liabilities):.2f}",
        "liquid_assets": f"{liquid_assets:.2f}",
        "annual_income": _stringify(annual_income),
        "annual_spending_target": _stringify(annual_spending),
        "extra_annual_debt_service": f"{extra_debt_service:.2f}",
        "notes": notes,
    }


def _stressed_value(
    row: NormalizedAsset, investment_multiplier: float, property_multiplier: float
) -> float:
    value = float(row.market_value or 0.0)
    if value <= 0:
        return value
    if row.asset_type in PROPERTY_TYPES or row.risk_bucket == "real_estate":
        return value * property_multiplier
    if row.asset_type in INVESTMENT_TYPES:
        return value * investment_multiplier
    return value


def _stringify(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"
