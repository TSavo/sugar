// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_walk::emit::rust_function_term_json_for_file;

fn term_json(src: &str, name: &str) -> serde_json::Value {
    let file: syn::File = syn::parse_str(src).unwrap();
    let bytes = rust_function_term_json_for_file(&file, name, "d7_stmt_expr_other.rs").unwrap();
    serde_json::from_slice(&bytes).expect("term JSON")
}

#[test]
fn d7_lowers_index_expression_statement() {
    let parsed = term_json(
        r#"
            fn touch_index(xs: [i32; 2], mut out: i32) {
                xs[0];
                out = 1;
            }
        "#,
        "touch_index",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(drop(index(xs, 0)), assign(out, 1))")
    );
}

#[test]
fn d7_lowers_field_expression_statement() {
    let parsed = term_json(
        r#"
            struct Point { x: i32 }
            fn touch_field(p: Point, mut out: i32) {
                p.x;
                out = 1;
            }
        "#,
        "touch_field",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(drop(field(p, x)), assign(out, 1))")
    );
}

#[test]
fn d7_lowers_tuple_expression_statement() {
    let parsed = term_json(
        r#"
            fn touch_tuple(x: i32, mut out: i32) {
                (x, 2);
                out = 1;
            }
        "#,
        "touch_tuple",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(drop(tuple([x, 2])), assign(out, 1))")
    );
}

#[test]
fn d7_lowers_array_expression_statement() {
    let parsed = term_json(
        r#"
            fn touch_array(x: i32, mut out: i32) {
                [x, 2];
                out = 1;
            }
        "#,
        "touch_array",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(drop(array([x, 2])), assign(out, 1))")
    );
}

#[test]
fn d7_lowers_reference_expression_statement() {
    let parsed = term_json(
        r#"
            fn touch_reference(x: i32, mut out: i32) {
                &x;
                out = 1;
            }
        "#,
        "touch_reference",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(drop(borrow(x)), assign(out, 1))")
    );
}

#[test]
fn d7_lowers_path_expression_statement_as_noop() {
    let parsed = term_json(
        r#"
            fn touch_path(x: i32, mut out: i32) {
                x;
                out = 1;
            }
        "#,
        "touch_path",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(skip, assign(out, 1))")
    );
}

#[test]
fn d7_lowers_literal_expression_statement_as_noop() {
    let parsed = term_json(
        r#"
            fn touch_literal(mut out: i32) {
                1;
                out = 1;
            }
        "#,
        "touch_literal",
    );

    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("seq(skip, assign(out, 1))")
    );
}
