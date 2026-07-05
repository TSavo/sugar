from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, NoReturn

from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    FloorValue,
    PredicateValue,
    SetLiteralValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import _ConstBool, _ConstInt, _ConstReal, _ConstStr, atomic
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


@dataclass(frozen=True)
class ContainsOperation:
    method_name: ClassVar[str] = "contains_with"
    item: FloorValue
    owner: str = "MembershipAssertionSugar"
    blame: str = "<unknown>"

    def contains_string(self, receiver: StringValue, ctx: object) -> Outcome:
        del ctx
        if isinstance(self.item, SymbolicValue):
            return Complete(
                PredicateValue(
                    atomic(
                        "contains",
                        [
                            floor_to_term(receiver, owner=f"{self.owner} container"),
                            floor_to_term(self.item, owner=f"{self.owner} item"),
                        ],
                    )
                )
            )
        if not isinstance(self.item, StringValue):
            self._floor_gap(receiver="StringValue")
        return Complete(BoolValue(self.item.value in receiver.value))

    def contains_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        del ctx
        if not isinstance(self.item, TermValue):
            self._floor_gap(receiver="ArrayLiteral")
        return Complete(BoolValue(any(item == self.item for item in receiver.items)))

    def contains_set(self, receiver: SetLiteralValue, ctx: object) -> Outcome:
        del ctx
        item_term = floor_to_term(self.item, owner=f"{self.owner} item")
        if any(item == item_term for item in receiver.items):
            return Complete(BoolValue(True))
        if _is_ground_literal(item_term) and all(
            _is_ground_literal(item) for item in receiver.items
        ):
            return Complete(BoolValue(False))
        return Complete(
            PredicateValue(
                atomic(
                    "contains",
                    [
                        floor_to_term(receiver, owner=f"{self.owner} container"),
                        item_term,
                    ],
                )
            )
        )

    def contains_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            PredicateValue(
                atomic(
                    "contains",
                    [
                        floor_to_term(receiver, owner=f"{self.owner} container"),
                        floor_to_term(self.item, owner=f"{self.owner} item"),
                    ],
                )
            )
        )

    def _floor_gap(self, *, receiver: str) -> NoReturn:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=f"{receiver}.contains({type(self.item).__name__})",
            requested="contains item floor",
            fix=f"add contains support for {receiver} with {type(self.item).__name__}",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="contains item floor",
                status="floor-gap",
                observed=info.observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )


def _is_ground_literal(term) -> bool:
    return isinstance(term, (_ConstBool, _ConstInt, _ConstReal, _ConstStr))
