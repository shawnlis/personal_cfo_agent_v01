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
    discovery_success: bool = False
    context_opened: bool = False
    account_list_query_attempted: bool = False
    account_list_query_success: bool = False
    account_count_redacted: int = 0
    selected_account_hash: str | None = None
    selected_context_mode: str | None = None
    selected_discovery_context_mode: str | None = None
    selected_read_context_mode: str | None = None
    account_filter_mismatch: bool = False
    account_info_query_attempted: bool = False
    account_info_query_success: bool = False
    accinfo_query_attempted: bool = False
    accinfo_query_success: bool = False
    accinfo_failure_stage: str | None = None
    accinfo_sdk_ret_code_sanitized: str | None = None
    accinfo_exception_category_sanitized: str | None = None
    position_query_attempted: bool = False
    position_query_success: bool = False
    position_failure_stage: str | None = None
    position_sdk_ret_code_sanitized: str | None = None
    position_exception_category_sanitized: str | None = None
    position_count: int = 0
    cash_query_attempted: bool = False
    cash_query_success: bool = False
    cash_currency_count: int = 0
    normalized_rows: int = 0
    sdk_output_suppressed: bool = False
    forbidden_api_called: bool = False
    timeout_seconds: float = 0.0
    terminal_warning_codes: list[WarningCode] = field(default_factory=list)
    variant_warning_codes: list[WarningCode] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)
    stage_failures: dict[str, str] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "opend_socket_reachable": self.opend_socket_reachable,
            "discovery_success": self.discovery_success,
            "context_opened": self.context_opened,
            "account_list_query_attempted": self.account_list_query_attempted,
            "account_list_query_success": self.account_list_query_success,
            "account_count_redacted": self.account_count_redacted,
            "selected_account_hash": self.selected_account_hash,
            "selected_context_mode": self.selected_context_mode,
            "selected_discovery_context_mode": self.selected_discovery_context_mode,
            "selected_read_context_mode": self.selected_read_context_mode,
            "account_filter_mismatch": self.account_filter_mismatch,
            "account_info_query_attempted": self.account_info_query_attempted,
            "account_info_query_success": self.account_info_query_success,
            "accinfo_query_attempted": self.accinfo_query_attempted,
            "accinfo_query_success": self.accinfo_query_success,
            "accinfo_failure_stage": self.accinfo_failure_stage,
            "accinfo_sdk_ret_code_sanitized": self.accinfo_sdk_ret_code_sanitized,
            "accinfo_exception_category_sanitized": (
                self.accinfo_exception_category_sanitized
            ),
            "position_query_attempted": self.position_query_attempted,
            "position_query_success": self.position_query_success,
            "position_failure_stage": self.position_failure_stage,
            "position_sdk_ret_code_sanitized": self.position_sdk_ret_code_sanitized,
            "position_exception_category_sanitized": (
                self.position_exception_category_sanitized
            ),
            "position_count": self.position_count,
            "cash_query_attempted": self.cash_query_attempted,
            "cash_query_success": self.cash_query_success,
            "cash_currency_count": self.cash_currency_count,
            "normalized_rows": self.normalized_rows,
            "sdk_output_suppressed": self.sdk_output_suppressed,
            "forbidden_api_called": self.forbidden_api_called,
            "timeout_seconds": self.timeout_seconds,
            "terminal_warning_codes": [
                code.value for code in self.terminal_warning_codes
            ],
            "variant_warning_codes": [code.value for code in self.variant_warning_codes],
            "warning_codes": [code.value for code in self.warning_codes],
            "stage_failures": dict(self.stage_failures),
        }


@dataclass(frozen=True)
class MoomooReadOnlySnapshot:
    accounts: list[MoomooAccountRow] = field(default_factory=list)
    cash: list[MoomooCashRow] = field(default_factory=list)
    positions: list[MoomooPositionRow] = field(default_factory=list)
    diagnostics: MoomooReadDiagnostics = field(default_factory=MoomooReadDiagnostics)
