from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula, not_


@dataclass(frozen=True)
class NotSugar:
    """A polarity marker.

    Python's `is not` is not an outer `not` expression around `is`; it is a single
    comparison operator. This sugar does not own the relation. It marks the relation
    sugar so the relation owner can negate its own formula.
    """

    source_role = "python.not-sugar"

    def apply(self, formula: Formula) -> Formula:
        return not_(formula)
