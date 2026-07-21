"""A `while` over CONCRETE state dissolves: each iteration is one more
substitution, the condition ground-decided structurally against the carried
state. `while True:` exhausts the fuel (an infinite concrete loop is a
non-termination the unroll must not fake) and a symbolic condition keeps the
node -- both land loud, honest unwritten segments."""

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


def _out(src):
    return _fn(src).sugar().desugar().value.post().args[1]


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


def test_symbolic_condition_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(n):\n    i = 0\n    while i < n:\n        i = i + 1\n    return i\n").sugar()


if __name__ == "__main__":
    test_concrete_counter_unrolls()
    test_concrete_accumulator_unrolls()
    test_false_condition_skips_the_body()
    test_while_true_stays_loud()
    test_symbolic_condition_stays_loud()
    print("ok: concrete while unrolls; True/symbolic loud")
