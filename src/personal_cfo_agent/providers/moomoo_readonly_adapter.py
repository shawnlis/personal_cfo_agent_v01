"""Guarded Moomoo/Futu OpenD read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any

from personal_cfo_agent.providers.moomoo_models import (
    MoomooAccountRow,
    MoomooCashRow,
    MoomooPositionRow,
    MoomooReadOnlySnapshot,
)


class MoomooSDKNotInstalledError(RuntimeError):
    pass


class MoomooConnectionError(RuntimeError):
    pass


class MoomooFetchError(RuntimeError):
    pass


class MoomooReadOnlyAdapter:
    """Collects account data from a manually started OpenD session."""

    def __init__(self, host: str, port: int, account_id: str = "moomoo_default") -> None:
        self.host = host
        self.port = port
        self.account_id = account_id

    def collect(self) -> MoomooReadOnlySnapshot:
        sdk = _load_sdk()
        context = None
        source_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            context = sdk.OpenSecTradeContext(host=self.host, port=self.port)
        except Exception as exc:  # pragma: no cover - exercised with live OpenD only
            raise MoomooConnectionError(str(exc)) from exc

        try:
            cash_rows = self._collect_cash(context, sdk, source_timestamp)
            position_rows = self._collect_positions(context, sdk, source_timestamp)
        except MoomooFetchError:
            raise
        except Exception as exc:  # pragma: no cover - exercised with live OpenD only
            raise MoomooFetchError(str(exc)) from exc
        finally:
            close = getattr(context, "close", None)
            if callable(close):
                close()

        currencies = [row.currency for row in cash_rows if row.currency]
        account_currency = currencies[0] if currencies else None
        return MoomooReadOnlySnapshot(
            accounts=[
                MoomooAccountRow(
                    account_id=self.account_id,
                    currency=account_currency,
                    notes="Moomoo OpenD read-only account",
                )
            ],
            cash=cash_rows,
            positions=position_rows,
        )

    def _collect_cash(
        self, context: Any, sdk: Any, source_timestamp: str
    ) -> list[MoomooCashRow]:
        ret_code, data = context.accinfo_query(trd_env=sdk.TrdEnv.REAL)
        if ret_code != sdk.RET_OK:
            raise MoomooFetchError(str(data))
        rows = _rows(data)
        cash_rows: list[MoomooCashRow] = []
        for row in rows:
            cash_amount = _first_float(row, ["cash", "cash_balance", "total_cash"])
            currency = str(_first_value(row, ["currency", "cash_currency"], "UNKNOWN"))
            if cash_amount is not None:
                cash_rows.append(
                    MoomooCashRow(
                        account_id=self.account_id,
                        currency=currency,
                        amount=cash_amount,
                        source_timestamp=source_timestamp,
                        notes="Moomoo OpenD account info cash",
                    )
                )
        return cash_rows

    def _collect_positions(
        self, context: Any, sdk: Any, source_timestamp: str
    ) -> list[MoomooPositionRow]:
        ret_code, data = context.position_list_query(trd_env=sdk.TrdEnv.REAL)
        if ret_code != sdk.RET_OK:
            raise MoomooFetchError(str(data))
        positions: list[MoomooPositionRow] = []
        for row in _rows(data):
            code = str(_first_value(row, ["code", "stock_code", "symbol"], ""))
            name = str(_first_value(row, ["stock_name", "name"], code))
            quantity = _first_float(row, ["qty", "quantity", "can_sell_qty"]) or 0.0
            market_value = _first_float(row, ["market_val", "market_value"])
            cost_basis = _first_float(row, ["cost_price", "average_cost"])
            currency = _first_value(row, ["currency"], None)
            positions.append(
                MoomooPositionRow(
                    account_id=self.account_id,
                    asset_id=f"MOOMOO-{code}",
                    asset_type="equity",
                    symbol=code,
                    name=name,
                    quantity=quantity,
                    currency=str(currency) if currency else None,
                    market_value=market_value,
                    cost_basis=cost_basis,
                    source_timestamp=source_timestamp,
                    notes="Moomoo OpenD position list",
                )
            )
        return positions


def _load_sdk() -> Any:
    try:
        return importlib.import_module("futu")
    except ImportError as exc:
        raise MoomooSDKNotInstalledError("futu is not installed") from exc


def _rows(data: Any) -> list[dict[str, Any]]:
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        return list(to_dict("records"))
    if isinstance(data, list):
        return [dict(row) for row in data]
    if isinstance(data, dict):
        return [dict(data)]
    return []


def _first_value(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return default


def _first_float(row: dict[str, Any], keys: list[str]) -> float | None:
    value = _first_value(row, keys)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
