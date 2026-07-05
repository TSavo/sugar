// SPDX-License-Identifier: MIT OR Apache-2.0
//
// FFI smoke test for the C ABI exposed by libsugar per CCP §6.2.
//
// Runs the same two pure identity atoms as the in-Rust smoke test
// (tests/compose_smoke.rs), but feeds them through the C entry point
// `pk_compose_chain_contracts` instead of the Rust function. Asserts
// that the CID returned across the C ABI equals the pinned CID from
// the Rust smoke test, byte-for-byte.
//
// This is the load-bearing assertion for §6.2: same algebra called
// via different binding modes MUST produce the same CID.
//
// We exercise the FFI in two ways:
//
//   1. The Rust-side helper `compose_chain_contracts_jcs`, which is
//      the testable layer below the extern "C" wrapper.
//   2. The actual `pk_compose_chain_contracts` extern "C" function,
//      called via raw pointers and the accessor / free family.
//
// Both paths must produce the same pinned CID.

use std::ffi::CStr;
use std::os::raw::c_char;
use std::sync::Arc;

use libsugar::compose::{build_value, cid_of_value, jcs_bytes_of_value, EffectSet, Locus};
use libsugar::ffi::{
    compose_chain_contracts_jcs, pk_compose_chain_contracts, pk_composition_result_body_jcs,
    pk_composition_result_cid, pk_composition_result_error, pk_composition_result_free,
};
use serde_json::{json, Value as JsonValue};
use sugar_canonicalizer::Value;
use sugar_ir_types::{IrFormula, IrTerm, Sort};

const PINNED_CID: &str = "blake3-512:36212b7bf7b9ccf264950940a33d64e1cfe88b6f4d8a47c01949fc64d9359d1813d6147aa2e1afe82b01e6e7ebcbe0a413683284b5f47ffef5bf364213304665";

/// Build the canonical body JSON for a pure identity contract whose
/// post is `result = <formal>`. We pass it through `build_value` (the
/// canonical encoding the algebra expects), then re-parse the JCS
/// bytes into a serde_json::Value so we can splice it into the
/// envelope shape the FFI consumes.
fn pure_identity_body_json(fn_name: &str, formal: &str) -> JsonValue {
    let formals = vec![formal.to_string()];
    let formal_sorts = vec![Sort::Primitive {
        name: "u32".to_string(),
    }];
    let return_sort = Sort::Primitive {
        name: "u32".to_string(),
    };
    let pre = IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    };
    let post = IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![
            IrTerm::Var {
                name: "result".to_string(),
            },
            IrTerm::Var {
                name: formal.to_string(),
            },
        ],
    };
    let effects = EffectSet::empty();
    let locus = Locus::unknown();

    let value: Arc<Value> = build_value(
        fn_name,
        &formals,
        &formal_sorts,
        &return_sort,
        &pre,
        &post,
        None,
        &effects,
        &locus,
        &[],
    );
    let body_bytes = jcs_bytes_of_value(&value);
    // Sanity: every per-atom CID is reproducible.
    let _atom_cid = cid_of_value(&value);
    serde_json::from_slice(&body_bytes).expect("canonical JCS is valid JSON")
}

fn build_inputs() -> (String, String) {
    // Inner is the leaf, outer consumes inner's result at formal 0.
    let inner_body = pure_identity_body_json("inner", "y");
    let outer_body = pure_identity_body_json("outer", "x");

    let atoms = json!([
        { "memento": inner_body.clone(), "formalIdx": 0 },
        { "memento": outer_body.clone(), "formalIdx": 0 },
    ]);
    // effects_jcs MUST mirror the embedded `effects` in each memento.
    // For pure atoms that's the empty array.
    let effects = json!([
        inner_body.get("effects").cloned().unwrap_or(json!([])),
        outer_body.get("effects").cloned().unwrap_or(json!([])),
    ]);

    (atoms.to_string(), effects.to_string())
}

fn build_impure_inputs() -> (String, String) {
    let inner_body = pure_identity_body_json("inner", "y");
    let mut outer_body = pure_identity_body_json("outer", "x");
    outer_body["effects"] = json!([{"kind": "io"}]);

    let atoms = json!([
        { "memento": inner_body.clone(), "formalIdx": 0 },
        { "memento": outer_body.clone(), "formalIdx": 0 },
    ]);
    let effects = json!([
        inner_body.get("effects").cloned().unwrap_or(json!([])),
        outer_body.get("effects").cloned().unwrap_or(json!([])),
    ]);

    (atoms.to_string(), effects.to_string())
}

#[test]
fn rust_jcs_entrypoint_pins_cid() {
    let (atoms_jcs, effects_jcs) = build_inputs();
    let (cid, body_jcs) = compose_chain_contracts_jcs(&atoms_jcs, &effects_jcs)
        .expect("compose_chain_contracts_jcs succeeds for two pure atoms");

    assert!(cid.starts_with("blake3-512:"));
    assert!(!body_jcs.is_empty());
    assert_eq!(
        cid, PINNED_CID,
        "FFI-side composed CID must equal the Rust-side pinned CID; same algebra → same CID"
    );
}

#[test]
fn rust_jcs_entrypoint_impure_input_returns_stable_refusal_cid() {
    let (atoms_jcs, effects_jcs) = build_impure_inputs();
    let first =
        compose_chain_contracts_jcs(&atoms_jcs, &effects_jcs).expect_err("impure input refuses");
    let second =
        compose_chain_contracts_jcs(&atoms_jcs, &effects_jcs).expect_err("impure input refuses");

    assert!(
        first.contains("composition-refusal"),
        "error must preserve the refusal artifact: {first}"
    );
    let first_cid = refusal_cid_from_error(&first);
    let second_cid = refusal_cid_from_error(&second);
    assert!(
        first_cid.starts_with("blake3-512:"),
        "refusal CID must be self-identifying, got {first_cid}"
    );
    assert_eq!(
        first_cid, second_cid,
        "same impure input must produce deterministic refusal CID"
    );
}

fn refusal_cid_from_error(message: &str) -> String {
    let (_, json) = message
        .split_once("refusal=")
        .expect("error includes serialized refusal");
    let value: JsonValue = serde_json::from_str(json).expect("refusal JSON parses");
    value["header"]["cid"]
        .as_str()
        .expect("refusal header cid")
        .to_string()
}

#[test]
fn extern_c_entrypoint_pins_cid() {
    let (atoms_jcs, effects_jcs) = build_inputs();
    let atoms_bytes = atoms_jcs.as_bytes();
    let effects_bytes = effects_jcs.as_bytes();

    // SAFETY: pointers stay valid for the duration of the call;
    // lengths are exact byte counts; the result handle is freed
    // at the end of this scope.
    unsafe {
        let result = pk_compose_chain_contracts(
            atoms_bytes.as_ptr() as *const c_char,
            effects_bytes.as_ptr() as *const c_char,
            atoms_bytes.len(),
            effects_bytes.len(),
        );
        assert!(
            !result.is_null(),
            "FFI must always return a non-null handle"
        );

        let err_ptr = pk_composition_result_error(result);
        if !err_ptr.is_null() {
            let msg = CStr::from_ptr(err_ptr).to_string_lossy().into_owned();
            pk_composition_result_free(result);
            panic!("pk_compose_chain_contracts returned error: {}", msg);
        }

        let cid_ptr = pk_composition_result_cid(result);
        assert!(
            !cid_ptr.is_null(),
            "cid pointer must be non-null on success"
        );
        let cid = CStr::from_ptr(cid_ptr).to_string_lossy().into_owned();

        let body_ptr = pk_composition_result_body_jcs(result);
        assert!(
            !body_ptr.is_null(),
            "body_jcs pointer must be non-null on success"
        );
        let body = CStr::from_ptr(body_ptr).to_string_lossy().into_owned();

        pk_composition_result_free(result);

        assert_eq!(
            cid, PINNED_CID,
            "extern \"C\" composed CID must equal the Rust-side pinned CID"
        );
        assert!(!body.is_empty(), "composed body JCS must be non-empty");
    }
}

#[test]
fn extern_c_handles_invalid_json() {
    let bad = b"not json";
    let effects = b"[]";
    unsafe {
        let result = pk_compose_chain_contracts(
            bad.as_ptr() as *const c_char,
            effects.as_ptr() as *const c_char,
            bad.len(),
            effects.len(),
        );
        assert!(!result.is_null());
        let err_ptr = pk_composition_result_error(result);
        assert!(
            !err_ptr.is_null(),
            "invalid JSON must populate the error accessor"
        );
        let msg = CStr::from_ptr(err_ptr).to_string_lossy().into_owned();
        pk_composition_result_free(result);
        assert!(
            msg.contains("invalid JCS JSON") || msg.contains("atoms_jcs"),
            "error message should identify the bad input: {}",
            msg
        );
    }
}

#[test]
fn extern_c_handles_null_input() {
    use std::ptr;
    unsafe {
        let result = pk_compose_chain_contracts(ptr::null(), ptr::null(), 0, 0);
        assert!(!result.is_null());
        let err_ptr = pk_composition_result_error(result);
        assert!(!err_ptr.is_null(), "null input must yield an error");
        let msg = CStr::from_ptr(err_ptr).to_string_lossy().into_owned();
        pk_composition_result_free(result);
        assert!(
            msg.contains("null"),
            "null-input error should mention null: {}",
            msg
        );
    }
}
