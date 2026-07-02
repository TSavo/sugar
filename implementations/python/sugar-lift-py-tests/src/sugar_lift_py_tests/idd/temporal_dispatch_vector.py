from __future__ import annotations

from dataclasses import dataclass

from .temporal_dispatch_offender import TemporalDispatchOffender


@dataclass(frozen=True)
class TemporalDispatchVector:
    values: dict[str, int]

    @classmethod
    def from_offenders(
        cls, offenders: list[TemporalDispatchOffender]
    ) -> "TemporalDispatchVector":
        values = {
            "direct_temporal_bindings": 0,
            "direct_temporal_replacements": 0,
            "temporal_rewrite_switches": 0,
            "direct_context_minting": 0,
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
