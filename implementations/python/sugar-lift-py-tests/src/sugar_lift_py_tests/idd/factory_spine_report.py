from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .factory_spine_offender import FactorySpineOffender
from .factory_spine_vector import FactorySpineVector


@dataclass(frozen=True)
class FactorySpineReport:
    offenders: list[FactorySpineOffender]

    @property
    def r(self) -> FactorySpineVector:
        return FactorySpineVector.from_offenders(self.offenders)

    @property
    def is_zero(self) -> bool:
        return self.r.is_zero

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "python-factory-spine-frontier-audit",
            "r": {**self.r.values, "total": self.r.total},
            "offenders": [offender.to_json() for offender in self.offenders],
        }
