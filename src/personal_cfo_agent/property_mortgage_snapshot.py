"""Offline manual property and mortgage snapshot generation."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.4.3"
STALE_VALUATION_DAYS = 90

PROPERTY_ASSET_LEDGER_FIELDNAMES = [
    "property_id_hash",
    "label",
    "type",
    "country",
    "area",
    "ownership_pct",
    "valuation_amount",
    "currency",
    "valuation_date",
    "source",
    "confidence",
    "review_required",
]

MORTGAGE_LIABILITY_LEDGER_FIELDNAMES = [
    "loan_id_hash",
    "linked_property_id_hash",
    "lender_label",
    "outstanding_balance",
    "currency",
    "interest_rate",
    "rate_type",
    "monthly_payment",
    "repricing_date",
    "maturity_date",
    "snapshot_date",
    "review_required",
]


@dataclass
class PropertyMortgageSnapshotResult:
    property_input: Path
    mortgage_input: Path
    output_dir: Path | None
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    property_count: int = 0
    mortgage_count: int = 0
    unlinked_mortgage_count: int = 0
    generated: bool = False


def record_property_mortgage_snapshot(
    *,
    property_input: Path,
    mortgage_input: Path,
    out_dir: Path,
    generated_at: datetime | None = None,
) -> PropertyMortgageSnapshotResult:
    """Record a local manual property/mortgage snapshot from offline inputs."""

    generated_at = generated_at or datetime.now(timezone.utc)
    snapshot_date = generated_at.date().isoformat()
    warnings: list[WarningCode] = []
    if not property_input.exists() or not mortgage_input.exists():
        return PropertyMortgageSnapshotResult(
            property_input=property_input,
            mortgage_input=mortgage_input,
            output_dir=None,
            warning_codes=[
                WarningCode.PROPERTY_MORTGAGE_INPUT_MISSING,
                WarningCode.PROPERTY_MORTGAGE_FAILED,
            ],
        )

    property_rows = _read_records(property_input, "properties")
    mortgage_rows = _read_records(mortgage_input, "mortgages")
    if not property_rows:
        return _failed_result(
            property_input,
            mortgage_input,
            [WarningCode.PROPERTY_INPUT_EMPTY, WarningCode.PROPERTY_MORTGAGE_FAILED],
        )
    if not mortgage_rows:
        warnings.append(WarningCode.MORTGAGE_INPUT_EMPTY)

    property_validation_warnings = _validate_properties(property_rows, generated_at.date())
    mortgage_validation_warnings = _validate_mortgages(mortgage_rows)
    terminal_warnings = [
        code
        for code in [*property_validation_warnings, *mortgage_validation_warnings]
        if code
        in {
            WarningCode.PROPERTY_REQUIRED_FIELD_MISSING,
            WarningCode.PROPERTY_OWNERSHIP_MISSING,
            WarningCode.PROPERTY_VALUATION_MISSING,
            WarningCode.MORTGAGE_REQUIRED_FIELD_MISSING,
        }
    ]
    if terminal_warnings:
        return _failed_result(
            property_input,
            mortgage_input,
            _dedupe_warning_codes(
                [
                    *warnings,
                    *property_validation_warnings,
                    *mortgage_validation_warnings,
                    WarningCode.PROPERTY_MORTGAGE_FAILED,
                ]
            ),
        )

    property_ids = {_clean(row.get("property_id_hash")) for row in property_rows}
    link_warnings, unlinked_mortgage_count = _mortgage_link_warnings(
        mortgage_rows, property_ids
    )
    warnings = _dedupe_warning_codes(
        [
            *warnings,
            *property_validation_warnings,
            *mortgage_validation_warnings,
            *link_warnings,
        ]
    )
    if any(_yes(row.get("review_required")) for row in [*property_rows, *mortgage_rows]):
        warnings.append(WarningCode.PROPERTY_MORTGAGE_REVIEW_REQUIRED)
    completion = (
        WarningCode.PROPERTY_MORTGAGE_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.PROPERTY_MORTGAGE_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    out_dir.mkdir(parents=True, exist_ok=True)
    property_ledger_rows = [_property_ledger_row(row) for row in property_rows]
    mortgage_ledger_rows = [_mortgage_ledger_row(row, snapshot_date) for row in mortgage_rows]
    summary = _equity_summary(
        property_rows=property_ledger_rows,
        mortgage_rows=mortgage_ledger_rows,
        snapshot_date=snapshot_date,
        warning_codes=warnings,
        unlinked_mortgage_count=unlinked_mortgage_count,
    )

    paths = {
        "property_asset_ledger": out_dir / "property_asset_ledger.csv",
        "mortgage_liability_ledger": out_dir / "mortgage_liability_ledger.csv",
        "property_equity_summary": out_dir / "property_equity_summary.json",
        "property_mortgage_warnings": out_dir / "property_mortgage_warnings.md",
        "markdown_report": out_dir / "PROPERTY_MORTGAGE_SNAPSHOT_V043.md",
    }
    _write_csv(paths["property_asset_ledger"], PROPERTY_ASSET_LEDGER_FIELDNAMES, property_ledger_rows)
    _write_csv(
        paths["mortgage_liability_ledger"],
        MORTGAGE_LIABILITY_LEDGER_FIELDNAMES,
        mortgage_ledger_rows,
    )
    paths["property_equity_summary"].write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _write_warnings(paths["property_mortgage_warnings"], warnings)
    _write_markdown(paths["markdown_report"], summary=summary, warnings=warnings)

    return PropertyMortgageSnapshotResult(
        property_input=property_input,
        mortgage_input=mortgage_input,
        output_dir=out_dir,
        output_paths=paths,
        warning_codes=warnings,
        property_count=len(property_ledger_rows),
        mortgage_count=len(mortgage_ledger_rows),
        unlinked_mortgage_count=unlinked_mortgage_count,
        generated=True,
    )


def _failed_result(
    property_input: Path,
    mortgage_input: Path,
    warnings: list[WarningCode],
) -> PropertyMortgageSnapshotResult:
    return PropertyMortgageSnapshotResult(
        property_input=property_input,
        mortgage_input=mortgage_input,
        output_dir=None,
        warning_codes=_dedupe_warning_codes(warnings),
    )


def _validate_properties(
    rows: list[dict[str, object]], today: date
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    for row in rows:
        for field in ("property_id_hash", "label", "type", "country", "currency"):
            if not _clean(row.get(field)):
                warnings.append(WarningCode.PROPERTY_REQUIRED_FIELD_MISSING)
        if _parse_number(row.get("ownership_pct")) is None:
            warnings.append(WarningCode.PROPERTY_OWNERSHIP_MISSING)
        if _parse_number(row.get("valuation_amount")) is None:
            warnings.append(WarningCode.PROPERTY_VALUATION_MISSING)
        valuation_date = _parse_date(row.get("valuation_date"))
        if valuation_date is None:
            warnings.append(WarningCode.MISSING_VALUATION_DATE)
        elif (today - valuation_date).days > STALE_VALUATION_DAYS:
            warnings.append(WarningCode.PROPERTY_VALUATION_STALE)
    return _dedupe_warning_codes(warnings)


def _validate_mortgages(rows: list[dict[str, object]]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    for row in rows:
        for field in ("loan_id_hash", "lender_label", "outstanding_balance", "currency"):
            if not _clean(row.get(field)):
                warnings.append(WarningCode.MORTGAGE_REQUIRED_FIELD_MISSING)
        if _parse_number(row.get("outstanding_balance")) is None:
            warnings.append(WarningCode.MORTGAGE_REQUIRED_FIELD_MISSING)
    return _dedupe_warning_codes(warnings)


def _mortgage_link_warnings(
    rows: list[dict[str, object]], property_ids: set[str]
) -> tuple[list[WarningCode], int]:
    warnings: list[WarningCode] = []
    unlinked_count = 0
    for row in rows:
        linked_property_id = _clean(row.get("linked_property_id_hash"))
        if not linked_property_id:
            warnings.append(WarningCode.MORTGAGE_UNLINKED)
            unlinked_count += 1
        elif linked_property_id not in property_ids:
            warnings.append(WarningCode.MORTGAGE_PROPERTY_LINK_MISSING)
            unlinked_count += 1
    return _dedupe_warning_codes(warnings), unlinked_count


def _property_ledger_row(row: dict[str, object]) -> dict[str, str]:
    return {
        "property_id_hash": _clean(row.get("property_id_hash")),
        "label": _clean(row.get("label")),
        "type": _clean(row.get("type")),
        "country": _clean(row.get("country")),
        "area": _clean(row.get("area")),
        "ownership_pct": _number_to_text(_parse_number(row.get("ownership_pct"))),
        "valuation_amount": _number_to_text(_parse_number(row.get("valuation_amount"))),
        "currency": _clean(row.get("currency")),
        "valuation_date": _clean(row.get("valuation_date")),
        "source": _clean(row.get("source")),
        "confidence": _clean(row.get("confidence")),
        "review_required": "yes" if _yes(row.get("review_required")) else "no",
    }


def _mortgage_ledger_row(row: dict[str, object], snapshot_date: str) -> dict[str, str]:
    return {
        "loan_id_hash": _clean(row.get("loan_id_hash")),
        "linked_property_id_hash": _clean(row.get("linked_property_id_hash")),
        "lender_label": _clean(row.get("lender_label")),
        "outstanding_balance": _number_to_text(_parse_number(row.get("outstanding_balance"))),
        "currency": _clean(row.get("currency")),
        "interest_rate": _number_to_text(_parse_number(row.get("interest_rate"))),
        "rate_type": _clean(row.get("rate_type")),
        "monthly_payment": _number_to_text(_parse_number(row.get("monthly_payment"))),
        "repricing_date": _clean(row.get("repricing_date")),
        "maturity_date": _clean(row.get("maturity_date")),
        "snapshot_date": _clean(row.get("snapshot_date")) or snapshot_date,
        "review_required": "yes" if _yes(row.get("review_required")) else "no",
    }


def _equity_summary(
    *,
    property_rows: list[dict[str, str]],
    mortgage_rows: list[dict[str, str]],
    snapshot_date: str,
    warning_codes: list[WarningCode],
    unlinked_mortgage_count: int,
) -> dict[str, object]:
    mortgage_by_property: dict[str, float] = {}
    unlinked_liability_total_by_currency: dict[str, float] = {}
    for row in mortgage_rows:
        balance = _parse_number(row.get("outstanding_balance")) or 0.0
        linked_property_id = _clean(row.get("linked_property_id_hash"))
        if linked_property_id:
            mortgage_by_property[linked_property_id] = (
                mortgage_by_property.get(linked_property_id, 0.0) + balance
            )
        else:
            currency = _clean(row.get("currency")) or "UNKNOWN"
            unlinked_liability_total_by_currency[currency] = (
                unlinked_liability_total_by_currency.get(currency, 0.0) + balance
            )

    property_equity_rows: list[dict[str, str]] = []
    total_equity_by_currency: dict[str, float] = {}
    for row in property_rows:
        property_id = _clean(row.get("property_id_hash"))
        currency = _clean(row.get("currency")) or "UNKNOWN"
        value = _parse_number(row.get("valuation_amount")) or 0.0
        ownership = _parse_number(row.get("ownership_pct")) or 0.0
        owned_value = value * ownership
        linked_mortgage_balance = mortgage_by_property.get(property_id, 0.0)
        equity = owned_value - linked_mortgage_balance
        total_equity_by_currency[currency] = total_equity_by_currency.get(currency, 0.0) + equity
        property_equity_rows.append(
            {
                "property_id_hash": property_id,
                "currency": currency,
                "owned_property_value": _number_to_text(owned_value),
                "linked_mortgage_balance": _number_to_text(linked_mortgage_balance),
                "equity": _number_to_text(equity),
                "review_required": row.get("review_required", "no"),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_date": snapshot_date,
        "property_count": len(property_rows),
        "mortgage_count": len(mortgage_rows),
        "unlinked_mortgage_count": unlinked_mortgage_count,
        "property_equity_rows": property_equity_rows,
        "total_equity_by_currency": {
            currency: _number_to_text(value)
            for currency, value in sorted(total_equity_by_currency.items())
        },
        "unlinked_liability_total_by_currency": {
            currency: _number_to_text(value)
            for currency, value in sorted(unlinked_liability_total_by_currency.items())
        },
        "warning_codes": [code.value for code in warning_codes],
        "review_required": "yes" if _review_required(warning_codes, property_rows, mortgage_rows) else "no",
        "source": "manual_offline_snapshot",
    }


def _review_required(
    warnings: list[WarningCode],
    property_rows: list[dict[str, str]],
    mortgage_rows: list[dict[str, str]],
) -> bool:
    if any(row.get("review_required") == "yes" for row in [*property_rows, *mortgage_rows]):
        return True
    return any(
        code
        not in {
            WarningCode.PROPERTY_MORTGAGE_GENERATED_OK,
        }
        for code in warnings
    )


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
        "# Property Mortgage Snapshot Warnings",
        "",
        "This file lists warning codes for the offline manual property and mortgage snapshot.",
        "",
        "## Warning Codes",
    ]
    lines.extend(f"- {code.value}" for code in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown(
    path: Path, *, summary: dict[str, object], warnings: list[WarningCode]
) -> None:
    lines = [
        "# Property Mortgage Snapshot v0.4.3",
        "",
        "This local snapshot records manual property assets and mortgage liabilities.",
        "It uses offline files only and does not connect to banks, HDB, SingPass, browsers, or brokers.",
        "It does not move money, place orders, or produce recommendations.",
        "",
        "## Snapshot",
        f"- Property count: {summary['property_count']}",
        f"- Mortgage count: {summary['mortgage_count']}",
        f"- Unlinked mortgage count: {summary['unlinked_mortgage_count']}",
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


def _parse_date(value: object) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _number_to_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


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
