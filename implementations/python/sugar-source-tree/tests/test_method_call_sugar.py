"""The attribute callee: `<receiver>.<name>(<args>)` -- the census's largest
family (61%). A composition: receiver reduces like any value; the call stands as
the method coordinate `call:<name>(receiver, args)`; chains compose; the
receiver rides as runtime_dispatch_receiver for a future type-aware dig."""

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


def test_method_call_is_the_method_coordinate():
    t = _out("def A(z):\n    return z.bit_length()\n")
    assert t.name == "call:bit_length"
    assert t.args[0].name == "z"  # the receiver is the first coordinate operand


def test_method_chains_compose():
    # z.get(k).strip() -> call:strip(call:get(z, k))
    t = _out("def A(z, k):\n    return z.get(k).strip()\n")
    assert t.name == "call:strip"
    inner = t.args[0]
    assert inner.name == "call:get"
    assert inner.args[0].name == "z" and inner.args[1].name == "k"


def test_assert_consumes_the_coordinate():
    inv = _fn("def A(s):\n    assert s.upper() == s\n    return s\n").sugar().desugar().value.invs()[0]
    assert inv.name == "py.eq"
    assert inv.args[0].name == "call:upper"


def test_keyword_args_stay_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z):\n    return z.get(1, default=2)\n").sugar()


def test_computed_callee_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(fs, x):\n    return fs[0](x)\n").sugar()


if __name__ == "__main__":
    test_method_call_is_the_method_coordinate()
    test_method_chains_compose()
    test_assert_consumes_the_coordinate()
    test_keyword_args_stay_loud()
    test_computed_callee_stays_loud()
    print("ok: method calls -- coordinate, chains, assert; kwargs/computed loud")
