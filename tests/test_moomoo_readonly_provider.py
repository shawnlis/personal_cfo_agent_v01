from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig, load_moomoo_config
from personal_cfo_agent.models import ConnectionMode, ProviderLevel, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.providers.moomoo_models import (
    MoomooAccountRow,
    MoomooCashRow,
    MoomooPositionRow,
    MoomooReadDiagnostics,
    MoomooReadOnlySnapshot,
)
from personal_cfo_agent.providers.moomoo_connection_diagnostics import (
    run_moomoo_connection_diagnostics,
)
from personal_cfo_agent.providers.moomoo_account_discovery import (
    run_moomoo_account_discovery,
)
from personal_cfo_agent.providers.moomoo_provider import MoomooProvider
from personal_cfo_agent.providers.moomoo_readonly_adapter import MoomooReadOnlyAdapter
from personal_cfo_agent.runner import build_arg_parser, collect_provider_snapshots, main, run
from personal_cfo_agent.runner import _format_moomoo_data_diagnostics


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "moomoo_readonly_snapshot_v012.json"
FORBIDDEN_PUBLIC_METHODS = {
    "place_order",
    "placeOrder",
    "submit_order",
    "modify_order",
    "cancel_order",
    "preview_order",
    "transfer_cash",
    "withdraw_cash",
    "buy",
    "sell",
    "trade",
    "roll",
    "open_position",
    "close_position",
    "unlock_trade",
}


def test_moomoo_disabled_by_default() -> None:
    provider = MoomooProvider(load_moomoo_config({}))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes


def test_moomoo_missing_config_fails_closed() -> None:
    provider = MoomooProvider(load_moomoo_config({"CFO_MOOMOO_ENABLED": "true"}))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes


def test_moomoo_no_live_without_allow_flag() -> None:
    fake_adapter = _FakeAdapter(_fixture_snapshot())
    provider = MoomooProvider(_valid_config(), allow_live_read=False, live_adapter=fake_adapter)
    snapshot = provider._sync()
    assert not fake_adapter.called
    assert not snapshot.has_data()
    assert WarningCode.LIVE_READ_NOT_ALLOWED in snapshot.status.warning_codes


def test_moomoo_live_blocked_when_flag_exists_but_env_disabled() -> None:
    fake_adapter = _FakeAdapter(_fixture_snapshot())
    provider = MoomooProvider(load_moomoo_config({}), allow_live_read=True, live_adapter=fake_adapter)
    snapshot = provider._sync()
    assert not fake_adapter.called
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes


def test_futu_import_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "futu", raising=False)
    provider = MoomooProvider(_valid_config())
    provider.readiness_check()
    assert "futu" not in sys.modules


def test_missing_futu_sdk_returns_sdk_not_installed(monkeypatch) -> None:
    import personal_cfo_agent.providers.moomoo_readonly_adapter as adapter_module

    def _missing_sdk(name: str):
        if name == "futu":
            raise ImportError(name)
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _missing_sdk)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.MOOMOO_SDK_NOT_INSTALLED in snapshot.status.warning_codes
    assert WarningCode.SDK_NOT_INSTALLED in snapshot.status.warning_codes


def test_connection_diagnostics_does_not_initiate_live_read(monkeypatch) -> None:
    import personal_cfo_agent.providers.moomoo_connection_diagnostics as diagnostics_module

    def _unreachable(*args, **kwargs):
        raise OSError("not reachable")

    monkeypatch.setattr(diagnostics_module.socket, "create_connection", _unreachable)
    diagnostics = run_moomoo_connection_diagnostics(
        _valid_env(),
        local_env_loaded=True,
        timeout_seconds=0.01,
    )

    assert diagnostics.local_env_loaded is True
    assert diagnostics.enabled_true is True
    assert diagnostics.opend_socket_reachable is False
    assert WarningCode.MOOMOO_OPEND_UNREACHABLE in diagnostics.warning_codes
    assert WarningCode.PROVIDER_CONNECTION_FAILED in diagnostics.warning_codes


def test_cli_moomoo_account_discovery_command_exists() -> None:
    args = build_arg_parser().parse_args(["--provider", "moomoo", "--account-discovery"])

    assert args.provider == "moomoo"
    assert args.account_discovery is True


def test_moomoo_account_discovery_calls_get_acc_list_only_and_redacts(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    import personal_cfo_agent.providers.moomoo_account_discovery as discovery_module

    calls: list[str] = []

    class _DiscoveryContext:
        def __init__(
            self,
            *,
            host: str,
            port: int,
            filter_trdmarket=None,
            security_firm=None,
            need_general_sec_acc: bool = False,
        ) -> None:
            calls.append("context")
            print("SDK_CONTEXT_STDOUT_SENTINEL")
            print("SDK_CONTEXT_STDERR_SENTINEL", file=sys.stderr)

        def get_acc_list(self):
            calls.append("get_acc_list")
            print("SDK_GET_ACC_LIST_STDOUT_SENTINEL")
            print("SDK_GET_ACC_LIST_STDERR_SENTINEL", file=sys.stderr)
            return 0, [
                {
                    "acc_id": "MOOMOO_RAW_ACCOUNT_SENTINEL",
                    "card_num": "CARD_NUM_SENTINEL",
                    "uni_card_num": "UNI_CARD_NUM_SENTINEL",
                    "trd_env": "REAL",
                    "acc_type": "SEC",
                    "security_firm": "RIGHT_SECURITIES",
                    "trdmarket_auth": ["HK", "US"],
                    "acc_status": "ACTIVE",
                }
            ]

        def accinfo_query(self, *args, **kwargs):
            raise AssertionError("account funds query must not be called")

        def position_list_query(self, *args, **kwargs):
            raise AssertionError("position query must not be called")

        def unlock_trade(self, *args, **kwargs):
            raise AssertionError("unlock must not be called")

        def order_list_query(self, *args, **kwargs):
            raise AssertionError("order list must not be called")

        def place_order(self, *args, **kwargs):
            raise AssertionError("order placement must not be called")

        def modify_order(self, *args, **kwargs):
            raise AssertionError("order modification must not be called")

        def cancel_order(self, *args, **kwargs):
            raise AssertionError("order cancellation must not be called")

        def transfer_cash(self, *args, **kwargs):
            raise AssertionError("cash transfer must not be called")

        def withdraw_cash(self, *args, **kwargs):
            raise AssertionError("cash withdrawal must not be called")

        def close(self) -> None:
            calls.append("close")
            print("SDK_CLOSE_STDOUT_SENTINEL")

    _install_fake_discovery_sdk(monkeypatch, _DiscoveryContext)
    _patch_discovery_socket(monkeypatch, discovery_module)
    monkeypatch.chdir(tmp_path)
    _set_valid_moomoo_env(monkeypatch)

    exit_code = main(["--provider", "moomoo", "--account-discovery"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    combined = captured.out + captured.err

    assert exit_code == 0
    assert "get_acc_list" in calls
    assert "MOOMOO_RAW_ACCOUNT_SENTINEL" not in combined
    assert "CARD_NUM_SENTINEL" not in combined
    assert "UNI_CARD_NUM_SENTINEL" not in combined
    assert "SDK_CONTEXT_STDOUT_SENTINEL" not in combined
    assert "SDK_GET_ACC_LIST_STDOUT_SENTINEL" not in combined
    assert "SDK_CLOSE_STDOUT_SENTINEL" not in combined
    assert payload["sdk_import_ok"] is True
    assert payload["opend_socket_reachable"] is True
    assert payload["account_count_redacted"] == 1
    assert payload["selected_account_hash"].startswith("acct_")
    assert payload["account_id_hashes"] == [payload["selected_account_hash"]]
    assert payload["trd_env_values"] == ["REAL"]
    assert payload["acc_type_values"] == ["SEC"]
    assert payload["security_firm_values"] == ["RIGHT_SECURITIES"]
    assert payload["trdmarket_auth_values"] == ["HK", "US"]
    assert payload["acc_status_values"] == ["ACTIVE"]
    assert "MOOMOO_ACCOUNT_DISCOVERY_OK" in payload["warning_codes"]
    assert "MOOMOO_SDK_OUTPUT_SUPPRESSED" in payload["warning_codes"]
    assert "Loaded local environment" not in captured.out


def test_moomoo_account_discovery_records_security_and_market_mismatch(
    monkeypatch,
) -> None:
    import personal_cfo_agent.providers.moomoo_account_discovery as discovery_module

    class _DiscoveryContext:
        def __init__(
            self,
            *,
            host: str,
            port: int,
            filter_trdmarket=None,
            security_firm=None,
            need_general_sec_acc: bool = False,
        ) -> None:
            self.filter_trdmarket = filter_trdmarket
            self.security_firm = security_firm

        def get_acc_list(self):
            if self.security_firm == "RIGHT_SECURITIES" and self.filter_trdmarket == "HK":
                return 0, [
                    {
                        "acc_id": "MOOMOO_RIGHT_CONTEXT_ACCOUNT",
                        "trd_env": "REAL",
                        "acc_type": "SEC",
                        "security_firm": "RIGHT_SECURITIES",
                        "trdmarket_auth": ["HK"],
                        "acc_status": "ACTIVE",
                    }
                ]
            return 1, "raw SDK failure details"

        def close(self) -> None:
            pass

    _install_fake_discovery_sdk(
        monkeypatch,
        _DiscoveryContext,
        market_names=("HK", "US"),
        security_names=("RIGHT_SECURITIES", "WRONG_SECURITIES"),
    )
    _patch_discovery_socket(monkeypatch, discovery_module)

    diagnostics = run_moomoo_account_discovery(_valid_env())
    payload = diagnostics.to_redacted_dict()

    assert payload["account_count_redacted"] == 1
    assert "MOOMOO_ACCOUNT_DISCOVERY_OK" in payload["warning_codes"]
    assert "MOOMOO_SECURITY_FIRM_MISMATCH" in payload["warning_codes"]
    assert "MOOMOO_MARKET_FILTER_MISMATCH" in payload["warning_codes"]
    assert any("WRONG_SECURITIES" in value for value in payload["failed_context_variants"])
    assert any("filter_trdmarket=US" in value for value in payload["failed_context_variants"])


def test_moomoo_account_discovery_need_general_sec_acc_can_recover_universal_account(
    monkeypatch,
) -> None:
    import personal_cfo_agent.providers.moomoo_account_discovery as discovery_module

    class _DiscoveryContext:
        def __init__(
            self,
            *,
            host: str,
            port: int,
            filter_trdmarket=None,
            security_firm=None,
            need_general_sec_acc: bool = False,
        ) -> None:
            self.need_general_sec_acc = need_general_sec_acc

        def get_acc_list(self):
            if not self.need_general_sec_acc:
                return 0, []
            return 0, [
                {
                    "acc_id": "MOOMOO_UNIVERSAL_ACCOUNT_SENTINEL",
                    "trd_env": "REAL",
                    "acc_type": "UNIVERSAL_SECURITIES",
                    "security_firm": "RIGHT_SECURITIES",
                    "trdmarket_auth": ["HK", "US", "SG"],
                    "acc_status": "ACTIVE",
                }
            ]

        def close(self) -> None:
            pass

    _install_fake_discovery_sdk(monkeypatch, _DiscoveryContext)
    _patch_discovery_socket(monkeypatch, discovery_module)

    diagnostics = run_moomoo_account_discovery(_valid_env())
    payload = diagnostics.to_redacted_dict()
    text = json.dumps(payload)

    assert payload["account_count_redacted"] == 1
    assert payload["selected_context_mode"] is not None
    assert "need_general_sec_acc=True" in payload["selected_context_mode"]
    assert "MOOMOO_GENERAL_SEC_ACCOUNT_REQUIRED" in payload["warning_codes"]
    assert "MOOMOO_UNIVERSAL_ACCOUNT_SENTINEL" not in text


def test_moomoo_account_discovery_no_accounts_returns_redacted_warning(
    monkeypatch,
) -> None:
    import personal_cfo_agent.providers.moomoo_account_discovery as discovery_module

    class _DiscoveryContext:
        def __init__(
            self,
            *,
            host: str,
            port: int,
            filter_trdmarket=None,
            security_firm=None,
            need_general_sec_acc: bool = False,
        ) -> None:
            pass

        def get_acc_list(self):
            return 0, []

        def close(self) -> None:
            pass

    _install_fake_discovery_sdk(monkeypatch, _DiscoveryContext)
    _patch_discovery_socket(monkeypatch, discovery_module)

    diagnostics = run_moomoo_account_discovery(_valid_env())
    payload = diagnostics.to_redacted_dict()

    assert payload["account_count_redacted"] == 0
    assert payload["selected_account_hash"] is None
    assert payload["account_id_hashes"] == []
    assert "MOOMOO_NO_ACCOUNT_DISCOVERED" in payload["warning_codes"]
    assert "MOOMOO_SELECTED_ACCOUNT_MISSING" in payload["warning_codes"]
    assert "MOOMOO_ACCOUNT_DISCOVERY_FAILED" in payload["warning_codes"]


def test_cli_moomoo_connection_diagnostics_redacts_values_and_does_not_live_read(
    tmp_path,
) -> None:
    local_env = tmp_path / ".env.local"
    local_env.write_text(
        "\n".join(
            [
                "CFO_MOOMOO_ENABLED=true",
                "CFO_MOOMOO_HOST=192.0.2.55",
                "CFO_MOOMOO_PORT=not-a-port",
                "CFO_ACCOUNT_HASH_SALT" + "=" + "REDACTED_SALT_PLACEHOLDER",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "personal_cfo_agent.py"),
            "--provider",
            "moomoo",
            "--connection-diagnostics",
        ],
        cwd=tmp_path,
        env=_without_cfo_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0
    assert "Loaded local environment from .env.local; values redacted" in result.stdout
    assert "Moomoo connection diagnostics (values redacted)" in result.stdout
    assert ".env.local loaded: yes" in result.stdout
    assert "CFO_MOOMOO_ENABLED present and true: yes" in result.stdout
    assert "CFO_ACCOUNT_HASH_SALT present: yes, redacted" in result.stdout
    assert "OpenD socket reachable host/port:" in result.stdout
    assert "Read-only Moomoo sync only" not in result.stdout
    assert "No provider produced data" not in result.stdout
    for raw_value in ("192.0.2.55", "not-a-port", "REDACTED_SALT_PLACEHOLDER"):
        assert raw_value not in combined


def test_moomoo_provider_public_api_has_no_forbidden_methods() -> None:
    provider = MoomooProvider(load_moomoo_config({}))
    public_names = {name for name in dir(provider) if not name.startswith("_")}
    assert public_names.isdisjoint(FORBIDDEN_PUBLIC_METHODS)


def test_moomoo_provider_public_callable_api_is_allowlisted() -> None:
    provider = MoomooProvider(load_moomoo_config({}))
    allowed = {
        "validate_config",
        "connection_diagnostics",
        "connect_read_only",
        "fetch_accounts",
        "fetch_cash",
        "fetch_positions",
        "fetch_balances",
        "disconnect",
        "readiness_check",
    }
    public_callables = {
        name
        for name in dir(provider)
        if not name.startswith("_") and callable(getattr(provider, name))
    }
    assert public_callables == allowed


def test_fixture_moomoo_snapshot_normalizes_and_hashes_account_id() -> None:
    raw_account_id = "MOOMOO-TEST-ACCOUNT-123456"
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(_fixture_snapshot()),
    )
    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    assert snapshot.status.provider_level == ProviderLevel.LEVEL_2
    assert snapshot.status.connection_mode == ConnectionMode.LIVE_READ
    assert len(rows) == 2
    assert all(row.provider == "moomoo" for row in rows)
    assert all(row.account_id_hash.startswith("acct_") for row in rows)
    assert all(row.account_id_hash != raw_account_id for row in rows)

    output_text = "\n".join(str(row.to_csv_row()) for row in rows)
    assert raw_account_id not in output_text
    assert "account_id_hash" in output_text


def test_moomoo_data_diagnostics_schema_is_stable() -> None:
    diagnostics = MoomooReadDiagnostics(
        sdk_import_ok=True,
        opend_socket_reachable=True,
        context_opened=True,
        account_list_query_attempted=True,
        account_list_query_success=True,
        account_count_redacted=1,
        selected_account_hash="acct_test_hash",
        account_filter_mismatch=False,
        account_info_query_attempted=True,
        account_info_query_success=True,
        position_query_attempted=True,
        position_query_success=True,
        position_count=2,
        cash_query_attempted=True,
        cash_query_success=True,
        cash_currency_count=1,
        normalized_rows=3,
        sdk_output_suppressed=True,
        timeout_seconds=10.0,
        warning_codes=[WarningCode.MOOMOO_POSITION_LIST_EMPTY],
        stage_failures={"positions": "SDK returned nonzero ret code"},
    ).to_redacted_dict()

    assert tuple(diagnostics.keys()) == (
        "sdk_import_ok",
        "opend_socket_reachable",
        "context_opened",
        "account_list_query_attempted",
        "account_list_query_success",
        "account_count_redacted",
        "selected_account_hash",
        "account_filter_mismatch",
        "account_info_query_attempted",
        "account_info_query_success",
        "position_query_attempted",
        "position_query_success",
        "position_count",
        "cash_query_attempted",
        "cash_query_success",
        "cash_currency_count",
        "normalized_rows",
        "sdk_output_suppressed",
        "timeout_seconds",
        "warning_codes",
        "stage_failures",
    )
    text = "\n".join(_format_moomoo_data_diagnostics(diagnostics))
    assert "Context opened: yes" in text
    assert "Account count redacted: 1" in text
    assert "Normalized rows count: 3" in text
    assert "MOOMOO_POSITION_LIST_EMPTY" in text
    assert "Stage failures: positions=SDK returned nonzero ret code" in text


def test_empty_moomoo_account_list_warning_is_handled() -> None:
    diagnostics = MoomooReadDiagnostics(
        context_opened=True,
        account_list_query_attempted=True,
        account_list_query_success=True,
        account_count_redacted=0,
        warning_codes=[
            WarningCode.MOOMOO_ACCOUNT_LIST_EMPTY,
            WarningCode.MOOMOO_NO_DATA_RETURNED,
        ],
    )
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(MoomooReadOnlySnapshot(diagnostics=diagnostics)),
    )
    snapshot = provider._sync()

    assert WarningCode.MOOMOO_ACCOUNT_LIST_EMPTY in snapshot.status.warning_codes
    assert WarningCode.MOOMOO_NO_DATA_RETURNED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["account_list_query_success"] is True
    assert snapshot.status.diagnostics["account_count_redacted"] == 0


def test_empty_moomoo_positions_warning_is_handled() -> None:
    diagnostics = MoomooReadDiagnostics(
        context_opened=True,
        account_list_query_attempted=True,
        account_list_query_success=True,
        account_count_redacted=1,
        position_query_attempted=True,
        position_query_success=True,
        position_count=0,
        warning_codes=[WarningCode.MOOMOO_POSITION_LIST_EMPTY],
    )
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(
            MoomooReadOnlySnapshot(
                accounts=[MoomooAccountRow(account_id="MOOMOO-EMPTY-ACCOUNT-123456")],
                diagnostics=diagnostics,
            )
        ),
    )
    snapshot = provider._sync()

    assert WarningCode.MOOMOO_POSITION_LIST_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["position_query_success"] is True
    assert snapshot.status.diagnostics["position_count"] == 0


def test_empty_moomoo_cash_warning_is_handled() -> None:
    diagnostics = MoomooReadDiagnostics(
        context_opened=True,
        account_list_query_attempted=True,
        account_list_query_success=True,
        account_count_redacted=1,
        cash_query_attempted=True,
        cash_query_success=True,
        cash_currency_count=0,
        warning_codes=[WarningCode.MOOMOO_CASH_EMPTY],
    )
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(
            MoomooReadOnlySnapshot(
                accounts=[MoomooAccountRow(account_id="MOOMOO-EMPTY-ACCOUNT-123456")],
                diagnostics=diagnostics,
            )
        ),
    )
    snapshot = provider._sync()

    assert WarningCode.MOOMOO_CASH_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["cash_query_success"] is True
    assert snapshot.status.diagnostics["cash_currency_count"] == 0


def test_moomoo_connection_failure_returns_warning_code_without_crashing() -> None:
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("connection"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.MOOMOO_CONNECTION_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes


def test_moomoo_fetch_failure_returns_warning_code_without_crashing() -> None:
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("fetch"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes


def test_moomoo_live_adapter_suppresses_sdk_console_output(monkeypatch, capsys) -> None:
    import personal_cfo_agent.providers.moomoo_readonly_adapter as adapter_module

    class _NoisyLogger:
        console_level = 20
        file_level = 10

    class _FakeFtLogger:
        logger = _NoisyLogger()

    class _FakeCommon:
        ft_logger = _FakeFtLogger()

    class _FakeTrdEnv:
        REAL = "REAL"

    class _NoisyContext:
        def __init__(self, *, host: str, port: int) -> None:
            print("SDK_METADATA_SENTINEL_STDOUT")
            print("SDK_METADATA_SENTINEL_STDERR", file=sys.stderr)

        def acc_list_query(self):
            print("SDK_ACCOUNT_SENTINEL_STDOUT")
            return 0, [{"acc_id": "MOOMOO_TEST_ACCOUNT_SENTINEL"}]

        def accinfo_query(self, *, trd_env):
            print("SDK_BALANCE_SENTINEL_STDOUT")
            return 0, [{"currency": "USD", "cash": 10.0}]

        def position_list_query(self, *, trd_env):
            print("SDK_POSITION_SENTINEL_STDOUT")
            return 0, []

        def close(self) -> None:
            print("SDK_CLOSE_SENTINEL_STDOUT")

    class _FakeSdk:
        common = _FakeCommon()
        RET_OK = 0
        TrdEnv = _FakeTrdEnv()
        OpenSecTradeContext = _NoisyContext

    monkeypatch.setattr(adapter_module.importlib, "import_module", lambda name: _FakeSdk)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert snapshot.has_data()
    assert combined == ""
    assert _FakeSdk.common.ft_logger.logger.console_level == 30
    assert _FakeSdk.common.ft_logger.logger.file_level == 30
    assert WarningCode.MOOMOO_SDK_OUTPUT_SUPPRESSED in snapshot.status.warning_codes


def test_moomoo_live_adapter_fetch_failure_keeps_redacted_diagnostics(
    monkeypatch,
) -> None:
    import personal_cfo_agent.providers.moomoo_readonly_adapter as adapter_module

    class _FakeContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 1, "raw account id MOOMOO_TEST_ACCOUNT_SENTINEL"

        def close(self) -> None:
            pass

    class _FakeSdk:
        RET_OK = 0
        OpenSecTradeContext = _FakeContext

    monkeypatch.setattr(adapter_module.importlib, "import_module", lambda name: _FakeSdk)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes
    assert WarningCode.MOOMOO_ACCOUNT_LIST_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["context_opened"] is True
    assert snapshot.status.diagnostics["account_list_query_attempted"] is True
    assert snapshot.status.diagnostics["account_list_query_success"] is False
    assert snapshot.status.diagnostics["warning_codes"] == [
        "MOOMOO_SDK_OUTPUT_SUPPRESSED",
        "MOOMOO_ACCOUNT_LIST_FAILED",
        "PROVIDER_FETCH_FAILED",
    ]
    assert snapshot.status.diagnostics["stage_failures"] == {
        "account_list": "SDK returned nonzero ret code"
    }
    assert "MOOMOO_TEST_ACCOUNT_SENTINEL" not in json.dumps(snapshot.status.diagnostics)


def test_moomoo_context_open_failure_returns_stage_code(monkeypatch) -> None:
    class _ContextOpenFails:
        def __init__(self, *, host: str, port: int) -> None:
            raise RuntimeError("raw context metadata should not appear")

    _install_fake_sdk(monkeypatch, _ContextOpenFails)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.MOOMOO_CONTEXT_OPEN_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["context_opened"] is False
    assert snapshot.status.diagnostics["stage_failures"] == {
        "context_open": "SDK context open failed"
    }


def test_moomoo_empty_account_list_returns_stage_code(monkeypatch) -> None:
    class _EmptyAccountContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 0, []

        def accinfo_query(self, *, trd_env):
            return 0, []

        def position_list_query(self, *, trd_env):
            return 0, []

        def close(self) -> None:
            pass

    _install_fake_sdk(monkeypatch, _EmptyAccountContext)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert WarningCode.MOOMOO_ACCOUNT_LIST_EMPTY in snapshot.status.warning_codes
    assert WarningCode.MOOMOO_NO_DATA_RETURNED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["account_list_query_success"] is True
    assert snapshot.status.diagnostics["account_count_redacted"] == 0


def test_moomoo_account_filter_mismatch_returns_stage_code(monkeypatch) -> None:
    class _DifferentAccountContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 0, [{"acc_id": "MOOMOO_OTHER_ACCOUNT_SENTINEL"}]

        def close(self) -> None:
            pass

    _install_fake_sdk(monkeypatch, _DifferentAccountContext)
    provider = MoomooProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=MoomooReadOnlyAdapter(
            host="127.0.0.1",
            port=11111,
            account_id="MOOMOO_FILTER_ACCOUNT_SENTINEL",
        ),
    )

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.MOOMOO_ACCOUNT_FILTER_MISMATCH in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["account_filter_mismatch"] is True
    assert snapshot.status.diagnostics["stage_failures"] == {
        "account_filter": "Configured account filter not found in account list"
    }


def test_moomoo_position_query_failure_returns_stage_code(monkeypatch) -> None:
    class _PositionFailureContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 0, [{"acc_id": "MOOMOO_TEST_ACCOUNT_SENTINEL"}]

        def accinfo_query(self, *, trd_env):
            return 0, [{"currency": "USD", "cash": 1.0}]

        def position_list_query(self, *, trd_env):
            return 1, "raw position failure details"

        def close(self) -> None:
            pass

    _install_fake_sdk(monkeypatch, _PositionFailureContext)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.MOOMOO_POSITION_LIST_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["account_info_query_success"] is True
    assert snapshot.status.diagnostics["position_query_attempted"] is True
    assert snapshot.status.diagnostics["position_query_success"] is False
    assert snapshot.status.diagnostics["stage_failures"] == {
        "positions": "SDK returned nonzero ret code"
    }


def test_moomoo_empty_positions_return_stage_code(monkeypatch) -> None:
    class _EmptyPositionContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 0, [{"acc_id": "MOOMOO_TEST_ACCOUNT_SENTINEL"}]

        def accinfo_query(self, *, trd_env):
            return 0, [{"currency": "USD", "cash": 1.0}]

        def position_list_query(self, *, trd_env):
            return 0, []

        def close(self) -> None:
            pass

    _install_fake_sdk(monkeypatch, _EmptyPositionContext)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert snapshot.has_data()
    assert WarningCode.MOOMOO_POSITION_LIST_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["position_query_success"] is True
    assert snapshot.status.diagnostics["position_count"] == 0


def test_moomoo_cash_query_failure_returns_stage_code(monkeypatch) -> None:
    class _CashFailureContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 0, [{"acc_id": "MOOMOO_TEST_ACCOUNT_SENTINEL"}]

        def accinfo_query(self, *, trd_env):
            return 1, "raw cash failure details"

        def close(self) -> None:
            pass

    _install_fake_sdk(monkeypatch, _CashFailureContext)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.MOOMOO_ACCOUNT_INFO_FAILED in snapshot.status.warning_codes
    assert WarningCode.MOOMOO_CASH_QUERY_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["cash_query_attempted"] is True
    assert snapshot.status.diagnostics["cash_query_success"] is False
    assert snapshot.status.diagnostics["stage_failures"] == {
        "account_info": "SDK returned nonzero ret code"
    }


def test_moomoo_empty_cash_returns_stage_code(monkeypatch) -> None:
    class _EmptyCashContext:
        def __init__(self, *, host: str, port: int) -> None:
            pass

        def acc_list_query(self):
            return 0, [{"acc_id": "MOOMOO_TEST_ACCOUNT_SENTINEL"}]

        def accinfo_query(self, *, trd_env):
            return 0, []

        def position_list_query(self, *, trd_env):
            return 0, [
                {
                    "code": "US.TEST",
                    "stock_name": "Test",
                    "qty": 1,
                    "market_val": 1.0,
                    "currency": "USD",
                }
            ]

        def close(self) -> None:
            pass

    _install_fake_sdk(monkeypatch, _EmptyCashContext)
    provider = MoomooProvider(_valid_config(), allow_live_read=True)

    snapshot = provider._sync()

    assert snapshot.has_data()
    assert WarningCode.MOOMOO_CASH_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["cash_query_success"] is True
    assert snapshot.status.diagnostics["cash_currency_count"] == 0


def test_moomoo_normalization_failure_returns_stage_code(monkeypatch) -> None:
    import personal_cfo_agent.runner as runner_module
    from personal_cfo_agent.models import (
        ProviderStatus,
        RawAccount,
        RawCash,
        RawProviderSnapshot,
    )

    status = ProviderStatus(
        provider_name="moomoo",
        provider_level=ProviderLevel.LEVEL_2,
        connection_mode=ConnectionMode.LIVE_READ,
        diagnostics={
            "warning_codes": [],
            "stage_failures": {},
            "normalized_rows": 1,
        },
    )
    raw_snapshot = RawProviderSnapshot(
        provider_name="moomoo",
        status=status,
        accounts=[RawAccount(account_id="MOOMOO_TEST_ACCOUNT_SENTINEL")],
        cash=[
            RawCash(
                account_id="MOOMOO_TEST_ACCOUNT_SENTINEL",
                currency="USD",
                amount=1.0,
                source_timestamp="2026-06-14T00:00:00+00:00",
            )
        ],
    )

    monkeypatch.setattr(
        runner_module,
        "collect_provider_snapshots",
        lambda config: [raw_snapshot],
    )

    def _fail_normalization(snapshots):
        raise ValueError("raw normalization failure details")

    monkeypatch.setattr(runner_module, "normalize_snapshots", _fail_normalization)

    result = runner_module.run(RuntimeConfig(provider="moomoo"))
    moomoo_status = result.statuses[0]

    assert result.exit_code == 1
    assert WarningCode.MOOMOO_NORMALIZATION_FAILED in moomoo_status.warning_codes
    assert WarningCode.PROVIDER_FETCH_FAILED in moomoo_status.warning_codes
    assert moomoo_status.diagnostics["normalized_rows"] == 0
    assert moomoo_status.diagnostics["stage_failures"] == {
        "normalization": "Normalization failed"
    }


def test_moomoo_diagnostics_formatter_redacts_balances_and_account_ids() -> None:
    diagnostics = {
        "sdk_import_ok": True,
        "opend_socket_reachable": True,
        "context_opened": True,
        "account_list_query_attempted": True,
        "account_list_query_success": False,
        "account_count_redacted": 0,
        "selected_account_hash": "acct_redacted_hash",
        "account_filter_mismatch": False,
        "account_info_query_attempted": False,
        "account_info_query_success": False,
        "position_query_attempted": False,
        "position_query_success": False,
        "position_count": 0,
        "cash_query_attempted": False,
        "cash_query_success": False,
        "cash_currency_count": 0,
        "normalized_rows": 0,
        "sdk_output_suppressed": True,
        "timeout_seconds": 10.0,
        "warning_codes": ["MOOMOO_ACCOUNT_LIST_FAILED", "PROVIDER_FETCH_FAILED"],
        "stage_failures": {"account_list": "SDK returned nonzero ret code"},
    }

    text = "\n".join(_format_moomoo_data_diagnostics(diagnostics))

    assert "acct_redacted_hash" in text
    assert "MOOMOO_TEST_ACCOUNT_SENTINEL" not in text
    assert "EXACT_BALANCE_SENTINEL" not in text
    assert "SDK returned nonzero ret code" in text


def test_provider_mode_required_for_moomoo_live_gate() -> None:
    snapshots = collect_provider_snapshots(
        RuntimeConfig(env=_valid_env(), allow_live_read=True, provider="all")
    )
    moomoo_status = next(
        snapshot.status for snapshot in snapshots if snapshot.provider_name == "moomoo"
    )
    assert WarningCode.LIVE_READ_NOT_ALLOWED in moomoo_status.warning_codes


def test_cli_moomoo_readiness_check_works_without_opend_running() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "moomoo",
            "--readiness-check",
        ],
        cwd=ROOT,
        env={**os.environ, **_valid_env()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "moomoo: api_contract_stub; warnings=None" in result.stdout
    assert "No provider produced data; no reports generated." in result.stdout


def test_cli_moomoo_live_read_refuses_without_explicit_flag(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "moomoo",
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=ROOT,
        env={**os.environ, **_valid_env()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "LIVE_READ_NOT_ALLOWED" in result.stdout
    assert "Read-only Moomoo sync only" not in result.stdout
    assert not (tmp_path / "reports").exists()


def test_cli_moomoo_data_diagnostics_requires_explicit_live_flag(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "personal_cfo_agent.py"),
            "--provider",
            "moomoo",
            "--moomoo-data-diagnostics",
        ],
        cwd=tmp_path,
        env={**_without_cfo_env(), **_valid_env()},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--moomoo-data-diagnostics requires --allow-live-read" in result.stderr
    assert "Read-only Moomoo sync only" not in result.stdout


def test_generated_moomoo_outputs_stay_under_ignored_reports_path() -> None:
    report_path = "reports/personal_cfo_agent/moomoo_v012_live_smoke/provider_sync_summary.json"
    result = subprocess.run(
        ["git", "check-ignore", "-v", report_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "reports/" in result.stdout


def test_env_local_remains_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", ".env.local"],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_moomoo_source_has_no_forbidden_call_markers() -> None:
    for path in [
        ROOT / "src" / "personal_cfo_agent" / "providers" / "moomoo_provider.py",
        ROOT / "src" / "personal_cfo_agent" / "providers" / "moomoo_readonly_adapter.py",
    ]:
        text = path.read_text(encoding="utf-8").lower()
        for marker in FORBIDDEN_PUBLIC_METHODS:
            assert re.search(rf"\b{re.escape(marker.lower())}\b", text) is None


def _install_fake_discovery_sdk(
    monkeypatch,
    context_cls,
    *,
    market_names: tuple[str, ...] = ("HK",),
    security_names: tuple[str, ...] = ("RIGHT_SECURITIES",),
):
    import personal_cfo_agent.providers.moomoo_account_discovery as discovery_module

    class _FakeLogger:
        console_level = 20
        file_level = 10

    class _FakeFtLogger:
        logger = _FakeLogger()

    class _FakeCommon:
        ft_logger = _FakeFtLogger()

    class _FakeTrdMarket:
        pass

    for name in market_names:
        setattr(_FakeTrdMarket, name, name)

    class _FakeSecurityFirm:
        pass

    for name in security_names:
        setattr(_FakeSecurityFirm, name, name)

    class _FakeSdk:
        common = _FakeCommon()
        RET_OK = 0
        TrdMarket = _FakeTrdMarket()
        SecurityFirm = _FakeSecurityFirm()
        OpenSecTradeContext = context_cls

    monkeypatch.setattr(discovery_module.importlib, "import_module", lambda name: _FakeSdk)
    return _FakeSdk


def _patch_discovery_socket(monkeypatch, discovery_module) -> None:
    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        discovery_module.socket,
        "create_connection",
        lambda *args, **kwargs: _FakeSocket(),
    )


def _set_valid_moomoo_env(monkeypatch) -> None:
    for key, value in _valid_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CFO_ACCOUNT_HASH_SALT", "TEST_HASH_SALT")


def _install_fake_sdk(monkeypatch, context_cls):
    import personal_cfo_agent.providers.moomoo_readonly_adapter as adapter_module

    class _FakeLogger:
        console_level = 20
        file_level = 10

    class _FakeFtLogger:
        logger = _FakeLogger()

    class _FakeCommon:
        ft_logger = _FakeFtLogger()

    class _FakeTrdEnv:
        REAL = "REAL"

    class _FakeSdk:
        common = _FakeCommon()
        RET_OK = 0
        TrdEnv = _FakeTrdEnv()
        OpenSecTradeContext = context_cls

    monkeypatch.setattr(adapter_module.importlib, "import_module", lambda name: _FakeSdk)
    return _FakeSdk


class _FakeAdapter:
    def __init__(self, snapshot: MoomooReadOnlySnapshot) -> None:
        self.snapshot = snapshot
        self.called = False

    def collect(self) -> MoomooReadOnlySnapshot:
        self.called = True
        return self.snapshot


class _FailingAdapter:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def collect(self) -> MoomooReadOnlySnapshot:
        from personal_cfo_agent.providers.moomoo_readonly_adapter import (
            MoomooConnectionError,
            MoomooFetchError,
        )

        if self.mode == "connection":
            raise MoomooConnectionError(
                "OpenD unavailable",
                MoomooReadDiagnostics(
                    warning_codes=[
                        WarningCode.MOOMOO_OPEND_UNREACHABLE,
                        WarningCode.MOOMOO_CONNECTION_FAILED,
                    ]
                ),
            )
        if self.mode == "fetch":
            raise MoomooFetchError("fetch failed")
        raise RuntimeError("unexpected adapter failure")


def _fixture_snapshot() -> MoomooReadOnlySnapshot:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    account_id = payload["account_id"]
    source_timestamp = payload["source_timestamp"]
    return MoomooReadOnlySnapshot(
        accounts=[MoomooAccountRow(account_id=account_id, currency="HKD")],
        cash=[
            MoomooCashRow(
                account_id=account_id,
                currency=row["currency"],
                amount=float(row["amount"]),
                source_timestamp=source_timestamp,
            )
            for row in payload["cash"]
        ],
        positions=[
            MoomooPositionRow(
                account_id=account_id,
                asset_id=row["asset_id"],
                asset_type=row["asset_type"],
                symbol=row["symbol"],
                name=row["name"],
                quantity=float(row["quantity"]),
                currency=row["currency"],
                market_value=row["market_value"],
                cost_basis=row["cost_basis"],
                source_timestamp=source_timestamp,
            )
            for row in payload["positions"]
        ],
    )


def _valid_config(extra: dict[str, str] | None = None):
    return load_moomoo_config({**_valid_env(), **(extra or {})})


def _valid_env() -> dict[str, str]:
    return {
        "CFO_MOOMOO_ENABLED": "true",
        "CFO_MOOMOO_HOST": "127.0.0.1",
        "CFO_MOOMOO_PORT": "11111",
    }


def _without_cfo_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CFO_IBKR_")
        and not key.startswith("CFO_MOOMOO_")
        and not key.startswith("CFO_TIGER_")
        and key != "CFO_ACCOUNT_HASH_SALT"
    }
