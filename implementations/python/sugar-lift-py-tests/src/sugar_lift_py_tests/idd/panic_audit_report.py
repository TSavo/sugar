from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .lift_target import LiftTarget
from .panic_record import PanicRecord
from .panic_vector import PanicVector


@dataclass(frozen=True)
class PanicAuditReport:
    targets: tuple[LiftTarget, ...]
    records: list[PanicRecord]
    diagnostics: list[str] = field(default_factory=list)

    @property
    def r(self) -> PanicVector:
        return PanicVector.from_records(self.records)

    @property
    def is_zero(self) -> bool:
        return self.r.is_zero and not self.diagnostics

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "python-numpy-pandas-panic-audit",
            "r": dict(self.r.values),
            "diagnostics": list(self.diagnostics),
            "records": [record.to_json() for record in self.records],
            "targets": [{"name": target.name, "path": str(target.path)} for target in self.targets],
        }
