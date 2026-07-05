// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_walk::emit::rust_function_term_json_for_file;

fn term_json(src: &str, name: &str) -> serde_json::Value {
    let file: syn::File = syn::parse_str(src).unwrap();
    let bytes = rust_function_term_json_for_file(&file, name, "proc_macro.rs").unwrap();
    serde_json::from_slice(&bytes).expect("term JSON")
}

fn invocations(parsed: &serde_json::Value) -> Vec<&serde_json::Value> {
    parsed["proc_macro_invocations"]
        .as_array()
        .expect("proc_macro_invocations array")
        .iter()
        .collect()
}

fn assert_no_procedural_macro_loss(parsed: &serde_json::Value) {
    assert!(!parsed["loss_record"]
        .as_array()
        .expect("loss_record array")
        .iter()
        .any(|loss| loss["loss"] == "procedural-macro"));
}

fn only_invocation(parsed: &serde_json::Value) -> &serde_json::Value {
    let invocations = invocations(parsed);
    assert_eq!(invocations.len(), 1, "expected one invocation");
    invocations[0]
}

fn arg_names(invocation: &serde_json::Value) -> Vec<String> {
    invocation["args"]
        .as_array()
        .expect("args array")
        .iter()
        .filter_map(|arg| arg["name"].as_str())
        .map(str::to_string)
        .collect()
}

fn assert_op_cid(invocation: &serde_json::Value) {
    assert!(invocation["op_cid"]
        .as_str()
        .expect("op_cid")
        .starts_with("blake3-512:"));
}

#[test]
fn derive_struct_lifts_to_typed_subcase() {
    let parsed = term_json(
        r#"
            #[derive(Clone, Debug)]
            struct Snapshot {
                value: i32,
            }

            fn read(x: i32) -> i32 {
                x
            }
        "#,
        "read",
    );

    assert_no_procedural_macro_loss(&parsed);
    let invocation = only_invocation(&parsed);
    assert_eq!(invocation["kind"], "concept:op-application");
    assert_op_cid(invocation);
    assert_eq!(invocation["macro_path"], "derive");
    assert_eq!(invocation["token_stream"], "#[derive(Clone, Debug)]");
    assert_eq!(arg_names(invocation), vec!["Clone", "Debug"]);
    assert!(invocation["macro_cid"]
        .as_str()
        .expect("macro_cid")
        .starts_with("blake3-512:"));
}

#[test]
fn derive_enum_lifts_without_general_attribute_variant() {
    let parsed = term_json(
        r#"
            #[derive(PartialEq, Eq)]
            enum State {
                Open,
                Closed,
            }

            fn flag(x: i32) -> i32 {
                x
            }
        "#,
        "flag",
    );

    assert_no_procedural_macro_loss(&parsed);
    let invocation = only_invocation(&parsed);
    assert_op_cid(invocation);
    assert_eq!(arg_names(invocation), vec!["PartialEq", "Eq"]);
}

#[test]
fn derive_preserves_qualified_trait_path() {
    let parsed = term_json(
        r#"
            #[derive(serde::Serialize)]
            struct Wire {
                value: i32,
            }

            fn value(x: i32) -> i32 {
                x
            }
        "#,
        "value",
    );

    assert_no_procedural_macro_loss(&parsed);
    let invocation = only_invocation(&parsed);
    assert_op_cid(invocation);
    assert_eq!(arg_names(invocation), vec!["serde::Serialize"]);
}

#[test]
fn function_attribute_macro_lifts_to_proc_macro_invocation() {
    let parsed = term_json(
        r#"
            #[instrument]
            fn traced(x: i32) -> i32 {
                x
            }
        "#,
        "traced",
    );

    assert_no_procedural_macro_loss(&parsed);
    let invocation = only_invocation(&parsed);
    assert_eq!(invocation["kind"], "concept:op-application");
    assert_op_cid(invocation);
    assert_eq!(invocation["macro_path"], "instrument");
    assert_eq!(invocation["token_stream"], "#[instrument]");
}

#[test]
fn attribute_macro_args_preserve_term_list() {
    let parsed = term_json(
        r#"
            #[route(GET, "/v1")]
            fn endpoint(x: i32) -> i32 {
                x
            }
        "#,
        "endpoint",
    );

    assert_no_procedural_macro_loss(&parsed);
    let invocation = only_invocation(&parsed);
    assert_op_cid(invocation);
    assert_eq!(invocation["macro_path"], "route");
    assert_eq!(invocation["token_stream"], "#[route(GET, \"/v1\")]");
    let args = invocation["args"].as_array().expect("args array");
    assert_eq!(args[0]["kind"], "symbol");
    assert_eq!(args[0]["name"], "GET");
    assert_eq!(args[1]["kind"], "const");
    assert_eq!(args[1]["value"], "/v1");
}

#[test]
fn method_attribute_macro_lifts_from_impl_context() {
    let parsed = term_json(
        r#"
            struct Worker;

            impl Worker {
                #[tracing::instrument(skip(self))]
                pub fn run(&self) -> i32 {
                    1
                }
            }
        "#,
        "run",
    );

    assert_no_procedural_macro_loss(&parsed);
    let invocation = only_invocation(&parsed);
    assert_op_cid(invocation);
    assert_eq!(invocation["macro_path"], "tracing::instrument");
    assert_eq!(
        invocation["token_stream"],
        "#[tracing::instrument(skip(self))]"
    );
}
