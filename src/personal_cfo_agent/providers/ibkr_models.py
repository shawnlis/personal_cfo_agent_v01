"""Internal IBKR read-only transfer models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IBKRAccountRow:
    account_id: str
    account_type: str = "ibkr"
    currency: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class IBKRCashRow:
    account_id: str
    currency: str
    amount: float
    source_timestamp: str
    notes: str = ""


@dataclass(frozen=True)
class IBKRPositionRow:
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
class IBKRReadOnlySnapshot:
    accounts: list[IBKRAccountRow] = field(default_factory=list)
    cash: list[IBKRCashRow] = field(default_factory=list)
    positions: list[IBKRPositionRow] = field(default_factory=list)
