from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.operations.object_method_call import call_object_method_value
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody

_RICH_COMPARISON_DUNDERS: dict[str, str] = {
    "NotEq": "__ne__",
    "Lt": "__lt__",
    "LtE": "__le__",
    "Gt": "__gt__",
    "GtE": "__ge__",
}


@dataclass(frozen=True)
class ObjectRichComparisonTermSugar(Sugar, role=SugarRole.TERM):
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Compare":
            return False
        return (
            len(site.compare_ops()) == 1
            and len(site.compare_comparators()) == 1
            and site.compare_ops()[0] in _RICH_COMPARISON_DUNDERS
        )

    @classmethod
    def build(cls, site, ctx) -> "ObjectRichComparisonTermSugar":
        if not cls.owns(site):
            raise TypeError(
                "ObjectRichComparisonTermSugar claim built a non-rich compare"
            )
        return cls(
            operator=site.compare_ops()[0],
            left=ctx.build_body(site.compare_left(), SugarRole.TERM),
            right=ctx.build_body(site.compare_comparators()[0], SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        left_outcome = self.left.reduce(ctx)
        if isinstance(left_outcome, Incomplete):
            return left_outcome
        right_outcome = self.right.reduce(ctx)
        if isinstance(right_outcome, Incomplete):
            return right_outcome
        left = complete_value(left_outcome, owner="ObjectRichComparisonTermSugar left")
        right = complete_value(
            right_outcome, owner="ObjectRichComparisonTermSugar right"
        )
        if isinstance(left, ObjectValue):
            return call_object_method_value(
                left,
                _RICH_COMPARISON_DUNDERS[self.operator],
                (right,),
                owner="ObjectRichComparisonTermSugar",
                blame=self.blame,
            )
        return Complete(
            SymbolicValue(
                ctor(
                    f"py.compare:{self.operator}",
                    [
                        floor_to_term(
                            left, owner="ObjectRichComparisonTermSugar left"
                        ),
                        floor_to_term(
                            right, owner="ObjectRichComparisonTermSugar right"
                        ),
                    ],
                )
            )
        )
