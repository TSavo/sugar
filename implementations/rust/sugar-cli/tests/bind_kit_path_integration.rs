// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use libsugar::core::{
    address, execute_path, named_term_document_cid, named_term_document_from_bind_payload,
    strip_realize_sidecar_from_lift_term, BindKit, ConformanceDeclaration, Dialect,
    HashMapInputCatalog, Input, Kit, KitRegistry, LiftKit, Path as CorePath, PathAlgebra, Term,
    Verb,
};

const BIND_NONCARRIER: ConformanceDeclaration = ConformanceDeclaration::NonCarrier {
    reason: "transforms Input::Term to NamedTerm DomainClaim; emits no target source",
};
const LIFT_NONCARRIER: ConformanceDeclaration = ConformanceDeclaration::NonCarrier {
    reason: "lifts source bytes to DomainClaim; no target source produced",
};
use serde_json::{json, Value};
use sugar_ir_types::Sort;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn primitive_sort(name: &str) -> Sort {
    Sort::Primitive {
        name: name.to_string(),
    }
}

fn write_executable(path: &Path, contents: &str) {
    fs::write(path, contents).expect("write script");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path).expect("metadata").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod script");
    }
}

fn fake_lifter(root: &Path) -> PathBuf {
    let script = root.join("fake-rust-lifter.sh");
    write_executable(
        &script,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"fake-rust-lifter","protocol_version":"pep/1.7.0","capabilities":{"surfaces":["rust"]}}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","sourceLanguage":"rust","ir":[{"kind":"bind-lift-entry","file":"src/lib.rs","fn_name":"id","fn_line":1,"concept_annotation":"identity","param_names":["x"],"param_types":["i64"],"return_type":"i64","term_shape":{"kind":"var","name":"x"},"term_shape_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","witnesses":[]}]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    script
}

fn bind_input_value() -> Value {
    json!({
        "kind": "ir-document",
        "sourceLanguage": "rust",
        "workspaceRoot": "/tmp/sugar-bind-path-test",
        "ir": [{
            "kind": "bind-lift-entry",
            "file": "src/lib.rs",
            "fn_name": "deposit",
            "fn_line": 14,
            "concept_annotation": "deposit-then-balance",
            "param_names": ["balance", "amount"],
            "param_types": ["i64", "i64"],
            "return_type": "i64",
            "term_shape": {
                "kind": "body",
                "stmts": [
                    {"kind": "let"},
                    {"kind": "bin", "op": "+"}
                ]
            },
            "term_shape_cid": "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111",
            "witnesses": [{
                "role": "post",
                "predicate_text": "out == balance + amount",
                "source_kind": "annotation"
            }]
        }]
    })
}

fn run_bind_cli(term_value: &Value) -> Vec<u8> {
    let mut child = Command::new(sugar_bin())
        .arg("bind")
        .arg("-")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn bind");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(term_value.to_string().as_bytes())
        .expect("write term");
    let output = child.wait_with_output().expect("wait bind");
    assert!(
        output.status.success(),
        "bind cli failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    output.stdout
}

#[test]
fn bind_path_executor_matches_cmd_bind_named_term_document_bytes() {
    let term_value = bind_input_value();
    let input_term = Term::Const {
        value: term_value.clone(),
        sort: primitive_sort("LiftPluginResponse"),
    };
    let mut inputs = HashMapInputCatalog::default();
    let term_cid = address(&input_term);
    inputs.put(term_cid.clone(), Input::Term(input_term.clone()));
    let path = Input::Path(Box::new(CorePath {
        algebra: vec![PathAlgebra {
            name: "bind".to_string(),
            kit: "bind-default".to_string(),
            inputs: vec![term_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }));
    let mut registry = KitRegistry::default();
    registry.register("bind-default", BindKit::default(), BIND_NONCARRIER);

    let chain = execute_path(&path, &registry, &inputs).expect("bind path executes");
    let claim = chain.terminal_claim();
    let cli_bytes = run_bind_cli(&term_value);
    // cmd_bind's stdout is the named-term-document payload; recover the
    // NamedTermDocument via the same helper the path-execution claim consumers use.
    let cli_payload: Term = serde_json::from_slice(&cli_bytes).expect("cmd_bind Term parse");
    let cli_named =
        named_term_document_from_bind_payload(&cli_payload).expect("cmd_bind recovers named term");
    let cli_cid = named_term_document_cid(&cli_named).expect("cmd_bind named terms cid");

    assert_eq!(claim.artifacts, vec![cli_cid]);
    // Bind cites the canonical content CID (strip realize sidecar) of its input.
    let canonical_input = strip_realize_sidecar_from_lift_term(input_term.clone());
    assert_eq!(claim.from, vec![address(&canonical_input)]);
    // bind_term_document's recovered named-term has empty `function` because
    // fn_name is stripped from the bind payload hash (closes #1093).
    assert!(cli_named.terms[0].function.is_empty());
    let payload = claim.payload.as_ref().expect("bind claim payload");
    let named =
        named_term_document_from_bind_payload(payload).expect("bind payload recovers named term");
    assert!(named.terms[0].function.is_empty());
}

#[test]
fn lift_then_bind_path_carries_lift_output_and_claim_premise() {
    let temp = tempfile::tempdir().expect("tempdir");
    let script = fake_lifter(temp.path());
    let workspace_root = temp
        .path()
        .canonicalize()
        .unwrap_or_else(|_| temp.path().to_path_buf());
    let request = json!({
        "surface": "rust",
        "workspace_root": workspace_root,
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {
            "layer": "all",
            "identifyOnly": false
        }
    });
    let command = vec!["bash".to_string(), script.display().to_string()];
    let source = Input::Source {
        dialect: Dialect::Rust,
        bytes: serde_json::to_vec(&request).expect("encode lift request"),
    };
    let lift_kit = LiftKit::new(
        Dialect::Rust,
        "rust",
        command.clone(),
        Some(temp.path().to_path_buf()),
    );
    let lift_claim = lift_kit
        .transform(&source)
        .expect("lift transform succeeds");

    let mut inputs = HashMapInputCatalog::default();
    let source_cid = inputs.insert(source);
    let path = Input::Path(Box::new(CorePath {
        algebra: vec![
            PathAlgebra {
                name: "lift".to_string(),
                kit: "lift-rust".to_string(),
                inputs: vec![source_cid],
                depends_on: vec![],
                verb: Verb::Transform,
            },
            PathAlgebra {
                name: "bind".to_string(),
                kit: "bind-default".to_string(),
                inputs: vec![lift_claim.to.clone()],
                depends_on: vec!["lift".to_string()],
                verb: Verb::Transform,
            },
        ],
    }));
    let mut registry = KitRegistry::default();
    registry.register(
        "lift-rust",
        LiftKit::new(
            Dialect::Rust,
            "rust",
            command,
            Some(temp.path().to_path_buf()),
        ),
        LIFT_NONCARRIER,
    );
    registry.register("bind-default", BindKit::default(), BIND_NONCARRIER);

    let chain = execute_path(&path, &registry, &inputs).expect("lift bind path executes");
    let bind_claim = chain.terminal_claim();

    assert_eq!(bind_claim.from, vec![lift_claim.to.clone()]);
    assert_eq!(bind_claim.premises, vec![lift_claim.cid()]);
}

#[test]
fn bind_path_refuses_unregistered_bind_variant_with_composition_refusal_memento() {
    let term_value = bind_input_value();
    let input_term = Term::Const {
        value: term_value,
        sort: primitive_sort("LiftPluginResponse"),
    };
    let mut inputs = HashMapInputCatalog::default();
    let term_cid = address(&input_term);
    inputs.put(term_cid.clone(), Input::Term(input_term));
    let path = Input::Path(Box::new(CorePath {
        algebra: vec![PathAlgebra {
            name: "bind".to_string(),
            kit: "bind-missing".to_string(),
            inputs: vec![term_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }));
    let registry = KitRegistry::default();

    let error = execute_path(&path, &registry, &inputs).expect_err("missing bind kit refuses");
    let refusal = error
        .composition_refusal()
        .expect("missing bind kit emits refusal memento");
    assert_eq!(refusal.header.failure_kind, "memento-required-missing");
    assert_eq!(
        refusal
            .header
            .missing_memento_requirements
            .as_ref()
            .unwrap()[0]
            .role,
        Some("kit-registry".to_string())
    );
}
