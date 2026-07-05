// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_walk::emit::rust_function_term_json_for_file;

fn term_json(src: &str, name: &str) -> serde_json::Value {
    let file: syn::File = syn::parse_str(src).unwrap();
    let bytes = rust_function_term_json_for_file(&file, name, "d3.rs").unwrap();
    serde_json::from_slice(&bytes).expect("term JSON")
}

fn assert_partial_loss(parsed: &serde_json::Value, dimension: &str) {
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

fn assert_no_loss(parsed: &serde_json::Value, dimension: &str) {
    assert!(!parsed["loss_record"]
        .as_array()
        .unwrap()
        .iter()
        .any(|loss| loss["loss"] == dimension));
}

fn fully_qualified_paths(term: &serde_json::Value) -> Vec<String> {
    let mut paths = Vec::new();
    collect_fully_qualified_paths(term, &mut paths);
    paths
}

fn collect_fully_qualified_paths(term: &serde_json::Value, paths: &mut Vec<String>) {
    if term["kind"] == "fully-qualified-path" {
        paths.push(term["path"].as_str().unwrap().to_string());
    }

    if let Some(args) = term["args"].as_array() {
        for arg in args {
            collect_fully_qualified_paths(arg, paths);
        }
    }
    if let Some(items) = term["items"].as_array() {
        for item in items {
            collect_fully_qualified_paths(item, paths);
        }
    }
    if let Some(fields) = term["fields"].as_array() {
        for field in fields {
            collect_fully_qualified_paths(&field["value"], paths);
        }
    }
}

#[test]
fn carries_procedural_macro_invocation_as_op_application() {
    let parsed = term_json(
        r#"
            #[instrument]
            fn traced(x: i32) -> i32 {
                x
            }
        "#,
        "traced",
    );
    assert!(!parsed["loss_record"]
        .as_array()
        .unwrap()
        .iter()
        .any(|loss| loss["loss"] == "procedural-macro"));
    assert!(parsed["proc_macro_invocations"]
        .as_array()
        .unwrap()
        .iter()
        .any(|invocation| invocation["op_cid"]
            .as_str()
            .is_some_and(|cid| cid.starts_with("blake3-512:"))
            && invocation["macro_path"] == "instrument"));
}

#[test]
fn retains_module_qualified_path_without_truncation_loss() {
    let parsed = term_json(
        r#"
            mod math {
                pub const VALUE: i32 = 1;
            }

            fn caller() -> i32 {
                let y: i32 = math::VALUE;
                y
            }
        "#,
        "caller",
    );
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_no_loss(&parsed, "trait-path-truncated");
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("let(pattern_bind(y), math::VALUE, return(y))")
    );
    assert_eq!(fully_qualified_paths(&parsed["term"]), vec!["math::VALUE"]);
    assert_eq!(
        parsed["term"]["args"][1]["concept"].as_str(),
        Some("concept:fully-qualified-path")
    );
}

#[test]
fn distinguishes_same_leaf_names_in_different_modules() {
    let parsed = term_json(
        r#"
            mod left {
                pub const VALUE: i32 = 1;
            }
            mod right {
                pub const VALUE: i32 = 2;
            }

            fn caller() -> i32 {
                let a: i32 = left::VALUE;
                let b: i32 = right::VALUE;
                a + b
            }
        "#,
        "caller",
    );
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_no_loss(&parsed, "trait-path-truncated");
    assert_eq!(
        fully_qualified_paths(&parsed["term"]),
        vec!["left::VALUE", "right::VALUE"]
    );
}

#[test]
fn retains_leading_crate_root_for_absolute_paths() {
    let parsed = term_json(
        r#"
            mod root {
                pub const VALUE: i32 = 1;
            }

            fn caller() -> i32 {
                let y: i32 = ::root::VALUE;
                y
            }
        "#,
        "caller",
    );
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_no_loss(&parsed, "trait-path-truncated");
    assert_eq!(
        fully_qualified_paths(&parsed["term"]),
        vec!["::root::VALUE"]
    );
}

#[test]
fn retains_associated_trait_const_path_without_truncation_loss() {
    let parsed = term_json(
        r#"
            trait Named {
                const VALUE: i32;
            }
            struct Thing;
            impl Named for Thing {
                const VALUE: i32 = 7;
            }

            fn caller() -> i32 {
                let y: i32 = <Thing as Named>::VALUE;
                y
            }
        "#,
        "caller",
    );
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_no_loss(&parsed, "trait-path-truncated");
    assert_eq!(
        fully_qualified_paths(&parsed["term"]),
        vec!["<Thing as Named>::VALUE"]
    );
}

#[test]
fn distinguishes_associated_consts_with_same_leaf_name() {
    let parsed = term_json(
        r#"
            trait Named {
                const VALUE: i32;
            }
            struct Left;
            struct Right;
            impl Named for Left {
                const VALUE: i32 = 1;
            }
            impl Named for Right {
                const VALUE: i32 = 2;
            }

            fn caller() -> i32 {
                let a: i32 = <Left as Named>::VALUE;
                let b: i32 = <Right as Named>::VALUE;
                a + b
            }
        "#,
        "caller",
    );
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_no_loss(&parsed, "trait-path-truncated");
    assert_eq!(
        fully_qualified_paths(&parsed["term"]),
        vec!["<Left as Named>::VALUE", "<Right as Named>::VALUE"]
    );
}

#[test]
fn retains_qualified_trait_path_inside_associated_path() {
    let parsed = term_json(
        r#"
            mod carriers {
                pub struct Thing;
            }
            mod traits {
                pub trait Named {
                    const VALUE: i32;
                }
            }
            impl traits::Named for carriers::Thing {
                const VALUE: i32 = 7;
            }

            fn caller() -> i32 {
                let y: i32 = <carriers::Thing as traits::Named>::VALUE;
                y
            }
        "#,
        "caller",
    );
    assert_eq!(parsed["handling"].as_str(), Some("handles-fully"));
    assert_no_loss(&parsed, "trait-path-truncated");
    assert_eq!(
        fully_qualified_paths(&parsed["term"]),
        vec!["<carriers::Thing as traits::Named>::VALUE"]
    );
}

#[test]
fn accepts_impl_associated_type_as_named_loss() {
    let parsed = term_json(
        r#"
            trait Shape {
                type Output;
                fn value(&self) -> i32;
            }

            struct UnitShape;

            impl Shape for UnitShape {
                type Output = i32;

                fn value(&self) -> i32 {
                    1
                }
            }
        "#,
        "value",
    );
    assert_partial_loss(&parsed, "impl-associated-type-not-lowered");
}

#[test]
fn accepts_abi_attribute_as_named_loss() {
    let parsed = term_json(
        r#"
            extern "C" fn exposed(x: i32) -> i32 {
                x
            }
        "#,
        "exposed",
    );
    assert_partial_loss(&parsed, "abi-attribute-not-carried");
}

#[test]
fn accepts_statement_macro_as_named_loss() {
    let parsed = term_json(
        r#"
            fn checked(x: i32) -> i32 {
                debug_assert!(x >= 0);
                x
            }
        "#,
        "checked",
    );
    assert_partial_loss(&parsed, "macro-not-expanded");
}
