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
    manual_snapshot_path: Path | None = None
    output_root: Path = Path("reports/personal_cfo_agent/v01")
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
        "status": "supported_candidate",
        "method": "TWS API / IB Gateway / Client Portal later",
        "asset_read": True,
        "position_read": True,
        "cash_read": True,
        "implementation_priority": 1,
        "notes": "read-only wrapper required",
    },
    "moomoo": {
        "status": "supported_candidate",
        "method": "OpenD + SDK",
        "asset_read": "likely_yes",
        "position_read": "likely_yes",
        "cash_read": "likely_yes",
        "implementation_priority": 1,
        "notes": "OpenD local gateway required; read-only wrapper required",
    },
    "tiger": {
        "status": "supported_candidate",
        "method": "TigerOpen Python SDK",
        "asset_read": True,
        "position_read": True,
        "cash_read": True,
        "implementation_priority": 2,
        "notes": "SDK includes account-write surfaces, so read-only wrapper required",
    },
    "webull": {
        "status": "unsupported_until_official_api_verified",
        "method": "no official retail API confirmed",
        "implementation_priority": None,
        "notes": "manual snapshot only unless an official account API is verified",
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
        "CFO_IBKR_ACCOUNT",
    )
    return ProviderConfig(
        provider_name="ibkr",
        enabled=env_bool(env, "CFO_IBKR_ENABLED"),
        required_env_vars=required,
        settings={key: env.get(key, "") for key in ("CFO_IBKR_ENABLED", *required)},
    )


def load_moomoo_config(env: Mapping[str, str]) -> ProviderConfig:
    required = ("CFO_MOOMOO_HOST", "CFO_MOOMOO_PORT")
    return ProviderConfig(
        provider_name="moomoo",
        enabled=env_bool(env, "CFO_MOOMOO_ENABLED"),
        required_env_vars=required,
        settings={key: env.get(key, "") for key in ("CFO_MOOMOO_ENABLED", *required)},
    )


def load_tiger_config(env: Mapping[str, str]) -> ProviderConfig:
    required = ("CFO_TIGER_CONFIG_DIR", "CFO_TIGER_ACCOUNT")
    return ProviderConfig(
        provider_name="tiger",
        enabled=env_bool(env, "CFO_TIGER_ENABLED"),
        required_env_vars=required,
        settings={key: env.get(key, "") for key in ("CFO_TIGER_ENABLED", *required)},
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
    if str(status.get("status", "")).startswith("unsupported"):
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
