from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.runner import build_arg_parser, main
from personal_cfo_agent.sg_manual_snapshot import (
    CPF_SNAPSHOT_LEDGER_FIELDNAMES,
    HDB_LOAN_SNAPSHOT_LEDGER_FIELDNAMES,
    SRS_SNAPSHOT_LEDGER_FIELDNAMES,
    TAX_SNAPSHOT_LEDGER_FIELDNAMES,
    record_sg_manual_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sg_manual_snapshot"
RAW_GOV_IDENTIFIER = "synthetic_government_identifier_should_not_appear"
FORBIDDEN_OUTPUT_MARKERS = (
    RAW_GOV_IDENTIFIER.lower(),
    "singpass",
    "cpf.gov.sg",
    "iras.gov.sg",
    "hdb.gov.sg",
    "file your taxes",
    "tax advice",
    "recommended allocation",
    "buy ",
    "sell ",
)


def test_sg_manual_snapshot_outputs_ledgers_and_summary(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path)

    result = record_sg_manual_snapshot(
        **inputs,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert set(result.output_paths) == {
        "cpf_snapshot_ledger",
        "srs_snapshot_ledger",
        "tax_snapshot_ledger",
        "hdb_loan_snapshot_ledger",
        "sg_retirement_tax_summary",
        "sg_retirement_tax_warnings",
        "markdown_report",
    }
    assert (tmp_path / "out" / "SG_RETIREMENT_TAX_SNAPSHOT_V044.md").exists()
    cpf_rows = _read_rows(result.output_paths["cpf_snapshot_ledger"])
    srs_rows = _read_rows(result.output_paths["srs_snapshot_ledger"])
    tax_rows = _read_rows(result.output_paths["tax_snapshot_ledger"])
    hdb_rows = _read_rows(result.output_paths["hdb_loan_snapshot_ledger"])
    assert list(cpf_rows[0]) == CPF_SNAPSHOT_LEDGER_FIELDNAMES
    assert list(srs_rows[0]) == SRS_SNAPSHOT_LEDGER_FIELDNAMES
    assert list(tax_rows[0]) == TAX_SNAPSHOT_LEDGER_FIELDNAMES
    assert list(hdb_rows[0]) == HDB_LOAN_SNAPSHOT_LEDGER_FIELDNAMES

    summary = json.loads(result.output_paths["sg_retirement_tax_summary"].read_text(encoding="utf-8"))
    assert summary["schema_version"] == "v0.4.4"
    assert summary["cpf_row_count"] == 1
    assert summary["srs_row_count"] == 1
    assert summary["tax_row_count"] == 1
    assert summary["hdb_loan_row_count"] == 1
    assert summary["tax_snapshot_mode"] == "informational_review_only"
    assert summary["hdb_loan_snapshot_mode"] == "manual_snapshot_only"


def test_missing_optional_values_warn_but_generate(tmp_path: Path) -> None:
    inputs = _write_inputs(
        tmp_path,
        cpf_overrides={"ma": ""},
        srs_overrides={"cash": ""},
        tax_overrides={"tax_paid_available": ""},
        hdb_overrides={"outstanding_balance_available": ""},
    )

    result = record_sg_manual_snapshot(
        **inputs,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert WarningCode.CPF_BALANCE_MISSING in result.warning_codes
    assert WarningCode.SRS_BALANCE_MISSING in result.warning_codes
    assert WarningCode.TAX_DATA_INCOMPLETE in result.warning_codes
    assert WarningCode.HDB_LOAN_BALANCE_MISSING in result.warning_codes
    assert WarningCode.SG_SNAPSHOT_GENERATED_WITH_WARNINGS in result.warning_codes


def test_missing_snapshot_date_fails_closed(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path, cpf_overrides={"snapshot_date": ""})

    result = record_sg_manual_snapshot(
        **inputs,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert not result.generated
    assert result.output_dir is None
    assert WarningCode.CPF_SNAPSHOT_MISSING in result.warning_codes
    assert not (tmp_path / "out").exists()


def test_hdb_loan_without_property_link_warns_but_generates(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path, hdb_overrides={"linked_property_id_hash": ""})

    result = record_sg_manual_snapshot(
        **inputs,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert WarningCode.HDB_LOAN_PROPERTY_LINK_MISSING in result.warning_codes
    hdb_rows = _read_rows(result.output_paths["hdb_loan_snapshot_ledger"])
    assert hdb_rows[0]["linked_property_id_hash"] == ""


def test_raw_government_identifiers_fail_closed(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path, cpf_overrides={"raw_nric": RAW_GOV_IDENTIFIER})

    result = record_sg_manual_snapshot(
        **inputs,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    assert not result.generated
    assert WarningCode.CPF_SNAPSHOT_MISSING in result.warning_codes
    assert not (tmp_path / "out").exists()


def test_outputs_exclude_identifiers_and_forbidden_language(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path)

    result = record_sg_manual_snapshot(
        **inputs,
        out_dir=tmp_path / "out",
        generated_at=_generated_at(),
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in result.output_paths.values())
    lower = combined.lower()
    assert "review-only" in lower
    for marker in FORBIDDEN_OUTPUT_MARKERS:
        assert marker not in lower


def test_cli_generates_sg_manual_snapshot_without_loading_local_env(tmp_path: Path, capsys) -> None:
    inputs = _write_inputs(tmp_path)

    exit_code = main(
        [
            "--sg-manual-snapshot",
            "--cpf-input",
            str(inputs["cpf_input"]),
            "--srs-input",
            str(inputs["srs_input"]),
            "--tax-input",
            str(inputs["tax_input"]),
            "--hdb-loan-input",
            str(inputs["hdb_loan_input"]),
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO Singapore Manual Snapshot v0.4.4 (offline)" in captured
    assert "External connections used: no" in captured
    assert "Loaded local environment" not in captured
    assert "Snapshot generated: yes" in captured


def test_cli_rejects_live_discovery_and_other_generators(tmp_path: Path) -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--sg-manual-snapshot" in option_strings
    assert "--cpf-input" in option_strings
    assert "--srs-input" in option_strings
    assert "--tax-input" in option_strings
    assert "--hdb-loan-input" in option_strings

    base_args = [
        "--sg-manual-snapshot",
        "--cpf-input",
        str(tmp_path / "cpf.json"),
        "--srs-input",
        str(tmp_path / "srs.json"),
        "--tax-input",
        str(tmp_path / "tax.json"),
        "--hdb-loan-input",
        str(tmp_path / "hdb.json"),
        "--out-dir",
        str(tmp_path / "out"),
    ]
    with pytest.raises(SystemExit):
        main([*base_args, "--allow-live-read"])
    with pytest.raises(SystemExit):
        main([*base_args, "--provider", "moomoo", "--account-discovery"])
    with pytest.raises(SystemExit):
        main([*base_args, "--merge-provider-bundles"])
    with pytest.raises(SystemExit):
        main([*base_args, "--property-mortgage-snapshot"])


def test_tracked_fixtures_are_synthetic_only() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURE_DIR.glob("*.json"))
    assert "synthetic_manual_fixture" in combined
    assert RAW_GOV_IDENTIFIER not in combined
    assert "CPF Account" not in combined
    assert "Tax Reference" not in combined
    assert "raw_address" not in combined


def test_source_has_no_login_browser_or_portal_markers() -> None:
    source_text = (ROOT / "src" / "personal_cfo_agent" / "sg_manual_snapshot.py").read_text(
        encoding="utf-8"
    )
    lower = source_text.lower()
    for marker in ("selenium", "playwright", "singpass", "cpf.gov", "iras.gov", "login"):
        assert marker not in lower


def test_sg_manual_snapshot_report_path_is_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/sg_snapshot_v044_fixture/sg_retirement_tax_summary.json",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def _write_inputs(
    tmp_path: Path,
    *,
    cpf_overrides: dict[str, object] | None = None,
    srs_overrides: dict[str, object] | None = None,
    tax_overrides: dict[str, object] | None = None,
    hdb_overrides: dict[str, object] | None = None,
) -> dict[str, Path]:
    cpf_input = tmp_path / "cpf.json"
    srs_input = tmp_path / "srs.json"
    tax_input = tmp_path / "tax.json"
    hdb_loan_input = tmp_path / "hdb_loan.json"
    cpf_row = {
        "snapshot_date": "2026-06-16",
        "oa": "1000.00",
        "sa": "2000.00",
        "ma": "3000.00",
        "ra": "0.00",
        "total": "6000.00",
        "currency": "SGD",
        "source_type": "synthetic_manual_fixture",
        "source_date": "2026-06-16",
        "review_required": True,
    }
    srs_row = {
        "snapshot_date": "2026-06-16",
        "provider_label": "Synthetic SRS provider",
        "cash": "500.00",
        "investments_value": "1500.00",
        "total": "2000.00",
        "contribution_ytd": "100.00",
        "currency": "SGD",
        "source_type": "synthetic_manual_fixture",
        "source_date": "2026-06-16",
        "review_required": True,
    }
    tax_row = {
        "year_of_assessment": "2026",
        "assessable_income_available": True,
        "tax_payable_available": True,
        "tax_paid_available": False,
        "reliefs_available": True,
        "source_type": "synthetic_manual_fixture",
        "source_date": "2026-06-16",
        "review_required": True,
    }
    hdb_row = {
        "snapshot_date": "2026-06-16",
        "loan_id_hash": "loan_synthetic_hdb_hash",
        "linked_property_id_hash": "prop_synthetic_home_hash",
        "monthly_installment_available": True,
        "outstanding_balance_available": True,
        "currency": "SGD",
        "source_type": "synthetic_manual_fixture",
        "source_date": "2026-06-16",
        "review_required": True,
    }
    cpf_row.update(cpf_overrides or {})
    srs_row.update(srs_overrides or {})
    tax_row.update(tax_overrides or {})
    hdb_row.update(hdb_overrides or {})
    cpf_input.write_text(json.dumps({"cpf": [cpf_row]}), encoding="utf-8")
    srs_input.write_text(json.dumps({"srs_accounts": [srs_row]}), encoding="utf-8")
    tax_input.write_text(json.dumps({"tax_records": [tax_row]}), encoding="utf-8")
    hdb_loan_input.write_text(json.dumps({"hdb_loans": [hdb_row]}), encoding="utf-8")
    return {
        "cpf_input": cpf_input,
        "srs_input": srs_input,
        "tax_input": tax_input,
        "hdb_loan_input": hdb_loan_input,
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _generated_at() -> datetime:
    return datetime(2026, 6, 16, 0, 0, 0, tzinfo=timezone.utc)
