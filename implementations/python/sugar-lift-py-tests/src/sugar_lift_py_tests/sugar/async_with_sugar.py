from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.operations import AsyncContextManagerOperation
from sugar_lift_py_tests.operations import perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AsyncWithSugar(Sugar, role=SugarRole.STATEMENT):
    manager: SugarBody
    body: SugarBody
    optional_name: str | None
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.manager, SugarBody):
            raise TypeError("AsyncWithSugar manager must be factory-built")
        if not isinstance(self.body, SugarBody):
            raise TypeError("AsyncWithSugar body must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "AsyncWith"

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason=(
                "async context-manager execution is runtime support, not a "
                "current FOL claim"
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "AsyncWithSugar":
        if site.observed != "AsyncWith":
            raise TypeError("AsyncWithSugar claim built a non-async-with statement")
        _require_single_item(site)
        optional_name = site.with_optional_vars_name()
        optional_observed = site.with_optional_vars_observed()
        if optional_observed is not None and optional_name is None:
            _raise_async_with_gap(
                site,
                observed=f"AsyncWith.as:{optional_observed}",
                requested="simple async-with-as name",
                fix="add async with target binding sugar for this optional_vars shape",
            )
        return cls(
            manager=ctx.build_body(site.with_context_expr(), SugarRole.TERM),
            body=ctx.build_body(site.with_body(), SugarRole.STATEMENT),
            optional_name=optional_name,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        manager_outcome = self.manager.reduce(ctx)
        if isinstance(manager_outcome, Incomplete):
            return manager_outcome
        manager = complete_value(manager_outcome, owner="AsyncWithSugar manager")
        return perform_operation(
            owner="AsyncWithSugar",
            blame=self.blame,
            receiver=manager,
            operation=AsyncContextManagerOperation(
                body=self.body,
                optional_name=self.optional_name,
                owner="AsyncWithSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


def _require_single_item(site) -> None:
    count = site.with_item_count()
    if count == 1:
        return
    _raise_async_with_gap(
        site,
        observed=f"AsyncWith.items:{count}",
        requested="single async context manager",
        fix="split multiple async context managers into nested AsyncWithSugar statements",
    )


def _raise_async_with_gap(site, *, observed: str, requested: str, fix: str) -> None:
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
            selected="AsyncWithSugar",
            candidates=["AsyncWithSugar"],
            message=info.message,
        ),
    )
