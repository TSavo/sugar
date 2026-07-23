"""Keyword arguments and spreads ride the call bridge coordinate faithfully."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
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


def test_named_call_spread_builds_explicit_bridge_operand():
    t = _out("def A(x, d):\n    return f(x, **d)\n")

    assert t.name == "call:f"
    spread = t.args[-1]
    assert spread.name == "python:double_starred_kwarg"
    assert spread.args[0].name == "d"


def test_named_call_positional_spread_builds_reference_bridge_operand():
    t = _out("def A(xs):\n    return f(0, *xs)\n")

    assert t.name == "call:f"
    spread = t.args[-1]
    assert spread.name == "python:starred_arg"
    assert spread.args[0].name == "xs"


def test_spread_call_discriminates_the_wrapped_value():
    left = _out("def A(xs, ys):\n    return f(*xs)\n")
    right = _out("def A(xs, ys):\n    return f(*ys)\n")

    assert left.args[0].name == "python:starred_arg"
    assert right.args[0].name == "python:starred_arg"
    assert left.args[0].args[0].name == "xs"
    assert right.args[0].args[0].name == "ys"
    assert left != right


def test_same_spelling_keyword_is_not_admitted_as_double_spread():
    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    term = CallSiteSugar(
        target_name="f",
        args=(),
        keywords=(("**", NameSugar(name="d", site="lying")),),
        site="lying",
    ).desugar().value.to_term(owner="lying")

    assert term.args[0].name == "py.kwarg"
    assert term.args[0].args[0].value == "**"
    assert term.args[0].name != "python:double_starred_kwarg"


def test_contextless_spread_value_stays_a_loud_floor_gap():
    from sugar_lift_py_tests.floor.spread_value import SpreadValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.ir import make_var

    lying = SpreadValue(SymbolicValue(make_var("xs")))
    with pytest.raises(ConstructionPanic):
        lying.to_term(owner="no enclosing spread role")
