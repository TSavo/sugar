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

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_tuple(self, ctx)
