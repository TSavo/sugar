from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import OSExitRuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


@dataclass(frozen=True)
class OsSugar(Sugar, role=SugarRole.TERM):
    """`os.exit(...)` halts the program at runtime. It is a runtime effect: its value
    does not exist until the program runs, so it reduces to an Incomplete, not a fact.
    It owns the whole call and does not lift the argument -- the effect is atomic."""

    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_qualified_target_name() == "os.exit"
        )

    @classmethod
    def new(cls, site, ctx) -> "OsSugar":
        del ctx  # a runtime effect: the argument is not lifted
        return cls(blame=site.blame)

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="os_exit_runtime_effect",
            owner_sugar=cls.__name__,
            source="def A(z):\n    return os.exit(0)\n",
            effect_class="OSExitRuntimeEffect",
            reason_needle="OS exit",
            blame_needle="test_witness.py:2:11",
            wrong_reason_needle="owner=AwaitSugar",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Incomplete(
            OSExitRuntimeEffect(
                f"OS exit runtime boundary: os.exit halts the program at runtime; "
                f"owner=OsSugar blame={self.blame}"
            )
        )
