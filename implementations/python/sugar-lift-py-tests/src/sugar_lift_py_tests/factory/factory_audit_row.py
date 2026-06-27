from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class FactoryAuditRow:
    role: str
    status: str
    observed: str
    blame: str
    selected: Optional[str]
    candidates: List[str]
    message: str

    def to_json(self):
        return {
            "kind": "factory-audit-row",
            "role": self.role,
            "status": self.status,
            "observed": self.observed,
            "blame": self.blame,
            "selected": self.selected,
            "candidates": list(self.candidates),
            "message": self.message,
        }
