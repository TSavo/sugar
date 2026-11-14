"""Subscript operation: one demand against one reduced receiver + index.

``discharge_subscript`` is the one door for ``receiver[index]``.  Floors that
implement ``subscript_with`` re-dispatch here; floors that only implement
``subscript`` answer through ``subscript_with_occurrence``.  No module outside
this one calls a floor's ``subscript`` / ``subscript_with`` /
``subscript_with_occurrence`` on another value, and a floor calls its own only
inside those protocol methods (``test_subscript_one_door_7757``): every read
(a source subscript, a pattern's projection, a walrus's presented value, a
mapping object's ``__getitem__``, an opaque operation's downstream value, each
arm of a guarded value) reaches the receiver through the door, so a parameter
in either operand defers to the caller wherever the read is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, NoReturn

from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import num
from sugar_lift_py_tests.outcome import ExitSet


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

    @property
    def site(self) -> object:
        """The source locus of this subscript demand.

        Sibling operations expose ``site``; this one recorded the same fragment
        under ``blame`` (subscript_sugar passes ``blame=self.site``). A consumer
        that reduces a subscript over an undecided receiver (an ImportMemberValue
        under an enrolled stdlib body, e.g. warnings) reads ``operation.site`` --
        without this it raised AttributeError and voided the file (31 files on the
        warnings tip board).
        """
        return self.blame

    def submit(self, receiver: Any, ctx: object) -> ExitSet:
        """Ask the receiver to answer this subscript demand."""
        return receiver.subscript_with(self, ctx)

    def subscript_string(self, receiver, ctx: object) -> ExitSet:
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
            return ExitSet.completed(StringValue(receiver.value[index.value]))
        return ExitSet.completed(
            EncodedStringValue(
                table=tuple(ord(ch) for ch in receiver.value),
                indices=(_string_index_term(index),),
            )
        )

    def subscript_tuple(self, receiver, ctx: object) -> ExitSet:
        index = force_floor(self.index, ctx, owner=f"{self.owner} tuple index")
        return _subscript_sequence(
            receiver.items,
            _unwrap_index(index),
            owner=self.owner,
            blame=self.blame,
            observed_name="TupleLiteralValue",
        )

    def subscript_object(self, receiver, ctx: object) -> ExitSet:
        return receiver.call_method_value(
            "__getitem__",
            (self.index,),
            owner=self.owner,
            blame=self.blame,
            ctx=ctx,
        )


def defer_formal_subscript(receiver, index, site):
    """``receiver[index]`` with a function parameter in either operand: the
    ``subscript`` carrier, decided by the caller's actual.

    The one mint of the ``subscript`` demand.  A formal receiver (``p[0]``)
    and a formal index on any receiver (``[1, 2][i]``) defer alike, one
    coordinate slot per ordered operand; ``None`` when neither operand is a
    formal, and the receiver answers the read itself.  A parameter inside a
    slice bound (``xs[start:]``) never reaches here as a formal: the slice it
    bounds is itself deferred (``construct_slice``, the ``slice`` carrier), and
    the read runs on the slice the caller's actual decides.
    """
    coordinates = (
        getattr(receiver, "formal_coordinate", None),
        getattr(index, "formal_coordinate", None),
    )
    if all(coordinate is None for coordinate in coordinates):
        return None
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    return NativeOperationExitCarrierV1.mint(
        site=site,
        operator="subscript",
        operands=(receiver, index),
        coordinates=coordinates,
    )


def discharge_subscript(
    receiver, index, site, ctx, *, owner: str, use_occurrence=None
) -> ExitSet:
    """The one door for ``receiver[index]``, under ``ctx``.

    ``SubscriptSugar`` (a source subscript), the mutation door's
    read-modify-store (``obj[k] += v``,
    ``PathContainerCallSugar._read_modify_store``) and the ``subscript``
    carrier's projector (a
    formal's subscript, at the caller's actuals) all answer here, so an
    actual is asked exactly what the source subscript asks.  A parameter in
    either operand defers to the caller (:func:`defer_formal_subscript`); an
    actual that is still its own caller's formal defers again.  Otherwise a
    receiver that overrides ``subscript_with`` owns the operation edge; any
    other answers through ``subscript_with_occurrence`` / ``subscript``.
    """
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    receiver = receiver.project_operation_receiver(ctx, owner=f"{owner} receiver")
    index = index.project_operation_receiver(ctx, owner=f"{owner} index")
    deferred = defer_formal_subscript(receiver, index, site)
    if deferred is not None:
        return deferred
    operation = SubscriptOperation(
        index=index,
        owner=owner,
        blame=site,
        use_occurrence=use_occurrence,
    )
    if (
        isinstance(receiver, FloorValue)
        and type(receiver).subscript_with is not FloorValue.subscript_with
    ):
        return receiver.subscript_with(operation, ctx)
    return receiver.subscript_with_occurrence(index, site, use_occurrence)


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
) -> ExitSet:
    from sugar_lift_py_tests.floor import BoolValue, TermValue

    index = _unwrap_index(index)
    if isinstance(index, BoolValue):
        index = TermValue(1 if index.value else 0)
    if isinstance(index, TermValue) and type(index.value) is int:
        item_index = index.value
        if item_index < 0:
            item_index += len(items)
        if 0 <= item_index < len(items):
            return ExitSet.completed(items[item_index])
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


def _subscript_string_slice(receiver, index, blame: object) -> ExitSet:
    from sugar_lift_py_tests.floor import StringValue, TermValue

    lower = _concrete_slice_bound(index.lower, blame)
    upper = _concrete_slice_bound(index.upper, blame)
    step = _concrete_slice_bound(index.step, blame)
    return ExitSet.completed(StringValue(receiver.value[slice(lower, upper, step)]))


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
