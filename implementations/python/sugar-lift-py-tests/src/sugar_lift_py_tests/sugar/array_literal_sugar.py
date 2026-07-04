from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
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
    def witnesses(cls) -> SugarWitnessPair:
        return _map_method_witness(
            name="array_literal_map_method",
            owner_sugar=cls.__name__,
        )

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
        items = []
        for element in self.elements:
            element_outcome = element.reduce(ctx)
            if isinstance(element_outcome, Incomplete):
                return element_outcome
            items.append(
                _array_element(
                    complete_value(element_outcome, owner="ArrayLiteralSugar"),
                    element=element,
                )
            )
        return Complete(
            ArrayLiteral(tuple(items))
        )


def _array_element(value, *, element: SugarBody):
    if not isinstance(
        value,
        (
            TermValue,
            BoolValue,
            ObjectValue,
            StringValue,
            SymbolicValue,
            ArrayLiteral,
            TupleLiteralValue,
        ),
    ):
        blame = _element_blame(element)
        info = FactoryGapInfo(
            owner="ArrayLiteralSugar",
            blame=blame,
            observed=type(value).__name__,
            requested="array element floor",
            fix=f"add ArrayLiteral element floor for {type(value).__name__}",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="array element floor",
                status="floor-gap",
                observed=info.observed,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
    return value


def _element_blame(element: SugarBody) -> str:
    row = getattr(element, "audit_row", None)
    blame = getattr(row, "blame", None)
    return blame or "<array element>"


def _map_method_witness(*, name: str, owner_sugar: str) -> SugarWitnessPair:
    return SugarWitnessPair(
        name=name,
        owner_sugar=owner_sugar,
        family="array-map",
        truthful=WitnessSource(
            source=(
                "def test_array_map_sugar():\n"
                "    assert [1, 2, 3].map(lambda x: x + 1) == [2, 3, 4]\n"
            ),
            expected="sat",
        ),
        lying=WitnessSource(
            source=(
                "def test_array_map_sugar():\n"
                "    assert [1, 2, 3].map(lambda x: x + 1) == [2, 3, 99]\n"
            ),
            expected="unsat",
        ),
    )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

ARRAY_LITERAL_CLAIM = next(c for c in _rc() if c.name == "ArrayLiteralSugar")
