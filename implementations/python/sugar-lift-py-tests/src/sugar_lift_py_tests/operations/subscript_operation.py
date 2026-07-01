from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    Bv32Value,
    EncodedStringValue,
    FloorValue,
    SliceValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


@dataclass(frozen=True)
class SubscriptOperation:
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
        if isinstance(index, TermValue) and type(index.value) is int:
            if 0 <= index.value < len(receiver.items):
                return Complete(receiver.items[index.value])
            _raise_subscript_gap(
                owner=self.owner,
                blame=self.blame,
                observed=f"ArrayLiteral[{index.value}]",
                requested="bounds-safe array subscript",
                fix="add bounds-safe projection support for ArrayLiteral",
            )
        _raise_subscript_gap(
            owner=self.owner,
            blame=self.blame,
            observed=type(index).__name__,
            requested="concrete array index",
            fix=f"add array index floor for {type(index).__name__}",
        )

    def subscript_object(self, receiver, ctx: object) -> Outcome:
        del ctx
        return receiver.call_method_value(
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


def _string_index_term(value: FloorValue):
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, TermValue):
        return num(value.value)
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
) -> None:
    info = FactoryGapInfo(
        owner="StringSubscriptSugar.string_slice",
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind="Floor",
        gap_locus="construction",
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
) -> None:
    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
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
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
