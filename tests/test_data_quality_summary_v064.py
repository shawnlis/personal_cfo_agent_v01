from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.runner import _run_net_worth_refresh, build_arg_parser


ROOT = Path(__file__).resolve().parents[1]
INPUT_TEMPLATE = ROOT / "templates" / "private_inputs" / "personal_cfo_input.example.json"
PRIVATE_VALUE_MARKER = "9876543.21"


def test_net_worth_refresh_confirm_snapshot_history_cli_option_exists() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--confirm-snapshot-history-write" in option_strings


def test_net_worth_refresh_writes_data_quality_outputs(tmp_path: Path) -> None:
    input_file = _write_private_input(tmp_path)
    result = _run_net_worth_refresh(
        input_file=input_file,
        out_dir=tmp_path / "refresh",
        brokers=[],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=_write_fx_rates(tmp_path),
        env=_synthetic_env(),
        allow_live_read=False,
    )

    assert result.generated is True
    assert result.data_quality_result is not None
    assert result.data_quality_result.generated is True
    summary_path = result.data_quality_result.output_paths["summary"]
    warnings_path = result.data_quality_result.output_paths["warnings"]
    report_path = result.data_quality_result.output_paths["report"]
    assert summary_path.name == "data_quality_summary.json"
    assert warnings_path.name == "data_quality_warnings.md"
    assert report_path.name == "DATA_QUALITY_SUMMARY_V064.md"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["providers"]["requested"] == []
    assert summary["providers"]["succeeded"] == []
    assert summary["providers"]["failed"] == []
    assert summary["manual_layers"]["manual_input_converted"] is True
    assert summary["counts"]["account_nav_row_count"] == 3
    assert summary["counts"]["position_row_count"] == 0
    assert summary["snapshot"]["generated"] is True
    assert summary["dashboard"]["generated"] is True
    assert summary["integrity_guard"]["generated"] is True
    assert summary["integrity_guard"]["ready_to_confirm"] is True
    assert summary["integrity_guard"]["blocking_warning_codes"] == []
    assert summary["fx"]["file_present"] is True
    assert summary["fx"]["complete"] is True
    assert WarningCode.DATA_QUALITY_FX_INCOMPLETE.value not in summary["warning_codes"]
    assert result.snapshot_history_confirmed is False
    assert WarningCode.NET_WORTH_REFRESH_SNAPSHOT_PENDING_REVIEW in result.warning_codes
    assert (result.output_dir / "snapshots" / "net_worth_history.csv").exists()
    assert not (result.output_dir / "snapshots_confirmed" / "net_worth_history.csv").exists()


def test_net_worth_refresh_confirmed_snapshot_history_write(tmp_path: Path) -> None:
    result = _run_net_worth_refresh(
        input_file=_write_private_input(tmp_path),
        out_dir=tmp_path / "refresh_confirmed",
        brokers=[],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=_write_fx_rates(tmp_path),
        env=_synthetic_env(),
        allow_live_read=False,
        confirm_snapshot_history_write=True,
    )

    assert result.generated is True
    assert result.snapshot_history_confirmed is True
    assert result.integrity_guard_result is not None
    assert result.integrity_guard_result.ready_to_confirm is True
    assert WarningCode.NET_WORTH_REFRESH_SNAPSHOT_HISTORY_CONFIRMED in result.warning_codes
    assert WarningCode.NET_WORTH_REFRESH_SNAPSHOT_PENDING_REVIEW not in result.warning_codes
    assert (result.output_dir / "snapshots" / "net_worth_history.csv").exists()
    assert (result.output_dir / "snapshots_confirmed" / "net_worth_history.csv").exists()


def test_net_worth_refresh_confirmed_write_blocks_failed_broker_refresh(
    tmp_path: Path,
) -> None:
    result = _run_net_worth_refresh(
        input_file=_write_private_input(tmp_path),
        out_dir=tmp_path / "refresh_confirm_blocked",
        brokers=["ibkr"],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=_write_fx_rates(tmp_path),
        env=_synthetic_env(),
        allow_live_read=False,
        confirm_snapshot_history_write=True,
    )

    assert result.generated is True
    assert result.snapshot_history_confirmed is False
    assert result.integrity_guard_result is not None
    assert result.integrity_guard_result.ready_to_confirm is False
    assert WarningCode.INTEGRITY_GUARD_BLOCKED in result.warning_codes
    assert WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING in result.warning_codes
    assert WarningCode.NET_WORTH_REFRESH_SNAPSHOT_PENDING_REVIEW in result.warning_codes
    assert not (result.output_dir / "snapshots_confirmed" / "net_worth_history.csv").exists()
    summary = json.loads(
        result.data_quality_result.output_paths["summary"].read_text(encoding="utf-8")
    )
    assert summary["integrity_guard"]["generated"] is True
    assert summary["integrity_guard"]["ready_to_confirm"] is False
    assert (
        WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING.value
        in summary["integrity_guard"]["blocking_warning_codes"]
    )


def test_data_quality_written_when_missing_fx_blocks_refresh(tmp_path: Path) -> None:
    result = _run_net_worth_refresh(
        input_file=_write_private_input(tmp_path),
        out_dir=tmp_path / "refresh_missing_fx",
        brokers=[],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=None,
        env=_synthetic_env(),
        allow_live_read=False,
    )

    assert result.data_quality_result is not None
    summary = json.loads(
        result.data_quality_result.output_paths["summary"].read_text(encoding="utf-8")
    )
    assert summary["snapshot"]["generated"] == bool(
        result.snapshot_result and result.snapshot_result.generated
    )
    assert summary["dashboard"]["generated"] == bool(
        result.dashboard_result and result.dashboard_result.generated
    )
    assert summary["fx"]["file_present"] is False
    assert summary["fx"]["complete"] is False
    assert WarningCode.DATA_QUALITY_FX_INCOMPLETE.value in summary["warning_codes"]


def test_data_quality_marks_explicit_fx_complete(tmp_path: Path) -> None:
    result = _run_net_worth_refresh(
        input_file=_write_private_input(tmp_path),
        out_dir=tmp_path / "refresh_fx",
        brokers=[],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=_write_fx_rates(tmp_path),
        env=_synthetic_env(),
        allow_live_read=False,
    )

    assert result.data_quality_result is not None
    summary = json.loads(
        result.data_quality_result.output_paths["summary"].read_text(encoding="utf-8")
    )
    assert summary["fx"]["file_present"] is True
    assert summary["fx"]["complete"] is True
    assert WarningCode.DATA_QUALITY_FX_INCOMPLETE.value not in summary["warning_codes"]


def test_data_quality_surfaces_broker_failure_without_live_read(tmp_path: Path) -> None:
    result = _run_net_worth_refresh(
        input_file=_write_private_input(tmp_path),
        out_dir=tmp_path / "refresh_broker_failure",
        brokers=["ibkr"],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=_write_fx_rates(tmp_path),
        env=_synthetic_env(),
        allow_live_read=False,
    )

    assert result.data_quality_result is not None
    summary = json.loads(
        result.data_quality_result.output_paths["summary"].read_text(encoding="utf-8")
    )
    assert summary["providers"]["requested"] == ["ibkr"]
    assert summary["providers"]["succeeded"] == []
    assert summary["providers"]["failed"] == ["ibkr"]
    assert WarningCode.DATA_QUALITY_BROKER_FAILURES.value in summary["warning_codes"]


def test_data_quality_outputs_do_not_include_private_values(tmp_path: Path) -> None:
    result = _run_net_worth_refresh(
        input_file=_write_private_input(tmp_path, private_marker=True),
        out_dir=tmp_path / "refresh_redaction",
        brokers=[],
        dashboard_dir=None,
        snapshot_id=None,
        fx_rates_input=_write_fx_rates(tmp_path),
        env=_synthetic_env(),
        allow_live_read=False,
    )

    assert result.data_quality_result is not None
    for path in result.data_quality_result.output_paths.values():
        assert PRIVATE_VALUE_MARKER not in path.read_text(encoding="utf-8")


def test_net_worth_refresh_cli_summary_stays_redacted(tmp_path: Path) -> None:
    input_file = _write_private_input(tmp_path, private_marker=True)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--run-net-worth-refresh",
            "--refresh-brokers",
            "none",
            "--input-file",
            str(input_file),
            "--out-dir",
            str(tmp_path / "refresh_cli"),
        ],
        cwd=ROOT,
        env={**os.environ, **_synthetic_env(), "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python"},
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Data quality files:" in output
    assert "data_quality_summary.json" in output
    assert PRIVATE_VALUE_MARKER not in output


def test_data_quality_reports_remain_under_ignored_reports_boundary() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "reports/" in gitignore


def _write_private_input(tmp_path: Path, *, private_marker: bool = False) -> Path:
    payload = json.loads(INPUT_TEMPLATE.read_text(encoding="utf-8"))
    _refresh_fixture_dates(payload)
    if private_marker:
        payload["manual_nav_accounts"][0]["account_nav"] = PRIVATE_VALUE_MARKER
    path = tmp_path / "personal_cfo_input.local.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _refresh_fixture_dates(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in list(payload.items()):
            if key in {
                "snapshot_date",
                "as_of_date",
                "valuation_date",
                "source_date",
                "repricing_date",
                "maturity_date",
            }:
                payload[key] = "2026-06-21"
            else:
                _refresh_fixture_dates(value)
    elif isinstance(payload, list):
        for item in payload:
            _refresh_fixture_dates(item)


def _synthetic_env() -> dict[str, str]:
    return {"CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"}


def _write_fx_rates(tmp_path: Path) -> Path:
    path = tmp_path / "fx_rates.json"
    path.write_text(
        json.dumps(
            {
                "base_currency": "SGD",
                "rates_to_base": {
                    "SGD": "1.0",
                    "USD": "1.3",
                    "HKD": "0.17",
                    "CNY": "0.18",
                },
            }
        ),
        encoding="utf-8",
    )
    return path
