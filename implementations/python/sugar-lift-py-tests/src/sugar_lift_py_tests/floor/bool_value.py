from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BoolValue(FloorValue):
    value: bool

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import bool_const

        return bool_const(self.value)

    def project_callsite_with(self, operation, ctx):
        return operation.project_literal(self, ctx)
