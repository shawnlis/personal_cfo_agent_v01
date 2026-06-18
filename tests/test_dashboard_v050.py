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
        out_dir=tmp_path / "dashboard_v3",
    )

    assert result.generated
    assert set(result.output_paths) == {
        "markdown_report",
        "html_report",
        "dashboard_summary",
        "net_worth_progress",
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
    assert by_category["mortgage_liabilities"]["amount"] == ""
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


def test_dashboard_v3_cli_rejects_live_discovery_and_other_generators(tmp_path: Path) -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--dashboard-v3" in option_strings
    assert "--snapshot-dir" in option_strings
    assert "--property-mortgage-dir" in option_strings
    assert "--sg-snapshot-dir" in option_strings

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


def _number(value: str) -> float:
    return float(value or "0")
