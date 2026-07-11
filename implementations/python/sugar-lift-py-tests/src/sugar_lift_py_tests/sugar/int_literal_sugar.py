from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class IntLiteralSugar(Sugar, role=SugarRole.TERM):
    """An integer literal. Unlike a bool -- two values, two types -- an int has
    infinitely many values, so the value is a field. It reduces to a TermValue: the
    number as a term. (`type(...) is int` recognizes an int and not a bool, since bool
    is a subclass of int but `type(True)` is bool.)"""

    value: int
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "PrimitiveLiteral"
            and type(site.literal_value()) is int
        )

    @classmethod
    def new(cls, site, ctx) -> "IntLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(value=site.literal_value(), site=site)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="int_literal_return",
            owner_sugar="IntLiteralSugar",
            body="5",
            truthful="5",
            lying="6",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the number stands as a term
        return Complete(TermValue(self.value))
