// SPDX-License-Identifier: MIT OR Apache-2.0
//
// serde_json -> canonical Value bridge. ONE door for protocol content-
// addressing (#3901):
//
//   * `json_to_value` / `json_to_value_at` — Result form; refuses non-
//     integer numbers. Feed, mint, claim-envelope, and libsugar::canonical
//     must call this rather than re-implement Number→Value.
//   * `jcs_cid_of_json` — same conversion + JCS + blake3-512; panics on
//     non-integer input so a CID is never minted from a float guess.
//
// Callers must not hash pretty-printed serde output (key order /
// whitespace drift) and must not grow a second Number membrane
// (`as_f64` → string / null / silent zero). The dual-encoder residual
// instrument greps for those shapes.

use std::sync::Arc;

use crate::hash::blake3_512_of;
use crate::jcs::encode_jcs;
use crate::value::Value;
use crate::CanonicalizerError;

/// Content-address a serde_json value: canonical Value -> JCS -> blake3-512.
/// Numbers must be integers; a non-integer number is invalid protocol input
/// and panics with the JSON path rather than guessing at float formatting.
pub fn jcs_cid_of_json(v: &serde_json::Value) -> String {
    let value = json_to_value_at(v, "$").unwrap_or_else(|err| panic!("{err}"));
    blake3_512_of(encode_jcs(&value).as_bytes())
}

/// Convert serde_json → canonical `Value` at path `"$"`.
///
/// #3901 single door: integer numbers widen into the i128 carrier; every
/// non-integer JSON number is `Err`. No silent zero, no float→string, no
/// float→null. Call this from feed/mint instead of a local encoder.
pub fn json_to_value(j: &serde_json::Value) -> Result<Arc<Value>, CanonicalizerError> {
    json_to_value_at(j, "$")
}

/// Convert serde_json → canonical `Value`, reporting JSON path on refusal.
pub fn json_to_value_at(
    j: &serde_json::Value,
    path: &str,
) -> Result<Arc<Value>, CanonicalizerError> {
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
                out.push(json_to_value_at(item, &array_path(path, idx))?);
            }
            Ok(Value::array(out))
        }
        serde_json::Value::Object(map) => {
            let mut out = Vec::with_capacity(map.len());
            for (key, value) in map {
                out.push((
                    key.clone(),
                    json_to_value_at(value, &object_path(path, key))?,
                ));
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

    #[test]
    fn json_to_value_public_door_accepts_integers_and_refuses_floats() {
        use super::json_to_value;
        let i = json_to_value(&json!(42)).expect("i64");
        assert_eq!(
            encode_jcs(i.as_ref()),
            encode_jcs(Value::integer(42).as_ref())
        );
        let big = u64::MAX;
        let u =
            json_to_value(&serde_json::Value::Number(serde_json::Number::from(big))).expect("u64");
        assert_eq!(
            encode_jcs(u.as_ref()),
            encode_jcs(Value::integer(i128::from(big)).as_ref())
        );
        let err = json_to_value(&json!(3.14)).expect_err("float must refuse");
        let msg = err.to_string();
        assert!(msg.contains("non-integer"), "{msg}");
        assert!(msg.contains("3.14"), "{msg}");
    }
}

/// #3901 dual Number→CValue encoder membrane.
///
/// Axis `R_mint_feed_local_number_encoder`: production mint/feed critical-path
/// sources must route JSON numbers through `sugar_canonicalizer::json_to_value`
/// (or `json_to_value_at`). A second local Number arm is the habitat of the
/// silent-zero / float→string / float→null class.
///
/// Replacement: delete the local arm; call the shared door; map errors into
/// the caller's typed residual (`FeedError::Incomplete`, panic, SugarError).
#[cfg(test)]
mod dual_number_encoder_3901_tests {
    use std::path::PathBuf;

    /// Mint/feed critical path: claim-envelope mint, feed fold, libsugar CID.
    const CRITICAL_PATH: &[&str] = &[
        "sugar-claim-envelope/src/lib.rs",
        "sugar-compiler/src/feed_from_tree.rs",
        "libsugar/src/canonical.rs",
    ];

    fn rust_impl_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("sugar-canonicalizer lives under implementations/rust")
            .to_path_buf()
    }

    /// True when a line is a local fail-open Number membrane (not a comment /
    /// string discussing the banned shape).
    fn is_local_failopen_number_arm(line: &str) -> bool {
        let trimmed = line.trim_start();
        if trimmed.starts_with("//") {
            return false;
        }
        // Local arms that invent a CValue from a non-integer without the door.
        let has_as_f64 = trimmed.contains("as_f64()");
        let silent_zero = trimmed.contains("Value::integer(0)")
            || trimmed.contains("CValue::integer(0)")
            || trimmed.contains("unwrap_or(0)");
        let float_to_string_or_null = has_as_f64
            && (trimmed.contains("to_string()")
                || trimmed.contains("Value::null()")
                || trimmed.contains("Value::string")
                || trimmed.contains("CValue::string")
                || trimmed.contains("as i128")
                || trimmed.contains("as i64"));
        float_to_string_or_null || (has_as_f64 && silent_zero)
    }

    fn file_uses_shared_door(src: &str) -> bool {
        src.contains("json_to_value(") || src.contains("json_to_value_at(")
    }

    #[test]
    fn r_mint_feed_local_number_encoder_is_zero() {
        let root = rust_impl_root();
        let mut offenders: Vec<String> = Vec::new();

        for rel in CRITICAL_PATH {
            let path = root.join(rel);
            let src = std::fs::read_to_string(&path)
                .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
            if !file_uses_shared_door(&src) {
                offenders.push(format!(
                    "{rel}: missing sugar_canonicalizer::json_to_value call — \
                     R_mint_feed_local_number_encoder: route Number→Value through \
                     the shared refuse door (json.rs)"
                ));
            }
            for (idx, line) in src.lines().enumerate() {
                if is_local_failopen_number_arm(line) {
                    offenders.push(format!(
                        "{rel}:{}: local fail-open Number arm: {}",
                        idx + 1,
                        line.trim()
                    ));
                }
            }
        }

        let r = offenders.len();
        eprintln!(
            "R_mint_feed_local_number_encoder={r} — critical mint/feed path must \
             share sugar_canonicalizer::json_to_value (refuse non-integers)"
        );
        for o in &offenders {
            eprintln!("  offender: {o}");
        }
        assert!(
            r == 0,
            "R_mint_feed_local_number_encoder={r} > 0 — delete local Number→Value \
             arms on the mint/feed path; call sugar_canonicalizer::json_to_value. \
             offenders:\n{}",
            offenders.join("\n")
        );
    }
}
