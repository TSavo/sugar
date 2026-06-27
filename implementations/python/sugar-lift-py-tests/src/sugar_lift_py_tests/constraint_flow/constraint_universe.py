from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constraint_dig_request import ConstraintDigRequest


@dataclass(frozen=True)
class ConstraintUniverse:
    predicates: list[dict[str, Any]]
    proofir: list[dict[str, Any]]
    effects: list[dict[str, Any]]
    source_memento: dict[str, Any]
    sugar_chain: list[str]
    warranted_by: ConstraintDigRequest

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "constraint-universe",
            "predicates": list(self.predicates),
            "proofir": list(self.proofir),
            "effects": list(self.effects),
            "sourceMemento": dict(self.source_memento),
            "sugarChain": list(self.sugar_chain),
            "warrantedBy": self.warranted_by.to_json(),
        }
