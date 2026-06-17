"""Offline Singapore CPF/SRS/tax/HDB manual snapshot generation."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.4.4"

CPF_SNAPSHOT_LEDGER_FIELDNAMES = [
    "snapshot_date",
    "oa",
    "sa",
    "ma",
    "ra",
    "total",
    "currency",
    "source_type",
    "source_date",
    "review_required",
    "warning_codes",
]

SRS_SNAPSHOT_LEDGER_FIELDNAMES = [
    "snapshot_date",
    "provider_label",
    "cash",
    "investments_value",
    "total",
    "contribution_ytd",
    "currency",
    "tax_wrapper",
    "source_type",
    "source_date",
    "review_required",
    "warning_codes",
]

TAX_SNAPSHOT_LEDGER_FIELDNAMES = [
    "year_of_assessment",
    "assessable_income_available",
    "tax_payable_available",
    "tax_paid_available",
    "reliefs_available",
    "source_type",
    "source_date",
    "review_required",
    "warning_codes",
]

HDB_LOAN_SNAPSHOT_LEDGER_FIELDNAMES = [
    "snapshot_date",
    "loan_id_hash",
    "linked_property_id_hash",
    "monthly_installment_available",
    "outstanding_balance_available",
    "currency",
    "source_type",
    "source_date",
    "review_required",
    "warning_codes",
]

_NRIC_PATTERN = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
_RAW_IDENTIFIER_KEYS = {
    "nric",
    "fin",
    "uin",
    "raw_nric",
    "identity_number",
    "government_id",
    "cpf_account_number",
    "hdb_account_number",
    "tax_reference_number",
}


@dataclass
class SGManualSnapshotResult:
    cpf_input: Path
    srs_input: Path
    tax_input: Path
    hdb_loan_input: Path
    output_dir: Path | None
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    cpf_count: int = 0
    srs_count: int = 0
    tax_count: int = 0
    hdb_loan_count: int = 0
    generated: bool = False


def record_sg_manual_snapshot(
    *,
    cpf_input: Path,
    srs_input: Path,
    tax_input: Path,
    hdb_loan_input: Path,
    out_dir: Path,
    generated_at: datetime | None = None,
) -> SGManualSnapshotResult:
    """Record local manual Singapore retirement, tax, and HDB loan snapshots."""

    generated_at = generated_at or datetime.now(timezone.utc)
    input_warnings = _input_warnings(cpf_input, srs_input, tax_input, hdb_loan_input)
    if input_warnings:
        return _failed_result(cpf_input, srs_input, tax_input, hdb_loan_input, input_warnings)

    cpf_rows = _read_records(cpf_input, "cpf")
    srs_rows = _read_records(srs_input, "srs_accounts")
    tax_rows = _read_records(tax_input, "tax_records")
    hdb_rows = _read_records(hdb_loan_input, "hdb_loans")

    missing_warnings: list[WarningCode] = []
    if not cpf_rows:
        missing_warnings.append(WarningCode.CPF_SNAPSHOT_MISSING)
    if not srs_rows:
        missing_warnings.append(WarningCode.SRS_SNAPSHOT_MISSING)
    if not tax_rows:
        missing_warnings.append(WarningCode.TAX_SNAPSHOT_MISSING)
    if not hdb_rows:
        missing_warnings.append(WarningCode.HDB_LOAN_SNAPSHOT_MISSING)
    if missing_warnings:
        return _failed_result(
            cpf_input,
            srs_input,
            tax_input,
            hdb_loan_input,
            missing_warnings,
        )

    identifier_warnings = _raw_identifier_warnings(cpf_rows, srs_rows, tax_rows, hdb_rows)
    if identifier_warnings:
        return _failed_result(
            cpf_input,
            srs_input,
            tax_input,
            hdb_loan_input,
            identifier_warnings,
        )

    terminal_warnings = _terminal_warnings(cpf_rows, srs_rows, tax_rows, hdb_rows)
    if terminal_warnings:
        return _failed_result(
            cpf_input,
            srs_input,
            tax_input,
            hdb_loan_input,
            terminal_warnings,
        )

    cpf_ledger_rows, cpf_warnings = _cpf_ledger_rows(cpf_rows)
    srs_ledger_rows, srs_warnings = _srs_ledger_rows(srs_rows)
    tax_ledger_rows, tax_warnings = _tax_ledger_rows(tax_rows)
    hdb_ledger_rows, hdb_warnings = _hdb_loan_ledger_rows(hdb_rows)

    warnings = _dedupe_warning_codes(
        [
            *cpf_warnings,
            *srs_warnings,
            *tax_warnings,
            *hdb_warnings,
        ]
    )
    completion = (
        WarningCode.SG_SNAPSHOT_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.SG_SNAPSHOT_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    out_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(
        generated_at=generated_at,
        cpf_rows=cpf_ledger_rows,
        srs_rows=srs_ledger_rows,
        tax_rows=tax_ledger_rows,
        hdb_rows=hdb_ledger_rows,
        warnings=warnings,
    )

    paths = {
        "cpf_snapshot_ledger": out_dir / "cpf_snapshot_ledger.csv",
        "srs_snapshot_ledger": out_dir / "srs_snapshot_ledger.csv",
        "tax_snapshot_ledger": out_dir / "tax_snapshot_ledger.csv",
        "hdb_loan_snapshot_ledger": out_dir / "hdb_loan_snapshot_ledger.csv",
        "sg_retirement_tax_summary": out_dir / "sg_retirement_tax_summary.json",
        "sg_retirement_tax_warnings": out_dir / "sg_retirement_tax_warnings.md",
        "markdown_report": out_dir / "SG_RETIREMENT_TAX_SNAPSHOT_V044.md",
    }
    _write_csv(paths["cpf_snapshot_ledger"], CPF_SNAPSHOT_LEDGER_FIELDNAMES, cpf_ledger_rows)
    _write_csv(paths["srs_snapshot_ledger"], SRS_SNAPSHOT_LEDGER_FIELDNAMES, srs_ledger_rows)
    _write_csv(paths["tax_snapshot_ledger"], TAX_SNAPSHOT_LEDGER_FIELDNAMES, tax_ledger_rows)
    _write_csv(
        paths["hdb_loan_snapshot_ledger"],
        HDB_LOAN_SNAPSHOT_LEDGER_FIELDNAMES,
        hdb_ledger_rows,
    )
    paths["sg_retirement_tax_summary"].write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _write_warnings(paths["sg_retirement_tax_warnings"], warnings)
    _write_markdown(paths["markdown_report"], summary=summary, warnings=warnings)

    return SGManualSnapshotResult(
        cpf_input=cpf_input,
        srs_input=srs_input,
        tax_input=tax_input,
        hdb_loan_input=hdb_loan_input,
        output_dir=out_dir,
        output_paths=paths,
        warning_codes=warnings,
        cpf_count=len(cpf_ledger_rows),
        srs_count=len(srs_ledger_rows),
        tax_count=len(tax_ledger_rows),
        hdb_loan_count=len(hdb_ledger_rows),
        generated=True,
    )


def _input_warnings(
    cpf_input: Path, srs_input: Path, tax_input: Path, hdb_loan_input: Path
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if not cpf_input.exists():
        warnings.append(WarningCode.CPF_SNAPSHOT_MISSING)
    if not srs_input.exists():
        warnings.append(WarningCode.SRS_SNAPSHOT_MISSING)
    if not tax_input.exists():
        warnings.append(WarningCode.TAX_SNAPSHOT_MISSING)
    if not hdb_loan_input.exists():
        warnings.append(WarningCode.HDB_LOAN_SNAPSHOT_MISSING)
    return warnings


def _failed_result(
    cpf_input: Path,
    srs_input: Path,
    tax_input: Path,
    hdb_loan_input: Path,
    warnings: list[WarningCode],
) -> SGManualSnapshotResult:
    return SGManualSnapshotResult(
        cpf_input=cpf_input,
        srs_input=srs_input,
        tax_input=tax_input,
        hdb_loan_input=hdb_loan_input,
        output_dir=None,
        warning_codes=_dedupe_warning_codes(warnings),
    )


def _terminal_warnings(
    cpf_rows: list[dict[str, object]],
    srs_rows: list[dict[str, object]],
    tax_rows: list[dict[str, object]],
    hdb_rows: list[dict[str, object]],
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if any(not _clean(row.get("snapshot_date")) for row in cpf_rows):
        warnings.append(WarningCode.CPF_SNAPSHOT_MISSING)
    if any(not _clean(row.get("snapshot_date")) for row in srs_rows):
        warnings.append(WarningCode.SRS_SNAPSHOT_MISSING)
    if any(not _clean(row.get("year_of_assessment")) for row in tax_rows):
        warnings.append(WarningCode.TAX_SNAPSHOT_MISSING)
    if any(
        not _clean(row.get("snapshot_date")) or not _clean(row.get("loan_id_hash"))
        for row in hdb_rows
    ):
        warnings.append(WarningCode.HDB_LOAN_SNAPSHOT_MISSING)
    return _dedupe_warning_codes(warnings)


def _raw_identifier_warnings(
    *groups: list[dict[str, object]],
) -> list[WarningCode]:
    for rows in groups:
        for row in rows:
            for key, value in row.items():
                key_text = _clean(key).lower()
                value_text = _clean(value)
                if key_text in _RAW_IDENTIFIER_KEYS or _NRIC_PATTERN.search(value_text):
                    return [
                        WarningCode.CPF_SNAPSHOT_MISSING,
                        WarningCode.TAX_SNAPSHOT_MISSING,
                        WarningCode.HDB_LOAN_SNAPSHOT_MISSING,
                    ]
    return []


def _cpf_ledger_rows(
    rows: list[dict[str, object]]
) -> tuple[list[dict[str, str]], list[WarningCode]]:
    ledger_rows: list[dict[str, str]] = []
    warnings: list[WarningCode] = []
    for row in rows:
        row_warnings: list[WarningCode] = []
        if any(_parse_number(row.get(field)) is None for field in ("oa", "sa", "ma", "ra", "total")):
            row_warnings.extend(
                [WarningCode.CPF_BALANCE_MISSING, WarningCode.CPF_REVIEW_REQUIRED]
            )
        if _yes(row.get("review_required")):
            row_warnings.append(WarningCode.CPF_REVIEW_REQUIRED)
        row_warnings = _dedupe_warning_codes(row_warnings)
        warnings.extend(row_warnings)
        ledger_rows.append(
            {
                "snapshot_date": _clean(row.get("snapshot_date")),
                "oa": _number_to_text(_parse_number(row.get("oa"))),
                "sa": _number_to_text(_parse_number(row.get("sa"))),
                "ma": _number_to_text(_parse_number(row.get("ma"))),
                "ra": _number_to_text(_parse_number(row.get("ra"))),
                "total": _number_to_text(_parse_number(row.get("total"))),
                "currency": _clean(row.get("currency")) or "SGD",
                "source_type": _clean(row.get("source_type")),
                "source_date": _clean(row.get("source_date")),
                "review_required": _review_text(row, row_warnings),
                "warning_codes": _warning_text(row_warnings),
            }
        )
    return ledger_rows, _dedupe_warning_codes(warnings)


def _srs_ledger_rows(
    rows: list[dict[str, object]]
) -> tuple[list[dict[str, str]], list[WarningCode]]:
    ledger_rows: list[dict[str, str]] = []
    warnings: list[WarningCode] = []
    for row in rows:
        row_warnings = [WarningCode.SRS_TAX_WRAPPER_REVIEW]
        if any(
            _parse_number(row.get(field)) is None
            for field in ("cash", "investments_value", "total", "contribution_ytd")
        ):
            row_warnings.append(WarningCode.SRS_BALANCE_MISSING)
        if _yes(row.get("review_required")):
            row_warnings.append(WarningCode.SRS_TAX_WRAPPER_REVIEW)
        row_warnings = _dedupe_warning_codes(row_warnings)
        warnings.extend(row_warnings)
        ledger_rows.append(
            {
                "snapshot_date": _clean(row.get("snapshot_date")),
                "provider_label": _clean(row.get("provider_label")),
                "cash": _number_to_text(_parse_number(row.get("cash"))),
                "investments_value": _number_to_text(_parse_number(row.get("investments_value"))),
                "total": _number_to_text(_parse_number(row.get("total"))),
                "contribution_ytd": _number_to_text(_parse_number(row.get("contribution_ytd"))),
                "currency": _clean(row.get("currency")) or "SGD",
                "tax_wrapper": "true",
                "source_type": _clean(row.get("source_type")),
                "source_date": _clean(row.get("source_date")),
                "review_required": _review_text(row, row_warnings),
                "warning_codes": _warning_text(row_warnings),
            }
        )
    return ledger_rows, _dedupe_warning_codes(warnings)


def _tax_ledger_rows(
    rows: list[dict[str, object]]
) -> tuple[list[dict[str, str]], list[WarningCode]]:
    ledger_rows: list[dict[str, str]] = []
    warnings: list[WarningCode] = []
    availability_fields = (
        "assessable_income_available",
        "tax_payable_available",
        "tax_paid_available",
        "reliefs_available",
    )
    for row in rows:
        row_warnings = [WarningCode.TAX_REVIEW_REQUIRED]
        if any(_availability(row.get(field)) == "unknown" for field in availability_fields):
            row_warnings.append(WarningCode.TAX_DATA_INCOMPLETE)
        row_warnings = _dedupe_warning_codes(row_warnings)
        warnings.extend(row_warnings)
        ledger_rows.append(
            {
                "year_of_assessment": _clean(row.get("year_of_assessment")),
                "assessable_income_available": _availability(row.get("assessable_income_available")),
                "tax_payable_available": _availability(row.get("tax_payable_available")),
                "tax_paid_available": _availability(row.get("tax_paid_available")),
                "reliefs_available": _availability(row.get("reliefs_available")),
                "source_type": _clean(row.get("source_type")),
                "source_date": _clean(row.get("source_date")),
                "review_required": "yes",
                "warning_codes": _warning_text(row_warnings),
            }
        )
    return ledger_rows, _dedupe_warning_codes(warnings)


def _hdb_loan_ledger_rows(
    rows: list[dict[str, object]]
) -> tuple[list[dict[str, str]], list[WarningCode]]:
    ledger_rows: list[dict[str, str]] = []
    warnings: list[WarningCode] = []
    for row in rows:
        row_warnings: list[WarningCode] = []
        if _availability(row.get("monthly_installment_available")) == "unknown":
            row_warnings.append(WarningCode.HDB_LOAN_BALANCE_MISSING)
        if _availability(row.get("outstanding_balance_available")) == "unknown":
            row_warnings.append(WarningCode.HDB_LOAN_BALANCE_MISSING)
        if not _clean(row.get("linked_property_id_hash")):
            row_warnings.append(WarningCode.HDB_LOAN_PROPERTY_LINK_MISSING)
        row_warnings = _dedupe_warning_codes(row_warnings)
        warnings.extend(row_warnings)
        ledger_rows.append(
            {
                "snapshot_date": _clean(row.get("snapshot_date")),
                "loan_id_hash": _clean(row.get("loan_id_hash")),
                "linked_property_id_hash": _clean(row.get("linked_property_id_hash")),
                "monthly_installment_available": _availability(
                    row.get("monthly_installment_available")
                ),
                "outstanding_balance_available": _availability(
                    row.get("outstanding_balance_available")
                ),
                "currency": _clean(row.get("currency")) or "SGD",
                "source_type": _clean(row.get("source_type")),
                "source_date": _clean(row.get("source_date")),
                "review_required": _review_text(row, row_warnings),
                "warning_codes": _warning_text(row_warnings),
            }
        )
    return ledger_rows, _dedupe_warning_codes(warnings)


def _summary(
    *,
    generated_at: datetime,
    cpf_rows: list[dict[str, str]],
    srs_rows: list[dict[str, str]],
    tax_rows: list[dict[str, str]],
    hdb_rows: list[dict[str, str]],
    warnings: list[WarningCode],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "cpf_row_count": len(cpf_rows),
        "srs_row_count": len(srs_rows),
        "tax_row_count": len(tax_rows),
        "hdb_loan_row_count": len(hdb_rows),
        "retirement_tax_wrapper_buckets": ["cpf", "srs"],
        "tax_snapshot_mode": "informational_review_only",
        "hdb_loan_snapshot_mode": "manual_snapshot_only",
        "review_required": "yes" if _review_required([*cpf_rows, *srs_rows, *tax_rows, *hdb_rows]) else "no",
        "warning_codes": [code.value for code in warnings],
    }


def _review_required(rows: list[dict[str, str]]) -> bool:
    return any(row.get("review_required") == "yes" for row in rows)


def _read_records(path: Path, json_key: str) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        candidate = payload.get(json_key)
        rows = candidate if isinstance(candidate, list) else []
    else:
        rows = []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = [
        "# Singapore Retirement Tax Snapshot Warnings",
        "",
        "This file lists warning codes for the offline manual Singapore snapshot.",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown(
    path: Path, *, summary: dict[str, object], warnings: list[WarningCode]
) -> None:
    lines = [
        "# Singapore Retirement Tax Snapshot v0.4.4",
        "",
        "This local snapshot records manual CPF, SRS, tax, and HDB loan review data.",
        "It uses offline files only and does not connect to external portals or accounts.",
        "The tax section is informational and review-only; it does not file taxes or give advice.",
        "",
        "## Snapshot",
        f"- CPF rows: {summary['cpf_row_count']}",
        f"- SRS rows: {summary['srs_row_count']}",
        f"- Tax rows: {summary['tax_row_count']}",
        f"- HDB loan rows: {summary['hdb_loan_row_count']}",
        f"- Review required: {summary['review_required']}",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_number(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _number_to_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _availability(value: object) -> str:
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y", "available"}:
        return "yes"
    if text in {"0", "false", "no", "n", "unavailable"}:
        return "no"
    return "unknown"


def _review_text(row: dict[str, object], warnings: list[WarningCode]) -> str:
    if warnings or _yes(row.get("review_required")):
        return "yes"
    return "no"


def _warning_text(warnings: list[WarningCode]) -> str:
    return ",".join(code.value for code in warnings)


def _yes(value: object) -> bool:
    return _clean(value).lower() in {"1", "true", "yes", "y"}


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
