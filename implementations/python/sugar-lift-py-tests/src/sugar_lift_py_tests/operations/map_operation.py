from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value


@dataclass(frozen=True)
class MapOperation:
    method_name: ClassVar[str] = "map_with"
    mapper: Any
    owner: str = "MapSugar"
    blame: str = "<unknown>"

    def map_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        mapped = []
        for item in receiver.items:
            outcome = self.mapper.apply(item, ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            mapped.append(outcome)
        return Complete(ArrayLiteral(tuple(mapped)))

    def map_builder(self, receiver: BuilderState, ctx: object) -> Outcome:
        current = complete_value(receiver.current.map_with(self, ctx), owner=self.owner)
        if not isinstance(current, ArrayLiteral):
            raise TypeError("MapOperation over BuilderState must produce ArrayLiteral")
        return Complete(BuilderState(current))
