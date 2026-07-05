// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Extended JCS-JSON encoder tests. Covers the RFC 8785 / spec-pass-7
// invariants the unit tests in jcs.rs only sample.
//
// NOTE: the Value tree is integer-only — there is no Float variant. The
// "integer-valued floats render without decimal" rule from RFC 8785
// §3.2.2.3 is satisfied trivially: integers always render without a
// decimal point because there is no float path. The first test below
// pins that invariant explicitly.

use sugar_canonicalizer::{encode_jcs, Value};

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

#[test]
fn integer_renders_without_decimal_point() {
    // RFC 8785 §3.2.2.3: integer-valued numbers render with no decimal
    // point. Value tree is i64-only so this is the only path.
    assert_eq!(encode_jcs(&Value::integer(42)), "42");
    assert_eq!(encode_jcs(&Value::integer(0)), "0");
    assert_eq!(encode_jcs(&Value::integer(1)), "1");
}

#[test]
fn integer_negative() {
    assert_eq!(encode_jcs(&Value::integer(-1)), "-1");
    assert_eq!(encode_jcs(&Value::integer(-42)), "-42");
    assert_eq!(
        encode_jcs(&Value::integer(i128::from(i64::MIN))),
        i64::MIN.to_string()
    );
}

#[test]
fn integer_max_boundaries() {
    assert_eq!(
        encode_jcs(&Value::integer(i128::from(i64::MAX))),
        i64::MAX.to_string()
    );
    assert_eq!(encode_jcs(&Value::integer(0x7fff_ffff)), "2147483647");
    assert_eq!(encode_jcs(&Value::integer(0x8000_0000)), "2147483648");
}

// ---------------------------------------------------------------------------
// Booleans / null
// ---------------------------------------------------------------------------

#[test]
fn booleans_and_null() {
    assert_eq!(encode_jcs(&Value::Bool(true)), "true");
    assert_eq!(encode_jcs(&Value::Bool(false)), "false");
    assert_eq!(encode_jcs(&Value::Null), "null");
}

// ---------------------------------------------------------------------------
// Strings — escaping rules
// ---------------------------------------------------------------------------

#[test]
fn empty_string() {
    assert_eq!(encode_jcs(&Value::String("".into())), "\"\"");
}

#[test]
fn ascii_passes_through_unescaped() {
    assert_eq!(
        encode_jcs(&Value::String("hello world".into())),
        "\"hello world\""
    );
}

#[test]
fn double_quote_is_escaped() {
    assert_eq!(encode_jcs(&Value::String("\"".into())), "\"\\\"\"");
}

#[test]
fn backslash_is_escaped() {
    assert_eq!(encode_jcs(&Value::String("\\".into())), "\"\\\\\"");
}

#[test]
fn control_characters_are_unicode_escaped() {
    // U+0000..U+001F render as `\u00XX` (lowercase hex). The encoder
    // does NOT use the named short escapes (\n, \t, etc.) — it uses
    // \u00XX uniformly for determinism.
    assert_eq!(encode_jcs(&Value::String("\u{0000}".into())), "\"\\u0000\"");
    assert_eq!(encode_jcs(&Value::String("\u{001f}".into())), "\"\\u001f\"");
    assert_eq!(encode_jcs(&Value::String("\n".into())), "\"\\u000a\"");
    assert_eq!(encode_jcs(&Value::String("\r".into())), "\"\\u000d\"");
    assert_eq!(encode_jcs(&Value::String("\t".into())), "\"\\u0009\"");
    assert_eq!(encode_jcs(&Value::String("\u{0008}".into())), "\"\\u0008\"");
    assert_eq!(encode_jcs(&Value::String("\u{000c}".into())), "\"\\u000c\"");
}

#[test]
fn control_character_hex_is_lowercase() {
    // The encoder writes lowercase hex for \u00XX. RFC 8785 mandates
    // lowercase.
    let s = encode_jcs(&Value::String("\u{000a}\u{001f}".into()));
    assert!(!s.chars().any(|c| c.is_ascii_uppercase()));
    assert!(s.contains("\\u000a"));
    assert!(s.contains("\\u001f"));
}

#[test]
fn space_and_above_pass_through() {
    // 0x20 (space) is the first unescaped character.
    assert_eq!(encode_jcs(&Value::String(" ".into())), "\" \"");
    // Tilde 0x7e.
    assert_eq!(encode_jcs(&Value::String("~".into())), "\"~\"");
}

#[test]
fn forward_slash_is_not_escaped() {
    // RFC 8785 doesn't require escaping `/`; we must NOT emit \/.
    assert_eq!(encode_jcs(&Value::String("/".into())), "\"/\"");
    assert_eq!(
        encode_jcs(&Value::String("https://example".into())),
        "\"https://example\""
    );
}

#[test]
fn non_ascii_strings_round_trip_byte_faithful() {
    // RFC 8785: non-ASCII Unicode emits as verbatim UTF-8 bytes. The
    // earlier byte-iteration form double-encoded multi-byte UTF-8;
    // commit c4a2ef5 fixed it by iterating chars instead. This test
    // locks the fixed behavior so any regression is loud.
    let s = encode_jcs(&Value::String("héllo".into()));
    assert_eq!(s, "\"héllo\"");
    // And the bytes themselves are exactly the source's UTF-8.
    assert_eq!(s.as_bytes(), b"\"h\xc3\xa9llo\"");

    let j = encode_jcs(&Value::String("日本語".into()));
    assert_eq!(j, "\"日本語\"");
}

#[test]
fn ascii_only_strings_are_fully_byte_faithful() {
    // ASCII-only strings (the only kind the protocol envelopes use)
    // are emitted byte-for-byte after the obligatory escape rules.
    let inputs = ["", "a", "abc", "Hello World 1234", "@#$%&()*+,-./:;=?[]{}~"];
    for s in &inputs {
        let encoded = encode_jcs(&Value::String((*s).into()));
        // Outer quotes + inner string == source.
        assert_eq!(encoded, format!("\"{s}\""));
    }
}

#[test]
fn long_string() {
    let s = "a".repeat(10_000);
    let encoded = encode_jcs(&Value::String(s.clone()));
    assert_eq!(encoded.len(), s.len() + 2); // +2 for the quotes
    assert!(encoded.starts_with('"'));
    assert!(encoded.ends_with('"'));
}

// ---------------------------------------------------------------------------
// Objects — sort order, no whitespace
// ---------------------------------------------------------------------------

#[test]
fn empty_object() {
    let v = Value::object([] as [(String, _); 0]);
    assert_eq!(encode_jcs(&v), "{}");
}

#[test]
fn single_entry_object() {
    let v = Value::object([("a", Value::integer(1))]);
    assert_eq!(encode_jcs(&v), "{\"a\":1}");
}

#[test]
fn object_keys_are_byte_sorted() {
    // Insertion order: c, a, b. Output: a, b, c.
    let v = Value::object([
        ("c", Value::integer(3)),
        ("a", Value::integer(1)),
        ("b", Value::integer(2)),
    ]);
    assert_eq!(encode_jcs(&v), "{\"a\":1,\"b\":2,\"c\":3}");
}

#[test]
fn object_keys_sorted_by_unicode_code_point_for_ascii_only() {
    // Spec: Unicode code-point order. For ASCII this matches UTF-8 byte order.
    // Capital letters (0x41..) sort before lowercase (0x61..).
    let v = Value::object([
        ("a", Value::integer(1)),
        ("A", Value::integer(2)),
        ("Z", Value::integer(3)),
    ]);
    assert_eq!(encode_jcs(&v), "{\"A\":2,\"Z\":3,\"a\":1}");
}

#[test]
fn object_keys_sorted_by_unicode_code_point_for_non_ascii() {
    // RFC 8785 sorts keys by Unicode code point: A U+0041, z U+007A,
    // é U+00E9, 😀 U+1F600. UTF-8 preserves that order bytewise.
    let v = Value::object([
        ("😀", Value::integer(3)),
        ("é", Value::integer(2)),
        ("z", Value::integer(1)),
        ("A", Value::integer(0)),
    ]);
    assert_eq!(encode_jcs(&v), "{\"A\":0,\"z\":1,\"é\":2,\"😀\":3}");
}

#[test]
fn no_whitespace_between_pairs() {
    let v = Value::object([("a", Value::integer(1)), ("b", Value::integer(2))]);
    let s = encode_jcs(&v);
    assert!(!s.contains(' '));
    assert!(!s.contains('\n'));
    assert!(!s.contains('\t'));
}

#[test]
fn nested_object_sorts_at_each_level() {
    let v = Value::object([
        (
            "outer",
            Value::object([("z", Value::integer(1)), ("a", Value::integer(2))]),
        ),
        ("first", Value::integer(0)),
    ]);
    assert_eq!(encode_jcs(&v), "{\"first\":0,\"outer\":{\"a\":2,\"z\":1}}");
}

#[test]
fn duplicate_keys_in_input_both_emitted() {
    // The Value tree allows duplicate keys (it's a Vec, not a Map). The
    // encoder sorts and emits all of them. JSON itself does not say what
    // to do with duplicates; for our purposes we only build trees with
    // unique keys, but document the encoder's literal behavior.
    let v = Value::object([("a", Value::integer(1)), ("a", Value::integer(2))]);
    let s = encode_jcs(&v);
    // Both entries land; sort is stable on equal keys.
    assert!(s.contains("\"a\":1"));
    assert!(s.contains("\"a\":2"));
}

// ---------------------------------------------------------------------------
// Arrays — order preserved, no whitespace
// ---------------------------------------------------------------------------

#[test]
fn empty_array() {
    assert_eq!(encode_jcs(&Value::array(vec![])), "[]");
}

#[test]
fn array_of_integers() {
    let v = Value::array(vec![
        Value::integer(3),
        Value::integer(1),
        Value::integer(2),
    ]);
    // Arrays preserve insertion order (NOT sorted).
    assert_eq!(encode_jcs(&v), "[3,1,2]");
}

#[test]
fn array_of_strings() {
    let v = Value::array(vec![Value::string("zeta"), Value::string("alpha")]);
    assert_eq!(encode_jcs(&v), "[\"zeta\",\"alpha\"]");
}

#[test]
fn array_of_objects() {
    let v = Value::array(vec![
        Value::object([("b", Value::integer(2)), ("a", Value::integer(1))]),
        Value::object([("y", Value::integer(20))]),
    ]);
    assert_eq!(encode_jcs(&v), "[{\"a\":1,\"b\":2},{\"y\":20}]");
}

#[test]
fn deeply_nested_array() {
    let v = Value::array(vec![Value::array(vec![Value::array(vec![
        Value::integer(1),
    ])])]);
    assert_eq!(encode_jcs(&v), "[[[1]]]");
}

// ---------------------------------------------------------------------------
// Determinism (same input -> same output across calls)
// ---------------------------------------------------------------------------

#[test]
fn deterministic_across_calls() {
    let build = || {
        Value::object([
            ("zeta", Value::integer(2)),
            ("alpha", Value::string("x")),
            (
                "nested",
                Value::array(vec![
                    Value::integer(1),
                    Value::object([("k", Value::boolean(true))]),
                ]),
            ),
        ])
    };
    let a = encode_jcs(&build());
    for _ in 0..100 {
        assert_eq!(encode_jcs(&build()), a);
    }
}

#[test]
fn differently_ordered_inputs_produce_same_output() {
    let v1 = Value::object([
        ("a", Value::integer(1)),
        ("b", Value::integer(2)),
        ("c", Value::integer(3)),
    ]);
    let v2 = Value::object([
        ("c", Value::integer(3)),
        ("a", Value::integer(1)),
        ("b", Value::integer(2)),
    ]);
    let v3 = Value::object([
        ("b", Value::integer(2)),
        ("c", Value::integer(3)),
        ("a", Value::integer(1)),
    ]);
    let s = encode_jcs(&v1);
    assert_eq!(encode_jcs(&v2), s);
    assert_eq!(encode_jcs(&v3), s);
}

#[test]
fn realistic_envelope_shape_round_trips() {
    // Smoke test on something that looks like a real claim envelope.
    let v = Value::object([
        ("schemaVersion", Value::string("1")),
        ("bindingHash", Value::string("blake3-512:abcdef1234567890")),
        ("verdict", Value::string("holds")),
        ("inputCids", Value::array(vec![])),
        (
            "evidence",
            Value::object([
                ("kind", Value::string("contract")),
                ("schema", Value::string("blake3-512:000c01")),
            ]),
        ),
    ]);
    let s = encode_jcs(&v);
    // Top-level keys appear in lex order: bindingHash, evidence,
    // inputCids, schemaVersion, verdict.
    assert!(s.starts_with("{\"bindingHash\":"));
    let i_evidence = s.find("evidence").unwrap();
    let i_input = s.find("inputCids").unwrap();
    let i_schema = s.find("schemaVersion").unwrap();
    let i_verdict = s.find("verdict").unwrap();
    assert!(i_evidence < i_input);
    assert!(i_input < i_schema);
    assert!(i_schema < i_verdict);
}
