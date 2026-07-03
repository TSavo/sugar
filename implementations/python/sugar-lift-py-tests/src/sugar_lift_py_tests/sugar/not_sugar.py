from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, not_
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import not_assertion_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NotSugar(Sugar, role=SugarRole.ASSERTION):
    """A polarity marker.

    Python has both shapes:
      * `assert not <expr>` is a normal wrapper: build the child assertion body,
        then negate whatever it lowers to.
      * `x is not y` is not an outer `not` expression around `is`; it is a
        single comparison operator. In that shape this class is only a marker:
        the relation sugar owns the relation and calls `apply`.
    """

    source_role = "python.not-sugar"

    body: SugarBody | None = None

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        return test.observed == "UnaryOp" and test.operator_kind() == "Not"

    @classmethod
    def build(cls, site, ctx) -> "NotSugar":
        test = site.assert_test()
        operand_assert = site.assert_with_test(test.unaryop_operand())
        return cls(body=ctx.build_body(operand_assert, SugarRole.ASSERTION))

    @classmethod
    def witnesses(cls):
        return not_assertion_witness()

    def apply(self, formula: Formula) -> Formula:
        return not_(formula)

    def desugar(self, ctx) -> Formula:
        if self.body is None:
            raise TypeError("NotSugar polarity marker has no assertion body to desugar")
        return self.apply(self.body.reduce(ctx))
