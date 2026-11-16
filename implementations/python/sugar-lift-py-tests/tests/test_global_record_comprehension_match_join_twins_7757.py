"""Twins: a module global a call changed is read as the call left it after
a comprehension, after a ``match``, and after an ``if`` that joined one
call's different records (#7757 H14, L4).

- A comprehension over members not in hand ran its own recurrence beside
  the loop's: its item began from the globals as they stood before it, and
  it carried out only its walrus writes, so every record a member's call
  made was dropped (``_symbolic_writes`` skipped a write with no walrus
  prior).  It now begins its item from the recurrence's record of the
  globals and leaves with its calls' records by the loop's one rule
  (``loop_recurrence_sugar.entering_the_recurrence``, ``records_left``),
  each standing where some member reached it.
- In-hand comprehension members carry their records out as they were made
  (``_carried_out``); a generator consumed by a builtin is a call no
  contract states, which records every global.  Both are pinned here.
- A ``match`` keeps each case's route as its own face, so a record one case
  made stands on that case alone (pinned).
- An ``if`` whose arm reached one call on two faces joined its two records
  into a ``GuardedValue``, which the reader skipped, reading an older state
  (``call_site_sugar._global_after_call``).  Each arm's record now stands on
  its own arm (``if_sugar._records_on_their_own_arms``) and the reader reads
  the join (``call_site_value.is_call_record``).

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
_BUMP_RETURNING = "def bump_ret():\n    G[0] = 2\n    return 0\n\n\n"
_READER = "def h():\n    return G[0]\n\n\n"
_TEST = "def test_f():\n    assert {claim}\n"


# ``name: (source, ((truthful claim, lying claim), ...))``.  Braces are
# doubled: the source is a ``str.format`` template.
_SHAPES = {
    # (H14) A comprehension over a formal (the recurrence): after it the
    # global is what a member's call left -- never the entry's ``[1]`` --
    # and where no member ran, never the call's state.
    "call-in-a-comprehension-over-a-formal-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f(xs):\n"
        "    [bump() for _ in xs]\n"
        "    return h()\n\n\n" + _TEST,
        (("f([0]) == 2", "f([0]) == 1"), ("f([]) == 1", "f([]) == 2")),
    ),
    # (H14) The same with a condition: the record stands where a member
    # reached the call.
    "call-in-a-filtered-comprehension-over-a-formal-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP_RETURNING
        + _READER
        + "def f(xs):\n"
        "    [bump_ret() for x in xs if x]\n"
        "    return h()\n\n\n" + _TEST,
        (("f([1]) == 2", "f([1]) == 1"), ("f([0]) == 1", "f([0]) == 2")),
    ),
    # (H14, pinned) A comprehension whose members are in hand carries the
    # record its member's call made.
    "call-in-a-comprehension-in-hand-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f():\n"
        "    [bump() for _ in [0]]\n"
        "    return h()\n\n\n" + _TEST,
        (("f() == 2", "f() == 1"),),
    ),
    # (H14, confirmation) A generator consumed by a builtin: the builtin is
    # a call no contract states, which records every global.
    "call-in-a-generator-consumed-by-sum-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP_RETURNING
        + _READER
        + "def f(xs):\n"
        "    sum(bump_ret() for _ in xs)\n"
        "    return h()\n\n\n" + _TEST,
        (("f([0]) == 2", "f([0]) == 1"),),
    ),
    # (match, pinned) Each case carries its own record: the case that ran
    # the call reads its state, the one that did not reads the entry's.
    "call-in-one-match-case-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f(c):\n"
        "    match c:\n"
        "        case 1:\n"
        "            bump()\n"
        "    return h()\n\n\n" + _TEST,
        (("f(1) == 2", "f(1) == 1"), ("f(2) == 1", "f(2) == 2")),
    ),
    # (L4) One call reached on the two faces a ``match`` leaves in an
    # ``if`` arm: the arm's two records join, and a later call reads the
    # join -- the call's state where the arm ran, the entry's where it did
    # not.
    "one-call-on-two-faces-of-an-if-arm-then-a-reader": (
        "G = [1]\n\n\n"
        + _BUMP
        + _READER
        + "def f(c, d):\n"
        "    if c:\n"
        "        match d:\n"
        "            case 1:\n"
        "                pass\n"
        "        bump()\n"
        "    return h()\n\n\n" + _TEST,
        (
            ("f(True, 1) == 2", "f(True, 1) == 1"),
            ("f(True, 2) == 2", "f(True, 2) == 1"),
            ("f(False, 1) == 1", "f(False, 1) == 2"),
        ),
    ),
}


def _cases():
    for shape, (_source, pairs) in sorted(_SHAPES.items()):
        for index, (truthful, lying) in enumerate(pairs):
            for half, claim in (("truthful", truthful), ("lying", lying)):
                yield pytest.param(shape, claim, half, id=f"{shape}-{index}-{half}")


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize(("shape", "claim", "half"), list(_cases()))
def test_a_global_a_comprehension_or_match_changed_is_never_read_as_before(
    tmp_path: Path, shape: str, claim: str, half: str
) -> None:
    source, _pairs = _SHAPES[shape]
    text = source.format(claim=claim)
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


def _record(name):
    from sugar_lift_py_tests.floor.call_site_value import AfterCallRecordValue
    from sugar_lift_py_tests.ir import make_var

    return AfterCallRecordValue(make_var(name), ((("global", "G"), "global:G"),))


def test_a_join_of_records_is_a_record_and_stands_under_a_guard() -> None:
    """``is_call_record`` reads a join of records as one; ``record_under``
    guards each record of a join, keeping the join's selection."""
    from sugar_lift_py_tests.floor.call_site_value import (
        is_call_record,
        record_under,
    )
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import and_, atomic, make_var

    c = atomic("python:test.c", [make_var("p")])
    w = atomic("python:test.w", [make_var("q")])
    one, two = _record("r1"), _record("r2")
    join = GuardedValue(c, one, two)
    assert is_call_record(one)
    assert is_call_record(join)
    assert not is_call_record(GuardedValue(c, one, SymbolicValue(make_var("x"))))
    guarded = record_under(join, w)
    assert guarded.guard == c
    assert guarded.when_true.guard == w
    assert guarded.when_false.guard == w
    assert record_under(record_under(one, w), c).guard == and_([c, w])


def test_a_recurrence_leaves_with_its_calls_records_only() -> None:
    """``records_left``: nothing where the path made no call's record, or
    only the record the recurrence began its item from; every record, in
    order, otherwise."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        global_recurrence,
        records_left,
    )

    began = global_recurrence("target")
    call = ("k#after-call", _record("r1"))
    name = ("n", SymbolicValue(make_var("n")))
    assert records_left("target", ()) == ()
    assert records_left("target", (began, name)) == ()
    assert records_left("target", (began, name, call)) == (began, call)
