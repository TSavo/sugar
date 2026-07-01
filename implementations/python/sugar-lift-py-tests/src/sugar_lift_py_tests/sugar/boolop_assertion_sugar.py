from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, and_, or_
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BoolOpAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.boolop-assertion-sugar"

    operator: str
    values: tuple[SugarBody, ...]

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        return test.observed == "BoolOp" and test.boolop_op_kind() in {"and", "or"}

    @classmethod
    def build(cls, site, ctx) -> "BoolOpAssertionSugar":
        test = site.assert_test()
        return cls(
            operator=test.boolop_op_kind(),
            values=tuple(
                ctx.build_body(site.assert_with_test(value), SugarRole.ASSERTION)
                for value in test.boolop_values()
            ),
        )

    def desugar(self, ctx) -> Formula:
        formulas = [value.reduce(ctx) for value in self.values]
        if self.operator == "and":
            return and_(formulas)
        if self.operator == "or":
            return or_(formulas)
        raise TypeError(
            f"write more Sugar for BoolOpAssertionSugar `{self.operator}`: "
            "add assertion connective lowering"
        )
