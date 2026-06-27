from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_list_literal_sugar
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ListLiteralSugar:
    elements: tuple[SugarBody, ...]

    @classmethod
    def from_site(
        cls, site, *, elements: tuple[SugarBody, ...]
    ) -> "ListLiteralSugar | None":
        if not isinstance(site.node, ast.List):
            return None
        return cls(elements=elements)

    def desugar(self, ctx) -> Outcome:
        items: list[TermValue] = []
        for element in self.elements:
            value = complete_value(element.reduce(ctx), owner="ListLiteralSugar")
            if not isinstance(value, TermValue):
                raise TypeError("ListLiteralSugar elements must reduce to TermValue")
            items.append(value)
        return Complete(ArrayLiteral(tuple(items)))


def _owns(site) -> bool:
    return isinstance(site.node, ast.List)


LIST_LITERAL_CLAIM = SugarClaim(
    name="ListLiteralSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_list_literal_sugar,
)
