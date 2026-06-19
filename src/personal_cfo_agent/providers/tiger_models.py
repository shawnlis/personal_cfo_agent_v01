"""Internal TigerOpen read-only data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_cfo_agent.models import WarningCode


@dataclass(frozen=True)
class TigerReadDiagnostics:
    sdk_import_ok: bool = False
    config_dir_exists: bool = False
    config_file_exists: bool = False
    config_loaded: bool = False
    tiger_config_mode_selected: str = "failed"
    tiger_config_constructed: bool = False
    tiger_client_constructed: bool = False
    tiger_config_warning_codes: tuple[WarningCode, ...] = ()
    tiger_id_present_redacted: bool = False
    account_present_redacted: bool = False
    private_key_present_redacted: bool = False
    private_key_format_detected_redacted: str = "missing"
    client_init_attempted: bool = False
    client_init_success: bool = False
    client_auth_success: bool = False
    account_context_observed: bool = False
    selected_account_hash: str = "not configured"
    account_count_redacted: int = 0
    assets_query_attempted: bool = False
    assets_query_success: bool = False
    positions_query_attempted: bool = False
    positions_query_success: bool = False
    position_count: int = 0
    cash_query_attempted: bool = False
    cash_query_success: bool = False
    cash_currency_count: int = 0
    normalized_rows: int = 0
    sdk_output_suppressed: bool = False
    warning_codes: tuple[WarningCode, ...] = ()
    stage_failures: dict[str, str] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "config_dir_exists": self.config_dir_exists,
            "config_file_exists": self.config_file_exists,
            "config_loaded": self.config_loaded,
            "tiger_config_mode_selected": self.tiger_config_mode_selected,
            "tiger_config_constructed": self.tiger_config_constructed,
            "tiger_client_constructed": self.tiger_client_constructed,
            "tiger_config_warning_codes": [
                code.value for code in self.tiger_config_warning_codes
            ],
            "tiger_id_present_redacted": self.tiger_id_present_redacted,
            "account_present_redacted": self.account_present_redacted,
            "private_key_present_redacted": self.private_key_present_redacted,
            "private_key_format_detected_redacted": self.private_key_format_detected_redacted,
            "client_init_attempted": self.client_init_attempted,
            "client_init_success": self.client_init_success,
            "client_auth_success": self.client_auth_success,
            "account_context_observed": self.account_context_observed,
            "selected_account_hash": self.selected_account_hash,
            "account_count_redacted": self.account_count_redacted,
            "assets_query_attempted": self.assets_query_attempted,
            "assets_query_success": self.assets_query_success,
            "positions_query_attempted": self.positions_query_attempted,
            "positions_query_success": self.positions_query_success,
            "position_count": self.position_count,
            "cash_query_attempted": self.cash_query_attempted,
            "cash_query_success": self.cash_query_success,
            "cash_currency_count": self.cash_currency_count,
            "normalized_rows": self.normalized_rows,
            "sdk_output_suppressed": self.sdk_output_suppressed,
            "warning_codes": [code.value for code in self.warning_codes],
            "stage_failures": dict(self.stage_failures),
        }


@dataclass(frozen=True)
class TigerAccountRow:
    account_id: str
    account_type: str = "tiger"
    currency: str | None = None
    account_nav: float | None = None
    source_timestamp: str | None = None
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
    diagnostics: dict[str, object] = field(default_factory=dict)
