from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value

from .primitive_literal_sugar import PrimitiveLiteralSugar


@dataclass(frozen=True)
class ArrayLiteralSugar:
    node: ast.List
    elements: tuple[PrimitiveLiteralSugar, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(element, PrimitiveLiteralSugar) for element in self.elements):
            raise TypeError("ArrayLiteralSugar elements must be PrimitiveLiteralSugar")

    @classmethod
    def from_site(cls, site, ctx) -> "ArrayLiteralSugar | None":
        if not isinstance(site.node, ast.List):
            return None
        elements: list[PrimitiveLiteralSugar] = []
        for item in site.node.elts:
            child = ctx.build_child(item, SugarRole.TERM).sugar
            if not isinstance(child, PrimitiveLiteralSugar):
                raise TypeError(
                    "ArrayLiteralSugar elements must be PrimitiveLiteralSugar"
                )
            elements.append(child)
        return cls(node=site.node, elements=tuple(elements))

    def desugar(self) -> Outcome:
        return Complete(
            ArrayLiteral(
                tuple(
                    _term_value(complete_value(element.desugar(), owner="ArrayLiteralSugar"))
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


def _build(site, ctx) -> ArrayLiteralSugar:
    sugar = ArrayLiteralSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("ArrayLiteralSugar claim built a non-array literal")
    return sugar


ARRAY_LITERAL_CLAIM = SugarClaim(
    name="ArrayLiteralSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
