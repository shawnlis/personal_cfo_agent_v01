"""Safe local IBKR read-only sync wrapper."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_SCRIPT = Path("scripts") / "personal_cfo_agent.py"
DEFAULT_SYNC_ROOT = Path("reports") / "personal_cfo_agent" / "ibkr_sync"
INDEX_FILENAME = "ibkr_sync_index.json"
INDEX_SCHEMA_VERSION = "ibkr_safe_local_sync_v0.2.2"
DEFAULT_MAX_INDEX_RUNS = 50

SYNC_RUN_KEYS = (
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
)

SAFETY_BOUNDARY = {
    "read_only": True,
    "trading_enabled": False,
    "order_placement_enabled": False,
    "cash_transfer_enabled": False,
    "recommendation_output": False,
    "raw_account_ids_output": False,
    "env_file_committed": False,
    "reports_committed": False,
}

_RAW_ACCOUNT_PATTERN = re.compile(r"\b[A-Z]{1,5}[A-Z0-9_-]*\d{5,}\b")
_RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}$")


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        parser.error("--run-id must use YYYYMMDD_HHMMSS")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_root = _resolve_repo_path(args.out_root)
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = _resolve_repo_path(args.index_path) if args.index_path else output_root / INDEX_FILENAME

    diagnostics = _run_agent_command(["--provider", "ibkr", "--connection-diagnostics"])
    _emit_command_output(diagnostics)
    readiness = _run_agent_command(["--provider", "ibkr", "--readiness-check"])
    _emit_command_output(readiness)

    diagnostics_warnings = _extract_warning_codes(diagnostics.combined_output)
    readiness_warnings = _extract_warning_codes(readiness.combined_output)
    diagnostics_status = _status_for(diagnostics, diagnostics_warnings)
    readiness_status = _status_for(readiness, readiness_warnings)
    warning_codes = sorted({*diagnostics_warnings, *readiness_warnings})

    live_read_attempted = False
    live_read_success = False
    row_count = 0
    positions_count = 0
    cash_currency_count = 0
    exit_code = 0

    if args.diagnostics_only:
        exit_code = 0 if diagnostics.returncode == 0 and readiness.returncode == 0 else 1
    elif not args.allow_live_read:
        print(
            "Refusing IBKR live read: rerun with --allow-live-read after manual confirmation.",
            file=sys.stderr,
        )
        exit_code = 2
    elif diagnostics_status == "passed" and readiness_status == "passed":
        live_read_attempted = True
        live = _run_agent_command(
            [
                "--provider",
                "ibkr",
                "--allow-live-read",
                "--ibkr-data-diagnostics",
                "--out-dir",
                str(output_dir),
            ]
        )
        _emit_command_output(live)
        live_warnings = _extract_warning_codes(live.combined_output)
        warning_codes = sorted({*warning_codes, *live_warnings})
        row_count = _extract_int(live.combined_output, r"Normalized ledger rows:\s*(\d+)")
        positions_count = _extract_int(live.combined_output, r"Position count:\s*(\d+)")
        cash_currency_count = _extract_int(live.combined_output, r"Cash currency count:\s*(\d+)")
        live_read_success = live.returncode == 0 and row_count > 0
        exit_code = 0 if live_read_success else 1
    else:
        print("Diagnostics/readiness did not pass; live read was not attempted.", file=sys.stderr)
        exit_code = 1

    run_record = build_run_record(
        run_id=run_id,
        timestamp=timestamp,
        diagnostics_status=diagnostics_status,
        readiness_status=readiness_status,
        live_read_attempted=live_read_attempted,
        live_read_success=live_read_success,
        output_dir=output_dir,
        index_path=index_path,
        warning_codes=warning_codes,
        row_count=row_count,
        positions_count=positions_count,
        cash_currency_count=cash_currency_count,
    )
    write_sync_index(index_path, run_record, max_runs=args.max_index_runs)
    print(f"IBKR sync output path: {_display_path(output_dir)}")
    print(f"IBKR sync index written to: {_display_path(index_path)}")
    return exit_code


def build_run_record(
    *,
    run_id: str,
    timestamp: str,
    diagnostics_status: str,
    readiness_status: str,
    live_read_attempted: bool,
    live_read_success: bool,
    output_dir: Path,
    index_path: Path,
    warning_codes: Sequence[str],
    row_count: int,
    positions_count: int,
    cash_currency_count: int,
) -> dict[str, object]:
    record = {
        "run_id": run_id,
        "timestamp": timestamp,
        "provider": "ibkr",
        "diagnostics_status": diagnostics_status,
        "readiness_status": readiness_status,
        "live_read_attempted": live_read_attempted,
        "live_read_success": live_read_success,
        "output_dir": _display_path(output_dir),
        "warning_codes": sorted(set(warning_codes)),
        "row_count": row_count,
        "positions_count": positions_count,
        "cash_currency_count": cash_currency_count,
        "redaction_confirmed": False,
        "reports_ignored": reports_ignored(output_dir) and reports_ignored(index_path),
        "safety_boundary": dict(SAFETY_BOUNDARY),
    }
    record["redaction_confirmed"] = not contains_raw_account_id(record)
    return {key: record[key] for key in SYNC_RUN_KEYS}


def write_sync_index(index_path: Path, run_record: dict[str, object], max_runs: int) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    existing_runs: list[dict[str, object]] = []
    if index_path.exists():
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        runs = payload.get("runs", [])
        if isinstance(runs, list):
            existing_runs = [run for run in runs if isinstance(run, dict)]
    retained_runs = [*existing_runs, run_record]
    if max_runs > 0:
        retained_runs = retained_runs[-max_runs:]
    payload = {"schema_version": INDEX_SCHEMA_VERSION, "runs": retained_runs}
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def reports_ignored(path: Path) -> bool:
    try:
        relative = _repo_relative(path)
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()],
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode == 0


def contains_raw_account_id(payload: object) -> bool:
    text = json.dumps(payload, sort_keys=True)
    return _RAW_ACCOUNT_PATTERN.search(text) is not None


def _run_agent_command(args: Sequence[str]) -> CommandResult:
    command = [sys.executable, str(AGENT_SCRIPT), *args]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        args=tuple(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a safe local IBKR read-only sync.")
    parser.add_argument(
        "--allow-live-read",
        action="store_true",
        help="Permit the final gated IBKR read-only sync command.",
    )
    parser.add_argument(
        "--diagnostics-only",
        action="store_true",
        help="Run diagnostics and readiness only, then update the local sync index.",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_SYNC_ROOT,
        help="Ignored local root for timestamped IBKR sync outputs.",
    )
    parser.add_argument(
        "--index-path",
        type=Path,
        default=None,
        help="Optional local sync index path. Defaults under --out-root.",
    )
    parser.add_argument(
        "--max-index-runs",
        type=int,
        default=DEFAULT_MAX_INDEX_RUNS,
        help="Retain only this many latest index entries. Use 0 to keep all.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id for tests or supervised reruns. Defaults to YYYYMMDD_HHMMSS.",
    )
    return parser


def _status_for(result: CommandResult, warning_codes: Sequence[str]) -> str:
    if result.returncode != 0:
        return "failed"
    if warning_codes:
        return "warning"
    return "passed"


def _extract_warning_codes(text: str) -> list[str]:
    codes: list[str] = []
    for line in text.splitlines():
        if "warning codes:" in line:
            codes.extend(_split_warning_text(line.split("warning codes:", 1)[1]))
        if "warnings=" in line:
            codes.extend(_split_warning_text(line.split("warnings=", 1)[1]))
    return sorted(set(codes))


def _split_warning_text(raw_text: str) -> list[str]:
    cleaned = raw_text.strip().rstrip(".")
    if cleaned in {"", "None", "none"}:
        return []
    return [
        token
        for token in (part.strip() for part in re.split(r"[,;]", cleaned))
        if re.fullmatch(r"[A-Z0-9_]+", token)
    ]


def _extract_int(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    if not match:
        return 0
    return int(match.group(1))


def _emit_command_output(result: CommandResult) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _repo_relative(path: Path) -> Path:
    absolute = path.resolve()
    return absolute.relative_to(REPO_ROOT.resolve())


def _display_path(path: Path) -> str:
    try:
        return _repo_relative(path).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
