"""Financial independence summary placeholder for v0.1 dashboards."""

from __future__ import annotations

from dataclasses import dataclass

from personal_cfo_agent.models import RiskSummary


@dataclass(frozen=True)
class FireSnapshot:
    investable_assets: float
    liquid_assets: float
    notes: str


def build_fire_snapshot(risk_summary: RiskSummary) -> FireSnapshot:
    return FireSnapshot(
        investable_assets=risk_summary.investable_assets,
        liquid_assets=risk_summary.liquid_assets,
        notes="Descriptive only; no recommendation or planning advice generated.",
    )
