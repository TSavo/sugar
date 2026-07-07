// SPDX-License-Identifier: MIT OR Apache-2.0
//
// serde_json -> canonical Value bridge. One public entry point:
// `jcs_cid_of_json` content-addresses any serde_json value by converting it
// to the canonical Value, JCS-encoding, and hashing. This is THE way a JSON
// artifact (a ledger, a diff verdict) gets a CID; callers must not hash
// pretty-printed serde output, whose bytes depend on key order and whitespace.

use std::sync::Arc;

use crate::hash::blake3_512_of;
use crate::jcs::encode_jcs;
use crate::value::Value;
use crate::CanonicalizerError;

/// Content-address a serde_json value: canonical Value -> JCS -> blake3-512.
/// Numbers must be integers; a non-integer number is invalid protocol input
/// and panics with the JSON path rather than guessing at float formatting.
pub fn jcs_cid_of_json(v: &serde_json::Value) -> String {
    let value = json_to_value(v, "$").unwrap_or_else(|err| panic!("{err}"));
    blake3_512_of(encode_jcs(&value).as_bytes())
}

fn json_to_value(j: &serde_json::Value, path: &str) -> Result<Arc<Value>, CanonicalizerError> {
    match j {
        serde_json::Value::Null => Ok(Value::null()),
        serde_json::Value::Bool(b) => Ok(Value::boolean(*b)),
        serde_json::Value::Number(n) => {
            // i64/u64 widen losslessly into the i128 carrier. A JSON number
            // that is neither is a float under default serde_json; the
            // protocol is integer-only, so refusing is the canonical form.
            if let Some(i) = n.as_i64() {
                Ok(Value::integer(i128::from(i)))
            } else if let Some(u) = n.as_u64() {
                Ok(Value::integer(i128::from(u)))
            } else if let Ok(i) = n.to_string().parse::<i128>() {
                // Big integers beyond i64/u64 (e.g. i128::MAX = 2^127-1, sworn
                // by real vendor proofs such as pandas') widen losslessly into
                // the i128 carrier. With serde_json's arbitrary_precision the
                // exact digits survive to here so the parse is exact -- the
                // same fallback proof_graph's canonical bridge uses. A true
                // float still refuses below.
                Ok(Value::integer(i))
            } else {
                Err(CanonicalizerError::Other(format!(
                    "non-integer JSON number at {path}: {n}"
                )))
            }
        }
        serde_json::Value::String(s) => Ok(Value::string(s.clone())),
        serde_json::Value::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for (idx, item) in items.iter().enumerate() {
                out.push(json_to_value(item, &array_path(path, idx))?);
            }
            Ok(Value::array(out))
        }
        serde_json::Value::Object(map) => {
            let mut out = Vec::with_capacity(map.len());
            for (key, value) in map {
                out.push((key.clone(), json_to_value(value, &object_path(path, key))?));
            }
            Ok(Value::object(out))
        }
    }
}

fn array_path(parent: &str, idx: usize) -> String {
    format!("{parent}[{idx}]")
}

fn object_path(parent: &str, key: &str) -> String {
    if !key.is_empty() && key.chars().all(|c| c == '_' || c.is_ascii_alphanumeric()) {
        format!("{parent}.{key}")
    } else {
        let quoted = serde_json::to_string(key).expect("JSON string key serialization");
        format!("{parent}[{quoted}]")
    }
}

#[cfg(test)]
mod tests {
    use super::jcs_cid_of_json;
    use crate::{blake3_512_of, encode_jcs, Value, BLAKE3_512_PREFIX};
    use serde_json::json;
    use std::any::Any;

    fn panic_message(panic: Box<dyn Any + Send>) -> String {
        if let Some(msg) = panic.downcast_ref::<String>() {
            msg.clone()
        } else if let Some(msg) = panic.downcast_ref::<&'static str>() {
            (*msg).to_string()
        } else {
            "<non-string panic>".to_string()
        }
    }

    #[test]
    fn cid_is_blake3_512_tagged_and_deterministic() {
        let v = json!({"b": 2, "a": "x", "nested": {"k": [1, 2, 3]}});
        let cid = jcs_cid_of_json(&v);
        assert!(cid.starts_with(BLAKE3_512_PREFIX));
        assert_eq!(cid, jcs_cid_of_json(&v));
    }

    #[test]
    fn cid_ignores_key_insertion_order() {
        let mut first = serde_json::Map::new();
        first.insert("zeta".into(), json!(1));
        first.insert("alpha".into(), json!(2));
        let mut second = serde_json::Map::new();
        second.insert("alpha".into(), json!(2));
        second.insert("zeta".into(), json!(1));
        assert_eq!(
            jcs_cid_of_json(&serde_json::Value::Object(first)),
            jcs_cid_of_json(&serde_json::Value::Object(second))
        );
    }

    #[test]
    fn cid_matches_manual_canonical_value_hash() {
        // Byte-identity with the existing encode_jcs + blake3_512_of path:
        // the bridge must not invent a second canonical form.
        let v = json!({"name": "ledger", "count": 42, "ok": true, "gap": null});
        let manual = Value::object(vec![
            ("name".to_string(), Value::string("ledger")),
            ("count".to_string(), Value::integer(42)),
            ("ok".to_string(), Value::boolean(true)),
            ("gap".to_string(), Value::null()),
        ]);
        assert_eq!(
            jcs_cid_of_json(&v),
            blake3_512_of(encode_jcs(&manual).as_bytes())
        );
    }

    #[test]
    fn jcs_cid_of_json_refuses_non_integer_number_with_path() {
        let v = json!({
            "outer": [
                {
                    "value": 1.5
                }
            ]
        });

        let panic = std::panic::catch_unwind(|| {
            let _ = jcs_cid_of_json(&v);
        })
        .expect_err("non-integer JSON numbers must be refused");
        let msg = panic_message(panic);
        assert!(msg.contains("non-integer JSON number"), "{msg}");
        assert!(msg.contains("$.outer[0].value"), "{msg}");
    }
}
