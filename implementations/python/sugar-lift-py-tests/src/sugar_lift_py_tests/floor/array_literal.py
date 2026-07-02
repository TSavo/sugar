from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .object_value import ObjectValue
from .term_value import TermValue
from .tuple_literal_value import TupleLiteralValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    # Each item is a scalar, object, nested array, or a tuple literal.
    items: tuple["TermValue | ObjectValue | ArrayLiteral | TupleLiteralValue", ...]

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("array", [item.to_term(owner=owner) for item in self.items])

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_array(self, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_array(self, ctx)

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return operation.contains_array(self, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return operation.subscript_array(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_array(self, ctx)
