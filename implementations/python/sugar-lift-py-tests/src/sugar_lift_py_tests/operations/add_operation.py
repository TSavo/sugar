from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value


@dataclass(frozen=True)
class AddOperation:
    operand: TermValue
    owner: str = "AddSugar"
    blame: str = "<unknown>"

    def add_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        return Complete(
            ArrayLiteral(
                tuple(
                    TermValue(item.value + self.operand.value) for item in receiver.items
                )
            )
        )

    def add_builder(self, receiver: BuilderState, ctx: object) -> Outcome:
        current = complete_value(receiver.current.add_with(self, ctx), owner=self.owner)
        if not isinstance(current, ArrayLiteral):
            raise TypeError("AddOperation over BuilderState must produce ArrayLiteral")
        return Complete(BuilderState(current))
