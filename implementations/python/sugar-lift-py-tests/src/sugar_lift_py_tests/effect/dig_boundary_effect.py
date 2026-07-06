from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.factory.dig_boundary import DigBoundary


@dataclass(frozen=True)
class DigBoundaryEffect:
    """Typed-effect wrapper for a DigBoundary."""

    callee: str
    blame: str
    caught: str
    reason: str

    @classmethod
    def from_refusal(cls, refusal: DigBoundary) -> DigBoundaryEffect:
        return cls(
            callee=refusal.callee,
            blame=refusal.blame,
            caught=refusal.caught,
            reason=refusal.reason,
        )

    def to_diagnostic(self) -> dict[str, Any]:
        return {
            "kind": "dig-boundary",
            "callee": self.callee,
            "blame": self.blame,
            "caught": self.caught,
            "reason": self.reason,
        }
