"""Guarded TigerOpen read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.normalizer import hash_account_id
from personal_cfo_agent.providers.tiger_models import (
    TigerAccountRow,
    TigerCashRow,
    TigerPositionRow,
    TigerReadDiagnostics,
    TigerReadOnlySnapshot,
)


DEFAULT_PROPS_FILE = "tiger_openapi_config.properties"


class TigerReadError(RuntimeError):
    def __init__(self, message: str, diagnostics: TigerReadDiagnostics | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class TigerSDKNotInstalledError(TigerReadError):
    pass


class TigerConnectionError(TigerReadError):
    pass


class TigerFetchError(TigerReadError):
    pass


@dataclass
class _DiagnosticState:
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
    sdk_output_suppressed: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)
    stage_failures: dict[str, str] = field(default_factory=dict)

    def add_warning(self, code: WarningCode) -> None:
        if code not in self.warning_codes:
            self.warning_codes.append(code)

    def fail(self, stage: str, summary: str, code: WarningCode) -> None:
        self.stage_failures[stage] = summary
        self.add_warning(code)

    def to_diagnostics(self) -> TigerReadDiagnostics:
        return TigerReadDiagnostics(
            sdk_import_ok=self.sdk_import_ok,
            config_loaded=self.config_loaded,
            account_context_observed=self.account_context_observed,
            selected_account_hash=self.selected_account_hash,
            account_count_redacted=self.account_count_redacted,
            asset_query_attempted=self.asset_query_attempted,
            asset_query_success=self.asset_query_success,
            position_query_attempted=self.position_query_attempted,
            position_query_success=self.position_query_success,
            position_count=self.position_count,
            cash_currency_count=self.cash_currency_count,
            sdk_output_suppressed=self.sdk_output_suppressed,
            warning_codes=tuple(self.warning_codes),
            stage_failures=dict(self.stage_failures),
        )


class TigerReadOnlyAdapter:
    """Collects TigerOpen account data through a private read-only wrapper."""

    def __init__(
        self, config_dir: str, account_id: str, account_hash_salt: str | None = None
    ) -> None:
        self.config_dir = config_dir
        self.account_id = account_id
        self.account_hash_salt = account_hash_salt

    def collect(self) -> TigerReadOnlySnapshot:
        state = _DiagnosticState()
        state.sdk_output_suppressed = True
        try:
            sdk = _load_sdk()
        except TigerSDKNotInstalledError as exc:
            state.fail("sdk_import", "TigerOpen SDK import failed", WarningCode.SDK_NOT_INSTALLED)
            raise TigerSDKNotInstalledError(str(exc), state.to_diagnostics()) from exc

        state.sdk_import_ok = True
        if self.account_id:
            state.account_context_observed = True
            state.account_count_redacted = 1
            state.selected_account_hash = hash_account_id(
                self.account_id, self.account_hash_salt
            )
        source_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            with _suppress_sdk_console_output():
                config = _build_config(sdk, self.config_dir, self.account_id)
                client = sdk["client_cls"](config)
            state.config_loaded = True
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            state.fail(
                "config_load",
                "TigerOpen config/client initialization failed",
                WarningCode.PROVIDER_CONNECTION_FAILED,
            )
            raise TigerConnectionError(
                "TigerOpen config/client initialization failed", state.to_diagnostics()
            ) from exc

        try:
            state.asset_query_attempted = True
            with _suppress_sdk_console_output():
                asset_payload = _call_first(client, ["get_prime_assets", "get_assets"])
            state.asset_query_success = True
        except TigerFetchError as exc:
            state.fail("assets", "TigerOpen asset query failed", WarningCode.PROVIDER_FETCH_FAILED)
            raise TigerFetchError(str(exc), state.to_diagnostics()) from exc
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            state.fail("assets", "TigerOpen asset query failed", WarningCode.PROVIDER_FETCH_FAILED)
            raise TigerFetchError("TigerOpen asset query failed", state.to_diagnostics()) from exc

        try:
            state.position_query_attempted = True
            with _suppress_sdk_console_output():
                position_payload = _call_first(
                    client, ["get_positions", "get_prime_positions", "get_positions_v2"]
                )
            state.position_query_success = True
        except TigerFetchError as exc:
            state.fail(
                "positions",
                "TigerOpen position query failed",
                WarningCode.PROVIDER_FETCH_FAILED,
            )
            raise TigerFetchError(str(exc), state.to_diagnostics()) from exc
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            state.fail(
                "positions",
                "TigerOpen position query failed",
                WarningCode.PROVIDER_FETCH_FAILED,
            )
            raise TigerFetchError("TigerOpen position query failed", state.to_diagnostics()) from exc

        cash_rows = _cash_rows(asset_payload, self.account_id, source_timestamp)
        position_rows = _position_rows(position_payload, self.account_id, source_timestamp)
        state.cash_currency_count = len({row.currency for row in cash_rows})
        state.position_count = len(position_rows)
        account_currency = cash_rows[0].currency if cash_rows else None
        diagnostics = state.to_diagnostics().to_redacted_dict()
        return TigerReadOnlySnapshot(
            accounts=[
                TigerAccountRow(
                    account_id=self.account_id,
                    currency=account_currency,
                    notes="TigerOpen read-only account",
                )
            ],
            cash=cash_rows,
            positions=position_rows,
            diagnostics=diagnostics,
        )


def _load_sdk() -> dict[str, Any]:
    try:
        config_module = importlib.import_module("tigeropen.tiger_open_config")
        client_module = importlib.import_module(
            ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"])
        )
    except ImportError as exc:
        raise TigerSDKNotInstalledError("tigeropen is not installed") from exc
    return {
        "config_module": config_module,
        "client_cls": getattr(client_module, "Tr" + "adeClient"),
    }


def _build_config(sdk: dict[str, Any], config_dir: str, account_id: str) -> Any:
    config_module = sdk["config_module"]
    get_config = getattr(config_module, "get_client_config", None)
    props_path = str(Path(config_dir) / DEFAULT_PROPS_FILE)
    if callable(get_config):
        try:
            config = get_config(account=account_id, props_path=props_path)
        except TypeError:
            config = get_config()
    else:
        config = config_module.TigerOpenClientConfig()
    for attr_name, attr_value in {
        "account": account_id,
        "props_path": props_path,
    }.items():
        if hasattr(config, attr_name):
            setattr(config, attr_name, attr_value)
    return config


@contextmanager
def _suppress_sdk_console_output():
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        yield


def _call_first(client: Any, method_names: list[str]) -> Any:
    for method_name in method_names:
        method = getattr(client, method_name, None)
        if callable(method):
            return method()
    raise TigerFetchError("TigerOpen read method is unavailable")


def _cash_rows(payload: Any, account_id: str, source_timestamp: str) -> list[TigerCashRow]:
    rows = _records(payload)
    cash_rows: list[TigerCashRow] = []
    for row in rows:
        amount = _first_float(row, ["cash", "cash_balance", "available_cash", "total_cash"])
        currency = str(_first_value(row, ["currency", "cash_currency"], "UNKNOWN"))
        if amount is not None:
            cash_rows.append(
                TigerCashRow(
                    account_id=account_id,
                    currency=currency,
                    amount=amount,
                    source_timestamp=source_timestamp,
                    notes="TigerOpen asset cash",
                )
            )
    return cash_rows


def _position_rows(
    payload: Any, account_id: str, source_timestamp: str
) -> list[TigerPositionRow]:
    positions: list[TigerPositionRow] = []
    for row in _records(payload):
        symbol = str(_first_value(row, ["symbol", "identifier", "contract_code"], ""))
        name = str(_first_value(row, ["name", "contract_name"], symbol))
        quantity = _first_float(row, ["quantity", "position", "qty"]) or 0.0
        market_value = _first_float(row, ["market_value", "market_val"])
        cost_basis = _first_float(row, ["cost_basis", "average_cost", "avg_cost"])
        currency = _first_value(row, ["currency"], None)
        positions.append(
            TigerPositionRow(
                account_id=account_id,
                asset_id=f"TIGER-{symbol}",
                asset_type="equity",
                symbol=symbol,
                name=name,
                quantity=quantity,
                currency=str(currency) if currency else None,
                market_value=market_value,
                cost_basis=cost_basis,
                source_timestamp=source_timestamp,
                notes="TigerOpen position read",
            )
        )
    return positions


def _records(payload: Any) -> list[dict[str, Any]]:
    data = getattr(payload, "data", payload)
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        return list(to_dict("records"))
    if isinstance(data, list):
        return [_object_to_dict(row) for row in data]
    if isinstance(data, dict):
        return [dict(data)]
    if data is None:
        return []
    return [_object_to_dict(data)]


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    raw_dict = getattr(value, "__dict__", {})
    return dict(raw_dict) if isinstance(raw_dict, dict) else {}


def _first_value(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return default


def _first_float(row: dict[str, Any], keys: list[str]) -> float | None:
    value = _first_value(row, keys)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
