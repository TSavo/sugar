from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class BlockValue(FloorValue):
    """The composed outcome of a block (a suite): the ordered return outcomes of its
    statements (Support absorbed, lets threaded). `fall_through` is the guard under
    which execution leaves the block without returning -- it is `()` for an
    exhaustive block (every path returns) and `(not test,)` for a trailing
    `if test: return ...` with no else, so the ENCLOSING block guards later
    statements by it."""

    statements: tuple[object, ...]
    fall_through: tuple = ()

    def guard_with(self, operation: Any, ctx: Any) -> Any:
        return operation.guard_block(self, ctx)

    def route_raises_with(self, operation: Any, ctx: Any) -> Any:
        return operation.route_block_raises(self, ctx)

    def merge_finally_with(self, operation: Any, ctx: Any) -> Any:
        return operation.merge_finally_block(self, ctx)
