"""Concrete While dissolves; clean symbolic While constructs fold/invariant."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.tree_enumerate import audit_file_gaps
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _out(src):
    return _fn(src).sugar().desugar().value.post().args[1]


def _invs(src):
    return _fn(src).sugar().desugar().value.invs()


def _while_gaps(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    _sf, gaps = audit_file_gaps(path)
    return [(node, panic) for node, panic in gaps if node.kind == "While"]


def test_concrete_counter_unrolls():
    # i = 0; while i < 3: i = i + 1; return i  ->  out == 3
    assert _out("def A():\n    i = 0\n    while i < 3:\n        i = i + 1\n    return i\n").value == 3


def test_concrete_accumulator_unrolls():
    # sum 0..3 through a while: out == 6
    assert _out(
        "def A():\n    i = 0\n    t = 0\n    while i < 4:\n        t = t + i\n"
        "        i = i + 1\n    return t\n"
    ).value == 6


def test_false_condition_skips_the_body():
    assert _out("def A():\n    i = 5\n    while False:\n        i = 9\n    return i\n").value == 5


def test_while_true_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    i = 0\n    while True:\n        i = i + 1\n    return i\n").sugar()


def test_symbolic_single_accumulator_is_a_conditioned_fold_coordinate():
    post = _fn(
        "def A(n):\n    i = 0\n    while i < n:\n        i = i + 1\n    return i\n"
    ).sugar().desugar().value.post()
    fold = post.args[1]
    assert fold.name == "call:py.while.fold"
    assert fold.args[0].value == 0
    assert fold.args[1].name == "py.lt"
    assert fold.args[2].name == "+"


def test_symbolic_call_update_remains_a_nested_dig_coordinate():
    post = _fn(
        "def A(limit):\n    state = seed\n    while state != limit:\n"
        "        state = step(state)\n    return state\n"
    ).sugar().desugar().value.post()
    fold = post.args[1]
    assert fold.name == "call:py.while.fold"
    assert fold.args[1].name == "py.not"
    assert fold.args[2].name == "call:step"


def test_symbolic_assert_only_while_is_a_guarded_invariant():
    inv = _invs(
        "def A(active, value):\n    while active:\n"
        "        assert value == value\n    return value\n"
    )[0]
    assert inv.kind == "implies"
    assert inv.operands[0].name == "py.truthy"
    assert inv.operands[1].name == "py.eq"


if __name__ == "__main__":
    test_concrete_counter_unrolls()
    test_concrete_accumulator_unrolls()
    test_false_condition_skips_the_body()
    test_while_true_stays_loud()
    test_symbolic_single_accumulator_is_a_conditioned_fold_coordinate()
    test_symbolic_assert_only_while_is_a_guarded_invariant()
    test_while_else_splices_after_the_exit()
    print("ok: concrete While unrolls; clean symbolic While builds")


def test_while_else_splices_after_the_exit():
    # The unroll exits only via condition-false; with no break, else always runs.
    src = (
        "def A():\n    i = 0\n    while i < 2:\n        i = i + 1\n"
        "    else:\n        i = i + 100\n    return i\n"
    )
    assert _out(src).value == 102


@pytest.mark.parametrize(
    "src",
    (
        "def A():\n    i = 0\n    while i < 2:\n        i = i + 1\n    return i\n",
        "def A(n):\n    i = 0\n    while i < n:\n        i = i + 1\n    return i\n",
        "def A(active, value):\n    while active:\n"
        "        assert value == value\n    return value\n",
        "def A(limit):\n    state = seed\n    while state != limit:\n"
        "        state = step(state)\n    return state\n",
    ),
    ids=("concrete", "symbolic-fold", "assert-invariant", "call-fold"),
)
def test_admitted_while_shapes_leave_no_production_gap(src):
    assert _while_gaps(src) == []


@pytest.mark.parametrize(
    "src",
    (
        "def A(n):\n    i = 0\n    while i < n:\n        break\n    return i\n",
        "def A(n):\n    i = 0\n    while i < n:\n        continue\n    return i\n",
        "def A(n):\n    i = 0\n    total = 0\n    while i < n:\n"
        "        total = total + i\n        i = i + 1\n    return total\n",
        "def A(n):\n    i = 0\n    while i < n:\n"
        "        assert i == i\n        i = i + 1\n    return i\n",
        "def A(n):\n    i = 0\n    while i < n:\n        i = i + 1\n"
        "    else:\n        i = 100\n    return i\n",
        "def A(active):\n    while active:\n        consume(active)\n    return active\n",
        "def A():\n    i = 0\n    while i < 129:\n        i = i + 1\n    return i\n",
    ),
    ids=(
        "break",
        "continue",
        "multi-carried",
        "mixed",
        "symbolic-else",
        "effect",
        "over-fuel",
    ),
)
def test_hard_while_shapes_report_exact_production_gap(src):
    gaps = _while_gaps(src)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is SugarNotWritten
