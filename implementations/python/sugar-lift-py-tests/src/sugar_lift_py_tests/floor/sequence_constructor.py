from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class SequenceConstructor(FloorValue):
    kind: str

    def construct_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.construct_sequence(self, ctx)
