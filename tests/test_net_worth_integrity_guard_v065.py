from __future__ import annotations

import csv
import json
from pathlib import Path

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.net_worth_integrity_guard import (
    run_net_worth_integrity_guard,
)
from personal_cfo_agent.provider_bundle_merge import ACCOUNT_NAV_FIELDNAMES


PRIVATE_MARKER = "acct_private_marker"


def test_integrity_guard_allows_complete_provider_nav(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[
            _account_row("ibkr", "1000.00", "SGD"),
            _account_row("moomoo", "2000.00", "SGD"),
        ],
        total="3000.00",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr", "moomoo"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[],
    )

    assert result.generated is True
    assert result.ready_to_confirm is True
    assert result.blocking_warning_codes == []
    assert WarningCode.INTEGRITY_GUARD_OK in result.warning_codes
    assert WarningCode.INTEGRITY_CONFIRMED_HISTORY_MISSING in result.warning_codes

    summary = json.loads(result.output_paths["summary"].read_text(encoding="utf-8"))
    assert summary["ready_to_confirm"] is True
    assert summary["provider_checks"]["ibkr"]["status"] == "ok"
    assert summary["current_total_net_worth_available"] is True
    assert "current_total_net_worth" not in summary


def test_integrity_guard_blocks_missing_requested_broker(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[_account_row("ibkr", "1000.00", "SGD")],
        total="1000.00",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr", "moomoo"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[],
    )

    assert result.ready_to_confirm is False
    assert WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING in result.blocking_warning_codes
    assert WarningCode.INTEGRITY_GUARD_BLOCKED in result.warning_codes


def test_integrity_guard_blocks_derived_provider_nav_for_requested_broker(
    tmp_path: Path,
) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[
            _account_row(
                "ibkr",
                "1000.00",
                "SGD",
                provider_reported="no",
                nav_source="derived",
            )
        ],
        total="1000.00",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[],
    )

    assert result.ready_to_confirm is False
    assert WarningCode.INTEGRITY_PROVIDER_NAV_MISSING in result.blocking_warning_codes


def test_integrity_guard_blocks_mixed_currency_without_fx(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[
            _account_row("ibkr", "1000.00", "USD"),
            _account_row("moomoo", "2000.00", "SGD"),
        ],
        total="3000.00",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr", "moomoo"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[],
    )

    assert result.ready_to_confirm is False
    assert WarningCode.INTEGRITY_MIXED_CURRENCY_BLOCKED in result.blocking_warning_codes
    assert WarningCode.INTEGRITY_FX_REQUIRED in result.blocking_warning_codes


def test_integrity_guard_allows_mixed_currency_with_explicit_fx(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[
            _account_row("ibkr", "1000.00", "USD"),
            _account_row("moomoo", "2000.00", "SGD"),
        ],
        total="3000.00",
    )
    fx_rates = tmp_path / "fx_rates.json"
    fx_rates.write_text(
        json.dumps({"base_currency": "SGD", "rates_to_base": {"USD": "1.3", "SGD": "1.0"}}),
        encoding="utf-8",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr", "moomoo"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=fx_rates,
        upstream_warning_codes=[],
    )

    assert result.ready_to_confirm is True
    assert WarningCode.INTEGRITY_MIXED_CURRENCY_BLOCKED not in result.warning_codes


def test_integrity_guard_blocks_mixed_dates_and_stale_inputs(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[_account_row("ibkr", "1000.00", "SGD")],
        total="1000.00",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[
            WarningCode.MIXED_AS_OF_DATES,
            WarningCode.STALE_PROVIDER_BUNDLE,
        ],
    )

    assert WarningCode.INTEGRITY_MIXED_AS_OF_DATES in result.blocking_warning_codes
    assert WarningCode.INTEGRITY_STALE_PROVIDER_DATA in result.blocking_warning_codes


def test_integrity_guard_blocks_large_change_vs_confirmed_history(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[_account_row("ibkr", "5000.00", "SGD")],
        total="5000.00",
    )
    confirmed_dir = tmp_path / "confirmed"
    confirmed_dir.mkdir()
    _write_rows(
        confirmed_dir / "net_worth_history.csv",
        ["snapshot_date", "snapshot_id", "base_currency", "total_account_nav"],
        [
            {
                "snapshot_date": "2026-06-20",
                "snapshot_id": "confirmed",
                "base_currency": "SGD",
                "total_account_nav": "1000.00",
            }
        ],
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[],
        confirmed_history_dir=confirmed_dir,
        nav_change_abs_threshold=500.0,
    )

    assert result.ready_to_confirm is False
    assert WarningCode.INTEGRITY_NAV_CHANGE_REVIEW_REQUIRED in result.blocking_warning_codes


def test_integrity_guard_outputs_redact_account_hashes(tmp_path: Path) -> None:
    refresh_dir = _write_refresh(
        tmp_path,
        account_rows=[_account_row("ibkr", "1000.00", "SGD", account_hash=PRIVATE_MARKER)],
        total="1000.00",
    )

    result = run_net_worth_integrity_guard(
        refresh_dir=refresh_dir,
        out_dir=tmp_path / "guard",
        providers_requested=["ibkr"],
        merge_result=None,
        snapshot_result=None,
        dashboard_result=None,
        fx_rates_file=None,
        upstream_warning_codes=[],
    )

    for path in result.output_paths.values():
        assert PRIVATE_MARKER not in path.read_text(encoding="utf-8")


def _write_refresh(
    tmp_path: Path, *, account_rows: list[dict[str, str]], total: str
) -> Path:
    refresh_dir = tmp_path / "refresh"
    merged_dir = refresh_dir / "merged"
    snapshot_dir = refresh_dir / "snapshots"
    dashboard_dir = refresh_dir / "dashboard"
    merged_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    _write_rows(merged_dir / "merged_account_nav_ledger.csv", ACCOUNT_NAV_FIELDNAMES, account_rows)
    _write_rows(
        snapshot_dir / "net_worth_history.csv",
        ["snapshot_date", "snapshot_id", "base_currency", "total_account_nav"],
        [
            {
                "snapshot_date": "2026-06-21",
                "snapshot_id": "review",
                "base_currency": "SGD",
                "total_account_nav": total,
            }
        ],
    )
    _write_rows(
        dashboard_dir / "net_worth_progress.csv",
        ["snapshot_date", "snapshot_id", "base_currency", "integrated_net_worth"],
        [
            {
                "snapshot_date": "2026-06-21",
                "snapshot_id": "review",
                "base_currency": "SGD",
                "integrated_net_worth": total,
            }
        ],
    )
    return refresh_dir


def _account_row(
    provider: str,
    account_nav: str,
    currency: str,
    *,
    provider_reported: str = "yes",
    nav_source: str = "provider_reported",
    account_hash: str = "acct_hash",
) -> dict[str, str]:
    return {
        "provider": provider,
        "account_id_hash": account_hash,
        "account_nav_bucket": "liquid_investment_assets",
        "source_bundle_id": f"{provider}_bundle",
        "source_snapshot_id": f"{provider}_snapshot",
        "as_of_date": "2026-06-21",
        "base_currency": currency,
        "account_nav": account_nav,
        "total_assets": account_nav,
        "cash_total": "",
        "securities_market_value": "",
        "margin_or_debt": "",
        "buying_power": "",
        "provider_reported_nav_available": provider_reported,
        "nav_source": nav_source,
        "source_confidence": "test_fixture",
        "warning_codes": "",
    }


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
