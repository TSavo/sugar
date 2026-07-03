from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class StringValue(FloorValue):
    value: str

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.value)

    def project_callsite_with(self, operation, ctx):
        return operation.project_literal(self, ctx)

    def contains_with(self, operation, ctx):
        return operation.contains_string(self, ctx)

    def subscript_with(self, operation, ctx):
        return operation.subscript_string(self, ctx)

    def str_with(self, operation, ctx):
        return operation.str_string(self, ctx)

    def binary_operator_with(self, operation, ctx):
        return operation.binary_string(self, ctx)
