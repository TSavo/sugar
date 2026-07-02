// SPDX-License-Identifier: Apache-2.0
//
// Loops and exceptions in the substrate.
//
// Paper 07's claim is that the substrate handles general control flow,
// not just linear sequences of let-bindings + callsites + flat
// if-statements. This module adds two extensions:
//
// 1. Loops (`while`, `for`, `loop`).
//    Without invariants, loops are tagged opaque per paper 07 §10's
//    `predicate_quantification` reason code. The substrate emits a
//    `LoopMemento` that records:
//       - pre_loop: WP demanded BEFORE the loop
//       - mutated_vars: the variable names the loop body modifies
//       - body_cid: CID of the body's shadow (unverified for now)
//       - opacity_reason: "predicate_quantification" or
//         "explicit_invariant" once invariant lifting lands
//    The post-loop state for any mutated variable is treated as a
//    fresh existential — the substrate flags this as a gap that an
//    invariant can fill later.
//
//    With invariants (provided as hand-written `assert!()` at loop
//    entry, or via dedicated annotations in a stretch iteration),
//    the loop emits three obligation edges:
//       (a) pre_loop → invariant            (entry preserves invariant)
//       (b) invariant ∧ cond → wp(body, invariant)  (preservation)
//       (c) invariant ∧ ¬cond → post_loop   (exit yields postcondition)
//    Each is a one-step implication, content-addressed and cached.
//
// 2. Exceptions: `Result<T, E>` matching, `?` operator, panics.
//    The `panic!()` case is already first-class (via if-then-panic
//    contraposition in lift.rs). This module adds:
//       - Match-arm postcondition splitting: a function whose body
//         ends in `match expr { Ok(v) => ok_body, Err(e) => err_body }`
//         has a postcondition that splits into Ok and Err disjuncts.
//       - `?` operator: at `expr?` the function may early-return Err,
//         so the post for the Err-path is "result = expr's_Err" and
//         the continuation's post assumes Ok.
//
// MVP scope: loop opacity-tagging + match-arm structural recognition.
// Invariant lifting and `?` operator handling are tagged for the next
// iteration.

use std::sync::Arc;

use sugar_canonicalizer::Value;
use sugar_ir_types::{IrFormula, IrTerm};
use syn::visit::{self, Visit};
use syn::{Block, Expr, ExprForLoop, ExprLoop, ExprWhile, ItemFn, Pat, Stmt};

use crate::canonical::{cid_of_value, formula_to_canonical, jcs_bytes_of_value};
use crate::lift::lift_expr_to_term;
use crate::wp::Wp;

// ---- Loop memento ----

/// One loop encountered in a function body. Carries the loop's
/// pre-state predicate, the variables it mutates (best-effort
/// extraction), and an opacity reason indicating whether soundness
/// was preserved by an explicit invariant or by tagging the loop's
/// effect as opaque.
#[derive(Debug, Clone)]
pub struct LoopMemento {
    pub fn_name: String,
    pub source_index: usize,
    pub kind: LoopKind,
    pub pre_loop: Wp,
    pub mutated_vars: Vec<String>,
    pub opacity_reason: String,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopKind {
    While,
    For,
    Unconditional,
}

impl LoopKind {
    fn label(&self) -> &'static str {
        match self {
            LoopKind::While => "while",
            LoopKind::For => "for",
            LoopKind::Unconditional => "loop",
        }
    }
}

/// Walk the function body and emit one LoopMemento per loop encountered.
/// pre_loop_default is the precondition the function entry already has;
/// it carries through to the loop's pre-state in this MVP.
pub fn extract_loop_mementos(item_fn: &ItemFn, pre_loop_default: &Wp) -> Vec<LoopMemento> {
    let fn_name = item_fn.sig.ident.to_string();
    let mut out = Vec::new();
    for (idx, stmt) in item_fn.block.stmts.iter().enumerate() {
        visit_stmt_for_loops(stmt, &fn_name, idx, pre_loop_default, &mut out);
    }
    out
}

fn visit_stmt_for_loops(
    stmt: &Stmt,
    fn_name: &str,
    source_index: usize,
    pre_loop: &Wp,
    out: &mut Vec<LoopMemento>,
) {
    match stmt {
        Stmt::Local(local) => {
            if let Some(init) = &local.init {
                visit_expr_for_loops(&init.expr, fn_name, source_index, pre_loop, out);
            }
        }
        Stmt::Expr(expr, _) => {
            visit_expr_for_loops(expr, fn_name, source_index, pre_loop, out);
        }
        Stmt::Macro(_) | Stmt::Item(_) => {}
    }
}

fn visit_expr_for_loops(
    expr: &Expr,
    fn_name: &str,
    source_index: usize,
    pre_loop: &Wp,
    out: &mut Vec<LoopMemento>,
) {
    let mut visitor = LoopMementoVisitor {
        fn_name,
        source_index,
        pre_loop,
        out,
    };
    visitor.visit_expr(expr);
}

struct LoopMementoVisitor<'a, 'out> {
    fn_name: &'a str,
    source_index: usize,
    pre_loop: &'a Wp,
    out: &'out mut Vec<LoopMemento>,
}

impl<'ast> Visit<'ast> for LoopMementoVisitor<'_, '_> {
    fn visit_expr_while(&mut self, node: &'ast ExprWhile) {
        self.out.push(mint_loop_memento(
            self.fn_name,
            self.source_index,
            LoopKind::While,
            self.pre_loop,
            collect_mutated_vars(&node.body),
            "predicate_quantification",
        ));
        visit::visit_expr_while(self, node);
    }

    fn visit_expr_for_loop(&mut self, node: &'ast ExprForLoop) {
        self.out.push(mint_loop_memento(
            self.fn_name,
            self.source_index,
            LoopKind::For,
            self.pre_loop,
            collect_mutated_vars(&node.body),
            "predicate_quantification",
        ));
        visit::visit_expr_for_loop(self, node);
    }

    fn visit_expr_loop(&mut self, node: &'ast ExprLoop) {
        self.out.push(mint_loop_memento(
            self.fn_name,
            self.source_index,
            LoopKind::Unconditional,
            self.pre_loop,
            collect_mutated_vars(&node.body),
            "predicate_quantification",
        ));
        visit::visit_expr_loop(self, node);
    }
}

/// Best-effort: walk the loop body and collect names of variables that
/// appear on the LHS of an assignment (a = ..., a += ..., etc.). This
/// is the set of "mutated" variables whose post-loop state is opaque.
fn collect_mutated_vars(body: &Block) -> Vec<String> {
    let mut names = Vec::new();
    for stmt in &body.stmts {
        collect_mutated_in_stmt(stmt, &mut names);
    }
    names.sort();
    names.dedup();
    names
}

fn collect_mutated_in_stmt(stmt: &Stmt, names: &mut Vec<String>) {
    if let Stmt::Expr(e, _) = stmt {
        collect_mutated_in_expr(e, names);
    }
}

fn collect_mutated_in_expr(expr: &Expr, names: &mut Vec<String>) {
    match expr {
        Expr::Assign(a) => {
            if let Expr::Path(p) = a.left.as_ref() {
                if let Some(seg) = p.path.segments.last() {
                    names.push(seg.ident.to_string());
                }
            }
        }
        Expr::Binary(b) => {
            collect_mutated_in_expr(&b.left, names);
            collect_mutated_in_expr(&b.right, names);
        }
        Expr::Block(b) => {
            for s in &b.block.stmts {
                collect_mutated_in_stmt(s, names);
            }
        }
        Expr::If(i) => {
            for s in &i.then_branch.stmts {
                collect_mutated_in_stmt(s, names);
            }
            if let Some((_, else_e)) = &i.else_branch {
                collect_mutated_in_expr(else_e, names);
            }
        }
        _ => {}
    }
}

fn mint_loop_memento(
    fn_name: &str,
    source_index: usize,
    kind: LoopKind,
    pre_loop: &Wp,
    mutated_vars: Vec<String>,
    opacity_reason: &str,
) -> LoopMemento {
    let mutated_values: Vec<Arc<Value>> = mutated_vars
        .iter()
        .map(|n| Value::string(n.clone()))
        .collect();
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("loop")),
        ("fnName", Value::string(fn_name.to_string())),
        ("sourceIndex", Value::integer(source_index as i128)),
        ("loopKind", Value::string(kind.label())),
        ("preLoop", formula_to_canonical(pre_loop.as_formula())),
        ("mutatedVars", Value::array(mutated_values)),
        ("opacityReason", Value::string(opacity_reason.to_string())),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);
    LoopMemento {
        fn_name: fn_name.to_string(),
        source_index,
        kind,
        pre_loop: pre_loop.clone(),
        mutated_vars,
        opacity_reason: opacity_reason.to_string(),
        canonical_bytes,
        cid,
    }
}

// ---- Match-arm postcondition splitting ----

/// One match arm's lifted postcondition. Used when a function body
/// ends in a `match` expression: the function's overall post is the
/// disjunction of arm posts (each guarded by the arm's pattern shape).
#[derive(Debug, Clone)]
pub struct ArmPost {
    pub pattern_label: String,
    pub post: IrFormula,
}

/// Lift a match-arm split from the function body's trailing match
/// expression. Returns one ArmPost per arm. If the body does not end
/// in a match (or the match shape isn't recognized), returns an empty
/// vector.
pub fn lift_match_arm_postconditions(item_fn: &ItemFn) -> Vec<ArmPost> {
    let last = match item_fn.block.stmts.last() {
        Some(Stmt::Expr(Expr::Match(m), _)) => m,
        _ => return Vec::new(),
    };
    let mut out = Vec::with_capacity(last.arms.len());
    for arm in &last.arms {
        let pattern_label = pattern_to_label(&arm.pat);
        let post = arm_body_post(&arm.body);
        out.push(ArmPost {
            pattern_label,
            post,
        });
    }
    out
}

fn pattern_to_label(pat: &Pat) -> String {
    use quote::ToTokens;
    pat.to_token_stream().to_string()
}

/// For an arm body that's a single expression, derive `result = <expr>`
/// as the arm's postcondition. For more complex bodies the MVP returns
/// `true` (vacuous).
fn arm_body_post(body: &Expr) -> IrFormula {
    if let Some(term) = lift_expr_to_term(body) {
        return IrFormula::Atomic {
            name: "=".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "result".to_string(),
                },
                term,
            ],
        };
    }
    IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_fn(src: &str) -> ItemFn {
        let file: syn::File = syn::parse_str(src).unwrap();
        file.items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) => Some(f),
                _ => None,
            })
            .unwrap()
    }

    #[test]
    fn while_loop_emits_opaque_memento_with_mutated_vars() {
        let item_fn = parse_fn(
            r#"
            fn count_to(n: u32) -> u32 {
                let mut i: u32 = 0;
                let mut sum: u32 = 0;
                while i < n {
                    sum = sum + i;
                    i = i + 1;
                }
                sum
            }
        "#,
        );
        let pre = Wp(IrFormula::Atomic {
            name: "true".to_string(),
            args: vec![],
        });
        let mementos = extract_loop_mementos(&item_fn, &pre);
        assert_eq!(mementos.len(), 1);
        let m = &mementos[0];
        assert_eq!(m.kind, LoopKind::While);
        assert!(m.cid.starts_with("blake3-512:"));
        assert_eq!(m.cid.len(), 139);
        assert_eq!(m.opacity_reason, "predicate_quantification");
        // Mutated variables: i and sum (both assigned in the body).
        assert!(m.mutated_vars.iter().any(|v| v == "i"));
        assert!(m.mutated_vars.iter().any(|v| v == "sum"));
    }

    #[test]
    fn for_loop_emits_memento() {
        let item_fn = parse_fn(
            r#"
            fn iterate(items: u32) -> u32 {
                let mut total: u32 = 0;
                for x in 0..items {
                    total = total + x;
                }
                total
            }
        "#,
        );
        let pre = Wp(IrFormula::Atomic {
            name: "true".to_string(),
            args: vec![],
        });
        let mementos = extract_loop_mementos(&item_fn, &pre);
        assert_eq!(mementos.len(), 1);
        assert_eq!(mementos[0].kind, LoopKind::For);
    }

    #[test]
    fn match_arm_loop_emits_memento() {
        let item_fn = parse_fn(
            r#"
            fn branch_loop(flag: bool, n: u32) {
                match flag {
                    true => while n > 0 {},
                    false => {},
                }
            }
        "#,
        );
        let pre = Wp(IrFormula::Atomic {
            name: "true".to_string(),
            args: vec![],
        });
        let mementos = extract_loop_mementos(&item_fn, &pre);
        assert_eq!(
            mementos.len(),
            1,
            "loop inside a match arm must not be silently dropped"
        );
        assert_eq!(mementos[0].kind, LoopKind::While);
    }

    #[test]
    fn match_arms_yield_per_arm_postconditions() {
        let item_fn = parse_fn(
            r#"
            fn classify(x: u32) -> u32 {
                match x {
                    0 => 100,
                    1 => 200,
                    _ => x,
                }
            }
        "#,
        );
        let arms = lift_match_arm_postconditions(&item_fn);
        assert_eq!(arms.len(), 3);
        // The first arm `0 => 100` yields `result = 100`.
        let first_post_json = serde_json::to_string(&arms[0].post).unwrap();
        assert!(
            first_post_json.contains("\"result\"") && first_post_json.contains("100"),
            "expected first arm to produce `result = 100`: {}",
            first_post_json
        );
    }

    #[test]
    fn loop_cids_deterministic_and_distinct_per_kind() {
        let while_fn = parse_fn(
            r#"
            fn a() { let mut i: u32 = 0; while i < 10 { i = i + 1; } }
        "#,
        );
        let for_fn = parse_fn(
            r#"
            fn b() { let mut s: u32 = 0; for x in 0..10 { s = s + x; } }
        "#,
        );
        let pre = Wp(IrFormula::Atomic {
            name: "true".to_string(),
            args: vec![],
        });
        let m_a = extract_loop_mementos(&while_fn, &pre).remove(0);
        let m_b = extract_loop_mementos(&for_fn, &pre).remove(0);
        let m_a2 = extract_loop_mementos(&while_fn, &pre).remove(0);

        assert_eq!(m_a.cid, m_a2.cid, "deterministic across runs");
        assert_ne!(m_a.cid, m_b.cid, "distinct kinds yield distinct CIDs");
    }
}
