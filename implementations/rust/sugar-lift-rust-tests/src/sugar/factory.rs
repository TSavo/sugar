// SPDX-License-Identifier: Apache-2.0
//
//! The recursive Sugar factory: **AST node in, Sugar out**, via two ORDERED REGISTRIES
//! of self-contained recognizer nodes.
//!
//! `build_term(expr, fcx) -> Box<dyn Sugar>` lifts an expression's TERM SUBLANGUAGE;
//! `build_composite(expr, fcx) -> Box<dyn Sugar>` is the DISTINCT statement / sequence
//! dispatch the collector's `.dug()` sites consume. Each shrinks to the SAME shape:
//! walk its registry in order, return the first recognizer's `Some`, else
//! `unsupported()`. That walk is the ENTIRE factory dispatch — there are no inline node
//! structs, no `decompose_*` calls, no term/ctor construction logic here.
//!
//! ## The recognizer-fn pattern
//!
//! Every construct is a SELF-CONTAINED node living in its own `src/sugar/*.rs` module,
//! owning BOTH a recognizer `fn recognize(expr: &Expr, fcx: &FactoryCtx) ->
//! Option<Box<dyn Sugar>>` (returns `Some(boxed self)` if this AST shape matches —
//! building any children via `build_term`/`build_composite` — else `None`) AND its
//! `desugar`. The former free `decompose_*` functions are reused INSIDE these
//! recognizers; the old inline `MethodCallTermSugar`/`CtorSugar`/`ResolvedTermSugar`/
//! `ReasonedHitSugar` now live in their own modules.
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
//! ## Order matters
//!
//! The registry arrays reproduce the CURRENT dispatch precedence exactly: in the term
//! registry, the format-`+` hook precedes the generic `BinOp` (both inside the `Binary`
//! recognizer); in the composite registry, `fold` precedes `for_each` precedes
//! `closure_adaptor` precedes `match_scrutinee`. Because each `Expr` variant is owned by
//! exactly one recognizer (guarded variant splits like `Path`-`None` / `Reference` live
//! INSIDE a single recognizer), the only cross-recognizer precedence that is observable
//! is the method-call composite chain, whose ordering the array encodes directly.
//!
//! ## The genuinely dual shapes
//!
//! `Array`, `Repeat`, and `MethodCall` have DISTINCT term vs composite roles, so they
//! get SEPARATE nodes per registry — never one node branching on a position flag. The
//! term `Expr::Array` is the `literal_aggregate` ctor (`array_term`); the composite
//! `Expr::Array` is the sequence-floor `LiteralSugar` (`literal`). The term `Expr::Repeat`
//! expands a literal-count aggregate (`repeat_term`); the composite one is the
//! `ArrayRepeat` refuse-shape (`array_repeat`). The term `Expr::MethodCall` is the
//! `method:` ctor (`method_call_term`); the composite one is the
//! `fold`/`for_each`/`closure_adaptor`/`match_scrutinee` quantifier chain.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::{
    array_repeat, array_term, await_term, binop, block_term, call, cast_term, closure_adaptor,
    closure_term, conditional, const_block, control_flow_term, field_term, fold, forall, index,
    literal, macro_term, match_node, match_scrutinee, method_call_term, path, range_term,
    raw_addr_term, reference_term, repeat_term, struct_term, term_literal, transparent_term,
    tuple_term, unary,
};
use crate::{LiftOptions, Outcome, Sugar, SugarCtx, TemporalScope};

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

/// The type of a registry entry: an AST-shape recognizer. `Some(node)` if the shape
/// matches (building any children via `build_term`/`build_composite`), else `None`.
type Recognizer = fn(&Expr, &FactoryCtx) -> Option<Box<dyn Sugar>>;

/// The TERM-position recognizers, in dispatch precedence order. Each owns exactly one
/// `Expr` variant (or a guarded split of one); the walk returns the first `Some`.
/// Faithfully reproduces the former `build` match's arm order.
const TERM_RECOGNIZERS: &[Recognizer] = &[
    term_literal::recognize,           // Expr::Lit
    const_block::recognize,            // Expr::Const
    unary::recognize,                  // Expr::Unary
    path::recognize,                   // Expr::Path (None-ctor guard, then make_var)
    call::recognize,                   // Expr::Call (type_id preamble, then call ctor)
    array_term::recognize,             // Expr::Array (literal_aggregate ctor)
    tuple_term::recognize,             // Expr::Tuple
    repeat_term::recognize,            // Expr::Repeat (literal-count aggregate / refuse)
    struct_term::recognize,            // Expr::Struct
    method_call_term::recognize,       // Expr::MethodCall (method: ctor)
    await_term::recognize,             // Expr::Await
    reference_term::recognize,         // Expr::Reference (ref / ref_mut / refuse)
    raw_addr_term::recognize,          // Expr::RawAddr
    cast_term::recognize,              // Expr::Cast
    range_term::recognize,             // Expr::Range
    field_term::recognize,             // Expr::Field
    index::recognize,                  // Expr::Index (const_index + temporal_read, then ctor)
    binop::recognize,                  // Expr::Binary (format-+, then compare, then arith)
    transparent_term::recognize,       // Expr::Paren / Expr::Group (transparent)
    macro_term::recognize,             // Expr::Macro
    closure_term::recognize,           // Expr::Closure
    block_term::recognize,             // Expr::Unsafe / Expr::Block (value-transparent)
    control_flow_term::recognize_term, // Expr::TryBlock / Async / Try (refuse)
];

/// The recursive Sugar factory and COMPLETE TERM LIFTER: walk the term registry and
/// return the first recognizer's node, else the structural backstop. TOTAL — every
/// shape news a node (a reasoned leaf for the no-value shapes). RECURSIVE — composite
/// term recognizers build their operands with `build_term`. Never decides the walk early.
pub(crate) fn build_term(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    for recognize in TERM_RECOGNIZERS {
        if let Some(node) = recognize(expr, fcx) {
            return node;
        }
    }
    unsupported()
}

/// The COMPOSITE / sequence recognizers, in dispatch precedence order. The method-call
/// chain (`fold` -> `for_each` -> `closure_adaptor` -> `match_scrutinee`) is encoded as
/// successive entries so its precedence is the array's. Faithfully reproduces the former
/// `build_composite` + `build_method_call_composite` order.
const COMPOSITE_RECOGNIZERS: &[Recognizer] = &[
    transparent_term::recognize_composite, // Expr::Paren / Expr::Group (transparent)
    conditional::recognize_composite,      // Expr::If (implication)
    match_node::recognize_composite,       // Expr::Match (conjunction)
    forall::recognize_for_loop,            // Expr::ForLoop (universal)
    array_repeat::recognize_composite,     // Expr::Repeat (refuse-shape)
    control_flow_term::recognize_composite, // Expr::TryBlock / Async / Try (refuse-shape)
    literal::recognize_composite,          // Expr::Array / Range (sequence domain)
    fold::recognize_composite,             // Expr::MethodCall fold terminal
    forall::recognize_for_each,            // Expr::MethodCall for_each quantifier
    closure_adaptor::recognize_composite,  // Expr::MethodCall closure-bearing adaptor
    match_scrutinee::recognize_composite,  // Expr::MethodCall match-scrutinee shape
];

/// The recursive composite / sequence factory: the statement-position dispatch the
/// collector's `.dug()` sites consume. DISTINCT from `build_term` (the term lifter):
/// walk the composite registry and return the first recognizer's node, else the
/// structural backstop. Total: an unowned shape becomes the [`UnsupportedSugar`] backstop.
pub(crate) fn build_composite(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    for recognize in COMPOSITE_RECOGNIZERS {
        if let Some(node) = recognize(expr, fcx) {
            return node;
        }
    }
    unsupported()
}

/// Box a recognized concrete node, or fall to the structural backstop when a decomposer
/// declined (`None`). Used by the composite recognizers that wrap an `Option<S>`-
/// returning `decompose_*` whose `None` is a recognized-but-declined verdict (the `If`/
/// `Match`/`ForLoop`/`Repeat`/control-flow arms boxed it directly in the old factory).
pub(crate) fn boxed<S: Sugar + 'static>(node: Option<S>) -> Box<dyn Sugar> {
    match node {
        Some(node) => Box::new(node),
        None => unsupported(),
    }
}

/// The structural backstop leaf.
fn unsupported() -> Box<dyn Sugar> {
    Box::new(UnsupportedSugar)
}

/// The structural backstop: an AST shape the factory does not own. `desugar` is the
/// byte-identical legacy `None` bail (`Outcome::from_opt(None)` -> `Hit(Effect::
/// Unsupported)` carrying the structural-backstop reason), discarded by a `.dug()`
/// consumer exactly as the old `None` was.
struct UnsupportedSugar;

impl Sugar for UnsupportedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt(None)
    }
}
