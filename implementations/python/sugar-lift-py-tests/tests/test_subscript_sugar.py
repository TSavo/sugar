"""Subscript construction and floor projection tests."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import (
    IndexErrorRuntimeEffect,
    KeyErrorRuntimeEffect,
    SubscriptResultRuntimeEffect,
)
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComprehensionValue,
    PredicateValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num, py_eq
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


def test_comprehension_subscript_keeps_a_proof_bearing_coordinate() -> None:
    receiver = ComprehensionValue(ctor("py.list_comp", [make_var("items")]))

    value = reduce_value("values[0]", binds={"values": receiver})

    assert type(value) is CallSiteValue
    assert value.term == ctor(
        "py.subscript", [ctor("py.list_comp", [make_var("items")]), num(0)]
    )


def test_predicate_subscript_stays_a_named_authenticated_runtime_effect() -> None:
    receiver = PredicateValue(py_eq(make_var("left"), make_var("right")))

    outcome = _outcome("result[0]", binds={"result": receiver})

    assert type(outcome) is Incomplete
    assert type(outcome.effect) is SubscriptResultRuntimeEffect
    assert outcome.effect.witness.operation.name == "py.subscript"
    assert outcome.effect.witness.site.filename == "t.py"
    assert "PredicateValue runtime result shape" in outcome.effect.reason


def test_callsite_index_rides_the_subscript_coordinate_without_forcing_a_body() -> None:
    value = reduce_value("z[indexer()]", binds={"z": SymbolicValue(make_var("z"))})

    assert type(value) is CallSiteValue
    assert value.term == ctor("py.subscript", [make_var("z"), ctor("call:indexer", [])])


def test_literal_slice_index_selects_the_narrow_slice_owner() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("z[1:2]", mode="eval").body
    body = ctx.build_body(node, SugarRole.TERM)

    assert type(body.sugar).__name__ == "SliceSubscriptSugar"


def test_dynamic_slice_is_a_citable_subscript_coordinate() -> None:
    value = reduce_value(
        "arr[i:i + n]",
        binds={
            "arr": SymbolicValue(make_var("arr")),
            "i": SymbolicValue(make_var("i")),
            "n": SymbolicValue(make_var("n")),
        },
    )

    assert isinstance(value, CallSiteValue)
    assert value.term.name == "py.subscript"
    assert value.term.args[1].name == "py.slice"


def test_tuple_slice_is_a_citable_multidimensional_coordinate() -> None:
    value = reduce_value(
        "table[:, i]",
        binds={
            "table": SymbolicValue(make_var("table")),
            "i": SymbolicValue(make_var("i")),
        },
    )

    assert isinstance(value, CallSiteValue)
    assert value.term.name == "py.subscript"
    assert value.term.args[1].name == "tuple"
    assert value.term.args[1].args[0].name == "py.slice"


def test_dynamic_slice_and_tuple_slice_have_structural_owners() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    dynamic = ctx.build_body(
        ast.parse("arr[i:i + n]", mode="eval").body, SugarRole.TERM
    )
    multidimensional = ctx.build_body(
        ast.parse("table[:, i]", mode="eval").body, SugarRole.TERM
    )

    assert type(dynamic.sugar).__name__ == "SliceSubscriptSugar"
    assert type(multidimensional.sugar).__name__ == "SubscriptSugar"
