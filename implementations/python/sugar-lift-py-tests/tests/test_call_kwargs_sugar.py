"""Keyword-argument calls carry their kwarg VALUES on the call coordinate.

CallSugar / MethodCallSugar own has-keyword Calls (partitioned from
positional-only shapes they already owned, and from OsSugar's os.exit).
Keyword names ride in CallSiteValue.parameters; values ride in the ctor args
after positionals. **kwargs expansion stays a loud FactoryPanic gap.
"""

from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.sugar.call_sugar import CallSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar


def _site(expr: str):
    node = ast.parse(expr, mode="eval").body
    return SourceFragment.from_node(node, "t.py")


# ---------------------------------------------------------------------------
# (1) positive: keyword values ride the call coordinate
# ---------------------------------------------------------------------------


def test_plain_keyword_call_carries_kwarg_value() -> None:
    """f(x=1) -> CallSiteValue(call:f(1)) with parameters=('x',)."""
    value = reduce_value("f(x=1)")
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor("call:f", [num(1)])
    assert value.parameters == ("x",)


def test_method_keyword_call_carries_kwarg_value() -> None:
    """obj.m(axis=1) -> call:m(obj, 1) with parameters=('axis',)."""
    value = reduce_value(
        "z.m(axis=1)", binds={"z": SymbolicValue(make_var("z"))}
    )
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "m"
    assert value.term == ctor("call:m", [make_var("z"), num(1)])
    assert value.parameters == ("axis",)


def test_mixed_positional_and_keyword_values() -> None:
    """f(1, y=2) appends the keyword VALUE after the positional."""
    value = reduce_value("f(1, y=2)")
    assert value.term == ctor("call:f", [num(1), num(2)])
    assert value.parameters == ("y",)


# ---------------------------------------------------------------------------
# (2) discrimination: keyword VALUE is carried, not dropped
# ---------------------------------------------------------------------------


def test_keyword_value_discriminates_the_coordinate() -> None:
    """f(x=1) and f(x=2) produce DIFFERENT terms -- the kwarg value rides."""
    one = reduce_value("f(x=1)")
    two = reduce_value("f(x=2)")
    assert one.term == ctor("call:f", [num(1)])
    assert two.term == ctor("call:f", [num(2)])
    assert one.term != two.term


def test_keyword_name_rides_in_parameters() -> None:
    """Different keyword NAME is recorded in parameters (not dropped)."""
    x = reduce_value("f(x=1)")
    y = reduce_value("f(y=1)")
    # Values alone would collide; names stay in parameters.
    assert x.term == y.term == ctor("call:f", [num(1)])
    assert x.parameters == ("x",)
    assert y.parameters == ("y",)
    assert x.parameters != y.parameters


def test_method_keyword_value_discriminates() -> None:
    one = reduce_value(
        "z.m(axis=1)", binds={"z": SymbolicValue(make_var("z"))}
    )
    two = reduce_value(
        "z.m(axis=2)", binds={"z": SymbolicValue(make_var("z"))}
    )
    assert one.term != two.term
    assert one.term == ctor("call:m", [make_var("z"), num(1)])
    assert two.term == ctor("call:m", [make_var("z"), num(2)])


# ---------------------------------------------------------------------------
# (3) structural: owns partitions cleanly vs positional / os.exit
# ---------------------------------------------------------------------------


def test_owns_keyword_not_positional_or_os_exit() -> None:
    """CallSugar owns f(x=1); MethodCallSugar owns z.m(a=1); not each other's
    positional shapes; not os.exit."""
    assert CallSugar.owns(_site("f(x=1)")) is True
    assert CallSugar.owns(_site("f(1, y=2)")) is True
    assert CallSugar.owns(_site("f(1)")) is True  # still owns positional
    assert CallSugar.owns(_site("z.m(a=1)")) is False
    assert CallSugar.owns(_site("os.exit(0)")) is False

    assert MethodCallSugar.owns(_site("z.m(a=1)")) is True
    assert MethodCallSugar.owns(_site("z.m(1, inplace=True)")) is True
    assert MethodCallSugar.owns(_site("z.m(1)")) is True  # still owns positional
    assert MethodCallSugar.owns(_site("f(x=1)")) is False
    assert MethodCallSugar.owns(_site("os.exit(0)")) is False

    catalog = default_catalog()
    plain_kw = [c.name for c in catalog.candidates_for(SugarRole.TERM, _site("f(x=1)"))]
    method_kw = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("z.m(a=1)"))
    ]
    plain_pos = [c.name for c in catalog.candidates_for(SugarRole.TERM, _site("f(1)"))]
    method_pos = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("z.m(1)"))
    ]
    exit_cands = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("os.exit(0)"))
    ]
    assert "CallSugar" in plain_kw
    assert "MethodCallSugar" not in plain_kw
    assert "MethodCallSugar" in method_kw
    assert "CallSugar" not in method_kw
    assert "CallSugar" in plain_pos
    assert "MethodCallSugar" in method_pos
    assert "OsSugar" in exit_cands
    assert "MethodCallSugar" not in exit_cands


def test_kwargs_expansion_stays_a_loud_gap() -> None:
    """f(**k) / z.m(**k) are unowned -- FactoryPanic, not silent drop."""
    assert CallSugar.owns(_site("f(**k)")) is False
    assert MethodCallSugar.owns(_site("z.m(**k)")) is False
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("f(**k)")
    assert raised.value.info.observed == "Call"
    with pytest.raises(FactoryPanic) as raised_m:
        reduce_value("z.m(**k)", binds={"z": SymbolicValue(make_var("z"))})
    assert raised_m.value.info.observed == "Call"
