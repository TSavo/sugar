// SPDX-License-Identifier: MIT OR Apache-2.0

use serde_json::{json, Value};
use sugar_walk::emit::rust_function_term_json_for_file;

const UNRESOLVED_CALL_SIGNATURE_CID: &str = "blake3-512:2d368ad6123c2617a938deb71b7094a20cecfa6229909dad7c1d368aa0f931ed9bd2ff4bbf497962f8cdf104ddda56050275e6ee4a2998ce3d75b36925c362cf";

fn term_json(src: &str, name: &str) -> Value {
    let file: syn::File = syn::parse_str(src).unwrap();
    let bytes = rust_function_term_json_for_file(&file, name, "ffi_effect_occurrence.rs").unwrap();
    serde_json::from_slice(&bytes).expect("term JSON")
}

fn effect_occurrences(parsed: &Value) -> &[Value] {
    parsed["effect_occurrences"]
        .as_array()
        .expect("effect_occurrences array")
}

fn assert_no_loss(parsed: &Value) {
    assert!(parsed["loss_record"]
        .as_array()
        .expect("loss_record array")
        .is_empty());
}

fn assert_unresolved_call_occurrence(parsed: &Value, expected_name: &str, expected_binding: &str) {
    assert_no_loss(parsed);
    let effects = effect_occurrences(parsed);
    assert_eq!(effects.len(), 1, "expected one effect occurrence");
    let effect = &effects[0];
    let expected_discharge_key = format!("unresolved-call:{expected_name}");
    assert_eq!(effect["args"], json!({"name": expected_name}));
    assert_eq!(
        effect["discharge_key"].as_str(),
        Some(expected_discharge_key.as_str())
    );
    assert_eq!(effect["locator"]["abi"].as_str(), Some("C"));
    assert_eq!(
        effect["locator"]["binding"].as_str(),
        Some(expected_binding)
    );
    assert_eq!(
        effect["locator"]["file"].as_str(),
        Some("ffi_effect_occurrence.rs")
    );
    assert_eq!(effect["locator"]["source"].as_str(), Some("extern"));
    assert_eq!(effect["occurrence_kind"].as_str(), Some("UnresolvedCall"));
    assert_eq!(effect["role"].as_str(), Some("body"));
    assert_eq!(
        effect["signature_cid"].as_str(),
        Some(UNRESOLVED_CALL_SIGNATURE_CID)
    );
}

#[test]
fn tail_ffi_call_emits_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                fn rust_add(x: i32, y: i32) -> i32;
            }

            fn caller(x: i32) -> i32 {
                rust_add(x, 1)
            }
        "#,
        "caller",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("return(call:rust_add(rust_add, [x, 1]))")
    );
    assert_unresolved_call_occurrence(&parsed, "rust_add", "rust_add");
}

#[test]
fn tail_ffi_call_uses_link_name_for_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                #[link_name = "native_add"]
                fn rust_add(x: i32, y: i32) -> i32;
            }

            fn caller(x: i32) -> i32 {
                rust_add(x, 1)
            }
        "#,
        "caller",
    );

    assert_unresolved_call_occurrence(&parsed, "native_add", "rust_add");
}

#[test]
fn tail_local_call_does_not_emit_ffi_effect_occurrence() {
    let parsed = term_json(
        r#"
            fn helper(x: i32) -> i32 { x + 1 }

            fn caller(x: i32) -> i32 {
                helper(x)
            }
        "#,
        "caller",
    );

    assert_no_loss(&parsed);
    assert!(effect_occurrences(&parsed).is_empty());
}

#[test]
fn let_rhs_ffi_call_emits_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                fn rust_len(ptr: i32) -> i32;
            }

            fn caller(ptr: i32) -> i32 {
                let size: i32 = rust_len(ptr);
                size
            }
        "#,
        "caller",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("let(pattern_bind(size), call:rust_len(rust_len, [ptr]), return(size))")
    );
    assert_unresolved_call_occurrence(&parsed, "rust_len", "rust_len");
}

#[test]
fn let_rhs_ffi_call_uses_link_name_for_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                #[link_name = "native_len"]
                fn rust_len(ptr: i32) -> i32;
            }

            fn caller(ptr: i32) -> i32 {
                let size: i32 = rust_len(ptr);
                size
            }
        "#,
        "caller",
    );

    assert_unresolved_call_occurrence(&parsed, "native_len", "rust_len");
}

#[test]
fn let_rhs_local_call_does_not_emit_ffi_effect_occurrence() {
    let parsed = term_json(
        r#"
            fn helper(x: i32) -> i32 { x + 1 }

            fn caller(x: i32) -> i32 {
                let y: i32 = helper(x);
                y
            }
        "#,
        "caller",
    );

    assert_no_loss(&parsed);
    assert!(effect_occurrences(&parsed).is_empty());
}

#[test]
fn statement_ffi_call_emits_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                fn rust_touch(x: i32);
            }

            fn caller(x: i32) {
                rust_touch(x);
            }
        "#,
        "caller",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("call:rust_touch(rust_touch, [x])")
    );
    assert_unresolved_call_occurrence(&parsed, "rust_touch", "rust_touch");
}

#[test]
fn statement_ffi_call_uses_link_name_for_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                #[link_name = "native_touch"]
                fn rust_touch(x: i32);
            }

            fn caller(x: i32) {
                rust_touch(x);
            }
        "#,
        "caller",
    );

    assert_unresolved_call_occurrence(&parsed, "native_touch", "rust_touch");
}

#[test]
fn statement_local_call_does_not_emit_ffi_effect_occurrence() {
    let parsed = term_json(
        r#"
            fn helper(x: i32) {}

            fn caller(x: i32) {
                helper(x);
            }
        "#,
        "caller",
    );

    assert_no_loss(&parsed);
    assert!(effect_occurrences(&parsed).is_empty());
}

#[test]
fn unsafe_tail_ffi_call_emits_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                fn rust_add(x: i32, y: i32) -> i32;
            }

            fn caller(x: i32) -> i32 {
                unsafe { rust_add(x, 1) }
            }
        "#,
        "caller",
    );

    assert_unresolved_call_occurrence(&parsed, "rust_add", "rust_add");
}

#[test]
fn unsafe_let_rhs_ffi_call_emits_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                fn rust_len(ptr: i32) -> i32;
            }

            fn caller(ptr: i32) -> i32 {
                let size: i32 = unsafe { rust_len(ptr) };
                size
            }
        "#,
        "caller",
    );

    assert_unresolved_call_occurrence(&parsed, "rust_len", "rust_len");
}

#[test]
fn unsafe_statement_ffi_call_emits_effect_occurrence() {
    let parsed = term_json(
        r#"
            extern "C" {
                fn rust_touch(x: i32);
            }

            fn caller(x: i32) {
                unsafe { rust_touch(x); }
            }
        "#,
        "caller",
    );

    assert_unresolved_call_occurrence(&parsed, "rust_touch", "rust_touch");
}
