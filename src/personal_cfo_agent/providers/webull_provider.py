"""Webull provider scaffold with readiness-only diagnostics."""

from __future__ import annotations

from personal_cfo_agent.models import (
    ConnectionMode,
    ProviderLevel,
    RawAccount,
    RawBalance,
    RawCash,
    RawPosition,
    WarningCode,
)
from personal_cfo_agent.provider_base import ProviderBase
from personal_cfo_agent.providers.webull_connection_diagnostics import (
    run_webull_connection_diagnostics,
)


class WebullProvider(ProviderBase):
    provider_name = "webull"
    provider_level = ProviderLevel.LEVEL_1
    connection_mode = ConnectionMode.API_STUB

    def validate_config(self) -> list[WarningCode]:
        diagnostics = run_webull_connection_diagnostics(self.config.settings)
        self.diagnostics = _diagnostics_dict(diagnostics)
        return [code for code in diagnostics.warning_codes if code != WarningCode.WEBULL_READINESS_OK]

    def readiness_check(self) -> list[WarningCode]:
        diagnostics = run_webull_connection_diagnostics(self.config.settings)
        self.diagnostics = _diagnostics_dict(diagnostics)
        self.warning_codes = _dedupe([*self.warning_codes, *diagnostics.warning_codes])
        self.connection_mode = ConnectionMode.LIVE_READINESS
        return self.warning_codes

    def connection_diagnostics(self):
        return run_webull_connection_diagnostics(self.config.settings)

    def connect_read_only(self) -> bool:
        if WarningCode.PROVIDER_DISABLED in self.warning_codes:
            return False
        if WarningCode.PROVIDER_CONFIG_MISSING in self.warning_codes:
            return False
        if WarningCode.SDK_NOT_INSTALLED in self.warning_codes:
            return False
        self.warning_codes = _dedupe(
            [*self.warning_codes, WarningCode.LIVE_READ_NOT_ALLOWED]
        )
        return False

    def fetch_accounts(self) -> list[RawAccount]:
        return []

    def fetch_cash(self) -> list[RawCash]:
        return []

    def fetch_positions(self) -> list[RawPosition]:
        return []

    def fetch_balances(self) -> list[RawBalance]:
        return []

    def disconnect(self) -> None:
        return None


def _diagnostics_dict(diagnostics) -> dict[str, object]:
    return {
        "enabled_present": diagnostics.enabled_present,
        "enabled_true": diagnostics.enabled_true,
        "app_key_present_redacted": diagnostics.app_key_present,
        "app_secret_present_redacted": diagnostics.app_secret_present,
        "api_host_present_redacted": diagnostics.api_host_present,
        "sdk_import_ok": diagnostics.sdk_import_ok,
        "sdk_module_detected": diagnostics.sdk_module_detected,
        "live_connection_attempted": diagnostics.live_connection_attempted,
        "warning_codes": [code.value for code in diagnostics.warning_codes],
    }


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
