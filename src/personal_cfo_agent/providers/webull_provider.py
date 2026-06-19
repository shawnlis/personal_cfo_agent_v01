"""Webull provider with guarded supervised read-only proof support."""

from __future__ import annotations

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
from personal_cfo_agent.providers.webull_connection_diagnostics import (
    run_webull_connection_diagnostics,
)
from personal_cfo_agent.providers.webull_readonly_adapter import (
    WebullClientInitError,
    WebullFetchError,
    WebullReadError,
    WebullReadOnlyAdapter,
    WebullReadOnlySnapshot,
    WebullSDKNotInstalledError,
)


class WebullProvider(ProviderBase):
    provider_name = "webull"
    provider_level = ProviderLevel.LEVEL_1
    connection_mode = ConnectionMode.API_STUB

    def __init__(
        self,
        config,
        allow_live_read: bool = False,
        live_adapter: WebullReadOnlyAdapter | None = None,
    ) -> None:
        super().__init__(config=config, allow_live_read=allow_live_read)
        self._snapshot: WebullReadOnlySnapshot | None = None
        self._live_adapter = live_adapter

    def validate_config(self) -> list[WarningCode]:
        diagnostics = run_webull_connection_diagnostics(self.config.settings)
        self.diagnostics = _diagnostics_dict(diagnostics)
        mapped = _map_config_warnings(diagnostics.warning_codes)
        return [code for code in mapped if code != WarningCode.WEBULL_READINESS_OK]

    def readiness_check(self) -> list[WarningCode]:
        diagnostics = run_webull_connection_diagnostics(self.config.settings)
        self.diagnostics = _diagnostics_dict(diagnostics)
        self.warning_codes = _dedupe([*self.warning_codes, *diagnostics.warning_codes])
        self.connection_mode = ConnectionMode.LIVE_READINESS
        return self.warning_codes

    def connection_diagnostics(self):
        return run_webull_connection_diagnostics(self.config.settings)

    def connect_read_only(self) -> bool:
        if WarningCode.PROVIDER_DISABLED in self.warning_codes:
            return False
        if WarningCode.PROVIDER_CONFIG_MISSING in self.warning_codes:
            return False
        if WarningCode.WEBULL_CONFIG_MISSING in self.warning_codes:
            return False
        if WarningCode.SDK_NOT_INSTALLED in self.warning_codes:
            return False
        if WarningCode.WEBULL_SDK_NOT_INSTALLED in self.warning_codes:
            return False
        if not self.allow_live_read:
            self.warning_codes = _dedupe(
                [*self.warning_codes, WarningCode.LIVE_READ_NOT_ALLOWED]
            )
            return False
        adapter = self._live_adapter or self._build_adapter()
        try:
            self._snapshot = adapter.collect()
        except WebullSDKNotInstalledError as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    *_warning_codes_from_diagnostics(self.diagnostics),
                    WarningCode.WEBULL_SDK_NOT_INSTALLED,
                    WarningCode.SDK_NOT_INSTALLED,
                ]
            )
            return False
        except WebullClientInitError as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    *_warning_codes_from_diagnostics(self.diagnostics),
                    WarningCode.WEBULL_CLIENT_INIT_FAILED,
                    WarningCode.PROVIDER_CONNECTION_FAILED,
                ]
            )
            return False
        except WebullFetchError as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    *_warning_codes_from_diagnostics(self.diagnostics),
                    WarningCode.WEBULL_LIVE_READ_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ]
            )
            return False
        except Exception:
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    WarningCode.WEBULL_LIVE_READ_FAILED,
                    WarningCode.PROVIDER_FETCH_FAILED,
                ]
            )
            return False
        self.diagnostics = dict(self._snapshot.diagnostics)
        self.warning_codes = _dedupe(
            [*self.warning_codes, *_warning_codes_from_diagnostics(self.diagnostics)]
        )
        self.provider_level = ProviderLevel.LEVEL_2
        self.connection_mode = ConnectionMode.LIVE_READ
        return True

    def fetch_accounts(self) -> list[RawAccount]:
        snapshot = self._require_snapshot()
        return [
            RawAccount(
                account_id=row.account_id,
                account_type=row.account_type,
                currency=row.currency,
                notes=row.notes,
            )
            for row in snapshot.accounts
        ]

    def fetch_cash(self) -> list[RawCash]:
        snapshot = self._require_snapshot()
        return [
            RawCash(
                account_id=row.account_id,
                currency=row.currency,
                amount=row.amount,
                source_timestamp=row.source_timestamp,
                notes=row.notes,
            )
            for row in snapshot.cash
        ]

    def fetch_positions(self) -> list[RawPosition]:
        snapshot = self._require_snapshot()
        return [
            RawPosition(
                account_id=row.account_id,
                asset_id=row.asset_id,
                asset_type=row.asset_type,
                symbol=row.symbol,
                name=row.name,
                quantity=row.quantity,
                currency=row.currency,
                market_value=row.market_value,
                cost_basis=row.cost_basis,
                liquidity_bucket="liquid",
                risk_bucket=row.asset_type,
                source_timestamp=row.source_timestamp,
                source_confidence="webull_read_only_live",
                needs_review=row.market_value is None,
                warning_codes=(
                    [WarningCode.MISSING_MARKET_VALUE] if row.market_value is None else []
                ),
                notes=row.notes,
            )
            for row in snapshot.positions
        ]

    def fetch_balances(self) -> list[RawBalance]:
        snapshot = self._require_snapshot()
        balances: list[RawBalance] = []
        for row in snapshot.accounts:
            if row.account_nav is None:
                continue
            balances.append(
                RawBalance(
                    account_id=row.account_id,
                    asset_id="WEBULL-ACCOUNT-NAV",
                    asset_type="account_nav",
                    name="Webull account NAV",
                    currency=row.currency,
                    amount=row.account_nav,
                    liquidity_bucket="account_nav",
                    risk_bucket="account_nav",
                    source_timestamp=row.source_timestamp,
                    source_confidence="webull_provider_reported_nav",
                    needs_review=False,
                    warning_codes=[WarningCode.ACCOUNT_NAV_PROVIDER_REPORTED],
                    notes="Webull provider-reported account NAV",
                )
            )
        return balances

    def disconnect(self) -> None:
        return None

    def _build_adapter(self) -> WebullReadOnlyAdapter:
        return WebullReadOnlyAdapter(self.config.settings)

    def _require_snapshot(self) -> WebullReadOnlySnapshot:
        if self._snapshot is None:
            raise RuntimeError("Webull live snapshot was not collected")
        return self._snapshot


def _diagnostics_dict(diagnostics) -> dict[str, object]:
    return {
        "enabled_present": diagnostics.enabled_present,
        "enabled_true": diagnostics.enabled_true,
        "app_key_present_redacted": diagnostics.app_key_present,
        "app_secret_present_redacted": diagnostics.app_secret_present,
        "api_host_present_redacted": diagnostics.api_host_present,
        "sdk_import_ok": diagnostics.sdk_import_ok,
        "sdk_module_detected": diagnostics.sdk_module_detected,
        "live_connection_attempted": diagnostics.live_connection_attempted,
        "warning_codes": [code.value for code in diagnostics.warning_codes],
    }


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _map_config_warnings(codes: tuple[WarningCode, ...]) -> list[WarningCode]:
    mapped: list[WarningCode] = []
    for code in codes:
        mapped.append(code)
        if code == WarningCode.PROVIDER_CONFIG_MISSING:
            mapped.append(WarningCode.WEBULL_CONFIG_MISSING)
        if code == WarningCode.SDK_NOT_INSTALLED:
            mapped.append(WarningCode.WEBULL_SDK_NOT_INSTALLED)
    return _dedupe(mapped)


def _diagnostics_from_error(exc: BaseException | None = None) -> dict[str, object]:
    if isinstance(exc, WebullReadError) and exc.diagnostics is not None:
        return exc.diagnostics.to_redacted_dict()
    return {}


def _warning_codes_from_diagnostics(diagnostics: dict[str, object]) -> list[WarningCode]:
    raw_codes = diagnostics.get("warning_codes") if diagnostics else []
    codes: list[WarningCode] = []
    if not isinstance(raw_codes, list):
        return codes
    for raw_code in raw_codes:
        try:
            codes.append(WarningCode(str(raw_code)))
        except ValueError:
            continue
    return codes
