"""A guarded value's two arms are siblings: both are evaluated (#7757).

Found by #8123, #7827 item 1.  ``GuardedValue``'s distribution helpers
(``_map``, ``_map_over``, ``_predicate``, ``predicate_from_left``,
``map_from_left``) returned as soon as one arm's exits all halted, so the
other arm was never evaluated and its faces -- its completions and its own
halts -- were dropped.  A halt is never dropped: each arm's outcome stands
under its own polarity, joined by ``ExitSet.union``.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import GuardedValue, StringValue, TermValue, TupleValue
from sugar_lift_py_tests.ir import atomic, not_
from sugar_lift_py_tests.operations.subscript_operation import discharge_subscript
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Subscript
from sugar_source_tree.tree import SourceFile


def _site():
    source = "def helper(xs, key):\n    return xs[key]\n"
    tree = SourceFile(
        (source, "guarded-siblings.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, Subscript)).fragment


def _tuple(*values: int) -> TupleValue:
    return TupleValue(tuple(TermValue(value) for value in values))


def _read(receiver, index, site):
    return discharge_subscript(receiver, index, site, None, owner="SubscriptSugar")


def _halts(outcome) -> set:
    return {
        (face.guard, face.effect.exception_name)
        for face in outcome.exits
        if isinstance(face, Halted)
    }


def _completions(outcome) -> set:
    return {
        (face.guard, face.value)
        for face in outcome.exits
        if isinstance(face, Completed)
    }


def _raise_and_complete(guarded, site):
    """The true arm raises (an ``IndexError``), the false arm completes with
    ``1``; ``guarded`` only selects the arm handed to ``operate``."""
    raised = _read(_tuple(), TermValue(0), site)
    assert _halts(raised) and not _completions(raised), raised

    def operate(arm):
        return raised if arm is guarded.when_true else ExitSet.completed(TermValue(1))

    return operate


# ---------------------------------------------------------------------------
# _map: one arm raises, the other completes
# ---------------------------------------------------------------------------


def test_a_raising_true_arm_keeps_the_false_arms_completion() -> None:
    """``(() if c else (5,))[0]``: ``IndexError`` under ``c``, ``5`` under
    ``not c``.  Before, the true arm's halt returned at once and the false
    arm's read never ran."""
    site = _site()
    guard = atomic("chosen", [])

    outcome = _read(GuardedValue(guard, _tuple(), _tuple(5)), TermValue(0), site)

    assert _halts(outcome) == {(guard, "IndexError")}, outcome
    assert _completions(outcome) == {(not_(guard), TermValue(5))}, outcome


def test_a_raising_false_arm_keeps_the_true_arms_completion() -> None:
    site = _site()
    guard = atomic("chosen", [])

    outcome = _read(GuardedValue(guard, _tuple(5), _tuple()), TermValue(0), site)

    assert _halts(outcome) == {(not_(guard), "IndexError")}, outcome
    assert _completions(outcome) == {(guard, TermValue(5))}, outcome


# ---------------------------------------------------------------------------
# _map_over: a guarded operand's arms are siblings too
# ---------------------------------------------------------------------------


def test_a_guarded_index_whose_true_arm_raises_keeps_the_false_arms_read() -> None:
    """``(x if c else y)[9 if d else 0]`` with ``x = (5,)``, ``y = (6,)``:
    the ``9`` read raises on both receiver arms (under ``d``); the ``0`` read
    completes (under ``not d``)."""
    site = _site()
    receiver_guard = atomic("chosen", [])
    index_guard = atomic("indexed", [])
    receiver = GuardedValue(receiver_guard, _tuple(5), _tuple(6))
    index = GuardedValue(index_guard, TermValue(9), TermValue(0))

    outcome = _read(receiver, index, site)

    assert _halts(outcome) == {(index_guard, "IndexError")}, outcome
    assert _completions(outcome) == {
        (not_(index_guard), GuardedValue(receiver_guard, TermValue(5), TermValue(6)))
    }, outcome


def test_both_arms_raising_keep_both_raises() -> None:
    """``(x if c else y)[0 if d else "a"]`` with ``x = y = ()``: ``IndexError``
    under ``d`` and ``TypeError`` under ``not d``.  Before, only the first
    arm's ``IndexError`` stood."""
    site = _site()
    receiver_guard = atomic("chosen", [])
    index_guard = atomic("indexed", [])
    receiver = GuardedValue(receiver_guard, _tuple(), _tuple())
    index = GuardedValue(index_guard, TermValue(0), StringValue("a"))

    outcome = _read(receiver, index, site)

    assert not _completions(outcome), outcome
    assert _halts(outcome) == {
        (index_guard, "IndexError"),
        (not_(index_guard), "TypeError"),
    }, outcome


# ---------------------------------------------------------------------------
# _predicate, predicate_from_left, map_from_left
# ---------------------------------------------------------------------------


def test_a_predicate_whose_true_arm_raises_keeps_the_false_arm() -> None:
    site = _site()
    guard = atomic("chosen", [])
    guarded = GuardedValue(guard, TermValue(0), TermValue(1))

    outcome = guarded._predicate(
        _raise_and_complete(guarded, site),
        operation="truth",
        operand=site,
        blame=site,
    )

    assert _halts(outcome) == {(guard, "IndexError")}, outcome
    assert _completions(outcome) == {(not_(guard), TermValue(1))}, outcome


def test_a_predicate_from_left_whose_true_arm_raises_keeps_the_false_arm() -> None:
    site = _site()
    guard = atomic("chosen", [])
    guarded = GuardedValue(guard, TermValue(0), TermValue(1))

    outcome = guarded.predicate_from_left(
        _raise_and_complete(guarded, site), site, operation="less_than"
    )

    assert _halts(outcome) == {(guard, "IndexError")}, outcome
    assert _completions(outcome) == {(not_(guard), TermValue(1))}, outcome


def test_a_map_from_left_whose_true_arm_raises_keeps_the_false_arm() -> None:
    site = _site()
    guard = atomic("chosen", [])
    guarded = GuardedValue(guard, TermValue(0), TermValue(1))

    outcome = guarded.map_from_left(
        _raise_and_complete(guarded, site), site, operation="add"
    )

    assert _halts(outcome) == {(guard, "IndexError")}, outcome
    assert _completions(outcome) == {(not_(guard), TermValue(1))}, outcome
