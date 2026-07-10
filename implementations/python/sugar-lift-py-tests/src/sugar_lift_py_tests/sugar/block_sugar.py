from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import block_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BlockSugar(Sugar, role=SugarRole.STATEMENT):
    """A block is its statements. `desugar` reduces them in order into a record:

        (Complete, Complete, ..., Incomplete, <unresolved sugar>, <unresolved sugar>...)

    It reduces up to the first effect, which halts the run; everything past the halt is
    unreachable, so it is kept exactly as it is -- raw, unreduced sugar. The block owns
    no distinction and never branches: the outcome owns whether the run continues (a
    Complete reduces the rest) or stops (an Incomplete leaves the rest unresolved)."""

    statements: tuple[SugarBody, ...]
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Block"

    @classmethod
    def new(cls, site, ctx) -> "BlockSugar":
        # Each statement is a factory-built sugar (nesting is blocks within blocks).
        return cls(
            statements=tuple(
                ctx.build_body(stmt, SugarRole.STATEMENT)
                for stmt in site.statements()
            ),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        return block_return_witness()

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(BlockValue(self._collect(self.statements, ctx)))

    def _collect(self, statements: tuple, ctx: object) -> tuple:
        if not statements:
            return ()
        head, *rest = statements
        rest = tuple(rest)
        outcome = head.reduce(ctx)
        # The outcome owns what joins the record (floor value, or itself if incomplete)
        # and whether the rest reduces. Support contributes nothing and is absorbed.
        return (
            *outcome.contribution(),
            *outcome.follow(rest, lambda more: self._collect(more, ctx)),
        )
