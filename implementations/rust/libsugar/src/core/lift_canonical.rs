// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Lift-term content-addressing canonical form (#3855 sugar-walk purification).
//
// Realize-sidecar fields (attr_pre/post, concept_annotation, operand_bindings,
// source_function_name, realize_*, bind-lift-entry visibility/generics/docs)
// are irrelevant to the proof-chain CID: adding a comment that shifts `fn_line`
// must not invalidate `lift.to` / `bind.from`. That strip is membrane law —
// federation identity of the hashed lift term — not rust-kit knowledge.
//
// Home is libsugar so:
// - sugar-compiler's neutral kit_path engine can strip without importing
//   sugar-walk (BOUNDARY IMPURITY retired for this path);
// - sugar-walk BindKit uses the same function without duplication;
// - SourceMemento / SrcSpan also live in libsugar so sugar-compiler can drop
//   its sugar-walk Cargo edge (arch-guard ban; #3855).

use serde_json::Value as Json;

use super::types::Term;

/// Strip realize-sidecar metadata from a lift-output `Term::Const`.
///
/// Used to compute the canonical content CID that `lift.to` and `bind.from`
/// both target. Non-`Const` terms pass through unchanged. Payload consumers
/// that need realize-time metadata must keep the pre-strip term separately.
pub fn strip_realize_sidecar_from_lift_term(term: Term) -> Term {
    let Term::Const { mut value, sort } = term else {
        return term;
    };
    if let Some(entries) = value.get_mut("ir").and_then(Json::as_array_mut) {
        for entry in entries {
            if let Some(object) = entry.as_object_mut() {
                object.remove("attr_pre");
                object.remove("attrPre");
                object.remove("attr_post");
                object.remove("attrPost");
                object.remove("concept_annotation");
                object.remove("conceptAnnotation");
                object.remove("operand_bindings");
                object.remove("operandBindings");
                object.remove("proc_macro_invocations");
                object.remove("procMacroInvocations");
                object.remove("source_function_name");
                object.remove("sourceFunctionName");
                object.remove("realize_param_types");
                object.remove("realizeParamTypes");
                object.remove("realize_return_type");
                object.remove("realizeReturnType");
                object.remove("realize_original_param_types");
                object.remove("realizeOriginalParamTypes");
                // #1075/A9 federation: the bind-lift-entry is the cross-language
                // boundary surface and must hash to the SAME bytes whether
                // lifted from typed Rust or untyped Python. The Python lifter
                // emits only {kind, param_names, term_shape, term_shape_cid,
                // operand_bindings, realize_*, source_function_name, witnesses};
                // Rust additionally carries visibility/generic_params/doc_lines
                // for the Java boundary realize path. Those are realize-only
                // metadata (read off the UN-stripped lift IR by cmd_lower, never
                // off this hashed term) so they ride CID-invisible here too,
                // scoped to bind-lift-entry to leave sugar-entry CIDs untouched.
                if object.get("kind").and_then(Json::as_str) == Some("bind-lift-entry") {
                    object.remove("visibility");
                    object.remove("generic_params");
                    object.remove("genericParams");
                    object.remove("doc_lines");
                    object.remove("docLines");
                }
            }
        }
    }
    Term::Const { value, sort }
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use sugar_ir_types::Sort;

    use super::*;

    fn const_term(value: serde_json::Value) -> Term {
        Term::Const {
            value,
            sort: Sort::Primitive {
                name: "Term".to_string(),
            },
        }
    }

    #[test]
    fn strips_realize_sidecar_fields_from_ir_entries() {
        let term = const_term(json!({
            "ir": [{
                "kind": "sugar-entry",
                "attr_pre": 1,
                "attrPre": 1,
                "attr_post": 2,
                "concept_annotation": "x",
                "operand_bindings": [],
                "proc_macro_invocations": [],
                "source_function_name": "f",
                "realize_param_types": [],
                "realize_return_type": "i32",
                "realize_original_param_types": [],
                "keep_me": true,
            }]
        }));
        let stripped = strip_realize_sidecar_from_lift_term(term);
        let Term::Const { value, .. } = stripped else {
            panic!("expected Const");
        };
        let entry = &value["ir"][0];
        for key in [
            "attr_pre",
            "attrPre",
            "attr_post",
            "concept_annotation",
            "operand_bindings",
            "proc_macro_invocations",
            "source_function_name",
            "realize_param_types",
            "realize_return_type",
            "realize_original_param_types",
        ] {
            assert!(
                entry.get(key).is_none(),
                "sidecar field `{key}` must be stripped"
            );
        }
        assert_eq!(entry["keep_me"], true);
        assert_eq!(entry["kind"], "sugar-entry");
    }

    #[test]
    fn strips_bind_lift_entry_rust_only_metadata() {
        let term = const_term(json!({
            "ir": [{
                "kind": "bind-lift-entry",
                "visibility": "pub",
                "generic_params": ["T"],
                "doc_lines": ["hi"],
                "param_names": ["x"],
                "term_shape": "body",
            }]
        }));
        let stripped = strip_realize_sidecar_from_lift_term(term);
        let Term::Const { value, .. } = stripped else {
            panic!("expected Const");
        };
        let entry = &value["ir"][0];
        assert!(entry.get("visibility").is_none());
        assert!(entry.get("generic_params").is_none());
        assert!(entry.get("doc_lines").is_none());
        assert_eq!(entry["param_names"], json!(["x"]));
        assert_eq!(entry["term_shape"], "body");
    }

    #[test]
    fn non_const_terms_pass_through() {
        let term = Term::Var {
            name: "x".to_string(),
        };
        assert_eq!(strip_realize_sidecar_from_lift_term(term.clone()), term);
    }
}
