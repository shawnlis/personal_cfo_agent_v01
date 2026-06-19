"""Redacted Moomoo account-context discovery using get_acc_list only."""

from __future__ import annotations

import importlib
import inspect
import io
import logging
import socket
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.normalizer import hash_account_id


_MARKET_FILTER_NAMES = ("NONE", "HK", "US", "SG")
_MARKET_AUTH_NAMES = {"HK", "US", "SG"}
_ACTIVE_STATUS_MARKERS = {"ACTIVE", "NORMAL", "ENABLED"}


@dataclass(frozen=True)
class MoomooAccountDiscoveryDiagnostics:
    sdk_import_ok: bool = False
    opend_socket_reachable: bool = False
    discovery_success: bool = False
    context_variant_count: int = 0
    successful_context_variants: list[str] = field(default_factory=list)
    failed_context_variants: list[str] = field(default_factory=list)
    account_count_redacted: int = 0
    account_id_hashes: list[str] = field(default_factory=list)
    trd_env_values: list[str] = field(default_factory=list)
    acc_type_values: list[str] = field(default_factory=list)
    security_firm_values: list[str] = field(default_factory=list)
    trdmarket_auth_values: list[str] = field(default_factory=list)
    acc_status_values: list[str] = field(default_factory=list)
    selected_account_hash: str | None = None
    selected_context_mode: str | None = None
    terminal_warning_codes: list[WarningCode] = field(default_factory=list)
    variant_warning_codes: list[WarningCode] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)
    selected_account_id: Any | None = field(default=None, repr=False, compare=False)
    candidate_account_ids: list[Any] = field(
        default_factory=list, repr=False, compare=False
    )
    selected_filter_name: str | None = field(default=None, repr=False, compare=False)
    selected_security_firm_name: str | None = field(default=None, repr=False, compare=False)
    selected_need_general_sec_acc: bool = field(default=False, repr=False, compare=False)
    selected_need_general_arg_name: str | None = field(
        default=None, repr=False, compare=False
    )

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "opend_socket_reachable": self.opend_socket_reachable,
            "discovery_success": self.discovery_success,
            "context_variant_count": self.context_variant_count,
            "successful_context_variants": list(self.successful_context_variants),
            "failed_context_variants": list(self.failed_context_variants),
            "account_count_redacted": self.account_count_redacted,
            "account_id_hashes": list(self.account_id_hashes),
            "trd_env_values": list(self.trd_env_values),
            "acc_type_values": list(self.acc_type_values),
            "security_firm_values": list(self.security_firm_values),
            "trdmarket_auth_values": list(self.trdmarket_auth_values),
            "acc_status_values": list(self.acc_status_values),
            "selected_account_hash": self.selected_account_hash,
            "selected_context_mode": self.selected_context_mode,
            "terminal_warning_codes": [
                code.value for code in self.terminal_warning_codes
            ],
            "variant_warning_codes": [code.value for code in self.variant_warning_codes],
            "warning_codes": [code.value for code in self.warning_codes],
        }


@dataclass(frozen=True)
class _ContextVariant:
    filter_name: str
    filter_value: Any
    security_firm_name: str
    security_firm_value: Any
    need_general_sec_acc: bool
    need_general_arg_name: str | None

    @property
    def mode(self) -> str:
        return (
            f"filter_trdmarket={self.filter_name};"
            f"security_firm={self.security_firm_name};"
            f"need_general_sec_acc={self.need_general_sec_acc}"
        )


@dataclass(frozen=True)
class _AccountCandidate:
    account_id: Any = field(repr=False, compare=False)
    account_hash: str
    variant: _ContextVariant = field(repr=False, compare=False)
    context_mode: str
    need_general_sec_acc: bool
    trd_env_values: tuple[str, ...]
    acc_type_values: tuple[str, ...]
    security_firm_values: tuple[str, ...]
    trdmarket_auth_values: tuple[str, ...]
    acc_status_values: tuple[str, ...]


def run_moomoo_account_discovery(
    env: Mapping[str, str],
    *,
    timeout_seconds: float = 3.0,
) -> MoomooAccountDiscoveryDiagnostics:
    """Discover Moomoo account context without reading funds, positions, or orders."""

    terminal_warnings: list[WarningCode] = []
    variant_warnings: list[WarningCode] = []
    status_warnings: list[WarningCode] = []
    if not env_bool(env, "CFO_MOOMOO_ENABLED"):
        terminal_warnings.append(WarningCode.PROVIDER_DISABLED)
    host = env.get("CFO_MOOMOO_HOST", "")
    port = env.get("CFO_MOOMOO_PORT", "")
    if not host.strip() or not port.strip():
        terminal_warnings.append(WarningCode.PROVIDER_CONFIG_MISSING)

    try:
        sdk = importlib.import_module("futu")
        sdk_import_ok = True
        _quiet_sdk_logging(sdk)
        status_warnings.append(WarningCode.MOOMOO_SDK_OUTPUT_SUPPRESSED)
    except ImportError:
        terminal_warnings.extend(
            [
                WarningCode.MOOMOO_SDK_NOT_INSTALLED,
                WarningCode.SDK_NOT_INSTALLED,
                WarningCode.MOOMOO_ACCOUNT_DISCOVERY_FAILED,
            ]
        )
        return MoomooAccountDiscoveryDiagnostics(
            sdk_import_ok=False,
            opend_socket_reachable=_socket_reachable(host, port, timeout_seconds),
            terminal_warning_codes=_dedupe(terminal_warnings),
            warning_codes=_dedupe([*status_warnings, *terminal_warnings]),
        )

    socket_reachable = _socket_reachable(host, port, timeout_seconds)
    if not socket_reachable:
        terminal_warnings.extend(
            [
                WarningCode.MOOMOO_OPEND_UNREACHABLE,
                WarningCode.PROVIDER_CONNECTION_FAILED,
                WarningCode.MOOMOO_ACCOUNT_DISCOVERY_FAILED,
            ]
        )
        return MoomooAccountDiscoveryDiagnostics(
            sdk_import_ok=sdk_import_ok,
            opend_socket_reachable=False,
            terminal_warning_codes=_dedupe(terminal_warnings),
            warning_codes=_dedupe([*status_warnings, *terminal_warnings]),
        )

    try:
        port_number = int(port.strip())
    except ValueError:
        terminal_warnings.extend(
            [
                WarningCode.PROVIDER_CONFIG_MISSING,
                WarningCode.MOOMOO_ACCOUNT_DISCOVERY_FAILED,
            ]
        )
        return MoomooAccountDiscoveryDiagnostics(
            sdk_import_ok=sdk_import_ok,
            opend_socket_reachable=socket_reachable,
            terminal_warning_codes=_dedupe(terminal_warnings),
            warning_codes=_dedupe([*status_warnings, *terminal_warnings]),
        )

    variants = _build_context_variants(sdk, variant_warnings)
    candidates: list[_AccountCandidate] = []
    successful_context_variants: list[str] = []
    failed_context_variants: list[str] = []

    for variant in variants:
        context = None
        try:
            context = _open_context(sdk, variant, host.strip(), port_number)
            query = getattr(context, "get_acc_list", None)
            if not callable(query):
                failed_context_variants.append(
                    f"{variant.mode}:MOOMOO_ACCOUNT_DISCOVERY_FAILED"
                )
                variant_warnings.append(WarningCode.MOOMOO_ACCOUNT_DISCOVERY_FAILED)
                continue
            with _suppress_sdk_console_output():
                ret_code, data = query()
            if ret_code != _ret_ok(sdk):
                failed_context_variants.append(
                    f"{variant.mode}:MOOMOO_ACCOUNT_DISCOVERY_FAILED"
                )
                _record_variant_mismatch_warnings(variant, variant_warnings)
                continue
            rows = _rows(data)
            if not rows:
                failed_context_variants.append(f"{variant.mode}:MOOMOO_NO_ACCOUNT_DISCOVERED")
                _record_variant_mismatch_warnings(variant, variant_warnings)
                continue
            successful_context_variants.append(variant.mode)
            for row in rows:
                candidate = _candidate_from_row(
                    row,
                    variant,
                    env.get("CFO_ACCOUNT_HASH_SALT"),
                )
                if candidate is not None:
                    candidates.append(candidate)
        except TypeError:
            failed_context_variants.append(
                f"{variant.mode}:MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED"
            )
            variant_warnings.append(WarningCode.MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED)
        except Exception:
            failed_context_variants.append(
                f"{variant.mode}:MOOMOO_ACCOUNT_DISCOVERY_FAILED"
            )
            _record_variant_mismatch_warnings(variant, variant_warnings)
        finally:
            close = getattr(context, "close", None)
            if callable(close):
                with _suppress_sdk_console_output():
                    close()

    selected = _select_account(candidates)
    account_hashes = _dedupe_text([candidate.account_hash for candidate in candidates])
    candidate_account_ids = _dedupe_account_ids(
        [candidate.account_id for candidate in candidates]
    )
    if selected is None:
        terminal_warnings.extend(
            [
                WarningCode.MOOMOO_NO_ACCOUNT_DISCOVERED,
                WarningCode.MOOMOO_SELECTED_ACCOUNT_MISSING,
                WarningCode.MOOMOO_ACCOUNT_DISCOVERY_FAILED,
            ]
        )
    else:
        status_warnings.append(WarningCode.MOOMOO_ACCOUNT_DISCOVERY_OK)
        status_warnings.append(WarningCode.MOOMOO_SELECTED_ACCOUNT_HASHED)
        status_warnings.append(WarningCode.MOOMOO_EXPLICIT_ACC_ID_SELECTED)
        if not _has_active_status(selected.acc_status_values):
            terminal_warnings.append(WarningCode.MOOMOO_ACCOUNT_STATUS_NOT_ACTIVE)
        if not _has_market_auth(selected.trdmarket_auth_values):
            terminal_warnings.append(WarningCode.MOOMOO_TRDMARKET_AUTH_MISSING)
        if _only_general_sec_account_worked(candidates):
            variant_warnings.append(WarningCode.MOOMOO_GENERAL_SEC_ACCOUNT_REQUIRED)
        if _looks_unlock_related(selected.acc_status_values):
            terminal_warnings.append(
                WarningCode.MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW
            )
        if variant_warnings:
            variant_warnings.append(
                WarningCode.MOOMOO_DISCOVERY_SUCCESS_WITH_VARIANT_WARNINGS
            )

    warning_codes = _dedupe([*status_warnings, *terminal_warnings, *variant_warnings])
    discovery_success = (
        selected is not None
        and selected.account_hash is not None
        and WarningCode.MOOMOO_ACCOUNT_DISCOVERY_OK in warning_codes
    )

    return MoomooAccountDiscoveryDiagnostics(
        sdk_import_ok=sdk_import_ok,
        opend_socket_reachable=socket_reachable,
        discovery_success=discovery_success,
        context_variant_count=len(variants),
        successful_context_variants=_dedupe_text(successful_context_variants),
        failed_context_variants=_dedupe_text(failed_context_variants),
        account_count_redacted=len(account_hashes),
        account_id_hashes=account_hashes,
        trd_env_values=_candidate_values(candidates, "trd_env_values"),
        acc_type_values=_candidate_values(candidates, "acc_type_values"),
        security_firm_values=_candidate_values(candidates, "security_firm_values"),
        trdmarket_auth_values=_candidate_values(candidates, "trdmarket_auth_values"),
        acc_status_values=_candidate_values(candidates, "acc_status_values"),
        selected_account_hash=selected.account_hash if selected else None,
        selected_context_mode=selected.context_mode if selected else None,
        terminal_warning_codes=_dedupe(terminal_warnings),
        variant_warning_codes=_dedupe(variant_warnings),
        warning_codes=warning_codes,
        selected_account_id=selected.account_id if selected else None,
        candidate_account_ids=candidate_account_ids,
        selected_filter_name=selected.variant.filter_name if selected else None,
        selected_security_firm_name=(
            selected.variant.security_firm_name if selected else None
        ),
        selected_need_general_sec_acc=(
            selected.variant.need_general_sec_acc if selected else False
        ),
        selected_need_general_arg_name=(
            selected.variant.need_general_arg_name if selected else None
        ),
    )


def open_moomoo_discovered_context(
    sdk: Any,
    diagnostics: MoomooAccountDiscoveryDiagnostics,
    *,
    host: str,
    port: int,
) -> Any:
    """Open the selected account-discovery context mode."""

    kwargs: dict[str, Any] = {"host": host, "port": port}
    context_factory = sdk.OpenSecTradeContext
    supported_kwargs = _supported_kwargs(context_factory)
    if diagnostics.selected_filter_name and diagnostics.selected_filter_name != "DEFAULT":
        filter_value = _enum_value(getattr(sdk, "TrdMarket", None), diagnostics.selected_filter_name)
        if filter_value is not None and _kwarg_supported(
            supported_kwargs, "filter_trdmarket"
        ):
            kwargs["filter_trdmarket"] = filter_value
    if (
        diagnostics.selected_security_firm_name
        and diagnostics.selected_security_firm_name != "DEFAULT"
    ):
        security_firm = _enum_value(
            getattr(sdk, "SecurityFirm", None), diagnostics.selected_security_firm_name
        )
        if security_firm is not None and _kwarg_supported(supported_kwargs, "security_firm"):
            kwargs["security_firm"] = security_firm
    if (
        diagnostics.selected_need_general_sec_acc
        and diagnostics.selected_need_general_arg_name
        and _kwarg_supported(supported_kwargs, diagnostics.selected_need_general_arg_name)
    ):
        kwargs[diagnostics.selected_need_general_arg_name] = True
    with _suppress_sdk_console_output():
        return context_factory(**kwargs)


def _build_context_variants(sdk: Any, warnings: list[WarningCode]) -> list[_ContextVariant]:
    filter_members = _named_enum_values(getattr(sdk, "TrdMarket", None), _MARKET_FILTER_NAMES)
    if not filter_members:
        filter_members = [("DEFAULT", None)]
        warnings.append(WarningCode.MOOMOO_MARKET_FILTER_MISMATCH)

    security_members = _named_enum_values(getattr(sdk, "SecurityFirm", None), None)
    if not security_members:
        security_members = [("DEFAULT", None)]
        warnings.append(WarningCode.MOOMOO_SECURITY_FIRM_MISMATCH)

    general_arg_name = _general_sec_account_arg_name(getattr(sdk, "OpenSecTradeContext"))
    if general_arg_name is None:
        general_options = [False]
        warnings.append(WarningCode.MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED)
    else:
        general_options = [False, True]

    return [
        _ContextVariant(
            filter_name=filter_name,
            filter_value=filter_value,
            security_firm_name=security_firm_name,
            security_firm_value=security_firm_value,
            need_general_sec_acc=need_general,
            need_general_arg_name=general_arg_name,
        )
        for filter_name, filter_value in filter_members
        for security_firm_name, security_firm_value in security_members
        for need_general in general_options
    ]


def _open_context(sdk: Any, variant: _ContextVariant, host: str, port: int) -> Any:
    kwargs: dict[str, Any] = {"host": host, "port": port}
    if variant.filter_value is not None:
        kwargs["filter_trdmarket"] = variant.filter_value
    if variant.security_firm_value is not None:
        kwargs["security_firm"] = variant.security_firm_value
    if variant.need_general_sec_acc and variant.need_general_arg_name is not None:
        kwargs[variant.need_general_arg_name] = True
    with _suppress_sdk_console_output():
        return sdk.OpenSecTradeContext(**kwargs)


def _candidate_from_row(
    row: dict[str, Any],
    variant: _ContextVariant,
    account_hash_salt: str | None,
) -> _AccountCandidate | None:
    account_id = _first_value(row, ["acc_id", "accID", "account_id", "account"], "")
    if not _has_value(account_id):
        return None
    return _AccountCandidate(
        account_id=account_id,
        account_hash=hash_account_id(str(account_id), account_hash_salt),
        variant=variant,
        context_mode=variant.mode,
        need_general_sec_acc=variant.need_general_sec_acc,
        trd_env_values=_row_values(row, ["trd_env", "env"]),
        acc_type_values=_row_values(row, ["acc_type", "account_type"]),
        security_firm_values=_row_values(row, ["security_firm"]),
        trdmarket_auth_values=_row_values(row, ["trdmarket_auth", "market_auth"]),
        acc_status_values=_row_values(row, ["acc_status", "status"]),
    )


def _select_account(candidates: list[_AccountCandidate]) -> _AccountCandidate | None:
    if not candidates:
        return None
    only_general = _only_general_sec_account_worked(candidates)

    def score(candidate: _AccountCandidate) -> tuple[int, int, int, int]:
        return (
            1 if _has_real_env(candidate.trd_env_values) else 0,
            1 if _has_active_status(candidate.acc_status_values) else 0,
            1 if _has_market_auth(candidate.trdmarket_auth_values) else 0,
            1 if only_general and candidate.need_general_sec_acc else 0,
        )

    return max(candidates, key=score)


def _candidate_values(candidates: list[_AccountCandidate], attr: str) -> list[str]:
    values: list[str] = []
    for candidate in candidates:
        values.extend(getattr(candidate, attr))
    return _dedupe_text(values)


def _named_enum_values(enum_obj: Any, wanted_names: tuple[str, ...] | None) -> list[tuple[str, Any]]:
    if enum_obj is None:
        return []
    names = list(wanted_names) if wanted_names is not None else []
    if not names:
        members = getattr(enum_obj, "__members__", None)
        if isinstance(members, dict):
            names = [str(name) for name in members]
        else:
            names = [
                name
                for name in dir(enum_obj)
                if name.isupper() and not name.startswith("_")
            ]
    result: list[tuple[str, Any]] = []
    for name in names:
        if not hasattr(enum_obj, name):
            continue
        value = getattr(enum_obj, name)
        if callable(value):
            continue
        result.append((name, value))
    return result


def _general_sec_account_arg_name(context_factory: Any) -> str | None:
    try:
        signature = inspect.signature(context_factory)
    except (TypeError, ValueError):
        return None
    parameters = signature.parameters
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return "need_general_sec_acc"
    if "need_general_sec_acc" in parameters:
        return "need_general_sec_acc"
    if "needGeneralSecAccount" in parameters:
        return "needGeneralSecAccount"
    return None


def _supported_kwargs(callable_obj: Any) -> set[str] | None:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return None
    parameters = signature.parameters
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return None
    return set(parameters)


def _kwarg_supported(supported_kwargs: set[str] | None, name: str) -> bool:
    return supported_kwargs is None or name in supported_kwargs


def _enum_value(enum_obj: Any, name: str) -> Any:
    if enum_obj is None or not hasattr(enum_obj, name):
        return None
    value = getattr(enum_obj, name)
    return None if callable(value) else value


def _record_variant_mismatch_warnings(
    variant: _ContextVariant,
    warnings: list[WarningCode],
) -> None:
    warnings.append(WarningCode.MOOMOO_ACCOUNT_DISCOVERY_FAILED)
    if variant.security_firm_name != "DEFAULT":
        warnings.append(WarningCode.MOOMOO_SECURITY_FIRM_MISMATCH)
    if variant.filter_name not in {"DEFAULT", "NONE"}:
        warnings.append(WarningCode.MOOMOO_MARKET_FILTER_MISMATCH)


def _socket_reachable(host: str, port: str, timeout_seconds: float) -> bool:
    host_value = host.strip()
    port_value = port.strip()
    if not host_value or not port_value:
        return False
    try:
        port_number = int(port_value)
    except ValueError:
        return False
    try:
        with socket.create_connection((host_value, port_number), timeout=timeout_seconds):
            return True
    except OSError:
        return False


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


def _first_value(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if _has_value(value):
            return value
    return default


def _has_value(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and value == "")


def _row_values(row: dict[str, Any], keys: list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for key in keys:
        if key not in row:
            continue
        values.extend(_flatten_public_values(row[key]))
    return tuple(_dedupe_text(values))


def _flatten_public_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_flatten_public_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_flatten_public_values(item))
        return values
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return [name]
    return [str(value)]


def _has_real_env(values: tuple[str, ...]) -> bool:
    return any("REAL" in value.upper() for value in values)


def _has_active_status(values: tuple[str, ...]) -> bool:
    if not values:
        return True
    return any(
        any(marker in value.upper() for marker in _ACTIVE_STATUS_MARKERS)
        for value in values
    )


def _has_market_auth(values: tuple[str, ...]) -> bool:
    return any(value.upper() in _MARKET_AUTH_NAMES for value in values)


def _only_general_sec_account_worked(candidates: list[_AccountCandidate]) -> bool:
    return bool(candidates) and all(candidate.need_general_sec_acc for candidate in candidates)


def _looks_unlock_related(values: tuple[str, ...]) -> bool:
    return any("LOCK" in value.upper() for value in values)


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _dedupe_account_ids(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(value)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result
