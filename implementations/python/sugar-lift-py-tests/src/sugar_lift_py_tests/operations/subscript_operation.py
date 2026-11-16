"""Subscript operation: one demand against one reduced receiver + index.

``discharge_subscript`` is the one door for ``receiver[index]``.  Floors that
implement ``subscript_with`` re-dispatch here; floors that only implement
``subscript`` answer through ``subscript_with_occurrence``.  No module outside
this one calls a floor's ``subscript`` / ``subscript_with`` /
``subscript_with_occurrence`` on another value, and a floor calls its own only
inside those protocol methods (``test_subscript_one_door_7757``): every read
(a source subscript, a pattern's projection, a walrus's presented value, a
mapping object's ``__getitem__``, an opaque operation's downstream value, each
arm of a guarded value) reaches the receiver through the door.  No read waits
on a caller's actual (#7757): a parameter receiver (``p[k]``, ``p[a:b]``) is
the one undecided read (``FloorValue.undecided_subscript``), and a parameter
index or slice bound on a receiver the lift decides is that receiver's own
read with the symbolic key, wherever the read is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, NoReturn

from sugar_lift_py_tests.floor.call_site_value import force_floor
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


def discharge_subscript(
    receiver, index, site, ctx, *, owner: str, use_occurrence=None
) -> ExitSet:
    """The one door for ``receiver[index]``, under ``ctx``.

    ``SubscriptSugar`` (a source subscript) and the mutation door's
    read-modify-store (``obj[k] += v``,
    ``PathContainerCallSugar._read_modify_store``) both answer here.  A
    receiver whose type binds no ``__getitem__`` raises its ``TypeError``.
    Otherwise a receiver that overrides ``subscript_with`` owns the operation
    edge; any other answers through ``subscript_with_occurrence`` /
    ``subscript``.  A parameter receiver answers as every receiver whose type
    nothing here decides does: the one undecided read, both faces, owed
    (``SymbolicValue.subscript``).  A parameter index (or a slice whose bound
    is one) on a receiver the lift decides is that receiver's own read with
    the symbolic key, every halt face of it kept, as an opaque call result's
    key is.  No read waits on a caller's actual (#7757).
    """
    from sugar_lift_py_tests.floor.floor_value import (
        FloorValue,
        receiver_lacks_item_method,
    )

    receiver = receiver.project_operation_receiver(ctx, owner=f"{owner} receiver")
    index = index.project_operation_receiver(ctx, owner=f"{owner} index")
    operation = SubscriptOperation(
        index=index,
        owner=owner,
        blame=site,
        use_occurrence=use_occurrence,
    )
    if receiver_lacks_item_method(receiver, "__getitem__"):
        # The receiver's type binds no ``__getitem__``: the read raises
        # ``TypeError`` whatever the index is (``ObjectValue.subscript_with``).
        return receiver.subscript_with(operation, ctx)
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
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    index = _unwrap_index(index)
    # ``bool`` is an ``int``: ``t[True]`` is ``t[1]`` and ``t[False]`` is
    # ``t[0]``. A decided boolean is one of the two literal values.
    if type(index) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar):
        index = TermValue(1 if type(index) is TrueBoolLiteralSugar else 0)
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
