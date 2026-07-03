// SPDX-License-Identifier: Apache-2.0

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::json;
use sugar_ir_types::membership::{
    BoolSort, CallTerm, ClaimFormula, ConstTerm, ConstructionError, EqualityFact,
    FormulaProvenance, IntSort, OpenFormula, ProvenanceKind, ScopedFormula, VarTerm,
};
use sugar_ir_types::{Formula, Sort};

fn crate_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before epoch")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "sugar_proofir_membership_{label}_{}_{}",
        std::process::id(),
        now
    ))
}

fn stated_fixture_provenance() -> FormulaProvenance {
    FormulaProvenance::new(
        ProvenanceKind::Stated,
        "proofir-vocab-s10-test",
        "construction-law fixture",
    )
    .expect("fixture provenance is well-formed")
}

fn closed_equality_claim() -> ClaimFormula {
    let call = CallTerm::<IntSort>::new("A", Vec::new()).expect("call term");
    let rhs = ConstTerm::<IntSort>::int(0).into_typed();
    EqualityFact::new(call, rhs)
        .into_open_formula()
        .scope(BTreeMap::new())
        .expect("closed equality has no free vars")
        .close()
        .with_provenance(stated_fixture_provenance())
        .expect("provenance")
        .claim("EqualityFact.inv")
        .expect("claim role")
}

#[test]
fn role_wrapper_chain_constructs_claim_formula_without_wire_drift() {
    let claim = closed_equality_claim();
    let formula_json = serde_json::to_value(claim.formula()).expect("formula json");
    let claim_json = serde_json::to_value(&claim).expect("claim json");

    assert_eq!(
        claim_json, formula_json,
        "ClaimFormula is a compile-time membership wrapper; wire shape stays the Formula DTO"
    );
    assert_eq!(claim.role(), "EqualityFact.inv");
    assert_eq!(claim.provenance().kind(), ProvenanceKind::Stated);
    assert_eq!(
        serde_json::to_vec(&claim_json).expect("claim bytes"),
        serde_json::to_vec(&formula_json).expect("formula bytes"),
        "serde DTO bytes stay identical because the wrapper serializes transparently"
    );
}

#[test]
fn scoped_formula_refuses_illegal_free_var() {
    let x = VarTerm::<IntSort>::new("x").expect("var").into_typed();
    let zero = ConstTerm::<IntSort>::int(0).into_typed();
    let open = OpenFormula::from_equality_terms(x, zero);

    let err = open
        .scope(BTreeMap::new())
        .expect_err("free x is not closed by an empty scope");
    assert!(matches!(err, ConstructionError::IllegalFreeVars { .. }));
}

#[test]
fn scoped_formula_refuses_sort_mismatch_between_formula_and_scope() {
    let x = VarTerm::<IntSort>::new("x").expect("var").into_typed();
    let zero = ConstTerm::<IntSort>::int(0).into_typed();
    let open = OpenFormula::from_equality_terms(x, zero);
    let mut scope = BTreeMap::new();
    scope.insert(
        "x".to_string(),
        Sort::Primitive {
            name: "Bool".to_string(),
        },
    );

    let err = open
        .scope(scope)
        .expect_err("x is carried as Int and cannot be scoped as Bool");
    assert!(matches!(err, ConstructionError::MismatchedVarSort { .. }));
}

#[test]
fn provenance_and_claim_role_are_required() {
    let call = CallTerm::<IntSort>::new("A", Vec::new()).expect("call term");
    let rhs = ConstTerm::<IntSort>::int(0).into_typed();
    let closed = EqualityFact::new(call, rhs)
        .into_open_formula()
        .scope(BTreeMap::new())
        .expect("closed equality has no free vars")
        .close();

    let bad_provenance = FormulaProvenance::new(ProvenanceKind::Derived, "", "fixture");
    assert!(matches!(
        bad_provenance,
        Err(ConstructionError::MissingProvenance { .. })
    ));

    let provenanced = closed
        .with_provenance(stated_fixture_provenance())
        .expect("provenance");
    let err = provenanced
        .claim("")
        .expect_err("empty claim role is refused");
    assert!(matches!(err, ConstructionError::MissingClaimRole));
}

#[test]
fn call_term_return_sort_is_the_carried_sort() {
    let call = CallTerm::<BoolSort>::new("is_ready", Vec::new()).expect("call term");
    assert_eq!(
        call.sort(),
        Sort::Primitive {
            name: "Bool".to_string(),
        }
    );
}

#[test]
fn formula_transport_decode_enters_the_chain_with_frontend_provenance() {
    let formula: Formula = serde_json::from_value(json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0},
            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": 0}
        ]
    }))
    .expect("formula");

    let claim = ClaimFormula::from_frontend_transport(
        formula.clone(),
        "sugar-ir-compiler::CompilerInput::decode_json",
    )
    .expect("frontend transport claim");
    assert_eq!(claim.formula(), &formula);
    assert_eq!(claim.role(), "compiler-input-formula");
    assert_eq!(claim.provenance().kind(), ProvenanceKind::FrontendTransport);
}

#[test]
fn wrong_sort_equality_and_missing_provenance_are_type_errors() {
    let temp = unique_temp_dir("compile_fail");
    fs::create_dir_all(temp.join("src")).expect("create temp crate");
    fs::write(
        temp.join("Cargo.toml"),
        format!(
            r#"[package]
name = "s10-membership-compile-fail"
version = "0.0.0"
edition = "2021"

[dependencies]
sugar-ir-types = {{ path = "{}" }}
"#,
            crate_root().display()
        ),
    )
    .expect("write Cargo.toml");
    fs::write(
        temp.join("src/lib.rs"),
        r#"
use sugar_ir_types::membership::{
    BoolSort, CallTerm, ClaimFormula, ConstTerm, EqualityFact, IntSort,
};

pub fn wrong_sort_equality() {
    let call = CallTerm::<IntSort>::new("A", Vec::new()).unwrap();
    let rhs = ConstTerm::<BoolSort>::bool(true).into_typed();
    let _ = EqualityFact::new(call, rhs);
}

pub fn naked_claim_shortcut(formula: sugar_ir_types::Formula) {
    let _ = ClaimFormula::new(formula);
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
        "wrong-sort equality and naked ClaimFormula construction must fail to compile"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("expected `TypedTerm<IntSort>`")
            || stderr.contains("no function or associated item named `new`"),
        "compile failure must be structural membership typing, got:\n{stderr}"
    );
}

#[test]
fn legal_near_miss_scopes_explicit_free_var() {
    let x = VarTerm::<IntSort>::new("x").expect("var").into_typed();
    let zero = ConstTerm::<IntSort>::int(0).into_typed();
    let open = OpenFormula::from_equality_terms(x, zero);
    let mut scope = BTreeMap::new();
    scope.insert(
        "x".to_string(),
        Sort::Primitive {
            name: "Int".to_string(),
        },
    );

    let scoped: ScopedFormula = open.scope(scope).expect("x is explicitly scoped as Int");
    assert!(scoped.formula().free_vars().contains("x"));
}
