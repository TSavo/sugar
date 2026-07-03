from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, eq
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import (
    projected_equality_assertion_witness,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ProjectedEqualityAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.projected-equality-assertion-sugar"

    left: SugarBody
    right: SugarBody

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
        return left.observed in {"Attribute", "Subscript"}

    @classmethod
    def build(cls, site, ctx) -> "ProjectedEqualityAssertionSugar":
        test = site.assert_test()
        return cls(
            left=ctx.build_body(test.compare_left(), SugarRole.TERM),
            right=ctx.build_body(test.compare_comparators()[0], SugarRole.TERM),
        )

    @classmethod
    def witnesses(cls):
        return projected_equality_assertion_witness()

    def assertion_formula(self, ctx) -> Formula:
        return eq(
            floor_to_term(
                complete_value(self.left.reduce(ctx), owner="projected equality left"),
                owner="projected equality left",
            ),
            floor_to_term(
                complete_value(
                    self.right.reduce(ctx), owner="projected equality right"
                ),
                owner="projected equality right",
            ),
        )

    def desugar(self, ctx):
        return self.assertion_formula(ctx)
