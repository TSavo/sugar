from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ListLiteralSugar(Sugar, role=SugarRole.TERM):
    elements: tuple[SugarBody, ...]

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "List"

    @classmethod
    def build(cls, site, ctx) -> "ListLiteralSugar":
        sugar = cls.from_site(
            site,
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.terms()
            ),
        )
        if sugar is None:
            raise TypeError("ListLiteralSugar claim built a non-list literal")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, elements: tuple[SugarBody, ...]
    ) -> "ListLiteralSugar | None":
        if site.observed != "List":
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


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402
LIST_LITERAL_CLAIM = next(c for c in _rc() if c.name == "ListLiteralSugar")
