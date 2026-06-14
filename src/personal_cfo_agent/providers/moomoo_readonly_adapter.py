"""Guarded Moomoo/Futu OpenD read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.providers.moomoo_models import (
    MoomooAccountRow,
    MoomooCashRow,
    MoomooPositionRow,
    MoomooReadDiagnostics,
    MoomooReadOnlySnapshot,
)


class MoomooSDKNotInstalledError(RuntimeError):
    pass


class _MoomooError(RuntimeError):
    def __init__(self, message: str, diagnostics: MoomooReadDiagnostics | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class MoomooConnectionError(_MoomooError):
    pass


class MoomooFetchError(_MoomooError):
    pass


class MoomooReadOnlyAdapter:
    """Collects account data from a manually started OpenD session."""

    def __init__(
        self,
        host: str,
        port: int,
        account_id: str = "moomoo_default",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.account_id = account_id
        self.timeout_seconds = timeout_seconds

    def collect(self) -> MoomooReadOnlySnapshot:
        sdk = _load_sdk()
        context = None
        source_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            context = sdk.OpenSecTradeContext(host=self.host, port=self.port)
        except Exception as exc:  # pragma: no cover - exercised with live OpenD only
            diagnostics = _build_diagnostics(
                connected_to_opend=False,
                connection_established=False,
                account_list_seen=False,
                account_count=0,
                positions_seen=False,
                position_count=0,
                cash_seen=False,
                cash_currency_count=0,
                normalized_row_count=0,
                timeout_seconds=self.timeout_seconds,
                warning_codes=[
                    WarningCode.MOOMOO_OPEND_UNREACHABLE,
                    WarningCode.MOOMOO_CONNECTION_FAILED,
                    WarningCode.PROVIDER_CONNECTION_FAILED,
                ],
            )
            raise MoomooConnectionError("Moomoo OpenD connection failed", diagnostics) from exc

        try:
            account_ids, account_list_seen = self._collect_account_ids(context, sdk)
            cash_rows, cash_seen = self._collect_cash(context, sdk, source_timestamp)
            position_rows, positions_seen = self._collect_positions(
                context, sdk, source_timestamp
            )
        except MoomooFetchError:
            raise
        except Exception as exc:  # pragma: no cover - exercised with live OpenD only
            diagnostics = _build_diagnostics(
                connected_to_opend=True,
                connection_established=True,
                account_list_seen=False,
                account_count=0,
                positions_seen=False,
                position_count=0,
                cash_seen=False,
                cash_currency_count=0,
                normalized_row_count=0,
                timeout_seconds=self.timeout_seconds,
                warning_codes=[
                    WarningCode.MOOMOO_CALLBACK_TIMEOUT,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ],
            )
            raise MoomooFetchError("Moomoo read requests failed", diagnostics) from exc
        finally:
            close = getattr(context, "close", None)
            if callable(close):
                close()

        currencies = [row.currency for row in cash_rows if row.currency]
        account_currency = currencies[0] if currencies else None
        account_count = len(account_ids)
        if not account_ids and (cash_rows or position_rows):
            account_ids = [self.account_id]
        warnings = _data_path_warnings(
            account_list_seen=account_list_seen,
            account_count=account_count,
            cash_seen=cash_seen,
            cash_rows=cash_rows,
            positions_seen=positions_seen,
            position_rows=position_rows,
        )
        diagnostics = _build_diagnostics(
            connected_to_opend=True,
            connection_established=True,
            account_list_seen=account_list_seen,
            account_count=account_count,
            positions_seen=positions_seen,
            position_count=len(position_rows),
            cash_seen=cash_seen,
            cash_currency_count=len({row.currency for row in cash_rows if row.currency}),
            normalized_row_count=len(cash_rows) + len(position_rows),
            timeout_seconds=self.timeout_seconds,
            warning_codes=warnings,
        )
        return MoomooReadOnlySnapshot(
            accounts=[
                MoomooAccountRow(
                    account_id=account_ids[0] if account_ids else self.account_id,
                    currency=account_currency,
                    notes="Moomoo OpenD read-only account",
                )
            ],
            cash=cash_rows,
            positions=position_rows,
            diagnostics=diagnostics,
        )

    def _collect_account_ids(self, context: Any, sdk: Any) -> tuple[list[str], bool]:
        query = _first_callable(context, ["acc_list_query", "get_acc_list"])
        if query is None:
            return [], False
        ret_code, data = query()
        if ret_code != _ret_ok(sdk):
            raise MoomooFetchError(str(data))
        account_ids: list[str] = []
        for row in _rows(data):
            account_id = _first_value(row, ["acc_id", "accID", "account_id", "account"], "")
            if account_id:
                account_ids.append(str(account_id))
        return account_ids, True

    def _collect_cash(
        self, context: Any, sdk: Any, source_timestamp: str
    ) -> tuple[list[MoomooCashRow], bool]:
        query = _first_callable(context, ["accinfo_query"])
        if query is None:
            return [], False
        ret_code, data = query(trd_env=_real_env(sdk))
        if ret_code != _ret_ok(sdk):
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
        return cash_rows, True

    def _collect_positions(
        self, context: Any, sdk: Any, source_timestamp: str
    ) -> tuple[list[MoomooPositionRow], bool]:
        query = _first_callable(context, ["position_list_query"])
        if query is None:
            return [], False
        ret_code, data = query(trd_env=_real_env(sdk))
        if ret_code != _ret_ok(sdk):
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
        return positions, True


def _load_sdk() -> Any:
    try:
        return importlib.import_module("futu")
    except ImportError as exc:
        raise MoomooSDKNotInstalledError("futu is not installed") from exc


def _first_callable(context: Any, names: list[str]) -> Any | None:
    for name in names:
        candidate = getattr(context, name, None)
        if callable(candidate):
            return candidate
    return None


def _ret_ok(sdk: Any) -> Any:
    return getattr(sdk, "RET_OK", 0)


def _real_env(sdk: Any) -> Any:
    trd_env = getattr(sdk, "TrdEnv", None)
    return getattr(trd_env, "REAL", "REAL")


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


def _data_path_warnings(
    *,
    account_list_seen: bool,
    account_count: int,
    cash_seen: bool,
    cash_rows: list[MoomooCashRow],
    positions_seen: bool,
    position_rows: list[MoomooPositionRow],
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if not account_list_seen and not cash_seen and not positions_seen:
        warnings.append(WarningCode.MOOMOO_DATA_PATH_NOT_IMPLEMENTED)
    if account_list_seen and account_count == 0:
        warnings.append(WarningCode.MOOMOO_ACCOUNT_LIST_EMPTY)
    if positions_seen and not position_rows:
        warnings.append(WarningCode.MOOMOO_POSITIONS_EMPTY)
    if cash_seen and not cash_rows:
        warnings.append(WarningCode.MOOMOO_CASH_EMPTY)
    if not cash_seen or not positions_seen:
        warnings.append(WarningCode.MOOMOO_CALLBACK_TIMEOUT)
    if not cash_rows and not position_rows:
        warnings.extend(
            [WarningCode.MOOMOO_NO_DATA_RETURNED, WarningCode.MOOMOO_READ_SUCCEEDED_EMPTY]
        )
    return _dedupe_warning_codes(warnings)


def _build_diagnostics(
    *,
    connected_to_opend: bool,
    connection_established: bool,
    account_list_seen: bool,
    account_count: int,
    positions_seen: bool,
    position_count: int,
    cash_seen: bool,
    cash_currency_count: int,
    normalized_row_count: int,
    timeout_seconds: float,
    warning_codes: list[WarningCode],
) -> MoomooReadDiagnostics:
    return MoomooReadDiagnostics(
        connected_to_opend=connected_to_opend,
        connection_established=connection_established,
        account_list_seen=account_list_seen,
        account_count_redacted=account_count,
        positions_seen=positions_seen,
        position_count=position_count,
        cash_seen=cash_seen,
        cash_currency_count=cash_currency_count,
        normalized_row_count=normalized_row_count,
        timeout_seconds=timeout_seconds,
        warning_codes=_dedupe_warning_codes(warning_codes),
    )


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
