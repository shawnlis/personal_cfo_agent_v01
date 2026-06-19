"""uSMART read-only adapter scaffold for future separately approved live work."""

from __future__ import annotations

from dataclasses import dataclass

from personal_cfo_agent.models import WarningCode


class USMARTLiveReadNotImplementedError(RuntimeError):
    """Raised when code attempts to use the not-yet-approved uSMART live path."""


@dataclass(frozen=True)
class USMARTReadinessSnapshot:
    warning_codes: tuple[WarningCode, ...]


class USMARTReadOnlyAdapter:
    """Read-only scaffold only.

    v0.5.7 stops at feasibility checks. This class exists to reserve a safe
    adapter boundary without creating API clients, sending requests, or reading
    account data.
    """

    def collect(self) -> USMARTReadinessSnapshot:
        raise USMARTLiveReadNotImplementedError(
            "uSMART live read is not implemented in v0.5.7"
        )
