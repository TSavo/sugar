# SPDX-License-Identifier: Apache-2.0
#
# Cross-language conformance tests. Hash and JCS strings are pinned from
# the Rust probe at implementations/rust/examples/layer2_py_probe.rs.
# The protocol is the bytes; if these diverge, the Python impl is wrong.

from __future__ import annotations

from sugar_lift_py_tests.canonicalizer import (
    BLAKE3_512_PREFIX,
    blake3_512_of,
    encode_jcs,
    jcs_hash,
    varr,
    vbool,
    vint,
    vobj,
    vstr,
)


def test_empty_blake3_512_matches_rust():
    assert blake3_512_of(b"") == (
        "blake3-512:af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
        "e00f03e7b69af26b7faaf09fcd333050338ddfe085b8cc869ca98b206c08243a"
    )


def test_empty_object_and_array():
    assert encode_jcs(vobj([])) == "{}"
    assert encode_jcs(varr([])) == "[]"


def test_object_keys_sort_by_codepoint():
    v = vobj([("b", vint(1)), ("a", vstr("x"))])
    assert encode_jcs(v) == '{"a":"x","b":1}'


def test_string_escapes_quote_and_backslash():
    assert encode_jcs(vstr('a"b\\c')) == '"a\\"b\\\\c"'


def test_control_char_lower_hex_escape():
    # U+0001 ->  lowercase
    assert encode_jcs(vstr("\x01")) == '"\\u0001"'


def test_unicode_atomic_predicate_glyphs_round_trip_verbatim():
    # The kit's atomic predicate names use ≥ ≤ ≠. Cross-language hash
    # agreement requires UTF-8 verbatim emission; the previous
    # byte-iteration form in the Rust impl corrupted these.
    for sym in ("≥", "≤", "≠"):
        encoded = encode_jcs(vstr(sym))
        assert encoded == f'"{sym}"'
        # Inner bytes are the same UTF-8 the input carried.
        inner = encoded[1:-1]
        assert inner.encode("utf-8") == sym.encode("utf-8")


def test_unicode_in_object_key_and_value_matches_rust():
    v = vobj([("name", vstr("≥"))])
    encoded = encode_jcs(v)
    assert encoded == '{"name":"≥"}'
    # Byte-identical to the Rust impl: e2 89 a5 for ≥.
    assert encoded.encode("utf-8") == b'{"name":"\xe2\x89\xa5"}'


def test_unicode_object_jcs_matches_pinned_rust_bytes():
    # Pinned from `cargo run --example layer2_py_probe`.
    v = vobj([("name", vstr("≥"))])
    assert encode_jcs(v) == '{"name":"≥"}'


def test_bool_and_null_emit_verbatim():
    assert encode_jcs(vbool(True)) == "true"
    assert encode_jcs(vbool(False)) == "false"
    from sugar_lift_py_tests.canonicalizer import vnull

    assert encode_jcs(vnull()) == "null"


def test_jcs_hash_self_identifying_prefix():
    h = jcs_hash(vstr("hi"))
    assert h.startswith(BLAKE3_512_PREFIX)
    assert len(h) == len(BLAKE3_512_PREFIX) + 128


def test_blake3_rejects_non_bytes():
    import pytest as _pytest

    with _pytest.raises(TypeError):
        blake3_512_of("not bytes")  # type: ignore[arg-type]
