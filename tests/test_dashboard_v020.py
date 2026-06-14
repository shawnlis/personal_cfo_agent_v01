from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest

from personal_cfo_agent.config import RuntimeConfig
from personal_cfo_agent.dashboard.dashboard_runner import build_dashboard
from personal_cfo_agent.dashboard.fire import calculate_fire, load_dashboard_assumptions
from personal_cfo_agent.dashboard.liquidity import calculate_liquidity
from personal_cfo_agent.dashboard.net_worth import calculate_net_worth
from personal_cfo_agent.dashboard.report_writer import DASHBOARD_STATEMENT, write_dashboard_bundle
from personal_cfo_agent.dashboard.stress import build_stress_scenarios
from personal_cfo_agent.models import (
    ConnectionMode,
    NormalizedAsset,
    ProviderLevel,
    ProviderStatus,
    WarningCode,
)
from personal_cfo_agent.runner import build_arg_parser, run


ROOT = Path(__file__).resolve().parents[1]
LEDGER_FIXTURE = ROOT / "tests" / "fixtures" / "dashboard_normalized_asset_ledger_v020.csv"
ASSUMPTIONS_FIXTURE = ROOT / "tests" / "fixtures" / "dashboard_assumptions_v020.json"
MANUAL_FIXTURE = ROOT / "tests" / "fixtures" / "manual_snapshot_workflow_v014.json"
RAW_MANUAL_FIXTURE = ROOT / "tests" / "fixtures" / "manual_snapshot" / "sample_manual_assets_v010.json"
FULL_ACCOUNT_IDS = (
    "TEST-BROKER-ACCOUNT-123456789",
    "TEST-PROPERTY-ACCOUNT-987654321",
    "TEST-MORTGAGE-ACCOUNT-555555555",
)
FORBIDDEN_REPORT_PHRASES = (
    "buy",
    "sell",
    "hold",
    "retire now",
    "you should retire",
    "increase risk",
    "reduce risk",
    "repay mortgage",
    "refinance",
    "switch allocation",
    "recommended portfolio",
    "optimal allocation",
    "you should invest",
    "you should save",
    "you should reduce spending",
)
REQUIRED_ASSUMPTION_KEYS = (
    "current_age",
    "target_fire_age",
    "annual_spending_target",
    "safe_withdrawal_rate",
    "expected_annual_return",
    "inflation_rate",
    "emergency_buffer_months",
    "base_currency",
)


def test_dashboard_consumes_normalized_ledger_fixture() -> None:
    dashboard = build_dashboard(
        _ledger_rows(),
        [_manual_status()],
        load_dashboard_assumptions(ASSUMPTIONS_FIXTURE),
        as_of_date="20260614",
    )
    assert dashboard["net_worth"]["total_assets"] == 1230000.0
    assert dashboard["liquidity"]["liquid_assets"] == 230000.0
    assert dashboard["fire"]["fire_number"] == 3000000.0


def test_net_worth_deterministic() -> None:
    summary = calculate_net_worth(_ledger_rows(), expected_provider_count=1)
    assert summary.total_assets == 1230000.0
    assert summary.total_liabilities == 400000.0
    assert summary.net_worth == 830000.0
    assert summary.currency_exposure == {"SGD": 680000.0, "USD": 150000.0}
    assert summary.provider_coverage == 1.0
    assert summary.manual_asset_share == 1.0


def test_liquidity_deterministic() -> None:
    assumptions = load_dashboard_assumptions(ASSUMPTIONS_FIXTURE)
    summary = calculate_liquidity(
        _ledger_rows(),
        assumptions.annual_spending_target,
        assumptions.emergency_buffer_months,
    )
    assert summary.liquid_assets == 230000.0
    assert summary.investable_assets == 230000.0
    assert summary.monthly_spending_target == 10000.0
    assert summary.emergency_buffer_target == 60000.0
    assert summary.liquidity_runway_months == 23.0


def test_fire_number_and_coverage_deterministic() -> None:
    assumptions = load_dashboard_assumptions(ASSUMPTIONS_FIXTURE)
    summary = calculate_fire(230000.0, assumptions)
    assert summary.fire_number == 3000000.0
    assert summary.fire_coverage_ratio == 0.0767
    assert summary.gap_to_fire == 2770000.0
    assert summary.target_years_remaining == 15.0


def test_stress_scenarios_generated() -> None:
    assumptions = load_dashboard_assumptions(ASSUMPTIONS_FIXTURE)
    scenarios = build_stress_scenarios(_ledger_rows(), assumptions)
    names = {row["scenario"] for row in scenarios}
    assert {
        "investment_assets_down_30",
        "property_down_20",
        "mortgage_rate_up_2",
        "income_down_30",
        "expenses_up_20",
        "combined_recession",
    } <= names
    combined = next(row for row in scenarios if row["scenario"] == "combined_recession")
    assert combined["net_worth"] == "576000.00"


def test_stale_and_manual_warnings_propagate() -> None:
    dashboard = build_dashboard(
        _ledger_rows(),
        [_manual_status()],
        load_dashboard_assumptions(ASSUMPTIONS_FIXTURE),
        as_of_date="20260614",
    )
    warnings = set(dashboard["warnings"])
    assert WarningCode.STALE_SOURCE_DATA.value in warnings
    assert WarningCode.MANUAL_VALUE_NEEDS_REVIEW.value in warnings
    assert WarningCode.NEEDS_REVIEW.value in warnings
    assert WarningCode.HIGH_PROPERTY_CONCENTRATION.value in warnings
    assert WarningCode.FIRE_GAP_LARGE.value in warnings


def test_report_contains_non_advice_statement_and_no_recommendation_language(tmp_path) -> None:
    dashboard = build_dashboard(
        _ledger_rows(),
        [_manual_status()],
        load_dashboard_assumptions(ASSUMPTIONS_FIXTURE),
        as_of_date="20260614",
    )
    output_paths = write_dashboard_bundle(tmp_path, dashboard)
    report_text = output_paths["markdown_report"].read_text(encoding="utf-8")
    assert DASHBOARD_STATEMENT in report_text
    _assert_no_forbidden_recommendation_phrases(output_paths.values())


def test_fire_assumptions_appear_in_json_and_markdown(tmp_path) -> None:
    dashboard = build_dashboard(
        _ledger_rows(),
        [_manual_status()],
        load_dashboard_assumptions(ASSUMPTIONS_FIXTURE),
        as_of_date="20260614",
    )
    output_paths = write_dashboard_bundle(tmp_path, dashboard)
    payload = json.loads(output_paths["net_worth_dashboard"].read_text(encoding="utf-8"))
    report_text = output_paths["markdown_report"].read_text(encoding="utf-8")

    assert "not forecasts" in report_text
    for key in REQUIRED_ASSUMPTION_KEYS:
        assert key in payload["assumptions"]
        assert key in report_text


def test_fire_gap_outputs_have_no_recommendation_phrases(tmp_path) -> None:
    dashboard = build_dashboard(
        _ledger_rows(),
        [_manual_status()],
        load_dashboard_assumptions(ASSUMPTIONS_FIXTURE),
        as_of_date="20260614",
    )
    output_paths = write_dashboard_bundle(tmp_path, dashboard)

    assert dashboard["fire"]["gap_to_fire"] == 2770000.0
    _assert_no_forbidden_recommendation_phrases(output_paths.values())


def test_raw_account_ids_absent_from_all_dashboard_outputs(tmp_path) -> None:
    result = run(
        RuntimeConfig(
            dashboard=True,
            manual_snapshot_path=RAW_MANUAL_FIXTURE,
            dashboard_assumptions_path=ASSUMPTIONS_FIXTURE,
            output_dir=tmp_path,
            as_of_date="20260614",
            env={},
        )
    )
    assert result.exit_code == 0
    assert set(result.output_paths) == {
        "markdown_report",
        "net_worth_dashboard",
        "asset_allocation",
        "liquidity_dashboard",
        "fire_progress",
        "liability_dashboard",
        "stress_scenarios",
        "dashboard_warnings",
    }
    combined_text = "\n".join(path.read_text(encoding="utf-8") for path in result.output_paths.values())
    for account_id in FULL_ACCOUNT_IDS:
        assert account_id not in combined_text
    assert "account_id_hash" in combined_text


def test_dashboard_has_no_production_csv_ledger_input() -> None:
    parser = build_arg_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    for option in ("--ledger-csv", "--normalized-ledger", "--csv-ledger"):
        assert option not in option_strings
        with pytest.raises(SystemExit):
            parser.parse_args(["--dashboard", option, str(LEDGER_FIXTURE)])


def test_dashboard_runner_writes_output_contract_from_provider_aggregation(tmp_path) -> None:
    result = run(
        RuntimeConfig(
            dashboard=True,
            manual_snapshot_path=MANUAL_FIXTURE,
            dashboard_assumptions_path=ASSUMPTIONS_FIXTURE,
            output_dir=tmp_path,
            as_of_date="20260614",
            env={},
        )
    )
    assert result.exit_code == 0
    assert result.output_dir == tmp_path
    assert set(result.output_paths) == {
        "markdown_report",
        "net_worth_dashboard",
        "asset_allocation",
        "liquidity_dashboard",
        "fire_progress",
        "liability_dashboard",
        "stress_scenarios",
        "dashboard_warnings",
    }
    for path in result.output_paths.values():
        assert path.exists()

    payload = json.loads(result.output_paths["net_worth_dashboard"].read_text(encoding="utf-8"))
    assert payload["statement"] == DASHBOARD_STATEMENT
    assert payload["net_worth"]["total_assets"] > 0


def test_dashboard_output_contract_is_under_ignored_reports_path() -> None:
    ignored_path = "reports/personal_cfo_agent/v020_dashboard_test/net_worth_dashboard.json"
    result = subprocess.run(
        ["git", "check-ignore", "-q", ignored_path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_dashboard_makes_no_network_call_by_default(tmp_path) -> None:
    result = run(RuntimeConfig(dashboard=True, output_dir=tmp_path, env={}))
    assert result.exit_code == 0
    assert result.output_dir is None
    assert result.output_paths == {}
    assert result.normalized_assets == []
    assert not any(tmp_path.iterdir())


def _assert_no_forbidden_recommendation_phrases(paths) -> None:
    combined_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    for phrase in FORBIDDEN_REPORT_PHRASES:
        assert phrase not in combined_text


def _ledger_rows() -> list[NormalizedAsset]:
    with LEDGER_FIXTURE.open(newline="", encoding="utf-8") as handle:
        return [_row_from_csv(row) for row in csv.DictReader(handle)]


def _row_from_csv(row: dict[str, str]) -> NormalizedAsset:
    return NormalizedAsset(
        provider=row["provider"],
        account_id_hash=row["account_id_hash"],
        asset_id=row["asset_id"],
        asset_type=row["asset_type"],
        symbol=row["symbol"],
        name=row["name"],
        quantity=_optional_float(row["quantity"]),
        currency=row["currency"] or None,
        market_value=_optional_float(row["market_value"]),
        cost_basis=_optional_float(row["cost_basis"]),
        unrealized_pnl=_optional_float(row["unrealized_pnl"]),
        liquidity_bucket=row["liquidity_bucket"],
        risk_bucket=row["risk_bucket"],
        source_timestamp=row["source_timestamp"],
        source_confidence=row["source_confidence"],
        needs_review=row["needs_review"] == "true",
        warning_codes=[
            WarningCode(code)
            for code in row["warning_codes"].split(";")
            if code
        ],
        notes=row["notes"],
    )


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def _manual_status() -> ProviderStatus:
    return ProviderStatus(
        provider_name="manual_snapshot",
        provider_level=ProviderLevel.LEVEL_0,
        connection_mode=ConnectionMode.FIXTURE,
    )
