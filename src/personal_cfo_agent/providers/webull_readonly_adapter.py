"""Webull read-only adapter scaffold for future separately approved live work."""

from __future__ import annotations

from dataclasses import dataclass

from personal_cfo_agent.models import WarningCode


class WebullLiveReadNotImplementedError(RuntimeError):
    """Raised when code attempts to use the not-yet-approved Webull live path."""


@dataclass(frozen=True)
class WebullReadinessSnapshot:
    warning_codes: tuple[WarningCode, ...]


class WebullReadOnlyAdapter:
    """Read-only scaffold only.

    v0.5.4 stops at feasibility checks. This class exists to reserve a safe adapter
    boundary without creating API clients, sending requests, or reading account data.
    """

    def collect(self) -> WebullReadinessSnapshot:
        raise WebullLiveReadNotImplementedError(
            "Webull live read is not implemented in v0.5.4"
        )
