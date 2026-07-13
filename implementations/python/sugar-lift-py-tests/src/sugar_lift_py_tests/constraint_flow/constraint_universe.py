from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constraint_dig_request import ConstraintDigRequest
from ..factory.factory_gap import dig_boundary_panic


@dataclass(frozen=True)
class ConstraintUniverse:
    predicates: list[dict[str, Any]]
    proofir: list[dict[str, Any]]
    effects: list[dict[str, Any]]
    source_memento: dict[str, Any]
    sugar_chain: list[str]
    warranted_by: ConstraintDigRequest
    dig_diagnostics: list

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "constraint-universe",
            "predicates": list(self.predicates),
            "proofir": list(self.proofir),
            "effects": list(self.effects),
            "sourceMemento": dict(self.source_memento),
            "sugarChain": list(self.sugar_chain),
            "warrantedBy": self.warranted_by.to_json(),
            # DigBoundary soft rows are deleted. Any dig gap panics at the
            # record site, so this diagnostic list is always empty.
            "diagnostics": list(self.dig_diagnostics),
        }
