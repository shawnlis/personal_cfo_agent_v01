"""Offline redacted snapshot history manager."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.snapshot_store import (
    ACCOUNT_NAV_HISTORY_FIELDNAMES,
    NET_WORTH_HISTORY_FIELDNAMES,
    PROVIDER_NAV_HISTORY_FIELDNAMES,
)
from personal_cfo_agent.warning_text import warning_details, warning_lines


SCHEMA_VERSION = "v0.6.8"

SUMMARY_NAME = "snapshot_history_manager_summary.json"
WARNINGS_NAME = "snapshot_history_manager_warnings.md"
REPORT_NAME = "SNAPSHOT_HISTORY_MANAGER_V068.md"

_NET_WORTH_HISTORY = "net_worth_history.csv"
_ACCOUNT_NAV_HISTORY = "account_nav_history.csv"
_PROVIDER_NAV_HISTORY = "provider_nav_history.csv"


@dataclass(frozen=True)
class SnapshotHistoryManagerResult:
    snapshot_dir: Path
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    backup_dir: Path | None = None
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False
    applied: bool = False
    matched_snapshot_count: int = 0


def manage_snapshot_history(
    *,
    snapshot_dir: Path,
    out_dir: Path,
    keep_snapshot_dates: list[str] | None = None,
    keep_snapshot_ids: list[str] | None = None,
    apply_changes: bool = False,
    generated_at: datetime | None = None,
) -> SnapshotHistoryManagerResult:
    """Inspect or rewrite local snapshot history without printing private values."""

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "warnings": out_dir / WARNINGS_NAME,
        "report": out_dir / REPORT_NAME,
    }
    keep_dates = _clean_list(keep_snapshot_dates or [])
    keep_ids = _clean_list(keep_snapshot_ids or [])
    warnings: list[WarningCode] = []
    if not apply_changes:
        warnings.append(WarningCode.SNAPSHOT_HISTORY_MANAGER_DRY_RUN)

    if not snapshot_dir.exists():
        warnings.append(WarningCode.SNAPSHOT_HISTORY_MANAGER_INPUT_MISSING)
        summary = _summary(
            snapshot_dir=snapshot_dir,
            apply_changes=apply_changes,
            keep_dates=keep_dates,
            keep_ids=keep_ids,
            rows_before={},
            rows_after={},
            matched_snapshot_ids=[],
            warning_codes=_with_completion(warnings),
            backup_dir=None,
        )
        _write_outputs(output_paths, summary)
        return SnapshotHistoryManagerResult(
            snapshot_dir=snapshot_dir,
            output_dir=out_dir,
            output_paths=output_paths,
            warning_codes=[WarningCode(code) for code in summary["warning_codes"]],
            generated=True,
        )

    net_worth_rows = _read_csv(snapshot_dir / _NET_WORTH_HISTORY)
    account_rows = _read_csv(snapshot_dir / _ACCOUNT_NAV_HISTORY)
    provider_rows = _read_csv(snapshot_dir / _PROVIDER_NAV_HISTORY)
    if not net_worth_rows:
        warnings.append(WarningCode.SNAPSHOT_HISTORY_MANAGER_NO_HISTORY_ROWS)

    matched_ids = _matched_snapshot_ids(
        net_worth_rows=net_worth_rows,
        keep_dates=keep_dates,
        keep_ids=keep_ids,
    )
    has_keep_criteria = bool(keep_dates or keep_ids)
    if has_keep_criteria and not matched_ids:
        warnings.append(WarningCode.SNAPSHOT_HISTORY_MANAGER_KEEP_SET_EMPTY)

    rows_before = {
        "net_worth_history": len(net_worth_rows),
        "account_nav_history": len(account_rows),
        "provider_nav_history": len(provider_rows),
    }
    filtered_net_worth = _filter_rows(net_worth_rows, matched_ids) if has_keep_criteria else net_worth_rows
    filtered_account = _filter_rows(account_rows, matched_ids) if has_keep_criteria else account_rows
    filtered_provider = _filter_rows(provider_rows, matched_ids) if has_keep_criteria else provider_rows
    rows_after = {
        "net_worth_history": len(filtered_net_worth),
        "account_nav_history": len(filtered_account),
        "provider_nav_history": len(filtered_provider),
    }

    backup_dir = None
    applied = False
    if apply_changes and has_keep_criteria and matched_ids:
        generated_at = generated_at or datetime.now(timezone.utc)
        backup_dir = out_dir / ("backup_before_apply_" + generated_at.strftime("%Y%m%dT%H%M%SZ"))
        backup_dir.mkdir(parents=True, exist_ok=True)
        for filename in (
            _NET_WORTH_HISTORY,
            _ACCOUNT_NAV_HISTORY,
            _PROVIDER_NAV_HISTORY,
        ):
            source = snapshot_dir / filename
            if source.exists():
                shutil.copyfile(source, backup_dir / filename)
        warnings.extend(
            [
                WarningCode.SNAPSHOT_HISTORY_MANAGER_BACKUP_CREATED,
                WarningCode.SNAPSHOT_HISTORY_MANAGER_APPLIED,
            ]
        )
        _write_csv(snapshot_dir / _NET_WORTH_HISTORY, NET_WORTH_HISTORY_FIELDNAMES, filtered_net_worth)
        _write_csv(
            snapshot_dir / _ACCOUNT_NAV_HISTORY,
            ACCOUNT_NAV_HISTORY_FIELDNAMES,
            filtered_account,
        )
        _write_csv(
            snapshot_dir / _PROVIDER_NAV_HISTORY,
            PROVIDER_NAV_HISTORY_FIELDNAMES,
            filtered_provider,
        )
        applied = True

    final_warnings = _with_completion(warnings)
    summary = _summary(
        snapshot_dir=snapshot_dir,
        apply_changes=apply_changes,
        keep_dates=keep_dates,
        keep_ids=keep_ids,
        rows_before=rows_before,
        rows_after=rows_after,
        matched_snapshot_ids=matched_ids,
        warning_codes=final_warnings,
        backup_dir=backup_dir,
    )
    _write_outputs(output_paths, summary)
    return SnapshotHistoryManagerResult(
        snapshot_dir=snapshot_dir,
        output_dir=out_dir,
        output_paths=output_paths,
        backup_dir=backup_dir,
        warning_codes=final_warnings,
        generated=True,
        applied=applied,
        matched_snapshot_count=len(matched_ids),
    )


def _matched_snapshot_ids(
    *,
    net_worth_rows: list[dict[str, str]],
    keep_dates: list[str],
    keep_ids: list[str],
) -> list[str]:
    if not keep_dates and not keep_ids:
        return sorted(
            {
                _clean(row.get("snapshot_id"))
                for row in net_worth_rows
                if _clean(row.get("snapshot_id"))
            }
        )
    keep_date_set = set(keep_dates)
    keep_id_set = set(keep_ids)
    matched = {
        _clean(row.get("snapshot_id"))
        for row in net_worth_rows
        if _clean(row.get("snapshot_id"))
        and (
            _clean(row.get("snapshot_id")) in keep_id_set
            or _clean(row.get("snapshot_date")) in keep_date_set
        )
    }
    return sorted(matched)


def _filter_rows(
    rows: list[dict[str, str]], matched_snapshot_ids: list[str]
) -> list[dict[str, str]]:
    matched = set(matched_snapshot_ids)
    return [row for row in rows if _clean(row.get("snapshot_id")) in matched]


def _summary(
    *,
    snapshot_dir: Path,
    apply_changes: bool,
    keep_dates: list[str],
    keep_ids: list[str],
    rows_before: dict[str, int],
    rows_after: dict[str, int],
    matched_snapshot_ids: list[str],
    warning_codes: list[WarningCode],
    backup_dir: Path | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "redacted": True,
        "snapshot_dir": str(snapshot_dir),
        "apply_requested": bool(apply_changes),
        "applied": WarningCode.SNAPSHOT_HISTORY_MANAGER_APPLIED in warning_codes,
        "keep_snapshot_dates": keep_dates,
        "keep_snapshot_ids": keep_ids,
        "matched_snapshot_count": len(matched_snapshot_ids),
        "matched_snapshot_ids": matched_snapshot_ids,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "backup_dir": str(backup_dir) if backup_dir is not None else "",
        "warning_codes": [code.value for code in warning_codes],
        "warning_details": warning_details(warning_codes),
    }


def _write_outputs(paths: dict[str, Path], summary: dict[str, Any]) -> None:
    paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_warnings(paths["warnings"], [WarningCode(code) for code in summary["warning_codes"]])
    paths["report"].write_text(_report(summary), encoding="utf-8")


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = ["# Snapshot History Manager Warnings", ""]
    lines.extend(warning_lines(warnings))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(summary: dict[str, Any]) -> str:
    lines = [
        "# Snapshot History Manager v0.6.8",
        "",
        "Offline redacted manager for local snapshot history CSV files.",
        "",
        "## Mode",
        "",
        f"- Apply requested: {_yes_no(summary['apply_requested'])}",
        f"- Applied: {_yes_no(summary['applied'])}",
        f"- Backup directory: {summary['backup_dir'] or 'None'}",
        "",
        "## Keep Criteria",
        "",
        f"- Keep dates: {', '.join(summary['keep_snapshot_dates']) or 'None'}",
        f"- Keep snapshot ids: {', '.join(summary['keep_snapshot_ids']) or 'None'}",
        f"- Matched snapshot count: {summary['matched_snapshot_count']}",
        "",
        "## Row Counts",
        "",
        *_row_count_lines(summary),
        "",
        "## Warning Codes",
        "",
        *warning_lines(summary["warning_codes"]),
    ]
    return "\n".join(lines) + "\n"


def _row_count_lines(summary: dict[str, Any]) -> list[str]:
    before = summary.get("rows_before", {})
    after = summary.get("rows_after", {})
    keys = sorted({*before.keys(), *after.keys()})
    if not keys:
        return ["- None"]
    return [
        f"- {key}: before={before.get(key, 0)}; after={after.get(key, 0)}"
        for key in keys
    ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _with_completion(warnings: list[WarningCode]) -> list[WarningCode]:
    blocking_or_review = [
        code
        for code in warnings
        if code
        not in {
            WarningCode.SNAPSHOT_HISTORY_MANAGER_DRY_RUN,
            WarningCode.SNAPSHOT_HISTORY_MANAGER_BACKUP_CREATED,
            WarningCode.SNAPSHOT_HISTORY_MANAGER_APPLIED,
        }
    ]
    completion = (
        WarningCode.SNAPSHOT_HISTORY_MANAGER_GENERATED_WITH_WARNINGS
        if blocking_or_review
        else WarningCode.SNAPSHOT_HISTORY_MANAGER_GENERATED_OK
    )
    return _dedupe([*warnings, completion])


def _clean_list(values: list[str]) -> list[str]:
    return sorted({_clean(value) for value in values if _clean(value)})


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result
