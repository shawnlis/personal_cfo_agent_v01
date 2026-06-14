"""Manual snapshot provider for unsupported or not-yet-verified platforms."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from personal_cfo_agent.config import ProviderConfig
from personal_cfo_agent.manual_snapshot import (
    ManualSnapshotReadError,
    ManualSnapshotValidationError,
    is_structured_manual_snapshot,
    load_manual_snapshot_document,
    manual_snapshot_to_provider_payload,
)
from personal_cfo_agent.models import (
    ConnectionMode,
    ProviderLevel,
    RawAccount,
    RawBalance,
    RawCash,
    RawPosition,
    WarningCode,
)
from personal_cfo_agent.provider_base import ProviderBase


class ManualSnapshotProvider(ProviderBase):
    provider_name = "manual_snapshot"
    provider_level = ProviderLevel.LEVEL_0
    connection_mode = ConnectionMode.FIXTURE

    def __init__(self, config: ProviderConfig, allow_live_read: bool = False) -> None:
        super().__init__(config=config, allow_live_read=allow_live_read)
        self.credentials_source = config.credentials_source
        self._data: dict[str, Any] | None = None

    def validate_config(self) -> list[WarningCode]:
        if not self.config.enabled:
            return [WarningCode.PROVIDER_DISABLED]
        path = self._snapshot_path()
        if path is None or not path.exists():
            return [WarningCode.PROVIDER_CONFIG_MISSING]
        self.raw_snapshot_path = str(path)
        return []

    def connect_read_only(self) -> bool:
        if WarningCode.PROVIDER_DISABLED in self.warning_codes:
            return False
        if WarningCode.PROVIDER_CONFIG_MISSING in self.warning_codes:
            return False
        try:
            path = self._snapshot_path()
            loaded_data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded_data, dict) and is_structured_manual_snapshot(loaded_data):
                document = load_manual_snapshot_document(path)
                self.warning_codes = _dedupe(
                    [
                        *self.warning_codes,
                        *(issue.code for issue in document.validation_result.warnings),
                    ]
                )
                self._data = manual_snapshot_to_provider_payload(document)
            else:
                self._data = loaded_data
        except (OSError, json.JSONDecodeError):
            self.warning_codes = _dedupe(
                [*self.warning_codes, WarningCode.PROVIDER_FETCH_FAILED]
            )
            return False
        except ManualSnapshotReadError:
            self.warning_codes = _dedupe(
                [*self.warning_codes, WarningCode.PROVIDER_FETCH_FAILED]
            )
            return False
        except ManualSnapshotValidationError as exc:
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    WarningCode.PROVIDER_FETCH_FAILED,
                    *(issue.code for issue in exc.result.issues),
                ]
            )
            return False
        return True

    def fetch_accounts(self) -> list[RawAccount]:
        data = self._require_data()
        accounts: list[RawAccount] = []
        for row in data.get("accounts", []):
            accounts.append(
                RawAccount(
                    account_id=str(row["account_id"]),
                    account_type=str(row.get("account_type", "unknown")),
                    currency=row.get("currency"),
                    notes=str(row.get("notes", "")),
                )
            )
        return accounts

    def fetch_cash(self) -> list[RawCash]:
        data = self._require_data()
        default_timestamp = str(data.get("source_timestamp", ""))
        cash_rows: list[RawCash] = []
        for row in data.get("cash", []):
            cash_rows.append(
                RawCash(
                    account_id=str(row["account_id"]),
                    currency=str(row["currency"]),
                    amount=float(row["amount"]),
                    source_timestamp=str(row.get("source_timestamp", default_timestamp)),
                    notes=str(row.get("notes", "")),
                )
            )
        return cash_rows

    def fetch_positions(self) -> list[RawPosition]:
        data = self._require_data()
        default_timestamp = str(data.get("source_timestamp", ""))
        positions: list[RawPosition] = []
        for row in data.get("positions", []):
            positions.append(
                RawPosition(
                    account_id=str(row["account_id"]),
                    asset_id=str(row["asset_id"]),
                    asset_type=str(row["asset_type"]),
                    symbol=str(row.get("symbol", "")),
                    name=str(row.get("name", "")),
                    quantity=float(row.get("quantity", 0.0)),
                    currency=row.get("currency"),
                    market_value=_optional_float(row.get("market_value")),
                    cost_basis=_optional_float(row.get("cost_basis")),
                    unrealized_pnl=_optional_float(row.get("unrealized_pnl")),
                    liquidity_bucket=str(row.get("liquidity_bucket", "unknown")),
                    risk_bucket=str(row.get("risk_bucket", "unknown")),
                    source_timestamp=str(row.get("source_timestamp", default_timestamp)),
                    source_confidence=str(row.get("source_confidence", "manual")),
                    needs_review=bool(row.get("needs_review", False)),
                    warning_codes=_parse_warning_codes(row.get("warning_codes", [])),
                    notes=str(row.get("notes", "")),
                )
            )
        return positions

    def fetch_balances(self) -> list[RawBalance]:
        data = self._require_data()
        default_timestamp = str(data.get("source_timestamp", ""))
        balances: list[RawBalance] = []
        for row in data.get("balances", []):
            balances.append(
                RawBalance(
                    account_id=str(row["account_id"]),
                    asset_id=str(row["asset_id"]),
                    asset_type=str(row.get("asset_type", "liability")),
                    name=str(row.get("name", "")),
                    currency=row.get("currency"),
                    amount=_optional_float(row.get("amount")),
                    source_timestamp=str(row.get("source_timestamp", default_timestamp)),
                    liquidity_bucket=str(row.get("liquidity_bucket", "liability")),
                    risk_bucket=str(row.get("risk_bucket", "liability")),
                    source_confidence=str(row.get("source_confidence", "manual")),
                    needs_review=bool(row.get("needs_review", False)),
                    warning_codes=_parse_warning_codes(row.get("warning_codes", [])),
                    notes=str(row.get("notes", "")),
                )
            )
        return balances

    def disconnect(self) -> None:
        return None

    def _snapshot_path(self) -> Path | None:
        raw_path = self.config.settings.get("CFO_MANUAL_SNAPSHOT_PATH", "")
        if not raw_path:
            return None
        return Path(raw_path)

    def _require_data(self) -> dict[str, Any]:
        if self._data is None:
            raise RuntimeError("manual snapshot was not loaded")
        return self._data


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_warning_codes(values: object) -> list[WarningCode]:
    if not isinstance(values, list):
        return [WarningCode.NEEDS_REVIEW]
    parsed: list[WarningCode] = []
    for value in values:
        try:
            parsed.append(WarningCode(str(value)))
        except ValueError:
            parsed.append(WarningCode.NEEDS_REVIEW)
    return parsed


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
