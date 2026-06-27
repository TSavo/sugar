from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.factory import FactoryAuditRow


@dataclass(frozen=True)
class AuditOnlyGap:
    label: str
    info: dict[str, str]
    audit_row: FactoryAuditRow
    message: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "audit-only-construction-gap",
            "label": self.label,
            "message": self.message,
            "gap": dict(self.info),
            "auditRow": self.audit_row.to_json(),
        }
