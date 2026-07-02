from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value


@dataclass(frozen=True)
class AddOperation:
    operand: TermValue
    owner: str = "AddSugar"
    blame: str = "<unknown>"

    def add_term(self, receiver: TermValue, ctx: object) -> Outcome:
        del ctx
        if not isinstance(self.operand, TermValue):
            self._floor_gap(receiver=type(receiver).__name__)
        return Complete(TermValue(receiver.value + self.operand.value))

    def add_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        return Complete(
            ArrayLiteral(
                tuple(
                    TermValue(self._array_term(item).value + self.operand.value)
                    for item in receiver.items
                )
            )
        )

    def add_builder(self, receiver: BuilderState, ctx: object) -> Outcome:
        current = complete_value(receiver.current.add_with(self, ctx), owner=self.owner)
        if not isinstance(current, ArrayLiteral):
            raise TypeError("AddOperation over BuilderState must produce ArrayLiteral")
        return Complete(BuilderState(current))

    def _array_term(self, item) -> TermValue:
        if isinstance(item, TermValue):
            return item
        self._floor_gap(receiver=f"ArrayLiteral[{type(item).__name__}]")

    def _floor_gap(self, *, receiver: str) -> NoReturn:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver}+{type(self.operand).__name__}",
            requested="add operand floor",
            fix=f"add AddOperation support for {receiver} with {type(self.operand).__name__}",
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="add operand floor",
                status="floor-gap",
                observed=info.observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
