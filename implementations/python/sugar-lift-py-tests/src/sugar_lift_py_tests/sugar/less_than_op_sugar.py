from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import less_than_return_witness
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
        return less_than_return_witness()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.less_than(right, self.blame)
            )
        )
