# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.call_symbol import call_symbol
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

    def denotes_a_value(self) -> bool:
        # An operator coordinate denotes the operator's RESULT. Same testimony
        # as CallSiteValue: a value of undecided identity, never a callable.
        return True

    def to_term(self, *, owner: str) -> Term:
        from sugar_lift_py_tests.ir import ctor

        args = [self.arg.to_term(owner=owner)]
        args.extend(extra.to_term(owner=owner) for extra in self.extra_args)
        return ctor(call_symbol(self.callee), args, symbol_kind="method-coordinate")

    def callsites(self):
        return (self,)

    def companion_formula(self, *, owner: str):
        """Return the computed grounding fact without collapsing the coordinate."""
        if self.computed is None:
            return None
        from sugar_lift_py_tests.ir import eq

        return eq(
            self.to_term(owner=owner),
            self.computed.to_term(owner=owner),
        )

    def edge_contribution(self, source_contract):
        """Project the bridge carried by this builtin-operator coordinate."""
        return (
            {
                "kind": "call-edge",
                "sourceContract": source_contract,
                "targetSymbol": call_symbol(self.callee),
            },
        )

    def truth(self, site):
        """Cite Python truth over the already-built operator coordinate."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                py_truthy(self.to_term(owner=str(site))),
                site,
                operand_callsites=(self,),
            )
        )

    def equals(self, other, site, ctx):
        from sugar_lift_py_tests.floor.equality_atom import resolve_equality_atom
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet

        companion = self.companion_formula(owner=str(site))
        companions = (companion,) if companion is not None else ()
        formula, bridges = resolve_equality_atom(self, other, owner=str(site))
        return ExitSet.completed(
            PredicateValue(
                formula,
                site,
                operand_callsites=(self,),
                derived_formulas=(*companions, *bridges),
            )
        )

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

    def add(self, other, site, ctx):
        return self._arithmetic("add", other, site, ctx)

    def subtract(self, other, site, ctx):
        return self._arithmetic("subtract", other, site, ctx)

    def multiply(self, other, site, ctx):
        return self._arithmetic("multiply", other, site, ctx)

    def divide(self, other, site, ctx):
        return self._arithmetic("divide", other, site, ctx)

    def subscript(self, index, site):
        # Preserve a computed operator value when one exists; otherwise the
        # operator coordinate is the symbolic receiver.  Both paths retain the
        # lookup rather than inventing an element.
        return self._downstream().subscript(index, site)

    def floor_divide(self, other, site, ctx):
        return self._arithmetic("floor_divide", other, site, ctx)

    def modulo(self, other, site, ctx):
        return self._arithmetic("modulo", other, site, ctx)

    def left_shift(self, other, site, ctx):
        return self._arithmetic("left_shift", other, site, ctx)

    def right_shift(self, other, site, ctx):
        return self._arithmetic("right_shift", other, site, ctx)

    def bitwise_and(self, other, site, ctx):
        return self._arithmetic("bitwise_and", other, site, ctx)

    def bitwise_or(self, other, site, ctx):
        return self._arithmetic("bitwise_or", other, site, ctx)

    def unary_minus(self, site):
        return self._downstream().unary_minus(site)

    def _arithmetic(self, method: str, other: FloorValue, site, ctx):
        return getattr(self._downstream(), method)(other, site, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        """Tuple-unpack of an opaque coordinate: ``a, b = opaque_call(…)``.

        SymbolicValue already projects via ``py.unpack(term, i)``; route
        opaque (or fold-computed) results through ``_downstream()`` so unpack
        never invents element values.
        """
        return self._downstream().project_sequence_with(operation, ctx)

    def next_with(self, operation: Any, ctx: Any) -> Any:
        """``next(opaque_iter)`` (e.g. ``next(df.itertuples(...))``).

        Folded receivers delegate; opaque mints ``call:next(self)`` with
        ``computed=None`` — never invent the first yielded element.
        """
        if self.computed is not None:
            return self.computed.next_with(operation, ctx)
        del ctx, operation
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            OpaqueOpCallsite(
                callee="next",
                arg=self,
                computed=None,
            )
        )

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().subscript_with(operation, ctx)


def is_concrete_floor_value(value: FloorValue) -> bool:
    """True when `value` is a statically folded construction the wrap can ground.

    SymbolicValue / OpaqueOpCallsite / ObjectValue / ArrayLiteral are not
    concrete — they do not supply a companion equality by themselves.
    """
    from .string_value import StringValue
    from .term_value import TermValue
    from .tuple_literal_value import TupleLiteralValue

    if isinstance(value, (TermValue, StringValue)):
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
        `computed=None` is the panic regression the witness corpus caught.
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
