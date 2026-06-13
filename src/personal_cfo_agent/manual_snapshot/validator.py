"""Validation for v0.1.4 structured manual snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

from personal_cfo_agent.manual_snapshot.schema import (
    ASSET_TYPES,
    GOVERNMENT_PROVIDERS,
    LIABILITY_TYPES,
    MANUAL_ONLY_PROVIDERS,
)
from personal_cfo_agent.models import WarningCode


STALE_MANUAL_VALUATION_DAYS = 90
BLOCKED_SOURCE_MARKERS = (
    "scrap",
    "automation",
    "unofficial api",
    "unofficial_api",
    "screen capture",
    "screen_capture",
    "singpass",
)


@dataclass(frozen=True)
class ManualSnapshotIssue:
    path: str
    code: WarningCode
    severity: Literal["error", "warning"]
    message: str


@dataclass(frozen=True)
class ManualSnapshotValidationResult:
    errors: list[ManualSnapshotIssue]
    warnings: list[ManualSnapshotIssue]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def issues(self) -> list[ManualSnapshotIssue]:
        return [*self.errors, *self.warnings]


def validate_manual_snapshot_payload(
    payload: dict[str, Any], as_of_date: date | None = None
) -> ManualSnapshotValidationResult:
    errors: list[ManualSnapshotIssue] = []
    warnings: list[ManualSnapshotIssue] = []
    review_date = as_of_date or datetime.now(timezone.utc).date()

    if not isinstance(payload, dict):
        return ManualSnapshotValidationResult(
            errors=[
                _issue("$", WarningCode.NEEDS_REVIEW, "error", "Snapshot must be a JSON object.")
            ],
            warnings=[],
        )

    _require_text(payload, "snapshot_date", "$", errors)
    _require_text(payload, "base_currency", "$", errors, WarningCode.MISSING_CURRENCY)
    _require_text(payload, "source_note", "$", warnings, severity="warning")
    _require_key(payload, "warnings_acknowledged", "$", warnings)

    source_note = str(payload.get("source_note", ""))
    if _has_blocked_source_marker(source_note):
        errors.append(
            _issue(
                "$.source_note",
                WarningCode.SINGPASS_AUTOMATION_BLOCKED,
                "error",
                "Snapshot source must be manual or official-app summarized, not automated.",
            )
        )

    assets = payload.get("assets", [])
    liabilities = payload.get("liabilities", [])
    if not isinstance(assets, list):
        errors.append(_issue("$.assets", WarningCode.NEEDS_REVIEW, "error", "Assets must be a list."))
        assets = []
    if not isinstance(liabilities, list):
        errors.append(
            _issue("$.liabilities", WarningCode.NEEDS_REVIEW, "error", "Liabilities must be a list.")
        )
        liabilities = []

    for index, row in enumerate(assets):
        if not isinstance(row, dict):
            errors.append(
                _issue(f"assets[{index}]", WarningCode.NEEDS_REVIEW, "error", "Asset must be an object.")
            )
            continue
        _validate_asset(row, index, review_date, errors, warnings)

    for index, row in enumerate(liabilities):
        if not isinstance(row, dict):
            errors.append(
                _issue(
                    f"liabilities[{index}]",
                    WarningCode.NEEDS_REVIEW,
                    "error",
                    "Liability must be an object.",
                )
            )
            continue
        _validate_liability(row, index, errors)

    return ManualSnapshotValidationResult(errors=errors, warnings=warnings)


def _validate_asset(
    row: dict[str, Any],
    index: int,
    review_date: date,
    errors: list[ManualSnapshotIssue],
    warnings: list[ManualSnapshotIssue],
) -> None:
    path = f"assets[{index}]"
    asset_type = _text(row.get("asset_type")).lower()
    provider = _text(row.get("provider")).lower()
    source = _text(row.get("valuation_source")).lower()

    for field_name in ("asset_id", "asset_type", "provider", "name"):
        _require_text(row, field_name, path, errors)
    _require_text(row, "currency", path, errors, WarningCode.MISSING_CURRENCY)

    if asset_type and asset_type not in ASSET_TYPES:
        errors.append(
            _issue(
                f"{path}.asset_type",
                WarningCode.NEEDS_REVIEW,
                "error",
                f"Unsupported manual asset type: {asset_type}",
            )
        )

    amount = _float_value(row.get("estimated_value"))
    if amount is None or amount < 0:
        errors.append(
            _issue(
                f"{path}.estimated_value",
                WarningCode.INVALID_AMOUNT,
                "error",
                "Asset estimated_value must be present and non-negative.",
            )
        )

    valuation_date = _text(row.get("valuation_date"))
    if not valuation_date:
        warnings.extend(
            [
                _issue(
                    f"{path}.valuation_date",
                    WarningCode.MISSING_VALUATION_DATE,
                    "warning",
                    "Manual asset is missing a valuation date.",
                ),
                _issue(
                    f"{path}.valuation_date",
                    WarningCode.NEEDS_REVIEW,
                    "warning",
                    "Manual asset needs review before use.",
                ),
            ]
        )
    else:
        parsed_valuation_date = _parse_date(valuation_date)
        if parsed_valuation_date is None:
            warnings.append(
                _issue(
                    f"{path}.valuation_date",
                    WarningCode.MANUAL_VALUE_NEEDS_REVIEW,
                    "warning",
                    "Manual asset valuation date could not be parsed.",
                )
            )
        elif (review_date - parsed_valuation_date).days > STALE_MANUAL_VALUATION_DAYS:
            warnings.append(
                _issue(
                    f"{path}.valuation_date",
                    WarningCode.STALE_MANUAL_VALUATION,
                    "warning",
                    "Manual asset valuation is older than 90 days.",
                )
            )

    if _has_blocked_source_marker(source):
        errors.append(
            _issue(
                f"{path}.valuation_source",
                WarningCode.SINGPASS_AUTOMATION_BLOCKED,
                "error",
                "Manual snapshot source must not be automated.",
            )
        )

    if _is_government_row(provider, asset_type) and not _source_is_manual_or_sgfindex(source):
        errors.append(
            _issue(
                f"{path}.valuation_source",
                WarningCode.UNSUPPORTED_PROVIDER_MANUAL_ONLY,
                "error",
                "CPF, IRAS, and HDB values must be manual or SGFinDex-derived.",
            )
        )

    if _is_manual_only_row(provider, asset_type) and not _source_is_manual(source):
        errors.append(
            _issue(
                f"{path}.valuation_source",
                WarningCode.UNSUPPORTED_PROVIDER_MANUAL_ONLY,
                "error",
                "Unsupported broker values must be marked manual.",
            )
        )


def _validate_liability(
    row: dict[str, Any],
    index: int,
    errors: list[ManualSnapshotIssue],
) -> None:
    path = f"liabilities[{index}]"
    liability_type = _text(row.get("liability_type")).lower()
    for field_name in ("liability_id", "liability_type", "provider", "name"):
        _require_text(row, field_name, path, errors)
    _require_text(row, "currency", path, errors, WarningCode.MISSING_CURRENCY)
    if liability_type and liability_type not in LIABILITY_TYPES:
        errors.append(
            _issue(
                f"{path}.liability_type",
                WarningCode.NEEDS_REVIEW,
                "error",
                f"Unsupported manual liability type: {liability_type}",
            )
        )
    amount = _float_value(row.get("outstanding_balance"))
    if amount is None or amount < 0:
        errors.append(
            _issue(
                f"{path}.outstanding_balance",
                WarningCode.INVALID_AMOUNT,
                "error",
                "Liability outstanding_balance must be present and non-negative.",
            )
        )


def _is_government_row(provider: str, asset_type: str) -> bool:
    return provider in GOVERNMENT_PROVIDERS or asset_type.startswith("cpf_")


def _is_manual_only_row(provider: str, asset_type: str) -> bool:
    if asset_type == "unsupported_broker":
        return True
    return provider in MANUAL_ONLY_PROVIDERS


def _source_is_manual(source: str) -> bool:
    return "manual" in source or "user" in source or "statement" in source


def _source_is_manual_or_sgfindex(source: str) -> bool:
    return _source_is_manual(source) or "sgfindex" in source


def _has_blocked_source_marker(source: str) -> bool:
    normalized = source.lower()
    return any(marker in normalized for marker in BLOCKED_SOURCE_MARKERS)


def _require_key(
    row: dict[str, Any],
    field_name: str,
    path: str,
    issues: list[ManualSnapshotIssue],
    severity: Literal["error", "warning"] = "warning",
) -> None:
    if field_name not in row:
        issues.append(
            _issue(
                f"{path}.{field_name}",
                WarningCode.NEEDS_REVIEW,
                severity,
                f"Missing field: {field_name}",
            )
        )


def _require_text(
    row: dict[str, Any],
    field_name: str,
    path: str,
    issues: list[ManualSnapshotIssue],
    code: WarningCode = WarningCode.NEEDS_REVIEW,
    severity: Literal["error", "warning"] = "error",
) -> None:
    if not _text(row.get(field_name)):
        issues.append(
            _issue(
                f"{path}.{field_name}",
                code,
                severity,
                f"Missing field: {field_name}",
            )
        )


def _issue(
    path: str, code: WarningCode, severity: Literal["error", "warning"], message: str
) -> ManualSnapshotIssue:
    return ManualSnapshotIssue(path=path, code=code, severity=severity, message=message)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
