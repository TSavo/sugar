// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Relocated from `libsugar/tests/core_interface.rs` by
// #evict-2-liftplugin-pathexec: these tests exercise `LiftPluginKit`,
// `LiftKit`, `execute_path`, and `KitRegistry`, which moved from
// `libsugar::core` to `sugar_cli::kit_path`.

use libsugar::core::{
    address, ConformanceDeclaration, Dialect, DomainKind, HashMapInputCatalog, Input, Kit, Path,
    PathAlgebra, Term, Verb,
};
use sugar_compiler::kit_path::{execute_path, KitRegistry, LiftKit, LiftPluginKit};
use sugar_ir_types::Sort;

#[test]
fn lift_plugin_transport_is_a_core_kit_with_legacy_response_escape_hatch() {
    let temp = std::env::temp_dir().join(format!("sugar-lift-plugin-kit-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&temp);
    std::fs::create_dir_all(&temp).expect("create temp dir");
    let script = temp.join("fake-lifter.sh");
    std::fs::write(
        &script,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*) echo '{"jsonrpc":"2.0","id":1,"result":{"name":"fake-lifter"}}' ;;
    *'"method":"lift"'*) echo '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[],"diagnostics":[]}}' ;;
    *'"method":"shutdown"'*) exit 0 ;;
  esac
done
"#,
    )
    .expect("write fake lifter");

    let kit = LiftPluginKit::new(
        "test-surface",
        vec!["sh".to_string(), script.display().to_string()],
        Some(temp.clone()),
    );
    let input = Input::Spec(serde_json::json!({
        "surface": "test-surface",
        "workspace_root": temp,
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {"layer": "all", "identifyOnly": false}
    }));

    let session = kit
        .parse_session(&input)
        .expect("session exposes transport metadata");
    assert_eq!(
        session.response().get("kind").and_then(|v| v.as_str()),
        Some("ir-document")
    );
    assert_eq!(
        session.claim.domain,
        DomainKind::Other("lift-plugin".to_string())
    );
    assert_eq!(session.claim.from, vec![address(&input)]);
    let response_term = Term::Const {
        value: session.response().clone(),
        sort: Sort::Primitive {
            name: "LiftPluginResponse".to_string(),
        },
    };
    assert_eq!(session.claim.to, address(&response_term));
    assert_eq!(session.claim.artifacts, vec![address(&response_term)]);
    assert_eq!(
        session.claim.contract.body_cid.as_deref(),
        Some(session.claim.to.as_str())
    );
    assert_eq!(
        session.response().get("kind").and_then(|v| v.as_str()),
        Some("ir-document")
    );
    let _ = std::fs::remove_dir_all(&temp);
}

#[test]
fn lift_kit_transforms_source_through_lift_plugin_transport_and_carries_term_payload() {
    let temp = std::env::temp_dir().join(format!("sugar-lift-kit-source-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&temp);
    std::fs::create_dir_all(&temp).expect("create temp dir");
    let script = temp.join("fake-lifter.sh");
    std::fs::write(
        &script,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*) echo '{"jsonrpc":"2.0","id":1,"result":{"name":"fake-rust-lifter"}}' ;;
    *'"method":"lift"'*) echo '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"bind-lift-entry","file":"src/lib.rs","fn_name":"id","fn_line":1,"param_names":["x"],"param_types":["i64"],"return_type":"i64","term_shape":{"kind":"var","name":"x"},"term_shape_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","witnesses":[]}],"diagnostics":[]}}' ;;
    *'"method":"shutdown"'*) exit 0 ;;
  esac
done
"#,
    )
    .expect("write fake lifter");

    let request = serde_json::json!({
        "surface": "rust",
        "workspace_root": temp,
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {"layer": "all", "identifyOnly": false}
    });
    let source = Input::Source {
        dialect: libsugar::core::Dialect::Rust,
        bytes: serde_json::to_vec(&request).expect("source request JSON"),
    };
    let kit = LiftKit::new(
        libsugar::core::Dialect::Rust,
        "rust",
        vec!["sh".to_string(), script.display().to_string()],
        Some(temp.clone()),
    );

    let claim = kit
        .transform(&source)
        .expect("source input lifts through the transport");
    let expected_term = Term::Const {
        value: serde_json::json!({
            "kind": "ir-document",
            "ir": [{
                "kind": "bind-lift-entry",
                "file": "src/lib.rs",
                "fn_name": "id",
                "fn_line": 1,
                "param_names": ["x"],
                "param_types": ["i64"],
                "return_type": "i64",
                "term_shape": {"kind": "var", "name": "x"},
                "term_shape_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "witnesses": []
            }],
            "diagnostics": []
        }),
        sort: Sort::Primitive {
            name: "LiftPluginResponse".to_string(),
        },
    };

    assert_eq!(claim.to, address(&expected_term));
    assert_eq!(claim.artifacts, vec![address(&expected_term)]);
    assert_eq!(claim.payload.as_ref(), Some(&expected_term));
    assert_eq!(claim.from, vec![address(&source)]);
    let _ = std::fs::remove_dir_all(&temp);
}

#[test]
fn execute_path_refuses_unregistered_lift_kit_with_composition_refusal_memento() {
    let source = Input::Source {
        dialect: libsugar::core::Dialect::Other("unknown".to_string()),
        bytes: b"fn id(x: i64) -> i64 { x }".to_vec(),
    };
    let mut inputs = HashMapInputCatalog::default();
    let source_cid = inputs.insert(source);
    let path = Input::Path(Box::new(Path {
        algebra: vec![PathAlgebra {
            name: "lift".to_string(),
            kit: "lift-unknown".to_string(),
            inputs: vec![source_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }));
    let registry = KitRegistry::default();

    let err = execute_path(&path, &registry, &inputs).expect_err("unknown lift kit refuses");
    let refusal = err
        .composition_refusal()
        .expect("path executor error carries composition refusal");
    assert_eq!(refusal.header.failure_kind, "memento-required-missing");
    assert!(refusal
        .header
        .missing_memento_requirements
        .as_ref()
        .expect("missing requirements")
        .iter()
        .any(|requirement| requirement.role.as_deref() == Some("kit-registry")));
}

#[test]
fn kit_registry_register_requires_and_exposes_conformance_declaration() {
    fn register_with_declaration(
        registry: &mut KitRegistry,
        name: &str,
        kit: impl Kit + 'static,
        conformance: ConformanceDeclaration,
    ) {
        registry.register(name, kit, conformance);
    }

    let conformance = ConformanceDeclaration::NonCarrier {
        reason: "lifts source bytes to DomainClaim; no target source produced",
    };
    let mut registry = KitRegistry::default();

    register_with_declaration(
        &mut registry,
        "lift-rust",
        LiftKit::new(Dialect::Rust, "rust", vec!["true".to_string()], None),
        conformance.clone(),
    );

    assert_eq!(registry.conformance("lift-rust"), Some(&conformance));
    assert_eq!(registry.conformance("unknown"), None);
}
