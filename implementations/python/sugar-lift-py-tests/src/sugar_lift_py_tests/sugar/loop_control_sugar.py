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
        """``break``/``continue``: a halt whose state is a record, as every
        halt of a block's is.  Nothing ran inside the statement before it, so
        the record holds no entries of its own; the block composition that
        runs it splices what ran ahead of it onto the record
        (``function_universe_sugar._prefixed``), and an ``if`` its
        condition's testimony (``if_sugar``), so the loop it leaves leaves
        with what the item did (``LoopRecurrenceSugar._after_loop_control``).
        The record's context is the one the statement received at its
        source occurrence, which the loop authenticates
        (``LoopRecurrenceSugar._require_loop_control_state``)."""
        from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record

        return ExitSet.halted(
            LoopControlEffect(self.action, self.target_cid, self.occurrence_cid),
            state=halt_record(ctx),
        )
