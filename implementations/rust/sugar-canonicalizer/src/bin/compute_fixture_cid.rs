use serde_json::Value;
use std::fs;
use std::sync::Arc;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};

fn to_cvalue(v: &Value) -> Arc<CValue> {
    match v {
        Value::Null => CValue::null(),
        Value::Bool(b) => CValue::boolean(*b),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(f) = n.as_f64() {
                CValue::string(format!("{}", f))
            } else {
                CValue::null()
            }
        }
        Value::String(s) => CValue::string(s.clone()),
        Value::Array(arr) => CValue::array(arr.iter().map(to_cvalue).collect()),
        Value::Object(obj) => CValue::object(obj.iter().map(|(k, v)| (k.clone(), to_cvalue(v)))),
    }
}

fn main() {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let repo_root = std::path::Path::new(manifest_dir)
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let args: Vec<String> = std::env::args().collect();
    let fixture_path = if args.len() > 1 {
        std::path::PathBuf::from(&args[1])
    } else {
        repo_root.join("protocol/conformance/2026-05-05-sort-dependent-byte-pinned.json")
    };
    let json_str = fs::read_to_string(&fixture_path)
        .unwrap_or_else(|e| panic!("read fixture {:?}: {}", fixture_path, e));
    let v: Value = serde_json::from_str(&json_str).unwrap_or_else(|e| panic!("parse JSON: {}", e));
    let cv = to_cvalue(&v);
    let jcs = encode_jcs(&cv);
    let cid = blake3_512_of(jcs.as_bytes());
    println!("{}", cid);
}
