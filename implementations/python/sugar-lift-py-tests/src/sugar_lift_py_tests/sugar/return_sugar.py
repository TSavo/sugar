from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
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
    def build(cls, site, ctx) -> "ReturnSugar":
        if site.observed != "Return":
            raise TypeError("ReturnSugar claim built a non-return")
        value_site = site.return_value()
        if value_site is None:
            raise TypeError("ReturnSugar requires a return value")
        return cls(value=ctx.build_body(value_site, SugarRole.TERM))

    def desugar(self, ctx) -> Outcome:
        returned = complete_value(self.value.reduce(ctx), owner="return value")
        return Complete(ReturnValue(returned))
