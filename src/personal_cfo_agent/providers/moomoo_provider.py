"""Moomoo Level 1 provider stub with guarded Level 2 readiness mode."""

from __future__ import annotations

from personal_cfo_agent.provider_base import ReadinessOnlyProvider


class MoomooProvider(ReadinessOnlyProvider):
    provider_name = "moomoo"
