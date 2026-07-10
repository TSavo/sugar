from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NotOpSugar(Sugar, role=SugarRole.TERM):
    """The `not` operator. It reduces the operand and asks it to negate itself.
    The bool literal owns the flip; values that do not stand on the negate floor
    panic for free. Its own sugar, its own type; no fork."""

    operand: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "UnaryOp" and site.operator_kind() == "Not"

    @classmethod
    def new(cls, site, ctx) -> "NotOpSugar":
        return cls(
            operand=ctx.build_body(site.unaryop_operand(), SugarRole.TERM),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if not 1 == 2:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return SugarWitnessPair(
            name="not_return",
            owner_sugar="NotOpSugar",
            family="literal-call",
            truthful=WitnessSource(
                source=prefix + "def test_a():\n    assert A(5) == 5\n",
                expected="sat",
            ),
            lying=WitnessSource(
                source=prefix + "def test_a():\n    assert A(5) == 0\n",
                expected="unsat",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.operand.reduce(ctx).and_then(lambda value: value.negate())
