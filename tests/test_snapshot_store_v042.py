from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.provider_bundle_merge import (
    ACCOUNT_NAV_FIELDNAMES,
    POSITION_LEDGER_FIELDNAMES,
    merge_provider_bundles,
)
from personal_cfo_agent.runner import build_arg_parser, main
from personal_cfo_agent.snapshot_store import (
    ACCOUNT_NAV_HISTORY_FIELDNAMES,
    NET_WORTH_HISTORY_FIELDNAMES,
    PROVIDER_NAV_HISTORY_FIELDNAMES,
    record_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_ACCOUNT_ID = "RAW_ACCOUNT_ID_SHOULD_NOT_APPEAR"
FORBIDDEN_MARKERS = (
    "place_order",
    "preview_order",
    "modify_order",
    "cancel_order",
    "order_list_query",
    "history_order_list_query",
    "deal_list_query",
    "history_deal_list_query",
    "transfer_cash",
    "withdraw_cash",
    "unlock_trade",
    "recommended portfolio",
    "optimal allocation",
    "buy ",
    "sell ",
)


def test_snapshot_manifest_generated_from_synthetic_merged_ledger(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(merge_dir, dashboard_dir)

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_synthetic_001",
        generated_at=_generated_at(),
    )

    assert result.generated
    manifest = json.loads(result.output_paths["snapshot_manifest"].read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == "snapshot_synthetic_001"
    assert manifest["schema_version"] == "v0.4.2"
    assert manifest["provider_count"] == 2
    assert manifest["account_count"] == 2
    assert manifest["total_account_nav_available"] == "yes"


def test_snapshot_history_files_created(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(merge_dir, dashboard_dir)

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_synthetic_002",
        generated_at=_generated_at(),
    )

    assert set(result.output_paths) == {
        "snapshot_manifest",
        "net_worth_history",
        "account_nav_history",
        "provider_nav_history",
        "snapshot_warnings",
        "markdown_report",
    }
    net_worth_rows = _read_rows(result.output_paths["net_worth_history"])
    account_rows = _read_rows(result.output_paths["account_nav_history"])
    provider_rows = _read_rows(result.output_paths["provider_nav_history"])
    assert net_worth_rows[0].keys() == set(NET_WORTH_HISTORY_FIELDNAMES)
    assert account_rows[0].keys() == set(ACCOUNT_NAV_HISTORY_FIELDNAMES)
    assert provider_rows[0].keys() == set(PROVIDER_NAV_HISTORY_FIELDNAMES)
    assert len(net_worth_rows) == 1
    assert len(account_rows) == 2
    assert len(provider_rows) == 2


def test_duplicate_snapshot_id_fails_closed(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    out_dir = tmp_path / "snapshots"
    _write_snapshot_inputs(merge_dir, dashboard_dir)

    first = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=out_dir,
        snapshot_id="snapshot_duplicate",
        generated_at=_generated_at(),
    )
    second = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=out_dir,
        snapshot_id="snapshot_duplicate",
        generated_at=_generated_at(),
    )

    assert first.generated
    assert not second.generated
    assert WarningCode.SNAPSHOT_ID_DUPLICATE in second.warning_codes
    assert len(_read_rows(out_dir / "net_worth_history.csv")) == 1


def test_distinct_snapshots_append_without_duplicate_headers_and_old_id_reuse_fails(
    tmp_path: Path,
) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    out_dir = tmp_path / "snapshots"
    _write_snapshot_inputs(merge_dir, dashboard_dir)

    first = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=out_dir,
        snapshot_id="snapshot_append_a",
        generated_at=_generated_at(),
    )
    second = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=out_dir,
        snapshot_id="snapshot_append_b",
        generated_at=_generated_at(),
    )
    duplicate_old = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=out_dir,
        snapshot_id="snapshot_append_a",
        generated_at=_generated_at(),
    )

    assert first.generated
    assert second.generated
    assert not duplicate_old.generated
    assert WarningCode.SNAPSHOT_ID_DUPLICATE in duplicate_old.warning_codes
    net_worth_text = (out_dir / "net_worth_history.csv").read_text(encoding="utf-8")
    account_text = (out_dir / "account_nav_history.csv").read_text(encoding="utf-8")
    provider_text = (out_dir / "provider_nav_history.csv").read_text(encoding="utf-8")
    assert net_worth_text.count("snapshot_date,snapshot_id") == 1
    assert account_text.count("snapshot_date,snapshot_id") == 1
    assert provider_text.count("snapshot_date,snapshot_id") == 1
    net_worth_rows = _read_rows(out_dir / "net_worth_history.csv")
    account_rows = _read_rows(out_dir / "account_nav_history.csv")
    provider_rows = _read_rows(out_dir / "provider_nav_history.csv")
    assert [row["snapshot_id"] for row in net_worth_rows] == [
        "snapshot_append_a",
        "snapshot_append_b",
    ]
    assert {row["snapshot_id"] for row in account_rows} == {
        "snapshot_append_a",
        "snapshot_append_b",
    }
    assert {row["snapshot_id"] for row in provider_rows} == {
        "snapshot_append_a",
        "snapshot_append_b",
    }


def test_missing_account_nav_ledger_fails_closed(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    merge_dir.mkdir()

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=None,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_missing",
    )

    assert not result.generated
    assert result.output_dir is None
    assert WarningCode.SNAPSHOT_ACCOUNT_NAV_LEDGER_MISSING in result.warning_codes


def test_missing_dashboard_summary_warns_not_fails(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(merge_dir, dashboard_dir, write_dashboard_summary=False)

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_missing_dashboard",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert WarningCode.SNAPSHOT_DASHBOARD_SUMMARY_MISSING in result.warning_codes


def test_missing_provider_summary_warns_not_fails(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(merge_dir, dashboard_dir, write_provider_summary=False)

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_missing_provider",
        generated_at=_generated_at(),
    )

    assert result.generated
    assert WarningCode.SNAPSHOT_PROVIDER_SUMMARY_MISSING in result.warning_codes


def test_mixed_as_of_and_stale_warnings_are_surfaced(tmp_path: Path) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(
        merge_dir,
        dashboard_dir,
        account_warnings="MIXED_AS_OF_DATES;STALE_PROVIDER_BUNDLE",
        summary_warnings=["MIXED_AS_OF_DATES", "STALE_PROVIDER_BUNDLE"],
    )

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_warned",
        generated_at=_generated_at(),
    )

    assert WarningCode.SNAPSHOT_MIXED_AS_OF_DATES in result.warning_codes
    assert WarningCode.SNAPSHOT_STALE_INPUT_WARNING in result.warning_codes
    assert WarningCode.SNAPSHOT_WARNINGS_PRESENT in result.warning_codes


def test_snapshot_outputs_exclude_raw_ids_forbidden_markers_and_exact_real_values(
    tmp_path: Path,
) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(merge_dir, dashboard_dir, account_source_map_value=RAW_ACCOUNT_ID)

    result = record_snapshot(
        merge_dir=merge_dir,
        dashboard_dir=dashboard_dir,
        out_dir=tmp_path / "snapshots",
        snapshot_id="snapshot_redaction",
        generated_at=_generated_at(),
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in result.output_paths.values())
    lower = combined.lower()
    assert RAW_ACCOUNT_ID not in combined
    assert "DU123456789" not in combined
    assert "987654321" not in combined
    for marker in FORBIDDEN_MARKERS:
        assert marker not in lower


def test_snapshot_cli_generates_fixture_snapshot_without_loading_local_env(
    tmp_path: Path, capsys
) -> None:
    merge_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    _write_snapshot_inputs(merge_dir, dashboard_dir)

    exit_code = main(
        [
            "--record-snapshot",
            "--merge-dir",
            str(merge_dir),
            "--dashboard-dir",
            str(dashboard_dir),
            "--out-dir",
            str(tmp_path / "snapshots"),
            "--snapshot-id",
            "snapshot_cli",
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO Snapshot Store v0.4.2 (offline)" in captured
    assert "Broker connections used: no" in captured
    assert "Loaded local environment" not in captured
    assert "Snapshot generated: yes" in captured


def test_snapshot_cli_rejects_live_and_discovery_modes(tmp_path: Path) -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--record-snapshot" in option_strings
    assert "--merge-dir" in option_strings
    assert "--dashboard-dir" in option_strings

    with pytest.raises(SystemExit):
        main(
            [
                "--record-snapshot",
                "--merge-dir",
                str(tmp_path / "merged"),
                "--out-dir",
                str(tmp_path / "snapshots"),
                "--allow-live-read",
            ]
        )
    with pytest.raises(SystemExit):
        main(
            [
                "--record-snapshot",
                "--merge-dir",
                str(tmp_path / "merged"),
                "--out-dir",
                str(tmp_path / "snapshots"),
                "--provider",
                "moomoo",
                "--account-discovery",
            ]
        )


def test_snapshot_fixture_chain_from_merge_and_dashboard(tmp_path: Path) -> None:
    merged_dir = tmp_path / "merged"
    dashboard_dir = tmp_path / "dashboard"
    snapshot_dir = tmp_path / "snapshots"
    merge_provider_bundles(input_root=None, out_dir=merged_dir, fixture_mode=True)
    assert main(["--dashboard-v2", "--input-dir", str(merged_dir), "--out-dir", str(dashboard_dir)]) == 0

    exit_code = main(
        [
            "--record-snapshot",
            "--merge-dir",
            str(merged_dir),
            "--dashboard-dir",
            str(dashboard_dir),
            "--out-dir",
            str(snapshot_dir),
            "--snapshot-id",
            "snapshot_fixture_chain",
        ]
    )

    assert exit_code == 0
    assert (snapshot_dir / "snapshot_manifest.json").exists()
    assert (snapshot_dir / "net_worth_history.csv").exists()
    assert (snapshot_dir / "account_nav_history.csv").exists()
    assert (snapshot_dir / "provider_nav_history.csv").exists()
    assert (snapshot_dir / "snapshot_warnings.md").exists()
    assert (snapshot_dir / "SNAPSHOT_STORE_V042.md").exists()


def test_snapshot_report_path_is_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "reports/personal_cfo_agent/snapshots_v042_fixture/snapshot_manifest.json",
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def _write_snapshot_inputs(
    merge_dir: Path,
    dashboard_dir: Path,
    *,
    write_dashboard_summary: bool = True,
    write_provider_summary: bool = True,
    account_warnings: str = "",
    summary_warnings: list[str] | None = None,
    account_source_map_value: str = "",
) -> None:
    merge_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    account_rows = [
        _account_row(
            "manual_snapshot",
            "acct_manual_synthetic_hash",
            "1234.50",
            warning_codes=account_warnings,
        ),
        _account_row(
            "ibkr",
            "acct_ibkr_synthetic_hash",
            "2345.60",
            as_of_date="2026-06-16",
            warning_codes=account_warnings,
        ),
    ]
    _write_csv(merge_dir / "merged_account_nav_ledger.csv", ACCOUNT_NAV_FIELDNAMES, account_rows)
    _write_csv(
        merge_dir / "merged_position_ledger.csv",
        POSITION_LEDGER_FIELDNAMES,
        [_position_row("manual_snapshot"), _position_row("ibkr")],
    )
    warnings = summary_warnings or []
    (merge_dir / "merged_account_nav_summary.json").write_text(
        json.dumps(
            {
                "account_nav_row_count": len(account_rows),
                "provider_counts": {"ibkr": 1, "manual_snapshot": 1},
                "warning_codes": warnings,
            }
        ),
        encoding="utf-8",
    )
    if write_provider_summary:
        (merge_dir / "merged_provider_summary.json").write_text(
            json.dumps(
                {
                    "source_bundle_count": 2,
                    "account_nav_row_count": 2,
                    "position_row_count": 2,
                    "provider_counts": {"ibkr": 1, "manual_snapshot": 1},
                    "bundle_results": [
                        {"provider": "ibkr", "status": "imported"},
                        {"provider": "manual_snapshot", "status": "imported"},
                    ],
                    "warning_codes": warnings,
                }
            ),
            encoding="utf-8",
        )
    (merge_dir / "account_source_map.json").write_text(
        json.dumps(
            {
                "acct_ibkr_synthetic_hash": {
                    "providers": ["ibkr"],
                    "source_bundle_ids": [account_source_map_value] if account_source_map_value else [],
                }
            }
        ),
        encoding="utf-8",
    )
    (merge_dir / "merge_warnings.md").write_text(
        "\n".join(f"- {warning}" for warning in warnings), encoding="utf-8"
    )
    if write_dashboard_summary:
        (dashboard_dir / "dashboard_v040_summary.json").write_text(
            json.dumps(
                {
                    "account_count": 2,
                    "provider_count": 2,
                    "position_count": 2,
                    "warning_codes": warnings,
                }
            ),
            encoding="utf-8",
        )
    (dashboard_dir / "dashboard_warnings.md").write_text(
        "\n".join(f"- {warning}" for warning in warnings), encoding="utf-8"
    )


def _account_row(
    provider: str,
    account_hash: str,
    account_nav: str,
    *,
    as_of_date: str = "2026-06-15",
    warning_codes: str = "",
) -> dict[str, str]:
    return {
        "provider": provider,
        "account_id_hash": account_hash,
        "source_bundle_id": f"{provider}_synthetic_source",
        "source_snapshot_id": "",
        "as_of_date": as_of_date,
        "base_currency": "USD",
        "account_nav": account_nav,
        "total_assets": account_nav,
        "cash_total": "100.00",
        "securities_market_value": "200.00",
        "margin_or_debt": "",
        "buying_power": "",
        "provider_reported_nav_available": "yes",
        "nav_source": "provider_reported",
        "source_confidence": "synthetic_fixture",
        "warning_codes": warning_codes,
    }


def _position_row(provider: str) -> dict[str, str]:
    return {
        "provider": provider,
        "account_id_hash": f"acct_{provider}_synthetic_hash",
        "source_bundle_id": f"{provider}_synthetic_source",
        "source_snapshot_id": "",
        "asset_type": "equity",
        "symbol": "SYNTH",
        "name": "Synthetic position",
        "currency": "USD",
        "quantity": "1",
        "market_value": "200.00",
        "cost_basis": "150.00",
        "average_cost": "150.00",
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


def _generated_at() -> datetime:
    return datetime(2026, 6, 16, 0, 0, 0, tzinfo=timezone.utc)
