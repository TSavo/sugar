from __future__ import annotations

from dataclasses import dataclass

from .guard_stable_value import GuardStableValue


def _is_set_coordinate(term) -> bool:
    return getattr(term, "name", None) in {
        "py.setcomp",
        "py.set_difference",
        "py.set_union",
    }


@dataclass(frozen=True)
class ComprehensionValue(GuardStableValue):
    """A native comprehension coordinate with no invented cardinality.

    Finite literal comprehensions reduce to concrete collection floors. All
    other comprehensions retain their constructor term, but ``length`` stays on
    FloorValue's loud missing arm until cardinality semantics are constructed.
    ``finite_elements`` is present only when the comprehension owner projected
    every member of an exact finite iterable; ``None`` means no such testimony
    exists and must never be treated as an empty collection.
    """

    term: object
    finite_elements: tuple | None = None

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def project_sequence_with(self, operation, ctx):
        """`a, b = <comprehension>` -- the comprehension owns the cardinality.

        It answers from `finite_elements` when its owner projected every member
        of an exact finite iterable, and otherwise retains the arity demand. The
        operation reads the testimony; this face only routes to it.
        """
        return operation.project_comprehension(self, ctx)

    def contains(self, item, site):
        # Finite comprehension testimony folds like a list; otherwise membership
        # stays the py.in coordinate over the comprehension term.
        if self.finite_elements is not None:
            from sugar_lift_py_tests.floor.set_value import (
                _bool_result,
                _closed_member_equal,
            )

            decisions = tuple(
                _closed_member_equal(item, element) for element in self.finite_elements
            )
            if any(decision is True for decision in decisions):
                return _bool_result(True, site)
            if all(decision is False for decision in decisions):
                return _bool_result(False, site)
            if any(decision is None for decision in decisions):
                from sugar_lift_py_tests.floor.predicate_value import PredicateValue
                from sugar_lift_py_tests.ir import atomic
                from sugar_lift_py_tests.outcome import Complete

                return Complete(
                    PredicateValue(
                        atomic(
                            "py.in",
                            [
                                item.to_term(
                                    owner="ComprehensionValue.contains member"
                                ),
                                self.term,
                            ],
                        ),
                        site,
                        operand_callsites=(*item.callsites(),),
                    )
                )
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ComprehensionValue.contains",
                blame=str(site),
                observed=type(item).__name__,
                requested="constructed finite member or typed symbolic membership",
                fix="construct comprehension membership on the Python floor or keep it loud",
            )
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                atomic(
                    "py.in",
                    [
                        item.to_term(owner="ComprehensionValue.contains member"),
                        self.term,
                    ],
                ),
                site,
                operand_callsites=(*item.callsites(),),
            )
        )

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
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        if type(other) in (ComprehensionValue, ListValue):
            # Symbolic folds are constructed coordinates. Sequence concat of two
            # such coordinates is another coordinate (py.sequence_concat as `+`
            # ctor), not a RuntimeEffect that re-asks for a "genuine runtime
            # operand" while already holding the fold term.
            other_term = other.to_term(owner=str(site))
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
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

            return SymbolicValue(self.term).add(other, site)
        return super().add(other, site)

    def subtract(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if (
            type(other) is ComprehensionValue
            and _is_set_coordinate(self.term)
            and _is_set_coordinate(other.term)
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

    def bitwise_or(self, other, site):
        if (
            type(other) is ComprehensionValue
            and _is_set_coordinate(self.term)
            and _is_set_coordinate(other.term)
        ):
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                ComprehensionValue(ctor("py.set_union", [self.term, other.term]))
            )
        return super().bitwise_or(other, site)

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
