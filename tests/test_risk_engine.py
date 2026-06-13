from __future__ import annotations

from pathlib import Path

from personal_cfo_agent.config import load_manual_config
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.normalizer import normalize_snapshot
from personal_cfo_agent.providers import ManualSnapshotProvider
from personal_cfo_agent.risk_engine import calculate_risk_summary


FIXTURE = Path("tests/fixtures/manual_snapshot_sample.json")


def test_risk_engine_calculates_v01_summary_metrics() -> None:
    provider = ManualSnapshotProvider(load_manual_config({}, FIXTURE))
    rows = normalize_snapshot(provider.sync())
    summary = calculate_risk_summary(rows, expected_provider_count=4, as_of_date="20260614")

    assert summary.total_assets == 1037000.00
    assert summary.total_liabilities == 400000.00
    assert summary.net_worth == 637000.00
    assert summary.liquid_assets == 37000.00
    assert summary.investable_assets == 37000.00
    assert summary.provider_coverage_ratio == 0.25
    assert summary.manual_asset_share == 1.0
    assert summary.currency_exposure["USD"] == 37000.00
    assert summary.currency_exposure["SGD"] == 600000.00
    assert WarningCode.STALE_SOURCE_DATA in summary.warning_codes
