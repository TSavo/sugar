from __future__ import annotations

from dataclasses import dataclass

from .dunder_slot import DunderSlot

DunderAxis = str


@dataclass(frozen=True)
class DunderFrontierVector:
    values: dict[DunderAxis, int]

    @classmethod
    def from_slots(cls, slots: list[DunderSlot]) -> "DunderFrontierVector":
        values: dict[str, int] = {f"{slot.axis}_slots": 0 for slot in slots}
        for slot in slots:
            if slot.status != "missing":
                continue
            values[f"{slot.axis}_slots"] = values.get(f"{slot.axis}_slots", 0) + 1
        return cls(dict(sorted(values.items())))

    @property
    def total(self) -> int:
        return sum(self.values.values())

    @property
    def is_zero(self) -> bool:
        return self.total == 0
