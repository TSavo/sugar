from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConstraintDigRequest:
    fact_subject: str
    target_symbol: str
    source_memento: dict[str, Any]
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "constraint-dig-request",
            "factSubject": self.fact_subject,
            "targetSymbol": self.target_symbol,
            "sourceMemento": dict(self.source_memento),
            "reason": self.reason,
        }
