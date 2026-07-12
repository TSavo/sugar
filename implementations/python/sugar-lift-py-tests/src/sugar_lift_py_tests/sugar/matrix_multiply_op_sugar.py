from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MatrixMultiplyOpSugar(Sugar, role=SugarRole.TERM):
    """The native Python ``@`` operator dispatched through its floor."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "MatMult"

    @classmethod
    def new(cls, site, ctx) -> "MatrixMultiplyOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(x, y):\n    return x @ y\n\n"
        return _call_pair(
            name="matrix_multiply_return",
            owner_sugar="MatrixMultiplyOpSugar",
            truthful=prefix + "def test_a():\n    assert A(2, 3) == 6\n",
            lying=prefix + "def test_a():\n    assert A(2, 3) == 7\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.matrix_multiply(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
