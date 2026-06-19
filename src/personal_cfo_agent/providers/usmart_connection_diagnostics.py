"""Redacted uSMART API readiness diagnostics.

This module performs local-only checks: environment/config presence and SDK
importability. It does not construct an API client or send network traffic.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import Callable, Mapping

from personal_cfo_agent.config import env_bool
from personal_cfo_agent.models import WarningCode


DEFAULT_USMART_SDK_MODULE_CANDIDATES = (
    "usmart",
    "usmart_openapi",
    "usmart.openapi",
)


@dataclass(frozen=True)
class USMARTConnectionDiagnostics:
    enabled_present: bool
    enabled_true: bool
    api_key_present: bool
    api_secret_present: bool
    api_host_present: bool
    sdk_module_candidates: tuple[str, ...]
    sdk_import_ok: bool
    sdk_module_detected: str
    python_executable: str
    live_connection_attempted: bool
    warning_codes: tuple[WarningCode, ...]


def run_usmart_connection_diagnostics(
    env: Mapping[str, str],
    import_module: Callable[[str], object] | None = None,
) -> USMARTConnectionDiagnostics:
    module_candidates = _sdk_module_candidates(env)
    sdk_import_ok, sdk_module_detected = _detect_sdk(
        module_candidates,
        import_module=import_module or importlib.import_module,
    )
    enabled_true = env_bool(env, "CFO_USMART_ENABLED")
    api_key_present = _present(env, "CFO_USMART_API_KEY")
    api_secret_present = _present(env, "CFO_USMART_API_SECRET")
    warning_codes = _warning_codes(
        enabled_true=enabled_true,
        api_key_present=api_key_present,
        api_secret_present=api_secret_present,
        sdk_import_ok=sdk_import_ok,
    )
    return USMARTConnectionDiagnostics(
        enabled_present=_present(env, "CFO_USMART_ENABLED"),
        enabled_true=enabled_true,
        api_key_present=api_key_present,
        api_secret_present=api_secret_present,
        api_host_present=_present(env, "CFO_USMART_API_HOST"),
        sdk_module_candidates=module_candidates,
        sdk_import_ok=sdk_import_ok,
        sdk_module_detected=sdk_module_detected,
        python_executable=sys.executable,
        live_connection_attempted=False,
        warning_codes=warning_codes,
    )


def _sdk_module_candidates(env: Mapping[str, str]) -> tuple[str, ...]:
    configured = env.get("CFO_USMART_SDK_MODULE", "").strip()
    if configured:
        return (configured,)
    return DEFAULT_USMART_SDK_MODULE_CANDIDATES


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
    api_key_present: bool,
    api_secret_present: bool,
    sdk_import_ok: bool,
) -> tuple[WarningCode, ...]:
    if not enabled_true:
        return (WarningCode.PROVIDER_DISABLED,)
    if not api_key_present or not api_secret_present:
        return (WarningCode.PROVIDER_CONFIG_MISSING,)
    if not sdk_import_ok:
        return (WarningCode.SDK_NOT_INSTALLED,)
    return (WarningCode.USMART_READINESS_OK,)


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())
