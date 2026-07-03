from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BuilderState,
    ObjectValue,
    SymbolicValue,
    TermValue,
    TupleLiteralValue,
)
from sugar_lift_py_tests.outcome import Complete, Outcome

ArrayMaterial = (
    TermValue | ObjectValue | SymbolicValue | ArrayLiteral | TupleLiteralValue
)


@dataclass(frozen=True)
class MaterializeOperation:
    method_name: ClassVar[str] = "materialize_with"
    owner: str = "ToListSugar"
    blame: str = "<unknown>"

    def materialize_builder(self, receiver: BuilderState, ctx: object) -> Outcome:
        del ctx
        return Complete(receiver.current)

    def materialize_tuple(self, receiver: TupleLiteralValue, ctx: object) -> Outcome:
        del ctx
        return Complete(ArrayLiteral(_array_items(receiver)))


def _array_items(receiver: TupleLiteralValue) -> tuple[ArrayMaterial, ...]:
    items: list[ArrayMaterial] = []
    for item in receiver.items:
        if isinstance(
            item,
            (TermValue, ObjectValue, SymbolicValue, ArrayLiteral, TupleLiteralValue),
        ):
            items.append(item)
            continue
        raise TypeError(
            f"cannot materialize tuple item `{type(item).__name__}` as an array item"
        )
    return tuple(items)
