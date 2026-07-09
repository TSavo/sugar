from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .array_literal import ArrayLiteral
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuilderState(FloorValue):
    current: ArrayLiteral

    def to_term(self, *, owner: str):
        # A builder is a stateful array construction; the coordinate for
        # `len(Builder([...]))` projects as the underlying array term.
        return self.current.to_term(owner=owner)

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_builder(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_builder(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        return self.current.call_method_with(operation, ctx)

    def materialize_with(self, operation: Any, ctx: Any) -> Any:
        return operation.materialize_builder(self, ctx)
