from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ModuloOpSugar(Sugar, role=SugarRole.TERM):
    """The `%` operator. It reduces both sides and asks the left for the remainder
    by the right (the modulo floor). Numbers fold; a concrete zero divisor is a
    runtime effect. Its own sugar, its own type; the value owns the answer, no
    fork."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "Mod"

    @classmethod
    def new(cls, site, ctx) -> "ModuloOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Concrete `7 % 3 == 1` folds on the modulo floor; the True/False face
        # picks the if-face. The truthful twin rides that face, the lying twin
        # asserts the other -- the pair proves the lift discriminates on the remainder.
        prefix = (
            "def A(z):\n"
            "    if 7 % 3 == 1:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="modulo_return",
            owner_sugar="ModuloOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.modulo(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
