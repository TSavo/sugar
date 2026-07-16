# SPDX-License-Identifier: MIT OR Apache-2.0
"""CallSiteValue right_shift / bitwise_and floors (A2 mint-failed class).

python-literal-base64 / base64-federation / base20 mint panics when
`ord(c) >> 2` or `b0 & 15` land on CallSiteValue without a floor.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, num
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_callsite_right_shift_cites_the_opaque_operator_coordinate() -> None:
    receiver = CallSiteValue(
        target_name="ord",
        arg_values=(),
        parameters=(),
        term=ctor("call:ord", []),
        body=None,
    )
    outcome = receiver.right_shift(TermValue(2), "test_base64.py:7")

    assert outcome.value.to_term(owner="test") == ctor(
        ">>", [ctor("call:ord", []), num(2)]
    )


def test_callsite_bitwise_and_cites_the_opaque_operator_coordinate() -> None:
    receiver = CallSiteValue(
        target_name="ord",
        arg_values=(),
        parameters=(),
        term=ctor("call:ord", []),
        body=None,
    )
    outcome = receiver.bitwise_and(TermValue(15), "test_base20.py:4")

    assert outcome.value.to_term(owner="test") == ctor(
        "&", [ctor("call:ord", []), num(15)]
    )


def test_callsite_declares_right_shift_and_bitwise_and_structurally() -> None:
    assert "right_shift" in CallSiteValue.__dict__
    assert "bitwise_and" in CallSiteValue.__dict__


def test_base64_encode_body_lifts_without_right_shift_panic() -> None:
    """encodeBase64 uses >> & << | on ord() results — mint must not FactoryPanic."""
    source = (
        "def encodeBase64(value):\n"
        '    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"\n'
        "    b0 = ord(value[0])\n"
        "    b1 = ord(value[1])\n"
        "    b2 = ord(value[2])\n"
        "    return (\n"
        "        alphabet[b0 >> 2]\n"
        "        + alphabet[((b0 & 3) << 4) | (b1 >> 4)]\n"
        "        + alphabet[((b1 & 15) << 2) | (b2 >> 6)]\n"
        "        + alphabet[b2 & 63]\n"
        "    )\n"
        "\n"
        "def test_encode_base64():\n"
        '    assert encodeBase64("abc") == "YWJj"\n'
    )
    payload = lift_file_payload(source, "test_base64.py")
    names = [row.name for row in payload.ir]
    assert any("encodeBase64" in (n or "") for n in names) or any(
        row.kind == "function-contract" for row in payload.ir
    )


def test_base20_encode_body_lifts_without_bitwise_and_panic() -> None:
    source = (
        "def encode20(value):\n"
        '    alphabet = "ABCDEFGHIJKLMNOPQRST"\n'
        "    b0 = ord(value[0])\n"
        "    return alphabet[b0 & 15] + alphabet[(b0 >> 4) & 15]\n"
        "\n"
        "def test_encode20():\n"
        '    assert encode20("A") == "BE"\n'
    )
    payload = lift_file_payload(source, "test_base20.py")
    assert any(row.kind in {"function-contract", "contract"} for row in payload.ir)
