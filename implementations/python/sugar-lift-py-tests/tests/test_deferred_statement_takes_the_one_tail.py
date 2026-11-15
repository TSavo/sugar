"""Step 6 (reduce), #7757: a deferred statement takes the block's one tail.

A statement whose operation waits on its caller's actual
(``NativeOperationExitCarrierV1``) had a branch of its own in the block
reducer: it retained the statement's projection and returned, so what every
other statement gets once its exits are known was skipped. The statement now
waits for its exits and takes the same tail
(``reduce_block_to_exitset``, ``leaves``).

The twin is at the reduction level, over the function's own proof: with no
caller, each operation on a formal is its unanswered two faces, which is the
only place an ``if`` on a formal and a later operation on another formal are
both undecided. Through the solver the same source owes its ``undecided``
members and reads ``open`` on both halves, so the solver cannot tell them
apart.

``f``: ``if c: return 1`` then ``y = -x`` then ``return 2``.

TRUTHFUL: where ``c`` held the function returned 1, whatever ``-x`` does. So
the return is a completed face of its own, and the halt of ``-x`` holds only
where the ``if`` did not return.

LYING: the return face dropped. ``-x`` halts the function wherever it does not
complete, ``c`` unstated: an arm that says "halted" where Python returned 1.
That is what the deferred branch stated, and it must not be stated.

``g``: the same ``if`` before ``if flag: assert claim``. A halt of the
``assert`` carries the suite's own record; the block splices what ran before
the ``if flag`` in front of it, as it does for any nested statement's halt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

SOURCE = """\
def f(c, x):
    if c:
        return 1
    y = -x
    return 2


def g(c, flag, claim):
    if c:
        return 1
    if flag:
        assert claim
    return 2
"""

COMPLETED = "completed"
# A halt whose record holds the ``if``'s ``return``: it left after the ``if``.
HALTED_AFTER = "halted after the if"
HALTED_BEFORE = "halted before the if"

RETURNED = "where the if returned"
WENT_ON = "where the if did not return"
UNSTATED = "the if unstated"


def _own_proof(tmp_path: Path, name: str):
    """``name``'s outcome as its own proof states it: every operation on a
    formal is its unanswered two faces
    (``tree_enumerate.as_its_own_proof_states``)."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "deferred_tail.py").write_text(SOURCE, encoding="utf-8")
    source_file = open_source_file_for_construction(
        root / "deferred_tail.py", root=root
    )
    (function,) = [fn for fn in source_file.functions() if fn.name == name]
    return function_universe_outcome(function)


def _conjuncts(guard) -> tuple:
    if getattr(guard, "kind", None) == "and":
        return tuple(
            literal for operand in guard.operands for literal in _conjuncts(operand)
        )
    return (guard,)


def _returns_before(arm) -> tuple:
    """The guarded ``return`` entries in a halted arm's record."""
    return tuple(
        entry
        for entry in getattr(arm.state, "entries", ())
        if isinstance(entry, GuardedReturn)
    )


def _faces(outcome) -> list[tuple[str, str]]:
    """Each arm as ``(what it is, where it holds against the if's return)``.

    The guard the ``if``'s ``return 1`` was taken under is read off the
    record of a halt that left after it (the first ``GuardedReturn`` there);
    an arm holds where the ``if`` returned when its guard states that guard,
    where it did not when its guard states the negation, and leaves the
    ``if`` unstated otherwise."""
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    halts = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    after = [arm for arm in halts if _returns_before(arm)]
    assert after, f"no halt left after the if's return: {outcome!r}"
    taken = _returns_before(after[0])[0].guards
    assert taken

    def position(arm) -> str:
        literals = _conjuncts(arm.guard)
        if all(guard in literals for guard in taken):
            return RETURNED
        if any(not_(guard) in literals for guard in taken):
            return WENT_ON
        return UNSTATED

    faces = []
    for arm in outcome.exits:
        if isinstance(arm, Completed):
            kind = COMPLETED
        elif _returns_before(arm):
            kind = HALTED_AFTER
        else:
            kind = HALTED_BEFORE
        faces.append((kind, position(arm)))
    return sorted(faces)


def test_the_truthful_half_states_the_return_beside_the_deferred_halt(
    tmp_path: Path,
) -> None:
    """TRUTHFUL: both faces. The earlier ``return`` is a completed face where
    the ``if`` returned, and ``-x``'s halt holds only where it did not."""
    faces = _faces(_own_proof(tmp_path, "f"))

    assert (COMPLETED, RETURNED) in faces, faces
    assert [face for face in faces if face[0] == HALTED_AFTER] == [
        (HALTED_AFTER, WENT_ON)
    ], faces
    # The function went on past the ``if`` only where it did not return.
    assert (COMPLETED, WENT_ON) in faces, faces


def test_the_lying_half_that_drops_the_return_face_is_not_stated(
    tmp_path: Path,
) -> None:
    """LYING: the return face dropped, the halt unrestricted. The deferred
    branch stated exactly these arms; none of them may stand."""
    lying = {
        (COMPLETED, UNSTATED),
        (HALTED_AFTER, UNSTATED),
        (HALTED_BEFORE, UNSTATED),
    }

    faces = _faces(_own_proof(tmp_path, "f"))

    assert set(faces) != lying, faces
    # The halt of ``-x`` never holds where the ``if`` returned.
    assert (HALTED_AFTER, UNSTATED) not in faces, faces
    assert (HALTED_AFTER, RETURNED) not in faces, faces
    # And no completion leaves the ``if`` unstated beside a halt that states
    # it: the arm that ran ``-x`` is where the ``if`` did not return.
    assert (COMPLETED, UNSTATED) not in faces, faces


def test_a_halt_inside_a_deferred_statement_carries_what_ran_before_it(
    tmp_path: Path,
) -> None:
    """SPLICED: every halt of ``if flag: assert claim`` left after the first
    ``if``, so its record holds that ``if``'s ``return`` and its guard states
    the ``if`` did not return. The one halt before it is ``bool(c)``'s."""
    faces = _faces(_own_proof(tmp_path, "g"))

    halts = [face for face in faces if face[0] != COMPLETED]
    assert halts.count((HALTED_BEFORE, UNSTATED)) == 1, faces
    after = [face for face in halts if face[0] == HALTED_AFTER]
    # ``bool(flag)``, ``bool(claim)`` and the failed ``assert``.
    assert len(after) == len(halts) - 1 and len(after) >= 2, faces
    assert set(after) == {(HALTED_AFTER, WENT_ON)}, faces
    assert (COMPLETED, RETURNED) in faces, faces
