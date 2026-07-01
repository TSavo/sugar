from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class PredicateValue(FloorValue):
    formula: Formula
