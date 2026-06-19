from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig, connector_status, load_usmart_config
from personal_cfo_agent.models import ConnectionMode, WarningCode
from personal_cfo_agent.providers.usmart_connection_diagnostics import (
    run_usmart_connection_diagnostics,
)
from personal_cfo_agent.providers.usmart_provider import USMARTProvider
from personal_cfo_agent.runner import run_readiness_check


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_USMART_MARKERS = (
    "place_order",
    "submit_order",
    "modify_order",
    "cancel_order",
    "preview_order",
    "transfer_cash",
    "withdraw_cash",
)


def test_usmart_provider_disabled_by_default() -> None:
    provider = USMARTProvider(load_usmart_config({}))
    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_DISABLED in snapshot.status.warning_codes
    assert snapshot.status.diagnostics["live_connection_attempted"] is False


def test_usmart_missing_config_fails_closed() -> None:
    provider = USMARTProvider(load_usmart_config({"CFO_USMART_ENABLED": "true"}))
    snapshot = provider._sync()

    assert not snapshot.has_data()
    assert WarningCode.PROVIDER_CONFIG_MISSING in snapshot.status.warning_codes


def test_usmart_sdk_missing_is_reported_after_config_present() -> None:
    diagnostics = run_usmart_connection_diagnostics(
        _enabled_env(),
        import_module=lambda name: (_raise_import_error(name)),
    )

    assert diagnostics.sdk_import_ok is False
    assert diagnostics.warning_codes == (WarningCode.SDK_NOT_INSTALLED,)
    assert diagnostics.live_connection_attempted is False


def test_usmart_sdk_import_exception_fails_closed_without_leaking_error_text() -> None:
    diagnostics = run_usmart_connection_diagnostics(
        _enabled_env({"CFO_USMART_SDK_MODULE": "broken_usmart_sdk"}),
        import_module=lambda name: (_raise_runtime_error(name)),
    )

    assert diagnostics.sdk_import_ok is False
    assert diagnostics.sdk_module_detected == "unavailable"
    assert diagnostics.warning_codes == (WarningCode.SDK_NOT_INSTALLED,)


def test_usmart_readiness_success_with_mocked_sdk_and_config() -> None:
    diagnostics = run_usmart_connection_diagnostics(
        _enabled_env({"CFO_USMART_SDK_MODULE": "mock_usmart_sdk"}),
        import_module=lambda name: object(),
    )

    assert diagnostics.sdk_import_ok is True
    assert diagnostics.sdk_module_detected == "mock_usmart_sdk"
    assert diagnostics.warning_codes == (WarningCode.USMART_READINESS_OK,)
    assert diagnostics.live_connection_attempted is False


def test_usmart_provider_readiness_uses_redacted_diagnostics(monkeypatch) -> None:
    import personal_cfo_agent.providers.usmart_connection_diagnostics as diag_module

    monkeypatch.setattr(diag_module.importlib, "import_module", lambda name: object())
    provider = USMARTProvider(load_usmart_config(_enabled_env()))
    warnings = provider.readiness_check()

    assert warnings == [WarningCode.USMART_READINESS_OK]
    assert provider._status().connection_mode == ConnectionMode.LIVE_READINESS
    output = str(provider._status().to_dict())
    assert "API_KEY_SENTINEL" not in output
    assert "API_SECRET_SENTINEL" not in output
    assert "api_key_present_redacted" in output


def test_usmart_readiness_cli_exists_and_redacts_config_values() -> None:
    env = {
        **os.environ,
        **_enabled_env({"CFO_USMART_SDK_MODULE": "os"}),
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "usmart",
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
    assert "usmart: live_readiness_check_only" in result.stdout
    assert "USMART_READINESS_OK" in result.stdout
    assert "API_KEY_SENTINEL" not in combined
    assert "API_SECRET_SENTINEL" not in combined


def test_usmart_connection_diagnostics_cli_does_not_call_network_or_print_secrets() -> None:
    env = {
        **os.environ,
        **_enabled_env({"CFO_USMART_SDK_MODULE": "os"}),
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--provider",
            "usmart",
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
    assert "uSMART readiness diagnostics (values redacted)" in result.stdout
    assert "Live connection attempted: no" in result.stdout
    assert "API_KEY_SENTINEL" not in combined
    assert "API_SECRET_SENTINEL" not in combined


def test_usmart_connector_status_is_feasibility_only() -> None:
    status = connector_status("usmart")

    assert status["status"] == "readiness_feasibility_only"
    assert status["asset_read"] is False
    assert status["position_read"] is False
    assert status["cash_read"] is False


def test_usmart_source_has_no_write_api_markers() -> None:
    usmart_files = sorted((ROOT / "src" / "personal_cfo_agent" / "providers").glob("usmart_*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in usmart_files)
    for marker in FORBIDDEN_USMART_MARKERS:
        assert re.search(rf"\b{re.escape(marker)}\b", source) is None


def test_usmart_config_example_is_placeholder_only() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "CFO_USMART_ENABLED=false" in text
    assert "CFO_USMART_API_KEY=\n" in text
    assert "CFO_USMART_API_SECRET=\n" in text
    assert "API_KEY_SENTINEL" not in text


def test_usmart_readiness_does_not_affect_existing_providers() -> None:
    result = run_readiness_check(RuntimeConfig(provider="usmart", env=_enabled_env()))

    assert len(result.statuses) == 1
    assert result.statuses[0].provider_name == "usmart"


def _enabled_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "CFO_USMART_ENABLED": "true",
        "CFO_USMART_API_KEY": "API_KEY_SENTINEL",
        "CFO_USMART_API_SECRET": "API_SECRET_SENTINEL",
        "CFO_USMART_API_HOST": "api.example.invalid",
    }
    if extra:
        env.update(extra)
    return env


def _raise_import_error(name: str) -> None:
    raise ImportError(name)


def _raise_runtime_error(name: str) -> None:
    raise RuntimeError(f"simulated import failure for {name}")
