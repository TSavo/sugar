// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::{
    address, ConformanceDeclaration, Dialect, DomainClaim, HashMapInputCatalog, Input, Kit,
    KitError, Path as CorePath, PathAlgebra, Term, Verb, Verdict, Witness,
};
use sugar_cli::kit_path::{execute_path, KitRegistry, LiftKit, LiftPluginKit};
use serde_json::json;
use sugar_ir_types::Sort;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
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
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","sourceLanguage":"rust","ir":[{"kind":"bind-lift-entry","file":"src/lib.rs","fn_name":"id","fn_line":1,"param_names":["x"],"param_types":["i64"],"return_type":"i64","term_shape":{"kind":"var","name":"x"},"term_shape_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","witnesses":[]}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    script
}

struct ProveStubKit;

impl Kit for ProveStubKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other("prove-stub".to_string())
    }

    fn transform(&self, _input: &Input) -> Result<DomainClaim, KitError> {
        Err(KitError::Transformation(
            "prove-stub transform must not be called".to_string(),
        ))
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        let input_claim_cid = claim.cid();
        let mut proved = claim;
        let mut premises = proved.premises.clone();
        premises.push(input_claim_cid.clone());
        premises.sort();
        premises.dedup();
        proved.from = vec![input_claim_cid];
        proved.premises = premises;
        proved.verdict = Verdict::Proved;
        proved.witness = Some(Witness::Proof {
            tree: json!({"kit": "prove-stub"}),
        });
        Ok(proved)
    }

    fn parse(&self, _input: &Input) -> Result<Term, KitError> {
        Err(KitError::Serialization(
            "prove-stub parse is not supported".to_string(),
        ))
    }

    fn serialize(&self, _term: &Term) -> Result<Input, KitError> {
        Err(KitError::Serialization(
            "prove-stub serialize is not supported".to_string(),
        ))
    }
}

struct TransformOnlyKit {
    claim: DomainClaim,
}

impl Kit for TransformOnlyKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other("transform-only".to_string())
    }

    fn transform(&self, _input: &Input) -> Result<DomainClaim, KitError> {
        Ok(self.claim.clone())
    }

    fn parse(&self, _input: &Input) -> Result<Term, KitError> {
        Err(KitError::Serialization(
            "transform-only parse is not supported".to_string(),
        ))
    }

    fn serialize(&self, _term: &Term) -> Result<Input, KitError> {
        Err(KitError::Serialization(
            "transform-only serialize is not supported".to_string(),
        ))
    }
}

#[test]
fn lift_rust_path_executor_matches_existing_cmd_lift_transport_term_cid() {
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
            "identifyOnly": false,
        }
    });
    let command = vec!["bash".to_string(), script.display().to_string()];
    let existing = LiftPluginKit::new("rust", command.clone(), Some(temp.path().to_path_buf()))
        .parse_session(&Input::Spec(request.clone()))
        .expect("existing lift plugin transport succeeds");

    let source = Input::Source {
        dialect: Dialect::Rust,
        bytes: serde_json::to_vec(&request).expect("encode lift request"),
    };
    let mut inputs = HashMapInputCatalog::default();
    let source_cid = inputs.insert(source);
    let path = Input::Path(Box::new(CorePath {
        algebra: vec![PathAlgebra {
            name: "lift".to_string(),
            kit: "lift-rust".to_string(),
            inputs: vec![source_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
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
        ConformanceDeclaration::NonCarrier {
            reason: "lifts source bytes to DomainClaim; no target source produced",
        },
    );

    let chain = execute_path(&path, &registry, &inputs).expect("lift path executes");
    let claim = chain.terminal_claim();
    assert_eq!(claim.to, existing.claim.to);
    assert_eq!(claim.artifacts, existing.claim.artifacts);
    assert_eq!(
        claim.payload.as_ref(),
        Some(&Term::Const {
            value: json!({
                "kind": "ir-document",
                "sourceLanguage": "rust",
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
        })
    );
    assert_eq!(
        claim.to,
        address(claim.payload.as_ref().expect("payload term"))
    );
}

#[test]
fn lift_rust_then_prove_stub_path_routes_second_step_to_kit_prove() {
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
            "identifyOnly": false,
        }
    });
    let source = Input::Source {
        dialect: Dialect::Rust,
        bytes: serde_json::to_vec(&request).expect("encode lift request"),
    };
    let command = vec!["bash".to_string(), script.display().to_string()];
    let expected_lift_claim = LiftKit::new(
        Dialect::Rust,
        "rust",
        command.clone(),
        Some(temp.path().to_path_buf()),
    )
    .transform(&source)
    .expect("expected lift transform succeeds");
    let mut inputs = HashMapInputCatalog::default();
    let source_cid = inputs.insert(source);
    let lift_claim_input_cid = address(&Input::Claim(expected_lift_claim.clone()));
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
                name: "prove".to_string(),
                kit: "prove-stub".to_string(),
                inputs: vec![lift_claim_input_cid],
                depends_on: vec!["lift".to_string()],
                verb: Verb::Prove,
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
        ConformanceDeclaration::NonCarrier {
            reason: "lifts source bytes to DomainClaim; no target source produced",
        },
    );
    registry.register(
        "prove-stub",
        ProveStubKit,
        ConformanceDeclaration::NonCarrier {
            reason: "discharges claims; no source emission",
        },
    );

    let chain = execute_path(&path, &registry, &inputs).expect("lift then prove path executes");
    let claim = chain.terminal_claim();

    assert_eq!(claim.verdict, Verdict::Proved);
    assert_eq!(
        claim.witness,
        Some(Witness::Proof {
            tree: json!({"kit": "prove-stub"})
        })
    );
    assert_eq!(claim.from, vec![expected_lift_claim.cid()]);
}

#[test]
fn default_kit_prove_refuses_prove_verb_step_with_composition_refusal_memento() {
    let source = Input::Spec(json!({"fixture": "transform-only"}));
    let mut inputs = HashMapInputCatalog::default();
    let source_cid = inputs.insert(source);
    let claim = libsugar::core::RustKit::default()
        .transform(&Input::Term(Term::Const {
            value: json!({"fixture": "claim"}),
            sort: Sort::Primitive {
                name: "Fixture".to_string(),
            },
        }))
        .expect("fixture transform claim");
    let claim_input_cid = address(&Input::Claim(claim.clone()));
    let path = Input::Path(Box::new(CorePath {
        algebra: vec![
            PathAlgebra {
                name: "transform".to_string(),
                kit: "transform-only".to_string(),
                inputs: vec![source_cid],
                depends_on: vec![],
                verb: Verb::Transform,
            },
            PathAlgebra {
                name: "prove".to_string(),
                kit: "prove-default".to_string(),
                inputs: vec![claim_input_cid],
                depends_on: vec!["transform".to_string()],
                verb: Verb::Prove,
            },
        ],
    }));
    let mut registry = KitRegistry::default();
    registry.register(
        "transform-only",
        TransformOnlyKit {
            claim: claim.clone(),
        },
        ConformanceDeclaration::NonCarrier {
            reason: "test fixture; does not emit target source",
        },
    );
    registry.register(
        "prove-default",
        TransformOnlyKit { claim },
        ConformanceDeclaration::NonCarrier {
            reason: "test fixture; does not emit target source",
        },
    );

    let error = execute_path(&path, &registry, &inputs)
        .expect_err("default Kit::prove must refuse Prove verb");
    let refusal = error
        .composition_refusal()
        .expect("Prove verb NotSupported maps to composition refusal");

    assert_eq!(refusal.header.failure_kind, "memento-required-missing");
}

#[test]
fn lift_cli_refuses_unregistered_dialect_with_composition_refusal_memento() {
    let temp = tempfile::tempdir().expect("tempdir");
    let project = temp.path().join("project");
    fs::create_dir_all(project.join(".sugar")).expect("create project config dir");
    fs::write(
        project.join(".sugar/config.toml"),
        "[authoring.lift]\nsurface = \"neverlang\"\n",
    )
    .expect("write config");

    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg(&project)
        .arg("--json")
        .arg("--quiet")
        .output()
        .expect("spawn sugar lift");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        !output.status.success(),
        "unknown lift dialect must fail\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stderr.contains("composition-refusal")
            && stderr.contains("memento-required-missing")
            && stderr.contains("kit-registry"),
        "stderr should carry the registry refusal memento\nstderr:\n{stderr}"
    );
}
