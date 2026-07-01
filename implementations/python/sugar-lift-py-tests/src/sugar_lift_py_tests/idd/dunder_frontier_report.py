from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dunder_frontier_vector import DunderFrontierVector
from .dunder_slot import DunderSlot


@dataclass(frozen=True)
class DunderFrontierReport:
    slots: list[DunderSlot]

    @property
    def r(self) -> DunderFrontierVector:
        return DunderFrontierVector.from_slots(self.slots)

    @property
    def is_zero(self) -> bool:
        return self.r.is_zero

    @property
    def missing_slots(self) -> list[DunderSlot]:
        return [slot for slot in self.slots if slot.status == "missing"]

    @property
    def owned_slots(self) -> list[DunderSlot]:
        return [slot for slot in self.slots if slot.status == "owned"]

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "python-dunder-frontier-audit",
            "r": {**self.r.values, "total": self.r.total},
            "slots": [slot.to_json() for slot in self.slots],
        }
