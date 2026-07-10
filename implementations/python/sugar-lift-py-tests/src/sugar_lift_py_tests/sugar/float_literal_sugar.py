from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import float_literal_return_witness


@dataclass(frozen=True)
class FloatLiteralSugar(Sugar, role=SugarRole.TERM):
    """A float literal. Same collapsed Number as an int literal -- 3 and 3.0 are
    the same number -- so it reduces to a TermValue: the number as a term. Two
    literal syntaxes, one floor; Int/Real is emission-time sort inference."""

    value: float
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "PrimitiveLiteral"
            and type(site.literal_value()) is float
        )

    @classmethod
    def new(cls, site, ctx) -> "FloatLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(value=site.literal_value(), blame=site.blame)

    @classmethod
    def witnesses(cls):
        return float_literal_return_witness()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the number stands as a term
        return Complete(TermValue(self.value))
