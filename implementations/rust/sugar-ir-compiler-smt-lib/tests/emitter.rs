// SPDX-License-Identifier: Apache-2.0
//
// SMT-LIB v2.6 emitter tests. Each formula kind translates correctly,
// free-variable collection respects shadowing, bad inputs are
// rejected. Moved here from sugar-verifier/tests/smt_emitter.rs as
// part of the IR compiler protocol extraction.

use serde_json::json;

use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT};

fn emit(ir: &serde_json::Value) -> Result<String, String> {
    let input = CompilerInput::decode_json(ir.clone()).map_err(|error| error.to_string())?;
    SmtLibCompiler::new()
        .compile_typed(&input, DIALECT)
        .map(|compiled| compiled.script())
        .map_err(|error| error.to_string())
}

// ---------------------------------------------------------------------------
// Atomic predicates
// ---------------------------------------------------------------------------

#[test]
fn atomic_gt_translates_to_smt_lib() {
    let f = json!({
        "kind": "atomic", "name": ">",
        "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(> x 0)"));
    assert!(s.contains("(declare-const x Int)"));
}

#[test]
fn atomic_lt_translates_to_smt_lib() {
    let f = json!({
        "kind": "atomic", "name": "<",
        "args": [
            {"kind": "var", "name": "y"},
            {"kind": "const", "value": 10,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(< y 10)"));
}

#[test]
fn atomic_eq_translates_to_smt_lib() {
    let f = json!({
        "kind": "atomic", "name": "=",
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(= a b)"));
}

#[test]
fn atomic_unicode_ne_translates_to_distinct() {
    let f = json!({
        "kind": "atomic", "name": "\u{2260}",
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(distinct a b)"));
}

#[test]
fn atomic_unicode_le_translates_to_smt_le() {
    let f = json!({
        "kind": "atomic", "name": "\u{2264}",
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(<= a b)"));
}

#[test]
fn atomic_unicode_ge_translates_to_smt_ge() {
    let f = json!({
        "kind": "atomic", "name": "\u{2265}",
        "args": [
            {"kind": "var", "name": "a"},
            {"kind": "var", "name": "b"}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(>= a b)"));
}

// ---------------------------------------------------------------------------
// Strong string-theory atoms: malformed means refuse, not generic fallback
// ---------------------------------------------------------------------------

#[test]
fn malformed_bv_blocks_refuses() {
    let f = json!({
        "kind": "atomic",
        "name": "str.eq-bv-blocks",
        "args": [
            {"kind": "var", "name": "out"},
            {"kind": "const", "value": "not json",
             "sort": {"kind": "primitive", "name": "String"}}
        ]
    });
    let err = emit(&f).expect_err("malformed str.eq-bv-blocks must refuse loudly");
    assert!(err.contains("str.eq-bv-blocks"), "{err}");
    assert!(err.contains("malformed"), "{err}");
    assert!(err.contains("refusing rather than weakening"), "{err}");
}

#[test]
fn non_regular_regex_refuses_by_name() {
    let f = json!({
        "kind": "atomic",
        "name": "str.in-regex",
        "args": [
            {"kind": "var", "name": "subject"},
            {"kind": "const", "value": "foo(?=bar)",
             "sort": {"kind": "primitive", "name": "String"}}
        ]
    });
    let err = emit(&f).expect_err("non-regular str.in-regex must refuse loudly");
    assert!(err.contains("str.in-regex"), "{err}");
    assert!(err.contains("lookahead"), "{err}");
    assert!(err.contains("refusing rather than weakening"), "{err}");
}

#[test]
fn generic_atoms_still_pass_through() {
    let f = json!({
        "kind": "atomic",
        "name": "domain.opaque",
        "args": [
            {"kind": "var", "name": "x"}
        ]
    });
    let s = emit(&f).expect("generic domain predicate should still emit");
    assert!(
        s.contains("(declare-fun domain.opaque (Int) Bool)"),
        "generic predicate declaration missing:\n{s}"
    );
    assert!(
        s.contains("(domain.opaque x)"),
        "generic predicate application missing:\n{s}"
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
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": "<", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 10,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = emit(&f).expect("emit");
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
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 1,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(or "));
}

#[test]
fn connective_not_translates_to_smt_not() {
    let f = json!({
        "kind": "not",
        "operands": [
            {"kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = emit(&f).expect("emit");
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
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": -1,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(=> "));
}

// ---------------------------------------------------------------------------
// Quantifiers
// ---------------------------------------------------------------------------

#[test]
fn forall_translates_to_smt_forall_with_bound_var() {
    let f = json!({
        "kind": "forall", "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(forall ((n Int)) (> n 0))"));
}

#[test]
fn exists_translates_to_smt_exists_with_bound_var() {
    let f = json!({
        "kind": "exists", "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 42,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(exists ((n Int)) (= n 42))"));
}

#[test]
fn forall_real_sort_emits_real() {
    let f = json!({
        "kind": "forall", "name": "x",
        "sort": {"kind": "primitive", "name": "Real"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "x"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Real"}}
            ]
        }
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(forall ((x Real))"));
}

#[test]
fn forall_bool_sort_emits_bool() {
    let f = json!({
        "kind": "forall", "name": "p",
        "sort": {"kind": "primitive", "name": "Bool"},
        "body": {
            "kind": "atomic", "name": "=", "args": [
                {"kind": "var", "name": "p"},
                {"kind": "var", "name": "p"}
            ]
        }
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(forall ((p Bool))"));
}

// ---------------------------------------------------------------------------
// Free-variable collection (shadowing)
// ---------------------------------------------------------------------------

#[test]
fn free_var_under_quantifier_is_not_declared() {
    let f = json!({
        "kind": "forall", "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let s = emit(&f).expect("emit");
    assert!(!s.contains("(declare-const n "));
}

#[test]
fn free_var_outside_quantifier_is_declared_at_top() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": "y"},
            {"kind": "const", "value": 0,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(declare-const y Int)"));
}

#[test]
fn shadowing_quantifier_does_not_declare_outer_var() {
    let f = json!({
        "kind": "forall", "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "forall", "name": "n",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": {
                "kind": "atomic", "name": ">", "args": [
                    {"kind": "var", "name": "n"},
                    {"kind": "const", "value": 0,
                     "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }
    });
    let s = emit(&f).expect("emit");
    assert!(!s.contains("(declare-const n "));
}

#[test]
fn multiple_free_vars_all_declared_sorted_by_name() {
    let f = json!({
        "kind": "and",
        "operands": [
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "z"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]},
            {"kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "a"},
                {"kind": "const", "value": 0,
                 "sort": {"kind": "primitive", "name": "Int"}}
            ]}
        ]
    });
    let s = emit(&f).expect("emit");
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
            {"kind": "const", "value": 0,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = emit(&f).expect("emit");
    assert!(s.starts_with("(set-logic ALL)"));
}

#[test]
fn emitted_script_asserts_negation_for_unsat_check() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": "x"},
            {"kind": "const", "value": 0,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    let s = emit(&f).expect("emit");
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
    let s = emit(&f).expect("emit");
    assert!(s.trim_end().ends_with("(check-sat)"));
}

// ---------------------------------------------------------------------------
// Bad inputs: fail-closed
// ---------------------------------------------------------------------------

#[test]
fn unknown_formula_kind_returns_err() {
    let f = json!({"kind": "boguskind", "operands": []});
    assert!(emit(&f).is_err());
}

#[test]
fn non_object_formula_returns_err() {
    let f = json!("not an object");
    assert!(emit(&f).is_err());
}

#[test]
fn atomic_without_args_returns_err() {
    let f = json!({"kind": "atomic", "name": ">"});
    assert!(emit(&f).is_err());
}

#[test]
fn unknown_term_kind_returns_err() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "boguskind", "name": "x"},
            {"kind": "const", "value": 0,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    assert!(emit(&f).is_err());
}

#[test]
fn var_with_empty_name_returns_err() {
    let f = json!({
        "kind": "atomic", "name": ">", "args": [
            {"kind": "var", "name": ""},
            {"kind": "const", "value": 0,
             "sort": {"kind": "primitive", "name": "Int"}}
        ]
    });
    // PR #39 added structural validation: empty var names are malformed
    // IR (SMT-LIB rejects empty symbols, every host-language lifter
    // refuses empty identifiers). The function name was correct; the
    // prior assertion documented the bug instead of catching it.
    assert!(emit(&f).is_err());
}

#[test]
fn quantifier_without_body_returns_err() {
    let f = json!({
        "kind": "forall", "name": "n",
        "sort": {"kind": "primitive", "name": "Int"}
    });
    assert!(emit(&f).is_err());
}

// ---------------------------------------------------------------------------
// Lambda terms
// ---------------------------------------------------------------------------

#[test]
fn lambda_emits_smt_lib_lambda() {
    let f = json!({
        "kind": "lambda",
        "paramName": "x",
        "paramSort": {"kind": "primitive", "name": "Int"},
        "body": {"kind": "const", "value": 42, "sort": {"kind": "primitive", "name": "Int"}}
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(lambda"));
    assert!(s.contains("x"));
    assert!(s.contains("42"));
}

// ---------------------------------------------------------------------------
// Let terms
// ---------------------------------------------------------------------------

#[test]
fn let_emits_smt_lib_let() {
    let f = json!({
        "kind": "let",
        "bindings": [
            {"name": "x", "boundTerm": {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}}
        ],
        "body": {"kind": "var", "name": "x"}
    });
    let s = emit(&f).expect("emit");
    assert!(s.contains("(let"));
    assert!(s.contains("(x 1)"));
    assert!(s.contains("x"));
}

// ---------------------------------------------------------------------------
// Choice formulas
// ---------------------------------------------------------------------------

#[test]
fn choice_emits_exists_with_uniqueness() {
    let f = json!({
        "kind": "choice",
        "varName": "x",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {"kind": "atomic", "name": "true", "args": []}
    });
    let s = emit(&f).expect("emit");
    // Choice encodes as: exists x. body ∧ (forall y. body[y/x] => y = x)
    assert!(s.contains("(exists"));
    assert!(s.contains("(and"));
    assert!(s.contains("(forall"));
}
