from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ComprehensionValue(FloorValue):
    """A native comprehension coordinate with no invented cardinality.

    Finite literal comprehensions reduce to concrete collection floors. All
    other comprehensions retain their constructor term, but ``length`` stays on
    FloorValue's loud missing arm until cardinality semantics are constructed.
    """

    term: object

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def truth(self, site):
        """Opaque comprehensions stand as conditions via ``py.truthy``.

        Finite literal comprehensions fold to concrete collection floors before
        truth is asked. A residual comprehension keeps its constructor term and
        emits the same truthy atom as other opaque coordinates — never invent
        emptiness, never panic for a lawful ``if history:`` face.
        """
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(py_truthy(self.term), site, operand_callsites=())
        )

    def append_with(self, value, site):
        """Construct the post-state of a list comprehension append.

        The comprehension's members may be runtime-derived, but its container
        kind and Python append semantics are already known. Preserve the prior
        list coordinate and appended value without inventing either history or
        cardinality.
        """
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        return Complete(
            ComprehensionValue(
                ctor(
                    "py.list_append",
                    [
                        self.term,
                        floor_to_term(
                            value, owner="ComprehensionValue.append_with value"
                        ),
                    ],
                    symbol_kind="method-coordinate",
                )
            )
        )

    def add(self, other, site):
        from sugar_lift_py_tests.effect import (
            SequenceConcatenationRuntimeEffect,
            is_lift_time_decidable,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(other) in (ComprehensionValue, ListValue):
            other_term = other.to_term(owner=str(site))
            if is_lift_time_decidable(self.term) and is_lift_time_decidable(other_term):
                return Complete(
                    ComprehensionValue(
                        ctor(
                            "+",
                            [
                                self.term,
                                other_term,
                            ],
                        )
                    )
                )
            return Incomplete(
                SequenceConcatenationRuntimeEffect(
                    "sequence concatenation depends on runtime comprehension "
                    f"members; owner=ComprehensionValue.add site={site}",
                    **runtime_effect_evidence(
                        "py.sequence_concat",
                        self if not is_lift_time_decidable(self.term) else other,
                        site,
                    ),
                )
            )
        return super().add(other, site)

    def subtract(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if (
            type(other) is ComprehensionValue
            and getattr(self.term, "name", None) == "py.setcomp"
            and getattr(other.term, "name", None) == "py.setcomp"
        ):
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                ComprehensionValue(ctor("py.set_difference", [self.term, other.term]))
            )
        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.effect import runtime_subtract

            return runtime_subtract(self, other, site)
        return super().subtract(other, site)

    def multiply(self, other, site):
        """Preserve repetition when the count is a constructed Python integer."""
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        if (
            getattr(self.term, "name", None) == "py.listcomp"
            and type(other) is TermValue
            and type(other.value) is int
        ):
            return SymbolicValue(self.term).multiply(other, site)
        return super().multiply(other, site)

    def subscript(self, index, site):
        # A runtime comprehension still has Python collection semantics, but
        # neither its members nor its cardinality are available at lift time.
        # Preserve the real lookup as a proof-bearing coordinate; do not invent
        # an element or silently assume the lookup succeeds.
        return self.py_subscript_coordinate(index, site)

    def setitem(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, index, value, site
    ):
        """Carry the exact post-state of a name-bound comprehension store."""
        from typing import cast

        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import Term, ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        index_term = floor_to_term(index, owner="ComprehensionValue.setitem index")
        value_term = floor_to_term(value, owner="ComprehensionValue.setitem value")
        return Complete(
            CallSiteValue(
                target_name="setitem",
                arg_values=(self, index, value),
                parameters=(),
                term=ctor(
                    "py.setitem",
                    [
                        cast(Term, self.to_term(owner=str(site))),
                        index_term,
                        value_term,
                    ],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )
