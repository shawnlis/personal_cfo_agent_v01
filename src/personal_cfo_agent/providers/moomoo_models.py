"""Internal Moomoo read-only data models."""

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
    sdk_import_ok: bool = False
    opend_socket_reachable: bool = False
    context_opened: bool = False
    account_list_query_attempted: bool = False
    account_list_query_success: bool = False
    account_count_redacted: int = 0
    selected_account_hash: str | None = None
    account_filter_mismatch: bool = False
    account_info_query_attempted: bool = False
    account_info_query_success: bool = False
    position_query_attempted: bool = False
    position_query_success: bool = False
    position_count: int = 0
    cash_query_attempted: bool = False
    cash_query_success: bool = False
    cash_currency_count: int = 0
    normalized_rows: int = 0
    sdk_output_suppressed: bool = False
    timeout_seconds: float = 0.0
    warning_codes: list[WarningCode] = field(default_factory=list)
    stage_failures: dict[str, str] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "opend_socket_reachable": self.opend_socket_reachable,
            "context_opened": self.context_opened,
            "account_list_query_attempted": self.account_list_query_attempted,
            "account_list_query_success": self.account_list_query_success,
            "account_count_redacted": self.account_count_redacted,
            "selected_account_hash": self.selected_account_hash,
            "account_filter_mismatch": self.account_filter_mismatch,
            "account_info_query_attempted": self.account_info_query_attempted,
            "account_info_query_success": self.account_info_query_success,
            "position_query_attempted": self.position_query_attempted,
            "position_query_success": self.position_query_success,
            "position_count": self.position_count,
            "cash_query_attempted": self.cash_query_attempted,
            "cash_query_success": self.cash_query_success,
            "cash_currency_count": self.cash_currency_count,
            "normalized_rows": self.normalized_rows,
            "sdk_output_suppressed": self.sdk_output_suppressed,
            "timeout_seconds": self.timeout_seconds,
            "warning_codes": [code.value for code in self.warning_codes],
            "stage_failures": dict(self.stage_failures),
        }


@dataclass(frozen=True)
class MoomooReadOnlySnapshot:
    accounts: list[MoomooAccountRow] = field(default_factory=list)
    cash: list[MoomooCashRow] = field(default_factory=list)
    positions: list[MoomooPositionRow] = field(default_factory=list)
    diagnostics: MoomooReadDiagnostics = field(default_factory=MoomooReadDiagnostics)
