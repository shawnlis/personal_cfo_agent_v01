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
    FIRE_TARGET_FIELDNAMES,
    LIQUID_WITHDRAWAL_FIELDNAMES,
    write_dashboard_v4,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.net_worth_integrity_guard import run_net_worth_integrity_guard
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
        "fire_target_projection",
        "net_worth_bucket_history",
        "dashboard_warnings",
        "asset_bucket_chart",
        "withdrawal_cashflow_chart",
        "net_worth_bucket_history_chart",
    }
    assert result.bucket_count == 5
    assert result.history_count == 1
    assert result.withdrawal_row_count == 9
    assert result.fire_projection_row_count == 5
    assert WarningCode.DASHBOARD_V4_WITHDRAWAL_CASHFLOW_GENERATED in result.warning_codes
    assert WarningCode.DASHBOARD_V4_FIRE_TARGET_GENERATED in result.warning_codes
    assert WarningCode.DASHBOARD_V4_GENERATED_WITH_WARNINGS in result.warning_codes

    bucket_rows = _read_rows(result.output_paths["asset_bucket_summary"])
    by_bucket = {row["bucket"]: row for row in bucket_rows}
    assert list(bucket_rows[0]) == ASSET_BUCKET_FIELDNAMES
    assert by_bucket["fixed_assets"]["amount"] == "200000.00"
    assert by_bucket["retirement_accounts"]["amount"] == "8000.00"
    assert by_bucket["non_liquid_unvested_equity"]["amount"] == "480.00"
    assert by_bucket["liquid_investment_assets"]["amount"] == "2700.00"
    assert by_bucket["fixed_assets"]["currency"] == "SGD"
    assert by_bucket["retirement_accounts"]["currency"] == "SGD"
    assert by_bucket["non_liquid_unvested_equity"]["currency"] == "SGD"
    assert by_bucket["liquid_investment_assets"]["currency"] == "SGD"
    assert "Fixed assets" in by_bucket["fixed_assets"]["bucket_label"]
    assert "Retirement accounts" in by_bucket["retirement_accounts"]["bucket_label"]
    assert "Non-liquid unvested equity" in by_bucket["non_liquid_unvested_equity"]["bucket_label"]
    assert "Liquid investment assets" in by_bucket["liquid_investment_assets"]["bucket_label"]

    history_rows = _read_rows(result.output_paths["net_worth_bucket_history"])
    assert list(history_rows[0]) == BUCKET_HISTORY_FIELDNAMES
    assert history_rows[0]["fixed_assets"] == "200000.00"
    assert history_rows[0]["retirement_accounts"] == "8000.00"
    assert history_rows[0]["non_liquid_unvested_equity"] == "480.00"
    assert history_rows[0]["liquid_investment_assets"] == "2700.00"
    markdown = result.output_paths["markdown_report"].read_text(encoding="utf-8")
    html = result.output_paths["html_report"].read_text(encoding="utf-8")
    summary = json.loads(result.output_paths["dashboard_summary"].read_text(encoding="utf-8"))
    assert "## Data Source Coverage" in markdown
    assert "## Integrity Status" in markdown
    assert "Integrity Status" in html
    assert "Integrity guard generated: yes" in markdown
    assert "Ready to confirm history: yes" in markdown
    assert "Blocking warning codes: None" in markdown
    assert "Broker data included: no" in markdown
    assert "Broker provider inputs: None" in markdown
    assert "Account NAV rows: 4" in markdown
    assert "No broker provider input folders found; live broker assets are not confirmed in this refresh." in markdown
    assert "Data Source Coverage" in html
    assert "live broker assets are not confirmed" in html
    assert "Withdrawal ladder rows" not in markdown
    assert "Withdrawal ladder rows" not in html
    assert "Uses liquid investment assets only" not in markdown
    assert "Uses liquid investment assets only" not in html
    assert "Uses explicit local FX rates" not in markdown
    assert "Uses explicit local FX rates" not in html
    assert "Output Files" not in markdown
    assert "Output Files" not in html
    assert "asset_bucket_summary.csv" not in markdown
    assert "asset_bucket_summary.csv" not in html
    assert "Warning Codes" not in markdown
    assert "Warning Codes" not in html
    assert "DASHBOARD_V4_BUCKET_HISTORY_LIMITED" not in markdown
    assert "DASHBOARD_V4_BUCKET_HISTORY_LIMITED" not in html
    assert "Static SVG output" not in markdown
    assert "Static SVG output" not in html
    assert "Review Queue" not in markdown
    assert "Review Queue" not in html
    assert "Rows: 1" not in markdown
    assert "Rows: 1" not in html
    assert "History rows" not in markdown
    assert "History rows" not in html
    assert "Unclassified or missing-currency assets are retained for review" not in markdown
    assert "Unclassified or missing-currency assets are retained for review" not in html
    assert "Missing FX rates skip conversion" not in markdown
    assert "Missing FX rates skip conversion" not in html
    assert "## Snapshot History Review" in markdown
    assert "Snapshot History Review" in html
    assert "Review snapshot generated: yes" in markdown
    assert "Confirmed history write present: no" in markdown
    assert "--confirm-snapshot-history-write" in markdown
    assert "--confirm-snapshot-history-write" in html
    assert "Fixed assets: 200,000.00 SGD" in markdown
    assert "Fixed assets: 200,000.00 SGD" in html
    assert "Non-liquid unvested equity: 480.00 SGD" in markdown
    assert "Non-liquid unvested equity: 480.00 SGD" in html
    assert "Liquid investment assets: 2,700.00 SGD" in markdown
    assert "Liquid investment assets: 2,700.00 SGD" in html
    assert "Total assets: 211,180.00 SGD (100.00%)" in markdown
    assert "Total assets: 211,180.00 SGD (100.00%)" in html
    assert "| Rate | Annual | Monthly | Daily |" in markdown
    assert "| 3.0% | US$62.31<br>S$81.00<br>¥450.00 | US$5.19<br>S$6.75<br>¥37.50 | US$0.17<br>S$0.22<br>¥1.23 |" in markdown
    assert "## FIRE Target Scenario" in markdown
    assert "Target: US$20,000,000.00" in markdown
    assert "Annual investment: US$400,000.00" in markdown
    assert "Start liquid NAV: US$2,076.92" in markdown
    assert "| Return | Years |" in markdown
    assert "| 10% | 18.79 |" in markdown
    assert "Full years" not in markdown
    assert "Approx years" not in markdown
    assert "<table>" in html
    assert "<th>Annual</th>" in html
    assert "<td>US$62.31<br>S$81.00<br>¥450.00</td>" in html
    assert "FIRE Target Scenario" in html
    assert "fire-assumptions" in html
    assert 'id="fire-target-usd"' in html
    assert 'value="20000000.00"' in html
    assert 'id="fire-annual-investment-usd"' in html
    assert 'value="400000.00"' in html
    assert 'data-start-usd="2076.92"' in html
    assert "fire-target-table" in html
    assert 'data-return-rate="0.100000"' in html
    assert 'class="fire-years-cell"' in html
    assert "yearsToTarget" in html
    assert "Target: US$20,000,000.00" not in html
    assert "Annual investment: US$400,000.00" not in html
    assert "US$2,076.92" in html
    assert "<th>Currency</th>" not in html
    assert "Target Annual Withdrawal" in html
    assert "target-annual-withdrawal" in html
    assert "Current liquid assets" in html
    assert "2,700.00 SGD" in html
    assert "4% annual capacity" in html
    assert "108.00 SGD" in html
    assert "Required liquid assets" in html
    assert "Progress" in html
    assert 'data-liquid-amount="2700.00"' in html
    assert "chart-stack" in html
    assert "width=\"1120\"" in html
    assert "class=\"grid\"" not in html
    assert "3.0% / USD: annual" not in markdown
    assert "3.0% / USD: annual" not in html
    assert "Asset buckets: 4" in markdown
    assert summary["asset_bucket_count"] == 5
    assert summary["display_asset_bucket_count"] == 4
    assert summary["source_coverage"]["account_nav_row_count"] == 4
    assert summary["source_coverage"]["broker_data_included"] is False
    assert summary["source_coverage"]["broker_provider_input_dirs"] == []
    assert summary["integrity_guard"]["generated"] is True
    assert summary["integrity_guard"]["ready_to_confirm"] is True
    assert summary["integrity_guard"]["blocking_warning_codes"] == []
    assert summary["fire_target_projection_row_count"] == 5
    assert summary["fire_target_usd"] == "20000000.00"
    assert summary["fire_annual_investment_usd"] == "400000.00"
    assert "Needs review / unclassified" not in markdown
    assert "Needs review / unclassified" not in html

    fire_rows = _read_rows(result.output_paths["fire_target_projection"])
    assert list(fire_rows[0]) == FIRE_TARGET_FIELDNAMES
    assert [row["return_rate"] for row in fire_rows] == [
        "0.100",
        "0.150",
        "0.200",
        "0.250",
        "0.300",
    ]
    assert {row["starting_liquid_nav_usd"] for row in fire_rows} == {"2076.92"}
    assert {row["annual_investment_usd"] for row in fire_rows} == {"400000.00"}
    assert {row["fire_target_usd"] for row in fire_rows} == {"20000000.00"}
    assert fire_rows[0]["estimated_years_to_target"] == "18.79"
    assert fire_rows[3]["estimated_years_to_target"] != fire_rows[4]["estimated_years_to_target"]
    assert all(int(row["years_to_target"]) > 0 for row in fire_rows)
    assert {row["fx_mode"] for row in fire_rows} == {"SGD_to_USD"}


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
    assert by_rate_currency[("0.030", "SGD")]["annual"] == "81.00"
    assert by_rate_currency[("0.030", "SGD")]["monthly"] == "6.75"
    assert by_rate_currency[("0.030", "SGD")]["daily"] == "0.22"
    assert by_rate_currency[("0.030", "USD")]["annual"] == "62.31"
    assert by_rate_currency[("0.030", "CNY")]["annual"] == "450.00"


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
    assert WarningCode.DASHBOARD_V4_FIRE_TARGET_INPUT_MISSING in result.warning_codes
    assert result.fire_projection_row_count == 0
    bucket_rows = _read_rows(result.output_paths["asset_bucket_summary"])
    liquid = {row["bucket"]: row for row in bucket_rows}["liquid_investment_assets"]
    assert liquid["amount"] == ""
    assert liquid["currency"] == "MIXED"
    assert "USD:2000.00" in liquid["native_totals"]
    assert "HKD:3000.00" not in liquid["native_totals"]
    unvested = {row["bucket"]: row for row in bucket_rows}["non_liquid_unvested_equity"]
    assert "HKD:3000.00" in unvested["native_totals"]


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
    markdown = result.output_paths["markdown_report"].read_text(encoding="utf-8")
    html = result.output_paths["html_report"].read_text(encoding="utf-8")

    assert unclassified["review_required"] == "yes"
    assert "Needs review / unclassified" in markdown
    assert "Needs review / unclassified" in html
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
    assert "Asset bucket rows: 5" in output
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
    assert "<script>" in combined
    for marker in (
        "fetch(",
        "xmlhttprequest",
        "sendbeacon",
        "localstorage",
        "sessionstorage",
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
    run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=refresh_dir / "integrity_guard",
        providers_requested=[],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=_write_fx_rates(tmp_path),
        upstream_warning_codes=[],
    )
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
    account_rows[2]["account_nav_bucket"] = "non_liquid_unvested_equity"
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
