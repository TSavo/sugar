// SPDX-License-Identifier: Apache-2.0
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

/// Content-address a serde_json value: canonical Value -> JCS -> blake3-512.
/// Numbers are carried as i64 (the protocol's canonical form produces no
/// floats); non-i64 numerics collapse the same way the emit path collapses
/// them, so a CID computed here is byte-identical to one computed there.
pub fn jcs_cid_of_json(v: &serde_json::Value) -> String {
    blake3_512_of(encode_jcs(&json_to_value(v)).as_bytes())
}

fn json_to_value(j: &serde_json::Value) -> Arc<Value> {
    match j {
        serde_json::Value::Null => Value::null(),
        serde_json::Value::Bool(b) => Value::boolean(*b),
        serde_json::Value::Number(n) => {
            // i64/u64 widen losslessly into the i128 carrier. A JSON number
            // that is neither (only a float under default serde_json) keeps
            // the legacy truncating collapse -- the kit/mint flow never emits
            // floats here, and a wide INTEGER const is carried as a String
            // (sort-tagged Int) on the proofir path, not as a bare number.
            if let Some(i) = n.as_i64() {
                Value::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                Value::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                Value::integer(f as i128)
            } else {
                Value::integer(0)
            }
        }
        serde_json::Value::String(s) => Value::string(s.clone()),
        serde_json::Value::Array(items) => Value::array(items.iter().map(json_to_value).collect()),
        serde_json::Value::Object(map) => Value::object(
            map.iter()
                .map(|(k, v)| (k.clone(), json_to_value(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::jcs_cid_of_json;
    use crate::{blake3_512_of, encode_jcs, Value, BLAKE3_512_PREFIX};
    use serde_json::json;

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
}
