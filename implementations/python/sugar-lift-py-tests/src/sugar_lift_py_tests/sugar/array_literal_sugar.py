from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_array_literal_sugar
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ArrayLiteralSugar:
    elements: tuple[SugarBody, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(element, SugarBody) for element in self.elements):
            raise TypeError("ArrayLiteralSugar elements must be factory-built bodies")

    @classmethod
    def from_site(
        cls, site, *, elements: tuple[SugarBody, ...]
    ) -> "ArrayLiteralSugar | None":
        if not isinstance(site.node, ast.List):
            return None
        return cls(elements=elements)

    def desugar(self, ctx=None) -> Outcome:
        return Complete(
            ArrayLiteral(
                tuple(
                    _term_value(
                        complete_value(element.reduce(ctx), owner="ArrayLiteralSugar")
                    )
                    for element in self.elements
                )
            )
        )


def _term_value(value) -> TermValue:
    if not isinstance(value, TermValue):
        raise TypeError("ArrayLiteralSugar elements must desugar to TermValue")
    return value


def _owns(site) -> bool:
    return isinstance(site.node, ast.List)


ARRAY_LITERAL_CLAIM = SugarClaim(
    name="ArrayLiteralSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_array_literal_sugar,
)
