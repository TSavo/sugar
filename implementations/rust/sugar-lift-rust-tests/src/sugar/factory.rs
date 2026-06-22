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
    FactoryAudit, FactoryCandidateAudit, FactoryDisposition, LiftOptions, Outcome, Sugar, SugarCtx,
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

pub(crate) fn has_expr_role(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> bool {
    !catalog::matching_expr_claims_for_role(expr, fcx, role).is_empty()
}

pub(crate) fn has_item_role(item: &Item, fcx: &SugarBuildCtx, role: SugarRole) -> bool {
    !catalog::matching_item_claims_for_role(item, fcx, role).is_empty()
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
            Outcome::Dug(Desugared::Constraints { kind, .. }) => match kind {
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
            Outcome::Dug(Desugared::Term(_)) => (FactoryDisposition::Warranted, "term", None),
            Outcome::Dug(Desugared::TupleComponents(_)) => {
                (FactoryDisposition::Warranted, "tuple-components", None)
            }
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
                    FactoryDisposition::WarrantPending,
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
                        FactoryDisposition::WarrantPending,
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

/// FIX(a): the factory-level over-refusal fix. A RECOGNIZED **Term** sugar (`selected`
/// is Some) that struck ONLY the GENERIC structural backstop (`Outcome::is_structural_bail`
/// -- a pure-but-untranslated term, NOT a NAMED order-loss effect) degrades to an
/// opaque-EUF term `Var{name:"opaque:<site>"}` -- a warranted-UNDECIDED congruence leaf --
/// instead of a refusal. A structural bail in term position is OUR untranslated-term gap,
/// not a source property; refusing it manufactures a false dragon (over-refusal). The
/// opaque var has NO teeth (SAT for any value) so it can NEVER false-discharge AND never
/// false-refute: the only motion is refused->undecided, which is strictly safer. Keyed by
/// the token-key so identical subterms stay congruent.
///
/// NOT converted (stay refused / unchanged): a NAMED effect (mutation / runtime / temporal
/// / IO -- a real source property); a non-Term role (a Constraint that cannot lift IS a
/// refusal); an UNRECOGNIZED shape (`selected` is None -> nothing claimed it); and the two
/// exempt recognizers -- `match_value_term` (owns a value-CONTRACT emission path whose
/// deliberate decline must stand) and `transparent_term` (paren/group pass-through; a
/// paren's inner is converted at its own level, so the wrapper only bails when its inner
/// is itself exempt, e.g. `(match ...)`).
fn term_bail_to_opaque(
    requested_role: &str,
    selected: Option<&'static str>,
    site: &str,
    outcome: Outcome,
) -> Outcome {
    let eligible = requested_role == "Term"
        && selected.is_some()
        && !matches!(
            selected,
            Some("match_value_term") | Some("transparent_term")
        )
        && outcome.is_structural_bail();
    if eligible {
        Outcome::Dug(Desugared::Term(std::rc::Rc::new(
            sugar_ir_symbolic::Term::Var {
                name: format!("opaque:{site}"),
            },
        )))
    } else {
        outcome
    }
}

impl Sugar for AccountedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let outcome = term_bail_to_opaque(
            &self.seed.requested_role,
            self.seed.selected,
            &self.seed.site,
            self.inner.desugar(ctx),
        );
        let audit = self.seed.audit(&outcome);
        if matches!(
            audit.disposition,
            FactoryDisposition::Refused
                | FactoryDisposition::WarrantPending
                | FactoryDisposition::Unresolved
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
        outcome
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
            requested_role: "Constraint".to_string(),
            selected: Some("panic_free"),
            candidates: Vec::new(),
        };
        let outcome = Outcome::Dug(Desugared::Constraints {
            atom: eq(bool_const(true), bool_const(true)),
            n: 0,
            kind: AssertionFactKind::Support,
            warrant: Warrant {
                name: Some("panic-free".to_string()),
            },
        });

        let audit = seed.audit(&outcome);

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

    // FIX(a) discrimination: a recognized-TERM GENERIC structural bail degrades to an
    // opaque-EUF term (warranted-UNDECIDED), never a refusal -- but a named/reasoned
    // refusal, an unrecognized backstop, a non-Term role, the exempt recognizers, and a
    // successful Dug are all left UNCHANGED. (opaque-EUF carries no teeth, so the only
    // motion is refused->undecided: it can neither false-discharge nor false-refute.)
    #[test]
    fn fix_a_term_structural_bail_degrades_to_opaque_undecided_not_refused() {
        use sugar_ir_symbolic::Term;
        let is_opaque = |o: &Outcome| {
            matches!(o, Outcome::Dug(Desugared::Term(t))
                if matches!(t.as_ref(), Term::Var { name } if name.starts_with("opaque:")))
        };
        let is_refused = |o: &Outcome| matches!(o, Outcome::Hit(_));

        // (1) THE FIX: a recognized-Term generic structural bail -> opaque-EUF (undecided).
        let bailed = term_bail_to_opaque("Term", Some("binop"), "a + b", Outcome::from_opt(None));
        assert!(
            is_opaque(&bailed),
            "a recognized-Term structural bail must become an opaque-EUF undecided term"
        );

        // (2) a NAMED / reasoned refusal (non-backstop reason) STAYS the loud refusal.
        let named = Outcome::Hit(Effect::Unsupported {
            reason: "unsupported term operator `@`".to_string(),
        });
        assert!(
            is_refused(&term_bail_to_opaque("Term", Some("binop"), "x", named)),
            "a named/reasoned refusal must stay refused"
        );

        // (3) an UNRECOGNIZED shape (no candidate selected -> backstop) stays refused.
        assert!(
            is_refused(&term_bail_to_opaque(
                "Term",
                None,
                "x",
                Outcome::from_opt(None)
            )),
            "an unrecognized backstop bail must stay refused (nothing claimed it)"
        );

        // (4) a non-Term role stays refused (a Constraint that cannot lift IS a refusal).
        assert!(
            is_refused(&term_bail_to_opaque(
                "Constraint",
                Some("c"),
                "x",
                Outcome::from_opt(None)
            )),
            "a non-Term role bail must stay refused"
        );

        // (5) the exempt recognizers keep their deliberate decline.
        for exempt in ["match_value_term", "transparent_term"] {
            assert!(
                is_refused(&term_bail_to_opaque(
                    "Term",
                    Some(exempt),
                    "x",
                    Outcome::from_opt(None)
                )),
                "exempt recognizer `{exempt}` must stay refused"
            );
        }

        // (6) a successful Dug passes through unchanged (no spurious opaque substitution).
        let dug = Outcome::Dug(Desugared::Term(std::rc::Rc::new(Term::Var {
            name: "real".to_string(),
        })));
        assert!(
            matches!(term_bail_to_opaque("Term", Some("binop"), "x", dug),
                Outcome::Dug(Desugared::Term(t)) if matches!(t.as_ref(), Term::Var { name } if name == "real")),
            "a successful Dug must pass through unchanged"
        );
    }
}
