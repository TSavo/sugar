from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MultiplyOpSugar(Sugar, role=SugarRole.TERM):
    """The `*` operator. It reduces both sides and asks the left to multiply by the
    right (the multiplication floor). Its own sugar, its own type; the value owns the
    product, no fork."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "Mult"

    @classmethod
    def new(cls, site, ctx) -> "MultiplyOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `*` folds concrete numbers on the multiplication floor; the product feeds
        # `==`, and the True/False literal picks the if-face: the truthful twin rides
        # the face the product comparison picked, the lying twin asserts the other --
        # the pair proves the lift discriminates on the product.
        prefix = (
            "def A(z):\n"
            "    if 2 * 3 == 6:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="multiply_return",
            owner_sugar="MultiplyOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.multiply(right, self.site)
            )
        )
