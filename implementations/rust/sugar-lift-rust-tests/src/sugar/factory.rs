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

use syn::{Expr, Item};

use crate::sugar::{
    array_repeat, array_term, await_term, binop, block_term, call, cast_term, closure_adaptor,
    closure_term, conditional, const_block, control_flow_term, field_term, fold, forall,
    impl_method, index, iter_terminal, literal, macro_term, match_node, match_scrutinee,
    method_call_term, monadic, path, range_term, raw_addr_term, reference_term, repeat_term,
    statement_position, struct_term, term_literal, transparent_term, tuple_term, unary,
};
use crate::{
    Effect, LiftOptions, Outcome, Sugar, SugarCtx, TemporalScope, STRUCTURAL_BACKSTOP_REASON,
};

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
    // The std Option/Result CONSTRUCTORS (`Some(x)`/`Ok(x)`/`Err(x)`/`None`) --
    // BEFORE `path` and `call`, so a monadic constructor grounds to its
    // ADT-backed `opt:some`/`res:ok`/... value (structural equality teeth)
    // instead of the generic `call:Some` / `call:None` ctor that would route
    // the equality through the federated, teeth-less `call:eq:Some` EUF path.
    monadic::recognize,                // Expr::Call(Some/Ok/Err) / Expr::Path(None)
    term_literal::recognize,           // Expr::Lit
    const_block::recognize,            // Expr::Const
    unary::recognize,                  // Expr::Unary
    path::recognize,                   // Expr::Path (None-ctor guard, then make_var)
    call::recognize,                   // Expr::Call (type_id preamble, then call ctor)
    array_term::recognize,             // Expr::Array (literal_aggregate ctor)
    tuple_term::recognize,             // Expr::Tuple
    repeat_term::recognize,            // Expr::Repeat (literal-count aggregate / refuse)
    struct_term::recognize,            // Expr::Struct
    // Expr::MethodCall iterator reduction/advance terminal over a LITERAL Seq -- BEFORE
    // the opaque `method:` ctor, so a literal-domain `.sum()`/`.next()`/... grounds to
    // its value; a non-literal / unrecognized receiver returns `None` and falls through
    // to `method_call_term` (the opaque ctor, the established sound under-claim).
    iter_terminal::recognize,
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

/// The type of an ITEM-shape recognizer: an `&syn::Item`-position recognizer. `Some(node)`
/// if the shape matches, else `None`. The `Item` analogue of [`Recognizer`] — an `impl` block
/// is a `syn::Item`/`ItemImpl`, not an `Expr`, so it cannot go through `build_term`/
/// `build_composite`; it gets its own tiny registry walked by [`build_item`].
type ItemRecognizer = fn(&Item, &FactoryCtx) -> Option<Box<dyn Sugar>>;

/// The ITEM-position recognizers, in dispatch precedence order. Currently the single
/// statement-nested-`impl` REFUSE node; faithfully reproduces the former
/// `Stmt::Item(Item::Impl)` router arm's `decompose_impl_method` call.
const ITEM_RECOGNIZERS: &[ItemRecognizer] = &[
    impl_method::recognize, // Item::Impl (statement-nested asserting impl method)
];

/// The recursive Sugar factory for ITEM-position constructs: the third dispatch the
/// collector's statement-nested-`impl` site consumes. DISTINCT from `build_term` /
/// `build_composite` because its input is a `syn::Item`, not an `Expr`. Same shape: walk the
/// item registry and return the first recognizer's node, else the structural backstop. Total:
/// a pure / assert-free `impl` becomes the [`UnsupportedSugar`] backstop, which the
/// verdict-reading router discards exactly as the old `decompose_impl_method` `None`.
pub(crate) fn build_item(item: &Item, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    for recognize in ITEM_RECOGNIZERS {
        if let Some(node) = recognize(item, fcx) {
            return node;
        }
    }
    unsupported()
}

/// Build the closure-adaptor REFUSE node for a statement expr (the [`closure_adaptor`] node),
/// walking its single-recognizer registry. The verdict-reading routers
/// (`closure_method_terminal_effect`) `desugar` this and read the named order-loss `Effect`;
/// a non-recognized shape returns the [`UnsupportedSugar`] backstop, which those routers
/// discard exactly as the old `decompose_closure_adaptor` `None`. This is the SAME node the
/// composite registry's `closure_adaptor::recognize_composite` slot produces in the method-call
/// chain; this entry is the verdict-reader's dedicated single-shape walk (it never competes
/// with `fold`/`for_each` precedence — the router wants the closure-adaptor verdict alone).
pub(crate) fn build_closure_adaptor(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    closure_adaptor::recognize_composite(expr, fcx).unwrap_or_else(unsupported)
}

/// Build the statement-position REFUSE node for a bare statement expr (the
/// [`statement_position`] node), walking its single-recognizer registry. The verdict-reading
/// router (`statement_position_terminal_effect`) `desugar`s this and reads the named
/// value-NOT-in-scope `Effect`; a non-asserting statement returns the [`UnsupportedSugar`]
/// backstop, discarded exactly as the old `decompose_statement_position` `None`.
pub(crate) fn build_statement_position(expr: &Expr, fcx: &FactoryCtx) -> Box<dyn Sugar> {
    statement_position::recognize(expr, fcx).unwrap_or_else(unsupported)
}

/// Build the match-scrutinee REFUSE node for an `Expr::Match` (the [`match_scrutinee`] node),
/// walking its single-recognizer registry. The verdict-reading router
/// (`runtime_match_scrutinee_effect`) `desugar`s this and reads the runtime-match-scrutinee
/// `Effect`; a non-`match` / constructed-scrutinee `match` returns the [`UnsupportedSugar`]
/// backstop, discarded exactly as the old `decompose_match_scrutinee` `None`. The verdict is
/// purely SYNTACTIC (the recognizer and node ignore the build/desugar env), so this entry is
/// ctx-FREE — it needs no `FactoryCtx` and no `SugarCtx`. It both BUILDS the node and reduces
/// it through the node's own ctx-free reduction, returning the `Outcome` directly: a
/// recognized `Expr::Match` over a runtime scrutinee `Hit`s `RuntimeMatchScrutinee`; a
/// non-recognized shape is the structural backstop (`from_opt(None)` =
/// `Hit(Unsupported{STRUCTURAL_BACKSTOP_REASON})`), discarded by the verdict-reading router
/// exactly as the old `decompose_match_scrutinee` `None`. This is what lets the ctx-less
/// `translate_bool_assertion` callsite route through the factory unchanged.
pub(crate) fn build_match_scrutinee(expr: &Expr) -> Outcome {
    match match_scrutinee::recognize(expr) {
        Some(node) => node.desugar_ctx_free(),
        None => Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        }),
    }
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
