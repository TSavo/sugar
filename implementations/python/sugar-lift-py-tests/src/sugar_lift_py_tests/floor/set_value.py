from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SetValue(FloorValue):
    """A set of reduced floor values, in construction order.

    The sugar reduces each element; the floor holds what those reductions were.
    No methods beyond the dataclass -- floors this set does not implement panic
    for free via FloorValue defaults.
    """

    elements: tuple

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:set",
            [element.to_term(owner=owner) for element in self.elements],
        )

    def truth(self, site):
        # A set's truth is nonempty.
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
        # A set knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements)))

    def subtract(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                SetValue(
                    tuple(
                        element
                        for element in self.elements
                        if element not in other.elements
                    )
                )
            )
        return super().subtract(other, site)

    def bitwise_or(self, other, site):
        if type(other) is SetValue:
            del site
            from sugar_lift_py_tests.outcome import Complete

            elements = list(self.elements)
            elements.extend(
                element for element in other.elements if element not in elements
            )
            return Complete(SetValue(tuple(elements)))
        return super().bitwise_or(other, site)
