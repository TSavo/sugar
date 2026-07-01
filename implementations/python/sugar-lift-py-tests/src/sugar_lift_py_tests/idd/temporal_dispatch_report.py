from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .temporal_dispatch_offender import TemporalDispatchOffender
from .temporal_dispatch_vector import TemporalDispatchVector


@dataclass(frozen=True)
class TemporalDispatchReport:
    offenders: list[TemporalDispatchOffender]

    @property
    def r(self) -> TemporalDispatchVector:
        return TemporalDispatchVector.from_offenders(self.offenders)

    @property
    def is_zero(self) -> bool:
        return self.r.is_zero

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "python-temporal-dispatch-frontier-audit",
            "r": {**self.r.values, "total": self.r.total},
            "offenders": [offender.to_json() for offender in self.offenders],
        }
