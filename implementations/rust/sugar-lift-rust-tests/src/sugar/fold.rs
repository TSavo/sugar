// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `FoldSugar` / `RFoldSugar` / `ForEachSugar`-as-fold: a finite-domain fold reduced to
// the finite conjunction of its per-iteration body (the construction axiom). Relocated
// verbatim from the `lib.rs` monolith (pure code-motion, zero behavior change). Carries
// its OWNED machinery: a typed receiver `SugarBody<CompositeFloor>`, the
// `FoldItemBinder` enum, and the `decompose_fold` constructor.
// Shared substrate (`peel_fold_adaptors`, `wrap_rev`, `capture_literal_arrays`, the
// collector, the term/const helpers) stays in `crate::` and is imported below; the base
// node `LiteralSugar` lives in the sibling `crate::sugar::literal`.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, make_var, num, Term};
use syn::{Expr, Pat, Stmt};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{FoldFloor, TemporalFloorRefusal};
use crate::{
    canonical_term_sig, closure_body_is_side_effecting, closure_single_param_ident,
    collect_assertion_entries, const_acc_init_value, const_fold_acc_update_value,
    const_fold_int_term, const_int_acc_init, const_val_term, count_asserts_in_stmts,
    resolve_index_in_formula_with_bindings, simple_path_name, strip_refs_groups,
    subst_var_in_formula, subst_var_in_term, token_key, translate_term_in_scope, tuple_components,
    AssertionFactKind, ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
    Warrant, SUGAR_SEQ_CAP,
};
use tracing::debug;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "fold",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_fold_good() {
                    let _fold_owner = [(1i32, 1i32), (2, 3)].into_iter().fold(0, |acc, (x, expected)| {
                        assert_eq!(acc + x, expected);
                        acc + x
                    });
                }
            "#,
            r#"
                #[test]
                fn t_fold_bad() {
                    let _fold_owner = [(1i32, 1i32), (2, 4)].into_iter().fold(0, |acc, (x, expected)| {
                        assert_eq!(acc + x, expected);
                        acc + x
                    });
                }
            "#,
        ),
        recognize_composite,
    );

/// COMPOSITE method-call recognizer for a `fold` terminal ([`FoldSugar`] via
/// [`decompose_fold`]): `Some` only for a recognized `fold` shape, else `None` (the
/// walk falls through to the next method-call recognizer). Mirrors the FIRST arm of the
/// old `build_method_call_composite` chain — BEFORE `for_each`.
pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            if method == "fold" || method == "rfold" {
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
                            "refusing consumed iterator fold body without a temporal rewrite"
                        );
                        return Some(Box::new(ConsumedFoldSugar {
                            receiver: name,
                            site: token_key(expr),
                        }));
                    }
                }
            }
            decompose_fold(expr, fcx).map(|node| Box::new(node) as Box<dyn Sugar>)
        }
        _ => None,
    }
}

struct ConsumedFoldSugar {
    receiver: String,
    site: String,
}

impl Sugar for ConsumedFoldSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let reason = ctx
            .scope
            .unknown_iterator_consumption_reason(&self.receiver)
            .unwrap_or_else(|| {
                format!(
                    "consumed-iterator local `{}` without temporal rewrite at `{}`; \
                     fold body cannot be replayed to a single literal sequence; \
                     refused as temporally unstable",
                    self.receiver, self.site
                )
            });
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity { reason })
    }
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
    receiver: SugarBody<CompositeFloor>,
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
        let let_inits = scope_let_inits(ctx);
        let acc_0 = const_acc_init_value(&self.init_expr, &let_inits)
            .unwrap_or_else(|| fold_gap("fold accumulator init did not reduce to an integer"));
        let mut seq = match self.receiver.reduce(ctx) {
            Outcome::Complete(Desugared::Seq(seq)) => seq
                .into_iter()
                .map(FoldReplayElem::Source)
                .collect::<Vec<_>>(),
            Outcome::Complete(Desugared::TermSeq(terms)) => terms
                .into_iter()
                .map(FoldReplayElem::Term)
                .collect::<Vec<_>>(),
            Outcome::Complete(_) => fold_gap("fold receiver reduced to non-sequence"),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        if self.rev_fold {
            seq.reverse();
        }
        if seq.is_empty() {
            // The adaptor chain emptied the sequence (`.filter` kept nothing /
            // `.take(0)`): the fold body never runs. That is not an effect, but it
            // also emits no warrantable body facts.
            fold_gap("fold receiver reduced to an empty sequence");
        }
        if seq.len() > SUGAR_SEQ_CAP as usize {
            fold_gap("fold sequence exceeded sugar cap");
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::fold",
            method = %self.method,
            seq_len = seq.len(),
            acc0 = ?acc_0,
            "fold replay resolved temporal sequence"
        );
        let n_body = count_asserts_in_stmts(&self.body_stmts);
        if n_body == 0 {
            fold_gap("fold body contains no assertions");
        }
        // Purity: the closure body must not mutate external state / advance an
        // iterator (a side-effecting body makes each iteration observe a varying
        // value, so the finite conjunction would be a false claim). HALF 2 then
        // makes it terminal. Scan the FULL closure body (tail included), exactly as
        // the procedural defolder did.
        if closure_body_is_side_effecting(&self.closure_body) {
            return Outcome::Incomplete(Effect::Mutation);
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
            fold_gap("fold body did not reduce to warranted assertion facts");
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

        let mut tail_scope = ctx
            .scope
            .fork_with_stable_term_binding(&self.acc_var, make_var(&self.acc_var));
        match &self.item_binder {
            FoldItemBinder::Whole(var) => {
                tail_scope = tail_scope.fork_with_stable_term_binding(var, make_var(var));
            }
            FoldItemBinder::Pair(c0, c1) => {
                tail_scope = tail_scope.fork_with_stable_term_binding(c0, make_var(c0));
                tail_scope = tail_scope.fork_with_stable_term_binding(c1, make_var(c1));
            }
        }
        let tail_template = translate_term_in_scope(&self.tail, &tail_scope)
            .unwrap_or_else(|_| fold_gap("fold accumulator update did not translate to a term"));

        // Thread the accumulator over the RESULTING element sequence: substitute the
        // concrete acc_k + the item binder's component(s) into the body formula, and
        // const-fold the tail to acc_{k+1} given those same bindings.
        let floor = FoldFloor::default();
        let operand = match floor.derived_operand(seq.len()) {
            Ok(operand) => operand,
            Err(err) => return fold_floor_refusal(err),
        };
        let acc_term =
            const_val_term(&acc_0).unwrap_or_else(|| fold_gap("fold accumulator was not a term"));
        let init = FoldAccumulator {
            value: acc_0,
            term: acc_term,
        };
        let output = match floor.desugar(
            ctx.scope.temporal_floor(),
            operand,
            &self.acc_var,
            init,
            seq.iter(),
            |iteration, acc, elem, alias| {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::fold",
                    method = %self.method,
                    iteration,
                    acc = ?acc.value,
                    item = %elem.label(),
                    value = ?elem.value(),
                    "fold replay iteration"
                );
                let mut inst = subst_var_in_formula(&body_conj, &self.acc_var, &acc.term);
                let mut recurrence_rhs =
                    subst_var_in_term(&tail_template, &self.acc_var, &acc.term);
                let mut tail_env: BTreeMap<String, ConstVal> = BTreeMap::new();
                tail_env.insert(self.acc_var.clone(), acc.value.clone());
                match &self.item_binder {
                    FoldItemBinder::Whole(var) => {
                        let t = elem.whole_term(ctx);
                        inst = subst_var_in_formula(&inst, var, &t);
                        recurrence_rhs = subst_var_in_term(&recurrence_rhs, var, &t);
                        if let Some(value) = elem.whole_value() {
                            tail_env.insert(var.clone(), value);
                        }
                    }
                    FoldItemBinder::Pair(c0, c1) => {
                        let (t0, t1) = elem.pair_terms(ctx);
                        inst = subst_var_in_formula(&inst, c0, &t0);
                        inst = subst_var_in_formula(&inst, c1, &t1);
                        recurrence_rhs = subst_var_in_term(&recurrence_rhs, c0, &t0);
                        recurrence_rhs = subst_var_in_term(&recurrence_rhs, c1, &t1);
                        if let Some(ConstVal::Tuple(parts)) = elem.value() {
                            if let Some(value) = parts.first() {
                                tail_env.insert(c0.clone(), value.clone());
                            }
                            if let Some(value) = parts.get(1) {
                                tail_env.insert(c1.clone(), value.clone());
                            }
                        }
                    }
                }
                // Resolve `index(<lit-array>, <const>)` reads (the now-threaded index) to
                // their literal elements -- the teeth: the asserted RHS carries the real
                // element value, so a wrong-expected twin is z3-refutable.
                if !array_terms.is_empty() {
                    let acc_index_term = const_val_term(&acc.value)
                        .unwrap_or_else(|| fold_gap("fold accumulator was not a term"));
                    let mut index_bindings =
                        BTreeMap::from([(self.acc_var.clone(), acc_index_term.clone())]);
                    if let Term::Var { name } = acc.term.as_ref() {
                        index_bindings.insert(name.clone(), acc_index_term);
                    }
                    inst = resolve_index_in_formula_with_bindings(
                        &inst,
                        &array_terms,
                        &index_bindings,
                    );
                }
                let next_value = const_fold_acc_update_value(&self.tail, &tail_env)
                    .unwrap_or_else(|| fold_gap("fold accumulator update did not const-fold"));
                let next_term = make_var(alias.value().to_string());
                let recurrence = eq(next_term.clone(), recurrence_rhs);
                (
                    and_(vec![inst, recurrence]),
                    FoldAccumulator {
                        value: next_value,
                        term: next_term,
                    },
                )
            },
        ) {
            Ok(output) => output,
            Err(err) => return fold_floor_refusal(err),
        };
        ctx.record_fold_floor_audit(&self.method, output.ticks().len());
        let instances = output
            .ticks()
            .iter()
            .map(|tick| tick.emission().clone())
            .collect();
        let conj = and_(instances);
        let warrant = Warrant {
            name: Some(format!("{}::{}", ctx.scope.local_scope(), self.method)),
        };
        Outcome::Complete(Desugared::Constraints {
            atom: conj,
            n: n_body,
            kind: AssertionFactKind::Warranted,
            warrant,
        })
    }
}

#[derive(Clone)]
struct FoldAccumulator {
    value: ConstVal,
    term: Rc<Term>,
}

enum FoldReplayElem {
    Source(DesugaredElem),
    Term(Rc<Term>),
}

impl FoldReplayElem {
    fn label(&self) -> String {
        match self {
            FoldReplayElem::Source(elem) => token_key(&elem.expr),
            FoldReplayElem::Term(term) => canonical_term_sig(term),
        }
    }

    fn value(&self) -> Option<&ConstVal> {
        match self {
            FoldReplayElem::Source(elem) => elem.value.as_ref(),
            FoldReplayElem::Term(_) => None,
        }
    }

    fn whole_term(&self, ctx: &SugarCtx) -> Rc<Term> {
        match self {
            FoldReplayElem::Source(elem) => translate_term_in_scope(&elem.expr, ctx.scope)
                .unwrap_or_else(|_| fold_gap("fold item did not reduce to a term")),
            FoldReplayElem::Term(term) => {
                const_fold_int_term(term).map_or_else(|| Rc::clone(term), num)
            }
        }
    }

    fn whole_value(&self) -> Option<ConstVal> {
        match self {
            FoldReplayElem::Source(elem) => elem.value.clone(),
            FoldReplayElem::Term(term) => const_fold_int_term(term).map(ConstVal::Int),
        }
    }

    fn pair_terms(&self, ctx: &SugarCtx) -> (Rc<Term>, Rc<Term>) {
        let FoldReplayElem::Source(elem) = self else {
            fold_gap("fold pair item reduced to term sequence without tuple components");
        };
        let comps = tuple_components(&elem.expr)
            .unwrap_or_else(|| fold_gap("fold pair item was not a tuple"));
        if comps.len() != 2 {
            fold_gap("fold pair item did not have exactly two components");
        }
        let t0 = translate_term_in_scope(comps[0], ctx.scope)
            .unwrap_or_else(|_| fold_gap("fold pair component 0 did not reduce to a term"));
        let t1 = translate_term_in_scope(comps[1], ctx.scope)
            .unwrap_or_else(|_| fold_gap("fold pair component 1 did not reduce to a term"));
        (t0, t1)
    }
}

fn fold_gap(reason: &str) -> ! {
    panic!("fold did not reach a lawful floor: {reason}")
}

fn fold_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
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
        receiver: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
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
