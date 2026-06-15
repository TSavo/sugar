// SPDX-License-Identifier: Apache-2.0
//
// Conformance test: FunctionSort byte-pinned fixture.
// Verifies that the Rust kit produces the pinned CID for the
// cross-kit conformance fixture containing Sort::Function.

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
        .join("protocol/conformance/2026-05-05-sort-function-byte-pinned.json")
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
        .join("protocol/conformance/2026-05-05-sort-function-byte-pinned.cid.txt")
}

#[test]
fn rust_kit_produces_function_sort_pinned_cid() {
    let fixture = fixture_path();
    let cid_file = cid_path();

    let json_str = fs::read_to_string(&fixture)
        .unwrap_or_else(|e| panic!("read fixture {:?}: {}", fixture, e));
    let v: serde_json::Value =
        serde_json::from_str(&json_str).unwrap_or_else(|e| panic!("parse JSON: {}", e));
    let cv = to_cvalue(&v);
    let jcs = encode_jcs(&cv);
    let actual = blake3_512_of(jcs.as_bytes());

    let expected = fs::read_to_string(&cid_file)
        .unwrap_or_else(|e| panic!("read cid file {:?}: {}", cid_file, e))
        .trim()
        .to_string();

    assert_eq!(
        actual, expected,
        "Rust kit CID must match pinned value.\n  actual:   {}\n  expected: {}",
        actual, expected
    );
}

#[test]
fn fixture_contains_function_sort() {
    let fixture = fixture_path();
    let json_str = fs::read_to_string(&fixture)
        .unwrap_or_else(|e| panic!("read fixture {:?}: {}", fixture, e));
    let v: serde_json::Value =
        serde_json::from_str(&json_str).unwrap_or_else(|e| panic!("parse JSON: {}", e));

    let has_function = v.get("kind").and_then(|k| k.as_str()) == Some("function");
    let has_args = v.get("args").and_then(|a| a.as_array()).is_some();
    let has_return = v.get("return").is_some();

    assert!(has_function, "fixture must be a FunctionSort");
    assert!(has_args, "fixture must have args array");
    assert!(has_return, "fixture must have return sort");
}
