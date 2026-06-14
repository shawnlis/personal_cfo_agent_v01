"""Redacted TigerOpen local configuration diagnostics."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode


DEFAULT_PROPS_FILE = "tiger_openapi_config.properties"


@dataclass(frozen=True)
class TigerConnectionDiagnostics:
    enabled_present: bool
    enabled_true: bool
    config_dir_present: bool
    config_dir_exists: bool
    config_file_exists: bool
    account_present: bool
    hash_salt_present: bool
    python_executable: str
    tigeropen_import_ok: bool
    warning_codes: tuple[WarningCode, ...]


def run_tiger_connection_diagnostics(env: Mapping[str, str]) -> TigerConnectionDiagnostics:
    enabled_present = _present(env, "CFO_TIGER_ENABLED")
    enabled_true = env_bool(env, "CFO_TIGER_ENABLED")
    config_dir_value = env.get("CFO_TIGER_CONFIG_DIR", "").strip()
    config_dir_present = bool(config_dir_value)
    config_dir = Path(config_dir_value) if config_dir_value else None
    config_dir_exists = bool(config_dir and config_dir.exists() and config_dir.is_dir())
    config_file_exists = bool(
        config_dir and (config_dir / DEFAULT_PROPS_FILE).exists()
    )
    account_present = _present(env, "CFO_TIGER_ACCOUNT")
    hash_salt_present = _present(env, "CFO_ACCOUNT_HASH_SALT")
    tigeropen_import_ok = _tigeropen_import_ok()
    warning_codes = _warning_codes(
        enabled_true=enabled_true,
        config_dir_present=config_dir_present,
        config_dir_exists=config_dir_exists,
        config_file_exists=config_file_exists,
        account_present=account_present,
        tigeropen_import_ok=tigeropen_import_ok,
    )
    return TigerConnectionDiagnostics(
        enabled_present=enabled_present,
        enabled_true=enabled_true,
        config_dir_present=config_dir_present,
        config_dir_exists=config_dir_exists,
        config_file_exists=config_file_exists,
        account_present=account_present,
        hash_salt_present=hash_salt_present,
        python_executable=sys.executable,
        tigeropen_import_ok=tigeropen_import_ok,
        warning_codes=warning_codes,
    )


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())


def _tigeropen_import_ok() -> bool:
    try:
        importlib.import_module("tigeropen")
    except ImportError:
        return False
    return True


def _warning_codes(
    *,
    enabled_true: bool,
    config_dir_present: bool,
    config_dir_exists: bool,
    config_file_exists: bool,
    account_present: bool,
    tigeropen_import_ok: bool,
) -> tuple[WarningCode, ...]:
    codes: list[WarningCode] = []
    if not enabled_true:
        codes.append(WarningCode.PROVIDER_DISABLED)
    if not (
        config_dir_present
        and config_dir_exists
        and config_file_exists
        and account_present
    ):
        codes.append(WarningCode.PROVIDER_CONFIG_MISSING)
    if not tigeropen_import_ok:
        codes.append(WarningCode.SDK_NOT_INSTALLED)
    return tuple(codes)
