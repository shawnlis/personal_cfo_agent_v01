"""Redacted Webull OpenAPI readiness diagnostics.

This module intentionally performs local-only checks: environment/config presence and
SDK importability. It does not construct an API client or send network traffic.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import Callable, Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode


DEFAULT_WEBULL_SDK_MODULE_CANDIDATES = (
    "webull",
    "webull_openapi",
    "webull.openapi",
    "webull_openapi_python_sdk",
)


@dataclass(frozen=True)
class WebullConnectionDiagnostics:
    enabled_present: bool
    enabled_true: bool
    app_key_present: bool
    app_secret_present: bool
    api_host_present: bool
    sdk_module_candidates: tuple[str, ...]
    sdk_import_ok: bool
    sdk_module_detected: str
    python_executable: str
    live_connection_attempted: bool
    warning_codes: tuple[WarningCode, ...]


def run_webull_connection_diagnostics(
    env: Mapping[str, str],
    import_module: Callable[[str], object] | None = None,
) -> WebullConnectionDiagnostics:
    module_candidates = _sdk_module_candidates(env)
    sdk_import_ok, sdk_module_detected = _detect_sdk(
        module_candidates,
        import_module=import_module or importlib.import_module,
    )
    enabled_true = env_bool(env, "CFO_WEBULL_ENABLED")
    app_key_present = _present(env, "CFO_WEBULL_APP_KEY")
    app_secret_present = _present(env, "CFO_WEBULL_APP_SECRET")
    warning_codes = _warning_codes(
        enabled_true=enabled_true,
        app_key_present=app_key_present,
        app_secret_present=app_secret_present,
        sdk_import_ok=sdk_import_ok,
    )
    return WebullConnectionDiagnostics(
        enabled_present=_present(env, "CFO_WEBULL_ENABLED"),
        enabled_true=enabled_true,
        app_key_present=app_key_present,
        app_secret_present=app_secret_present,
        api_host_present=_present(env, "CFO_WEBULL_API_HOST"),
        sdk_module_candidates=module_candidates,
        sdk_import_ok=sdk_import_ok,
        sdk_module_detected=sdk_module_detected,
        python_executable=sys.executable,
        live_connection_attempted=False,
        warning_codes=warning_codes,
    )


def _sdk_module_candidates(env: Mapping[str, str]) -> tuple[str, ...]:
    configured = env.get("CFO_WEBULL_SDK_MODULE", "").strip()
    if configured:
        return (configured,)
    return DEFAULT_WEBULL_SDK_MODULE_CANDIDATES


def _detect_sdk(
    candidates: tuple[str, ...],
    import_module: Callable[[str], object],
) -> tuple[bool, str]:
    for candidate in candidates:
        try:
            import_module(candidate)
        except Exception:
            continue
        return True, candidate
    return False, "unavailable"


def _warning_codes(
    *,
    enabled_true: bool,
    app_key_present: bool,
    app_secret_present: bool,
    sdk_import_ok: bool,
) -> tuple[WarningCode, ...]:
    if not enabled_true:
        return (WarningCode.PROVIDER_DISABLED,)
    if not app_key_present or not app_secret_present:
        return (WarningCode.PROVIDER_CONFIG_MISSING,)
    if not sdk_import_ok:
        return (WarningCode.SDK_NOT_INSTALLED,)
    return (WarningCode.WEBULL_READINESS_OK,)


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())
