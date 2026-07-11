from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class TupleValue(FloorValue):
    """A tuple of reduced floor values, in construction order.

    The sugar reduces each element; the floor holds what those reductions were.
    No methods beyond the dataclass -- floors this tuple does not implement panic
    for free via FloorValue defaults.
    """

    elements: tuple

    def to_term(self, *, owner: str):
        # Project each element; vendor digs return tuples (sign/unsign pairs,
        # return_timestamp) that must enter FOL for assert equality.
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "tuple",
            [elt.to_term(owner=owner) for elt in self.elements],
        )

    def truth(self, site):
        # A tuple's truth is nonempty.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.elements
            else FalseBoolLiteralSugar(site=site)
        )

    def length(self, site):
        # A tuple knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements)))

    def subscript(self, index, site):
        # Concrete tuple + in-range TermValue int folds to the element; out of
        # range is IndexError. Non-concrete index stays the py.subscript coordinate.
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(index) is TermValue and type(index.value) is int:
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                return Complete(self.elements[i])
            from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect

            return Incomplete(
                IndexErrorRuntimeEffect(
                    f"tuple index out of range runtime boundary: "
                    f"index={i} length={n}; owner=TupleValue.subscript site={site}"
                )
            )
        return self.py_subscript_coordinate(index, site)
