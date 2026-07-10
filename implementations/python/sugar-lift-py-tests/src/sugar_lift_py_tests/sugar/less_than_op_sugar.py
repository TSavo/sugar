from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class LessThanOpSugar(Sugar, role=SugarRole.TERM):
    """The `<` operator. It reduces both sides and asks the left whether it is less
    than the right (the ordering floor), which gives back a True/False literal.
    Its own sugar, its own type; the value owns the answer, no fork."""

    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["Lt"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "LessThanOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        # `<` folds concrete operands to the True/False literal, and the literal picks
        # the if-face: the truthful twin rides the face `<` picked, the lying twin
        # asserts the other -- the pair proves the lift discriminates on order.
        prefix = (
            "def A(z):\n" "    if 1 < 2:\n" "        return z\n" "    return 0\n" "\n"
        )
        return _call_pair(
            name="less_than_return",
            owner_sugar="LessThanOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.less_than(right, self.blame)
            )
        )
