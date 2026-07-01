from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class TermValue(FloorValue):
    # The collapsed Number: an int OR a float. Int embeds in Real losslessly, so they are
    # one value type -- 3 and 3.0 are the same number, and 3.0 == 3 is reflexively true.
    # The Int/Real SMT sort is an emission-time inference, not a value-level split.
    value: int | float

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_term(self, ctx)
