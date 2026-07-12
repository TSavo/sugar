"""A subscript-selected callable is an address-bearing call receiver."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num


def _site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def test_subscript_selected_callable_carries_receiver_coordinate() -> None:
    value = reduce_value(
        "dispatch[key](3)",
        binds={
            "dispatch": SymbolicValue(make_var("dispatch")),
            "key": SymbolicValue(make_var("key")),
        },
    )

    assert isinstance(value, CallSiteValue)
    receiver = ctor("py.subscript", [make_var("dispatch"), make_var("key")])
    assert value.target_name == "__call__"
    assert value.arg_values[0].to_term(owner="test") == receiver
    assert value.term == ctor("call:__call__", [receiver, num(3)])


def test_other_computed_callee_shapes_stay_loud() -> None:
    for expression in ("factory()(3)", "(lambda x: x)(3)"):
        with pytest.raises(FactoryPanic):
            build_node(
                ast.parse(expression, mode="eval").body,
                filename="t.py",
                role=SugarRole.TERM,
            )


def test_subscript_call_owner_is_exactly_the_subscript_callee_partition() -> None:
    catalog = default_catalog()

    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.TERM, _site("dispatch[key](3)")
        )
    ] == ["SubscriptCallSugar"]
    assert "SubscriptCallSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("f(3)"))
    ]
    assert "SubscriptCallSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("f()(3)"))
    ]
