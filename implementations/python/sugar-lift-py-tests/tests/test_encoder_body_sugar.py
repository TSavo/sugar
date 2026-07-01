"""EncoderBodySugar lowers a string-encoder body -- composed by the Block to an
EncodedStringValue -- to the existing str.eq-bv-blocks atom. The new logic is reading
the byte vars out of the composed index terms, in byte-index order."""

from __future__ import annotations

import json

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.floor import EncodedStringValue
from sugar_lift_py_tests.ir import bvlshr, formula_to_value, make_var, num
from sugar_lift_py_tests.sugar.encoder_body_sugar import EncoderBodySugar, _byte_vars


def test_byte_vars_collected_in_index_order():
    # indices may reference the bytes in any order; str.eq-bv-blocks needs them by
    # byte position, so they come back sorted by the index in `byte_<source>_<index>`.
    indices = (bvlshr(make_var("byte_value_2"), num(6)), make_var("byte_value_0"))
    assert _byte_vars(indices) == ["byte_value_0", "byte_value_2"]


def test_encoder_lowers_to_str_eq_bv_blocks():
    encoded = EncodedStringValue(
        table=(65, 66),
        indices=(make_var("byte_value_0"), make_var("byte_value_1")),
    )
    sugar = EncoderBodySugar(parameter="value", encoded=encoded)
    formula = sugar.constraint_formulas()[0]
    rendered = json.loads(encode_jcs(formula_to_value(formula)))
    assert rendered["name"] == "str.eq-bv-blocks"
    subject, input_term, payload = rendered["args"]
    assert subject == {"kind": "var", "name": "out"}
    assert input_term == {"kind": "var", "name": "value"}
    body = json.loads(payload["value"])
    assert body["vars"] == ["byte_value_0", "byte_value_1"]
    assert body["table"] == [65, 66]
    assert len(body["per_char"]) == 2
