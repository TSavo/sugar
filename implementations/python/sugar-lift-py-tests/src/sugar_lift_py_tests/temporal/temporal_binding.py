from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class TemporalBinding:
    name: str
    value: FloorValue
    blame: str | None = None
