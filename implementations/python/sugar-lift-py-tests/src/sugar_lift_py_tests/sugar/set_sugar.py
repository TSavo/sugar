from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SetLiteralValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import collection_len_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SetSugar(Sugar, role=SugarRole.TERM):
    elements: tuple[SugarBody, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(element, SugarBody) for element in self.elements):
            raise TypeError("SetSugar elements must be factory-built bodies")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Set"

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="SetLiteralValue",
                reason=(
                    "set literals are structural term support; set-constructor "
                    "equality is not currently a standalone solver verdict"
                ),
            ),
            collection_len_return_witness(
                name="set_literal_len_return",
                owner_sugar=cls.__name__,
                expression="{1, 1, 2}",
                truthful=2,
                lying=3,
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "SetSugar":
        if site.observed != "Set":
            raise TypeError("SetSugar claim built a non-set literal")
        return cls(
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.terms()
            )
        )

    def _build(self, ctx) -> Outcome:
        items: list[Term] = []
        for element in self.elements:
            outcome = element.reduce(ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            term = floor_to_term(
                complete_value(outcome, owner="SetSugar element"),
                owner="SetSugar element",
            )
            if term not in items:
                items.append(term)
        return Complete(SetLiteralValue(tuple(items)))
