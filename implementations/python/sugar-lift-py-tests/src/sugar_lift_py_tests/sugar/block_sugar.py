from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_block_sugar
from sugar_lift_py_tests.floor import (
    BlockValue,
    BoundVar,
    GuardedReturn,
    ReturnValue,
    SupportValue,
)
# (BlockValue is also an if's outcome -- the guarded returns of its branches.)
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BlockSugar:
    """The composer for a block (a Python suite).

    Its children are the block's statements, each already dispatched to its own sugar
    by `owns` (CommentSugar, and Return/Assign/If as they arrive) -- the same way an
    expression sugar holds its operand sub-bodies. Desugaring composes them inside-out
    and absorbs the Support (inert) ones; the remaining statement outcomes ARE the
    block's value. There is no walk and no dispatch loop -- it is composition.
    """

    statements: tuple[SugarBody, ...]

    def desugar(self, ctx) -> Outcome:
        outcomes: list[object] = []
        pending: tuple = ()  # guards accumulated from prior fall-through ifs
        for child in self.statements:
            value = complete_value(child.reduce(ctx), owner="block statement")
            if isinstance(value, SupportValue):
                continue  # Support (a comment) is inert -- absorbed
            if isinstance(value, BoundVar):
                # an assignment: thread the bound var into scope so LATER statements
                # resolve the name. The BoundVar itself is bound (not its collapsed
                # value), keeping the aliased source recoverable.
                ctx = replace(
                    ctx, temporal=ctx.temporal.bind_value(value.name, value)
                )
                continue
            if isinstance(value, ReturnValue):
                # a return is live only if every prior fall-through guard held.
                outcomes.append(
                    GuardedReturn(pending, value.value) if pending else value
                )
                continue
            if isinstance(value, BlockValue):
                # an `if`: its guarded returns flatten in (under any pending guards),
                # and its fall-through (a no-else if) extends the pending guards for
                # the statements that come after it.
                for gr in value.statements:
                    outcomes.append(GuardedReturn(pending + gr.guards, gr.value))
                pending = pending + value.fall_through
                continue
            outcomes.append(value)
        return Complete(BlockValue(tuple(outcomes), pending))


def _owns(site) -> bool:
    return site.observed == "Block"


BLOCK_CLAIM = SugarClaim(
    name="BlockSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_block_sugar,
)
