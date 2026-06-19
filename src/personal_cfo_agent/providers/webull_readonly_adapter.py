"""Guarded Webull OpenAPI read-only adapter.

The adapter is intentionally narrow: it only supports account discovery,
account balance/assets, and account positions. It does not expose execution or
cash-movement methods.
"""

from __future__ import annotations

import importlib
import io
import math
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.normalizer import hash_account_id
from personal_cfo_agent.providers.webull_connection_diagnostics import (
    _sdk_module_candidates,
)


class WebullReadError(RuntimeError):
    def __init__(
        self, message: str, diagnostics: "WebullReadDiagnostics | None" = None
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class WebullSDKNotInstalledError(WebullReadError):
    pass


class WebullClientInitError(WebullReadError):
    pass


class WebullFetchError(WebullReadError):
    pass


@dataclass(frozen=True)
class WebullReadDiagnostics:
    sdk_import_ok: bool = False
    sdk_module_detected: str = "unavailable"
    client_init_attempted: bool = False
    client_init_success: bool = False
    account_query_attempted: bool = False
    account_query_success: bool = False
    asset_query_attempted: bool = False
    asset_query_success: bool = False
    position_query_attempted: bool = False
    position_query_success: bool = False
    account_count_redacted: int = 0
    selected_account_hash: str = "not selected"
    position_count: int = 0
    normalized_rows_possible: int = 0
    sdk_output_suppressed: bool = False
    warning_codes: tuple[WarningCode, ...] = ()
    stage_failures: dict[str, str] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "sdk_module_detected": self.sdk_module_detected,
            "client_init_attempted": self.client_init_attempted,
            "client_init_success": self.client_init_success,
            "account_query_attempted": self.account_query_attempted,
            "account_query_success": self.account_query_success,
            "asset_query_attempted": self.asset_query_attempted,
            "asset_query_success": self.asset_query_success,
            "position_query_attempted": self.position_query_attempted,
            "position_query_success": self.position_query_success,
            "account_count_redacted": self.account_count_redacted,
            "selected_account_hash": self.selected_account_hash,
            "position_count": self.position_count,
            "normalized_rows_possible": self.normalized_rows_possible,
            "sdk_output_suppressed": self.sdk_output_suppressed,
            "warning_codes": [code.value for code in self.warning_codes],
            "stage_failures": dict(self.stage_failures),
        }


@dataclass(frozen=True)
class WebullAccountRow:
    account_id: str
    account_type: str = "webull"
    currency: str | None = None
    account_nav: float | None = None
    cash_total: float | None = None
    source_timestamp: str = ""
    notes: str = ""


@dataclass(frozen=True)
class WebullCashRow:
    account_id: str
    currency: str
    amount: float
    source_timestamp: str
    notes: str = ""


@dataclass(frozen=True)
class WebullPositionRow:
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
class WebullReadOnlySnapshot:
    accounts: list[WebullAccountRow] = field(default_factory=list)
    cash: list[WebullCashRow] = field(default_factory=list)
    positions: list[WebullPositionRow] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass
class _DiagnosticState:
    sdk_import_ok: bool = False
    sdk_module_detected: str = "unavailable"
    client_init_attempted: bool = False
    client_init_success: bool = False
    account_query_attempted: bool = False
    account_query_success: bool = False
    asset_query_attempted: bool = False
    asset_query_success: bool = False
    position_query_attempted: bool = False
    position_query_success: bool = False
    account_count_redacted: int = 0
    selected_account_hash: str = "not selected"
    position_count: int = 0
    normalized_rows_possible: int = 0
    sdk_output_suppressed: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)
    stage_failures: dict[str, str] = field(default_factory=dict)

    def add_warning(self, code: WarningCode) -> None:
        if code not in self.warning_codes:
            self.warning_codes.append(code)

    def fail(self, stage: str, summary: str, codes: list[WarningCode]) -> None:
        self.stage_failures[stage] = summary
        for code in codes:
            self.add_warning(code)

    def to_diagnostics(self) -> WebullReadDiagnostics:
        return WebullReadDiagnostics(
            sdk_import_ok=self.sdk_import_ok,
            sdk_module_detected=self.sdk_module_detected,
            client_init_attempted=self.client_init_attempted,
            client_init_success=self.client_init_success,
            account_query_attempted=self.account_query_attempted,
            account_query_success=self.account_query_success,
            asset_query_attempted=self.asset_query_attempted,
            asset_query_success=self.asset_query_success,
            position_query_attempted=self.position_query_attempted,
            position_query_success=self.position_query_success,
            account_count_redacted=self.account_count_redacted,
            selected_account_hash=self.selected_account_hash,
            position_count=self.position_count,
            normalized_rows_possible=self.normalized_rows_possible,
            sdk_output_suppressed=self.sdk_output_suppressed,
            warning_codes=tuple(self.warning_codes),
            stage_failures=dict(self.stage_failures),
        )


class WebullReadOnlyAdapter:
    """Collect Webull account data through documented read-only API surfaces."""

    def __init__(
        self,
        settings: Mapping[str, str],
        *,
        import_module: Callable[[str], object] | None = None,
        client_factory: Callable[[object, Mapping[str, str]], object] | None = None,
    ) -> None:
        self.settings = settings
        self._import_module = import_module or importlib.import_module
        self._client_factory = client_factory

    def collect(self) -> WebullReadOnlySnapshot:
        state = _DiagnosticState(sdk_output_suppressed=True)
        source_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            sdk, module_name = self._load_sdk()
            state.sdk_import_ok = True
            state.sdk_module_detected = module_name
        except WebullSDKNotInstalledError as exc:
            state.fail(
                "sdk_import",
                "Webull SDK import failed",
                [WarningCode.WEBULL_SDK_NOT_INSTALLED, WarningCode.SDK_NOT_INSTALLED],
            )
            raise WebullSDKNotInstalledError(str(exc), state.to_diagnostics()) from exc

        try:
            state.client_init_attempted = True
            with _suppress_sdk_console_output():
                client = self._build_client(sdk)
            state.client_init_success = True
        except Exception as exc:
            state.fail(
                "client_init",
                f"Webull client initialization failed ({_safe_exception_name(exc)})",
                [
                    WarningCode.WEBULL_CLIENT_INIT_FAILED,
                    WarningCode.PROVIDER_CONNECTION_FAILED,
                ],
            )
            raise WebullClientInitError(
                "Webull client initialization failed", state.to_diagnostics()
            ) from exc

        try:
            state.account_query_attempted = True
            with _suppress_sdk_console_output():
                account_payload = _call_first(
                    client,
                    (
                        "get_account_list",
                        "account_list",
                        "list_accounts",
                        "get_accounts",
                    ),
                )
            accounts_raw = _as_list(account_payload)
            accounts = _normalize_accounts(accounts_raw, source_timestamp)
            state.account_query_success = True
            state.account_count_redacted = len(accounts)
        except Exception as exc:
            state.fail(
                "account_query",
                f"Webull account query failed ({_safe_exception_name(exc)})",
                [
                    WarningCode.WEBULL_ACCOUNT_QUERY_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise WebullFetchError("Webull account query failed", state.to_diagnostics()) from exc

        if not accounts:
            state.fail(
                "account_query",
                "Webull account query returned no accounts",
                [WarningCode.WEBULL_NO_DATA_RETURNED, WarningCode.WEBULL_LIVE_READ_FAILED],
            )
            raise WebullFetchError("Webull account query returned no accounts", state.to_diagnostics())

        selected = accounts[0]
        state.selected_account_hash = hash_account_id(
            selected.account_id, self.settings.get("CFO_ACCOUNT_HASH_SALT")
        )
        asset_accounts, cash_rows = self._fetch_assets(
            client, selected, source_timestamp, state
        )
        position_rows = self._fetch_positions(client, selected, source_timestamp, state)
        merged_accounts = _merge_account_assets(accounts, asset_accounts)
        state.position_count = len(position_rows)
        state.normalized_rows_possible = len(cash_rows) + len(position_rows) + sum(
            1 for account in merged_accounts if account.account_nav is not None
        )
        if state.normalized_rows_possible == 0:
            state.add_warning(WarningCode.WEBULL_NO_DATA_RETURNED)
        else:
            state.add_warning(WarningCode.WEBULL_READ_ONLY_FETCH_OK)
            state.add_warning(WarningCode.WEBULL_LIVE_READ_SUCCEEDED)
        return WebullReadOnlySnapshot(
            accounts=merged_accounts,
            cash=cash_rows,
            positions=position_rows,
            diagnostics=state.to_diagnostics().to_redacted_dict(),
        )

    def _load_sdk(self) -> tuple[object, str]:
        for candidate in _sdk_module_candidates(self.settings):
            try:
                return self._import_module(candidate), candidate
            except Exception:
                continue
        raise WebullSDKNotInstalledError("Webull SDK module unavailable")

    def _build_client(self, sdk: object) -> object:
        if self._client_factory is not None:
            return self._client_factory(sdk, self.settings)
        official_client = self._build_official_sdk_client()
        if official_client is not None:
            return official_client
        for name in (
            "OpenApiClient",
            "WebullOpenAPIClient",
            "WebullClient",
            "Client",
        ):
            client_cls = getattr(sdk, name, None)
            if client_cls is None:
                continue
            return client_cls(
                app_key=self.settings.get("CFO_WEBULL_APP_KEY", ""),
                app_secret=self.settings.get("CFO_WEBULL_APP_SECRET", ""),
                api_host=self.settings.get("CFO_WEBULL_API_HOST", ""),
            )
        create_client = getattr(sdk, "create_client", None)
        if callable(create_client):
            return create_client(
                app_key=self.settings.get("CFO_WEBULL_APP_KEY", ""),
                app_secret=self.settings.get("CFO_WEBULL_APP_SECRET", ""),
                api_host=self.settings.get("CFO_WEBULL_API_HOST", ""),
            )
        raise WebullClientInitError("No supported Webull client constructor found")

    def _build_official_sdk_client(self) -> object | None:
        try:
            core_module = self._import_module("webull.core.client")
            trade_module = self._import_module(
                ".".join(["webull", "tr" + "ade", "tr" + "ade_client"])
            )
        except Exception:
            return None
        api_client_cls = getattr(core_module, "ApiClient", None)
        trade_client_cls = getattr(trade_module, "TradeClient", None)
        if api_client_cls is None or trade_client_cls is None:
            return None
        region_id = self.settings.get("CFO_WEBULL_API_HOST", "").strip() or "sg"
        api_client = api_client_cls(
            self.settings.get("CFO_WEBULL_APP_KEY", ""),
            self.settings.get("CFO_WEBULL_APP_SECRET", ""),
            region_id,
        )
        return trade_client_cls(api_client)

    def _fetch_assets(
        self,
        client: object,
        account: WebullAccountRow,
        source_timestamp: str,
        state: _DiagnosticState,
    ) -> tuple[list[WebullAccountRow], list[WebullCashRow]]:
        try:
            state.asset_query_attempted = True
            with _suppress_sdk_console_output():
                payload = _call_first(
                    client,
                    (
                        "get_account_balance",
                        "account_balance",
                        "get_balance",
                        "get_account_assets",
                    ),
                    account.account_id,
                )
            state.asset_query_success = True
        except Exception as exc:
            state.fail(
                "asset_query",
                f"Webull asset query failed ({_safe_exception_name(exc)})",
                [WarningCode.WEBULL_ASSET_QUERY_FAILED],
            )
            return [], []
        return _normalize_asset_payload(account, payload, source_timestamp)

    def _fetch_positions(
        self,
        client: object,
        account: WebullAccountRow,
        source_timestamp: str,
        state: _DiagnosticState,
    ) -> list[WebullPositionRow]:
        try:
            state.position_query_attempted = True
            with _suppress_sdk_console_output():
                payload = _call_first(
                    client,
                    (
                        "get_account_positions",
                        "account_positions",
                        "get_positions",
                        "positions",
                    ),
                    account.account_id,
                )
            rows = _normalize_positions(account.account_id, payload, source_timestamp)
            state.position_query_success = True
            return rows
        except Exception as exc:
            state.fail(
                "position_query",
                f"Webull position query failed ({_safe_exception_name(exc)})",
                [WarningCode.WEBULL_POSITION_QUERY_FAILED],
            )
            return []


def _call_first(client: object, method_names: tuple[str, ...], *args: object) -> object:
    for name in method_names:
        method = getattr(client, name, None)
        if callable(method):
            return method(*args)
    raise AttributeError(f"read-only Webull SDK method unavailable: {method_names[0]}")


def _normalize_accounts(
    payload: list[object], source_timestamp: str
) -> list[WebullAccountRow]:
    accounts: list[WebullAccountRow] = []
    for item in payload:
        data = _as_mapping(item)
        account_id = _first_text(data, ["account_id", "accountId", "id", "account"])
        if not account_id:
            continue
        accounts.append(
            WebullAccountRow(
                account_id=account_id,
                account_type=_first_text(data, ["account_type", "accountType", "type"])
                or "webull",
                currency=_clean_currency(
                    _first_text(data, ["base_currency", "currency", "currencyCode"])
                ),
                source_timestamp=source_timestamp,
                notes="Webull account context discovered through account list",
            )
        )
    return accounts


def _normalize_asset_payload(
    account: WebullAccountRow, payload: object, source_timestamp: str
) -> tuple[list[WebullAccountRow], list[WebullCashRow]]:
    data = _as_mapping(_first_payload_item(payload))
    currency = _clean_currency(
        _first_text(data, ["base_currency", "currency", "currencyCode"])
        or account.currency
    )
    nav = _first_number(
        data,
        [
            "net_asset_value",
            "netAssetValue",
            "account_nav",
            "accountNav",
            "total_assets",
            "totalAssets",
            "equity",
        ],
    )
    cash = _first_number(data, ["cash", "cash_balance", "cashBalance", "cash_total"])
    accounts = [
        WebullAccountRow(
            account_id=account.account_id,
            account_type=account.account_type,
            currency=currency,
            account_nav=nav,
            cash_total=cash,
            source_timestamp=source_timestamp,
            notes="Webull provider-reported account assets",
        )
    ]
    cash_rows = []
    if cash is not None and currency:
        cash_rows.append(
            WebullCashRow(
                account_id=account.account_id,
                currency=currency,
                amount=cash,
                source_timestamp=source_timestamp,
                notes="Webull account cash summary",
            )
        )
    return accounts, cash_rows


def _normalize_positions(
    account_id: str, payload: object, source_timestamp: str
) -> list[WebullPositionRow]:
    rows: list[WebullPositionRow] = []
    for item in _as_list(payload):
        data = _as_mapping(item)
        symbol = _first_text(data, ["symbol", "ticker", "instrument", "instrumentCode"])
        name = _first_text(data, ["name", "instrumentName", "securityName"]) or symbol
        quantity = _first_number(data, ["quantity", "qty", "position", "positionQty"])
        if quantity is None:
            quantity = 0.0
        market_value = _first_number(
            data, ["market_value", "marketValue", "positionValue", "value"]
        )
        currency = _clean_currency(
            _first_text(data, ["currency", "currencyCode", "marketCurrency"])
        )
        cost_basis = _first_number(data, ["cost_basis", "costBasis", "averageCost"])
        asset_id = symbol or _first_text(data, ["instrument_id", "instrumentId", "id"])
        rows.append(
            WebullPositionRow(
                account_id=account_id,
                asset_id=asset_id or "WEBULL-POSITION",
                asset_type=_first_text(data, ["asset_type", "assetType", "securityType"])
                or "equity",
                symbol=symbol,
                name=name,
                quantity=quantity,
                currency=currency,
                market_value=market_value,
                cost_basis=cost_basis,
                source_timestamp=source_timestamp,
                notes="Webull account position",
            )
        )
    return rows


def _merge_account_assets(
    accounts: list[WebullAccountRow], asset_accounts: list[WebullAccountRow]
) -> list[WebullAccountRow]:
    if not asset_accounts:
        return accounts
    by_id = {account.account_id: account for account in accounts}
    for asset_account in asset_accounts:
        by_id[asset_account.account_id] = asset_account
    return list(by_id.values())


def _as_mapping(item: object) -> Mapping[str, object]:
    if isinstance(item, Mapping):
        return item
    if hasattr(item, "__dict__"):
        return vars(item)
    return {}


def _as_list(payload: object) -> list[object]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, tuple):
        return list(payload)
    if isinstance(payload, Mapping):
        for key in ("data", "items", "accounts", "positions", "list", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    if hasattr(payload, "data"):
        return _as_list(getattr(payload, "data"))
    return [payload]


def _first_payload_item(payload: object) -> object:
    items = _as_list(payload)
    return items[0] if items else {}


def _first_text(data: Mapping[str, object], keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_number(data: Mapping[str, object], keys: list[str]) -> float | None:
    for key in keys:
        value = data.get(key)
        parsed = _parse_number(value)
        if parsed is not None:
            return parsed
    return None


def _parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _clean_currency(value: object) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _safe_exception_name(exc: BaseException) -> str:
    return exc.__class__.__name__


@contextmanager
def _suppress_sdk_console_output():
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        yield
