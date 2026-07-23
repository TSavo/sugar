// SPDX-License-Identifier: MIT OR Apache-2.0

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
use sugar_ir_types::{Declaration, Document, Formula, Sort, Term};

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

fn python_comprehension_document(expression: &str, parameters: &str) -> Document {
    let repo = crate_root()
        .ancestors()
        .nth(3)
        .expect("sugar-ir-types lives below the repository root");
    let python_path = [
        repo.join("implementations/python/sugar-source-tree/src"),
        repo.join("implementations/python/sugar-lift-py-tests/src"),
        repo.join("implementations/python/sugar-lift-python-source/src"),
    ]
    .iter()
    .map(|path| path.display().to_string())
    .collect::<Vec<_>>()
    .join(":");
    let script = r#"
import json
import sys
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.ir import ContractDecl, atomic, declarations_to_value, encode_jcs, make_var
from sugar_source_tree.tree import SourceFile

expression, parameters = sys.argv[1], sys.argv[2]
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as source:
    source.write(f"def A({parameters}):\n    return {expression}\n")
    path = source.name
function = next(SourceFile(path_source(path)).functions())
term = function.sugar().desugar().value.post().args[1]
post = atomic("=", [make_var("out"), term])
print(encode_jcs(declarations_to_value([ContractDecl("A", post=post)])))
"#;
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(expression)
        .arg(parameters)
        .env("PYTHONPATH", python_path)
        .current_dir(repo)
        .output()
        .expect("run Python comprehension construction");
    assert!(
        output.status.success(),
        "Python construction failed:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("parse complete Python ProofIR document")
}

fn document_post_term(document: Document) -> Term {
    let Declaration::Contract {
        post: Some(Formula::Atomic { mut args, .. }),
        ..
    } = document.into_iter().next().expect("one contract")
    else {
        panic!("Python document must contain one contract with an atomic post")
    };
    assert_eq!(args.len(), 2, "post equality has output and comprehension");
    args.pop().expect("comprehension term")
}

fn free_vars(term: Term) -> std::collections::BTreeSet<String> {
    let formula = Formula::Atomic {
        name: "=".to_string(),
        args: vec![term],
    };
    let open = OpenFormula::from_ir_formula_with_sorts(formula, BTreeMap::new());
    open.free_vars()
}

#[test]
fn python_comprehension_lambda_survives_rust_parse_and_membership() {
    let term = document_post_term(python_comprehension_document(
        "[f(x, y) for x in xs]",
        "xs, y",
    ));
    let Term::Ctor { args, .. } = &term else {
        panic!("comprehension must remain a constructor coordinate")
    };
    let transform = args.get(1).expect("comprehension transform");
    assert!(matches!(transform, Term::Lambda { .. }));
    assert_eq!(free_vars(transform.clone()), ["y".to_string()].into());
    assert_eq!(
        free_vars(term.clone()),
        ["xs".to_string(), "y".to_string()].into()
    );

    let formula = Formula::Atomic {
        name: "=".to_string(),
        args: vec![term],
    };
    let sorts = BTreeMap::from([
        (
            "xs".to_string(),
            Sort::Primitive {
                name: "Value".into(),
            },
        ),
        (
            "y".to_string(),
            Sort::Primitive {
                name: "Value".into(),
            },
        ),
    ]);
    OpenFormula::from_ir_formula_with_sorts(formula, sorts.clone())
        .scope(sorts)
        .expect("membership admits xs and y without admitting bound x");
}

#[test]
fn bound_transform_spelling_does_not_turn_a_ctor_into_a_binder() {
    let lying: Term = serde_json::from_value(json!({
        "kind": "ctor",
        "name": "py.bound_transform",
        "args": [
            {"kind": "const", "value": "x", "sort": {"kind": "primitive", "name": "String"}},
            {"kind": "ctor", "name": "call:f", "args": [{"kind": "var", "name": "x"}]}
        ]
    }))
    .expect("lying constructor parses as an ordinary term");
    assert!(matches!(lying, Term::Ctor { .. }));
    assert_eq!(free_vars(lying.clone()), ["x".to_string()].into());

    let formula = Formula::Atomic {
        name: "=".to_string(),
        args: vec![lying],
    };
    let err = OpenFormula::from_ir_formula_with_sorts(formula, BTreeMap::new())
        .scope(BTreeMap::new())
        .expect_err("x is not admitted");
    assert!(matches!(err, ConstructionError::IllegalFreeVars { .. }));
}

#[test]
fn same_spelling_binds_only_transform_body_after_rust_parse() {
    let term = document_post_term(python_comprehension_document("[f(x) for x in x]", "x"));
    let Term::Ctor { args, .. } = &term else {
        panic!("comprehension must remain a constructor coordinate")
    };
    assert_eq!(
        free_vars(args[1].clone()),
        std::collections::BTreeSet::new()
    );
    assert_eq!(free_vars(term), ["x".to_string()].into());
}

#[test]
fn python_generator_expression_stays_lazy_after_rust_parse() {
    let eager = document_post_term(python_comprehension_document("[f(x) for x in xs]", "xs"));
    let lazy = document_post_term(python_comprehension_document("(f(x) for x in xs)", "xs"));

    let Term::Ctor {
        name: eager_name,
        args: eager_args,
    } = &eager
    else {
        panic!("eager comprehension must remain a constructor coordinate")
    };
    let Term::Ctor {
        name: lazy_name,
        args: lazy_args,
    } = &lazy
    else {
        panic!("generator expression must remain a constructor coordinate")
    };

    assert_eq!(eager_name, "py.listcomp");
    assert_eq!(lazy_name, "py.generatorexp");
    assert_ne!(eager, lazy, "eager and lazy coordinates must stay distinct");

    let Some(Term::Lambda { body, .. }) = lazy_args.get(1) else {
        panic!("generator transform must remain a real lambda binder")
    };
    assert!(
        matches!(body.as_ref(), Term::Ctor { name, .. } if name == "call:f"),
        "generator creation must retain the call inside the unforced transform"
    );
    assert_eq!(
        eager_args.get(1),
        lazy_args.get(1),
        "only the eager/lazy consumer coordinate differs"
    );
    assert_eq!(free_vars(lazy), ["xs".to_string()].into());
}

#[test]
fn python_spread_call_and_literals_survive_rust_parse() {
    let call = document_post_term(python_comprehension_document("f(0, *xs, **kw)", "xs, kw"));
    let Term::Ctor {
        name: call_name,
        args: call_args,
    } = call
    else {
        panic!("spread call must remain a constructor coordinate")
    };
    assert_eq!(call_name, "call:f");
    assert!(matches!(
        call_args.get(1),
        Some(Term::Ctor { name, args })
            if name == "python:starred_arg" && matches!(args.as_slice(), [Term::Var { name }] if name == "xs")
    ));
    assert!(matches!(
        call_args.get(2),
        Some(Term::Ctor { name, args })
            if name == "python:double_starred_kwarg" && matches!(args.as_slice(), [Term::Var { name }] if name == "kw")
    ));

    for (expression, outer) in [
        ("[0, *xs]", "python:list"),
        ("(0, *xs)", "python:tuple"),
        ("{0, *xs}", "python:set"),
    ] {
        let term = document_post_term(python_comprehension_document(expression, "xs"));
        let Term::Ctor { name, args } = term else {
            panic!("spread display must remain a constructor coordinate")
        };
        assert_eq!(name, outer);
        assert!(matches!(
            args.last(),
            Some(Term::Ctor { name, args })
                if name == "python:starred" && matches!(args.as_slice(), [Term::Var { name }] if name == "xs")
        ));
    }

    let dict = document_post_term(python_comprehension_document("{0: 1, **kw}", "kw"));
    let Term::Ctor { name, args } = dict else {
        panic!("spread dict must remain a constructor coordinate")
    };
    assert_eq!(name, "python:dict");
    assert!(matches!(
        args.last(),
        Some(Term::Ctor { name, args })
            if name == "python:dict_entry"
                && matches!(args.as_slice(), [Term::Ctor { name: none, args }, Term::Var { name: kw }]
                    if none == "None" && args.is_empty() && kw == "kw")
    ));
}

#[test]
fn malformed_spread_spelling_remains_an_ordinary_ctor_after_rust_parse() {
    let malformed: Term = serde_json::from_value(json!({
        "kind": "ctor",
        "name": "python:starred_arg",
        "args": []
    }))
    .expect("generic ProofIR constructors do not fabricate spread admission");

    assert!(matches!(
        malformed,
        Term::Ctor { name, args } if name == "python:starred_arg" && args.is_empty()
    ));
}
