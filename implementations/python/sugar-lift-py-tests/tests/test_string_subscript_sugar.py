"""StringSubscriptSugar reduces `table[index]` to an EncodedStringValue: the string
literal becomes its tuple of byte ordinals and the index becomes a bv term, so the
pair (table, index) IS the per-character constraint the encoder universe carries."""

from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import (
    Bv32Value,
    EncodedStringValue,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num

NONE = ctor("None", [])


def test_subscript_reduces_to_encoded_string_table_and_index():
    value = reduce_value(
        "tbl[i]", {"tbl": StringValue("ABCD"), "i": Bv32Value(make_var("i"))}
    )
    assert value == EncodedStringValue(table=(65, 66, 67, 68), indices=(make_var("i"),))


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


def test_string_slice_reaches_named_floor_gap():
    with pytest.raises(FactoryGap) as raised:
        reduce_value("'abcdef'[1:3]")

    assert raised.value.info["owner"] == "StringSubscriptSugar.string_slice"
    assert raised.value.info["observed"] == "SliceValue"
    assert raised.value.info["requested"] == "StringValue slice lowering"
    assert raised.value.info["fix"] == "add concrete StringValue slice lowering"
