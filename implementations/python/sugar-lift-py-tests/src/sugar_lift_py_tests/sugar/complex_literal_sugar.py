from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.complex_value import ComplexValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class ComplexLiteralSugar(Sugar):
    """A `complex` literal (e.g. `2j`). A leaf: it holds its real/imaginary
    parts and no child sugars, and it desugars to the ComplexValue floor --
    which stands as the vendor-canonical ``py.complex(<real>, <imag>)`` term
    already consumed downstream (verifier structural ground-ctor whitelist
    #4398, isinstance fold table)."""

    real: float
    imag: float
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="complex_literal_return",
            owner_sugar="ComplexLiteralSugar",
            body="2j",
            truthful="2j",
            lying="3j",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the complex value stands as a floor value
        return Complete(ComplexValue(self.real, self.imag))
