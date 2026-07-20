from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class IntLiteralSugar(Sugar):
    """An integer literal. A leaf: it holds its value and no child sugars, and
    it desugars to the number as a term. (`bool` is a subclass of `int`, so the
    node that constructs this must have already distinguished `True`/`False` --
    a Constant whose value is exactly an `int`, not a `bool`.)"""

    value: int
    site: object = dataclass_field(compare=False)

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
