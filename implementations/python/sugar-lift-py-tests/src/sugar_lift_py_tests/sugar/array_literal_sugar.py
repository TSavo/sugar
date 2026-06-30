from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ArrayLiteralSugar(Sugar, role=SugarRole.TERM, comes_before=("ListLiteralSugar",)):
    # When both own a `[...]` fragment, ArrayLiteralSugar wins in any catalog that has
    # both; a catalog with only ListLiteralSugar still selects it (no competitor).
    elements: tuple[SugarBody, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(element, SugarBody) for element in self.elements):
            raise TypeError("ArrayLiteralSugar elements must be factory-built bodies")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "List"

    @classmethod
    def build(cls, site, ctx) -> "ArrayLiteralSugar":
        sugar = cls.from_site(
            site,
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.terms()
            ),
        )
        if sugar is None:
            raise TypeError("ArrayLiteralSugar claim built a non-array literal")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, elements: tuple[SugarBody, ...]
    ) -> "ArrayLiteralSugar | None":
        if site.observed != "List":
            return None
        return cls(elements=elements)

    def desugar(self, ctx=None) -> Outcome:
        return Complete(
            ArrayLiteral(
                tuple(
                    _array_element(
                        complete_value(element.reduce(ctx), owner="ArrayLiteralSugar")
                    )
                    for element in self.elements
                )
            )
        )


def _array_element(value):
    if not isinstance(value, (TermValue, ArrayLiteral)):
        raise TypeError(
            "ArrayLiteralSugar elements must desugar to a scalar or a nested array"
        )
    return value


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402
ARRAY_LITERAL_CLAIM = next(c for c in _rc() if c.name == "ArrayLiteralSugar")
