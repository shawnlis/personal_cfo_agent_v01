from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.runner import build_arg_parser, main
from personal_cfo_agent.snapshot_history_manager import manage_snapshot_history
from personal_cfo_agent.snapshot_store import (
    ACCOUNT_NAV_HISTORY_FIELDNAMES,
    NET_WORTH_HISTORY_FIELDNAMES,
    PROVIDER_NAV_HISTORY_FIELDNAMES,
)


PRIVATE_VALUE_MARKER = "9876543.21"
ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MARKERS = (
    "allow-live-read",
    "account-discovery",
    "read-context-probe",
    "webull-data-diagnostics",
    "moomoo-data-diagnostics",
    "place_order",
    "preview_order",
    "modify_order",
    "cancel_order",
    "transfer_cash",
    "withdraw_cash",
    "unlock_trade",
)


def test_snapshot_history_manager_cli_option_exists() -> None:
    parser = build_arg_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert "--snapshot-history-manager" in option_strings
    assert "--keep-snapshot-date" in option_strings
    assert "--keep-snapshot-id" in option_strings
    assert "--apply-snapshot-history-changes" in option_strings


def test_snapshot_history_manager_dry_run_generates_redacted_reports(
    tmp_path: Path,
) -> None:
    snapshot_dir = _write_history(tmp_path)
    original = (snapshot_dir / "net_worth_history.csv").read_text(encoding="utf-8")

    result = manage_snapshot_history(
        snapshot_dir=snapshot_dir,
        out_dir=tmp_path / "manager",
        keep_snapshot_dates=["2026-06-21"],
    )

    assert result.generated is True
    assert result.applied is False
    assert result.matched_snapshot_count == 1
    assert WarningCode.SNAPSHOT_HISTORY_MANAGER_DRY_RUN in result.warning_codes
    assert (snapshot_dir / "net_worth_history.csv").read_text(encoding="utf-8") == original
    _assert_outputs_redacted(result.output_paths)


def test_snapshot_history_manager_apply_keeps_selected_snapshot_and_backs_up(
    tmp_path: Path,
) -> None:
    snapshot_dir = _write_history(tmp_path)

    result = manage_snapshot_history(
        snapshot_dir=snapshot_dir,
        out_dir=tmp_path / "manager_apply",
        keep_snapshot_ids=["snapshot_keep"],
        apply_changes=True,
    )

    assert result.generated is True
    assert result.applied is True
    assert result.backup_dir is not None
    assert (result.backup_dir / "net_worth_history.csv").exists()
    assert WarningCode.SNAPSHOT_HISTORY_MANAGER_BACKUP_CREATED in result.warning_codes
    assert WarningCode.SNAPSHOT_HISTORY_MANAGER_APPLIED in result.warning_codes
    assert [row["snapshot_id"] for row in _read_rows(snapshot_dir / "net_worth_history.csv")] == [
        "snapshot_keep"
    ]
    assert {row["snapshot_id"] for row in _read_rows(snapshot_dir / "account_nav_history.csv")} == {
        "snapshot_keep"
    }
    assert {row["snapshot_id"] for row in _read_rows(snapshot_dir / "provider_nav_history.csv")} == {
        "snapshot_keep"
    }
    _assert_outputs_redacted(result.output_paths)


def test_snapshot_history_manager_missing_input_fails_closed(tmp_path: Path) -> None:
    result = manage_snapshot_history(
        snapshot_dir=tmp_path / "missing_snapshots",
        out_dir=tmp_path / "manager_missing",
    )

    assert result.generated is True
    assert WarningCode.SNAPSHOT_HISTORY_MANAGER_INPUT_MISSING in result.warning_codes
    assert WarningCode.SNAPSHOT_HISTORY_MANAGER_GENERATED_WITH_WARNINGS in result.warning_codes


def test_snapshot_history_manager_cli_is_offline_and_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot_dir = _write_history(tmp_path)
    out_dir = tmp_path / "manager_cli"

    exit_code = main(
        [
            "--snapshot-history-manager",
            "--snapshot-dir",
            str(snapshot_dir),
            "--keep-snapshot-date",
            "2026-06-21",
            "--out-dir",
            str(out_dir),
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Personal CFO snapshot history manager v0.6.8" in captured
    assert "External connections used: no" in captured
    assert "Broker live reads used: no" in captured
    assert "Changes applied: no" in captured
    assert "Matched snapshot count: 1" in captured
    assert PRIVATE_VALUE_MARKER not in captured
    assert (out_dir / "SNAPSHOT_HISTORY_MANAGER_V068.md").exists()


def test_snapshot_history_manager_apply_without_keep_criteria_rejected(
    tmp_path: Path,
) -> None:
    snapshot_dir = _write_history(tmp_path)

    with pytest.raises(SystemExit):
        main(
            [
                "--snapshot-history-manager",
                "--snapshot-dir",
                str(snapshot_dir),
                "--apply-snapshot-history-changes",
                "--out-dir",
                str(tmp_path / "manager_rejected"),
            ]
        )


def test_snapshot_history_manager_does_not_expose_live_or_trading_paths() -> None:
    text = (ROOT / "src" / "personal_cfo_agent" / "snapshot_history_manager.py").read_text(
        encoding="utf-8"
    )
    lowered = text.lower()

    for marker in FORBIDDEN_MARKERS:
        assert marker.lower() not in lowered


def _write_history(tmp_path: Path) -> Path:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _write_csv(
        snapshot_dir / "net_worth_history.csv",
        NET_WORTH_HISTORY_FIELDNAMES,
        [
            {
                "snapshot_date": "2026-06-20",
                "snapshot_id": "snapshot_drop",
                "base_currency": "SGD",
                "total_account_nav": PRIVATE_VALUE_MARKER,
                "liquid_net_worth": PRIVATE_VALUE_MARKER,
                "investable_assets": PRIVATE_VALUE_MARKER,
                "property_equity": "0.00",
                "cpf_total": "0.00",
                "srs_total": "0.00",
                "liabilities_total": "0.00",
                "provider_count": "1",
                "account_count": "1",
                "warning_count": "0",
                "review_required": "false",
                "source_confidence": "synthetic",
            },
            {
                "snapshot_date": "2026-06-21",
                "snapshot_id": "snapshot_keep",
                "base_currency": "SGD",
                "total_account_nav": PRIVATE_VALUE_MARKER,
                "liquid_net_worth": PRIVATE_VALUE_MARKER,
                "investable_assets": PRIVATE_VALUE_MARKER,
                "property_equity": "0.00",
                "cpf_total": "0.00",
                "srs_total": "0.00",
                "liabilities_total": "0.00",
                "provider_count": "1",
                "account_count": "1",
                "warning_count": "0",
                "review_required": "false",
                "source_confidence": "synthetic",
            },
        ],
    )
    _write_csv(
        snapshot_dir / "account_nav_history.csv",
        ACCOUNT_NAV_HISTORY_FIELDNAMES,
        [
            {
                "snapshot_date": "2026-06-20",
                "snapshot_id": "snapshot_drop",
                "provider": "manual_nav",
                "account_id_hash": "acct_synthetic_drop",
                "account_nav": PRIVATE_VALUE_MARKER,
                "cash_total": "",
                "securities_market_value": "",
                "margin_or_debt": "",
                "base_currency": "SGD",
                "nav_source": "synthetic",
                "as_of_date": "2026-06-20",
                "warning_codes": "",
                "source_confidence": "synthetic",
            },
            {
                "snapshot_date": "2026-06-21",
                "snapshot_id": "snapshot_keep",
                "provider": "manual_nav",
                "account_id_hash": "acct_synthetic_keep",
                "account_nav": PRIVATE_VALUE_MARKER,
                "cash_total": "",
                "securities_market_value": "",
                "margin_or_debt": "",
                "base_currency": "SGD",
                "nav_source": "synthetic",
                "as_of_date": "2026-06-21",
                "warning_codes": "",
                "source_confidence": "synthetic",
            },
        ],
    )
    _write_csv(
        snapshot_dir / "provider_nav_history.csv",
        PROVIDER_NAV_HISTORY_FIELDNAMES,
        [
            {
                "snapshot_date": "2026-06-20",
                "snapshot_id": "snapshot_drop",
                "provider": "manual_nav",
                "account_count": "1",
                "provider_nav_total": PRIVATE_VALUE_MARKER,
                "import_status": "synthetic",
                "warning_codes": "",
                "as_of_date_min": "2026-06-20",
                "as_of_date_max": "2026-06-20",
            },
            {
                "snapshot_date": "2026-06-21",
                "snapshot_id": "snapshot_keep",
                "provider": "manual_nav",
                "account_count": "1",
                "provider_nav_total": PRIVATE_VALUE_MARKER,
                "import_status": "synthetic",
                "warning_codes": "",
                "as_of_date_min": "2026-06-21",
                "as_of_date_max": "2026-06-21",
            },
        ],
    )
    return snapshot_dir


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _assert_outputs_redacted(paths: dict[str, Path]) -> None:
    for path in paths.values():
        text = path.read_text(encoding="utf-8")
        assert PRIVATE_VALUE_MARKER not in text
        assert "acct_synthetic_" not in text
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["redacted"] is True
