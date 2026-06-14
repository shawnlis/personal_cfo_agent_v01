"""Liquidity dashboard calculations."""

from __future__ import annotations

from dataclasses import dataclass

from personal_cfo_agent.models import NormalizedAsset


LIQUID_BUCKETS = {"cash", "near_cash", "liquid"}
INVESTABLE_TYPES = {
    "cash",
    "equity",
    "etf",
    "fund",
    "bond",
    "fixed_income",
    "unsupported_broker",
    "insurance_cash_value",
}


@dataclass(frozen=True)
class LiquiditySummary:
    liquid_assets: float
    investable_assets: float
    monthly_spending_target: float | None
    emergency_buffer_target: float | None
    liquidity_runway_months: float | None


def calculate_liquidity(
    rows: list[NormalizedAsset],
    annual_spending_target: float | None,
    emergency_buffer_months: float | None,
) -> LiquiditySummary:
    liquid_assets = sum(
        _value(row)
        for row in rows
        if _value(row) > 0 and row.liquidity_bucket in LIQUID_BUCKETS
    )
    investable_assets = sum(
        _value(row)
        for row in rows
        if _value(row) > 0 and row.asset_type in INVESTABLE_TYPES
    )
    monthly_spending = (
        annual_spending_target / 12.0
        if annual_spending_target is not None and annual_spending_target > 0
        else None
    )
    emergency_target = (
        monthly_spending * emergency_buffer_months
        if monthly_spending is not None
        and emergency_buffer_months is not None
        and emergency_buffer_months > 0
        else None
    )
    runway = liquid_assets / monthly_spending if monthly_spending else None
    return LiquiditySummary(
        liquid_assets=round(liquid_assets, 2),
        investable_assets=round(investable_assets, 2),
        monthly_spending_target=_round_optional(monthly_spending),
        emergency_buffer_target=_round_optional(emergency_target),
        liquidity_runway_months=_round_optional(runway),
    )


def liquidity_rows(summary: LiquiditySummary) -> list[dict[str, str]]:
    return [
        {"metric": "liquid_assets", "value": _stringify(summary.liquid_assets)},
        {"metric": "investable_assets", "value": _stringify(summary.investable_assets)},
        {
            "metric": "monthly_spending_target",
            "value": _stringify(summary.monthly_spending_target),
        },
        {
            "metric": "emergency_buffer_target",
            "value": _stringify(summary.emergency_buffer_target),
        },
        {
            "metric": "liquidity_runway_months",
            "value": _stringify(summary.liquidity_runway_months),
        },
    ]


def _value(row: NormalizedAsset) -> float:
    return float(row.market_value or 0.0)


def _round_optional(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _stringify(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"
