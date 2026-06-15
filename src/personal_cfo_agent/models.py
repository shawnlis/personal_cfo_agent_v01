"""Core data models for Personal CFO Agent v0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderLevel(str, Enum):
    LEVEL_0 = "level_0_fixture_manual_snapshot"
    LEVEL_1 = "level_1_api_contract_stub"
    LEVEL_2 = "level_2_read_only_live_connector"


class ConnectionMode(str, Enum):
    FIXTURE = "fixture_manual_snapshot"
    API_STUB = "api_contract_stub"
    LIVE_READINESS = "live_readiness_check_only"
    LIVE_READ = "live_read_only"


class WarningCode(str, Enum):
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    PROVIDER_CONFIG_MISSING = "PROVIDER_CONFIG_MISSING"
    LIVE_READ_NOT_ALLOWED = "LIVE_READ_NOT_ALLOWED"
    PROVIDER_CONNECTION_FAILED = "PROVIDER_CONNECTION_FAILED"
    PROVIDER_FETCH_FAILED = "PROVIDER_FETCH_FAILED"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    MANUAL_SNAPSHOT_REQUIRED = "MANUAL_SNAPSHOT_REQUIRED"
    STALE_SOURCE_DATA = "STALE_SOURCE_DATA"
    MISSING_MARKET_VALUE = "MISSING_MARKET_VALUE"
    MISSING_CURRENCY = "MISSING_CURRENCY"
    ACCOUNT_ID_HASHED = "ACCOUNT_ID_HASHED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MANUAL_VALUE_NEEDS_REVIEW = "MANUAL_VALUE_NEEDS_REVIEW"
    STALE_MANUAL_VALUATION = "STALE_MANUAL_VALUATION"
    MISSING_VALUATION_DATE = "MISSING_VALUATION_DATE"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    UNSUPPORTED_PROVIDER_MANUAL_ONLY = "UNSUPPORTED_PROVIDER_MANUAL_ONLY"
    SINGPASS_AUTOMATION_BLOCKED = "SINGPASS_AUTOMATION_BLOCKED"
    LOW_LIQUIDITY_BUFFER = "LOW_LIQUIDITY_BUFFER"
    HIGH_PROPERTY_CONCENTRATION = "HIGH_PROPERTY_CONCENTRATION"
    HIGH_LEVERAGE_EXPOSURE = "HIGH_LEVERAGE_EXPOSURE"
    FIRE_GAP_LARGE = "FIRE_GAP_LARGE"
    ASSUMPTION_NEEDS_REVIEW = "ASSUMPTION_NEEDS_REVIEW"
    SECRET_DETECTED = "SECRET_DETECTED"
    FORBIDDEN_METHOD_EXPOSED = "FORBIDDEN_METHOD_EXPOSED"
    UNOFFICIAL_API_BLOCKED = "UNOFFICIAL_API_BLOCKED"
    SDK_NOT_INSTALLED = "SDK_NOT_INSTALLED"
    IBKR_HANDSHAKE_TIMEOUT = "IBKR_HANDSHAKE_TIMEOUT"
    IBKR_MANAGED_ACCOUNTS_EMPTY = "IBKR_MANAGED_ACCOUNTS_EMPTY"
    IBKR_POSITIONS_EMPTY = "IBKR_POSITIONS_EMPTY"
    IBKR_ACCOUNT_SUMMARY_EMPTY = "IBKR_ACCOUNT_SUMMARY_EMPTY"
    IBKR_ACCOUNT_FILTER_MISMATCH = "IBKR_ACCOUNT_FILTER_MISMATCH"
    IBKR_CALLBACK_TIMEOUT = "IBKR_CALLBACK_TIMEOUT"
    IBKR_NO_DATA_RETURNED = "IBKR_NO_DATA_RETURNED"
    IBKR_DATA_PATH_NOT_IMPLEMENTED = "IBKR_DATA_PATH_NOT_IMPLEMENTED"
    IBKR_READ_SUCCEEDED_EMPTY = "IBKR_READ_SUCCEEDED_EMPTY"
    MOOMOO_SDK_NOT_INSTALLED = "MOOMOO_SDK_NOT_INSTALLED"
    MOOMOO_OPEND_UNREACHABLE = "MOOMOO_OPEND_UNREACHABLE"
    MOOMOO_CONNECTION_FAILED = "MOOMOO_CONNECTION_FAILED"
    MOOMOO_CONTEXT_OPEN_FAILED = "MOOMOO_CONTEXT_OPEN_FAILED"
    MOOMOO_ACCOUNT_LIST_FAILED = "MOOMOO_ACCOUNT_LIST_FAILED"
    MOOMOO_ACCOUNT_LIST_EMPTY = "MOOMOO_ACCOUNT_LIST_EMPTY"
    MOOMOO_ACCOUNT_FILTER_MISMATCH = "MOOMOO_ACCOUNT_FILTER_MISMATCH"
    MOOMOO_ACCOUNT_INFO_FAILED = "MOOMOO_ACCOUNT_INFO_FAILED"
    MOOMOO_POSITION_LIST_FAILED = "MOOMOO_POSITION_LIST_FAILED"
    MOOMOO_POSITION_LIST_EMPTY = "MOOMOO_POSITION_LIST_EMPTY"
    MOOMOO_POSITIONS_EMPTY = "MOOMOO_POSITIONS_EMPTY"
    MOOMOO_CASH_QUERY_FAILED = "MOOMOO_CASH_QUERY_FAILED"
    MOOMOO_CASH_EMPTY = "MOOMOO_CASH_EMPTY"
    MOOMOO_NORMALIZATION_FAILED = "MOOMOO_NORMALIZATION_FAILED"
    MOOMOO_CALLBACK_TIMEOUT = "MOOMOO_CALLBACK_TIMEOUT"
    MOOMOO_NO_DATA_RETURNED = "MOOMOO_NO_DATA_RETURNED"
    MOOMOO_DATA_PATH_NOT_IMPLEMENTED = "MOOMOO_DATA_PATH_NOT_IMPLEMENTED"
    MOOMOO_READ_SUCCEEDED_EMPTY = "MOOMOO_READ_SUCCEEDED_EMPTY"
    MOOMOO_SDK_OUTPUT_SUPPRESSED = "MOOMOO_SDK_OUTPUT_SUPPRESSED"
    MOOMOO_READ_REQUIRES_MANUAL_REVIEW = "MOOMOO_READ_REQUIRES_MANUAL_REVIEW"
    MOOMOO_ACCOUNT_DISCOVERY_OK = "MOOMOO_ACCOUNT_DISCOVERY_OK"
    MOOMOO_ACCOUNT_DISCOVERY_FAILED = "MOOMOO_ACCOUNT_DISCOVERY_FAILED"
    MOOMOO_NO_ACCOUNT_DISCOVERED = "MOOMOO_NO_ACCOUNT_DISCOVERED"
    MOOMOO_SECURITY_FIRM_MISMATCH = "MOOMOO_SECURITY_FIRM_MISMATCH"
    MOOMOO_MARKET_FILTER_MISMATCH = "MOOMOO_MARKET_FILTER_MISMATCH"
    MOOMOO_GENERAL_SEC_ACCOUNT_REQUIRED = "MOOMOO_GENERAL_SEC_ACCOUNT_REQUIRED"
    MOOMOO_ACCOUNT_STATUS_NOT_ACTIVE = "MOOMOO_ACCOUNT_STATUS_NOT_ACTIVE"
    MOOMOO_TRDMARKET_AUTH_MISSING = "MOOMOO_TRDMARKET_AUTH_MISSING"
    MOOMOO_SELECTED_ACCOUNT_MISSING = "MOOMOO_SELECTED_ACCOUNT_MISSING"
    MOOMOO_SELECTED_ACCOUNT_HASHED = "MOOMOO_SELECTED_ACCOUNT_HASHED"
    MOOMOO_EXPLICIT_ACC_ID_SELECTED = "MOOMOO_EXPLICIT_ACC_ID_SELECTED"
    MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED = "MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED"
    MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW = (
        "MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW"
    )
    MOOMOO_DISCOVERY_SUCCESS_WITH_VARIANT_WARNINGS = (
        "MOOMOO_DISCOVERY_SUCCESS_WITH_VARIANT_WARNINGS"
    )
    MOOMOO_ACC_INDEX_FALLBACK_USED = "MOOMOO_ACC_INDEX_FALLBACK_USED"
    MOOMOO_ACCINFO_QUERY_FAILED = "MOOMOO_ACCINFO_QUERY_FAILED"
    MOOMOO_POSITION_QUERY_FAILED = "MOOMOO_POSITION_QUERY_FAILED"
    MOOMOO_FUNDS_DATA_EMPTY = "MOOMOO_FUNDS_DATA_EMPTY"
    MOOMOO_POSITION_DATA_EMPTY = "MOOMOO_POSITION_DATA_EMPTY"
    MOOMOO_CASH_NORMALIZATION_SHAPE_WARNING = (
        "MOOMOO_CASH_NORMALIZATION_SHAPE_WARNING"
    )
    MOOMOO_READ_CONTEXT_PROBE_OK = "MOOMOO_READ_CONTEXT_PROBE_OK"
    MOOMOO_READ_CONTEXT_PROBE_FAILED = "MOOMOO_READ_CONTEXT_PROBE_FAILED"
    MOOMOO_READ_CONTEXT_NOT_FOUND = "MOOMOO_READ_CONTEXT_NOT_FOUND"
    MOOMOO_SELECTED_READ_CONTEXT_MISSING = "MOOMOO_SELECTED_READ_CONTEXT_MISSING"
    MOOMOO_ACCINFO_QUERY_OK = "MOOMOO_ACCINFO_QUERY_OK"
    MOOMOO_POSITION_QUERY_OK = "MOOMOO_POSITION_QUERY_OK"
    MOOMOO_PARTIAL_READ_ONLY_FETCH_OK = "MOOMOO_PARTIAL_READ_ONLY_FETCH_OK"
    MOOMOO_NORMALIZED_ROWS_EMPTY = "MOOMOO_NORMALIZED_ROWS_EMPTY"
    MOOMOO_READ_ONLY_FETCH_OK = "MOOMOO_READ_ONLY_FETCH_OK"
    MOOMOO_READ_ONLY_FETCH_FAILED = "MOOMOO_READ_ONLY_FETCH_FAILED"
    TIGER_CONFIG_DIR_MISSING = "TIGER_CONFIG_DIR_MISSING"
    TIGER_CONFIG_FILE_MISSING = "TIGER_CONFIG_FILE_MISSING"
    TIGER_CONFIG_PREFLIGHT_FAILED = "TIGER_CONFIG_PREFLIGHT_FAILED"
    TIGER_CONFIG_FILE_UNREADABLE = "TIGER_CONFIG_FILE_UNREADABLE"
    TIGER_CONFIG_FILE_INSIDE_REPO = "TIGER_CONFIG_FILE_INSIDE_REPO"
    TIGER_CONFIG_FILE_TRACKED = "TIGER_CONFIG_FILE_TRACKED"
    TIGER_CONFIG_HISTORY_RISK = "TIGER_CONFIG_HISTORY_RISK"
    TIGER_CONFIG_REQUIRED_KEY_MISSING = "TIGER_CONFIG_REQUIRED_KEY_MISSING"
    TIGER_CONFIG_LOAD_FAILED = "TIGER_CONFIG_LOAD_FAILED"
    TIGER_PRIVATE_KEY_FIELD_MISSING = "TIGER_PRIVATE_KEY_FIELD_MISSING"
    TIGER_PRIVATE_KEY_FORMAT_UNKNOWN = "TIGER_PRIVATE_KEY_FORMAT_UNKNOWN"
    TIGER_PROPS_PATH_MISMATCH = "TIGER_PROPS_PATH_MISMATCH"
    TIGER_CONFIG_PREFLIGHT_OK = "TIGER_CONFIG_PREFLIGHT_OK"
    TIGER_SDK_CONFIG_PROBE_FAILED = "TIGER_SDK_CONFIG_PROBE_FAILED"
    TIGER_PROPS_PATH_MODE_FAILED = "TIGER_PROPS_PATH_MODE_FAILED"
    TIGER_PROPS_PATH_DIRECTORY_FAILED = "TIGER_PROPS_PATH_DIRECTORY_FAILED"
    TIGER_PROPS_PATH_FILE_FAILED = "TIGER_PROPS_PATH_FILE_FAILED"
    TIGER_SDK_DEFAULT_CONFIG_FAILED = "TIGER_SDK_DEFAULT_CONFIG_FAILED"
    TIGER_EXPLICIT_CONFIG_OBJECT_FAILED = "TIGER_EXPLICIT_CONFIG_OBJECT_FAILED"
    TIGER_SDK_CONFIG_CONSTRUCTED = "TIGER_SDK_CONFIG_CONSTRUCTED"
    TIGER_SDK_CLIENT_CONSTRUCTED = "TIGER_SDK_CLIENT_CONSTRUCTED"
    TIGER_SDK_EXCEPTION_SANITIZED = "TIGER_SDK_EXCEPTION_SANITIZED"
    TIGER_OFFICIAL_DIRECTORY_CONFIG_FAILED = "TIGER_OFFICIAL_DIRECTORY_CONFIG_FAILED"
    TIGER_HELPER_CONFIG_FALLBACK_USED = "TIGER_HELPER_CONFIG_FALLBACK_USED"
    TIGER_HELPER_CONFIG_FALLBACK_FAILED = "TIGER_HELPER_CONFIG_FALLBACK_FAILED"
    TIGER_CONFIG_MODE_SELECTED = "TIGER_CONFIG_MODE_SELECTED"
    TIGER_PRIVATE_KEY_MISSING = "TIGER_PRIVATE_KEY_MISSING"
    TIGER_PRIVATE_KEY_FORMAT_INVALID = "TIGER_PRIVATE_KEY_FORMAT_INVALID"
    TIGER_ACCOUNT_MISSING = "TIGER_ACCOUNT_MISSING"
    TIGER_CLIENT_INIT_FAILED = "TIGER_CLIENT_INIT_FAILED"
    TIGER_CLIENT_AUTH_FAILED = "TIGER_CLIENT_AUTH_FAILED"
    TIGER_ACCOUNT_CONTEXT_EMPTY = "TIGER_ACCOUNT_CONTEXT_EMPTY"
    TIGER_ASSETS_QUERY_FAILED = "TIGER_ASSETS_QUERY_FAILED"
    TIGER_POSITIONS_QUERY_FAILED = "TIGER_POSITIONS_QUERY_FAILED"
    TIGER_CASH_QUERY_FAILED = "TIGER_CASH_QUERY_FAILED"
    TIGER_NO_DATA_RETURNED = "TIGER_NO_DATA_RETURNED"
    TIGER_READ_SUCCEEDED_EMPTY = "TIGER_READ_SUCCEEDED_EMPTY"
    TIGER_NORMALIZATION_FAILED = "TIGER_NORMALIZATION_FAILED"
    TIGER_DATA_PATH_NOT_IMPLEMENTED = "TIGER_DATA_PATH_NOT_IMPLEMENTED"


LEDGER_FIELDNAMES = [
    "provider",
    "account_id_hash",
    "asset_id",
    "asset_type",
    "symbol",
    "name",
    "quantity",
    "currency",
    "market_value",
    "cost_basis",
    "unrealized_pnl",
    "liquidity_bucket",
    "risk_bucket",
    "source_timestamp",
    "source_confidence",
    "needs_review",
    "warning_codes",
    "notes",
]


@dataclass(frozen=True)
class ProviderStatus:
    provider_name: str
    provider_level: ProviderLevel
    connection_mode: ConnectionMode
    read_only: bool = True
    trading_enabled: bool = False
    order_placement_enabled: bool = False
    credentials_source: str = "environment_variables"
    last_sync_time: str | None = None
    warning_codes: list[WarningCode] = field(default_factory=list)
    raw_snapshot_path: str | None = None
    normalized_positions: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "provider_name": self.provider_name,
            "provider_level": self.provider_level.value,
            "connection_mode": self.connection_mode.value,
            "read_only": self.read_only,
            "trading_enabled": self.trading_enabled,
            "order_placement_enabled": self.order_placement_enabled,
            "credentials_source": self.credentials_source,
            "last_sync_time": self.last_sync_time,
            "warning_codes": [code.value for code in self.warning_codes],
            "raw_snapshot_path": self.raw_snapshot_path,
            "normalized_positions": self.normalized_positions,
        }
        if self.diagnostics:
            payload["diagnostics"] = self.diagnostics
        return payload


@dataclass(frozen=True)
class RawAccount:
    account_id: str
    account_type: str = "unknown"
    currency: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class RawCash:
    account_id: str
    currency: str
    amount: float
    source_timestamp: str
    notes: str = ""


@dataclass(frozen=True)
class RawPosition:
    account_id: str
    asset_id: str
    asset_type: str
    symbol: str
    name: str
    quantity: float
    currency: str | None
    market_value: float | None
    cost_basis: float | None = None
    unrealized_pnl: float | None = None
    liquidity_bucket: str = "unknown"
    risk_bucket: str = "unknown"
    source_timestamp: str = ""
    source_confidence: str = "manual"
    needs_review: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class RawBalance:
    account_id: str
    asset_id: str
    asset_type: str
    name: str
    currency: str | None
    amount: float | None
    source_timestamp: str
    liquidity_bucket: str = "liability"
    risk_bucket: str = "liability"
    source_confidence: str = "manual"
    needs_review: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class RawProviderSnapshot:
    provider_name: str
    status: ProviderStatus
    accounts: list[RawAccount] = field(default_factory=list)
    cash: list[RawCash] = field(default_factory=list)
    positions: list[RawPosition] = field(default_factory=list)
    balances: list[RawBalance] = field(default_factory=list)

    def has_data(self) -> bool:
        return bool(self.accounts or self.cash or self.positions or self.balances)


@dataclass(frozen=True)
class NormalizedAsset:
    provider: str
    account_id_hash: str
    asset_id: str
    asset_type: str
    symbol: str
    name: str
    quantity: float | None
    currency: str | None
    market_value: float | None
    cost_basis: float | None
    unrealized_pnl: float | None
    liquidity_bucket: str
    risk_bucket: str
    source_timestamp: str
    source_confidence: str
    needs_review: bool
    warning_codes: list[WarningCode]
    notes: str = ""

    def to_csv_row(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "account_id_hash": self.account_id_hash,
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "symbol": self.symbol,
            "name": self.name,
            "quantity": _stringify_number(self.quantity),
            "currency": self.currency or "",
            "market_value": _stringify_number(self.market_value),
            "cost_basis": _stringify_number(self.cost_basis),
            "unrealized_pnl": _stringify_number(self.unrealized_pnl),
            "liquidity_bucket": self.liquidity_bucket,
            "risk_bucket": self.risk_bucket,
            "source_timestamp": self.source_timestamp,
            "source_confidence": self.source_confidence,
            "needs_review": str(self.needs_review).lower(),
            "warning_codes": ";".join(code.value for code in self.warning_codes),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class RiskSummary:
    total_assets: float
    total_liabilities: float
    net_worth: float
    liquid_assets: float
    investable_assets: float
    provider_coverage_ratio: float
    manual_asset_share: float
    currency_exposure: dict[str, float]
    warning_codes: list[WarningCode]


def _stringify_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"
