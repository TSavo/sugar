from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ReturnSugar(Sugar, role=SugarRole.STATEMENT):
    """A `return <value>` statement. Its child is the value expression -- built by
    the factory at the TERM role and handed in. Desugaring reduces that value and
    wraps it in a ReturnValue: the path's returned outcome."""

    value: SugarBody

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Return"

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return SugarWitnessPair(
            name="literal_call_return",
            owner_sugar=cls.__name__,
            family="literal-call",
            truthful=WitnessSource(
                source=(
                    "def A(x):\n"
                    "    return x + 1\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A(5) == 6\n"
                ),
                expected="sat",
            ),
            lying=WitnessSource(
                source=(
                    "def A(x):\n"
                    "    return x + 1\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A(5) == 7\n"
                ),
                expected="unsat",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "ReturnSugar":
        if site.observed != "Return":
            raise TypeError("ReturnSugar claim built a non-return")
        value_site = site.return_value()
        if value_site is None:
            raise TypeError("ReturnSugar requires a return value")
        return cls(value=ctx.build_body(value_site, SugarRole.TERM))

    def desugar(self, ctx) -> Outcome:
        # match the returned expression: an Incomplete (its evaluation raises) bubbles
        # upward unchanged -- there is no value to return.
        outcome = self.value.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        return Complete(ReturnValue(complete_value(outcome, owner="return value")))
