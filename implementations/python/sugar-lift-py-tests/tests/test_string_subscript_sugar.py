"""StringSubscriptSugar reduces `table[index]` to an EncodedStringValue: the string
literal becomes its tuple of byte ordinals and the index becomes a bv term, so the
pair (table, index) IS the per-character constraint the encoder universe carries."""

from __future__ import annotations

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import Bv32Value, EncodedStringValue, StringValue
from sugar_lift_py_tests.ir import make_var


def test_subscript_reduces_to_encoded_string_table_and_index():
    value = reduce_value(
        "tbl[i]", {"tbl": StringValue("ABCD"), "i": Bv32Value(make_var("i"))}
    )
    assert value == EncodedStringValue(table=(65, 66, 67, 68), indices=(make_var("i"),))
