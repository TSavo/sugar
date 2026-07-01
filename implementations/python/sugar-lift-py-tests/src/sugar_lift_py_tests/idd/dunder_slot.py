from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DunderSlotStatus = Literal["owned", "missing"]


@dataclass(frozen=True)
class DunderSlot:
    axis: str
    name: str
    status: DunderSlotStatus
    owner: str
    fix: str

    def to_json(self) -> dict[str, str]:
        return {
            "axis": self.axis,
            "name": self.name,
            "status": self.status,
            "owner": self.owner,
            "fix": self.fix,
        }
