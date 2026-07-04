// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_walk::emit::rust_function_term_json_for_file;
use sugar_walk::type_decl::lift_file_type_decls;

fn parse_file(src: &str) -> syn::File {
    syn::parse_str(src).unwrap()
}

fn term_json(src: &str, name: &str) -> serde_json::Value {
    let file = parse_file(src);
    let bytes = rust_function_term_json_for_file(&file, name, "d5.rs").unwrap();
    serde_json::from_slice(&bytes).expect("term JSON")
}

#[test]
fn struct_type_param_is_carried_in_type_decl_memento() {
    let file = parse_file("struct Foo<T> { x: T }");
    let set = lift_file_type_decls(&file, Some("d5.rs"));
    let foo = &set.structs[0];

    assert_eq!(foo.generic_parameters.len(), 1);
    assert_eq!(foo.generic_parameters[0].name, "T");
    assert_eq!(foo.generic_parameters[0].kind, "type");
    assert_eq!(foo.handling, "handles-fully");

    let json: serde_json::Value = serde_json::from_slice(&foo.canonical_bytes).unwrap();
    assert_eq!(json["genericParameters"][0]["name"], "T");
    assert_eq!(json["genericParameters"][0]["kind"], "type");
}

#[test]
fn struct_where_clause_is_carried_as_where_bound_citation() {
    let file = parse_file("struct Foo<T> where T: Clone { x: T }");
    let set = lift_file_type_decls(&file, Some("d5.rs"));
    let foo = &set.structs[0];

    assert_eq!(foo.where_bounds.len(), 1);
    assert_eq!(foo.where_bounds[0].concept, "concept:where-bound");
    assert_eq!(foo.where_bounds[0].predicate, "T : Clone");
    assert_eq!(foo.handling, "handles-fully");

    let json: serde_json::Value = serde_json::from_slice(&foo.canonical_bytes).unwrap();
    assert_eq!(json["whereBounds"][0]["concept"], "concept:where-bound");
    assert_eq!(json["whereBounds"][0]["predicate"], "T : Clone");
}

#[test]
fn struct_lifetime_param_is_carried_in_type_decl_memento() {
    let file = parse_file("struct Borrowed<'a> { x: &'a str }");
    let set = lift_file_type_decls(&file, Some("d5.rs"));
    let borrowed = &set.structs[0];

    assert_eq!(borrowed.generic_parameters.len(), 1);
    assert_eq!(borrowed.generic_parameters[0].name, "'a");
    assert_eq!(borrowed.generic_parameters[0].kind, "lifetime");
    assert_eq!(borrowed.handling, "handles-fully");
}

#[test]
fn unsupported_where_bound_shape_becomes_named_loss() {
    let file = parse_file("struct Foo<T> where T: Iterator<Item = u8> { x: T }");
    let set = lift_file_type_decls(&file, Some("d5.rs"));
    let foo = &set.structs[0];

    assert_eq!(foo.handling, "handles-partially-with-loss-record");
    assert!(foo
        .loss_record
        .iter()
        .any(|loss| loss.loss == "generics-bounds-not-discharged"));
}

#[test]
fn proof_run_nested_use_item_is_non_executable() {
    let parsed = term_json(
        r#"
            fn proof_run_json_to_canonical_like(x: i32) -> i32 {
                use sugar_canonicalizer::Value as CanonicalValue;
                x
            }
        "#,
        "proof_run_json_to_canonical_like",
    );

    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_eq!(parsed["term_surface"].as_str(), Some("return(x)"));
}

#[test]
fn serde_nested_use_item_is_non_executable() {
    let parsed = term_json(
        r#"
            fn serde_json_to_canonical_value_like(flag: bool) -> bool {
                use sugar_canonicalizer::Value as CanonicalValue;
                flag
            }
        "#,
        "serde_json_to_canonical_value_like",
    );

    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_eq!(parsed["term_surface"].as_str(), Some("return(flag)"));
}

#[test]
fn migration_nested_use_item_is_non_executable() {
    let parsed = term_json(
        r#"
            fn migration_json_to_canonical_like() {
                use sugar_canonicalizer::Value as CanonicalValue;
            }
        "#,
        "migration_json_to_canonical_like",
    );

    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_eq!(parsed["term_surface"].as_str(), Some("skip"));
}
