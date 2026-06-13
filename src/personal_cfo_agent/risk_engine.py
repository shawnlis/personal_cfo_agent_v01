"""Simple v0.1 personal finance risk and summary calculations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from personal_cfo_agent.models import NormalizedAsset, RiskSummary, WarningCode


LIQUID_BUCKETS = {"cash", "near_cash", "liquid"}
INVESTABLE_TYPES = {"cash", "equity", "etf", "fund", "bond", "fixed_income"}
STALE_DAYS = 45


def calculate_risk_summary(
    rows: list[NormalizedAsset],
    expected_provider_count: int,
    as_of_date: str | None = None,
) -> RiskSummary:
    total_assets = sum(_value(row) for row in rows if _value(row) > 0)
    total_liabilities = abs(sum(_value(row) for row in rows if _value(row) < 0))
    net_worth = total_assets - total_liabilities
    liquid_assets = sum(
        _value(row)
        for row in rows
        if _value(row) > 0 and row.liquidity_bucket in LIQUID_BUCKETS
    )
    investable_assets = sum(
        _value(row) for row in rows if _value(row) > 0 and row.asset_type in INVESTABLE_TYPES
    )
    currency_exposure: dict[str, float] = {}
    warnings: list[WarningCode] = []
    for row in rows:
        currency = row.currency or "UNKNOWN"
        currency_exposure[currency] = currency_exposure.get(currency, 0.0) + _value(row)
        warnings.extend(row.warning_codes)
        if _is_stale(row.source_timestamp, as_of_date):
            warnings.append(WarningCode.STALE_SOURCE_DATA)

    providers_with_rows = {row.provider for row in rows}
    provider_coverage_ratio = (
        len(providers_with_rows) / expected_provider_count if expected_provider_count else 0.0
    )
    manual_positive_assets = sum(
        _value(row)
        for row in rows
        if row.provider == "manual_snapshot" and _value(row) > 0
    )
    manual_asset_share = manual_positive_assets / total_assets if total_assets else 0.0
    return RiskSummary(
        total_assets=round(total_assets, 2),
        total_liabilities=round(total_liabilities, 2),
        net_worth=round(net_worth, 2),
        liquid_assets=round(liquid_assets, 2),
        investable_assets=round(investable_assets, 2),
        provider_coverage_ratio=round(provider_coverage_ratio, 4),
        manual_asset_share=round(manual_asset_share, 4),
        currency_exposure={key: round(value, 2) for key, value in currency_exposure.items()},
        warning_codes=_dedupe(warnings),
    )


def _value(row: NormalizedAsset) -> float:
    return float(row.market_value or 0.0)


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
