from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.floor.sequence_constructor import SequenceConstructor
from sugar_lift_py_tests.operations.perform_operation import perform_operation
from sugar_lift_py_tests.operations.sequence_construction_operation import (
    SequenceConstructionOperation,
)
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ListLiteralSugar(Sugar, role=SugarRole.TERM):
    elements: tuple[SugarBody, ...]
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not all(isinstance(element, SugarBody) for element in self.elements):
            raise TypeError("ListLiteralSugar elements must be factory-built bodies")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "List"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "default-catalog list literals are verdict-bearing through "
                "ArrayLiteralSugar; this fallback constructor is shadowed support"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "ListLiteralSugar":
        sugar = cls.from_site(
            site,
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.terms()
            ),
            blame=site.blame,
        )
        if sugar is None:
            raise TypeError("ListLiteralSugar claim built a non-list literal")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, elements: tuple[SugarBody, ...], blame: str | None = None
    ) -> "ListLiteralSugar | None":
        if site.observed != "List":
            return None
        return cls(elements=elements, blame=blame or site.blame)

    def desugar(self, ctx) -> Outcome:
        items: list[FloorValue] = []
        for element in self.elements:
            value = complete_value(element.reduce(ctx), owner="ListLiteralSugar")
            items.append(value)
        return perform_operation(
            owner="ListLiteralSugar",
            blame=self.blame,
            receiver=SequenceConstructor("list"),
            operation=SequenceConstructionOperation(
                elements=tuple(items),
                owner="ListLiteralSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

LIST_LITERAL_CLAIM = next(c for c in _rc() if c.name == "ListLiteralSugar")
