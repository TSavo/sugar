// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeSet;
use std::path::Path;

use libsugar::desugar::{
    desugar, load_desugaring_rules_from_dir, DesugarRule, DesugaringSet, RefusalKind,
};
use serde_json::json;
use sugar_ir_types::{IrTerm, Sort};

fn any_sort() -> Sort {
    Sort::Primitive {
        name: "Any".to_string(),
    }
}

fn term_var(name: &str) -> IrTerm {
    IrTerm::Var {
        name: name.to_string(),
    }
}

fn term_const(value: serde_json::Value) -> IrTerm {
    IrTerm::Const {
        value,
        sort: any_sort(),
    }
}

fn op(name: &str, args: Vec<IrTerm>) -> IrTerm {
    IrTerm::Ctor {
        name: name.to_string(),
        args,
    }
}

fn rule(json: serde_json::Value) -> DesugarRule {
    DesugarRule::from_json_value(json).expect("fixture rule parses")
}

#[test]
fn innermost_desugar_rewrites_to_fixpoint() {
    let inner = rule(json!({
        "kind": "equation",
        "fn_name": "test:inner-desugar",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:inner", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:core_inner", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {
                "kind": "wp-preservation",
                "status": "discharged",
                "method": "unit-test-fixture"
            }
        }
    }));
    let outer = rule(json!({
        "kind": "equation",
        "fn_name": "test:outer-desugar",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:outer", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:core_outer", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {
                "kind": "wp-preservation",
                "status": "discharged",
                "method": "unit-test-fixture"
            }
        }
    }));
    let set = DesugaringSet::new(vec![outer, inner]).expect("non-overlapping rules certify");
    let surface = op("test:outer", vec![op("test:inner", vec![term_var("x")])]);

    let out = desugar(&set, surface).expect("desugar succeeds");

    assert_eq!(
        out.normal_form,
        op(
            "test:core_outer",
            vec![op("test:core_inner", vec![term_var("x")])]
        )
    );
    assert_eq!(
        out.applied_rules,
        vec![
            "test:inner-desugar".to_string(),
            "test:outer-desugar".to_string()
        ]
    );
    assert!(out.cid.starts_with("blake3-512:"));
}

#[test]
fn desugar_refuses_non_terminating_rule_set() {
    let looping = rule(json!({
        "kind": "equation",
        "fn_name": "test:looping-desugar",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:sugar", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:sugar", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {
                "kind": "wp-preservation",
                "status": "discharged",
                "method": "unit-test-fixture"
            }
        }
    }));

    let err = DesugaringSet::new(vec![looping]).expect_err("looping set refuses");

    assert_eq!(
        err.kind(),
        RefusalKind::NonTerminatingDesugaringSet.as_str()
    );
}

#[test]
fn desugar_refuses_non_confluent_duplicate_left_hand_side() {
    let first = rule(json!({
        "kind": "equation",
        "fn_name": "test:sugar-to-a",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:sugar", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:a", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {
                "kind": "wp-preservation",
                "status": "discharged",
                "method": "unit-test-fixture"
            }
        }
    }));
    let second = rule(json!({
        "kind": "equation",
        "fn_name": "test:sugar-to-b",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:sugar", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:b", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {
                "kind": "wp-preservation",
                "status": "discharged",
                "method": "unit-test-fixture"
            }
        }
    }));

    let err = DesugaringSet::new(vec![first, second]).expect_err("ambiguous set refuses");

    assert_eq!(err.kind(), RefusalKind::NonConfluentDesugaringSet.as_str());
}

#[test]
fn parse_refuses_non_trivial_pre_side_condition() {
    // A `pre` other than the trivially-true atomic predicate gates the rewrite;
    // the rewriter does not evaluate side-conditions, so such a memento must be
    // refused -- not silently treated as if the guard always held.
    let err = DesugarRule::from_json_value(json!({
        "kind": "equation",
        "fn_name": "test:guarded-desugar",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "is-null", "args": [{"kind": "var", "name": "x"}]},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:surface", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:core", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {"kind": "wp-preservation", "status": "discharged", "method": "n/a"}
        }
    }))
    .expect_err("non-trivial pre is refused");
    assert_eq!(err.kind(), RefusalKind::InvalidDesugaringEquation.as_str());
    assert!(err.to_string().contains("pre"));
}

#[test]
fn parse_accepts_trivially_true_pre() {
    let r = DesugarRule::from_json_value(json!({
        "kind": "equation",
        "fn_name": "test:plain-desugar",
        "formals": ["x"],
        "formal_sorts": ["sort_any.spec.json"],
        "role": "desugaring",
        "direction": "left-to-right",
        "pre": {"kind": "atomic", "name": "true", "args": []},
        "post": {
            "kind": "equation",
            "lhs": {"kind": "op", "name": "test:surface", "args": [{"kind": "var", "name": "x"}]},
            "rhs": {"kind": "op", "name": "test:core", "args": [{"kind": "var", "name": "x"}]}
        },
        "obligations": {
            "wp_preservation": {"kind": "wp-preservation", "status": "discharged", "method": "n/a"}
        }
    }))
    .expect("trivially-true pre parses");
    assert_eq!(r.fn_name, "test:plain-desugar");
}

#[test]
fn csharp_for_surface_program_collapses_to_core_normal_form() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .expect("repo root");
    let csharp_specs = repo_root.join("menagerie/csharp-language-signature/specs");
    let rules = load_desugaring_rules_from_dir(&csharp_specs).expect("load csharp desugars");
    let set = DesugaringSet::new(rules).expect("csharp desugars certify");

    let surface = op(
        "csharp:for",
        vec![
            op(
                "csharp:decl",
                vec![term_const(json!("i")), term_const(json!(0))],
            ),
            op("csharp:lt", vec![term_var("i"), term_const(json!(10))]),
            op(
                "csharp:assign",
                vec![
                    term_var("i"),
                    op("csharp:add", vec![term_var("i"), term_const(json!(1))]),
                ],
            ),
            op(
                "csharp:call",
                vec![term_const(json!("body")), term_var("i")],
            ),
        ],
    );

    let first = desugar(&set, surface.clone()).expect("desugar succeeds");
    let second = desugar(&set, surface).expect("desugar is repeatable");

    assert!(!contains_op(&first.normal_form, "csharp:for"));
    assert_eq!(
        first.normal_form,
        op(
            "csharp:seq",
            vec![
                op(
                    "csharp:decl",
                    vec![term_const(json!("i")), term_const(json!(0))]
                ),
                op(
                    "csharp:while",
                    vec![
                        op("csharp:lt", vec![term_var("i"), term_const(json!(10))]),
                        op(
                            "csharp:seq",
                            vec![
                                op(
                                    "csharp:call",
                                    vec![term_const(json!("body")), term_var("i")]
                                ),
                                op(
                                    "csharp:assign",
                                    vec![
                                        term_var("i"),
                                        op("csharp:add", vec![term_var("i"), term_const(json!(1))]),
                                    ],
                                )
                            ]
                        )
                    ]
                )
            ]
        )
    );
    assert_eq!(first.canonical_bytes, second.canonical_bytes);
    assert_eq!(first.cid, second.cid);
    assert_eq!(first.applied_rules, vec!["csharp:for-desugar"]);
    assert_eq!(first.wp_obligations.len(), 1);
    assert_eq!(first.wp_obligations[0].status, "discharged");

    let core_ops = BTreeSet::from([
        "csharp:add".to_string(),
        "csharp:assign".to_string(),
        "csharp:call".to_string(),
        "csharp:decl".to_string(),
        "csharp:lt".to_string(),
        "csharp:seq".to_string(),
        "csharp:while".to_string(),
    ]);
    assert!(set
        .non_core_ops(&first.normal_form, &core_ops)
        .expect("core check succeeds")
        .is_empty());
}

#[test]
fn python_boolean_surface_program_collapses_to_core_normal_form() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .expect("repo root");
    let python_specs = repo_root.join("menagerie/python-language-signature/specs");
    let rules = load_desugaring_rules_from_dir(&python_specs).expect("load python desugars");
    let set = DesugaringSet::new(rules).expect("python desugars certify");

    let surface = op(
        "python:not",
        vec![op("python:and", vec![term_var("a"), term_var("b")])],
    );

    let out = desugar(&set, surface).expect("desugar succeeds");

    assert!(!contains_op(&out.normal_form, "python:not"));
    assert!(!contains_op(&out.normal_form, "python:and"));
    assert_eq!(
        out.normal_form,
        op(
            "python:ite-bool",
            vec![
                op(
                    "python:ite-bool",
                    vec![
                        term_var("a"),
                        term_var("b"),
                        IrTerm::Const {
                            value: json!(false),
                            sort: Sort::Primitive {
                                name: "Bool".to_string(),
                            },
                        },
                    ],
                ),
                IrTerm::Const {
                    value: json!(false),
                    sort: Sort::Primitive {
                        name: "Bool".to_string(),
                    },
                },
                IrTerm::Const {
                    value: json!(true),
                    sort: Sort::Primitive {
                        name: "Bool".to_string(),
                    },
                },
            ],
        )
    );
    assert_eq!(
        out.applied_rules,
        vec!["python:and-desugar", "python:not-desugar"]
    );
    assert_eq!(out.wp_obligations.len(), 2);
}

fn contains_op(term: &IrTerm, name: &str) -> bool {
    match term {
        IrTerm::Ctor {
            name: term_name,
            args,
        } => term_name == name || args.iter().any(|arg| contains_op(arg, name)),
        IrTerm::Let { bindings, body } => {
            bindings
                .iter()
                .any(|binding| contains_op(&binding.bound_term, name))
                || contains_op(body, name)
        }
        IrTerm::Lambda { body, .. } => contains_op(body, name),
        IrTerm::Var { .. } | IrTerm::Const { .. } => false,
    }
}
