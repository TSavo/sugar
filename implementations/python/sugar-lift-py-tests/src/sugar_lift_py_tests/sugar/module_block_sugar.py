from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.function_universe_sugar import (
    _ReducedBlock,
    block_values,
    reduce_block_to_exitset,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class ModuleBlockSugar(Sugar):
    """The already-constructed statements of one source module, in order."""

    statements: tuple[Sugar, ...]
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="BlockValue",
            reason="module blocks project the ordinary constructed block",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.run(ctx)[0]

    def run(self, ctx: object = None) -> tuple:
        """``(outcome, ends)``: the module body's one run.

        ``outcome`` is what ``desugar`` answers (the ordinary block,
        ``reduce_body``).  ``ends`` is the reducer context each completed arm
        of the run ended with, in arm order: the module-end state, the one
        source of the value of each module-final binding a function called
        after import reads (``tree_enumerate.module_end_contexts``).  A
        halted arm ends no import, so it has no end here.  A run still
        waiting on a caller's actuals (a deferred native operation) has no
        end either.
        """
        exits = reduce_block_to_exitset(self.statements, ctx)
        ends = tuple(
            exit_.value.context
            for exit_ in (exits.exits if isinstance(exits, ExitSet) else ())
            if isinstance(exit_, Completed)
            and isinstance(exit_.value, _ReducedBlock)
            and exit_.value.context is not None
        )
        return block_values(exits), ends
