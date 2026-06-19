"""Unified local-only private input center for manual Personal CFO data."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from personal_cfo_agent.manual_nav_input import (
    ManualNavBundleResult,
    manual_nav_to_provider_bundle,
    validate_manual_nav_input,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.property_mortgage_snapshot import (
    PropertyMortgageSnapshotResult,
    record_property_mortgage_snapshot,
)
from personal_cfo_agent.sg_manual_snapshot import (
    SGManualSnapshotResult,
    record_sg_manual_snapshot,
)


SCHEMA_VERSION = "v0.5.8"
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "templates" / "private_inputs"
PRIVATE_INPUT_CENTER_EXAMPLE = TEMPLATE_DIR / "personal_cfo_input.example.json"
PRIVATE_INPUT_CENTER_FORM_TEMPLATE = TEMPLATE_DIR / "personal_cfo_input_form.html"

SECTION_KEYS = (
    "manual_nav_accounts",
    "properties",
    "mortgages",
    "cpf",
    "srs",
    "tax",
    "hdb_loans",
)

_NRIC_PATTERN = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
_FORBIDDEN_KEYS = {
    "account_id",
    "account_number",
    "raw_account_id",
    "raw_account_number",
    "address",
    "raw_address",
    "postal_code",
    "unit_number",
    "nric",
    "fin",
    "uin",
    "government_id",
    "identity_number",
    "cpf_account_number",
    "hdb_account_number",
    "tax_reference_number",
    "bank_account_number",
    "password",
    "token",
    "secret",
    "api_key",
}


@dataclass(frozen=True)
class PrivateInputCenterFormResult:
    output_dir: Path
    output_path: Path
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterInitResult:
    output_file: Path
    created: bool
    skipped: bool
    overwritten: bool
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterValidationResult:
    input_file: Path
    valid: bool
    manual_nav_account_count: int = 0
    property_count: int = 0
    mortgage_count: int = 0
    cpf_count: int = 0
    srs_count: int = 0
    tax_count: int = 0
    hdb_loan_count: int = 0
    provider_labels: list[str] = field(default_factory=list)
    base_currencies: list[str] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterSnapshotResult:
    input_file: Path
    output_dir: Path
    manual_nav_output_dir: Path
    property_output_dir: Path
    sg_output_dir: Path
    manual_nav_result: ManualNavBundleResult | None = None
    property_result: PropertyMortgageSnapshotResult | None = None
    sg_result: SGManualSnapshotResult | None = None
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False


def generate_private_input_center_form(*, out_dir: Path) -> PrivateInputCenterFormResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "personal_cfo_input_form.html"
    shutil.copyfile(PRIVATE_INPUT_CENTER_FORM_TEMPLATE, output_path)
    return PrivateInputCenterFormResult(
        output_dir=out_dir,
        output_path=output_path,
        warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_FORM_GENERATED],
    )


def init_private_input_center(
    *, out_file: Path, overwrite: bool = False
) -> PrivateInputCenterInitResult:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists() and not overwrite:
        return PrivateInputCenterInitResult(
            output_file=out_file,
            created=False,
            skipped=True,
            overwritten=False,
            warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_EXISTS_SKIPPED],
        )
    overwritten = out_file.exists()
    shutil.copyfile(PRIVATE_INPUT_CENTER_EXAMPLE, out_file)
    warnings = [WarningCode.PRIVATE_INPUT_CENTER_INITIALIZED]
    if overwritten:
        warnings.append(WarningCode.PRIVATE_INPUT_CENTER_OVERWRITE_USED)
    return PrivateInputCenterInitResult(
        output_file=out_file,
        created=not overwritten,
        skipped=False,
        overwritten=overwritten,
        warning_codes=warnings,
    )


def validate_private_input_center(*, input_file: Path) -> PrivateInputCenterValidationResult:
    payload, read_warnings = _load_payload(input_file)
    if payload is None:
        return PrivateInputCenterValidationResult(
            input_file=input_file,
            valid=False,
            warning_codes=read_warnings,
        )
    with tempfile.TemporaryDirectory(prefix="personal_cfo_input_center_") as temp_name:
        temp_dir = Path(temp_name)
        split_paths = _write_split_inputs(payload, temp_dir)
        manual_result = validate_manual_nav_input(input_file=split_paths["manual_nav"])

    warnings = _dedupe(
        [
            *_payload_warnings(payload),
            *_map_manual_nav_warnings(manual_result.warning_codes),
        ]
    )
    blocking = {
        WarningCode.PRIVATE_INPUT_CENTER_INPUT_MISSING,
        WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID,
        WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING,
        WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED,
    }
    valid = not any(code in blocking for code in warnings)
    completion = (
        WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_FAILED
        if not valid
        else WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS
        if warnings
        else WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_OK
    )
    return PrivateInputCenterValidationResult(
        input_file=input_file,
        valid=valid,
        manual_nav_account_count=_section_count(payload, "manual_nav_accounts"),
        property_count=_section_count(payload, "properties"),
        mortgage_count=_section_count(payload, "mortgages"),
        cpf_count=_section_count(payload, "cpf"),
        srs_count=_section_count(payload, "srs"),
        tax_count=_section_count(payload, "tax"),
        hdb_loan_count=_section_count(payload, "hdb_loans"),
        provider_labels=sorted(
            {
                _clean(account.get("provider_label"))
                for account in _rows(payload, "manual_nav_accounts")
                if _clean(account.get("provider_label"))
            }
        ),
        base_currencies=sorted(
            {
                _clean(account.get("base_currency"))
                for account in _rows(payload, "manual_nav_accounts")
                if _clean(account.get("base_currency"))
            }
        ),
        warning_codes=_dedupe([*warnings, completion]),
    )


def private_input_center_to_snapshots(
    *,
    input_file: Path,
    out_dir: Path,
    env: Mapping[str, str],
    generated_at: datetime | None = None,
) -> PrivateInputCenterSnapshotResult:
    validation = validate_private_input_center(input_file=input_file)
    manual_out = out_dir / "manual_nav"
    property_out = out_dir / "property_mortgage"
    sg_out = out_dir / "sg_retirement_tax"
    if not validation.valid:
        return PrivateInputCenterSnapshotResult(
            input_file=input_file,
            output_dir=out_dir,
            manual_nav_output_dir=manual_out,
            property_output_dir=property_out,
            sg_output_dir=sg_out,
            warning_codes=_dedupe(
                [
                    *validation.warning_codes,
                    WarningCode.PRIVATE_INPUT_CENTER_GENERATION_FAILED,
                ]
            ),
        )

    payload, _ = _load_payload(input_file)
    assert payload is not None
    generated_at = generated_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="personal_cfo_input_center_") as temp_name:
        split_paths = _write_split_inputs(payload, Path(temp_name))
        manual_result = manual_nav_to_provider_bundle(
            input_file=split_paths["manual_nav"],
            out_dir=manual_out,
            env=env,
            generated_at=generated_at,
        )
        property_result = record_property_mortgage_snapshot(
            property_input=split_paths["property"],
            mortgage_input=split_paths["mortgage"],
            out_dir=property_out,
            generated_at=generated_at,
        )
        sg_result = record_sg_manual_snapshot(
            cpf_input=split_paths["cpf"],
            srs_input=split_paths["srs"],
            tax_input=split_paths["tax"],
            hdb_loan_input=split_paths["hdb_loan"],
            out_dir=sg_out,
            generated_at=generated_at,
        )

    validation_warnings = [
        code
        for code in validation.warning_codes
        if code
        not in {
            WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_OK,
            WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS,
        }
    ]
    warnings = _dedupe(
        [
            *validation_warnings,
            *manual_result.warning_codes,
            *property_result.warning_codes,
            *sg_result.warning_codes,
        ]
    )
    generated = manual_result.generated and property_result.generated and sg_result.generated
    completion = (
        WarningCode.PRIVATE_INPUT_CENTER_GENERATED_WITH_WARNINGS
        if generated and warnings
        else WarningCode.PRIVATE_INPUT_CENTER_GENERATED_OK
        if generated
        else WarningCode.PRIVATE_INPUT_CENTER_GENERATION_FAILED
    )
    return PrivateInputCenterSnapshotResult(
        input_file=input_file,
        output_dir=out_dir,
        manual_nav_output_dir=manual_out,
        property_output_dir=property_out,
        sg_output_dir=sg_out,
        manual_nav_result=manual_result,
        property_result=property_result,
        sg_result=sg_result,
        warning_codes=_dedupe([*warnings, completion]),
        generated=generated,
    )


def _load_payload(path: Path) -> tuple[dict[str, Any] | None, list[WarningCode]]:
    if not path.exists():
        return None, [WarningCode.PRIVATE_INPUT_CENTER_INPUT_MISSING]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, [WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID]
    if not isinstance(payload, dict):
        return None, [WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID]
    return payload, []


def _payload_warnings(payload: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    for key in ("schema_version", "snapshot_date", "base_currency", "source_type", "review_required"):
        if not _has_value(payload.get(key)):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    if _parse_date(payload.get("snapshot_date")) is None:
        warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    for section in SECTION_KEYS:
        if not isinstance(payload.get(section), list) or not payload.get(section):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID)
    if _contains_raw_identifier(payload):
        warnings.append(WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED)
    warnings.extend(_property_warnings(_rows(payload, "properties")))
    warnings.extend(_mortgage_warnings(_rows(payload, "mortgages")))
    warnings.extend(_sg_date_warnings(payload))
    return _dedupe(warnings)


def _property_warnings(rows: list[dict[str, Any]]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    required = (
        "property_id_hash",
        "label",
        "type",
        "country",
        "ownership_pct",
        "valuation_amount",
        "currency",
        "valuation_date",
    )
    optional = ("area", "source", "confidence")
    for row in rows:
        if any(not _has_value(row.get(field)) for field in required):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
        if any(not _has_value(row.get(field)) for field in optional):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_OPTIONAL_FIELD_MISSING)
    return warnings


def _mortgage_warnings(rows: list[dict[str, Any]]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    required = ("loan_id_hash", "lender_label", "outstanding_balance", "currency")
    optional = (
        "linked_property_id_hash",
        "interest_rate",
        "rate_type",
        "monthly_payment",
        "repricing_date",
        "maturity_date",
        "snapshot_date",
    )
    for row in rows:
        if any(not _has_value(row.get(field)) for field in required):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
        if any(not _has_value(row.get(field)) for field in optional):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_OPTIONAL_FIELD_MISSING)
    return warnings


def _sg_date_warnings(payload: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    for section in ("cpf", "srs", "hdb_loans"):
        for row in _rows(payload, section):
            if _parse_date(row.get("snapshot_date")) is None:
                warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    for row in _rows(payload, "tax"):
        if not _has_value(row.get("year_of_assessment")):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    return warnings


def _map_manual_nav_warnings(codes: list[WarningCode]) -> list[WarningCode]:
    mapped: list[WarningCode] = []
    for code in codes:
        if code in {
            WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING,
            WarningCode.MANUAL_NAV_SCHEMA_INVALID,
            WarningCode.MANUAL_NAV_INPUT_MISSING,
        }:
            mapped.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
        elif code == WarningCode.MANUAL_NAV_RAW_IDENTIFIER_DETECTED:
            mapped.append(WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED)
        elif code in {
            WarningCode.MANUAL_NAV_OPTIONAL_SPLIT_MISSING,
            WarningCode.MANUAL_NAV_MIXED_CURRENCIES,
        }:
            mapped.append(code)
    return mapped


def _write_split_inputs(payload: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "manual_nav": out_dir / "manual_nav_input.local.json",
        "property": out_dir / "property_snapshot.json",
        "mortgage": out_dir / "mortgage_snapshot.json",
        "cpf": out_dir / "cpf_snapshot.json",
        "srs": out_dir / "srs_snapshot.json",
        "tax": out_dir / "tax_snapshot.json",
        "hdb_loan": out_dir / "hdb_loan_snapshot.json",
    }
    _write_json(
        paths["manual_nav"],
        {
            "schema_version": "v0.5.7",
            "snapshot_date": _clean(payload.get("snapshot_date")),
            "base_currency": _clean(payload.get("base_currency")),
            "source_type": _clean(payload.get("source_type")),
            "review_required": payload.get("review_required", True),
            "accounts": _rows(payload, "manual_nav_accounts"),
        },
    )
    _write_json(paths["property"], {"properties": _rows(payload, "properties")})
    _write_json(paths["mortgage"], {"mortgages": _rows(payload, "mortgages")})
    _write_json(paths["cpf"], {"cpf": _rows(payload, "cpf")})
    _write_json(paths["srs"], {"srs_accounts": _rows(payload, "srs")})
    _write_json(paths["tax"], {"tax_records": _rows(payload, "tax")})
    _write_json(paths["hdb_loan"], {"hdb_loans": _rows(payload, "hdb_loans")})
    return paths


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _rows(payload: dict[str, Any], section: str) -> list[dict[str, Any]]:
    rows = payload.get(section)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _section_count(payload: dict[str, Any], section: str) -> int:
    return len(_rows(payload, section))


def _contains_raw_identifier(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                return True
            if _contains_raw_identifier(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_raw_identifier(item) for item in value)
    if isinstance(value, str):
        return bool(_NRIC_PATTERN.search(value))
    return False


def _parse_date(value: object) -> date | None:
    text = _clean(value)
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


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
