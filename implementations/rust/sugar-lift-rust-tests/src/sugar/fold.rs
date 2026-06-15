// SPDX-License-Identifier: Apache-2.0
//
// FoldSugar / RFold -- the threaded-accumulator finite conjunction.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per Sugar
// class). Behaviour-preserving: the desugar logic is byte-identical to the
// monolith; only its physical location changed.

use std::collections::BTreeMap;

use syn::{Expr, Pat, Stmt};

use crate::*;

use crate::sugar::adaptor::decompose_seq;
use crate::sugar::literal::SUGAR_SEQ_CAP;

/// The item-binder of a `fold`/`rfold` closure's second parameter: a plain ident
/// binds the WHOLE element; a 2-tuple binds `(comp0, comp1)` of a tuple element.
pub(crate) enum FoldItemBinder {
    Whole(String),
    Pair(String, String),
}

/// `FoldSugar` / `RFoldSugar` (and `ForEachSugar` as the `acc = ()` degenerate):
/// `<seq-sugar>.fold(init, |acc, item| { <asserts>; <tail> })` over a FINITE
/// literal domain is the finite conjunction of the per-iteration body with `acc`
/// threaded as a CONST-FOLDED integer and `item`/index bound to the concrete
/// element -- the construction axiom (desugar fold WITH fold). `.rfold` reverses
/// the element order (the inner seq-sugar already carries the `Rev`). `desugar`
/// recurses on `inner` for the element sequence, then threads + substitutes;
/// EXACT-OR-BAIL throughout (a non-const-foldable accumulator / side-effecting
/// body / opaque element -> None).
pub(crate) struct FoldSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) acc_var: String,
    pub(crate) item_binder: FoldItemBinder,
    pub(crate) acc_0: i64,
    pub(crate) body_stmts: Vec<Stmt>,
    pub(crate) tail: Expr,
    pub(crate) method: String,
    /// The FULL closure body expr (block including the acc-update tail). The
    /// purity gate scans this whole body -- byte-identical to the procedural
    /// defolder, which checked `&closure.body` (tail included).
    pub(crate) closure_body: Expr,
}

impl Sugar for FoldSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
        // The post-adaptor element sequence (the inner seq-sugar bottoms out at a
        // literal domain or bails).
        let seq = self.inner.desugar(ctx)?.into_seq()?;
        if seq.is_empty() {
            // The adaptor chain emptied the sequence (`.filter` kept nothing /
            // `.take(0)`): the fold body never runs -> vacuous. None rather than a
            // vacuous `true`.
            return None;
        }
        if seq.len() as i64 > SUGAR_SEQ_CAP {
            return None;
        }
        let n_body = count_asserts_in_stmts(&self.body_stmts);
        if n_body == 0 {
            return None;
        }
        // Purity: the closure body must not mutate external state / advance an
        // iterator (a side-effecting body makes each iteration observe a varying
        // value, so the finite conjunction would be a false claim). HALF 2 then
        // makes it terminal. Scan the FULL closure body (tail included), exactly as
        // the procedural defolder did.
        if closure_body_is_side_effecting(&self.closure_body) {
            return None;
        }
        // Lift the body ONCE, free in acc_var / elem_var / idx_var. All-or-nothing.
        let mut body_entries = Vec::new();
        let mut body_skipped = Vec::new();
        let mut body_lifted = 0usize;
        let mut body_helpers = HashSet::new();
        collect_assertion_entries(
            &self.body_stmts,
            ctx.scope.local_scope(),
            ctx.options,
            ctx.reducer,
            *ctx.float_widths.borrow_mut(),
            &mut body_entries,
            &mut body_skipped,
            &mut body_lifted,
            &mut body_helpers,
            ctx.macro_depth,
            &ctx.scope.plan.interior_mut,
        );
        if !body_skipped.is_empty() || body_entries.len() != n_body {
            return None;
        }
        let body_conj = and_(body_entries.iter().map(|e| e.atom.clone()).collect());

        // Thread the accumulator over the RESULTING element sequence: substitute the
        // concrete acc_k + the item binder's component(s) into the body formula, and
        // const-fold the tail to acc_{k+1} given those same bindings.
        let mut instances = Vec::with_capacity(seq.len());
        let mut acc = self.acc_0;
        for elem in &seq {
            let mut inst = subst_var_in_formula(&body_conj, &self.acc_var, &num(acc));
            let mut tail_env: BTreeMap<String, i64> = BTreeMap::new();
            tail_env.insert(self.acc_var.clone(), acc);
            match &self.item_binder {
                FoldItemBinder::Whole(var) => {
                    let t = translate_term_in_scope(&elem.expr, ctx.scope).ok()?;
                    inst = subst_var_in_formula(&inst, var, &t);
                    if let Some(n) = elem.value.as_ref().and_then(ConstVal::as_int) {
                        tail_env.insert(var.clone(), n);
                    }
                }
                FoldItemBinder::Pair(c0, c1) => {
                    let comps = tuple_components(&elem.expr)?;
                    if comps.len() != 2 {
                        return None;
                    }
                    let t0 = translate_term_in_scope(comps[0], ctx.scope).ok()?;
                    let t1 = translate_term_in_scope(comps[1], ctx.scope).ok()?;
                    inst = subst_var_in_formula(&inst, c0, &t0);
                    inst = subst_var_in_formula(&inst, c1, &t1);
                    if let Some(ConstVal::Tuple(parts)) = &elem.value {
                        if let Some(n) = parts.first().and_then(ConstVal::as_int) {
                            tail_env.insert(c0.clone(), n);
                        }
                        if let Some(n) = parts.get(1).and_then(ConstVal::as_int) {
                            tail_env.insert(c1.clone(), n);
                        }
                    }
                }
            }
            instances.push(inst);
            acc = const_fold_acc_update(&self.tail, &tail_env)?;
        }
        let conj = and_(instances);
        let warrant = Warrant {
            name: Some(format!("{}::{}", ctx.scope.local_scope(), self.method)),
        };
        Some(Desugared::Constraints {
            atom: conj,
            n: n_body,
            warrant,
        })
    }
}

/// Build a `FoldSugar` (or `RFoldSugar`) from a `.fold`/`.rfold` method call, by
/// decomposing the receiver into its sequence-`Sugar` tree and capturing the
/// closure's binders + body + acc-update tail. None (bail) on any shape outside
/// the represented set -- this IS the front half of `try_lift_fold_forall`
/// (parsing), with the reduction living in `FoldSugar::desugar`.
pub(crate) fn decompose_fold(
    expr: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<FoldSugar> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    let rev_fold = match method.as_str() {
        "fold" => false,
        "rfold" => true,
        _ => return None,
    };
    if call.args.len() != 2 {
        return None;
    }
    let init_expr = &call.args[0];
    let Expr::Closure(closure) = &call.args[1] else {
        return None;
    };
    if closure.inputs.len() != 2 {
        return None;
    }
    let acc_var = match &closure.inputs[0] {
        Pat::Ident(p) if p.subpat.is_none() => p.ident.to_string(),
        _ => return None,
    };
    let item_binder = match &closure.inputs[1] {
        Pat::Tuple(t) if t.elems.len() == 2 => {
            let c0 = closure_single_param_ident(&t.elems[0])?;
            let c1 = closure_single_param_ident(&t.elems[1])?;
            FoldItemBinder::Pair(c0, c1)
        }
        other => FoldItemBinder::Whole(closure_single_param_ident(other)?),
    };
    let acc_0 = const_int(init_expr)?;
    let inner = decompose_seq(&call.receiver, let_inits, rev_fold)?;
    // The closure body: block-bodied (asserts + acc-update tail). The tail is the
    // final expr-without-semi; the preceding statements are the body.
    let Expr::Block(body_block) = &*closure.body else {
        return None;
    };
    let stmts = &body_block.block.stmts;
    let Some((Stmt::Expr(tail, None), body_stmts)) = stmts.split_last() else {
        return None;
    };
    Some(FoldSugar {
        inner,
        acc_var,
        item_binder,
        acc_0,
        body_stmts: body_stmts.to_vec(),
        tail: tail.clone(),
        method,
        closure_body: (*closure.body).clone(),
    })
}
