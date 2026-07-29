from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class LoopControlSugar(Sugar):
    action: str
    target_cid: str
    occurrence_cid: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None):
        from sugar_lift_py_tests.outcome.exit_set import _construct_nonraise_halted
        effect = LoopControlEffect(self.action, self.target_cid, self.occurrence_cid)
        face = _construct_nonraise_halted(
            "loop_control_sugar", self.site, effect, ctx, effect.occurrence_cid,
            true_guard(), frozenset(), ()
        )
        return ExitSet((face,)).normalize()
