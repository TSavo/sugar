"""A positional call on a reduced call result carries that result as address."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var


def _site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def test_call_result_is_the_receiver_first_call_coordinate() -> None:
    value = reduce_value(
        "type(self)(dtype)",
        binds={
            "self": SymbolicValue(make_var("self")),
            "dtype": SymbolicValue(make_var("dtype")),
        },
    )

    assert isinstance(value, CallSiteValue)
    receiver = ctor("call:type", [make_var("self")])
    assert value.target_name == "__call__"
    assert value.arg_values[0].to_term(owner="test") == receiver
    assert value.term == ctor("call:__call__", [receiver, make_var("dtype")])


def test_keyword_and_expansion_call_result_shapes_stay_loud() -> None:
    for expression in (
        "factory()(value=1)",
        "factory()(*args)",
        "factory()(**kwargs)",
    ):
        with pytest.raises(FactoryPanic):
            build_node(
                ast.parse(expression, mode="eval").body,
                filename="t.py",
                role=SugarRole.TERM,
            )


def test_call_result_owner_is_exactly_the_positional_call_callee_partition() -> None:
    catalog = default_catalog()

    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.TERM, _site("factory()(value)")
        )
    ] == ["CallResultCallSugar"]
    for expression in ("f(value)", "dispatch[key](value)", "factory()(value=1)"):
        assert "CallResultCallSugar" not in [
            candidate.name
            for candidate in catalog.candidates_for(SugarRole.TERM, _site(expression))
        ]
