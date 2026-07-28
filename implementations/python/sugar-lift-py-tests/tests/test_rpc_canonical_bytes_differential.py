# SPDX-License-Identifier: MIT OR Apache-2.0
#
# THE ENCODER IS THE PROTOCOL. `ir._rpc_canonical_bytes` was rewritten from a
# pre-scan (`any(...)` over every character, asking whether a surrogate is
# present) into a try/except around the encode that answers the same question
# in C. The rewrite is a pure speed change: every string must produce
# byte-identical output, and therefore an identical CID, before and after.
#
# The ORACLE is the pre-scan itself, kept here verbatim. It is not a
# re-derivation -- it is the exact code that shipped, so byte identity is
# measured against the thing that minted every pinned CID.

from __future__ import annotations

import random

import pytest

from sugar_lift_py_tests.ir import _rpc_canonical_bytes

SURROGATES = range(0xD800, 0xE000)


def _oracle_rpc_canonical_bytes(canonical: str) -> bytes:
    """The pre-optimization pre-scan, verbatim. THE specification."""
    if not any(0xD800 <= ord(char) <= 0xDFFF for char in canonical):
        return canonical.encode("utf-8")
    safe = "".join("�" if 0xD800 <= ord(char) <= 0xDFFF else char for char in canonical)
    return safe.encode("utf-8")


def test_encode_refuses_exactly_the_surrogate_range() -> None:
    """The load-bearing assumption of the rewrite.

    The try/except is only equivalent to the pre-scan if `str.encode("utf-8")`
    raises on every surrogate and on nothing else. If CPython ever widened or
    narrowed that set, the rewrite would silently change bytes -- so this is
    asserted directly over the entire codepoint space, not sampled.
    """
    refused = set()
    for codepoint in range(0x110000):
        try:
            chr(codepoint).encode("utf-8")
        except UnicodeEncodeError:
            refused.add(codepoint)
    assert refused == set(SURROGATES)
    assert len(refused) == 2048


def test_byte_identity_over_every_codepoint() -> None:
    """Exhaustive single-character twin across the whole codepoint space."""
    mismatches = [
        hex(codepoint)
        for codepoint in range(0x110000)
        if _rpc_canonical_bytes(chr(codepoint))
        != _oracle_rpc_canonical_bytes(chr(codepoint))
    ]
    assert mismatches == []


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a",
        "ascii only",
        "café",
        "中文字",
        "\U0001f41d",
        "\ud800",
        "\udfff",
        "a\ud800b",
        "\ud800\U0001f41d",
        "�\ud800�",
        "\x00\ud800",
        "𐀀",
    ],
    ids=[
        "empty",
        "ascii-single",
        "ascii-run",
        "latin1",
        "cjk",
        "astral",
        "lone-high",
        "lone-low",
        "surrogate-interior",
        "surrogate-plus-astral",
        "replacement-around-surrogate",
        "nul-plus-surrogate",
        "surrogate-pair-unpaired-in-str",
    ],
)
def test_byte_identity_named_edges(value: str) -> None:
    assert _rpc_canonical_bytes(value) == _oracle_rpc_canonical_bytes(value)


def test_byte_identity_randomized_surrogate_heavy() -> None:
    """Multi-character strings from a surrogate-dense alphabet.

    A real corpus is overwhelmingly surrogate-free, which is exactly why the
    slow path needs deliberate over-sampling here: it is the path a corpus run
    would never exercise.
    """
    rng = random.Random(1234)
    alphabet = [
        chr(codepoint)
        for codepoint in (
            0x00,
            0x41,
            0xE9,
            0x4E2D,
            0x1F41D,
            0xD800,
            0xDBFF,
            0xDC00,
            0xDFFF,
            0xFFFD,
            0x10FFFF,
        )
    ]
    for _ in range(20000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        assert _rpc_canonical_bytes(value) == _oracle_rpc_canonical_bytes(value), repr(
            value
        )


def test_surrogates_still_become_replacement_char() -> None:
    """Positive control: the slow path is reachable and does something.

    Byte-identity twins pass trivially if both sides are wrong in the same way.
    This pins the actual substitution independently of the oracle.
    """
    assert _rpc_canonical_bytes("a\ud800b") == "a�b".encode("utf-8")
    assert _rpc_canonical_bytes("\ud800") == b"\xef\xbf\xbd"
    assert _rpc_canonical_bytes("plain") == b"plain"
