"""A `for` over a CONCRETE iterable runs in hand: the reduction runs the
body once per member through the loop's one item runner, the body's facts
stated once per element (#7757 new 6, #8957). No rewrite unrolls it.
Symbolic iterables run as the loop's recurrence. A target that does not
destructure its member is the positional unpack's own ``ValueError`` halt,
as in Python.

Each file is opened through the one construction door under a workspace
root, as the lift opens it: the iteration's own ``StopIteration`` and a
ground exit cite a workspace-relative locus."""

import tempfile
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_source_tree.panic import SugarNotWritten

from native_carrier_testimony import undecided_function_value


def _fn(src):
    root = Path(tempfile.mkdtemp(prefix="for-unroll-"))
    path = root / "subject.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _invs(src):
    function = _fn(src)
    outcome = function.sugar().desugar()
    if isinstance(outcome, ExitSet) and outcome.completed_value() is not None:
        return outcome.completed_value().invs()
    # Each loop-body equality over the formal is the undecided equality's two
    # faces: the universe completes under their completes atoms (#7757 NEW-1).
    return undecided_function_value(function, owner="UndecidedCompare:Eq").invs()


def _returned(src):
    return _fn(src).sugar().desugar().completed_value().post().args[1].value


def _only_halt(outcome, exception_name):
    """Every arm of ``outcome`` halts, and each halt is the ``exception_name``
    Python raises: nothing completes past it."""
    assert isinstance(outcome, ExitSet), outcome
    assert outcome.exits and outcome.halts() == outcome.exits, outcome.exits
    assert not any(isinstance(exit_, Completed) for exit_ in outcome.exits)
    assert all(
        isinstance(halt.effect, RaiseEffect)
        and halt.effect.exception_name == exception_name
        for halt in outcome.halts()
    ), outcome.halts()


def test_concrete_for_unrolls_the_body_per_element():
    invs = _invs(
        "def A(z):\n    for x in [1, 2, 3]:\n        assert x == z\n    return z\n"
    )
    assert len(invs) == 3
    # Each is the undecided ``==``, keyed per evaluation (#7757 NEW-1):
    # the truth of ``python:compare_result("Eq", x, z, <key>)``, one key per
    # item.
    assert all(i.name == "python:truth_result" for i in invs)
    compared = [i.args[0] for i in invs]
    assert [c.args[1].value for c in compared] == [1, 2, 3]  # x = each element
    assert all(
        c.name == "python:compare_result"
        and c.args[0].value == "Eq"
        and c.args[2].name == "z"
        for c in compared
    )
    assert len({c.args[-1] for c in compared}) == 3
    assert len({i.args[-1] for i in invs}) == 3


def test_empty_concrete_for_states_nothing():
    invs = _invs("def A(z):\n    for x in []:\n        assert x == z\n    return z\n")
    assert invs == ()


def test_symbolic_assert_only_loop_is_loop_recurrence():
    """Live law (replaces factory forall-in-invs): symbolic for is LoopRecurrenceSugar.

    The factory-era emit of ``forall x. member(x, xs) -> P(x)`` into invs is
    retired. Live construction is ``LoopRecurrenceSugar`` (see
    ``test_live_loop_post_projection`` for step/post face algebra).
    """
    sugar = _fn(
        "def A(z, xs):\n    for x in xs:\n        assert x == z\n    return z\n"
    ).sugar()
    assert type(sugar.statements[0]).__name__ == "LoopRecurrenceSugar"


def test_symbolic_carried_accumulator_is_the_recurrences_value():
    """Live law (replaces py.fold.Add on linear .value.post): ExitSet + recurrence.

    A symbolic loop publishes what a concrete one does: the carried total is
    bound under its binding coordinate to the recurrence's value of it, so
    the read after the loop is ``python:loop.recurrence``, never a term no
    publication bound.
    """
    function = _fn(
        "def A(xs):\n    total = 0\n    for x in xs:\n        total = total + x\n    return total\n"
    )
    loop = next(
        statement
        for statement in function.sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet)
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert completed
    post = completed[0].value.post()
    # out = python:loop.recurrence(loop, total's binding coordinate)
    assert post.name == "="
    assert post.args[1].name == "python:loop.recurrence"
    assert post.args[1].args[0].value == loop.target_cid
    assert post.args[1].args[1].value in loop.binding_coordinate_cids


def test_accumulator_referencing_assert_constructs_as_loop_recurrence():
    """Live law (replaces factory SugarNotWritten): assert on carried total is recurrence."""
    sugar = _fn(
        "def A(xs):\n    total = 0\n    for x in xs:\n        assert total == 0\n"
        "        total = total + x\n    return total\n"
    ).sugar()
    assert any(type(s).__name__ == "LoopRecurrenceSugar" for s in sugar.statements)


def test_loop_carried_accumulator_folds_over_a_concrete_iterable():
    # t = 0; for x in [1,2,3]: t = t + x; return t  -- each item reads what the
    # previous one handed on, so the run in hand returns 6.
    assert (
        _returned(
            "def A():\n    t = 0\n    for x in [1, 2, 3]:\n        t = t + x\n    return t\n"
        )
        == 6
    )


def test_tuple_target_destructures_the_concrete_element():
    # for a, b in [(1, 2), (3, 4)]: each member destructures into the
    # target's names, so the fold is 1*2 + 3*4.
    assert (
        _returned(
            "def A():\n    t = 0\n    for a, b in [(1, 2), (3, 4)]:\n"
            "        t = t + a * b\n    return t\n"
        )
        == 14
    )


def test_a_ground_false_assert_in_a_destructured_item_is_the_assertion_halt():
    # The first item binds a = 1, b = 2: ``assert a == b`` is decided false,
    # so the function raises AssertionError there. The halt is kept and no
    # item's claim is stated as an invariant past it.
    _only_halt(
        _fn(
            "def A(z):\n    for a, b in [(1, 2), (3, 4)]:\n        assert a == b\n    return z\n"
        )
        .sugar()
        .desugar(),
        "AssertionError",
    )


def test_starred_target_binds_or_is_refused_by_name():
    # for a, *b in [(1, 2)]: Python binds a = 1, b = [2], and ``assert a == a``
    # holds. The reduction either runs it to that completion with no halt, or
    # refuses the target by name; it never binds a wrong shape.
    function = _fn(
        "def A(z):\n    for a, *b in [(1, 2)]:\n        assert a == a\n    return z\n"
    )
    try:
        outcome = function.sugar().desugar()
    except SugarNotWritten:
        return
    assert isinstance(outcome, ExitSet), outcome
    assert not outcome.halts(), outcome.halts()
    assert outcome.completed_value() is not None, outcome.exits


def test_arity_mismatch_is_the_unpack_value_error_halt():
    # the target has two names, the element three: running it is Python's
    # ValueError, the positional unpack's own halt (#8957). It is never a
    # wrong shape bound and never a completion.
    _only_halt(
        _fn(
            "def A(z):\n    for a, b in [(1, 2, 3)]:\n        assert a == b\n    return z\n"
        )
        .sugar()
        .desugar(),
        "ValueError",
    )


def test_jump_bearing_body_unrolls_with_exact_break_exit():
    # break is consumed at its owning loop.  It must not duplicate the jump
    # or apply later elements: Python's exact post is 1.
    assert (
        _returned(
            "def A():\n    t = 0\n    for x in [1, 2, 3]:\n        t = t + x\n        break\n    return t\n"
        )
        == 1
    )


def test_for_else_splices_after_the_unroll():
    # No break: the else ALWAYS runs, after the items.
    assert (
        _returned(
            "def A():\n    t = 0\n    for x in [1, 2]:\n        t = t + x\n"
            "    else:\n        t = t + 100\n    return t\n"
        )
        == 103
    )
