"""base20 pins the GENERIC factory: a different string-table encoder (20-char
alphabet, 1 input byte, 2 output chars, nibble slices) lifts by composing the
same generic catalog sugars as base64 -- no base64-specific sugar exists."""
from __future__ import annotations

import json

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

ENCODE20 = (
    "def encode20(value):\n"
    '    alphabet = "ABCDEFGHIJKLMNOPQRST"\n'
    "    b0 = ord(value[0])\n"
    "    return alphabet[b0 & 15] + alphabet[(b0 >> 4) & 15]\n"
    "\n"
    "def test_encode20():\n"
    '    assert encode20("A") == "{expected}"\n'
)


def _lift(expected: str):
    src = ENCODE20.format(expected=expected)
    return build_literal_call_report(
        source=src, filename="test_base20.py", memento_file="test_base20.py"
    )


def test_base20_lifts_by_generic_composition_not_a_base64_sugar() -> None:
    rep = _lift("BE")
    # The body composes as ONE Block through the generic catalog (BlockSugar drives
    # AssignSugar / OrdByteSugar / BitwiseOp / StringSubscript / BinOp internally);
    # nothing base64-specific. The string encoder is a recognized leaf INSIDE the
    # Block, lowered to the same str.eq-bv-blocks relation -- not a separate dispatch.
    selected = [row.selected for row in rep.payload.factory_walk]
    assert selected == ["BlockSugar", "FunctionCallSugar"]
    names = [c.name for c in rep.payload.ir]
    assert names == [
        "test_base20::encode20::callable",
        "encode20#euf#c:call:encode20(s:'A')::assertion",
    ]
    # The composed universe is the str.eq-bv-blocks relation over the 20-char table.
    post = json.dumps(rep.payload.ir[0].post)
    assert "str.eq-bv-blocks" in post
    assert [ord(c) for c in "ABCDEFGHIJKLMNOPQRST"][-1] == 84  # T -> 20-entry table
