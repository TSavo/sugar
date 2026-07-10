from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubtractOpSugar(Sugar, role=SugarRole.TERM):
    """The `-` operator. It reduces both sides and asks the left to subtract the
    right (the subtraction floor), which gives back a term. Its own sugar, its own
    type; the value owns the answer, no fork."""

    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "Sub"

    @classmethod
    def new(cls, site, ctx) -> "SubtractOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        # `-` folds concrete operands on the subtraction floor, and the equals fold
        # picks the if-face: the truthful twin rides the face `3 - 1 == 2` picked,
        # the lying twin asserts the other -- the pair proves the lift discriminates.
        prefix = (
            "def A(z):\n"
            "    if 3 - 1 == 2:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="subtract_return",
            owner_sugar="SubtractOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.subtract(right, self.blame)
            )
        )
