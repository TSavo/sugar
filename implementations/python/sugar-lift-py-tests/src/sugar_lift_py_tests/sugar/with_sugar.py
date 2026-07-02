from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.operations import ContextManagerOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class WithSugar(Sugar, role=SugarRole.STATEMENT):
    manager: SugarBody
    body: SugarBody
    optional_name: str | None
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.manager, SugarBody):
            raise TypeError("WithSugar manager must be factory-built")
        if not isinstance(self.body, SugarBody):
            raise TypeError("WithSugar body must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "With"

    @classmethod
    def build(cls, site, ctx) -> "WithSugar":
        if site.observed != "With":
            raise TypeError("WithSugar claim built a non-with statement")
        _require_single_item(site)
        optional_name = site.with_optional_vars_name()
        optional_observed = site.with_optional_vars_observed()
        if optional_observed is not None and optional_name is None:
            _raise_with_gap(
                site,
                observed=f"With.as:{optional_observed}",
                requested="simple with-as name",
                fix="add with target binding sugar for this optional_vars shape",
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
        manager = complete_value(manager_outcome, owner="WithSugar manager")
        return perform_operation(
            owner="WithSugar",
            blame=self.blame,
            receiver=manager,
            method_name="context_manager_with",
            operation=ContextManagerOperation(
                body=self.body,
                optional_name=self.optional_name,
                owner="WithSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


def _require_single_item(site) -> None:
    count = site.with_item_count()
    if count == 1:
        return
    _raise_with_gap(
        site,
        observed=f"With.items:{count}",
        requested="single context manager",
        fix="split multiple context managers into nested WithSugar-owned statements",
    )


def _raise_with_gap(site, *, observed: str, requested: str, fix: str) -> None:
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
            selected="WithSugar",
            candidates=["WithSugar"],
            message=info.message,
        ),
    )
