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
//! owning BOTH a recognizer `fn recognize(expr: &Expr, fcx: &FactoryCtx) ->
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
//! `method:` ctor (`method`); the composite one is the
//! `fold`/`for_each`/`closure_adaptor`/`match_scrutinee` quantifier chain.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::catalog;
use crate::sugar::claim::SugarRole;
use crate::{LiftOptions, Sugar, TemporalScope};

/// What a recognizer needs from its environment to construct a node: the temporal
/// `scope` (binding / mutability oracle), the lift `options`, and the in-scope `let`
/// initializers (`name -> &init_expr`) that binding-resolving recognizers (`fold`,
/// `for_each`, `closure_adaptor`) capture. This is the BUILD-time env; the dual
/// [`SugarCtx`] is the DESUGAR-time env.
pub(crate) struct FactoryCtx<'a, 'e> {
    pub(crate) scope: &'a TemporalScope,
    pub(crate) options: &'a LiftOptions,
    pub(crate) let_inits: &'a BTreeMap<String, &'e Expr>,
}

pub(crate) fn build_expr(expr: &Expr, fcx: &FactoryCtx, role: SugarRole) -> Box<dyn Sugar> {
    catalog::build_expr_role(expr, fcx, role)
}

/// Compatibility TERM wrapper: ask the unified candidate catalog, then return the first
/// candidate whose old source-position role is `Term`, else the structural backstop.
/// TOTAL — every shape news a node (a reasoned leaf for the no-value shapes).
/// RECURSIVE — composite term recognizers build their operands with `build_term`.
pub(crate) fn build_term(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Term)
}

/// Compatibility COMPOSITE wrapper: ask the unified candidate catalog, then return the
/// first candidate whose old source-position role is `Composite`, else the structural
/// backstop. Total: an unowned shape becomes the [`UnsupportedSugar`] backstop.
pub(crate) fn build_composite(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Composite)
}
