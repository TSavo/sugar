"""Subscript operation: one demand against one reduced receiver + index.

Floors that implement ``subscript_with`` re-dispatch here. Floors that only
implement legacy ``subscript`` stay on that path via
``SubscriptSugar`` fallback — this module does not own those floors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, NoReturn

from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import num
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class SubscriptOperation:
    """One ``receiver[index]`` demand.

    ``method_name`` is the floor protocol edge. Species that override
    ``subscript_with`` call back into the species-specific methods below.
    """

    method_name: ClassVar[str] = "subscript_with"

    index: Any
    owner: str
    blame: object
    use_occurrence: object | None = None

    def subscript_string(self, receiver, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import (
            Bv32Value,
            EncodedStringValue,
            SliceValue,
            StringValue,
            TermValue,
        )

        index = force_floor(self.index, ctx, owner=f"{self.owner} index")
        index = _unwrap_index(index)
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

    def subscript_array(self, receiver, ctx: object) -> Outcome:
        index = force_floor(self.index, ctx, owner=f"{self.owner} array index")
        return _subscript_sequence(
            receiver.items,
            _unwrap_index(index),
            owner=self.owner,
            blame=self.blame,
            observed_name="ArrayLiteral",
        )

    def subscript_tuple(self, receiver, ctx: object) -> Outcome:
        index = force_floor(self.index, ctx, owner=f"{self.owner} tuple index")
        return _subscript_sequence(
            receiver.items,
            _unwrap_index(index),
            owner=self.owner,
            blame=self.blame,
            observed_name="TupleLiteralValue",
        )

    def subscript_object(self, receiver, ctx: object) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__getitem__",
            (self.index,),
            owner=self.owner,
            blame=self.blame,
        )

    def subscript_symbolic(self, receiver, ctx: object) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        index = self.index
        if hasattr(index, "to_term"):
            index_term = index.to_term(owner=f"{self.owner} index")
        elif hasattr(index, "term"):
            index_term = index.term
        else:
            raise TypeError(
                f"SubscriptOperation.subscript_symbolic needs index.to_term "
                f"(got {type(index).__name__})"
            )
        return Complete(
            SymbolicValue(
                ctor(
                    "py.subscript",
                    [receiver.term, index_term],
                )
            )
        )


def _unwrap_index(index: Any) -> Any:
    """Sequence indices consume the downstream value of an opaque-op coordinate."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

    if isinstance(index, OpaqueOpCallsite):
        return index._downstream()
    return index


def _subscript_sequence(
    items: tuple[Any, ...],
    index: Any,
    *,
    owner: str,
    blame: object,
    observed_name: str,
) -> Outcome:
    from sugar_lift_py_tests.floor import BoolValue, TermValue

    index = _unwrap_index(index)
    if isinstance(index, BoolValue):
        index = TermValue(1 if index.value else 0)
    if isinstance(index, TermValue) and type(index.value) is int:
        item_index = index.value
        if item_index < 0:
            item_index += len(items)
        if 0 <= item_index < len(items):
            return Complete(items[item_index])
        _raise_subscript_gap(
            owner=owner,
            blame=str(blame),
            observed=f"{observed_name}[{index.value}]",
            requested="bounds-safe sequence subscript",
            fix=f"add bounds-safe projection support for {observed_name}",
        )
    _raise_subscript_gap(
        owner=owner,
        blame=str(blame),
        observed=type(index).__name__,
        requested="concrete sequence index",
        fix=f"add sequence index floor for {type(index).__name__}",
    )


def _string_index_term(value: Any):
    from sugar_lift_py_tests.floor import Bv32Value, TermValue

    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, TermValue):
        return num(int(value.value))
    raise TypeError(
        f"write more Floor for SubscriptOperation string index "
        f"`{type(value).__name__}`: expected TermValue or Bv32Value"
    )


def _subscript_string_slice(receiver, index, blame: object) -> Outcome:
    from sugar_lift_py_tests.floor import StringValue, TermValue

    lower = _concrete_slice_bound(index.lower, blame)
    upper = _concrete_slice_bound(index.upper, blame)
    step = _concrete_slice_bound(index.step, blame)
    return Complete(StringValue(receiver.value[slice(lower, upper, step)]))


def _concrete_slice_bound(value: Any | None, blame: object) -> int | None:
    from sugar_lift_py_tests.floor import TermValue

    if value is None:
        return None
    if isinstance(value, TermValue) and type(value.value) is int:
        return value.value
    _raise_subscript_gap(
        owner="SubscriptOperation.string_slice",
        blame=str(blame),
        observed=type(value).__name__,
        requested="concrete slice bounds",
        fix="add symbolic StringValue slice lowering",
    )


def _raise_subscript_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import construction_panic

    construction_panic(
        ConstructionGap(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    )
