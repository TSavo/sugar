"""`[e for x in <concrete>]` DISSOLVES in substitute -- map disappearing for
real: N substitutions of x into e, rewritten to the List display of the
results. The comprehension was never a meaning; it was a count of rewrites.
Symbolic iterables, filters (ifs), multi-generator, and async keep the node
(loud until their segments are written)."""

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


def test_identity_comprehension_is_the_display():
    t = _out("def A():\n    return [x for x in [1, 2, 3]]\n")
    assert t.name == "array" and [a.value for a in t.args] == [1, 2, 3]


def test_mapped_comprehension_folds_per_element():
    t = _out("def A():\n    return [x + 10 for x in [1, 2]]\n")
    assert [a.value for a in t.args] == [11, 12]


def test_tuple_target_comprehension_destructures():
    t = _out("def A():\n    return [a + b for a, b in [(1, 2), (3, 4)]]\n")
    assert [a.value for a in t.args] == [3, 7]


def test_composes_with_len():
    t = _out("def A():\n    return len([x for x in [1, 2, 3]])\n")
    assert t.name == "call:len"


def test_filtered_comprehension_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    return [x for x in [1, 2] if x == 1]\n").sugar()


def test_symbolic_comprehension_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(xs):\n    return [x for x in xs]\n").sugar()


if __name__ == "__main__":
    test_identity_comprehension_is_the_display()
    test_mapped_comprehension_folds_per_element()
    test_tuple_target_comprehension_destructures()
    test_composes_with_len()
    test_filtered_comprehension_stays_loud()
    test_symbolic_comprehension_stays_loud()
    test_comprehension_over_range_dissolves()
    print("ok: the concrete comprehension dissolves to its display")


def test_comprehension_over_range_dissolves():
    # [x + 1 for x in range(3)] -> array(1, 2, 3). Also the regression for the
    # borrowed-helper crash: ListComp borrows For's readers, and every internal
    # call must be class-explicit (an unbound self._helper AttributeError'd on
    # real pandas code, arrow/accessors.py).
    t = _out("def A():\n    return [x + 1 for x in range(3)]\n")
    assert t.name == "array" and [a.value for a in t.args] == [1, 2, 3]
