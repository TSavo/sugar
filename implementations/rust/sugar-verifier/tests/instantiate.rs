// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 4 (instantiate) tests. Pins:
//   - substitutes the call's arg term for the forall's bound variable
//     in the body
//   - respects shadowing: an inner quantifier rebinding the same name
//     blocks substitution beneath it
//   - rejects non-forall resolved formulas (fail-closed)
//   - rejects when no arg term is supplied
//   - rejects when resolved property has no ir_formula

use serde_json::json;

use sugar_verifier::{instantiate, ResolvedProperty};

fn forall_n_gt_0() -> serde_json::Value {
    json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    })
}

fn resolved(formula: serde_json::Value) -> ResolvedProperty {
    ResolvedProperty {
        cid: "blake3-512:00".into(),
        ir_formula: Some(formula),
        ir_kit_version: String::new(),
        ..Default::default()
    }
}

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------

#[test]
fn substitutes_var_for_bound_name_in_atomic() {
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&resolved(forall_n_gt_0()), &arg).expect("instantiate");
    let body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    let args = body.pointer("/args").unwrap();
    assert_eq!(args[0], json!({"kind": "var", "name": "x"}));
}

#[test]
fn body_kind_preserved_after_substitution() {
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&resolved(forall_n_gt_0()), &arg).expect("instantiate");
    let body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    assert_eq!(body.get("kind").unwrap(), "atomic");
    assert_eq!(body.get("name").unwrap(), ">");
}

#[test]
fn substitutes_const_term() {
    let arg =
        Some(json!({"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}));
    let r = instantiate::run(&resolved(forall_n_gt_0()), &arg).expect("instantiate");
    let body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    let args = body.pointer("/args").unwrap();
    assert_eq!(args[0].get("value").unwrap(), 42);
}

#[test]
fn substitutes_ctor_term() {
    let arg = Some(json!({
        "kind": "ctor",
        "name": "parseInt",
        "args": [{"kind": "var", "name": "s"}]
    }));
    let r = instantiate::run(&resolved(forall_n_gt_0()), &arg).expect("instantiate");
    let body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    let args = body.pointer("/args").unwrap();
    assert_eq!(args[0].get("kind").unwrap(), "ctor");
    assert_eq!(args[0].get("name").unwrap(), "parseInt");
}

#[test]
fn substitutes_in_connective_operands() {
    let formula = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "and",
            "operands": [
                {"kind": "atomic", "name": ">", "args": [
                    {"kind": "var", "name": "n"},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]},
                {"kind": "atomic", "name": "<", "args": [
                    {"kind": "var", "name": "n"},
                    {"kind": "const", "value": 100, "sort": {"kind": "primitive", "name": "Int"}}
                ]}
            ]
        }
    });
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&resolved(formula), &arg).expect("instantiate");
    let body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    let ops = body.pointer("/operands").unwrap();
    // Both atomics should have arg[0] = {"kind":"var","name":"x"}
    assert_eq!(ops[0].pointer("/args/0/name").unwrap(), "x");
    assert_eq!(ops[1].pointer("/args/0/name").unwrap(), "x");
}

#[test]
fn substitution_propagates_through_ctor_args() {
    let formula = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": "=", "args": [
                {"kind": "ctor", "name": "f", "args": [{"kind": "var", "name": "n"}]},
                {"kind": "var", "name": "n"}
            ]
        }
    });
    let arg =
        Some(json!({"kind": "const", "value": 7, "sort": {"kind": "primitive", "name": "Int"}}));
    let r = instantiate::run(&resolved(formula), &arg).expect("instantiate");
    let body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    // Inside the ctor's args, n should be replaced.
    let ctor_arg0 = body.pointer("/args/0/args/0").unwrap();
    assert_eq!(ctor_arg0.get("value").unwrap(), 7);
    let direct_arg = body.pointer("/args/1").unwrap();
    assert_eq!(direct_arg.get("value").unwrap(), 7);
}

// ---------------------------------------------------------------------------
// Shadowing
// ---------------------------------------------------------------------------

#[test]
fn inner_quantifier_with_same_name_blocks_substitution() {
    // forall n. forall n. n > 0: when we instantiate the OUTER n,
    // the inner forall rebinds n, so the body's "n" remains untouched.
    let formula = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "forall",
            "name": "n",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": {
                "kind": "atomic", "name": ">", "args": [
                    {"kind": "var", "name": "n"},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }
    });
    let arg =
        Some(json!({"kind": "const", "value": 99, "sort": {"kind": "primitive", "name": "Int"}}));
    let r = instantiate::run(&resolved(formula), &arg).expect("instantiate");
    // Expected: the outer forall's body is `forall n. n > 0` and we
    // do NOT descend into shadowed inner-n. So inner-body's n stays a
    // var, not 99.
    let outer_body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    let inner_body = outer_body.pointer("/body").unwrap();
    let n_in_inner = inner_body.pointer("/args/0").unwrap();
    assert_eq!(n_in_inner.get("kind").unwrap(), "var");
    assert_eq!(n_in_inner.get("name").unwrap(), "n");
}

#[test]
fn inner_quantifier_with_different_name_allows_substitution() {
    // forall n. forall m. n > m: instantiate n as 5; m is left alone.
    let formula = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "forall",
            "name": "m",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": {
                "kind": "atomic", "name": ">", "args": [
                    {"kind": "var", "name": "n"},
                    {"kind": "var", "name": "m"}
                ]
            }
        }
    });
    let arg =
        Some(json!({"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}));
    let r = instantiate::run(&resolved(formula), &arg).expect("instantiate");
    let outer_body = r
        .ir_formula
        .pointer("/body")
        .expect("ir_formula is forall with body");
    let inner_body = outer_body.pointer("/body").unwrap();
    let arg_n = inner_body.pointer("/args/0").unwrap();
    let arg_m = inner_body.pointer("/args/1").unwrap();
    assert_eq!(arg_n.get("value").unwrap(), 5);
    assert_eq!(arg_m.get("kind").unwrap(), "var");
    assert_eq!(arg_m.get("name").unwrap(), "m");
}

// ---------------------------------------------------------------------------
// Fail-closed: bad inputs
// ---------------------------------------------------------------------------

#[test]
fn errors_when_no_arg_term_supplied() {
    let r = instantiate::run(&resolved(forall_n_gt_0()), &None);
    assert!(r.is_err());
}

#[test]
fn errors_when_resolved_has_no_ir_formula() {
    let rp = ResolvedProperty {
        cid: "blake3-512:00".into(),
        ir_formula: None,
        ir_kit_version: String::new(),
        ..Default::default()
    };
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&rp, &arg);
    assert!(r.is_err());
}

#[test]
fn errors_when_resolved_formula_is_not_forall() {
    let formula = json!({
        "kind": "atomic",
        "name": ">",
        "args": [
            {"kind": "var", "name": "n"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&resolved(formula), &arg);
    assert!(r.is_err());
}

#[test]
fn errors_when_forall_lacks_name() {
    let formula = json!({
        "kind": "forall",
        // no name
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {"kind": "atomic", "name": "=", "args": []}
    });
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&resolved(formula), &arg);
    assert!(r.is_err());
}

#[test]
fn errors_when_forall_lacks_body() {
    let formula = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"}
        // no body
    });
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let r = instantiate::run(&resolved(formula), &arg);
    assert!(r.is_err());
}

#[test]
fn obligation_carries_property_cid_and_kit_version() {
    let arg = Some(json!({"kind": "var", "name": "x"}));
    let rp = ResolvedProperty {
        cid: "blake3-512:abc".into(),
        ir_formula: Some(forall_n_gt_0()),
        ir_kit_version: "rust-kit@1.0".into(),
        ..Default::default()
    };
    let r = instantiate::run(&rp, &arg).expect("instantiate");
    assert_eq!(r.property_cid, "blake3-512:abc");
    assert_eq!(r.ir_kit_version, "rust-kit@1.0");
}

#[test]
fn specialized_precondition_substitutes_all_formals_with_call_actuals() {
    let formula = json!({
        "kind": "forall",
        "name": "self",
        "sort": {"kind": "primitive", "name": "Self"},
        "body": {
            "kind": "and",
            "operands": [
                {"kind": "atomic", "name": ">=", "args": [
                    {"kind": "var", "name": "radix"},
                    {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
                ]},
                {"kind": "atomic", "name": "<=", "args": [
                    {"kind": "var", "name": "radix"},
                    {"kind": "const", "value": 36, "sort": {"kind": "primitive", "name": "Int"}}
                ]}
            ]
        }
    });
    let rp = ResolvedProperty {
        cid: "blake3-512:to-digit".into(),
        ir_formula: Some(formula),
        formal_names: vec!["self".into(), "radix".into()],
        formal_sorts: vec![
            json!({"kind": "primitive", "name": "Self"}),
            json!({"kind": "primitive", "name": "Int"}),
        ],
        ..Default::default()
    };
    let actuals = vec![
        json!({"kind": "var", "name": "ch"}),
        json!({"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}}),
    ];
    let formal_actuals = json!({
        "self": actuals[0].clone(),
        "radix": actuals[1].clone()
    });
    let r = instantiate::run_specialized(&rp, &actuals, Some(&formal_actuals)).expect("specialize");
    assert_eq!(
        r.ir_formula,
        json!({
            "kind": "and",
            "operands": [
                {"kind": "atomic", "name": ">=", "args": [
                    {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}},
                    {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
                ]},
                {"kind": "atomic", "name": "<=", "args": [
                    {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}},
                    {"kind": "const", "value": 36, "sort": {"kind": "primitive", "name": "Int"}}
                ]}
            ]
        })
    );
}

#[test]
fn specialized_precondition_refuses_when_actual_count_does_not_cover_formals() {
    let formula = json!({
        "kind": "forall",
        "name": "self",
        "sort": {"kind": "primitive", "name": "Self"},
        "body": {"kind": "atomic", "name": ">=", "args": [
            {"kind": "var", "name": "radix"},
            {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
        ]}
    });
    let rp = ResolvedProperty {
        cid: "blake3-512:to-digit".into(),
        ir_formula: Some(formula),
        formal_names: vec!["self".into(), "radix".into()],
        ..Default::default()
    };
    let actuals = vec![json!({"kind": "var", "name": "ch"})];
    let err = instantiate::run_specialized(&rp, &actuals, None).expect_err("must fail closed");
    assert!(
        err.contains("formalActuals required for multi-formal precondition"),
        "expected a fail-closed arity error, got {err}"
    );
}

#[test]
fn specialized_precondition_binds_free_function_formals_by_name() {
    let formula = json!({
        "kind": "forall",
        "name": "lo",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {"kind": "atomic", "name": "<=", "args": [
            {"kind": "var", "name": "lo"},
            {"kind": "var", "name": "hi"}
        ]}
    });
    let rp = ResolvedProperty {
        cid: "blake3-512:range".into(),
        ir_formula: Some(formula),
        formal_names: vec!["lo".into(), "hi".into()],
        ..Default::default()
    };
    let actuals = vec![
        json!({"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}),
        json!({"kind": "const", "value": 9, "sort": {"kind": "primitive", "name": "Int"}}),
    ];
    let formal_actuals = json!({
        "hi": actuals[1].clone(),
        "lo": actuals[0].clone()
    });
    let r = instantiate::run_specialized(&rp, &actuals, Some(&formal_actuals))
        .expect("specialize free function by formal map");
    assert_eq!(
        r.ir_formula,
        json!({"kind": "atomic", "name": "<=", "args": [
            {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}},
            {"kind": "const", "value": 9, "sort": {"kind": "primitive", "name": "Int"}}
        ]})
    );
}

#[test]
fn specialized_precondition_binds_by_formal_actual_map_not_position() {
    let formula = json!({
        "kind": "forall",
        "name": "self",
        "sort": {"kind": "primitive", "name": "Self"},
        "body": {
            "kind": "atomic", "name": "<=", "args": [
                {"kind": "var", "name": "radix"},
                {"kind": "const", "value": 36, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let rp = ResolvedProperty {
        cid: "blake3-512:to-digit".into(),
        ir_formula: Some(formula),
        formal_names: vec!["self".into(), "radix".into()],
        ..Default::default()
    };
    let actuals = vec![
        json!({"kind": "var", "name": "receiver"}),
        json!({"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}}),
    ];
    let formal_actuals = json!({
        "radix": {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}},
        "self": {"kind": "var", "name": "receiver"}
    });
    let r = instantiate::run_specialized(&rp, &actuals, Some(&formal_actuals))
        .expect("specialize by explicit formal map");
    assert_eq!(
        r.ir_formula,
        json!({
            "kind": "atomic", "name": "<=", "args": [
                {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}},
                {"kind": "const", "value": 36, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        })
    );
}

#[test]
fn specialized_precondition_refuses_when_formal_actual_map_misses_guarded_formal() {
    let formula = json!({
        "kind": "forall",
        "name": "self",
        "sort": {"kind": "primitive", "name": "Self"},
        "body": {"kind": "atomic", "name": "<=", "args": [
            {"kind": "var", "name": "radix"},
            {"kind": "const", "value": 36, "sort": {"kind": "primitive", "name": "Int"}}
        ]}
    });
    let rp = ResolvedProperty {
        cid: "blake3-512:to-digit".into(),
        ir_formula: Some(formula),
        formal_names: vec!["self".into(), "radix".into()],
        ..Default::default()
    };
    let actuals = vec![json!({"kind": "var", "name": "receiver"})];
    let formal_actuals = json!({"self": {"kind": "var", "name": "receiver"}});
    let err = instantiate::run_specialized(&rp, &actuals, Some(&formal_actuals))
        .expect_err("missing guarded formal must fail closed");
    assert!(
        err.contains("formalActuals missing target formal `radix`"),
        "expected missing-formal failure, got {err}"
    );
}
