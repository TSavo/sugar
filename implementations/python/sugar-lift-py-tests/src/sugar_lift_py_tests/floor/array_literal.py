from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    # Each item is a scalar (TermValue) or a nested array (ArrayLiteral).
    items: tuple["TermValue | ArrayLiteral", ...]

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_array(self, ctx)

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return operation.contains_array(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_array(self, ctx)
