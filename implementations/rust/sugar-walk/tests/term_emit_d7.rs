// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_walk::emit::rust_function_term_json_for_file;

fn term_json(src: &str, name: &str) -> serde_json::Value {
    let file: syn::File = syn::parse_str(src).unwrap();
    let bytes = rust_function_term_json_for_file(&file, name, "d7.rs").unwrap();
    serde_json::from_slice(&bytes).expect("term JSON")
}

fn assert_loss(parsed: &serde_json::Value, dimension: &str) {
    assert_eq!(
        parsed["handling"].as_str(),
        Some("handles-partially-with-loss-record")
    );
    assert!(parsed["loss_record"]
        .as_array()
        .unwrap()
        .iter()
        .any(|loss| loss["loss"] == dimension));
}

fn assert_no_loss_or_effect(parsed: &serde_json::Value) {
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert!(parsed["loss_record"].as_array().unwrap().is_empty());
    assert!(parsed["effect_occurrences"].as_array().unwrap().is_empty());
}

#[test]
fn d7_lowers_mut_let_binding_with_path_call_rhs() {
    let parsed = term_json(
        r#"
            fn init_hasher() {
                let mut hasher = blake3::Hasher::new();
            }
        "#,
        "init_hasher",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("let(pattern_bind(hasher), call:new(blake3::Hasher::new, []), skip)")
    );
    assert_loss(&parsed, "let-binding-mutability");
}

#[test]
fn d7_lowers_let_binding_with_method_call_rhs() {
    let parsed = term_json(
        r#"
            struct Expr;
            impl Expr {
                fn some_method(self, arg: i32) -> i32 { arg }
            }
            fn use_method(expr: Expr, arg: i32) {
                let result = expr.some_method(arg);
            }
        "#,
        "use_method",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("let(pattern_bind(result), method:some_method(expr, [arg]), skip)")
    );
    assert_no_loss_or_effect(&parsed);
}

#[test]
fn d7_lowers_wildcard_let_binding_with_path_call_rhs() {
    let parsed = term_json(
        r#"
            fn discard(out: Vec<u8>) {
                let _ = hex::encode(out);
            }
        "#,
        "discard",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("let(pattern_wild(), call:encode(hex::encode, [out]), skip)")
    );
    assert_no_loss_or_effect(&parsed);
}

#[test]
fn d7_lowers_closure_in_value_position_with_loss_record() {
    let parsed = term_json(
        r#"
            fn make_incrementer() {
                let inc = |x| x + 1;
            }
        "#,
        "make_incrementer",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("let(pattern_bind(inc), closure([x], add(x, 1)), skip)")
    );
    assert_loss(&parsed, "closure-captures-environment");
}

#[test]
fn d7_lowers_vec_macro_value_to_array_with_macro_loss() {
    let parsed = term_json(
        r#"
            fn make_vec() -> Vec<i32> {
                vec![1, 2, 3]
            }
        "#,
        "make_vec",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("return(array([1, 2, 3]))")
    );
    assert_loss(&parsed, "macro-not-expanded");
}

#[test]
fn d7_lowers_println_statement_macro_to_opaque_macro_call() {
    let parsed = term_json(
        r#"
            fn log_hi() {
                println!("hi");
            }
        "#,
        "log_hi",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("macro_call:println(\"hi\")")
    );
    assert_loss(&parsed, "macro-not-expanded");
}

#[test]
fn d7_lowers_assert_statement_macro_to_opaque_macro_call() {
    let parsed = term_json(
        r#"
            fn check(cond: bool) {
                assert!(cond);
            }
        "#,
        "check",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("macro_call:assert(cond)")
    );
    assert_loss(&parsed, "macro-not-expanded");
}
