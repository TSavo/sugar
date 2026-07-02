from __future__ import annotations

from dataclasses import dataclass

from .factory_spine_offender import FactorySpineOffender


@dataclass(frozen=True)
class FactorySpineVector:
    values: dict[str, int]

    @classmethod
    def from_offenders(
        cls, offenders: list[FactorySpineOffender]
    ) -> "FactorySpineVector":
        values = {
            "callee_body_worklists": 0,
            "block_of_callee_body_reductions": 0,
            "callsite_values_with_null_multistatement_body": 0,
            "mini_interpreter_consumers_not_reading_terms": 0,
            "transitive_worklist_drains": 0,
            "projection_ladders": 0,
            "prior_assignment_replays": 0,
        }
        for offender in offenders:
            values[offender.kind] += 1
        return cls(values)

    @property
    def total(self) -> int:
        return sum(self.values.values())

    @property
    def is_zero(self) -> bool:
        return self.total == 0
