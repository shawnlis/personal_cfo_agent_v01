from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from personal_cfo_agent.asset_ledger import write_normalized_asset_ledger
from personal_cfo_agent.config import load_manual_config
from personal_cfo_agent.manual_snapshot import (
    load_manual_snapshot_document,
    validate_manual_snapshot_payload,
    write_manual_snapshot_template,
)
from personal_cfo_agent.models import LEDGER_FIELDNAMES, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.providers import ManualSnapshotProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "manual_snapshot_workflow_v014.json"


def test_template_writer_creates_valid_empty_template(tmp_path) -> None:
    template_path = tmp_path / "manual_snapshot_template.json"
    write_manual_snapshot_template(template_path)
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert result.is_valid
    assert payload["assets"] == []
    assert payload["liabilities"] == []


def test_valid_manual_snapshot_loads() -> None:
    document = load_manual_snapshot_document(FIXTURE)
    assert document.validation_result.is_valid
    assert len(document.snapshot.assets) == 4
    assert len(document.snapshot.liabilities) == 1


def test_missing_currency_fails_closed(tmp_path) -> None:
    payload = _valid_payload()
    payload["assets"][0]["currency"] = ""
    path = _write_payload(tmp_path, payload)

    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert not result.is_valid
    assert WarningCode.MISSING_CURRENCY in {issue.code for issue in result.errors}

    provider = ManualSnapshotProvider(load_manual_config({}, path))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.MISSING_CURRENCY in snapshot.status.warning_codes


def test_missing_amount_fails_closed(tmp_path) -> None:
    payload = _valid_payload()
    payload["assets"][0].pop("estimated_value")
    path = _write_payload(tmp_path, payload)

    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert not result.is_valid
    assert WarningCode.INVALID_AMOUNT in {issue.code for issue in result.errors}

    provider = ManualSnapshotProvider(load_manual_config({}, path))
    snapshot = provider._sync()
    assert not snapshot.has_data()
    assert WarningCode.INVALID_AMOUNT in snapshot.status.warning_codes


def test_stale_valuation_emits_warning() -> None:
    payload = _valid_payload()
    payload["assets"][0]["valuation_date"] = "2025-01-01"
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert result.is_valid
    assert WarningCode.STALE_MANUAL_VALUATION in {issue.code for issue in result.warnings}


def test_missing_valuation_date_emits_review_warning() -> None:
    payload = _valid_payload()
    payload["assets"][0]["valuation_date"] = ""
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert result.is_valid
    warning_codes = {issue.code for issue in result.warnings}
    assert WarningCode.MISSING_VALUATION_DATE in warning_codes
    assert WarningCode.NEEDS_REVIEW in warning_codes


def test_negative_asset_and_liability_amounts_fail_closed() -> None:
    payload = _valid_payload()
    payload["assets"][0]["estimated_value"] = -1.0
    payload["liabilities"][0]["outstanding_balance"] = -1.0
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert not result.is_valid
    assert [issue.code for issue in result.errors].count(WarningCode.INVALID_AMOUNT) == 2


def test_cpf_values_cannot_be_marked_scraped() -> None:
    payload = _valid_payload()
    payload["assets"][1]["valuation_source"] = "scraped identity portal"
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert not result.is_valid
    assert WarningCode.SINGPASS_AUTOMATION_BLOCKED in {issue.code for issue in result.errors}


def test_webull_and_poems_values_must_be_manual() -> None:
    payload = _valid_payload()
    payload["assets"][2]["valuation_source"] = "api aggregate"
    payload["assets"].append(
        {
            "asset_id": "manual-poems-aggregate",
            "asset_type": "unsupported_broker",
            "provider": "poems",
            "name": "POEMS aggregate value",
            "currency": "SGD",
            "estimated_value": 10000.0,
            "valuation_date": "2026-06-14",
            "valuation_source": "api aggregate",
            "liquidity_bucket": "liquid",
            "risk_bucket": "equity",
            "notes": "Fixture only.",
        }
    )
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert not result.is_valid
    codes = [issue.code for issue in result.errors]
    assert codes.count(WarningCode.UNSUPPORTED_PROVIDER_MANUAL_ONLY) == 2


def test_singpass_automation_markers_forbidden() -> None:
    payload = _valid_payload()
    payload["source_note"] = "SingPass automation export"
    result = validate_manual_snapshot_payload(payload, as_of_date=date(2026, 6, 14))
    assert not result.is_valid
    assert WarningCode.SINGPASS_AUTOMATION_BLOCKED in {issue.code for issue in result.errors}


def test_manual_snapshot_normalizes_into_asset_ledger(tmp_path) -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, FIXTURE))
    snapshot = provider._sync()
    rows = normalize_snapshot(snapshot)
    assert snapshot.has_data()
    assert len(rows) == 5
    assert {row.asset_type for row in rows} >= {
        "residential_property",
        "cpf_oa",
        "unsupported_broker",
        "insurance_cash_value",
        "mortgage",
    }
    mortgage = next(row for row in rows if row.asset_type == "mortgage")
    assert mortgage.market_value == -400000.0

    output_path = tmp_path / "normalized_asset_ledger.csv"
    write_normalized_asset_ledger(output_path, rows)
    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == LEDGER_FIELDNAMES
        assert len(list(reader)) == 5


def test_raw_account_ids_remain_absent_from_manual_workflow_outputs(tmp_path) -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, FIXTURE))
    rows = normalize_snapshot(provider._sync())
    output_path = tmp_path / "normalized_asset_ledger.csv"
    write_normalized_asset_ledger(output_path, rows)
    text = output_path.read_text(encoding="utf-8")
    assert "manual_snapshot:asset" not in text
    assert "manual_snapshot:liability" not in text
    assert "account_id_hash" in text


def test_manual_snapshot_cli_template_and_validation(tmp_path) -> None:
    template_path = tmp_path / "manual_snapshot_template.json"
    write_result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--write-manual-template",
            str(template_path),
        ],
        cwd=ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert write_result.returncode == 0
    assert template_path.exists()

    validate_result = subprocess.run(
        [
            sys.executable,
            "scripts/personal_cfo_agent.py",
            "--validate-manual-snapshot",
            str(FIXTURE),
        ],
        cwd=ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate_result.returncode == 0
    assert "Manual snapshot validation passed." in validate_result.stdout


def test_manual_snapshots_directory_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-v", "manual_snapshots/my_snapshot.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "manual_snapshots/" in result.stdout


def _valid_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write_payload(tmp_path, payload: dict) -> Path:
    path = tmp_path / "manual_snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
