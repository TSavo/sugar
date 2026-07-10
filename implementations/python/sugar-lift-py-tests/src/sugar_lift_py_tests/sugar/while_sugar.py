# SPDX-License-Identifier: MIT OR Apache-2.0
"""While loop is a typed runtime boundary (sibling of ForSugar).

`while test: body [else: …]` evaluates a condition, optionally runs the body
(and break/continue control), and may fall through an else. That iterator-
free control protocol is not yet a floor; the honest outcome is a typed
RuntimeEffect Incomplete — not a silent SupportValue and not a fabricated
loop unrolling.

Lift-probe (before): empty STATEMENT catalog candidates for While →
FactoryGap `create sugar_lift_py_tests.sugar.while.while_sugar`.
Mechanism: missing AST recognizer (not a floor totalizer).
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


@dataclass(frozen=True)
class WhileSugar(Sugar, role=SugarRole.STATEMENT):
    """`while` statement → typed RuntimeEffect (condition/body protocol boundary)."""

    blame: str
    has_else: bool

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "While"

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="while_runtime_effect",
            owner_sugar=cls.__name__,
            source=(
                "def A(z):\n"
                "    x = z\n"
                "    while x:\n"
                "        x = 0\n"
                "    return x\n"
            ),
            effect_class="RuntimeEffect",
            reason_needle="while loop runtime boundary",
            blame_needle="test_witness.py:3:4",
            wrong_reason_needle="for loop runtime boundary",
        )

    @classmethod
    def build(cls, site, ctx) -> "WhileSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("WhileSugar claim built a non-while statement")
        return cls(
            blame=site.blame,
            has_else=site.while_orelse_count() != 0,
        )

    def _build(self, ctx) -> Outcome:
        del ctx
        else_note = " with else/fallthrough" if self.has_else else ""
        return Incomplete(
            RuntimeEffect(
                "while loop runtime boundary: Python evaluates the condition, "
                f"loop body effects{else_note}, break/continue, and fallthrough "
                "at runtime; keep as typed red until condition/body floors own "
                f"this shape. blame={self.blame}"
            )
        )
