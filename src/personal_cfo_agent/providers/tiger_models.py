"""Internal TigerOpen read-only transfer models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TigerAccountRow:
    account_id: str
    account_type: str = "tiger"
    currency: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class TigerCashRow:
    account_id: str
    currency: str
    amount: float
    source_timestamp: str
    notes: str = ""


@dataclass(frozen=True)
class TigerPositionRow:
    account_id: str
    asset_id: str
    asset_type: str
    symbol: str
    name: str
    quantity: float
    currency: str | None
    market_value: float | None
    cost_basis: float | None
    source_timestamp: str
    notes: str = ""


@dataclass(frozen=True)
class TigerReadOnlySnapshot:
    accounts: list[TigerAccountRow] = field(default_factory=list)
    cash: list[TigerCashRow] = field(default_factory=list)
    positions: list[TigerPositionRow] = field(default_factory=list)
