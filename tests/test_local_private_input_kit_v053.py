from __future__ import annotations

import json
import subprocess
from pathlib import Path

from personal_cfo_agent.local_private_input_kit import (
    PRIVATE_INPUT_FILES,
    init_private_input_kit,
    private_input_template_names,
    run_manual_snapshot_chain,
    validate_private_inputs,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.runner import build_arg_parser, main


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates" / "private_inputs"
PRIVATE_VALUE_MARKER = "9876543.21"
FORBIDDEN_MARKERS = (
    "S1234567A",
    "raw_address",
    "account_number",
    "singpass",
    "cpf.gov",
    "iras.gov",
    "hdb.gov",
    "place_order",
    "preview_order",
    "transfer_cash",
    "withdraw_cash",
    "recommended allocation",
    "tax advice",
    "buy ",
    "sell ",
)


def test_cli_options_exist() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--init-private-input-kit" in option_strings
    assert "--validate-private-inputs" in option_strings
    assert "--run-manual-snapshot-chain" in option_strings
    assert "--overwrite" in option_strings


def test_init_kit_creates_expected_placeholder_files(tmp_path: Path) -> None:
    result = init_private_input_kit(out_dir=tmp_path / "private_inputs")

    assert result.created_files
    assert {path.name for path in result.created_files} == set(PRIVATE_INPUT_FILES.values())
    assert WarningCode.PRIVATE_INPUT_KIT_INITIALIZED in result.warning_codes
    for file_name in PRIVATE_INPUT_FILES.values():
        assert (tmp_path / "private_inputs" / file_name).exists()


def test_init_kit_does_not_overwrite_by_default(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    property_path = input_dir / "property_snapshot.json"
    property_path.write_text("LOCAL_PRIVATE_VALUE_SHOULD_STAY", encoding="utf-8")

    result = init_private_input_kit(out_dir=input_dir)

    assert property_path.read_text(encoding="utf-8") == "LOCAL_PRIVATE_VALUE_SHOULD_STAY"
    assert property_path in result.skipped_files
    assert WarningCode.PRIVATE_INPUT_FILE_EXISTS_SKIPPED in result.warning_codes


def test_init_kit_overwrites_only_when_explicit(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    property_path = input_dir / "property_snapshot.json"
    property_path.write_text("LOCAL_PRIVATE_VALUE_CAN_BE_REPLACED", encoding="utf-8")

    result = init_private_input_kit(out_dir=input_dir, overwrite=True)

    assert "LOCAL_PRIVATE_VALUE_CAN_BE_REPLACED" not in property_path.read_text(
        encoding="utf-8"
    )
    assert property_path in result.overwritten_files
    assert WarningCode.PRIVATE_INPUT_OVERWRITE_USED in result.warning_codes


def test_validate_private_inputs_passes_placeholders_without_printing_values(
    tmp_path: Path, capsys
) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    property_path = input_dir / "property_snapshot.json"
    payload = json.loads(property_path.read_text(encoding="utf-8"))
    payload["properties"][0]["valuation_amount"] = PRIVATE_VALUE_MARKER
    property_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(["--validate-private-inputs", "--input-dir", str(input_dir)])
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Validation passed: yes" in captured
    assert PRIVATE_VALUE_MARKER not in captured
    assert "property_snapshot.json" in captured


def test_validate_private_inputs_detects_missing_required_fields(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    cpf_path = input_dir / "cpf_snapshot.json"
    payload = json.loads(cpf_path.read_text(encoding="utf-8"))
    payload["cpf"][0]["snapshot_date"] = ""
    cpf_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_inputs(input_dir=input_dir)

    assert not result.valid
    assert WarningCode.PRIVATE_INPUT_REQUIRED_FIELD_MISSING in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_VALIDATION_FAILED in result.warning_codes


def test_validate_private_inputs_detects_unusable_property_shape(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    property_path = input_dir / "property_snapshot.json"
    payload = json.loads(property_path.read_text(encoding="utf-8"))
    payload["properties"][0]["ownership_pct"] = "not_a_number"
    payload["properties"][0]["valuation_date"] = "2025-01-01"
    property_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_inputs(input_dir=input_dir)

    assert not result.valid
    assert WarningCode.PROPERTY_OWNERSHIP_MISSING in result.warning_codes
    assert WarningCode.PROPERTY_VALUATION_STALE in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_VALIDATION_FAILED in result.warning_codes


def test_validate_private_inputs_accepts_percent_property_ownership(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    property_path = input_dir / "property_snapshot.json"
    payload = json.loads(property_path.read_text(encoding="utf-8"))
    payload["properties"][0]["ownership_pct"] = "50%"
    payload["properties"][0]["valuation_date"] = "2025-01-01"
    property_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_inputs(input_dir=input_dir)

    assert result.valid
    assert WarningCode.PROPERTY_OWNERSHIP_MISSING not in result.warning_codes
    assert WarningCode.PROPERTY_VALUATION_STALE in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_VALIDATION_WITH_WARNINGS in result.warning_codes


def test_validate_private_inputs_detects_unusable_mortgage_balance(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    mortgage_path = input_dir / "mortgage_snapshot.json"
    payload = json.loads(mortgage_path.read_text(encoding="utf-8"))
    payload["mortgages"][0]["outstanding_balance"] = "not_a_number"
    mortgage_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_inputs(input_dir=input_dir)

    assert not result.valid
    assert WarningCode.MORTGAGE_REQUIRED_FIELD_MISSING in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_VALIDATION_FAILED in result.warning_codes


def test_validate_private_inputs_detects_raw_identifiers(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    init_private_input_kit(out_dir=input_dir)
    hdb_path = input_dir / "hdb_loan_snapshot.json"
    payload = json.loads(hdb_path.read_text(encoding="utf-8"))
    payload["hdb_loans"][0]["account_number"] = "S1234567A"
    hdb_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_inputs(input_dir=input_dir)

    assert not result.valid
    assert WarningCode.PRIVATE_INPUT_RAW_IDENTIFIER_DETECTED in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_VALIDATION_FAILED in result.warning_codes


def test_gitignore_covers_private_input_directories() -> None:
    for path in (
        "private_inputs/property_snapshot.json",
        "local_private_inputs/cpf_snapshot.json",
        "reports/personal_cfo_agent/private_inputs/srs_snapshot.json",
    ):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, check=False)
        assert result.returncode == 0


def test_manual_snapshot_chain_runs_with_local_synthetic_inputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "private_inputs"
    output_dir = tmp_path / "reports" / "manual_snapshot_v053_local"
    init_private_input_kit(out_dir=input_dir)

    result = run_manual_snapshot_chain(input_dir=input_dir, out_dir=output_dir)

    assert result.generated
    assert (output_dir / "property_mortgage" / "property_asset_ledger.csv").exists()
    assert (output_dir / "property_mortgage" / "mortgage_liability_ledger.csv").exists()
    assert (output_dir / "sg_retirement_tax" / "cpf_snapshot_ledger.csv").exists()
    assert (output_dir / "sg_retirement_tax" / "srs_snapshot_ledger.csv").exists()
    assert WarningCode.PRIVATE_INPUT_CHAIN_GENERATED_WITH_WARNINGS in result.warning_codes


def test_manual_snapshot_chain_cli_outputs_safe_summary(tmp_path: Path, capsys) -> None:
    input_dir = tmp_path / "private_inputs"
    output_dir = tmp_path / "reports" / "manual_snapshot_v053_local"
    init_private_input_kit(out_dir=input_dir)

    exit_code = main(
        [
            "--run-manual-snapshot-chain",
            "--input-dir",
            str(input_dir),
            "--out-dir",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO Manual Snapshot Chain v0.5.3 (offline)" in captured
    assert "External connections used: no" in captured
    assert "Broker connections used: no" in captured
    assert PRIVATE_VALUE_MARKER not in captured
    assert "Snapshot chain generated: yes" in captured


def test_committed_templates_are_safe_placeholders() -> None:
    assert set(private_input_template_names()) == {
        "property_snapshot.example.json",
        "mortgage_snapshot.example.json",
        "cpf_snapshot.example.json",
        "srs_snapshot.example.json",
        "tax_snapshot.example.json",
        "hdb_loan_snapshot.example.json",
    }
    combined = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_DIR.glob("*.json"))
    lower = combined.lower()
    assert "placeholder" in lower
    assert "1000000" not in combined
    assert "300000" not in combined
    for marker in FORBIDDEN_MARKERS:
        assert marker.lower() not in lower


def test_source_has_no_login_browser_or_action_markers() -> None:
    source_text = (ROOT / "src" / "personal_cfo_agent" / "local_private_input_kit.py").read_text(
        encoding="utf-8"
    )
    lower = source_text.lower()
    for marker in (
        "selenium",
        "playwright",
        "singpass",
        "cpf.gov",
        "iras.gov",
        "hdb.gov",
        "login",
        "place_order",
        "transfer_cash",
        "recommended allocation",
        "tax advice",
    ):
        assert marker not in lower
