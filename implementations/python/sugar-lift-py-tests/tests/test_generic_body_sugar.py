"""GenericBodySugar reduces a string-encoder body (a table literal + per-byte
`ord`s + a subscript-concat return) to ONE first-order constraint:
`str.eq-bv-blocks(out, input, payload)`, where the payload pins the table and the
per-character bv index expressions.

It is GENERIC -- not a base64 sugar (that per-vendor shape was retired). Any table,
any byte count, any block structure reduces the same way. The two cases below are
the SAME sugar over two structurally different encoders; each gets its OWN table.
"""
from __future__ import annotations

import json

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

# 64-char table, 3 bytes -> 4 chars.
BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
BASE64 = (
    "def encode64(value):\n"
    f'    alphabet = "{BASE64_ALPHABET}"\n'
    "    b0 = ord(value[0])\n"
    "    b1 = ord(value[1])\n"
    "    b2 = ord(value[2])\n"
    "    return (\n"
    "        alphabet[b0 >> 2]\n"
    "        + alphabet[((b0 & 3) << 4) | (b1 >> 4)]\n"
    "        + alphabet[((b1 & 15) << 2) | (b2 >> 6)]\n"
    "        + alphabet[b2 & 63]\n"
    "    )\n"
)

# A DIFFERENT encoder: 20-char table, 1 byte -> 2 chars. No shared structure.
BASE20_ALPHABET = "ABCDEFGHIJKLMNOPQRST"
BASE20 = (
    "def encode20(value):\n"
    f'    alphabet = "{BASE20_ALPHABET}"\n'
    "    b0 = ord(value[0])\n"
    "    return alphabet[b0 & 15] + alphabet[(b0 >> 4) & 15]\n"
)


def _universe_post(encoder_src: str, call: str):
    src = encoder_src + "def t():\n" f"    assert {call}\n"
    rep = build_literal_call_report(source=src, filename="b.py", memento_file="b.py")
    universe = [c for c in rep.payload.ir if getattr(c, "post", None) is not None]
    assert universe, "the dig must mint a universe for the encoder body"
    return universe[0].post


def _assert_encoder(encoder_src, call, *, alphabet, out_chars):
    post = _universe_post(encoder_src, call)
    # ONE atomic constraint relating the output to the input string.
    assert post["name"] == "str.eq-bv-blocks"
    out, src, payload = post["args"]
    assert out == {"kind": "var", "name": "out"}
    assert src == {"kind": "var", "name": "value"}
    spec = json.loads(payload["value"])
    assert spec["table"] == [ord(ch) for ch in alphabet]
    assert len(spec["per_char"]) == out_chars


def test_64_char_encoder_reduces_to_str_eq_bv_blocks_over_its_table():
    _assert_encoder(
        BASE64, 'encode64("abc") == "YWJj"', alphabet=BASE64_ALPHABET, out_chars=4
    )


def test_a_structurally_different_encoder_reduces_the_same_way_with_its_own_table():
    # Same GenericBodySugar, a 20-char table and 1->2 byte structure: same
    # str.eq-bv-blocks shape, ITS table, two output chars. Nothing base64 survives.
    _assert_encoder(
        BASE20, 'encode20("A") == "BE"', alphabet=BASE20_ALPHABET, out_chars=2
    )
