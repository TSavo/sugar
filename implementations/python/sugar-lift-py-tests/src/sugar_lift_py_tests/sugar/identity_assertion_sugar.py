from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, identity
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


@dataclass(frozen=True)
class IdentityAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.identity-assertion-sugar"

    left: Term
    right: Term

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Compare":
            return False
        if test.compare_ops() != ["Is"]:
            return False
        if len(test.compare_comparators()) != 1:
            return False
        return can_symbolic_term(test.compare_left()) and can_symbolic_term(
            test.compare_comparators()[0]
        )

    @classmethod
    def build(cls, site, ctx) -> "IdentityAssertionSugar":
        del ctx
        test = site.assert_test()
        return cls(
            left=symbolic_term(test.compare_left(), owner="identity assertion left"),
            right=symbolic_term(
                test.compare_comparators()[0],
                owner="identity assertion right",
            ),
        )

    def assertion_formula(self) -> Formula:
        return identity(self.left, self.right)

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()
