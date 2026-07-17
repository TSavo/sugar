from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class GroundSequenceRepetitionValue(FloorValue):
    """A ground Python sequence repetition without eager tuple expansion."""

    constructor_name: str
    elements: tuple
    repetitions: int

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, num

        return ctor(
            "*",
            [
                ctor(
                    self.constructor_name,
                    [element.to_term(owner=owner) for element in self.elements],
                ),
                num(self.repetitions),
            ],
        )

    def length(self, site):
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements) * max(self.repetitions, 0)))

    def truth(self, site):
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.elements and self.repetitions > 0
            else FalseBoolLiteralSugar(site=site)
        )
