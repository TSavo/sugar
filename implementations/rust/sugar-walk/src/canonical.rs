// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Bridge from `sugar_ir_types::IrFormula` and `sugar_ir_types::IrTerm`
// (which are serde-serializable) into `sugar_canonicalizer::Value`
// (which is what the JCS encoder consumes).
//
// We go through `serde_json::Value` as a structural intermediate. The IR
// types' serde representation already produces the canonical JSON shape
// (tagged unions with `kind`, etc.) that v1.5.0 mementos expect.

use std::sync::Arc;

use serde_json::Value as JsonValue;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_ir_types::{IrFormula, IrTerm};

/// Convert a serde_json::Value tree into the canonicalizer's Arc<Value> tree.
/// Object key order is preserved at build time; the JCS encoder re-sorts at
/// emit time, so order here does not affect the resulting bytes.
pub fn serde_to_canonical(j: JsonValue) -> Arc<Value> {
    match j {
        JsonValue::Null => Value::null(),
        JsonValue::Bool(b) => Value::boolean(b),
        JsonValue::Number(n) => match n.as_i64() {
            Some(i) => Value::integer(i128::from(i)),
            None => {
                // A float or u64-out-of-i64-range number must NOT be encoded as
                // a plain string: that would make the numeric constant 42.5 and
                // the string "42.5" produce identical CIDs, breaking content-
                // address distinctness. Use a tagged object to distinguish the
                // source type from a literal string value.
                Value::object(vec![(
                    "__sugar_non_i64_number__".to_string(),
                    Value::string(n.to_string()),
                )])
            }
        },
        JsonValue::String(s) => Value::string(s),
        JsonValue::Array(items) => {
            let mapped: Vec<Arc<Value>> = items.into_iter().map(serde_to_canonical).collect();
            Value::array(mapped)
        }
        JsonValue::Object(map) => {
            let entries: Vec<(String, Arc<Value>)> = map
                .into_iter()
                .map(|(k, v)| (k, serde_to_canonical(v)))
                .collect();
            Value::object(entries)
        }
    }
}

/// Canonicalize an `IrFormula` into a JCS-canonicalizer Value tree.
pub fn formula_to_canonical(f: &IrFormula) -> Arc<Value> {
    let serde =
        serde_json::to_value(f).expect("IrFormula serializes (sugar-ir-types is generated)");
    serde_to_canonical(serde)
}

/// Canonicalize an `IrTerm` into a JCS-canonicalizer Value tree.
pub fn term_to_canonical(t: &IrTerm) -> Arc<Value> {
    let serde = serde_json::to_value(t).expect("IrTerm serializes (sugar-ir-types is generated)");
    serde_to_canonical(serde)
}

/// Compute the BLAKE3-512 CID of a canonicalizer Value, JCS-encoded.
/// Returns the spec's `"blake3-512:<hex>"` self-identifying string.
pub fn cid_of_value(v: &Value) -> String {
    blake3_512_of(encode_jcs(v).as_bytes())
}

/// Encode a canonicalizer Value to JCS bytes.
pub fn jcs_bytes_of_value(v: &Value) -> Vec<u8> {
    encode_jcs(v).into_bytes()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wp::{atomic_ge, const_int, var};

    #[test]
    fn formula_canonical_is_deterministic() {
        let f = atomic_ge(var("y"), const_int(10)).into_formula();
        let v1 = formula_to_canonical(&f);
        let v2 = formula_to_canonical(&f);
        assert_eq!(cid_of_value(&v1), cid_of_value(&v2));
    }

    #[test]
    fn distinct_formulas_distinct_cids() {
        let f1 = atomic_ge(var("y"), const_int(10)).into_formula();
        let f2 = atomic_ge(const_int(42), const_int(10)).into_formula();
        let v1 = formula_to_canonical(&f1);
        let v2 = formula_to_canonical(&f2);
        assert_ne!(cid_of_value(&v1), cid_of_value(&v2));
    }

    #[test]
    fn non_i64_number_distinct_from_string_of_same_digits() {
        // Bug #8: a JSON Number that doesn't fit i64 (e.g. 42.5) must
        // NOT canonicalize to the same value as the string "42.5".
        // Before the fix, both fell through to Value::string(n.to_string()).
        let number_json: serde_json::Value = serde_json::from_str("42.5").unwrap();
        let string_json: serde_json::Value = serde_json::from_str("\"42.5\"").unwrap();

        let number_canon = serde_to_canonical(number_json);
        let string_canon = serde_to_canonical(string_json);

        // Their CIDs must differ — they are distinct source types.
        assert_ne!(
            cid_of_value(&number_canon),
            cid_of_value(&string_canon),
            "float 42.5 and string \"42.5\" must produce distinct CIDs"
        );

        // The number canonical value must be a tagged object, not a plain string.
        let bytes = encode_jcs(&number_canon);
        let reparsed: serde_json::Value = serde_json::from_str(&bytes).unwrap();
        assert!(
            reparsed.is_object(),
            "non-i64 number must canonicalize to a tagged object, not a string: {}",
            bytes
        );
    }
}
