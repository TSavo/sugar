from __future__ import annotations

from dataclasses import dataclass

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
