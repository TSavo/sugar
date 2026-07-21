"""A statement that states nothing -- an inert contribution to the block.

A pure-fold `for` (only carried assignments) has no fact of its own: its meaning
rode into the tail as the fold binding (substitution_binding), consumed where the
carried name is read. So the loop node itself contributes an empty record."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class InertSugar(Sugar):
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue

        return Complete(BlockValue((), can_fall_through=True))
