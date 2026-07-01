from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class Bv32Value(FloorValue):
    term: Term

    def str_with(self, operation, ctx):
        return operation.str_bv32(self, ctx)

    def bitwise_with(self, operation, ctx):
        return operation.bitwise_bv32(self, ctx)
