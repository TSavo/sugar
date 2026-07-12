"""Defaulted positional functions own their defaults and bind omitted calls."""

from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, UniverseValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import ctor, eq, make_var, num
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import complete_value


def _build_function(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    return build_node(node, filename="t.py", role=SugarRole.DEFINITION, ctx=ctx), ctx


def _reduce_call(source: str, call: str) -> CallSiteValue:
    function = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    ctx = replace(ctx, name_resolver={"f": function})
    result = build_node(
        ast.parse(call).body[0].value,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert type(value) is CallSiteValue
    return value


def test_defaulted_function_is_owned_and_binds_all_formals() -> None:
    result, ctx = _build_function("def f(a, b=1):\n    return a + b\n")
    assert result.audit_row.selected == "FunctionDefSugar"
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert type(value) is UniverseValue
    assert value.formals == ("a", "b")
    assert value.post() == eq(
        make_var("out"), ctor("+", [make_var("a"), make_var("b")])
    )


def test_omitted_default_and_explicit_argument_discriminate() -> None:
    source = "def f(a, b=1):\n    return a + b\n"
    omitted = _reduce_call(source, "f(3)")
    explicit = _reduce_call(source, "f(3, 5)")
    assert omitted.parameters == ("a", "b")
    assert [value.to_term(owner="test") for value in omitted.arg_values] == [
        num(3),
        num(1),
    ]
    assert [value.to_term(owner="test") for value in explicit.arg_values] == [
        num(3),
        num(5),
    ]


def test_inner_assertion_in_defaulted_def_is_not_silent() -> None:
    source = "def f(a, b=1):\n    assert a == 3\n    return a + b\n"
    payload = lift_file_payload(source, "t.py").to_rpc()
    axis = account_lift_coverage(census_source(source, file="t.py"), payload).to_json()[
        "assertions"
    ]
    assert axis["stated"] == 1
    assert axis["lifted_cited"] + axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0


@pytest.mark.parametrize(
    "source",
    [
        "def f(a, *args):\n    return a\n",
        "def f(a, **kwargs):\n    return a\n",
        "def f(a, *, b=1):\n    return a + b\n",
        "@decorator\ndef f(a, b=1):\n    return a + b\n",
        "def f(a, b=(lambda x=1: x)):\n    return a\n",
    ],
)
def test_unowned_parameter_and_default_shapes_stay_loud(source: str) -> None:
    with pytest.raises(FactoryPanic):
        _build_function(source)


def test_plain_non_default_function_still_lifts() -> None:
    result, ctx = _build_function("def f(a):\n    return a\n")
    assert result.audit_row.selected == "FunctionDefSugar"
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert type(value) is UniverseValue
    assert value.formals == ("a",)
