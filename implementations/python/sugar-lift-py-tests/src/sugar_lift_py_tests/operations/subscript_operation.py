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
    Bv32Value,
    EncodedStringValue,
    FloorValue,
    ObjectValue,
    SliceValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleLiteralValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

from .object_method_call import call_object_method_value


@dataclass(frozen=True)
class SubscriptOperation:
    method_name: ClassVar[str] = "subscript_with"
    index: FloorValue
    owner: str = "StringSubscriptSugar"
    blame: str = "<unknown>"

    def subscript_string(self, receiver: StringValue, ctx: object) -> Outcome:
        index = force_floor(
            self.index,
            ctx,
            owner=f"{self.owner} index",
        )
        if isinstance(index, SliceValue):
            return _subscript_string_slice(receiver, index, self.blame)
        if isinstance(index, TermValue) and type(index.value) is int:
            return Complete(StringValue(receiver.value[index.value]))
        return Complete(
            EncodedStringValue(
                table=tuple(ord(ch) for ch in receiver.value),
                indices=(_string_index_term(index),),
            )
        )

    def subscript_array(self, receiver: ArrayLiteral, ctx: object) -> Outcome:
        index = force_floor(
            self.index,
            ctx,
            owner=f"{self.owner} array index",
        )
        return _subscript_sequence(
            receiver.items,
            index,
            owner=self.owner,
            blame=self.blame,
            observed_name="ArrayLiteral",
        )

    def subscript_tuple(self, receiver: TupleLiteralValue, ctx: object) -> Outcome:
        index = force_floor(
            self.index,
            ctx,
            owner=f"{self.owner} tuple index",
        )
        return _subscript_sequence(
            receiver.items,
            index,
            owner=self.owner,
            blame=self.blame,
            observed_name="TupleLiteralValue",
        )

    def subscript_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        return call_object_method_value(
            receiver,
            "__getitem__",
            (self.index,),
            owner=self.owner,
            blame=self.blame,
        )

    def subscript_symbolic(self, receiver: SymbolicValue, ctx: object) -> Outcome:
        del ctx
        return Complete(
            SymbolicValue(
                ctor(
                    "py.subscript",
                    [
                        receiver.term,
                        floor_to_term(self.index, owner=f"{self.owner} index"),
                    ],
                )
            )
        )


def _subscript_sequence(
    items: tuple[FloorValue, ...],
    index: FloorValue,
    *,
    owner: str,
    blame: str,
    observed_name: str,
) -> Outcome:
    if isinstance(index, BoolValue):
        index = TermValue(1 if index.value else 0)
    if isinstance(index, TermValue) and type(index.value) is int:
        if 0 <= index.value < len(items):
            return Complete(items[index.value])
        _raise_subscript_gap(
            owner=owner,
            blame=blame,
            observed=f"{observed_name}[{index.value}]",
            requested="bounds-safe sequence subscript",
            fix=f"add bounds-safe projection support for {observed_name}",
        )
    _raise_subscript_gap(
        owner=owner,
        blame=blame,
        observed=type(index).__name__,
        requested="concrete sequence index",
        fix=f"add sequence index floor for {type(index).__name__}",
    )


def _string_index_term(value: FloorValue):
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, TermValue):
        return num(int(value.value))
    raise TypeError(
        f"write more Floor for StringSubscriptSugar index `{type(value).__name__}`: "
        "expected TermValue or Bv32Value"
    )


def _subscript_string_slice(
    receiver: StringValue, index: SliceValue, blame: str
) -> Outcome:
    lower = _concrete_slice_bound(index.lower, blame)
    upper = _concrete_slice_bound(index.upper, blame)
    step = _concrete_slice_bound(index.step, blame)
    return Complete(StringValue(receiver.value[slice(lower, upper, step)]))


def _concrete_slice_bound(value: FloorValue | None, blame: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, TermValue) and type(value.value) is int:
        return value.value
    _raise_string_slice_gap(
        blame=blame,
        observed=type(value).__name__,
        requested="concrete slice bounds",
        fix="add symbolic StringValue slice lowering",
    )


def _raise_string_slice_gap(
    *,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    info = FactoryGapInfo(
        owner="StringSubscriptSugar.string_slice",
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role="string_slice",
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _raise_subscript_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role=requested,
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
