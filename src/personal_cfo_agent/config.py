"""Environment-only configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from personal_cfo_agent.models import WarningCode


TRUE_VALUES = {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class RuntimeConfig:
    allow_live_read: bool = False
    provider: str = "all"
    readiness_check: bool = False
    ibkr_data_diagnostics: bool = False
    moomoo_data_diagnostics: bool = False
    tiger_data_diagnostics: bool = False
    webull_data_diagnostics: bool = False
    manual_snapshot_path: Path | None = None
    dashboard: bool = False
    dashboard_assumptions_path: Path | None = None
    output_root: Path = Path("reports/personal_cfo_agent/v01")
    output_dir: Path | None = None
    as_of_date: str | None = None
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))


@dataclass(frozen=True)
class ProviderConfig:
    provider_name: str
    enabled: bool
    required_env_vars: tuple[str, ...]
    credentials_source: str = "environment_variables"
    settings: Mapping[str, str] = field(default_factory=dict)
    warning_codes: tuple[WarningCode, ...] = ()

    def missing_required_env_vars(self) -> list[str]:
        if not self.enabled:
            return []
        return [key for key in self.required_env_vars if not self.settings.get(key)]


CONNECTOR_STATUS_MATRIX: dict[str, dict[str, object]] = {
    "ibkr": {
        "status": "read_only_live_proof_accepted",
        "method": "TWS API / IB Gateway through supervised local session",
        "asset_read": True,
        "position_read": True,
        "cash_read": True,
        "implementation_priority": 1,
        "notes": "v0.2.2 supervised read-only proof and safe local sync workflow; TWS or IB Gateway must be started manually",
    },
    "moomoo": {
        "status": "read_only_live_proof_accepted",
        "method": "OpenD + SDK through supervised local session",
        "asset_read": True,
        "position_read": True,
        "cash_read": True,
        "implementation_priority": 1,
        "notes": "v0.3.2 supervised read-only proof; redacted get_acc_list account discovery required before funds/positions/cash read",
    },
    "tiger": {
        "status": "read_only_live_proof_accepted",
        "method": "TigerOpen Python SDK through supervised local configuration",
        "asset_read": True,
        "position_read": True,
        "cash_read": True,
        "implementation_priority": 2,
        "notes": "v0.3.1 supervised read-only proof; TigerOpen must be configured locally",
    },
    "webull": {
        "status": "supervised_read_only_live_proof_in_progress",
        "method": "official OpenAPI account list, account balance, and account positions through supervised local session",
        "asset_read": True,
        "position_read": True,
        "cash_read": True,
        "implementation_priority": None,
        "notes": "v0.5.6 adds explicit --allow-live-read supervised read-only proof path; no execution or cash movement workflow",
    },
    "poems": {
        "status": "unsupported_until_official_api_verified",
        "method": "no official retail account API confirmed",
        "implementation_priority": None,
        "notes": "manual snapshot only unless an official API is verified",
    },
    "cpf": {
        "status": "indirect_via_sgfindex_or_manual_snapshot",
        "method": "SGFinDex user-facing aggregation / manual update",
        "implementation_priority": "manual_only",
        "notes": "do not automate identity login or scrape government portals",
    },
    "iras": {
        "status": "indirect_via_sgfindex_or_manual_snapshot",
        "method": "SGFinDex user-facing aggregation / manual update",
        "implementation_priority": "manual_only",
        "notes": "do not automate identity login or scrape government portals",
    },
    "hdb": {
        "status": "indirect_via_sgfindex_or_manual_snapshot",
        "method": "SGFinDex user-facing aggregation / manual update",
        "implementation_priority": "manual_only",
        "notes": "do not automate identity login or scrape government portals",
    },
}


def env_bool(env: Mapping[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in TRUE_VALUES


def load_ibkr_config(env: Mapping[str, str]) -> ProviderConfig:
    required = (
        "CFO_IBKR_HOST",
        "CFO_IBKR_PORT",
        "CFO_IBKR_CLIENT_ID",
    )
    return ProviderConfig(
        provider_name="ibkr",
        enabled=env_bool(env, "CFO_IBKR_ENABLED"),
        required_env_vars=required,
        settings={
            key: env.get(key, "")
            for key in (
                "CFO_IBKR_ENABLED",
                *required,
                "CFO_IBKR_ACCOUNT",
                "CFO_ACCOUNT_HASH_SALT",
            )
        },
    )


def load_moomoo_config(env: Mapping[str, str]) -> ProviderConfig:
    required = ("CFO_MOOMOO_HOST", "CFO_MOOMOO_PORT")
    return ProviderConfig(
        provider_name="moomoo",
        enabled=env_bool(env, "CFO_MOOMOO_ENABLED"),
        required_env_vars=required,
        settings={
            key: env.get(key, "")
            for key in ("CFO_MOOMOO_ENABLED", *required, "CFO_ACCOUNT_HASH_SALT")
        },
    )


def load_tiger_config(env: Mapping[str, str]) -> ProviderConfig:
    required = ("CFO_TIGER_CONFIG_DIR", "CFO_TIGER_ACCOUNT")
    return ProviderConfig(
        provider_name="tiger",
        enabled=env_bool(env, "CFO_TIGER_ENABLED"),
        required_env_vars=required,
        settings={
            key: env.get(key, "")
            for key in (
                "CFO_TIGER_ENABLED",
                *required,
                "CFO_TIGER_BASE_CURRENCY",
                "CFO_ACCOUNT_HASH_SALT",
            )
        },
    )


def load_webull_config(env: Mapping[str, str]) -> ProviderConfig:
    required = ("CFO_WEBULL_APP_KEY", "CFO_WEBULL_APP_SECRET")
    return ProviderConfig(
        provider_name="webull",
        enabled=env_bool(env, "CFO_WEBULL_ENABLED"),
        required_env_vars=required,
        settings={
            key: env.get(key, "")
            for key in (
                "CFO_WEBULL_ENABLED",
                *required,
                "CFO_WEBULL_API_HOST",
                "CFO_WEBULL_SDK_MODULE",
                "CFO_WEBULL_TOTAL_ASSET_CURRENCY",
                "CFO_WEBULL_ACCOUNT_HASH_SELECTOR",
                "CFO_WEBULL_ACCOUNT_HASH",
                "CFO_WEBULL_ACCOUNT_ID_HASH",
                "CFO_ACCOUNT_HASH_SALT",
            )
        },
    )


def load_manual_config(
    env: Mapping[str, str], manual_snapshot_path: Path | None
) -> ProviderConfig:
    configured_path = manual_snapshot_path or _path_from_env(env, "CFO_MANUAL_SNAPSHOT_PATH")
    return ProviderConfig(
        provider_name="manual_snapshot",
        enabled=configured_path is not None,
        required_env_vars=(),
        credentials_source="explicit_path_or_environment_variable",
        settings={"CFO_MANUAL_SNAPSHOT_PATH": str(configured_path or "")},
    )


def connector_status(provider_name: str) -> dict[str, object]:
    key = provider_name.strip().lower()
    if key not in CONNECTOR_STATUS_MATRIX:
        return {
            "status": "unsupported_provider",
            "warning_codes": [
                WarningCode.UNSUPPORTED_PROVIDER.value,
                WarningCode.UNOFFICIAL_API_BLOCKED.value,
            ],
        }
    status = dict(CONNECTOR_STATUS_MATRIX[key])
    if key == "webull":
        status["warning_codes"] = []
    elif str(status.get("status", "")).startswith("unsupported"):
        status["warning_codes"] = [
            WarningCode.UNSUPPORTED_PROVIDER.value,
            WarningCode.UNOFFICIAL_API_BLOCKED.value,
            WarningCode.MANUAL_SNAPSHOT_REQUIRED.value,
        ]
    return status


def _path_from_env(env: Mapping[str, str], key: str) -> Path | None:
    raw_value = env.get(key, "").strip()
    if not raw_value:
        return None
    return Path(raw_value)
