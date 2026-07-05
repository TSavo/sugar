// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Conformance test: DependentSort byte-pinned fixture.

use std::fs;
use std::sync::Arc;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};

fn to_cvalue(v: &serde_json::Value) -> Arc<CValue> {
    match v {
        serde_json::Value::Null => CValue::null(),
        serde_json::Value::Bool(b) => CValue::boolean(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(f) = n.as_f64() {
                CValue::string(format!("{}", f))
            } else {
                CValue::null()
            }
        }
        serde_json::Value::String(s) => CValue::string(s.clone()),
        serde_json::Value::Array(arr) => CValue::array(arr.iter().map(to_cvalue).collect()),
        serde_json::Value::Object(obj) => {
            CValue::object(obj.iter().map(|(k, v)| (k.clone(), to_cvalue(v))))
        }
    }
}

fn fixture_path() -> std::path::PathBuf {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    std::path::Path::new(manifest_dir)
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("protocol/conformance/2026-05-05-sort-dependent-byte-pinned.json")
}

fn cid_path() -> std::path::PathBuf {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    std::path::Path::new(manifest_dir)
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("protocol/conformance/2026-05-05-sort-dependent-byte-pinned.cid.txt")
}

#[test]
fn rust_kit_produces_dependent_sort_pinned_cid() {
    let fixture = fixture_path();
    let cid_file = cid_path();
    let json_str = fs::read_to_string(&fixture).unwrap_or_else(|e| panic!("read fixture: {}", e));
    let v: serde_json::Value =
        serde_json::from_str(&json_str).unwrap_or_else(|e| panic!("parse JSON: {}", e));
    let cv = to_cvalue(&v);
    let jcs = encode_jcs(&cv);
    let actual = blake3_512_of(jcs.as_bytes());
    let expected = fs::read_to_string(&cid_file)
        .unwrap_or_else(|e| panic!("read cid file: {}", e))
        .trim()
        .to_string();
    assert_eq!(actual, expected, "Rust kit CID must match pinned value");
}

#[test]
fn fixture_contains_dependent_sort() {
    let fixture = fixture_path();
    let json_str = fs::read_to_string(&fixture).unwrap_or_else(|e| panic!("read fixture: {}", e));
    let v: serde_json::Value =
        serde_json::from_str(&json_str).unwrap_or_else(|e| panic!("parse JSON: {}", e));
    assert_eq!(v.get("kind").and_then(|k| k.as_str()), Some("dependent"));
    assert_eq!(v.get("name").and_then(|n| n.as_str()), Some("Vec"));
    assert!(v.get("indexVar").is_some());
    assert!(v.get("indexSort").is_some());
}
