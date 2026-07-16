from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class InequalityOpSugar(Sugar, role=SugarRole.TERM):
    """The `!=` operator. It is `not (a == b)`: it reduces both sides, asks the left
    whether it equals the right (the equals floor), and negates the resulting bool
    literal. Its own sugar, its own type; the negation is the literal negating itself,
    no fork."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["NotEq"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "InequalityOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.equals(right, self.site).and_then(
                    lambda equal: equal.negate()
                )
            )
        )

    def walk_children(self):
        return (self.left, self.right)
