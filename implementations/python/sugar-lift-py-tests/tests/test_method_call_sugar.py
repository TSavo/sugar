"""MethodCallSugar: recv.m(args) is call:m(recv, *args).

Composes on the AttributeSugar / CallSugar coordinate family. Disjoint from
plain-name CallSugar and OsSugar's os.exit.
"""

from __future__ import annotations

import ast

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar


def _site(expr: str):
    node = ast.parse(expr, mode="eval").body
    return SourceFragment.from_node(node, "t.py")


def test_method_call_reduces_to_call_method_coordinate() -> None:
    """(1) recv.m(a) -> CallSiteValue(call:m(recv, a))."""
    value = reduce_value("z.m(3)", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "m"
    assert value.term == ctor("call:m", [make_var("z"), num(3)])


def test_method_name_and_args_discriminate_the_coordinate() -> None:
    """(2) Different method name or arg produces a different term."""
    m = reduce_value("z.m(3)", binds={"z": SymbolicValue(make_var("z"))})
    n = reduce_value("z.n(3)", binds={"z": SymbolicValue(make_var("z"))})
    m4 = reduce_value("z.m(4)", binds={"z": SymbolicValue(make_var("z"))})
    assert m.term == ctor("call:m", [make_var("z"), num(3)])
    assert n.term == ctor("call:n", [make_var("z"), num(3)])
    assert m4.term == ctor("call:m", [make_var("z"), num(4)])
    assert m.term != n.term
    assert m.term != m4.term


def test_owns_method_call_not_plain_name_or_os_exit() -> None:
    """(3) owns fires on recv.m(); not on f() or os.exit()."""
    assert MethodCallSugar.owns(_site("z.m()")) is True
    assert MethodCallSugar.owns(_site("z.m(1, 2)")) is True
    assert MethodCallSugar.owns(_site("f(1)")) is False
    assert MethodCallSugar.owns(_site("os.exit(0)")) is False

    catalog = default_catalog()
    method_cands = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("z.m(1)"))
    ]
    plain_cands = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("f(1)"))
    ]
    exit_cands = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("os.exit(0)"))
    ]
    assert "MethodCallSugar" in method_cands
    assert "CallSugar" not in method_cands
    assert "MethodCallSugar" not in plain_cands
    assert "CallSugar" in plain_cands
    assert "MethodCallSugar" not in exit_cands
    assert "OsSugar" in exit_cands


def test_keyword_method_call_rides_the_coordinate() -> None:
    # Keyword VALUES ride the method coordinate (not dropped). **kwargs
    # expansion stays a loud gap -- see test_call_kwargs_sugar.py.
    value = reduce_value("z.m(a=1)", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "call:m", [make_var("z"), ctor("kw", [str_const("a"), num(1)])]
    )
    assert value.parameters == ("a",)


def test_zero_arg_method_call() -> None:
    value = reduce_value("z.copy()", binds={"z": SymbolicValue(make_var("z"))})
    assert value.term == ctor("call:copy", [make_var("z")])
