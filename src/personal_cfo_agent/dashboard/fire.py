"""Simple deterministic FIRE dashboard calculations."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DashboardAssumptions:
    current_age: float | None = None
    target_fire_age: float | None = None
    annual_spending_target: float | None = None
    safe_withdrawal_rate: float | None = None
    expected_annual_return: float | None = None
    inflation_rate: float | None = None
    emergency_buffer_months: float | None = None
    base_currency: str | None = None
    annual_income: float | None = None


@dataclass(frozen=True)
class FireSummary:
    fire_number: float | None
    fire_coverage_ratio: float | None
    gap_to_fire: float | None
    estimated_years_to_fire: float | None
    current_age: float | None
    target_fire_age: float | None
    target_years_remaining: float | None


def load_dashboard_assumptions(path: Path | None) -> DashboardAssumptions:
    if path is None:
        return DashboardAssumptions()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return DashboardAssumptions()
    return DashboardAssumptions(
        current_age=_optional_float(payload.get("current_age")),
        target_fire_age=_optional_float(payload.get("target_fire_age")),
        annual_spending_target=_optional_float(payload.get("annual_spending_target")),
        safe_withdrawal_rate=_optional_float(payload.get("safe_withdrawal_rate")),
        expected_annual_return=_optional_float(payload.get("expected_annual_return")),
        inflation_rate=_optional_float(payload.get("inflation_rate")),
        emergency_buffer_months=_optional_float(payload.get("emergency_buffer_months")),
        base_currency=_optional_text(payload.get("base_currency")),
        annual_income=_optional_float(payload.get("annual_income")),
    )


def calculate_fire(investable_assets: float, assumptions: DashboardAssumptions) -> FireSummary:
    fire_number = _fire_number(
        assumptions.annual_spending_target, assumptions.safe_withdrawal_rate
    )
    coverage = (
        investable_assets / fire_number
        if fire_number is not None and fire_number > 0
        else None
    )
    gap = (
        max(fire_number - investable_assets, 0.0)
        if fire_number is not None
        else None
    )
    target_years_remaining = (
        max(assumptions.target_fire_age - assumptions.current_age, 0.0)
        if assumptions.current_age is not None and assumptions.target_fire_age is not None
        else None
    )
    return FireSummary(
        fire_number=_round_optional(fire_number),
        fire_coverage_ratio=_round_optional(coverage, places=4),
        gap_to_fire=_round_optional(gap),
        estimated_years_to_fire=_round_optional(
            _estimated_years_to_fire(investable_assets, fire_number, assumptions)
        ),
        current_age=assumptions.current_age,
        target_fire_age=assumptions.target_fire_age,
        target_years_remaining=_round_optional(target_years_remaining),
    )


def fire_rows(summary: FireSummary) -> list[dict[str, str]]:
    return [
        {"metric": "fire_number", "value": _stringify(summary.fire_number)},
        {
            "metric": "fire_coverage_ratio",
            "value": _stringify(summary.fire_coverage_ratio, places=4),
        },
        {"metric": "gap_to_fire", "value": _stringify(summary.gap_to_fire)},
        {
            "metric": "estimated_years_to_fire",
            "value": _stringify(summary.estimated_years_to_fire),
        },
        {"metric": "current_age", "value": _stringify(summary.current_age)},
        {"metric": "target_fire_age", "value": _stringify(summary.target_fire_age)},
        {
            "metric": "target_years_remaining",
            "value": _stringify(summary.target_years_remaining),
        },
    ]


def _fire_number(
    annual_spending_target: float | None, safe_withdrawal_rate: float | None
) -> float | None:
    if annual_spending_target is None or annual_spending_target <= 0:
        return None
    if safe_withdrawal_rate is None or safe_withdrawal_rate <= 0:
        return None
    return annual_spending_target / safe_withdrawal_rate


def _estimated_years_to_fire(
    investable_assets: float,
    fire_number: float | None,
    assumptions: DashboardAssumptions,
) -> float | None:
    if fire_number is None or fire_number <= 0:
        return None
    if investable_assets >= fire_number:
        return 0.0
    if investable_assets <= 0:
        return None
    nominal_return = assumptions.expected_annual_return
    inflation_rate = assumptions.inflation_rate or 0.0
    if nominal_return is None:
        return None
    real_return = ((1.0 + nominal_return) / (1.0 + inflation_rate)) - 1.0
    if real_return <= 0:
        return None
    return math.log(fire_number / investable_assets) / math.log(1.0 + real_return)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _round_optional(value: float | None, places: int = 2) -> float | None:
    return round(value, places) if value is not None else None


def _stringify(value: float | None, places: int = 2) -> str:
    return "" if value is None else f"{value:.{places}f}"
