"""Normalize provider snapshots into the internal asset ledger."""

from __future__ import annotations

import hashlib
import os

from personal_cfo_agent.models import (
    NormalizedAsset,
    RawBalance,
    RawCash,
    RawPosition,
    RawProviderSnapshot,
    WarningCode,
)


def hash_account_id(account_id: str, salt: str | None = None) -> str:
    salt_value = salt if salt is not None else os.environ.get("CFO_ACCOUNT_HASH_SALT", "")
    digest = hashlib.sha256(f"{salt_value}:{account_id}".encode("utf-8")).hexdigest()
    return f"acct_{digest[:16]}"


def normalize_snapshots(snapshots: list[RawProviderSnapshot]) -> list[NormalizedAsset]:
    assets: list[NormalizedAsset] = []
    for snapshot in snapshots:
        assets.extend(normalize_snapshot(snapshot))
    return assets


def normalize_snapshot(snapshot: RawProviderSnapshot) -> list[NormalizedAsset]:
    rows: list[NormalizedAsset] = []
    for cash_row in snapshot.cash:
        rows.append(_normalize_cash(snapshot.provider_name, cash_row))
    for position in snapshot.positions:
        rows.append(_normalize_position(snapshot.provider_name, position))
    for balance in snapshot.balances:
        rows.append(_normalize_balance(snapshot.provider_name, balance))
    return rows


def _normalize_cash(provider: str, row: RawCash) -> NormalizedAsset:
    warnings = [WarningCode.ACCOUNT_ID_HASHED]
    if not row.currency:
        warnings.append(WarningCode.MISSING_CURRENCY)
    return NormalizedAsset(
        provider=provider,
        account_id_hash=hash_account_id(row.account_id),
        asset_id=f"CASH-{row.currency}",
        asset_type="cash",
        symbol=row.currency,
        name=f"{row.currency} cash",
        quantity=row.amount,
        currency=row.currency,
        market_value=row.amount,
        cost_basis=None,
        unrealized_pnl=None,
        liquidity_bucket="cash",
        risk_bucket="cash",
        source_timestamp=row.source_timestamp,
        source_confidence="provider_or_manual",
        needs_review=False,
        warning_codes=warnings,
        notes=row.notes,
    )


def _normalize_position(provider: str, row: RawPosition) -> NormalizedAsset:
    warnings = _base_warnings(row.warning_codes, row.currency, row.market_value)
    return NormalizedAsset(
        provider=provider,
        account_id_hash=hash_account_id(row.account_id),
        asset_id=row.asset_id,
        asset_type=row.asset_type,
        symbol=row.symbol,
        name=row.name,
        quantity=row.quantity,
        currency=row.currency,
        market_value=row.market_value,
        cost_basis=row.cost_basis,
        unrealized_pnl=row.unrealized_pnl,
        liquidity_bucket=row.liquidity_bucket,
        risk_bucket=row.risk_bucket,
        source_timestamp=row.source_timestamp,
        source_confidence=row.source_confidence,
        needs_review=row.needs_review,
        warning_codes=warnings,
        notes=row.notes,
    )


def _normalize_balance(provider: str, row: RawBalance) -> NormalizedAsset:
    warnings = _base_warnings(row.warning_codes, row.currency, row.amount)
    return NormalizedAsset(
        provider=provider,
        account_id_hash=hash_account_id(row.account_id),
        asset_id=row.asset_id,
        asset_type=row.asset_type,
        symbol="",
        name=row.name,
        quantity=None,
        currency=row.currency,
        market_value=row.amount,
        cost_basis=None,
        unrealized_pnl=None,
        liquidity_bucket=row.liquidity_bucket,
        risk_bucket=row.risk_bucket,
        source_timestamp=row.source_timestamp,
        source_confidence=row.source_confidence,
        needs_review=row.needs_review,
        warning_codes=warnings,
        notes=row.notes,
    )


def _base_warnings(
    existing: list[WarningCode], currency: str | None, market_value: float | None
) -> list[WarningCode]:
    warnings = [WarningCode.ACCOUNT_ID_HASHED, *existing]
    if not currency:
        warnings.append(WarningCode.MISSING_CURRENCY)
    if market_value is None:
        warnings.append(WarningCode.MISSING_MARKET_VALUE)
    return _dedupe(warnings)


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
