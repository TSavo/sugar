from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.factory.dig_refusal import DigBoundary


@dataclass(frozen=True)
class DigBoundaryEffect:
    """#3632: typed-effect wrapper for a DigBoundary. Previously named
    `DigRefusalEffect`; that name remains a compatibility alias below."""

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
            # #3632: this diagnostic's wire "kind" used to be "dig-refusal".
            # Every in-tree reader of this field accepts both "dig-boundary"
            # (current) and the legacy "dig-refusal" spelling, since a
            # diagnostic emitted by an older kit build may still carry it.
            "kind": "dig-boundary",
            "callee": self.callee,
            "blame": self.blame,
            "caught": self.caught,
            "reason": self.reason,
        }


# Compatibility alias: pre-#3632 code imports `DigRefusalEffect`.
DigRefusalEffect = DigBoundaryEffect
