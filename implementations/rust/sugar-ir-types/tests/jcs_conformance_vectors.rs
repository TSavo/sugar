// SPDX-License-Identifier: MIT OR Apache-2.0
//
// JCS conformance vectors for sugar_canonicalizer::encode_jcs.
//
// Each test pins the byte-stable canonical output of encode_jcs against a
// known-good golden string. Together they exercise the tricky corners of
// RFC 8785 (JSON Canonicalization Scheme):
//
//   V1  Large integer (u64 > 2^53, above JS Number.MAX_SAFE_INTEGER)
//   V2  Multi-char ASCII key sorting (byte-order determines output order)
//   V3  Control-character escaping (U+0000..U+001F -> \u00XX, lowercase hex)
//   V4  Nested objects with mixed scalar types and sorted keys
//   V5  i64::MAX boundary condition for the Integer variant
//   V6  Empty-string key (sorts before all non-empty ASCII keys)
//   V7  Non-ASCII UTF-8 chars emitted verbatim (no escaping for >= U+0080)

use sugar_canonicalizer::{encode_jcs, Value};

// ---------------------------------------------------------------------------
// V1 -- Large integer (exceeds 2^53)
// ---------------------------------------------------------------------------

#[test]
fn v1_large_integer_above_js_safe_integer() {
    // This value exceeds Number.MAX_SAFE_INTEGER (9007199254740992 = 2^53).
    // A JS JSON.stringify() silently truncates it to ...000; our encoder must
    // emit all 19 decimal digits verbatim.
    let v = Value::object([("large_integer", Value::integer(4614253070214989087_i128))]);
    let jcs = encode_jcs(&v);
    assert_eq!(jcs, r#"{"large_integer":4614253070214989087}"#);
}

// ---------------------------------------------------------------------------
// V2 -- Multi-char ASCII key sorting (byte-order)
// ---------------------------------------------------------------------------

#[test]
fn v2_object_keys_sorted_by_byte_order() {
    // Keys inserted in non-alphabetical order; JCS must emit them
    // sorted by byte-value (0x61='a' < 0x6D='m' < 0x7A='z').
    let v = Value::object([
        ("z", Value::integer(1)),
        ("a", Value::integer(2)),
        ("m", Value::integer(3)),
    ]);
    let jcs = encode_jcs(&v);
    assert_eq!(jcs, r#"{"a":2,"m":3,"z":1}"#);
}

// ---------------------------------------------------------------------------
// V3 -- Control-character escaping (\u00XX form, lowercase hex)
// ---------------------------------------------------------------------------

#[test]
fn v3_control_chars_escaped_as_u00xx() {
    // RFC 8785 requires U+0000..U+001F to be escaped. Both short-form
    // (\t, \n) and \u00XX are conformant; this implementation uses \u00XX
    // for determinism so it matches the C++ peer byte-for-byte.
    // U+0009 (HT) escapes to \u0009, U+000A (LF) escapes to \u000a (lowercase hex).
    let s = "\t\n";
    let v = Value::String(s.to_string());
    let jcs = encode_jcs(&v);
    assert_eq!(jcs, "\"\\u0009\\u000a\"");
}

// ---------------------------------------------------------------------------
// V4 -- Nested object with mixed scalar types
// ---------------------------------------------------------------------------

#[test]
fn v4_nested_object_mixed_types() {
    // "arr" (bytes: 61 72 72) sorts before "outer" (6F 75 74 65 72) byte-wise.
    // Inner keys: "b" (62) < "n" (6E) < "s" (73).
    let inner = Value::object([
        ("s", Value::string("hello")),
        ("b", Value::boolean(true)),
        ("n", Value::null()),
    ]);
    let arr = Value::array(vec![
        Value::integer(1),
        Value::integer(2),
        Value::integer(3),
    ]);
    let v = Value::object([("outer", inner), ("arr", arr)]);
    let jcs = encode_jcs(&v);
    assert_eq!(
        jcs,
        r#"{"arr":[1,2,3],"outer":{"b":true,"n":null,"s":"hello"}}"#
    );
}

// ---------------------------------------------------------------------------
// V5 -- i64::MAX boundary condition
// ---------------------------------------------------------------------------

#[test]
fn v5_i64_max_integer() {
    // i64::MAX = 9223372036854775807 (2^63 - 1). The encoder must serialize
    // it as all 19 decimal digits with no truncation or overflow.
    let v = Value::object([("big", Value::integer(i128::from(i64::MAX)))]);
    let jcs = encode_jcs(&v);
    assert_eq!(jcs, r#"{"big":9223372036854775807}"#);
}

// ---------------------------------------------------------------------------
// V6 -- Empty-string key sorts before all non-empty ASCII keys
// ---------------------------------------------------------------------------

#[test]
fn v6_empty_string_key_sorts_first() {
    // The empty string is lexicographically less than any non-empty string
    // under byte-order comparison. A common bug inserts it last.
    let v = Value::object([("a", Value::integer(1)), ("", Value::string("v"))]);
    let jcs = encode_jcs(&v);
    assert_eq!(jcs, r#"{"":"v","a":1}"#);
}

// ---------------------------------------------------------------------------
// V7 -- Non-ASCII UTF-8 string values emitted verbatim
// ---------------------------------------------------------------------------

#[test]
fn v7_non_ascii_utf8_emitted_verbatim() {
    // U+4E16 (CJK: world, 3-byte UTF-8) and U+1F600 (emoji, 4-byte UTF-8).
    // RFC 8785 does not require \uXXXX escaping for codepoints >= U+0080.
    // Emitting verbatim preserves cross-language hash agreement: every
    // implementation that agrees on UTF-8 source bytes produces identical hashes.
    let s = "\u{4E16}\u{1F600}";
    let v = Value::String(s.to_string());
    let jcs = encode_jcs(&v);
    let expected = format!("\"{}\"", s);
    assert_eq!(jcs, expected);
    // Inner bytes are exactly the UTF-8 encoding of the input string.
    let inner = &jcs[1..jcs.len() - 1];
    assert_eq!(inner.as_bytes(), s.as_bytes());
}
