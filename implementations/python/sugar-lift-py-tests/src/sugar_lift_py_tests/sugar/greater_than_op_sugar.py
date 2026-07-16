from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class GreaterThanOpSugar(Sugar, role=SugarRole.TERM):
    """The faithful Python `>` operator, resolved per atom by operand warrants."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["Gt"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "GreaterThanOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Concrete operands fold to the True/False literal, and the literal picks
        # the if-face. The truthful twin
        # rides the face `>` picked, the lying twin asserts the other -- the pair
        # proves the lift discriminates on order.
        prefix = (
            "def A(z):\n" "    if 2 > 1:\n" "        return z\n" "    return 0\n" "\n"
        )
        return _call_pair(
            name="greater_than_return",
            owner_sugar="GreaterThanOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.greater_than(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
