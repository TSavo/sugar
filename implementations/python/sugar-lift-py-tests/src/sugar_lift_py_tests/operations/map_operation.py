from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value


@dataclass(frozen=True)
class MapOperation:
    mapper: Any
    owner: str = "MapSugar"
    blame: str = "<unknown>"

    def map_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        return Complete(
            ArrayLiteral(tuple(self.mapper.apply(item, ctx) for item in receiver.items))
        )

    def map_builder(self, receiver: BuilderState, ctx: object) -> Outcome:
        current = complete_value(receiver.current.map_with(self, ctx), owner=self.owner)
        if not isinstance(current, ArrayLiteral):
            raise TypeError("MapOperation over BuilderState must produce ArrayLiteral")
        return Complete(BuilderState(current))
