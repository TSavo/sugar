// SPDX-License-Identifier: Apache-2.0
//
// CallsiteSugar -- call-site inlining AS a Sugar.
//
// This module LIFTS-AND-REPLACES the old procedural R7 inlining block (the
// `else if macro_depth < MAX_MACRO_EXPANSION_DEPTH && resolve_inlinable_helper_call(..)`
// arm that used to live inline in `collect_assertion_entries`) into the Sugar
// hierarchy. There is now ONE inlining engine -- this one -- not a parallel
// procedural copy.
//
// THE CONSTRUCT. An assertion can live inside a NON-`#[test]` helper fn, reachable
// only by inlining a call to that helper. `CallsiteSugar::decompose` recognizes a
// bare call statement `helper(arg0, arg1, ..)` to a file-resolvable, non-runtime-
// opaque helper whose body asserts (resolving nested-in-test helpers first via
// `resolve_inlinable_helper_call_scoped`), and binds `param := callsite actual`.
// `CallsiteSugar`
// then β-reduces (substitutes the actuals into the helper body) and re-decomposes /
// desugars the substituted body THROUGH THE SAME hierarchy (the ordinary collector,
// which itself dispatches Fold/ForAll/Conditional/Literal/term/macro/...). This is
// the doctrine's complete-to-literals applied across a call boundary.
//
// THE GATE (exact-or-bail, the soundness line). The complete is the fake-discharge-
// dangerous direction: inlining a body that does NOT fully reduce would turn one
// honest "reachable only via call-site inlining" refusal into N×M unclassified
// instances (the helper is called from N sites, each re-hitting the same M gaps).
// So `desugar` TRIALS the inline into scratch buffers and COMMITS only when the
// substituted body adds ZERO unclassified -- it fully discharges or terminal-
// refuses. Otherwise it BAILS: the helper stays unreduced and Pass 2 keeps the
// single "reachable only" refusal. Inlining therefore only ever DRAINS, never
// inflates. This reproduces the old gate byte-for-byte (so the assertion-multiset
// CID and the discharged/refused/unclassified counts are conserved); the change is
// that the gate now lives in a typed Sugar, and that `desugar` NAMES why a bail
// happened (the typed `Outcome`/`Effect` machinery) for the STEP-1 census.

use std::collections::{BTreeSet, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, ImplItemFn, ItemFn, Stmt};

// Child of crate root: sees crate-root-private items (the Sugar hierarchy, the
// collector, the resolver, the substitution, the disposition classifier).
use std::collections::BTreeMap;

use crate::{
    callsite_child_fallback_term, child_block_scope, collect_assertion_entries,
    count_asserts_in_stmts, expr_head_key, helper_body_runtime_terminal_reason,
    is_consuming_iterator_method, receiver_is_versioned_iterator, refusal_disposition,
    resolve_inlinable_helper_call_scoped, resolve_inlinable_method_call_scoped,
    stmts_have_runtime_terminal_body_shape, substitute_stmts, AssertionEntry, Disposition, Effect,
    ExprBindings, FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, SugarCtx,
    TemporalScope, MAX_MACRO_EXPANSION_DEPTH,
};

/// Build the opaque panic-freedom subject for a call/method expression.
///
/// Panic-freedom is about the callsite reaching normal return, not the value the
/// call returns. This callsite sugar therefore owns the `call:*#panic_callsite` /
/// `method:*#panic_callsite` subject and only asks child term floors to reduce
/// receiver/argument structure. If a child hits a named effect, the subject falls
/// back to an opaque child identity rather than laundering that value effect into
/// the panic predicate.
pub(crate) fn opaque_callsite_term(ctx: &SugarCtx, expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Call(_) | Expr::MethodCall(_) => Some(opaque_callsite_call_or_method_term(ctx, expr)),
        _ => None,
    }
}

fn opaque_callsite_call_or_method_term(ctx: &SugarCtx, expr: &Expr) -> Rc<Term> {
    let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
    let dig_child = |expr: &Expr| -> Rc<Term> {
        if crate::sugar::method_family::literal_sequence_static_len_in_scope(
            expr, &let_inits, ctx.scope,
        ) == Some(0)
        {
            return callsite_child_identity_term(expr, ctx.scope);
        }
        let opaque_or_fallback = || {
            if matches!(expr, Expr::Call(_) | Expr::MethodCall(_)) {
                opaque_callsite_call_or_method_term(ctx, expr)
            } else {
                callsite_child_identity_term(expr, ctx.scope)
            }
        };
        if matches!(expr, Expr::Call(_) | Expr::MethodCall(_)) {
            return opaque_or_fallback();
        }
        if source_less_format_args_builtin(expr, ctx) {
            return callsite_child_identity_term(expr, ctx.scope);
        }
        if callsite_child_is_opaque_value(expr) {
            return callsite_child_identity_term(expr, ctx.scope);
        }
        match callsite_child_floor_term(expr, ctx) {
            CallsiteChildFloorTerm::Term(term) => return term,
            CallsiteChildFloorTerm::NotTerm => {}
            CallsiteChildFloorTerm::Effect(effect) => {
                let _ = effect;
            }
        }
        callsite_child_identity_term(expr, ctx.scope)
    };

    match expr {
        Expr::Call(call) => {
            let mut args = Vec::new();
            for arg in &call.args {
                args.push(dig_child(arg));
            }
            Rc::new(Term::Ctor {
                name: format!("call:{}#panic_callsite", expr_head_key(&call.func)),
                args,
            })
        }
        Expr::MethodCall(call) => {
            let mut receiver = dig_child(&call.receiver);
            if is_consuming_iterator_method(&call.method.to_string()) {
                if let Term::Var { name } = receiver.as_ref() {
                    if receiver_is_versioned_iterator(name, ctx.scope) {
                        let occ = ctx.scope.bump_consuming_occurrence(name);
                        if occ > 0 {
                            receiver = make_var(format!("{name}@adv{occ}"));
                        }
                    }
                }
            }
            let mut args = vec![receiver];
            for arg in &call.args {
                args.push(dig_child(arg));
            }
            Rc::new(Term::Ctor {
                name: format!(
                    "method:{}#panic_callsite",
                    crate::sugar::method::method_key(call)
                ),
                args,
            })
        }
        _ => panic!(
            "opaque callsite term constructed for non-call expression `{}`",
            expr_head_key(expr)
        ),
    }
}

fn callsite_child_is_opaque_value(expr: &Expr) -> bool {
    match expr {
        Expr::Closure(_) => true,
        Expr::Block(_) | Expr::Unsafe(_) => {
            !crate::sugar::block_term::has_transparent_term_tail(expr)
        }
        _ => false,
    }
}

enum CallsiteChildFloorTerm {
    Term(Rc<Term>),
    NotTerm,
    Effect(Effect),
}

fn callsite_child_floor_term(expr: &Expr, ctx: &SugarCtx) -> CallsiteChildFloorTerm {
    match crate::sugar::factory::SugarBody::synthesized_term(expr, ctx).reduce(ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .map(CallsiteChildFloorTerm::Term)
            .unwrap_or(CallsiteChildFloorTerm::NotTerm),
        Outcome::Incomplete(effect) => CallsiteChildFloorTerm::Effect(effect),
    }
}

fn callsite_child_identity_term(expr: &Expr, scope: &crate::TemporalScope) -> Rc<Term> {
    callsite_child_fallback_term(expr, scope).unwrap_or_else(|| {
        panic!(
            "callsite child identity unavailable for `{}`",
            expr_head_key(expr)
        )
    })
}

fn source_less_format_args_builtin(expr: &Expr, ctx: &SugarCtx) -> bool {
    if ctx.scope.macro_registry().lookup("format_args").is_some() {
        return false;
    }
    if crate::sugar::format::is_format_args_macro_shape(expr) {
        return true;
    }
    let Expr::Path(path) = crate::strip_refs_groups(expr) else {
        return false;
    };
    let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
        return false;
    };
    ctx.scope
        .stable_let_binding_for_term(&name)
        .is_some_and(crate::sugar::format::is_format_args_macro_shape)
}

/// A call-site inlining opportunity, decomposed from a bare call statement. The
/// payload mirrors `resolve_inlinable_helper_call`'s tuple: the resolved helper, its
/// name (the `reduced_helpers` key), and the `param := actual` bindings.
///
/// `'a` is the lifetime of the source items the `ReductionCtx` borrows the helper
/// from (the helper is `&'a ItemFn`, owned by the parsed `syn::File`).
pub(crate) struct CallsiteSugar<'a> {
    pub(crate) helper: &'a ItemFn,
    pub(crate) name: String,
    pub(crate) closed_args: ExprBindings,
}

/// A source-backed method-call inlining opportunity. The method name is not assertion
/// vocabulary; it is only a path to visible source. Its body is substituted and
/// re-entered through the same collector, so assertion meaning comes from shapes such as
/// `lhs cmp rhs`, `assert!(...)`, or `if cond { panic!() }`.
pub(crate) struct MethodCallsiteSugar {
    pub(crate) helper: Rc<ImplItemFn>,
    pub(crate) name: String,
    pub(crate) closed_args: ExprBindings,
}

/// The committed payload of a successful inline: the scratch buffers the trial
/// produced. The dispatch site folds these back into the real collector state
/// (`entries`/`skipped`/`macros_lifted`/`reduced_helpers`). Carrying them in a typed
/// value (rather than mutating the real buffers during the trial) is what makes the
/// gate exact -- nothing is committed until `added_unclassified == 0` is proven.
pub(crate) struct InlineCommit {
    pub(crate) entries: Vec<AssertionEntry>,
    pub(crate) skipped: Vec<String>,
    pub(crate) macros_lifted: usize,
    pub(crate) reduced_helpers: HashSet<String>,
    pub(crate) name: String,
}

/// The typed outcome of a `CallsiteSugar::desugar`, the inlining mirror of the
/// crate-root `Outcome { Complete, Incomplete }`:
///
///   * `Complete(InlineCommit)` -- the substituted body FULLY reduced (every body assert
///     discharged or terminal-refused; `added_unclassified == 0`). The inline
///     commits; the asserts lift via the byte-identical complete path. This is the
///     blessed inlining-unblock: `discharged` may rise, no fake-discharge.
///   * `Bail(BailCause)` -- the substituted body did NOT fully reduce (some body
///     assert is honestly unclassified -- a pure-but-untranslated term, or an
///     unsupported construct), OR the call was not a carryable closed-arg call to a
///     resolvable helper. The helper stays unreduced; Pass 2 keeps the single
///     "reachable only via call-site inlining" refusal. HONEST: a pure-but-
///     untranslated body stays unclassified -- never fake-complete, never fake-refused.
///
/// There is deliberately NO callsite-level `Incomplete(Effect)` variant that COMMITS a
/// differently-shaped result: a body whose asserts are ALL order-loss effects
/// already has `added_unclassified == 0`, so it reaches `Complete` and commits-as-refused
/// through the normal collector (the effect asserts become terminal-refused entries
/// inside the inlined body). Introducing a separate committing `Incomplete` here would move
/// the counts. The `BailCause` below NAMES an effect when the bail residue is one,
/// for the census -- it does not change which bodies commit.
pub(crate) enum CallsiteOutcome {
    Complete(InlineCommit),
    Bail(BailCause),
}

/// Why a `CallsiteSugar` bailed -- the STEP-1 categorization of the residue. This is
/// the typed cause of the un-committed inline (the thing the 112 "reachable only"
/// asserts are blocked on). It is diagnostic: the dispatch site treats every bail
/// identically (fall through, leave the helper unreduced).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum BailCause {
    /// The call was not a carryable closed-arg call to a file-resolvable, non-runtime
    /// helper (no inlinable opportunity at this site). Includes runtime-opaque-param
    /// helpers, ambiguous helpers, arity mismatch, self-receivers, depth exhaustion.
    NotInlinable,
    /// The substituted body fully reduced but `desugar` was invoked with the trial
    /// gate -- this is never returned; kept for exhaustiveness clarity. (Unused.)
    #[allow(dead_code)]
    FullyReduced,
    /// The substituted body left N assertions UNCLASSIFIED. The categorization splits
    /// that residue by the reason SHAPE so the census can report what each blocked
    /// body actually hits. `added_unclassified` is the count; `sample_reasons` are
    /// the distinct unclassified reasons (for the census, ungrouped).
    UnclassifiedResidue {
        added_unclassified: usize,
        sample_reasons: Vec<String>,
    },
}

impl<'a> CallsiteSugar<'a> {
    /// Decompose a bare call statement into a `CallsiteSugar`, or `None` if `expr` is
    /// not a carryable inlinable call (the resolver declines: not a simple call, no
    /// resolvable/unambiguous helper, helper does not assert, inactive cfg, non-simple
    /// params, arity mismatch, self-receiver). This is the front half of the old R7
    /// arm's `resolve_inlinable_helper_call(..).is_some()` guard.
    ///
    /// `local_fns` are the nested fns lexically in scope at the call site (the current
    /// block's `Item::Fn`s). They are resolved FIRST -- THE DRAIN: a helper defined
    /// inside a `#[test]` fn body (invisible to the global reducer) inlines exactly
    /// like a top-level one. The monotonic gate in `desugar` keeps this sound.
    pub(crate) fn decompose(
        expr: &Expr,
        local_fns: &BTreeMap<String, &'a ItemFn>,
        reducer: &ReductionCtx<'a>,
        options: &LiftOptions,
        macro_depth: usize,
    ) -> Option<CallsiteSugar<'a>> {
        if macro_depth >= MAX_MACRO_EXPANSION_DEPTH {
            return None;
        }
        let (helper, name, closed_args) =
            resolve_inlinable_helper_call_scoped(expr, local_fns, reducer, options)?;
        Some(CallsiteSugar {
            helper,
            name,
            closed_args,
        })
    }

    /// Build a `CallsiteSugar` directly from a helper + an ALREADY-COLLECTED
    /// `param := actual` binding set, bypassing the bare-statement-call recognizer.
    ///
    /// THE ARG-POSITION REACH. The bare-statement `decompose` only fires when the helper
    /// call IS the whole statement (`helper(arg0, ..);`). The corpus's remaining
    /// concrete-helper residue calls the helper in ARGUMENT position -- inside another
    /// call / reference / macro arg (`assert_ne!(hash(&val), hash(&zero_byte(val, 0)))`).
    /// The helper itself is never a bare statement, so its INTERNAL asserts
    /// (`assert!(byte < 8)`) were left as the single "reachable only via call-site
    /// inlining" refusal. This constructor lets the collector, having found such a call
    /// site and extracted its `param := actual` bindings, replay the SAME gated
    /// `desugar` trial on the helper body.
    ///
    /// SOUND BY THE SAME GATE: nothing about the construction path changes the soundness
    /// line. `desugar` substitutes the actuals into the body and commits ONLY when the
    /// substituted body adds zero unclassified. A param bound to a RUNTIME actual that
    /// the body's asserts actually read produces unclassified residue (an uninterpreted
    /// term it cannot close) and BAILS; a param bound to a closed literal that the asserts
    /// read completes to a point-wise FOL obligation. A runtime actual the asserts do NOT read
    /// (e.g. `zero_byte`'s `val`, used only to compute the unasserted return value) never
    /// reaches an obligation, so the body still completes -- exactly the intended drain.
    pub(crate) fn from_bindings(
        helper: &'a ItemFn,
        name: String,
        closed_args: ExprBindings,
    ) -> CallsiteSugar<'a> {
        CallsiteSugar {
            helper,
            name,
            closed_args,
        }
    }

    /// β-reduce + re-desugar through the hierarchy, gated. Substitutes
    /// `closed_args` (param := callsite actual) into the helper body, then runs the
    /// SAME collector (which re-dispatches the body's own Fold/ForAll/Conditional/
    /// Literal/term/macro sugars) on the substituted body in SCRATCH buffers. Commits
    /// (`Complete`) iff the body adds zero unclassified; bails otherwise.
    ///
    /// `local_scope` / `stmt_idx` reproduce the old arm's
    /// `child_block_scope(local_scope, stmt_idx)` for the inlined body's consistency
    /// scope. `reduced_helpers` is the CURRENT reduced set (cloned into the trial so a
    /// nested inline is visible but the real set is untouched until commit).
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn desugar(
        &self,
        local_scope: &str,
        stmt_idx: usize,
        options: &LiftOptions,
        reducer: &ReductionCtx<'_>,
        float_widths: &mut FloatWidthScope,
        reduced_helpers: &HashSet<String>,
        macro_depth: usize,
        factory_audits: Option<&FactoryAuditLog>,
    ) -> CallsiteOutcome {
        desugar_substituted_stmts(
            &self.name,
            &self.helper.block.stmts,
            &self.closed_args,
            local_scope,
            stmt_idx,
            options,
            reducer,
            float_widths,
            reduced_helpers,
            macro_depth,
            factory_audits,
        )
    }
}

impl MethodCallsiteSugar {
    pub(crate) fn decompose(
        expr: &Expr,
        scope: &TemporalScope,
        options: &LiftOptions,
        macro_depth: usize,
    ) -> Option<MethodCallsiteSugar> {
        if macro_depth >= MAX_MACRO_EXPANSION_DEPTH {
            return None;
        }
        let (helper, name, closed_args) =
            resolve_inlinable_method_call_scoped(expr, scope, options)?;
        Some(MethodCallsiteSugar {
            helper,
            name,
            closed_args,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn desugar(
        &self,
        local_scope: &str,
        stmt_idx: usize,
        options: &LiftOptions,
        reducer: &ReductionCtx<'_>,
        float_widths: &mut FloatWidthScope,
        reduced_helpers: &HashSet<String>,
        macro_depth: usize,
        factory_audits: Option<&FactoryAuditLog>,
    ) -> CallsiteOutcome {
        desugar_substituted_stmts(
            &self.name,
            &self.helper.block.stmts,
            &self.closed_args,
            local_scope,
            stmt_idx,
            options,
            reducer,
            float_widths,
            reduced_helpers,
            macro_depth,
            factory_audits,
        )
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_substituted_stmts(
    name: &str,
    stmts: &[Stmt],
    closed_args: &ExprBindings,
    local_scope: &str,
    stmt_idx: usize,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    reduced_helpers: &HashSet<String>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> CallsiteOutcome {
    let mut subst = substitute_stmts(stmts, closed_args);
    drop_assertion_free_tail_value(&mut subst);
    let mut te: Vec<AssertionEntry> = Vec::new();
    let mut ts: Vec<String> = Vec::new();
    let mut tl = 0usize;
    let mut th = reduced_helpers.clone();
    if stmts_have_runtime_terminal_body_shape(&subst) {
        let count = count_asserts_in_stmts(&subst);
        if count == 0 {
            return CallsiteOutcome::Bail(BailCause::NotInlinable);
        }
        th.insert(name.to_string());
        return CallsiteOutcome::Complete(InlineCommit {
            entries: te,
            skipped: vec![helper_body_runtime_terminal_reason(name); count],
            macros_lifted: tl,
            reduced_helpers: th,
            name: name.to_string(),
        });
    }
    let trial_options;
    let trial_options_ref = if options.panic_freedom_enabled() {
        trial_options = options.clone().without_panic_freedom();
        &trial_options
    } else {
        options
    };
    collect_assertion_entries(
        &subst,
        &child_block_scope(local_scope, stmt_idx),
        trial_options_ref,
        reducer,
        float_widths,
        &mut te,
        &mut ts,
        &mut tl,
        &mut th,
        factory_audits,
        macro_depth + 1,
        &BTreeSet::new(),
        None,
        &crate::MacroRegistry::new(),
        &BTreeMap::new(),
        &crate::FnRegistry::new(),
        &crate::LayoutTypeRegistry::new(),
    );
    let unclassified: Vec<&String> = ts
        .iter()
        .filter(|r| matches!(refusal_disposition(r), Disposition::Unclassified))
        .collect();
    if unclassified.is_empty() {
        if te.is_empty() && ts.is_empty() && tl == 0 {
            return CallsiteOutcome::Bail(BailCause::NotInlinable);
        }
        th.insert(name.to_string());
        CallsiteOutcome::Complete(InlineCommit {
            entries: te,
            skipped: ts,
            macros_lifted: tl,
            reduced_helpers: th,
            name: name.to_string(),
        })
    } else {
        let mut sample_reasons: Vec<String> = unclassified.iter().map(|r| (*r).clone()).collect();
        sample_reasons.sort();
        sample_reasons.dedup();
        CallsiteOutcome::Bail(BailCause::UnclassifiedResidue {
            added_unclassified: unclassified.len(),
            sample_reasons,
        })
    }
}

fn drop_assertion_free_tail_value(stmts: &mut Vec<Stmt>) {
    let Some(last) = stmts.last() else {
        return;
    };
    if !matches!(last, Stmt::Expr(_, None)) {
        return;
    }
    if count_asserts_in_stmts(std::slice::from_ref(last)) == 0 {
        stmts.pop();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP-1 CENSUS: categorize the residue of the 112 "reachable only via call-site
// inlining" asserts. For every non-`#[test]` helper that ends up NOT reduced, this
// classifies WHY its inline failed, by SHAPE of the unclassified residue. Pure
// diagnostic; never touches the lift counts or the wire format. Run via the
// `coretests_sweep --callsite-census` hook (stderr-only).
// ─────────────────────────────────────────────────────────────────────────────

/// One residue reason classified into a census bucket. The buckets mirror the
/// prompt's STEP-1 axes: pure-untranslated-term / unsupported-construct /
/// genuine-effect / non-closed-args.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum ResidueCategory {
    /// A pure-but-untranslated term: `unsupported term ...` that is NOT an order-loss
    /// effect (e.g. `1i32 as f64`, a pure stdlib method we have not transcribed). This
    /// STAYS UNCLASSIFIED -- honest future work for a Sugar/const-eval arm, never
    /// fake-refused.
    PureUntranslatedTerm,
    /// An unsupported CONSTRUCT: a control-flow / adaptor shape the body uses that the
    /// hierarchy does not yet complete through (an `if`/`while`/`match` branch, a bin-1
    /// literal-domain loop body, a closure adaptor, a nested unlifted expr stmt).
    UnsupportedConstruct,
    /// A genuine order-loss EFFECT that nonetheless surfaced as UNCLASSIFIED (it was
    /// not on the terminal whitelist). NOTE: a fully-effect body has
    /// added_unclassified == 0 and COMMITS; an effect only blocks an inline when it
    /// rides alongside other unclassified residue. Counted for completeness.
    GenuineEffect,
    /// The helper exposes no carryable closed-arg call site (runtime-opaque params, or
    /// simply never called with closeable actuals). The "reachable only" refusal is
    /// emitted by Pass 2 with no inline ever attempted.
    NonClosedArgs,
}

/// Classify a single unclassified residue reason string into a census bucket. Pure
/// over the reason text; mirrors the shapes the collector emits.
pub fn classify_residue_reason(reason: &str) -> ResidueCategory {
    // An order-loss effect reason that happens to be unclassified (not whitelisted).
    // These name a mutation / iterator-advance / opaque-runtime / mutable-read cause.
    let effect_markers = [
        "side-effecting closure body",
        "advances an iterator",
        "mutates captured state",
        "mutable container is not temporally stable",
        "temporally unstable",
        "ambiguous temporal identity",
        "opaque runtime",
        "opaque/effectful accessor",
    ];
    if effect_markers.iter().any(|m| reason.contains(m)) {
        return ResidueCategory::GenuineEffect;
    }
    // A pure-but-untranslated TERM: the term path could not translate a leaf, but the
    // leaf is not an order-loss effect (no `mut`/effect marker above). This is the
    // honest "we have not taught this term yet" residue.
    if reason.contains("unsupported term") {
        return ResidueCategory::PureUntranslatedTerm;
    }
    // Everything else unclassified is an unsupported CONSTRUCT: a control-flow shape
    // or adaptor the complete does not yet enter (`under for context`, bin-1 literal
    // domain, nested unlifted expr stmt, unsupported macro matcher, ...).
    ResidueCategory::UnsupportedConstruct
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        lift_file_with_macro_imports, refusal_disposition, sugar_ctx, Disposition, FloatWidthScope,
        LiftOptions, MacroRegistry, ReductionCtx, TemporalPlan, TemporalScope,
    };

    fn lift(src: &str) -> crate::AdapterOutput {
        let file = syn::parse_file(src).expect("parse");
        lift_file_with_macro_imports(
            &file,
            "test.rs",
            &LiftOptions::default(),
            &MacroRegistry::new(),
        )
    }

    fn reachable_only(out: &crate::AdapterOutput) -> usize {
        out.skip_reasons
            .iter()
            .filter(|r| r.contains("reachable only via call-site inlining"))
            .count()
    }

    fn discharged(out: &crate::AdapterOutput) -> usize {
        out.assertions_lifted
    }

    #[test]
    fn format_args_builtin_child_falls_back_for_panic_subject_identity() {
        let expr: Expr =
            syn::parse_str(r#"format_args!("Hello").estimated_capacity()"#).expect("parse expr");
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);

        let term = opaque_callsite_term(&ctx, &expr)
            .expect("format_args method call should produce a panic subject");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected callsite ctor, got {term:?}");
        };
        assert_eq!(name, "method:estimated_capacity#panic_callsite");
        assert_eq!(args.len(), 1);
        let Term::Ctor {
            name: receiver_name,
            args: receiver_args,
        } = args[0].as_ref()
        else {
            panic!("expected opaque receiver ctor, got {:?}", args[0]);
        };
        assert!(
            receiver_name.starts_with("opaque:callsite-child:")
                && receiver_name.contains("format_args"),
            "format_args! receiver should be an opaque callsite child, got {receiver_name}"
        );
        assert!(
            receiver_args.is_empty(),
            "opaque callsite child should not carry forged macro children"
        );
    }

    // ── DIG: a closed-arg call to a pure scalar helper INLINES and discharges. The
    // helper asserts `x == x`-shaped point-wise facts the term path can lift. ──
    #[test]
    fn closed_arg_call_to_pure_helper_inlines_and_discharges_no_reachable_only() {
        let out = lift(
            r#"
            fn check(x: i32) { assert_eq!(x + 0, x); }
            #[test]
            fn t() { check(3); }
            "#,
        );
        assert!(
            discharged(&out) >= 1,
            "the inlined body assert must discharge (commit), got {}",
            discharged(&out)
        );
        assert_eq!(
            reachable_only(&out),
            0,
            "a fully-digging inline must NOT leave a `reachable only` refusal"
        );
    }

    // ── REFUTABLE (not fake-green): a CONTRADICTORY inlined body is NOT laundered to
    // green. The inline commits (the body's assert lifts) and the verifier's
    // consistency pass would catch the contradiction -- the complete path is byte-identical,
    // so a false body is CAUGHT, not masked. We assert the assert is lifted as an atom
    // (entered the obligation set), not silently dropped. ──
    #[test]
    fn contradictory_inlined_body_is_lifted_not_silently_dropped() {
        let out = lift(
            r#"
            fn check(x: i32) { assert_eq!(x, x + 1); }
            #[test]
            fn t() { check(0); }
            "#,
        );
        // The contradictory assert MUST be accounted (lifted as an atom for the
        // consistency pass), never silently dropped -- the complete is refutable.
        assert!(
            discharged(&out) >= 1,
            "the contradictory body must be lifted as an obligation, not dropped"
        );
        assert_eq!(reachable_only(&out), 0);
    }

    // ── BAIL (honest): a helper whose inlined body leaves a genuinely UNCLASSIFIED
    // residue must NOT be force-committed -- it stays "reachable only" (Pass 2). This
    // is the bail direction of the monotonic gate (`added_unclassified == 0` to
    // commit). EFFECT-OR-LEAVE: an incomplete body is left unclassified, never fake-complete.
    //
    // The body's assert lives under a `closure` -- a closure body is NOT
    // unconditionally evaluated (it may never run, or runs per-call), so the
    // hierarchy classifies it UNCLASSIFIED (an honest WORK item, not a source
    // property). This is the SAME blocker the live corpus census reports for the
    // un-drained nested helpers (a body assert under a construct the complete does not
    // yet enter point-wise). The gate refuses to commit, so the helper is unreduced
    // and the single "reachable only via call-site inlining" refusal survives.
    // Soundness: the assert is accounted (no silent drop) and NOT laundered to a
    // fake discharge.
    //
    // NOTE: a `match`-arm body is NO LONGER such a residue -- `MatchSugar` partitions
    // the arms into `⋀_i (guard_i => A_i)` and discharges them. This test now uses a
    // closure body (still un-entered) to exercise the BAIL direction of the gate.
    #[test]
    fn helper_with_unclassified_body_residue_bails_to_reachable_only() {
        let out = lift(
            r#"
            fn check(n: i32) { let f = || assert!(n > 0); f(); }
            #[test]
            fn t() { check(5); }
            "#,
        );
        let accounted = out.assertions_lifted + out.assertions_refused;
        assert!(accounted >= 1, "the assert must be accounted, not dropped");
        // The branch-partitioned body must NOT commit: it stays "reachable only" and is
        // classified UNCLASSIFIED (lifter work), never refused as a source property and
        // never fake-discharged as green.
        assert!(
            reachable_only(&out) >= 1
                && out
                    .skip_reasons
                    .iter()
                    .any(|r| matches!(refusal_disposition(r), Disposition::Unclassified)),
            "an unclassified-residue body must BAIL (reachable-only + unclassified); reasons={:?}",
            out.skip_reasons
        );
    }

    // ── UNINTERPRETED-LIFT IS NOT A FALSE GREEN: a helper body asserting over an
    // opaque sub-term (a runtime call result) lifts that sub-term as an UNINTERPRETED
    // symbol -- a sound point-wise obligation `gt(uf, 0)`, exactly as the term path
    // does at top level (the inline is byte-identical to the complete path). This is the
    // stated-not-derived discipline: the vendor's point-wise claim at this call is
    // recorded as an obligation the consistency pass checks; it does NOT assert the
    // helper is universally true. The inline therefore commits and is accounted (no
    // silent drop), and crucially is NOT a fabricated discharge of an unprovable
    // universal. ──
    #[test]
    fn opaque_subterm_lifts_as_sound_uninterpreted_obligation_no_silent_drop() {
        let out = lift(
            r#"
            fn check(x: i32) { assert!(some_runtime_call(x).field > 0); }
            #[test]
            fn t() { check(1); }
            "#,
        );
        // Accounted (lifted as an uninterpreted obligation), never silently dropped.
        assert!(
            out.assertions_lifted + out.assertions_refused >= 1,
            "the assert is accounted (lifted or refused), not silently dropped"
        );
        assert!(
            out.assertions_lifted >= 1,
            "the opaque-subterm relation lifts as a sound uninterpreted obligation, \
             got lifted={}",
            out.assertions_lifted
        );
    }

    // ── CENSUS classifier: the three unclassified shapes map to distinct buckets, and
    // a pure-but-untranslated term is NEVER classified as a genuine effect (the
    // fake-refuse guard, in classifier form). ──
    #[test]
    fn classify_residue_separates_pure_term_from_effect_and_construct() {
        assert_eq!(
            classify_residue_reason("assert_eq!: unsupported term `1i32 as f64`"),
            ResidueCategory::PureUntranslatedTerm,
            "a pure cast term is pure-untranslated, NOT an effect"
        );
        assert_eq!(
            classify_residue_reason(
                "unsupported term `a[i]`: mutable container is not temporally stable"
            ),
            ResidueCategory::GenuineEffect,
            "a mutable-container read is a genuine effect"
        );
        assert_eq!(
            classify_residue_reason(
                "assertion under for context over a literal range (bin-1: domain constructed, body not yet point-wise liftable); not unconditional point-wise; released to layer 0"
            ),
            ResidueCategory::UnsupportedConstruct,
            "a bin-1 for-loop body is an unsupported construct"
        );
    }

    // ── The classifier must not misclassify a pure term carrying the word "iterator"
    // in a value position as an effect unless it names an advance. (Adversarial: the
    // effect markers are specific phrases, not bare substrings like `iter`.) ──
    #[test]
    fn classify_does_not_overreach_on_pure_terms() {
        assert_eq!(
            classify_residue_reason("assert_eq!: unsupported term `Foo::ITER_CONST`"),
            ResidueCategory::PureUntranslatedTerm,
        );
    }

    // ── THE DRAIN: a helper defined INSIDE a `#[test]` fn body, called with closed
    // args, INLINES at the call sites and is NOT left as "reachable only". This is the
    // corpus's dominant blocked shape (slice.rs `fn test<T>(x)`, char.rs `fn check`).
    // Before the drain, a nested helper was invisible to the global reducer, so its
    // body asserts fell to "reachable only" unclassified even when the body completes.
    // Resolving `local_fns` first (in `decompose`) plus DEFERRING the nested-fn-
    // definition refusal (block-local Pass-2 in the collector) makes a nested closed-
    // arg helper inline exactly like a top-level one. SOUNDNESS: same monotonic gate;
    // a discriminating second call site with a DIFFERENT arg must NOT collapse onto the
    // first (distinct point-wise obligations), or a contradiction across calls would be
    // masked. ──
    #[test]
    fn nested_in_test_helper_with_closed_args_inlines_not_reachable_only() {
        let out = lift(
            r#"
            #[test]
            fn drives() {
                fn check(n: i32) { assert_eq!(probe(n), n); }
                check(2);
                check(3);
            }
            "#,
        );
        // The nested helper must be drained: NOT left as a "reachable only" refusal.
        assert_eq!(
            reachable_only(&out),
            0,
            "a nested closed-arg helper must inline (drain), not be left reachable-only: {:?}",
            out.skip_reasons
        );
        // It discharges point-wise per call site (the inline commits via the complete path).
        assert!(
            discharged(&out) >= 1,
            "the inlined nested-helper body must discharge: {}",
            discharged(&out)
        );
        // DISCRIMINATION: two call sites with DIFFERENT args must produce DISTINCT
        // probe obligations, never collapse to one (which would hide a cross-call
        // contradiction). At least two distinct probe-bearing decls.
        let probes: Vec<&str> = out
            .decls
            .iter()
            .map(|d| d.name.as_str())
            .filter(|n| n.contains("probe"))
            .collect();
        assert!(
            probes.len() >= 2 || out.decls.len() >= 2,
            "expected a distinct probe obligation per closed call site (no collapse): {:?}",
            out.decls.iter().map(|d| &d.name).collect::<Vec<_>>()
        );
    }

    // ── BUCKET 1 (assert-prefixed nested helper resolved lexically): an `assert_*`-
    // prefixed helper defined INSIDE the `#[test]` fn body, called as a bare statement,
    // is resolved via `local_fns` (not the global registry) and its body re-completes. A
    // pure point-wise body discharges -- this is the "has no visible source" drain when
    // the body is liftable. ──
    #[test]
    fn nested_assert_prefixed_helper_resolves_lexically_and_digs() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                fn assert_small(n: i32) { assert!(n < 10); }
                assert_small(3);
            }
            "#,
        );
        assert!(
            discharged(&out) >= 1,
            "a lexically-resolved nested assert_* helper with a pure body must discharge: {} / {:?}",
            discharged(&out),
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("has no visible source")),
            "the nested helper must resolve (no `has no visible source`): {:?}",
            out.skip_reasons
        );
    }

    // ── BUCKET 1 BAD-TWIN (RESOLVE-THEN-CLASSIFY, honest non-complete): a nested `assert_*`
    // helper whose body is RUNTIME (a `let mut` mutable-local trajectory) must NOT be
    // fake-complete. It resolves lexically (its source is now SHOWN), and its `let mut`
    // trajectory is a SOURCE property (a mutated local has no single timeless `t`, kin to
    // `temporally unstable`) -- so it is terminal-REFUSED with a named effect, never
    // discharged. (Mirrors the real corpus `assert_exact_exp`'s `let mut writer`; the
    // `assert_predicates_exact` collection twin is covered below.) The KEY guarantee: the
    // body is accounted and NOT discharged (no fake-complete). ──
    #[test]
    fn nested_assert_prefixed_helper_with_runtime_body_is_refused_not_fake_complete() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                fn assert_built(n: i32) {
                    let mut acc = 0;
                    acc += n;
                    assert_eq!(acc, n);
                }
                assert_built(3);
            }
            "#,
        );
        let accounted = out.assertions_lifted + out.assertions_refused;
        assert!(accounted >= 1, "the assert must be accounted, not dropped");
        assert_eq!(
            discharged(&out),
            0,
            "a runtime `let mut` body must NOT be fake-complete: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "a resolved runtime-body nested helper must be terminal-REFUSED (named effect): {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn bound_format_args_to_string_uses_format_value_floor() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                let a = format_args!("hello {}", "there");
                assert_eq!(a.to_string(), "hello there");
            }
            "#,
        );

        assert!(
            discharged(&out) >= 1,
            "bound format_args!.to_string() should discharge through the format-value floor: {:?}",
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons
                .iter()
                .any(|reason| reason.contains("macro `format_args`")),
            "format_args! must not reach generic macro fallback: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn shadowed_format_args_capture_uses_previous_binding_floor() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                let a = format_args!("hello");
                let a = format_args!("hello {a}");
                let a = format_args!("hello {a:1}");
                let a = format_args!("hello {a} {a:?}");
                assert_eq!(a.to_string(), "hello hello hello hello hello hello hello");
            }
            "#,
        );

        assert!(
            discharged(&out) >= 1,
            "shadowed format_args! captures should dispatch through the previous binding floor: {:?}",
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons
                .iter()
                .any(|reason| reason.contains("self-referential")),
            "format_args! capture shadowing must not be treated as self-reference: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn write_fmt_format_args_refuses_as_fmt_write_not_macro_gap() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                use core::fmt::Write;

                struct Buf(String);

                impl Write for Buf {
                    fn write_str(&mut self, s: &str) -> core::fmt::Result {
                        self.0.write_str(s)
                    }
                }

                let mut buf = Buf(String::new());
                buf.write_fmt(format_args!("a")).unwrap();
                assert_eq!(buf.0, "a");
            }
            "#,
        );

        assert!(
            out.skip_reasons.iter().any(|reason| {
                reason.contains("mutable-local state machine driven by fmt-write")
                    || reason.contains("temporally unstable mutating method read")
            }),
            "write_fmt(format_args!(...)) should be owned by a writer mutation effect, not macro fallback: {:?}",
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons
                .iter()
                .any(|reason| reason.contains("macro `format_args`")),
            "format_args! must not reach generic macro fallback: {:?}",
            out.skip_reasons
        );
    }

    // ── BUCKET 1 COLLECTION TWIN (RESOLVE-THEN-CLASSIFY): a nested helper whose body is a
    // RUNTIME ITERATOR/COLLECTION construct (`xs.iter().map(..).collect()`) resolves
    // lexically and is terminal-REFUSED (bin-2 runtime aggregate data), never fake-complete.
    // Mirrors the real corpus `mem/type_info.rs::assert_predicates_exact`. ──
    #[test]
    fn nested_assert_prefixed_helper_with_collection_body_is_refused_not_fake_complete() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                fn assert_collected(xs: &[u32]) {
                    let ys: Vec<u32> = xs.iter().copied().collect();
                    assert_eq!(xs.len(), ys.len());
                }
                let data = [1u32, 2u32, 3u32];
                assert_collected(&data);
            }
            "#,
        );
        let accounted = out.assertions_lifted + out.assertions_refused;
        assert!(accounted >= 1, "the assert must be accounted, not dropped");
        assert_eq!(
            discharged(&out),
            0,
            "a runtime collection body must NOT be fake-complete: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| matches!(refusal_disposition(r), Disposition::Refused)
                    && r.contains("collection")),
            "a resolved collection-body nested helper must be terminal-REFUSED (bin-2): {:?}",
            out.skip_reasons
        );
    }

    // ── DISCRIMINATION (the fake-refuse guardrail): a nested helper whose body is PURE
    // (no `let mut`, no collection construct) still DIGS when resolved -- a pure `let`
    // binding folds and the assert discharges. This proves the runtime-body refusal is
    // EARNED by the runtime shape, not a blanket relabel of every resolved helper. ──
    #[test]
    fn nested_assert_prefixed_helper_with_pure_let_body_digs() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                fn assert_doubled(n: i32) {
                    let twice = n + n;
                    assert_eq!(twice, n * 2);
                }
                assert_doubled(4);
            }
            "#,
        );
        assert!(
            discharged(&out) >= 1,
            "a pure-let nested helper body must DIG (no fake-refuse): {} / {:?}",
            discharged(&out),
            out.skip_reasons
        );
    }

    // ── BUCKET 2 (arg-position closed-literal inlining): a concrete nested helper called
    // ONLY in argument position (`outer(helper(LIT))`, never as a bare statement) has its
    // INTERNAL assert lifted point-wise at the literal call sites. This is the `zero_byte`
    // shape: `assert_ne!(hash(&val), hash(&zero_byte(val, 0)))` -- the internal
    // `assert!(byte < 8)` completes with `byte := 0`, even though `val` is runtime (the assert
    // does not read it). ──
    #[test]
    fn arg_position_concrete_helper_internal_assert_digs_at_literal_sites() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                let val = some_runtime();
                assert_ne!(opaque(&val), opaque(&masked(val, 0)));
                assert_ne!(opaque(&val), opaque(&masked(val, 1)));
                fn masked(val: u64, byte: usize) -> u64 {
                    assert!(byte < 8);
                    val & !(0xff << (byte * 8))
                }
            }
            "#,
        );
        // The internal `assert!(byte < 8)` is lifted point-wise at the two literal sites.
        assert!(
            discharged(&out) >= 2,
            "the internal assert must lift at each distinct literal site (>=2): {} / {:?}",
            discharged(&out),
            out.skip_reasons
        );
        // The helper's body assert is no longer left as a "reachable only" refusal.
        assert_eq!(
            reachable_only(&out),
            0,
            "an arg-position-inlined concrete helper must not stay reachable-only: {:?}",
            out.skip_reasons
        );
    }

    // ── BUCKET 2 BAD-TWIN (no forged pin): a concrete arg-position helper whose INTERNAL
    // assert reads a RUNTIME actual must NOT be force-discharged. With `n := runtime`, the
    // body assert `n == 7` reads an opaque value; it must NOT manufacture a closed `7 == 7`
    // -- either the site bails (helper stays reachable-only) or `n` lifts as an
    // uninterpreted obligation, never a fabricated closed truth. ──
    #[test]
    fn arg_position_helper_with_runtime_assert_actual_does_not_forge_a_pin() {
        let out = lift(
            r#"
            #[test]
            fn t() {
                let runtime = some_call();
                assert_ne!(opaque(&runtime), opaque(&checked(runtime)));
                fn checked(n: i32) -> i32 {
                    assert_eq!(n, 7);
                    n
                }
            }
            "#,
        );
        let claims_seven_as_closed = out.decls.iter().any(|d| {
            let dump = format!("{:?}", d.inv);
            dump.contains("Int(7)") && !dump.contains("runtime") && !dump.contains("some_call")
        });
        assert!(
            !claims_seven_as_closed,
            "a runtime actual the assert reads must not forge a closed `7 == 7`: {:?}",
            out.decls
                .iter()
                .map(|d| format!("{:?}", d.inv))
                .collect::<Vec<_>>()
        );
    }

    // ── DRAIN GUARD (no over-reach): a nested helper called with a NON-closed actual
    // (a free local, not a source literal) must NOT manufacture a pinned obligation --
    // the body reads runtime data no call site supplies as a literal. Either the inline
    // bails (helper stays reachable-only) or the body lifts the free var as a sound
    // uninterpreted symbol; in NEITHER case is a closed value forged. We assert the
    // free-actual case never claims more discharge than the closed-actual case for the
    // SAME helper (no fabricated pin). ──
    #[test]
    fn nested_helper_with_non_closed_actual_does_not_forge_a_pin() {
        let out = lift(
            r#"
            #[test]
            fn drives() {
                fn check(n: i32) { assert_eq!(n, 7); }
                let runtime = some_call();
                check(runtime);
            }
            "#,
        );
        // `runtime` is not a literal. The assert `n == 7` with `n := runtime` must NOT
        // be discharged as a closed truth (`runtime` is opaque). It is either refused
        // (reachable-only / unclassified) or lifted as an uninterpreted obligation the
        // consistency pass checks -- never a fabricated `7 == 7`.
        let claims_seven_as_closed = out.decls.iter().any(|d| {
            let dump = format!("{:?}", d.inv);
            dump.contains("Int(7)") && !dump.contains("runtime") && !dump.contains("some_call")
        });
        assert!(
            !claims_seven_as_closed,
            "a non-closed actual must not forge a closed pin: {:?}",
            out.decls
                .iter()
                .map(|d| format!("{:?}", d.inv))
                .collect::<Vec<_>>()
        );
    }
}
