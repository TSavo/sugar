"""A `for` loop, UNROLLED over a concrete iterable.

A loop is a fold; over a concrete iterable the fold has known length, so it
unrolls -- the loop projects its body once per element (the target
re-substituted), and the flattened body statements are just a block. This sugar
holds that already-unrolled statement sequence and reduces it like any block:
the loop class itself has dissolved, there is nothing loop-specific left to
reduce. (The symbolic fold -- carried variables as fold terms, the body as a
universal -- is a different, not-yet-written shape; this only ever holds a
concrete unroll.)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class ForSugar(Sugar):
    """The unrolled body: a flat tuple of statement sugars (the body reduced once
    per concrete element, target substituted), reduced as one block."""

    statements: tuple
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="for_unroll_return", owner_sugar="ForSugar",
            body="[x for x in [z]][0]" and "z", truthful="z", lying="0",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        entries, can_fall_through, fall_through = reduce_statements(self.statements)
        return Complete(
            BlockValue(entries, fall_through=fall_through, can_fall_through=can_fall_through)
        )
