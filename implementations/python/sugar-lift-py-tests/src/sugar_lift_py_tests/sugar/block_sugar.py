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
                ctx.build_body(stmt, SugarRole.STATEMENT) for stmt in site.statements()
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
        entries, _final_ctx, can_fall_through, fall_through = self._collect_iterative(
            self.statements, ctx
        )
        return Complete(
            BlockValue(
                entries,
                fall_through=fall_through,
                can_fall_through=can_fall_through,
            )
        )

    def reduce_with_scope(self, ctx: object):
        """Reduce once, returning both the record and its terminal context."""
        statements, final_ctx, can_fall_through, fall_through = (
            self._collect_with_scope(self.statements, ctx)
        )
        return (
            BlockValue(
                statements,
                fall_through=fall_through,
                can_fall_through=can_fall_through,
            ),
            final_ctx,
        )

    def _collect_with_scope(self, statements: tuple, ctx: object):
        return self._collect_iterative(statements, ctx)

    def _collect(self, statements: tuple, ctx: object) -> tuple:
        entries, _final_ctx, _can_fall_through, _fall_through = self._collect_iterative(
            statements, ctx
        )
        return entries

    def _collect_iterative(self, statements: tuple, ctx: object):
        entries: list[object] = []
        transforms = []
        fall_through = []
        final_ctx = ctx
        can_fall_through = True

        for index, head in enumerate(statements):
            outcome = head.reduce(final_ctx)
            final_ctx = outcome.extend_scope(final_ctx)

            contribution = outcome.contribution()
            for transform in reversed(transforms):
                contribution = transform(contribution)
            entries.extend(contribution)

            follow = outcome.follow()
            if not follow.continues:
                can_fall_through = False
                tail = statements[index + 1 :] if follow.keeps_rest else ()
                for transform in reversed(transforms):
                    tail = transform(tail)
                entries.extend(tail)
                break
            if follow.transform is not None:
                transforms.append(follow.transform)
            if follow.continuation_guard is not None:
                fall_through.append(follow.continuation_guard)

        return (
            tuple(entries),
            final_ctx,
            can_fall_through,
            tuple(fall_through) if can_fall_through else (),
        )

    def walk_children(self):
        return self.statements

    def scope_after(self, ctx):
        """Thread only the temporal effects of this block in execution order."""
        for statement in self.statements:
            outcome = statement.reduce(ctx)
            ctx = outcome.extend_scope(ctx)
        return ctx
