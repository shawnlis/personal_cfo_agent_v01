from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from personal_cfo_agent.dashboard_v3 import write_dashboard_v3
from personal_cfo_agent.dashboard_v4 import (
    ASSET_BUCKET_FIELDNAMES,
    BUCKET_HISTORY_FIELDNAMES,
    LIQUID_WITHDRAWAL_FIELDNAMES,
    write_dashboard_v4,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import merge_provider_bundles
from personal_cfo_agent.runner import build_arg_parser, main


ROOT = Path(__file__).resolve().parents[1]
PROPERTY_FIXTURE = ROOT / "tests" / "fixtures" / "property_mortgage" / "property_v043.json"
MORTGAGE_FIXTURE = ROOT / "tests" / "fixtures" / "property_mortgage" / "mortgage_v043.json"
CPF_FIXTURE = ROOT / "tests" / "fixtures" / "sg_manual_snapshot" / "cpf_v044.json"
SRS_FIXTURE = ROOT / "tests" / "fixtures" / "sg_manual_snapshot" / "srs_v044.json"
TAX_FIXTURE = ROOT / "tests" / "fixtures" / "sg_manual_snapshot" / "tax_v044.json"
HDB_LOAN_FIXTURE = ROOT / "tests" / "fixtures" / "sg_manual_snapshot" / "hdb_loan_v044.json"


def test_dashboard_v4_cli_options_exist() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--dashboard-v4" in option_strings
    assert "--refresh-dir" in option_strings
    assert "--fx-rates-file" in option_strings


def test_dashboard_v4_generates_asset_buckets_and_outputs(tmp_path: Path) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    fx_rates = _write_fx_rates(tmp_path)

    result = write_dashboard_v4(
        refresh_dir=refresh_dir,
        fx_rates_file=fx_rates,
        out_dir=tmp_path / "dashboard_v4",
    )

    assert result.generated is True
    assert set(result.output_paths) == {
        "markdown_report",
        "html_report",
        "dashboard_summary",
        "asset_bucket_summary",
        "liquid_withdrawal_cashflow",
        "net_worth_bucket_history",
        "dashboard_warnings",
        "asset_bucket_chart",
        "withdrawal_cashflow_chart",
        "net_worth_bucket_history_chart",
    }
    assert result.bucket_count == 4
    assert result.history_count == 1
    assert result.withdrawal_row_count == 9
    assert WarningCode.DASHBOARD_V4_WITHDRAWAL_CASHFLOW_GENERATED in result.warning_codes
    assert WarningCode.DASHBOARD_V4_GENERATED_WITH_WARNINGS in result.warning_codes

    bucket_rows = _read_rows(result.output_paths["asset_bucket_summary"])
    by_bucket = {row["bucket"]: row for row in bucket_rows}
    assert list(bucket_rows[0]) == ASSET_BUCKET_FIELDNAMES
    assert by_bucket["fixed_assets"]["amount"] == "200000.00"
    assert by_bucket["retirement_accounts"]["amount"] == "8000.00"
    assert by_bucket["liquid_investment_assets"]["amount"] == "3180.00"
    assert by_bucket["fixed_assets"]["currency"] == "SGD"
    assert by_bucket["retirement_accounts"]["currency"] == "SGD"
    assert by_bucket["liquid_investment_assets"]["currency"] == "SGD"
    assert "Fixed assets" in by_bucket["fixed_assets"]["bucket_label"]
    assert "Retirement accounts" in by_bucket["retirement_accounts"]["bucket_label"]
    assert "Liquid investment assets" in by_bucket["liquid_investment_assets"]["bucket_label"]

    history_rows = _read_rows(result.output_paths["net_worth_bucket_history"])
    assert list(history_rows[0]) == BUCKET_HISTORY_FIELDNAMES
    assert history_rows[0]["fixed_assets"] == "200000.00"
    assert history_rows[0]["retirement_accounts"] == "8000.00"
    assert history_rows[0]["liquid_investment_assets"] == "3180.00"


def test_dashboard_v4_withdrawal_cashflow_uses_explicit_fx(tmp_path: Path) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    result = write_dashboard_v4(
        refresh_dir=refresh_dir,
        fx_rates_file=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "dashboard_v4_cashflow",
    )

    rows = _read_rows(result.output_paths["liquid_withdrawal_cashflow"])
    assert list(rows[0]) == LIQUID_WITHDRAWAL_FIELDNAMES
    by_rate_currency = {(row["withdrawal_rate"], row["currency"]): row for row in rows}
    assert by_rate_currency[("0.030", "SGD")]["annual"] == "95.40"
    assert by_rate_currency[("0.030", "SGD")]["monthly"] == "7.95"
    assert by_rate_currency[("0.030", "SGD")]["daily"] == "0.26"
    assert by_rate_currency[("0.030", "USD")]["annual"] == "73.38"
    assert by_rate_currency[("0.030", "CNY")]["annual"] == "530.00"


def test_dashboard_v4_fx_file_with_bom_still_generates_all_display_currencies(
    tmp_path: Path,
) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    fx_rates = _write_fx_rates(tmp_path)
    fx_rates.write_text(f"\ufeff{fx_rates.read_text(encoding='utf-8')}", encoding="utf-8")

    result = write_dashboard_v4(
        refresh_dir=refresh_dir,
        fx_rates_file=fx_rates,
        out_dir=tmp_path / "dashboard_v4_bom_fx",
    )

    rows = _read_rows(result.output_paths["liquid_withdrawal_cashflow"])
    assert len(rows) == 9
    assert {row["withdrawal_rate"] for row in rows} == {"0.030", "0.035", "0.040"}
    assert {row["currency"] for row in rows} == {"USD", "SGD", "CNY"}
    assert WarningCode.DASHBOARD_V4_FX_RATES_MISSING not in result.warning_codes
    assert WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED not in result.warning_codes


def test_dashboard_v4_missing_fx_warns_and_skips_conversion(tmp_path: Path) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)

    result = write_dashboard_v4(
        refresh_dir=refresh_dir,
        fx_rates_file=None,
        out_dir=tmp_path / "dashboard_v4_missing_fx",
    )

    assert WarningCode.DASHBOARD_V4_FX_RATES_MISSING in result.warning_codes
    assert WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED in result.warning_codes
    bucket_rows = _read_rows(result.output_paths["asset_bucket_summary"])
    liquid = {row["bucket"]: row for row in bucket_rows}["liquid_investment_assets"]
    assert liquid["amount"] == ""
    assert liquid["currency"] == "MIXED"
    assert "USD:2000.00" in liquid["native_totals"]
    assert "HKD:3000.00" in liquid["native_totals"]


def test_dashboard_v4_unclassified_assets_are_review_required(tmp_path: Path) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    account_path = refresh_dir / "merged" / "merged_account_nav_ledger.csv"
    rows = _read_rows(account_path)
    rows.append({field: "" for field in rows[0]})
    rows[-1]["provider"] = "synthetic_missing_currency_provider"
    _write_rows(account_path, rows)

    result = write_dashboard_v4(
        refresh_dir=refresh_dir,
        fx_rates_file=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "dashboard_v4_unclassified",
    )

    bucket_rows = _read_rows(result.output_paths["asset_bucket_summary"])
    unclassified = {row["bucket"]: row for row in bucket_rows}["unclassified"]
    assert unclassified["review_required"] == "yes"
    assert WarningCode.DASHBOARD_V4_UNCLASSIFIED_ASSETS in result.warning_codes
    assert WarningCode.DASHBOARD_V4_BUCKET_CLASSIFICATION_WARNING in result.warning_codes


def test_dashboard_v4_cli_generates_redacted_offline_summary(tmp_path: Path, capsys) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    out_dir = tmp_path / "dashboard_v4_cli"

    assert (
        main(
            [
                "--dashboard-v4",
                "--refresh-dir",
                str(refresh_dir),
                "--fx-rates-file",
                str(_write_fx_rates(tmp_path)),
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out

    assert "Personal CFO Dashboard v4 v0.6.0 (offline)" in output
    assert "External connections used: no" in output
    assert "Broker connections used: no" in output
    assert "Asset bucket rows: 4" in output
    assert "Warning codes:" in output
    assert (out_dir / "PERSONAL_CFO_DASHBOARD_V060.md").exists()


def test_dashboard_v4_cli_rejects_live_and_other_generators(tmp_path: Path) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    out_dir = tmp_path / "dashboard_v4_reject"

    for extra_args in (
        ["--allow-live-read"],
        ["--provider", "moomoo", "--account-discovery"],
        ["--run-net-worth-refresh", "--input-file", str(tmp_path / "input.json")],
        ["--dashboard-v3", "--merge-dir", str(tmp_path / "merged")],
    ):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/personal_cfo_agent.py",
                "--dashboard-v4",
                "--refresh-dir",
                str(refresh_dir),
                "--out-dir",
                str(out_dir),
                *extra_args,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert "cannot be combined" in result.stderr


def test_dashboard_v4_outputs_are_static_local_and_redacted(tmp_path: Path) -> None:
    refresh_dir = _generate_refresh_dir(tmp_path)
    result = write_dashboard_v4(
        refresh_dir=refresh_dir,
        fx_rates_file=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "dashboard_v4_static",
    )

    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in result.output_paths.values()
        if path.suffix.lower() in {".html", ".md", ".json", ".csv", ".svg"}
    ).lower()
    for marker in (
        "<script",
        "fetch(",
        "xmlhttprequest",
        "sendbeacon",
        "cdn",
        "upload",
        "raw_account",
        "account_id_hash",
        "nric",
        "singpass",
        "api_key",
        "secret",
        "recommended portfolio",
        "optimal allocation",
        "tax advice",
        "place_order",
        "transfer_cash",
    ):
        assert marker not in combined


def test_dashboard_v4_report_path_is_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/dashboard_v060_fixture/dashboard_v060_summary.json",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def _generate_refresh_dir(tmp_path: Path) -> Path:
    dirs = _generate_fixture_chain(tmp_path)
    refresh_dir = tmp_path / "net_worth_refresh_v059"
    (refresh_dir / "manual_layers").mkdir(parents=True)
    shutil.copytree(dirs["merged"], refresh_dir / "merged")
    shutil.copytree(dirs["snapshot"], refresh_dir / "snapshots")
    shutil.copytree(dirs["dashboard_v3"], refresh_dir / "dashboard")
    shutil.copytree(dirs["property"], refresh_dir / "manual_layers" / "property_mortgage")
    shutil.copytree(dirs["sg"], refresh_dir / "manual_layers" / "sg_retirement_tax")
    return refresh_dir


def _generate_fixture_chain(tmp_path: Path) -> dict[str, Path]:
    merged = tmp_path / "merged"
    dashboard_v2 = tmp_path / "dashboard_v2"
    snapshot = tmp_path / "snapshot"
    property_dir = tmp_path / "property"
    sg_dir = tmp_path / "sg"
    dashboard_v3 = tmp_path / "dashboard_v3"
    merge_provider_bundles(input_root=None, out_dir=merged, fixture_mode=True)
    account_path = merged / "merged_account_nav_ledger.csv"
    account_rows = _read_rows(account_path)
    for row in account_rows:
        row["account_nav"] = "0.00"
        row["base_currency"] = "SGD"
    account_rows[0]["account_nav"] = "100.00"
    account_rows[0]["base_currency"] = "SGD"
    account_rows[1]["account_nav"] = "2000.00"
    account_rows[1]["base_currency"] = "USD"
    account_rows[2]["account_nav"] = "3000.00"
    account_rows[2]["base_currency"] = "HKD"
    _write_rows(account_path, account_rows)
    assert main(["--dashboard-v2", "--input-dir", str(merged), "--out-dir", str(dashboard_v2)]) == 0
    assert (
        main(
            [
                "--record-snapshot",
                "--merge-dir",
                str(merged),
                "--dashboard-dir",
                str(dashboard_v2),
                "--out-dir",
                str(snapshot),
                "--snapshot-id",
                "snapshot_v060_synthetic",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--property-mortgage-snapshot",
                "--property-input",
                str(PROPERTY_FIXTURE),
                "--mortgage-input",
                str(MORTGAGE_FIXTURE),
                "--out-dir",
                str(property_dir),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--sg-manual-snapshot",
                "--cpf-input",
                str(CPF_FIXTURE),
                "--srs-input",
                str(SRS_FIXTURE),
                "--tax-input",
                str(TAX_FIXTURE),
                "--hdb-loan-input",
                str(HDB_LOAN_FIXTURE),
                "--out-dir",
                str(sg_dir),
            ]
        )
        == 0
    )
    write_dashboard_v3(
        merge_dir=merged,
        snapshot_dir=snapshot,
        dashboard_dir=dashboard_v2,
        property_mortgage_dir=property_dir,
        sg_snapshot_dir=sg_dir,
        fx_rates_input=_write_fx_rates(tmp_path),
        out_dir=dashboard_v3,
    )
    return {
        "merged": merged,
        "dashboard_v2": dashboard_v2,
        "snapshot": snapshot,
        "property": property_dir,
        "sg": sg_dir,
        "dashboard_v3": dashboard_v3,
    }


def _write_fx_rates(tmp_path: Path) -> Path:
    path = tmp_path / "fx_rates_v060_fixture.json"
    path.write_text(
        json.dumps(
            {
                "base_currency": "SGD",
                "rates_to_base": {
                    "SGD": "1.00",
                    "USD": "1.30",
                    "HKD": "0.16",
                    "CNY": "0.18",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
