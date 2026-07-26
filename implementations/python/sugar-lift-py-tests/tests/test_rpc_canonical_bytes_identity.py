# SPDX-License-Identifier: MIT OR Apache-2.0
#
# THE PREIMAGE IS THE PROTOCOL. `_rpc_canonical_bytes` was rewritten from an
# always-scan `ord` walk into encode-first with a surrogate-replacement fallback.
# Every CID that routes through term-table materialization hashes these bytes.
# These twins pin byte identity against the previous implementation before any
# CID preimage can move.

from __future__ import annotations

import random
import unicodedata

import pytest

from sugar_lift_py_tests import ir as IR
from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs, vstr
from sugar_lift_py_tests.ir import (
    TermTableBuilder,
    _Ctor,
    _rpc_canonical_bytes,
    make_var,
    term_to_value,
)


def _oracle_rpc_canonical_bytes(canonical: str) -> bytes:
    """The pre-optimization implementation, verbatim. THE specification."""
    if not any(0xD800 <= ord(char) <= 0xDFFF for char in canonical):
        return canonical.encode("utf-8")
    safe = "".join(
        "\ufffd" if 0xD800 <= ord(char) <= 0xDFFF else char for char in canonical
    )
    return safe.encode("utf-8")


def _assert_identical(canonical: str) -> None:
    old = _oracle_rpc_canonical_bytes(canonical)
    new = _rpc_canonical_bytes(canonical)
    assert old == new, f"rpc bytes diverge on {canonical!r}: {old!r} != {new!r}"
    assert blake3_512_of(old) == blake3_512_of(new)


def test_ascii_and_cid_strings_are_utf8():
    for value in ["", "x", "blake3-512:" + "ab" * 64, '{"kind":"var","name":"x"}']:
        _assert_identical(value)
        assert _rpc_canonical_bytes(value) == value.encode("utf-8")


def test_non_ascii_bmp_and_astral_are_verbatim_utf8():
    for value in ["日", "日本語", "≥≠∀", "😀🎉", "👨‍👩‍👧‍👦", "é"]:
        _assert_identical(value)
        assert _rpc_canonical_bytes(value) == value.encode("utf-8")


def test_combining_forms_are_not_normalized():
    decomposed = "é"
    precomposed = unicodedata.normalize("NFC", decomposed)
    assert decomposed != precomposed
    _assert_identical(decomposed)
    _assert_identical(precomposed)
    assert _rpc_canonical_bytes(decomposed) != _rpc_canonical_bytes(precomposed)


def test_lone_surrogates_become_replacement_character():
    # RPC boundary replaces unpaired surrogates with U+FFFD before hashing.
    for value in ["\ud800", "\udfff", "a\udc00b", "\ud83d", "x\ud800y\udfffz"]:
        _assert_identical(value)
        expected = value.replace("\ud800", "\ufffd")
        for cp in range(0xD800, 0xE000):
            expected = expected.replace(chr(cp), "\ufffd")
        # Rebuild expected via the oracle rule only (already asserted equal).
        assert _rpc_canonical_bytes(value) == _oracle_rpc_canonical_bytes(value)
        assert b"\xef\xbf\xbd" in _rpc_canonical_bytes(value)  # UTF-8 of U+FFFD


def test_surrogate_mixed_with_ascii_and_bmp():
    _assert_identical("pre\ud83dmid日post")
    _assert_identical("\ud800" * 100 + "ok" + "\udfff" * 100)


def test_long_canonical_preimages():
    for value in ["x" * 200_000, "日" * 50_000, '{"k":"' + ("ab" * 10_000) + '"}']:
        _assert_identical(value)


def test_jcs_encoded_terms_keep_their_cids():
    """Corpus-shaped term preimages: CIDs must not move under the rewrite."""
    terms = [
        make_var("leaf"),
        _Ctor("ssa:0", (make_var("leaf"),)),
        _Ctor("root", (_Ctor("a", (make_var("x"),)), _Ctor("b", (make_var("y"),)))),
    ]
    for term in terms:
        canonical = encode_jcs(term_to_value(term))
        _assert_identical(canonical)
        assert blake3_512_of(_rpc_canonical_bytes(canonical)) == blake3_512_of(
            _oracle_rpc_canonical_bytes(canonical)
        )


def test_term_table_cid_equals_oracle_hash_of_expanded_jcs():
    """Typed door: table CID is blake3(_rpc_canonical_bytes(encode_jcs(term)))."""
    leaf = make_var("leaf")
    spine = leaf
    for index in range(40):
        spine = _Ctor(f"ssa:{index}", (spine,))
    table = TermTableBuilder()
    cid = table._cid(spine)
    canonical = encode_jcs(term_to_value(spine))
    expected = blake3_512_of(_oracle_rpc_canonical_bytes(canonical))
    assert cid == expected
    assert cid == blake3_512_of(_rpc_canonical_bytes(canonical))


_ALPHABET = (
    [chr(c) for c in range(0x00, 0x80)]
    + [chr(c) for c in (0xA9, 0x2028, 0x4E2D, 0x1F600, 0x10FFFF)]
    + [chr(c) for c in (0xD800, 0xDBFF, 0xDC00, 0xDFFF)]
)


def test_differential_fuzz_rpc_bytes():
    rng = random.Random(20260726)
    for _ in range(5_000):
        length = rng.randint(0, 64)
        _assert_identical("".join(rng.choice(_ALPHABET) for _ in range(length)))


def test_encode_string_fast_path_matches_oracle_across_corpus_shapes():
    """lift-py-tests encoder must stay byte-identical to the per-char oracle."""
    from sugar_lift_py_tests import canonicalizer as C

    def oracle(value: str, out: list[str]) -> None:
        out.append('"')
        for char in value:
            codepoint = ord(char)
            if char == '"':
                out.append('\\"')
            elif char == "\\":
                out.append("\\\\")
            elif codepoint < 0x20:
                out.append("\\u00")
                out.append("0123456789abcdef"[(codepoint >> 4) & 0xF])
                out.append("0123456789abcdef"[codepoint & 0xF])
            else:
                out.append(char)
        out.append('"')

    samples = [
        "",
        "identifier",
        "blake3-512:" + "cd" * 64,
        'quote " and \\ and \n',
        "日😀",
        "\ud800",
        "/" * 100,
        "a" * 10_000,
    ]
    for value in samples:
        old: list[str] = []
        new: list[str] = []
        oracle(value, old)
        C._encode_string(value, new)
        assert "".join(old) == "".join(new), value


def test_rpc_materialize_does_not_rehash_child_preimages(monkeypatch):
    """Parent edges must reuse child CIDs — one _rpc_canonical_bytes per node."""
    calls: list[int] = []
    original = IR._rpc_canonical_bytes

    def counting(canonical: str) -> bytes:
        calls.append(len(canonical))
        return original(canonical)

    monkeypatch.setattr(IR, "_rpc_canonical_bytes", counting)

    leaf = {"kind": "var", "name": "x"}
    # Build a spine of plain RPC dicts (source-lifter shape).
    node = leaf
    for index in range(30):
        node = {"kind": "ctor", "name": f"ssa:{index}", "args": [node]}

    table = TermTableBuilder()
    table.reference_rpc(node)
    # 1 leaf + 30 ctors = 31 nodes; never one extra walk per parent edge.
    assert len(calls) == 31, len(calls)
    assert len(table.nodes) == 31
