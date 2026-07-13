from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import OSExitRuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class OsSugar(Sugar, role=SugarRole.TERM):
    """`os.exit(...)` halts the program at runtime. It is a runtime effect: its value
    does not exist until the program runs, so it reduces to an Incomplete, not a fact.
    The effect is atomic at reduce time, but the arguments are factory-built like any
    other child -- an unowned node inside them panics at construction."""

    args: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call" and site.call_qualified_target_name() == "os.exit"
        )

    @classmethod
    def new(cls, site, ctx) -> "OsSugar":
        # The arguments are factory-built (audited), never reduced here.
        return cls(
            args=tuple(ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()),
            site=site,
        )

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
        from sugar_lift_py_tests.effect import runtime_effect_witness
        from sugar_lift_py_tests.ir import ctor

        def effect(operand) -> Outcome:
            return Incomplete(
                OSExitRuntimeEffect(
                    f"OS exit runtime boundary: os.exit halts the program at runtime; "
                    f"owner=OsSugar site={self.site}",
                    witness=runtime_effect_witness("py.os_exit", operand, self.site),
                )
            )

        if not self.args:
            return effect(ctor("py.none", []))
        return self.args[0].reduce(ctx).and_then(effect)

    def walk_children(self):
        return self.args
