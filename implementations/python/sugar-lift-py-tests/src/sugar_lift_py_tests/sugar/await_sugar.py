from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.operations import AwaitOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair
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
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="await_runtime_effect",
            owner_sugar=cls.__name__,
            source="async def A(z):\n    return await z\n",
            effect_class="FactoryGap",
            reason_needle="owner=AwaitSugar",
            blame_needle="test_witness.py:2:11",
            wrong_reason_needle="owner=StarredSugar",
        )

    @classmethod
    def build(cls, site, ctx) -> "AwaitSugar":
        if site.observed != "Await":
            raise TypeError("AwaitSugar claim built a non-await expression")
        return cls(
            awaitable=ctx.build_body(site.await_value(), SugarRole.TERM),
            blame=site.blame,
        )

    def _build(self, ctx) -> Outcome:
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
