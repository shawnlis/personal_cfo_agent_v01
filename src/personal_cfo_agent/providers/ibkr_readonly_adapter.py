"""Guarded IBKR read-only adapter with lazy SDK import."""

from __future__ import annotations

import importlib
import threading
from datetime import datetime, timezone
from typing import Any

from personal_cfo_agent.providers.ibkr_models import (
    IBKRAccountRow,
    IBKRCashRow,
    IBKRPositionRow,
    IBKRReadOnlySnapshot,
)


class IBKRSDKNotInstalledError(RuntimeError):
    pass


class IBKRConnectionError(RuntimeError):
    pass


class IBKRFetchError(RuntimeError):
    pass


class IBKRReadOnlyAdapter:
    """Collects IBKR account data through allowlisted read requests only."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        account_filter: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_filter = account_filter
        self.timeout_seconds = timeout_seconds

    def collect(self) -> IBKRReadOnlySnapshot:
        client_module, wrapper_module = _load_ibapi_modules()
        source_timestamp = datetime.now(timezone.utc).isoformat()

        class _ReadOnlyApp(wrapper_module.EWrapper, client_module.EClient):  # type: ignore[name-defined]
            def __init__(self, account_filter: str | None) -> None:
                wrapper_module.EWrapper.__init__(self)
                client_module.EClient.__init__(self, self)
                self.account_filter = account_filter
                self.ready_event = threading.Event()
                self.account_summary_event = threading.Event()
                self.positions_event = threading.Event()
                self.errors: list[str] = []
                self.accounts: dict[str, IBKRAccountRow] = {}
                self.cash: list[IBKRCashRow] = []
                self.positions: list[IBKRPositionRow] = []

            def nextValidId(self, orderId: int) -> None:  # noqa: N802
                self.ready_event.set()

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
                if self.account_filter and account != self.account_filter:
                    return
                self.accounts.setdefault(
                    account,
                    IBKRAccountRow(
                        account_id=account,
                        currency=currency or None,
                        notes="IBKR account summary",
                    ),
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
                if self.account_filter and account != self.account_filter:
                    return
                symbol = str(getattr(contract, "symbol", "") or "")
                asset_type = str(getattr(contract, "secType", "") or "unknown").lower()
                currency = getattr(contract, "currency", None)
                self.accounts.setdefault(
                    account,
                    IBKRAccountRow(
                        account_id=account,
                        currency=currency,
                        notes="IBKR positions",
                    ),
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
        except Exception as exc:  # pragma: no cover - exercised with live gateway only
            raise IBKRConnectionError(str(exc)) from exc

        worker = threading.Thread(target=app.run, daemon=True)
        worker.start()
        if not app.ready_event.wait(self.timeout_seconds):
            app.disconnect()
            raise IBKRConnectionError("IBKR client did not become ready")

        app.reqAccountSummary(
            9101,
            "All",
            "TotalCashValue,CashBalance,SettledCash,NetLiquidation,AvailableFunds",
        )
        app.reqPositions()
        account_done = app.account_summary_event.wait(self.timeout_seconds)
        positions_done = app.positions_event.wait(self.timeout_seconds)
        try:
            app.cancelAccountSummary(9101)
        finally:
            app.disconnect()

        if app.errors:
            raise IBKRFetchError("; ".join(app.errors))
        if not account_done and not positions_done:
            raise IBKRFetchError("IBKR read requests timed out")

        return IBKRReadOnlySnapshot(
            accounts=list(app.accounts.values()),
            cash=app.cash,
            positions=app.positions,
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
