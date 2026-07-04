// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_walk::emit::rust_function_term_json_for_file;

fn term_json(src: &str, name: &str) -> serde_json::Value {
    let file: syn::File = syn::parse_str(src).unwrap();
    let bytes = rust_function_term_json_for_file(&file, name, "d4.rs").unwrap();
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

#[test]
fn d4_lowers_int_field_expression() {
    let parsed = term_json(
        r#"
            struct Point { x: i32 }
            fn get_x(p: Point) -> i32 {
                p.x + 1
            }
        "#,
        "get_x",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("return(add(field(p, x), 1))")
    );
    assert_loss(&parsed, "type-inference-assumed-int");
}

#[test]
fn d4_lowers_int_path_expression() {
    let parsed = term_json(
        r#"
            const ONE: i32 = 1;
            fn add_one(x: i32) -> i32 {
                x + ONE
            }
        "#,
        "add_one",
    );
    assert_eq!(parsed["term_surface"].as_str(), Some("return(add(x, ONE))"));
    assert_loss(&parsed, "type-inference-assumed-int");
}

#[test]
fn d4_lowers_int_unary_expression() {
    let parsed = term_json(
        r#"
            fn negated(x: i32) -> i32 {
                -x
            }
        "#,
        "negated",
    );
    assert_eq!(parsed["term_surface"].as_str(), Some("return(neg(x))"));
}

#[test]
fn d4_lowers_boolean_field_expression() {
    let parsed = term_json(
        r#"
            struct Flags { ok: bool }
            fn is_ok(flags: Flags) -> bool {
                flags.ok
            }
        "#,
        "is_ok",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("return(field(flags, ok))")
    );
    assert_loss(&parsed, "type-inference-assumed-bool");
}

#[test]
fn d4_accepts_boolean_let_expression_as_named_loss() {
    let parsed = term_json(
        r#"
            fn has_value(value: Option<i32>) -> bool {
                if let Some(x) = value {
                    true
                } else {
                    false
                }
            }
        "#,
        "has_value",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(if(if_let(pattern_some(pattern_bind(x)), value), return(true), skip), return(false))")
    );
    assert_loss(&parsed, "Expr::Let");
}

#[test]
fn d4_accepts_boolean_macro_expression_as_named_loss() {
    let parsed = term_json(
        r#"
            fn is_one(x: i32) -> bool {
                matches!(x, 1)
            }
        "#,
        "is_one",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("return(macro_call:matches(x , 1))")
    );
    assert_loss(&parsed, "macro-not-expanded");
}

#[test]
fn d4_lowers_boolean_match_expression() {
    let parsed = term_json(
        r#"
            fn is_zero(x: i32) -> bool {
                match x {
                    0 => true,
                    _ => false,
                }
            }
        "#,
        "is_zero",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some(
            "return(match_expr(x, arms([arm(pattern_bind(0), true), arm(pattern_wild(), false)])))"
        )
    );
}

#[test]
fn d4_lowers_assignment_statement() {
    let parsed = term_json(
        r#"
            fn assign_value(mut x: i32) {
                x = 1;
            }
        "#,
        "assign_value",
    );
    assert_eq!(parsed["term_surface"].as_str(), Some("assign(x, 1)"));
}

#[test]
fn d4_lowers_for_loop_statement() {
    let parsed = term_json(
        r#"
            fn visit(xs: Vec<i32>) {
                for x in xs {};
            }
        "#,
        "visit",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("for(pattern_bind(x), into_iter(xs), skip)")
    );
}

#[test]
fn d4_lowers_match_statement() {
    let parsed = term_json(
        r#"
            fn visit_match(x: i32) {
                match x {
                    0 => (),
                    _ => (),
                };
            }
        "#,
        "visit_match",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("match(x, arms([arm(pattern_bind(0), skip), arm(pattern_wild(), skip)]))")
    );
}

#[test]
fn d4_lowers_try_statement() {
    let parsed = term_json(
        r#"
            fn maybe() -> Result<(), i32> { Ok(()) }
            fn use_try() -> Result<(), i32> {
                maybe()?;
                Ok(())
            }
        "#,
        "use_try",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(try(call:maybe(maybe, [])), return(call:Ok(Ok, [unit])))")
    );
}

#[test]
fn d4_lowers_unit_for_loop_tail_expression() {
    let parsed = term_json(
        r#"
            fn visit_tail(xs: Vec<i32>) {
                for x in xs {}
            }
        "#,
        "visit_tail",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(for(pattern_bind(x), into_iter(xs), skip), return(unit))")
    );
}

#[test]
fn d4_lowers_unit_if_tail_expression() {
    let parsed = term_json(
        r#"
            fn unit_if(x: bool) {
                if x {}
            }
        "#,
        "unit_if",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(if(x, skip, skip), return(unit))")
    );
}

#[test]
fn d4_lowers_unit_match_tail_expression() {
    let parsed = term_json(
        r#"
            fn unit_match(x: i32) {
                match x {
                    0 => (),
                    _ => (),
                }
            }
        "#,
        "unit_match",
    );
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(match(x, arms([arm(pattern_bind(0), skip), arm(pattern_wild(), skip)])), return(unit))")
    );
}
