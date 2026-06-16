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

use crate::{cfg_eval_for_attrs, CfgEval, Desugared, Effect, Outcome, Sugar, SugarCtx};

/// A cfg-attributed construct: the `#[cfg(..)]` attrs paired with the inner `Sugar` they
/// gate. `desugar` resolves the predicate ONCE (the single place cfg composes) and either
/// digs the inner (Active), digs the empty floor (Inactive), or Hits the ambiguous-cfg
/// boundary (Ambiguous). The wrapped `inner` is built unconditionally by the factory; this
/// node decides -- purely from the pinned target facts -- whether it CONTRIBUTES.
pub(crate) struct ConfigurationSugar {
    attrs: Vec<Attribute>,
    inner: Box<dyn Sugar>,
}

impl ConfigurationSugar {
    /// Wrap an inner `Sugar` with the `#[cfg(..)]` attrs that gate it.
    pub(crate) fn new(attrs: Vec<Attribute>, inner: Box<dyn Sugar>) -> Self {
        Self { attrs, inner }
    }
}

impl Sugar for ConfigurationSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match cfg_eval_for_attrs(&self.attrs, ctx.options) {
            // The construct exists on this target: compose straight through to the inner.
            CfgEval::Active => self.inner.desugar(ctx),
            // Stripped on this target (like rustc pre-codegen): the empty literal floor,
            // a no-op that contributes nothing. NOT a refusal -- inactive is not in this
            // target's universe.
            CfgEval::Inactive(_) => Outcome::Dug(Desugared::Seq(Vec::new())),
            // No pinned target facts -> we cannot resolve the predicate. The no-scan law:
            // a named, terminal Hit, never a silent skip.
            CfgEval::Ambiguous(reason) => Outcome::Hit(Effect::Unsupported {
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
