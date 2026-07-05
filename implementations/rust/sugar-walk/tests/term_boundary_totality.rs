// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IrTerm boundary-collapse campaign (#3192), Slice 2 Instrument A re-anchor.

use std::panic;

use sugar_ir_types as ir;
use sugar_walk::term_boundary::{lower_ir, lower_ir_formula, raise_ir, raise_ir_formula};

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct ExpectedConversionRefusal {
    name: &'static str,
    replacement: &'static str,
}

const EXPECTED_CONVERSION_REFUSALS: &[ExpectedConversionRefusal] = &[
    ExpectedConversionRefusal {
        name: "Function sort",
        replacement: "model function sorts in symbolic Sort before lowering",
    },
    ExpectedConversionRefusal {
        name: "Dependent sort",
        replacement: "model dependent sorts in symbolic Sort before lowering",
    },
    ExpectedConversionRefusal {
        name: "Region sort",
        replacement: "lower regions before symbolic conversion or model Region in symbolic Sort",
    },
];

fn primitive(name: &str) -> ir::Sort {
    ir::Sort::Primitive { name: name.into() }
}

fn var(name: &str) -> ir::Term {
    ir::Term::Var { name: name.into() }
}

fn int_const(value: i64) -> ir::Term {
    ir::Term::Const {
        value: serde_json::json!(value),
        sort: primitive("Int"),
    }
}

fn wide_int_const(value: &str) -> ir::Term {
    ir::Term::Const {
        value: serde_json::json!(value),
        sort: primitive("Int"),
    }
}

fn real_const(value: &str) -> ir::Term {
    ir::Term::Const {
        value: serde_json::json!(value),
        sort: primitive("Real"),
    }
}

fn string_const(value: &str) -> ir::Term {
    ir::Term::Const {
        value: serde_json::json!(value),
        sort: primitive("String"),
    }
}

fn bool_const(value: bool) -> ir::Term {
    ir::Term::Const {
        value: serde_json::json!(value),
        sort: primitive("Bool"),
    }
}

fn ctor(name: &str, args: Vec<ir::Term>) -> ir::Term {
    ir::Term::Ctor {
        name: name.into(),
        args,
    }
}

fn term_corpus() -> Vec<(&'static str, ir::Term)> {
    vec![
        ("var", var("x")),
        ("const-int", int_const(42)),
        (
            "const-wide-int",
            wide_int_const("170141183460469231731687303715884105727"),
        ),
        ("const-real", real_const("2.5")),
        ("const-string", string_const("hello")),
        ("const-bool", bool_const(true)),
        (
            "ctor-nested",
            ctor(
                "cf_ite",
                vec![
                    ctor("is_some", vec![var("opt")]),
                    ctor("unwrap", vec![var("opt")]),
                    int_const(0),
                ],
            ),
        ),
        (
            "lambda",
            ir::Term::Lambda {
                param_name: "n".into(),
                param_sort: primitive("Int"),
                body: Box::new(ctor("+", vec![var("n"), int_const(1)])),
            },
        ),
        (
            "let",
            ir::Term::Let {
                bindings: vec![ir::LetBinding {
                    name: "tmp".into(),
                    bound_term: ctor("method:len", vec![var("xs")]),
                }],
                body: Box::new(ctor("cf_eq", vec![var("tmp"), int_const(1)])),
            },
        ),
    ]
}

fn formula_corpus() -> Vec<(&'static str, ir::Formula)> {
    vec![
        (
            "atomic",
            ir::Formula::Atomic {
                name: "=".into(),
                args: vec![ctor("parseInt", vec![string_const("7")]), int_const(7)],
            },
        ),
        (
            "and-or-not-implies",
            ir::Formula::Implies {
                operands: vec![
                    ir::Formula::And {
                        operands: vec![
                            ir::Formula::Atomic {
                                name: ">".into(),
                                args: vec![var("x"), int_const(0)],
                            },
                            ir::Formula::Not {
                                operands: vec![ir::Formula::Atomic {
                                    name: "=".into(),
                                    args: vec![var("x"), int_const(13)],
                                }],
                            },
                        ],
                    },
                    ir::Formula::Or {
                        operands: vec![
                            ir::Formula::Atomic {
                                name: ">=".into(),
                                args: vec![var("x"), int_const(1)],
                            },
                            ir::Formula::Atomic {
                                name: "=".into(),
                                args: vec![var("x"), int_const(0)],
                            },
                        ],
                    },
                ],
            },
        ),
        (
            "forall",
            ir::Formula::Forall {
                name: "n".into(),
                sort: primitive("Int"),
                body: Box::new(ir::Formula::Atomic {
                    name: ">".into(),
                    args: vec![var("n"), int_const(0)],
                }),
            },
        ),
        (
            "exists",
            ir::Formula::Exists {
                name: "s".into(),
                sort: primitive("String"),
                body: Box::new(ir::Formula::Atomic {
                    name: "=".into(),
                    args: vec![ctor("parseInt", vec![var("s")]), int_const(1)],
                }),
            },
        ),
        (
            "choice",
            ir::Formula::Choice {
                var_name: "chosen".into(),
                sort: primitive("Bool"),
                body: Box::new(ir::Formula::Atomic {
                    name: "=".into(),
                    args: vec![var("chosen"), bool_const(true)],
                }),
            },
        ),
    ]
}

fn assert_same_term_json_bytes(label: &str, before: &ir::Term, after: &ir::Term) {
    let before_bytes = serde_json::to_vec(before).expect("serialize original IR");
    let after_bytes = serde_json::to_vec(after).expect("serialize round-tripped IR");
    assert_eq!(
        before, after,
        "{label} changed structurally after raise(lower)"
    );
    assert_eq!(
        before_bytes, after_bytes,
        "{label} changed JSON bytes after raise(lower)"
    );
}

fn assert_same_formula_json_bytes(label: &str, before: &ir::Formula, after: &ir::Formula) {
    let before_bytes = serde_json::to_vec(before).expect("serialize original IR");
    let after_bytes = serde_json::to_vec(after).expect("serialize round-tripped IR");
    assert_eq!(
        before, after,
        "{label} changed structurally after raise(lower)"
    );
    assert_eq!(
        before_bytes, after_bytes,
        "{label} changed JSON bytes after raise(lower)"
    );
}

#[test]
fn ir_terms_round_trip_through_term_boundary_byte_identically() {
    let corpus = term_corpus();
    for (label, original) in &corpus {
        let lowered = lower_ir(original);
        let raised = raise_ir(&lowered);
        assert_same_term_json_bytes(label, original, &raised);
    }
    eprintln!(
        "R(term-boundary-term-byte-drift) = 0 corpus_terms={}",
        corpus.len()
    );
}

#[test]
fn ir_formulas_round_trip_through_term_boundary_byte_identically() {
    let corpus = formula_corpus();
    for (label, original) in &corpus {
        let lowered = lower_ir_formula(original);
        let raised = raise_ir_formula(&lowered);
        assert_same_formula_json_bytes(label, original, &raised);
    }
    eprintln!(
        "R(term-boundary-formula-byte-drift) = 0 corpus_formulas={}",
        corpus.len()
    );
}

fn unsupported_sort_for(name: &str) -> ir::Sort {
    match name {
        "Function sort" => ir::Sort::Function {
            args: vec![primitive("Int")],
            ret: Box::new(primitive("Bool")),
        },
        "Dependent sort" => ir::Sort::Dependent {
            name: "Vector".into(),
            index_var: "n".into(),
            index_sort: Box::new(primitive("Int")),
        },
        "Region sort" => ir::Sort::Region { name: "'a".into() },
        other => panic!("unknown conversion refusal fixture: {other}"),
    }
}

fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(message) = payload.downcast_ref::<String>() {
        message.clone()
    } else if let Some(message) = payload.downcast_ref::<&str>() {
        (*message).to_string()
    } else {
        "<non-string panic payload>".to_string()
    }
}

#[test]
fn unsupported_sorts_are_loud_refusals_through_term_boundary() {
    let mut observed = Vec::new();
    for expected in EXPECTED_CONVERSION_REFUSALS {
        let term = ir::Term::Const {
            value: serde_json::json!(0),
            sort: unsupported_sort_for(expected.name),
        };
        let refusal = panic::catch_unwind(|| lower_ir(&term));
        let Err(payload) = refusal else {
            panic!(
                "{} silently converted; replacement is {}",
                expected.name, expected.replacement
            );
        };
        let message = panic_message(payload.as_ref());
        assert!(
            message.contains("not supported in symbolic Sort wrapper"),
            "{} refusal did not name the symbolic Sort wrapper seam: {message}",
            expected.name
        );
        observed.push(expected.name);
    }

    let expected_names = EXPECTED_CONVERSION_REFUSALS
        .iter()
        .map(|entry| entry.name)
        .collect::<Vec<_>>();
    assert_eq!(observed, expected_names);
    eprintln!(
        "R(conversion-refusals) = {} pinned={:?}",
        EXPECTED_CONVERSION_REFUSALS.len(),
        expected_names
    );
}
