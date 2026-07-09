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

    def _downstream(self) -> FloorValue:
        """The value a downstream operation consumes. A computed length behaves as
        its counted value (`len([1,2,3]) + 1 == 4`); an OPAQUE length behaves as its
        symbolic coordinate term `call:len(<x>)` -- exactly the symbolic citizen the
        retired `py.len` `SymbolicValue` was, now spelled `call:len`. Either way an
        operator over a length is a total floor, never a construction gap. (The
        coordinate itself is preserved in `to_term`; `_downstream` is only the value
        an ARITHMETIC/format expression consumes.)"""
        if self.computed is not None:
            return self.computed
        from .symbolic_value import SymbolicValue

        return SymbolicValue(self.to_term(owner="OpaqueOpCallsite.symbolic"))

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        # A nested `len` ALWAYS wraps into another opaque coordinate --
        # `len(len(x))` -> `call:len(call:len(<x>))` -- and never delegates to the
        # computed value: the length of a length is not the count of a scalar
        # (Python's `len(3)` is a TypeError), so there is nothing to compute. This
        # replaces the `TermValue.__len__` gap the old scalar collapse triggered.
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(OpaqueOpCallsite(callee="len", arg=self, computed=None))
        return self._downstream().call_method_with(operation, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().binary_operator_with(operation, ctx)

    def reflected_binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().reflected_binary_operator_with(operation, ctx)

    def unary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().unary_operator_with(operation, ctx)

    def bitwise_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().bitwise_with(operation, ctx)

    def format_value_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().format_value_with(operation, ctx)

    def str_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().str_with(operation, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().subscript_with(operation, ctx)

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().contains_with(operation, ctx)
