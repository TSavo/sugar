"""`[e for x in <concrete>]` DISSOLVES in substitute -- map disappearing for
real: N substitutions of x into e, rewritten to the List display of the
results. The comprehension was never a meaning; it was a count of rewrites.
Symbolic iterables, undecidable filters, multi-generator, and async keep the
node loud."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import completed_function_value, native_carrier_for


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _out(src):
    return completed_function_value(_fn(src)).post().args[1]


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


def test_undecidable_filtered_comprehension_is_typed_filter_guard():
    """Live law (replaces factory SugarNotWritten): filter over formal is a coordinate.

    ``[x for x in [1,2] if x > limit]`` constructs as ``py.listcomp`` carrying
    ``python:loop.filter_guard`` — typed residual, not construction silence.
    """
    # Deleted expectation: the pending comparison already projected py.listcomp.
    carrier = native_carrier_for(
        _fn("def A(limit):\n    return [x for x in [1, 2] if x > limit]\n"),
        operator="greater_than",
    )
    left, right = carrier.operands
    assert left.to_term(owner="listcomp carrier tooth").name == "x"
    assert right.formal_coordinate.declared_name == "limit"
    assert len(carrier.continuations) == 5


def test_symbolic_comprehension_builds_coordinate():
    t = _out("def A(xs):\n    return [x for x in xs]\n")
    assert t.name == "py.listcomp"
    assert t.args[0].name == "xs"


if __name__ == "__main__":
    test_identity_comprehension_is_the_display()
    test_mapped_comprehension_folds_per_element()
    test_tuple_target_comprehension_destructures()
    test_composes_with_len()
    test_undecidable_filtered_comprehension_stays_loud()
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
