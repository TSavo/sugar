from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair
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
        prefix = "class C:\n" "    def __init__(self, x):\n" "        self.x = x\n" "\n"
        explicit_eq_prefix = (
            "class C:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "    def __eq__(self, other):\n"
            "        return self.x == other.x\n"
            "\n"
        )
        return (
            _call_return_pair(
                name="object_equality_identity_return",
                owner_sugar="ObjectEqualityTermSugar",
                body="C(z) == C(z)",
                truthful="False",
                lying="True",
                prefix=prefix,
            ),
            _call_return_pair(
                name="object_equality_return",
                owner_sugar="ObjectEqualityTermSugar",
                body="C(z) == C(z)",
                truthful="True",
                lying="False",
                prefix=explicit_eq_prefix,
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.equals(right, self.site).and_then(
                    lambda equal: equal.negate()
                )
            )
        )
