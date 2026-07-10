from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IfSugar(Sugar, role=SugarRole.STATEMENT):
    """`if` is a condition and one or two bodies. `elif` is an `IfSugar` nested in
    the else. It reduces with no fork of its own: the condition floors to bool, and
    the standing (True/False) or the effect owns the binary conditional -- True
    emits the then-face, False emits the else-face (or nothing), an effect returns
    itself. The sugar owns the two emit faces (its bodies); the standing owns the
    decision. See floor/bool_floor.py."""

    condition: SugarBody
    then: SugarBody
    else_body: SugarBody | None
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "If"

    @classmethod
    def new(cls, site, ctx) -> "IfSugar":
        # The condition, the then-block, and the else-block (if present) are all
        # factory-built sugars. `elif` needs no special case: Python parses it as a
        # lone `If` inside the else-block, so building that block yields a nested
        # IfSugar -- a tower of sugar falls out of ordinary construction.
        blocks = site.statements()
        return cls(
            condition=ctx.build_body(site.if_test(), SugarRole.TERM),
            then=ctx.build_body(blocks[0], SugarRole.STATEMENT),
            else_body=(
                ctx.build_body(blocks[1], SugarRole.STATEMENT)
                if len(blocks) > 1
                else None
            ),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n" "    if z == 1:\n" "        return 7\n" "    return 0\n" "\n"
        return _call_pair(
            name="if_return",
            owner_sugar="IfSugar",
            truthful=prefix + "def test_a():\n    assert A(1) == 7\n",
            lying=prefix + "def test_a():\n    assert A(1) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.condition.reduce(ctx).binary_conditional(
            self.then, self.else_body, ctx
        )
