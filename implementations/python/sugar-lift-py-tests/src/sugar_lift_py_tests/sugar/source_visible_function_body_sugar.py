from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.function_universe_sugar import (
    block_values,
    reduce_block_to_exitset,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class SourceVisibleFunctionBodySugar(Sugar):
    """Already-constructed statement Sugars for one source-visible call frame.

    What a call of the frame does to objects its caller shares is never read
    off this body (#7757 steps 5 and 6: a same-file call is its coordinate
    and edge, joined at prove; the caller's objects take the one exposure
    rule).  The body reduces to the ordinary constructed block."""

    statements: tuple[object, ...]
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="BlockValue",
            reason="call-frame bodies project the ordinary constructed block",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        return block_values(reduce_block_to_exitset(self.statements, ctx))
