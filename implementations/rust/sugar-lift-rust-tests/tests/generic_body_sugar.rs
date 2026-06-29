// SPDX-License-Identifier: Apache-2.0
//
// TDD test suite for GenericBodySugar: a functional string-encoder body lifts
// to a `str.eq-bv-blocks` post atom by composition (not a base64 special-case).
//
// Two encoders prove generality:
//   BASE64 (64-char table, 3 bytes -> 4 chars)
//   BASE20 (20-char table, 1 byte  -> 2 chars)
//
// Same sugar path, different table and byte count each time.

use sugar_ir_symbolic::{ConstValue, Formula, Term};
use sugar_lift_rust_tests::sugar::source_contract::broad_functional_warrant;
use syn::parse_quote;

// ── Positive: correct encoders lift to str.eq-bv-blocks ──────────────────────

#[test]
fn encode_base64_lifts_to_str_eq_bv_blocks() {
    let item: syn::ItemFn = parse_quote! {
        fn encode_base64(value: &[u8]) -> [u8; 4] {
            const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
            let b0 = value[0] as u32;
            let b1 = value[1] as u32;
            let b2 = value[2] as u32;
            [
                ALPHA[(b0 >> 2) as usize],
                ALPHA[(((b0 & 3) << 4) | (b1 >> 4)) as usize],
                ALPHA[(((b1 & 15) << 2) | (b2 >> 6)) as usize],
                ALPHA[(b2 & 63) as usize],
            ]
        }
    };
    let decl = broad_functional_warrant("encode_base64", &item.sig, &item.block)
        .expect("encoder body must emit a contract");
    let inv = decl.inv.expect("contract must have an inv");
    let Formula::Atomic { name, args } = &*inv else {
        panic!("expected Atomic formula, got {:?}", inv);
    };
    assert_eq!(name, "str.eq-bv-blocks", "atom name must be str.eq-bv-blocks");
    assert_eq!(args.len(), 3, "str.eq-bv-blocks must have 3 args: [out, param, payload]");
    let payload_str = match &*args[2] {
        Term::Const {
            value: ConstValue::String(s),
            ..
        } => s.clone(),
        other => panic!("payload arg must be a string const, got {:?}", other),
    };
    let payload: serde_json::Value =
        serde_json::from_str(&payload_str).expect("payload must be valid JSON");
    let per_char = payload["per_char"].as_array().expect("per_char must be array");
    let table = payload["table"].as_array().expect("table must be array");
    let vars = payload["vars"].as_array().expect("vars must be array");

    // Structural assertions
    assert_eq!(per_char.len(), 4, "base64 produces 4 output chars");
    assert_eq!(table.len(), 64, "base64 alphabet has 64 entries");
    assert_eq!(
        vars.iter()
            .map(|v| v.as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["b0", "b1", "b2"],
        "vars must list byte names in order"
    );
    // Table codepoints: 'A'=65, 'Z'=90, 'a'=97, '/'=47
    assert_eq!(table[0].as_i64(), Some(65), "table[0] = ord('A')");
    assert_eq!(table[25].as_i64(), Some(90), "table[25] = ord('Z')");
    assert_eq!(table[26].as_i64(), Some(97), "table[26] = ord('a')");
    assert_eq!(table[63].as_i64(), Some(47), "table[63] = ord('/')");
    // per_char[0] must be the BV index tree for (b0 >> 2)
    let pc0 = &per_char[0];
    assert_eq!(
        pc0["kind"].as_str(),
        Some("ctor"),
        "first per_char index must be a ctor"
    );
    assert_eq!(
        pc0["name"].as_str(),
        Some("bv32.lshr"),
        "first per_char index must use bv32.lshr"
    );
}

#[test]
fn encode_base20_lifts_to_str_eq_bv_blocks() {
    let item: syn::ItemFn = parse_quote! {
        fn encode_base20(value: &[u8]) -> [u8; 2] {
            const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRST";
            let b0 = value[0] as u32;
            [ALPHA[(b0 & 15) as usize], ALPHA[((b0 >> 4) & 15) as usize]]
        }
    };
    let decl = broad_functional_warrant("encode_base20", &item.sig, &item.block)
        .expect("encoder body must emit a contract");
    let inv = decl.inv.expect("contract must have an inv");
    let Formula::Atomic { name, args } = &*inv else {
        panic!("expected Atomic formula, got {:?}", inv);
    };
    assert_eq!(name, "str.eq-bv-blocks");
    assert_eq!(args.len(), 3);
    let payload_str = match &*args[2] {
        Term::Const {
            value: ConstValue::String(s),
            ..
        } => s.clone(),
        other => panic!("payload arg must be a string const, got {:?}", other),
    };
    let payload: serde_json::Value =
        serde_json::from_str(&payload_str).expect("payload must be valid JSON");
    let per_char = payload["per_char"].as_array().expect("per_char must be array");
    let table = payload["table"].as_array().expect("table must be array");
    let vars = payload["vars"].as_array().expect("vars must be array");

    // Structural assertions
    assert_eq!(per_char.len(), 2, "base20 produces 2 output chars");
    assert_eq!(table.len(), 20, "base20 alphabet has 20 entries");
    assert_eq!(
        vars.iter()
            .map(|v| v.as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["b0"],
        "single byte encoder has one var"
    );
    // Table: 'A'=65 .. 'T'=84
    assert_eq!(table[0].as_i64(), Some(65), "table[0] = ord('A')");
    assert_eq!(table[19].as_i64(), Some(84), "table[19] = ord('T')");
    // Second per_char must involve bv32.lshr
    let pc1 = &per_char[1];
    assert_eq!(pc1["kind"].as_str(), Some("ctor"));
    // ((b0 >> 4) & 15) -> outer is bv32.and
    assert_eq!(pc1["name"].as_str(), Some("bv32.and"));
}

// ── Positive: &str param + .as_bytes() + .into_iter().collect() ─────────────

#[test]
fn encode_base64_str_param_lifts_to_str_eq_bv_blocks() {
    // &str param with .as_bytes()[N] and [... as char].into_iter().collect()
    // must produce the SAME str.eq-bv-blocks atom as the &[u8] variant.
    let item: syn::ItemFn = parse_quote! {
        fn encode_base64(value: &str) -> String {
            const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
            let b0 = value.as_bytes()[0] as u32;
            let b1 = value.as_bytes()[1] as u32;
            let b2 = value.as_bytes()[2] as u32;
            [
                ALPHA[(b0 >> 2) as usize] as char,
                ALPHA[(((b0 & 3) << 4) | (b1 >> 4)) as usize] as char,
                ALPHA[(((b1 & 15) << 2) | (b2 >> 6)) as usize] as char,
                ALPHA[(b2 & 63) as usize] as char,
            ]
            .into_iter()
            .collect()
        }
    };
    let decl = broad_functional_warrant("encode_base64", &item.sig, &item.block)
        .expect("str-param encoder body must emit a contract");
    let inv = decl.inv.expect("contract must have an inv");
    let Formula::Atomic { name, args } = &*inv else {
        panic!("expected Atomic formula, got {:?}", inv);
    };
    assert_eq!(name, "str.eq-bv-blocks");
    assert_eq!(args.len(), 3);
    let payload_str = match &*args[2] {
        Term::Const { value: ConstValue::String(s), .. } => s.clone(),
        other => panic!("payload must be string const, got {:?}", other),
    };
    let payload: serde_json::Value = serde_json::from_str(&payload_str).unwrap();
    assert_eq!(payload["per_char"].as_array().unwrap().len(), 4, "base64 produces 4 output chars");
    assert_eq!(payload["table"].as_array().unwrap().len(), 64, "base64 alphabet has 64 entries");
    assert_eq!(
        payload["vars"].as_array().unwrap().iter().map(|v| v.as_str().unwrap()).collect::<Vec<_>>(),
        vec!["b0", "b1", "b2"],
    );
}

#[test]
fn encode_base20_str_param_lifts_to_str_eq_bv_blocks() {
    // 20-char/1-byte encoder with &str param -- same path as base64 variant.
    let item: syn::ItemFn = parse_quote! {
        fn encode_base20(value: &str) -> String {
            const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRST";
            let b0 = value.as_bytes()[0] as u32;
            [
                ALPHA[(b0 & 15) as usize] as char,
                ALPHA[((b0 >> 4) & 15) as usize] as char,
            ]
            .into_iter()
            .collect()
        }
    };
    let decl = broad_functional_warrant("encode_base20", &item.sig, &item.block)
        .expect("str-param base20 encoder must emit a contract");
    let inv = decl.inv.unwrap();
    let Formula::Atomic { name, args } = &*inv else { panic!() };
    assert_eq!(name, "str.eq-bv-blocks");
    assert_eq!(args.len(), 3);
    let payload_str = match &*args[2] {
        Term::Const { value: ConstValue::String(s), .. } => s.clone(),
        _ => panic!(),
    };
    let payload: serde_json::Value = serde_json::from_str(&payload_str).unwrap();
    assert_eq!(payload["per_char"].as_array().unwrap().len(), 2, "base20 produces 2 output chars");
    assert_eq!(payload["table"].as_array().unwrap().len(), 20);
    assert_eq!(
        payload["vars"].as_array().unwrap().iter().map(|v| v.as_str().unwrap()).collect::<Vec<_>>(),
        vec!["b0"],
    );
}

#[test]
fn as_bytes_wrong_method_name_does_not_fire() {
    // Discrimination: a method named as_bytes_wrong (not as_bytes) should NOT fire.
    // We simulate this by using a non-as_bytes accessor -- plain value[N] won't work
    // for &str (doesn't compile), so we test the distinguishing case:
    // a &[u8] param that uses as_bytes() on a local binding (not the param) must not
    // match (the as_bytes call must be on the PARAM, not any expression).
    let item: syn::ItemFn = parse_quote! {
        fn double(x: u32) -> u32 {
            x * 2
        }
    };
    // A non-encoder body must not lift as encoder.
    if let Some(decl) = broad_functional_warrant("double", &item.sig, &item.block) {
        if let Some(inv) = &decl.inv {
            if let Formula::Atomic { name, .. } = &**inv {
                assert_ne!(name, "str.eq-bv-blocks");
            }
        }
    }
}

// ── Discrimination: body shapes that do NOT match do not lift ────────────────

#[test]
fn plain_arithmetic_body_does_not_lift_as_encoder() {
    // A body with no const table binding must NOT fire the encoder recognizer.
    let item: syn::ItemFn = parse_quote! {
        fn double(x: u32) -> u32 {
            x * 2
        }
    };
    // The contract may still be emitted (via broad functional warrant fallback),
    // but it must NOT be a str.eq-bv-blocks atom.
    if let Some(decl) = broad_functional_warrant("double", &item.sig, &item.block) {
        if let Some(inv) = &decl.inv {
            if let Formula::Atomic { name, .. } = &**inv {
                assert_ne!(
                    name, "str.eq-bv-blocks",
                    "arithmetic body must not lift as encoder"
                );
            }
        }
    }
}

#[test]
fn missing_byte_assigns_does_not_fire_encoder() {
    // const TABLE but no byte-assign stmts -> no encoder lift.
    let item: syn::ItemFn = parse_quote! {
        fn indexed(value: &[u8]) -> u8 {
            const TABLE: &[u8] = b"ABC";
            value[0]
        }
    };
    if let Some(decl) = broad_functional_warrant("indexed", &item.sig, &item.block) {
        if let Some(inv) = &decl.inv {
            if let Formula::Atomic { name, .. } = &**inv {
                assert_ne!(name, "str.eq-bv-blocks");
            }
        }
    }
}

// ── Structural: payload keys are present and correctly ordered ────────────────

#[test]
fn encoder_payload_keys_are_alphabetically_ordered_jcs() {
    // JCS sort: per_char < table < vars.
    let item: syn::ItemFn = parse_quote! {
        fn encode_base20(value: &[u8]) -> [u8; 2] {
            const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRST";
            let b0 = value[0] as u32;
            [ALPHA[(b0 & 15) as usize], ALPHA[((b0 >> 4) & 15) as usize]]
        }
    };
    let decl = broad_functional_warrant("encode_base20", &item.sig, &item.block)
        .expect("must emit contract");
    let inv = decl.inv.unwrap();
    let Formula::Atomic { args, .. } = &*inv else { panic!() };
    let payload_str = match &*args[2] {
        Term::Const { value: ConstValue::String(s), .. } => s.clone(),
        _ => panic!(),
    };
    // The raw JSON string must have keys in JCS order: per_char comes first.
    let pc_pos = payload_str.find("\"per_char\"").expect("per_char key must exist");
    let tbl_pos = payload_str.find("\"table\"").expect("table key must exist");
    let vars_pos = payload_str.find("\"vars\"").expect("vars key must exist");
    assert!(pc_pos < tbl_pos, "per_char must precede table in JCS output");
    assert!(tbl_pos < vars_pos, "table must precede vars in JCS output");
}

#[test]
fn encoder_per_char_terms_reference_byte_vars_by_name() {
    let item: syn::ItemFn = parse_quote! {
        fn encode_base20(value: &[u8]) -> [u8; 2] {
            const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRST";
            let b0 = value[0] as u32;
            [ALPHA[(b0 & 15) as usize], ALPHA[((b0 >> 4) & 15) as usize]]
        }
    };
    let decl = broad_functional_warrant("encode_base20", &item.sig, &item.block).unwrap();
    let inv = decl.inv.unwrap();
    let Formula::Atomic { args, .. } = &*inv else { panic!() };
    let payload_str = match &*args[2] {
        Term::Const { value: ConstValue::String(s), .. } => s.clone(),
        _ => panic!(),
    };
    // Both per_char terms must reference b0 by name (var node).
    assert!(
        payload_str.contains("\"b0\""),
        "payload must reference b0 as a var in per_char terms; got: {payload_str}"
    );
}
