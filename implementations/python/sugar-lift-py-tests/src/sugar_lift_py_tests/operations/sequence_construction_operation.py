from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ArrayLiteral, FloorValue, ObjectValue, TermValue
from sugar_lift_py_tests.floor.sequence_constructor import SequenceConstructor
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class SequenceConstructionOperation:
    elements: tuple[FloorValue, ...]
    owner: str
    blame: str

    def construct_sequence(self, receiver: SequenceConstructor, ctx: object) -> Outcome:
        del ctx
        if receiver.kind == "tuple":
            return Complete(TupleLiteralValue(self.elements))
        if receiver.kind == "list":
            return Complete(
                ArrayLiteral(tuple(self._list_element(item) for item in self.elements))
            )
        self._floor_gap(
            observed=f"SequenceConstructor({receiver.kind})",
            requested="sequence kind",
            fix=f"add SequenceConstructionOperation support for {receiver.kind}",
        )

    def _list_element(
        self, item: FloorValue
    ) -> TermValue | ObjectValue | ArrayLiteral | TupleLiteralValue:
        if isinstance(item, (TermValue, ObjectValue, ArrayLiteral, TupleLiteralValue)):
            return item
        self._floor_gap(
            observed=f"ListLiteralSugar element {type(item).__name__}",
            requested="list element floor",
            fix=f"add ListLiteralSugar construction support for {type(item).__name__}",
        )

    def _floor_gap(self, *, observed: str, requested: str, fix: str) -> NoReturn:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role=requested,
                status="floor-gap",
                observed=observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
