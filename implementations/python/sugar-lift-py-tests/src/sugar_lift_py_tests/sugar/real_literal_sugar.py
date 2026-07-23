from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class RealLiteralSugar(Sugar):
    """A float literal. Like IntLiteralSugar, it stands as a TermValue -- but a
    float carries the Real sort (int -> Int, float -> Real; there is no Number
    sort). A leaf: no child sugars."""

    value: float
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="real_literal_return",
            owner_sugar="RealLiteralSugar",
            body="2.5",
            truthful="2.5",
            lying="2.6",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(TermValue(self.value))
