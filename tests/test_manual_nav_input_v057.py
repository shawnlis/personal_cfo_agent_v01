from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.manual_nav_input import (
    generate_manual_nav_form,
    init_manual_nav_input,
    manual_nav_to_provider_bundle,
    validate_manual_nav_input,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import merge_provider_bundles


ROOT = Path(__file__).resolve().parents[1]


def test_manual_nav_form_generation_creates_static_local_html(tmp_path: Path) -> None:
    result = generate_manual_nav_form(out_dir=tmp_path)

    html = result.output_path.read_text(encoding="utf-8").lower()
    assert result.output_path.name == "manual_nav_form.html"
    assert "<html" in html
    assert "manual account nav input" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html
    assert "fetch(" not in html
    assert "upload" not in html
    assert WarningCode.MANUAL_NAV_FORM_GENERATED in result.warning_codes


def test_manual_nav_init_creates_local_placeholder_and_does_not_overwrite(
    tmp_path: Path,
) -> None:
    out_file = tmp_path / "manual_nav_input.local.json"

    first = init_manual_nav_input(out_file=out_file)
    original = out_file.read_text(encoding="utf-8")
    out_file.write_text('{"local":"edited"}', encoding="utf-8")
    second = init_manual_nav_input(out_file=out_file)

    assert first.created is True
    assert "schema_version" in original
    assert second.skipped is True
    assert json.loads(out_file.read_text(encoding="utf-8")) == {"local": "edited"}
    assert WarningCode.MANUAL_NAV_INPUT_EXISTS_SKIPPED in second.warning_codes


def test_manual_nav_validation_accepts_valid_synthetic_input(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)

    result = validate_manual_nav_input(input_file=input_file)

    assert result.valid is True
    assert result.account_count == 3
    assert result.provider_labels == ["syfe_trade", "usmart", "webull"]
    assert WarningCode.MANUAL_NAV_VALIDATION_WITH_WARNINGS in result.warning_codes
    assert WarningCode.MANUAL_NAV_OPTIONAL_SPLIT_MISSING in result.warning_codes
    assert WarningCode.MANUAL_NAV_MIXED_CURRENCIES in result.warning_codes


def test_manual_nav_validation_fails_on_missing_account_nav(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["accounts"][0]["account_nav"] = ""
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_manual_nav_input(input_file=input_file)

    assert result.valid is False
    assert WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING in result.warning_codes
    assert WarningCode.MANUAL_NAV_VALIDATION_FAILED in result.warning_codes


def test_manual_nav_validation_fails_on_missing_as_of_date(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["accounts"][0]["as_of_date"] = ""
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_manual_nav_input(input_file=input_file)

    assert result.valid is False
    assert WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING in result.warning_codes


def test_manual_nav_raw_identifier_detection(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)
    payload = json.loads(input_file.read_text(encoding="utf-8"))
    payload["accounts"][0]["account_number"] = "ABC123456789"
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_manual_nav_input(input_file=input_file)

    assert result.valid is False
    assert WarningCode.MANUAL_NAV_RAW_IDENTIFIER_DETECTED in result.warning_codes


def test_manual_nav_bundle_requires_hash_salt(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)

    result = manual_nav_to_provider_bundle(
        input_file=input_file,
        out_dir=tmp_path / "bundle",
        env={},
    )

    assert result.generated is False
    assert WarningCode.MANUAL_NAV_HASH_SALT_MISSING in result.warning_codes


def test_manual_nav_provider_bundle_hashes_accounts_and_merges(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)
    out_dir = tmp_path / "reports" / "manual_nav_v057_fixture"

    result = manual_nav_to_provider_bundle(
        input_file=input_file,
        out_dir=out_dir,
        env={"CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"},
    )
    rows = _read_csv(out_dir / "normalized_asset_ledger.csv")
    combined_output = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            out_dir / "normalized_asset_ledger.csv",
            out_dir / "provider_sync_summary.json",
            out_dir / "manual_nav_warnings.md",
            out_dir / "MANUAL_NAV_INPUT_V057.md",
        )
    )
    merge = merge_provider_bundles(
        input_root=tmp_path / "reports",
        out_dir=tmp_path / "reports" / "merged",
    )

    assert result.generated is True
    assert len(rows) == 3
    assert {row["provider"] for row in rows} == {"syfe_trade", "webull", "usmart"}
    assert all(row["account_id_hash"].startswith("acct_") for row in rows)
    assert "Synthetic Syfe Trade account" not in combined_output
    assert "Synthetic Webull account" not in combined_output
    assert "Synthetic uSMART account" not in combined_output
    assert merge.account_nav_row_count == 3
    assert merge.position_row_count == 0


def test_manual_nav_cli_redacts_values_and_generates_bundle(tmp_path: Path) -> None:
    input_file = _write_valid_input(tmp_path)
    out_dir = tmp_path / "bundle_cli"
    env = {**os.environ, "CFO_ACCOUNT_HASH_SALT": "SYNTHETIC_TEST_SALT"}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--manual-nav-to-provider-bundle",
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
    assert "Bundle generated: yes" in result.stdout
    assert "1000.00" not in combined
    assert "Synthetic Syfe Trade account" not in combined


def test_manual_nav_templates_have_no_real_private_or_live_markers() -> None:
    paths = [
        ROOT / "templates" / "private_inputs" / "manual_nav_input.example.json",
        ROOT / "templates" / "private_inputs" / "manual_nav_form.html",
    ]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)

    forbidden = [
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
    ]
    for marker in forbidden:
        assert marker not in text


def _write_valid_input(tmp_path: Path) -> Path:
    source = ROOT / "templates" / "private_inputs" / "manual_nav_input.example.json"
    target = tmp_path / "manual_nav_input.local.json"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
