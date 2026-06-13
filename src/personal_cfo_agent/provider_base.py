"""Read-only provider contract for Personal CFO Agent v0.1."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from personal_cfo_agent.config import ProviderConfig
from personal_cfo_agent.models import (
    ConnectionMode,
    ProviderLevel,
    ProviderStatus,
    RawAccount,
    RawBalance,
    RawCash,
    RawPosition,
    RawProviderSnapshot,
    WarningCode,
)


class ProviderBase(ABC):
    """Base class exposing the v0.1 read-only account data contract."""

    provider_name: str
    provider_level: ProviderLevel
    connection_mode: ConnectionMode

    def __init__(self, config: ProviderConfig, allow_live_read: bool = False) -> None:
        self.config = config
        self.allow_live_read = allow_live_read
        self.read_only = True
        self.trading_enabled = False
        self.order_placement_enabled = False
        self.credentials_source = config.credentials_source
        self.last_sync_time: str | None = None
        self.warning_codes: list[WarningCode] = list(config.warning_codes)
        self.raw_snapshot_path: str | None = None
        self.normalized_positions: list[dict[str, object]] = []

    @abstractmethod
    def validate_config(self) -> list[WarningCode]:
        """Validate provider configuration without touching the network."""

    @abstractmethod
    def connect_read_only(self) -> bool:
        """Prepare for read-only data collection."""

    @abstractmethod
    def fetch_accounts(self) -> list[RawAccount]:
        """Fetch account descriptors."""

    @abstractmethod
    def fetch_cash(self) -> list[RawCash]:
        """Fetch cash balances."""

    @abstractmethod
    def fetch_positions(self) -> list[RawPosition]:
        """Fetch security and asset positions."""

    @abstractmethod
    def fetch_balances(self) -> list[RawBalance]:
        """Fetch liability or account balance rows."""

    @abstractmethod
    def disconnect(self) -> None:
        """Release provider resources."""

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_name=self.provider_name,
            provider_level=self.provider_level,
            connection_mode=self.connection_mode,
            read_only=self.read_only,
            trading_enabled=self.trading_enabled,
            order_placement_enabled=self.order_placement_enabled,
            credentials_source=self.credentials_source,
            last_sync_time=self.last_sync_time,
            warning_codes=self.warning_codes,
            raw_snapshot_path=self.raw_snapshot_path,
            normalized_positions=self.normalized_positions,
        )

    def sync(self) -> RawProviderSnapshot:
        self.warning_codes = _dedupe_codes([*self.warning_codes, *self.validate_config()])
        if WarningCode.PROVIDER_CONFIG_MISSING in self.warning_codes:
            return self._empty_snapshot()

        connected = self.connect_read_only()
        if not connected:
            return self._empty_snapshot()

        try:
            accounts = self.fetch_accounts()
            cash = self.fetch_cash()
            positions = self.fetch_positions()
            balances = self.fetch_balances()
            self.last_sync_time = datetime.now(timezone.utc).isoformat()
            return RawProviderSnapshot(
                provider_name=self.provider_name,
                status=self.status(),
                accounts=accounts,
                cash=cash,
                positions=positions,
                balances=balances,
            )
        finally:
            self.disconnect()

    def _empty_snapshot(self) -> RawProviderSnapshot:
        return RawProviderSnapshot(provider_name=self.provider_name, status=self.status())


class ReadinessOnlyProvider(ProviderBase):
    """Common Level 1 provider skeleton for future API connectors."""

    provider_level = ProviderLevel.LEVEL_1
    connection_mode = ConnectionMode.API_STUB

    def validate_config(self) -> list[WarningCode]:
        if not self.config.enabled:
            return [WarningCode.PROVIDER_DISABLED]
        if self.config.missing_required_env_vars():
            return [WarningCode.PROVIDER_CONFIG_MISSING]
        return []

    def connect_read_only(self) -> bool:
        if WarningCode.PROVIDER_DISABLED in self.warning_codes:
            return False
        if WarningCode.PROVIDER_CONFIG_MISSING in self.warning_codes:
            return False
        if not self.allow_live_read:
            self.warning_codes = _dedupe_codes(
                [*self.warning_codes, WarningCode.LIVE_READ_NOT_ALLOWED]
            )
            return False
        self.connection_mode = ConnectionMode.LIVE_READINESS
        self.warning_codes = _dedupe_codes([*self.warning_codes, WarningCode.NEEDS_REVIEW])
        return True

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


def _dedupe_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
