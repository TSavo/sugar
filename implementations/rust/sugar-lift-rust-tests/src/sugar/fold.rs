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

use sugar_ir_symbolic::{and_, atomic_, num, Term};
use syn::{Expr, Pat, Stmt};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::{method, method_family};
use crate::{
    closure_body_is_side_effecting, closure_single_param_ident, collect_assertion_entries,
    const_fold_acc_update, const_int_acc_init, count_asserts_in_expr, count_asserts_in_stmts,
    resolve_index_in_formula, simple_path_name, strip_refs_groups, subst_var_in_formula, token_key,
    translate_term_in_scope, tuple_components, AssertionFactKind, ConstVal, Desugared, Outcome,
    Sugar, SugarCtx, Warrant, SUGAR_SEQ_CAP,
};
use tracing::debug;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("fold", recognize_composite);

/// COMPOSITE method-call recognizer for a `fold` terminal ([`FoldSugar`] via
/// [`decompose_fold`]): `Some` only for a recognized `fold` shape, else `None` (the
/// walk falls through to the next method-call recognizer). Mirrors the FIRST arm of the
/// old `build_method_call_composite` chain — BEFORE `for_each`.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            if matches!(method.as_str(), "fold" | "rfold") {
                if let Some(name) = simple_path_name(&call.receiver) {
                    let version = fcx.scope().version_of(&name);
                    let advanced = version.is_some_and(|version| version > 1);
                    let has_temporal_rewrite =
                        fcx.scope().temporal_rewrite_expr_for(&name).is_some();
                    if (fcx.scope().is_consumed_iterator_local(&name) || advanced)
                        && !has_temporal_rewrite
                    {
                        debug!(
                            target: "sugar::fold",
                            method = %method,
                            receiver = %name,
                            ?version,
                            "routing consumed iterator fold body through opaque warranted obligation"
                        );
                        return method::recognize(expr, fcx).map(|fallback| {
                            Box::new(ConsumedFoldSugar {
                                fallback,
                                claim_count: count_consumed_fold_assertions(call),
                                name: format!("consumed-iterator-fold::{}", token_key(expr)),
                            }) as Box<dyn Sugar>
                        });
                    }
                }
            }
            decompose_fold(expr, fcx).map(|node| Box::new(node) as Box<dyn Sugar>)
        }
        _ => None,
    }
}

struct ConsumedFoldSugar {
    fallback: Box<dyn Sugar>,
    claim_count: usize,
    name: String,
}

impl Sugar for ConsumedFoldSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let term = match self.fallback.desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        Outcome::Complete(Desugared::Constraints {
            atom: atomic_("iter.consumed_fold_body", vec![term]),
            n: self.claim_count,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant {
                name: Some(self.name.clone()),
            },
        })
    }
}

fn count_consumed_fold_assertions(call: &syn::ExprMethodCall) -> usize {
    call.args
        .iter()
        .find_map(|arg| match arg {
            Expr::Closure(closure) => Some(count_asserts_in_expr(&closure.body)),
            _ => None,
        })
        .unwrap_or(0)
}

/// Build the sequence-`Sugar` tree for a fold/for_each RECEIVER: a base literal
/// domain wrapped by the ordered adaptor chain (`LiteralSugar` innermost, each
/// per-class decorator `Sugar` -- `IdentitySugar`/`RevSugar`/`EnumerateSugar`/
/// `FilterSugar`/`MapSugar`/`FilterMapSugar`/`SkipSugar`/`TakeSugar`/`SkipWhileSugar`/
/// `TakeWhileSugar`, each in `src/sugar/*.rs` -- applied in base->terminal order). This is
/// `peel_fold_adaptors` in reverse-construction: peel to (base, wrappers), then nest
/// by folding each application-order wrapper over the running node. Resolving
/// `let`-bound receivers through `let_inits` is delegated to `peel_fold_adaptors`.
/// `extra_rev` appends a final `RevSugar` (for `.rfold`). None on an unrepresentable
/// adaptor / unresolvable binding (-> bail).
fn decompose_seq(expr: &Expr, ctx: &SugarCtx, extra_rev: bool) -> Option<Box<dyn Sugar>> {
    let let_inits = scope_let_inits(ctx);
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
    let mut node = method_family::build_literal_sequence_composite(expr, &fcx)?;
    if extra_rev {
        node = Box::new(crate::sugar::rev::RevSugar { inner: node });
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
/// the element order. `desugar` lazily builds the inner seq-sugar for the element
/// sequence, then threads + substitutes;
/// EXACT-OR-BAIL throughout (a non-const-foldable accumulator / side-effecting
/// body / opaque element -> None).
pub(crate) struct FoldSugar {
    receiver: Expr,
    init_expr: Expr,
    acc_var: String,
    item_binder: FoldItemBinder,
    body_stmts: Vec<Stmt>,
    tail: Expr,
    method: String,
    rev_fold: bool,
    /// The FULL closure body expr (block including the acc-update tail). The
    /// purity gate scans this whole body -- byte-identical to the procedural
    /// defolder, which checked `&closure.body` (tail included).
    closure_body: Expr,
}

impl Sugar for FoldSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // TOTAL: the complete body computes the legacy `Option<Desugared>`; `Outcome::from_opt`
        // lifts it (the structural bail -> `Incomplete(Effect::Unsupported)`, discarded by the
        // fall-through consumer exactly as the old `None` was).
        Outcome::from_opt((|| {
            let let_inits = scope_let_inits(ctx);
            let acc_0 = const_int_acc_init(&self.init_expr, &let_inits)?;
            let inner = decompose_seq(&self.receiver, ctx, self.rev_fold)?;
            // The post-adaptor element sequence (the inner seq-sugar bottoms out at a
            // literal domain or bails).
            let seq = inner.desugar(ctx).complete()?.into_seq()?;
            if seq.is_empty() {
                // The adaptor chain emptied the sequence (`.filter` kept nothing /
                // `.take(0)`): the fold body never runs -> vacuous. None rather than a
                // vacuous `true`.
                return None;
            }
            if seq.len() > SUGAR_SEQ_CAP as usize {
                return None;
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::fold",
                method = %self.method,
                seq_len = seq.len(),
                acc0 = acc_0,
                "fold replay resolved temporal sequence"
            );
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
                ctx.factory_audits,
                ctx.macro_depth,
                &ctx.scope.plan.interior_mut,
                None,
                ctx.scope.macro_registry(),
                &BTreeMap::new(),
                ctx.scope.fn_registry(),
                &ctx.scope.layout_type_registry,
            );
            let warranted: usize = body_entries
                .iter()
                .filter(|entry| matches!(entry.kind, AssertionFactKind::Warranted))
                .map(|entry| entry.claim_count)
                .sum();
            if !body_skipped.is_empty() || warranted != n_body {
                return None;
            }
            let body_conj = and_(body_entries.iter().map(|e| e.atom.clone()).collect());

            // Pre-translate the captured literal arrays' element exprs to TERMS so a body
            // `index(ys, <const>)` can resolve to its concrete element after the index is
            // threaded. An element that does not translate cleanly drops that array (its
            // `index` reads stay the EUF accessor -- a sound under-claim, never a fake-complete).
            let mut array_terms: BTreeMap<String, Vec<Rc<Term>>> = BTreeMap::new();
            let literal_arrays = literal_arrays_from_ctx(ctx);
            for (arr, elems) in &literal_arrays {
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
            let mut acc = acc_0;
            for (iteration, elem) in seq.iter().enumerate() {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::fold",
                    method = %self.method,
                    iteration,
                    acc,
                    item = %token_key(&elem.expr),
                    value = ?elem.value,
                    "fold replay iteration"
                );
                let mut inst =
                    subst_var_in_formula(&body_conj, &self.acc_var, &num(i128::from(acc)));
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
                kind: AssertionFactKind::Warranted,
                warrant,
            })
        })())
    }
}

fn scope_let_inits<'a, 'c>(ctx: &SugarCtx<'a, 'c>) -> BTreeMap<String, &'a Expr> {
    ctx.scope
        .let_bindings_iter()
        .map(|(name, init)| (name.clone(), init))
        .collect()
}

fn literal_arrays_from_ctx(ctx: &SugarCtx) -> BTreeMap<String, Vec<Expr>> {
    let mut literal_arrays: BTreeMap<String, Vec<Expr>> = BTreeMap::new();
    for (name, init) in ctx.scope.let_bindings_iter() {
        if let Expr::Array(arr) = strip_refs_groups(init) {
            literal_arrays.insert(name.clone(), arr.elems.iter().cloned().collect());
        }
    }
    literal_arrays
}

/// Build a `FoldSugar` (or `RFoldSugar`) from a `.fold`/`.rfold` method call, by
/// capturing the raw receiver plus the closure's binders + body + acc-update tail.
/// None (bail) on any shape outside the represented set -- this IS the front half of
/// `try_lift_fold_forall` (parsing), with the reduction living in
/// `FoldSugar::desugar`.
pub(crate) fn decompose_fold(expr: &Expr, fcx: &SugarBuildCtx) -> Option<FoldSugar> {
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
    const_int_acc_init(init_expr, fcx.let_inits())?;
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !receiver_has_temporal_rewrite(&call.receiver, fcx)
    {
        return None;
    }
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
        receiver: (*call.receiver).clone(),
        init_expr: init_expr.clone(),
        acc_var,
        item_binder,
        body_stmts: body_stmts.to_vec(),
        tail: tail.clone(),
        method,
        rev_fold,
        closure_body: (*closure.body).clone(),
    })
}

fn receiver_has_temporal_rewrite(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Some(name) = simple_path_name(expr) else {
        return false;
    };
    fcx.scope().temporal_rewrite_expr_for(&name).is_some()
}
