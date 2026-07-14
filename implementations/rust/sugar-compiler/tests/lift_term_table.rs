use std::sync::Arc;

use serde_json::json;
use sugar_canonicalizer::jcs_cid_of_json;
use sugar_compiler::kit_path::LiftTermTable;

#[test]
fn decoder_reuses_one_shared_node_per_term_cid() {
    let leaf_value = json!({"kind": "var", "name": "x"});
    let leaf = jcs_cid_of_json(&leaf_value);
    let parent_value = json!({
        "kind": "ctor", "name": "call:pair", "args": [leaf_value.clone(), leaf_value]
    });
    let parent = jcs_cid_of_json(&parent_value);
    let payload = json!({
        "termTable": {
            leaf.clone(): {"kind": "var", "name": "x"},
            parent.clone(): {"kind": "ctor", "name": "call:pair", "args": [
                {"kind": "term-ref", "cid": leaf.clone()},
                {"kind": "term-ref", "cid": leaf}
            ]}
        }
    });

    let table = LiftTermTable::decode(&payload).expect("decode table");
    let parent = table.get(&parent).expect("parent");
    let args = parent.args().expect("ctor args");

    assert!(Arc::ptr_eq(&args[0], &args[1]));
}

#[test]
fn decoder_loudly_rejects_a_missing_child_cid() {
    let payload = json!({
        "termTable": {
            "blake3-512:parent": {"kind": "ctor", "name": "call:pair", "args": [
                {"kind": "term-ref", "cid": "blake3-512:missing"}
            ]}
        }
    });

    let error = LiftTermTable::decode(&payload).expect_err("missing term CID must be loud");
    assert!(error.contains("missing term-table CID"), "{error}");
}
