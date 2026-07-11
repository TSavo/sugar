"""SubscriptSugar: `x[i]` folds concrete containers, halts out-of-range / missing
key as named runtime effects, and coordinates symbolic receivers as
ctor("py.subscript", [recv, index]). Slice indexes stay a loud factory gap."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import IndexErrorRuntimeEffect, KeyErrorRuntimeEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import Incomplete


def _outcome(expr: str, binds: dict | None = None):
    from dataclasses import replace

    from sugar_lift_py_tests.temporal import TemporalContext

    node = ast.parse(expr, mode="eval").body
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    if binds:
        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = replace(ctx, temporal=temporal)
    return ctx.build_body(node, SugarRole.TERM).reduce(ctx)


def test_list_subscript_folds_to_element() -> None:
    assert reduce_value("[10,20,30][1]") == TermValue(20)


def test_string_subscript_folds_to_one_char() -> None:
    assert reduce_value('"abc"[0]') == StringValue("a")


def test_list_subscript_out_of_range_is_index_error() -> None:
    outcome = _outcome("[1,2][5]")
    assert type(outcome) is Incomplete
    assert type(outcome.effect) is IndexErrorRuntimeEffect


def test_dict_subscript_folds_to_value() -> None:
    assert reduce_value('{"k":9}["k"]') == TermValue(9)


def test_dict_subscript_missing_key_is_key_error() -> None:
    outcome = _outcome('{"k":9}["missing"]')
    assert type(outcome) is Incomplete
    assert type(outcome.effect) is KeyErrorRuntimeEffect


def test_symbolic_receiver_is_py_subscript_coordinate() -> None:
    value = reduce_value("z[0]", binds={"z": SymbolicValue(make_var("z"))})
    assert type(value) is CallSiteValue
    assert value.term == ctor("py.subscript", [make_var("z"), num(0)])


def test_slice_index_stays_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("z[1:2]", mode="eval").body
    with pytest.raises(FactoryPanic):
        ctx.build_body(node, SugarRole.TERM)
