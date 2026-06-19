from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.config import connector_status, load_webull_config
from personal_cfo_agent.models import ConnectionMode, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.providers.webull_connection_diagnostics import (
    run_webull_connection_diagnostics,
)
from personal_cfo_agent.providers.webull_provider import WebullProvider
from personal_cfo_agent.providers.webull_readonly_adapter import (
    WebullAccountRow,
    WebullCashRow,
    WebullClientInitError,
    WebullFetchError,
    WebullPositionRow,
    WebullReadDiagnostics,
    WebullReadOnlyAdapter,
    WebullReadOnlySnapshot,
    WebullSDKNotInstalledError,
)
from personal_cfo_agent.runner import main, run_readiness_check
from personal_cfo_agent.config import RuntimeConfig


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_WEBULL_MARKERS = (
    "place_order",
    "submit_order",
    "modify_order",
    "cancel_order",
    "preview_order",
    "transfer_cash",
    "withdraw_cash",
)


def test_webull_provider_disabled_by_default() -> None:
    provider = WebullProvider(load_webull_config({}))
    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["live_connection_attempted"] is False


def test_webull_missing_config_fails_closed() -> None:
    provider = WebullProvider(load_webull_config({"CFO_WEBULL_ENABLED": "true"}))
    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes


def test_webull_sdk_missing_is_reported_after_config_present() -> None:
    env = _enabled_env()
    diagnostics = run_webull_connection_diagnostics(
        env,
        import_module=lambda name: (_raise_import_error(name)),
    )

    assert diagnostics.sdk_import_ok is False
    assert diagnostics.warning_codes == (WarningCode.SDK_NOT_INSTALLED,)
    assert diagnostics.live_connection_attempted is False


def test_webull_sdk_import_exception_fails_closed_without_leaking_error_text() -> None:
    diagnostics = run_webull_connection_diagnostics(
        _enabled_env({"CFO_WEBULL_SDK_MODULE": "broken_webull_sdk"}),
        import_module=lambda name: (_raise_runtime_error(name)),
    )

    assert diagnostics.sdk_import_ok is False
    assert diagnostics.sdk_module_detected == "unavailable"
    assert diagnostics.warning_codes == (WarningCode.SDK_NOT_INSTALLED,)


def test_webull_readiness_success_with_mocked_sdk_and_config() -> None:
    diagnostics = run_webull_connection_diagnostics(
        _enabled_env({"CFO_WEBULL_SDK_MODULE": "mock_webull_sdk"}),
        import_module=lambda name: object(),
    )

    assert diagnostics.sdk_import_ok is True
    assert diagnostics.sdk_module_detected == "mock_webull_sdk"
    assert diagnostics.warning_codes == (WarningCode.WEBULL_READINESS_OK,)
    assert diagnostics.live_connection_attempted is False


def test_webull_provider_readiness_uses_redacted_diagnostics(monkeypatch) -> None:
    import personal_cfo_agent.providers.webull_connection_diagnostics as diag_module

    monkeypatch.setattr(diag_module.importlib, "import_module", lambda name: object())
    provider = WebullProvider(load_webull_config(_enabled_env()))
    warnings = provider.readiness_check()

    assert warnings == [WarningCode.WEBULL_READINESS_OK]
    assert provider._status().connection_mode == ConnectionMode.LIVE_READINESS
    output = str(provider._status().to_dict())
    assert "APP_KEY_SENTINEL" not in output
    assert "APP_SECRET_SENTINEL" not in output
    assert "app_key_present_redacted" in output


def test_webull_readiness_cli_exists_and_redacts_config_values() -> None:
    env = {
        **os.environ,
        **_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"}),
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "webull",
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
    assert "webull: live_readiness_check_only" in result.stdout
    assert "WEBULL_READINESS_OK" in result.stdout
    assert "APP_KEY_SENTINEL" not in combined
    assert "APP_SECRET_SENTINEL" not in combined


def test_webull_connection_diagnostics_cli_does_not_call_network_or_print_secrets() -> None:
    env = {
        **os.environ,
        **_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"}),
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "webull",
            "--connection-diagnostics",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Webull readiness diagnostics (values redacted)" in result.stdout
    assert "Live connection attempted: no" in result.stdout
    assert "APP_KEY_SENTINEL" not in combined
    assert "APP_SECRET_SENTINEL" not in combined


def test_webull_connector_status_is_feasibility_only() -> None:
    status = connector_status("webull")

    assert status["status"] == "supervised_read_only_live_proof_in_progress"
    assert status["asset_read"] is True
    assert status["position_read"] is True
    assert status["cash_read"] is True


def test_webull_source_has_no_write_api_markers() -> None:
    webull_files = sorted((ROOT / "src" / "personal_cfo_agent" / "providers").glob("webull_*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in webull_files)
    for marker in FORBIDDEN_WEBULL_MARKERS:
        assert re.search(rf"\b{re.escape(marker)}\b", source) is None


def test_webull_config_example_is_placeholder_only() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "CFO_WEBULL_ENABLED=false" in text
    assert "CFO_WEBULL_APP_KEY=\n" in text
    assert "CFO_WEBULL_APP_SECRET=\n" in text
    assert "APP_KEY_SENTINEL" not in text


def test_webull_readiness_does_not_affect_other_provider_readiness() -> None:
    result = run_readiness_check(RuntimeConfig(provider="webull", env=_enabled_env()))

    assert len(result.statuses) == 1
    assert result.statuses[0].provider_name == "webull"


def test_webull_live_requires_allow_live_read_gate(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "webull",
            "--webull-data-diagnostics",
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=ROOT,
        env={**os.environ, **_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"})},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--webull-data-diagnostics requires --allow-live-read" in (
        result.stdout + result.stderr
    )
    assert not (tmp_path / "reports").exists()


def test_webull_sdk_missing_fails_closed_in_live_path() -> None:
    provider = WebullProvider(
        load_webull_config(_enabled_env({"CFO_WEBULL_SDK_MODULE": "missing_webull_sdk"})),
        allow_live_read=True,
        live_adapter=_FailingAdapter(
            WebullSDKNotInstalledError(
                "missing",
                WebullReadDiagnostics(
                    warning_codes=(
                        WarningCode.WEBULL_SDK_NOT_INSTALLED,
                        WarningCode.SDK_NOT_INSTALLED,
                    )
                ),
            )
        ),
    )

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.WEBULL_SDK_NOT_INSTALLED in snapshot.status.warning_codes
    assert WarningCode.SDK_NOT_INSTALLED in snapshot.status.warning_codes


def test_webull_client_init_failure_fails_closed() -> None:
    provider = WebullProvider(
        load_webull_config(_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"})),
        allow_live_read=True,
        live_adapter=_FailingAdapter(
            WebullClientInitError(
                "init failed",
                WebullReadDiagnostics(
                    client_init_attempted=True,
                    warning_codes=(WarningCode.WEBULL_CLIENT_INIT_FAILED,),
                ),
            )
        ),
    )

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.WEBULL_CLIENT_INIT_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes


def test_webull_auth_failure_is_sanitized_as_client_init_failure() -> None:
    provider = WebullProvider(
        load_webull_config(_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"})),
        allow_live_read=True,
        live_adapter=_FailingAdapter(
            WebullClientInitError(
                "auth failed",
                WebullReadDiagnostics(
                    client_init_attempted=True,
                    warning_codes=(WarningCode.WEBULL_AUTH_FAILED,),
                ),
            )
        ),
    )

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.WEBULL_AUTH_FAILED in snapshot.status.warning_codes
    assert "APP_SECRET_SENTINEL" not in str(snapshot.status.to_dict())


def test_webull_account_asset_position_success_normalizes_nav_and_positions() -> None:
    raw_account_id = "WEBULL_ACCOUNT_SENTINEL"
    provider = WebullProvider(
        load_webull_config(_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"})),
        allow_live_read=True,
        live_adapter=_SnapshotAdapter(_fixture_webull_snapshot(raw_account_id)),
    )

    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    nav_rows = [row for row in rows if row.asset_type == "account_nav"]
    position_rows = [row for row in rows if row.symbol == "AAPL"]

    assert snapshot.has_data()
    assert snapshot.status.connection_mode == ConnectionMode.LIVE_READ
    assert WarningCode.WEBULL_READ_ONLY_FETCH_OK in snapshot.status.warning_codes
    assert WarningCode.WEBULL_LIVE_READ_SUCCEEDED in snapshot.status.warning_codes
    assert len(nav_rows) == 1
    assert WarningCode.ACCOUNT_NAV_PROVIDER_REPORTED in nav_rows[0].warning_codes
    assert len(position_rows) == 1
    assert raw_account_id not in str([row.to_csv_row() for row in rows])


def test_webull_fetch_failures_return_stage_warning_codes() -> None:
    provider = WebullProvider(
        load_webull_config(_enabled_env({"CFO_WEBULL_SDK_MODULE": "os"})),
        allow_live_read=True,
        live_adapter=_FailingAdapter(
            WebullFetchError(
                "asset failed",
                WebullReadDiagnostics(
                    account_query_attempted=True,
                    account_query_success=True,
                    asset_query_attempted=True,
                    warning_codes=(
                        WarningCode.WEBULL_ASSET_QUERY_FAILED,
                        WarningCode.WEBULL_LIVE_READ_FAILED,
                    ),
                    stage_failures={"asset_query": "Webull asset query failed"},
                ),
            )
        ),
    )

    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.WEBULL_ASSET_QUERY_FAILED in snapshot.status.warning_codes
    assert WarningCode.WEBULL_LIVE_READ_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["stage_failures"] == {
        "asset_query": "Webull asset query failed"
    }


def test_webull_adapter_suppresses_sdk_stdout_and_maps_payloads(capsys) -> None:
    class _FakeClient:
        def get_account_list(self):
            print("SDK_ACCOUNT_STDOUT")
            return [{"accountId": "WEBULL_ACCOUNT_SENTINEL", "currency": "USD"}]

        def get_account_balance(self, account_id):
            print("SDK_BALANCE_STDOUT")
            return {"netAssetValue": "123.45", "cashBalance": "23.45", "currency": "USD"}

        def get_account_positions(self, account_id):
            print("SDK_POSITION_STDOUT")
            return [{"symbol": "AAPL", "quantity": "1", "marketValue": "100"}]

    adapter = WebullReadOnlyAdapter(
        _enabled_env({"CFO_WEBULL_SDK_MODULE": "fake_webull_sdk"}),
        import_module=lambda name: object(),
        client_factory=lambda sdk, settings: _FakeClient(),
    )

    snapshot = adapter.collect()
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""
    assert snapshot.diagnostics["sdk_output_suppressed"] is True
    assert snapshot.diagnostics["account_count_redacted"] == 1
    assert snapshot.diagnostics["position_count"] == 1
    assert "WEBULL_ACCOUNT_SENTINEL" not in str(snapshot.diagnostics)


def test_webull_cli_data_diagnostics_redacts_and_writes_report(
    tmp_path, monkeypatch, capsys
) -> None:
    import personal_cfo_agent.providers.webull_provider as provider_module

    monkeypatch.setattr(
        provider_module.WebullProvider,
        "_build_adapter",
        lambda self: _SnapshotAdapter(_fixture_webull_snapshot("WEBULL_ACCOUNT_SENTINEL")),
    )
    monkeypatch.setenv("CFO_WEBULL_ENABLED", "true")
    monkeypatch.setenv("CFO_WEBULL_APP_KEY", "APP_KEY_SENTINEL")
    monkeypatch.setenv("CFO_WEBULL_APP_SECRET", "APP_SECRET_SENTINEL")
    monkeypatch.setenv("CFO_WEBULL_API_HOST", "api.example.invalid")
    monkeypatch.setenv("CFO_WEBULL_SDK_MODULE", "os")
    out_dir = tmp_path / "webull_report"

    exit_code = main(
        [
            "--provider",
            "webull",
            "--allow-live-read",
            "--webull-data-diagnostics",
            "--out-dir",
            str(out_dir),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Webull data-path diagnostics (values redacted)" in output
    assert "WEBULL_ACCOUNT_SENTINEL" not in output
    assert "APP_KEY_SENTINEL" not in output
    assert "APP_SECRET_SENTINEL" not in output
    assert (out_dir / "normalized_asset_ledger.csv").exists()
    assert (out_dir / "provider_sync_summary.json").exists()


def test_webull_reports_are_gitignored() -> None:
    assert _is_ignored("reports/personal_cfo_agent/webull_v056_live_acceptance")


def test_webull_source_has_no_credential_literals_or_raw_account_output() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "src" / "personal_cfo_agent" / "providers").glob("webull_*.py"))
    )
    assert "APP_KEY_SENTINEL" not in source
    assert "APP_SECRET_SENTINEL" not in source
    assert "WEBULL_ACCOUNT_SENTINEL" not in source


def _enabled_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "CFO_WEBULL_ENABLED": "true",
        "CFO_WEBULL_APP_KEY": "APP_KEY_SENTINEL",
        "CFO_WEBULL_APP_SECRET": "APP_SECRET_SENTINEL",
        "CFO_WEBULL_API_HOST": "api.example.invalid",
    }
    if extra:
        env.update(extra)
    return env


class _SnapshotAdapter:
    def __init__(self, snapshot: WebullReadOnlySnapshot) -> None:
        self._snapshot = snapshot

    def collect(self) -> WebullReadOnlySnapshot:
        return self._snapshot


class _FailingAdapter:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def collect(self) -> WebullReadOnlySnapshot:
        raise self._exc


def _fixture_webull_snapshot(account_id: str) -> WebullReadOnlySnapshot:
    diagnostics = WebullReadDiagnostics(
        sdk_import_ok=True,
        sdk_module_detected="mock_webull_sdk",
        client_init_attempted=True,
        client_init_success=True,
        account_query_attempted=True,
        account_query_success=True,
        asset_query_attempted=True,
        asset_query_success=True,
        position_query_attempted=True,
        position_query_success=True,
        account_count_redacted=1,
        selected_account_hash="acct_fixture_hash",
        position_count=1,
        normalized_rows_possible=3,
        sdk_output_suppressed=True,
        warning_codes=(
            WarningCode.WEBULL_READ_ONLY_FETCH_OK,
            WarningCode.WEBULL_LIVE_READ_SUCCEEDED,
        ),
    )
    return WebullReadOnlySnapshot(
        accounts=[
            WebullAccountRow(
                account_id=account_id,
                account_type="cash",
                currency="USD",
                account_nav=123.45,
                source_timestamp="2026-06-19T00:00:00+00:00",
            )
        ],
        cash=[
            WebullCashRow(
                account_id=account_id,
                currency="USD",
                amount=23.45,
                source_timestamp="2026-06-19T00:00:00+00:00",
            )
        ],
        positions=[
            WebullPositionRow(
                account_id=account_id,
                asset_id="AAPL",
                asset_type="equity",
                symbol="AAPL",
                name="Apple Inc synthetic",
                quantity=1.0,
                currency="USD",
                market_value=100.0,
                cost_basis=90.0,
                source_timestamp="2026-06-19T00:00:00+00:00",
            )
        ],
        diagnostics=diagnostics.to_redacted_dict(),
    )


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _raise_import_error(name: str) -> None:
    raise ImportError(name)


def _raise_runtime_error(name: str) -> None:
    raise RuntimeError(f"simulated import failure for {name}")
