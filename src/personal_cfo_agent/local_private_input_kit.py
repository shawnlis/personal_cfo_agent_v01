"""Local-only private input templates, validation, and manual snapshot chain."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.property_mortgage_snapshot import (
    PropertyMortgageSnapshotResult,
    record_property_mortgage_snapshot,
)
from personal_cfo_agent.sg_manual_snapshot import (
    SGManualSnapshotResult,
    record_sg_manual_snapshot,
)


SCHEMA_VERSION = "v0.5.3"

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "templates" / "private_inputs"

PRIVATE_INPUT_FILES = {
    "property": "property_snapshot.json",
    "mortgage": "mortgage_snapshot.json",
    "cpf": "cpf_snapshot.json",
    "srs": "srs_snapshot.json",
    "tax": "tax_snapshot.json",
    "hdb_loan": "hdb_loan_snapshot.json",
}

TEMPLATE_FILES = {
    "property": "property_snapshot.example.json",
    "mortgage": "mortgage_snapshot.example.json",
    "cpf": "cpf_snapshot.example.json",
    "srs": "srs_snapshot.example.json",
    "tax": "tax_snapshot.example.json",
    "hdb_loan": "hdb_loan_snapshot.example.json",
}

_NRIC_PATTERN = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
_FORBIDDEN_KEYS = {
    "address",
    "raw_address",
    "postal_code",
    "unit_number",
    "nric",
    "fin",
    "uin",
    "raw_nric",
    "government_id",
    "identity_number",
    "account_number",
    "cpf_account_number",
    "hdb_account_number",
    "tax_reference_number",
    "bank_account_number",
}


@dataclass(frozen=True)
class PrivateInputFileValidation:
    file_name: str
    present: bool
    row_count: int = 0
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputKitInitResult:
    output_dir: Path
    created_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)
    overwritten_files: list[Path] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputValidationResult:
    input_dir: Path
    file_results: list[PrivateInputFileValidation] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)
    valid: bool = False


@dataclass(frozen=True)
class ManualSnapshotChainResult:
    input_dir: Path
    output_dir: Path
    property_output_dir: Path
    sg_output_dir: Path
    property_result: PropertyMortgageSnapshotResult | None = None
    sg_result: SGManualSnapshotResult | None = None
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False


def init_private_input_kit(
    *, out_dir: Path, overwrite: bool = False
) -> PrivateInputKitInitResult:
    """Copy committed placeholder templates into a local ignored input folder."""

    out_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    skipped: list[Path] = []
    overwritten: list[Path] = []
    warnings: list[WarningCode] = []

    for key, target_name in PRIVATE_INPUT_FILES.items():
        source = TEMPLATE_DIR / TEMPLATE_FILES[key]
        target = out_dir / target_name
        if target.exists() and not overwrite:
            skipped.append(target)
            warnings.append(WarningCode.PRIVATE_INPUT_FILE_EXISTS_SKIPPED)
            continue
        if target.exists() and overwrite:
            overwritten.append(target)
            warnings.append(WarningCode.PRIVATE_INPUT_OVERWRITE_USED)
        else:
            created.append(target)
        shutil.copyfile(source, target)

    if not warnings:
        warnings.append(WarningCode.PRIVATE_INPUT_KIT_INITIALIZED)
    else:
        warnings.append(WarningCode.PRIVATE_INPUT_KIT_INITIALIZED)
    return PrivateInputKitInitResult(
        output_dir=out_dir,
        created_files=created,
        skipped_files=skipped,
        overwritten_files=overwritten,
        warning_codes=_dedupe_warning_codes(warnings),
    )


def validate_private_inputs(*, input_dir: Path) -> PrivateInputValidationResult:
    """Validate local private input files without printing or returning values."""

    file_results = [
        _validate_one_file(input_dir / PRIVATE_INPUT_FILES[key], key)
        for key in PRIVATE_INPUT_FILES
    ]
    warnings = _dedupe_warning_codes(
        [code for result in file_results for code in result.warning_codes]
    )
    failed = any(
        code
        in {
            WarningCode.PRIVATE_INPUT_FILE_MISSING,
            WarningCode.PRIVATE_INPUT_SCHEMA_INVALID,
            WarningCode.PRIVATE_INPUT_REQUIRED_FIELD_MISSING,
            WarningCode.PRIVATE_INPUT_RAW_IDENTIFIER_DETECTED,
            WarningCode.PROPERTY_REQUIRED_FIELD_MISSING,
            WarningCode.PROPERTY_OWNERSHIP_MISSING,
            WarningCode.PROPERTY_VALUATION_MISSING,
            WarningCode.MORTGAGE_REQUIRED_FIELD_MISSING,
        }
        for code in warnings
    )
    if failed:
        warnings = _dedupe_warning_codes(
            [*warnings, WarningCode.PRIVATE_INPUT_VALIDATION_FAILED]
        )
    elif warnings:
        warnings = _dedupe_warning_codes(
            [*warnings, WarningCode.PRIVATE_INPUT_VALIDATION_WITH_WARNINGS]
        )
    else:
        warnings = [WarningCode.PRIVATE_INPUT_VALIDATION_OK]
    return PrivateInputValidationResult(
        input_dir=input_dir,
        file_results=file_results,
        warning_codes=warnings,
        valid=not failed,
    )


def run_manual_snapshot_chain(
    *, input_dir: Path, out_dir: Path, generated_at: datetime | None = None
) -> ManualSnapshotChainResult:
    """Run property/mortgage and Singapore manual snapshots from local inputs."""

    validation = validate_private_inputs(input_dir=input_dir)
    property_out = out_dir / "property_mortgage"
    sg_out = out_dir / "sg_retirement_tax"
    if not validation.valid:
        return ManualSnapshotChainResult(
            input_dir=input_dir,
            output_dir=out_dir,
            property_output_dir=property_out,
            sg_output_dir=sg_out,
            warning_codes=_dedupe_warning_codes(
                [*validation.warning_codes, WarningCode.PRIVATE_INPUT_CHAIN_FAILED]
            ),
        )

    generated_at = generated_at or datetime.now(timezone.utc)
    property_result = record_property_mortgage_snapshot(
        property_input=input_dir / PRIVATE_INPUT_FILES["property"],
        mortgage_input=input_dir / PRIVATE_INPUT_FILES["mortgage"],
        out_dir=property_out,
        generated_at=generated_at,
    )
    sg_result = record_sg_manual_snapshot(
        cpf_input=input_dir / PRIVATE_INPUT_FILES["cpf"],
        srs_input=input_dir / PRIVATE_INPUT_FILES["srs"],
        tax_input=input_dir / PRIVATE_INPUT_FILES["tax"],
        hdb_loan_input=input_dir / PRIVATE_INPUT_FILES["hdb_loan"],
        out_dir=sg_out,
        generated_at=generated_at,
    )
    generated = property_result.generated and sg_result.generated
    validation_warnings = [
        code
        for code in validation.warning_codes
        if code != WarningCode.PRIVATE_INPUT_VALIDATION_OK
    ]
    warnings = _dedupe_warning_codes(
        [
            *validation_warnings,
            *property_result.warning_codes,
            *sg_result.warning_codes,
        ]
    )
    completion = (
        WarningCode.PRIVATE_INPUT_CHAIN_GENERATED_WITH_WARNINGS
        if generated and warnings
        else WarningCode.PRIVATE_INPUT_CHAIN_GENERATED_OK
        if generated
        else WarningCode.PRIVATE_INPUT_CHAIN_FAILED
    )
    return ManualSnapshotChainResult(
        input_dir=input_dir,
        output_dir=out_dir,
        property_output_dir=property_out,
        sg_output_dir=sg_out,
        property_result=property_result,
        sg_result=sg_result,
        warning_codes=_dedupe_warning_codes([*warnings, completion]),
        generated=generated,
    )


def private_input_template_names() -> list[str]:
    return [TEMPLATE_FILES[key] for key in PRIVATE_INPUT_FILES]


def _validate_one_file(path: Path, key: str) -> PrivateInputFileValidation:
    if not path.exists():
        return PrivateInputFileValidation(
            file_name=path.name,
            present=False,
            warning_codes=[WarningCode.PRIVATE_INPUT_FILE_MISSING],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return PrivateInputFileValidation(
            file_name=path.name,
            present=True,
            warning_codes=[WarningCode.PRIVATE_INPUT_SCHEMA_INVALID],
        )

    top_key = _top_key_for(key)
    rows = payload.get(top_key) if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        return PrivateInputFileValidation(
            file_name=path.name,
            present=True,
            warning_codes=[WarningCode.PRIVATE_INPUT_SCHEMA_INVALID],
        )

    warnings: list[WarningCode] = []
    if _contains_raw_identifier(payload):
        warnings.append(WarningCode.PRIVATE_INPUT_RAW_IDENTIFIER_DETECTED)
    for row in rows:
        if any(not _has_value(row.get(field)) for field in _required_fields_for(key)):
            warnings.append(WarningCode.PRIVATE_INPUT_REQUIRED_FIELD_MISSING)
        if any(not _has_value(row.get(field)) for field in _optional_fields_for(key)):
            warnings.append(WarningCode.PRIVATE_INPUT_OPTIONAL_FIELD_MISSING)
        warnings.extend(_field_shape_warnings(key, row))
    return PrivateInputFileValidation(
        file_name=path.name,
        present=True,
        row_count=len(rows),
        warning_codes=_dedupe_warning_codes(warnings),
    )


def _top_key_for(key: str) -> str:
    return {
        "property": "properties",
        "mortgage": "mortgages",
        "cpf": "cpf",
        "srs": "srs_accounts",
        "tax": "tax_records",
        "hdb_loan": "hdb_loans",
    }[key]


def _required_fields_for(key: str) -> tuple[str, ...]:
    return {
        "property": (
            "property_id_hash",
            "label",
            "type",
            "country",
            "ownership_pct",
            "valuation_amount",
            "currency",
            "valuation_date",
        ),
        "mortgage": ("loan_id_hash", "lender_label", "outstanding_balance", "currency"),
        "cpf": ("snapshot_date", "currency", "source_type", "source_date"),
        "srs": ("snapshot_date", "provider_label", "currency", "source_type", "source_date"),
        "tax": ("year_of_assessment", "source_type", "source_date"),
        "hdb_loan": ("snapshot_date", "loan_id_hash", "currency", "source_type", "source_date"),
    }[key]


def _optional_fields_for(key: str) -> tuple[str, ...]:
    return {
        "property": ("area", "source", "confidence"),
        "mortgage": (
            "linked_property_id_hash",
            "interest_rate",
            "rate_type",
            "monthly_payment",
            "repricing_date",
            "maturity_date",
            "snapshot_date",
        ),
        "cpf": ("oa", "sa", "ma", "ra", "total"),
        "srs": ("cash", "investments_value", "total", "contribution_ytd"),
        "tax": (
            "assessable_income_available",
            "tax_payable_available",
            "tax_paid_available",
            "reliefs_available",
        ),
        "hdb_loan": (
            "linked_property_id_hash",
            "monthly_installment_available",
            "outstanding_balance_available",
        ),
    }[key]


def _contains_raw_identifier(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_KEYS:
                return True
            if _contains_raw_identifier(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_raw_identifier(item) for item in value)
    if isinstance(value, str):
        return bool(_NRIC_PATTERN.search(value))
    return False


def _field_shape_warnings(key: str, row: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if key == "property":
        if _parse_ownership_pct(row.get("ownership_pct")) is None:
            warnings.append(WarningCode.PROPERTY_OWNERSHIP_MISSING)
        if _parse_number(row.get("valuation_amount")) is None:
            warnings.append(WarningCode.PROPERTY_VALUATION_MISSING)
        valuation_date = _parse_date(row.get("valuation_date"))
        if valuation_date is None:
            warnings.append(WarningCode.MISSING_VALUATION_DATE)
        elif (date.today() - valuation_date).days > 90:
            warnings.append(WarningCode.PROPERTY_VALUATION_STALE)
    elif key == "mortgage":
        if _parse_number(row.get("outstanding_balance")) is None:
            warnings.append(WarningCode.MORTGAGE_REQUIRED_FIELD_MISSING)
    return warnings


def _parse_number(value: object) -> float | None:
    text = str(value).strip().replace(",", "") if value is not None else ""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_ownership_pct(value: object) -> float | None:
    text = str(value).strip().replace(",", "") if value is not None else ""
    if not text:
        return None
    if text.endswith("%"):
        parsed = _parse_number(text[:-1])
        return parsed / 100.0 if parsed is not None else None
    return _parse_number(text)


def _parse_date(value: object) -> date | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
