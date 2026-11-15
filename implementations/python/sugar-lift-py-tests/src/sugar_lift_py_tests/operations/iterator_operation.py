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


def discharge_iter(receiver, site, ctx, *, owner: str = "project_iter"):
    """Production projector body: established ``iter_with`` floor edge, under
    the caller's context."""
    return IteratorOperation(owner=owner, blame=site).submit(receiver, ctx)


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
    the answer.  A formal's is the ``iter`` carrier its caller's actual
    discharges; any other receiver whose ``__iter__`` is not decided here is
    the one two-faced undecided read (``FloorValue.undecided_iteration``);
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
    ``python:next.completes``, its undecided raise owed under the
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
