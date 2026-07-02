from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class TupleLiteralValue(FloorValue):
    items: tuple[FloorValue, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(item, FloorValue) for item in self.items):
            raise TypeError("TupleLiteralValue items must be floor values")

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("tuple", [item.to_term(owner=owner) for item in self.items])

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_tuple(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_tuple(self, ctx)

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)
