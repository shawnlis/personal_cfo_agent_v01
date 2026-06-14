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
    tiger_id_present: bool
    account_present: bool
    config_account_present: bool
    private_key_present: bool
    private_key_format_detected: str
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
    file_metadata = _read_config_metadata(config_dir / DEFAULT_PROPS_FILE) if config_dir else {}
    tiger_id_present = _present(env, "TIGEROPEN_TIGER_ID") or bool(
        file_metadata.get("tiger_id_present")
    )
    account_present = _present(env, "CFO_TIGER_ACCOUNT")
    config_account_present = _present(env, "TIGEROPEN_ACCOUNT") or bool(
        file_metadata.get("account_present")
    )
    private_key_present = _present(env, "TIGEROPEN_PRIVATE_KEY") or bool(
        file_metadata.get("private_key_present")
    )
    private_key_format_detected = str(
        file_metadata.get("private_key_format_detected") or "missing"
    )
    if _present(env, "TIGEROPEN_PRIVATE_KEY") and private_key_format_detected == "missing":
        private_key_format_detected = "env_present"
    hash_salt_present = _present(env, "CFO_ACCOUNT_HASH_SALT")
    tigeropen_import_ok = _tigeropen_import_ok()
    warning_codes = _warning_codes(
        enabled_true=enabled_true,
        config_dir_present=config_dir_present,
        config_dir_exists=config_dir_exists,
        config_file_exists=config_file_exists,
        account_present=account_present,
        config_account_present=config_account_present,
        private_key_present=private_key_present,
        private_key_format_detected=private_key_format_detected,
        tigeropen_import_ok=tigeropen_import_ok,
    )
    return TigerConnectionDiagnostics(
        enabled_present=enabled_present,
        enabled_true=enabled_true,
        config_dir_present=config_dir_present,
        config_dir_exists=config_dir_exists,
        config_file_exists=config_file_exists,
        tiger_id_present=tiger_id_present,
        account_present=account_present,
        config_account_present=config_account_present,
        private_key_present=private_key_present,
        private_key_format_detected=private_key_format_detected,
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
    config_account_present: bool,
    private_key_present: bool,
    private_key_format_detected: str,
    tigeropen_import_ok: bool,
) -> tuple[WarningCode, ...]:
    codes: list[WarningCode] = []
    if not enabled_true:
        codes.append(WarningCode.PROVIDER_DISABLED)
    else:
        if not config_dir_present or not config_dir_exists:
            codes.append(WarningCode.TIGER_CONFIG_DIR_MISSING)
        if not config_file_exists:
            codes.append(WarningCode.TIGER_CONFIG_FILE_MISSING)
        if not account_present and not config_account_present:
            codes.append(WarningCode.TIGER_ACCOUNT_MISSING)
        if not private_key_present:
            codes.append(WarningCode.TIGER_PRIVATE_KEY_MISSING)
        if private_key_present and private_key_format_detected == "unknown":
            codes.append(WarningCode.TIGER_PRIVATE_KEY_FORMAT_INVALID)
        if codes:
            codes.append(WarningCode.PROVIDER_CONFIG_MISSING)
    if not tigeropen_import_ok:
        codes.append(WarningCode.SDK_NOT_INSTALLED)
    return tuple(codes)


def _read_config_metadata(path: Path) -> dict[str, object]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    pairs = _properties_pairs(text)
    private_key_values = [
        value
        for key, value in pairs.items()
        if key.lower() in {"private_key", "private_key_pk1", "private_key_pk8"}
    ]
    return {
        "tiger_id_present": bool(pairs.get("tiger_id", "").strip()),
        "account_present": bool(pairs.get("account", "").strip()),
        "private_key_present": any(value.strip() for value in private_key_values),
        "private_key_format_detected": _detect_private_key_format(pairs),
    }


def _properties_pairs(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        separator_indexes = [index for index in (line.find("="), line.find(":")) if index >= 0]
        if not separator_indexes:
            continue
        index = min(separator_indexes)
        key = line[:index].strip().lower()
        value = line[index + 1 :].strip()
        if key:
            pairs[key] = value
    return pairs


def _detect_private_key_format(pairs: dict[str, str]) -> str:
    for key in ("private_key_pk1", "private_key_pk8", "private_key"):
        value = pairs.get(key, "").strip()
        if not value:
            continue
        lowered = value.lower()
        if key == "private_key_pk1" or "begin rsa private key" in lowered:
            return "pkcs1"
        if key == "private_key_pk8" or "begin private key" in lowered:
            return "pkcs8"
        if lowered.endswith((".pem", ".key")):
            return "path"
        return "unknown"
    return "missing"
