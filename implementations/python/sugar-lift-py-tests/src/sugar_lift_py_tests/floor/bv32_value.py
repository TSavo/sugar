from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class Bv32Value(FloorValue):
    term: Term
