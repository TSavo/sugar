from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, NoReturn, cast

from sugar_lift_py_tests.factory import (
    FactoryAuditRow, factory_panic,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.ir import _ConstStr, _Ctor, Formula, Term, eq


@dataclass(frozen=True)
class CallsiteProjectionOperation:
    method_name: ClassVar[str] = "project_callsite_with"
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

    def project_symbolic(self, receiver, ctx: Any) -> Formula | None:
        del ctx
        if _is_concrete_python_bytes_term(receiver.term):
            return eq(self.call_term(), receiver.term)
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

        projected = perform_operation(
            owner=self.owner,
            blame=self.blame,
            receiver=value,
            operation=self,
            ctx=ctx,
        )
        return cast(Formula | None, projected)

    def project_unknown(self, receiver: FloorValue, ctx: Any) -> NoReturn:
        del ctx
        self._floor_gap(type(receiver).__name__)

    def call_term(self) -> Term:
        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        return euf_call_term(self.callee_name, list(self.arg_terms))

    def _floor_gap(self, observed: str) -> NoReturn:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=observed,
            requested="project callsite floor",
            fix=f"write more Floor: implement {observed}.project_callsite_with",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.PROJECTION,
        )
        factory_panic(
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


def _is_concrete_python_bytes_term(term: Term) -> bool:
    return (
        isinstance(term, _Ctor)
        and term.name == "python:bytes"
        and len(term.args) == 1
        and isinstance(term.args[0], _ConstStr)
    )
