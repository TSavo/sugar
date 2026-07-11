from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class GreaterEqualOpSugar(Sugar, role=SugarRole.TERM):
    """The `>=` operator. It is `not (a < b)`: the ordering floor, and the resulting bool
    literal negates itself. Its own sugar, its own type; the value owns the answer, no fork."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["GtE"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "GreaterEqualOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `>=` is `not (a < b)`: folds concrete operands to the True/False literal, and
        # the literal picks the if-face: the truthful twin rides the face `>=` picked,
        # the lying twin asserts the other -- the pair proves the lift discriminates
        # on order.
        prefix = (
            "def A(z):\n" "    if 2 >= 2:\n" "        return z\n" "    return 0\n" "\n"
        )
        return _call_pair(
            name="greater_equal_return",
            owner_sugar="GreaterEqualOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.less_than(right, self.site).and_then(
                    lambda less: less.negate()
                )
            )
        )

    def walk_children(self):
        return (self.left, self.right)
