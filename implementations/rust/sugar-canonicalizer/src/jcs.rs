// SPDX-License-Identifier: Apache-2.0
//
// JCS-JSON encoder (RFC 8785 / "JSON Canonicalization Scheme"). v1.
// Mirrors implementations/cpp/sugar/canonicalizer/jcs.cpp 1:1.
//
// Rules (RFC 8785 + protocol/specs/2026-04-30-canonicalization-grammar.md
// pass 7):
//   - Object keys sorted by Unicode code-point order. For ASCII-only
//     keys this collapses to byte-order; the protocol's keys are all
//     ASCII so byte-order suffices.
//   - Numbers: integers serialized as plain decimal digits (we only
//     carry i64; floats are not produced by the kit/mint flow).
//   - Strings: UTF-8 verbatim, escape `"` and `\\` and U+0000..U+001F
//     as `\u00XX` (lowercase hex). RFC 8785 also permits the named
//     short escapes (\n etc.) but the C++ peer chose `\u00XX` for
//     determinism; we match.
//   - true / false / null verbatim.
//   - No whitespace anywhere.

use crate::value::Value;

pub fn encode_jcs(v: &Value) -> String {
    let mut out = String::new();
    encode_value(v, &mut out);
    out
}

fn encode_value(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Integer(n) => {
            // i128 toString -- plain decimal digits, no exponent/grouping.
            // Matches ECMA-262 ToString applied to a finite integer and
            // RFC 8785 integer serialization for the full i128 range. We do
            // not produce floats from the kit, so this covers all integer
            // cases; a small value's bytes are identical to the former i64
            // form (CID conserved).
            out.push_str(&n.to_string());
        }
        Value::String(s) => encode_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                encode_value(item, out);
            }
            out.push(']');
        }
        Value::Object(entries) => {
            // Sort by key (byte-order sort works for the ASCII keys
            // this protocol uses).
            let mut sorted: Vec<&(String, std::sync::Arc<Value>)> = entries.iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(&b.0));
            out.push('{');
            for (i, (k, val)) in sorted.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                encode_string(k, out);
                out.push(':');
                encode_value(val, out);
            }
            out.push('}');
        }
    }
}

fn encode_string(s: &str, out: &mut String) {
    out.push('"');
    // Iterate over Unicode scalar values. Non-ASCII characters (anything
    // >= U+0080) emit verbatim; pushing a char into a Rust String encodes
    // it back as the same UTF-8 bytes the input carried, so cross-language
    // hash agreement is preserved. The previous byte-iteration form
    // corrupted U+0080..U+10FFFF chars by treating each UTF-8 continuation
    // byte as a Latin-1 code point and re-encoding it.
    for c in s.chars() {
        if c == '"' {
            out.push_str("\\\"");
        } else if c == '\\' {
            out.push_str("\\\\");
        } else if (c as u32) < 0x20 {
            // U+0000..U+001F as \u00XX with lowercase hex
            const HEX: &[u8; 16] = b"0123456789abcdef";
            let n = c as u32;
            out.push_str("\\u00");
            out.push(HEX[((n >> 4) & 0xF) as usize] as char);
            out.push(HEX[(n & 0xF) as usize] as char);
        } else {
            out.push(c);
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::value::Value;

    #[test]
    fn encode_simple_object_sorts_keys() {
        let v = Value::object([("b", Value::integer(1)), ("a", Value::string("x"))]);
        assert_eq!(encode_jcs(&v), r#"{"a":"x","b":1}"#);
    }

    #[test]
    fn encode_nested_array_object() {
        let v = Value::object([(
            "xs",
            Value::array(vec![Value::integer(1), Value::integer(2)]),
        )]);
        assert_eq!(encode_jcs(&v), r#"{"xs":[1,2]}"#);
    }

    #[test]
    fn escape_quotes_and_backslash() {
        let v = Value::string(r#"a"b\c"#);
        assert_eq!(encode_jcs(&v), r#""a\"b\\c""#);
    }

    #[test]
    fn empty_object_and_array() {
        assert_eq!(encode_jcs(&Value::object([] as [(String, _); 0])), "{}");
        assert_eq!(encode_jcs(&Value::array(vec![])), "[]");
    }

    #[test]
    fn unicode_atomic_predicates_round_trip_verbatim() {
        // Regression: the previous byte-iteration form treated each UTF-8
        // continuation byte as a Latin-1 code point and re-encoded it,
        // corrupting U+0080..U+10FFFF chars. The kit's atomic predicate
        // names use exactly these (>=, <=, !=). Cross-language hash
        // agreement depends on this preservation.
        for sym in ["\u{2265}", "\u{2264}", "\u{2260}"] {
            let v = Value::string(sym);
            let encoded = encode_jcs(&v);
            // The encoded form is the input with surrounding quotes; nothing
            // else changes for these chars (they aren't ", \\, or U+0000..U+001F).
            assert_eq!(encoded, format!("\"{}\"", sym));
            // The bytes inside the quotes are the same UTF-8 bytes the input had.
            let inner = &encoded[1..encoded.len() - 1];
            assert_eq!(inner.as_bytes(), sym.as_bytes());
        }
    }

    #[test]
    fn mixed_ascii_and_unicode_preserved() {
        let s = "x \u{2265} 0";
        let v = Value::string(s);
        let encoded = encode_jcs(&v);
        assert_eq!(encoded, "\"x \u{2265} 0\"");
        assert_eq!(&encoded.as_bytes()[1..encoded.len() - 1], s.as_bytes());
    }

    #[test]
    fn unicode_in_object_key_and_value() {
        // Used as an atomic name in IR-JSON: {"kind":"atomic","name":"\u{2265}",...}
        let v = Value::object([("name", Value::string("\u{2265}"))]);
        let encoded = encode_jcs(&v);
        assert_eq!(encoded, "{\"name\":\"\u{2265}\"}");
        // Bytes match what a sibling impl (C++ writing raw UTF-8 bytes) produces.
        assert_eq!(encoded.as_bytes(), b"{\"name\":\"\xe2\x89\xa5\"}");
    }
}
