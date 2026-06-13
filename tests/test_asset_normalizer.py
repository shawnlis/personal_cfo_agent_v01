from __future__ import annotations

import csv
from pathlib import Path

from personal_cfo_agent.asset_ledger import write_normalized_asset_ledger
from personal_cfo_agent.config import load_manual_config
from personal_cfo_agent.models import LEDGER_FIELDNAMES, WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.providers import ManualSnapshotProvider


FIXTURE = Path("tests/fixtures/manual_snapshot_sample.json")
FULL_ACCOUNT_IDS = [
    "TEST-BROKER-ACCOUNT-123456789",
    "TEST-PROPERTY-ACCOUNT-987654321",
    "TEST-MORTGAGE-ACCOUNT-555555555",
]


def test_manual_snapshot_provider_loads_fixture_data() -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, FIXTURE))
    snapshot = provider.sync()
    assert snapshot.has_data()
    assert len(snapshot.accounts) == 2
    assert len(snapshot.cash) == 1
    assert len(snapshot.positions) == 2
    assert len(snapshot.balances) == 1


def test_normalizer_produces_stable_ledger_schema(tmp_path) -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, FIXTURE))
    rows = normalize_snapshot(provider.sync())
    assert len(rows) == 4
    assert all(row.account_id_hash.startswith("acct_") for row in rows)
    assert all(WarningCode.ACCOUNT_ID_HASHED in row.warning_codes for row in rows)

    output_path = tmp_path / "normalized_asset_ledger.csv"
    write_normalized_asset_ledger(output_path, rows)
    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == LEDGER_FIELDNAMES
        csv_rows = list(reader)
    assert len(csv_rows) == 4


def test_full_account_ids_do_not_appear_in_ledger_outputs(tmp_path) -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, FIXTURE))
    rows = normalize_snapshot(provider.sync())
    output_path = tmp_path / "normalized_asset_ledger.csv"
    write_normalized_asset_ledger(output_path, rows)
    output_text = output_path.read_text(encoding="utf-8")
    for account_id in FULL_ACCOUNT_IDS:
        assert account_id not in output_text
