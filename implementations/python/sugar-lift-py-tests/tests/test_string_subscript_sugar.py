"""StringSubscriptSugar reduces `table[index]` to an EncodedStringValue: the string
literal becomes its tuple of byte ordinals and the index becomes a bv term, so the
pair (table, index) IS the per-character constraint the encoder universe carries."""

from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    Bv32Value,
    EncodedStringValue,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.temporal import TemporalContext

NONE = ctor("None", [])


def _reduce_value_with_operation_log(expr: str, binds: dict):
    temporal = TemporalContext.empty()
    for name, value in binds.items():
        temporal = temporal.bind_value(name, value)
    build_ctx = replace(
        FactoryBuildContext(filename="t.py", catalog=default_catalog()),
        temporal=temporal,
    )
    body = build_ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    reduce_ctx = ReduceContext(temporal=temporal)
    value = complete_value(body.reduce(reduce_ctx), owner="test")
    return value, reduce_ctx.operation_log


def test_subscript_reduces_to_encoded_string_table_and_index():
    value = reduce_value(
        "tbl[i]", {"tbl": StringValue("ABCD"), "i": Bv32Value(make_var("i"))}
    )
    assert value == EncodedStringValue(table=(65, 66, 67, 68), indices=(make_var("i"),))


def test_subscript_uses_shared_operation_dispatch_path():
    value, operation_log = _reduce_value_with_operation_log(
        "tbl[i]", {"tbl": StringValue("ABCD"), "i": Bv32Value(make_var("i"))}
    )

    assert value == EncodedStringValue(table=(65, 66, 67, 68), indices=(make_var("i"),))
    assert operation_log == [
        ("StringSubscriptSugar", "subscript_with", "SubscriptOperation")
    ]


def test_subscript_dispatches_symbolic_receiver_to_symbolic_floor_term():
    value = reduce_value("values[0]", {"values": SymbolicValue(make_var("values"))})

    assert value == SymbolicValue(ctor("py.subscript", [make_var("values"), num(0)]))


def test_subscript_dispatches_symbolic_receiver_and_index_to_symbolic_floor_term():
    value = reduce_value(
        "values[i]",
        {
            "values": SymbolicValue(make_var("values")),
            "i": SymbolicValue(make_var("i")),
        },
    )

    assert value == SymbolicValue(
        ctor("py.subscript", [make_var("values"), make_var("i")])
    )


def test_subscript_dispatches_symbolic_receiver_with_slice_index():
    value = reduce_value("values[::2]", {"values": SymbolicValue(make_var("values"))})

    assert value == SymbolicValue(
        ctor(
            "py.subscript",
            [
                make_var("values"),
                ctor("py.slice", [NONE, NONE, num(2)]),
            ],
        )
    )


def test_subscript_dispatches_symbolic_receiver_with_tuple_slice_index():
    value = reduce_value(
        "values[..., 0, :]", {"values": SymbolicValue(make_var("values"))}
    )

    assert value == SymbolicValue(
        ctor(
            "py.subscript",
            [
                make_var("values"),
                ctor(
                    "tuple",
                    [
                        ctor("py.ellipsis", []),
                        num(0),
                        ctor("py.slice", [NONE, NONE, NONE]),
                    ],
                ),
            ],
        )
    )


def test_string_scalar_index_uses_python_string_value():
    value = reduce_value("'abcde'[-1]")

    assert value == StringValue("e")


def test_string_slice_uses_python_string_value():
    assert reduce_value("'abcdef'[1:3]") == StringValue("bc")
    assert reduce_value("'abcdef'[::2]") == StringValue("ace")
    assert reduce_value("'abcdef'[-2:]") == StringValue("ef")


def test_subscript_receiver_runtime_effect_bubbles() -> None:
    temporal = TemporalContext.empty().bind_value(
        "flag", SymbolicValue(make_var("flag"))
    )
    build_ctx = replace(
        FactoryBuildContext(filename="t.py", catalog=default_catalog()),
        temporal=temporal,
    )
    body = build_ctx.build_body(
        ast.parse("('abc' if flag else 'def')[0]", mode="eval").body,
        SugarRole.TERM,
    )

    outcome = body.reduce(ReduceContext(temporal=temporal))

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "conditional expression runtime boundary" in outcome.effect.reason


def test_symbolic_string_slice_bound_reaches_named_floor_gap():
    with pytest.raises(FactoryGap) as raised:
        reduce_value(
            "s[i:3]",
            {"s": StringValue("abcdef"), "i": SymbolicValue(make_var("i"))},
        )

    assert raised.value.info["owner"] == "StringSubscriptSugar.string_slice"
    assert raised.value.info["observed"] == "SymbolicValue"
    assert raised.value.info["requested"] == "concrete slice bounds"
    assert raised.value.info["fix"] == "add symbolic StringValue slice lowering"
