// SPDX-License-Identifier: Apache-2.0
//
//! Tests for the `libsugar::wp` evaluator (spec
//! `protocol/specs/2026-05-13-wp-as-formula.md`).
//!
//! Covered:
//!   - synthesized `wp` for value-ops `add` (`pre ∧ Q[result := lhs+rhs]`)
//!     and `div` (`not_zero(rhs) ∧ Q[result := lhs/rhs]`);
//!   - an authored Dijkstra-`if` `wp_rule`, instantiated correctly;
//!   - the evaluator on a small body term
//!     `seq(if(c, return(x), return(y)), skip)` for a postcondition `Q`,
//!     asserting the expected formula and that the result contains no
//!     `Substitute` / `Apply` nodes;
//!   - the loop / unresolved-call refusal paths;
//!   - `substitute` / `apply` round-trip + a pinned CID (byte-determinism).

use std::collections::HashMap;

use serde_json::json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_types::{IrFormula, IrTerm, Sort};

use crate::core::types::{Cid, Term};
use crate::wp::*;

// ============================================================
// A tiny in-memory resolver for the test op vocabulary.
// ============================================================

#[derive(Default)]
struct MapResolver(HashMap<String, OpContractInfo>);

impl MapResolver {
    fn with(mut self, name: &str, c: OpContractInfo) -> Self {
        self.0.insert(name.to_string(), c);
        self
    }
}

impl OpContractResolver for MapResolver {
    fn lookup(&self, op_name: &str) -> Option<OpContractInfo> {
        self.0.get(op_name).cloned()
    }
}

// ----- term / formula constructors -----

fn int_sort() -> Sort {
    Sort::Primitive {
        name: "Int".to_string(),
    }
}
fn t_var(n: &str) -> Term {
    Term::Var {
        name: n.to_string(),
    }
}
fn t_const(n: i64) -> Term {
    Term::Const {
        value: json!(n),
        sort: int_sort(),
    }
}
/// A `Term::Op` with a fixed sentinel op CID (the evaluator looks up by
/// name, not by CID, in this PR; the CID rides along on the term).
fn t_op(name: &str, args: Vec<Term>) -> Term {
    Term::Op {
        op_cid: sentinel_cid(),
        name: name.to_string(),
        args,
    }
}
fn sentinel_cid() -> Cid {
    Cid::parse(format!("blake3-512:{}", "0".repeat(128))).expect("sentinel cid is valid")
}
fn ir_var(n: &str) -> IrTerm {
    IrTerm::Var {
        name: n.to_string(),
    }
}
fn ir_const(n: i64) -> IrTerm {
    IrTerm::Const {
        value: json!(n),
        sort: int_sort(),
    }
}
fn op_term(name: &str, args: Vec<IrTerm>) -> IrTerm {
    IrTerm::Ctor {
        name: name.to_string(),
        args,
    }
}
fn atomic(name: &str, args: Vec<IrTerm>) -> IrFormula {
    IrFormula::Atomic {
        name: name.to_string(),
        args,
    }
}
fn prop(name: &str) -> IrFormula {
    atomic(name, vec![])
}
fn implies(a: IrFormula, b: IrFormula) -> IrFormula {
    IrFormula::Implies {
        operands: vec![a, b],
    }
}
fn not(a: IrFormula) -> IrFormula {
    IrFormula::Not { operands: vec![a] }
}
fn and(ops: Vec<IrFormula>) -> IrFormula {
    IrFormula::And { operands: ops }
}
fn apply(fn_name: &str, arg: IrFormula) -> IrFormula {
    IrFormula::Apply {
        args: vec![arg],
        r#fn: fn_name.to_string(),
    }
}
fn subst(target: IrFormula, var: &str, term: IrTerm) -> IrFormula {
    IrFormula::Substitute {
        target: Box::new(target),
        term,
        var: var.to_string(),
    }
}

// ----- op contracts used across the tests -----

/// `concept:add` — value-op, `pre = no_signed_overflow(add(lhs, rhs))`,
/// `post = (result == add(lhs, rhs))`. Synthesized rule.
fn add_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::value("lhs"), SlotInfo::value("rhs")]);
    c.pre = Some(atomic(
        "no_signed_overflow",
        vec![op_term("add", vec![ir_var("lhs"), ir_var("rhs")])],
    ));
    c.post = Some(atomic(
        "=",
        vec![
            ir_var("result"),
            op_term("add", vec![ir_var("lhs"), ir_var("rhs")]),
        ],
    ));
    c
}

/// `concept:div` — value-op, `pre = not_zero(rhs)`,
/// `post = (result == div(lhs, rhs))`. Synthesized rule.
fn div_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::value("lhs"), SlotInfo::value("rhs")]);
    c.pre = Some(atomic("not_zero", vec![ir_var("rhs")]));
    c.post = Some(atomic(
        "=",
        vec![
            ir_var("result"),
            op_term("div", vec![ir_var("lhs"), ir_var("rhs")]),
        ],
    ));
    c
}

/// `uop_neg` — value-op, `post = (result == neg(x))`.
fn neg_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::value("x")]);
    c.post = Some(atomic(
        "=",
        vec![ir_var("result"), op_term("neg", vec![ir_var("x")])],
    ));
    c
}

/// `bop_eq` — value-op, `post = (result == eq(lhs, rhs))`.
fn eq_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::value("lhs"), SlotInfo::value("rhs")]);
    c.post = Some(atomic(
        "=",
        vec![
            ir_var("result"),
            op_term("eq", vec![ir_var("lhs"), ir_var("rhs")]),
        ],
    ));
    c
}

/// `concept:if` / `concept:conditional` — control-flow, slot `cond`
/// value-typed, `then_branch` / `else_branch` `Stmt`-typed. Authored
/// `wp_rule` = the Dijkstra rule:
///   (cond ⇒ wp_then_branch(Q)) ∧ (¬cond ⇒ wp_else_branch(Q))
///
/// Note: the rule references its condition as the propositional var
/// `Atomic{name:"cond", args:[]}`. The `cond` *slot* is value-typed, so
/// the evaluator computes its value expression and substitutes it for the
/// *term-variable* `cond`; but `Atomic{name:"cond", args:[]}` carries no
/// term args, so term-substitution does not reach it — the rule's `cond`
/// propositional var stays as-is, which is the documented behavior (the
/// Dijkstra branch structure is preserved exactly; the condition's
/// identity is symbolic, correct for an opaque boolean).
fn if_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![
        SlotInfo::value("cond"),
        SlotInfo::stmt("then_branch"),
        SlotInfo::stmt("else_branch"),
    ]);
    c.wp_rule = Some(and(vec![
        implies(
            prop("cond"),
            apply("wp_then_branch", postcondition_placeholder()),
        ),
        implies(
            not(prop("cond")),
            apply("wp_else_branch", postcondition_placeholder()),
        ),
    ]));
    c
}

/// `concept:seq` — control-flow, slots `first` / `second` both
/// `Stmt`-typed. Authored `wp_rule` = `wp_first(wp_second(Q))`.
fn seq_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::stmt("first"), SlotInfo::stmt("second")]);
    c.wp_rule = Some(apply(
        "wp_first",
        apply("wp_second", postcondition_placeholder()),
    ));
    c
}

/// `concept:return` — control-flow, slot `value` value-typed. Authored
/// `wp_rule` = `Q[result := value]`. (Exercises the authored-rule path on
/// a control-flow op with no `Stmt` slots and a `substitute` node.)
fn return_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::value("value")]);
    c.wp_rule = Some(subst(
        postcondition_placeholder(),
        "result",
        ir_var("value"),
    ));
    c
}

/// `concept:skip` — control-flow, no slots. `wp_rule = Q`.
fn skip_contract() -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![]);
    c.wp_rule = Some(postcondition_placeholder());
    c
}

/// `concept:while` over a loop whose `LoopInvariantMemento` is *not* in
/// the pool: `wp` is not computable; the evaluator refuses naming the
/// loop CID.
fn opaque_while_contract(loop_cid: Cid) -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![SlotInfo::value("cond"), SlotInfo::stmt("body")]);
    c.opaque_loop = Some(loop_cid);
    c
}

/// An indirect / unresolved call whose callee contract has not landed.
fn opaque_call_contract(callee: &str) -> OpContractInfo {
    let mut c = OpContractInfo::new(vec![]);
    c.unresolved_call = Some(callee.to_string());
    c
}

fn base_resolver() -> MapResolver {
    MapResolver::default()
        .with("add", add_contract())
        .with("div", div_contract())
        .with("uop_neg", neg_contract())
        .with("bop_eq", eq_contract())
        .with("if", if_contract())
        .with("seq", seq_contract())
        .with("return", return_contract())
        .with("skip", skip_contract())
}

// ============================================================
// Synthesized value-op rules.
// ============================================================

#[test]
fn synthesizes_add_rule_pre_and_q_substituted() {
    // wp(add(a, b), Q) == no_signed_overflow(add(a, b)) ∧ Q[result := add(a, b)]
    let q = prop("Q_post"); // a propositional Q with no `result` var
    let term = t_op("add", vec![t_var("a"), t_var("b")]);
    let got = wp(&term, &q, &base_resolver()).expect("synthesized");

    let value_expr = op_term("add", vec![ir_var("a"), ir_var("b")]);
    let expected = and(vec![
        atomic("no_signed_overflow", vec![value_expr]),
        prop("Q_post"), // Q[result := add(a,b)] = Q_post (no `result` to replace)
    ]);
    assert_eq!(got, expected);
    assert!(!contains_schema_node(&got));
}

#[test]
fn synthesizes_add_rule_substitutes_into_a_q_that_mentions_result() {
    // wp(add(a, b), result < 100) == no_signed_overflow(add(a,b)) ∧ add(a,b) < 100
    let q = atomic("<", vec![ir_var("result"), ir_const(100)]);
    let term = t_op("add", vec![t_var("a"), t_var("b")]);
    let got = wp(&term, &q, &base_resolver()).expect("synthesized");

    let value_expr = op_term("add", vec![ir_var("a"), ir_var("b")]);
    let expected = and(vec![
        atomic("no_signed_overflow", vec![value_expr.clone()]),
        atomic("<", vec![value_expr, ir_const(100)]),
    ]);
    assert_eq!(got, expected);
}

#[test]
fn synthesizes_div_rule_not_zero_guard() {
    // wp(div(p, q), result == 7) == not_zero(q) ∧ div(p, q) == 7
    let post = atomic("=", vec![ir_var("result"), ir_const(7)]);
    let term = t_op("div", vec![t_var("p"), t_var("q")]);
    let got = wp(&term, &post, &base_resolver()).expect("synthesized");

    let value_expr = op_term("div", vec![ir_var("p"), ir_var("q")]);
    let expected = and(vec![
        atomic("not_zero", vec![ir_var("q")]),
        atomic("=", vec![value_expr, ir_const(7)]),
    ]);
    assert_eq!(got, expected);
}

#[test]
fn synthesize_value_rule_returns_the_substitute_schema_node() {
    // Before instantiation a synthesized value-op rule is literally
    // `pre ∧ substitute(Q, result, value_expr)` — the schema node is the
    // payload that gets reduced once Q is known.
    let rule = add_contract()
        .synthesize_value_rule()
        .expect("synthesizable");
    let expected = and(vec![
        atomic(
            "no_signed_overflow",
            vec![op_term("add", vec![ir_var("lhs"), ir_var("rhs")])],
        ),
        subst(
            postcondition_placeholder(),
            "result",
            op_term("add", vec![ir_var("lhs"), ir_var("rhs")]),
        ),
    ]);
    assert_eq!(rule, expected);
}

#[test]
fn no_rule_for_value_op_with_no_post() {
    let resolver =
        MapResolver::default().with("mystery", OpContractInfo::new(vec![SlotInfo::value("x")]));
    let term = t_op("mystery", vec![t_var("a")]);
    let err = wp(&term, &prop("Q"), &resolver).unwrap_err();
    assert!(matches!(err, WpError::NoRule { op } if op == "mystery"));
}

// ============================================================
// Authored control-flow rule: the Dijkstra `if`.
// ============================================================

#[test]
fn authored_if_rule_instantiated() {
    // wp( if(bop_eq(x,0), return(uop_neg(22)), return(x)),  result == out )
    //   = ( cond  ⇒ wp(return(uop_neg(22)), result==out) )
    //   ∧ ( ¬cond ⇒ wp(return(x),           result==out) )
    //   = ( cond  ⇒ neg(22) == out )
    //   ∧ ( ¬cond ⇒ x       == out )
    let q = atomic("=", vec![ir_var("result"), ir_var("out")]);
    let term = t_op(
        "if",
        vec![
            t_op("bop_eq", vec![t_var("x"), t_const(0)]),
            t_op("return", vec![t_op("uop_neg", vec![t_const(22)])]),
            t_op("return", vec![t_var("x")]),
        ],
    );
    let got = wp(&term, &q, &base_resolver()).expect("instantiated");
    let then_wp = atomic("=", vec![op_term("neg", vec![ir_const(22)]), ir_var("out")]);
    let else_wp = atomic("=", vec![ir_var("x"), ir_var("out")]);
    let expected = and(vec![
        implies(prop("cond"), then_wp),
        implies(not(prop("cond")), else_wp),
    ]);
    assert_eq!(got, expected);
    assert!(
        !contains_schema_node(&got),
        "no Substitute/Apply nodes remain after instantiation"
    );
}

#[test]
fn authored_if_rule_dijkstra_shape_with_propositional_branches() {
    // With both branches `return` of a bare variable, the two conjuncts
    // are `cond ⇒ Q[result := a]` and `¬cond ⇒ Q[result := b]`. With Q a
    // propositional `Q` (no `result`), each reduces to `Q`.
    let q = prop("Q");
    let term = t_op(
        "if",
        vec![
            t_op("bop_eq", vec![t_var("x"), t_const(0)]),
            t_op("return", vec![t_var("a")]),
            t_op("return", vec![t_var("b")]),
        ],
    );
    let got = wp(&term, &q, &base_resolver()).expect("instantiated");
    let expected = and(vec![
        implies(prop("cond"), prop("Q")),
        implies(not(prop("cond")), prop("Q")),
    ]);
    assert_eq!(got, expected);
}

// ============================================================
// The evaluator on a small body term.
// ============================================================

#[test]
fn evaluates_seq_if_return_skip_body() {
    // wp( seq(if(c, return(x), return(y)), skip),  result == out )
    //   = wp_first( wp_second(Q) )                          [seq rule]
    //   = wp( if(c, return(x), return(y)),  wp(skip, Q) )
    //   = wp( if(c, return(x), return(y)),  Q )             [skip: wp(skip,Q)=Q]
    //   = ( cond  ⇒ wp(return(x), Q) ) ∧ ( ¬cond ⇒ wp(return(y), Q) )   [if rule]
    //   = ( cond  ⇒ x == out ) ∧ ( ¬cond ⇒ y == out )
    let q = atomic("=", vec![ir_var("result"), ir_var("out")]);
    let term = t_op(
        "seq",
        vec![
            t_op(
                "if",
                vec![
                    t_op("bop_eq", vec![t_var("p"), t_const(0)]),
                    t_op("return", vec![t_var("x")]),
                    t_op("return", vec![t_var("y")]),
                ],
            ),
            t_op("skip", vec![]),
        ],
    );
    let got = wp(&term, &q, &base_resolver()).expect("evaluated");
    let expected = and(vec![
        implies(prop("cond"), atomic("=", vec![ir_var("x"), ir_var("out")])),
        implies(
            not(prop("cond")),
            atomic("=", vec![ir_var("y"), ir_var("out")]),
        ),
    ]);
    assert_eq!(got, expected);
    assert!(
        !contains_schema_node(&got),
        "no Substitute/Apply nodes remain"
    );
}

#[test]
fn wp_of_leaves() {
    let r = base_resolver();
    // wp(var v, Q) = Q[result := v]
    assert_eq!(
        wp(
            &t_var("v"),
            &atomic("=", vec![ir_var("result"), ir_const(3)]),
            &r
        )
        .unwrap(),
        atomic("=", vec![ir_var("v"), ir_const(3)])
    );
    // wp(const 5, Q) = Q[result := 5]
    assert_eq!(
        wp(
            &t_const(5),
            &atomic("<", vec![ir_var("result"), ir_const(9)]),
            &r
        )
        .unwrap(),
        atomic("<", vec![ir_const(5), ir_const(9)])
    );
    // wp(unit, Q) = Q
    assert_eq!(wp(&Term::Unit, &prop("Q"), &r).unwrap(), prop("Q"));
}

// ============================================================
// Refusal paths.
// ============================================================

#[test]
fn refuses_opaque_loop_naming_the_loop_cid() {
    let loop_cid = Cid::parse(format!("blake3-512:{}", "a".repeat(128))).unwrap();
    let resolver = base_resolver().with("while", opaque_while_contract(loop_cid.clone()));
    // A body that contains the opaque loop: seq( while(c, skip), skip ).
    let term = t_op(
        "seq",
        vec![
            t_op(
                "while",
                vec![
                    t_op("bop_eq", vec![t_var("i"), t_var("n")]),
                    t_op("skip", vec![]),
                ],
            ),
            t_op("skip", vec![]),
        ],
    );
    let err = wp(&term, &prop("Q"), &resolver).unwrap_err();
    match err {
        WpError::Refused(Refusal::OpaqueLoop { loop_cid: c }) => assert_eq!(c, loop_cid),
        other => panic!("expected OpaqueLoop refusal, got {other:?}"),
    }
}

#[test]
fn refuses_unresolved_call_naming_the_callee() {
    let resolver = base_resolver().with("indirect_call", opaque_call_contract("fn_ptr"));
    let term = t_op(
        "seq",
        vec![t_op("indirect_call", vec![]), t_op("skip", vec![])],
    );
    let err = wp(&term, &prop("Q"), &resolver).unwrap_err();
    match err {
        WpError::Refused(Refusal::OpaqueCall { callee }) => assert_eq!(callee, "fn_ptr"),
        other => panic!("expected OpaqueCall refusal, got {other:?}"),
    }
}

#[test]
fn refuses_unknown_op_as_unresolved_call() {
    let term = t_op("totally_unknown_op", vec![]);
    let err = wp(&term, &prop("Q"), &base_resolver()).unwrap_err();
    match err {
        WpError::Refused(Refusal::OpaqueCall { callee }) => {
            assert_eq!(callee, "totally_unknown_op")
        }
        other => panic!("expected OpaqueCall refusal, got {other:?}"),
    }
}

#[test]
fn malformed_rule_applying_a_non_slot_transformer() {
    let mut c = OpContractInfo::new(vec![SlotInfo::stmt("body")]);
    c.wp_rule = Some(apply("not_a_transformer", postcondition_placeholder()));
    let resolver = base_resolver().with("weird", c);
    let term = t_op("weird", vec![t_op("skip", vec![])]);
    let err = wp(&term, &prop("Q"), &resolver).unwrap_err();
    assert!(
        matches!(err, WpError::MalformedRule { op, fn_name } if op == "weird" && fn_name == "not_a_transformer")
    );
}

#[test]
fn malformed_rule_applying_a_transformer_for_a_missing_slot() {
    // The rule applies `wp_body`, but the op has no `body` Stmt slot.
    let mut c = OpContractInfo::new(vec![SlotInfo::stmt("only")]);
    c.wp_rule = Some(apply("wp_body", postcondition_placeholder()));
    let resolver = base_resolver().with("weird", c);
    let term = t_op("weird", vec![t_op("skip", vec![])]);
    let err = wp(&term, &prop("Q"), &resolver).unwrap_err();
    assert!(
        matches!(err, WpError::MalformedRule { op, fn_name } if op == "weird" && fn_name == "wp_body")
    );
}

#[test]
fn arity_mismatch_is_a_bug_not_a_refusal() {
    let resolver = base_resolver(); // `add` has 2 slots
    let term = t_op("add", vec![t_var("only_one")]);
    let err = wp(&term, &prop("Q"), &resolver).unwrap_err();
    assert!(matches!(err, WpError::ArityMismatch { op, expected: 2, actual: 1 } if op == "add"));
}

// ============================================================
// Schema-node round-trip + pinned CIDs (byte-determinism).
// ============================================================

/// Canonicalize an `IrFormula` to JCS bytes and return the
/// self-identifying BLAKE3-512 CID, the way the rest of the substrate
/// addresses formula bytes.
fn formula_cid(f: &IrFormula) -> String {
    let value: serde_json::Value = serde_json::to_value(f).expect("IrFormula serializes");
    let cv = serde_to_cvalue(value);
    blake3_512_of(encode_jcs(&cv).as_bytes())
}

fn serde_to_cvalue(j: serde_json::Value) -> std::sync::Arc<CValue> {
    match j {
        serde_json::Value::Null => CValue::null(),
        serde_json::Value::Bool(b) => CValue::boolean(b),
        serde_json::Value::Number(n) => match n.as_i64().map(i128::from).or_else(|| n.as_u64().map(i128::from)) {
            Some(i) => CValue::integer(i),
            None => CValue::object(vec![(
                "__sugar_non_i64_number__".to_string(),
                CValue::string(n.to_string()),
            )]),
        },
        serde_json::Value::String(s) => CValue::string(s),
        serde_json::Value::Array(items) => {
            CValue::array(items.into_iter().map(serde_to_cvalue).collect())
        }
        serde_json::Value::Object(map) => CValue::object(
            map.into_iter()
                .map(|(k, v)| (k, serde_to_cvalue(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

#[test]
fn substitute_node_round_trips_and_canonicalizes_deterministically() {
    let node = subst(
        postcondition_placeholder(),
        "result",
        op_term("add", vec![ir_var("lhs"), ir_var("rhs")]),
    );
    // serde round-trip
    let json = serde_json::to_string(&node).unwrap();
    let back: IrFormula = serde_json::from_str(&json).unwrap();
    assert_eq!(node, back);
    let v: serde_json::Value = serde_json::from_str(&json).unwrap();
    assert_eq!(v["kind"], "substitute");
    assert_eq!(v["var"], "result");
    assert!(v.get("target").is_some() && v.get("term").is_some());
    // Pinned CID — byte-determinism (Supra omnia rectum). If this changes,
    // the canonical encoding of a `substitute` node changed; that is a
    // CID-affecting edit and must be a deliberate, reviewed change.
    let cid = formula_cid(&node);
    assert_eq!(cid.len(), "blake3-512:".len() + 128);
    assert_eq!(cid, formula_cid(&node), "deterministic recompute");
    assert_eq!(
        cid, PINNED_SUBSTITUTE_NODE_CID,
        "pinned substitute-node CID; update only on a reviewed canonical-encoding change",
    );
}

#[test]
fn apply_node_round_trips_and_canonicalizes_deterministically() {
    let node = apply("wp_then_branch", postcondition_placeholder());
    let json = serde_json::to_string(&node).unwrap();
    let back: IrFormula = serde_json::from_str(&json).unwrap();
    assert_eq!(node, back);
    let v: serde_json::Value = serde_json::from_str(&json).unwrap();
    assert_eq!(v["kind"], "apply");
    assert_eq!(v["fn"], "wp_then_branch");
    assert!(v.get("args").is_some());
    let cid = formula_cid(&node);
    assert_eq!(cid, formula_cid(&node), "deterministic recompute");
    assert_eq!(
        cid, PINNED_APPLY_NODE_CID,
        "pinned apply-node CID; update only on a reviewed canonical-encoding change",
    );
}

// Pinned CIDs for the two new node kinds. These were computed by the
// canonicalizer (JCS + BLAKE3-512) on the canonical bytes of the exact
// node values built above; they pin the wire encoding of `substitute` /
// `apply` so any change to it surfaces as a deliberate, reviewed edit.
const PINNED_SUBSTITUTE_NODE_CID: &str =
    "blake3-512:1a48c69f0af6d3e560627a36d07e8b80d6a3457d97ca7fe71a557fe0b7300c7466957af4b8fdefe8a3c089fef0834882d190929cf4699fe71e8e2f11db622ee4";
const PINNED_APPLY_NODE_CID: &str =
    "blake3-512:e098642f2fdcc05ad1556a13fe0ff033426a8f04d26ca82f39a99d0d06cc831b8cc6c26a77e9f46f69a8794a8fec942e2a1545e2a7b15c99a2b10d434225a87d";

// ============================================================
// Compound-aware discharge tests (PR-F of #716).
// ============================================================

use crate::wp::{aggregate_conjunction, wp_compound, EvidenceVerdict};
use std::collections::BTreeMap;
use sugar_ir_types::{
    AggregationStrategy, CompoundContractMemento, EvidenceMemento, EvidenceRef, LossRecord,
    SourceKind, SourceLocator, SourceLocatorPoint, SourceLocatorSpan, VerdictKind,
};

/// Build a minimal `SourceLocator` for test fixtures.
fn test_locator() -> SourceLocator {
    SourceLocator {
        source_cid: "blake3-512:".to_string() + &"0".repeat(128),
        span: SourceLocatorSpan {
            start: SourceLocatorPoint { line: 1, col: 0 },
            end: SourceLocatorPoint { line: 1, col: 10 },
        },
    }
}

/// Build a minimal `EvidenceMemento` with the given CID and predicate.
fn make_evidence(cid: &str, predicate: IrFormula) -> EvidenceMemento {
    EvidenceMemento {
        cid: cid.to_string(),
        confidence_basis_points: 10000,
        extension_fields: BTreeMap::new(),
        kind: "evidence".to_string(),
        lifter_cid: "blake3-512:".to_string() + &"0".repeat(128),
        predicate,
        schema_version: "1".to_string(),
        source_kind: SourceKind::TypeSignature,
        source_locator: test_locator(),
    }
}

/// Build a minimal `CompoundContractMemento` with given strategy and evidence refs.
fn make_compound(
    cid: &str,
    strategy: AggregationStrategy,
    evidence_refs: Vec<EvidenceRef>,
) -> CompoundContractMemento {
    CompoundContractMemento {
        aggregation_strategy: strategy,
        cid: cid.to_string(),
        composed_post: prop("true"),
        composed_pre: prop("true"),
        evidences: evidence_refs,
        function_term_cid: "blake3-512:".to_string() + &"0".repeat(128),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    }
}

fn evidence_ref(cid: &str) -> EvidenceRef {
    EvidenceRef {
        evidence_cid: cid.to_string(),
        weight_basis_points: 10000,
    }
}

// ---- Test 1: degenerate compound (zero evidences) is vacuously exact ----

#[test]
fn wp_compound_empty_evidences_is_exact() {
    let compound = make_compound("cid-empty", AggregationStrategy::Conjunction, vec![]);
    let target = t_var("x");
    let report = wp_compound(&compound, &target, &[], &base_resolver())
        .expect("empty compound must succeed");

    assert_eq!(report.compound_cid, "cid-empty");
    assert_eq!(report.per_evidence_verdicts, vec![]);
    assert_eq!(report.compound_verdict, VerdictKind::Exact);
    assert!(
        report.composed_loss_record.0.is_empty(),
        "vacuous exact has no loss"
    );
}

// ---- Test 2: single exact evidence ----

#[test]
fn wp_compound_single_exact_evidence() {
    // wp(skip, Q) = Q; if evidence.predicate = Q, verdict is Exact.
    let q = prop("Q");
    let evidence = make_evidence("cid-e1", q.clone());
    let compound = make_compound(
        "cid-compound-1",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-e1")],
    );
    let target = t_op("skip", vec![]);

    let report =
        wp_compound(&compound, &target, &[evidence], &base_resolver()).expect("single exact");

    assert_eq!(report.compound_verdict, VerdictKind::Exact);
    assert_eq!(report.per_evidence_verdicts.len(), 1);
    assert_eq!(report.per_evidence_verdicts[0].verdict, VerdictKind::Exact);
    assert!(report.per_evidence_verdicts[0].loss_record.0.is_empty());
}

// ---- Test 3: all evidences exact → compound exact ----

#[test]
fn wp_compound_all_exact_yields_exact() {
    let q = prop("Q");
    let e1 = make_evidence("cid-e1", q.clone());
    let e2 = make_evidence("cid-e2", q.clone());
    let compound = make_compound(
        "cid-compound-all-exact",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-e1"), evidence_ref("cid-e2")],
    );
    let target = t_op("skip", vec![]);

    let report = wp_compound(&compound, &target, &[e1, e2], &base_resolver()).expect("all exact");

    assert_eq!(report.compound_verdict, VerdictKind::Exact);
    assert!(report
        .per_evidence_verdicts
        .iter()
        .all(|v| v.verdict == VerdictKind::Exact));
}

// ---- Test 4: one lossy evidence → compound loudly-bounded-lossy ----

#[test]
fn wp_compound_one_lossy_evidence_yields_lossy() {
    // Target: uop_neg(x).  neg_contract has no `pre`, post = (result == neg(x)).
    // wp(neg(x), Q_no_result_var) = Q  (Q[result := neg(x)] = Q when Q has no `result`)
    // wp(neg(x), result == 0)     = neg(x) == 0  (substitution fires, result differs)
    //
    // Evidence 1: predicate = Q (no result var)   → wp(neg(x), Q) = Q      → Exact.
    // Evidence 2: predicate = result == 0         → wp(neg(x), result==0) = neg(x)==0  → LoudlyBoundedLossy.
    let q = prop("Q"); // no `result` var
    let result_is_zero = atomic("=", vec![ir_var("result"), ir_const(0)]);

    let exact_ev = make_evidence("cid-exact", q.clone());
    let lossy_ev = make_evidence("cid-lossy", result_is_zero.clone());

    let compound = make_compound(
        "cid-compound-lossy",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-exact"), evidence_ref("cid-lossy")],
    );
    let target = t_op("uop_neg", vec![t_var("x")]);

    let report = wp_compound(&compound, &target, &[exact_ev, lossy_ev], &base_resolver())
        .expect("lossy compound");

    assert_eq!(report.compound_verdict, VerdictKind::LoudlyBoundedLossy);
    // composed loss record must contain the divergence key
    assert!(report
        .composed_loss_record
        .0
        .contains_key("structural_divergence"));
    // per-evidence: first is exact, second is lossy
    assert_eq!(report.per_evidence_verdicts[0].verdict, VerdictKind::Exact);
    assert_eq!(
        report.per_evidence_verdicts[1].verdict,
        VerdictKind::LoudlyBoundedLossy
    );
}

// ---- Test 5: one refuse evidence → compound refuse ----

#[test]
fn wp_compound_one_refuse_yields_compound_refuse() {
    // Use an opaque call evidence (wp returns Refused) and one exact evidence.
    let opaque_resolver = MapResolver::default()
        .with("add", add_contract())
        .with("div", div_contract())
        .with("uop_neg", neg_contract())
        .with("bop_eq", eq_contract())
        .with("if", if_contract())
        .with("seq", seq_contract())
        .with("return", return_contract())
        .with("skip", skip_contract())
        .with("opaque_call", opaque_call_contract("missing_fn"));

    let q = prop("Q");
    // This evidence's predicate will be evaluated via wp(opaque_call, Q).
    // wp will return Err(WpError::Refused(OpaqueCall{..})) → Refuse verdict.
    let opaque_target = t_op("opaque_call", vec![]);
    let refuse_ev = make_evidence("cid-refuse", q.clone());

    // Build compound with two evidences; use the opaque_call as the target.
    // Both evidences use the same predicate Q. But we need to show that when
    // wp returns Refused for the target term, a Refuse verdict is produced.
    //
    // Strategy: run wp_compound with the opaque target for a compound that
    // has one evidence whose predicate is Q.
    let compound = make_compound(
        "cid-compound-refuse",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-refuse")],
    );

    let report = wp_compound(&compound, &opaque_target, &[refuse_ev], &opaque_resolver)
        .expect("refuse compound result");

    assert_eq!(report.compound_verdict, VerdictKind::Refuse);
    assert!(
        report.composed_loss_record.0.is_empty(),
        "refuse has no loss"
    );
    assert_eq!(report.per_evidence_verdicts[0].verdict, VerdictKind::Refuse);
}

// ---- Test 6: any refuse dominates lossy under conjunction ----
//
// NOTE: wp_compound takes ONE target_term shared by all evidences. A Refuse
// verdict is triggered by the target itself (loop CID / opaque call), which
// means ALL evidences refuse together — you cannot get mixed Refuse+Lossy
// verdicts from a single wp_compound call. The correct way to test the
// "refuse dominates" aggregation rule is to call aggregate_conjunction
// directly with synthetic EvidenceVerdict slices.

#[test]
fn wp_compound_refuse_dominates_lossy() {
    // Synthesise one Refuse verdict and one LoudlyBoundedLossy verdict.
    let lossy_loss = {
        let mut m = BTreeMap::new();
        m.insert(
            "structural_divergence".to_string(),
            prop("divergence_formula"),
        );
        LossRecord(m)
    };

    let verdicts = vec![
        EvidenceVerdict {
            evidence_cid: "cid-lossy".to_string(),
            verdict: VerdictKind::LoudlyBoundedLossy,
            loss_record: lossy_loss.clone(),
        },
        EvidenceVerdict {
            evidence_cid: "cid-refuse".to_string(),
            verdict: VerdictKind::Refuse,
            loss_record: LossRecord(BTreeMap::new()),
        },
    ];

    let (compound_verdict, composed_loss) = aggregate_conjunction(&verdicts);

    // Refuse must dominate.
    assert_eq!(compound_verdict, VerdictKind::Refuse);
    // Refuse compound carries no loss record.
    assert!(composed_loss.0.is_empty(), "refuse has no loss");
}

// ---- Test 7: unimplemented strategy returns Err, not panic ----

#[test]
fn wp_compound_unimplemented_strategy_returns_err() {
    let compound = make_compound(
        "cid-best-confidence",
        AggregationStrategy::BestConfidence,
        vec![],
    );
    let target = t_var("x");
    let err = wp_compound(&compound, &target, &[], &base_resolver())
        .expect_err("BestConfidence must fail");
    assert!(
        matches!(err, WpError::UnimplementedAggregationStrategy { .. }),
        "expected UnimplementedAggregationStrategy, got {err:?}"
    );

    let compound2 = make_compound(
        "cid-lbd",
        AggregationStrategy::LoudlyBoundedDisjunction,
        vec![],
    );
    let err2 = wp_compound(&compound2, &target, &[], &base_resolver())
        .expect_err("LoudlyBoundedDisjunction must fail");
    assert!(
        matches!(err2, WpError::UnimplementedAggregationStrategy { .. }),
        "expected UnimplementedAggregationStrategy, got {err2:?}"
    );
}

// ---- Test 8: Other strategy returns Err ----

#[test]
fn wp_compound_other_strategy_returns_err() {
    let compound = make_compound(
        "cid-other",
        AggregationStrategy::Other("future-strategy-v2".to_string()),
        vec![],
    );
    let target = t_var("x");
    let err = wp_compound(&compound, &target, &[], &base_resolver())
        .expect_err("Other strategy must fail");
    match err {
        WpError::UnimplementedAggregationStrategy { strategy } => {
            assert_eq!(strategy, "future-strategy-v2");
        }
        other => panic!("expected UnimplementedAggregationStrategy, got {other:?}"),
    }
}

// ---- Test 9: determinism — same inputs produce identical reports ----

#[test]
fn wp_compound_is_deterministic() {
    let q = prop("Q");
    let e1 = make_evidence("cid-e1", q.clone());
    let e2 = make_evidence("cid-e2", q.clone());
    let compound = make_compound(
        "cid-determinism",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-e1"), evidence_ref("cid-e2")],
    );
    let target = t_op("skip", vec![]);

    let r1 = wp_compound(
        &compound,
        &target,
        &[e1.clone(), e2.clone()],
        &base_resolver(),
    )
    .expect("first run");
    let r2 = wp_compound(&compound, &target, &[e1, e2], &base_resolver()).expect("second run");

    assert_eq!(r1, r2, "wp_compound must be deterministic");
}

// ---- Test 10: multi-evidence with all-exact — compound_cid matches ----

#[test]
fn wp_compound_report_carries_compound_cid() {
    let q = prop("Q");
    let e1 = make_evidence("cid-e1", q.clone());
    let compound = make_compound(
        "the-compound-cid",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-e1")],
    );
    let target = t_op("skip", vec![]);

    let report = wp_compound(&compound, &target, &[e1], &base_resolver()).expect("report");

    assert_eq!(report.compound_cid, "the-compound-cid");
    assert_eq!(report.per_evidence_verdicts[0].evidence_cid, "cid-e1");
}

// ---- Test 11: two lossy evidences — loss records union, not LWW ----
//
// Regression for the LWW bug in aggregate_conjunction (Opus review #726):
// when two evidences both emit "structural_divergence", the last-write-wins
// `BTreeMap::insert` silently dropped the first formula. The fix unions them
// as `And { operands: [F1, F2] }`.
//
// Verification protocol: temporarily revert F1 (union) to LWW (plain insert)
// and this test MUST fail — only F2 survives, not F1.

#[test]
fn wp_compound_multiple_lossy_evidences_union_loss_records() {
    // uop_neg target. Two evidences with different predicates that both diverge
    // from wp(uop_neg(x), predicate):
    //   ev1: predicate = (result == 0)  → wp = (neg(x) == 0)  — diverges → F1 in loss
    //   ev2: predicate = (result == 1)  → wp = (neg(x) == 1)  — diverges → F2 in loss
    let result_is_zero = atomic("=", vec![ir_var("result"), ir_const(0)]);
    let result_is_one = atomic("=", vec![ir_var("result"), ir_const(1)]);

    let ev1 = make_evidence("cid-lossy-1", result_is_zero.clone());
    let ev2 = make_evidence("cid-lossy-2", result_is_one.clone());

    let compound = make_compound(
        "cid-compound-two-lossy",
        AggregationStrategy::Conjunction,
        vec![evidence_ref("cid-lossy-1"), evidence_ref("cid-lossy-2")],
    );
    let target = t_op("uop_neg", vec![t_var("x")]);

    let report =
        wp_compound(&compound, &target, &[ev1, ev2], &base_resolver()).expect("two-lossy compound");

    assert_eq!(report.compound_verdict, VerdictKind::LoudlyBoundedLossy);

    let structural = report
        .composed_loss_record
        .0
        .get("structural_divergence")
        .expect("structural_divergence dimension must be present");

    // Must be a conjunction of BOTH evidence formulas, not just the last one.
    match structural {
        IrFormula::And { operands } => {
            assert_eq!(
                operands.len(),
                2,
                "union must be And of two formulas, not LWW singleton"
            );
        }
        other => {
            panic!("expected IrFormula::And (union of two divergence formulas), got {other:?}")
        }
    }
}

// ============================================================
// Helpers.
// ============================================================

/// True iff the formula tree contains a `Substitute` or `Apply` node.
fn contains_schema_node(f: &IrFormula) -> bool {
    match f {
        IrFormula::Substitute { .. } | IrFormula::Apply { .. } => true,
        IrFormula::Atomic { .. } => false,
        IrFormula::And { operands }
        | IrFormula::Or { operands }
        | IrFormula::Not { operands }
        | IrFormula::Implies { operands } => operands.iter().any(contains_schema_node),
        IrFormula::Forall { body, .. }
        | IrFormula::Exists { body, .. }
        | IrFormula::Choice { body, .. } => contains_schema_node(body),
        IrFormula::DivergenceBetween { source, target } => {
            contains_schema_node(source) || contains_schema_node(target)
        }
    }
}
