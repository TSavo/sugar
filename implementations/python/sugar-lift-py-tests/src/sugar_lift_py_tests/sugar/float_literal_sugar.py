from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


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
        return _call_return_pair(
            name="float_literal_return",
            owner_sugar="FloatLiteralSugar",
            body="2.5",
            truthful="2.5",
            lying="3.5",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the number stands as a term
        return Complete(TermValue(self.value))
