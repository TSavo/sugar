from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import (
    BlockValue,
    BoundVar,
    RaiseValue,
    ReturnValue,
    SupportValue,
)
from sugar_lift_py_tests.operations import ControlFlowGuardOperation, perform_operation
from sugar_lift_py_tests.outcome import (
    Complete,
    Incomplete,
    Outcome,
    complete_value,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import block_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal


@dataclass(frozen=True)
class BlockFold:
    outcome: Outcome
    ctx: Any


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
    blame: str
    effect_consumer_reason = (
        "folds statement effects through block control-flow composition"
    )

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Block"

    @classmethod
    def witnesses(cls):
        return block_return_witness()

    @classmethod
    def build(cls, site, ctx) -> "BlockSugar":
        if site.observed != "Block":
            raise TypeError("BlockSugar claim built a non-block")
        return cls(
            statements=tuple(
                ctx.build_body(stmt, SugarRole.STATEMENT) for stmt in site.statements()
            ),
            blame=site.blame,
        )

    def _desugar_with_effects(self, ctx) -> Outcome:
        return self.fold_with_context(ctx).outcome

    def _build(self, ctx, **complete_operands) -> Outcome:
        del ctx, complete_operands
        raise AssertionError("BlockSugar reduces through _desugar_with_effects")

    def fold_with_context(self, ctx) -> BlockFold:
        outcomes: list[object] = []
        pending: tuple = ()  # guards accumulated from prior fall-through ifs
        for child in self.statements:
            outcome = child.reduce(ctx)
            if isinstance(outcome, Incomplete):
                # A statement raised (an effect). Execution halts: every statement after
                # it is unreachable, so we do NO further work -- no outcomes, no pending
                # guards -- and bubble the Incomplete upward unchanged.
                return BlockFold(outcome, ctx)
            value = complete_value(outcome, owner="block statement")
            if isinstance(value, SupportValue):
                continue  # Support (a comment) is inert -- absorbed
            if isinstance(value, BoundVar):
                ctx = bind_temporal(
                    ctx,
                    value.name,
                    value,
                    owner="BlockSugar",
                    blame=self.blame,
                )
                continue
            if isinstance(value, ReturnValue):
                outcomes.append(_guard_exit(value, pending, ctx, self.blame))
                return BlockFold(Complete(BlockValue(tuple(outcomes))), ctx)
            if isinstance(value, RaiseValue):
                outcomes.append(_guard_exit(value, pending, ctx, self.blame))
                return BlockFold(Complete(BlockValue(tuple(outcomes))), ctx)
            if isinstance(value, BlockValue):
                exit_emitted = False
                for statement in value.statements:
                    if isinstance(statement, BoundVar):
                        ctx = bind_temporal(
                            ctx,
                            statement.name,
                            statement,
                            owner="BlockSugar",
                            blame=self.blame,
                        )
                        continue
                    exit_emitted = True
                    outcomes.append(_guard_exit(statement, pending, ctx, self.blame))
                if exit_emitted and not value.fall_through:
                    return BlockFold(Complete(BlockValue(tuple(outcomes))), ctx)
                pending = pending + value.fall_through
                continue
            outcomes.append(value)
        return BlockFold(Complete(BlockValue(tuple(outcomes), pending)), ctx)


def _guard_exit(statement: object, guards: tuple, ctx, blame: str):
    if not guards:
        return statement
    guarded = complete_value(
        perform_operation(
            owner="BlockSugar",
            blame=blame,
            receiver=BlockValue((statement,)),
            operation=ControlFlowGuardOperation(
                guards,
                owner="BlockSugar",
                blame=blame,
            ),
            ctx=ctx,
        ),
        owner="block guarded exit",
    )
    if not isinstance(guarded, BlockValue):
        raise TypeError("BlockSugar guard dispatch must return a block")
    if len(guarded.statements) != 1:
        raise TypeError("BlockSugar guard dispatch must preserve one exit")
    return guarded.statements[0]
