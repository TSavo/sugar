from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
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
    site: object = dataclass_field(compare=False)

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
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    x = z\n    y = x\n    return y\n\n"
        return _call_pair(
            name="block_return",
            owner_sugar="BlockSugar",
            truthful=prefix + "def test_a():\n    assert A(2) == 2\n",
            lying=prefix + "def test_a():\n    assert A(2) == 3\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(BlockValue(self._collect(self.statements, ctx)))

    def _collect(self, statements: tuple, ctx: object) -> tuple:
        if not statements:
            return ()
        head, *rest = statements
        rest = tuple(rest)
        outcome = head.reduce(ctx)
        # The outcome owns what joins the record (floor value, or itself if incomplete),
        # whether the rest reduces, and what scope the rest reduces under (a BoundVar
        # extends; Support and ordinary values leave the scope alone).
        next_ctx = outcome.extend_scope(ctx)
        return (
            *outcome.contribution(),
            *outcome.follow(rest, lambda more: self._collect(more, next_ctx)),
        )

    def walk_children(self):
        return self.statements

    def scope_after(self, ctx):
        """Thread only the temporal effects of this block in execution order."""
        for statement in self.statements:
            outcome = statement.reduce(ctx)
            ctx = outcome.extend_scope(ctx)
        return ctx
