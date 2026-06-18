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
//! `ReasonedHitSugar` now live in their own modules. Ambiguity is represented by
//! MULTIPLE candidates, not by a hidden factory choice.
//!
//! ## The three laws
//!
//! 1. **TOTAL.** Every `Expr` maps to *some* `Box<dyn Sugar>`. A term shape with no
//!    constructible value becomes a reasoned leaf (a `ReasonedHitSugar` carrying the
//!    arm's EXACT refusal string, or [`UnsupportedSugar`] for the structural backstop)
//!    — NEVER a silent skip. The walk cannot return `None`.
//! 2. **RECURSIVE.** A composite term node builds each operand with `build_term(child)`
//!    and composes the child Sugar; transparent wrappers (`Paren`/`Group`) recurse
//!    straight through. `desugar` then collapses the whole tree inside-out.
//! 3. **NEVER DECIDE EARLY (the sin).** A recognizer only *recognizes and news*;
//!    degeneracy is a LEAF property that propagates for free through the composites.
//!
//! ## Candidate priority
//!
//! Multiple Sugars may correctly claim the same source shape. Each candidate carries its
//! Sugar-declared priority: lower numbers are better decompositions. The catalog brokers
//! candidates and sorts by that declared priority; the factory does not encode exclusion
//! lists.
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

use crate::sugar::catalog;
use crate::sugar::claim::SugarRole;
use crate::{
    refusal_disposition, token_key, Desugared, Disposition, Effect, FactoryAudit,
    FactoryCandidateAudit, FactoryDisposition, LiftOptions, Outcome, Sugar, SugarCtx,
    TemporalScope, STRUCTURAL_BACKSTOP_REASON,
};

/// What a recognizer needs from its environment to construct a node: the temporal
/// `scope` (binding / mutability oracle), the lift `options`, and the in-scope `let`
/// initializers (`name -> &init_expr`) that binding-resolving recognizers (`fold`,
/// `for_each`, closure verdicts) capture. This is the BUILD-time env; the dual
/// [`SugarCtx`] is the DESUGAR-time env.
pub(crate) struct SugarBuildCtx<'a, 'e> {
    scope: &'a TemporalScope,
    options: &'a LiftOptions,
    let_inits: &'a BTreeMap<String, &'e Expr>,
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
}

pub(crate) fn build_expr(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    catalog::build_expr_role(expr, fcx, role)
}

pub(crate) fn has_expr_role(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> bool {
    catalog::matching_expr_claims(expr, fcx)
        .iter()
        .any(|candidate| candidate.role() == role)
}

pub(crate) fn has_item_role(item: &Item, fcx: &SugarBuildCtx, role: SugarRole) -> bool {
    catalog::matching_item_claims(item, fcx)
        .iter()
        .any(|candidate| candidate.role() == role)
}

/// Compatibility TERM wrapper: ask the unified candidate catalog, then return the first
/// candidate whose old source-position role is `Term`, else the structural backstop.
/// TOTAL — every shape news a node (a reasoned leaf for the no-value shapes).
/// RECURSIVE — composite term recognizers build their operands with `build_term`.
pub(crate) fn build_term(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Term)
}

/// Compatibility COMPOSITE wrapper: ask the unified candidate catalog, then return the
/// first candidate whose old source-position role is `Composite`, else the structural
/// backstop. Total: an unowned shape becomes the [`UnsupportedSugar`] backstop.
pub(crate) fn build_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Composite)
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

pub(crate) fn has_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    has_expr_role(expr, fcx, SugarRole::Constraint)
}

pub(crate) struct FactoryAuditSeed {
    ast_kind: &'static str,
    site: String,
    line: usize,
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
            requested_role: format!("{requested_role:?}"),
            selected,
            candidates,
        }
    }

    fn audit(&self, outcome: &Outcome) -> FactoryAudit {
        let (disposition, output, reason) = self.disposition(outcome);
        FactoryAudit {
            ast_kind: self.ast_kind,
            site: self.site.clone(),
            line: self.line,
            requested_role: self.requested_role.clone(),
            selected: self.selected,
            candidates: self.candidates.clone(),
            disposition,
            output,
            reason,
        }
    }

    fn disposition(&self, outcome: &Outcome) -> (FactoryDisposition, &'static str, Option<String>) {
        match outcome {
            Outcome::Dug(Desugared::Constraints { .. }) => {
                (FactoryDisposition::Warranted, "constraints", None)
            }
            Outcome::Dug(Desugared::Term(_)) => (FactoryDisposition::Warranted, "term", None),
            Outcome::Dug(Desugared::Seq(seq)) if seq.is_empty() => (
                FactoryDisposition::Support,
                "empty-sequence",
                Some("inert: empty sequence; no obligation emitted".to_string()),
            ),
            Outcome::Dug(Desugared::Seq(_)) => (FactoryDisposition::Warranted, "sequence", None),
            Outcome::Hit(Effect::Unsupported { reason })
                if reason == STRUCTURAL_BACKSTOP_REASON =>
            {
                (
                    FactoryDisposition::Unresolved,
                    "structural-backstop",
                    Some(self.unresolved_reason()),
                )
            }
            Outcome::Hit(effect) => {
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
                        "structural-backstop",
                        Some(format!("{reason}; write more Sugar for this AST")),
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
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let outcome = self.inner.desugar(ctx);
        ctx.record_factory_audit(self.seed.audit(&outcome));
        outcome
    }
}
