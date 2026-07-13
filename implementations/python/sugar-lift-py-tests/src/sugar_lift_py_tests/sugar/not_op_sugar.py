from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NotOpSugar(Sugar, role=SugarRole.TERM):
    """Legacy `not` arm -- ownership moved to UnaryOpSugar (all four UnaryOp
    shapes: -/+/not/~). Kept registered only so comes_before edges remain
    valid; owns always returns False."""

    operand: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # UnaryOpSugar owns UnaryOp including Not -- do not double-claim.
        del site
        return False

    @classmethod
    def new(cls, site, ctx) -> "NotOpSugar":
        return cls(
            operand=ctx.build_body(site.unaryop_operand(), SugarRole.TERM),
            site=site,
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

    def walk_children(self):
        return (self.operand,)
