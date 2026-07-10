from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import string_literal_return_witness


@dataclass(frozen=True)
class StringLiteralSugar(Sugar, role=SugarRole.TERM):
    """A string literal. Infinitely many values, so the value is a field. It reduces
    to a StringValue: the string as a term. (`type(...) is str` recognizes a str.)"""

    value: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "PrimitiveLiteral"
            and type(site.literal_value()) is str
        )

    @classmethod
    def new(cls, site, ctx) -> "StringLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(value=site.literal_value(), blame=site.blame)

    @classmethod
    def witnesses(cls):
        return string_literal_return_witness()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the string stands as a term
        return Complete(StringValue(self.value))
