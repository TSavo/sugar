from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.ir import Formula, Term, eq


@dataclass(frozen=True)
class CallsiteProjectionOperation:
    callee_name: str
    arg_terms: tuple[Term, ...]
    owner: str = "CallsiteProjectionOperation"
    blame: str = "<unknown>"

    def project_literal(self, receiver: FloorValue, ctx: Any) -> Formula:
        del ctx
        return eq(self.call_term(), receiver.to_term(owner=self.owner))

    def project_callsite(self, receiver, ctx: Any) -> Formula:
        del ctx
        return eq(self.call_term(), receiver.term)

    def project_symbolic(self, receiver, ctx: Any) -> None:
        del receiver, ctx
        return None

    def project_return(self, receiver, ctx: Any) -> Formula | None:
        return self.project_value(receiver.value, ctx)

    def project_block(self, receiver, ctx: Any) -> Formula | None:
        if len(receiver.statements) != 1 or receiver.fall_through:
            return None
        return self.project_value(receiver.statements[0], ctx)

    def project_value(self, value, ctx: Any) -> Formula | None:
        if not isinstance(value, FloorValue):
            self._floor_gap(type(value).__name__)
        from sugar_lift_py_tests.operations.perform_operation import perform_operation

        return perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=value,
            method_name="project_callsite_with",
            operation=self,
            ctx=ctx,
        )

    def project_unknown(self, receiver: FloorValue, ctx: Any) -> None:
        del ctx
        self._floor_gap(type(receiver).__name__)

    def call_term(self) -> Term:
        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        return euf_call_term(self.callee_name, list(self.arg_terms))

    def _floor_gap(self, observed: str) -> None:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=observed,
            requested="project callsite floor",
            fix=f"write more Floor: implement {observed}.project_callsite_with",
            gap_kind="Floor",
            gap_locus="Projection",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="project_callsite_with",
                status="floor-gap",
                observed=observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
