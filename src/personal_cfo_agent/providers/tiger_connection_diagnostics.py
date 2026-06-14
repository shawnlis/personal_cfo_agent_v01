"""Redacted TigerOpen local configuration diagnostics."""

from __future__ import annotations

import importlib
import io
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode


DEFAULT_PROPS_FILE = "tiger_openapi_config.properties"
PREFLIGHT_CONFIG_FILE_PATTERN = f"<CFO_TIGER_CONFIG_DIR>/{DEFAULT_PROPS_FILE}"
PREFLIGHT_PROPS_PATH_EXPECTATION = "directory_path"
TIGEROPEN_PRIVATE_KEY_PROPERTY_FIELDS = ("private_key_pk1", "private_key_pk8")
TIGEROPEN_PRIVATE_KEY_ENV_OR_PATH = "TIGEROPEN_PRIVATE_KEY or private_key_path"
SDK_CONFIG_PROBE_MODES = ("directory", "file", "explicit_props_path", "sdk_default")


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


@dataclass(frozen=True)
class TigerConfigPreflight:
    enabled_present: bool
    enabled_true: bool
    config_dir_present: bool
    config_dir_exists: bool
    config_dir_is_directory: bool
    expected_config_file_pattern: str
    expected_props_filename: str
    props_path_expectation: str
    props_path_matches_adapter: bool
    config_file_exists: bool
    config_file_readable: bool
    config_file_outside_repo: bool
    config_file_tracked: bool
    config_history_risk: bool
    tiger_id_present: bool
    account_present: bool
    config_account_present: bool
    private_key_field_present: bool
    private_key_path_present: bool
    private_key_format_category: str
    warning_codes: tuple[WarningCode, ...]


@dataclass(frozen=True)
class TigerSDKConfigProbeVariant:
    mode: str
    config_constructed: bool
    client_constructed: bool
    exception_class_sanitized: str
    exception_category: str
    warning_codes: tuple[WarningCode, ...]


@dataclass(frozen=True)
class TigerSDKConfigProbe:
    sdk_import_ok: bool
    tigeropen_package_path: str
    props_path_modes_tested: tuple[str, ...]
    working_props_path_mode: str
    expected_config_filename: str
    config_file_detected: bool
    required_keys_present_redacted: dict[str, bool]
    private_key_format_category: str
    sdk_config_constructed: bool
    sdk_client_constructed: bool
    sdk_exception_class_sanitized: str
    sdk_exception_category: str
    variant_results: tuple[TigerSDKConfigProbeVariant, ...]
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


def run_tiger_sdk_config_probe(
    env: Mapping[str, str], repo_root: Path | None = None
) -> TigerSDKConfigProbe:
    preflight = run_tiger_config_preflight(env, repo_root=repo_root)
    config_dir_value = env.get("CFO_TIGER_CONFIG_DIR", "").strip()
    config_dir = Path(config_dir_value) if config_dir_value else None
    props_file = config_dir / DEFAULT_PROPS_FILE if config_dir else None
    required_keys_present = {
        "tiger_id": preflight.tiger_id_present,
        "account": preflight.account_present or preflight.config_account_present,
        "private_key": preflight.private_key_field_present
        or preflight.private_key_path_present,
    }

    try:
        tigeropen_module = importlib.import_module("tigeropen")
        config_module = importlib.import_module("tigeropen.tiger_open_config")
        client_module = importlib.import_module(
            ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"])
        )
    except ImportError as exc:
        variant_results: tuple[TigerSDKConfigProbeVariant, ...] = ()
        return TigerSDKConfigProbe(
            sdk_import_ok=False,
            tigeropen_package_path="unavailable",
            props_path_modes_tested=SDK_CONFIG_PROBE_MODES,
            working_props_path_mode="none",
            expected_config_filename=DEFAULT_PROPS_FILE,
            config_file_detected=preflight.config_file_exists,
            required_keys_present_redacted=required_keys_present,
            private_key_format_category=preflight.private_key_format_category,
            sdk_config_constructed=False,
            sdk_client_constructed=False,
            sdk_exception_class_sanitized=_safe_exception_name(exc),
            sdk_exception_category="sdk_import",
            variant_results=variant_results,
            warning_codes=(
                WarningCode.SDK_NOT_INSTALLED,
                WarningCode.TIGER_SDK_CONFIG_PROBE_FAILED,
                WarningCode.TIGER_SDK_EXCEPTION_SANITIZED,
            ),
        )

    sdk = {
        "config_module": config_module,
        "client_cls": getattr(client_module, "Tr" + "adeClient"),
    }
    results = tuple(
        _probe_sdk_config_variant(mode, sdk, config_dir, props_file, env)
        for mode in SDK_CONFIG_PROBE_MODES
    )
    working = _select_probe_result(results, require_client=False)
    client_success = _select_probe_result(results, require_client=True)
    terminal = client_success or working or (results[-1] if results else None)
    warning_codes = _sdk_probe_warning_codes(results, terminal)
    return TigerSDKConfigProbe(
        sdk_import_ok=True,
        tigeropen_package_path=_redact_user_home(getattr(tigeropen_module, "__file__", "")),
        props_path_modes_tested=SDK_CONFIG_PROBE_MODES,
        working_props_path_mode=working.mode if working else "none",
        expected_config_filename=DEFAULT_PROPS_FILE,
        config_file_detected=preflight.config_file_exists,
        required_keys_present_redacted=required_keys_present,
        private_key_format_category=preflight.private_key_format_category,
        sdk_config_constructed=working is not None,
        sdk_client_constructed=client_success is not None,
        sdk_exception_class_sanitized=(
            terminal.exception_class_sanitized if terminal else "None"
        ),
        sdk_exception_category=terminal.exception_category if terminal else "none",
        variant_results=results,
        warning_codes=warning_codes,
    )


def run_tiger_config_preflight(
    env: Mapping[str, str], repo_root: Path | None = None
) -> TigerConfigPreflight:
    enabled_present = _present(env, "CFO_TIGER_ENABLED")
    enabled_true = env_bool(env, "CFO_TIGER_ENABLED")
    config_dir_value = env.get("CFO_TIGER_CONFIG_DIR", "").strip()
    config_dir_present = bool(config_dir_value)
    config_dir = Path(config_dir_value) if config_dir_value else None
    config_dir_exists = bool(config_dir and config_dir.exists())
    config_dir_is_directory = bool(config_dir and config_dir.exists() and config_dir.is_dir())
    props_path_matches_adapter = bool(config_dir_present and config_dir_is_directory)
    props_path = (config_dir / DEFAULT_PROPS_FILE) if config_dir else None
    config_file_exists = bool(props_path and props_path.exists() and props_path.is_file())

    text, config_file_readable = _read_config_text_strict(props_path)
    pairs = _properties_pairs(text) if text is not None else {}
    repo = (repo_root or Path.cwd()).resolve()
    config_file_outside_repo = bool(
        props_path and config_file_exists and not _is_path_inside(props_path, repo)
    )
    config_file_tracked = bool(props_path and _git_file_tracked(repo, props_path))
    config_history_risk = _git_history_risk(repo)

    tiger_id_present = _present(env, "TIGEROPEN_TIGER_ID") or bool(
        pairs.get("tiger_id", "").strip()
    )
    account_present = _present(env, "CFO_TIGER_ACCOUNT")
    config_account_present = _present(env, "TIGEROPEN_ACCOUNT") or bool(
        pairs.get("account", "").strip()
    )
    private_key_field_present = any(
        pairs.get(key, "").strip() for key in TIGEROPEN_PRIVATE_KEY_PROPERTY_FIELDS
    )
    private_key_path_present = _present(env, "TIGEROPEN_PRIVATE_KEY") or bool(
        pairs.get("private_key", "").strip() or pairs.get("private_key_path", "").strip()
    )
    private_key_format_category = _detect_preflight_private_key_format(pairs, env)

    warning_codes = _preflight_warning_codes(
        enabled_true=enabled_true,
        config_dir_present=config_dir_present,
        config_dir_exists=config_dir_exists,
        config_dir_is_directory=config_dir_is_directory,
        config_file_exists=config_file_exists,
        config_file_readable=config_file_readable,
        config_file_outside_repo=config_file_outside_repo,
        config_file_tracked=config_file_tracked,
        config_history_risk=config_history_risk,
        tiger_id_present=tiger_id_present,
        account_present=account_present,
        config_account_present=config_account_present,
        private_key_field_present=private_key_field_present,
        private_key_path_present=private_key_path_present,
        private_key_format_category=private_key_format_category,
    )
    return TigerConfigPreflight(
        enabled_present=enabled_present,
        enabled_true=enabled_true,
        config_dir_present=config_dir_present,
        config_dir_exists=config_dir_exists,
        config_dir_is_directory=config_dir_is_directory,
        expected_config_file_pattern=PREFLIGHT_CONFIG_FILE_PATTERN,
        expected_props_filename=DEFAULT_PROPS_FILE,
        props_path_expectation=PREFLIGHT_PROPS_PATH_EXPECTATION,
        props_path_matches_adapter=props_path_matches_adapter,
        config_file_exists=config_file_exists,
        config_file_readable=config_file_readable,
        config_file_outside_repo=config_file_outside_repo,
        config_file_tracked=config_file_tracked,
        config_history_risk=config_history_risk,
        tiger_id_present=tiger_id_present,
        account_present=account_present,
        config_account_present=config_account_present,
        private_key_field_present=private_key_field_present,
        private_key_path_present=private_key_path_present,
        private_key_format_category=private_key_format_category,
        warning_codes=warning_codes,
    )


def _probe_sdk_config_variant(
    mode: str,
    sdk: dict[str, Any],
    config_dir: Path | None,
    props_file: Path | None,
    env: Mapping[str, str],
) -> TigerSDKConfigProbeVariant:
    try:
        with _suppress_sdk_console_output():
            config = _construct_probe_config(mode, sdk["config_module"], config_dir, props_file, env)
        _apply_probe_account(config, env)
        missing_keys = _missing_loaded_config_keys(config)
        if missing_keys:
            return TigerSDKConfigProbeVariant(
                mode=mode,
                config_constructed=False,
                client_constructed=False,
                exception_class_sanitized="None",
                exception_category="required_key_missing",
                warning_codes=_dedupe_warning_codes(
                    [
                        _mode_failure_code(mode),
                        WarningCode.TIGER_CONFIG_REQUIRED_KEY_MISSING,
                    ]
                ),
            )
    except Exception as exc:
        return TigerSDKConfigProbeVariant(
            mode=mode,
            config_constructed=False,
            client_constructed=False,
            exception_class_sanitized=_safe_exception_name(exc),
            exception_category=_sdk_exception_category(exc),
            warning_codes=_dedupe_warning_codes(
                [
                    _mode_failure_code(mode),
                    WarningCode.TIGER_PROPS_PATH_MODE_FAILED,
                    WarningCode.TIGER_SDK_EXCEPTION_SANITIZED,
                ]
            ),
        )

    try:
        _disable_probe_token_refresh(config)
        with _suppress_sdk_console_output():
            sdk["client_cls"](config)
    except Exception as exc:
        return TigerSDKConfigProbeVariant(
            mode=mode,
            config_constructed=True,
            client_constructed=False,
            exception_class_sanitized=_safe_exception_name(exc),
            exception_category=_sdk_exception_category(exc),
            warning_codes=_dedupe_warning_codes(
                [
                    WarningCode.TIGER_SDK_CONFIG_CONSTRUCTED,
                    WarningCode.TIGER_SDK_EXCEPTION_SANITIZED,
                ]
            ),
        )

    return TigerSDKConfigProbeVariant(
        mode=mode,
        config_constructed=True,
        client_constructed=True,
        exception_class_sanitized="None",
        exception_category="none",
        warning_codes=(
            WarningCode.TIGER_SDK_CONFIG_CONSTRUCTED,
            WarningCode.TIGER_SDK_CLIENT_CONSTRUCTED,
        ),
    )


def _construct_probe_config(
    mode: str,
    config_module: Any,
    config_dir: Path | None,
    props_file: Path | None,
    env: Mapping[str, str],
) -> Any:
    config_cls = getattr(config_module, "TigerOpenClientConfig", None)
    get_config = getattr(config_module, "get_client_config", None)
    if mode == "directory":
        return config_cls(props_path=str(config_dir))
    if mode == "file":
        return config_cls(props_path=str(props_file))
    if mode == "explicit_props_path":
        return get_config(props_path=str(config_dir))
    if mode == "sdk_default":
        return config_cls()
    raise ValueError("unsupported Tiger SDK config probe mode")


def _apply_probe_account(config: Any, env: Mapping[str, str]) -> None:
    account_id = env.get("CFO_TIGER_ACCOUNT", "").strip()
    if account_id and hasattr(config, "account") and not getattr(config, "account", None):
        setattr(config, "account", account_id)


def _missing_loaded_config_keys(config: Any) -> list[str]:
    missing: list[str] = []
    if not getattr(config, "tiger_id", None):
        missing.append("tiger_id")
    if not getattr(config, "account", None):
        missing.append("account")
    if not getattr(config, "private_key", None):
        missing.append("private_key")
    return missing


def _disable_probe_token_refresh(config: Any) -> None:
    # Avoid creating a background token refresh thread during the no-data probe.
    if getattr(config, "token", None) and getattr(config, "license", None):
        try:
            setattr(config, "_token", None)
        except Exception:
            return


def _sdk_probe_warning_codes(
    results: tuple[TigerSDKConfigProbeVariant, ...],
    terminal: TigerSDKConfigProbeVariant | None,
) -> tuple[WarningCode, ...]:
    if any(result.client_constructed for result in results):
        return (
            WarningCode.TIGER_SDK_CONFIG_CONSTRUCTED,
            WarningCode.TIGER_SDK_CLIENT_CONSTRUCTED,
        )
    if any(result.config_constructed for result in results):
        return (WarningCode.TIGER_SDK_CONFIG_CONSTRUCTED,)
    codes: list[WarningCode] = []
    for result in results:
        codes.extend(result.warning_codes)
    if terminal is not None and terminal.exception_class_sanitized != "None":
        codes.append(WarningCode.TIGER_SDK_EXCEPTION_SANITIZED)
    return _dedupe_warning_codes([*codes, WarningCode.TIGER_SDK_CONFIG_PROBE_FAILED])


def _select_probe_result(
    results: tuple[TigerSDKConfigProbeVariant, ...], *, require_client: bool
) -> TigerSDKConfigProbeVariant | None:
    priority = ("directory", "file", "explicit_props_path", "sdk_default")
    for mode in priority:
        for result in results:
            if result.mode != mode:
                continue
            if require_client and result.client_constructed:
                return result
            if not require_client and result.config_constructed:
                return result
    return None


def _mode_failure_code(mode: str) -> WarningCode:
    if mode == "directory":
        return WarningCode.TIGER_PROPS_PATH_DIRECTORY_FAILED
    if mode == "file":
        return WarningCode.TIGER_PROPS_PATH_FILE_FAILED
    if mode == "sdk_default":
        return WarningCode.TIGER_SDK_DEFAULT_CONFIG_FAILED
    return WarningCode.TIGER_EXPLICIT_CONFIG_OBJECT_FAILED


def _safe_exception_name(exc: BaseException) -> str:
    return exc.__class__.__name__


def _sdk_exception_category(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__} {str(exc)}".lower()
    if "private" in text and "key" in text:
        return "private_key"
    if "tiger id" in text or "tiger_id" in text:
        return "tiger_id"
    if "account" in text:
        return "account"
    if "props" in text or "properties" in text:
        return "props_path"
    if "domain" in text or "network" in text or "timeout" in text:
        return "sdk_network_metadata"
    if "auth" in text or "permission" in text or "signature" in text:
        return "auth"
    return "unknown"


@contextmanager
def _suppress_sdk_console_output():
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        yield


def _redact_user_home(value: object) -> str:
    text = str(value or "")
    home = str(Path.home())
    return text.replace(home, "<USER_HOME>")


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


def _read_config_text_strict(path: Path | None) -> tuple[str | None, bool]:
    if path is None or not path.exists() or not path.is_file():
        return None, False
    try:
        return path.read_text(encoding="utf-8"), True
    except (OSError, UnicodeError):
        return None, False


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


def _preflight_warning_codes(
    *,
    enabled_true: bool,
    config_dir_present: bool,
    config_dir_exists: bool,
    config_dir_is_directory: bool,
    config_file_exists: bool,
    config_file_readable: bool,
    config_file_outside_repo: bool,
    config_file_tracked: bool,
    config_history_risk: bool,
    tiger_id_present: bool,
    account_present: bool,
    config_account_present: bool,
    private_key_field_present: bool,
    private_key_path_present: bool,
    private_key_format_category: str,
) -> tuple[WarningCode, ...]:
    codes: list[WarningCode] = []
    if not enabled_true:
        codes.append(WarningCode.PROVIDER_DISABLED)
    if not config_dir_present or not config_dir_exists:
        codes.append(WarningCode.TIGER_CONFIG_DIR_MISSING)
    if config_dir_present and config_dir_exists and not config_dir_is_directory:
        codes.append(WarningCode.TIGER_PROPS_PATH_MISMATCH)
    if not config_file_exists:
        codes.append(WarningCode.TIGER_CONFIG_FILE_MISSING)
    elif not config_file_readable:
        codes.append(WarningCode.TIGER_CONFIG_FILE_UNREADABLE)
    if config_file_exists and not config_file_outside_repo:
        codes.append(WarningCode.TIGER_CONFIG_FILE_INSIDE_REPO)
    if config_file_tracked:
        codes.append(WarningCode.TIGER_CONFIG_FILE_TRACKED)
    if config_history_risk:
        codes.append(WarningCode.TIGER_CONFIG_HISTORY_RISK)
    if not tiger_id_present or (not account_present and not config_account_present):
        codes.append(WarningCode.TIGER_CONFIG_REQUIRED_KEY_MISSING)
    if not private_key_field_present and not private_key_path_present:
        codes.append(WarningCode.TIGER_PRIVATE_KEY_FIELD_MISSING)
    if private_key_format_category == "unknown_format":
        codes.append(WarningCode.TIGER_PRIVATE_KEY_FORMAT_UNKNOWN)
    if codes:
        return _dedupe_warning_codes(
            [*codes, WarningCode.PROVIDER_CONFIG_MISSING, WarningCode.TIGER_CONFIG_PREFLIGHT_FAILED]
        )
    return (WarningCode.TIGER_CONFIG_PREFLIGHT_OK,)


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


def _detect_preflight_private_key_format(
    pairs: dict[str, str], env: Mapping[str, str]
) -> str:
    if pairs.get("private_key_pk1", "").strip():
        return "pkcs1_like"
    if pairs.get("private_key_pk8", "").strip():
        return "pkcs8_like"
    value = pairs.get("private_key", "").strip() or pairs.get("private_key_path", "").strip()
    if value:
        lowered = value.lower()
        if "begin rsa private key" in lowered:
            return "pkcs1_like"
        if "begin private key" in lowered:
            return "pkcs8_like"
        return "unknown_format"
    env_value = env.get("TIGEROPEN_PRIVATE_KEY", "").strip()
    if env_value:
        lowered = env_value.lower()
        if "begin rsa private key" in lowered:
            return "pkcs1_like"
        if "begin private key" in lowered:
            return "pkcs8_like"
        return "unknown_format"
    return "missing"


def _dedupe_warning_codes(codes: list[WarningCode]) -> tuple[WarningCode, ...]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return tuple(result)


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _git_file_tracked(repo_root: Path, path: Path) -> bool:
    if not _is_path_inside(path, repo_root):
        return False
    try:
        relative_path = path.resolve().relative_to(repo_root)
    except ValueError:
        return False
    result = _run_git(repo_root, ["ls-files", "--", relative_path.as_posix()])
    return bool(result and result.stdout.strip())


def _git_history_risk(repo_root: Path) -> bool:
    result = _run_git(
        repo_root,
        [
            "log",
            "--all",
            "--format=%H",
            "--",
            ":(glob)**/tiger_openapi_config*",
            ":(glob)**/*_tiger_openapi_config.properties",
            ":(glob)**/tiger_openapi_token*",
            ":(glob)**/*.pem",
            ":(glob)**/*.key",
        ],
    )
    return bool(result and result.stdout.strip())


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
