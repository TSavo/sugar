// SPDX-License-Identifier: Apache-2.0
//
// `ForAllSugar` / `ForEachSugar`: a bounded universal over a finite-construction domain
// (`for v in <lit> { body }` / `<lit>.iter().for_each(|v| body)`). Relocated verbatim
// from the `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// machinery: `lift_bounded_forall` (the shared verified core: literal-int-range unroll /
// literal-array conjunction / guarded forall) and the `decompose_for_loop` constructor.
// Shared substrate (the collector, the term/formula helpers, `bounded_domain_from_expr`,
// `capture_literal_arrays`, `SUGAR_SEQ_CAP`) stays in `crate::` and is imported below.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, forall, implies, lt, lte, num, Formula, Sort, Term};
use syn::{Expr, Pat, Stmt};

use crate::sugar::factory::{boxed, FactoryCtx};
use crate::{
    bounded_domain_from_expr, capture_literal_arrays, collect_assertion_entries,
    count_asserts_in_stmts, iter_adaptor_base, loop_body_mutates, resolve_index_in_formula,
    subst_var_in_formula, term_as_int, translate_term_in_scope, BoundedDomain, Desugared,
    FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx, TemporalScope, Warrant,
    SUGAR_SEQ_CAP,
};

/// COMPOSITE recognizer for `Expr::ForLoop`: the universal-quantifier composite
/// ([`ForAllSugar`] via [`decompose_for_loop`]). Byte-identical to the
/// `Expr::ForLoop(f) => boxed(decompose_for_loop(f, fcx.scope, fcx.let_inits))` arm of
/// the old fat `build_composite`.
pub(crate) fn recognize_for_loop(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::ForLoop(f) => Some(boxed(decompose_for_loop(f, fcx.scope, fcx.let_inits))),
        _ => None,
    }
}

/// COMPOSITE method-call recognizer for a `.for_each(|v| body)` quantifier terminal
/// ([`ForAllSugar`] via [`decompose_for_each`]): `Some` only for a recognized `for_each`
/// shape, else `None` (the walk falls through to the next method-call recognizer).
/// Mirrors the second arm of the old `build_method_call_composite` chain — AFTER
/// `fold`, BEFORE `closure_adaptor`.
pub(crate) fn recognize_for_each(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::MethodCall(_) => {
            decompose_for_each(expr, fcx.scope, fcx.let_inits).map(|node| Box::new(node) as Box<dyn Sugar>)
        }
        _ => None,
    }
}

/// and `try_lift_for_each_forall` (a `.for_each(|var| body)` adaptor): a `for`
/// loop and a `.for_each` over the SAME constructed domain assert the SAME
/// universal, so the construction is one piece of code. Returns the quantified
/// formula and the number of body assert macros it accounts for, or None to
/// refuse (mutation, body not point-wise, or count mismatch).
#[allow(clippy::too_many_arguments)]
fn lift_bounded_forall(
    var: &str,
    domain: BoundedDomain,
    body_stmts: &[Stmt],
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
    // In-scope IMMUTABLE literal arrays (name -> element TERMS), already mut-gated and
    // translated by the caller. Used to resolve a body `index(arr, <const>)` read to
    // its concrete element in the LITERAL-INT RANGE unroll. Empty -> no index read is
    // resolved (the reads stay the EUF accessor -- the established sound floor).
    literal_arrays: &BTreeMap<String, Vec<Rc<Term>>>,
) -> Option<(Rc<Formula>, usize)> {
    // Lift the body through the normal collector. Truth-table-or-gutter: every
    // body assert must lift cleanly (none refused, none missing) or we refuse
    // the whole loop.
    let n_body = count_asserts_in_stmts(body_stmts);
    if n_body == 0 {
        return None;
    }
    // Purity gate: the body must not mutate anything. An assignment, a `let mut`,
    // or a `&mut` borrow means a value varies across iterations independently of
    // the loop variable (e.g. an accumulator `count = count + 1`), so a single
    // universal over x would be a false claim. Gutter such loops -- the
    // single-iteration view can look stable when it is not.
    if loop_body_mutates(body_stmts) {
        return None;
    }
    let mut body_entries = Vec::new();
    let mut body_skipped = Vec::new();
    let mut body_lifted = 0usize;
    let mut body_helpers = HashSet::new();
    collect_assertion_entries(
        body_stmts,
        scope.local_scope(),
        options,
        reducer,
        float_widths,
        &mut body_entries,
        &mut body_skipped,
        &mut body_lifted,
        &mut body_helpers,
        macro_depth,
        &scope.plan.interior_mut,
        &BTreeMap::new(),
    );
    if !body_skipped.is_empty() || body_entries.len() != n_body {
        return None;
    }
    let body_conj = and_(body_entries.iter().map(|e| e.atom.clone()).collect());

    let quantified = match domain {
        BoundedDomain::Range {
            start,
            end,
            inclusive,
        } => {
            // LITERAL-INT RANGE UNROLL (the value-in-scope dig). When BOTH endpoints
            // are literal int constants, the iteration domain is the FINITE set of
            // concrete positions {start, start+1, ..} -- a literal in scope, exactly
            // as a literal array's elements are. THE LAW: a value at a determinable
            // position over a literal domain is in scope -> dig. We unroll to the
            // finite conjunction body[var:=start] ∧ .. ∧ body[var:=last], each `var`
            // a concrete `num(k)`, then resolve any `index(arr, k)` read against the
            // captured immutable literal arrays so the asserted RHS carries the REAL
            // element (teeth: a wrong-expected twin is z3-refutable, not an
            // always-SAT EUF accessor). This is what lifts `for i in 0..n {
            // assert_eq!(v[i], ys[i]) }` point-wise.
            //
            // GUARDRAILS (exact-or-bail): (1) both endpoints LITERAL ints, else fall
            // through to the guarded forall (a runtime endpoint like `0..v.len()` is
            // NOT a finite literal construction). (2) count in `[0, SUGAR_SEQ_CAP]`
            // -- an empty range is vacuous (None), a huge one is left as the guarded
            // forall (the unroll would be unrepresentable). (3) the index resolution
            // only fires over an IMMUTABLE literal array (the caller mut-gated
            // `literal_arrays`); an unknown / mutable array read stays the EUF floor.
            // (4) the unroll engages ONLY when there is at least one resolvable literal
            // array to index into (`!literal_arrays.is_empty()`): a plain `for x in
            // 0..3 { g(x) }` with no literal-array read has NOTHING to dig, so it stays
            // the guarded forall it always was (the unroll would merely reshape an
            // already-discharged universal -- no new teeth, and it would change the
            // lifted FOL form of existing-discharged loops; we leave those untouched so
            // discharged/CID are conserved). The unroll is purely ADDITIVE: it only
            // reaches a literal-domain loop whose body indexes an immutable literal
            // array, the value-in-scope dig the guarded forall could not express.
            let lit_bounds = if literal_arrays.is_empty() {
                None
            } else {
                term_as_int(&start)
                    .zip(term_as_int(&end))
                    // `checked_add`: an inclusive end at i128::MAX would
                    // overflow; bail (None) rather than wrap.
                    .and_then(|(s, e)| {
                        if inclusive {
                            e.checked_add(1).map(|hi| (s, hi))
                        } else {
                            Some((s, e))
                        }
                    })
            };
            match lit_bounds {
                Some((lo, hi)) if hi > lo && (hi - lo) <= i128::from(SUGAR_SEQ_CAP) => {
                    // The cap gate bounds `hi - lo` to <= 4096, so `as usize`
                    // below is in range.
                    let mut instances = Vec::with_capacity((hi - lo) as usize);
                    for k in lo..hi {
                        let mut inst = subst_var_in_formula(&body_conj, var, &num(k));
                        if !literal_arrays.is_empty() {
                            inst = resolve_index_in_formula(&inst, literal_arrays);
                        }
                        instances.push(inst);
                    }
                    and_(instances)
                }
                // Empty literal range (`hi <= lo`): the loop never runs -> vacuous;
                // refuse rather than emit a vacuous `true` (mirrors the empty-array
                // bail in `bounded_domain_from_expr`).
                Some((lo, hi)) if hi <= lo => return None,
                // Runtime endpoint, or a literal range too large to unroll: the
                // guarded universal it states, body free in `var`.
                // forall x:Int. ( start <= x (< | <=) end ) => body[var := x]
                _ => {
                    let bound_var = var.to_string();
                    forall(Sort::int(), move |x| {
                        let lower = lte(start.clone(), x.clone());
                        let upper = if inclusive {
                            lte(x.clone(), end.clone())
                        } else {
                            lt(x.clone(), end.clone())
                        };
                        let guard = and_(vec![lower, upper]);
                        let body = subst_var_in_formula(&body_conj, &bound_var, &x);
                        implies(guard, body)
                    })
                }
            }
        }
        // `for x in [e0, e1, ...]` is exactly the FINITE conjunction
        // body[x:=e0] ∧ body[x:=e1] ∧ ... -- a complete unroll over the constructed
        // element terms, every instance concrete (full point-wise teeth). This is
        // the construction axiom directly: the domain is allocated at formation, so
        // `∀x ∈ {e_i}. body` IS the finite conjunction, no quantifier needed.
        BoundedDomain::Array(elems) => {
            let instances = elems
                .iter()
                .map(|e| {
                    let mut inst = subst_var_in_formula(&body_conj, var, e);
                    // Resolve a body `index(arr, <const>)` read whose index const-folds
                    // to a literal (e.g. the element `e` is itself a literal position).
                    // A non-resolvable read stays the EUF accessor (sound floor).
                    if !literal_arrays.is_empty() {
                        inst = resolve_index_in_formula(&inst, literal_arrays);
                    }
                    inst
                })
                .collect();
            and_(instances)
        }
    };
    Some((quantified, n_body))
}

/// `ForEachSugar` / `ForAllSugar`: a bounded universal over a finite-construction
/// domain. `for v in <lit> { body }` and `<lit>.iter().for_each(|v| body)` assert
/// the SAME universal (a finite conjunction over a literal array; a guarded forall
/// over a closed range) -- `for_each` is `fold` with the unit accumulator, so the
/// construction is one piece of code (`lift_bounded_forall`, the shared verified
/// core). `desugar` reduces to that conjunction or bails (mutation / non-point-wise
/// body / count mismatch). `kind` only flavors the warrant name (`for_each`/`loop`).
pub(crate) struct ForAllSugar {
    var: String,
    domain: BoundedDomain,
    body_stmts: Vec<Stmt>,
    /// The warrant-name flavor: `"for_each"` (adaptor) or `"loop"` (for-loop).
    kind: &'static str,
    /// In-scope LITERAL arrays (`ys -> [13, 15, ..]`), captured from `let_inits` at
    /// decompose time -- the same capture `FoldSugar` does. Used ONLY to resolve a
    /// body `index(ys, <const>)` read to its concrete literal element AFTER the loop
    /// index has been threaded to a literal position (the LITERAL-INT RANGE unroll
    /// below). A body `assert_eq!(v[i], ys[i])` over a literal `0..n` index and
    /// immutable literal `v`/`ys` is point-wise diggable: at each unrolled `i` both
    /// reads resolve to their concrete elements, so the asserted equality carries the
    /// REAL element values (teeth: a wrong-expected twin is z3-refutable). A
    /// non-literal-array binding is absent -> its `index` reads stay the EUF accessor
    /// (sound under-claim, the established floor). Empty for a `for x in <range>`
    /// whose body indexes nothing -- then this is inert.
    literal_arrays: BTreeMap<String, Vec<Expr>>,
}

impl Sugar for ForAllSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // TOTAL: the dig body computes the legacy `Option<Desugared>`; `Outcome::from_opt`
        // lifts it (the structural bail -> `Hit(Effect::Unsupported)`, discarded by the
        // fall-through consumer exactly as the old `None` was).
        Outcome::from_opt((|| {
        // Translate the captured literal arrays' element exprs to TERMS so the body's
        // `index(ys, <const>)` reads (the LITERAL-INT RANGE unroll) can resolve to
        // concrete elements. SOUNDNESS: only an IMMUTABLE literal array may have its
        // index reads resolved -- a `let mut arr = [..]` could be index-assigned, so
        // its value at a later point is not the written literal (leave its reads as
        // the EUF accessor). An element that does not translate cleanly drops that
        // array (its reads stay the EUF accessor -- a sound under-claim, never a
        // fake-dig). Byte-identical to `FoldSugar`'s array_terms capture.
        let mut array_terms: BTreeMap<String, Vec<Rc<Term>>> = BTreeMap::new();
        for (arr, elems) in &self.literal_arrays {
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

        // `lift_bounded_forall` is the shared verified core: it const-checks the
        // domain (range -> guarded forall OR -- when both endpoints are literal ints
        // and the count is small -- a finite point-wise unroll; array -> finite
        // conjunction), lifts the body all-or-nothing through the normal collector,
        // and gates purity. We re-discriminate the domain here (it is consumed by
        // value) by re-reading; pass the already-resolved `BoundedDomain`.
        let (quantified, n_body) = lift_bounded_forall(
            &self.var,
            self.domain.clone(),
            &self.body_stmts,
            ctx.scope,
            ctx.options,
            ctx.reducer,
            *ctx.float_widths.borrow_mut(),
            ctx.macro_depth,
            &array_terms,
        )?;
        let warrant = Warrant {
            name: Some(format!(
                "{}::{}::{}",
                ctx.scope.local_scope(),
                self.kind,
                self.var
            )),
        };
        Some(Desugared::Constraints {
            atom: quantified,
            n: n_body,
            warrant,
        })
        })())
    }
}

/// Build a `ForEachSugar` from a `<receiver>.for_each(|v| body)` adaptor: the
/// receiver (less one element-producing adaptor) must resolve to a finite-
/// construction domain, the closure must bind one plain ident. None (bail)
/// otherwise. This is the front half of `try_lift_for_each_forall`.
pub(crate) fn decompose_for_each(
    expr: &Expr,
    scope: &TemporalScope,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<ForAllSugar> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "for_each" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = &call.args[0] else {
        return None;
    };
    if closure.inputs.len() != 1 {
        return None;
    }
    let var = match &closure.inputs[0] {
        Pat::Ident(p) if p.subpat.is_none() => p.ident.to_string(),
        Pat::Reference(r) => match &*r.pat {
            Pat::Ident(p) if p.subpat.is_none() && r.mutability.is_none() => p.ident.to_string(),
            _ => return None,
        },
        _ => return None,
    };
    let base = iter_adaptor_base(&call.receiver);
    let domain = bounded_domain_from_expr(base, scope)?;
    let body_stmts: Vec<Stmt> = match &*closure.body {
        Expr::Block(b) => b.block.stmts.clone(),
        other => vec![Stmt::Expr(other.clone(), None)],
    };
    Some(ForAllSugar {
        var,
        domain,
        body_stmts,
        kind: "for_each",
        literal_arrays: capture_literal_arrays(let_inits),
    })
}

/// Build a `ForAllSugar` from a `for <var> in <domain> { body }` loop: the domain
/// must be a finite construction (closed range / literal array). None (bail)
/// otherwise. This is the front half of `try_lift_for_loop_forall`.
pub(crate) fn decompose_for_loop(
    f: &syn::ExprForLoop,
    scope: &TemporalScope,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<ForAllSugar> {
    let var = match &*f.pat {
        Pat::Ident(p) if p.subpat.is_none() => p.ident.to_string(),
        _ => return None,
    };
    let domain = bounded_domain_from_expr(&f.expr, scope)?;
    Some(ForAllSugar {
        var,
        domain,
        body_stmts: f.body.stmts.clone(),
        kind: "loop",
        literal_arrays: capture_literal_arrays(let_inits),
    })
}
