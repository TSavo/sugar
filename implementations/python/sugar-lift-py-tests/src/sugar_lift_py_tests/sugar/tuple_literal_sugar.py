from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleLiteralSugar(Sugar, role=SugarRole.TERM):
    elements: tuple[SugarBody, ...]

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Tuple"

    @classmethod
    def build(cls, site, ctx) -> "TupleLiteralSugar":
        return cls(
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.terms()
            )
        )

    def desugar(self, ctx) -> Outcome:
        terms = [
            floor_to_term(
                complete_value(element.reduce(ctx), owner="TupleLiteralSugar element"),
                owner="TupleLiteralSugar",
            )
            for element in self.elements
        ]
        return Complete(SymbolicValue(ctor("tuple", terms)))
