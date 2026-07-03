use std::path::Path;

use serde_json::{json, Value as Json};
use sugar_ir_compiler::{CompileError, CompilerInput, IrCompiler};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT as LEAN_DIALECT};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT as SMT_DIALECT};

fn repo_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-verifier lives under implementations/rust/sugar-verifier")
}

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn int_const(value: i64) -> Json {
    json!({"kind": "const", "value": value, "sort": int_sort()})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn formula_fixture() -> Json {
    json!({
        "kind": "atomic",
        "name": "=",
        "args": [var("x"), int_const(7)]
    })
}

fn term_fixture() -> Json {
    json!({
        "kind": "ctor",
        "name": "Some",
        "args": [int_const(7)]
    })
}

fn typed(ir: Json) -> CompilerInput {
    CompilerInput::decode_json(ir).expect("fixture decodes through frontend")
}

#[test]
fn smtlib_and_lean_compile_typed_do_not_reencode_to_transport_json() {
    for (label, rel_path, forbidden) in [
        (
            "smt-lib",
            "implementations/rust/sugar-ir-compiler-smt-lib/src/lib.rs",
            vec![
                "let ir = ir.to_json_value()?",
                "serde_json::from_value(ir_formula.clone())",
            ],
        ),
        (
            "lean",
            "implementations/rust/sugar-ir-compiler-lean/src/lib.rs",
            vec![
                "let ir = ir.to_json_value()?",
                "let term: Term = serde_json::from_value",
                "serde_json::from_value(ir.clone()).map_err",
            ],
        ),
    ] {
        let text = std::fs::read_to_string(repo_root().join(rel_path)).expect(rel_path);
        for needle in forbidden {
            assert!(
                !text.contains(needle),
                "{label} S3a typed backend ingress still contains legacy transport decode/shim `{needle}`"
            );
        }
    }
}

#[test]
fn smtlib_compile_typed_term_matches_legacy_term_emitter() {
    let ir = term_fixture();
    let typed = typed(ir);
    let out = SmtLibCompiler::new()
        .compile_typed(&typed, SMT_DIALECT)
        .expect("typed SMT-LIB term compile");
    let CompilerInput::Term(term) = &typed else {
        panic!("fixture should decode as a term");
    };
    let expected =
        sugar_ir_compiler_smt_lib::compile_term_to_parts(term).expect("typed SMT-LIB term emitter");
    assert_eq!(out.script(), expected.script());
}

#[test]
fn smtlib_and_lean_compile_typed_formula_match_native_typed_emitters() {
    let typed = typed(formula_fixture());
    let CompilerInput::Formula(formula) = &typed else {
        panic!("fixture should decode as a formula");
    };

    let smt = SmtLibCompiler::new();
    assert_eq!(
        smt.compile_typed(&typed, SMT_DIALECT).expect("typed smt"),
        sugar_ir_compiler_smt_lib::compile_formula_to_parts(formula.formula())
            .expect("typed smt emitter")
    );

    let lean = LeanCompiler::new();
    assert_eq!(
        lean.compile_typed(&typed, LEAN_DIALECT)
            .expect("typed lean"),
        sugar_ir_compiler_lean::compile_formula_to_parts(formula.formula())
            .expect("typed lean emitter")
    );
}

#[test]
fn lean_compile_typed_term_matches_native_typed_emitter() {
    let typed = typed(term_fixture());
    let CompilerInput::Term(term) = &typed else {
        panic!("fixture should decode as a term");
    };
    let lean = LeanCompiler::new();
    assert_eq!(
        lean.compile_typed(&typed, LEAN_DIALECT)
            .expect("typed lean"),
        sugar_ir_compiler_lean::compile_term_to_parts(term).expect("typed lean emitter")
    );
}

#[test]
fn smtlib_target_admissibility_stays_backend_local_on_typed_input() {
    let empty_var_formula = typed(json!({
        "kind": "atomic",
        "name": "=",
        "args": [var(""), int_const(0)]
    }));
    let err = SmtLibCompiler::new()
        .compile_typed(&empty_var_formula, SMT_DIALECT)
        .expect_err("empty variable must remain a backend admissibility refusal");
    assert!(
        matches!(err, CompileError::MalformedIr(detail) if detail == "var name must not be empty")
    );

    let unreduced_schema = typed(json!({
        "kind": "substitute",
        "target": formula_fixture(),
        "term": int_const(1),
        "var": "x"
    }));
    let err = SmtLibCompiler::new()
        .compile_typed(&unreduced_schema, SMT_DIALECT)
        .expect_err("unreduced schema must remain a backend admissibility refusal");
    assert!(
        matches!(err, CompileError::MalformedIr(detail) if detail.contains("wp-rule schema node"))
    );
}

#[test]
fn byte_identity_control_would_notice_s3a_drift() {
    let typed = typed(formula_fixture());
    let mut drifted = LeanCompiler::new()
        .compile_typed(&typed, LEAN_DIALECT)
        .expect("compile");
    let original = drifted.clone();
    drifted.body.push_str("-- planted-drift-control\n");
    assert_ne!(drifted, original);
}
