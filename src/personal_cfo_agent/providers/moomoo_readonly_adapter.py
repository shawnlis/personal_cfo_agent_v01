"""Guarded Moomoo/Futu OpenD read-only adapter with lazy SDK import."""

from __future__ import annotations

import io
import importlib
import inspect
import logging
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.normalizer import hash_account_id
from personal_cfo_agent.providers.moomoo_account_discovery import (
    open_moomoo_discovered_context,
    run_moomoo_account_discovery,
)
from personal_cfo_agent.providers.moomoo_models import (
    MoomooAccountRow,
    MoomooCashRow,
    MoomooPositionRow,
    MoomooReadDiagnostics,
    MoomooReadOnlySnapshot,
)


class MoomooSDKNotInstalledError(RuntimeError):
    pass


class _MoomooError(RuntimeError):
    def __init__(self, message: str, diagnostics: MoomooReadDiagnostics | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class MoomooConnectionError(_MoomooError):
    pass


class MoomooFetchError(_MoomooError):
    pass


@dataclass
class _DiagnosticState:
    sdk_import_ok: bool = False
    opend_socket_reachable: bool = False
    discovery_success: bool = False
    context_opened: bool = False
    account_list_query_attempted: bool = False
    account_list_query_success: bool = False
    account_count_redacted: int = 0
    selected_account_hash: str | None = None
    selected_context_mode: str | None = None
    account_filter_mismatch: bool = False
    account_info_query_attempted: bool = False
    account_info_query_success: bool = False
    accinfo_query_attempted: bool = False
    accinfo_query_success: bool = False
    position_query_attempted: bool = False
    position_query_success: bool = False
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

    def add_warning(self, code: WarningCode) -> None:
        if code not in self.warning_codes:
            self.warning_codes.append(code)

    def add_warnings(self, codes: list[WarningCode]) -> None:
        for code in codes:
            self.add_warning(code)

    def fail(self, stage: str, summary: str, codes: list[WarningCode]) -> None:
        self.stage_failures[stage] = summary
        self.add_warnings(codes)

    def to_diagnostics(self) -> MoomooReadDiagnostics:
        return MoomooReadDiagnostics(
            sdk_import_ok=self.sdk_import_ok,
            opend_socket_reachable=self.opend_socket_reachable,
            discovery_success=self.discovery_success,
            context_opened=self.context_opened,
            account_list_query_attempted=self.account_list_query_attempted,
            account_list_query_success=self.account_list_query_success,
            account_count_redacted=self.account_count_redacted,
            selected_account_hash=self.selected_account_hash,
            selected_context_mode=self.selected_context_mode,
            account_filter_mismatch=self.account_filter_mismatch,
            account_info_query_attempted=self.account_info_query_attempted,
            account_info_query_success=self.account_info_query_success,
            accinfo_query_attempted=self.accinfo_query_attempted,
            accinfo_query_success=self.accinfo_query_success,
            position_query_attempted=self.position_query_attempted,
            position_query_success=self.position_query_success,
            position_count=self.position_count,
            cash_query_attempted=self.cash_query_attempted,
            cash_query_success=self.cash_query_success,
            cash_currency_count=self.cash_currency_count,
            normalized_rows=self.normalized_rows,
            sdk_output_suppressed=self.sdk_output_suppressed,
            forbidden_api_called=self.forbidden_api_called,
            timeout_seconds=self.timeout_seconds,
            terminal_warning_codes=_dedupe_warning_codes(self.terminal_warning_codes),
            variant_warning_codes=_dedupe_warning_codes(self.variant_warning_codes),
            warning_codes=_dedupe_warning_codes(self.warning_codes),
            stage_failures=dict(self.stage_failures),
        )


class MoomooReadOnlyAdapter:
    """Collects account data from a manually started OpenD session."""

    def __init__(
        self,
        host: str,
        port: int,
        account_id: str = "moomoo_default",
        account_hash_salt: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.account_id = account_id
        self.account_hash_salt = account_hash_salt
        self.timeout_seconds = timeout_seconds

    def collect(self) -> MoomooReadOnlySnapshot:
        sdk = _load_sdk()
        _quiet_sdk_logging(sdk)
        state = _DiagnosticState(
            sdk_import_ok=True,
            sdk_output_suppressed=True,
            timeout_seconds=self.timeout_seconds,
        )
        state.add_warning(WarningCode.MOOMOO_SDK_OUTPUT_SUPPRESSED)
        context = None
        source_timestamp = datetime.now(timezone.utc).isoformat()

        discovery = run_moomoo_account_discovery(self._discovery_env())
        state.opend_socket_reachable = discovery.opend_socket_reachable
        state.discovery_success = discovery.discovery_success
        state.account_list_query_attempted = True
        state.account_list_query_success = discovery.discovery_success
        state.account_count_redacted = discovery.account_count_redacted
        state.selected_account_hash = discovery.selected_account_hash
        state.selected_context_mode = discovery.selected_context_mode
        state.terminal_warning_codes = list(discovery.terminal_warning_codes)
        state.variant_warning_codes = list(discovery.variant_warning_codes)
        state.add_warnings(list(discovery.warning_codes))

        selected_account_id = discovery.selected_account_id
        if not discovery.discovery_success or not selected_account_id:
            if discovery.account_count_redacted == 0:
                state.add_warning(WarningCode.MOOMOO_ACCOUNT_LIST_EMPTY)
                state.add_warning(WarningCode.MOOMOO_NO_DATA_RETURNED)
            state.fail(
                "account_discovery",
                "Account discovery did not select a usable account",
                [
                    WarningCode.MOOMOO_SELECTED_ACCOUNT_MISSING,
                    WarningCode.MOOMOO_READ_ONLY_FETCH_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise MoomooFetchError(
                "Moomoo account discovery failed", state.to_diagnostics()
            )
        if self.account_id != "moomoo_default" and selected_account_id != self.account_id:
            state.account_filter_mismatch = True
            state.fail(
                "account_filter",
                "Configured account filter not found in selected account context",
                [
                    WarningCode.MOOMOO_ACCOUNT_FILTER_MISMATCH,
                    WarningCode.MOOMOO_READ_ONLY_FETCH_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise MoomooFetchError(
                "Moomoo account filter mismatch", state.to_diagnostics()
            )

        try:
            with _suppress_sdk_console_output():
                context = open_moomoo_discovered_context(
                    sdk,
                    discovery,
                    host=self.host,
                    port=self.port,
                )
            state.opend_socket_reachable = True
            state.context_opened = True
        except Exception as exc:  # pragma: no cover - exercised with live OpenD only
            state.fail(
                "context_open",
                "SDK context open failed",
                [
                    WarningCode.MOOMOO_CONTEXT_OPEN_FAILED,
                    WarningCode.MOOMOO_OPEND_UNREACHABLE,
                    WarningCode.MOOMOO_CONNECTION_FAILED,
                    WarningCode.PROVIDER_CONNECTION_FAILED,
                ],
            )
            raise MoomooConnectionError(
                "Moomoo OpenD connection failed", state.to_diagnostics()
            ) from exc

        cash_rows: list[MoomooCashRow] = []
        position_rows: list[MoomooPositionRow] = []
        try:
            with _suppress_sdk_console_output():
                cash_rows = self._collect_cash(
                    context, sdk, source_timestamp, selected_account_id, state
                )
                position_rows = self._collect_positions(
                    context, sdk, source_timestamp, selected_account_id, state
                )
        except MoomooFetchError as exc:
            if exc.diagnostics is not None:
                raise
            state.add_warning(WarningCode.PROVIDER_FETCH_FAILED)
            raise MoomooFetchError(
                "Moomoo read requests failed", state.to_diagnostics()
            ) from exc
        except Exception as exc:  # pragma: no cover - exercised with live OpenD only
            state.fail(
                "fetch",
                f"SDK read stage raised {_safe_exception_name(exc)}",
                [WarningCode.MOOMOO_CALLBACK_TIMEOUT, WarningCode.PROVIDER_FETCH_FAILED],
            )
            raise MoomooFetchError(
                "Moomoo read requests failed", state.to_diagnostics()
            ) from exc
        finally:
            close = getattr(context, "close", None)
            if callable(close):
                with _suppress_sdk_console_output():
                    close()

        currencies = [row.currency for row in cash_rows if row.currency]
        account_currency = currencies[0] if currencies else None
        state.position_count = len(position_rows)
        state.cash_currency_count = len({row.currency for row in cash_rows if row.currency})
        state.normalized_rows = len(cash_rows) + len(position_rows)
        state.add_warnings(
            _data_path_warnings(
                state=state,
                cash_rows=cash_rows,
                position_rows=position_rows,
            )
        )
        if state.normalized_rows:
            state.add_warning(WarningCode.MOOMOO_READ_ONLY_FETCH_OK)
        else:
            state.add_warning(WarningCode.MOOMOO_READ_ONLY_FETCH_FAILED)
            state.add_warning(WarningCode.MOOMOO_NORMALIZED_ROWS_EMPTY)
        if (
            not state.account_info_query_success
            and not state.position_query_success
            and not state.normalized_rows
        ):
            state.add_warning(WarningCode.PROVIDER_FETCH_FAILED)
            raise MoomooFetchError("Moomoo read requests failed", state.to_diagnostics())
        return MoomooReadOnlySnapshot(
            accounts=[
                MoomooAccountRow(
                    account_id=selected_account_id,
                    currency=account_currency,
                    notes="Moomoo OpenD read-only account",
                )
            ],
            cash=cash_rows,
            positions=position_rows,
            diagnostics=state.to_diagnostics(),
        )

    def _discovery_env(self) -> dict[str, str]:
        return {
            "CFO_MOOMOO_ENABLED": "true",
            "CFO_MOOMOO_HOST": self.host,
            "CFO_MOOMOO_PORT": str(self.port),
            "CFO_ACCOUNT_HASH_SALT": self.account_hash_salt or "",
        }

    def _collect_account_ids(
        self, context: Any, sdk: Any, state: "_DiagnosticState"
    ) -> list[str]:
        query = _first_callable(context, ["acc_list_query", "get_acc_list"])
        if query is None:
            state.fail(
                "account_list",
                "SDK account list query unavailable",
                [WarningCode.MOOMOO_ACCOUNT_LIST_FAILED, WarningCode.PROVIDER_FETCH_FAILED],
            )
            raise MoomooFetchError("Moomoo account list query unavailable")
        state.account_list_query_attempted = True
        ret_code, data = query()
        if ret_code != _ret_ok(sdk):
            state.fail(
                "account_list",
                "SDK returned nonzero ret code",
                [WarningCode.MOOMOO_ACCOUNT_LIST_FAILED, WarningCode.PROVIDER_FETCH_FAILED],
            )
            raise MoomooFetchError("Moomoo account list query failed", state.to_diagnostics())
        account_ids: list[str] = []
        for row in _rows(data):
            account_id = _first_value(row, ["acc_id", "accID", "account_id", "account"], "")
            if account_id:
                account_ids.append(str(account_id))
        state.account_list_query_success = True
        state.account_count_redacted = len(account_ids)
        return account_ids

    def _select_account_id(
        self, account_ids: list[str], state: "_DiagnosticState"
    ) -> str:
        if self.account_id != "moomoo_default":
            if account_ids and self.account_id not in account_ids:
                state.account_filter_mismatch = True
                state.fail(
                    "account_filter",
                    "Configured account filter not found in account list",
                    [
                        WarningCode.MOOMOO_ACCOUNT_FILTER_MISMATCH,
                        WarningCode.PROVIDER_FETCH_FAILED,
                    ],
                )
                raise MoomooFetchError(
                    "Moomoo account filter mismatch", state.to_diagnostics()
                )
            selected = self.account_id
        elif account_ids:
            selected = account_ids[0]
        else:
            selected = self.account_id
        if selected != "moomoo_default":
            state.selected_account_hash = hash_account_id(selected, self.account_hash_salt)
        return selected

    def _collect_cash(
        self,
        context: Any,
        sdk: Any,
        source_timestamp: str,
        account_id: str,
        state: "_DiagnosticState",
    ) -> list[MoomooCashRow]:
        query = _first_callable(context, ["accinfo_query"])
        if query is None:
            state.fail(
                "account_info",
                "SDK account info query unavailable",
                [
                    WarningCode.MOOMOO_ACCOUNT_INFO_FAILED,
                    WarningCode.MOOMOO_ACCINFO_QUERY_FAILED,
                    WarningCode.MOOMOO_CASH_QUERY_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            return []
        state.account_info_query_attempted = True
        state.accinfo_query_attempted = True
        state.cash_query_attempted = True
        try:
            ret_code, data = _call_account_query(
                query,
                sdk,
                account_id=account_id,
                state=state,
                stage="account_info",
            )
        except Exception as exc:
            state.fail(
                "account_info",
                f"SDK account info query raised {_safe_exception_name(exc)}",
                [
                    WarningCode.MOOMOO_ACCOUNT_INFO_FAILED,
                    WarningCode.MOOMOO_ACCINFO_QUERY_FAILED,
                    WarningCode.MOOMOO_CASH_QUERY_FAILED,
                    *_unlock_warning(exc),
                ],
            )
            return []
        if ret_code != _ret_ok(sdk):
            state.fail(
                "account_info",
                "SDK returned nonzero ret code",
                [
                    WarningCode.MOOMOO_ACCOUNT_INFO_FAILED,
                    WarningCode.MOOMOO_ACCINFO_QUERY_FAILED,
                    WarningCode.MOOMOO_CASH_QUERY_FAILED,
                    *_unlock_warning(data),
                ],
            )
            return []
        rows = _rows(data)
        cash_rows: list[MoomooCashRow] = []
        # accinfo_query returns account funds data, usually one row per account
        # query, not a generic cash-currency row list. Keep this mapping narrow
        # and synthetic-fixture tested before relying on live cash normalization.
        for row in rows:
            for field_name, currency in _cash_field_currency_pairs(row):
                cash_amount = _float_value(row.get(field_name))
                if cash_amount is None:
                    continue
                cash_rows.append(
                    MoomooCashRow(
                        account_id=account_id,
                        currency=currency,
                        amount=cash_amount,
                        source_timestamp=source_timestamp,
                        notes="Moomoo OpenD account info cash",
                    )
                )
        state.account_info_query_success = True
        state.accinfo_query_success = True
        state.cash_query_success = True
        state.cash_currency_count = len({row.currency for row in cash_rows if row.currency})
        if rows and not cash_rows:
            state.add_warning(WarningCode.MOOMOO_CASH_NORMALIZATION_SHAPE_WARNING)
        if not rows:
            state.add_warning(WarningCode.MOOMOO_FUNDS_DATA_EMPTY)
        return cash_rows

    def _collect_positions(
        self,
        context: Any,
        sdk: Any,
        source_timestamp: str,
        account_id: str,
        state: "_DiagnosticState",
    ) -> list[MoomooPositionRow]:
        query = _first_callable(context, ["position_list_query"])
        if query is None:
            state.fail(
                "positions",
                "SDK position query unavailable",
                [
                    WarningCode.MOOMOO_POSITION_LIST_FAILED,
                    WarningCode.MOOMOO_POSITION_QUERY_FAILED,
                ],
            )
            return []
        state.position_query_attempted = True
        try:
            ret_code, data = _call_account_query(
                query,
                sdk,
                account_id=account_id,
                state=state,
                stage="positions",
            )
        except Exception as exc:
            state.fail(
                "positions",
                f"SDK position query raised {_safe_exception_name(exc)}",
                [
                    WarningCode.MOOMOO_POSITION_LIST_FAILED,
                    WarningCode.MOOMOO_POSITION_QUERY_FAILED,
                    *_unlock_warning(exc),
                ],
            )
            return []
        if ret_code != _ret_ok(sdk):
            state.fail(
                "positions",
                "SDK returned nonzero ret code",
                [
                    WarningCode.MOOMOO_POSITION_LIST_FAILED,
                    WarningCode.MOOMOO_POSITION_QUERY_FAILED,
                    *_unlock_warning(data),
                ],
            )
            return []
        positions: list[MoomooPositionRow] = []
        for row in _rows(data):
            code = str(_first_value(row, ["code", "stock_code", "symbol"], ""))
            name = str(_first_value(row, ["stock_name", "name"], code))
            quantity = _first_float(row, ["qty", "quantity", "can_sell_qty"]) or 0.0
            market_value = _first_float(row, ["market_val", "market_value"])
            cost_basis = _first_float(row, ["cost_price", "average_cost"])
            currency = _first_value(row, ["currency"], None)
            positions.append(
                MoomooPositionRow(
                    account_id=account_id,
                    asset_id=f"MOOMOO-{code}",
                    asset_type="equity",
                    symbol=code,
                    name=name,
                    quantity=quantity,
                    currency=str(currency) if currency else None,
                    market_value=market_value,
                    cost_basis=cost_basis,
                    source_timestamp=source_timestamp,
                    notes="Moomoo OpenD position list",
                )
            )
        state.position_query_success = True
        state.position_count = len(positions)
        if not positions:
            state.add_warning(WarningCode.MOOMOO_POSITION_DATA_EMPTY)
        return positions


def _load_sdk() -> Any:
    try:
        return importlib.import_module("futu")
    except ImportError as exc:
        raise MoomooSDKNotInstalledError("futu is not installed") from exc


def _quiet_sdk_logging(sdk: Any) -> None:
    logger = getattr(
        getattr(getattr(sdk, "common", None), "ft_logger", None),
        "logger",
        None,
    )
    if logger is None:
        return
    for attr in ("console_level", "file_level"):
        try:
            setattr(logger, attr, logging.WARNING)
        except Exception:
            continue


@contextmanager
def _suppress_sdk_console_output():
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        yield


def _first_callable(context: Any, names: list[str]) -> Any | None:
    for name in names:
        candidate = getattr(context, name, None)
        if callable(candidate):
            return candidate
    return None


def _ret_ok(sdk: Any) -> Any:
    return getattr(sdk, "RET_OK", 0)


def _real_env(sdk: Any) -> Any:
    trd_env = getattr(sdk, "TrdEnv", None)
    return getattr(trd_env, "REAL", "REAL")


def _call_account_query(
    query: Any,
    sdk: Any,
    *,
    account_id: str,
    state: _DiagnosticState,
    stage: str,
) -> tuple[Any, Any]:
    kwargs: dict[str, Any] = {}
    supported = _supported_query_kwargs(query)
    _set_supported_kwarg(kwargs, supported, "trd_env", _real_env(sdk))
    if _set_first_supported_kwarg(
        kwargs,
        supported,
        ["acc_id", "accID", "accId", "accid"],
        account_id,
    ):
        return query(**kwargs)
    if _kwarg_supported(supported, "acc_index") and not account_id:
        kwargs["acc_index"] = 0
        state.add_warning(WarningCode.MOOMOO_ACC_INDEX_FALLBACK_USED)
        return query(**kwargs)
    return query(**kwargs)


def _supported_query_kwargs(query: Any) -> set[str] | None:
    try:
        signature = inspect.signature(query)
    except (TypeError, ValueError):
        return None
    parameters = signature.parameters
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return None
    return set(parameters)


def _query_accepts_any_kwargs(supported: set[str] | None) -> bool:
    return supported is None


def _kwarg_supported(supported: set[str] | None, name: str) -> bool:
    return supported is None or name in supported


def _set_supported_kwarg(
    kwargs: dict[str, Any], supported: set[str] | None, name: str, value: Any
) -> bool:
    if not _kwarg_supported(supported, name):
        return False
    kwargs[name] = value
    return True


def _set_first_supported_kwarg(
    kwargs: dict[str, Any],
    supported: set[str] | None,
    names: list[str],
    value: Any,
) -> bool:
    if supported is None:
        kwargs[names[0]] = value
        return True
    for name in names:
        if name in supported:
            kwargs[name] = value
            return True
    return False


def _rows(data: Any) -> list[dict[str, Any]]:
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        return list(to_dict("records"))
    if isinstance(data, list):
        return [dict(row) for row in data]
    if isinstance(data, dict):
        return [dict(data)]
    return []


def _first_value(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return default


def _first_float(row: dict[str, Any], keys: list[str]) -> float | None:
    value = _first_value(row, keys)
    return _float_value(value)


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cash_field_currency_pairs(row: dict[str, Any]) -> list[tuple[str, str]]:
    pairs = [
        ("hk_cash", "HKD"),
        ("us_cash", "USD"),
        ("sg_cash", "SGD"),
        ("jp_cash", "JPY"),
        ("au_cash", "AUD"),
        ("ca_cash", "CAD"),
        ("my_cash", "MYR"),
        ("cnh_cash", "CNH"),
    ]
    available = [(field_name, currency) for field_name, currency in pairs if field_name in row]
    if "cash" in row:
        currency = str(_first_value(row, ["currency", "cash_currency"], "UNKNOWN"))
        available.insert(0, ("cash", currency))
    return available


def _unlock_warning(value: Any) -> list[WarningCode]:
    text = str(value).lower()
    if "unlock" in text or "password" in text:
        return [WarningCode.MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW]
    return []


def _data_path_warnings(
    *,
    state: _DiagnosticState,
    cash_rows: list[MoomooCashRow],
    position_rows: list[MoomooPositionRow],
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if not (
        state.account_list_query_attempted
        or state.cash_query_attempted
        or state.position_query_attempted
    ):
        warnings.append(WarningCode.MOOMOO_DATA_PATH_NOT_IMPLEMENTED)
    if state.account_list_query_success and state.account_count_redacted == 0:
        warnings.append(WarningCode.MOOMOO_ACCOUNT_LIST_EMPTY)
    if state.position_query_success and not position_rows:
        warnings.append(WarningCode.MOOMOO_POSITION_LIST_EMPTY)
        warnings.append(WarningCode.MOOMOO_POSITIONS_EMPTY)
        warnings.append(WarningCode.MOOMOO_POSITION_DATA_EMPTY)
    if state.cash_query_success and not cash_rows:
        warnings.append(WarningCode.MOOMOO_CASH_EMPTY)
        warnings.append(WarningCode.MOOMOO_CASH_NORMALIZATION_SHAPE_WARNING)
    if not state.cash_query_attempted or not state.position_query_attempted:
        warnings.append(WarningCode.MOOMOO_CALLBACK_TIMEOUT)
    if not cash_rows and not position_rows:
        warnings.extend(
            [
                WarningCode.MOOMOO_NO_DATA_RETURNED,
                WarningCode.MOOMOO_READ_SUCCEEDED_EMPTY,
                WarningCode.MOOMOO_NORMALIZED_ROWS_EMPTY,
            ]
        )
    return _dedupe_warning_codes(warnings)


def _safe_exception_name(exc: Exception) -> str:
    return exc.__class__.__name__


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
