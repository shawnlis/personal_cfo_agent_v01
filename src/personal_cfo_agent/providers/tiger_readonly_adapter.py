"""Guarded TigerOpen read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
import io
import os
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
from personal_cfo_agent.providers.tiger_connection_diagnostics import (
    DEFAULT_PROPS_FILE,
    _read_config_metadata,
)


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
    config_dir_exists: bool = False
    config_file_exists: bool = False
    config_loaded: bool = False
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
    sdk_output_suppressed: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)
    stage_failures: dict[str, str] = field(default_factory=dict)

    def add_warning(self, code: WarningCode) -> None:
        if code not in self.warning_codes:
            self.warning_codes.append(code)

    def add_warnings(self, codes: list[WarningCode]) -> None:
        for code in codes:
            self.add_warning(code)

    def fail(self, stage: str, summary: str, codes: list[WarningCode]) -> None:
        self.stage_failures[stage] = summary
        self.add_warnings(codes)

    def to_diagnostics(self) -> TigerReadDiagnostics:
        return TigerReadDiagnostics(
            sdk_import_ok=self.sdk_import_ok,
            config_dir_exists=self.config_dir_exists,
            config_file_exists=self.config_file_exists,
            config_loaded=self.config_loaded,
            tiger_id_present_redacted=self.tiger_id_present_redacted,
            account_present_redacted=self.account_present_redacted,
            private_key_present_redacted=self.private_key_present_redacted,
            private_key_format_detected_redacted=self.private_key_format_detected_redacted,
            client_init_attempted=self.client_init_attempted,
            client_init_success=self.client_init_success,
            client_auth_success=self.client_auth_success,
            account_context_observed=self.account_context_observed,
            selected_account_hash=self.selected_account_hash,
            account_count_redacted=self.account_count_redacted,
            assets_query_attempted=self.assets_query_attempted,
            assets_query_success=self.assets_query_success,
            positions_query_attempted=self.positions_query_attempted,
            positions_query_success=self.positions_query_success,
            position_count=self.position_count,
            cash_query_attempted=self.cash_query_attempted,
            cash_query_success=self.cash_query_success,
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
        props_path = Path(self.config_dir) / DEFAULT_PROPS_FILE
        _record_static_config_state(
            state, self.config_dir, self.account_id, self.account_hash_salt
        )
        if not state.config_dir_exists:
            state.fail(
                "config_dir",
                "TigerOpen config directory is missing",
                [
                    WarningCode.TIGER_CONFIG_DIR_MISSING,
                    WarningCode.PROVIDER_CONFIG_MISSING,
                ],
            )
            raise TigerConnectionError("TigerOpen config directory missing", state.to_diagnostics())
        if not state.config_file_exists:
            state.fail(
                "config_file",
                "TigerOpen config file is missing",
                [
                    WarningCode.TIGER_CONFIG_FILE_MISSING,
                    WarningCode.PROVIDER_CONFIG_MISSING,
                ],
            )
            raise TigerConnectionError("TigerOpen config file missing", state.to_diagnostics())

        try:
            sdk = _load_sdk()
        except TigerSDKNotInstalledError as exc:
            state.fail("sdk_import", "TigerOpen SDK import failed", [WarningCode.SDK_NOT_INSTALLED])
            raise TigerSDKNotInstalledError(str(exc), state.to_diagnostics()) from exc

        state.sdk_import_ok = True
        source_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            with _suppress_sdk_console_output():
                config = _build_config(sdk, self.config_dir, self.account_id)
            state.config_loaded = True
            _record_loaded_config_state(state, config)
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            state.fail(
                "config_load",
                f"TigerOpen config load failed ({_safe_exception_name(exc)})",
                [
                    WarningCode.TIGER_CONFIG_LOAD_FAILED,
                    *_config_failure_codes(exc),
                    WarningCode.PROVIDER_CONNECTION_FAILED,
                ],
            )
            raise TigerConnectionError(
                "TigerOpen config load failed", state.to_diagnostics()
            ) from exc

        _validate_loaded_config_state(state)
        if state.stage_failures:
            raise TigerConnectionError("TigerOpen config validation failed", state.to_diagnostics())

        try:
            state.client_init_attempted = True
            with _suppress_sdk_console_output():
                client = sdk["client_cls"](config)
            state.client_init_success = True
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            code = _client_failure_code(exc)
            stage = "client_auth" if code == WarningCode.TIGER_CLIENT_AUTH_FAILED else "client_init"
            summary = (
                "TigerOpen client auth failed"
                if code == WarningCode.TIGER_CLIENT_AUTH_FAILED
                else "TigerOpen client initialization failed"
            )
            state.fail(
                stage,
                f"{summary} ({_safe_exception_name(exc)})",
                [code, WarningCode.PROVIDER_CONNECTION_FAILED],
            )
            raise TigerConnectionError(summary, state.to_diagnostics()) from exc

        try:
            state.assets_query_attempted = True
            with _suppress_sdk_console_output():
                asset_payload = _call_first(client, ["get_prime_assets", "get_assets"])
            state.assets_query_success = True
            state.client_auth_success = True
        except TigerFetchError as exc:
            state.fail(
                "assets",
                "TigerOpen asset query failed",
                [
                    WarningCode.TIGER_ASSETS_QUERY_FAILED,
                    WarningCode.TIGER_CASH_QUERY_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise TigerFetchError(str(exc), state.to_diagnostics()) from exc
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            state.fail(
                "assets",
                f"TigerOpen asset query failed ({_safe_exception_name(exc)})",
                [
                    _query_failure_code(exc, WarningCode.TIGER_ASSETS_QUERY_FAILED),
                    WarningCode.TIGER_CASH_QUERY_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise TigerFetchError("TigerOpen asset query failed", state.to_diagnostics()) from exc

        try:
            state.positions_query_attempted = True
            with _suppress_sdk_console_output():
                position_payload = _call_first(
                    client, ["get_positions", "get_prime_positions", "get_positions_v2"]
                )
            state.positions_query_success = True
            state.client_auth_success = True
        except TigerFetchError as exc:
            state.fail(
                "positions",
                "TigerOpen position query failed",
                [
                    WarningCode.TIGER_POSITIONS_QUERY_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise TigerFetchError(str(exc), state.to_diagnostics()) from exc
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            state.fail(
                "positions",
                f"TigerOpen position query failed ({_safe_exception_name(exc)})",
                [
                    _query_failure_code(exc, WarningCode.TIGER_POSITIONS_QUERY_FAILED),
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise TigerFetchError("TigerOpen position query failed", state.to_diagnostics()) from exc

        try:
            state.cash_query_attempted = True
            cash_rows = _cash_rows(asset_payload, self.account_id, source_timestamp)
            state.cash_query_success = True
        except Exception as exc:
            state.fail(
                "cash",
                f"TigerOpen cash parsing failed ({_safe_exception_name(exc)})",
                [WarningCode.TIGER_CASH_QUERY_FAILED, WarningCode.PROVIDER_FETCH_FAILED],
            )
            raise TigerFetchError("TigerOpen cash query failed", state.to_diagnostics()) from exc
        position_rows = _position_rows(position_payload, self.account_id, source_timestamp)
        state.cash_currency_count = len({row.currency for row in cash_rows})
        state.position_count = len(position_rows)
        if not cash_rows and not position_rows:
            state.add_warnings(
                [WarningCode.TIGER_NO_DATA_RETURNED, WarningCode.TIGER_READ_SUCCEEDED_EMPTY]
            )
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
    config_cls = getattr(config_module, "TigerOpenClientConfig", None)
    get_config = getattr(config_module, "get_client_config", None)
    props_path = str(Path(config_dir) / DEFAULT_PROPS_FILE)
    if callable(config_cls):
        try:
            config = config_cls(enable_dynamic_domain=False, props_path=props_path)
        except TypeError:
            config = config_cls(props_path=props_path)
    elif callable(get_config):
        try:
            config = get_config(
                account=account_id,
                enable_dynamic_domain=False,
                props_path=props_path,
            )
        except TypeError:
            config = get_config()
    else:
        raise TigerConnectionError("TigerOpen config class is unavailable")
    for attr_name, attr_value in {
        "account": account_id,
        "props_path": props_path,
    }.items():
        if hasattr(config, attr_name):
            setattr(config, attr_name, attr_value)
    return config


def _record_static_config_state(
    state: _DiagnosticState,
    config_dir: str,
    account_id: str,
    account_hash_salt: str | None,
) -> None:
    config_dir_path = Path(config_dir)
    props_path = config_dir_path / DEFAULT_PROPS_FILE
    state.config_dir_exists = config_dir_path.exists() and config_dir_path.is_dir()
    state.config_file_exists = props_path.exists() and props_path.is_file()
    metadata = _read_config_metadata(props_path)
    state.tiger_id_present_redacted = bool(
        os.environ.get("TIGEROPEN_TIGER_ID") or metadata.get("tiger_id_present")
    )
    state.account_present_redacted = bool(
        account_id or os.environ.get("TIGEROPEN_ACCOUNT") or metadata.get("account_present")
    )
    state.private_key_present_redacted = bool(
        os.environ.get("TIGEROPEN_PRIVATE_KEY") or metadata.get("private_key_present")
    )
    state.private_key_format_detected_redacted = str(
        metadata.get("private_key_format_detected") or "missing"
    )
    if os.environ.get("TIGEROPEN_PRIVATE_KEY") and state.private_key_format_detected_redacted == "missing":
        state.private_key_format_detected_redacted = "env_present"
    if account_id:
        state.account_context_observed = True
        state.account_count_redacted = 1
        state.selected_account_hash = hash_account_id(account_id, account_hash_salt)


def _record_loaded_config_state(state: _DiagnosticState, config: Any) -> None:
    tiger_id = getattr(config, "tiger_id", None)
    account = getattr(config, "account", None)
    key_material = getattr(config, "private_key", None)
    if tiger_id:
        state.tiger_id_present_redacted = True
    if account:
        state.account_present_redacted = True
        state.account_context_observed = True
        state.account_count_redacted = 1
        if state.selected_account_hash == "not configured":
            state.selected_account_hash = hash_account_id(str(account), None)
    if key_material:
        state.private_key_present_redacted = True
        detected = _detect_private_key_value_format(str(key_material))
        if detected != "unknown":
            state.private_key_format_detected_redacted = detected


def _validate_loaded_config_state(state: _DiagnosticState) -> None:
    if not state.account_present_redacted:
        state.fail(
            "account_context",
            "Tiger account context is empty",
            [
                WarningCode.TIGER_ACCOUNT_MISSING,
                WarningCode.TIGER_ACCOUNT_CONTEXT_EMPTY,
                WarningCode.PROVIDER_CONFIG_MISSING,
            ],
        )
    if not state.private_key_present_redacted:
        state.fail(
            "private_key",
            "Tiger private key is missing",
            [
                WarningCode.TIGER_PRIVATE_KEY_MISSING,
                WarningCode.PROVIDER_CONFIG_MISSING,
            ],
        )
    if state.private_key_present_redacted and state.private_key_format_detected_redacted == "unknown":
        state.fail(
            "private_key",
            "Tiger private key format is invalid or unsupported",
            [
                WarningCode.TIGER_PRIVATE_KEY_FORMAT_INVALID,
                WarningCode.PROVIDER_CONFIG_MISSING,
            ],
        )


def _safe_exception_name(exc: BaseException) -> str:
    return exc.__class__.__name__


def _config_failure_codes(exc: BaseException) -> list[WarningCode]:
    category = _exception_category(exc)
    if category == "private_key_missing":
        return [WarningCode.TIGER_PRIVATE_KEY_MISSING]
    if category == "private_key_format":
        return [WarningCode.TIGER_PRIVATE_KEY_FORMAT_INVALID]
    if category == "account":
        return [WarningCode.TIGER_ACCOUNT_MISSING]
    return [WarningCode.TIGER_CONFIG_LOAD_FAILED]


def _client_failure_code(exc: BaseException) -> WarningCode:
    if _exception_category(exc) == "auth":
        return WarningCode.TIGER_CLIENT_AUTH_FAILED
    return WarningCode.TIGER_CLIENT_INIT_FAILED


def _query_failure_code(exc: BaseException, default: WarningCode) -> WarningCode:
    if _exception_category(exc) == "auth":
        return WarningCode.TIGER_CLIENT_AUTH_FAILED
    return default


def _exception_category(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__} {str(exc)}".lower()
    if "private" in text and "key" in text and any(term in text for term in ("missing", "not found", "empty")):
        return "private_key_missing"
    if "private" in text and "key" in text:
        return "private_key_format"
    if "account" in text and any(term in text for term in ("missing", "empty", "invalid")):
        return "account"
    if any(term in text for term in ("auth", "permission", "unauthor", "forbidden", "license", "signature", "401", "403")):
        return "auth"
    return "unknown"


def _detect_private_key_value_format(value: str) -> str:
    lowered = value.lower()
    if "begin rsa private key" in lowered:
        return "pkcs1"
    if "begin private key" in lowered:
        return "pkcs8"
    return "unknown"


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
