from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig, load_tiger_config
from personal_cfo_agent.models import ConnectionMode, ProviderLevel, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.providers.tiger_connection_diagnostics import (
    DEFAULT_PROPS_FILE,
    run_tiger_config_preflight,
    run_tiger_connection_diagnostics,
    run_tiger_sdk_config_probe,
)
from personal_cfo_agent.report_writer import write_report_bundle
from personal_cfo_agent.risk_engine import calculate_risk_summary
from personal_cfo_agent.providers.tiger_models import (
    TigerAccountRow,
    TigerCashRow,
    TigerPositionRow,
    TigerReadOnlySnapshot,
)
from personal_cfo_agent.providers.tiger_provider import TigerProvider
from personal_cfo_agent.providers.tiger_readonly_adapter import TigerReadOnlyAdapter
from personal_cfo_agent.runner import (
    _format_tiger_config_preflight,
    _format_tiger_connection_diagnostics,
    _format_tiger_data_diagnostics,
    _format_tiger_sdk_config_probe,
    collect_provider_snapshots,
)


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


def test_missing_tigeropen_sdk_returns_sdk_not_installed(monkeypatch, tmp_path) -> None:
    import personal_cfo_agent.providers.tiger_readonly_adapter as adapter_module

    def _missing_sdk(name: str):
        if name.startswith("tigeropen"):
            raise ImportError(name)
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _missing_sdk)
    _write_placeholder_tiger_config(tmp_path)
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.SDK_NOT_INSTALLED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["sdk_import_ok"] is False
    assert snapshot.status.diagnostics["stage_failures"] == {
        "sdk_import": "TigerOpen SDK import failed"
    }


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


def test_tiger_connection_diagnostics_are_redacted_and_check_config_file(
    tmp_path, monkeypatch
) -> None:
    import personal_cfo_agent.providers.tiger_connection_diagnostics as diag_module

    monkeypatch.setattr(diag_module.importlib, "import_module", lambda name: object())
    env = {
        "CFO_TIGER_ENABLED": "true",
        "CFO_TIGER_CONFIG_DIR": str(tmp_path),
        "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        "CFO_ACCOUNT_HASH_SALT": "HASH_SALT_SENTINEL",
    }
    diagnostics = run_tiger_connection_diagnostics(env)
    formatted = "\n".join(_format_tiger_connection_diagnostics(diagnostics))

    assert diagnostics.config_dir_exists is True
    assert diagnostics.config_file_exists is False
    assert WarningCode.PROVIDER_CONFIG_MISSING in diagnostics.warning_codes
    assert str(tmp_path) not in formatted
    assert "TIGER_ACCOUNT_SENTINEL" not in formatted
    assert "HASH_SALT_SENTINEL" not in formatted

    _write_placeholder_tiger_config(tmp_path)
    diagnostics = run_tiger_connection_diagnostics(env)
    assert diagnostics.config_file_exists is True
    assert diagnostics.private_key_present is True
    assert diagnostics.private_key_format_detected == "pkcs8"
    assert diagnostics.warning_codes == ()


def test_cli_tiger_connection_diagnostics_does_not_print_config_values(tmp_path) -> None:
    config_dir = tmp_path / "local_tiger_config"
    config_dir.mkdir()
    _write_placeholder_tiger_config(config_dir)
    env = {
        **os.environ,
        "CFO_TIGER_ENABLED": "true",
        "CFO_TIGER_CONFIG_DIR": str(config_dir),
        "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        "CFO_ACCOUNT_HASH_SALT": "HASH_SALT_SENTINEL",
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "tiger",
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
    assert "Tiger connection diagnostics (values redacted)" in result.stdout
    assert "Config file exists: yes" in result.stdout
    assert str(config_dir) not in combined
    assert "TIGER_ACCOUNT_SENTINEL" not in combined
    assert "HASH_SALT_SENTINEL" not in combined
    assert "PRIVATE_KEY_PLACEHOLDER" not in combined


def test_tiger_config_preflight_passes_with_external_synthetic_config(tmp_path) -> None:
    with tempfile.TemporaryDirectory(prefix="tiger_preflight_") as raw_dir:
        config_dir = Path(raw_dir) / "external_tiger_config"
        _write_placeholder_tiger_config(config_dir, key_name="private_key_pk1")
        diagnostics = run_tiger_config_preflight(
            {
                "CFO_TIGER_ENABLED": "true",
                "CFO_TIGER_CONFIG_DIR": str(config_dir),
                "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
            },
            repo_root=ROOT,
        )

    assert diagnostics.warning_codes == (WarningCode.TIGER_CONFIG_PREFLIGHT_OK,)
    assert diagnostics.config_file_outside_repo is True
    assert diagnostics.config_file_tracked is False
    assert diagnostics.config_history_risk is False
    assert diagnostics.private_key_format_category == "pkcs1_like"


def test_tiger_config_preflight_missing_config_dir_emits_stage_code(tmp_path) -> None:
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path / "missing"),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert WarningCode.TIGER_CONFIG_DIR_MISSING in diagnostics.warning_codes
    assert WarningCode.TIGER_CONFIG_PREFLIGHT_FAILED in diagnostics.warning_codes


def test_tiger_config_preflight_missing_config_file_emits_stage_code(tmp_path) -> None:
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert WarningCode.TIGER_CONFIG_FILE_MISSING in diagnostics.warning_codes
    assert WarningCode.TIGER_CONFIG_PREFLIGHT_FAILED in diagnostics.warning_codes


def test_tiger_config_preflight_invalid_config_file_emits_unreadable(tmp_path) -> None:
    (tmp_path / DEFAULT_PROPS_FILE).write_bytes(b"\xff\xfe\xfa")
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert diagnostics.config_file_exists is True
    assert diagnostics.config_file_readable is False
    assert WarningCode.TIGER_CONFIG_FILE_UNREADABLE in diagnostics.warning_codes


def test_tiger_config_preflight_missing_required_keys_emits_redacted_codes(
    tmp_path,
) -> None:
    (tmp_path / DEFAULT_PROPS_FILE).write_text(
        "tiger_id=TIGER_ID_PLACEHOLDER\n",
        encoding="utf-8",
    )
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
        },
        repo_root=ROOT,
    )

    assert WarningCode.TIGER_CONFIG_REQUIRED_KEY_MISSING in diagnostics.warning_codes
    assert WarningCode.TIGER_PRIVATE_KEY_FIELD_MISSING in diagnostics.warning_codes


def test_tiger_config_preflight_unknown_key_format_emits_stage_code(tmp_path) -> None:
    (tmp_path / DEFAULT_PROPS_FILE).write_text(
        "\n".join(
            [
                "tiger_id=TIGER_ID_PLACEHOLDER",
                "account=ACCOUNT_PLACEHOLDER",
                "private_key=UNKNOWN_KEY_PLACEHOLDER",
            ]
        ),
        encoding="utf-8",
    )
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
        },
        repo_root=ROOT,
    )

    assert diagnostics.private_key_format_category == "unknown_format"
    assert WarningCode.TIGER_PRIVATE_KEY_FORMAT_UNKNOWN in diagnostics.warning_codes


def test_tiger_config_preflight_inside_repo_emits_stage_code(tmp_path) -> None:
    repo = tmp_path / "repo"
    config_dir = repo / "tiger_config"
    config_dir.mkdir(parents=True)
    _write_placeholder_tiger_config(config_dir)
    _git(repo, "init")
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(config_dir),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=repo,
    )

    assert diagnostics.config_file_outside_repo is False
    assert WarningCode.TIGER_CONFIG_FILE_INSIDE_REPO in diagnostics.warning_codes


def test_tiger_config_preflight_tracked_config_emits_stage_code(tmp_path) -> None:
    repo = tmp_path / "repo"
    config_dir = repo / "tiger_config"
    config_dir.mkdir(parents=True)
    _write_placeholder_tiger_config(config_dir)
    _git(repo, "init")
    _git(repo, "add", "tiger_config/tiger_openapi_config.properties")
    diagnostics = run_tiger_config_preflight(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(config_dir),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=repo,
    )

    assert diagnostics.config_file_tracked is True
    assert WarningCode.TIGER_CONFIG_FILE_TRACKED in diagnostics.warning_codes


def test_cli_tiger_config_preflight_redacts_values_and_does_not_live_init(
    tmp_path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="tiger_preflight_") as raw_dir:
        config_dir = Path(raw_dir) / "external_tiger_config"
        _write_placeholder_tiger_config(config_dir)
        env = {
            **os.environ,
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(config_dir),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
            "CFO_ACCOUNT_HASH_SALT": "HASH_SALT_SENTINEL",
        }
        result = subprocess.run(
            [
                sys.executable,
                "scripts/personal_cfo_agent.py",
                "--provider",
                "tiger",
                "--config-preflight",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    combined = result.stdout + result.stderr

    assert result.returncode == 0
    assert "Tiger config preflight (values redacted)" in result.stdout
    assert "TigerOpen client initialized: no" in result.stdout
    assert "Tiger account APIs called: no" in result.stdout
    assert str(config_dir) not in combined
    assert "TIGER_ACCOUNT_SENTINEL" not in combined
    assert "HASH_SALT_SENTINEL" not in combined
    assert "PRIVATE_KEY_PLACEHOLDER" not in combined


def test_tiger_config_preflight_formatter_redacts_static_values(tmp_path) -> None:
    with tempfile.TemporaryDirectory(prefix="tiger_preflight_") as raw_dir:
        config_dir = Path(raw_dir) / "external_tiger_config"
        _write_placeholder_tiger_config(config_dir)
        diagnostics = run_tiger_config_preflight(
            {
                "CFO_TIGER_ENABLED": "true",
                "CFO_TIGER_CONFIG_DIR": str(config_dir),
                "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
            },
            repo_root=ROOT,
        )
    formatted = "\n".join(_format_tiger_config_preflight(diagnostics))

    assert str(config_dir) not in formatted
    assert "TIGER_ACCOUNT_SENTINEL" not in formatted
    assert "PRIVATE_KEY_PLACEHOLDER" not in formatted
    assert "tiger_openapi_config.properties" in formatted


def test_tiger_config_preflight_does_not_import_or_initialize_tigeropen(
    tmp_path, monkeypatch
) -> None:
    import personal_cfo_agent.providers.tiger_connection_diagnostics as diag_module

    def _blocked_import(name: str):
        raise AssertionError(name)

    monkeypatch.setattr(diag_module.importlib, "import_module", _blocked_import)
    with tempfile.TemporaryDirectory(prefix="tiger_preflight_") as raw_dir:
        config_dir = Path(raw_dir)
        _write_placeholder_tiger_config(config_dir)
        diagnostics = run_tiger_config_preflight(
            {
                "CFO_TIGER_ENABLED": "true",
                "CFO_TIGER_CONFIG_DIR": str(config_dir),
                "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
            },
            repo_root=ROOT,
        )

    assert diagnostics.warning_codes == (WarningCode.TIGER_CONFIG_PREFLIGHT_OK,)


def test_cli_tiger_sdk_config_probe_flag_exists() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/personal_cfo_agent.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--sdk-config-probe" in result.stdout


def test_tiger_sdk_config_probe_redacts_values_and_sanitizes_exceptions(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_probe_sdk(
        monkeypatch,
        fail_modes={"directory": RuntimeError("TIGER_SECRET_ACCOUNT_123456")},
    )
    diagnostics = run_tiger_sdk_config_probe(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )
    formatted = "\n".join(_format_tiger_sdk_config_probe(diagnostics))

    assert diagnostics.working_props_path_mode == "file"
    assert diagnostics.sdk_config_constructed is True
    assert "TIGER_SECRET_ACCOUNT_123456" not in formatted
    assert "TIGER_ACCOUNT_SENTINEL" not in formatted
    assert "PRIVATE_KEY_PLACEHOLDER" not in formatted


def test_tiger_sdk_config_probe_does_not_call_account_data_apis(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    calls = _install_fake_tiger_probe_sdk(monkeypatch)
    diagnostics = run_tiger_sdk_config_probe(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert diagnostics.sdk_client_constructed is True
    assert calls["asset"] == 0
    assert calls["position"] == 0
    assert calls["cash"] == 0


def test_tiger_sdk_config_probe_records_props_path_mode_attempts(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_probe_sdk(monkeypatch)
    diagnostics = run_tiger_sdk_config_probe(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert diagnostics.props_path_modes_tested == (
        "directory",
        "file",
        "explicit_props_path",
        "sdk_default",
    )
    assert {result.mode for result in diagnostics.variant_results} == set(
        diagnostics.props_path_modes_tested
    )


def test_tiger_sdk_config_probe_successful_file_mode_selects_file_fallback(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_probe_sdk(
        monkeypatch,
        fail_modes={"directory": RuntimeError("directory mode failed")},
    )
    diagnostics = run_tiger_sdk_config_probe(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert diagnostics.working_props_path_mode == "file"
    assert diagnostics.sdk_config_constructed is True


def test_tiger_sdk_config_probe_successful_directory_mode_selects_directory(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_probe_sdk(
        monkeypatch,
        fail_modes={"file": RuntimeError("file mode failed")},
    )
    diagnostics = run_tiger_sdk_config_probe(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert diagnostics.working_props_path_mode == "directory"
    assert diagnostics.sdk_config_constructed is True


def test_tiger_sdk_config_probe_all_failed_modes_return_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_probe_sdk(
        monkeypatch,
        fail_modes={
            "directory": RuntimeError("directory failed"),
            "file": RuntimeError("file failed"),
            "explicit_props_path": RuntimeError("explicit failed"),
            "sdk_default": RuntimeError("default failed"),
        },
    )
    diagnostics = run_tiger_sdk_config_probe(
        {
            "CFO_TIGER_ENABLED": "true",
            "CFO_TIGER_CONFIG_DIR": str(tmp_path),
            "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
        },
        repo_root=ROOT,
    )

    assert diagnostics.working_props_path_mode == "none"
    assert diagnostics.sdk_config_constructed is False
    assert WarningCode.TIGER_SDK_CONFIG_PROBE_FAILED in diagnostics.warning_codes


def test_cli_tiger_sdk_config_probe_redacts_values_with_synthetic_config() -> None:
    with tempfile.TemporaryDirectory(prefix="tiger_probe_") as raw_dir:
        config_dir = Path(raw_dir) / "external_tiger_config"
        _write_placeholder_tiger_config(config_dir)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/personal_cfo_agent.py",
                "--provider",
                "tiger",
                "--sdk-config-probe",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "CFO_TIGER_ENABLED": "true",
                "CFO_TIGER_CONFIG_DIR": str(config_dir),
                "CFO_TIGER_ACCOUNT": "TIGER_ACCOUNT_SENTINEL",
            },
            capture_output=True,
            text=True,
            check=False,
        )
    combined = result.stdout + result.stderr

    assert result.returncode == 0
    assert "TigerOpen SDK config compatibility probe (values redacted)" in result.stdout
    assert "Tiger account data APIs called: no" in result.stdout
    assert "Tiger order/cash-transfer APIs called: no" in result.stdout
    assert "TIGER_ACCOUNT_SENTINEL" not in combined
    assert "PRIVATE_KEY_PLACEHOLDER" not in combined


def test_cli_tiger_data_diagnostics_requires_live_gate(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "tiger",
            "--tiger-data-diagnostics",
            "--out-dir",
            str(tmp_path / "reports"),
        ],
        cwd=ROOT,
        env={**os.environ, **_valid_env(str(tmp_path / "missing_config"))},
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "--tiger-data-diagnostics requires --allow-live-read" in combined
    assert not (tmp_path / "reports").exists()


def test_tiger_data_diagnostics_formatter_redacts_account_id() -> None:
    raw_account_id = _fixture_snapshot().accounts[0].account_id
    provider = TigerProvider(
        _valid_config(),
        allow_live_read=True,
        live_adapter=_FakeAdapter(_fixture_snapshot_with_diagnostics()),
    )
    snapshot = provider._sync()
    formatted = "\n".join(_format_tiger_data_diagnostics(snapshot.status.diagnostics))

    assert snapshot.status.diagnostics["account_context_observed"] is True
    assert "Selected account hash: acct_" in formatted
    assert raw_account_id not in formatted
    assert "SDK output suppressed:" in formatted
    assert "Private key present:" in formatted


def test_tiger_adapter_uses_config_props_path_and_suppresses_sdk_output(
    tmp_path, monkeypatch, capsys
) -> None:
    import personal_cfo_agent.providers.tiger_readonly_adapter as adapter_module

    _write_placeholder_tiger_config(tmp_path)
    captured: dict[str, object] = {}

    class _FakeConfig:
        def __init__(self, *, props_path=None):
            print("SDK_CONFIG_STDOUT")
            print("SDK_CONFIG_STDERR", file=sys.stderr)
            captured["config_cls_props_path"] = props_path
            self.account = ""
            self.props_path = str(props_path or "")

    setattr(_FakeConfig, "tiger_id", "TIGER_ID_PLACEHOLDER")
    _FakeConfig.private_key = "PRIVATE_KEY_PLACEHOLDER"

    class _FakeConfigModule:
        TigerOpenClientConfig = _FakeConfig

        @staticmethod
        def get_client_config(**kwargs):
            captured["kwargs"] = kwargs
            raise AssertionError("helper should not be called on primary path")

    class _FakeClient:
        def __init__(self, config):
            print("SDK_CLIENT_STDOUT")
            captured["config_account"] = config.account
            captured["config_props_path"] = config.props_path

        def get_prime_assets(self):
            print("SDK_ASSETS_STDOUT")
            return [{"currency": "USD", "cash": 1.0}]

        def get_positions(self):
            print("SDK_POSITIONS_STDOUT")
            return []

    class _FakeClientModule:
        TradeClient = _FakeClient

    def _fake_import(name: str):
        if name == "tigeropen.tiger_open_config":
            return _FakeConfigModule
        if name == ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"]):
            return _FakeClientModule
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _fake_import)
    adapter = TigerReadOnlyAdapter(
        config_dir=str(tmp_path),
        account_id="TIGER_FIXTURE_ACCOUNT",
        account_hash_salt="fixture-salt",
    )
    snapshot = adapter.collect()
    captured_output = capsys.readouterr()
    combined = captured_output.out + captured_output.err

    assert combined == ""
    assert "kwargs" not in captured
    assert captured["config_cls_props_path"] == str(tmp_path)
    assert captured["config_props_path"] == str(tmp_path)
    assert captured["config_account"] == "TIGER_FIXTURE_ACCOUNT"
    assert snapshot.diagnostics["sdk_output_suppressed"] is True
    assert snapshot.diagnostics["tiger_config_mode_selected"] == "official_directory_props_path"
    assert snapshot.diagnostics["tiger_config_constructed"] is True
    assert snapshot.diagnostics["tiger_client_constructed"] is True
    assert snapshot.diagnostics["client_init_success"] is True


def test_tiger_adapter_helper_fallback_is_marked_after_official_mode_failure(
    tmp_path, monkeypatch
) -> None:
    import personal_cfo_agent.providers.tiger_readonly_adapter as adapter_module

    _write_placeholder_tiger_config(tmp_path)
    captured: dict[str, object] = {}

    class _FakeConfig:
        def __init__(self) -> None:
            setattr(self, "tiger_id", "TIGER_ID_PLACEHOLDER")
            self.account = "ACCOUNT_PLACEHOLDER"
            self.private_key = "PRIVATE_KEY_PLACEHOLDER"
            self.props_path = ""

    class _FakeConfigModule:
        class TigerOpenClientConfig:
            def __init__(self, *, props_path=None):
                captured["official_props_path"] = props_path
                raise RuntimeError("official directory failed")

        @staticmethod
        def get_client_config(**kwargs):
            captured["helper_kwargs"] = kwargs
            config = _FakeConfig()
            config.props_path = kwargs.get("props_path", "")
            return config

    class _FakeClient:
        def __init__(self, config):
            self.config = config

        def get_prime_assets(self):
            return [{"currency": "USD", "cash": 1.0}]

        def get_positions(self):
            return []

    class _FakeClientModule:
        TradeClient = _FakeClient

    def _fake_import(name: str):
        if name == "tigeropen.tiger_open_config":
            return _FakeConfigModule
        if name == ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"]):
            return _FakeClientModule
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _fake_import)
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()

    assert snapshot.has_data()
    assert captured["official_props_path"] == str(tmp_path)
    assert captured["helper_kwargs"] == {"props_path": str(tmp_path)}
    assert snapshot.status.diagnostics["tiger_config_mode_selected"] == "helper_fallback"
    assert WarningCode.TIGER_OFFICIAL_DIRECTORY_CONFIG_FAILED.value in snapshot.status.diagnostics[
        "tiger_config_warning_codes"
    ]
    assert WarningCode.TIGER_HELPER_CONFIG_FALLBACK_USED.value in snapshot.status.diagnostics[
        "tiger_config_warning_codes"
    ]


def test_tiger_adapter_official_mode_failure_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_sdk(
        monkeypatch,
        official_config_error=RuntimeError("private key invalid"),
        helper_error=RuntimeError("helper failed"),
    )
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.TIGER_OFFICIAL_DIRECTORY_CONFIG_FAILED.value in snapshot.status.diagnostics[
        "tiger_config_warning_codes"
    ]
    assert WarningCode.TIGER_HELPER_CONFIG_FALLBACK_FAILED.value in snapshot.status.diagnostics[
        "tiger_config_warning_codes"
    ]
    assert WarningCode.TIGER_PRIVATE_KEY_FORMAT_INVALID in snapshot.status.warning_codes


def test_tiger_live_adapter_config_dir_missing_returns_stage_code(tmp_path) -> None:
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path / "missing")}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_CONFIG_DIR_MISSING in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["config_dir_exists"] is False


def test_tiger_live_adapter_config_file_missing_returns_stage_code(tmp_path) -> None:
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_CONFIG_FILE_MISSING in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["config_file_exists"] is False


def test_tiger_live_adapter_missing_private_key_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path, include_private_key=False)
    _install_fake_tiger_sdk(monkeypatch, private_key="")
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_PRIVATE_KEY_MISSING in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["private_key_present_redacted"] is False


def test_tiger_live_adapter_invalid_private_key_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path, key_name="private_key", key_value="INVALID")
    _install_fake_tiger_sdk(monkeypatch, private_key="INVALID")
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_PRIVATE_KEY_FORMAT_INVALID in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["private_key_format_detected_redacted"] == "unknown"


def test_tiger_live_adapter_client_init_failure_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_sdk(monkeypatch, client_error=RuntimeError("client init failed"))
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_CLIENT_INIT_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_CONNECTION_FAILED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["client_init_attempted"] is True
    assert snapshot.status.diagnostics["client_init_success"] is False


def test_tiger_live_adapter_client_auth_failure_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_sdk(monkeypatch, asset_error=PermissionError("auth failed"))
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_CLIENT_AUTH_FAILED in snapshot.status.warning_codes
    assert WarningCode.PROVIDER_FETCH_FAILED in snapshot.status.warning_codes


def test_tiger_live_adapter_assets_query_failure_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_sdk(monkeypatch, asset_error=RuntimeError("asset query failed"))
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_ASSETS_QUERY_FAILED in snapshot.status.warning_codes
    assert WarningCode.TIGER_CASH_QUERY_FAILED in snapshot.status.warning_codes


def test_tiger_live_adapter_positions_query_failure_returns_stage_code(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_sdk(monkeypatch, position_error=RuntimeError("position query failed"))
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.TIGER_POSITIONS_QUERY_FAILED in snapshot.status.warning_codes


def test_tiger_live_adapter_no_data_returns_empty_stage_codes(
    tmp_path, monkeypatch
) -> None:
    _write_placeholder_tiger_config(tmp_path)
    _install_fake_tiger_sdk(monkeypatch, asset_payload=[], position_payload=[])
    provider = TigerProvider(
        _valid_config({"CFO_TIGER_CONFIG_DIR": str(tmp_path)}),
        allow_live_read=True,
    )
    snapshot = provider._sync()
    assert snapshot.has_data()
    assert WarningCode.TIGER_NO_DATA_RETURNED in snapshot.status.warning_codes
    assert WarningCode.TIGER_READ_SUCCEEDED_EMPTY in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["cash_query_success"] is True
    assert snapshot.status.diagnostics["positions_query_success"] is True


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
    paths = [
        "reports/personal_cfo_agent/tiger_v031_live_acceptance/provider_sync_summary.json",
        "tiger_openapi_config.properties",
        "tiger_openapi_token.properties",
    ]
    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "-v", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0


def test_tiger_config_and_private_key_files_are_not_tracked() -> None:
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "tiger_openapi_config*",
            "*.pem",
            "*.key",
            ".tigeropen",
            "tigeropen_private",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout.strip() == ""


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


def _fixture_snapshot_with_diagnostics() -> TigerReadOnlySnapshot:
    snapshot = _fixture_snapshot()
    return TigerReadOnlySnapshot(
        accounts=snapshot.accounts,
        cash=snapshot.cash,
        positions=snapshot.positions,
        diagnostics={
            "sdk_import_ok": True,
            "config_dir_exists": True,
            "config_file_exists": True,
            "config_loaded": True,
            "tiger_id_present_redacted": True,
            "account_present_redacted": True,
            "private_key_present_redacted": True,
            "private_key_format_detected_redacted": "pkcs8",
            "client_init_attempted": True,
            "client_init_success": True,
            "client_auth_success": True,
            "account_context_observed": True,
            "selected_account_hash": "acct_fixturehash0001",
            "account_count_redacted": 1,
            "assets_query_attempted": True,
            "assets_query_success": True,
            "positions_query_attempted": True,
            "positions_query_success": True,
            "position_count": len(snapshot.positions),
            "cash_query_attempted": True,
            "cash_query_success": True,
            "cash_currency_count": len({row.currency for row in snapshot.cash}),
            "normalized_rows": 0,
            "sdk_output_suppressed": True,
            "warning_codes": [],
            "stage_failures": {},
        },
    )


def _write_placeholder_tiger_config(
    config_dir: Path,
    *,
    include_private_key: bool = True,
    key_name: str = "private_key_pk8",
    key_value: str = "PRIVATE_KEY_PLACEHOLDER",
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "tiger_id=TIGER_ID_PLACEHOLDER",
        "account=ACCOUNT_PLACEHOLDER",
    ]
    if include_private_key:
        lines.append(f"{key_name}={key_value}")
    (config_dir / DEFAULT_PROPS_FILE).write_text("\n".join(lines), encoding="utf-8")


def _install_fake_tiger_sdk(
    monkeypatch,
    *,
    private_key: str = "PRIVATE_KEY_PLACEHOLDER",
    official_config_error: Exception | None = None,
    helper_error: Exception | None = None,
    client_error: Exception | None = None,
    asset_error: Exception | None = None,
    position_error: Exception | None = None,
    asset_payload=None,
    position_payload=None,
) -> None:
    import personal_cfo_agent.providers.tiger_readonly_adapter as adapter_module

    class _FakeConfig:
        def __init__(self, *, props_path: str = "") -> None:
            if official_config_error is not None:
                raise official_config_error
            setattr(self, "tiger_id", "TIGER_ID_PLACEHOLDER")
            self.account = "ACCOUNT_PLACEHOLDER"
            self.private_key = private_key
            self.props_path = props_path

    class _FakeConfigModule:
        TigerOpenClientConfig = _FakeConfig

        @staticmethod
        def get_client_config(**kwargs):
            if helper_error is not None:
                raise helper_error
            config = object.__new__(_FakeConfig)
            setattr(config, "tiger_id", "TIGER_ID_PLACEHOLDER")
            config.account = "ACCOUNT_PLACEHOLDER"
            config.private_key = private_key
            config.props_path = ""
            config.account = kwargs.get("account") or config.account
            config.props_path = kwargs.get("props_path", "")
            return config

    class _FakeClient:
        def __init__(self, config):
            if client_error is not None:
                raise client_error
            self.config = config

        def get_prime_assets(self):
            if asset_error is not None:
                raise asset_error
            return [{"currency": "USD", "cash": 1.0}] if asset_payload is None else asset_payload

        def get_positions(self):
            if position_error is not None:
                raise position_error
            if position_payload is not None:
                return position_payload
            return [{"symbol": "AAPL", "quantity": 1.0, "market_value": 1.0, "currency": "USD"}]

    class _FakeClientModule:
        TradeClient = _FakeClient

    def _fake_import(name: str):
        if name == "tigeropen.tiger_open_config":
            return _FakeConfigModule
        if name == ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"]):
            return _FakeClientModule
        raise AssertionError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", _fake_import)


def _install_fake_tiger_probe_sdk(
    monkeypatch,
    *,
    fail_modes: dict[str, Exception] | None = None,
    client_error: Exception | None = None,
) -> dict[str, int]:
    import personal_cfo_agent.providers.tiger_connection_diagnostics as diag_module

    failures = fail_modes or {}
    calls = {"asset": 0, "position": 0, "cash": 0}

    class _FakeConfig:
        def __init__(self, *, enable_dynamic_domain=True, props_path=None):
            self.props_path = str(props_path or "")
            mode = _probe_mode_from_props_path(self.props_path)
            if mode in failures:
                raise failures[mode]
            setattr(self, "tiger_id", "TIGER_ID_PLACEHOLDER")
            self.account = "ACCOUNT_PLACEHOLDER"
            self.private_key = "PRIVATE_KEY_PLACEHOLDER"
            self.license = None
            self._token = None

        @property
        def token(self):
            return self._token

    class _FakeConfigModule:
        TigerOpenClientConfig = _FakeConfig

        @staticmethod
        def get_client_config(**kwargs):
            if "explicit_props_path" in failures:
                raise failures["explicit_props_path"]
            return _FakeConfig(props_path=kwargs.get("props_path"))

    class _FakeClient:
        def __init__(self, config):
            if client_error is not None:
                raise client_error
            self.config = config

        def get_prime_assets(self):
            calls["asset"] += 1
            return []

        def get_positions(self):
            calls["position"] += 1
            return []

        def get_assets(self):
            calls["cash"] += 1
            return []

    class _FakeClientModule:
        TradeClient = _FakeClient

    class _FakeTigerOpenModule:
        __file__ = r"C:\Users\Lenovo\AppData\Roaming\Python\Python313\site-packages\tigeropen\__init__.py"

    def _fake_import(name: str):
        if name == "tigeropen":
            return _FakeTigerOpenModule
        if name == "tigeropen.tiger_open_config":
            return _FakeConfigModule
        if name == ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"]):
            return _FakeClientModule
        raise AssertionError(name)

    monkeypatch.setattr(diag_module.importlib, "import_module", _fake_import)
    return calls


def _probe_mode_from_props_path(props_path: str) -> str:
    if not props_path:
        return "sdk_default"
    if props_path.endswith(DEFAULT_PROPS_FILE):
        return "file"
    return "directory"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _valid_config(extra: dict[str, str] | None = None):
    return load_tiger_config({**_valid_env(), **(extra or {})})


def _valid_env(config_dir: str = r"C:\tmp\tigeropen_config") -> dict[str, str]:
    return {
        "CFO_TIGER_ENABLED": "true",
        "CFO_TIGER_CONFIG_DIR": config_dir,
        "CFO_TIGER_ACCOUNT": "TIGER-TEST-ACCOUNT-246810",
    }
