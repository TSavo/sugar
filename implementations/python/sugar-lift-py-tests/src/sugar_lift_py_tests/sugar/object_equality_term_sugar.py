from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue, force_floor
from sugar_lift_py_tests.operations import BinaryOperatorOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import object_equality_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ObjectEqualityTermSugar(Sugar, role=SugarRole.TERM):
    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Compare":
            return False
        return site.compare_ops() == ["Eq"] and len(site.compare_comparators()) == 1

    @classmethod
    def build(cls, site, ctx) -> "ObjectEqualityTermSugar":
        if not cls.owns(site):
            raise TypeError(
                "ObjectEqualityTermSugar claim built a non-equality compare"
            )
        return cls(
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        return object_equality_return_witness()

    def _build(self, ctx) -> Outcome:
        left_outcome = self.left.reduce(ctx)
        if isinstance(left_outcome, Incomplete):
            return left_outcome
        right_outcome = self.right.reduce(ctx)
        if isinstance(right_outcome, Incomplete):
            return right_outcome
        left = complete_value(left_outcome, owner="ObjectEqualityTermSugar left")
        right = complete_value(right_outcome, owner="ObjectEqualityTermSugar right")
        left = _force_equality_operand(left, ctx, owner="ObjectEqualityTermSugar left")
        right = _force_equality_operand(
            right, ctx, owner="ObjectEqualityTermSugar right"
        )
        return perform_operation(
            owner="ObjectEqualityTermSugar",
            blame=self.blame,
            receiver=left,
            operation=BinaryOperatorOperation(
                operator="==",
                right=right,
                owner="ObjectEqualityTermSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


def _force_equality_operand(value: FloorValue, ctx, *, owner: str) -> FloorValue:
    if isinstance(value, CallSiteValue):
        return force_floor(value, ctx, owner=owner)
    return value
