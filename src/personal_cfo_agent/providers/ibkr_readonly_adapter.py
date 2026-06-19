"""Guarded IBKR read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.normalizer import hash_account_id
from personal_cfo_agent.providers.ibkr_models import (
    IBKRAccountRow,
    IBKRCashRow,
    IBKRPositionRow,
    IBKRReadDiagnostics,
    IBKRReadOnlySnapshot,
)


class IBKRSDKNotInstalledError(RuntimeError):
    pass


class _IBKRError(RuntimeError):
    def __init__(self, message: str, diagnostics: IBKRReadDiagnostics | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class IBKRConnectionError(_IBKRError):
    pass


class IBKRFetchError(_IBKRError):
    pass


class IBKRReadOnlyAdapter:
    """Collects IBKR account data through allowlisted read requests only."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        account_filter: str | None = None,
        account_hash_salt: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_filter = account_filter
        self.account_hash_salt = account_hash_salt
        self.timeout_seconds = timeout_seconds

    def collect(self) -> IBKRReadOnlySnapshot:
        client_module, wrapper_module = _load_ibapi_modules()
        source_timestamp = datetime.now(timezone.utc).isoformat()
        requested_account_hash = (
            hash_account_id(self.account_filter, self.account_hash_salt)
            if self.account_filter
            else None
        )

        class _ReadOnlyApp(wrapper_module.EWrapper, client_module.EClient):  # type: ignore[name-defined]
            def __init__(self, account_filter: str | None) -> None:
                wrapper_module.EWrapper.__init__(self)
                client_module.EClient.__init__(self, self)
                self.account_filter = account_filter
                self.connected_to_socket = False
                self.api_handshake_seen = False
                self.ready_event = threading.Event()
                self.managed_accounts_event = threading.Event()
                self.account_summary_event = threading.Event()
                self.positions_event = threading.Event()
                self.errors: list[str] = []
                self.managed_accounts_seen = False
                self.managed_accounts: list[str] = []
                self.positions_callback_seen = False
                self.account_summary_callback_seen = False
                self.accounts: dict[str, IBKRAccountRow] = {}
                self.cash: list[IBKRCashRow] = []
                self.positions: list[IBKRPositionRow] = []

            def _upsert_account(
                self,
                account: str,
                *,
                currency: str | None = None,
                account_nav: float | None = None,
                notes: str = "IBKR account summary",
            ) -> None:
                existing = self.accounts.get(account)
                if existing is None:
                    self.accounts[account] = IBKRAccountRow(
                        account_id=account,
                        currency=currency or None,
                        account_nav=account_nav,
                        source_timestamp=source_timestamp,
                        notes=notes,
                    )
                    return
                self.accounts[account] = replace(
                    existing,
                    currency=currency or existing.currency,
                    account_nav=(
                        account_nav
                        if account_nav is not None
                        else existing.account_nav
                    ),
                    source_timestamp=existing.source_timestamp or source_timestamp,
                    notes=existing.notes or notes,
                )

            def nextValidId(self, orderId: int) -> None:  # noqa: N802
                self.api_handshake_seen = True
                self.ready_event.set()

            def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
                self.managed_accounts_seen = True
                self.managed_accounts = [
                    account.strip()
                    for account in str(accountsList or "").split(",")
                    if account.strip()
                ]
                self.managed_accounts_event.set()

            def error(  # noqa: N802
                self,
                reqId: int,
                errorCode: int,
                errorString: str,
                advancedOrderRejectJson: str = "",
            ) -> None:
                if errorCode not in {2104, 2106, 2158}:
                    self.errors.append(f"{errorCode}: {errorString}")

            def accountSummary(  # noqa: N802
                self,
                reqId: int,
                account: str,
                tag: str,
                value: str,
                currency: str,
            ) -> None:
                self.account_summary_callback_seen = True
                if self.account_filter and account != self.account_filter:
                    return
                self._upsert_account(
                    account,
                    currency=currency or None,
                    notes="IBKR account summary",
                )
                if tag == "NetLiquidation":
                    account_nav = _safe_float(value)
                    if account_nav is not None:
                        self._upsert_account(
                            account,
                            currency=currency or None,
                            account_nav=account_nav,
                            notes="IBKR account summary NetLiquidation",
                        )
                if tag in {"TotalCashValue", "CashBalance", "SettledCash"}:
                    amount = _safe_float(value)
                    if amount is not None and currency:
                        self.cash.append(
                            IBKRCashRow(
                                account_id=account,
                                currency=currency,
                                amount=amount,
                                source_timestamp=source_timestamp,
                                notes=f"IBKR account summary tag {tag}",
                            )
                    )

            def accountSummaryEnd(self, reqId: int) -> None:  # noqa: N802
                self.account_summary_event.set()

            def position(self, account: str, contract: Any, position: float, avgCost: float) -> None:  # noqa: N802
                self.positions_callback_seen = True
                if self.account_filter and account != self.account_filter:
                    return
                symbol = str(getattr(contract, "symbol", "") or "")
                asset_type = str(getattr(contract, "secType", "") or "unknown").lower()
                currency = getattr(contract, "currency", None)
                self._upsert_account(
                    account,
                    currency=currency,
                    notes="IBKR positions",
                )
                self.positions.append(
                    IBKRPositionRow(
                        account_id=account,
                        asset_id=f"IBKR-{asset_type.upper()}-{symbol}",
                        asset_type=asset_type,
                        symbol=symbol,
                        name=str(getattr(contract, "localSymbol", "") or symbol),
                        quantity=float(position),
                        currency=currency,
                        market_value=None,
                        cost_basis=_cost_basis(position, avgCost),
                        source_timestamp=source_timestamp,
                        notes="IBKR reqPositions read",
                    )
                )

            def positionEnd(self) -> None:  # noqa: N802
                self.positions_event.set()

        app = _ReadOnlyApp(self.account_filter)
        try:
            app.connect(self.host, self.port, self.client_id)
            app.connected_to_socket = True
        except Exception as exc:  # pragma: no cover - exercised with live gateway only
            diagnostics = _build_diagnostics(
                app,
                requested_account_hash,
                self.timeout_seconds,
                [WarningCode.PROVIDER_CONNECTION_FAILED],
            )
            raise IBKRConnectionError("IBKR socket connection failed", diagnostics) from exc

        worker = threading.Thread(target=app.run, daemon=True)
        worker.start()
        if not app.ready_event.wait(self.timeout_seconds):
            diagnostics = _build_diagnostics(
                app,
                requested_account_hash,
                self.timeout_seconds,
                [WarningCode.IBKR_HANDSHAKE_TIMEOUT, WarningCode.IBKR_CALLBACK_TIMEOUT],
            )
            app.disconnect()
            raise IBKRConnectionError("IBKR client did not become ready", diagnostics)

        app.reqManagedAccts()
        managed_done = app.managed_accounts_event.wait(self.timeout_seconds)
        warnings = _managed_account_warnings(app, managed_done)
        if self.account_filter and managed_done and self.account_filter not in app.managed_accounts:
            warnings.extend(
                [
                    WarningCode.IBKR_ACCOUNT_FILTER_MISMATCH,
                    WarningCode.IBKR_NO_DATA_RETURNED,
                ]
            )
            diagnostics = _build_diagnostics(
                app,
                requested_account_hash,
                self.timeout_seconds,
                warnings,
            )
            app.disconnect()
            return IBKRReadOnlySnapshot(diagnostics=diagnostics)

        if not callable(getattr(app, "reqAccountSummary", None)) or not callable(
            getattr(app, "reqPositions", None)
        ):
            warnings.extend(
                [
                    WarningCode.IBKR_DATA_PATH_NOT_IMPLEMENTED,
                    WarningCode.IBKR_NO_DATA_RETURNED,
                ]
            )
            diagnostics = _build_diagnostics(
                app,
                requested_account_hash,
                self.timeout_seconds,
                warnings,
            )
            app.disconnect()
            return IBKRReadOnlySnapshot(diagnostics=diagnostics)

        try:
            app.reqAccountSummary(
                9101,
                "All",
                "TotalCashValue,CashBalance,SettledCash,NetLiquidation,AvailableFunds",
            )
            app.reqPositions()
        except Exception as exc:  # pragma: no cover - exercised with live gateway only
            warnings.extend([WarningCode.IBKR_CALLBACK_TIMEOUT, WarningCode.IBKR_NO_DATA_RETURNED])
            diagnostics = _build_diagnostics(
                app,
                requested_account_hash,
                self.timeout_seconds,
                warnings,
            )
            app.disconnect()
            raise IBKRFetchError("IBKR read request setup failed", diagnostics) from exc

        account_done = app.account_summary_event.wait(self.timeout_seconds)
        positions_done = app.positions_event.wait(self.timeout_seconds)
        try:
            app.cancelAccountSummary(9101)
        except Exception:
            pass
        finally:
            app.disconnect()

        warnings = _data_path_warnings(app, managed_done, account_done, positions_done)
        if not app.cash and not app.positions:
            warnings.extend(
                [
                    WarningCode.IBKR_NO_DATA_RETURNED,
                    WarningCode.IBKR_READ_SUCCEEDED_EMPTY,
                ]
            )
        diagnostics = _build_diagnostics(
            app,
            requested_account_hash,
            self.timeout_seconds,
            warnings,
        )

        if app.errors:
            raise IBKRFetchError("IBKR read callbacks reported errors", diagnostics)
        if not account_done or not positions_done:
            raise IBKRFetchError("IBKR read callbacks timed out", diagnostics)

        return IBKRReadOnlySnapshot(
            accounts=list(app.accounts.values()),
            cash=app.cash,
            positions=app.positions,
            diagnostics=diagnostics,
        )


def _load_ibapi_modules() -> tuple[Any, Any]:
    try:
        return (
            importlib.import_module("ibapi.client"),
            importlib.import_module("ibapi.wrapper"),
        )
    except ImportError as exc:
        raise IBKRSDKNotInstalledError("ibapi is not installed") from exc


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cost_basis(quantity: float, average_cost: float) -> float | None:
    if average_cost == 0:
        return None
    return float(quantity) * float(average_cost)


def _build_diagnostics(
    app: Any,
    requested_account_hash: str | None,
    timeout_seconds: float,
    warning_codes: list[WarningCode],
) -> IBKRReadDiagnostics:
    requested_account_seen: bool | None = None
    if app.account_filter:
        requested_account_seen = (
            app.account_filter in app.managed_accounts if app.managed_accounts_seen else None
        )
    return IBKRReadDiagnostics(
        connected_to_socket=bool(app.connected_to_socket),
        api_handshake_seen=bool(app.api_handshake_seen),
        managed_accounts_seen=bool(app.managed_accounts_seen),
        managed_account_count_redacted=len(app.managed_accounts),
        requested_account_hash=requested_account_hash,
        requested_account_seen=requested_account_seen,
        positions_callback_seen=bool(app.positions_callback_seen),
        position_count=len(app.positions),
        account_summary_callback_seen=bool(app.account_summary_callback_seen),
        cash_currency_count=len({row.currency for row in app.cash if row.currency}),
        timeout_seconds=timeout_seconds,
        warning_codes=_dedupe_warning_codes(warning_codes),
    )


def _data_path_warnings(
    app: Any,
    managed_done: bool,
    account_done: bool,
    positions_done: bool,
) -> list[WarningCode]:
    warnings = _managed_account_warnings(app, managed_done)
    if account_done and not app.cash:
        warnings.append(WarningCode.IBKR_ACCOUNT_SUMMARY_EMPTY)
    if positions_done and not app.positions:
        warnings.append(WarningCode.IBKR_POSITIONS_EMPTY)
    if not account_done or not positions_done:
        warnings.append(WarningCode.IBKR_CALLBACK_TIMEOUT)
    return warnings


def _managed_account_warnings(app: Any, managed_done: bool) -> list[WarningCode]:
    if not managed_done:
        return [WarningCode.IBKR_CALLBACK_TIMEOUT]
    if not app.managed_accounts:
        return [WarningCode.IBKR_MANAGED_ACCOUNTS_EMPTY]
    return []


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
