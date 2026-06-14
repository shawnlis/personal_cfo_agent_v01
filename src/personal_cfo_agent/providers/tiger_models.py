"""Internal TigerOpen read-only data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_cfo_agent.models import WarningCode


@dataclass(frozen=True)
class TigerReadDiagnostics:
    sdk_import_ok: bool = False
    config_loaded: bool = False
    account_context_observed: bool = False
    selected_account_hash: str = "not configured"
    account_count_redacted: int = 0
    asset_query_attempted: bool = False
    asset_query_success: bool = False
    position_query_attempted: bool = False
    position_query_success: bool = False
    position_count: int = 0
    cash_currency_count: int = 0
    normalized_rows: int = 0
    sdk_output_suppressed: bool = False
    warning_codes: tuple[WarningCode, ...] = ()
    stage_failures: dict[str, str] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "config_loaded": self.config_loaded,
            "account_context_observed": self.account_context_observed,
            "selected_account_hash": self.selected_account_hash,
            "account_count_redacted": self.account_count_redacted,
            "asset_query_attempted": self.asset_query_attempted,
            "asset_query_success": self.asset_query_success,
            "position_query_attempted": self.position_query_attempted,
            "position_query_success": self.position_query_success,
            "position_count": self.position_count,
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
