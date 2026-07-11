from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ReturnSugar(Sugar, role=SugarRole.STATEMENT):
    """The `return <expr>` statement. It reduces the value, and the result is a
    return of it: a ReturnValue carrying the reduced floor. A block carries that
    ReturnValue. Bare `return` is not this sugar -- no invented None."""

    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Own only `return <expr>`; bare return stays a loud factory gap.
        return site.observed == "Return" and site.return_value() is not None

    @classmethod
    def new(cls, site, ctx) -> "ReturnSugar":
        return cls(
            value=ctx.build_body(site.return_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # `return <expr>` reduces the value and wraps it in a ReturnValue; the truthful
        # twin asserts the returned face, the lying twin asserts another -- the pair
        # proves the lift discriminates on the returned value.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="return_value",
            owner_sugar="ReturnSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda value: Complete(ReturnValue(value))
        )
