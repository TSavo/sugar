from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


@dataclass(frozen=True)
class UnaryOperatorOperation:
    operator: str
    owner: str = "UnaryOpSugar"
    blame: str = "<unknown>"

    def unary_term(self, receiver: TermValue, ctx: object) -> Outcome:
        del ctx
        if self.operator == "py.pos":
            return Complete(TermValue(+receiver.value))
        if self.operator == "py.neg":
            return Complete(TermValue(-receiver.value))
        self._floor_gap(receiver="TermValue")

    def unary_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        if self.operator == "py.pos":
            return Complete(receiver)
        if self.operator == "py.neg":
            return Complete(
                SymbolicValue(
                    ctor(
                        self.operator,
                        [floor_to_term(receiver, owner=f"{self.owner} operand")],
                    )
                )
            )
        self._floor_gap(receiver="SymbolicValue")

    def _floor_gap(self, *, receiver: str) -> None:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=f"{self.operator}({receiver})",
            requested="unary operator floor",
            fix=f"add UnaryOperatorOperation support for {self.operator} on {receiver}",
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="unary operator floor",
                status="floor-gap",
                observed=info.observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
