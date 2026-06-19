"""Unified local-only manual account NAV input tooling."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.5.7"
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "templates" / "private_inputs"
MANUAL_NAV_EXAMPLE = TEMPLATE_DIR / "manual_nav_input.example.json"
MANUAL_NAV_FORM_TEMPLATE = TEMPLATE_DIR / "manual_nav_form.html"

LEDGER_FIELDNAMES = [
    "provider",
    "account_id_hash",
    "source_bundle_id",
    "source_snapshot_id",
    "asset_type",
    "symbol",
    "name",
    "quantity",
    "currency",
    "base_currency",
    "market_value",
    "cost_basis",
    "average_cost",
    "unrealized_pnl",
    "account_nav",
    "total_assets",
    "cash_total",
    "securities_market_value",
    "margin_or_debt",
    "source_timestamp",
    "as_of_date",
    "source_confidence",
    "warning_codes",
]

ALLOWED_PROVIDER_LABELS = {"syfe_trade", "webull", "usmart", "other"}
ALLOWED_ACCOUNT_TYPES = {"brokerage", "robo", "cash", "retirement", "other"}
ALLOWED_SOURCE_TYPES = {"app_manual", "statement_manual", "screenshot_manual", "other", "synthetic_fixture"}
_RAW_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:account[_ -]?number|account[_ -]?id|nric|fin|password|token|secret|api[_ -]?key)\b",
    re.IGNORECASE,
)
_NRIC_PATTERN = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)


@dataclass(frozen=True)
class ManualNavFormResult:
    output_dir: Path
    output_path: Path
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class ManualNavInitResult:
    output_file: Path
    created: bool
    skipped: bool
    overwritten: bool
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class ManualNavValidationResult:
    input_file: Path
    valid: bool
    account_count: int
    provider_labels: list[str]
    base_currencies: list[str]
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class ManualNavBundleResult:
    input_file: Path
    output_dir: Path
    output_paths: dict[str, Path]
    generated: bool
    account_count: int
    provider_labels: list[str]
    warning_codes: list[WarningCode] = field(default_factory=list)


def generate_manual_nav_form(*, out_dir: Path) -> ManualNavFormResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "manual_nav_form.html"
    shutil.copyfile(MANUAL_NAV_FORM_TEMPLATE, output_path)
    return ManualNavFormResult(
        output_dir=out_dir,
        output_path=output_path,
        warning_codes=[WarningCode.MANUAL_NAV_FORM_GENERATED],
    )


def init_manual_nav_input(*, out_file: Path, overwrite: bool = False) -> ManualNavInitResult:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists() and not overwrite:
        return ManualNavInitResult(
            output_file=out_file,
            created=False,
            skipped=True,
            overwritten=False,
            warning_codes=[
                WarningCode.MANUAL_NAV_INPUT_EXISTS_SKIPPED,
            ],
        )
    overwritten = out_file.exists()
    shutil.copyfile(MANUAL_NAV_EXAMPLE, out_file)
    warnings = [WarningCode.MANUAL_NAV_INPUT_INITIALIZED]
    if overwritten:
        warnings.append(WarningCode.MANUAL_NAV_OVERWRITE_USED)
    return ManualNavInitResult(
        output_file=out_file,
        created=not overwritten,
        skipped=False,
        overwritten=overwritten,
        warning_codes=warnings,
    )


def validate_manual_nav_input(*, input_file: Path) -> ManualNavValidationResult:
    payload, read_warnings = _load_payload(input_file)
    if payload is None:
        return ManualNavValidationResult(
            input_file=input_file,
            valid=False,
            account_count=0,
            provider_labels=[],
            base_currencies=[],
            warning_codes=read_warnings,
        )
    warnings = _payload_warnings(payload)
    accounts = _accounts(payload)
    provider_labels = sorted(
        {_clean(account.get("provider_label")) for account in accounts if _clean(account.get("provider_label"))}
    )
    base_currencies = sorted(
        {_clean(account.get("base_currency")) for account in accounts if _clean(account.get("base_currency"))}
    )
    blocking = {
        WarningCode.MANUAL_NAV_INPUT_MISSING,
        WarningCode.MANUAL_NAV_SCHEMA_INVALID,
        WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING,
        WarningCode.MANUAL_NAV_RAW_IDENTIFIER_DETECTED,
    }
    valid = not any(code in blocking for code in warnings)
    if valid and len(base_currencies) > 1:
        warnings.append(WarningCode.MANUAL_NAV_MIXED_CURRENCIES)
    completion = (
        WarningCode.MANUAL_NAV_VALIDATION_FAILED
        if not valid
        else WarningCode.MANUAL_NAV_VALIDATION_WITH_WARNINGS
        if warnings
        else WarningCode.MANUAL_NAV_VALIDATION_OK
    )
    return ManualNavValidationResult(
        input_file=input_file,
        valid=valid,
        account_count=len(accounts),
        provider_labels=provider_labels,
        base_currencies=base_currencies,
        warning_codes=_dedupe([*warnings, completion]),
    )


def manual_nav_to_provider_bundle(
    *,
    input_file: Path,
    out_dir: Path,
    env: Mapping[str, str],
    generated_at: datetime | None = None,
) -> ManualNavBundleResult:
    validation = validate_manual_nav_input(input_file=input_file)
    hash_salt = _clean(env.get("CFO_ACCOUNT_HASH_SALT"))
    if not validation.valid or not hash_salt:
        warnings = [
            *validation.warning_codes,
            *([] if hash_salt else [WarningCode.MANUAL_NAV_HASH_SALT_MISSING]),
            WarningCode.MANUAL_NAV_BUNDLE_FAILED,
        ]
        return ManualNavBundleResult(
            input_file=input_file,
            output_dir=out_dir,
            output_paths={},
            generated=False,
            account_count=validation.account_count,
            provider_labels=validation.provider_labels,
            warning_codes=_dedupe(warnings),
        )

    payload, _ = _load_payload(input_file)
    assert payload is not None
    generated_at = generated_at or datetime.now(timezone.utc)
    source_bundle_id = f"manual_nav_v057_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
    source_snapshot_id = _clean(payload.get("snapshot_date")) or generated_at.strftime("%Y-%m-%d")
    rows = [
        _account_to_ledger_row(
            account,
            hash_salt=hash_salt,
            source_bundle_id=source_bundle_id,
            source_snapshot_id=source_snapshot_id,
        )
        for account in _accounts(payload)
    ]
    warnings = [
        code
        for code in validation.warning_codes
        if code
        not in {
            WarningCode.MANUAL_NAV_VALIDATION_OK,
            WarningCode.MANUAL_NAV_VALIDATION_WITH_WARNINGS,
        }
    ]
    completion = (
        WarningCode.MANUAL_NAV_BUNDLE_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.MANUAL_NAV_BUNDLE_GENERATED_OK
    )
    warnings = _dedupe([*warnings, completion])
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "normalized_asset_ledger": out_dir / "normalized_asset_ledger.csv",
        "provider_sync_summary": out_dir / "provider_sync_summary.json",
        "manual_nav_warnings": out_dir / "manual_nav_warnings.md",
        "markdown_report": out_dir / "MANUAL_NAV_INPUT_V057.md",
    }
    _write_csv(paths["normalized_asset_ledger"], rows)
    _write_summary(paths["provider_sync_summary"], rows, warnings, generated_at)
    _write_warnings(paths["manual_nav_warnings"], warnings, validation)
    _write_markdown(paths["markdown_report"], rows, warnings)
    return ManualNavBundleResult(
        input_file=input_file,
        output_dir=out_dir,
        output_paths=paths,
        generated=True,
        account_count=len(rows),
        provider_labels=validation.provider_labels,
        warning_codes=warnings,
    )


def _load_payload(path: Path) -> tuple[dict[str, Any] | None, list[WarningCode]]:
    if not path.exists():
        return None, [WarningCode.MANUAL_NAV_INPUT_MISSING]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, [WarningCode.MANUAL_NAV_SCHEMA_INVALID]
    if not isinstance(payload, dict):
        return None, [WarningCode.MANUAL_NAV_SCHEMA_INVALID]
    return payload, []


def _payload_warnings(payload: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    required_top = ("schema_version", "snapshot_date", "base_currency", "source_type", "review_required")
    if any(not _has_value(payload.get(field)) for field in required_top):
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if _parse_date(payload.get("snapshot_date")) is None:
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    accounts = _accounts(payload)
    if not accounts:
        warnings.append(WarningCode.MANUAL_NAV_SCHEMA_INVALID)
    if _contains_raw_identifier(payload):
        warnings.append(WarningCode.MANUAL_NAV_RAW_IDENTIFIER_DETECTED)
    for account in accounts:
        warnings.extend(_account_warnings(account))
    return _dedupe(warnings)


def _account_warnings(account: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    required = (
        "provider_label",
        "account_label",
        "account_type",
        "base_currency",
        "account_nav",
        "as_of_date",
        "source_type",
        "source_confidence",
        "review_required",
    )
    if any(not _has_value(account.get(field)) for field in required):
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if _clean(account.get("provider_label")) not in ALLOWED_PROVIDER_LABELS:
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if _clean(account.get("account_type")) not in ALLOWED_ACCOUNT_TYPES:
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if _clean(account.get("source_type")) not in ALLOWED_SOURCE_TYPES:
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if _parse_number(account.get("account_nav")) is None:
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if _parse_date(account.get("as_of_date")) is None:
        warnings.append(WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING)
    if not _has_value(account.get("cash_total")) or not _has_value(account.get("securities_market_value")):
        warnings.append(WarningCode.MANUAL_NAV_OPTIONAL_SPLIT_MISSING)
    return warnings


def _accounts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return []
    return [account for account in accounts if isinstance(account, dict)]


def _account_to_ledger_row(
    account: dict[str, Any],
    *,
    hash_salt: str,
    source_bundle_id: str,
    source_snapshot_id: str,
) -> dict[str, str]:
    provider = _clean(account.get("provider_label"))
    base_currency = _clean(account.get("base_currency"))
    account_nav = _number_to_text(_parse_number(account.get("account_nav")))
    cash_total = _number_to_text(_parse_number(account.get("cash_total")))
    securities_market_value = _number_to_text(
        _parse_number(account.get("securities_market_value"))
    )
    margin_or_debt = _number_to_text(_parse_number(account.get("margin_or_debt")))
    row_warnings = [WarningCode.ACCOUNT_ID_HASHED, WarningCode.ACCOUNT_NAV_PROVIDER_REPORTED]
    if not cash_total or not securities_market_value:
        row_warnings.append(WarningCode.MANUAL_NAV_OPTIONAL_SPLIT_MISSING)
    return {
        "provider": provider,
        "account_id_hash": _account_hash(
            provider,
            _clean(account.get("account_label")),
            hash_salt,
        ),
        "source_bundle_id": source_bundle_id,
        "source_snapshot_id": source_snapshot_id,
        "asset_type": "account_nav",
        "symbol": "NAV",
        "name": "Manual account NAV",
        "quantity": "1",
        "currency": base_currency,
        "base_currency": base_currency,
        "market_value": account_nav,
        "cost_basis": "",
        "average_cost": "",
        "unrealized_pnl": "",
        "account_nav": account_nav,
        "total_assets": account_nav,
        "cash_total": cash_total,
        "securities_market_value": securities_market_value,
        "margin_or_debt": margin_or_debt,
        "source_timestamp": _clean(account.get("as_of_date")),
        "as_of_date": _clean(account.get("as_of_date")),
        "source_confidence": _clean(account.get("source_confidence")),
        "warning_codes": ";".join(code.value for code in _dedupe(row_warnings)),
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(
    path: Path,
    rows: list[dict[str, str]],
    warnings: list[WarningCode],
    generated_at: datetime,
) -> None:
    providers = sorted({row["provider"] for row in rows})
    payload = {
        "version": SCHEMA_VERSION,
        "mode": "offline_manual_nav_input",
        "external_connections_used": "no",
        "broker_live_reads_used": "no",
        "account_count": len(rows),
        "provider_labels": providers,
        "normalized_row_count": len(rows),
        "generated_at": generated_at.isoformat(),
        "warning_codes": [code.value for code in warnings],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_warnings(
    path: Path, warnings: list[WarningCode], validation: ManualNavValidationResult
) -> None:
    lines = [
        "# Manual NAV Input Warnings",
        "",
        "This report contains warning codes only. It does not include private values.",
        "",
        f"- Account count: {validation.account_count}",
        f"- Provider labels: {', '.join(validation.provider_labels) or 'None'}",
        "",
        "## Warning Codes",
    ]
    for code in warnings:
        lines.append(f"- {code.value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown(path: Path, rows: list[dict[str, str]], warnings: list[WarningCode]) -> None:
    providers = sorted({row["provider"] for row in rows})
    lines = [
        "# Manual NAV Input v0.5.7",
        "",
        "Offline local-only manual NAV provider bundle.",
        "",
        "- External connections used: no",
        "- Broker live reads used: no",
        "- Account identifiers emitted: hashed only",
        f"- Account rows: {len(rows)}",
        f"- Provider labels: {', '.join(providers) or 'None'}",
        "",
        "## Warning Codes",
    ]
    for code in warnings:
        lines.append(f"- {code.value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _account_hash(provider_label: str, account_label: str, hash_salt: str) -> str:
    digest = hashlib.sha256(
        f"{hash_salt}|manual_nav|{provider_label}|{account_label}".encode("utf-8")
    ).hexdigest()[:16]
    return f"acct_{digest}"


def _contains_raw_identifier(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _RAW_IDENTIFIER_PATTERN.search(str(key)):
                return True
            if _contains_raw_identifier(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_raw_identifier(item) for item in value)
    if isinstance(value, str):
        return bool(_NRIC_PATTERN.search(value))
    return False


def _parse_number(value: object) -> float | None:
    text = str(value).strip().replace(",", "") if value is not None else ""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: object) -> date | None:
    text = str(value).strip() if value is not None else ""
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
