from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import (
    BlockValue,
    BoundVar,
    GuardedReturn,
    ReturnValue,
    SupportValue,
)
from sugar_lift_py_tests.outcome import (
    Complete,
    Incomplete,
    Outcome,
    complete_value,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BlockSugar(Sugar, role=SugarRole.STATEMENT):
    """The composer for a block (a Python suite).

    Its children are the block's statements, each already dispatched to its own sugar
    by `owns` (CommentSugar, and Return/Assign/If as they arrive) -- the same way an
    expression sugar holds its operand sub-bodies. Desugaring composes them inside-out
    and absorbs the Support (inert) ones; the remaining statement outcomes ARE the
    block's value. There is no walk and no dispatch loop -- it is composition.
    """

    statements: tuple[SugarBody, ...]

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Block"

    @classmethod
    def build(cls, site, ctx) -> "BlockSugar":
        if site.observed != "Block":
            raise TypeError("BlockSugar claim built a non-block")
        return cls(
            statements=tuple(
                ctx.build_body(stmt, SugarRole.STATEMENT) for stmt in site.statements()
            )
        )

    def desugar(self, ctx) -> Outcome:
        outcomes: list[object] = []
        pending: tuple = ()  # guards accumulated from prior fall-through ifs
        for child in self.statements:
            outcome = child.reduce(ctx)
            if isinstance(outcome, Incomplete):
                # A statement raised (an effect). Execution halts: every statement after
                # it is unreachable, so we do NO further work -- no outcomes, no pending
                # guards -- and bubble the Incomplete upward unchanged.
                return outcome
            value = complete_value(outcome, owner="block statement")
            if isinstance(value, SupportValue):
                continue  # Support (a comment) is inert -- absorbed
            if isinstance(value, BoundVar):
                ctx = replace(ctx, temporal=ctx.temporal.bind_value(value.name, value))
                continue
            if isinstance(value, ReturnValue):
                outcomes.append(
                    GuardedReturn(pending, value.value) if pending else value
                )
                continue
            if isinstance(value, BlockValue):
                for statement in value.statements:
                    if isinstance(statement, BoundVar):
                        ctx = replace(
                            ctx,
                            temporal=ctx.temporal.bind_value(statement.name, statement),
                        )
                        continue
                    if isinstance(statement, ReturnValue):
                        outcomes.append(
                            GuardedReturn(pending, statement.value)
                            if pending
                            else statement
                        )
                        continue
                    outcomes.append(
                        GuardedReturn(pending + statement.guards, statement.value)
                    )
                pending = pending + value.fall_through
                continue
            outcomes.append(value)
        return Complete(BlockValue(tuple(outcomes), pending))
