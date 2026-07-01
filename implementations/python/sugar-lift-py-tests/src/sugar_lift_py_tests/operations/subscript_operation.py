from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import (
    Bv32Value,
    EncodedStringValue,
    FloorValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


@dataclass(frozen=True)
class SubscriptOperation:
    index: FloorValue
    owner: str = "StringSubscriptSugar"
    blame: str = "<unknown>"

    def subscript_string(self, receiver: StringValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            EncodedStringValue(
                table=tuple(ord(ch) for ch in receiver.value),
                indices=(_string_index_term(self.index),),
            )
        )

    def subscript_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            SymbolicValue(
                ctor(
                    "py.subscript",
                    [
                        receiver.term,
                        floor_to_term(self.index, owner=f"{self.owner} index"),
                    ],
                )
            )
        )


def _string_index_term(value: FloorValue):
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, TermValue):
        return num(value.value)
    raise TypeError(
        f"write more Floor for StringSubscriptSugar index `{type(value).__name__}`: "
        "expected TermValue or Bv32Value"
    )
