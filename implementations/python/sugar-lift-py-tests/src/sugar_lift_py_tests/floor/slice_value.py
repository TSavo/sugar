from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SliceValue(FloorValue):
    lower: FloorValue | None
    upper: FloorValue | None
    step: FloorValue | None
