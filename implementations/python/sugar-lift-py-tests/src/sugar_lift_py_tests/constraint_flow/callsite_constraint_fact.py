from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constraint_dig_request import ConstraintDigRequest


@dataclass(frozen=True)
class CallsiteConstraintFact:
    sugar_name: str
    callsite: str
    subject: str
    fact: dict[str, Any]
    source_memento: dict[str, Any]
    target_symbol: str

    def trigger_dig(self) -> ConstraintDigRequest:
        return ConstraintDigRequest(
            fact_subject=self.subject,
            target_symbol=self.target_symbol,
            source_memento=dict(self.source_memento),
            reason=(
                "vendor callsite fact warrants constraint-universe dig "
                f"for {self.target_symbol}"
            ),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "callsite-constraint-fact",
            "sugarName": self.sugar_name,
            "callsite": self.callsite,
            "subject": self.subject,
            "fact": dict(self.fact),
            "sourceMemento": dict(self.source_memento),
            "targetSymbol": self.target_symbol,
        }
