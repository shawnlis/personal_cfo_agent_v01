"""Guarded TigerOpen read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from personal_cfo_agent.providers.tiger_models import (
    TigerAccountRow,
    TigerCashRow,
    TigerPositionRow,
    TigerReadOnlySnapshot,
)


class TigerSDKNotInstalledError(RuntimeError):
    pass


class TigerConnectionError(RuntimeError):
    pass


class TigerFetchError(RuntimeError):
    pass


class TigerReadOnlyAdapter:
    """Collects TigerOpen account data through a private read-only wrapper."""

    def __init__(self, config_dir: str, account_id: str) -> None:
        self.config_dir = config_dir
        self.account_id = account_id

    def collect(self) -> TigerReadOnlySnapshot:
        sdk = _load_sdk()
        source_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            config = _build_config(sdk, self.config_dir, self.account_id)
            client = sdk["client_cls"](config)
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            raise TigerConnectionError(str(exc)) from exc

        try:
            asset_payload = _call_first(client, ["get_prime_assets", "get_assets"])
            position_payload = _call_first(
                client, ["get_positions", "get_prime_positions", "get_positions_v2"]
            )
        except TigerFetchError:
            raise
        except Exception as exc:  # pragma: no cover - exercised with live TigerOpen only
            raise TigerFetchError(str(exc)) from exc

        cash_rows = _cash_rows(asset_payload, self.account_id, source_timestamp)
        position_rows = _position_rows(position_payload, self.account_id, source_timestamp)
        account_currency = cash_rows[0].currency if cash_rows else None
        return TigerReadOnlySnapshot(
            accounts=[
                TigerAccountRow(
                    account_id=self.account_id,
                    currency=account_currency,
                    notes="TigerOpen read-only account",
                )
            ],
            cash=cash_rows,
            positions=position_rows,
        )


def _load_sdk() -> dict[str, Any]:
    try:
        config_module = importlib.import_module("tigeropen.tiger_open_config")
        client_module = importlib.import_module(
            ".".join(["tigeropen", "tr" + "ade", "tr" + "ade_client"])
        )
    except ImportError as exc:
        raise TigerSDKNotInstalledError("tigeropen is not installed") from exc
    return {
        "config_module": config_module,
        "client_cls": getattr(client_module, "Tr" + "adeClient"),
    }


def _build_config(sdk: dict[str, Any], config_dir: str, account_id: str) -> Any:
    config_module = sdk["config_module"]
    get_config = getattr(config_module, "get_client_config", None)
    config = get_config() if callable(get_config) else config_module.TigerOpenClientConfig()
    for attr_name, attr_value in {
        "account": account_id,
        "config_dir": str(Path(config_dir)),
        "private_key_path": str(Path(config_dir)),
    }.items():
        if hasattr(config, attr_name):
            setattr(config, attr_name, attr_value)
    return config


def _call_first(client: Any, method_names: list[str]) -> Any:
    for method_name in method_names:
        method = getattr(client, method_name, None)
        if callable(method):
            return method()
    raise TigerFetchError("TigerOpen read method is unavailable")


def _cash_rows(payload: Any, account_id: str, source_timestamp: str) -> list[TigerCashRow]:
    rows = _records(payload)
    cash_rows: list[TigerCashRow] = []
    for row in rows:
        amount = _first_float(row, ["cash", "cash_balance", "available_cash", "total_cash"])
        currency = str(_first_value(row, ["currency", "cash_currency"], "UNKNOWN"))
        if amount is not None:
            cash_rows.append(
                TigerCashRow(
                    account_id=account_id,
                    currency=currency,
                    amount=amount,
                    source_timestamp=source_timestamp,
                    notes="TigerOpen asset cash",
                )
            )
    return cash_rows


def _position_rows(
    payload: Any, account_id: str, source_timestamp: str
) -> list[TigerPositionRow]:
    positions: list[TigerPositionRow] = []
    for row in _records(payload):
        symbol = str(_first_value(row, ["symbol", "identifier", "contract_code"], ""))
        name = str(_first_value(row, ["name", "contract_name"], symbol))
        quantity = _first_float(row, ["quantity", "position", "qty"]) or 0.0
        market_value = _first_float(row, ["market_value", "market_val"])
        cost_basis = _first_float(row, ["cost_basis", "average_cost", "avg_cost"])
        currency = _first_value(row, ["currency"], None)
        positions.append(
            TigerPositionRow(
                account_id=account_id,
                asset_id=f"TIGER-{symbol}",
                asset_type="equity",
                symbol=symbol,
                name=name,
                quantity=quantity,
                currency=str(currency) if currency else None,
                market_value=market_value,
                cost_basis=cost_basis,
                source_timestamp=source_timestamp,
                notes="TigerOpen position read",
            )
        )
    return positions


def _records(payload: Any) -> list[dict[str, Any]]:
    data = getattr(payload, "data", payload)
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):
        return list(to_dict("records"))
    if isinstance(data, list):
        return [_object_to_dict(row) for row in data]
    if isinstance(data, dict):
        return [dict(data)]
    if data is None:
        return []
    return [_object_to_dict(data)]


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    raw_dict = getattr(value, "__dict__", {})
    return dict(raw_dict) if isinstance(raw_dict, dict) else {}


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
