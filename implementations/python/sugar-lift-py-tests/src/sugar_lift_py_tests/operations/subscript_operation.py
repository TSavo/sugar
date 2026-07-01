from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import (
    Bv32Value,
    EncodedStringValue,
    FloorValue,
    SliceValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


@dataclass(frozen=True)
class SubscriptOperation:
    index: FloorValue
    owner: str = "StringSubscriptSugar"
    blame: str = "<unknown>"

    def subscript_string(self, receiver: StringValue, ctx: object) -> Outcome:
        del ctx
        if isinstance(self.index, SliceValue):
            return _subscript_string_slice(receiver, self.index, self.blame)
        if isinstance(self.index, TermValue) and type(self.index.value) is int:
            return Complete(StringValue(receiver.value[self.index.value]))
        return Complete(
            EncodedStringValue(
                table=tuple(ord(ch) for ch in receiver.value),
                indices=(_string_index_term(self.index),),
            )
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
