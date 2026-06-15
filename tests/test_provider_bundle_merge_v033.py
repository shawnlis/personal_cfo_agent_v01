from __future__ import annotations

import csv
import json
import subprocess
from datetime import date
from pathlib import Path

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import (
    MERGED_LEDGER_FIELDNAMES,
    merge_provider_bundles,
)
from personal_cfo_agent.runner import main


ROOT = Path(__file__).resolve().parents[1]
RAW_ACCOUNT_ID = "DU123456789"


def test_manual_and_ibkr_synthetic_merge(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "manual_snapshot", "manual_bundle", [_row("manual_snapshot", "SGD")])
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_row("ibkr", "AAPL")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    rows = _read_merged_rows(result.output_paths["merged_normalized_ledger"])
    assert len(rows) == 2
    assert result.provider_counts == {"ibkr": 1, "manual_snapshot": 1}
    assert rows[0].keys() == set(MERGED_LEDGER_FIELDNAMES)


def test_ibkr_and_tiger_synthetic_merge_preserves_same_symbol(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [_row("ibkr", "AAPL")])
    _write_bundle(input_root, "tiger", "tiger_bundle", [_row("tiger", "AAPL")])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    rows = _read_merged_rows(result.output_paths["merged_normalized_ledger"])
    assert len(rows) == 2
    assert {row["provider"] for row in rows} == {"ibkr", "tiger"}
    assert WarningCode.POSSIBLE_DUPLICATE_POSITION not in result.warning_codes


def test_ibkr_tiger_moomoo_synthetic_merge(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    for provider, symbol in [("ibkr", "AAPL"), ("tiger", "MSFT"), ("moomoo", "HKD")]:
        _write_bundle(input_root, provider, f"{provider}_bundle", [_row(provider, symbol)])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert result.row_count == 3
    assert result.provider_counts == {"ibkr": 1, "moomoo": 1, "tiger": 1}


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

    rows = _read_merged_rows(result.output_paths["merged_normalized_ledger"])
    assert WarningCode.POSSIBLE_DUPLICATE_POSITION in result.warning_codes
    assert all("POSSIBLE_DUPLICATE_POSITION" in row["merge_warnings"] for row in rows)


def test_missing_account_symbol_currency_warns(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    row = _row("ibkr", "")
    row["account_id_hash"] = ""
    row["currency"] = ""
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [row])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert WarningCode.ACCOUNT_HASH_MISSING in result.warning_codes
    assert WarningCode.SYMBOL_MISSING in result.warning_codes
    assert WarningCode.CURRENCY_MISSING in result.warning_codes


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


def test_empty_provider_ledger_warns(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(input_root, "ibkr", "ibkr_bundle", [])

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert WarningCode.EMPTY_PROVIDER_LEDGER in result.warning_codes
    assert result.row_count == 0


def test_provider_summary_missing_warns(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    _write_bundle(
        input_root,
        "ibkr",
        "ibkr_bundle",
        [_row("ibkr", "AAPL")],
        write_summary=False,
    )

    result = merge_provider_bundles(
        input_root=input_root,
        out_dir=tmp_path / "reports" / "merged",
        today=date(2026, 6, 15),
    )

    assert WarningCode.PROVIDER_SUMMARY_MISSING in result.warning_codes


def test_fixture_mode_cli_generates_ignored_reports_and_no_raw_ids(
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
    assert "Merged normalized rows: 5" in captured
    output_text = "\n".join(path.read_text(encoding="utf-8") for path in out_dir.glob("*.*"))
    assert RAW_ACCOUNT_ID not in output_text
    assert "place_order" not in output_text
    assert "transfer_cash" not in output_text
    assert "buy" not in output_text.lower()
    assert "sell" not in output_text.lower()
    assert "recommendation" not in output_text.lower()
    assert (out_dir / "merged_normalized_ledger.csv").exists()
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
            "reports/personal_cfo_agent/merged_v033/merged_normalized_ledger.csv",
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
        "asset_type",
        "symbol",
        "name",
        "quantity",
        "currency",
        "market_value",
        "cost_basis",
        "average_cost",
        "unrealized_pnl",
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


def _row(
    provider: str,
    symbol: str,
    *,
    name: str = "Synthetic asset",
    as_of: str = "2026-06-15",
) -> dict[str, str]:
    currency = "SGD" if symbol == "SGD" else "USD"
    return {
        "provider": provider,
        "account_id_hash": f"acct_{provider}_fixture_hash",
        "asset_type": "cash" if symbol in {"SGD", "HKD"} else "equity",
        "symbol": symbol,
        "name": name,
        "quantity": "1",
        "currency": currency,
        "market_value": "100.00",
        "cost_basis": "90.00",
        "average_cost": "90.00",
        "unrealized_pnl": "10.00",
        "source_timestamp": as_of,
        "source_confidence": "synthetic_fixture",
        "warning_codes": "ACCOUNT_ID_HASHED",
        "notes": "",
    }


def _read_merged_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
