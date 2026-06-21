"""Internal IBKR read-only transfer models."""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_cfo_agent.models import WarningCode


@dataclass(frozen=True)
class IBKRAccountRow:
    account_id: str
    account_type: str = "ibkr"
    currency: str | None = None
    account_nav: float | None = None
    source_timestamp: str = ""
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
class IBKRReadDiagnostics:
    session_type_redacted: str = "not_configured"
    connected_to_socket: bool = False
    api_handshake_seen: bool = False
    managed_accounts_seen: bool = False
    managed_account_count_redacted: int = 0
    requested_account_hash: str | None = None
    requested_account_seen: bool | None = None
    positions_callback_seen: bool = False
    position_count: int = 0
    account_summary_callback_seen: bool = False
    cash_currency_count: int = 0
    timeout_seconds: float = 0.0
    warning_codes: list[WarningCode] = field(default_factory=list)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "session_type_redacted": self.session_type_redacted,
            "connected_to_socket": self.connected_to_socket,
            "api_handshake_seen": self.api_handshake_seen,
            "managed_accounts_seen": self.managed_accounts_seen,
            "managed_account_count_redacted": self.managed_account_count_redacted,
            "requested_account_hash": self.requested_account_hash,
            "requested_account_seen": self.requested_account_seen,
            "positions_callback_seen": self.positions_callback_seen,
            "position_count": self.position_count,
            "account_summary_callback_seen": self.account_summary_callback_seen,
            "cash_currency_count": self.cash_currency_count,
            "timeout_seconds": self.timeout_seconds,
            "warning_codes": [code.value for code in self.warning_codes],
        }


@dataclass(frozen=True)
class IBKRReadOnlySnapshot:
    accounts: list[IBKRAccountRow] = field(default_factory=list)
    cash: list[IBKRCashRow] = field(default_factory=list)
    positions: list[IBKRPositionRow] = field(default_factory=list)
    diagnostics: IBKRReadDiagnostics = field(default_factory=IBKRReadDiagnostics)
