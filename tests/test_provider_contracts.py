from __future__ import annotations

from personal_cfo_agent.config import (
    load_ibkr_config,
    load_manual_config,
    load_moomoo_config,
    load_tiger_config,
)
from personal_cfo_agent.models import ProviderLevel, WarningCode
from personal_cfo_agent.provider_base import ProviderBase
from personal_cfo_agent.providers import (
    IBKRProvider,
    ManualSnapshotProvider,
    MoomooProvider,
    TigerProvider,
)


REQUIRED_METHODS = {
    "validate_config",
    "connect_read_only",
    "fetch_accounts",
    "fetch_cash",
    "fetch_positions",
    "fetch_balances",
    "disconnect",
}

FORBIDDEN_PUBLIC_METHODS = {
    "place_order",
    "submit_order",
    "modify_order",
    "cancel_order",
    "preview_order",
    "transfer_cash",
    "withdraw_cash",
    "trade",
    "buy",
    "sell",
    "roll",
    "close_position",
    "open_position",
    "placeOrder",
}


def test_provider_base_contract_exists() -> None:
    assert issubclass(ProviderBase, object)
    for method_name in REQUIRED_METHODS:
        assert hasattr(ProviderBase, method_name)


def test_ibkr_provider_exposes_only_read_contract_methods() -> None:
    provider = IBKRProvider(load_ibkr_config({}))
    _assert_read_only_provider(provider)
    assert provider.provider_level == ProviderLevel.LEVEL_1


def test_moomoo_provider_exposes_only_read_contract_methods() -> None:
    provider = MoomooProvider(load_moomoo_config({}))
    _assert_read_only_provider(provider)
    assert provider.provider_level == ProviderLevel.LEVEL_1


def test_tiger_provider_exposes_only_read_contract_methods() -> None:
    provider = TigerProvider(load_tiger_config({}))
    _assert_read_only_provider(provider)
    assert provider.provider_level == ProviderLevel.LEVEL_1


def test_manual_snapshot_provider_is_level_zero(tmp_path) -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, tmp_path / "missing.json"))
    _assert_read_only_provider(provider)
    assert provider.provider_level == ProviderLevel.LEVEL_0
    assert provider.validate_config() == [WarningCode.PROVIDER_CONFIG_MISSING]


def test_forbidden_method_names_are_not_provider_public_api() -> None:
    providers = [
        IBKRProvider(load_ibkr_config({})),
        MoomooProvider(load_moomoo_config({})),
        TigerProvider(load_tiger_config({})),
        ManualSnapshotProvider(load_manual_config({}, None)),
    ]
    for provider in providers:
        public_names = {name for name in dir(provider) if not name.startswith("_")}
        assert public_names.isdisjoint(FORBIDDEN_PUBLIC_METHODS)


def _assert_read_only_provider(provider: ProviderBase) -> None:
    for method_name in REQUIRED_METHODS:
        assert callable(getattr(provider, method_name))
    assert provider.read_only is True
    assert provider.trading_enabled is False
    assert provider.order_placement_enabled is False
