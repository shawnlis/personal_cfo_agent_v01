from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.net_worth_doctor import run_net_worth_doctor
from personal_cfo_agent.runner import build_arg_parser, main


ROOT = Path(__file__).resolve().parents[1]
INPUT_TEMPLATE = ROOT / "templates" / "private_inputs" / "personal_cfo_input.example.json"
PRIVATE_VALUE_MARKER = "9876543.21"


def test_net_worth_doctor_cli_option_exists() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--net-worth-doctor" in option_strings
    assert "--refresh-dir" in option_strings
    assert "--fx-rates-file" in option_strings


def test_net_worth_doctor_missing_input_fails_closed(tmp_path: Path) -> None:
    result = run_net_worth_doctor(
        input_file=tmp_path / "missing.json",
        refresh_dir=tmp_path / "missing_refresh",
        fx_rates_file=None,
        out_dir=tmp_path / "doctor",
        env={},
    )

    assert result.generated is True
    assert result.input_valid is False
    assert WarningCode.NET_WORTH_DOCTOR_INPUT_MISSING in result.warning_codes
    assert WarningCode.NET_WORTH_DOCTOR_REFRESH_MISSING in result.warning_codes
    assert WarningCode.NET_WORTH_DOCTOR_FX_MISSING in result.warning_codes


def test_net_worth_doctor_invalid_input_fails_closed(tmp_path: Path) -> None:
    input_file = tmp_path / "invalid.json"
    input_file.write_text("{not-json", encoding="utf-8")

    result = run_net_worth_doctor(
        input_file=input_file,
        refresh_dir=_write_refresh_dir(tmp_path),
        fx_rates_file=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "doctor",
        env={},
    )

    assert result.input_valid is False
    assert WarningCode.NET_WORTH_DOCTOR_INPUT_INVALID in result.warning_codes


def test_net_worth_doctor_generates_redacted_summary(tmp_path: Path) -> None:
    input_file = _write_private_input(tmp_path, private_marker=True)
    refresh_dir = _write_refresh_dir(tmp_path)
    fx_file = _write_fx_rates(tmp_path)

    result = run_net_worth_doctor(
        input_file=input_file,
        refresh_dir=refresh_dir,
        fx_rates_file=fx_file,
        out_dir=tmp_path / "doctor",
        env={
            "CFO_IBKR_ENABLED": "true",
            "CFO_IBKR_HOST": "127.0.0.1",
            "CFO_IBKR_PORT": "7497",
            "CFO_IBKR_CLIENT_ID": "101",
            "CFO_MOOMOO_ENABLED": "true",
            "CFO_MOOMOO_HOST": "127.0.0.1",
        },
    )

    summary_text = result.output_paths["summary"].read_text(encoding="utf-8")
    report_text = result.output_paths["report"].read_text(encoding="utf-8")
    summary = json.loads(summary_text)

    assert result.generated is True
    assert result.input_valid is True
    assert result.refresh_complete is True
    assert result.fx_complete is True
    assert summary["external_connections_used"] is False
    assert summary["broker_live_reads_used"] is False
    assert summary["input"]["manual_nav_account_count"] == 3
    assert summary["broker_config_presence"]["ibkr"]["enabled"] is True
    assert summary["broker_config_presence"]["ibkr"]["required_config_present"] is True
    assert summary["broker_config_presence"]["moomoo"]["enabled"] is True
    assert summary["broker_config_presence"]["moomoo"]["required_config_present"] is False
    assert WarningCode.NET_WORTH_DOCTOR_BROKER_CONFIG_MISSING in result.warning_codes
    assert PRIVATE_VALUE_MARKER not in summary_text
    assert PRIVATE_VALUE_MARKER not in report_text


def test_net_worth_doctor_incomplete_fx_warns(tmp_path: Path) -> None:
    input_file = _write_private_input(tmp_path)
    refresh_dir = _write_refresh_dir(tmp_path)
    fx_file = tmp_path / "fx.json"
    fx_file.write_text(
        json.dumps({"base_currency": "SGD", "rates_to_base": {"SGD": "1.0"}}),
        encoding="utf-8",
    )

    result = run_net_worth_doctor(
        input_file=input_file,
        refresh_dir=refresh_dir,
        fx_rates_file=fx_file,
        out_dir=tmp_path / "doctor",
        env={},
    )

    summary = json.loads(result.output_paths["summary"].read_text(encoding="utf-8"))
    assert result.fx_complete is False
    assert WarningCode.NET_WORTH_DOCTOR_FX_INCOMPLETE in result.warning_codes
    assert "USD" in summary["fx"]["missing_currencies"]
    assert "CNY" in summary["fx"]["missing_currencies"]


def test_net_worth_doctor_cli_redacts_and_uses_no_live_reads(tmp_path: Path) -> None:
    input_file = _write_private_input(tmp_path, private_marker=True)
    out_dir = tmp_path / "doctor_cli"
    env = {**os.environ, "CFO_IBKR_ENABLED": "true"}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--net-worth-doctor",
            "--input-file",
            str(input_file),
            "--refresh-dir",
            str(_write_refresh_dir(tmp_path)),
            "--fx-rates-file",
            str(_write_fx_rates(tmp_path)),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Personal CFO local net worth doctor v0.6.2" in output
    assert "External connections used: no" in output
    assert "Broker live reads used: no" in output
    assert PRIVATE_VALUE_MARKER not in output
    assert "token" not in output.lower()
    assert (out_dir / "net_worth_doctor_summary.json").exists()
    assert (out_dir / "net_worth_doctor_warnings.md").exists()
    assert (out_dir / "NET_WORTH_DOCTOR_V062.md").exists()


def test_net_worth_doctor_cannot_combine_with_live_read(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--net-worth-doctor",
                "--allow-live-read",
                "--input-file",
                str(tmp_path / "input.json"),
                "--refresh-dir",
                str(tmp_path / "refresh"),
                "--out-dir",
                str(tmp_path / "doctor"),
            ]
        )


def _write_private_input(tmp_path: Path, *, private_marker: bool = False) -> Path:
    payload = json.loads(INPUT_TEMPLATE.read_text(encoding="utf-8"))
    if private_marker:
        payload["manual_nav_accounts"][0]["account_nav"] = PRIVATE_VALUE_MARKER
    path = tmp_path / "personal_cfo_input.local.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_refresh_dir(tmp_path: Path) -> Path:
    refresh_dir = tmp_path / "refresh"
    merged = refresh_dir / "merged"
    snapshots = refresh_dir / "snapshots"
    dashboard = refresh_dir / "dashboard"
    property_dir = refresh_dir / "manual_layers" / "property_mortgage"
    sg_dir = refresh_dir / "manual_layers" / "sg_retirement_tax"
    for directory in (merged, snapshots, dashboard, property_dir, sg_dir):
        directory.mkdir(parents=True, exist_ok=True)
    _write_csv(
        merged / "merged_account_nav_ledger.csv",
        ["provider", "account_id_hash", "account_nav", "base_currency"],
        [
            {
                "provider": "synthetic",
                "account_id_hash": "acct_synthetic",
                "account_nav": "1000.00",
                "base_currency": "USD",
            }
        ],
    )
    _write_csv(
        snapshots / "net_worth_history.csv",
        ["snapshot_date", "snapshot_id", "total_net_worth", "currency"],
        [
            {
                "snapshot_date": "2026-01-01",
                "snapshot_id": "snap_synthetic",
                "total_net_worth": "1000.00",
                "currency": "SGD",
            }
        ],
    )
    _write_csv(
        dashboard / "net_worth_progress.csv",
        ["snapshot_date", "total_net_worth", "currency"],
        [{"snapshot_date": "2026-01-01", "total_net_worth": "1000.00", "currency": "SGD"}],
    )
    (property_dir / "property_equity_summary.json").write_text(
        json.dumps({"total_equity_by_currency": {"SGD": "0.00"}}),
        encoding="utf-8",
    )
    _write_csv(
        sg_dir / "cpf_snapshot_ledger.csv",
        ["snapshot_date", "total", "currency"],
        [{"snapshot_date": "2026-01-01", "total": "0.00", "currency": "SGD"}],
    )
    _write_csv(
        sg_dir / "srs_snapshot_ledger.csv",
        ["snapshot_date", "total", "currency"],
        [{"snapshot_date": "2026-01-01", "total": "0.00", "currency": "SGD"}],
    )
    return refresh_dir


def _write_fx_rates(tmp_path: Path) -> Path:
    path = tmp_path / "fx_rates.json"
    path.write_text(
        json.dumps(
            {
                "base_currency": "SGD",
                "rates_to_base": {
                    "SGD": "1.0",
                    "USD": "1.3",
                    "CNY": "0.18",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
