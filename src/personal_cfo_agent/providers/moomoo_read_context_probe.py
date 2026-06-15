"""Redacted Moomoo read-context probe using the discovered account only."""

from __future__ import annotations

import importlib
import inspect
import io
import logging
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.providers.moomoo_account_discovery import (
    MoomooAccountDiscoveryDiagnostics,
    run_moomoo_account_discovery,
)


_READ_FILTER_NAMES = ("HK", "US", "SG", "NONE")
_CASH_FIELD_NAMES = (
    "cash",
    "hk_cash",
    "us_cash",
    "sg_cash",
    "jp_cash",
    "au_cash",
    "ca_cash",
    "my_cash",
    "cnh_cash",
)


@dataclass(frozen=True)
class MoomooReadContextCandidateDiagnostics:
    context_mode: str
    accinfo_query_success: bool = False
    position_query_success: bool = False
    position_count: int = 0
    cash_field_count_detected: int = 0
    normalized_rows_possible: int = 0
    warning_codes: list[WarningCode] = field(default_factory=list)
    accinfo_sdk_ret_code_sanitized: str | None = None
    accinfo_exception_category_sanitized: str | None = None
    position_sdk_ret_code_sanitized: str | None = None
    position_exception_category_sanitized: str | None = None
    filter_name: str | None = field(default=None, repr=False, compare=False)
    security_firm_name: str | None = field(default=None, repr=False, compare=False)
    need_general_sec_acc: bool = field(default=False, repr=False, compare=False)
    need_general_arg_name: str | None = field(default=None, repr=False, compare=False)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "context_mode": self.context_mode,
            "accinfo_query_success": self.accinfo_query_success,
            "position_query_success": self.position_query_success,
            "position_count": self.position_count,
            "cash_field_count_detected": self.cash_field_count_detected,
            "normalized_rows_possible": self.normalized_rows_possible,
            "warning_codes": [code.value for code in self.warning_codes],
            "accinfo_sdk_ret_code_sanitized": self.accinfo_sdk_ret_code_sanitized,
            "accinfo_exception_category_sanitized": (
                self.accinfo_exception_category_sanitized
            ),
            "position_sdk_ret_code_sanitized": self.position_sdk_ret_code_sanitized,
            "position_exception_category_sanitized": (
                self.position_exception_category_sanitized
            ),
        }


@dataclass(frozen=True)
class MoomooReadContextProbeDiagnostics:
    sdk_import_ok: bool = False
    opend_socket_reachable: bool = False
    discovery_success: bool = False
    account_count_redacted: int = 0
    selected_account_hash: str | None = None
    selected_discovery_context_mode: str | None = None
    selected_read_context_mode: str | None = None
    accinfo_query_success: bool = False
    position_query_success: bool = False
    position_count: int = 0
    cash_field_count_detected: int = 0
    normalized_rows_possible: int = 0
    candidate_contexts: list[MoomooReadContextCandidateDiagnostics] = field(
        default_factory=list
    )
    terminal_warning_codes: list[WarningCode] = field(default_factory=list)
    variant_warning_codes: list[WarningCode] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)
    forbidden_api_called: bool = False
    selected_account_id: str | None = field(default=None, repr=False, compare=False)
    selected_filter_name: str | None = field(default=None, repr=False, compare=False)
    selected_security_firm_name: str | None = field(
        default=None, repr=False, compare=False
    )
    selected_need_general_sec_acc: bool = field(
        default=False, repr=False, compare=False
    )
    selected_need_general_arg_name: str | None = field(
        default=None, repr=False, compare=False
    )

    @property
    def probe_success(self) -> bool:
        return self.selected_read_context_mode is not None

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "opend_socket_reachable": self.opend_socket_reachable,
            "discovery_success": self.discovery_success,
            "account_count_redacted": self.account_count_redacted,
            "selected_account_hash": self.selected_account_hash,
            "selected_discovery_context_mode": self.selected_discovery_context_mode,
            "selected_read_context_mode": self.selected_read_context_mode,
            "accinfo_query_success": self.accinfo_query_success,
            "position_query_success": self.position_query_success,
            "position_count": self.position_count,
            "cash_field_count_detected": self.cash_field_count_detected,
            "normalized_rows_possible": self.normalized_rows_possible,
            "candidate_contexts": [
                candidate.to_redacted_dict() for candidate in self.candidate_contexts
            ],
            "terminal_warning_codes": [
                code.value for code in self.terminal_warning_codes
            ],
            "variant_warning_codes": [code.value for code in self.variant_warning_codes],
            "warning_codes": [code.value for code in self.warning_codes],
            "forbidden_api_called": self.forbidden_api_called,
        }


def run_moomoo_read_context_probe(
    env: Mapping[str, str],
    *,
    discovery: MoomooAccountDiscoveryDiagnostics | None = None,
) -> MoomooReadContextProbeDiagnostics:
    terminal_warnings: list[WarningCode] = []
    status_warnings: list[WarningCode] = [WarningCode.MOOMOO_SDK_OUTPUT_SUPPRESSED]
    variant_warnings: list[WarningCode] = []
    candidates: list[MoomooReadContextCandidateDiagnostics] = []

    if not env_bool(env, "CFO_MOOMOO_ENABLED"):
        terminal_warnings.append(WarningCode.PROVIDER_DISABLED)
        terminal_warnings.append(WarningCode.MOOMOO_READ_CONTEXT_PROBE_FAILED)
        return _build_result(
            terminal_warnings=terminal_warnings,
            status_warnings=status_warnings,
            variant_warnings=variant_warnings,
            candidates=candidates,
        )

    if discovery is None:
        discovery = run_moomoo_account_discovery(env)
    variant_warnings.extend(discovery.variant_warning_codes)
    sdk_import_ok = discovery.sdk_import_ok
    opend_reachable = discovery.opend_socket_reachable
    selected_account_id = discovery.selected_account_id

    if not discovery.discovery_success or not selected_account_id:
        terminal_warnings.extend(discovery.terminal_warning_codes)
        terminal_warnings.extend(
            [
                WarningCode.MOOMOO_SELECTED_ACCOUNT_MISSING,
                WarningCode.MOOMOO_READ_CONTEXT_PROBE_FAILED,
                WarningCode.MOOMOO_READ_CONTEXT_NOT_FOUND,
                WarningCode.MOOMOO_SELECTED_READ_CONTEXT_MISSING,
            ]
        )
        return _build_result(
            sdk_import_ok=sdk_import_ok,
            opend_socket_reachable=opend_reachable,
            discovery=discovery,
            terminal_warnings=terminal_warnings,
            status_warnings=status_warnings,
            variant_warnings=variant_warnings,
            candidates=candidates,
        )

    try:
        sdk = importlib.import_module("futu")
        _quiet_sdk_logging(sdk)
        sdk_import_ok = True
    except ImportError:
        terminal_warnings.extend(
            [
                WarningCode.MOOMOO_SDK_NOT_INSTALLED,
                WarningCode.SDK_NOT_INSTALLED,
                WarningCode.MOOMOO_READ_CONTEXT_PROBE_FAILED,
            ]
        )
        return _build_result(
            sdk_import_ok=False,
            opend_socket_reachable=opend_reachable,
            discovery=discovery,
            terminal_warnings=terminal_warnings,
            status_warnings=status_warnings,
            variant_warnings=variant_warnings,
            candidates=candidates,
        )

    host = str(env.get("CFO_MOOMOO_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    try:
        port = int(str(env.get("CFO_MOOMOO_PORT", "11111")).strip())
    except ValueError:
        terminal_warnings.extend(
            [
                WarningCode.PROVIDER_CONFIG_MISSING,
                WarningCode.MOOMOO_READ_CONTEXT_PROBE_FAILED,
            ]
        )
        return _build_result(
            sdk_import_ok=sdk_import_ok,
            opend_socket_reachable=opend_reachable,
            discovery=discovery,
            terminal_warnings=terminal_warnings,
            status_warnings=status_warnings,
            variant_warnings=variant_warnings,
            candidates=candidates,
        )

    for filter_name, filter_value in _read_filter_values(sdk):
        candidate = _probe_candidate(
            sdk=sdk,
            discovery=discovery,
            filter_name=filter_name,
            filter_value=filter_value,
            host=host,
            port=port,
        )
        candidates.append(candidate)

    selected = _select_candidate(candidates)
    if selected is None:
        terminal_warnings.extend(_candidate_terminal_warnings(candidates))
        terminal_warnings.extend(
            [
                WarningCode.MOOMOO_READ_CONTEXT_NOT_FOUND,
                WarningCode.MOOMOO_SELECTED_READ_CONTEXT_MISSING,
                WarningCode.MOOMOO_READ_CONTEXT_PROBE_FAILED,
                WarningCode.MOOMOO_READ_ONLY_FETCH_FAILED,
                WarningCode.MOOMOO_NORMALIZED_ROWS_EMPTY,
            ]
        )
    else:
        status_warnings.append(WarningCode.MOOMOO_READ_CONTEXT_PROBE_OK)
        if selected.accinfo_query_success and selected.position_query_success:
            status_warnings.append(WarningCode.MOOMOO_READ_ONLY_FETCH_OK)
        else:
            status_warnings.append(WarningCode.MOOMOO_PARTIAL_READ_ONLY_FETCH_OK)
            if not selected.accinfo_query_success:
                terminal_warnings.append(WarningCode.MOOMOO_ACCINFO_QUERY_FAILED)
            if not selected.position_query_success:
                terminal_warnings.append(WarningCode.MOOMOO_POSITION_QUERY_FAILED)
        if selected.normalized_rows_possible == 0:
            terminal_warnings.append(WarningCode.MOOMOO_NORMALIZED_ROWS_EMPTY)
        terminal_warnings.extend(
            code
            for code in selected.warning_codes
            if code is WarningCode.MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW
        )

    return _build_result(
        sdk_import_ok=sdk_import_ok,
        opend_socket_reachable=opend_reachable,
        discovery=discovery,
        terminal_warnings=terminal_warnings,
        status_warnings=status_warnings,
        variant_warnings=variant_warnings,
        candidates=candidates,
        selected=selected,
    )


def open_moomoo_read_context(
    sdk: Any,
    probe: MoomooReadContextProbeDiagnostics,
    *,
    host: str,
    port: int,
) -> Any:
    if probe.selected_filter_name is None or probe.selected_security_firm_name is None:
        raise RuntimeError("Moomoo selected read context is missing")
    context_factory = getattr(sdk, "OpenSecTradeContext")
    kwargs = _context_kwargs(
        sdk=sdk,
        context_factory=context_factory,
        host=host,
        port=port,
        filter_name=probe.selected_filter_name,
        filter_value=_enum_value(getattr(sdk, "TrdMarket", None), probe.selected_filter_name),
        security_firm_name=probe.selected_security_firm_name,
        need_general_sec_acc=probe.selected_need_general_sec_acc,
        need_general_arg_name=probe.selected_need_general_arg_name,
    )
    return context_factory(**kwargs)


def _probe_candidate(
    *,
    sdk: Any,
    discovery: MoomooAccountDiscoveryDiagnostics,
    filter_name: str,
    filter_value: Any,
    host: str,
    port: int,
) -> MoomooReadContextCandidateDiagnostics:
    warning_codes: list[WarningCode] = []
    accinfo_success = False
    position_success = False
    position_count = 0
    cash_field_count = 0
    accinfo_ret_code: str | None = None
    position_ret_code: str | None = None
    accinfo_exc_category: str | None = None
    position_exc_category: str | None = None
    context = None
    try:
        with _suppress_sdk_console_output():
            context = open_moomoo_candidate_context(
                sdk=sdk,
                discovery=discovery,
                filter_name=filter_name,
                filter_value=filter_value,
                host=host,
                port=port,
            )
            accinfo_success, accinfo_ret_code, accinfo_exc_category, cash_field_count, accinfo_warnings = (
                _probe_accinfo(context, sdk, str(discovery.selected_account_id))
            )
            position_success, position_ret_code, position_exc_category, position_count, position_warnings = (
                _probe_positions(context, sdk, str(discovery.selected_account_id))
            )
            warning_codes.extend(accinfo_warnings)
            warning_codes.extend(position_warnings)
    except Exception as exc:
        accinfo_exc_category = accinfo_exc_category or _safe_exception_name(exc)
        position_exc_category = position_exc_category or _safe_exception_name(exc)
        warning_codes.extend(
            [
                WarningCode.MOOMOO_READ_CONTEXT_PROBE_FAILED,
                *_unlock_warning(exc),
            ]
        )
    finally:
        close = getattr(context, "close", None)
        if callable(close):
            with _suppress_sdk_console_output():
                close()

    if accinfo_success:
        warning_codes.append(WarningCode.MOOMOO_ACCINFO_QUERY_OK)
    else:
        warning_codes.append(WarningCode.MOOMOO_ACCINFO_QUERY_FAILED)
    if position_success:
        warning_codes.append(WarningCode.MOOMOO_POSITION_QUERY_OK)
    else:
        warning_codes.append(WarningCode.MOOMOO_POSITION_QUERY_FAILED)
    normalized_rows_possible = cash_field_count + position_count
    if normalized_rows_possible == 0:
        warning_codes.append(WarningCode.MOOMOO_NORMALIZED_ROWS_EMPTY)
    if not accinfo_success and not position_success:
        warning_codes.append(WarningCode.MOOMOO_READ_ONLY_FETCH_FAILED)

    security_firm_name = discovery.selected_security_firm_name
    need_general_arg_name = discovery.selected_need_general_arg_name
    return MoomooReadContextCandidateDiagnostics(
        context_mode=_context_mode(
            filter_name=filter_name,
            security_firm_name=security_firm_name,
            need_general_sec_acc=discovery.selected_need_general_sec_acc,
        ),
        accinfo_query_success=accinfo_success,
        position_query_success=position_success,
        position_count=position_count,
        cash_field_count_detected=cash_field_count,
        normalized_rows_possible=normalized_rows_possible,
        warning_codes=_dedupe(warning_codes),
        accinfo_sdk_ret_code_sanitized=accinfo_ret_code,
        accinfo_exception_category_sanitized=accinfo_exc_category,
        position_sdk_ret_code_sanitized=position_ret_code,
        position_exception_category_sanitized=position_exc_category,
        filter_name=filter_name,
        security_firm_name=security_firm_name,
        need_general_sec_acc=discovery.selected_need_general_sec_acc,
        need_general_arg_name=need_general_arg_name,
    )


def open_moomoo_candidate_context(
    *,
    sdk: Any,
    discovery: MoomooAccountDiscoveryDiagnostics,
    filter_name: str,
    filter_value: Any,
    host: str,
    port: int,
) -> Any:
    context_factory = getattr(sdk, "OpenSecTradeContext")
    kwargs = _context_kwargs(
        sdk=sdk,
        context_factory=context_factory,
        host=host,
        port=port,
        filter_name=filter_name,
        filter_value=filter_value,
        security_firm_name=discovery.selected_security_firm_name,
        need_general_sec_acc=discovery.selected_need_general_sec_acc,
        need_general_arg_name=discovery.selected_need_general_arg_name,
    )
    return context_factory(**kwargs)


def _probe_accinfo(
    context: Any, sdk: Any, account_id: str
) -> tuple[bool, str | None, str | None, int, list[WarningCode]]:
    query = getattr(context, "accinfo_query", None)
    if not callable(query):
        return False, None, None, 0, [WarningCode.MOOMOO_ACCINFO_QUERY_FAILED]
    try:
        ret_code, data = _call_account_query(query, sdk, account_id=account_id)
    except Exception as exc:
        return (
            False,
            None,
            _safe_exception_name(exc),
            0,
            [WarningCode.MOOMOO_ACCINFO_QUERY_FAILED, *_unlock_warning(exc)],
        )
    if ret_code != _ret_ok(sdk):
        return (
            False,
            _sanitize_ret_code(ret_code),
            None,
            0,
            [WarningCode.MOOMOO_ACCINFO_QUERY_FAILED, *_unlock_warning(data)],
        )
    rows = _rows(data)
    cash_field_count = _cash_field_count(rows)
    warnings: list[WarningCode] = []
    if rows and cash_field_count == 0:
        warnings.append(WarningCode.MOOMOO_CASH_NORMALIZATION_SHAPE_WARNING)
    if not rows:
        warnings.append(WarningCode.MOOMOO_FUNDS_DATA_EMPTY)
    return True, _sanitize_ret_code(ret_code), None, cash_field_count, warnings


def _probe_positions(
    context: Any, sdk: Any, account_id: str
) -> tuple[bool, str | None, str | None, int, list[WarningCode]]:
    query = getattr(context, "position_list_query", None)
    if not callable(query):
        return False, None, None, 0, [WarningCode.MOOMOO_POSITION_QUERY_FAILED]
    try:
        ret_code, data = _call_account_query(query, sdk, account_id=account_id)
    except Exception as exc:
        return (
            False,
            None,
            _safe_exception_name(exc),
            0,
            [WarningCode.MOOMOO_POSITION_QUERY_FAILED, *_unlock_warning(exc)],
        )
    if ret_code != _ret_ok(sdk):
        return (
            False,
            _sanitize_ret_code(ret_code),
            None,
            0,
            [WarningCode.MOOMOO_POSITION_QUERY_FAILED, *_unlock_warning(data)],
        )
    rows = _rows(data)
    warnings: list[WarningCode] = []
    if not rows:
        warnings.append(WarningCode.MOOMOO_POSITION_DATA_EMPTY)
    return True, _sanitize_ret_code(ret_code), None, len(rows), warnings


def _build_result(
    *,
    terminal_warnings: list[WarningCode],
    status_warnings: list[WarningCode],
    variant_warnings: list[WarningCode],
    candidates: list[MoomooReadContextCandidateDiagnostics],
    sdk_import_ok: bool = False,
    opend_socket_reachable: bool = False,
    discovery: MoomooAccountDiscoveryDiagnostics | None = None,
    selected: MoomooReadContextCandidateDiagnostics | None = None,
) -> MoomooReadContextProbeDiagnostics:
    warning_codes = _dedupe([*status_warnings, *variant_warnings, *terminal_warnings])
    return MoomooReadContextProbeDiagnostics(
        sdk_import_ok=sdk_import_ok,
        opend_socket_reachable=opend_socket_reachable,
        discovery_success=bool(discovery.discovery_success) if discovery else False,
        account_count_redacted=discovery.account_count_redacted if discovery else 0,
        selected_account_hash=discovery.selected_account_hash if discovery else None,
        selected_discovery_context_mode=(
            discovery.selected_context_mode if discovery else None
        ),
        selected_read_context_mode=selected.context_mode if selected else None,
        accinfo_query_success=bool(selected.accinfo_query_success) if selected else False,
        position_query_success=bool(selected.position_query_success)
        if selected
        else False,
        position_count=selected.position_count if selected else 0,
        cash_field_count_detected=selected.cash_field_count_detected if selected else 0,
        normalized_rows_possible=selected.normalized_rows_possible if selected else 0,
        candidate_contexts=candidates,
        terminal_warning_codes=_dedupe(terminal_warnings),
        variant_warning_codes=_dedupe(variant_warnings),
        warning_codes=warning_codes,
        selected_account_id=discovery.selected_account_id if discovery else None,
        selected_filter_name=selected.filter_name if selected else None,
        selected_security_firm_name=selected.security_firm_name if selected else None,
        selected_need_general_sec_acc=selected.need_general_sec_acc if selected else False,
        selected_need_general_arg_name=selected.need_general_arg_name if selected else None,
    )


def _read_filter_values(sdk: Any) -> list[tuple[str, Any]]:
    enum_obj = getattr(sdk, "TrdMarket", None)
    result: list[tuple[str, Any]] = []
    for name in _READ_FILTER_NAMES:
        value = _enum_value(enum_obj, name)
        if value is not None:
            result.append((name, value))
    return result


def _select_candidate(
    candidates: list[MoomooReadContextCandidateDiagnostics],
) -> MoomooReadContextCandidateDiagnostics | None:
    for candidate in candidates:
        if candidate.position_query_success:
            return candidate
    for candidate in candidates:
        if candidate.accinfo_query_success:
            return candidate
    return None


def _candidate_terminal_warnings(
    candidates: list[MoomooReadContextCandidateDiagnostics],
) -> list[WarningCode]:
    terminal_codes = {
        WarningCode.MOOMOO_ACCINFO_QUERY_FAILED,
        WarningCode.MOOMOO_POSITION_QUERY_FAILED,
        WarningCode.MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW,
    }
    warnings: list[WarningCode] = []
    for candidate in candidates:
        for code in candidate.warning_codes:
            if code in terminal_codes:
                warnings.append(code)
    return _dedupe(warnings)


def _context_kwargs(
    *,
    sdk: Any,
    context_factory: Any,
    host: str,
    port: int,
    filter_name: str,
    filter_value: Any,
    security_firm_name: str | None,
    need_general_sec_acc: bool,
    need_general_arg_name: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"host": host, "port": port}
    supported = _supported_kwargs(context_factory)
    _set_supported_kwarg(kwargs, supported, "filter_trdmarket", filter_value)
    security_firm = _enum_value(getattr(sdk, "SecurityFirm", None), security_firm_name or "")
    if security_firm is not None:
        _set_supported_kwarg(kwargs, supported, "security_firm", security_firm)
    if need_general_sec_acc:
        arg_name = need_general_arg_name or _general_sec_account_arg_name(context_factory)
        if arg_name:
            _set_supported_kwarg(kwargs, supported, arg_name, True)
    return kwargs


def _call_account_query(query: Any, sdk: Any, *, account_id: str) -> tuple[Any, Any]:
    kwargs: dict[str, Any] = {}
    supported = _supported_kwargs(query)
    _set_supported_kwarg(kwargs, supported, "trd_env", _real_env(sdk))
    _set_first_supported_kwarg(
        kwargs,
        supported,
        ["acc_id", "accID", "accId", "accid"],
        account_id,
    )
    return query(**kwargs)


def _supported_kwargs(callable_obj: Any) -> set[str] | None:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return None
    parameters = signature.parameters
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return None
    return set(parameters)


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
    for name in names:
        if _set_supported_kwarg(kwargs, supported, name, value):
            return True
    return False


def _general_sec_account_arg_name(context_factory: Any) -> str | None:
    supported = _supported_kwargs(context_factory)
    if _kwarg_supported(supported, "need_general_sec_acc"):
        return "need_general_sec_acc"
    if _kwarg_supported(supported, "needGeneralSecAccount"):
        return "needGeneralSecAccount"
    return None


def _enum_value(enum_obj: Any, name: str) -> Any:
    if enum_obj is None or not name or not hasattr(enum_obj, name):
        return None
    value = getattr(enum_obj, name)
    return None if callable(value) else value


def _real_env(sdk: Any) -> Any:
    trd_env = getattr(sdk, "TrdEnv", None)
    return getattr(trd_env, "REAL", "REAL")


def _ret_ok(sdk: Any) -> Any:
    return getattr(sdk, "RET_OK", 0)


def _rows(data: Any) -> list[dict[str, Any]]:
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        return list(to_dict("records"))
    if isinstance(data, list):
        return [dict(row) for row in data]
    if isinstance(data, dict):
        return [dict(data)]
    return []


def _cash_field_count(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        for field_name in _CASH_FIELD_NAMES:
            if field_name in row and _parseable_number(row[field_name]):
                count += 1
    return count


def _parseable_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _context_mode(
    *,
    filter_name: str,
    security_firm_name: str | None,
    need_general_sec_acc: bool,
) -> str:
    firm = security_firm_name or "DEFAULT"
    return (
        f"filter_trdmarket={filter_name};"
        f"security_firm={firm};"
        f"need_general_sec_acc={need_general_sec_acc}"
    )


def _sanitize_ret_code(ret_code: Any) -> str:
    if isinstance(ret_code, (bool, int, float)):
        return str(ret_code)
    name = getattr(ret_code, "name", None)
    if isinstance(name, str):
        return name
    return type(ret_code).__name__


def _unlock_warning(value: Any) -> list[WarningCode]:
    text = str(value).upper()
    if "UNLOCK" in text or "PASSWORD" in text or "LOCKED" in text:
        return [WarningCode.MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW]
    return []


def _safe_exception_name(exc: Exception) -> str:
    return type(exc).__name__


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


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
