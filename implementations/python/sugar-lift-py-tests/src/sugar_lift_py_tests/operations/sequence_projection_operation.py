from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    FloorValue,
    ObjectValue,
    SymbolicValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.outcome.complete_value import complete_value


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

    def project_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        iter_value = force_floor(
            complete_value(
                receiver.call_method_value(
                    "__iter__",
                    (),
                    owner=f"{self.owner}.__iter__",
                    blame=self.blame,
                ),
                owner=f"{self.owner}.__iter__",
            ),
            ctx,
            owner=f"{self.owner}.__iter__",
            project_callsite=False,
        )
        from sugar_lift_py_tests.operations.perform_operation import perform_operation

        return perform_operation(
            owner=f"{self.owner}.__iter__",
            blame=self.blame,
            receiver=iter_value,
            method_name="project_sequence_with",
            operation=self,
            ctx=ctx,
        )

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
