"""Keyword arguments on calls ride the coordinate FAITHFULLY: each `name=expr`
appends a `py.kwarg(name, expr)` operand after the positionals. A `**spread`
is not one keyword and stays loud (the tree node guards it)."""

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


def test_named_call_kwarg_lifts():
    t = _out("def A(x):\n    return f(x, k=1)\n")
    assert t.name == "call:f"
    kwarg = t.args[-1]
    assert kwarg.name == "py.kwarg"
    assert kwarg.args[0].value == "k"
    assert kwarg.args[1].value == 1


def test_method_call_kwarg_lifts():
    t = _out("def A(z):\n    return z.get(1, default=2)\n")
    assert t.name == "call:get"
    kwarg = t.args[-1]
    assert kwarg.name == "py.kwarg"
    assert kwarg.args[0].value == "default"
    assert kwarg.args[1].value == 2


def test_kwarg_value_discriminates():
    t1 = _out("def A(x):\n    return f(x, k=1)\n")
    t2 = _out("def A(x):\n    return f(x, k=2)\n")
    assert t1.args[-1].args[1].value != t2.args[-1].args[1].value
    assert t1 != t2


def test_spread_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(x, d):\n    return f(x, **d)\n").sugar()
