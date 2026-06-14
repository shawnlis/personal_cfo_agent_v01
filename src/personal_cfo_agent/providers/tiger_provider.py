"""Tiger provider with guarded read-only TigerOpen proof support."""

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
from personal_cfo_agent.providers.tiger_models import TigerReadOnlySnapshot
from personal_cfo_agent.providers.tiger_readonly_adapter import (
    TigerConnectionError,
    TigerFetchError,
    TigerReadError,
    TigerReadOnlyAdapter,
    TigerSDKNotInstalledError,
)


class TigerProvider(ProviderBase):
    provider_name = "tiger"
    provider_level = ProviderLevel.LEVEL_1
    connection_mode = ConnectionMode.API_STUB

    def __init__(
        self,
        config,
        allow_live_read: bool = False,
        live_adapter: TigerReadOnlyAdapter | None = None,
    ) -> None:
        super().__init__(config=config, allow_live_read=allow_live_read)
        self._snapshot: TigerReadOnlySnapshot | None = None
        self._live_adapter = live_adapter

    def validate_config(self) -> list[WarningCode]:
        if not self.config.enabled:
            return [WarningCode.PROVIDER_DISABLED]
        if self.config.missing_required_env_vars():
            return [WarningCode.PROVIDER_CONFIG_MISSING]
        return []

    def readiness_check(self) -> list[WarningCode]:
        self.warning_codes = _dedupe([*self.warning_codes, *self.validate_config()])
        return self.warning_codes

    def connect_read_only(self) -> bool:
        if WarningCode.PROVIDER_DISABLED in self.warning_codes:
            return False
        if WarningCode.PROVIDER_CONFIG_MISSING in self.warning_codes:
            return False
        if not self.allow_live_read:
            self.warning_codes = _dedupe(
                [*self.warning_codes, WarningCode.LIVE_READ_NOT_ALLOWED]
            )
            return False

        adapter = self._live_adapter or self._build_adapter()
        try:
            self._snapshot = adapter.collect()
        except TigerSDKNotInstalledError as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    *_warning_codes_from_diagnostics(self.diagnostics),
                    WarningCode.SDK_NOT_INSTALLED,
                ]
            )
            return False
        except TigerConnectionError as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    *_warning_codes_from_diagnostics(self.diagnostics),
                    WarningCode.PROVIDER_CONNECTION_FAILED,
                ]
            )
            return False
        except TigerFetchError as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe(
                [
                    *self.warning_codes,
                    *_warning_codes_from_diagnostics(self.diagnostics),
                    WarningCode.PROVIDER_FETCH_FAILED,
                ]
            )
            return False
        except Exception as exc:
            self.diagnostics = _diagnostics_from_error(exc)
            self.warning_codes = _dedupe([*self.warning_codes, WarningCode.PROVIDER_FETCH_FAILED])
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
                source_confidence="tiger_read_only_live",
                needs_review=row.market_value is None,
                warning_codes=(
                    [WarningCode.MISSING_MARKET_VALUE] if row.market_value is None else []
                ),
                notes=row.notes,
            )
            for row in snapshot.positions
        ]

    def fetch_balances(self) -> list[RawBalance]:
        return []

    def disconnect(self) -> None:
        return None

    def _build_adapter(self) -> TigerReadOnlyAdapter:
        settings = self.config.settings
        return TigerReadOnlyAdapter(
            config_dir=str(settings["CFO_TIGER_CONFIG_DIR"]),
            account_id=str(settings["CFO_TIGER_ACCOUNT"]),
            account_hash_salt=settings.get("CFO_ACCOUNT_HASH_SALT"),
        )

    def _require_snapshot(self) -> TigerReadOnlySnapshot:
        if self._snapshot is None:
            raise RuntimeError("Tiger live snapshot was not collected")
        return self._snapshot


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _diagnostics_from_error(exc: BaseException | None = None) -> dict[str, object]:
    if isinstance(exc, TigerReadError) and exc.diagnostics is not None:
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
