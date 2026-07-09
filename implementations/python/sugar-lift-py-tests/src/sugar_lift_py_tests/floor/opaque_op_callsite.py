# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class OpaqueOpCallsite(FloorValue):
    """A builtin operator applied to arguments, as an opaque callsite coordinate.

    A pure builtin operator is an uninterpreted symbol carried in the coordinate
    name `call:<op>(<args>)`; its value is a *derived* companion fact, never a
    substitution that collapses the coordinate. This is the same shape a vendor
    callsite (`call:pandas.DataFrame()`) already has, so congruence can join
    operator facts across assertions.

    `computed` is the operator's value WHEN the arguments are real constructions
    the lift can fold (`len([1,2,3])` → `TermValue(3)`, `str(12)` →
    `StringValue("12")`); it is `None` when any argument is opaque or the
    operator is non-folding (`hash(...)`). The value is carried, never
    substituted for the coordinate: emission reads `computed` for the Derived
    companion `call:<op>(...) == <value>`. Downstream arithmetic/format
    delegates to `_downstream()` so a computed length participates in `+`
    without the coordinate collapsing at the comparison boundary.

    ONE wrap site produces every pure-value builtin coordinate
    (`BuiltinCallSugar` / `FormatBuiltinSugar` / `DivmodBuiltinSugar`);
    floor-level `__len__` handlers return bare folded values and the wrap
    re-attaches the coordinate.
    """

    callee: str
    arg: FloorValue
    computed: FloorValue | None = None
    # Additional operands (e.g. format's spec, divmod's right). Primary arg
    # stays `arg` so single-operand sites stay a one-field construction.
    extra_args: tuple[FloorValue, ...] = ()

    def to_term(self, *, owner: str) -> Term:
        from sugar_lift_py_tests.ir import ctor

        args = [self.arg.to_term(owner=owner)]
        args.extend(extra.to_term(owner=owner) for extra in self.extra_args)
        return ctor(f"call:{self.callee}", args)

    def _downstream(self) -> FloorValue:
        """The value a downstream operation consumes.

        A computed result behaves as that folded value; an opaque result
        behaves as the symbolic coordinate term `call:<op>(...)`. Either way
        the operator surface is total — never a construction gap.
        """
        if self.computed is not None:
            return self.computed
        from .symbolic_value import SymbolicValue

        return SymbolicValue(self.to_term(owner="OpaqueOpCallsite.symbolic"))

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        # Nested `len(len(x))` → `call:len(call:len(<x>))`. Never delegate to
        # computed: Python's `len(3)` is a TypeError.
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


def is_concrete_floor_value(value: FloorValue) -> bool:
    """True when `value` is a statically folded construction the wrap can ground.

    SymbolicValue / OpaqueOpCallsite / ObjectValue / ArrayLiteral are not
    concrete — they do not supply a companion equality by themselves.
    """
    from .bool_value import BoolValue
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_literal_value import TupleLiteralValue

    if isinstance(value, (TermValue, StringValue, BoolValue)):
        return True
    if isinstance(value, TupleLiteralValue):
        return all(is_concrete_floor_value(item) for item in value.items)
    return False


def wrap_builtin_operator(
    callee: str,
    arg: FloorValue,
    result: FloorValue,
    *,
    extra_args: tuple[FloorValue, ...] = (),
) -> FloorValue:
    """THE one wrap: foldable pure-value builtin result → `call:<op>(args)`.

    Partition is *foldable vs diggable/opaque*, not merely pure-value vs stateful:

    - **CallSiteValue** (e.g. `hash(Box())` / `repr(Box())` after ObjectValue
      method dispatch): diggable user-method body. Do NOT wrap — dig must still
      see the callsite. Wrapping to ungrounded `call:hash(...)` with
      `computed=None` is the refuse regression the witness corpus caught.
    - **Already-coordinate** same callee: idempotent pass-through.
    - **Concrete fold** (TermValue/StringValue/BoolValue/…): wrap with
      `computed=result` (companion ground).
    - **Symbolic non-fold**: wrap with `computed=None` (joinable uninterpreted
      op like `len(x)` / `str(x)` — never fabricate a value).
    """
    from .call_site_value import CallSiteValue

    # Diggable method body (Box.__hash__, Box.__repr__, …): leave for dig.
    # These behave like vendor attributes (sworn/dug), not foldable builtins.
    if isinstance(result, CallSiteValue):
        return result
    if (
        isinstance(result, OpaqueOpCallsite)
        and result.callee == callee
        and result.extra_args == extra_args
    ):
        return result
    computed = result if is_concrete_floor_value(result) else None
    return OpaqueOpCallsite(
        callee=callee,
        arg=arg,
        computed=computed,
        extra_args=extra_args,
    )
