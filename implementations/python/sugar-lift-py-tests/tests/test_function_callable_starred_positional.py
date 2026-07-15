from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    DictValue,
    ListValue,
    SymbolicValue,
    TermValue,
    TupleValue,
    UniverseValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.call_sugar import _expand_function_positional_args


def _root_universe(source: str) -> UniverseValue:
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="starred-call.py", catalog=default_catalog())
    result = build_node(
        node,
        filename="starred-call.py",
        role=SugarRole("definition"),
        ctx=ctx,
    )
    value = complete_value(result.sugar.desugar(ctx), owner="starred call regression")
    assert isinstance(value, UniverseValue)
    return value


def _star(value) -> CallSiteValue:
    return CallSiteValue(
        target_name="*",
        arg_values=(value,),
        parameters=(),
        term=ctor("py.star", [value.to_term(owner="starred test")]),
        body=None,
    )


def test_constructed_tuple_star_flattens_in_source_order_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(a, b, c, d):\n"
        "        return d\n"
        "    values = (6, 7)\n"
        "    return inner(5, *values, 8)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        TermValue(5),
        TermValue(6),
        TermValue(7),
        TermValue(8),
    )
    assert callsite.term == ctor(
        "call:inner",
        [
            num(5),
            ctor("py.star", [ctor("tuple", [num(6), num(7)])]),
            num(8),
        ],
        symbol_kind="contract-target",
    )


def test_multiple_list_and_tuple_stars_feed_declared_varargs_in_exact_order() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(head, *extras):\n"
        "        return extras\n"
        "    left = [6, 7]\n"
        "    right = (9, 10)\n"
        "    return inner(5, *left, 8, *right)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        TermValue(5),
        TupleValue(
            (
                TermValue(6),
                TermValue(7),
                TermValue(8),
                TermValue(9),
                TermValue(10),
            )
        ),
    )


def test_empty_constructed_star_preserves_default_binding() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, optional=4):\n"
        "        return optional\n"
        "    return inner(5, *[])\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5), TermValue(4))
    assert callsite.term == ctor(
        "call:inner",
        [num(5), ctor("py.star", [ctor("array", [])])],
        symbol_kind="contract-target",
    )


def test_unknown_symbolic_star_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _expand_function_positional_args(
            (_star(SymbolicValue(make_var("items"))),), site="symbolic-star"
        )

    assert raised.value.info.owner == "CallSugar"
    assert raised.value.info.requested == (
        "expand a constructed finite positional sequence at a starred call argument"
    )
    assert raised.value.info.observed == "SymbolicValue"


@pytest.mark.parametrize(
    "value",
    [TermValue(7), DictValue(((TermValue(0), TermValue(1)),))],
    ids=["non-iterable", "mapping"],
)
def test_non_sequence_star_stays_loud(value) -> None:
    with pytest.raises(FactoryPanic) as raised:
        _expand_function_positional_args((_star(value),), site="bad-star")

    assert raised.value.info.owner == "CallSugar"
    assert raised.value.info.observed == type(value).__name__


def test_no_star_positional_arguments_are_unchanged() -> None:
    args = (TermValue(5), ListValue((TermValue(6),)))
    assert _expand_function_positional_args(args, site="control") == args
