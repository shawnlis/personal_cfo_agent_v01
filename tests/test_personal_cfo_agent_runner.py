from __future__ import annotations

from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig
from personal_cfo_agent.models import ConnectionMode, WarningCode
from personal_cfo_agent.runner import collect_provider_snapshots, run


FIXTURE = Path("tests/fixtures/manual_snapshot_sample.json")
FULL_ACCOUNT_IDS = [
    "TEST-BROKER-ACCOUNT-123456789",
    "TEST-PROPERTY-ACCOUNT-987654321",
    "TEST-MORTGAGE-ACCOUNT-555555555",
]


def test_default_runner_does_not_generate_reports_or_live_reads(tmp_path) -> None:
    result = run(RuntimeConfig(output_root=tmp_path, env={}))
    assert result.exit_code == 0
    assert result.output_dir is None
    assert result.output_paths == {}
    assert result.normalized_assets == []
    assert not any(tmp_path.iterdir())


def test_live_read_requires_explicit_flag() -> None:
    env = {
        "CFO_IBKR_ENABLED": "1",
        "CFO_IBKR_HOST": "127.0.0.1",
        "CFO_IBKR_PORT": "7497",
        "CFO_IBKR_CLIENT_ID": "7",
        "CFO_IBKR_ACCOUNT": "DU_TEST",
    }
    snapshots = collect_provider_snapshots(
        RuntimeConfig(env=env, allow_live_read=False, provider="ibkr")
    )
    ibkr_status = snapshots[0].status
    assert WarningCode.LIVE_READ_NOT_ALLOWED in ibkr_status.warning_codes
    assert ibkr_status.connection_mode == ConnectionMode.API_STUB

    ungated_snapshots = collect_provider_snapshots(
        RuntimeConfig(env=env, allow_live_read=True, provider="all")
    )
    ungated_status = ungated_snapshots[0].status
    assert ungated_status.connection_mode == ConnectionMode.API_STUB
    assert WarningCode.LIVE_READ_NOT_ALLOWED in ungated_status.warning_codes


def test_missing_provider_config_fails_closed() -> None:
    snapshots = collect_provider_snapshots(
        RuntimeConfig(env={"CFO_IBKR_ENABLED": "1"}, allow_live_read=True, provider="ibkr")
    )
    ibkr_status = snapshots[0].status
    assert WarningCode.PROVIDER_CONFIG_MISSING in ibkr_status.warning_codes
    assert not snapshots[0].has_data()


def test_manual_fixture_runner_writes_required_output_bundle(tmp_path) -> None:
    result = run(
        RuntimeConfig(
            manual_snapshot_path=FIXTURE,
            output_root=tmp_path,
            as_of_date="20260614",
            env={},
        )
    )
    assert result.exit_code == 0
    assert result.output_dir == tmp_path / "20260614"
    assert set(result.output_paths) == {
        "markdown_report",
        "provider_sync_summary",
        "normalized_asset_ledger",
        "net_worth_summary",
        "liquidity_summary",
        "currency_exposure",
        "provider_warning_summary",
        "warnings_report",
    }
    for path in result.output_paths.values():
        assert path.exists()

    report_text = result.output_paths["markdown_report"].read_text(encoding="utf-8")
    assert (
        "“This is a personal finance aggregation and risk dashboard, not investment, "
        "tax, estate, insurance, or trading advice.”"
    ) in report_text
    combined_output = "\n".join(
        path.read_text(encoding="utf-8") for path in result.output_paths.values()
    )
    for account_id in FULL_ACCOUNT_IDS:
        assert account_id not in combined_output


def test_out_dir_writes_v010_contract_files(tmp_path) -> None:
    out_dir = tmp_path / "v010_final_smoke"
    result = run(
        RuntimeConfig(
            manual_snapshot_path=FIXTURE,
            output_dir=out_dir,
            as_of_date="20260614",
            env={},
        )
    )

    assert result.output_dir == out_dir
    assert (out_dir / "PERSONAL_CFO_AGENT_V010.md").exists()
    assert (out_dir / "provider_sync_summary.json").exists()
    assert (out_dir / "normalized_asset_ledger.csv").exists()
    assert (out_dir / "net_worth_summary.csv").exists()
    assert (out_dir / "liquidity_summary.csv").exists()
    assert (out_dir / "currency_exposure.csv").exists()
    assert (out_dir / "provider_warning_summary.csv").exists()
    assert (out_dir / "personal_cfo_warnings.md").exists()
