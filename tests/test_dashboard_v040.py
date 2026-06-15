from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest

from personal_cfo_agent.dashboard_v2 import write_dashboard_v2
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import (
    ACCOUNT_NAV_FIELDNAMES,
    POSITION_LEDGER_FIELDNAMES,
    merge_provider_bundles,
)
from personal_cfo_agent.runner import build_arg_parser, main


ROOT = Path(__file__).resolve().parents[1]
RAW_ACCOUNT_ID = "SYNTHETIC_RAW_ACCOUNT_IDENTIFIER"
FORBIDDEN_REPORT_PHRASES = (
    "buy",
    "sell",
    "hold",
    "retire now",
    "increase risk",
    "reduce risk",
    "recommended portfolio",
    "optimal allocation",
)


def test_dashboard_v2_reads_v033_fixture_account_nav_ledger(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    merge_provider_bundles(input_root=None, out_dir=merged_dir, fixture_mode=True)

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")

    assert result.generated
    assert result.account_count == 4
    assert result.provider_count == 4
    assert WarningCode.DASHBOARD_V2_GENERATED_WITH_WARNINGS in result.warning_codes


def test_dashboard_v2_produces_expected_output_files(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    merge_provider_bundles(input_root=None, out_dir=merged_dir, fixture_mode=True)

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")

    assert set(result.output_paths) == {
        "markdown_report",
        "dashboard_summary",
        "account_nav_dashboard",
        "provider_nav_summary",
        "position_drilldown",
        "dashboard_warnings",
    }
    for path in result.output_paths.values():
        assert path.exists()


def test_dashboard_v2_account_nav_is_primary_source(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    _write_dashboard_input(
        merged_dir,
        account_rows=[
            _account_row("ibkr", account_nav="1000.00", nav_source="provider_reported")
        ],
        position_rows=[
            _position_row("ibkr", market_value="99999.00"),
        ],
    )

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")
    provider_rows = _read_rows(result.output_paths["provider_nav_summary"])

    assert provider_rows[0]["account_nav_total"] == "1000.00"
    assert result.position_count == 1


def test_dashboard_v2_missing_position_ledger_warns_but_generates(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    _write_dashboard_input(
        merged_dir,
        account_rows=[_account_row("manual_snapshot", account_nav="1000.00")],
        position_rows=None,
    )

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")

    assert result.generated
    assert "position_drilldown" not in result.output_paths
    assert WarningCode.DASHBOARD_V2_POSITION_LEDGER_MISSING in result.warning_codes


def test_dashboard_v2_missing_provider_summary_warns_clearly(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    _write_dashboard_input(
        merged_dir,
        account_rows=[_account_row("moomoo", account_nav="1000.00")],
        write_provider_summary=False,
    )

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")

    assert result.generated
    assert WarningCode.DASHBOARD_V2_PROVIDER_SUMMARY_MISSING in result.warning_codes


def test_dashboard_v2_empty_account_nav_ledger_fails_closed(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    _write_csv(merged_dir / "merged_account_nav_ledger.csv", ACCOUNT_NAV_FIELDNAMES, [])

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")

    assert not result.generated
    assert result.output_dir is None
    assert WarningCode.DASHBOARD_V2_ACCOUNT_NAV_EMPTY in result.warning_codes


def test_dashboard_v2_surfaces_mixed_stale_and_reconciliation_warnings(
    tmp_path: Path,
) -> None:
    merged_dir = tmp_path / "merged"
    _write_dashboard_input(
        merged_dir,
        account_rows=[
            _account_row(
                "ibkr",
                account_nav="1000.00",
                as_of_date="2020-01-01",
                warning_codes="STALE_PROVIDER_BUNDLE;MIXED_AS_OF_DATES;ACCOUNT_NAV_RECONCILIATION_MISMATCH",
            )
        ],
        summary_warnings=[
            "STALE_PROVIDER_BUNDLE",
            "MIXED_AS_OF_DATES",
            "ACCOUNT_NAV_RECONCILIATION_MISMATCH",
        ],
    )

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")

    assert WarningCode.DASHBOARD_V2_STALE_DATA_WARNING in result.warning_codes
    assert WarningCode.DASHBOARD_V2_MIXED_AS_OF_DATES in result.warning_codes
    assert WarningCode.DASHBOARD_V2_NAV_RECONCILIATION_WARNINGS in result.warning_codes


def test_dashboard_v2_outputs_exclude_raw_account_ids_and_recommendation_phrases(
    tmp_path: Path,
) -> None:
    merged_dir = tmp_path / "merged"
    _write_dashboard_input(
        merged_dir,
        account_rows=[_account_row("tiger", account_nav="1000.00")],
        account_source_map={
            "acct_tiger_fixture_hash": {
                "providers": ["tiger"],
                "source_bundle_ids": [RAW_ACCOUNT_ID],
            }
        },
    )

    result = write_dashboard_v2(merged_dir, tmp_path / "dashboard")
    combined_text = "\n".join(path.read_text(encoding="utf-8") for path in result.output_paths.values())
    lower_text = combined_text.lower()

    assert RAW_ACCOUNT_ID not in combined_text
    for phrase in FORBIDDEN_REPORT_PHRASES:
        assert phrase not in lower_text
    for marker in ("place_order", "transfer_cash", "withdraw_cash", "cancel_order"):
        assert marker not in lower_text


def test_dashboard_v2_cli_generates_fixture_dashboard(tmp_path: Path, capsys) -> None:
    merged_dir = tmp_path / "merged"
    merge_provider_bundles(input_root=None, out_dir=merged_dir, fixture_mode=True)
    out_dir = tmp_path / "dashboard"

    exit_code = main(["--dashboard-v2", "--input-dir", str(merged_dir), "--out-dir", str(out_dir)])
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO Dashboard v2 (offline)" in captured
    assert "Broker connections used: no" in captured
    assert (out_dir / "PERSONAL_CFO_DASHBOARD_V040.md").exists()
    assert (out_dir / "dashboard_v040_summary.json").exists()
    assert (out_dir / "account_nav_dashboard.csv").exists()
    assert (out_dir / "provider_nav_summary.csv").exists()
    assert (out_dir / "dashboard_warnings.md").exists()


def test_dashboard_v2_cli_rejects_live_and_discovery_modes() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--dashboard-v2" in option_strings
    assert "--input-dir" in option_strings

    with pytest.raises(SystemExit):
        main(
            [
                "--dashboard-v2",
                "--input-dir",
                "reports/personal_cfo_agent/merged_v033_fixture",
                "--out-dir",
                "reports/personal_cfo_agent/dashboard_v040_fixture",
                "--allow-live-read",
            ]
        )


def test_dashboard_v2_output_contract_is_under_ignored_reports_path() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/dashboard_v040_fixture/dashboard_v040_summary.json",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def _write_dashboard_input(
    merged_dir: Path,
    *,
    account_rows: list[dict[str, str]],
    position_rows: list[dict[str, str]] | None = None,
    write_provider_summary: bool = True,
    summary_warnings: list[str] | None = None,
    account_source_map: dict[str, object] | None = None,
) -> None:
    merged_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(merged_dir / "merged_account_nav_ledger.csv", ACCOUNT_NAV_FIELDNAMES, account_rows)
    if position_rows is not None:
        _write_csv(merged_dir / "merged_position_ledger.csv", POSITION_LEDGER_FIELDNAMES, position_rows)
    warnings = summary_warnings or []
    (merged_dir / "merged_account_nav_summary.json").write_text(
        json.dumps({"warning_codes": warnings}), encoding="utf-8"
    )
    if write_provider_summary:
        providers = sorted({row["provider"] for row in account_rows})
        (merged_dir / "merged_provider_summary.json").write_text(
            json.dumps(
                {
                    "bundle_results": [
                        {"provider": provider, "status": "imported"}
                        for provider in providers
                    ],
                    "warning_codes": warnings,
                }
            ),
            encoding="utf-8",
        )
    (merged_dir / "account_source_map.json").write_text(
        json.dumps(account_source_map or {}), encoding="utf-8"
    )
    (merged_dir / "merge_warnings.md").write_text(
        "\n".join(f"- {warning}" for warning in warnings), encoding="utf-8"
    )


def _account_row(
    provider: str,
    *,
    account_nav: str,
    nav_source: str = "derived_from_cash_plus_positions",
    as_of_date: str = "2026-06-15",
    warning_codes: str = "",
) -> dict[str, str]:
    return {
        "provider": provider,
        "account_id_hash": f"acct_{provider}_fixture_hash",
        "source_bundle_id": f"{provider}_source",
        "source_snapshot_id": "",
        "as_of_date": as_of_date,
        "base_currency": "USD",
        "account_nav": account_nav,
        "total_assets": account_nav,
        "cash_total": "",
        "securities_market_value": "",
        "margin_or_debt": "",
        "buying_power": "",
        "provider_reported_nav_available": "yes" if nav_source == "provider_reported" else "no",
        "nav_source": nav_source,
        "source_confidence": "synthetic_fixture",
        "warning_codes": warning_codes,
    }


def _position_row(provider: str, *, market_value: str) -> dict[str, str]:
    return {
        "provider": provider,
        "account_id_hash": f"acct_{provider}_fixture_hash",
        "source_bundle_id": f"{provider}_source",
        "source_snapshot_id": "",
        "asset_type": "equity",
        "symbol": "SYNTH",
        "name": "Synthetic position",
        "currency": "USD",
        "quantity": "1",
        "market_value": market_value,
        "cost_basis": "1.00",
        "average_cost": "1.00",
        "unrealized_pnl": "",
        "as_of_date": "2026-06-15",
        "source_confidence": "synthetic_fixture",
        "normalization_warnings": "",
        "merge_warnings": "",
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
