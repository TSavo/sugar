// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::json;
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT};
use sugar_ir_types::membership::{
    CallTerm, ClaimFormula, ConstTerm, EqualityFact, FormulaProvenance, IntSort, ProvenanceKind,
};
use sugar_ir_types::Formula;

fn compiler_crate_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-ir-compiler-smt-lib has a parent")
        .join("sugar-ir-compiler")
}

fn ir_types_crate_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-ir-compiler-smt-lib has a parent")
        .join("sugar-ir-types")
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before epoch")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "sugar_proofir_membership_seam_{label}_{}_{}",
        std::process::id(),
        now
    ))
}

fn claim_formula() -> ClaimFormula {
    let provenance = FormulaProvenance::new(
        ProvenanceKind::Stated,
        "proofir-vocab-s10-test",
        "compiler seam fixture",
    )
    .expect("provenance");
    EqualityFact::new(
        CallTerm::<IntSort>::new("A", Vec::new()).expect("call"),
        ConstTerm::<IntSort>::int(0).into_typed(),
    )
    .into_open_formula()
    .scope(BTreeMap::new())
    .expect("closed equality")
    .close()
    .with_provenance(provenance)
    .expect("provenanced")
    .claim("EqualityFact.inv")
    .expect("claim")
}

#[test]
fn claim_formula_lowers_to_compiler_input_without_backend_byte_drift() {
    let claim = claim_formula();
    let via_claim = CompilerInput::from_claim_formula(claim.clone());
    let via_json = CompilerInput::decode_json(serde_json::to_value(claim.formula()).unwrap())
        .expect("frontend decode wraps formula as claim");

    assert_eq!(via_claim, via_json);

    let compiler = SmtLibCompiler::new();
    let compiled_from_claim = compiler
        .compile_typed(&via_claim, DIALECT)
        .expect("compile claim");
    let compiled_from_json = compiler
        .compile_typed(&via_json, DIALECT)
        .expect("compile decoded formula");

    assert_eq!(compiled_from_claim.preamble, compiled_from_json.preamble);
    assert_eq!(compiled_from_claim.body, compiled_from_json.body);
    assert_eq!(compiled_from_claim.free_vars, compiled_from_json.free_vars);
    assert_eq!(
        compiled_from_claim.opacity_manifest,
        compiled_from_json.opacity_manifest
    );
    assert_eq!(compiled_from_claim.metadata, compiled_from_json.metadata);
}

#[test]
fn naked_formula_cannot_construct_compiler_formula_input() {
    let temp = unique_temp_dir("compile_fail");
    fs::create_dir_all(temp.join("src")).expect("create temp crate");
    fs::write(
        temp.join("Cargo.toml"),
        format!(
            r#"[package]
name = "s10-naked-formula-compile-fail"
version = "0.0.0"
edition = "2021"

[dependencies]
sugar-ir-compiler = {{ path = "{}" }}
sugar-ir-types = {{ path = "{}" }}
serde_json = "1"
"#,
            compiler_crate_root().display(),
            ir_types_crate_root().display()
        ),
    )
    .expect("write Cargo.toml");
    fs::write(
        temp.join("src/lib.rs"),
        r#"
use serde_json::json;
use sugar_ir_compiler::CompilerInput;
use sugar_ir_types::Formula;

pub fn naked_formula_input() -> CompilerInput {
    let formula: Formula = serde_json::from_value(json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0},
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0}
        ]
    })).unwrap();
    CompilerInput::Formula(formula)
}
"#,
    )
    .expect("write lib.rs");

    let output = Command::new(std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string()))
        .arg("check")
        .arg("--quiet")
        .current_dir(&temp)
        .env("CARGO_TARGET_DIR", temp.join("target"))
        .output()
        .expect("run cargo check");
    let _ = fs::remove_dir_all(&temp);

    assert!(
        !output.status.success(),
        "a naked sugar_ir_types::Formula must not construct CompilerInput::Formula"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("expected `ClaimFormula`") || stderr.contains("mismatched types"),
        "compile failure must be the terminal membership wrapper, got:\n{stderr}"
    );
}

#[test]
fn frontend_decode_formula_still_accepts_existing_wire_shape() {
    let input = CompilerInput::decode_json(json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0},
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0}
        ]
    }))
    .expect("json formula decodes");
    let CompilerInput::Formula(claim) = input else {
        panic!("formula wire shape must decode to formula claim");
    };
    let expected: Formula = serde_json::from_value(serde_json::to_value(claim.formula()).unwrap())
        .expect("formula still serializes as Formula");
    assert_eq!(claim.formula(), &expected);
}
