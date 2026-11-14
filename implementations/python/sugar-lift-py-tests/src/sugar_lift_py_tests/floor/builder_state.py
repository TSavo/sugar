from __future__ import annotations

from dataclasses import dataclass

from .array_literal import ArrayLiteral
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuilderState(FloorValue):
    current: ArrayLiteral

    def to_term(self, *, owner: str):
        # A builder is a stateful array construction; the coordinate for
        # `len(Builder([...]))` projects as the underlying array term.
        return self.current.to_term(owner=owner)
