// SPDX-License-Identifier: Apache-2.0
//
//! The recursive Sugar factory: **source site in, Sugar candidates out**.
//!
//! `catalog::matching_expr_claims(expr, fcx)` asks every expression Sugar whether it
//! handles the source site and returns every candidate that says yes. `build_term(expr,
//! fcx)` and `build_composite(expr, fcx)` are compatibility wrappers over catalog role
//! selection. That walk is the ENTIRE factory dispatch -- there are no inline node
//! structs, no `decompose_*` calls, no term/ctor construction logic here.
//!
//! ## The recognizer-fn pattern
//!
//! Every construct is a SELF-CONTAINED node living in its own `src/sugar/*.rs` module,
//! owning BOTH a recognizer `fn recognize(expr: &Expr, fcx: &SugarBuildCtx) ->
//! Option<Box<dyn Sugar>>` (returns `Some(boxed self)` if this Sugar handles the site --
//! building any children via `build_term`/`build_composite` -- else `None`) AND its
//! `desugar`. The former free `decompose_*` functions are reused INSIDE these
//! recognizers; the old inline `MethodSugar`/`CtorSugar`/`ResolvedTermSugar`/
//! `ReasonedIncompleteSugar` now live in their own modules. Ambiguity is represented by
//! MULTIPLE candidates, not by a hidden factory choice.
//!
//! ## The three laws
//!
//! 1. **TOTAL.** Every `Expr` maps to *some* `Box<dyn Sugar>`. A term shape with a
//!    proven runtime/effect boundary becomes a reasoned leaf carrying the arm's EXACT
//!    refusal string. A structural miss reaches [`UnsupportedSugar`], but that is a gap
//!    sentinel, not a terminal verdict: accounted desugar records it as unresolved factory
//!    work so the production gate stays loud. The walk cannot return `None`.
//! 2. **RECURSIVE.** A composite term node builds each operand with `build_term(child)`
//!    and composes the child Sugar; transparent wrappers (`Paren`/`Group`) recurse
//!    straight through. `desugar` then collapses the whole tree inside-out.
//! 3. **NEVER DECIDE EARLY (the sin).** A recognizer only *recognizes and news*;
//!    degeneracy is a LEAF property that propagates for free through the composites.
//!
//! ## Candidate ordering
//!
//! Multiple Sugars may correctly claim the same source shape. Specific Sugars declare
//! `comes_before` edges toward broader gravitational wells. The catalog resolves the
//! resulting graph and panics when two same-role candidates are unordered or cyclic; the
//! factory does not encode exclusion lists or incidental catalog order.
//!
//! ## The genuinely dual shapes
//!
//! `Array`, `Repeat`, and `MethodCall` have DISTINCT term vs composite roles, so they
//! get SEPARATE nodes per role — never one node branching on a position flag. The
//! term `Expr::Array` is the `literal_aggregate` ctor (`array_term`); the composite
//! `Expr::Array` is the sequence-floor `LiteralSugar` (`literal`). The term `Expr::Repeat`
//! expands a literal-count aggregate (`repeat_term`); the composite one is the
//! `ArrayRepeat` refuse-shape (`array_repeat`). The term `Expr::MethodCall` is the
//! `method:` ctor (`method`); the composite one is the `fold`/`for_each`/sequence-adaptor
//! quantifier chain. Closure-adaptor and match-scrutinee terminal verdicts are separate
//! catalog roles, not composite fallbacks.

use std::collections::BTreeMap;

use quote::ToTokens;
use syn::spanned::Spanned;
use syn::{Expr, Item};
use tracing::{debug, warn};

use crate::sugar::catalog;
use crate::sugar::claim::SugarRole;
use crate::{
    refusal_disposition, token_key, AssertionFactKind, Desugared, Disposition, Effect,
    FactoryAudit, FactoryAuditSpan, FactoryCandidateAudit, FactoryDisposition, LiftOptions,
    Outcome, Sugar, SugarCtx, TemporalScope, STRUCTURAL_BACKSTOP_REASON,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct FactoryGap {
    pub(crate) reason: String,
}

pub(crate) type FactoryReduction = Result<Outcome, FactoryGap>;

impl FactoryGap {
    pub(crate) fn new(reason: impl Into<String>) -> Self {
        Self {
            reason: reason.into(),
        }
    }
}

/// A factory-built child/body for a parent Sugar.
///
/// This is the post-order contract in code: a non-leaf parent is constructed with
/// `SugarBody` values for the expressions it encloses. Raw `Expr` may still be kept for
/// provenance, token keys, literal fast paths, or pattern metadata, but not as the body
/// that the parent later re-builds through the factory.
pub(crate) struct SugarBody {
    node: Box<dyn Sugar>,
}

impl SugarBody {
    pub(crate) fn from_node(node: Box<dyn Sugar>) -> Self {
        Self { node }
    }

    pub(crate) fn term(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_term(expr, fcx))
    }

    pub(crate) fn composite(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_composite(expr, fcx))
    }

    pub(crate) fn constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_constraint(expr, fcx))
    }

    pub(crate) fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        self.node.reduce(ctx)
    }

    pub(crate) fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

/// What a recognizer needs from its environment to construct a node: the temporal
/// `scope` (binding / mutability oracle), the lift `options`, and the in-scope `let`
/// initializers (`name -> &init_expr`) that binding-resolving recognizers (`fold`,
/// `for_each`, closure verdicts) capture. This is the BUILD-time env; the dual
/// [`SugarCtx`] is the DESUGAR-time env.
pub(crate) struct SugarBuildCtx<'a, 'e> {
    scope: &'a TemporalScope,
    options: &'a LiftOptions,
    let_inits: &'a BTreeMap<String, &'e Expr>,
    bound_path_stack: Vec<String>,
    const_path_stack: Vec<String>,
}

impl<'a, 'e> SugarBuildCtx<'a, 'e> {
    pub(crate) fn new(
        scope: &'a TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a BTreeMap<String, &'e Expr>,
    ) -> Self {
        Self {
            scope,
            options,
            let_inits,
            bound_path_stack: Vec::new(),
            const_path_stack: Vec::new(),
        }
    }

    pub(crate) fn scope(&self) -> &TemporalScope {
        self.scope
    }

    pub(crate) fn options(&self) -> &LiftOptions {
        self.options
    }

    pub(crate) fn let_inits(&self) -> &BTreeMap<String, &'e Expr> {
        self.let_inits
    }

    pub(crate) fn resolving_bound_path(&self, name: &str) -> bool {
        self.bound_path_stack.iter().any(|current| current == name)
    }

    pub(crate) fn with_bound_path(&self, name: &str) -> Self {
        let mut bound_path_stack = self.bound_path_stack.clone();
        bound_path_stack.push(name.to_string());
        Self {
            scope: self.scope,
            options: self.options,
            let_inits: self.let_inits,
            bound_path_stack,
            const_path_stack: self.const_path_stack.clone(),
        }
    }

    pub(crate) fn resolving_const_path(&self, name: &str) -> bool {
        self.const_path_stack.iter().any(|current| current == name)
    }

    pub(crate) fn with_const_path(&self, name: &str) -> Self {
        let mut const_path_stack = self.const_path_stack.clone();
        const_path_stack.push(name.to_string());
        Self {
            scope: self.scope,
            options: self.options,
            let_inits: self.let_inits,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack,
        }
    }
}

pub(crate) fn build_expr(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    catalog::build_expr_role(expr, fcx, role)
}

pub(crate) fn reduce_expr(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    role: SugarRole,
    ctx: &SugarCtx,
) -> FactoryReduction {
    build_expr(expr, fcx, role).reduce(ctx)
}

pub(crate) fn has_expr_role(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> bool {
    !catalog::matching_expr_claims_for_role(expr, fcx, role).is_empty()
}

pub(crate) fn has_item_role(item: &Item, fcx: &SugarBuildCtx, role: SugarRole) -> bool {
    !catalog::matching_item_claims_for_role(item, fcx, role).is_empty()
}

/// Compatibility TERM wrapper: ask the unified candidate catalog, then return the first
/// candidate whose old source-position role is `Term`, else the structural gap sentinel.
/// TOTAL — every shape news a node, but an unclaimed node is unresolved factory work.
/// RECURSIVE — composite term recognizers build their operands with `build_term`.
pub(crate) fn build_term(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Term)
}

pub(crate) fn reduce_term(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> FactoryReduction {
    reduce_expr(expr, fcx, SugarRole::Term, ctx)
}

/// Compatibility COMPOSITE wrapper: ask the unified candidate catalog, then return the
/// first candidate whose old source-position role is `Composite`, else the structural
/// gap sentinel. Total: an unowned shape becomes [`UnsupportedSugar`], which accounted
/// desugar records as an unresolved factory gap.
pub(crate) fn build_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Composite)
}

pub(crate) fn reduce_composite(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> FactoryReduction {
    reduce_expr(expr, fcx, SugarRole::Composite, ctx)
}

pub(crate) fn has_composite(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    has_expr_role(expr, fcx, SugarRole::Composite)
}

/// CONSTRAINT wrapper: ask the unified candidate catalog for a source assertion /
/// predicate / obligation shape. The human spelling may be `assert_eq!`, `assert!`,
/// or a framework-specific assertion; the role is the semantic output: a ProofIR
/// constraint terminal.
pub(crate) fn build_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Constraint)
}

pub(crate) fn reduce_constraint(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> FactoryReduction {
    reduce_expr(expr, fcx, SugarRole::Constraint, ctx)
}

pub(crate) fn has_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    has_expr_role(expr, fcx, SugarRole::Constraint)
}

/// ASSERTION-SURFACE wrapper: ask the catalog for syntax that emits a fact at
/// statement position. Predicate sugars such as `matches!(..)` are still
/// `Constraint`; they only become facts when an assertion surface wraps them or
/// a source macro expands to one.
pub(crate) fn build_assertion_surface(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::AssertionSurface)
}

pub(crate) fn has_assertion_surface(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    has_expr_role(expr, fcx, SugarRole::AssertionSurface)
}

/// TUPLE-PRODUCER wrapper: ask the catalog for a source expression that yields a
/// tuple value whose components can be decomposed at desugar time.
pub(crate) fn build_tuple_producer(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::TupleProducer)
}

pub(crate) fn has_tuple_producer(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    has_expr_role(expr, fcx, SugarRole::TupleProducer)
}

pub(crate) struct FactoryAuditSeed {
    ast_kind: &'static str,
    site: String,
    line: usize,
    span: Option<FactoryAuditSpan>,
    requested_role: String,
    selected: Option<&'static str>,
    candidates: Vec<FactoryCandidateAudit>,
}

impl FactoryAuditSeed {
    pub(crate) fn expr(
        expr: &Expr,
        requested_role: SugarRole,
        selected: Option<&'static str>,
        candidates: Vec<FactoryCandidateAudit>,
    ) -> Self {
        Self {
            ast_kind: "expr",
            site: token_key(expr),
            line: expr.span().start().line,
            span: Some(factory_audit_span(expr.span())),
            requested_role: format!("{requested_role:?}"),
            selected,
            candidates,
        }
    }

    pub(crate) fn item(
        item: &Item,
        requested_role: SugarRole,
        selected: Option<&'static str>,
        candidates: Vec<FactoryCandidateAudit>,
    ) -> Self {
        Self {
            ast_kind: "item",
            site: item.to_token_stream().to_string(),
            line: item.span().start().line,
            span: Some(factory_audit_span(item.span())),
            requested_role: format!("{requested_role:?}"),
            selected,
            candidates,
        }
    }

    fn audit_result(&self, reduction: &FactoryReduction) -> FactoryAudit {
        let (disposition, output, reason) = self.disposition_result(reduction);
        self.audit_with(disposition, output, reason)
    }

    fn audit_with(
        &self,
        disposition: FactoryDisposition,
        output: &'static str,
        reason: Option<String>,
    ) -> FactoryAudit {
        FactoryAudit {
            ast_kind: self.ast_kind,
            site: self.site.clone(),
            line: self.line,
            span: self.span.clone(),
            requested_role: self.requested_role.clone(),
            selected: self.selected,
            candidates: self.candidates.clone(),
            disposition,
            output,
            reason,
        }
    }

    fn disposition_result(
        &self,
        reduction: &FactoryReduction,
    ) -> (FactoryDisposition, &'static str, Option<String>) {
        let outcome = match reduction {
            Ok(outcome) => outcome,
            Err(gap) => {
                return (
                    FactoryDisposition::Unresolved,
                    "gap",
                    Some(gap.reason.clone()),
                )
            }
        };
        self.disposition_outcome(outcome)
    }

    fn disposition_outcome(
        &self,
        outcome: &Outcome,
    ) -> (FactoryDisposition, &'static str, Option<String>) {
        match outcome {
            Outcome::Complete(Desugared::Constraints { kind, .. }) => match kind {
                AssertionFactKind::Warranted => {
                    (FactoryDisposition::Warranted, "constraints", None)
                }
                AssertionFactKind::Support => (
                    FactoryDisposition::Warranted,
                    "auxiliary-constraints",
                    Some(
                        "auxiliary constraint: emitted as panic-path/temporal universe; does not increment scalar assertion count"
                            .to_string(),
                    ),
                ),
            },
            Outcome::Complete(Desugared::Term(_)) => (FactoryDisposition::Warranted, "term", None),
            Outcome::Complete(Desugared::TupleComponents(_)) => {
                (FactoryDisposition::Warranted, "tuple-components", None)
            }
            Outcome::Complete(Desugared::Seq(seq)) if seq.is_empty() => (
                FactoryDisposition::Support,
                "empty-sequence",
                Some("inert: empty sequence; no obligation emitted".to_string()),
            ),
            Outcome::Complete(Desugared::Seq(_)) => (FactoryDisposition::Warranted, "sequence", None),
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                match refusal_disposition(&reason) {
                    Disposition::Refused => (FactoryDisposition::Refused, "effect", Some(reason)),
                    Disposition::Inactive => (
                        FactoryDisposition::Support,
                        "inactive",
                        Some(format!("inert: {reason}")),
                    ),
                    Disposition::Unclassified => (
                        FactoryDisposition::Unresolved,
                        "gap",
                        Some(gap_reason_from_unsupported_reason(self, &reason)),
                    ),
                }
            }
        }
    }

    fn unresolved_reason(&self) -> String {
        match self.selected {
            Some(selected) => format!(
                "Sugar `{selected}` did not desugar `{}` to bedrock for role {}; write more Sugar for this AST",
                self.site, self.requested_role
            ),
            None => format!(
                "no Sugar candidate for role {} at `{}`; write more Sugar for this AST",
                self.requested_role, self.site
            ),
        }
    }
}

fn structural_bail_to_gap(seed: &FactoryAuditSeed, outcome: Outcome) -> FactoryReduction {
    match &outcome {
        Outcome::Incomplete(Effect::Unsupported { reason })
            if refusal_disposition(reason) == Disposition::Unclassified =>
        {
            Err(FactoryGap {
                reason: gap_reason_from_unsupported_reason(seed, reason),
            })
        }
        _ => Ok(outcome),
    }
}

fn gap_reason_from_unsupported_reason(seed: &FactoryAuditSeed, reason: &str) -> String {
    if reason == STRUCTURAL_BACKSTOP_REASON {
        seed.unresolved_reason()
    } else if reason.contains("write more Sugar for this AST") {
        reason.to_string()
    } else {
        format!("{reason}; write more Sugar for this AST")
    }
}

fn gap_to_compat_outcome(gap: FactoryGap) -> Outcome {
    Outcome::Incomplete(Effect::Unsupported { reason: gap.reason })
}

fn factory_audit_span(span: proc_macro2::Span) -> FactoryAuditSpan {
    let start = span.start();
    let end = span.end();
    FactoryAuditSpan {
        start_line: start.line,
        start_col: start.column,
        end_line: end.line,
        end_col: end.column,
    }
}

pub(crate) struct AccountedSugar {
    seed: FactoryAuditSeed,
    inner: Box<dyn Sugar>,
}

impl AccountedSugar {
    pub(crate) fn new(seed: FactoryAuditSeed, inner: Box<dyn Sugar>) -> Box<dyn Sugar> {
        Box::new(Self { seed, inner })
    }
}

impl Sugar for AccountedSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let outcome = self.inner.desugar(ctx);
        let reduction = structural_bail_to_gap(&self.seed, outcome);
        let audit = self.seed.audit_result(&reduction);
        if matches!(
            audit.disposition,
            FactoryDisposition::Refused | FactoryDisposition::Unresolved
        ) {
            warn!(
                ast_kind = audit.ast_kind,
                line = audit.line,
                requested_role = audit.requested_role.as_str(),
                selected = audit.selected.unwrap_or("<none>"),
                disposition = audit.disposition.as_str(),
                output = audit.output,
                reason = audit.reason.as_deref().unwrap_or(""),
                site = audit.site.as_str(),
                candidates = audit.candidates.len(),
                "sugar factory terminal"
            );
        } else {
            debug!(
                ast_kind = audit.ast_kind,
                line = audit.line,
                requested_role = audit.requested_role.as_str(),
                selected = audit.selected.unwrap_or("<none>"),
                disposition = audit.disposition.as_str(),
                output = audit.output,
                site = audit.site.as_str(),
                candidates = audit.candidates.len(),
                "sugar factory dispatch"
            );
        }
        ctx.record_factory_audit(audit);
        reduction
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.reduce(ctx) {
            Ok(outcome) => outcome,
            Err(gap) => gap_to_compat_outcome(gap),
        }
    }
}

pub(crate) fn compat_reduction(reduction: FactoryReduction) -> Outcome {
    match reduction {
        Ok(outcome) => outcome,
        Err(gap) => gap_to_compat_outcome(gap),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{bool_const, AssertionFactKind, Desugared, Warrant};
    use sugar_ir_symbolic::eq;

    #[test]
    fn auxiliary_constraint_audit_is_warranted_not_support() {
        let seed = FactoryAuditSeed {
            ast_kind: "expr",
            site: "panic_free_call()".to_string(),
            line: 1,
            span: None,
            requested_role: "Constraint".to_string(),
            selected: Some("panic_free"),
            candidates: Vec::new(),
        };
        let outcome = Outcome::Complete(Desugared::Constraints {
            atom: eq(bool_const(true), bool_const(true)),
            n: 0,
            kind: AssertionFactKind::Support,
            warrant: Warrant {
                name: Some("panic-free".to_string()),
            },
        });

        let audit = seed.audit_result(&Ok(outcome));

        assert_eq!(audit.disposition, FactoryDisposition::Warranted);
        assert_eq!(audit.output, "auxiliary-constraints");
        assert!(
            audit
                .reason
                .as_deref()
                .is_some_and(|reason| reason.contains("auxiliary constraint")),
            "{audit:?}"
        );
    }

    #[test]
    fn structural_backstop_is_factory_gap_not_incomplete_outcome() {
        let seed = FactoryAuditSeed {
            ast_kind: "expr",
            site: "iter".to_string(),
            line: 7,
            span: None,
            requested_role: "Composite".to_string(),
            selected: Some("bound_path_composite"),
            candidates: Vec::new(),
        };

        let reduction = structural_bail_to_gap(&seed, Outcome::from_opt(None));
        assert!(
            reduction.is_err(),
            "a structural factory miss has no terminal Outcome"
        );

        let audit = seed.audit_result(&reduction);
        assert_eq!(audit.disposition, FactoryDisposition::Unresolved);
        assert_eq!(audit.output, "gap");
        assert!(
            audit
                .reason
                .as_deref()
                .is_some_and(|reason| reason.contains("write more Sugar")),
            "{audit:?}"
        );
    }

    #[test]
    fn no_candidate_structural_backstop_is_factory_gap() {
        let seed = FactoryAuditSeed {
            ast_kind: "expr",
            site: "opaque_shape()".to_string(),
            line: 11,
            span: None,
            requested_role: "Composite".to_string(),
            selected: None,
            candidates: Vec::new(),
        };

        let reduction = structural_bail_to_gap(&seed, Outcome::from_opt(None));
        assert!(
            reduction.is_err(),
            "a no-candidate factory miss has no terminal Outcome"
        );

        let audit = seed.audit_result(&reduction);
        assert_eq!(audit.disposition, FactoryDisposition::Unresolved);
        assert_eq!(audit.output, "gap");
        assert!(
            audit.reason.as_deref().is_some_and(|reason| reason
                .contains("no Sugar candidate for role Composite at `opaque_shape()`")),
            "{audit:?}"
        );
    }

    #[test]
    fn named_effect_stays_incomplete_outcome_not_factory_gap() {
        let seed = FactoryAuditSeed {
            ast_kind: "expr",
            site: "&mut x".to_string(),
            line: 7,
            span: None,
            requested_role: "Term".to_string(),
            selected: Some("reference_term"),
            candidates: Vec::new(),
        };

        let reduction = structural_bail_to_gap(
            &seed,
            Outcome::Incomplete(Effect::TemporalRead {
                boundary: "&mut x".to_string(),
            }),
        );
        assert!(
            reduction.is_ok(),
            "a real effect remains a terminal Outcome"
        );

        let audit = seed.audit_result(&reduction);
        assert_eq!(audit.disposition, FactoryDisposition::Refused);
        assert_eq!(audit.output, "effect");
    }

    #[test]
    fn recognized_term_structural_bail_is_gap_not_opaque_complete() {
        let seed = FactoryAuditSeed {
            ast_kind: "expr",
            site: "a + b".to_string(),
            line: 7,
            span: None,
            requested_role: "Term".to_string(),
            selected: Some("binop"),
            candidates: Vec::new(),
        };

        let bailed = structural_bail_to_gap(&seed, Outcome::from_opt(None));
        assert!(
            bailed.is_err(),
            "a recognized-Term structural bail must be a factory gap, not an opaque Complete"
        );

        let audit = seed.audit_result(&bailed);
        assert_eq!(audit.disposition, FactoryDisposition::Unresolved);
        assert_eq!(audit.output, "gap");

        let completed = Outcome::Complete(Desugared::Term(std::rc::Rc::new(
            sugar_ir_symbolic::Term::Var {
                name: "real".to_string(),
            },
        )));
        assert!(
            matches!(structural_bail_to_gap(&seed, completed),
                Ok(
                Outcome::Complete(Desugared::Term(t))
            ) if matches!(t.as_ref(), sugar_ir_symbolic::Term::Var { name } if name == "real")),
            "a successful Complete must pass through unchanged"
        );
    }
}
