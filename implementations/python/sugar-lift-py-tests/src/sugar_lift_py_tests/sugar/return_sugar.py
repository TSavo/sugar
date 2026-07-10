from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import return_value_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ReturnSugar(Sugar, role=SugarRole.STATEMENT):
    """The `return <expr>` statement. It reduces the value, and the result is a
    return of it: a ReturnValue carrying the reduced floor. A block carries that
    ReturnValue. Bare `return` is not this sugar -- no invented None."""

    value: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        # Own only `return <expr>`; bare return stays a loud factory gap.
        return site.observed == "Return" and site.return_value() is not None

    @classmethod
    def new(cls, site, ctx) -> "ReturnSugar":
        return cls(
            value=ctx.build_body(site.return_value(), SugarRole.TERM),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        return return_value_witness()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda value: Complete(ReturnValue(value))
        )
