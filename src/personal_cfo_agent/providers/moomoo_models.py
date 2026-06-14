"""Internal Moomoo read-only transfer models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MoomooAccountRow:
    account_id: str
    account_type: str = "moomoo"
    currency: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class MoomooCashRow:
    account_id: str
    currency: str
    amount: float
    source_timestamp: str
    notes: str = ""


@dataclass(frozen=True)
class MoomooPositionRow:
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
class MoomooReadOnlySnapshot:
    accounts: list[MoomooAccountRow] = field(default_factory=list)
    cash: list[MoomooCashRow] = field(default_factory=list)
    positions: list[MoomooPositionRow] = field(default_factory=list)
