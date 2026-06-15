// SPDX-License-Identifier: Apache-2.0
//
// `FoldSugar` / `RFoldSugar` / `ForEachSugar`-as-fold: a finite-domain fold reduced to
// the finite conjunction of its per-iteration body (the construction axiom). Relocated
// verbatim from the `lib.rs` monolith (pure code-motion, zero behavior change). Carries
// its OWNED machinery: `decompose_seq` (the receiver adaptor-chain builder), the
// `FoldItemBinder` enum, and the `decompose_fold` / `decompose_for_each` constructors.
// Shared substrate (`peel_fold_adaptors`, `wrap_rev`, `capture_literal_arrays`, the
// collector, the term/const helpers) stays in `crate::` and is imported below; the base
// node `LiteralSugar` lives in the sibling `crate::sugar::literal`.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, num, Term};
use syn::{Expr, Pat, Stmt};

use crate::sugar::literal::LiteralSugar;
use crate::{
    closure_body_is_side_effecting, closure_single_param_ident, collect_assertion_entries,
    const_fold_acc_update, const_int_acc_init, count_asserts_in_stmts, peel_fold_adaptors,
    resolve_index_in_formula, strip_refs_groups, subst_var_in_formula, translate_term_in_scope,
    tuple_components, wrap_rev, ConstVal, Desugared, Outcome, Sugar, SugarCtx, Warrant,
    SUGAR_SEQ_CAP,
};

/// Build the sequence-`Sugar` tree for a fold/for_each RECEIVER: a base literal
/// domain wrapped by the ordered adaptor chain (`LiteralSugar` innermost, each
/// per-class decorator `Sugar` -- `IdentitySugar`/`RevSugar`/`EnumerateSugar`/
/// `FilterSugar`/`MapSugar`/`SkipSugar`/`TakeSugar`/`SkipWhileSugar`/`TakeWhileSugar`,
/// each in `src/sugar/*.rs` -- applied in base->terminal order). This is
/// `peel_fold_adaptors` in reverse-construction: peel to (base, wrappers), then nest
/// by folding each application-order wrapper over the running node. Resolving
/// `let`-bound receivers through `let_inits` is delegated to `peel_fold_adaptors`.
/// `extra_rev` appends a final `RevSugar` (for `.rfold`). None on an unrepresentable
/// adaptor / unresolvable binding (-> bail).
fn decompose_seq(
    expr: &Expr,
    let_inits: &BTreeMap<String, &Expr>,
    extra_rev: bool,
) -> Option<Box<dyn Sugar>> {
    let (base, mut adaptors) = peel_fold_adaptors(expr, let_inits, 0)?;
    if extra_rev {
        adaptors.push(Box::new(wrap_rev));
    }
    let mut node: Box<dyn Sugar> = Box::new(LiteralSugar { base: base.clone() });
    for wrap in adaptors {
        node = wrap(node);
    }
    Some(node)
}

/// The item-binder of a `fold`/`rfold` closure's second parameter: a plain ident
/// binds the WHOLE element; a 2-tuple binds `(comp0, comp1)` of a tuple element.
enum FoldItemBinder {
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
    inner: Box<dyn Sugar>,
    acc_var: String,
    item_binder: FoldItemBinder,
    acc_0: i64,
    body_stmts: Vec<Stmt>,
    tail: Expr,
    method: String,
    /// The FULL closure body expr (block including the acc-update tail). The
    /// purity gate scans this whole body -- byte-identical to the procedural
    /// defolder, which checked `&closure.body` (tail included).
    closure_body: Expr,
    /// In-scope LITERAL arrays (`ys -> [13, 15, ..]`), captured from `let_inits` at
    /// decompose time. Used ONLY to resolve a body `index(ys, <const>)` term to its
    /// concrete literal element AFTER the accumulator (the index) has been threaded
    /// to a literal position -- the teeth: the asserted RHS carries the real element
    /// value, so a wrong-expected twin is z3-REFUTABLE, not vacuously satisfiable.
    /// Scoped to the fold body so no other (already-discharged) site's lifted form
    /// changes. A non-literal-array binding is absent -> the `index` term stays the
    /// uninterpreted EUF accessor (sound under-claim, the established floor).
    literal_arrays: BTreeMap<String, Vec<Expr>>,
}

impl Sugar for FoldSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // TOTAL: the dig body computes the legacy `Option<Desugared>`; `Outcome::from_opt`
        // lifts it (the structural bail -> `Hit(Effect::Unsupported)`, discarded by the
        // fall-through consumer exactly as the old `None` was).
        Outcome::from_opt((|| {
        // The post-adaptor element sequence (the inner seq-sugar bottoms out at a
        // literal domain or bails).
        let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
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
            &BTreeMap::new(),
        );
        if !body_skipped.is_empty() || body_entries.len() != n_body {
            return None;
        }
        let body_conj = and_(body_entries.iter().map(|e| e.atom.clone()).collect());

        // Pre-translate the captured literal arrays' element exprs to TERMS so a body
        // `index(ys, <const>)` can resolve to its concrete element after the index is
        // threaded. An element that does not translate cleanly drops that array (its
        // `index` reads stay the EUF accessor -- a sound under-claim, never a fake-dig).
        let mut array_terms: BTreeMap<String, Vec<Rc<Term>>> = BTreeMap::new();
        for (arr, elems) in &self.literal_arrays {
            // SOUNDNESS: only an IMMUTABLE literal array may have its `index(arr, k)`
            // read resolved to a literal element. A `let mut arr = [..]` could be
            // index-assigned / mutated, so its value at a later program point is not
            // the written literal -- leave its `index` reads as the EUF accessor.
            if ctx.scope.is_mut_local(arr) {
                continue;
            }
            let mut ts = Vec::with_capacity(elems.len());
            let mut ok = true;
            for e in elems {
                match translate_term_in_scope(e, ctx.scope) {
                    Ok(t) => ts.push(t),
                    Err(_) => {
                        ok = false;
                        break;
                    }
                }
            }
            if ok {
                array_terms.insert(arr.clone(), ts);
            }
        }

        // Thread the accumulator over the RESULTING element sequence: substitute the
        // concrete acc_k + the item binder's component(s) into the body formula, and
        // const-fold the tail to acc_{k+1} given those same bindings.
        let mut instances = Vec::with_capacity(seq.len());
        let mut acc = self.acc_0;
        for elem in &seq {
            let mut inst = subst_var_in_formula(&body_conj, &self.acc_var, &num(i128::from(acc)));
            let mut tail_env: BTreeMap<String, i64> = BTreeMap::new();
            tail_env.insert(self.acc_var.clone(), acc);
            match &self.item_binder {
                FoldItemBinder::Whole(var) => {
                    let t = translate_term_in_scope(&elem.expr, ctx.scope).ok()?;
                    inst = subst_var_in_formula(&inst, var, &t);
                    // The fold item enters the bounded i64 accumulator env; a wide
                    // element value is not a representable cursor input -> bail
                    // (EXACT-OR-BAIL).
                    if let Some(n) = elem
                        .value
                        .as_ref()
                        .and_then(ConstVal::as_int)
                        .and_then(|n| i64::try_from(n).ok())
                    {
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
                        if let Some(n) = parts
                            .first()
                            .and_then(ConstVal::as_int)
                            .and_then(|n| i64::try_from(n).ok())
                        {
                            tail_env.insert(c0.clone(), n);
                        }
                        if let Some(n) = parts
                            .get(1)
                            .and_then(ConstVal::as_int)
                            .and_then(|n| i64::try_from(n).ok())
                        {
                            tail_env.insert(c1.clone(), n);
                        }
                    }
                }
            }
            // Resolve `index(<lit-array>, <const>)` reads (the now-threaded index) to
            // their literal elements -- the teeth: the asserted RHS carries the real
            // element value, so a wrong-expected twin is z3-refutable.
            if !array_terms.is_empty() {
                inst = resolve_index_in_formula(&inst, &array_terms);
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
        })())
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
    let acc_0 = const_int_acc_init(init_expr, let_inits)?;
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
    // Capture the in-scope LITERAL arrays so the fold body's `index(ys, k)` term
    // (after the index `k` is threaded to a literal) can be resolved to its element.
    let mut literal_arrays: BTreeMap<String, Vec<Expr>> = BTreeMap::new();
    for (name, init) in let_inits {
        if let Expr::Array(arr) = strip_refs_groups(init) {
            literal_arrays.insert(name.clone(), arr.elems.iter().cloned().collect());
        }
    }
    Some(FoldSugar {
        inner,
        acc_var,
        item_binder,
        acc_0,
        body_stmts: body_stmts.to_vec(),
        tail: tail.clone(),
        method,
        closure_body: (*closure.body).clone(),
        literal_arrays,
    })
}
