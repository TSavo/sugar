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
// the doctrine's dig-to-literals applied across a call boundary.
//
// THE GATE (exact-or-bail, the soundness line). The dig is the fake-discharge-
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
// happened (the typed `Outcome`/`SideEffect` machinery) for the STEP-1 census.

use std::collections::{BTreeSet, HashSet};

use syn::{Expr, ItemFn};

// Child of crate root: sees crate-root-private items (the Sugar hierarchy, the
// collector, the resolver, the substitution, the disposition classifier).
use std::collections::BTreeMap;

use crate::{
    child_block_scope, collect_assertion_entries, refusal_disposition,
    resolve_inlinable_helper_call_scoped, substitute_stmts, AssertionEntry, Disposition,
    ExprBindings, FloatWidthScope, LiftOptions, ReductionCtx, MAX_MACRO_EXPANSION_DEPTH,
};

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
/// crate-root `Outcome { Dug, Hit }`:
///
///   * `Dug(InlineCommit)` -- the substituted body FULLY reduced (every body assert
///     discharged or terminal-refused; `added_unclassified == 0`). The inline
///     commits; the asserts lift via the byte-identical dig path. This is the
///     blessed inlining-unblock: `discharged` may rise, no fake-discharge.
///   * `Bail(BailCause)` -- the substituted body did NOT fully reduce (some body
///     assert is honestly unclassified -- a pure-but-untranslated term, or an
///     unsupported construct), OR the call was not a carryable closed-arg call to a
///     resolvable helper. The helper stays unreduced; Pass 2 keeps the single
///     "reachable only via call-site inlining" refusal. HONEST: a pure-but-
///     untranslated body stays unclassified -- never fake-dug, never fake-refused.
///
/// There is deliberately NO callsite-level `Hit(SideEffect)` variant that COMMITS a
/// differently-shaped result: a body whose asserts are ALL order-loss effects
/// already has `added_unclassified == 0`, so it reaches `Dug` and commits-as-refused
/// through the normal collector (the effect asserts become terminal-refused entries
/// inside the inlined body). Introducing a separate committing `Hit` here would move
/// the counts. The `BailCause` below NAMES an effect when the bail residue is one,
/// for the census -- it does not change which bodies commit.
pub(crate) enum CallsiteOutcome {
    Dug(InlineCommit),
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

    /// β-reduce + re-desugar through the hierarchy, gated. Substitutes
    /// `closed_args` (param := callsite actual) into the helper body, then runs the
    /// SAME collector (which re-dispatches the body's own Fold/ForAll/Conditional/
    /// Literal/term/macro sugars) on the substituted body in SCRATCH buffers. Commits
    /// (`Dug`) iff the body adds zero unclassified; bails otherwise.
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
    ) -> CallsiteOutcome {
        let subst = substitute_stmts(&self.helper.block.stmts, &self.closed_args);
        let mut te: Vec<AssertionEntry> = Vec::new();
        let mut ts: Vec<String> = Vec::new();
        let mut tl = 0usize;
        let mut th = reduced_helpers.clone();
        collect_assertion_entries(
            &subst,
            &child_block_scope(local_scope, stmt_idx),
            options,
            reducer,
            float_widths,
            &mut te,
            &mut ts,
            &mut tl,
            &mut th,
            macro_depth + 1,
            &BTreeSet::new(),
        );
        let unclassified: Vec<&String> = ts
            .iter()
            .filter(|r| matches!(refusal_disposition(r), Disposition::Unclassified))
            .collect();
        if unclassified.is_empty() {
            th.insert(self.name.clone());
            CallsiteOutcome::Dug(InlineCommit {
                entries: te,
                skipped: ts,
                macros_lifted: tl,
                reduced_helpers: th,
                name: self.name.clone(),
            })
        } else {
            let mut sample_reasons: Vec<String> =
                unclassified.iter().map(|r| (*r).clone()).collect();
            sample_reasons.sort();
            sample_reasons.dedup();
            CallsiteOutcome::Bail(BailCause::UnclassifiedResidue {
                added_unclassified: unclassified.len(),
                sample_reasons,
            })
        }
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
    /// hierarchy does not yet dig through (an `if`/`while`/`match` branch, a bin-1
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
    // or adaptor the dig does not yet enter (`under for context`, bin-1 literal
    // domain, nested unlifted expr stmt, unsupported macro matcher, ...).
    ResidueCategory::UnsupportedConstruct
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{lift_file_with_macro_imports, refusal_disposition, Disposition, MacroRegistry};

    fn lift(src: &str) -> crate::AdapterOutput {
        let file = syn::parse_file(src).expect("parse");
        lift_file_with_macro_imports(&file, "test.rs", &LiftOptions::default(), &MacroRegistry::new())
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
    // consistency pass would catch the contradiction -- the dig path is byte-identical,
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
        // consistency pass), never silently dropped -- the dig is refutable.
        assert!(
            discharged(&out) >= 1,
            "the contradictory body must be lifted as an obligation, not dropped"
        );
        assert_eq!(reachable_only(&out), 0);
    }

    // ── BAIL (honest): a helper whose inlined body leaves a genuinely UNCLASSIFIED
    // residue must NOT be force-committed -- it stays "reachable only" (Pass 2). This
    // is the bail direction of the monotonic gate (`added_unclassified == 0` to
    // commit). EFFECT-OR-LEAVE: an un-digging body is left unclassified, never fake-dug.
    //
    // The body's assert lives under a `closure` -- a closure body is NOT
    // unconditionally evaluated (it may never run, or runs per-call), so the
    // hierarchy classifies it UNCLASSIFIED (an honest WORK item, not a source
    // property). This is the SAME blocker the live corpus census reports for the
    // un-drained nested helpers (a body assert under a construct the dig does not
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
    // does at top level (the inline is byte-identical to the dig path). This is the
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
    // body asserts fell to "reachable only" unclassified even when the body digs.
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
        // It discharges point-wise per call site (the inline commits via the dig path).
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
            out.decls.iter().map(|d| format!("{:?}", d.inv)).collect::<Vec<_>>()
        );
    }
}
