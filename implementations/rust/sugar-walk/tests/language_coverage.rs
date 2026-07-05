// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Language-coverage tests: each Rust expression shape that lifts to an
// IrTerm or IrFormula gets one assertion here. Demonstrates that the
// substrate accepts realistic Rust source as input, not just toy fixtures.

use sugar_walk::lift::{lift_expr_to_term, lift_predicate};

fn parse_expr(src: &str) -> syn::Expr {
    syn::parse_str(src).expect("expr parses")
}

#[test]
fn references_pass_through() {
    // &x lifts as just x; &mut x same.
    let t1 = lift_expr_to_term(&parse_expr("&x")).unwrap();
    let t2 = lift_expr_to_term(&parse_expr("&mut x")).unwrap();
    let t3 = lift_expr_to_term(&parse_expr("x")).unwrap();
    assert_eq!(t1, t3);
    assert_eq!(t2, t3);
}

#[test]
fn casts_pass_through() {
    // `x as u32` lifts as just x.
    let t1 = lift_expr_to_term(&parse_expr("x as u32")).unwrap();
    let t2 = lift_expr_to_term(&parse_expr("x")).unwrap();
    assert_eq!(t1, t2);
}

#[test]
fn deref_passes_through() {
    // `*x` lifts as x for substitution purposes.
    let t1 = lift_expr_to_term(&parse_expr("*x")).unwrap();
    let t2 = lift_expr_to_term(&parse_expr("x")).unwrap();
    assert_eq!(t1, t2);
}

#[test]
fn field_access_lifts_as_ctor() {
    let t = lift_expr_to_term(&parse_expr("s.field")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"field\""));
    assert!(
        json.contains("\".field\""),
        "field name encoded with leading dot: {}",
        json
    );
}

#[test]
fn index_lifts_as_ctor() {
    let t = lift_expr_to_term(&parse_expr("arr[0]")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"index\""));
    assert!(json.contains("\"arr\""));
}

#[test]
fn method_call_lifts_with_method_name() {
    let t = lift_expr_to_term(&parse_expr("v.len()")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"method:len\""));
    assert!(json.contains("\"v\""));
}

#[test]
fn method_call_with_args_includes_them() {
    let t = lift_expr_to_term(&parse_expr("buf.write(data, 5)")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"method:write\""));
    assert!(json.contains("\"buf\""));
    assert!(json.contains("\"data\""));
    assert!(json.contains("5"));
}

#[test]
fn range_lifts_as_ctor() {
    let half_open = lift_expr_to_term(&parse_expr("0..10")).unwrap();
    let closed = lift_expr_to_term(&parse_expr("0..=10")).unwrap();
    let half_json = serde_json::to_string(&half_open).unwrap();
    let closed_json = serde_json::to_string(&closed).unwrap();
    assert!(half_json.contains("\"range\""));
    assert!(closed_json.contains("\"range_incl\""));
}

#[test]
fn tuple_lifts_as_ctor() {
    let t = lift_expr_to_term(&parse_expr("(a, b, 42)")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"tuple\""));
    assert!(json.contains("\"a\""));
    assert!(json.contains("\"b\""));
    assert!(json.contains("42"));
}

#[test]
fn bool_literal_lifts() {
    let t_true = lift_expr_to_term(&parse_expr("true")).unwrap();
    let t_false = lift_expr_to_term(&parse_expr("false")).unwrap();
    let json_true = serde_json::to_string(&t_true).unwrap();
    let json_false = serde_json::to_string(&t_false).unwrap();
    assert!(json_true.contains("\"Bool\""));
    assert!(json_true.contains("true"));
    assert!(json_false.contains("false"));
}

#[test]
fn bitwise_ops_lift_as_ctor() {
    for (src, op) in [
        ("x & y", "&"),
        ("x | y", "|"),
        ("x ^ y", "^"),
        ("x << 2", "<<"),
        ("x >> 1", ">>"),
    ] {
        let t = lift_expr_to_term(&parse_expr(src)).unwrap();
        let json = serde_json::to_string(&t).unwrap();
        assert!(
            json.contains(&format!("\"{}\"", op)),
            "{} → {}: {}",
            src,
            op,
            json
        );
    }
}

#[test]
fn predicate_with_field_access() {
    // `s.len > 10` lifts as `(> (field s ".len") 10)`.
    let f = lift_predicate(&parse_expr("s.len > 10")).unwrap();
    let json = serde_json::to_string(&f).unwrap();
    assert!(json.contains("\">\""));
    assert!(json.contains("\"field\""));
    assert!(json.contains("\".len\""));
}

#[test]
fn predicate_with_method_call() {
    // `v.is_empty() == false` ⇒ atomic with method:is_empty term.
    let f = lift_predicate(&parse_expr("v.is_empty() == false")).unwrap();
    let json = serde_json::to_string(&f).unwrap();
    assert!(json.contains("\"=\""));
    assert!(json.contains("\"method:is_empty\""));
}

#[test]
fn closure_lifts_as_lambda() {
    // |x| x + 1 lifts to IrTerm::Lambda { param=x#N, body=(x#N + 1) }.
    // Closure params are scope-resolved by the LiftCtx (#368 capture-
    // soundness): the binder name carries a unique scope id, and the
    // body's reference resolves to the same id.
    let t = lift_expr_to_term(&parse_expr("|x| x + 1")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(
        json.contains("\"lambda\""),
        "expected lambda variant: {}",
        json
    );
    assert!(
        json.contains("\"x#"),
        "expected scope-resolved x#N param: {}",
        json
    );
    assert!(json.contains("\"+\""));
}

#[test]
fn multi_arg_closure_nests() {
    // |x, y| x * y lifts to nested lambdas (right-associative): λx. λy. x * y.
    let t = lift_expr_to_term(&parse_expr("|x, y| x * y")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    // Two lambda nodes in the JSON.
    let lambda_count = json.matches("\"lambda\"").count();
    assert!(lambda_count >= 2, "expected ≥2 nested lambdas: {}", json);
}

#[test]
fn await_lifts_as_structural_seam() {
    // `future.await` is the explicit async seam. It must survive as a term so
    // the verifier can reuse the existing producer.post -> consumer.pre edge
    // across the suspension boundary.
    let awaited = lift_expr_to_term(&parse_expr("future.await")).unwrap();
    let json = serde_json::to_string(&awaited).unwrap();
    assert!(json.contains("\"await\""), "await seam missing: {json}");
    assert!(json.contains("\"future\""), "awaited base missing: {json}");
}

#[test]
fn async_block_lifts_trailing_value() {
    // async { 42 } produces a future that yields 42; lift as 42.
    let t = lift_expr_to_term(&parse_expr("async { 42 }")).unwrap();
    let direct = lift_expr_to_term(&parse_expr("42")).unwrap();
    assert_eq!(t, direct);
}

#[test]
fn array_literal_lifts_as_ctor() {
    let t = lift_expr_to_term(&parse_expr("[1, 2, 3]")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"array\""));
    assert!(json.contains("1"));
    assert!(json.contains("3"));
}

#[test]
fn array_repeat_lifts_as_ctor() {
    let t = lift_expr_to_term(&parse_expr("[0; 8]")).unwrap();
    let json = serde_json::to_string(&t).unwrap();
    assert!(json.contains("\"array_repeat\""));
    assert!(json.contains("8"));
}
