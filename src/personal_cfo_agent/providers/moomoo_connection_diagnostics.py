"""Redacted Moomoo/Futu OpenD connection diagnostics."""

from __future__ import annotations

import importlib
import socket
import sys
from dataclasses import dataclass
from typing import Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode


@dataclass(frozen=True)
class MoomooConnectionDiagnostics:
    local_env_loaded: bool
    enabled_present: bool
    enabled_true: bool
    host_present: bool
    port_present: bool
    hash_salt_present: bool
    python_executable: str
    futu_import_ok: bool
    opend_socket_reachable: bool
    warning_codes: tuple[WarningCode, ...]


def run_moomoo_connection_diagnostics(
    env: Mapping[str, str],
    *,
    local_env_loaded: bool = False,
    timeout_seconds: float = 3.0,
) -> MoomooConnectionDiagnostics:
    enabled_present = _present(env, "CFO_MOOMOO_ENABLED")
    enabled_true = env_bool(env, "CFO_MOOMOO_ENABLED")
    host_present = _present(env, "CFO_MOOMOO_HOST")
    port_present = _present(env, "CFO_MOOMOO_PORT")
    hash_salt_present = _present(env, "CFO_ACCOUNT_HASH_SALT")
    futu_import_ok = _futu_import_ok()
    socket_reachable = _socket_reachable(
        env.get("CFO_MOOMOO_HOST", ""),
        env.get("CFO_MOOMOO_PORT", ""),
        timeout_seconds=timeout_seconds,
    )
    warning_codes = _warning_codes(
        enabled_true=enabled_true,
        host_present=host_present,
        port_present=port_present,
        futu_import_ok=futu_import_ok,
        socket_reachable=socket_reachable,
    )
    return MoomooConnectionDiagnostics(
        local_env_loaded=local_env_loaded,
        enabled_present=enabled_present,
        enabled_true=enabled_true,
        host_present=host_present,
        port_present=port_present,
        hash_salt_present=hash_salt_present,
        python_executable=sys.executable,
        futu_import_ok=futu_import_ok,
        opend_socket_reachable=socket_reachable,
        warning_codes=warning_codes,
    )


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())


def _futu_import_ok() -> bool:
    try:
        importlib.import_module("futu")
    except ImportError:
        return False
    return True


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


def _warning_codes(
    *,
    enabled_true: bool,
    host_present: bool,
    port_present: bool,
    futu_import_ok: bool,
    socket_reachable: bool,
) -> tuple[WarningCode, ...]:
    codes: list[WarningCode] = []
    if not enabled_true:
        codes.append(WarningCode.PROVIDER_DISABLED)
    if not (host_present and port_present):
        codes.append(WarningCode.PROVIDER_CONFIG_MISSING)
    if not futu_import_ok:
        codes.extend([WarningCode.MOOMOO_SDK_NOT_INSTALLED, WarningCode.SDK_NOT_INSTALLED])
    if enabled_true and host_present and port_present and not socket_reachable:
        codes.extend(
            [
                WarningCode.MOOMOO_OPEND_UNREACHABLE,
                WarningCode.PROVIDER_CONNECTION_FAILED,
            ]
        )
    return _dedupe(codes)


def _dedupe(codes: list[WarningCode]) -> tuple[WarningCode, ...]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return tuple(result)
