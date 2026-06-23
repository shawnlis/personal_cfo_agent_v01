from __future__ import annotations

import json
from pathlib import Path

from personal_cfo_agent.local_workbench import write_local_workbench
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.runner import build_arg_parser, main
from personal_cfo_agent.snapshot_review import write_snapshot_review


PRIVATE_VALUE_MARKER = "9876543.21"
ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_review_cli_option_exists() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--snapshot-review" in option_strings
    assert "--local-workbench" in option_strings


def test_snapshot_review_generates_redacted_confirmation_gate(
    tmp_path: Path,
) -> None:
    refresh_dir = _write_refresh_review_inputs(tmp_path, ready=True)

    result = write_snapshot_review(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "snapshot_review",
    )

    assert result.generated is True
    assert result.ready_to_confirm is True
    assert WarningCode.SNAPSHOT_REVIEW_READY_TO_CONFIRM in result.warning_codes
    assert (result.output_dir / "snapshot_review_summary.json").exists()
    assert (result.output_dir / "SNAPSHOT_REVIEW_V066.md").exists()
    assert (result.output_dir / "snapshot_review.html").exists()
    for path in result.output_paths.values():
        text = path.read_text(encoding="utf-8")
        assert PRIVATE_VALUE_MARKER not in text
        assert "ready_to_confirm" in text or "Ready to confirm" in text


def test_snapshot_review_blocks_when_integrity_not_ready(tmp_path: Path) -> None:
    refresh_dir = _write_refresh_review_inputs(tmp_path, ready=False)

    result = write_snapshot_review(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "snapshot_review_blocked",
    )
    summary = json.loads(result.output_paths["summary"].read_text(encoding="utf-8"))

    assert result.generated is True
    assert result.ready_to_confirm is False
    assert WarningCode.SNAPSHOT_REVIEW_BLOCKED in result.warning_codes
    assert summary["confirmed_history_write_allowed"] is False
    assert WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING.value in summary["warning_codes"]


def test_snapshot_review_cli_is_offline_and_redacted(tmp_path: Path, capsys) -> None:
    refresh_dir = _write_refresh_review_inputs(tmp_path, ready=True)
    out_dir = tmp_path / "snapshot_review_cli"

    exit_code = main(
        [
            "--snapshot-review",
            "--refresh-dir",
            str(refresh_dir),
            "--out-dir",
            str(out_dir),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "External connections used: no" in captured
    assert "Broker live reads used: no" in captured
    assert "Ready to confirm history: yes" in captured
    assert PRIVATE_VALUE_MARKER not in captured
    assert (out_dir / "snapshot_review.html").exists()


def test_local_workbench_generates_static_redacted_launcher(tmp_path: Path) -> None:
    input_file = tmp_path / "personal_cfo_input.local.json"
    input_file.write_text("{}", encoding="utf-8")
    refresh_dir = _write_refresh_review_inputs(tmp_path, ready=True)
    fx_file = tmp_path / "fx_rates.local.json"
    fx_file.write_text("{}", encoding="utf-8")
    dashboard_dir = tmp_path / "dashboard_current"
    dashboard_dir.mkdir()
    (dashboard_dir / "PERSONAL_CFO_DASHBOARD_V060.html").write_text(
        "<!doctype html><title>Dashboard</title>",
        encoding="utf-8",
    )

    result = write_local_workbench(
        out_dir=tmp_path / "workbench",
        input_file=input_file,
        refresh_dir=refresh_dir,
        fx_rates_file=fx_file,
        dashboard_dir=dashboard_dir,
    )

    html = result.output_paths["html"].read_text(encoding="utf-8").lower()
    assert result.generated is True
    assert WarningCode.LOCAL_WORKBENCH_GENERATED_OK in result.warning_codes
    assert "open current dashboard v4" in html
    assert "open snapshot review" in html
    assert "fetch(" not in html
    assert "xmlhttprequest" not in html
    assert "sendbeacon" not in html
    assert "https://" not in html
    assert PRIVATE_VALUE_MARKER not in html


def test_local_workbench_cli_is_offline_and_reports_missing_paths(
    tmp_path: Path, capsys
) -> None:
    out_dir = tmp_path / "workbench_cli"

    exit_code = main(
        [
            "--local-workbench",
            "--input-file",
            str(tmp_path / "missing_input.json"),
            "--refresh-dir",
            str(tmp_path / "missing_refresh"),
            "--fx-rates-file",
            str(tmp_path / "missing_fx.json"),
            "--out-dir",
            str(out_dir),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO local workbench v0.6.6" in captured
    assert "External connections used: no" in captured
    assert "Broker live reads used: no" in captured
    assert "LOCAL_WORKBENCH_INPUT_MISSING" in captured
    assert PRIVATE_VALUE_MARKER not in captured
    assert (out_dir / "LOCAL_WORKBENCH_V066.html").exists()


def test_local_workflow_stabilization_doc_covers_delivery_standards() -> None:
    text = (ROOT / "docs" / "LOCAL_WORKFLOW_STABILIZATION_V066.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "Unified private input center remains the only user-facing manual input form",
        "--local-workbench",
        "--refresh-brokers none",
        "Provider gate is visible",
        "Source provenance is visible",
        "--snapshot-review",
        "Integrity guard remains the write gate",
        "dashboard_current",
        "Warning codes are human-readable",
        "Safety boundaries are machine-tested",
    ):
        assert phrase in text
    assert "broker live reads" in text
    assert "exact NAV" in text


def _write_refresh_review_inputs(tmp_path: Path, *, ready: bool) -> Path:
    refresh_dir = tmp_path / "refresh"
    integrity_dir = refresh_dir / "integrity_guard"
    dashboard_dir = refresh_dir / "dashboard"
    integrity_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    blocking_codes = [] if ready else [WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING.value]
    (integrity_dir / "net_worth_integrity_summary.json").write_text(
        json.dumps(
            {
                "ready_to_confirm": ready,
                "blocking_warning_codes": blocking_codes,
                "provider_checks": {
                    "ibkr": {
                        "status": "ok" if ready else "missing",
                        "account_nav_rows": 1 if ready else 0,
                        "provider_reported_nav_rows": 1 if ready else 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (refresh_dir / "data_quality_summary.json").write_text(
        json.dumps(
            {
                "providers": {
                    "requested": ["ibkr"],
                    "succeeded": ["ibkr"] if ready else [],
                    "failed": [] if ready else ["ibkr"],
                },
                "counts": {"account_nav_row_count": 1 if ready else 0, "position_row_count": 0},
                "fx": {"complete": True},
                "warning_codes": [] if ready else [WarningCode.DATA_QUALITY_BROKER_FAILURES.value],
            }
        ),
        encoding="utf-8",
    )
    (dashboard_dir / "dashboard_v050_summary.json").write_text("{}", encoding="utf-8")
    (refresh_dir / "snapshot_review").mkdir()
    (refresh_dir / "snapshot_review" / "snapshot_review.html").write_text(
        "<!doctype html><title>Snapshot Review</title>",
        encoding="utf-8",
    )
    return refresh_dir
