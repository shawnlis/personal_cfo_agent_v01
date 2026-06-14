"""Redacted IBKR connection diagnostics."""

from __future__ import annotations

import importlib
import socket
import sys
from dataclasses import dataclass
from typing import Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode


@dataclass(frozen=True)
class IBKRConnectionDiagnostics:
    enabled_present: bool
    enabled_true: bool
    host_present: bool
    port_present: bool
    client_id_present: bool
    account_present: bool
    hash_salt_present: bool
    python_executable: str
    ibapi_import_ok: bool
    tcp_socket_reachable: bool
    warning_codes: tuple[WarningCode, ...]


def run_ibkr_connection_diagnostics(
    env: Mapping[str, str], timeout_seconds: float = 3.0
) -> IBKRConnectionDiagnostics:
    enabled_present = _present(env, "CFO_IBKR_ENABLED")
    enabled_true = env_bool(env, "CFO_IBKR_ENABLED")
    host_present = _present(env, "CFO_IBKR_HOST")
    port_present = _present(env, "CFO_IBKR_PORT")
    client_id_present = _present(env, "CFO_IBKR_CLIENT_ID")
    account_present = _present(env, "CFO_IBKR_ACCOUNT")
    hash_salt_present = _present(env, "CFO_ACCOUNT_HASH_SALT")
    ibapi_import_ok = _ibapi_import_ok()
    socket_reachable = _socket_reachable(
        env.get("CFO_IBKR_HOST", ""),
        env.get("CFO_IBKR_PORT", ""),
        timeout_seconds=timeout_seconds,
    )
    warning_codes = _warning_codes(
        enabled_true=enabled_true,
        host_present=host_present,
        port_present=port_present,
        client_id_present=client_id_present,
        ibapi_import_ok=ibapi_import_ok,
        socket_reachable=socket_reachable,
    )
    return IBKRConnectionDiagnostics(
        enabled_present=enabled_present,
        enabled_true=enabled_true,
        host_present=host_present,
        port_present=port_present,
        client_id_present=client_id_present,
        account_present=account_present,
        hash_salt_present=hash_salt_present,
        python_executable=sys.executable,
        ibapi_import_ok=ibapi_import_ok,
        tcp_socket_reachable=socket_reachable,
        warning_codes=warning_codes,
    )


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())


def _ibapi_import_ok() -> bool:
    try:
        importlib.import_module("ibapi")
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
    client_id_present: bool,
    ibapi_import_ok: bool,
    socket_reachable: bool,
) -> tuple[WarningCode, ...]:
    codes: list[WarningCode] = []
    if not enabled_true:
        codes.append(WarningCode.PROVIDER_DISABLED)
    if not (host_present and port_present and client_id_present):
        codes.append(WarningCode.PROVIDER_CONFIG_MISSING)
    if not ibapi_import_ok:
        codes.append(WarningCode.SDK_NOT_INSTALLED)
    if enabled_true and host_present and port_present and client_id_present and not socket_reachable:
        codes.append(WarningCode.PROVIDER_CONNECTION_FAILED)
    return tuple(codes)
