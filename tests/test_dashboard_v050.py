from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest

from personal_cfo_agent.dashboard_v3 import (
    ASSET_LIABILITY_BREAKDOWN_FIELDNAMES,
    BALANCE_SHEET_SUMMARY_FIELDNAMES,
    NET_WORTH_PROGRESS_FIELDNAMES,
    write_dashboard_v3,
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

RAW_IDENTIFIER = "RAW_ACCOUNT_OR_GOV_IDENTIFIER_SHOULD_NOT_APPEAR"
FORBIDDEN_MARKERS = (
    RAW_IDENTIFIER.lower(),
    "nric",
    "singpass",
    "cpf.gov.sg",
    "iras.gov.sg",
    "hdb.gov.sg",
    "place_order",
    "preview_order",
    "modify_order",
    "cancel_order",
    "order_list_query",
    "history_order_list_query",
    "deal_list_query",
    "history_deal_list_query",
    "transfer_cash",
    "withdraw_cash",
    "unlock_trade",
    "recommended portfolio",
    "recommendation",
    "optimal allocation",
    "advice",
    "buy ",
    "sell ",
)


def test_dashboard_v3_generates_from_all_fixture_layers(tmp_path: Path) -> None:
    dirs = _generate_fixture_chain(tmp_path)

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=dirs["snapshot"],
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        fx_rates_input=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "dashboard_v3",
    )

    assert result.generated
    assert set(result.output_paths) == {
        "markdown_report",
        "html_report",
        "dashboard_summary",
        "net_worth_progress",
        "net_worth_history_chart",
        "balance_sheet_summary",
        "asset_liability_breakdown",
        "dashboard_warnings",
    }
    assert result.account_count == 4
    assert result.provider_count == 4
    assert result.net_worth_history_count == 1
    assert result.property_count == 1
    assert result.cpf_count == 1
    assert WarningCode.DASHBOARD_V3_GENERATED_WITH_WARNINGS in result.warning_codes
    summary = json.loads(result.output_paths["dashboard_summary"].read_text(encoding="utf-8"))
    assert summary["dashboard_v2_summary_present"] is True
    assert summary["dashboard_v2_account_count"] == 4
    assert summary["latest_snapshot_date"]
    assert summary["provider_names"] == ["ibkr", "manual_snapshot", "moomoo", "tiger"]
    layer_status = {row["layer"]: row for row in summary["layer_status"]}
    assert layer_status["merged_account_nav"]["status"] == "present"
    assert layer_status["snapshot_history"]["role"] == "primary"
    assert layer_status["property_mortgage"]["status"] == "review_required"
    assert layer_status["sg_manual_snapshot"]["status"] == "review_required"


def test_dashboard_v3_writes_expected_csv_shapes_and_consistent_balance_sheet(
    tmp_path: Path,
) -> None:
    dirs = _generate_fixture_chain(tmp_path)

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=dirs["snapshot"],
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        fx_rates_input=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "dashboard_v3",
    )

    net_worth_rows = _read_rows(result.output_paths["net_worth_progress"])
    balance_rows = _read_rows(result.output_paths["balance_sheet_summary"])
    breakdown_rows = _read_rows(result.output_paths["asset_liability_breakdown"])
    assert list(net_worth_rows[0]) == NET_WORTH_PROGRESS_FIELDNAMES
    assert list(balance_rows[0]) == BALANCE_SHEET_SUMMARY_FIELDNAMES
    assert list(breakdown_rows[0]) == ASSET_LIABILITY_BREAKDOWN_FIELDNAMES
    assert any(row["category"] == "integrated_net_worth" for row in balance_rows)
    assert any(row["layer"] == "cpf" for row in breakdown_rows)
    assert any(row["layer"] == "property" for row in breakdown_rows)
    by_category = {row["category"]: row for row in balance_rows}
    assert by_category["property_equity"]["amount"] == "200000.00"
    assert by_category["mortgage_liabilities"]["amount"] == "300000.00"
    expected_net_worth = (
        _number(by_category["account_nav"]["amount"])
        + _number(by_category["property_equity"]["amount"])
        + _number(by_category["cpf_retirement_assets"]["amount"])
        + _number(by_category["srs_retirement_assets"]["amount"])
    )
    assert _number(by_category["integrated_net_worth"]["amount"]) == expected_net_worth
    assert any(
        row["item_label"] == "gross_mortgage_liabilities" and row["amount"] == "300000.00"
        for row in breakdown_rows
    )


def test_dashboard_v3_fx_rates_normalize_mixed_currency_nav(tmp_path: Path) -> None:
    dirs = _generate_fixture_chain(tmp_path)
    account_path = dirs["merged"] / "merged_account_nav_ledger.csv"
    account_rows = _read_rows(account_path)
    for row in account_rows:
        row["account_nav"] = "0.00"
        row["base_currency"] = "SGD"
    account_rows[0]["account_nav"] = "100.00"
    account_rows[0]["base_currency"] = "USD"
    account_rows[1]["account_nav"] = "200.00"
    account_rows[1]["base_currency"] = "HKD"
    with account_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(account_rows[0]))
        writer.writeheader()
        writer.writerows(account_rows)
    mixed_snapshot = tmp_path / "snapshot_fx_normalized"
    assert (
        main(
            [
                "--record-snapshot",
                "--merge-dir",
                str(dirs["merged"]),
                "--dashboard-dir",
                str(dirs["dashboard_v2"]),
                "--out-dir",
                str(mixed_snapshot),
                "--snapshot-id",
                "snapshot_v050_fx_normalized",
            ]
        )
        == 0
    )

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=mixed_snapshot,
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        fx_rates_input=_write_fx_rates(tmp_path, usd="1.30", hkd="0.16", sgd="1.00"),
        out_dir=tmp_path / "dashboard_v3_fx_normalized",
    )

    net_worth_rows = _read_rows(result.output_paths["net_worth_progress"])
    balance_rows = _read_rows(result.output_paths["balance_sheet_summary"])
    breakdown_rows = _read_rows(result.output_paths["asset_liability_breakdown"])
    by_category = {row["category"]: row for row in balance_rows}

    assert WarningCode.DASHBOARD_V3_FX_NORMALIZATION_APPLIED in result.warning_codes
    assert net_worth_rows[0]["base_currency"] == "SGD"
    assert net_worth_rows[0]["total_account_nav"] == "162.00"
    assert by_category["account_nav"]["amount"] == "162.00"
    assert by_category["account_nav"]["currency"] == "SGD"
    assert {
        row["currency"] for row in breakdown_rows if row["layer"] == "account_nav"
    } == {"SGD"}


def test_dashboard_v3_fx_rates_do_not_guess_missing_account_currency(
    tmp_path: Path,
) -> None:
    dirs = _generate_fixture_chain(tmp_path)
    account_path = dirs["merged"] / "merged_account_nav_ledger.csv"
    account_rows = _read_rows(account_path)
    for row in account_rows:
        row["account_nav"] = "0.00"
        row["base_currency"] = "SGD"
    account_rows[0]["provider"] = "unknown_currency_provider"
    account_rows[0]["account_nav"] = "100.00"
    account_rows[0]["base_currency"] = ""
    with account_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(account_rows[0]))
        writer.writeheader()
        writer.writerows(account_rows)
    snapshot_dir = tmp_path / "snapshot_missing_currency"
    assert (
        main(
            [
                "--record-snapshot",
                "--merge-dir",
                str(dirs["merged"]),
                "--dashboard-dir",
                str(dirs["dashboard_v2"]),
                "--out-dir",
                str(snapshot_dir),
                "--snapshot-id",
                "snapshot_v050_missing_currency",
            ]
        )
        == 0
    )

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=snapshot_dir,
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        fx_rates_input=_write_fx_rates(tmp_path),
        out_dir=tmp_path / "dashboard_v3_missing_currency",
    )

    balance_rows = _read_rows(result.output_paths["balance_sheet_summary"])
    breakdown_rows = _read_rows(result.output_paths["asset_liability_breakdown"])
    by_category = {row["category"]: row for row in balance_rows}
    provider_rows = {
        row["item_label"]: row for row in breakdown_rows if row["layer"] == "account_nav"
    }

    assert WarningCode.DASHBOARD_V3_FX_RATE_MISSING in result.warning_codes
    assert by_category["account_nav"]["amount"] == ""
    assert provider_rows["unknown_currency_provider"]["amount"] == ""
    assert provider_rows["unknown_currency_provider"]["currency"] == "SGD"


def test_dashboard_v3_mixed_currency_account_nav_requires_review(
    tmp_path: Path,
) -> None:
    dirs = _generate_fixture_chain(tmp_path)
    account_path = dirs["merged"] / "merged_account_nav_ledger.csv"
    account_rows = _read_rows(account_path)
    account_rows[0]["base_currency"] = "USD"
    account_rows[1]["base_currency"] = "HKD"
    with account_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(account_rows[0]))
        writer.writeheader()
        writer.writerows(account_rows)
    mixed_snapshot = tmp_path / "snapshot_mixed_currency"
    assert (
        main(
            [
                "--record-snapshot",
                "--merge-dir",
                str(dirs["merged"]),
                "--dashboard-dir",
                str(dirs["dashboard_v2"]),
                "--out-dir",
                str(mixed_snapshot),
                "--snapshot-id",
                "snapshot_v050_mixed_currency",
            ]
        )
        == 0
    )

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=mixed_snapshot,
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        out_dir=tmp_path / "dashboard_v3_mixed_currency",
    )

    net_worth_rows = _read_rows(result.output_paths["net_worth_progress"])
    balance_rows = _read_rows(result.output_paths["balance_sheet_summary"])
    breakdown_rows = _read_rows(result.output_paths["asset_liability_breakdown"])
    by_category = {row["category"]: row for row in balance_rows}

    assert WarningCode.DASHBOARD_V3_MIXED_CURRENCY_NAV in result.warning_codes
    assert net_worth_rows[0]["base_currency"] == "MIXED"
    assert net_worth_rows[0]["total_account_nav"] == ""
    assert net_worth_rows[0]["integrated_net_worth"] == ""
    assert by_category["account_nav"]["amount"] == ""
    assert by_category["integrated_net_worth"]["amount"] == ""
    provider_currency = {
        row["item_label"]: row["currency"]
        for row in breakdown_rows
        if row["layer"] == "account_nav"
    }
    assert "USD" in provider_currency.values()
    assert "HKD" in provider_currency.values()


def test_dashboard_v3_missing_property_snapshot_warns_not_fails(tmp_path: Path) -> None:
    dirs = _generate_fixture_chain(tmp_path)

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=dirs["snapshot"],
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=tmp_path / "missing_property",
        sg_snapshot_dir=dirs["sg"],
        out_dir=tmp_path / "dashboard_v3",
    )

    assert result.generated
    assert WarningCode.DASHBOARD_V3_PROPERTY_SNAPSHOT_MISSING in result.warning_codes


def test_dashboard_v3_missing_sg_snapshot_warns_not_fails(tmp_path: Path) -> None:
    dirs = _generate_fixture_chain(tmp_path)

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=dirs["snapshot"],
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=tmp_path / "missing_sg",
        out_dir=tmp_path / "dashboard_v3",
    )

    assert result.generated
    assert WarningCode.DASHBOARD_V3_SG_SNAPSHOT_MISSING in result.warning_codes


def test_dashboard_v3_missing_snapshot_history_fails_closed(tmp_path: Path) -> None:
    merged = tmp_path / "merged"
    merge_provider_bundles(input_root=None, out_dir=merged, fixture_mode=True)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()

    result = write_dashboard_v3(
        merge_dir=merged,
        snapshot_dir=snapshot_dir,
        property_mortgage_dir=None,
        sg_snapshot_dir=None,
        out_dir=tmp_path / "dashboard_v3",
    )

    assert not result.generated
    assert result.output_dir is None
    assert WarningCode.DASHBOARD_V3_SNAPSHOT_HISTORY_MISSING in result.warning_codes


def test_dashboard_v3_cli_generates_fixture_dashboard_without_local_env(
    tmp_path: Path, capsys
) -> None:
    dirs = _generate_fixture_chain(tmp_path)

    exit_code = main(
        [
            "--dashboard-v3",
            "--merge-dir",
            str(dirs["merged"]),
            "--snapshot-dir",
            str(dirs["snapshot"]),
            "--dashboard-dir",
            str(dirs["dashboard_v2"]),
            "--property-mortgage-dir",
            str(dirs["property"]),
            "--sg-snapshot-dir",
            str(dirs["sg"]),
            "--out-dir",
            str(tmp_path / "dashboard_v3"),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO Dashboard v3 v0.5.0 (offline)" in captured
    assert "External connections used: no" in captured
    assert "Broker connections used: no" in captured
    assert "Loaded local environment" not in captured
    assert "Dashboard generated: yes" in captured


def test_dashboard_v3_markdown_and_html_show_readable_sections(tmp_path: Path) -> None:
    dirs = _generate_fixture_chain(tmp_path)

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=dirs["snapshot"],
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        out_dir=tmp_path / "dashboard_v3",
    )

    markdown = result.output_paths["markdown_report"].read_text(encoding="utf-8")
    html = result.output_paths["html_report"].read_text(encoding="utf-8")
    expected_sections = (
        "## CFO Cockpit",
        "## Data Source Layer Status",
        "## Data Freshness",
        "## Net Worth Progress",
        "## Balance Sheet Breakdown",
        "## Provider And Account NAV Summary",
        "## Property And Mortgage Review",
        "## Singapore Manual Snapshot Review",
        "## Warning Summary",
    )
    for section in expected_sections:
        assert section in markdown
        assert section.removeprefix("## ") in html
    assert "merged_account_nav: present" in markdown
    assert "property_mortgage: review_required" in markdown
    assert "sg_manual_snapshot: review_required" in markdown
    assert "Latest snapshot date:" in markdown
    assert "Warning count:" in markdown
    assert "dashboard_v050_warnings.md" in markdown
    assert "net_worth_history_chart.svg" in markdown
    assert "Net Worth History Chart" in html
    assert result.output_paths["net_worth_history_chart"].exists()
    assert "<svg" in result.output_paths["net_worth_history_chart"].read_text(
        encoding="utf-8"
    )
    assert "<style>" in html
    assert "<main>" in html


def test_dashboard_v3_cli_rejects_live_discovery_and_other_generators(tmp_path: Path) -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--dashboard-v3" in option_strings
    assert "--snapshot-dir" in option_strings
    assert "--property-mortgage-dir" in option_strings
    assert "--sg-snapshot-dir" in option_strings
    assert "--fx-rates-input" in option_strings

    base_args = [
        "--dashboard-v3",
        "--merge-dir",
        str(tmp_path / "merged"),
        "--snapshot-dir",
        str(tmp_path / "snapshot"),
        "--out-dir",
        str(tmp_path / "dashboard"),
    ]
    with pytest.raises(SystemExit):
        main([*base_args, "--allow-live-read"])
    with pytest.raises(SystemExit):
        main([*base_args, "--provider", "moomoo", "--account-discovery"])
    with pytest.raises(SystemExit):
        main([*base_args, "--merge-provider-bundles"])
    with pytest.raises(SystemExit):
        main([*base_args, "--sg-manual-snapshot"])


def test_dashboard_v3_outputs_exclude_raw_ids_and_forbidden_markers(tmp_path: Path) -> None:
    dirs = _generate_fixture_chain(tmp_path)
    (dirs["merged"] / "account_source_map.json").write_text(
        json.dumps({"acct_fixture": {"source_bundle_ids": [RAW_IDENTIFIER]}}),
        encoding="utf-8",
    )

    result = write_dashboard_v3(
        merge_dir=dirs["merged"],
        snapshot_dir=dirs["snapshot"],
        dashboard_dir=dirs["dashboard_v2"],
        property_mortgage_dir=dirs["property"],
        sg_snapshot_dir=dirs["sg"],
        out_dir=tmp_path / "dashboard_v3",
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in result.output_paths.values())
    lower = combined.lower()
    assert RAW_IDENTIFIER not in combined
    assert "DU123456789" not in combined
    assert "S1234567A" not in combined
    for marker in FORBIDDEN_MARKERS:
        assert marker not in lower


def test_dashboard_v3_report_path_is_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/dashboard_v050_fixture/dashboard_v050_summary.json",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def _generate_fixture_chain(tmp_path: Path) -> dict[str, Path]:
    merged = tmp_path / "merged"
    dashboard_v2 = tmp_path / "dashboard_v2"
    snapshot = tmp_path / "snapshot"
    property_dir = tmp_path / "property"
    sg_dir = tmp_path / "sg"
    merge_provider_bundles(input_root=None, out_dir=merged, fixture_mode=True)
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
                "snapshot_v050_synthetic",
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
    return {
        "merged": merged,
        "dashboard_v2": dashboard_v2,
        "snapshot": snapshot,
        "property": property_dir,
        "sg": sg_dir,
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_fx_rates(
    tmp_path: Path, *, usd: str = "1.00", hkd: str = "1.00", sgd: str = "1.00"
) -> Path:
    path = tmp_path / "fx_rates.json"
    path.write_text(
        json.dumps(
            {
                "base_currency": "SGD",
                "rates": {
                    "USD": usd,
                    "HKD": hkd,
                    "SGD": sgd,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _number(value: str) -> float:
    return float(value or "0")
