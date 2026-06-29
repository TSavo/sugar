from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BlockValue(FloorValue):
    """The composed outcome of a block (a suite): the ordered outcomes of its
    statements, with Support (inert) statements absorbed. An empty block -- only
    comments -- is `BlockValue(())`. As Return/Assign/If statement sugars arrive,
    their outcomes carry here and the block becomes the body's universe."""

    statements: tuple[object, ...]
