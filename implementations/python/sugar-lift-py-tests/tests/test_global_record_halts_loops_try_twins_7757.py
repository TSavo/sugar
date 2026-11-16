"""Twins: a module global a call changed is read as the call left it on the
call's halted face, after a live loop, and after a ``try`` (#7757 H7).

#9108 made every call that may reach a module global leave a record, so a
later call reads a mutable global as ``python:after(<call>, "global:G")``,
and made an ``if`` join the record under its arms' guards.  Two gaps stayed
open:

- a call that changed the global and then raised left no record on its
  halted face, so a handler (or a ``finally``) handed the global to a later
  call as it was before the call (``call_site_value.bind_after_call`` now
  records the halt where the call halted, with the same record);
- a record a call made inside a live loop's item went with the item's
  context, so after ``for _ in xs: bump()`` a later call read the global as
  it stood before the loop (``LoopRecurrenceSugar._records_made_here`` now
  publishes the records the loop made as it leaves, and the recurrence's
  symbolic item begins from the loop's record of the globals,
  ``_global_recurrence``).

A ``try`` keeps each route as its own face, each in the context it left in
(``try_sugar._try_outcome``), so the record a route made stands on that
route alone.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)


_BUMP = "def bump():\n    G[0] = 2\n\n\n"
_BUMP_THEN_RAISE = "def bump_then_raise():\n    G[0] = 2\n    raise ValueError()\n\n\n"
_READER = "def h():\n    return G[0]\n\n\n"
_TEST = "def test_f():\n    assert {claim}\n"


# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # (1) The callee changes ``G`` and raises; the handler hands ``G`` to a
    # later call, which must read what the callee left.
    "call-changes-then-raises-handler-calls-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP_THEN_RAISE
        + _READER
        + "def f():\n"
        "    try:\n"
        "        bump_then_raise()\n"
        "    except ValueError:\n"
        "        return h()\n"
        "    return 0\n\n\n" + _TEST,
        "f() == 2",
        "f() == 1",
    ),
    # (1') The same, read in the handler's own frame.
    "call-changes-then-raises-handler-reads-the-global": (
        "G = [1]\n\n\n"
        + _BUMP_THEN_RAISE
        + "def f():\n"
        "    try:\n"
        "        bump_then_raise()\n"
        "    except ValueError:\n"
        "        return G[0]\n"
        "    return 0\n\n\n" + _TEST,
        "f() == 2",
        "f() == 1",
    ),
    # (2) A call in a live loop over a formal (the recurrence): after the
    # loop the global is what the items left, never the pre-loop ``[1]``.
    "call-in-a-loop-over-a-formal-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f(xs):\n"
        "    for _ in xs:\n"
        "        bump()\n"
        "    return h()\n\n\n" + _TEST,
        "f([0]) == 2",
        "f([0]) == 1",
    ),
    # (2') A call in a live loop run in hand: the item's record leaves with
    # the loop.
    "call-in-a-loop-in-hand-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f():\n"
        "    for _ in [0]:\n"
        "        bump()\n"
        "    return h()\n\n\n" + _TEST,
        "f() == 2",
        "f() == 1",
    ),
    # (3) A call in a ``try`` body, the global read by a call in the
    # ``finally``: on the completed body the record stands, on the halted
    # face the call's halt carries it.
    "call-in-try-then-a-reader-in-finally": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f():\n"
        "    r = 0\n"
        "    try:\n"
        "        bump()\n"
        "    finally:\n"
        "        r = h()\n"
        "    return r\n\n\n" + _TEST,
        "f() == 2",
        "f() == 1",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_global_a_halted_looped_or_tried_call_changed_is_never_read_as_before(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(
        result.prove_doc,
        claims_from_line=_claims_line(text),
        lift_doc=result.lift_doc,
    )
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def test_a_halt_is_the_other_face_of_its_call_only() -> None:
    """``_its_other_face``: the halt of the one two-faced outcome, under the
    complement of the completion atom (with or without the prefix the call
    was reached under), never a halt that is no face of the call."""
    from sugar_lift_py_tests.floor.call_site_value import _its_other_face
    from sugar_lift_py_tests.ir import and_, atomic, make_var, not_

    completes = atomic("python:unknown_callee_call.completes", [make_var("r")])
    reached = atomic("python:reached", [make_var("p")])
    assert _its_other_face(not_(completes), completes)
    assert _its_other_face(and_([reached, not_(completes)]), and_([reached, completes]))
    assert not _its_other_face(not_(reached), completes)
    assert not _its_other_face(reached, and_([reached, completes]))
