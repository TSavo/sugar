from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class TemporalRewriteStep:
    kind: str
    name: str
    value: FloorValue
    blame: str

    @classmethod
    def add_assign(
        cls, name: str, value: FloorValue, *, blame: str
    ) -> "TemporalRewriteStep":
        return cls(kind="add_assign", name=name, value=value, blame=blame)
