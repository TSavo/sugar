from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class MapOperation:
    parameter: str
    addend: int

    def map_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        return Complete(
            ArrayLiteral(
                tuple(TermValue(item.value + self.addend) for item in receiver.items)
            )
        )
