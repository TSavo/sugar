"""The computed callee: `<callee>(<args>)` where the callee is an expression
rather than a bare name or attribute (`fs[0](x)`, `d["k"](x)`). A COMPOSITION:
the callee reduces like any value through whatever sugar its own node built
(SubscriptSugar for `fs[0]`), and the call stands as the coordinate
`py.call(callee, args)`. A callee whose node has no sugar (a Lambda called
inline) stays loud through the ordinary recursion -- this sugar never masks
that gap."""

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


def test_computed_call_is_the_py_call_coordinate():
    t = _out("def A(fs, x):\n    return fs[0](x)\n")
    assert t.name == "py.call"
    callee = t.args[0]
    assert callee.name == "py.subscript"  # fs[0], the callee operand
    assert t.args[1].name == "x"  # the argument


def test_assert_consumes_the_coordinate():
    inv = (
        _fn("def A(fs, x):\n    assert fs[0](x) == x\n    return x\n")
        .sugar()
        .desugar()
        .value.invs()[0]
    )
    assert inv.name == "py.eq"
    assert inv.args[0].name == "py.call"


def test_discrimination_differs_by_callee_operand():
    # fs[0](x) vs fs[1](x) -- same shape, different callee coordinate.
    t0 = _out("def A(fs, x):\n    return fs[0](x)\n")
    t1 = _out("def A(fs, x):\n    return fs[1](x)\n")
    assert t0.name == t1.name == "py.call"
    assert t0.args[0] != t1.args[0]  # the callee subscript differs
    assert t0 != t1


def test_lambda_callee_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(x):\n    return (lambda z: z)(x)\n").sugar()


if __name__ == "__main__":
    test_computed_call_is_the_py_call_coordinate()
    test_assert_consumes_the_coordinate()
    test_discrimination_differs_by_callee_operand()
    test_lambda_callee_stays_loud()
    print("ok: computed callee calls -- coordinate, assert, discrimination, lambda loud")
