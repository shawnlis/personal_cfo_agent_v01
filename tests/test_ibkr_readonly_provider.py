from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig, load_ibkr_config
from personal_cfo_agent.models import ConnectionMode, ProviderLevel, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.report_writer import write_report_bundle
from personal_cfo_agent.providers.ibkr_models import (
    IBKRAccountRow,
    IBKRCashRow,
    IBKRPositionRow,
    IBKRReadDiagnostics,
    IBKRReadOnlySnapshot,
)
from personal_cfo_agent.providers.ibkr_connection_diagnostics import (
    run_ibkr_connection_diagnostics,
)
from personal_cfo_agent.providers.ibkr_provider import IBKRProvider
from personal_cfo_agent.risk_engine import calculate_risk_summary
from personal_cfo_agent.runner import collect_provider_snapshots
from personal_cfo_agent.runner import _format_ibkr_data_diagnostics


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ibkr_readonly_snapshot_v011.json"
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
}


def test_ibkr_disabled_by_default() -> None:
    provider = IBKRProvider(load_ibkr_config({}))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes


def test_ibkr_missing_config_fails_closed() -> None:
    provider = IBKRProvider(load_ibkr_config({"CFO_IBKR_ENABLED": "true"}))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes


def test_ibkr_no_live_without_allow_flag() -> None:
    fake_adapter = _FakeAdapter(_fixture_snapshot())
    provider = IBKRProvider(_valid_config(), allow_live_read=False, live_adapter=fake_adapter)
    snapshot = provider._sync()
    assert not fake_adapter.called
    assert not snapshot.has_data()
    assert WarningCode.LIVE_READ_NOT_ALLOWED in snapshot.status.warning_codes


def test_ibapi_import_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "ibapi.client", raising=False)
    monkeypatch.delitem(sys.modules, "ibapi.wrapper", raising=False)
    provider = IBKRProvider(_valid_config())
    provider.readiness_check()
    assert "ibapi.client" not in sys.modules
    assert "ibapi.wrapper" not in sys.modules


def test_missing_ibapi_returns_sdk_not_installed(monkeypatch) -> None:
    import personal_cfo_agent.providers.ibkr_readonly_adapter as adapter_module

    def _missing_sdk(name: str):
        if name.startswith("ibapi."):
            raise ImportError(name)
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _missing_sdk)
    provider = IBKRProvider(_valid_config(), allow_live_read=True)
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.SDK_NOT_INSTALLED in snapshot.status.warning_codes


def test_ibkr_provider_public_api_has_no_forbidden_methods() -> None:
    provider = IBKRProvider(load_ibkr_config({}))
    public_names = {name for name in dir(provider) if not name.startswith("_")}
    assert public_names.isdisjoint(FORBIDDEN_PUBLIC_METHODS)


def test_ibkr_provider_public_callable_api_is_allowlisted() -> None:
    provider = IBKRProvider(load_ibkr_config({}))
    allowed = {
        "validate_config",
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


def test_fixture_ibkr_snapshot_normalizes_and_hashes_account_id(tmp_path) -> None:
    raw_account_id = "DU1234567"
    provider = IBKRProvider(
        _valid_config({"CFO_IBKR_ACCOUNT": raw_account_id}),
        allow_live_read=True,
        live_adapter=_FakeAdapter(_fixture_snapshot()),
    )
    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    assert snapshot.status.provider_level == ProviderLevel.LEVEL_2
    assert snapshot.status.connection_mode == ConnectionMode.LIVE_READ
    assert len(rows) == 2
    assert all(row.provider == "ibkr" for row in rows)
    assert all(row.account_id_hash.startswith("acct_") for row in rows)
    assert all(row.account_id_hash != raw_account_id for row in rows)

    output_text = "\n".join(str(row.to_csv_row()) for row in rows)
    assert raw_account_id not in output_text
    assert "account_id_hash" in output_text


def test_ibkr_net_liquidation_normalizes_as_account_nav_row() -> None:
    raw_account_id = "DU1234567"
    provider = IBKRProvider(
        _valid_config({"CFO_IBKR_ACCOUNT": raw_account_id}),
        allow_live_read=True,
        live_adapter=_FakeAdapter(
            IBKRReadOnlySnapshot(
                accounts=[
                    IBKRAccountRow(
                        account_id=raw_account_id,
                        currency="SGD",
                        account_nav=1234.56,
                        source_timestamp="2026-06-18T00:00:00+00:00",
                    )
                ],
            )
        ),
    )

    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    account_nav_rows = [row for row in rows if row.asset_type == "account_nav"]
    output_text = "\n".join(str(row.to_csv_row()) for row in rows)

    assert len(account_nav_rows) == 1
    assert account_nav_rows[0].market_value == 1234.56
    assert account_nav_rows[0].currency == "SGD"
    assert account_nav_rows[0].source_confidence == "ibkr_read_only_live"
    assert raw_account_id not in output_text


def test_live_read_blocked_when_flag_exists_but_env_disabled() -> None:
    fake_adapter = _FakeAdapter(_fixture_snapshot())
    provider = IBKRProvider(load_ibkr_config({}), allow_live_read=True, live_adapter=fake_adapter)
    snapshot = provider._sync()
    assert not fake_adapter.called
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes


def test_connection_failure_returns_warning_code_without_crashing() -> None:
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("connection"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes


def test_fetch_failure_returns_warning_code_without_crashing() -> None:
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("fetch"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes


def test_handshake_timeout_returns_explicit_diagnostic_warning_codes() -> None:
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("handshake"),
    )
    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.IBKR_HANDSHAKE_TIMEOUT in snapshot.status.warning_codes
    assert WarningCode.IBKR_CALLBACK_TIMEOUT in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["connected_to_socket"] is True
    assert snapshot.status.diagnostics["api_handshake_seen"] is False


def test_unexpected_adapter_failure_returns_fetch_warning_without_crashing() -> None:
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("unexpected"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes


def test_empty_managed_accounts_returns_explicit_warning_codes() -> None:
    diagnostics = IBKRReadDiagnostics(
        connected_to_socket=True,
        api_handshake_seen=True,
        managed_accounts_seen=True,
        managed_account_count_redacted=0,
        warning_codes=[
            WarningCode.IBKR_MANAGED_ACCOUNTS_EMPTY,
            WarningCode.IBKR_NO_DATA_RETURNED,
        ],
    )
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(IBKRReadOnlySnapshot(diagnostics=diagnostics)),
    )
    snapshot = provider._sync()

    assert WarningCode.IBKR_MANAGED_ACCOUNTS_EMPTY in snapshot.status.warning_codes
    assert WarningCode.IBKR_NO_DATA_RETURNED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["managed_accounts_seen"] is True
    assert snapshot.status.diagnostics["managed_account_count_redacted"] == 0


def test_successful_empty_callbacks_return_empty_read_warning_codes() -> None:
    diagnostics = IBKRReadDiagnostics(
        connected_to_socket=True,
        api_handshake_seen=True,
        managed_accounts_seen=True,
        managed_account_count_redacted=1,
        positions_callback_seen=False,
        position_count=0,
        account_summary_callback_seen=False,
        cash_currency_count=0,
        warning_codes=[
            WarningCode.IBKR_POSITIONS_EMPTY,
            WarningCode.IBKR_ACCOUNT_SUMMARY_EMPTY,
            WarningCode.IBKR_NO_DATA_RETURNED,
            WarningCode.IBKR_READ_SUCCEEDED_EMPTY,
        ],
    )
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(IBKRReadOnlySnapshot(diagnostics=diagnostics)),
    )
    snapshot = provider._sync()

    assert WarningCode.IBKR_POSITIONS_EMPTY in snapshot.status.warning_codes
    assert WarningCode.IBKR_ACCOUNT_SUMMARY_EMPTY in snapshot.status.warning_codes
    assert WarningCode.IBKR_READ_SUCCEEDED_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["position_count"] == 0
    assert snapshot.status.diagnostics["cash_currency_count"] == 0


def test_requested_account_mismatch_is_redacted_in_diagnostics() -> None:
    raw_account_id = "DU7654321"
    diagnostics = IBKRReadDiagnostics(
        connected_to_socket=True,
        api_handshake_seen=True,
        managed_accounts_seen=True,
        managed_account_count_redacted=1,
        requested_account_hash="acct_redacted1234",
        requested_account_seen=False,
        warning_codes=[
            WarningCode.IBKR_ACCOUNT_FILTER_MISMATCH,
            WarningCode.IBKR_NO_DATA_RETURNED,
        ],
    )
    provider = IBKRProvider(
        _valid_config({"CFO_IBKR_ACCOUNT": raw_account_id}),
        allow_live_read=True,
        live_adapter=_FakeAdapter(IBKRReadOnlySnapshot(diagnostics=diagnostics)),
    )
    snapshot = provider._sync()
    status_payload = json.dumps(snapshot.status.to_dict())

    assert WarningCode.IBKR_ACCOUNT_FILTER_MISMATCH in snapshot.status.warning_codes
    assert "acct_redacted1234" in status_payload
    assert raw_account_id not in status_payload


def test_stubbed_data_path_returns_not_implemented_warning_code() -> None:
    diagnostics = IBKRReadDiagnostics(
        connected_to_socket=True,
        api_handshake_seen=True,
        managed_accounts_seen=True,
        managed_account_count_redacted=1,
        warning_codes=[
            WarningCode.IBKR_DATA_PATH_NOT_IMPLEMENTED,
            WarningCode.IBKR_NO_DATA_RETURNED,
        ],
    )
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(IBKRReadOnlySnapshot(diagnostics=diagnostics)),
    )
    snapshot = provider._sync()

    assert WarningCode.IBKR_DATA_PATH_NOT_IMPLEMENTED in snapshot.status.warning_codes
    assert WarningCode.IBKR_NO_DATA_RETURNED in snapshot.status.warning_codes


def test_raw_account_id_redacted_from_markdown_json_and_csv_outputs(tmp_path) -> None:
    raw_account_id = "DU1234567"
    provider = IBKRProvider(
        _valid_config({"CFO_IBKR_ACCOUNT": raw_account_id}),
        allow_live_read=True,
        live_adapter=_FakeAdapter(_fixture_snapshot()),
    )
    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    risk_summary = calculate_risk_summary(rows, expected_provider_count=1, as_of_date="20260614")
    output_paths = write_report_bundle(tmp_path, [snapshot.status], rows, risk_summary)

    for path in output_paths.values():
        text = path.read_text(encoding="utf-8")
        assert raw_account_id not in text
    combined_text = "\n".join(path.read_text(encoding="utf-8") for path in output_paths.values())
    assert "account_id_hash" in combined_text


def test_provider_summary_records_read_only_safety_flags(tmp_path) -> None:
    provider = IBKRProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(_fixture_snapshot()),
    )
    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    risk_summary = calculate_risk_summary(rows, expected_provider_count=1, as_of_date="20260614")
    output_paths = write_report_bundle(tmp_path, [snapshot.status], rows, risk_summary)
    summary = json.loads(output_paths["provider_sync_summary"].read_text(encoding="utf-8"))
    provider_status = summary["provider_status"][0]

    assert provider_status["read_only"] is True
    assert provider_status["trading_enabled"] is False
    assert provider_status["order_placement_enabled"] is False


def test_config_values_are_not_printed_by_cli_readiness_check() -> None:
    env = {
        **os.environ,
        "CFO_IBKR_ENABLED": "true",
        "CFO_IBKR_HOST": "192.0.2.44",
        "CFO_IBKR_PORT": "4002",
        "CFO_IBKR_CLIENT_ID": "7331",
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "ibkr",
            "--readiness-check",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "192.0.2.44" not in combined
    assert "4002" not in combined
    assert "7331" not in combined


def test_cli_connection_diagnostics_redacts_values_and_does_not_live_read(tmp_path) -> None:
    local_env = tmp_path / ".env.local"
    local_env.write_text(
        "\n".join(
            [
                "CFO_IBKR_ENABLED=true",
                "CFO_IBKR_HOST=192.0.2.44",
                "CFO_IBKR_PORT=not-a-port",
                "CFO_IBKR_CLIENT_ID=7331",
                "CFO_IBKR_ACCOUNT" + "=" + "REDACTED_ACCOUNT_PLACEHOLDER",
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
            "ibkr",
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
    assert "IBKR connection diagnostics (values redacted)" in result.stdout
    assert "CFO_IBKR_ENABLED present and true: yes" in result.stdout
    assert "CFO_IBKR_ACCOUNT present: yes, redacted" in result.stdout
    assert "CFO_ACCOUNT_HASH_SALT present: yes, redacted" in result.stdout
    assert "TCP socket reachable host/port:" in result.stdout
    assert "Read-only IBKR sync only" not in result.stdout
    assert "No provider produced data" not in result.stdout
    for raw_value in (
        "192.0.2.44",
        "not-a-port",
        "7331",
        "REDACTED_ACCOUNT_PLACEHOLDER",
        "REDACTED_SALT_PLACEHOLDER",
    ):
        assert raw_value not in combined


def test_cli_data_diagnostics_requires_explicit_live_flag(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "personal_cfo_agent.py"),
            "--provider",
            "ibkr",
            "--ibkr-data-diagnostics",
        ],
        cwd=tmp_path,
        env={**_without_cfo_env(), **_valid_env()},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--ibkr-data-diagnostics requires --allow-live-read" in result.stderr
    assert "Read-only IBKR sync only" not in result.stdout


def test_ibkr_data_diagnostics_formatter_redacts_raw_values() -> None:
    raw_account_id = "DU1234567"
    diagnostics = IBKRReadDiagnostics(
        connected_to_socket=True,
        api_handshake_seen=True,
        managed_accounts_seen=True,
        managed_account_count_redacted=1,
        requested_account_hash="acct_abc123",
        requested_account_seen=True,
        positions_callback_seen=True,
        position_count=2,
        account_summary_callback_seen=True,
        cash_currency_count=1,
        timeout_seconds=10.0,
        warning_codes=[WarningCode.IBKR_POSITIONS_EMPTY],
    ).to_redacted_dict()
    text = "\n".join(_format_ibkr_data_diagnostics(diagnostics))

    assert "acct_abc123" in text
    assert raw_account_id not in text
    assert "IBKR_POSITIONS_EMPTY" in text


def test_connection_diagnostics_socket_unreachable_returns_warning(monkeypatch) -> None:
    import personal_cfo_agent.providers.ibkr_connection_diagnostics as diagnostics_module

    def _unreachable(*args, **kwargs):
        raise OSError("not reachable")

    monkeypatch.setattr(diagnostics_module.socket, "create_connection", _unreachable)
    diagnostics = run_ibkr_connection_diagnostics(_valid_env(), timeout_seconds=0.01)

    assert diagnostics.tcp_socket_reachable is False
    assert WarningCode.PROVIDER_CONNECTION_FAILED in diagnostics.warning_codes


def test_connection_diagnostics_missing_sdk_returns_warning(monkeypatch) -> None:
    import personal_cfo_agent.providers.ibkr_connection_diagnostics as diagnostics_module

    def _missing_sdk(name: str):
        if name == "ibapi":
            raise ImportError(name)
        raise AssertionError(name)

    monkeypatch.setattr(diagnostics_module.importlib, "import_module", _missing_sdk)
    diagnostics = run_ibkr_connection_diagnostics(_valid_env(), timeout_seconds=0.01)

    assert diagnostics.ibapi_import_ok is False
    assert WarningCode.SDK_NOT_INSTALLED in diagnostics.warning_codes


def test_ibapi_only_appears_as_lazy_import_string() -> None:
    adapter_text = (ROOT / "src" / "personal_cfo_agent" / "providers" / "ibkr_readonly_adapter.py").read_text(
        encoding="utf-8"
    )
    provider_text = (ROOT / "src" / "personal_cfo_agent" / "providers" / "ibkr_provider.py").read_text(
        encoding="utf-8"
    )
    assert "import ibapi" not in adapter_text
    assert "from ibapi" not in adapter_text
    assert "import ibapi" not in provider_text
    assert "from ibapi" not in provider_text
    assert 'importlib.import_module("ibapi.client")' in adapter_text
    assert 'importlib.import_module("ibapi.wrapper")' in adapter_text


def test_provider_mode_required_for_ibkr_live_gate() -> None:
    snapshots = collect_provider_snapshots(
        RuntimeConfig(env=_valid_env(), allow_live_read=True, provider="all")
    )
    ibkr_status = next(snapshot.status for snapshot in snapshots if snapshot.provider_name == "ibkr")
    assert WarningCode.LIVE_READ_NOT_ALLOWED in ibkr_status.warning_codes


def test_cli_readiness_check_works_without_tws_running() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "ibkr",
            "--readiness-check",
        ],
        cwd=ROOT,
        env={**os.environ, **_valid_env()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ibkr: api_contract_stub; warnings=None" in result.stdout
    assert "No provider produced data; no reports generated." in result.stdout


def test_cli_live_read_refuses_without_explicit_flag(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "ibkr",
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
    assert "Read-only IBKR sync only" not in result.stdout
    assert not (tmp_path / "reports").exists()


def test_generated_live_outputs_stay_under_ignored_reports_path() -> None:
    report_path = "reports/personal_cfo_agent/ibkr_v011_live_smoke/provider_sync_summary.json"
    result = subprocess.run(
        ["git", "check-ignore", "-v", report_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "reports/" in result.stdout


class _FakeAdapter:
    def __init__(self, snapshot: IBKRReadOnlySnapshot) -> None:
        self.snapshot = snapshot
        self.called = False

    def collect(self) -> IBKRReadOnlySnapshot:
        self.called = True
        return self.snapshot


class _FailingAdapter:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def collect(self) -> IBKRReadOnlySnapshot:
        from personal_cfo_agent.providers.ibkr_readonly_adapter import (
            IBKRConnectionError,
            IBKRFetchError,
        )

        if self.mode == "connection":
            raise IBKRConnectionError("gateway unavailable")
        if self.mode == "fetch":
            raise IBKRFetchError("fetch timed out")
        if self.mode == "handshake":
            raise IBKRConnectionError(
                "handshake timed out",
                IBKRReadDiagnostics(
                    connected_to_socket=True,
                    api_handshake_seen=False,
                    timeout_seconds=1.0,
                    warning_codes=[
                        WarningCode.IBKR_HANDSHAKE_TIMEOUT,
                        WarningCode.IBKR_CALLBACK_TIMEOUT,
                    ],
                ),
            )
        raise RuntimeError("unexpected adapter failure")


def _fixture_snapshot() -> IBKRReadOnlySnapshot:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    account_id = payload["account_id"]
    source_timestamp = payload["source_timestamp"]
    return IBKRReadOnlySnapshot(
        accounts=[IBKRAccountRow(account_id=account_id, currency="USD")],
        cash=[
            IBKRCashRow(
                account_id=account_id,
                currency=row["currency"],
                amount=float(row["amount"]),
                source_timestamp=source_timestamp,
            )
            for row in payload["cash"]
        ],
        positions=[
            IBKRPositionRow(
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
    return load_ibkr_config({**_valid_env(), **(extra or {})})


def _valid_env() -> dict[str, str]:
    return {
        "CFO_IBKR_ENABLED": "true",
        "CFO_IBKR_HOST": "127.0.0.1",
        "CFO_IBKR_PORT": "7497",
        "CFO_IBKR_CLIENT_ID": "991",
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
