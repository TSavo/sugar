from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import NoneValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource


@dataclass(frozen=True)
class NoneLiteralSugar(Sugar, role=SugarRole.TERM):
    """The literal `None`. It holds no value -- the None-ness IS the type. It
    reduces to a NoneValue: None as a term."""

    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "PrimitiveLiteral" and site.literal_value() is None

    @classmethod
    def new(cls, site, ctx) -> "NoneLiteralSugar":
        del ctx  # a literal is a leaf: no children
        return cls(blame=site.blame)

    @classmethod
    def witnesses(cls):
        # `None == None` folds True and picks the if-face: the truthful twin rides
        # that face, the lying twin asserts the other -- the pair discriminates.
        prefix = (
            "def A(z):\n"
            "    if None == None:\n"
            "        return z\n"
            "    return 0\n"
            "\n"
        )
        return SugarWitnessPair(
            name="none_literal_return",
            owner_sugar="NoneLiteralSugar",
            family="literal-call",
            truthful=WitnessSource(
                source=prefix + "def test_a():\n    assert A(5) == 5\n",
                expected="sat",
            ),
            lying=WitnessSource(
                source=prefix + "def test_a():\n    assert A(5) == 0\n",
                expected="unsat",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the None-ness stands as a term
        return Complete(NoneValue())
