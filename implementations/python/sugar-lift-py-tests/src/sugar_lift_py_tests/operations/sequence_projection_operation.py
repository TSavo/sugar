from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ArrayLiteral, FloorValue, SymbolicValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class SequenceProjectionOperation:
    index: int
    owner: str = "TupleUnpackProjection"
    blame: str = "<unknown>"

    def project_tuple(self, receiver: TupleLiteralValue, ctx: object) -> Outcome:
        del ctx
        return Complete(self._item(receiver.items, receiver="TupleLiteralValue"))

    def project_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        return Complete(self._item(receiver.items, receiver="ArrayLiteral"))

    def project_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            SymbolicValue(ctor("py.unpack", [receiver.term, num(self.index)]))
        )

    def _item(self, items: tuple[FloorValue, ...], *, receiver: str) -> FloorValue:
        if 0 <= self.index < len(items):
            return items[self.index]
        self._floor_gap(
            observed=f"{receiver}[{self.index}]",
            requested="sequence projection",
            fix=f"add bounds-safe projection support for {receiver}",
        )

    def _floor_gap(self, *, observed: str, requested: str, fix: str) -> None:
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
