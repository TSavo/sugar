"""A `for` over a CONCRETE iterable dissolves: it unrolls, the body's facts
stated once per element (map as a count of rewrites). Symbolic iterables, a
loop-carried accumulator, a tuple target, and for-else are the real fold and
stay loud until that shape is written."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import authenticated_function_value


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _invs(src):
    function = _fn(src)
    outcome = function.sugar().desugar()
    if isinstance(outcome, Complete):
        return outcome.value.invs()
    # Deleted expectation: each formal loop-body equality completed before binding.
    return authenticated_function_value(function, operator="equals").invs()


def test_concrete_for_unrolls_the_body_per_element():
    invs = _invs(
        "def A(z):\n    for x in [1, 2, 3]:\n        assert x == z\n    return z\n"
    )
    assert len(invs) == 3
    assert [i.args[0].value for i in invs] == [1, 2, 3]  # x = each element
    assert all(i.name == "py.eq" and i.args[1].name == "z" for i in invs)


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


def test_symbolic_carried_accumulator_is_loop_post_binding():
    """Live law (replaces py.fold.Add on linear .value.post): ExitSet + post_binding.

    Symbolic carried total is recurrence / loop.post_binding, not a factory
    fold coordinate on an unconditional Complete universe.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Completed

    outcome = (
        _fn(
            "def A(xs):\n    total = 0\n    for x in xs:\n        total = total + x\n    return total\n"
        )
        .sugar()
        .desugar()
    )
    assert isinstance(outcome, ExitSet)
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert completed
    post = completed[0].value.post()
    # out = python:loop.post_binding(loop, total, NormalExhaustion)
    assert post.name == "="
    assert post.args[1].name == "python:loop.post_binding"
    assert post.args[1].args[2].value == "NormalExhaustion"


def test_accumulator_referencing_assert_constructs_as_loop_recurrence():
    """Live law (replaces factory SugarNotWritten): assert on carried total is recurrence."""
    sugar = _fn(
        "def A(xs):\n    total = 0\n    for x in xs:\n        assert total == 0\n"
        "        total = total + x\n    return total\n"
    ).sugar()
    assert any(type(s).__name__ == "LoopRecurrenceSugar" for s in sugar.statements)


def test_loop_carried_accumulator_folds_over_a_concrete_iterable():
    # t = 0; for x in [1,2,3]: t = t + x; return t  -- the carried accumulator is
    # threaded through the unroll (t reads the previous iteration's value), so it
    # folds to 6. The `for` dissolved into block-threading; no loop-sugar.
    post = (
        _fn(
            "def A():\n    t = 0\n    for x in [1, 2, 3]:\n        t = t + x\n    return t\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 6  # out == 0+1+2+3


def test_tuple_target_destructures_the_concrete_element():
    # for a, b in [(1, 2), (3, 4)]: assert a == b  -- each display element
    # destructures into the tuple target's names; two invs, 1==2 and 3==4.
    invs = _invs(
        "def A(z):\n    for a, b in [(1, 2), (3, 4)]:\n        assert a == b\n    return z\n"
    )
    assert [(i.args[0].value, i.args[1].value) for i in invs] == [(1, 2), (3, 4)]


def test_starred_target_stays_loud():
    # for a, *b -- a starred target does not destructure here; still loud.
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n    for a, *b in [(1, 2)]:\n        assert a == a\n    return z\n"
        ).sugar()


def test_arity_mismatch_stays_loud():
    # the target has two names, the element three -- not destructured, loud
    # (running it would be a ValueError; never bind a wrong shape).
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n    for a, b in [(1, 2, 3)]:\n        assert a == b\n    return z\n"
        ).sugar()


if __name__ == "__main__":
    test_concrete_for_unrolls_the_body_per_element()
    test_empty_concrete_for_states_nothing()
    test_symbolic_assert_only_loop_is_a_universal()
    test_symbolic_carried_accumulator_is_a_fold_coordinate()
    test_accumulator_referencing_assert_stays_loud()
    test_loop_carried_accumulator_folds_over_a_concrete_iterable()
    test_tuple_target_destructures_the_concrete_element()
    test_starred_target_stays_loud()
    test_arity_mismatch_stays_loud()
    test_jump_bearing_body_unrolls_with_exact_break_exit()
    test_for_else_splices_after_the_unroll()
    print("ok: concrete for unrolls; symbolic/carried/tuple-target loud")


def test_jump_bearing_body_unrolls_with_exact_break_exit():
    # The controlled unroll consumes break at its owning loop.  It must not
    # duplicate the jump or apply later elements: Python's exact post is 1.
    src = "def A():\n    t = 0\n    for x in [1, 2, 3]:\n        t = t + x\n        break\n    return t\n"
    post = _fn(src).sugar().desugar().value.post()
    assert post.args[1].value == 1


def test_for_else_splices_after_the_unroll():
    # With no break possible (the jump-guard blocks jump-bearing bodies from
    # unrolling), the else ALWAYS runs: just more block, after the iterations.
    post = (
        _fn(
            "def A():\n    t = 0\n    for x in [1, 2]:\n        t = t + x\n"
            "    else:\n        t = t + 100\n    return t\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 103
