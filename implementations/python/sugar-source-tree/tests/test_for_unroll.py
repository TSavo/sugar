"""A `for` over a CONCRETE iterable dissolves: it unrolls, the body's facts
stated once per element (map as a count of rewrites). Symbolic iterables, a
loop-carried accumulator, a tuple target, and for-else are the real fold and
stay loud until that shape is written."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _invs(src):
    return _fn(src).sugar().desugar().value.invs()


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


def test_symbolic_assert_only_loop_is_a_universal():
    # for x in xs: assert P(x)  over a symbolic (formal) xs is the degenerate
    # fold -- forall x. member(x, xs) -> P(x). The loop no longer sinks the
    # function; it emits its FOL universal.
    inv = _invs(
        "def A(z, xs):\n    for x in xs:\n        assert x == z\n    return z\n"
    )[0]
    assert inv.kind == "forall"
    body = inv.body  # member(x, xs) -> (x == z)
    assert body.kind == "implies"
    assert body.operands[0].name == "py.in"  # member(x, xs)
    assert body.operands[1].name == "py.eq"  # x == z


def test_symbolic_carried_accumulator_is_a_fold_coordinate():
    # t = 0; for x in xs: t = t + x; return t  over a symbolic xs is the fold:
    # the carried t rebinds to the coordinate py.fold.Add(0, xs) -- a reference
    # the dig resolves (the recurrence), the same shape as a recursion's call:f.
    post = (
        _fn(
            "def A(xs):\n    total = 0\n    for x in xs:\n        total = total + x\n    return total\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    fold = post.args[1]
    assert fold.name == "call:py.fold.Add"
    assert fold.args[0].value == 0  # init
    assert fold.args[1].name == "xs"  # iterable


def test_accumulator_referencing_assert_stays_loud():
    # for x in xs: assert total > 0; total = total + x  -- the assert references
    # the RUNNING accumulator (point 3, a real loop invariant), still loud.
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(xs):\n    total = 0\n    for x in xs:\n        assert total == 0\n"
            "        total = total + x\n    return total\n"
        ).sugar()


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
