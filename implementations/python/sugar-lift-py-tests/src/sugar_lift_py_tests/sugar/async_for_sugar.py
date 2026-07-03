from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.operations import AsyncIteratorOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AsyncForSugar(Sugar, role=SugarRole.STATEMENT):
    iterable: SugarBody
    body: SugarBody
    target_name: str
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.iterable, SugarBody):
            raise TypeError("AsyncForSugar iterable must be factory-built")
        if not isinstance(self.body, SugarBody):
            raise TypeError("AsyncForSugar body must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "AsyncFor"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "async iteration needs an async execution model before it can "
                "carry a solver verdict"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "AsyncForSugar":
        if site.observed != "AsyncFor":
            raise TypeError("AsyncForSugar claim built a non-async-for statement")
        if site.for_orelse_count() != 0:
            _raise_async_for_gap(
                site,
                observed="AsyncFor.orelse",
                requested="async-for without else",
                fix="add AsyncForSugar else/fallthrough floor",
            )
        target_name = site.for_target_name()
        if target_name is None:
            _raise_async_for_gap(
                site,
                observed=f"AsyncFor.target:{site.for_target_observed()}",
                requested="simple async-for target name",
                fix="add async-for target binding sugar for this target shape",
            )
        return cls(
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            target_name=target_name,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        iterable_outcome = self.iterable.reduce(ctx)
        if isinstance(iterable_outcome, Incomplete):
            return iterable_outcome
        iterable = complete_value(iterable_outcome, owner="AsyncForSugar iterable")
        return perform_operation(
            owner="AsyncForSugar",
            blame=self.blame,
            receiver=iterable,
            operation=AsyncIteratorOperation(
                body=self.body,
                target_name=self.target_name,
                owner="AsyncForSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


def _raise_async_for_gap(site, *, observed: str, requested: str, fix: str) -> NoReturn:
    info = FactoryGapInfo(
        owner="python.factory",
        blame=site.blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind="Sugar",
        gap_locus="AST",
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role=requested,
            status="sugar-gap",
            observed=observed,
            blame=site.blame,
            selected="AsyncForSugar",
            candidates=["AsyncForSugar"],
            message=info.message,
        ),
    )
