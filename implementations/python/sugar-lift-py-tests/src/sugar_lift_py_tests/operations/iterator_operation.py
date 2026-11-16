"""Synchronous iterator surface: ``__iter__`` / iterable → iterator Floor.

Route:

    IteratorOperation(...)
        → receiver.iter_with(operation, ctx)

Exact containers (list/tuple/…) answer with an authenticated iterator Floor.
Species without authority take the construction-gap default on FloorValue.
ObjectValue answers through ``__iter__`` data-model methods (real coordinates).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class IteratorOperation:
    """One ``__iter__`` demand against one iterable receiver."""

    method_name: ClassVar[str] = "iter_with"

    owner: str
    blame: object

    @property
    def site(self) -> object:
        """The source locus of this demand (recorded under ``blame``).

        Consumers that reduce this operation over an undecided receiver -- an
        ImportMemberValue under an enrolled stdlib body -- read
        ``operation.site``. Sibling operations that lacked it raised
        AttributeError and voided the file (see SubscriptOperation.site).
        """
        return self.blame

    def submit(self, receiver: Any, ctx: Any = None) -> Any:
        """Ask the receiver for its iterator. The receiver owns the answer."""
        return receiver.iter_with(self, ctx)


# -- the iterable a loop runs item by item ------------------------------------
#
# A loop has one mechanism (#7757 new 6): its reduction runs its items one by
# one where it holds every member of the iterable, within the one unroll
# budget (``sugar_source_tree.nodes.LOOP_UNROLL_BUDGET``), and runs as its
# recurrence everywhere else.  The rewrite never unrolls a loop or a
# comprehension, and never decides how many items there are.


def in_hand_iterable(iterable):
    """``iterable`` as the reduction holds its members, for a loop
    (``LoopRecurrenceSugar``) or a comprehension (``ComprehensionSugar``)
    to run item by item: what a completed ``range(...)`` call over ground
    ``int`` operands returned is the tuple of the ints it yields; any other
    value is itself.

    On every face ``range(...)`` completes on it returned a range object
    (``source_call_resolution._range_object``: its halts are the call's own
    faces, decided by the cited fold over ground operands), and iterating
    one is CPython's own (``range_iter``) and never raises, so its items are
    exactly ``range(*ints)``, as iterating that tuple yields them.  A range
    with more items than the unroll budget (or more than an index holds)
    stays the range object: the loop over it runs as its recurrence."""
    from sugar_source_tree.nodes import LOOP_UNROLL_BUDGET

    from sugar_lift_py_tests.floor.builtin_container_method import _ground_int
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.source_call_resolution import _range_object

    if not _range_object(iterable) or iterable.keyword_names:
        return iterable
    ints = []
    for value in iterable.arg_values:
        ground = _ground_int(value)
        if ground is None:
            return iterable
        ints.append(ground)
    if not 1 <= len(ints) <= 3 or (len(ints) == 3 and ints[2] == 0):
        return iterable
    items = range(*ints)
    try:
        count = len(items)
    except OverflowError:
        return iterable
    if count > LOOP_UNROLL_BUDGET:
        return iterable
    return TupleValue(tuple(TermValue(item) for item in items))


def in_hand_members(iterable):
    """The members a loop (``LoopRecurrenceSugar``) or a comprehension
    (``ComprehensionSugar``) over ``iterable`` runs item by item, in the
    order iterating it yields them, or ``None``: the one gate of the one
    item runner (``advance_in_hand``, #7757 new 6).

    In hand is where the reduction holds every member in iteration order,
    within the one unroll budget: a list or tuple whose contents are current,
    a projected list comprehension (``comprehension_sugar._finite_members``), the
    ints a ground ``range(...)`` yields (``in_hand_iterable``), or a dict
    whose contents are current and whose keys are decided distinct (its
    insertion order, as ``DictValue.iter_with`` answers).  Iterating any of
    them is decided never to raise (``iteration_total``), so no ``iter`` is
    submitted, as ``iterated`` submits none.

    Anything else is not in hand and runs as the recurrence or the symbolic
    fold, over the one iterator path (``iterated``, ``stepped``): a
    symbolic value, a call's result, a generator, a container whose contents
    are not current, an instance, a ``str``/``bytes``/``set`` (whose order
    the floor does not hold), a dict whose keys are not decided distinct,
    and an iterator object (iterating it consumes it, and the reduction does
    not advance the object every other reader holds)."""
    from sugar_source_tree.nodes import LOOP_UNROLL_BUDGET

    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.iterator_value import (
        ListIteratorValue,
        TupleIteratorValue,
    )
    from sugar_lift_py_tests.floor.membership import decided_distinct
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.sugar.comprehension_sugar import _finite_members

    from sugar_lift_py_tests.floor.comprehension_value import (
        ComprehensionValue,
        _is_set_coordinate,
    )

    iterable = in_hand_iterable(iterable)
    if isinstance(iterable, (ListIteratorValue, TupleIteratorValue)):
        return None
    if isinstance(iterable, ComprehensionValue) and _is_set_coordinate(
        iterable.term
    ):
        # A set comprehension's members are held in the order they were
        # inserted, not the order iterating the set yields (its hash
        # table's, which the floor does not decide), as for a set display.
        return None
    members = _finite_members(iterable)
    if members is None and type(iterable) is DictValue and contents_current(iterable):
        keys = tuple(key for key, _value in iterable.entries)
        if decided_distinct(keys):
            members = keys
    if members is None or len(members) > LOOP_UNROLL_BUDGET:
        return None
    return tuple(members)


def in_hand_iterator(members):
    """The iterator the one item runner steps over ``members``
    (``in_hand_members``), from its first member."""
    from sugar_lift_py_tests.floor.iterator_value import TupleIteratorValue

    return TupleIteratorValue(tuple(members), index=0)


def advance_in_hand(
    iterator, ctx, *, index, owner: str, site, item, exhausted, left=None, record=None
):
    """Item ``index`` of an iteration run in hand: the one item runner a
    loop and a comprehension share (#7757 new 6).

    The item's ``next`` (``NextOperation``) is submitted to ``iterator``
    (``in_hand_iterator``, or what the previous item's ``next`` advanced it
    to) and read arm by arm.  Its authenticated ``StopIteration`` is the
    iteration's own end: it is consumed and the iteration leaves as
    ``exhausted()``, beneath its guard and faces.  Any other halt leaves as
    ``left(halt)`` (as itself when none is handed).  Its value runs the item:
    ``item(value, advanced)``, where ``advanced`` is the iterator the next
    item steps.  ``record`` is the record a statement's halt carries
    (``halts_recorded``); an expression's offers none.  A ``next`` that is
    neither one value nor a named exception is refused: an in-hand iterator
    always answers one or the other."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.iterator_value import NextResult
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
    from sugar_lift_py_tests.sugar.function_universe_sugar import halts_recorded
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        _is_authenticated_stop_iteration,
    )

    outcome = _require_exit_set(
        NextOperation(owner=owner, blame=site).submit(iterator, ctx),
        owner=f"{owner}.next",
    )
    if record is not None:
        outcome = halts_recorded(outcome, record)
    if outcome.exits and outcome.halts() == outcome.exits:
        effect = outcome.exits[0].effect
        if (
            len(outcome.exits) == 1
            and isinstance(effect, RaiseEffect)
            and _is_authenticated_stop_iteration(effect)
        ):
            return outcome.and_then(
                ExitSet.completed, consume=lambda _stop: exhausted()
            )
        if left is None:
            return outcome
        return outcome.and_then(ExitSet.completed, consume=left)
    next_result = outcome.completed_value()
    # A NextResult owing something has no linear place for the debt: it is
    # refused with every other shape, never carried on without it.
    if not isinstance(next_result, NextResult) or outcome.owed_items():
        raise TypeError("NextOperation must produce NextResult or a named exception")
    return item(next_result.value, next_result.advanced)


# -- the one iterator path of an iteration the reduction does not step -------
#
# A ``for`` run as its recurrence (``LoopRecurrenceSugar._desugar_with_iterable``)
# and a comprehension's symbolic fold (``ComprehensionSugar._after_iterable``)
# iterate an iterable whose members are not in hand.  Both run ``iter`` on it
# once (``iterated``), then a ``next`` per item (``stepped``): each answers
# here, the one way, and neither has a second form.


def iteration_total(iterable) -> bool:
    """Whether ``iter(iterable)`` and each ``next`` of it are decided never
    to raise: the iterable is an exact finite container in hand
    (``comprehension_sugar._finite_members``), or a value whose iteration is
    CPython's own and cannot raise
    (``source_call_resolution.iterates_without_raising``: a ``str``,
    ``bytes``, ``list``, ``tuple``, ``set`` or ``dict``, an evaluated
    list/set/dict comprehension, or what a completed ``range(...)`` call
    returned, a range object).  Such an iteration states no ``iter`` halt
    and no ``next`` halt.

    A container whose contents are not current
    (``object_identity.contents_stale``) is not: its ``iter`` is the
    undecided read its own receiver answers (``ListValue.iter_with``).
    Anything else -- a formal, any other call's result, an instance, any
    symbolic value -- has its ``iter`` submitted to it (``iterated``)."""
    from sugar_lift_py_tests.floor.object_identity import contents_stale
    from sugar_lift_py_tests.source_call_resolution import iterates_without_raising
    from sugar_lift_py_tests.sugar.comprehension_sugar import _finite_members

    if contents_stale(iterable):
        return False
    return _finite_members(iterable) is not None or iterates_without_raising(iterable)


def iterated(iterable, ctx, *, owner: str, site):
    """``iter(iterable)``, run once before any item: the one ``iter``
    operation (``IteratorOperation``), submitted to the receiver, which owns
    the answer.  A receiver whose ``__iter__`` is not decided here -- a
    formal's included (#7757 NEW-1) -- is the one two-faced undecided read
    (``FloorValue.undecided_iteration``);
    an instance's is its class's ``__iter__``, called.  The iteration is what
    follows the face ``iter`` completes on, whose value is the iterator
    ``stepped`` steps; the face it raises on leaves before any item.

    Where the iteration is decided never to raise (``iteration_total``) no
    ``iter`` is submitted -- several decided receivers answer ``iter_with``
    with a construction gap (a set: its order is not authenticated; a
    ``str``: no iterator floor), and nothing but whether ``iter`` can raise
    is read off it here: it completes, holding no iterator."""
    from sugar_lift_py_tests.outcome import ExitSet

    if iteration_total(iterable):
        return ExitSet.completed(None)
    return IteratorOperation(owner=owner, blame=site).submit(iterable, ctx)


def stepped(
    iterable,
    iterator,
    ctx,
    follow,
    *,
    owner: str,
    site,
    exhausted=None,
    record=None,
    left=None,
):
    """Each ``next`` of an iteration the reduction does not step, as one
    symbolic step of ``iterator`` (what ``iterated`` completed with), and
    ``follow()`` -- the item, the fold -- on the faces it goes on by.

    An iterator's ``__next__`` (a generator's body, a user ``__next__``, a
    file) may raise something other than ``StopIteration`` on any step, so
    the step has three faces (#7757, a halt is never dropped): its
    ``StopIteration`` (the iteration ends: ``exhausted()``, ``follow()`` when
    none is handed), its value (``follow()``), and its halt, which leaves as
    ``left(halt)`` (as itself when none is handed).  It is the one ``next``
    operation (``NextOperation``) submitted to the iterator, which owns the
    answer: an iterator whose ``__next__`` is not decided here is the one
    two-faced undecided read (``FloorValue.undecided_next``: its value under
    ``python:next_op.completes``, its undecided raise owed under the
    complement); an instance's is its class's ``__next__``, called, whose
    authenticated ``StopIteration`` is the iteration ending.  ``record`` is
    the record a statement's halt carries (``halts_recorded``); an
    expression's offers none.

    No step is submitted where the iteration's type is decided and its
    ``__next__`` cannot raise: an iteration decided never to raise
    (``iteration_total``), a decided builtin iterable whose contents are not
    current (``source_call_resolution.iterates_without_raising``: a list,
    tuple, ``str``, ``bytes``, set or dict iterator), or a decided builtin
    iterator (``ListIteratorValue``, ``TupleIteratorValue``)."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.iterator_value import (
        ListIteratorValue,
        TupleIteratorValue,
    )
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
    from sugar_lift_py_tests.source_call_resolution import iterates_without_raising
    from sugar_lift_py_tests.sugar.function_universe_sugar import halts_recorded
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        _is_authenticated_stop_iteration,
    )

    if (
        iteration_total(iterable)
        or iterates_without_raising(iterable)
        or isinstance(iterator, (ListIteratorValue, TupleIteratorValue))
    ):
        return follow()
    if exhausted is None:
        exhausted = follow
    step = NextOperation(owner=owner, blame=site).submit(iterator, ctx)
    if record is not None:
        step = halts_recorded(step, record)

    def halted(halt):
        effect = halt.effect
        if isinstance(effect, RaiseEffect) and _is_authenticated_stop_iteration(effect):
            return exhausted()
        return None if left is None else left(halt)

    def compose(outcome):
        return outcome.and_then(lambda _value: follow(), consume=halted)

    if isinstance(step, NativeOperationExitCarrierV1):
        return step.after_discharge(
            lambda projected: compose(
                _require_exit_set(projected, owner=f"{owner}.next")
            )
        )
    return compose(_require_exit_set(step, owner=f"{owner}.next"))
