from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.operations import AwaitOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AwaitSugar(Sugar, role=SugarRole.TERM):
    awaitable: SugarBody
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.awaitable, SugarBody):
            raise TypeError("AwaitSugar awaitable must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Await"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason="await unwrapping is async runtime support without a sync verdict path",
        )

    @classmethod
    def build(cls, site, ctx) -> "AwaitSugar":
        if site.observed != "Await":
            raise TypeError("AwaitSugar claim built a non-await expression")
        return cls(
            awaitable=ctx.build_body(site.await_value(), SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        awaitable_outcome = self.awaitable.reduce(ctx)
        if isinstance(awaitable_outcome, Incomplete):
            return awaitable_outcome
        awaitable = force_floor(
            complete_value(awaitable_outcome, owner="AwaitSugar awaitable"),
            ctx,
            owner="AwaitSugar awaitable",
        )
        return perform_operation(
            owner="AwaitSugar",
            blame=self.blame,
            receiver=awaitable,
            operation=AwaitOperation(
                owner="AwaitSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
