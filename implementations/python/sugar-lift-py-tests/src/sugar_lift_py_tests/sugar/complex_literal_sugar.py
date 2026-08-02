from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.complex_value import ComplexValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class ComplexLiteralSugar(ConstructedTermSugar):
    """A `complex` literal (e.g. `2j`). A leaf: it holds its real/imaginary
    parts and no child sugars, and it desugars to the ComplexValue floor --
    which stands as the vendor-canonical ``py.complex(<real>, <imag>)`` term
    already consumed downstream (verifier structural ground-ctor whitelist
    #4398, isinstance fold table).

    ConstructedTermSugar: a complex literal IS nested-construction testimony
    (same law as IntLiteralSugar / NoneLiteralSugar). Slots that require
    ConstructedTermSugar were never wrong about the meaning — this class was
    missing the base that admits it.
    """

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

    def to_term(self, *, owner: str):
        from decimal import Decimal

        from sugar_lift_py_tests.ir import ctor, real_lit

        # Same canonical-decimal-string discipline as ComplexValue.to_term /
        # TermValue.to_term: never hash a Python float's non-deterministic text.
        real_term = real_lit(format(Decimal(str(self.real)), "f"))
        imag_term = real_lit(format(Decimal(str(self.imag)), "f"))
        return ctor(
            "python:complex-literal-construction",
            (
                self.occurrence_term(owner=owner),
                ctor("py.complex", [real_term, imag_term]),
            ),
            symbol_kind="coordinate",
        )
