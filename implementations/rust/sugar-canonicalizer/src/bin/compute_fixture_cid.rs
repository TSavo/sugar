use serde_json::Value;
use std::fs;
use sugar_canonicalizer::jcs_cid_of_json;

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
    let cid = jcs_cid_of_json(&v);
    println!("{}", cid);
}
