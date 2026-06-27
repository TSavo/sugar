from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ListLiteralSugar:
    node: ast.List
    elements: tuple[SugarBody, ...]

    @classmethod
    def from_site(cls, site, ctx) -> "ListLiteralSugar | None":
        if not isinstance(site.node, ast.List):
            return None
        return cls(
            node=site.node,
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.node.elts
            ),
        )

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


def _build(site, ctx) -> ListLiteralSugar:
    sugar = ListLiteralSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("ListLiteralSugar claim built a non-list literal")
    return sugar


LIST_LITERAL_CLAIM = SugarClaim(
    name="ListLiteralSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
