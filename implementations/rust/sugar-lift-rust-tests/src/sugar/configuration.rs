// SPDX-License-Identifier: Apache-2.0
//
//! `#[cfg(..)]` as a FIRST-CLASS COMPOSING SUGAR.
//!
//! A `#[cfg(..)]`-attributed construct is sugar too: a CONFIGURATION PREDICATE over
//! pinned target facts that selects whether the wrapped construct EXISTS on this
//! target. Before this node, cfg resolution was hand-woven -- the same
//! `CfgEval::{Active|Inactive|Ambiguous}` three-arm dispatch (and the copy-pasted
//! `CfgEval::Ambiguous => return None` bail) was repeated at every cfg-attribution
//! point (match arms, items, statements, the `cfg!` guard). [`ConfigurationSugar`]
//! collapses that into ONE composing node: wrap a cfg-attributed inner `Sugar`, resolve
//! the predicate ONCE, and compose:
//!
//!   * **Active**    -> desugar the wrapped inner `Sugar` (the construct exists here).
//!   * **Inactive**  -> `Dug(Seq[])` -- the no-op / empty floor (rustc strips the
//!     construct pre-codegen, so it contributes nothing; NOT a refusal).
//!   * **Ambiguous** -> `Hit(Effect::Unsupported { "ambiguous cfg: <reason>" })` -- with
//!     no target facts we honestly cannot resolve it. By the no-scan / `Outcome` law this
//!     HITS (a named, terminal effect); it is NEVER a silent skip.
//!
//! The resolution is the EXISTING `cfg_eval_for_attrs` over the pinned target facts
//! (`SugarCtx::options.target_cfg`) -- a SEMANTIC predicate evaluation, never a syntactic
//! body scan. This node does not change WHAT cfg decides; it makes that decision COMPOSE
//! as a `Sugar`, so a cfg-gated ANYTHING flows through build + desugar for free.

use syn::Attribute;

use crate::{
    cfg_eval_for_attrs, cfg_eval_predicate, CfgEval, CfgPredicate, Desugared, Effect, LiftOptions,
    Outcome, Sugar, SugarCtx,
};

/// The composed disposition of a `#[cfg(..)]`-attributed construct over the pinned target
/// facts -- the SINGLE three-way vocabulary every cfg-attribution site speaks. It is the
/// composition of the raw [`CfgEval`] predicate result into "what the engine does with the
/// wrapped construct", computed in ONE place ([`resolve`]):
///   * `Present` -- the construct exists on this target (include / desugar it).
///   * `Absent(reason)` -- rustc strips it before codegen (a no-op: drop it / account it
///     inactive); `reason` is the inactive predicate, carried verbatim for the emit string.
///   * `Ambiguous(reason)` -- no pinned facts, so we honestly cannot resolve it (bail / Hit).
/// Sites match on THIS, never on a re-derived `CfgEval::{Active|Inactive|Ambiguous}` dispatch.
/// It carries the same two reason strings `CfgEval` did, so a site's emitted skip string is
/// byte-identical -- this is a 1:1 composition of the predicate result, not a re-decision.
pub(crate) enum CfgDisposition {
    Present,
    Absent(String),
    Ambiguous(String),
}

/// Resolve the `#[cfg(..)]` attrs of a construct against the pinned target facts -- the ONE
/// place the engine turns a cfg predicate into a [`CfgDisposition`]. REUSES the existing
/// `cfg_eval_for_attrs` (a SEMANTIC predicate evaluation over `options.target_cfg`, never a
/// syntactic body scan); this only composes its result into the engine's disposition
/// vocabulary. Every cfg-attribution point routes through here, so the formerly copy-pasted
/// `match cfg_eval_for_attrs { Active/Inactive/Ambiguous }` dispatch lives in a single body.
pub(crate) fn resolve(attrs: &[Attribute], options: &LiftOptions) -> CfgDisposition {
    compose(cfg_eval_for_attrs(attrs, options))
}

/// Resolve a SINGLE cfg `predicate` (a `cfg!(..)` guard, a synthetic `debug_assertions`
/// gate) against the pinned target facts -- the predicate analogue of [`resolve`] for the
/// sites that hold a parsed [`CfgPredicate`] rather than an attribute list. REUSES the
/// existing `cfg_eval_predicate` verbatim; this only composes its result into the shared
/// [`CfgDisposition`] vocabulary, so the predicate sites speak the same three-way language
/// as the attribute sites and the formerly copy-pasted dispatch lives in one body.
pub(crate) fn resolve_predicate(predicate: &CfgPredicate, options: &LiftOptions) -> CfgDisposition {
    compose(cfg_eval_predicate(predicate, options.target_cfg.as_ref()))
}

/// Compose a raw [`CfgEval`] predicate result into the engine's [`CfgDisposition`] -- the ONE
/// mapping shared by [`resolve`] and [`resolve_predicate`]. A 1:1 translation that carries
/// both reason strings verbatim (so every site's emit string is byte-identical).
fn compose(eval: CfgEval) -> CfgDisposition {
    match eval {
        CfgEval::Active => CfgDisposition::Present,
        CfgEval::Inactive(reason) => CfgDisposition::Absent(reason),
        CfgEval::Ambiguous(reason) => CfgDisposition::Ambiguous(reason),
    }
}

/// A cfg-attributed construct: the `#[cfg(..)]` attrs paired with the inner `Sugar` they
/// gate. `desugar` resolves the predicate ONCE (via [`resolve`]) and either digs the inner
/// (Present), digs the empty floor (Absent), or Hits the ambiguous-cfg boundary. The wrapped
/// `inner` is built unconditionally by the factory; this node decides -- purely from the
/// pinned target facts -- whether it CONTRIBUTES. This is the canonical composing form of a
/// cfg-gated construct; the collector sites that cannot yield a single `Outcome` (they emit
/// site-specific skip strings / counts) still resolve through [`resolve`], the same body.
pub(crate) struct ConfigurationSugar {
    attrs: Vec<Attribute>,
    inner: Box<dyn Sugar>,
}

impl ConfigurationSugar {
    /// Wrap an inner `Sugar` with the `#[cfg(..)]` attrs that gate it.
    pub(crate) fn new(attrs: Vec<Attribute>, inner: Box<dyn Sugar>) -> Self {
        Self { attrs, inner }
    }

    /// This node's [`CfgDisposition`] over the pinned target facts -- the single
    /// resolution `desugar` composes on. Exposed so a build-time caller that holds only
    /// `options` (no `SugarCtx`) -- e.g. a `match`-arm filter deciding which arms exist on
    /// this target -- can ask THE NODE for its disposition (build the node, ask it), rather
    /// than re-deriving a `CfgEval` dispatch inline. The desugar arms are the disposition's
    /// composition into an `Outcome`; this is the disposition itself.
    pub(crate) fn disposition(&self, options: &LiftOptions) -> CfgDisposition {
        resolve(&self.attrs, options)
    }
}

impl Sugar for ConfigurationSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.disposition(ctx.options) {
            // The construct exists on this target: compose straight through to the inner.
            CfgDisposition::Present => self.inner.desugar(ctx),
            // Stripped on this target (like rustc pre-codegen): the empty literal floor,
            // a no-op that contributes nothing. NOT a refusal -- inactive is not in this
            // target's universe.
            CfgDisposition::Absent(_) => Outcome::Dug(Desugared::Seq(Vec::new())),
            // No pinned target facts -> we cannot resolve the predicate. The no-scan law:
            // a named, terminal Hit, never a silent skip.
            CfgDisposition::Ambiguous(reason) => Outcome::Hit(Effect::Unsupported {
                reason: format!("ambiguous cfg: {reason}"),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TargetCfg};

    // A stub inner child that digs to a single-element sequence floor (its presence is
    // observable as a non-empty `Seq`), ignoring `ctx`.
    struct StubInner;
    impl Sugar for StubInner {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Dug(Desugared::Seq(vec![crate::DesugaredElem {
                expr: syn::parse_quote!(1),
                value: None,
            }]))
        }
    }

    fn run(attrs: Vec<Attribute>, options: &LiftOptions) -> Outcome {
        let scope = crate::TemporalScope::new("test", crate::TemporalPlan::default());
        let items: Vec<syn::Item> = Vec::new();
        let reducer = crate::ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let ctx = crate::sugar_ctx(&scope, options, &reducer, &mut float_widths, 0);
        let node = ConfigurationSugar::new(attrs, Box::new(StubInner));
        node.desugar(&ctx)
    }

    // A `#[cfg(..)]` attribute parsed from its predicate tokens.
    fn cfg_attr(pred: proc_macro2::TokenStream) -> Attribute {
        syn::parse_quote!(#[cfg(#pred)])
    }

    #[test]
    fn active_cfg_composes_through_to_inner() {
        // target_os = "linux" with linux pinned -> Active -> the inner's `Seq[1]` floor.
        let target = TargetCfg::from_rustc_cfg_facts(["target_os=\"linux\""]).unwrap();
        let options = LiftOptions::for_target_cfg(target);
        match run(vec![cfg_attr(quote::quote!(target_os = "linux"))], &options) {
            Outcome::Dug(Desugared::Seq(s)) => assert_eq!(s.len(), 1, "inner floor flows through"),
            Outcome::Dug(_) => panic!("expected the inner's Dug(Seq[1]), got a different Dug"),
            Outcome::Hit(_) => panic!("expected the inner's Dug(Seq[1]), got Hit"),
        }
    }

    #[test]
    fn inactive_cfg_digs_the_empty_floor() {
        // target_os = "windows" with only linux pinned -> Inactive -> empty `Seq[]`,
        // the no-op floor (stripped on this target), NOT a Hit.
        let target = TargetCfg::from_rustc_cfg_facts(["target_os=\"linux\""]).unwrap();
        let options = LiftOptions::for_target_cfg(target);
        match run(vec![cfg_attr(quote::quote!(target_os = "windows"))], &options) {
            Outcome::Dug(Desugared::Seq(s)) => {
                assert!(s.is_empty(), "inactive strips to the empty no-op floor")
            }
            Outcome::Dug(_) => panic!("expected Dug(Seq[]), got a different Dug"),
            Outcome::Hit(_) => panic!("expected Dug(Seq[]), inactive must NOT Hit"),
        }
    }

    #[test]
    fn ambiguous_cfg_hits_unsupported_not_silent() {
        // No target_cfg pinned at all -> Ambiguous -> Hit(Unsupported "ambiguous cfg: ..").
        // The no-scan law: it HITS, it is not a silent skip.
        let options = LiftOptions::default();
        match run(vec![cfg_attr(quote::quote!(target_os = "linux"))], &options) {
            Outcome::Hit(Effect::Unsupported { reason }) => {
                assert!(
                    reason.starts_with("ambiguous cfg: "),
                    "ambiguous cfg names its boundary, got {reason:?}"
                );
            }
            Outcome::Hit(_) => panic!("expected Hit(Unsupported), got a different Hit"),
            Outcome::Dug(_) => panic!("ambiguous cfg must HIT (no-scan law), not Dug"),
        }
    }

    #[test]
    fn no_cfg_attrs_is_active_and_composes() {
        // An empty attr set -> `cfg_eval_for_attrs` is Active -> inner flows through.
        let options = LiftOptions::default();
        match run(Vec::new(), &options) {
            Outcome::Dug(Desugared::Seq(s)) => assert_eq!(s.len(), 1),
            Outcome::Dug(_) => panic!("expected the inner's Dug(Seq[1]), got a different Dug"),
            Outcome::Hit(_) => panic!("no cfg attrs is Active; expected Dug, got Hit"),
        }
    }
}
