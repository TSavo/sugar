// SPDX-License-Identifier: MIT OR Apache-2.0

use std::path::PathBuf;

use sugar_walk::emit::rust_function_term_json_for_file;

fn read_canonicalizer_source(filename: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has a parent dir")
        .join("sugar-canonicalizer")
        .join("src")
        .join(filename);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("failed to read {:?}: {}", path, e))
}

#[test]
fn term_emit_ssa_hoists_statement_method_effects() {
    let src = read_canonicalizer_source("hash.rs");
    let file: syn::File = syn::parse_str(&src).expect("hash.rs parses");
    let bytes =
        rust_function_term_json_for_file(&file, "blake3_512_of", "sugar-canonicalizer/src/hash.rs")
            .expect("blake3_512_of term JSON");
    let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("term JSON");

    let surface = parsed["term_surface"].as_str().expect("term surface");
    assert!(
        surface.contains("method:update(hasher, [bytes])"),
        "term_surface missing update hoist: {surface}"
    );
    assert!(
        surface.contains("method:fill(method:finalize_xof(hasher_v1, []), [out])"),
        "term_surface missing fill hoist: {surface}"
    );
    assert!(
        surface.contains("call:encode(hex::encode, [out_v1])"),
        "term_surface did not use rebound digest bytes: {surface}"
    );

    let loss_record = serde_json::to_string(&parsed["loss_record"]).expect("loss record JSON");
    assert!(
        !loss_record.contains("update"),
        "update remained in loss_record: {loss_record}"
    );
    assert!(
        !loss_record.contains("fill"),
        "fill remained in loss_record: {loss_record}"
    );
}
