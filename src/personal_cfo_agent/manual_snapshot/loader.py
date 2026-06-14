"""Loader and adapter for v0.1.4 structured manual snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personal_cfo_agent.manual_snapshot.schema import ManualAsset, ManualLiability, ManualSnapshot
from personal_cfo_agent.manual_snapshot.validator import (
    ManualSnapshotIssue,
    ManualSnapshotValidationResult,
    validate_manual_snapshot_payload,
)
from personal_cfo_agent.models import WarningCode


class ManualSnapshotReadError(RuntimeError):
    pass


class ManualSnapshotValidationError(ValueError):
    def __init__(self, result: ManualSnapshotValidationResult) -> None:
        super().__init__("manual snapshot validation failed")
        self.result = result


@dataclass(frozen=True)
class ManualSnapshotDocument:
    snapshot: ManualSnapshot
    validation_result: ManualSnapshotValidationResult


def is_structured_manual_snapshot(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("snapshot_date", "assets", "liabilities"))


def load_manual_snapshot_document(path: Path) -> ManualSnapshotDocument:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualSnapshotReadError(str(exc)) from exc

    result = validate_manual_snapshot_payload(payload)
    if not result.is_valid:
        raise ManualSnapshotValidationError(result)
    return ManualSnapshotDocument(
        snapshot=_parse_snapshot(payload, result),
        validation_result=result,
    )


def manual_snapshot_to_provider_payload(document: ManualSnapshotDocument) -> dict[str, Any]:
    snapshot = document.snapshot
    data: dict[str, Any] = {
        "source_timestamp": snapshot.snapshot_date,
        "accounts": [],
        "cash": [],
        "positions": [],
        "balances": [],
    }
    for index, asset in enumerate(snapshot.assets):
        account_id = _synthetic_account_id("asset", asset.provider, asset.asset_id)
        data["accounts"].append(
            {
                "account_id": account_id,
                "account_type": asset.asset_type,
                "currency": asset.currency,
                "notes": "Structured manual snapshot asset",
            }
        )
        data["positions"].append(
            {
                "account_id": account_id,
                "asset_id": asset.asset_id,
                "asset_type": asset.asset_type,
                "symbol": "",
                "name": asset.name,
                "quantity": 1.0,
                "currency": asset.currency,
                "market_value": asset.estimated_value,
                "cost_basis": None,
                "unrealized_pnl": None,
                "liquidity_bucket": asset.liquidity_bucket,
                "risk_bucket": asset.risk_bucket,
                "source_timestamp": asset.valuation_date or snapshot.snapshot_date,
                "source_confidence": _source_confidence(asset.provider, asset.valuation_source),
                "needs_review": asset.needs_review,
                "warning_codes": [code.value for code in asset.warning_codes],
                "notes": asset.notes,
            }
        )
        _extend_row_warnings(
            data["positions"][-1],
            document.validation_result.warnings,
            f"assets[{index}]",
        )

    for index, liability in enumerate(snapshot.liabilities):
        account_id = _synthetic_account_id("liability", liability.provider, liability.liability_id)
        data["accounts"].append(
            {
                "account_id": account_id,
                "account_type": liability.liability_type,
                "currency": liability.currency,
                "notes": "Structured manual snapshot liability",
            }
        )
        data["balances"].append(
            {
                "account_id": account_id,
                "asset_id": liability.liability_id,
                "asset_type": liability.liability_type,
                "name": liability.name,
                "currency": liability.currency,
                "amount": -abs(liability.outstanding_balance),
                "source_timestamp": snapshot.snapshot_date,
                "liquidity_bucket": "liability",
                "risk_bucket": liability.liability_type,
                "source_confidence": "manual_snapshot",
                "needs_review": liability.needs_review,
                "warning_codes": [code.value for code in liability.warning_codes],
                "notes": _liability_notes(liability),
            }
        )
        _extend_row_warnings(
            data["balances"][-1],
            document.validation_result.warnings,
            f"liabilities[{index}]",
        )
    return data


def _parse_snapshot(
    payload: dict[str, Any], result: ManualSnapshotValidationResult
) -> ManualSnapshot:
    return ManualSnapshot(
        snapshot_date=str(payload.get("snapshot_date", "")),
        base_currency=str(payload.get("base_currency", "")),
        source_note=str(payload.get("source_note", "")),
        assets=[
            _parse_asset(row, _warnings_for_path(result.warnings, f"assets[{index}]"))
            for index, row in enumerate(payload.get("assets", []))
            if isinstance(row, dict)
        ],
        liabilities=[
            _parse_liability(row, _warnings_for_path(result.warnings, f"liabilities[{index}]"))
            for index, row in enumerate(payload.get("liabilities", []))
            if isinstance(row, dict)
        ],
        warnings_acknowledged=bool(payload.get("warnings_acknowledged", False)),
    )


def _parse_asset(row: dict[str, Any], warning_codes: list[WarningCode]) -> ManualAsset:
    return ManualAsset(
        asset_id=str(row.get("asset_id", "")),
        asset_type=str(row.get("asset_type", "")),
        provider=str(row.get("provider", "")),
        name=str(row.get("name", "")),
        currency=str(row.get("currency", "")),
        estimated_value=float(row.get("estimated_value", 0.0)),
        valuation_date=str(row.get("valuation_date", "")),
        valuation_source=str(row.get("valuation_source", "")),
        liquidity_bucket=str(row.get("liquidity_bucket", "unknown")),
        risk_bucket=str(row.get("risk_bucket", "unknown")),
        notes=str(row.get("notes", "")),
        warning_codes=_base_warning_codes(warning_codes),
        needs_review=True,
    )


def _parse_liability(row: dict[str, Any], warning_codes: list[WarningCode]) -> ManualLiability:
    return ManualLiability(
        liability_id=str(row.get("liability_id", "")),
        liability_type=str(row.get("liability_type", "")),
        provider=str(row.get("provider", "")),
        name=str(row.get("name", "")),
        currency=str(row.get("currency", "")),
        outstanding_balance=float(row.get("outstanding_balance", 0.0)),
        interest_rate=_optional_float(row.get("interest_rate")),
        monthly_payment=_optional_float(row.get("monthly_payment")),
        repricing_date=str(row.get("repricing_date", "")),
        maturity_date=str(row.get("maturity_date", "")),
        collateral=str(row.get("collateral", "")),
        notes=str(row.get("notes", "")),
        warning_codes=_base_warning_codes(warning_codes),
        needs_review=True,
    )


def _warnings_for_path(issues: list[ManualSnapshotIssue], prefix: str) -> list[WarningCode]:
    return [issue.code for issue in issues if issue.path.startswith(prefix)]


def _base_warning_codes(extra_codes: list[WarningCode]) -> list[WarningCode]:
    return _dedupe(
        [
            WarningCode.MANUAL_SNAPSHOT_REQUIRED,
            WarningCode.MANUAL_VALUE_NEEDS_REVIEW,
            WarningCode.NEEDS_REVIEW,
            *extra_codes,
        ]
    )


def _extend_row_warnings(
    row: dict[str, Any], warnings: list[ManualSnapshotIssue], prefix: str
) -> None:
    current = [WarningCode(str(code)) for code in row.get("warning_codes", [])]
    current.extend(_warnings_for_path(warnings, prefix))
    row["warning_codes"] = [code.value for code in _dedupe(current)]


def _synthetic_account_id(kind: str, provider: str, row_id: str) -> str:
    return f"manual_snapshot:{kind}:{provider}:{row_id}"


def _source_confidence(provider: str, source: str) -> str:
    source_value = source.strip().lower()
    if "sgfindex" in source_value:
        return "manual_sgfindex_derived"
    provider_value = provider.strip().lower()
    if not provider_value or provider_value == "manual":
        return "manual_snapshot"
    return f"manual_{provider_value}"


def _liability_notes(liability: ManualLiability) -> str:
    parts = [liability.notes]
    if liability.interest_rate is not None:
        parts.append(f"interest_rate={liability.interest_rate}")
    if liability.monthly_payment is not None:
        parts.append(f"monthly_payment={liability.monthly_payment}")
    if liability.repricing_date:
        parts.append(f"repricing_date={liability.repricing_date}")
    if liability.maturity_date:
        parts.append(f"maturity_date={liability.maturity_date}")
    if liability.collateral:
        parts.append(f"collateral={liability.collateral}")
    return "; ".join(part for part in parts if part)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
