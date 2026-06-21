// SPDX-License-Identifier: Apache-2.0
//
// `ScanSugar`: `.scan(init, |acc, x| { *acc <op>= rhs_expr; Some(*acc) })` over a
// FINITE LITERAL source — the stateful-map adaptor collapsed to a concrete integer
// `Desugared::Seq` so downstream iterator terminals (`sum`, `last`, `count`, `fold`,
// etc.) can operate on the grounded sequence with full z3 teeth.
//
// RECOGNITION SCOPE: the closure body must follow the canonical scan pattern:
// one `*acc <compound-assign-op> rhs_expr` mutation statement on the state param,
// followed by a `Some(*acc)` tail (yielding the updated state). Only a FINITE
// LITERAL receiver is accepted (the same gate as `IterTerminalSugar`/`FoldSugar`).
// Empty source → empty Seq (downstream terminals handle it correctly: `.last()`
// returns `None`, `.sum()` returns 0, etc.).
//
// Out of scope today: closures that reference `*acc` inside `rhs_expr` (where the
// rhs depends on both state and item simultaneously in an expression — the state is
// in env so simple forms like `*acc * x` DO work via `const_fold_acc_update`),
// non-integer state types, and `None`-returning (early-stop) closures. Any shape
// outside the supported set falls through to the opaque `method:` ctor (the
// established sound under-claim).
//
// REGISTERED AS: not in the catalog directly; recognized and constructed by
// `iter_terminal::try_build_scan_inner` as a pre-pass in that recognizer, so the
// full chain `source.scan(init, closure).terminal()` grounds with teeth.

use std::collections::BTreeMap;

use syn::{BinOp, Expr, Stmt, UnOp};

use crate::sugar::factory::SugarBuildCtx;
use crate::{
    closure_single_param_ident, const_fold_acc_update, const_int_acc_init, strip_refs_groups,
    ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx,
};

/// A parsed scan closure body: the compound-assign mutation and the fact that the
/// tail yields `*state_var` (so the yielded value = new state after the mutation).
struct ScanBody {
    /// The `<compound-assign-op>` in `*state_var <op>= rhs_expr`.
    assign_op: BinOp,
    /// The right-hand side of the compound assign. Const-evaluated at desugar
    /// time with the STATE VAR and ITEM VAR both bound (so `rhs_expr` may
    /// reference either).
    rhs: Expr,
}

/// Try to build a `ScanSugar` from a scan-call receiver expression. Returns `None`
/// if the expression is not a `.scan(init, closure)` call, if the scan's receiver
/// is not a finite literal-sequence composite, or if the closure body does not
/// match the supported `{ *acc <op>= rhs; Some(*acc) }` pattern. Called from
/// `iter_terminal::recognize` as a pre-pass before the standard peel path.
pub(crate) fn try_build_scan_inner(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method != "scan" || call.args.len() != 2 {
        return None;
    }
    // The scan's own receiver must bottom out in a finite literal sequence.
    let inner = crate::sugar::method_family::build_literal_sequence_composite(&call.receiver, fcx)?;
    // init: the initial state value (a const integer -- the same regime as fold's acc init).
    let init = const_int_acc_init(&call.args[0], fcx.let_inits())?;
    // Closure: |acc, x| { *acc <op>= rhs; Some(*acc) }
    let Expr::Closure(closure) = strip_refs_groups(&call.args[1]) else {
        return None;
    };
    if closure.inputs.len() != 2 {
        return None;
    }
    let state_var = closure_single_param_ident(&closure.inputs[0])?;
    let item_var = closure_single_param_ident(&closure.inputs[1])?;
    let body = parse_scan_body(&closure.body, &state_var)?;
    Some(Box::new(ScanSugar {
        inner,
        init,
        state_var,
        item_var,
        body,
    }))
}

/// A stateful-map adaptor over a finite literal source. Threads an integer
/// accumulator through each element and yields each updated state as a concrete
/// integer `DesugaredElem`. Produces `Desugared::Seq` so all downstream terminals
/// can operate on the grounded values with z3 teeth.
struct ScanSugar {
    inner: Box<dyn Sugar>,
    init: i64,
    state_var: String,
    item_var: String,
    body: ScanBody,
}

impl Sugar for ScanSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut state = self.init;
            let mut out: Vec<DesugaredElem> = Vec::with_capacity(seq.len());
            for elem in &seq {
                let item_val = elem
                    .value
                    .as_ref()
                    .and_then(ConstVal::as_int)
                    .and_then(|n| i64::try_from(n).ok())?;
                // Evaluate the rhs expression with BOTH state_var and item_var bound
                // so that expressions like `*acc * x` or `*acc + x` const-fold correctly.
                let mut env: BTreeMap<String, i64> = BTreeMap::new();
                env.insert(self.state_var.clone(), state);
                env.insert(self.item_var.clone(), item_val);
                let rhs_val = const_fold_acc_update(&self.body.rhs, &env)?;
                // Apply the compound-assign op to get the new state.
                state = apply_assign_op(&self.body.assign_op, state, rhs_val)?;
                // Synthesize a literal int expression so `translate_term_in_scope`
                // can ground it when the downstream terminal substitutes elements.
                let expr: Expr = syn::parse_str(&state.to_string())
                    .expect("i64 always parses as a Rust integer literal");
                out.push(DesugaredElem {
                    expr,
                    value: Some(ConstVal::Int(i128::from(state))),
                });
            }
            Some(Desugared::Seq(out))
        })())
    }
}

/// Parse the closure body `{ *state_var <op>= rhs; Some(*state_var) }`.
/// Returns `None` for any unsupported body shape (no mutations, wrong tail, etc.).
fn parse_scan_body(body: &Expr, state_var: &str) -> Option<ScanBody> {
    // Must be a block body (the canonical scan closure is always a block).
    let Expr::Block(block) = body else {
        return None;
    };
    let stmts = &block.block.stmts;
    // Need exactly: [compound_assign_stmt, Some(*state_var) tail]
    let (tail_stmt, update_stmts) = stmts.split_last()?;
    if update_stmts.len() != 1 {
        return None;
    }
    // Tail: `Some(*state_var)` with NO trailing semicolon (it IS the return value).
    let Stmt::Expr(tail_expr, None) = tail_stmt else {
        return None;
    };
    if !is_some_of_deref_state(tail_expr, state_var) {
        return None;
    }
    // Update: `*state_var <op>= rhs_expr;` (expression statement WITH semicolon).
    let Stmt::Expr(update_expr, Some(_)) = &update_stmts[0] else {
        return None;
    };
    let Expr::Binary(binary) = update_expr else {
        return None;
    };
    if !is_compound_assign_op(&binary.op) {
        return None;
    }
    // LHS must be `*state_var` (dereference of the mutable-ref state param).
    if !is_deref_of_ident(&binary.left, state_var) {
        return None;
    }
    Some(ScanBody {
        assign_op: binary.op.clone(),
        rhs: (*binary.right).clone(),
    })
}

/// Check that `expr` is `Some(<deref-of-state>)`.
fn is_some_of_deref_state(expr: &Expr, state_var: &str) -> bool {
    let expr = strip_refs_groups(expr);
    let Expr::Call(call) = expr else {
        return false;
    };
    if call.args.len() != 1 {
        return false;
    }
    // func must be the bare `Some` path (no turbofish, no module prefix).
    if !is_ident_path(&call.func, "Some") {
        return false;
    }
    is_deref_of_ident(&call.args[0], state_var)
}

/// Check that `expr` is `*<ident>` where `<ident>` matches `name`.
fn is_deref_of_ident(expr: &Expr, name: &str) -> bool {
    let expr = strip_refs_groups(expr);
    let Expr::Unary(unary) = expr else {
        return false;
    };
    if !matches!(unary.op, UnOp::Deref(_)) {
        return false;
    }
    is_bare_ident(&unary.expr, name)
}

/// Check that `expr` is a simple single-segment path equal to `name`.
fn is_ident_path(expr: &Expr, name: &str) -> bool {
    let expr = strip_refs_groups(expr);
    let Expr::Path(path) = expr else {
        return false;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return false;
    }
    path.path.segments[0].ident == name
}

/// Check that `expr` is a bare ident path matching `name` (no turbofish, no qself).
fn is_bare_ident(expr: &Expr, name: &str) -> bool {
    is_ident_path(expr, name)
}

fn is_compound_assign_op(op: &BinOp) -> bool {
    matches!(
        op,
        BinOp::AddAssign(_)
            | BinOp::SubAssign(_)
            | BinOp::MulAssign(_)
            | BinOp::DivAssign(_)
            | BinOp::RemAssign(_)
            | BinOp::BitXorAssign(_)
            | BinOp::BitAndAssign(_)
            | BinOp::BitOrAssign(_)
            | BinOp::ShlAssign(_)
            | BinOp::ShrAssign(_)
    )
}

/// Evaluate `old_state <assign-op> rhs_val` to produce the new state.
/// Returns `None` on overflow, division-by-zero, or unsupported op (all bail
/// the whole scan to the opaque fallback — EXACT-OR-BAIL, never a fake-dig).
fn apply_assign_op(op: &BinOp, state: i64, rhs: i64) -> Option<i64> {
    match op {
        BinOp::AddAssign(_) => state.checked_add(rhs),
        BinOp::SubAssign(_) => state.checked_sub(rhs),
        BinOp::MulAssign(_) => state.checked_mul(rhs),
        BinOp::DivAssign(_) if rhs != 0 => state.checked_div(rhs),
        BinOp::RemAssign(_) if rhs != 0 => state.checked_rem(rhs),
        BinOp::BitXorAssign(_) => Some(state ^ rhs),
        BinOp::BitAndAssign(_) => Some(state & rhs),
        BinOp::BitOrAssign(_) => Some(state | rhs),
        BinOp::ShlAssign(_) => u32::try_from(rhs)
            .ok()
            .filter(|&n| n < 64)
            .and_then(|n| state.checked_shl(n)),
        BinOp::ShrAssign(_) => u32::try_from(rhs)
            .ok()
            .filter(|&n| n < 64)
            .and_then(|n| state.checked_shr(n)),
        _ => None,
    }
}
