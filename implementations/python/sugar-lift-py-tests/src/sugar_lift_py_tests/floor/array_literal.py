from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .object_value import ObjectValue
from .string_value import StringValue
from .symbolic_value import SymbolicValue
from .term_value import TermValue
from .tuple_literal_value import TupleLiteralValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    # Each item is a scalar, object, symbolic parameter, nested array, or tuple literal.
    items: tuple[
        "TermValue | ObjectValue | StringValue | SymbolicValue | ArrayLiteral | TupleLiteralValue",
        ...,
    ]

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("array", [item.to_term(owner=owner) for item in self.items])

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return operation.subscript_array(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_array(self, ctx)

    def multiply(self, other, site, ctx):
        # Array repetition, through the one sequence-repetition law -- the same
        # law list and tuple were consolidated onto (#6060). This arm kept a
        # private copy that PANICKED above a static cap; the cap was abolished
        # there and the array was the straggler, still reaching for the deleted
        # `sugar.for_sugar` cap and raising ImportError instead of repeating.
        from sugar_lift_py_tests.floor.sequence_repetition import repeat_sequence

        return repeat_sequence(
            self, other, site, elements=self.items, rebuild=ArrayLiteral
        )
