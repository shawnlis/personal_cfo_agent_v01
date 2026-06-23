from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.private_input_center import (
    build_private_input_center_form_html,
    generate_private_input_center_form,
    init_private_input_center,
    private_input_center_to_snapshots,
    read_expected_source_contract,
    save_private_input_center_payload,
    validate_private_input_center,
    write_fx_rates_from_private_input_center,
)
from personal_cfo_agent.provider_bundle_merge import merge_provider_bundles
from personal_cfo_agent.runner import build_arg_parser, main


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "private_inputs" / "personal_cfo_input.example.json"
FORM_TEMPLATE = ROOT / "templates" / "private_inputs" / "personal_cfo_input_form.html"
PRIVATE_VALUE_MARKER = "9876543.21"


def test_private_input_center_cli_options_exist() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--private-input-center-form" in option_strings
    assert "--private-input-center-local-app" in option_strings
    assert "--init-private-input-center" in option_strings
    assert "--validate-private-input-center" in option_strings
    assert "--private-input-center-to-snapshots" in option_strings
    assert "--run-net-worth-refresh" in option_strings
    assert "--refresh-brokers" in option_strings
    assert "--snapshot-review" in option_strings
    assert "--local-workbench" in option_strings


def test_private_input_center_form_generation_is_static_local(tmp_path: Path) -> None:
    result = generate_private_input_center_form(out_dir=tmp_path)

    html = result.output_path.read_text(encoding="utf-8").lower()

    assert result.output_path.name == "personal_cfo_input_form.html"
    assert "personal cfo private input center" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" in html
    assert "fetch(local_save_endpoint" in html
    assert "xmlhttprequest" not in html
    assert "sendbeacon" not in html
    assert "upload" not in html
    assert "preview json" in html
    assert "save to local json" in html
    assert "download json" not in html
    assert "save json file" not in html
    assert "download_json" not in html
    assert "save_json" not in html
    assert "showsavefilepicker" not in html
    assert "global snapshot" in html
    assert "snapshot_date" in html
    assert "income tax payable" in html
    assert 'id="income_tax_payable"' in html
    assert "cpf ia" in html
    assert 'id="cpf_ia"' in html
    assert "cpf balance" in html
    assert 'id="cpf_balance"' in html
    assert "cpf retirement assets" not in html
    assert "amountsum([\"cpf_ia\", \"cpf_balance\"])" in html
    assert "fx rates" in html
    assert 'id="fx_usd_to_base"' in html
    assert 'id="fx_cny_to_base"' in html
    assert 'id="fx_hkd_to_base"' in html
    assert "optionalamount(\"fx_usd_to_base\")" in html
    assert "expected sources" in html
    assert 'id="expect_ibkr"' in html
    assert 'id="expect_moomoo"' in html
    assert 'id="expect_tiger"' in html
    assert 'id="expect_manual_nav"' in html
    assert "expected_sources" in html
    assert "value of unvested shares" in html
    assert 'id="unvested_shares_nav"' in html
    assert "webull nav" in html
    assert "usmart nav" in html
    assert "other nav" in html
    assert "webull manual nav" not in html
    assert "usmart manual nav" not in html
    assert "other manual nav" not in html
    assert "hdb loan balance" not in html
    assert 'id="hdb_loan_balance"' not in html
    assert "tax_payable_available: boolavailable(\"income_tax_payable\")" in html
    assert "outstanding_balance_available: false" in html
    assert 'for="property_id_hash"' not in html
    assert 'id="property_id_hash"' not in html
    assert 'for="loan_id_hash"' not in html
    assert 'id="loan_id_hash"' not in html
    assert WarningCode.PRIVATE_INPUT_CENTER_FORM_GENERATED in result.warning_codes


def test_private_input_center_form_can_embed_local_save_endpoint() -> None:
    html = build_private_input_center_form_html(
        local_save_endpoint="http://127.0.0.1:8765/save"
    )

    assert 'const LOCAL_SAVE_ENDPOINT = "http://127.0.0.1:8765/save";' in html
    assert "https://" not in html
    assert "sendbeacon" not in html.lower()
    assert "xmlhttprequest" not in html.lower()


def test_private_input_center_local_save_validates_before_write(tmp_path: Path) -> None:
    target = tmp_path / "personal_cfo_input.local.json"
    result = save_private_input_center_payload(
        input_file=target,
        payload_text=TEMPLATE.read_text(encoding="utf-8"),
    )

    assert result.saved is True
    assert target.exists()
    assert PRIVATE_VALUE_MARKER not in repr(result)
    assert WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS in result.warning_codes


def test_private_input_center_local_save_fails_closed_on_invalid_json(
    tmp_path: Path,
) -> None:
    target = tmp_path / "personal_cfo_input.local.json"
    result = save_private_input_center_payload(input_file=target, payload_text="{")

    assert result.saved is False
    assert not target.exists()
    assert WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID in result.warning_codes


def test_private_input_center_init_creates_and_does_not_overwrite(tmp_path: Path) -> None:
    out_file = tmp_path / "personal_cfo_input.local.json"

    first = init_private_input_center(out_file=out_file)
    out_file.write_text('{"local":"edited"}', encoding="utf-8")
    second = init_private_input_center(out_file=out_file)

    assert first.created is True
    assert second.skipped is True
    assert json.loads(out_file.read_text(encoding="utf-8")) == {"local": "edited"}
    assert WarningCode.PRIVATE_INPUT_CENTER_EXISTS_SKIPPED in second.warning_codes


def test_private_input_center_validation_accepts_synthetic_input(tmp_path: Path) -> None:
    input_file = _write_input(tmp_path)

    result = validate_private_input_center(input_file=input_file)

    assert result.valid is True
    assert result.manual_nav_account_count == 3
    assert result.property_count == 1
    assert result.mortgage_count == 1
    assert result.cpf_count == 1
    assert result.srs_count == 1
    assert result.tax_count == 1
    assert result.hdb_loan_count == 1
    assert result.provider_labels == ["syfe_trade", "usmart", "webull"]
    assert WarningCode.MANUAL_NAV_OPTIONAL_SPLIT_MISSING in result.warning_codes
    assert WarningCode.MANUAL_NAV_MIXED_CURRENCIES in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS in result.warning_codes


def test_private_input_center_reads_expected_source_contract(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["expected_sources"] = {
        "providers": [
            {"provider": "ibkr", "required": True},
            {"provider": "moomoo", "required": False},
        ],
        "manual_layers": {
            "manual_nav": "required",
            "property_mortgage": "optional",
        },
    }
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    contract = read_expected_source_contract(input_file=input_file)

    assert contract.providers_required == ["ibkr"]
    assert contract.providers_optional == ["moomoo"]
    assert contract.manual_layers_required == ["manual_nav"]
    assert contract.manual_layers_optional == ["property_mortgage"]
    assert contract.warning_codes == []


def test_private_input_center_invalid_expected_source_contract_warns(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["expected_sources"] = {"providers": "ibkr"}
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    validation = validate_private_input_center(input_file=input_file)
    contract = read_expected_source_contract(input_file=input_file)

    assert validation.valid is False
    assert WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID in validation.warning_codes
    assert WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_FAILED in validation.warning_codes
    assert WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID in contract.warning_codes


def test_private_input_center_maps_simplified_form_enums_for_manual_nav(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["source_type"] = "local_private_input_center"
    other_account = dict(payload["manual_nav_accounts"][0])
    other_account["provider_label"] = "manual_other"
    other_account["account_label"] = "Synthetic other manual account"
    other_account["account_nav"] = "4000.00"
    payload["manual_nav_accounts"].append(other_account)
    for account in payload["manual_nav_accounts"]:
        account["account_type"] = "manual_nav"
        account["source_type"] = "local_private_input_center"
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    validation = validate_private_input_center(input_file=input_file)
    out_dir = tmp_path / "reports" / "private_input_center_simplified_enums"
    generated = private_input_center_to_snapshots(
        input_file=input_file,
        out_dir=out_dir,
        env={"CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"},
    )

    rows = _read_csv(out_dir / "manual_nav" / "normalized_asset_ledger.csv")
    providers = sorted({row["provider"] for row in rows})

    assert validation.valid is True
    assert validation.provider_labels == ["other", "syfe_trade", "usmart", "webull"]
    assert generated.generated is True
    assert providers == ["other", "syfe_trade", "usmart", "webull"]
    assert WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING not in validation.warning_codes


def test_private_input_center_maps_form_percent_ownership_for_property_snapshot(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["properties"][0]["valuation_amount"] = "1000.00"
    payload["properties"][0]["ownership_pct"] = "100.00"
    payload["mortgages"][0]["outstanding_balance"] = "250.00"
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    out_dir = tmp_path / "reports" / "private_input_center_percent_ownership"

    result = private_input_center_to_snapshots(
        input_file=input_file,
        out_dir=out_dir,
        env={"CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"},
    )

    summary = json.loads(
        (out_dir / "property_mortgage" / "property_equity_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.generated is True
    assert summary["property_equity_rows"][0]["owned_property_value"] == "1000.00"
    assert summary["property_equity_rows"][0]["equity"] == "750.00"
    assert summary["total_equity_by_currency"]["SGD"] == "750.00"


def test_private_input_center_maps_cpf_ia_and_balance_to_total(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["cpf"][0]["cpf_ia"] = "1250.00"
    payload["cpf"][0]["cpf_balance"] = "2750.00"
    payload["cpf"][0]["total"] = "0.00"
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    out_dir = tmp_path / "reports" / "private_input_center_cpf_split"

    result = private_input_center_to_snapshots(
        input_file=input_file,
        out_dir=out_dir,
        env={"CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"},
    )

    rows = _read_csv(out_dir / "sg_retirement_tax" / "cpf_snapshot_ledger.csv")

    assert result.generated is True
    assert rows[0]["total"] == "4000.00"


def test_private_input_center_extracts_positive_fx_rates_only(tmp_path: Path) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["fx_rates"] = {
        "base_currency": "SGD",
        "rates_to_base": {
            "SGD": "1.00",
            "USD": "1.35",
            "CNY": "",
            "HKD": "0.00",
        },
    }
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    output = write_fx_rates_from_private_input_center(
        input_file=input_file,
        out_file=tmp_path / "fx_rates_from_input.json",
    )

    assert output is not None
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert exported["base_currency"] == "SGD"
    assert exported["rates_to_base"] == {"USD": "1.35", "SGD": "1.00"}
    assert "CNY" not in exported["rates_to_base"]
    assert "HKD" not in exported["rates_to_base"]
    assert PRIVATE_VALUE_MARKER not in output.read_text(encoding="utf-8")


def test_private_input_center_skips_fx_export_when_no_positive_cross_rate(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["fx_rates"] = {
        "base_currency": "SGD",
        "rates_to_base": {"SGD": "1.00", "USD": "", "CNY": "0.00"},
    }
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    output = write_fx_rates_from_private_input_center(
        input_file=input_file,
        out_file=tmp_path / "fx_rates_from_input.json",
    )

    assert output is None
    assert not (tmp_path / "fx_rates_from_input.json").exists()


def test_private_input_center_validation_fails_missing_required_dates(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["snapshot_date"] = ""
    payload["manual_nav_accounts"][0]["as_of_date"] = ""
    payload["cpf"][0]["snapshot_date"] = ""
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_input_center(input_file=input_file)

    assert result.valid is False
    assert WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING in result.warning_codes
    assert WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_FAILED in result.warning_codes


def test_private_input_center_validation_fails_missing_manual_nav(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["manual_nav_accounts"][0]["account_nav"] = ""
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_input_center(input_file=input_file)

    assert result.valid is False
    assert WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING in result.warning_codes


def test_private_input_center_validation_detects_raw_identifiers(tmp_path: Path) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["manual_nav_accounts"][0]["account_number"] = "ABC123456789"
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_private_input_center(input_file=input_file)

    assert result.valid is False
    assert WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED in result.warning_codes


def test_private_input_center_conversion_generates_all_outputs_and_merges(
    tmp_path: Path,
) -> None:
    input_file = _write_input(tmp_path)
    out_dir = tmp_path / "reports" / "private_input_center_v058_fixture"

    result = private_input_center_to_snapshots(
        input_file=input_file,
        out_dir=out_dir,
        env={"CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"},
    )
    merge = merge_provider_bundles(
        input_root=tmp_path / "reports",
        out_dir=tmp_path / "reports" / "merged",
    )

    assert result.generated is True
    assert (out_dir / "manual_nav" / "normalized_asset_ledger.csv").exists()
    assert (out_dir / "manual_nav" / "provider_sync_summary.json").exists()
    assert (out_dir / "property_mortgage" / "property_asset_ledger.csv").exists()
    assert (out_dir / "property_mortgage" / "mortgage_liability_ledger.csv").exists()
    assert (out_dir / "sg_retirement_tax" / "cpf_snapshot_ledger.csv").exists()
    assert (out_dir / "sg_retirement_tax" / "srs_snapshot_ledger.csv").exists()
    assert (out_dir / "sg_retirement_tax" / "tax_snapshot_ledger.csv").exists()
    assert (out_dir / "sg_retirement_tax" / "hdb_loan_snapshot_ledger.csv").exists()
    assert merge.account_nav_row_count == 3
    assert WarningCode.PRIVATE_INPUT_CENTER_GENERATED_WITH_WARNINGS in result.warning_codes


def test_private_input_center_cli_redacts_values_and_generates(tmp_path: Path) -> None:
    input_file = _write_input(tmp_path)
    out_dir = tmp_path / "reports" / "private_input_center_cli"
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["manual_nav_accounts"][0]["account_nav"] = PRIVATE_VALUE_MARKER
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    env = {**os.environ, "CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--private-input-center-to-snapshots",
            "--input-file",
            str(input_file),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Snapshot outputs generated: yes" in result.stdout
    assert PRIVATE_VALUE_MARKER not in combined
    assert "Synthetic Syfe Trade account" not in combined


def test_net_worth_refresh_requires_live_gate_for_broker_refresh(tmp_path: Path) -> None:
    input_file = _write_sgd_input(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--run-net-worth-refresh",
            "--input-file",
            str(input_file),
            "--out-dir",
            str(tmp_path / "reports" / "net_worth_refresh"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--allow-live-read" in result.stderr


def test_net_worth_refresh_manual_only_chain_generates_dashboard_and_chart(
    tmp_path: Path,
) -> None:
    input_file = _write_sgd_input(tmp_path)
    out_dir = tmp_path / "reports" / "net_worth_refresh"
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["manual_nav_accounts"][0]["account_nav"] = PRIVATE_VALUE_MARKER
    input_file.write_text(json.dumps(payload), encoding="utf-8")
    env = {**os.environ, "CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"}

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
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Dashboard generated: yes" in result.stdout
    assert "External provider reads attempted: no" in result.stdout
    assert PRIVATE_VALUE_MARKER not in combined
    assert (out_dir / "manual_layers" / "manual_nav" / "normalized_asset_ledger.csv").exists()
    assert (out_dir / "provider_inputs" / "manual_nav" / "normalized_asset_ledger.csv").exists()
    assert (out_dir / "merged" / "merged_account_nav_ledger.csv").exists()
    assert (out_dir / "snapshots" / "net_worth_history.csv").exists()
    assert (out_dir / "dashboard" / "PERSONAL_CFO_DASHBOARD_V050.md").exists()
    assert (out_dir / "dashboard" / "net_worth_history_chart.svg").exists()
    assert "NET_WORTH_REFRESH_LIVE_READ_SKIPPED" in result.stdout


def test_private_input_center_cli_validation_is_value_redacted(
    tmp_path: Path, capsys
) -> None:
    input_file = _write_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["properties"][0]["valuation_amount"] = PRIVATE_VALUE_MARKER
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(["--validate-private-input-center", "--input-file", str(input_file)])
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Validation passed: yes" in captured
    assert PRIVATE_VALUE_MARKER not in captured


def test_private_input_center_templates_are_safe_placeholders() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in (TEMPLATE, FORM_TEMPLATE)
    )
    forbidden = [
        "s1234567a",
        "raw_address",
        "account_number",
        "place_order",
        "submit_order",
        "modify_order",
        "cancel_order",
        "preview_order",
        "transfer_cash",
        "withdraw_cash",
        "recommendation",
        "buy/sell",
        "login",
        "singpass",
        "cpf.gov",
        "iras.gov",
        "hdb.gov",
        "tax advice",
    ]

    assert "placeholder" in text
    assert "9876543.21" not in text
    for marker in forbidden:
        assert marker not in text


def test_private_input_center_source_has_no_live_or_browser_markers() -> None:
    source_text = (
        ROOT / "src" / "personal_cfo_agent" / "private_input_center.py"
    ).read_text(encoding="utf-8")
    lower = source_text.lower()

    for marker in (
        "selenium",
        "playwright",
        "singpass",
        "cpf.gov",
        "iras.gov",
        "hdb.gov",
        "place_order",
        "transfer_cash",
        "recommended allocation",
        "tax advice",
    ):
        assert marker not in lower


def _write_input(tmp_path: Path) -> Path:
    target = tmp_path / "personal_cfo_input.local.json"
    target.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _write_sgd_input(tmp_path: Path) -> Path:
    target = _write_input(tmp_path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["base_currency"] = "SGD"
    for account in payload["manual_nav_accounts"]:
        account["base_currency"] = "SGD"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
