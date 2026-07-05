// SPDX-License-Identifier: MIT OR Apache-2.0
//
// SMT emitter tests. Each formula kind translates to correct SMT-LIB,
// free-variable collection respects shadowing, bad inputs are rejected.

use serde_json::json;

use sugar_verifier::smt_emitter;

// ---------------------------------------------------------------------------
// Atomic predicates
// ---------------------------------------------------------------------------

#[test]
fn atomic_gt_translates_to_smt_lib() {
    let f = json!({
        "kind": "atomic",
        "name": ">",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(> x 0)"));
    assert!(s.contains("(declare-const x Int)"));
}

#[test]
fn atomic_lt_translates_to_smt_lib() {
    let f = json!({
        "kind": "atomic",
        "name": "<",
        "args": [
            {"kind": "var", "name": "y"},
            {"kind": "const", "value": 10, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(< y 10)"));
}

#[test]
fn atomic_eq_translates_to_smt_lib() {
    let f = json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(= a b)"));
}

#[test]
fn atomic_unicode_ne_translates_to_distinct() {
    let f = json!({
        "kind": "atomic",
        "name": "\u{2260}",  // ≠
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(distinct a b)"));
}

#[test]
fn atomic_unicode_le_translates_to_smt_le() {
    let f = json!({
        "kind": "atomic",
        "name": "\u{2264}",  // ≤
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(<= a b)"));
}

#[test]
fn atomic_unicode_ge_translates_to_smt_ge() {
    let f = json!({
        "kind": "atomic",
        "name": "\u{2265}",  // ≥
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(>= a b)"));
}

#[test]
fn bug_zoo_predicate_aliases_translate_to_smt_lib() {
    let f = json!({
        "kind": "implies",
        "operands": [
            {"kind": "atomic", "name": "eq", "args": [
                {"kind": "var", "name": "value"},
                {"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": "gte", "args": [
                {"kind": "var", "name": "value"},
                {"kind": "const", "value": 43, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(= value 42)"));
    assert!(s.contains("(>= value 43)"));
    assert!(
        !s.contains("(eq value 42)"),
        "`eq` is a ProofIR alias and must not be emitted as an uninterpreted SMT symbol"
    );
    assert!(
        !s.contains("(gte value 43)"),
        "`gte` is a ProofIR alias and must not be emitted as an uninterpreted SMT symbol"
    );
}

// ---------------------------------------------------------------------------
// Connectives
// ---------------------------------------------------------------------------

#[test]
fn connective_and_translates_to_smt_and() {
    let f = json!({
        "kind": "and",
        "operands": [
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": "<", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 10, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(and "));
    assert!(s.contains("(> x 0)"));
    assert!(s.contains("(< x 10)"));
}

#[test]
fn connective_or_translates_to_smt_or() {
    let f = json!({
        "kind": "or",
        "operands": [
            {"kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(or "));
}

#[test]
fn connective_not_translates_to_smt_not() {
    let f = json!({
        "kind": "not",
        "operands": [
            {"kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(not "));
    assert!(s.contains("(= x 0)"));
}

#[test]
fn connective_implies_translates_to_smt_arrow() {
    let f = json!({
        "kind": "implies",
        "operands": [
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": -1, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(=> "));
}

// ---------------------------------------------------------------------------
// Quantifiers
// ---------------------------------------------------------------------------

#[test]
fn forall_translates_to_smt_forall_with_bound_var() {
    let f = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(forall ((n Int)) (> n 0))"));
}

#[test]
fn exists_translates_to_smt_exists_with_bound_var() {
    let f = json!({
        "kind": "exists",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(exists ((n Int)) (= n 42))"));
}

#[test]
fn forall_real_sort_emits_real() {
    let f = json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "Real"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Real"}}
            ]
        }
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(forall ((x Real))"));
}

#[test]
fn forall_bool_sort_emits_bool() {
    let f = json!({
        "kind": "forall",
        "name": "p",
        "sort": {"kind": "primitive", "name": "Bool"},
        "body": {
            "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "p"},
                {"kind": "var", "name": "p"}
            ]
        }
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(forall ((p Bool))"));
}

// ---------------------------------------------------------------------------
// Free-variable collection (shadowing)
// ---------------------------------------------------------------------------

#[test]
fn free_var_under_quantifier_is_not_declared() {
    let f = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let s = smt_emitter::emit(&f).expect("emit");
    // `n` is bound; no free declaration of n.
    assert!(!s.contains("(declare-const n "));
}

#[test]
fn free_var_outside_quantifier_is_declared_at_top() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": "y"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(declare-const y Int)"));
}

#[test]
fn shadowing_quantifier_does_not_declare_outer_var() {
    // forall n. forall n. n > 0: inner n shadows; only one declare needed (none, since both bind).
    let f = json!({
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
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(!s.contains("(declare-const n "));
}

#[test]
fn multiple_free_vars_all_declared_sorted_by_name() {
    let f = json!({
        "kind": "and",
        "operands": [
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "z"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "a"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    let i_a = s.find("(declare-const a ").expect("a declared");
    let i_z = s.find("(declare-const z ").expect("z declared");
    assert!(i_a < i_z, "free vars must be declared in sorted order");
}

// ---------------------------------------------------------------------------
// Output structure
// ---------------------------------------------------------------------------

#[test]
fn emitted_script_starts_with_set_logic_all() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.starts_with("(set-logic ALL)"));
}

#[test]
fn emitted_script_asserts_negation_for_unsat_check() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.contains("(assert (not (> x 0)))"));
}

#[test]
fn emitted_script_ends_with_check_sat() {
    let f = json!({
        "kind": "atomic", "name": "=", "args": [
            {"kind": "var", "name": "x"},
            {"kind": "var", "name": "x"}
        ]
    });
    let s = smt_emitter::emit(&f).expect("emit");
    assert!(s.trim_end().ends_with("(check-sat)"));
}

// ---------------------------------------------------------------------------
// Bad inputs: fail-closed
// ---------------------------------------------------------------------------

#[test]
fn unknown_formula_kind_returns_err() {
    let f = json!({"kind": "boguskind", "operands": []});
    let r = smt_emitter::emit(&f);
    assert!(r.is_err());
}

#[test]
fn non_object_formula_returns_err() {
    let f = json!("not an object");
    let r = smt_emitter::emit(&f);
    assert!(r.is_err());
}

#[test]
fn atomic_without_args_returns_err() {
    let f = json!({"kind": "atomic", "name": ">"});
    let r = smt_emitter::emit(&f);
    assert!(r.is_err());
}

#[test]
fn unknown_term_kind_returns_err() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "boguskind", "name": "x"},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let r = smt_emitter::emit(&f);
    assert!(r.is_err());
}

#[test]
fn var_with_empty_name_returns_err() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": ""},
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let r = smt_emitter::emit(&f);
    assert!(r.is_err());
}

#[test]
fn quantifier_without_body_returns_err() {
    let f = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"}
        // no body
    });
    let r = smt_emitter::emit(&f);
    assert!(r.is_err());
}

#[test]
fn undeclared_predicate_gets_declare_fun() {
    // roundTrips is a kit-defined predicate, not standard SMT
    let f = json!({
        "kind": "forall",
        "name": "x",
        "sort": {"kind": "primitive", "name": "String"},
        "body": {
            "kind": "atomic",
            "name": "roundTrips",
            "args": [
                {"kind": "var", "name": "x"}
            ]
        }
    });
    let s = smt_emitter::emit(&f).expect("emit");
    println!("{}", s);
    // Should declare roundTrips as an uninterpreted function with String arg
    assert!(s.contains("roundTrips"), "missing roundTrips declaration");
    assert!(s.contains("String"), "missing String in declaration");
}
