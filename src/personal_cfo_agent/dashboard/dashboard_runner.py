"""Build dashboard data from normalized ledger rows."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.dashboard.fire import (
    DashboardAssumptions,
    calculate_fire,
    fire_rows,
    load_dashboard_assumptions,
)
from personal_cfo_agent.dashboard.liquidity import calculate_liquidity, liquidity_rows
from personal_cfo_agent.dashboard.net_worth import (
    asset_allocation_rows,
    calculate_net_worth,
    liability_rows,
)
from personal_cfo_agent.dashboard.report_writer import write_dashboard_bundle
from personal_cfo_agent.dashboard.stress import build_stress_scenarios
from personal_cfo_agent.models import NormalizedAsset, ProviderStatus, WarningCode


STALE_DAYS = 45


def build_dashboard(
    rows: list[NormalizedAsset],
    statuses: list[ProviderStatus],
    assumptions: DashboardAssumptions,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    net_worth = calculate_net_worth(rows, expected_provider_count=len(statuses))
    liquidity = calculate_liquidity(
        rows,
        annual_spending_target=assumptions.annual_spending_target,
        emergency_buffer_months=assumptions.emergency_buffer_months,
    )
    fire = calculate_fire(liquidity.investable_assets, assumptions)
    stress_rows = build_stress_scenarios(rows, assumptions)
    warnings = _dashboard_warnings(rows, net_worth, liquidity, fire, assumptions, as_of_date)
    return {
        "as_of_date": as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d"),
        "assumptions": asdict(assumptions),
        "provider_status": [status.to_dict() for status in statuses],
        "net_worth": asdict(net_worth),
        "liquidity": asdict(liquidity),
        "fire": asdict(fire),
        "asset_allocation": asset_allocation_rows(rows),
        "liability_dashboard": liability_rows(rows),
        "stress_scenarios": stress_rows,
        "warnings": [code.value for code in warnings],
    }


def write_dashboard(
    output_dir: Path,
    rows: list[NormalizedAsset],
    statuses: list[ProviderStatus],
    assumptions_path: Path | None,
    as_of_date: str | None = None,
) -> dict[str, Path]:
    assumptions = load_dashboard_assumptions(assumptions_path)
    dashboard = build_dashboard(rows, statuses, assumptions, as_of_date=as_of_date)
    return write_dashboard_bundle(output_dir, dashboard)


def _dashboard_warnings(
    rows: list[NormalizedAsset],
    net_worth,
    liquidity,
    fire,
    assumptions: DashboardAssumptions,
    as_of_date: str | None,
) -> list[WarningCode]:
    codes: list[WarningCode] = []
    for row in rows:
        codes.extend(row.warning_codes)
        if row.needs_review:
            codes.append(WarningCode.NEEDS_REVIEW)
        if _is_stale(row.source_timestamp, as_of_date):
            codes.append(WarningCode.STALE_SOURCE_DATA)
    if (
        liquidity.emergency_buffer_target is not None
        and liquidity.liquid_assets < liquidity.emergency_buffer_target
    ):
        codes.append(WarningCode.LOW_LIQUIDITY_BUFFER)
    if net_worth.property_asset_share > 0.60:
        codes.append(WarningCode.HIGH_PROPERTY_CONCENTRATION)
    if net_worth.leverage_ratio > 0.50:
        codes.append(WarningCode.HIGH_LEVERAGE_EXPOSURE)
    if fire.fire_coverage_ratio is not None and fire.fire_coverage_ratio < 0.50:
        codes.append(WarningCode.FIRE_GAP_LARGE)
    if _assumptions_need_review(assumptions):
        codes.append(WarningCode.ASSUMPTION_NEEDS_REVIEW)
    return _dedupe(codes)


def _assumptions_need_review(assumptions: DashboardAssumptions) -> bool:
    return (
        assumptions.current_age is None
        or assumptions.current_age <= 0
        or assumptions.target_fire_age is None
        or assumptions.target_fire_age <= 0
        or assumptions.annual_spending_target is None
        or assumptions.annual_spending_target <= 0
        or assumptions.safe_withdrawal_rate is None
        or assumptions.safe_withdrawal_rate <= 0
        or assumptions.expected_annual_return is None
        or assumptions.inflation_rate is None
        or assumptions.emergency_buffer_months is None
        or assumptions.emergency_buffer_months < 0
        or assumptions.base_currency is None
    )


def _is_stale(source_timestamp: str, as_of_date: str | None) -> bool:
    if not source_timestamp:
        return True
    source_day = _parse_date(source_timestamp)
    as_of_day = _parse_as_of_date(as_of_date)
    if source_day is None:
        return True
    return (as_of_day - source_day).days > STALE_DAYS


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_as_of_date(value: str | None) -> date:
    if not value:
        return datetime.now(timezone.utc).date()
    return datetime.strptime(value, "%Y%m%d").date()


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
