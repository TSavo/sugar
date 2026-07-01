from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import BoolValue
from sugar_lift_py_tests.ir import Formula, bool_const, eq
from sugar_lift_py_tests.operations import ContainsOperation
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MembershipAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.membership-assertion-sugar"

    item: SugarBody
    container: SugarBody
    negated: bool
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Compare":
            return False
        return test.compare_ops() in (["In"], ["NotIn"]) and len(
            test.compare_comparators()
        ) == 1

    @classmethod
    def build(cls, site, ctx) -> "MembershipAssertionSugar":
        test = site.assert_test()
        if not cls.owns(site):
            raise TypeError("MembershipAssertionSugar claim built a non-membership assert")
        return cls(
            item=ctx.build_body(test.compare_left(), SugarRole.TERM),
            container=ctx.build_body(test.compare_comparators()[0], SugarRole.TERM),
            negated=test.compare_ops() == ["NotIn"],
            blame=site.blame,
        )

    def desugar(self, ctx):
        item_outcome = self.item.reduce(ctx)
        if isinstance(item_outcome, Incomplete):
            return item_outcome
        container_outcome = self.container.reduce(ctx)
        if isinstance(container_outcome, Incomplete):
            return container_outcome
        item = complete_value(item_outcome, owner="MembershipAssertionSugar item")
        container = complete_value(
            container_outcome, owner="MembershipAssertionSugar container"
        )
        operation = ContainsOperation(
            item=item,
            owner="MembershipAssertionSugar",
            blame=self.blame,
        )
        contains_outcome = _perform_contains(
            receiver=container,
            operation=operation,
            blame=self.blame,
            ctx=ctx,
        )
        contains = complete_value(
            contains_outcome, owner="MembershipAssertionSugar contains"
        )
        if not isinstance(contains, BoolValue):
            raise TypeError("MembershipAssertionSugar contains must reduce to BoolValue")
        result = not contains.value if self.negated else contains.value
        return _assert_true(result)


def _assert_true(value: bool) -> Formula:
    return eq(bool_const(value), bool_const(True))


def _perform_contains(*, receiver, operation: ContainsOperation, blame: str, ctx):
    method = getattr(receiver, "contains_with", None)
    if method is None:
        info = FactoryGapInfo(
            owner="MembershipAssertionSugar",
            blame=blame,
            observed=type(receiver).__name__,
            requested="contains_with",
            fix=f"add contains_with to {type(receiver).__name__}",
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="contains_with",
                status="floor-gap",
                observed=type(receiver).__name__,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
    return method(operation, ctx)
