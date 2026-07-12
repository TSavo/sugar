from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SliceValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def test_slice_sugar_reduces_bounds_to_slice_value():
    subscript = ast.parse("values[1:3:2]", mode="eval").body
    site = SourceFragment.from_node(subscript, "t.py").subscript_index()
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    value = complete_value(
        ctx.build_body(site, SugarRole.TERM).reduce(ctx), owner="test"
    )

    assert value == SliceValue(TermValue(1), TermValue(3), TermValue(2))


def test_slice_sugar_preserves_missing_bounds():
    subscript = ast.parse("values[:]", mode="eval").body
    site = SourceFragment.from_node(subscript, "t.py").subscript_index()
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    value = complete_value(
        ctx.build_body(site, SugarRole.TERM).reduce(ctx), owner="test"
    )

    assert value == SliceValue(None, None, None)


def test_slice_sugar_preserves_symbolic_bound_coordinates():
    subscript = ast.parse("values[start:stop]", mode="eval").body
    site = SourceFragment.from_node(subscript, "t.py").subscript_index()
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    temporal = (
        TemporalContext.empty()
        .bind_value("start", SymbolicValue(make_var("start")))
        .bind_value("stop", SymbolicValue(make_var("stop")))
    )
    ctx = replace(ctx, temporal=temporal)

    value = complete_value(
        ctx.build_body(site, SugarRole.TERM).reduce(ctx), owner="test"
    )

    assert value == SliceValue(
        SymbolicValue(make_var("start")),
        SymbolicValue(make_var("stop")),
        None,
    )


def test_unliftable_slice_bound_panics_naming_the_bound():
    function = ast.parse("def f():\n    return values[(yield 1):]\n").body[0]
    slice_node = function.body[0].value.slice
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    with pytest.raises(FactoryPanic) as raised:
        build_node(slice_node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert raised.value.info.to_json()["observed"] == "Yield"


def test_slice_owners_are_disjoint_by_observed_shape_and_ordered_subscript():
    from sugar_lift_py_tests.sugar.slice_subscript_sugar import SliceSubscriptSugar
    from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar

    subscript = SourceFragment.from_node(
        ast.parse("values[1:3]", mode="eval").body, "t.py"
    )
    slice_site = subscript.subscript_index()
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    assert SliceSugar.owns(slice_site)
    assert not SliceSugar.owns(subscript)
    assert SliceSubscriptSugar.owns(subscript)
    assert not SliceSubscriptSugar.owns(slice_site)
    built = build_node(subscript, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert type(built.sugar).__name__ == "SliceSubscriptSugar"
    assert built.audit_row.candidates == ["SliceSubscriptSugar"]
