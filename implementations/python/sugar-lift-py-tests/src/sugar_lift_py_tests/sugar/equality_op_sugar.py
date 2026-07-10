from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class EqualityOpSugar(Sugar, role=SugarRole.TERM):
    """The `==` operator. One of the comparison family (`!=`, `<`, ... are their own
    sugars, their own types -- no operator field to switch on). It reduces both sides
    and asks the left whether it equals the right: the left stands on the equals floor
    and gives back a True or False literal."""

    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Compare"
            and site.compare_ops() == ["Eq"]
            and len(site.compare_comparators()) == 1
        )

    @classmethod
    def new(cls, site, ctx) -> "EqualityOpSugar":
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            blame=site.blame,
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
                lambda right: left.equals(right, self.blame)
            )
        )
