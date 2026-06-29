from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.sugar_constructors import build_block_sugar
from sugar_lift_py_tests.floor import BlockValue, SupportValue
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
        for child in self.statements:
            value = complete_value(child.reduce(ctx), owner="block statement")
            if isinstance(value, SupportValue):
                continue  # Support is inert -- absorbed, contributes nothing
            outcomes.append(value)
        return Complete(BlockValue(tuple(outcomes)))


def _owns(site) -> bool:
    return isinstance(site.node, Block)


BLOCK_CLAIM = SugarClaim(
    name="BlockSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_block_sugar,
)
