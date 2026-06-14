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
from personal_cfo_agent.providers.moomoo_provider import MoomooProvider
from personal_cfo_agent.runner import collect_provider_snapshots
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
        connected_to_opend=True,
        connection_established=True,
        account_list_seen=True,
        account_count_redacted=1,
        positions_seen=True,
        position_count=2,
        cash_seen=True,
        cash_currency_count=1,
        normalized_row_count=3,
        timeout_seconds=10.0,
        warning_codes=[WarningCode.MOOMOO_POSITIONS_EMPTY],
    ).to_redacted_dict()

    assert tuple(diagnostics.keys()) == (
        "connected_to_opend",
        "connection_established",
        "account_list_seen",
        "account_count_redacted",
        "positions_seen",
        "position_count",
        "cash_seen",
        "cash_currency_count",
        "normalized_row_count",
        "timeout_seconds",
        "warning_codes",
    )
    text = "\n".join(_format_moomoo_data_diagnostics(diagnostics))
    assert "Connection established: yes" in text
    assert "Account count redacted: 1" in text
    assert "Normalized rows count: 3" in text
    assert "MOOMOO_POSITIONS_EMPTY" in text


def test_empty_moomoo_account_list_warning_is_handled() -> None:
    diagnostics = MoomooReadDiagnostics(
        connected_to_opend=True,
        connection_established=True,
        account_list_seen=True,
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
    assert snapshot.status.diagnostics["account_list_seen"] is True
    assert snapshot.status.diagnostics["account_count_redacted"] == 0


def test_empty_moomoo_positions_warning_is_handled() -> None:
    diagnostics = MoomooReadDiagnostics(
        connected_to_opend=True,
        connection_established=True,
        account_list_seen=True,
        account_count_redacted=1,
        positions_seen=True,
        position_count=0,
        warning_codes=[WarningCode.MOOMOO_POSITIONS_EMPTY],
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

    assert WarningCode.MOOMOO_POSITIONS_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["positions_seen"] is True
    assert snapshot.status.diagnostics["position_count"] == 0


def test_empty_moomoo_cash_warning_is_handled() -> None:
    diagnostics = MoomooReadDiagnostics(
        connected_to_opend=True,
        connection_established=True,
        account_list_seen=True,
        account_count_redacted=1,
        cash_seen=True,
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
    assert snapshot.status.diagnostics["cash_seen"] is True
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
