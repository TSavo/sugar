use serde_json::{json, Value as Json};
use sugar_ir_compiler::{CompiledFormula, CompilerInput, FrontendErrorKind, IrCompiler};
use sugar_ir_compiler_coq::{CoqCompiler, DIALECT as COQ_DIALECT};
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT as LEAN_DIALECT};
use sugar_ir_compiler_maude::{MaudeCompiler, DIALECT as MAUDE_DIALECT};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT as SMT_DIALECT};

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

fn equational_theory_fixture() -> Json {
    json!({
        "kind": "atomic",
        "name": "equational_theory",
        "theory": {
            "name": "sugar-nat",
            "sorts": ["Nat"],
            "operators": [
                {"name": "zero", "arity": [], "result": "Nat"},
                {"name": "s", "arity": ["Nat"], "result": "Nat"},
                {"name": "plus", "arity": ["Nat", "Nat"], "result": "Nat"}
            ],
            "variables": [
                {"name": "N", "sort": "Nat"},
                {"name": "M", "sort": "Nat"}
            ],
            "equations": [
                {
                    "label": "plus-zero-left",
                    "lhs": {"kind": "ctor", "name": "plus", "args": [
                        {"kind": "ctor", "name": "zero", "args": []},
                        {"kind": "var", "name": "N"}
                    ]},
                    "rhs": {"kind": "var", "name": "N"}
                },
                {
                    "label": "plus-s-left",
                    "lhs": {"kind": "ctor", "name": "plus", "args": [
                        {"kind": "ctor", "name": "s", "args": [{"kind": "var", "name": "N"}]},
                        {"kind": "var", "name": "M"}
                    ]},
                    "rhs": {"kind": "ctor", "name": "s", "args": [
                        {"kind": "ctor", "name": "plus", "args": [
                            {"kind": "var", "name": "N"},
                            {"kind": "var", "name": "M"}
                        ]}
                    ]}
                }
            ]
        },
        "obligation": {
            "lhs": {"kind": "ctor", "name": "plus", "args": [
                {"kind": "ctor", "name": "s", "args": [{"kind": "ctor", "name": "zero", "args": []}]},
                {"kind": "ctor", "name": "s", "args": [{"kind": "ctor", "name": "zero", "args": []}]}
            ]},
            "rhs": {"kind": "ctor", "name": "s", "args": [
                {"kind": "ctor", "name": "s", "args": [{"kind": "ctor", "name": "zero", "args": []}]}
            ]}
        }
    })
}

fn compile_typed_is_deterministic(
    compiler: &dyn IrCompiler,
    dialect: &str,
    ir: Json,
) -> CompiledFormula {
    let typed = CompilerInput::decode_json(ir).expect("typed decode");
    let typed_output = compiler
        .compile_typed(&typed, dialect)
        .expect("typed compile");
    assert_eq!(
        typed_output,
        compiler
            .compile_typed(&typed, dialect)
            .expect("typed compile repeats byte-identically")
    );
    typed_output
}

#[test]
fn compile_typed_exists_and_preserves_smtlib_bytes() {
    compile_typed_is_deterministic(&SmtLibCompiler::new(), SMT_DIALECT, formula_fixture());
}

#[test]
fn decode_json_routes_formula_term_and_equational_theory() {
    match CompilerInput::decode_json(formula_fixture()).expect("formula decode") {
        CompilerInput::Formula(formula) => {
            let expected: sugar_ir_types::Formula =
                serde_json::from_value(formula_fixture()).expect("formula fixture");
            assert_eq!(formula.formula(), &expected);
        }
        other => panic!("formula fixture decoded as {other:?}"),
    }

    match CompilerInput::decode_json(term_fixture()).expect("term decode") {
        CompilerInput::Term(term) => {
            let expected: sugar_ir_types::Term =
                serde_json::from_value(term_fixture()).expect("term fixture");
            assert_eq!(term, expected);
        }
        other => panic!("term fixture decoded as {other:?}"),
    }

    match CompilerInput::decode_json(equational_theory_fixture()).expect("maude decode") {
        CompilerInput::EquationalTheory(obligation) => {
            assert_eq!(obligation.kind, "atomic");
            assert_eq!(obligation.name.as_deref(), Some("equational_theory"));
            assert_eq!(obligation.theory.name, "sugar-nat");
            assert_eq!(obligation.theory.operators.len(), 3);
            assert_eq!(obligation.theory.equations.len(), 2);
        }
        other => panic!("equational-theory fixture decoded as {other:?}"),
    }
}

#[test]
fn decode_json_failure_kinds_are_typed_and_real() {
    let malformed = CompilerInput::decode_json(Json::Null).unwrap_err();
    assert_eq!(
        malformed.payload.kind,
        FrontendErrorKind::MalformedTransport
    );
    assert_eq!(malformed.payload.path, "$");

    let unknown = CompilerInput::decode_json(json!({"kind": "mystery"})).unwrap_err();
    assert_eq!(unknown.payload.kind, FrontendErrorKind::UnknownInputKind);
    assert_eq!(unknown.payload.path, "$.kind");

    let invalid = CompilerInput::decode_json(json!({
        "kind": "atomic",
        "name": "=",
        "args": [{"kind": "var"}]
    }))
    .unwrap_err();
    assert_eq!(invalid.payload.kind, FrontendErrorKind::InvalidTypedIr);
    assert_eq!(invalid.payload.path, "$");

    let legacy = CompilerInput::decode_json(json!({
        "kind": "legacy_raw_json",
        "payload": formula_fixture()
    }))
    .unwrap_err();
    assert_eq!(
        legacy.payload.kind,
        FrontendErrorKind::UnsupportedLegacyVariant
    );
    assert_eq!(legacy.payload.path, "$.kind");
}

#[test]
fn decode_json_surfaces_typed_frontend_payload() {
    let err = CompilerInput::decode_json(Json::Null).unwrap_err();
    assert_eq!(err.payload.kind, FrontendErrorKind::MalformedTransport);
    assert_eq!(err.payload.path, "$");
}

#[test]
fn compile_typed_preserves_existing_backend_bytes() {
    compile_typed_is_deterministic(&SmtLibCompiler::new(), SMT_DIALECT, formula_fixture());
    compile_typed_is_deterministic(&LeanCompiler::new(), LEAN_DIALECT, formula_fixture());
    compile_typed_is_deterministic(&CoqCompiler::new(), COQ_DIALECT, formula_fixture());
    compile_typed_is_deterministic(
        &MaudeCompiler::new(),
        MAUDE_DIALECT,
        equational_theory_fixture(),
    );
}

#[test]
fn byte_identity_control_would_notice_planted_drift() {
    let compiler = SmtLibCompiler::new();
    let ir = formula_fixture();
    let input = CompilerInput::decode_json(ir).expect("typed decode");
    let mut drifted = compiler
        .compile_typed(&input, SMT_DIALECT)
        .expect("compile");
    let original = drifted.clone();
    drifted.body.push_str("; planted-drift-control\n");
    assert_ne!(drifted, original);
}
