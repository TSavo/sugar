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
// non-integer state types except the unit-state item-yield identity shape, and
// `None`-returning (early-stop) closures. Any shape outside the supported set declines
// to the caller; a claimed terminal chain then reports a factory gap rather than forging
// a value.
//
// REGISTERED AS: not in the catalog directly; recognized and constructed by
// `iter_terminal::try_build_scan_inner` as a pre-pass in that recognizer, so the
// full chain `source.scan(init, closure).terminal()` grounds with teeth.

use std::collections::BTreeMap;

use syn::{BinOp, Expr, FnArg, Pat, Stmt, UnOp};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::{
    closure_single_param_ident, const_fold_acc_update, const_int_acc_init, simple_path_name,
    strip_refs_groups, ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("scan", recognize_composite);

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    try_build_scan_inner(expr, fcx)
}

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
pub(crate) fn try_build_scan_inner(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method != "scan" || call.args.len() != 2 {
        return None;
    }
    // The scan's own receiver must bottom out in a finite literal sequence.
    let inner = SugarBody::from_node(
        crate::sugar::method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
    );
    let plan = build_scan_plan(&call.args[0], &call.args[1], fcx)?;
    Some(Box::new(ScanSugar { inner, plan }))
}

pub(crate) fn build_scan_adaptor(
    inner: Box<dyn Sugar>,
    init: Expr,
    mapper: Expr,
    fcx: &SugarBuildCtx,
) -> Box<dyn Sugar> {
    let plan = build_scan_plan(&init, &mapper, fcx).unwrap_or_else(|| {
        scan_gap(
            "scan adaptor did not reach a supported integer-accumulator or unit-item-yield shape",
        )
    });
    Box::new(ScanSugar {
        inner: SugarBody::from_node(inner),
        plan,
    })
}

/// A stateful-map adaptor over a finite literal source. Threads an integer
/// accumulator through each element and yields each updated state as a concrete
/// integer `DesugaredElem`. Produces `Desugared::Seq` so all downstream terminals
/// can operate on the grounded values with z3 teeth.
struct ScanSugar {
    inner: SugarBody<CompositeFloor>,
    plan: ScanPlan,
}

enum ScanPlan {
    Accumulate { init: i64, mapper: ScanMapper },
    UnitYieldItem,
}

struct ScanMapper {
    state_var: String,
    item_var: String,
    body: ScanBody,
    yield_kind: ScanYield,
}

enum ScanYield {
    IntState,
    FloatState,
}

impl Sugar for ScanSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_seq()
                .unwrap_or_else(|| scan_gap("inner completed as non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let ScanPlan::Accumulate { init, mapper } = &self.plan else {
            return Outcome::Complete(Desugared::Seq(seq));
        };
        let mut state = *init;
        let mut out: Vec<DesugaredElem> = Vec::with_capacity(seq.len());
        for elem in &seq {
            let item_val = elem
                .value
                .as_ref()
                .and_then(ConstVal::as_int)
                .and_then(|n| i64::try_from(n).ok())
                .unwrap_or_else(|| scan_gap("sequence element did not carry an integer literal"));
            // Evaluate the rhs expression with BOTH state_var and item_var bound
            // so that expressions like `*acc * x` or `*acc + x` const-fold correctly.
            let mut env: BTreeMap<String, i64> = BTreeMap::new();
            env.insert(mapper.state_var.clone(), state);
            env.insert(mapper.item_var.clone(), item_val);
            let rhs_val = const_fold_acc_update(&mapper.body.rhs, &env)
                .unwrap_or_else(|| scan_gap("scan rhs did not reduce under literal state/item"));
            // Apply the compound-assign op to get the new state.
            state = apply_assign_op(&mapper.body.assign_op, state, rhs_val).unwrap_or_else(|| {
                scan_gap("scan compound assignment overflowed or divided by zero")
            });
            out.push(mapper.element(state));
        }
        Outcome::Complete(Desugared::Seq(out))
    }
}

impl ScanMapper {
    fn element(&self, state: i64) -> DesugaredElem {
        match self.yield_kind {
            ScanYield::IntState => {
                let expr: Expr = syn::parse_str(&state.to_string())
                    .expect("i64 always parses as a Rust integer literal");
                DesugaredElem {
                    expr,
                    value: Some(ConstVal::Int(i128::from(state))),
                }
            }
            ScanYield::FloatState => {
                let expr: Expr = syn::parse_str(&format!("{state}.0"))
                    .expect("i64 with .0 always parses as a Rust float literal");
                DesugaredElem { expr, value: None }
            }
        }
    }
}

fn scan_gap(reason: &str) -> ! {
    panic!("scan did not reach a lawful sequence floor: {reason}")
}

fn build_scan_plan(init: &Expr, mapper: &Expr, fcx: &SugarBuildCtx) -> Option<ScanPlan> {
    if is_unit_expr(init) && unit_state_item_yield_mapper(mapper).is_some() {
        return Some(ScanPlan::UnitYieldItem);
    }
    let init = const_int_acc_init(init, fcx.let_inits())?;
    let mapper = build_scan_mapper(mapper, fcx)?;
    Some(ScanPlan::Accumulate { init, mapper })
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
    parse_scan_update_stmt(&update_stmts[0], state_var)
}

fn build_scan_mapper(expr: &Expr, fcx: &SugarBuildCtx) -> Option<ScanMapper> {
    match strip_refs_groups(expr) {
        Expr::Closure(closure) => {
            if closure.inputs.len() != 2 {
                return None;
            }
            let state_var = closure_single_param_ident(&closure.inputs[0])?;
            let item_var = closure_single_param_ident(&closure.inputs[1])?;
            let body = parse_scan_body(&closure.body, &state_var)?;
            Some(ScanMapper {
                state_var,
                item_var,
                body,
                yield_kind: ScanYield::IntState,
            })
        }
        Expr::Path(_) => build_visible_scan_mapper(expr, fcx),
        _ => None,
    }
}

fn unit_state_item_yield_mapper(expr: &Expr) -> Option<()> {
    let Expr::Closure(closure) = strip_refs_groups(expr) else {
        return None;
    };
    if closure.inputs.len() != 2 {
        return None;
    }
    if !is_wildcard_pat(&closure.inputs[0]) {
        return None;
    }
    let item_var = scan_param_name(&closure.inputs[1])?;
    is_some_of_item(&closure.body, &item_var).then_some(())
}

fn build_visible_scan_mapper(expr: &Expr, fcx: &SugarBuildCtx) -> Option<ScanMapper> {
    let name = simple_path_name(expr)?;
    let helper = fcx.scope().visible_fn(&name)?;
    if helper.sig.asyncness.is_some() {
        scan_gap("visible scan mapper is async");
    }
    if crate::count_asserts_in_stmts(&helper.block.stmts) != 0 {
        scan_gap("visible scan mapper contains assertions");
    }
    let params = visible_scan_param_names(&helper)
        .unwrap_or_else(|| scan_gap("visible scan mapper parameter list is not scan-shaped"));
    let [state_var, item_var] = params.as_slice() else {
        scan_gap("visible scan mapper must have exactly two parameters");
    };
    let (body, yield_kind) = parse_visible_scan_body(&helper.block, state_var)
        .unwrap_or_else(|| scan_gap("visible scan mapper body is not scan-shaped"));
    Some(ScanMapper {
        state_var: state_var.clone(),
        item_var: item_var.clone(),
        body,
        yield_kind,
    })
}

fn visible_scan_param_names(helper: &syn::ItemFn) -> Option<Vec<String>> {
    helper
        .sig
        .inputs
        .iter()
        .map(|arg| match arg {
            FnArg::Typed(pat) => scan_param_name(&pat.pat),
            FnArg::Receiver(_) => None,
        })
        .collect()
}

fn scan_param_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(id) if id.subpat.is_none() => Some(id.ident.to_string()),
        Pat::Reference(reference) => scan_param_name(&reference.pat),
        Pat::Type(typed) => scan_param_name(&typed.pat),
        Pat::Paren(paren) => scan_param_name(&paren.pat),
        _ => None,
    }
}

fn parse_visible_scan_body(block: &syn::Block, state_var: &str) -> Option<(ScanBody, ScanYield)> {
    let (tail_stmt, update_stmts) = block.stmts.split_last()?;
    if update_stmts.len() != 1 {
        return None;
    }
    let body = parse_scan_update_stmt(&update_stmts[0], state_var)?;
    let Stmt::Expr(tail_expr, None) = tail_stmt else {
        return None;
    };
    let yield_kind = parse_scan_yield(tail_expr, state_var)?;
    Some((body, yield_kind))
}

fn parse_scan_update_stmt(stmt: &Stmt, state_var: &str) -> Option<ScanBody> {
    let Stmt::Expr(update_expr, Some(_)) = stmt else {
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

fn parse_scan_yield(expr: &Expr, state_var: &str) -> Option<ScanYield> {
    let expr = strip_refs_groups(expr);
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 || !is_ident_path(&call.func, "Some") {
        return None;
    }
    let yielded = strip_refs_groups(&call.args[0]);
    if is_deref_of_ident(yielded, state_var) {
        return Some(ScanYield::IntState);
    }
    let Expr::Cast(cast) = yielded else {
        return None;
    };
    if !is_deref_of_ident(&cast.expr, state_var) {
        return None;
    }
    let syn::Type::Path(path) = &*cast.ty else {
        return None;
    };
    let name = path.path.segments.last()?.ident.to_string();
    matches!(name.as_str(), "f32" | "f64").then_some(ScanYield::FloatState)
}

fn is_unit_expr(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Tuple(tuple) if tuple.elems.is_empty())
}

fn is_wildcard_pat(pat: &Pat) -> bool {
    match pat {
        Pat::Wild(_) => true,
        Pat::Type(typed) => is_wildcard_pat(&typed.pat),
        Pat::Paren(paren) => is_wildcard_pat(&paren.pat),
        _ => false,
    }
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

fn is_some_of_item(expr: &Expr, item_var: &str) -> bool {
    let expr = strip_refs_groups(expr);
    let Expr::Call(call) = expr else {
        return false;
    };
    if call.args.len() != 1 || !is_ident_path(&call.func, "Some") {
        return false;
    }
    let yielded = strip_refs_groups(&call.args[0]);
    is_bare_ident(yielded, item_var) || is_deref_of_ident(yielded, item_var)
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
/// the whole scan to the factory gap path -- EXACT-OR-BAIL, never a fake-complete).
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
