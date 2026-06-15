// SPDX-License-Identifier: Apache-2.0
//
//! The recursive Sugar factory (`SugarFactory`): **AST node in, Sugar out.**
//!
//! `build(expr) -> Box<dyn Sugar>` is the ONE named, TOTAL, recursive entry that
//! unifies the formerly-scattered `decompose_*` constructors. The collector used
//! to try each `decompose_*` inline at the point a shape can appear (a `fold` here,
//! an `if` there, a `match` somewhere else); that scatter IS what this factory
//! replaces. Read it and the engine exposes itself:
//!
//! > "Oh, look — a node. `new` the right Sugar, keep composing. At the end, call
//! > `desugar` and let the objects collapse the result into an `Outcome`."
//!
//! ## The three laws
//!
//! 1. **TOTAL.** Every `Expr` maps to *some* `Box<dyn Sugar>`. An AST shape the
//!    Sugar pipeline does not yet own becomes [`UnsupportedSugar`] — a structural
//!    backstop leaf, NEVER a silent skip. `build` cannot return `None`.
//! 2. **RECURSIVE.** A composite builds each operand with `build(child)` and
//!    composes the child Sugar; transparent wrappers (`Paren`/`Group`) recurse
//!    straight through. `desugar` then collapses the whole tree inside-out.
//! 3. **NEVER DECIDE EARLY (the sin).** `build` only *recognizes and news*; it
//!    never decides whether the walk "should stop". Degeneracy is a LEAF property
//!    (`Lit` → `Dug`; runtime / opaque / mutated → `Hit`) that propagates for free
//!    through compose-and-propagate composites. A "should I keep going?" check is
//!    the old detection soup sneaking back in.
//!
//! Soundness and auditability then fall out *for free*: `build` total ⟹ every node
//! walked (`SILENT = 0`); `desugar` total ⟹ every walked node judged
//! (`unclassified = 0`); the lift to FOL can only forget structure, never invent
//! it (homomorphism ⟹ sound). There is no second "verify" pass — total composition
//! IS the verdict.
//!
//! ## The Unsupported frontier (the arms still to grow)
//!
//! Today the Sugar pipeline owns the *composite / sequence* shapes (the `decompose_*`
//! family). The *term* sublanguage — scalar literals, `BinOp`/comparison, `Call`,
//! `Path`/binding reads, `Index` digs, `Unary` — is still lifted by the
//! `translate_term_*` / `translate_bool_assertion` pipeline and so reaches
//! [`UnsupportedSugar`] here. That is the honest backstop, not a claim: consumed via
//! `Outcome::dug()` an `Unsupported` leaf yields `None`, exactly the legacy
//! fall-through. Each future slice turns one `Unsupported` arm into a real
//! child-holding node (a `CompareSugar` composing `build(lhs)`/`build(rhs)`, …),
//! at which point the corresponding `translate_*` shard is deleted and its
//! assertion "falls out for free" through the factory.
//!
//! NOT wired into the collector yet — this module is a pure addition (nothing calls
//! `build`), so it cannot move the sweep (`discharged`/`refused`/CID unchanged). The
//! dispatch *order* and the position-dependent arms (statement-position,
//! `impl`-method item-level) are reconciled against the collector's exact try-order
//! in the wiring slice, each step verified byte-identical.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::array_repeat::decompose_array_repeat;
use crate::sugar::closure_adaptor::decompose_closure_adaptor;
use crate::sugar::conditional::decompose_if;
use crate::sugar::control_flow_term::decompose_control_flow_term;
use crate::sugar::fold::decompose_fold;
use crate::sugar::forall::{decompose_for_each, decompose_for_loop};
use crate::sugar::literal::LiteralSugar;
use crate::sugar::match_node::decompose_match;
use crate::sugar::match_scrutinee::decompose_match_scrutinee;
use crate::{LiftOptions, Outcome, Sugar, SugarCtx, TemporalScope};

/// What `build` needs from its environment to construct a node: the temporal
/// `scope` (binding / mutability oracle), the lift `options`, and the in-scope
/// `let` initializers (`name -> &init_expr`) that binding-resolving decomposers
/// (`fold`, `for_each`, `closure_adaptor`) capture. This is the BUILD-time env;
/// the dual [`SugarCtx`] is the DESUGAR-time env. Bundled so the recursive arms
/// stay terse — `build(child, fcx)`.
pub(crate) struct FactoryCtx<'a, 'e> {
    pub(crate) scope: &'a TemporalScope,
    pub(crate) options: &'a LiftOptions,
    pub(crate) let_inits: &'a BTreeMap<String, &'e Expr>,
}

/// The recursive Sugar factory: an `Expr` in, a `Box<dyn Sugar>` out. TOTAL — the
/// `_` arm is the structural backstop, never a skip. RECURSIVE — `Paren`/`Group`
/// recurse and composite decomposers build their own children. NEVER decides the
/// walk early — degeneracy is judged at `desugar`, not here.
pub(crate) fn build(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    match expr {
        // Transparent wrappers: recurse straight through (parentheses / invisible
        // delimiter groups carry no semantics of their own).
        Expr::Paren(p) => build(&p.expr, fcx),
        Expr::Group(g) => build(&g.expr, fcx),

        // Structural composites the Sugar pipeline owns. Each `decompose_*` returns
        // `None` when the instance is not its constructible shape (a runtime
        // receiver, a mutating body, a count mismatch); `boxed` turns that into the
        // `Unsupported` backstop, keeping `build` total.
        Expr::If(i) => boxed(decompose_if(i)),
        Expr::Match(m) => boxed(decompose_match(m, fcx.scope, fcx.options)),
        Expr::ForLoop(f) => boxed(decompose_for_loop(f, fcx.scope, fcx.let_inits)),

        // Array-repeat terminal (`[x; n]`) refuse-shape.
        Expr::Repeat(_) => boxed(decompose_array_repeat(expr)),

        // Control-flow term shapes (`try { .. }` / `async { .. }` / `?`): named
        // order-loss boundaries.
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => {
            boxed(decompose_control_flow_term(expr))
        }

        // The literal floor: a finite literal array / closed range bottoms out in
        // `LiteralSugar` (its `desugar` `Hit`s if the array/range is not actually a
        // closed literal domain).
        Expr::Array(_) | Expr::Range(_) => Box::new(LiteralSugar { base: expr.clone() }),

        // Method-call shapes, tried in the collector's recognizer order: a `fold`
        // terminal, a `for_each` quantifier, a closure-bearing adaptor, then a
        // match-scrutinee method shape. A method call matching none of these is a
        // term-pipeline value (e.g. `x.len()`) and reaches the backstop.
        Expr::MethodCall(_) => build_method_call(expr, fcx),

        // Everything else is still owned by the `translate_term_*` pipeline — the
        // Unsupported frontier (see module docs). The structural backstop, not a
        // claim of completeness.
        _ => unsupported(),
    }
}

/// The method-call recognizer chain. Distinct decomposers return distinct concrete
/// node types, so this is a first-match cascade rather than an `Option` `or_else`.
fn build_method_call(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    if let Some(node) = decompose_fold(expr, fcx.let_inits) {
        return Box::new(node);
    }
    if let Some(node) = decompose_for_each(expr, fcx.scope, fcx.let_inits) {
        return Box::new(node);
    }
    if let Some(node) = decompose_closure_adaptor(expr, fcx.let_inits) {
        return Box::new(node);
    }
    if let Some(node) = decompose_match_scrutinee(expr) {
        return Box::new(node);
    }
    unsupported()
}

/// Box a recognized concrete node, or fall to the structural backstop when the
/// decomposer declined (`None`). The single place `build` stays total over a
/// shape-level recognizer that returned no constructible node.
fn boxed<S: Sugar + 'static>(node: Option<S>) -> Box<dyn Sugar> {
    match node {
        Some(node) => Box::new(node),
        None => unsupported(),
    }
}

/// The structural backstop leaf.
fn unsupported() -> Box<dyn Sugar> {
    Box::new(UnsupportedSugar)
}

/// The structural backstop: an AST shape the Sugar pipeline does not yet own.
/// `desugar` is the byte-identical legacy `None` bail (`Outcome::from_opt(None)` ->
/// `Hit(Effect::Unsupported)` carrying the structural-backstop reason), discarded by
/// a `.dug()` consumer exactly as the old `None` was. It is honest future work — a
/// missing Sugar arm — never a silent skip and never a fake refuse with an invented
/// cause.
struct UnsupportedSugar;

impl Sugar for UnsupportedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt(None)
    }
}
