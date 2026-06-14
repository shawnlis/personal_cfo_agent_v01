from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import scripts.run_ibkr_readonly_sync as sync


ROOT = Path(__file__).resolve().parents[1]
PS_TEMPLATE = ROOT / "scripts" / "run_ibkr_readonly_sync.ps1.template"


def test_powershell_template_exists_and_contains_confirmation_prompts() -> None:
    text = PS_TEMPLATE.read_text(encoding="utf-8")

    assert PS_TEMPLATE.name.endswith(".ps1.template")
    assert not (ROOT / "scripts" / "run_ibkr_readonly_sync.ps1").exists()
    assert "Confirm TWS / IB Gateway is already open and API read-only mode is enabled" in text
    assert "Confirm this is read-only sync only" in text
    assert "python .\\scripts\\personal_cfo_agent.py --provider ibkr --connection-diagnostics" in text
    assert "python .\\scripts\\personal_cfo_agent.py --provider ibkr --readiness-check" in text
    assert "--allow-live-read" in text
    assert "--ibkr-data-diagnostics" in text


def test_powershell_template_has_no_env_values_or_scheduler_creation() -> None:
    text = PS_TEMPLATE.read_text(encoding="utf-8")

    assert "CFO_IBKR_" not in text
    assert "CFO_ACCOUNT_HASH_SALT" not in text
    assert re.search(r"\b[A-Z]{1,5}[A-Z0-9_-]*\d{5,}\b", text) is None
    assert "Register-ScheduledTask" not in text
    assert "New-ScheduledTask" not in text
    assert "schtasks" not in text.lower()


def test_powershell_template_orders_checks_before_live_sync() -> None:
    text = PS_TEMPLATE.read_text(encoding="utf-8")

    diagnostics_index = text.index("--connection-diagnostics")
    readiness_index = text.index("--readiness-check")
    live_index = text.index("--allow-live-read")
    assert diagnostics_index < readiness_index < live_index


def test_python_wrapper_refuses_live_sync_without_allow_flag(monkeypatch, tmp_path) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(args):
        commands.append(tuple(args))
        if "--connection-diagnostics" in args:
            return sync.CommandResult(tuple(args), 0, "diagnostic warning codes: None\n", "")
        return sync.CommandResult(tuple(args), 0, "ibkr: api_contract_stub; warnings=None\n", "")

    monkeypatch.setattr(sync, "_run_agent_command", fake_run)
    exit_code = sync.main(
        [
            "--run-id",
            "20260101_000000",
            "--out-root",
            str(tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync"),
            "--index-path",
            str(tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "ibkr_sync_index.json"),
        ]
    )

    assert exit_code == 2
    assert commands == [
        ("--provider", "ibkr", "--connection-diagnostics"),
        ("--provider", "ibkr", "--readiness-check"),
    ]
    assert not (tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "20260101_000000").exists()


def test_python_wrapper_dry_smoke_does_not_run_connection_diagnostics_or_live_read(
    monkeypatch, tmp_path, capsys
) -> None:
    commands: list[tuple[str, ...]] = []
    command_cwds: list[Path | None] = []

    def fake_run(args, cwd=None):
        commands.append(tuple(args))
        command_cwds.append(cwd)
        return sync.CommandResult(
            tuple(args),
            0,
            "Loaded local environment from .env.local; values redacted\n"
            "ibkr: api_contract_stub; warnings=PROVIDER_DISABLED\n"
            "No provider produced data; no reports generated.\n",
            "",
        )

    index_path = tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync_dry_smoke" / "ibkr_sync_index.json"
    monkeypatch.setattr(sync, "_run_agent_command", fake_run)
    exit_code = sync.main(
        [
            "--dry-smoke",
            "--run-id",
            "20260101_000002",
            "--out-root",
            str(tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync_dry_smoke"),
            "--index-path",
            str(index_path),
        ]
    )

    assert exit_code == 0
    assert commands == [("--provider", "ibkr", "--readiness-check")]
    assert command_cwds == [index_path.parent]
    captured = capsys.readouterr()
    assert ".env.local" not in captured.out
    assert "local environment file" in captured.out
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    run = payload["runs"][-1]
    assert run["diagnostics_status"] == "skipped_no_network"
    assert run["live_read_attempted"] is False
    assert "--connection-diagnostics" not in {part for command in commands for part in command}
    assert "--allow-live-read" not in {part for command in commands for part in command}
    assert not (
        tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync_dry_smoke" / "20260101_000002"
    ).exists()


def test_python_wrapper_diagnostics_only_mode_without_network(monkeypatch, tmp_path) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(args):
        commands.append(tuple(args))
        if "--connection-diagnostics" in args:
            return sync.CommandResult(
                tuple(args),
                0,
                "IBKR connection diagnostics (values redacted)\ndiagnostic warning codes: PROVIDER_DISABLED\n",
                "",
            )
        return sync.CommandResult(
            tuple(args),
            0,
            "ibkr: api_contract_stub; warnings=PROVIDER_DISABLED\nNo provider produced data; no reports generated.\n",
            "",
        )

    index_path = tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "ibkr_sync_index.json"
    monkeypatch.setattr(sync, "_run_agent_command", fake_run)
    exit_code = sync.main(
        [
            "--diagnostics-only",
            "--run-id",
            "20260101_000001",
            "--out-root",
            str(tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync"),
            "--index-path",
            str(index_path),
        ]
    )

    assert exit_code == 0
    assert commands == [
        ("--provider", "ibkr", "--connection-diagnostics"),
        ("--provider", "ibkr", "--readiness-check"),
    ]
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    run = payload["runs"][-1]
    assert run["live_read_attempted"] is False
    assert run["warning_codes"] == ["PROVIDER_DISABLED"]


def test_readiness_failure_prevents_live_read(monkeypatch, tmp_path) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(args):
        commands.append(tuple(args))
        if "--connection-diagnostics" in args:
            return sync.CommandResult(tuple(args), 0, "diagnostic warning codes: None\n", "")
        return sync.CommandResult(tuple(args), 1, "", "readiness failed\n")

    monkeypatch.setattr(sync, "_run_agent_command", fake_run)
    exit_code = sync.main(
        [
            "--allow-live-read",
            "--run-id",
            "20260101_000003",
            "--out-root",
            str(tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync"),
            "--index-path",
            str(tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "ibkr_sync_index.json"),
        ]
    )

    assert exit_code == 1
    assert commands == [
        ("--provider", "ibkr", "--connection-diagnostics"),
        ("--provider", "ibkr", "--readiness-check"),
    ]
    assert not (tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "20260101_000003").exists()


def test_sync_index_schema_is_stable(tmp_path) -> None:
    record = _sample_run_record(tmp_path)

    assert tuple(record.keys()) == sync.SYNC_RUN_KEYS
    assert set(record) == {
        "run_id",
        "timestamp",
        "provider",
        "diagnostics_status",
        "readiness_status",
        "live_read_attempted",
        "live_read_success",
        "output_dir",
        "warning_codes",
        "row_count",
        "positions_count",
        "cash_currency_count",
        "redaction_confirmed",
        "reports_ignored",
        "safety_boundary",
    }


def test_sync_index_safety_boundary_fields_are_stable(tmp_path) -> None:
    record = _sample_run_record(tmp_path)

    assert record["safety_boundary"] == {
        "read_only": True,
        "trading_enabled": False,
        "order_placement_enabled": False,
        "cash_transfer_enabled": False,
        "recommendation_output": False,
        "raw_account_ids_output": False,
        "env_file_committed": False,
        "reports_committed": False,
    }


def test_no_raw_account_ids_in_sync_index_fixture(tmp_path) -> None:
    record = _sample_run_record(tmp_path)
    payload = {"schema_version": sync.INDEX_SCHEMA_VERSION, "runs": [record]}
    text = json.dumps(payload)

    assert record["redaction_confirmed"] is True
    assert "DU1234567" not in text
    assert re.search(r"\b[A-Z]{1,5}[A-Z0-9_-]*\d{5,}\b", text) is None
    assert sync.contains_raw_account_id(payload) is False


def test_reports_output_path_is_under_ignored_reports_path() -> None:
    output_dir = ROOT / "reports" / "personal_cfo_agent" / "ibkr_sync" / "20260101_000000"
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", "reports/personal_cfo_agent/ibkr_sync/20260101_000000"],
        cwd=ROOT,
        check=False,
    )

    assert output_dir.relative_to(ROOT).as_posix().startswith("reports/personal_cfo_agent/ibkr_sync/")
    assert result.returncode == 0
    assert sync.reports_ignored(output_dir) is True


def test_env_local_remains_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", ".env.local"],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_local_powershell_copy_remains_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", "scripts/run_ibkr_readonly_sync.local.ps1"],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_standalone_sync_index_remains_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", "ibkr_sync_index.json"],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_no_forbidden_order_or_cash_transfer_markers() -> None:
    combined_text = "\n".join(
        [
            (ROOT / "scripts" / "run_ibkr_readonly_sync.py").read_text(encoding="utf-8"),
            PS_TEMPLATE.read_text(encoding="utf-8"),
        ]
    )
    forbidden_markers = (
        "placeOrder",
        "place_order",
        "submit_order",
        "modify_order",
        "cancel_order",
        "preview_order",
        "transfer_cash",
        "withdraw_cash",
        "buy",
        "sell",
        "trade",
        "roll",
        "open_position",
        "close_position",
    )

    for marker in forbidden_markers:
        assert marker not in combined_text


def _sample_run_record(tmp_path: Path) -> dict[str, object]:
    return sync.build_run_record(
        run_id="20260101_000000",
        timestamp="2026-01-01T00:00:00+00:00",
        diagnostics_status="passed",
        readiness_status="passed",
        live_read_attempted=True,
        live_read_success=True,
        output_dir=tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "20260101_000000",
        index_path=tmp_path / "reports" / "personal_cfo_agent" / "ibkr_sync" / "ibkr_sync_index.json",
        warning_codes=[],
        row_count=55,
        positions_count=54,
        cash_currency_count=1,
    )
