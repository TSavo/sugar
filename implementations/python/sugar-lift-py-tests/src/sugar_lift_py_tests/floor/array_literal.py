from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    items: tuple[TermValue, ...]

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)
