from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class FunctionCallable(FloorValue):
    name: str
    parameter: str
    return_name: str

    def apply(self, value: TermValue) -> TermValue:
        if self.return_name != self.parameter:
            raise ValueError(
                f"write more Callable floor for `{self.name}`: return `{self.return_name}`"
            )
        return value
