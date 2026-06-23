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
use tracing::debug;

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    bounded_domain_from_expr, capture_literal_arrays, collect_assertion_entries,
    const_fold_int_term, const_val_term, count_asserts_in_stmts, loop_body_mutates,
    resolve_index_in_formula, subst_var_in_formula, term_as_int, translate_term_in_scope,
    AssertionFactKind, BoundedDomain, Desugared, FloatWidthScope, LiftOptions, Outcome,
    ReductionCtx, Sugar, SugarCtx, TemporalScope, Warrant, SUGAR_SEQ_CAP,
};

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
    factory_audits: Option<&crate::FactoryAuditLog>,
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
        debug!(
            target: "sugar_lift_rust_tests::sugar::forall",
            var,
            "forall declined: body has no assertion macros"
        );
        return None;
    }
    // Purity gate: the body must not mutate anything. An assignment, a `let mut`,
    // or a `&mut` borrow means a value varies across iterations independently of
    // the loop variable (e.g. an accumulator `count = count + 1`), so a single
    // universal over x would be a false claim. Gutter such loops -- the
    // single-iteration view can look stable when it is not.
    if loop_body_mutates(body_stmts) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::forall",
            var,
            n_body,
            "forall declined: body mutates state"
        );
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
        factory_audits,
        macro_depth,
        &scope.plan.interior_mut,
        None,
        scope.macro_registry(),
        &BTreeMap::new(),
        scope.fn_registry(),
        &scope.layout_type_registry,
    );
    let warranted_assertions: usize = body_entries
        .iter()
        .filter(|entry| matches!(entry.kind, AssertionFactKind::Warranted))
        .map(|entry| entry.claim_count)
        .sum();
    if !body_skipped.is_empty() || warranted_assertions != n_body {
        debug!(
            target: "sugar_lift_rust_tests::sugar::forall",
            var,
            n_body,
            warranted_assertions,
            skipped = ?body_skipped,
            "forall declined: body did not lift point-wise"
        );
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
            // Plain literal-range body assertions also reduce here: `forall_loop` owns
            // the source shape, and the closed literal endpoints give the concrete
            // iteration values to substitute into the body.
            let lit_bounds = term_as_int(&start)
                .or_else(|| const_fold_int_term(&start))
                .zip(term_as_int(&end).or_else(|| const_fold_int_term(&end)))
                // `checked_add`: an inclusive end at i128::MAX would overflow; bail
                // (None) rather than wrap.
                .and_then(|(s, e)| {
                    if inclusive {
                        e.checked_add(1).map(|hi| (s, hi))
                    } else {
                        Some((s, e))
                    }
                });
            match lit_bounds {
                Some((lo, hi)) if hi > lo && (hi - lo) <= i128::from(SUGAR_SEQ_CAP) => {
                    // The cap gate bounds `hi - lo` to <= 4096, so `as usize`
                    // below is in range.
                    let mut instances = Vec::with_capacity((hi - lo) as usize);
                    for k in lo..hi {
                        let mut inst = subst_var_in_formula(&body_conj, var, &num(k));
                        inst = fold_literal_int_terms_in_formula(&inst);
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
                    inst = fold_literal_int_terms_in_formula(&inst);
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

fn fold_literal_int_terms_in_formula(formula: &Rc<Formula>) -> Rc<Formula> {
    match formula.as_ref() {
        Formula::Atomic { name, args } => Rc::new(Formula::Atomic {
            name: name.clone(),
            args: args.iter().map(fold_literal_int_term).collect(),
        }),
        Formula::Connective { kind, operands } => Rc::new(Formula::Connective {
            kind: kind.clone(),
            operands: operands
                .iter()
                .map(fold_literal_int_terms_in_formula)
                .collect(),
        }),
        Formula::Quantifier {
            kind,
            name,
            sort,
            body,
        } => Rc::new(Formula::Quantifier {
            kind: kind.clone(),
            name: name.clone(),
            sort: sort.clone(),
            body: fold_literal_int_terms_in_formula(body),
        }),
        Formula::Choice {
            var_name,
            sort,
            body,
        } => Rc::new(Formula::Choice {
            var_name: var_name.clone(),
            sort: sort.clone(),
            body: fold_literal_int_terms_in_formula(body),
        }),
    }
}

fn fold_literal_int_term(term: &Rc<Term>) -> Rc<Term> {
    match term.as_ref() {
        Term::Ctor { name, args } => const_fold_int_term(term).map_or_else(
            || {
                Rc::new(Term::Ctor {
                    name: name.clone(),
                    args: args.iter().map(fold_literal_int_term).collect(),
                })
            },
            num,
        ),
        _ => term.clone(),
    }
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
    domain: ForAllDomain,
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

enum ForAllDomain {
    Bounded(BoundedDomain),
    Sequence(Box<dyn Sugar>),
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
            let domain = match &self.domain {
                ForAllDomain::Bounded(domain) => domain.clone(),
                ForAllDomain::Sequence(receiver) => {
                    let seq = receiver.desugar(ctx).dug()?.into_seq()?;
                    if seq.is_empty() || seq.len() as i64 > SUGAR_SEQ_CAP {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::forall",
                            var = self.var.as_str(),
                            len = seq.len(),
                            cap = SUGAR_SEQ_CAP,
                            "forall sequence domain declined: empty or over cap"
                        );
                        return None;
                    }
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::forall",
                        var = self.var.as_str(),
                        len = seq.len(),
                        "forall sequence domain materialized"
                    );
                    let mut elems = Vec::with_capacity(seq.len());
                    for elem in seq {
                        let Some(term) = elem
                            .value
                            .as_ref()
                            .and_then(const_val_term)
                            .or_else(|| translate_term_in_scope(&elem.expr, ctx.scope).ok())
                        else {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::forall",
                                var = self.var.as_str(),
                                elem = %crate::token_key(&elem.expr),
                                "forall sequence domain declined: element did not translate to term"
                            );
                            return None;
                        };
                        elems.push(term);
                    }
                    BoundedDomain::Array(elems)
                }
            };
            let (quantified, n_body) = lift_bounded_forall(
                &self.var,
                domain,
                &self.body_stmts,
                ctx.scope,
                ctx.options,
                ctx.reducer,
                *ctx.float_widths.borrow_mut(),
                ctx.macro_depth,
                ctx.factory_audits,
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
                kind: AssertionFactKind::Warranted,
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
    let_inits: &BTreeMap<String, &Expr>,
    fcx: &SugarBuildCtx,
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
    if !method_family::resolves_literal_sequence(&call.receiver, let_inits) {
        return None;
    }
    let body_stmts: Vec<Stmt> = match &*closure.body {
        Expr::Block(b) => b.block.stmts.clone(),
        other => vec![Stmt::Expr(other.clone(), None)],
    };
    Some(ForAllSugar {
        var,
        domain: ForAllDomain::Sequence(build_composite(&call.receiver, fcx)),
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
    fcx: &SugarBuildCtx,
) -> Option<ForAllSugar> {
    let var = for_loop_pat_ident(&f.pat)?;
    let domain = if let Some(domain) = bounded_domain_from_expr(&f.expr, scope) {
        ForAllDomain::Bounded(domain)
    } else if has_composite(&f.expr, fcx) {
        ForAllDomain::Sequence(build_composite(&f.expr, fcx))
    } else {
        return None;
    };
    Some(ForAllSugar {
        var,
        domain,
        body_stmts: f.body.stmts.clone(),
        kind: "loop",
        literal_arrays: capture_literal_arrays(let_inits),
    })
}

fn for_loop_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(p) if p.subpat.is_none() => Some(p.ident.to_string()),
        Pat::Reference(r) if r.mutability.is_none() => for_loop_pat_ident(&r.pat),
        Pat::Paren(paren) => for_loop_pat_ident(&paren.pat),
        Pat::Type(ty) => for_loop_pat_ident(&ty.pat),
        _ => None,
    }
}
