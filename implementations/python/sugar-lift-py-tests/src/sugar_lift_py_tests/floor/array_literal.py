from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue
from .tuple_literal_value import TupleLiteralValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    # Each item is a scalar, a nested array, or a tuple literal.
    items: tuple["TermValue | ArrayLiteral | TupleLiteralValue", ...]

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_array(self, ctx)

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return operation.contains_array(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_array(self, ctx)
