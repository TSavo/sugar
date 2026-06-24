// SPDX-License-Identifier: Apache-2.0
//
// `BoundPathSugar`: a stable `let` binding used as a term is transparent to the
// ProofIR term it names. Recognition identifies the bound local and the factory hands
// this sugar its already-built body. Desugar never re-opens the factory from raw syntax.

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{
    has_tuple_producer, CompositeFloor, ConstraintFloor, SugarBody, SugarBuildCtx, TermFloor,
    TupleProducerFloor,
};
use crate::sugar::term_leaf::{reasoned_incomplete, resolved_term};
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};
use syn::{Expr, ExprPath};
use tracing::debug;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("bound_path", &["path"], recognize);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "bound_constraint",
    SugarRole::Constraint,
    recognize_constraint,
);

pub(crate) const COMPOSITE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::composite_before(
    "bound_path_composite",
    &["reference_sequence"],
    recognize_composite,
);

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::tuple_producer("bound_path_tuple_producer", recognize_tuple_producer);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_role(expr, fcx, BoundPathRole::Term)
}

fn recognize_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_role(expr, fcx, BoundPathRole::Constraint)
}

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_role(expr, fcx, BoundPathRole::Composite)
}

fn recognize_tuple_producer(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_role(expr, fcx, BoundPathRole::TupleProducer)
}

fn recognize_role(expr: &Expr, fcx: &SugarBuildCtx, role: BoundPathRole) -> Option<Box<dyn Sugar>> {
    let name = simple_local_path(expr)?;
    if fcx.resolving_bound_path(&name) {
        return None;
    }
    if let Some(hit) = alias_deref_mutated_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = temporally_unstable_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = unknown_iterator_consumption_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = unknown_mutation_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = ambiguous_identity_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = unresolved_destructured_source_backstop(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = runtime_destructured_source_refusal(&name, fcx) {
        return Some(hit);
    }
    construct_bound_path_sugar(name, fcx, role)
}

#[derive(Clone, Copy)]
enum BoundPathRole {
    Term,
    Constraint,
    Composite,
    TupleProducer,
}

impl BoundPathRole {
    fn as_log_role(self) -> &'static str {
        match self {
            BoundPathRole::Term => "Term",
            BoundPathRole::Constraint => "Constraint",
            BoundPathRole::Composite => "Composite",
            BoundPathRole::TupleProducer => "TupleProducer",
        }
    }
}

enum BoundPathSugar {
    Term {
        name: String,
        body: SugarBody<TermFloor>,
    },
    Constraint {
        name: String,
        body: SugarBody<ConstraintFloor>,
    },
    Composite {
        name: String,
        body: SugarBody<CompositeFloor>,
    },
    TupleProducer {
        name: String,
        body: SugarBody<TupleProducerFloor>,
    },
}

struct BoundPathTemporalEffectSugar {
    boundary: String,
    reason: String,
}

impl Sugar for BoundPathTemporalEffectSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
            boundary: self.boundary.clone(),
            reason: self.reason.clone(),
        })
    }
}

fn temporal_effect(name: &str, reason: String) -> Box<dyn Sugar> {
    Box::new(BoundPathTemporalEffectSugar {
        boundary: name.to_string(),
        reason,
    })
}

impl BoundPathSugar {
    fn name(&self) -> &str {
        match self {
            Self::Term { name, .. }
            | Self::Constraint { name, .. }
            | Self::Composite { name, .. }
            | Self::TupleProducer { name, .. } => name,
        }
    }

    fn role(&self) -> BoundPathRole {
        match self {
            Self::Term { .. } => BoundPathRole::Term,
            Self::Constraint { .. } => BoundPathRole::Constraint,
            Self::Composite { .. } => BoundPathRole::Composite,
            Self::TupleProducer { .. } => BoundPathRole::TupleProducer,
        }
    }
}

fn construct_bound_path_sugar(
    name: String,
    fcx: &SugarBuildCtx,
    role: BoundPathRole,
) -> Option<Box<dyn Sugar>> {
    let mut child_fcx = fcx.with_bound_path(&name);
    if let Some(expected) = fcx.scope().let_binding_expected_type(&name) {
        child_fcx = child_fcx.with_expected_type(Some(expected.to_string()));
    }
    match role {
        BoundPathRole::Term => construct_term_body(&name, fcx, &child_fcx)
            .map(|body| Box::new(BoundPathSugar::Term { name, body }) as Box<dyn Sugar>),
        BoundPathRole::Constraint => construct_constraint_body(&name, fcx, &child_fcx)
            .map(|body| Box::new(BoundPathSugar::Constraint { name, body }) as Box<dyn Sugar>),
        BoundPathRole::Composite => construct_composite_body(&name, fcx, &child_fcx)
            .map(|body| Box::new(BoundPathSugar::Composite { name, body }) as Box<dyn Sugar>),
        BoundPathRole::TupleProducer => construct_tuple_producer_body(&name, fcx, &child_fcx)
            .map(|body| Box::new(BoundPathSugar::TupleProducer { name, body }) as Box<dyn Sugar>),
    }
}

fn temporal_rewrite_expr(name: &str, fcx: &SugarBuildCtx, role: BoundPathRole) -> Option<Expr> {
    if let Some(current) = fcx.scope().temporal_rewrite_expr_for(name) {
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            value = %token_key(&current),
            role = role.as_log_role(),
            "factory constructed bound path temporal body"
        );
        return Some(current);
    }
    None
}

fn construct_term_body(
    name: &str,
    fcx: &SugarBuildCtx,
    child_fcx: &SugarBuildCtx,
) -> Option<SugarBody<TermFloor>> {
    if let Some(term) = fcx.scope().temporal_rewrite_term_for(name) {
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name,
            role = "Term",
            "factory constructed bound path temporal term body"
        );
        return Some(SugarBody::from_node(resolved_term(term)));
    }
    if let Some(current) = temporal_rewrite_expr(name, fcx, BoundPathRole::Term) {
        return Some(SugarBody::term(&current, child_fcx));
    }
    if let Some(term) = fcx.scope().stable_term_binding_for_term(name) {
        debug!(
            target: "sugar_lift_rust_tests::bound_path",
            binding = name,
            role = "Term",
            "factory constructed bound path term-binding body"
        );
        return Some(SugarBody::from_node(resolved_term(term)));
    }
    let init = fcx.scope().stable_let_binding_for_term(name)?;
    Some(SugarBody::term(init, child_fcx))
}

fn construct_constraint_body(
    name: &str,
    fcx: &SugarBuildCtx,
    child_fcx: &SugarBuildCtx,
) -> Option<SugarBody<ConstraintFloor>> {
    if let Some(current) = temporal_rewrite_expr(name, fcx, BoundPathRole::Constraint) {
        return Some(SugarBody::constraint(&current, child_fcx));
    }
    let init = fcx.scope().stable_let_binding_for_term(name)?;
    Some(SugarBody::constraint(init, child_fcx))
}

fn construct_composite_body(
    name: &str,
    fcx: &SugarBuildCtx,
    child_fcx: &SugarBuildCtx,
) -> Option<SugarBody<CompositeFloor>> {
    if let Some(current) = temporal_rewrite_expr(name, fcx, BoundPathRole::Composite) {
        return Some(SugarBody::composite(&current, child_fcx));
    }
    let init = fcx.scope().stable_let_binding_for_term(name)?;
    Some(SugarBody::composite(init, child_fcx))
}

fn construct_tuple_producer_body(
    name: &str,
    fcx: &SugarBuildCtx,
    child_fcx: &SugarBuildCtx,
) -> Option<SugarBody<TupleProducerFloor>> {
    if let Some(current) = temporal_rewrite_expr(name, fcx, BoundPathRole::TupleProducer) {
        return has_tuple_producer(&current, child_fcx)
            .then(|| SugarBody::tuple_producer(&current, child_fcx));
    }
    let init = fcx.scope().stable_let_binding_for_term(name)?;
    has_tuple_producer(init, child_fcx).then(|| SugarBody::tuple_producer(init, child_fcx))
}

impl Sugar for BoundPathSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::bound_path",
            binding = self.name(),
            role = self.role().as_log_role(),
            "reducing factory-constructed bound path body"
        );
        match self {
            BoundPathSugar::Term { body, .. } => body.reduce(ctx),
            BoundPathSugar::Constraint { body, .. } => body.reduce(ctx),
            BoundPathSugar::Composite { body, .. } => body.reduce(ctx),
            BoundPathSugar::TupleProducer { body, .. } => body.reduce(ctx),
        }
    }
}

fn runtime_destructured_source_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope().is_runtime_destructured_local(name).then(|| {
        reasoned_incomplete(format!(
            "destructured source runtime, not literal for `{name}`: pattern binding participates \
             in the assertion, but the destructured source did not resolve to a literal tuple/array; \
             refused"
        ))
    })
}

fn unresolved_destructured_source_backstop(
    name: &str,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    fcx.scope().is_unresolved_destructured_local(name).then(|| {
        reasoned_incomplete(format!(
            "destructured source trace unresolved for `{name}`: pattern binding participates \
             in the assertion, but SSA has not traced the destructured source to literal \
             components yet"
        ))
    })
}

/// THE NO-FALSE-REFUTATION GATE. A local MUTATED through a `&mut` alias the tracker
/// cannot resolve (`let r = &mut x; *r += 1;`) has a STALE tracked value -- the
/// alias-deref mutation is refused, so the rewrite never applies it. Reading that local
/// would lift the pre-mutation literal (`assert_eq!(x, 6)` -> `5 == 6`, UNSAT), which
/// REFUTES a true assertion: the inverse cardinal sin (a fake dragon over correct code).
/// So such a read REFUSES by name instead of resolving. This is conservative refuse-
/// tightening (it never adds a warrant, so it cannot false-DISCHARGE) and it makes the
/// no-false-refutation an EXPLICIT, intentional refuse rather than a coincidental
/// co-refusal masking. It does NOT warrant the post-mutation value -- that is the
/// attended SSA arm's job; this only stops the stale read.
fn alias_deref_mutated_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope().is_alias_deref_mutated(name).then(|| {
        // Classified as `ambiguous temporal identity` (the terminal-today Refused bucket
        // for an aliased-mutated value with no single `t`) -- the SAME family as a
        // conditionally/aliased-mutated receiver. Per the boundary-call note on that
        // reason, it flips to a warrant once the attended SSA arm teaches alias-mutation
        // resolution; until then it is a NAMED dragon, not a stale fake-light.
        temporal_effect(
            name,
            format!(
                "ambiguous temporal identity for `{name}`: mutated through a `&mut` alias \
             between borrow and read, so there is no single timeless value to read at the \
             assertion; refused"
            ),
        )
    })
}

/// THE NO-FALSE-REFUTATION GATE for the TEMPORAL-INSTABILITY class (#2342 sibling). A local
/// mutated (a counter via `+=`/`=`) inside a loop OR closure body the tracker cannot unroll-
/// resolve, then read afterward, has a STALE tracked value (its initial literal -- the
/// mutations were never applied). Reading it
/// lifts that stale value (`assert_eq!(n, 3)` -> `0 == 3`, UNSAT), which REFUTES a true
/// assertion (the inverse cardinal sin). So the read REFUSES by name. Conservative refuse-
/// tightening (zero new warrant -> zero cardinal-sin risk); it does NOT warrant the value
/// (warrant-side SSA, out of scope). Fed by `collect_loop_counter_stale_reads` (read-after-
/// gated counters) + `collect_loop_body_mutated` (broader loop/closure/consumed-iterator).
fn temporally_unstable_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope().is_temporally_unstable_read(name).then(|| {
        // Terminal refusal; substring `temporally unstable post-loop read` is pinned by tests.
        temporal_effect(
            name,
            format!(
                "temporally unstable post-loop read of `{name}`: for-loop domain runtime, not \
             literal, or loop/closure body not exactly replayable; there is no single \
             timeless value to read at the assertion; refused as temporally unstable"
            ),
        )
    })
}

/// A mutable iterator driven by a data-dependent terminal (`try_fold`, `try_find`, `any`, ...)
/// or through a borrowed adaptor (`by_ref().take(..).fold(..)`) advances by a count the
/// literal replay ledger does not own. The ledger intentionally forgets the pre-consumption
/// sequence at that boundary; a later read must NAME-REFUSE rather than replay stale source
/// text and refute a true assertion.
fn unknown_iterator_consumption_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope()
        .unknown_iterator_consumption_reason(name)
        .map(|reason| temporal_effect(name, reason))
}

fn unknown_mutation_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope()
        .unknown_mutation_reason(name)
        .map(|reason| temporal_effect(name, reason))
}

fn ambiguous_identity_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope().ambiguous_contains(name).then(|| {
        temporal_effect(
            name,
            format!("ambiguous temporal identity for receiver `{name}`; skipped assertion"),
        )
    })
}

fn simple_local_path(expr: &Expr) -> Option<String> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = expr
    else {
        return None;
    };
    path.get_ident().map(ToString::to_string)
}
