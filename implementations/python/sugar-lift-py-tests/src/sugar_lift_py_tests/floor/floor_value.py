from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.ir import Term


class FloorValue:
    non_fol_support = False

    def inplace_binary_operator_with(self, operation, ctx):
        return operation.inplace_default(self, ctx)

    def project_callsite_with(self, operation, ctx):
        return operation.project_unknown(self, ctx)

    def to_term(self, *, owner: str) -> "Term":
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner=owner,
            blame=observed,
            observed=observed,
            requested="project this floor value to a term",
            fix=f"write more Floor: implement {observed}.to_term",
            gap_kind="Floor",
            gap_locus="Projection",
        )
        gap = FactoryGap(
            info,
            FactoryAuditRow(
                role="to_term",
                status="floor-gap",
                observed=observed,
                blame=observed,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
        gap.info["gap_kind"] = "Floor"
        gap.info["gap_locus"] = "Projection"
        raise gap
