from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class OpaqueOpCallsite(FloorValue):
    """A builtin operator applied to an argument, as an opaque callsite coordinate.

    `len(x)` is not an operation we perform on `x` to get a scalar -- it is a
    different CONTRACT at a composed coordinate. `len` is an uninterpreted operator
    (no Python body anywhere to dig); wrapping a value in it seals the value inside
    the coordinate name `call:len(<x>)` and carries it by identity. This is the same
    shape a vendor callsite (`call:pandas.DataFrame()`) already has, and it makes the
    operator's spelling IDENTICAL wherever it appears -- LHS, RHS, or nested -- so
    congruence can join `len` facts across assertions. (Contrast the retired paths:
    the construction floors collapsed `len([1,2,3])` to the scalar `3`, destroying
    the `call:len(array(...))` coordinate; the symbolic floor spelled it `py.len`,
    a DIFFERENT symbol than the `call:len` the LHS emits.)

    `computed` is the operator's value WHEN the argument is a real construction the
    lift can count (`len([1,2,3])` -> `TermValue(3)`); it is `None` when the argument
    is opaque (`len(pd.Series())`). The value is carried, never substituted for the
    coordinate: the emission layer reads `computed` to emit the DERIVED companion
    fact `call:len(<x>) == 3` alongside the symbolic coordinate, so the solver grounds
    the coordinate by transitivity without the coordinate ever collapsing. When
    `computed` is present, downstream operations (arithmetic on a length, a nested
    operator) delegate to it -- the coordinate matters at the comparison/argument
    boundary, not inside an arithmetic expression that consumes the length.
    """

    callee: str
    arg: FloorValue
    computed: FloorValue | None = None

    def to_term(self, *, owner: str) -> Term:
        from sugar_lift_py_tests.ir import ctor

        return ctor(f"call:{self.callee}", [self.arg.to_term(owner=owner)])

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        # A nested `len` ALWAYS wraps into another opaque coordinate --
        # `len(len(x))` -> `call:len(call:len(<x>))` -- and never delegates to the
        # computed value: the length of a length is not the count of a scalar
        # (Python's `len(3)` is a TypeError), so there is nothing to compute. This
        # replaces the `TermValue.__len__` gap the old scalar collapse triggered.
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(OpaqueOpCallsite(callee="len", arg=self, computed=None))
        # Any other method over a computed length behaves as its value (e.g.
        # `.__int__` on a known count).
        if self.computed is not None:
            return self.computed.call_method_with(operation, ctx)
        return super().call_method_with(operation, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        if self.computed is not None:
            return self.computed.binary_operator_with(operation, ctx)
        return super().binary_operator_with(operation, ctx)

    def reflected_binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        if self.computed is not None:
            return self.computed.reflected_binary_operator_with(operation, ctx)
        return super().reflected_binary_operator_with(operation, ctx)

    def unary_operator_with(self, operation: Any, ctx: Any) -> Any:
        if self.computed is not None:
            return self.computed.unary_operator_with(operation, ctx)
        return super().unary_operator_with(operation, ctx)

    def bitwise_with(self, operation: Any, ctx: Any) -> Any:
        if self.computed is not None:
            return self.computed.bitwise_with(operation, ctx)
        return super().bitwise_with(operation, ctx)
