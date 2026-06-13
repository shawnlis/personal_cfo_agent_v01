"""Schema objects for v0.1.4 structured manual snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_cfo_agent.models import WarningCode


ASSET_TYPES = frozenset(
    {
        "residential_property",
        "cpf_oa",
        "cpf_sa",
        "cpf_ma",
        "cash",
        "unsupported_broker",
        "insurance_cash_value",
        "other_asset",
    }
)

LIABILITY_TYPES = frozenset(
    {
        "mortgage",
        "personal_loan",
        "credit_card",
        "other_liability",
    }
)

MANUAL_ONLY_PROVIDERS = frozenset(
    {
        "webull",
        "poems",
        "phillip",
        "unsupported_broker",
        "other_unsupported_broker",
    }
)

GOVERNMENT_PROVIDERS = frozenset({"cpf", "iras", "hdb"})


@dataclass(frozen=True)
class ManualAsset:
    asset_id: str
    asset_type: str
    provider: str
    name: str
    currency: str
    estimated_value: float
    valuation_date: str
    valuation_source: str
    liquidity_bucket: str
    risk_bucket: str
    notes: str = ""
    warning_codes: list[WarningCode] = field(default_factory=list)
    needs_review: bool = True


@dataclass(frozen=True)
class ManualLiability:
    liability_id: str
    liability_type: str
    provider: str
    name: str
    currency: str
    outstanding_balance: float
    interest_rate: float | None = None
    monthly_payment: float | None = None
    repricing_date: str = ""
    maturity_date: str = ""
    collateral: str = ""
    notes: str = ""
    warning_codes: list[WarningCode] = field(default_factory=list)
    needs_review: bool = True


@dataclass(frozen=True)
class ManualSnapshot:
    snapshot_date: str
    base_currency: str
    source_note: str
    assets: list[ManualAsset]
    liabilities: list[ManualLiability]
    warnings_acknowledged: bool
