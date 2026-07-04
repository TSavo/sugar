from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.factory.dig_refusal import DigRefusal


@dataclass(frozen=True)
class DigRefusalEffect:
    callee: str
    blame: str
    caught: str
    reason: str

    @classmethod
    def from_refusal(cls, refusal: DigRefusal) -> DigRefusalEffect:
        return cls(
            callee=refusal.callee,
            blame=refusal.blame,
            caught=refusal.caught,
            reason=refusal.reason,
        )

    def to_diagnostic(self) -> dict[str, Any]:
        return {
            "kind": "dig-refusal",
            "callee": self.callee,
            "blame": self.blame,
            "caught": self.caught,
            "reason": self.reason,
        }
