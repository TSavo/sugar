from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class PredicateValue(FloorValue):
    formula: Formula

    def negate(self):
        # A predicate flips by wrapping its formula in not_ -- the formula owns
        # the polarity, the carrier stays PredicateValue.
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(not_(self.formula)))

