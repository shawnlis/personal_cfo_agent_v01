from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig, load_tiger_config
from personal_cfo_agent.models import ConnectionMode, ProviderLevel, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.report_writer import write_report_bundle
from personal_cfo_agent.risk_engine import calculate_risk_summary
from personal_cfo_agent.providers.tiger_models import (
    TigerAccountRow,
    TigerCashRow,
    TigerPositionRow,
    TigerReadOnlySnapshot,
)
from personal_cfo_agent.providers.tiger_provider import TigerProvider
from personal_cfo_agent.runner import collect_provider_snapshots


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tiger_readonly_snapshot_v013.json"
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


def test_tiger_disabled_by_default() -> None:
    provider = TigerProvider(load_tiger_config({}))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes


def test_tiger_missing_config_fails_closed() -> None:
    provider = TigerProvider(load_tiger_config({"CFO_TIGER_ENABLED": "true"}))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes


def test_tiger_no_live_without_allow_flag() -> None:
    fake_adapter = _FakeAdapter(_fixture_snapshot())
    provider = TigerProvider(_valid_config(), allow_live_read=False, live_adapter=fake_adapter)
    snapshot = provider._sync()
    assert not fake_adapter.called
    assert not snapshot.has_data()
    assert WarningCode.LIVE_READ_NOT_ALLOWED in snapshot.status.warning_codes


def test_tiger_live_blocked_when_flag_exists_but_env_disabled() -> None:
    fake_adapter = _FakeAdapter(_fixture_snapshot())
    provider = TigerProvider(load_tiger_config({}), allow_live_read=True, live_adapter=fake_adapter)
    snapshot = provider._sync()
    assert not fake_adapter.called
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes


def test_tigeropen_import_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "tigeropen", raising=False)
    monkeypatch.delitem(sys.modules, "tigeropen.tiger_open_config", raising=False)
    provider = TigerProvider(_valid_config())
    provider.readiness_check()
    assert "tigeropen" not in sys.modules
    assert "tigeropen.tiger_open_config" not in sys.modules


def test_missing_tigeropen_sdk_returns_sdk_not_installed(monkeypatch) -> None:
    import personal_cfo_agent.providers.tiger_readonly_adapter as adapter_module

    def _missing_sdk(name: str):
        if name.startswith("tigeropen"):
            raise ImportError(name)
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _missing_sdk)
    provider = TigerProvider(_valid_config(), allow_live_read=True)
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.SDK_NOT_INSTALLED in snapshot.status.warning_codes


def test_tiger_provider_public_api_has_no_forbidden_methods() -> None:
    provider = TigerProvider(load_tiger_config({}))
    public_names = {name for name in dir(provider) if not name.startswith("_")}
    assert public_names.isdisjoint(FORBIDDEN_PUBLIC_METHODS)


def test_tiger_provider_public_callable_api_is_allowlisted() -> None:
    provider = TigerProvider(load_tiger_config({}))
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


def test_fixture_tiger_snapshot_normalizes_and_hashes_account_id() -> None:
    raw_account_id = "TIGER-TEST-ACCOUNT-246810"
    provider = TigerProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(_fixture_snapshot()),
    )
    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    assert snapshot.status.provider_level == ProviderLevel.LEVEL_2
    assert snapshot.status.connection_mode == ConnectionMode.LIVE_READ
    assert len(rows) == 2
    assert all(row.provider == "tiger" for row in rows)
    assert all(row.account_id_hash.startswith("acct_") for row in rows)
    assert all(row.account_id_hash != raw_account_id for row in rows)

    output_text = "\n".join(str(row.to_csv_row()) for row in rows)
    assert raw_account_id not in output_text
    assert "account_id_hash" in output_text


def test_tiger_connection_failure_returns_warning_code_without_crashing() -> None:
    provider = TigerProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("connection"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes


def test_tiger_fetch_failure_returns_warning_code_without_crashing() -> None:
    provider = TigerProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FailingAdapter("fetch"),
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes


def test_tiger_raw_account_id_redacted_from_markdown_json_and_csv_outputs(tmp_path) -> None:
    raw_account_id = "TIGER-TEST-ACCOUNT-246810"
    provider = TigerProvider(
        _valid_config(),
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


def test_tiger_provider_summary_records_read_only_safety_flags(tmp_path) -> None:
    provider = TigerProvider(
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


def test_config_values_are_not_printed_by_tiger_cli_readiness_check(tmp_path) -> None:
    env = {
        **os.environ,
        "CFO_TIGER_ENABLED": "true",
        "CFO_TIGER_CONFIG_DIR": str(tmp_path / "local_tiger_config"),
        "CFO_TIGER_ACCOUNT": "TIGER_SECRET_ACCOUNT_7331",
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "tiger",
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
    assert "local_tiger_config" not in combined
    assert "TIGER_SECRET_ACCOUNT_7331" not in combined


def test_tigeropen_only_appears_as_lazy_import_string() -> None:
    adapter_text = (
        ROOT / "src" / "personal_cfo_agent" / "providers" / "tiger_readonly_adapter.py"
    ).read_text(encoding="utf-8")
    provider_text = (
        ROOT / "src" / "personal_cfo_agent" / "providers" / "tiger_provider.py"
    ).read_text(encoding="utf-8")
    assert "import tigeropen" not in adapter_text
    assert "from tigeropen" not in adapter_text
    assert "import tigeropen" not in provider_text
    assert "from tigeropen" not in provider_text
    assert 'importlib.import_module("tigeropen.tiger_open_config")' in adapter_text
    assert '".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"])' in adapter_text


def test_provider_mode_required_for_tiger_live_gate() -> None:
    snapshots = collect_provider_snapshots(
        RuntimeConfig(env=_valid_env(), allow_live_read=True, provider="all")
    )
    tiger_status = next(snapshot.status for snapshot in snapshots if snapshot.provider_name == "tiger")
    assert WarningCode.LIVE_READ_NOT_ALLOWED in tiger_status.warning_codes


def test_cli_tiger_readiness_check_works_without_real_tiger_config(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "tiger",
            "--readiness-check",
        ],
        cwd=ROOT,
        env={**os.environ, **_valid_env(str(tmp_path / "missing_config"))},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "tiger: api_contract_stub; warnings=None" in result.stdout
    assert "No provider produced data; no reports generated." in result.stdout


def test_cli_tiger_live_read_refuses_without_explicit_flag(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "tiger",
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=ROOT,
        env={**os.environ, **_valid_env(str(tmp_path / "missing_config"))},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "LIVE_READ_NOT_ALLOWED" in result.stdout
    assert "Read-only Tiger sync only" not in result.stdout
    assert not (tmp_path / "reports").exists()


def test_generated_tiger_outputs_stay_under_ignored_reports_path() -> None:
    report_path = "reports/personal_cfo_agent/tiger_v013_live_smoke/provider_sync_summary.json"
    result = subprocess.run(
        ["git", "check-ignore", "-v", report_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "reports/" in result.stdout


def test_tiger_source_has_no_forbidden_call_markers() -> None:
    for path in [
        ROOT / "src" / "personal_cfo_agent" / "providers" / "tiger_provider.py",
        ROOT / "src" / "personal_cfo_agent" / "providers" / "tiger_readonly_adapter.py",
    ]:
        text = path.read_text(encoding="utf-8").lower()
        for marker in FORBIDDEN_PUBLIC_METHODS:
            assert re.search(rf"\b{re.escape(marker.lower())}\b", text) is None


class _FakeAdapter:
    def __init__(self, snapshot: TigerReadOnlySnapshot) -> None:
        self.snapshot = snapshot
        self.called = False

    def collect(self) -> TigerReadOnlySnapshot:
        self.called = True
        return self.snapshot


class _FailingAdapter:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def collect(self) -> TigerReadOnlySnapshot:
        from personal_cfo_agent.providers.tiger_readonly_adapter import (
            TigerConnectionError,
            TigerFetchError,
        )

        if self.mode == "connection":
            raise TigerConnectionError("TigerOpen config unavailable")
        if self.mode == "fetch":
            raise TigerFetchError("fetch failed")
        raise RuntimeError("unexpected adapter failure")


def _fixture_snapshot() -> TigerReadOnlySnapshot:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    account_id = payload["account_id"]
    source_timestamp = payload["source_timestamp"]
    return TigerReadOnlySnapshot(
        accounts=[TigerAccountRow(account_id=account_id, currency="USD")],
        cash=[
            TigerCashRow(
                account_id=account_id,
                currency=row["currency"],
                amount=float(row["amount"]),
                source_timestamp=source_timestamp,
            )
            for row in payload["cash"]
        ],
        positions=[
            TigerPositionRow(
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
    return load_tiger_config({**_valid_env(), **(extra or {})})


def _valid_env(config_dir: str = r"C:\tmp\tigeropen_config") -> dict[str, str]:
    return {
        "CFO_TIGER_ENABLED": "true",
        "CFO_TIGER_CONFIG_DIR": config_dir,
        "CFO_TIGER_ACCOUNT": "TIGER-TEST-ACCOUNT-246810",
    }
