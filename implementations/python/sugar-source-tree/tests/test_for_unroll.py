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
    invs = _invs("def A(z):\n    for x in [1, 2, 3]:\n        assert x == z\n    return z\n")
    assert len(invs) == 3
    assert [i.args[0].value for i in invs] == [1, 2, 3]  # x = each element
    assert all(i.name == "py.eq" and i.args[1].name == "z" for i in invs)


def test_empty_concrete_for_states_nothing():
    invs = _invs("def A(z):\n    for x in []:\n        assert x == z\n    return z\n")
    assert invs == ()


def test_symbolic_iterable_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z, xs):\n    for x in xs:\n        assert x == z\n    return z\n").sugar()


def test_loop_carried_accumulator_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z):\n    t = 0\n    for x in [1, 2]:\n        t = t + x\n    return t\n").sugar()


def test_tuple_target_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z):\n    for a, b in [(1, 2)]:\n        assert a == b\n    return z\n").sugar()


if __name__ == "__main__":
    test_concrete_for_unrolls_the_body_per_element()
    test_empty_concrete_for_states_nothing()
    test_symbolic_iterable_stays_loud()
    test_loop_carried_accumulator_stays_loud()
    test_tuple_target_stays_loud()
    print("ok: concrete for unrolls; symbolic/carried/tuple-target loud")
