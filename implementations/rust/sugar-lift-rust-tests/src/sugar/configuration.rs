// SPDX-License-Identifier: MIT OR Apache-2.0
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
//!   * **Inactive**  -> `Complete(Seq[])` -- the no-op / empty floor (rustc strips the
//!     construct pre-codegen, so it contributes nothing; NOT a refusal).
//!   * **Ambiguous** -> `Incomplete(Effect::Configuration { "ambiguous cfg: <reason>" })` -- with
//!     no target facts we honestly cannot resolve it. By the no-scan / `Outcome` law this
//!     RETURNS INCOMPLETE (a named, terminal effect); it is NEVER a silent skip.
//!
//! The resolution is the EXISTING `cfg_eval_for_attrs` over the pinned target facts
//! (`SugarCtx::options.target_cfg`) -- a SEMANTIC predicate evaluation, never a syntactic
//! body scan. This node does not change WHAT cfg decides; it makes that decision COMPOSE
//! as a `Sugar`, so a cfg-gated ANYTHING flows through build + desugar for free.

use quote::ToTokens;
use syn::Attribute;
use tracing::{debug, warn};

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
///   * `Ambiguous(reason)` -- no pinned facts, so we honestly cannot resolve it (bail / Incomplete).
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
    let disposition = compose(cfg_eval_for_attrs(attrs, options));
    trace_cfg_disposition("attrs", &render_cfg_attrs(attrs), &disposition);
    disposition
}

/// Resolve a SINGLE cfg `predicate` (a `cfg!(..)` guard, a synthetic `debug_assertions`
/// gate) against the pinned target facts -- the predicate analogue of [`resolve`] for the
/// sites that hold a parsed [`CfgPredicate`] rather than an attribute list. REUSES the
/// existing `cfg_eval_predicate` verbatim; this only composes its result into the shared
/// [`CfgDisposition`] vocabulary, so the predicate sites speak the same three-way language
/// as the attribute sites and the formerly copy-pasted dispatch lives in one body.
pub(crate) fn resolve_predicate(predicate: &CfgPredicate, options: &LiftOptions) -> CfgDisposition {
    let rendered = predicate.to_string();
    let disposition = compose(cfg_eval_predicate(predicate, options.target_cfg.as_ref()));
    trace_cfg_disposition("predicate", &rendered, &disposition);
    disposition
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

fn render_cfg_attrs(attrs: &[Attribute]) -> String {
    let rendered = attrs
        .iter()
        .filter(|attr| attr.path().is_ident("cfg"))
        .map(ToTokens::to_token_stream)
        .map(|tokens| tokens.to_string())
        .collect::<Vec<_>>()
        .join(" ");
    if rendered.is_empty() {
        "<none>".to_string()
    } else {
        rendered
    }
}

fn trace_cfg_disposition(source: &'static str, cfg: &str, disposition: &CfgDisposition) {
    let fields = cfg_trace_fields(disposition);
    match fields.level {
        CfgTraceLevel::Debug => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::configuration",
                source = source,
                cfg = cfg,
                disposition = fields.disposition,
                reason = fields.reason.unwrap_or(""),
                "configuration sugar cfg resolved"
            );
        }
        CfgTraceLevel::Warn => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::configuration",
                source = source,
                cfg = cfg,
                disposition = fields.disposition,
                reason = fields.reason.unwrap_or(""),
                "configuration sugar cfg boundary"
            );
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CfgTraceLevel {
    Debug,
    Warn,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct CfgTraceFields<'a> {
    level: CfgTraceLevel,
    disposition: &'static str,
    reason: Option<&'a str>,
}

fn cfg_trace_fields(disposition: &CfgDisposition) -> CfgTraceFields<'_> {
    match disposition {
        CfgDisposition::Present => CfgTraceFields {
            level: CfgTraceLevel::Debug,
            disposition: "present",
            reason: None,
        },
        CfgDisposition::Absent(reason) => CfgTraceFields {
            level: CfgTraceLevel::Debug,
            disposition: "absent",
            reason: Some(reason.as_str()),
        },
        CfgDisposition::Ambiguous(reason) => CfgTraceFields {
            level: CfgTraceLevel::Warn,
            disposition: "ambiguous",
            reason: Some(reason.as_str()),
        },
    }
}

/// A cfg-attributed construct: the `#[cfg(..)]` attrs paired with the inner `Sugar` they
/// gate. `desugar` resolves the predicate ONCE (via [`resolve`]) and either completes the inner
/// (Present), completes the empty floor (Absent), or returns Incomplete the ambiguous-cfg boundary. The wrapped
/// `inner` is built unconditionally by the factory; this node decides -- purely from the
/// pinned target facts -- whether it CONTRIBUTES. This is the canonical composing form of a
/// cfg-gated construct; the collector sites that cannot yield a single `Outcome` (they emit
/// site-specific skip strings / counts) still resolve through [`resolve`], the same body.
pub(crate) struct ConfigurationSugar {
    attrs: Vec<Attribute>,
    inner: Box<dyn Sugar>,
}

/// Empty inner sugar for cfg-gated macro collection sites that need to ask a
/// `ConfigurationSugar` for its disposition before collecting a concrete body.
pub(crate) struct EmptyConfigGateSugar;

impl Sugar for EmptyConfigGateSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Seq(Vec::new()))
    }
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
            CfgDisposition::Absent(_) => Outcome::Complete(Desugared::Seq(Vec::new())),
            // No pinned target facts -> we cannot resolve the predicate. The no-scan law:
            // a named, terminal Incomplete, never a silent skip.
            CfgDisposition::Ambiguous(reason) => Outcome::Incomplete(Effect::Configuration {
                reason: format!("ambiguous cfg: {reason}"),
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TargetCfg};

    // A stub inner child that completes to a single-element sequence floor (its presence is
    // observable as a non-empty `Seq`), ignoring `ctx`.
    struct StubInner;
    impl Sugar for StubInner {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Complete(Desugared::Seq(vec![crate::DesugaredElem {
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
    fn cfg_resolution_trace_fields_name_disposition_and_level() {
        assert_eq!(
            cfg_trace_fields(&CfgDisposition::Present),
            CfgTraceFields {
                level: CfgTraceLevel::Debug,
                disposition: "present",
                reason: None
            }
        );
        assert_eq!(
            cfg_trace_fields(&CfgDisposition::Absent("off target".to_string())),
            CfgTraceFields {
                level: CfgTraceLevel::Debug,
                disposition: "absent",
                reason: Some("off target")
            }
        );
        assert_eq!(
            cfg_trace_fields(&CfgDisposition::Ambiguous("missing facts".to_string())),
            CfgTraceFields {
                level: CfgTraceLevel::Warn,
                disposition: "ambiguous",
                reason: Some("missing facts")
            }
        );
    }

    #[test]
    fn cfg_resolution_renders_attr_and_predicate_diagnostics() {
        let attr = cfg_attr(quote::quote!(all(unix, target_pointer_width = "64")));
        assert_eq!(
            render_cfg_attrs(&[attr]),
            "# [cfg (all (unix , target_pointer_width = \"64\"))]"
        );

        let predicate = syn::parse_str::<CfgPredicate>("target_os = \"linux\"").unwrap();
        assert_eq!(predicate.to_string(), "target_os = \"linux\"");
    }

    #[test]
    fn active_cfg_composes_through_to_inner() {
        // target_os = "linux" with linux pinned -> Active -> the inner's `Seq[1]` floor.
        let target = TargetCfg::from_rustc_cfg_facts(["target_os=\"linux\""]).unwrap();
        let options = LiftOptions::for_target_cfg(target);
        match run(vec![cfg_attr(quote::quote!(target_os = "linux"))], &options) {
            Outcome::Complete(Desugared::Seq(s)) => {
                assert_eq!(s.len(), 1, "inner floor flows through")
            }
            Outcome::Complete(_) => {
                panic!("expected the inner's Complete(Seq[1]), got a different Complete")
            }
            Outcome::Incomplete(_) => {
                panic!("expected the inner's Complete(Seq[1]), got Incomplete")
            }
        }
    }

    #[test]
    fn inactive_cfg_digs_the_empty_floor() {
        // target_os = "windows" with only linux pinned -> Inactive -> empty `Seq[]`,
        // the no-op floor (stripped on this target), NOT a Incomplete.
        let target = TargetCfg::from_rustc_cfg_facts(["target_os=\"linux\""]).unwrap();
        let options = LiftOptions::for_target_cfg(target);
        match run(
            vec![cfg_attr(quote::quote!(target_os = "windows"))],
            &options,
        ) {
            Outcome::Complete(Desugared::Seq(s)) => {
                assert!(s.is_empty(), "inactive strips to the empty no-op floor")
            }
            Outcome::Complete(_) => panic!("expected Complete(Seq[]), got a different Complete"),
            Outcome::Incomplete(_) => {
                panic!("expected Complete(Seq[]), inactive must NOT Incomplete")
            }
        }
    }

    #[test]
    fn ambiguous_cfg_hits_configuration_not_silent() {
        // No target_cfg pinned at all -> Ambiguous -> Incomplete(Configuration "ambiguous cfg: ..").
        // The no-scan law: it RETURNS INCOMPLETE, it is not a silent skip.
        let options = LiftOptions::default();
        match run(vec![cfg_attr(quote::quote!(target_os = "linux"))], &options) {
            Outcome::Incomplete(Effect::Configuration { reason }) => {
                assert!(
                    reason.starts_with("ambiguous cfg: "),
                    "ambiguous cfg names its boundary, got {reason:?}"
                );
            }
            Outcome::Incomplete(_) => {
                panic!("expected Incomplete(Configuration), got a different Incomplete")
            }
            Outcome::Complete(_) => {
                panic!("ambiguous cfg must INCOMPLETE (no-scan law), not Complete")
            }
        }
    }

    #[test]
    fn no_cfg_attrs_is_active_and_composes() {
        // An empty attr set -> `cfg_eval_for_attrs` is Active -> inner flows through.
        let options = LiftOptions::default();
        match run(Vec::new(), &options) {
            Outcome::Complete(Desugared::Seq(s)) => assert_eq!(s.len(), 1),
            Outcome::Complete(_) => {
                panic!("expected the inner's Complete(Seq[1]), got a different Complete")
            }
            Outcome::Incomplete(_) => {
                panic!("no cfg attrs is Active; expected Complete, got Incomplete")
            }
        }
    }
}
