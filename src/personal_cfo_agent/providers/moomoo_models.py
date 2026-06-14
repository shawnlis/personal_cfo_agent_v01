"""Internal Moomoo read-only transfer models."""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_cfo_agent.models import WarningCode


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
class MoomooReadDiagnostics:
    connected_to_opend: bool = False
    connection_established: bool = False
    account_list_seen: bool = False
    account_count_redacted: int = 0
    positions_seen: bool = False
    position_count: int = 0
    cash_seen: bool = False
    cash_currency_count: int = 0
    normalized_row_count: int = 0
    timeout_seconds: float = 0.0
    warning_codes: list[WarningCode] = field(default_factory=list)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "connected_to_opend": self.connected_to_opend,
            "connection_established": self.connection_established,
            "account_list_seen": self.account_list_seen,
            "account_count_redacted": self.account_count_redacted,
            "positions_seen": self.positions_seen,
            "position_count": self.position_count,
            "cash_seen": self.cash_seen,
            "cash_currency_count": self.cash_currency_count,
            "normalized_row_count": self.normalized_row_count,
            "timeout_seconds": self.timeout_seconds,
            "warning_codes": [code.value for code in self.warning_codes],
        }


@dataclass(frozen=True)
class MoomooReadOnlySnapshot:
    accounts: list[MoomooAccountRow] = field(default_factory=list)
    cash: list[MoomooCashRow] = field(default_factory=list)
    positions: list[MoomooPositionRow] = field(default_factory=list)
    diagnostics: MoomooReadDiagnostics = field(default_factory=MoomooReadDiagnostics)
