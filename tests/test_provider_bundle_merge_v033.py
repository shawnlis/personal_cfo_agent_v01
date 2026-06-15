from __future__ import annotations

import csv
import json
import subprocess
from datetime import date
from pathlib import Path

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import (
    ACCOUNT_NAV_FIELDNAMES,
    POSITION_LEDGER_FIELDNAMES,
    merge_provider_bundles,
)
from personal_cfo_agent.runner import main


ROOT = Path(__file__).resolve().parents[1]
RAW_ACCOUNT_ID = "DU123456789"


def test_account_nav_ledger_generated_from_manual_and_ibkr(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "manual_snapshot", "manual_bundle", [_row("manual_snapshot", "SGD")])
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_account_nav_row("ibkr")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    account_rows = _read_rows(result.output_paths["merged_account_nav_ledger"])
    assert len(account_rows) == 2
    assert account_rows[0].keys() == set(ACCOUNT_NAV_FIELDNAMES)
    assert result.provider_counts == {"ibkr": 1, "manual_snapshot": 1}


def test_account_nav_ledger_generated_from_ibkr_tiger_moomoo(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    for provider in ("ibkr", "tiger", "moomoo"):
        _write_bundle(input_root, provider, f"{provider}_bundle", [_account_nav_row(provider)])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    account_rows = _read_rows(result.output_paths["merged_account_nav_ledger"])
    assert len(account_rows) == 3
    assert {row["provider"] for row in account_rows} == {"ibkr", "tiger", "moomoo"}


def test_provider_reported_nav_is_primary_source(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_account_nav_row("ibkr", nav="1000.00")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    account_row = _read_rows(result.output_paths["merged_account_nav_ledger"])[0]
    assert account_row["account_nav"] == "1000.00"
    assert account_row["provider_reported_nav_available"] == "yes"
    assert account_row["nav_source"] == "provider_reported"
    assert WarningCode.ACCOUNT_NAV_PROVIDER_REPORTED in result.warning_codes


def test_derived_nav_from_cash_and_positions_warns(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(
        input_root,
        "tiger",
        "tiger_bundle",
        [
            _row("tiger", "USD", asset_type="cash", market_value="100.00"),
            _row("tiger", "AAPL", asset_type="equity", market_value="200.00"),
        ],
    )

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    account_row = _read_rows(result.output_paths["merged_account_nav_ledger"])[0]
    assert account_row["account_nav"] == "300.00"
    assert account_row["nav_source"] == "derived_from_cash_plus_positions"
    assert WarningCode.ACCOUNT_NAV_DERIVED in result.warning_codes
    assert WarningCode.ACCOUNT_NAV_MISSING in result.warning_codes


def test_missing_position_rows_does_not_fail_account_nav_merge(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "moomoo", "moomoo_bundle", [_account_nav_row("moomoo")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert result.account_nav_row_count == 1
    assert result.position_row_count == 0
    assert WarningCode.POSITION_ROWS_MISSING in result.warning_codes
    account_row = _read_rows(result.output_paths["merged_account_nav_ledger"])[0]
    assert account_row["nav_source"] == "provider_reported"


def test_nav_reconciliation_ok_and_mismatch(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(
        input_root,
        "ibkr",
        "ibkr_ok",
        [
            _account_nav_row("ibkr", account_hash="acct_ok", nav="300.00"),
            _row("ibkr", "USD", account_hash="acct_ok", asset_type="cash", market_value="100.00"),
            _row("ibkr", "AAPL", account_hash="acct_ok", asset_type="equity", market_value="200.00"),
        ],
    )
    _write_bundle(
        input_root,
        "tiger",
        "tiger_mismatch",
        [
            _account_nav_row("tiger", account_hash="acct_bad", nav="999.00"),
            _row("tiger", "USD", account_hash="acct_bad", asset_type="cash", market_value="100.00"),
            _row("tiger", "MSFT", account_hash="acct_bad", asset_type="equity", market_value="200.00"),
        ],
    )

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert WarningCode.ACCOUNT_NAV_RECONCILIATION_OK in result.warning_codes
    assert WarningCode.ACCOUNT_NAV_RECONCILIATION_MISMATCH in result.warning_codes


def test_same_symbol_across_providers_preserved(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_row("ibkr", "AAPL")])
    _write_bundle(input_root, "tiger", "tiger_bundle", [_row("tiger", "AAPL")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    position_rows = _read_rows(result.output_paths["merged_position_ledger"])
    assert len(position_rows) == 2
    assert {row["provider"] for row in position_rows} == {"ibkr", "tiger"}
    assert WarningCode.POSSIBLE_DUPLICATE_POSITION not in result.warning_codes


def test_same_symbol_within_same_provider_account_source_warns(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(
        input_root,
        "ibkr",
        "ibkr_bundle",
        [_row("ibkr", "AAPL"), _row("ibkr", "AAPL", name="Apple duplicate")],
    )

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    position_rows = _read_rows(result.output_paths["merged_position_ledger"])
    assert WarningCode.POSSIBLE_DUPLICATE_POSITION in result.warning_codes
    assert len(position_rows) == 2
    assert all("POSSIBLE_DUPLICATE_POSITION" in row["merge_warnings"] for row in position_rows)


def test_schema_summary_missing_and_empty_status_are_distinct(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "empty_bundle", [])
    _write_schema_mismatch_bundle(input_root / "bad_schema")
    _write_bundle(
        input_root,
        "tiger",
        "summary_missing",
        [_row("tiger", "MSFT")],
        write_summary=False,
    )

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    summary = json.loads(
        result.output_paths["merged_provider_summary"].read_text(encoding="utf-8")
    )
    statuses = {entry["source_bundle_id"]: entry["status"] for entry in summary["bundle_results"]}
    assert statuses["empty_bundle"] == "empty_ledger"
    assert statuses["bad_schema"] == "schema_mismatch"
    assert statuses["summary_missing"] == "imported_with_warnings"
    assert WarningCode.PROVIDER_SCHEMA_MISMATCH in result.warning_codes
    assert WarningCode.PROVIDER_SUMMARY_MISSING in result.warning_codes
    assert WarningCode.EMPTY_PROVIDER_LEDGER in result.warning_codes


def test_missing_account_symbol_currency_and_as_of_warn(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    row = _row("ibkr", "")
    row["account_id_hash"] = ""
    row["currency"] = ""
    row["source_timestamp"] = ""
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [row])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert WarningCode.ACCOUNT_HASH_MISSING in result.warning_codes
    assert WarningCode.SYMBOL_MISSING in result.warning_codes
    assert WarningCode.CURRENCY_MISSING in result.warning_codes
    assert WarningCode.AS_OF_DATE_MISSING in result.warning_codes


def test_mixed_as_of_date_and_stale_bundle_warn(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_row("ibkr", "AAPL", as_of="2020-01-01")])
    _write_bundle(input_root, "tiger", "tiger_bundle", [_row("tiger", "MSFT", as_of="2026-06-15")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert WarningCode.STALE_PROVIDER_BUNDLE in result.warning_codes
    assert WarningCode.MIXED_AS_OF_DATES in result.warning_codes


def test_missing_input_root_warns_and_writes_empty_outputs(tmp_path: Path) -> None:
    result = merge_provider_bundles(
        input_root=tmp_path / "missing",
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert result.account_nav_row_count == 0
    assert WarningCode.PROVIDER_BUNDLE_MISSING in result.warning_codes
    assert (tmp_path / "reports" / "merged" / "merged_account_nav_ledger.csv").exists()


def test_fixture_mode_cli_generates_expected_outputs_and_no_raw_ids(
    tmp_path: Path, capsys
) -> None:
    out_dir = tmp_path / "reports" / "personal_cfo_agent" / "merged_v033_fixture"
    exit_code = main(
        [
            "--merge-provider-bundles",
            "--fixture-mode",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Broker connections used: no" in captured
    assert "Account NAV rows: 4" in captured
    output_text = "\n".join(path.read_text(encoding="utf-8") for path in out_dir.glob("*.*"))
    assert RAW_ACCOUNT_ID not in output_text
    assert "place_order" not in output_text
    assert "transfer_cash" not in output_text
    assert "order placement" not in output_text.lower()
    assert "cash transfer" not in output_text.lower()
    assert "recommendation" not in output_text.lower()
    assert (out_dir / "merged_account_nav_ledger.csv").exists()
    assert (out_dir / "merged_account_nav_summary.json").exists()
    assert (out_dir / "merged_position_ledger.csv").exists()
    assert (out_dir / "merged_provider_summary.json").exists()
    assert (out_dir / "account_source_map.json").exists()
    assert (out_dir / "merge_warnings.md").exists()
    assert (out_dir / "MERGED_LEDGER_V033.md").exists()


def test_generated_reports_path_is_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/merged_v033/merged_account_nav_ledger.csv",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_no_raw_account_ids_in_account_source_map(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    row = _row("ibkr", "AAPL")
    row["notes"] = RAW_ACCOUNT_ID
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [row])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    account_map = result.output_paths["account_source_map"].read_text(encoding="utf-8")
    assert RAW_ACCOUNT_ID not in account_map


def test_position_ledger_schema_is_best_effort(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_row("ibkr", "AAPL")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    position_rows = _read_rows(result.output_paths["merged_position_ledger"])
    assert position_rows[0].keys() == set(POSITION_LEDGER_FIELDNAMES)
    assert WarningCode.POSITION_LEDGER_BEST_EFFORT in result.warning_codes


def _write_bundle(
    input_root: Path,
    provider: str,
    bundle_name: str,
    rows: list[dict[str, str]],
    *,
    write_summary: bool = True,
) -> Path:
    bundle_dir = input_root / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "provider",
        "account_id_hash",
        "source_bundle_id",
        "source_snapshot_id",
        "asset_type",
        "symbol",
        "name",
        "quantity",
        "currency",
        "market_value",
        "cost_basis",
        "average_cost",
        "unrealized_pnl",
        "account_nav",
        "total_assets",
        "cash_total",
        "securities_market_value",
        "margin_or_debt",
        "buying_power",
        "source_timestamp",
        "source_confidence",
        "warning_codes",
        "notes",
    ]
    with (bundle_dir / "normalized_asset_ledger.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    if write_summary:
        (bundle_dir / "provider_sync_summary.json").write_text(
            json.dumps({"provider": provider, "normalized_row_count": len(rows)}),
            encoding="utf-8",
        )
    return bundle_dir


def _write_schema_mismatch_bundle(bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    with (bundle_dir / "normalized_asset_ledger.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "currency"])
        writer.writeheader()
        writer.writerow({"symbol": "AAPL", "currency": "USD"})


def _account_nav_row(
    provider: str,
    *,
    account_hash: str | None = None,
    nav: str = "1000.00",
) -> dict[str, str]:
    row = _row(
        provider,
        "NAV",
        account_hash=account_hash,
        asset_type="account_nav",
        market_value=nav,
    )
    row["account_nav"] = nav
    row["total_assets"] = nav
    row["cash_total"] = ""
    row["securities_market_value"] = ""
    return row


def _row(
    provider: str,
    symbol: str,
    *,
    account_hash: str | None = None,
    asset_type: str = "equity",
    name: str = "Synthetic asset",
    market_value: str = "100.00",
    as_of: str = "2026-06-15",
) -> dict[str, str]:
    currency = "SGD" if symbol == "SGD" else "USD"
    account_hash = account_hash or f"acct_{provider}_fixture_hash"
    return {
        "provider": provider,
        "account_id_hash": account_hash,
        "source_bundle_id": f"{provider}_source",
        "source_snapshot_id": "",
        "asset_type": asset_type,
        "symbol": symbol,
        "name": name,
        "quantity": "1",
        "currency": currency,
        "market_value": market_value,
        "cost_basis": "90.00" if asset_type not in {"cash", "account_nav"} else "",
        "average_cost": "90.00" if asset_type not in {"cash", "account_nav"} else "",
        "unrealized_pnl": "10.00" if asset_type not in {"cash", "account_nav"} else "",
        "account_nav": "",
        "total_assets": "",
        "cash_total": "",
        "securities_market_value": "",
        "margin_or_debt": "",
        "buying_power": "",
        "source_timestamp": as_of,
        "source_confidence": "synthetic_fixture",
        "warning_codes": "ACCOUNT_ID_HASHED",
        "notes": "",
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
