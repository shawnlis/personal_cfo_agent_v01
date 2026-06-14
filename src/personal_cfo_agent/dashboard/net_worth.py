"""Deterministic net worth dashboard calculations."""

from __future__ import annotations

from dataclasses import dataclass

from personal_cfo_agent.models import NormalizedAsset


PROPERTY_TYPES = {"residential_property", "property"}


@dataclass(frozen=True)
class NetWorthSummary:
    total_assets: float
    total_liabilities: float
    net_worth: float
    currency_exposure: dict[str, float]
    provider_coverage: float
    manual_asset_share: float
    property_asset_share: float
    leverage_ratio: float


def calculate_net_worth(
    rows: list[NormalizedAsset], expected_provider_count: int
) -> NetWorthSummary:
    total_assets = sum(_value(row) for row in rows if _value(row) > 0)
    total_liabilities = abs(sum(_value(row) for row in rows if _value(row) < 0))
    currency_exposure: dict[str, float] = {}
    for row in rows:
        currency = row.currency or "UNKNOWN"
        currency_exposure[currency] = currency_exposure.get(currency, 0.0) + _value(row)

    providers_with_rows = {row.provider for row in rows}
    manual_assets = sum(
        _value(row)
        for row in rows
        if row.provider == "manual_snapshot" and _value(row) > 0
    )
    property_assets = sum(
        _value(row)
        for row in rows
        if _value(row) > 0 and _is_property(row)
    )
    return NetWorthSummary(
        total_assets=round(total_assets, 2),
        total_liabilities=round(total_liabilities, 2),
        net_worth=round(total_assets - total_liabilities, 2),
        currency_exposure={
            currency: round(value, 2) for currency, value in sorted(currency_exposure.items())
        },
        provider_coverage=round(
            len(providers_with_rows) / expected_provider_count if expected_provider_count else 0.0,
            4,
        ),
        manual_asset_share=round(manual_assets / total_assets if total_assets else 0.0, 4),
        property_asset_share=round(property_assets / total_assets if total_assets else 0.0, 4),
        leverage_ratio=round(total_liabilities / total_assets if total_assets else 0.0, 4),
    )


def asset_allocation_rows(rows: list[NormalizedAsset]) -> list[dict[str, str]]:
    total_assets = sum(_value(row) for row in rows if _value(row) > 0)
    grouped: dict[str, float] = {}
    providers: dict[str, set[str]] = {}
    account_hashes: dict[str, set[str]] = {}
    source_confidences: dict[str, set[str]] = {}
    source_timestamps: dict[str, set[str]] = {}
    warning_codes: dict[str, set[str]] = {}
    needs_review: dict[str, bool] = {}
    for row in rows:
        value = _value(row)
        if value <= 0:
            continue
        grouped[row.asset_type] = grouped.get(row.asset_type, 0.0) + value
        providers.setdefault(row.asset_type, set()).add(row.provider)
        account_hashes.setdefault(row.asset_type, set()).add(row.account_id_hash)
        source_confidences.setdefault(row.asset_type, set()).add(row.source_confidence)
        source_timestamps.setdefault(row.asset_type, set()).add(row.source_timestamp)
        warning_codes.setdefault(row.asset_type, set()).update(code.value for code in row.warning_codes)
        needs_review[row.asset_type] = needs_review.get(row.asset_type, False) or row.needs_review
    return [
        {
            "asset_type": asset_type,
            "market_value": f"{value:.2f}",
            "share_of_assets": f"{(value / total_assets if total_assets else 0.0):.4f}",
            "providers": _join_values(providers[asset_type]),
            "account_id_hashes": _join_values(account_hashes[asset_type]),
            "source_confidences": _join_values(source_confidences[asset_type]),
            "source_timestamps": _join_values(source_timestamps[asset_type]),
            "needs_review": str(needs_review[asset_type]).lower(),
            "warning_codes": _join_values(warning_codes[asset_type]),
        }
        for asset_type, value in sorted(grouped.items())
    ]


def liability_rows(rows: list[NormalizedAsset]) -> list[dict[str, str]]:
    liabilities: list[dict[str, str]] = []
    for row in rows:
        value = _value(row)
        if value >= 0:
            continue
        liabilities.append(
            {
                "liability_id": row.asset_id,
                "liability_type": row.asset_type,
                "provider": row.provider,
                "account_id_hash": row.account_id_hash,
                "name": row.name,
                "currency": row.currency or "",
                "outstanding_balance": f"{abs(value):.2f}",
                "risk_bucket": row.risk_bucket,
                "source_timestamp": row.source_timestamp,
                "source_confidence": row.source_confidence,
                "needs_review": str(row.needs_review).lower(),
                "warning_codes": ";".join(code.value for code in row.warning_codes),
            }
        )
    return liabilities


def _is_property(row: NormalizedAsset) -> bool:
    return row.asset_type in PROPERTY_TYPES or row.risk_bucket == "real_estate"


def _value(row: NormalizedAsset) -> float:
    return float(row.market_value or 0.0)


def _join_values(values: set[str]) -> str:
    return ";".join(value for value in sorted(values) if value)
