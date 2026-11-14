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
    the lift can fold; it is `None` when any argument is opaque. The value is
    carried, never substituted for the coordinate: emission reads `computed`
    for the Derived companion `call:<op>(...) == <value>`. Downstream
    arithmetic/format delegates to `_downstream()` so a computed value
    participates in `+` without the coordinate collapsing at the comparison
    boundary.

    `callee` spells the coordinate's symbol only.  What the operator IS (the
    behaviour the language fixes for it) is `language_callee`, the
    `LanguageCallee` member its minting site decided: `str.join` over an
    opaque iterable (`StringValue`'s method fold) is `STR_JOIN`, and
    `str.split` by an opaque separator is `STR_SPLIT`.  A reader asks
    `language_callee`, never the spelling (#7757).
    """

    callee: str
    arg: FloorValue
    computed: FloorValue | None = None
    # Additional operands (e.g. a method's further arguments). Primary arg
    # stays `arg` so single-operand sites stay a one-field construction.
    extra_args: tuple[FloorValue, ...] = ()
    # The ``LanguageCallee`` the minting site decided this operator is, else
    # None (an operator no reader dispatches on).
    language_callee: object | None = None

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

        Folded receivers delegate; an opaque one re-dispatches on its symbolic
        downstream, whose ``next`` is the one two-faced unanswered outcome
        (``FloorValue.undecided_next``) -- never a completion that cannot
        raise, never an invented first element.
        """
        return self._downstream().next_with(operation, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return self._downstream().subscript_with(operation, ctx)

    def append_with(self, value, site):
        """``.append(v)`` on a ``str.split`` result: the ``py.list_append`` rebind.

        ``str.split`` always returns a new ``list``; ``StringValue``'s method
        fold marks the coordinate it mints for an opaque separator with
        ``LanguageCallee.STR_SPLIT``.  That marker, never the spelling
        ``split``, makes this value list-shaped (#7757).  Its elements are not
        known, so the append carries the prior coordinate and the value on
        ``py.list_append``.  Any other operator coordinate does not stand on
        the append floor and stays loud.
        """
        if self.stands_on_append_floor():
            from sugar_lift_py_tests.floor.call_site_value import (
                list_append_coordinate_value,
            )
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(list_append_coordinate_value(self, value, site))
        return super().append_with(value, site)

    def stands_on_append_floor(self) -> bool:
        """Only the ``STR_SPLIT`` coordinate is list-shaped (its marker).

        ``GuardedValue.append_with`` asks this before mapping an append over
        a face, so every other operator coordinate keeps the guarded append's
        runtime boundary exactly as before this door answered ``str.split``.
        """
        from sugar_source_tree.nodes import LanguageCallee

        return self.language_callee is LanguageCallee.STR_SPLIT
