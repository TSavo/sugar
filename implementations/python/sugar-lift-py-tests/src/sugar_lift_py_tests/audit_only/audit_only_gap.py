from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class AuditOnlyGap:
    label: str
    info: dict[str, str]
    message: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "audit-only-construction-gap",
            "label": self.label,
            "message": self.message,
            "gap": dict(self.info),
        }
