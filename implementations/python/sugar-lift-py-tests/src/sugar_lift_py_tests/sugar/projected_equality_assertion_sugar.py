from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, eq
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


@dataclass(frozen=True)
class ProjectedEqualityAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.projected-equality-assertion-sugar"

    left: Term
    right: Term

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Compare":
            return False
        if test.compare_ops() != ["Eq"]:
            return False
        if len(test.compare_comparators()) != 1:
            return False
        left = test.compare_left()
        right = test.compare_comparators()[0]
        if left.observed not in {"Attribute", "Subscript"}:
            return False
        return can_symbolic_term(left) and can_symbolic_term(right)

    @classmethod
    def build(cls, site, ctx) -> "ProjectedEqualityAssertionSugar":
        del ctx
        test = site.assert_test()
        return cls(
            left=symbolic_term(test.compare_left(), owner="projected equality left"),
            right=symbolic_term(
                test.compare_comparators()[0],
                owner="projected equality right",
            ),
        )

    def assertion_formula(self) -> Formula:
        return eq(self.left, self.right)

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()
