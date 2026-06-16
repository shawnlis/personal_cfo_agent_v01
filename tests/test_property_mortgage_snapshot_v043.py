from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.property_mortgage_snapshot import (
    MORTGAGE_LIABILITY_LEDGER_FIELDNAMES,
    PROPERTY_ASSET_LEDGER_FIELDNAMES,
    record_property_mortgage_snapshot,
)
from personal_cfo_agent.runner import build_arg_parser, main


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "property_mortgage"
RAW_ADDRESS = "SYNTHETIC_ADDRESS_SHOULD_NOT_APPEAR"
FORBIDDEN_MARKERS = (
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
    "optimal allocation",
    "buy ",
    "sell ",
)


def test_property_mortgage_snapshot_outputs_ledgers_and_summary(tmp_path: Path) -> None:
    property_input, mortgage_input = _write_inputs(tmp_path)

    result = record_property_mortgage_snapshot(
        property_input=property_input,
        mortgage_input=mortgage_input,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert set(result.output_paths) == {
        "property_asset_ledger",
        "mortgage_liability_ledger",
        "property_equity_summary",
        "property_mortgage_warnings",
        "markdown_report",
    }
    assert (tmp_path / "out" / "PROPERTY_MORTGAGE_SNAPSHOT_V043.md").exists()
    property_rows = _read_rows(result.output_paths["property_asset_ledger"])
    mortgage_rows = _read_rows(result.output_paths["mortgage_liability_ledger"])
    assert list(property_rows[0]) == PROPERTY_ASSET_LEDGER_FIELDNAMES
    assert list(mortgage_rows[0]) == MORTGAGE_LIABILITY_LEDGER_FIELDNAMES
    assert len(property_rows) == 1
    assert len(mortgage_rows) == 1


def test_equity_calculation_uses_owned_value_minus_linked_mortgage(tmp_path: Path) -> None:
    property_input, mortgage_input = _write_inputs(
        tmp_path,
        valuation_amount="1000000.00",
        ownership_pct="0.50",
        outstanding_balance="300000.00",
    )

    result = record_property_mortgage_snapshot(
        property_input=property_input,
        mortgage_input=mortgage_input,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    summary = json.loads(result.output_paths["property_equity_summary"].read_text(encoding="utf-8"))
    assert summary["property_equity_rows"][0]["owned_property_value"] == "500000.00"
    assert summary["property_equity_rows"][0]["linked_mortgage_balance"] == "300000.00"
    assert summary["property_equity_rows"][0]["equity"] == "200000.00"
    assert summary["total_equity_by_currency"]["SGD"] == "200000.00"


def test_stale_valuation_warns_but_generates(tmp_path: Path) -> None:
    property_input, mortgage_input = _write_inputs(tmp_path, valuation_date="2025-01-01")

    result = record_property_mortgage_snapshot(
        property_input=property_input,
        mortgage_input=mortgage_input,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert WarningCode.PROPERTY_VALUATION_STALE in result.warning_codes
    assert WarningCode.PROPERTY_MORTGAGE_GENERATED_WITH_WARNINGS in result.warning_codes


def test_missing_ownership_or_valuation_fails_closed(tmp_path: Path) -> None:
    property_input, mortgage_input = _write_inputs(
        tmp_path, ownership_pct="", valuation_amount=""
    )

    result = record_property_mortgage_snapshot(
        property_input=property_input,
        mortgage_input=mortgage_input,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert not result.generated
    assert result.output_dir is None
    assert WarningCode.PROPERTY_OWNERSHIP_MISSING in result.warning_codes
    assert WarningCode.PROPERTY_VALUATION_MISSING in result.warning_codes
    assert WarningCode.PROPERTY_MORTGAGE_FAILED in result.warning_codes
    assert not (tmp_path / "out").exists()


def test_unlinked_mortgage_stays_as_liability_with_warning(tmp_path: Path) -> None:
    property_input, mortgage_input = _write_inputs(tmp_path, linked_property_id_hash="")

    result = record_property_mortgage_snapshot(
        property_input=property_input,
        mortgage_input=mortgage_input,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert result.unlinked_mortgage_count == 1
    assert WarningCode.MORTGAGE_UNLINKED in result.warning_codes
    mortgage_rows = _read_rows(result.output_paths["mortgage_liability_ledger"])
    assert mortgage_rows[0]["linked_property_id_hash"] == ""
    summary = json.loads(result.output_paths["property_equity_summary"].read_text(encoding="utf-8"))
    assert summary["unlinked_liability_total_by_currency"]["SGD"] == "300000.00"


def test_outputs_exclude_raw_addresses_and_forbidden_markers(tmp_path: Path) -> None:
    property_input, mortgage_input = _write_inputs(tmp_path, raw_address=RAW_ADDRESS)

    result = record_property_mortgage_snapshot(
        property_input=property_input,
        mortgage_input=mortgage_input,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in result.output_paths.values())
    lower = combined.lower()
    assert RAW_ADDRESS not in combined
    for marker in FORBIDDEN_MARKERS:
        assert marker not in lower


def test_cli_generates_property_mortgage_snapshot_without_loading_local_env(
    tmp_path: Path, capsys
) -> None:
    property_input, mortgage_input = _write_inputs(tmp_path)

    exit_code = main(
        [
            "--property-mortgage-snapshot",
            "--property-input",
            str(property_input),
            "--mortgage-input",
            str(mortgage_input),
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO Property Mortgage Snapshot v0.4.3 (offline)" in captured
    assert "External connections used: no" in captured
    assert "Loaded local environment" not in captured
    assert "Snapshot generated: yes" in captured


def test_cli_rejects_live_discovery_and_other_generators(tmp_path: Path) -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--property-mortgage-snapshot" in option_strings
    assert "--property-input" in option_strings
    assert "--mortgage-input" in option_strings

    with pytest.raises(SystemExit):
        main(
            [
                "--property-mortgage-snapshot",
                "--property-input",
                str(tmp_path / "property.json"),
                "--mortgage-input",
                str(tmp_path / "mortgage.json"),
                "--out-dir",
                str(tmp_path / "out"),
                "--allow-live-read",
            ]
        )
    with pytest.raises(SystemExit):
        main(
            [
                "--property-mortgage-snapshot",
                "--property-input",
                str(tmp_path / "property.json"),
                "--mortgage-input",
                str(tmp_path / "mortgage.json"),
                "--out-dir",
                str(tmp_path / "out"),
                "--provider",
                "moomoo",
                "--account-discovery",
            ]
        )
    with pytest.raises(SystemExit):
        main(
            [
                "--property-mortgage-snapshot",
                "--property-input",
                str(tmp_path / "property.json"),
                "--mortgage-input",
                str(tmp_path / "mortgage.json"),
                "--out-dir",
                str(tmp_path / "out"),
                "--merge-provider-bundles",
            ]
        )


def test_tracked_fixtures_are_synthetic_only() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURE_DIR.glob("*.json"))
    assert "Synthetic" in combined
    assert "RAW_ACCOUNT" not in combined
    assert "SYNTHETIC_ADDRESS_SHOULD_NOT_APPEAR" not in combined


def test_property_mortgage_report_path_is_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/property_mortgage_v043_fixture/property_equity_summary.json",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def _write_inputs(
    tmp_path: Path,
    *,
    property_id_hash: str = "prop_synthetic_home_hash",
    valuation_amount: str = "1000000.00",
    ownership_pct: str = "0.50",
    valuation_date: str = "2026-06-16",
    linked_property_id_hash: str = "prop_synthetic_home_hash",
    outstanding_balance: str = "300000.00",
    raw_address: str = "",
) -> tuple[Path, Path]:
    property_input = tmp_path / "property.json"
    mortgage_input = tmp_path / "mortgage.json"
    property_payload = {
        "properties": [
            {
                "property_id_hash": property_id_hash,
                "label": "Synthetic home",
                "type": "residential_property",
                "country": "SG",
                "area": "Synthetic area",
                "ownership_pct": ownership_pct,
                "valuation_amount": valuation_amount,
                "currency": "SGD",
                "valuation_date": valuation_date,
                "source": "synthetic_fixture",
                "confidence": "synthetic",
                "review_required": True,
                "raw_address": raw_address,
            }
        ]
    }
    mortgage_payload = {
        "mortgages": [
            {
                "loan_id_hash": "loan_synthetic_home_hash",
                "linked_property_id_hash": linked_property_id_hash,
                "lender_label": "Synthetic lender",
                "outstanding_balance": outstanding_balance,
                "currency": "SGD",
                "interest_rate": "3.25",
                "rate_type": "floating",
                "monthly_payment": "2500.00",
                "repricing_date": "2027-01-01",
                "maturity_date": "2045-01-01",
                "snapshot_date": "2026-06-16",
                "review_required": True,
            }
        ]
    }
    property_input.write_text(json.dumps(property_payload), encoding="utf-8")
    mortgage_input.write_text(json.dumps(mortgage_payload), encoding="utf-8")
    return property_input, mortgage_input


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _generated_at() -> datetime:
    return datetime(2026, 6, 16, 0, 0, 0, tzinfo=timezone.utc)
