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
//! owning BOTH a recognizer `fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) ->
//! Option<Box<dyn Sugar>>` (returns `Some(boxed self)` if this Sugar handles the site --
//! building any children via `build_term`/`build_composite` -- else `None`) AND its
//! `desugar`. The former free `decompose_*` functions are reused INSIDE these
//! recognizers; the old inline `MethodSugar`/`CtorSugar`/`ResolvedTermSugar` now live
//! in their own modules. Ambiguity is represented by
//! MULTIPLE candidates, not by a hidden factory choice.
//!
//! ## The three laws
//!
//! 1. **TOTAL OR CRASH.** Every constructible `Expr` maps to a `Box<dyn Sugar>` whose
//!    `reduce` returns exactly one terminal boundary: `Complete` or `Incomplete(named
//!    Effect)`. A factory miss is not an Outcome; it is a construction-law violation that
//!    must be fixed by writing the Sugar or by proving a named runtime/effect boundary.
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
use std::marker::PhantomData;

use quote::ToTokens;
use sugar_canonicalizer::encode_jcs;
use sugar_ir_symbolic::serialize::formula_to_value;
use syn::spanned::Spanned;
use syn::{Expr, Item, Stmt};
use tracing::{debug, warn};

use crate::sugar::catalog;
use crate::sugar::claim::SugarRole;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    refusal_disposition, token_key, AssertionFactKind, Desugared, DesugaredElem, Disposition,
    Effect, FactoryAudit, FactoryAuditSpan, FactoryCandidateAudit, FactoryDisposition, LiftOptions,
    Outcome, Sugar, SugarCtx, TemporalScope,
};

pub(crate) enum FloorRead<T> {
    Complete(T),
    Incomplete(Effect),
}

pub(crate) trait BodyFloor {}

pub(crate) struct TermFloor;
pub(crate) struct CompositeFloor;
pub(crate) struct ConstraintFloor;
pub(crate) struct AssertionSurfaceFloor;
pub(crate) struct StatementEffectFloor;
pub(crate) struct TupleProducerFloor;
pub(crate) struct LiteralStringFloor;
pub(crate) struct LiteralCStrFloor;
pub(crate) struct FormatTemplateFloor;
pub(crate) struct FormatValueFloor;
pub(crate) struct BoolFloor;
pub(crate) struct IeeeFloatFloor;
pub(crate) struct IpAddrFloor;
/// SymbolicValue floor family. Carries a sort-neutral symbolic variable; the
/// backend chooses the carrier sort from surrounding operations.
#[allow(dead_code)]
pub(crate) struct SymbolicValueFloor;
/// CarrierEmbedding floor family. #3125 slice 2 implements the Duration
/// refinement; MonoidFold still reports this family for unimplemented carriers.
#[allow(dead_code)]
pub(crate) struct CarrierEmbeddingFloor;

impl BodyFloor for TermFloor {}
impl BodyFloor for CompositeFloor {}
impl BodyFloor for ConstraintFloor {}
impl BodyFloor for AssertionSurfaceFloor {}
impl BodyFloor for StatementEffectFloor {}
impl BodyFloor for TupleProducerFloor {}
impl BodyFloor for LiteralStringFloor {}
impl BodyFloor for LiteralCStrFloor {}
impl BodyFloor for FormatTemplateFloor {}
impl BodyFloor for FormatValueFloor {}
impl BodyFloor for BoolFloor {}
impl BodyFloor for IeeeFloatFloor {}
impl BodyFloor for IpAddrFloor {}
impl BodyFloor for SymbolicValueFloor {}
impl BodyFloor for CarrierEmbeddingFloor {}

/// A factory-built child/body for a parent Sugar.
///
/// This is the post-order contract in code: a non-leaf parent is constructed with
/// `SugarBody` values for the expressions it encloses. Raw `Expr` may still be kept for
/// provenance, token keys, literal fast paths, or pattern metadata, but not as the body
/// that the parent later re-builds through the factory.
pub(crate) struct SugarBody<F: BodyFloor> {
    node: Box<dyn Sugar>,
    _floor: PhantomData<F>,
}

impl<F: BodyFloor> SugarBody<F> {
    pub(crate) fn from_node(node: Box<dyn Sugar>) -> Self {
        Self {
            node,
            _floor: PhantomData,
        }
    }

    pub(crate) fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        self.node.reduce(ctx)
    }

    pub(crate) fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

impl SugarBody<TermFloor> {
    pub(crate) fn term(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_term(expr, fcx))
    }

    /// Build a `TermFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognizer bodies that
    /// call this constructor stay clean -- no `as_expr()` in the recognize body.
    pub(crate) fn term_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_term(
            frag.as_expr().expect("term_frag: non-expr fragment"),
            fcx,
        ))
    }

    pub(crate) fn synthesized_term(expr: &Expr, ctx: &SugarCtx) -> Self {
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        Self::term(expr, &fcx)
    }
}

impl SugarBody<IeeeFloatFloor> {
    pub(crate) fn ieee_float(
        expr: &Expr,
        fcx: &SugarBuildCtx,
        width_hint: Option<crate::sugar::float_floor::IeeeFloatWidth>,
        operation: &'static str,
    ) -> Self {
        Self::from_node(crate::sugar::float_floor::build_ieee_float(
            expr, fcx, width_hint, operation,
        ))
    }

    /// Build an `IeeeFloatFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies stay clean.
    pub(crate) fn ieee_float_frag(
        frag: &crate::sugar::source_fragment::SourceFragment,
        fcx: &SugarBuildCtx,
        width_hint: Option<crate::sugar::float_floor::IeeeFloatWidth>,
        operation: &'static str,
    ) -> Self {
        Self::from_node(crate::sugar::float_floor::build_ieee_float(
            frag.as_expr().expect("ieee_float_frag: non-expr fragment"),
            fcx,
            width_hint,
            operation,
        ))
    }
}

impl SugarBody<BoolFloor> {
    pub(crate) fn bool_expr(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_term(expr, fcx))
    }

    /// Build a `BoolFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies stay clean.
    pub(crate) fn bool_expr_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_term(
            frag.as_expr().expect("bool_expr_frag: non-expr fragment"),
            fcx,
        ))
    }
}

impl SugarBody<CompositeFloor> {
    pub(crate) fn composite(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_composite(expr, fcx))
    }

    /// Build a `CompositeFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies stay clean.
    pub(crate) fn composite_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_composite(
            frag.as_expr().expect("composite_frag: non-expr fragment"),
            fcx,
        ))
    }

    pub(crate) fn synthesized_composite(expr: &Expr, ctx: &SugarCtx) -> Self {
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        Self::composite(expr, &fcx)
    }

    pub(crate) fn reduce_sequence(
        &self,
        ctx: &SugarCtx,
        owner: &'static str,
    ) -> FloorRead<Vec<DesugaredElem>> {
        match self.reduce(ctx) {
            Outcome::Complete(desugared) => FloorRead::Complete(desugared.accept_sequence_floor(
                crate::sugar::sequence_floor::RequiredSequenceVisitor { owner },
            )),
            Outcome::Incomplete(effect) => FloorRead::Incomplete(effect),
        }
    }
}

impl SugarBody<ConstraintFloor> {
    pub(crate) fn constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_constraint(expr, fcx))
    }

    /// Build a `ConstraintFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies stay clean.
    pub(crate) fn constraint_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_constraint(
            frag.as_expr().expect("constraint_frag: non-expr fragment"),
            fcx,
        ))
    }

    pub(crate) fn synthesized_constraint(expr: &Expr, ctx: &SugarCtx) -> Self {
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        Self::constraint(expr, &fcx)
    }
}

impl SugarBody<AssertionSurfaceFloor> {
    pub(crate) fn assertion_surface(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_assertion_surface(expr, fcx))
    }
}

impl SugarBody<StatementEffectFloor> {
    pub(crate) fn statement_effect(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Self> {
        has_expr_role(expr, fcx, SugarRole::StatementEffect)
            .then(|| Self::from_node(build_expr(expr, fcx, SugarRole::StatementEffect)))
    }
}

impl SugarBody<TupleProducerFloor> {
    pub(crate) fn tuple_producer(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_tuple_producer(expr, fcx))
    }

    /// Build a `TupleProducerFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies stay clean.
    pub(crate) fn tuple_producer_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(build_tuple_producer(
            frag.as_expr()
                .expect("tuple_producer_frag: non-expr fragment"),
            fcx,
        ))
    }
}

impl SugarBody<LiteralStringFloor> {
    pub(crate) fn literal_string(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(crate::sugar::format::build_literal_string_body(expr, fcx))
    }

    pub(crate) fn reduce_literal_string(&self, ctx: &SugarCtx) -> FloorRead<String> {
        crate::sugar::format::literal_string_floor_from_outcome(self.reduce(ctx))
    }
}

impl SugarBody<LiteralCStrFloor> {
    pub(crate) fn literal_cstr(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(crate::sugar::cstr::build_literal_cstr_body(expr, fcx))
    }

    pub(crate) fn reduce_literal_cstr(
        &self,
        ctx: &SugarCtx,
    ) -> FloorRead<crate::sugar::cstr::CStrBytes> {
        crate::sugar::cstr::literal_cstr_floor_from_outcome(self.reduce(ctx))
    }
}

impl SugarBody<FormatTemplateFloor> {
    pub(crate) fn format_template(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(crate::sugar::format::build_format_template_body(expr, fcx))
    }

    pub(crate) fn reduce_format_template(&self, ctx: &SugarCtx) -> FloorRead<String> {
        crate::sugar::format::format_template_floor_from_outcome(self.reduce(ctx))
    }
}

impl SugarBody<FormatValueFloor> {
    pub(crate) fn format_value(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(crate::sugar::format::build_format_value_body(expr, fcx))
    }

    /// Build a `FormatValueFloor` child from a `&SourceFragment`. The `as_expr()` escape
    /// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies stay clean.
    pub(crate) fn format_value_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        Self::from_node(crate::sugar::format::build_format_value_body(
            frag.as_expr()
                .expect("format_value_frag: non-expr fragment"),
            fcx,
        ))
    }

    pub(crate) fn reduce_format_value(
        &self,
        ctx: &SugarCtx,
    ) -> FloorRead<crate::sugar::format::FmtValue> {
        crate::sugar::format::format_value_floor_from_outcome(self.reduce(ctx))
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
    expected_type: Option<String>,
    expected_sequence_array_len: Option<usize>,
    bound_path_stack: Vec<String>,
    const_path_stack: Vec<String>,
    macro_depth: usize,
    panic_freedom_effect: Option<Effect>,
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
            expected_type: None,
            expected_sequence_array_len: None,
            bound_path_stack: Vec::new(),
            const_path_stack: Vec::new(),
            macro_depth: 0,
            panic_freedom_effect: None,
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

    pub(crate) fn expected_type(&self) -> Option<&str> {
        self.expected_type.as_deref()
    }

    pub(crate) fn expected_sequence_array_len(&self) -> Option<usize> {
        self.expected_sequence_array_len
    }

    pub(crate) fn with_expected_type(&self, expected_type: Option<String>) -> Self {
        Self {
            scope: self.scope,
            options: self.options,
            let_inits: self.let_inits,
            expected_type,
            expected_sequence_array_len: self.expected_sequence_array_len,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack: self.const_path_stack.clone(),
            macro_depth: self.macro_depth,
            panic_freedom_effect: self.panic_freedom_effect.clone(),
        }
    }

    pub(crate) fn with_expected_sequence_array_len(
        &self,
        expected_sequence_array_len: Option<usize>,
    ) -> Self {
        Self {
            scope: self.scope,
            options: self.options,
            let_inits: self.let_inits,
            expected_type: self.expected_type.clone(),
            expected_sequence_array_len,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack: self.const_path_stack.clone(),
            macro_depth: self.macro_depth,
            panic_freedom_effect: self.panic_freedom_effect.clone(),
        }
    }

    pub(crate) fn with_scope<'s>(&self, scope: &'s TemporalScope) -> SugarBuildCtx<'s, 'e>
    where
        'a: 's,
    {
        SugarBuildCtx {
            scope,
            options: self.options,
            let_inits: self.let_inits,
            expected_type: self.expected_type.clone(),
            expected_sequence_array_len: self.expected_sequence_array_len,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack: self.const_path_stack.clone(),
            macro_depth: self.macro_depth,
            panic_freedom_effect: self.panic_freedom_effect.clone(),
        }
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
            expected_type: self.expected_type.clone(),
            expected_sequence_array_len: self.expected_sequence_array_len,
            bound_path_stack,
            const_path_stack: self.const_path_stack.clone(),
            macro_depth: self.macro_depth,
            panic_freedom_effect: self.panic_freedom_effect.clone(),
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
            expected_type: self.expected_type.clone(),
            expected_sequence_array_len: self.expected_sequence_array_len,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack,
            macro_depth: self.macro_depth,
            panic_freedom_effect: self.panic_freedom_effect.clone(),
        }
    }

    pub(crate) fn macro_depth(&self) -> usize {
        self.macro_depth
    }

    pub(crate) fn with_macro_depth(&self, macro_depth: usize) -> Self {
        Self {
            scope: self.scope,
            options: self.options,
            let_inits: self.let_inits,
            expected_type: self.expected_type.clone(),
            expected_sequence_array_len: self.expected_sequence_array_len,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack: self.const_path_stack.clone(),
            macro_depth,
            panic_freedom_effect: self.panic_freedom_effect.clone(),
        }
    }

    pub(crate) fn panic_freedom_effect(&self) -> Option<&Effect> {
        self.panic_freedom_effect.as_ref()
    }

    pub(crate) fn with_panic_freedom_effect(&self, effect: Option<Effect>) -> Self {
        Self {
            scope: self.scope,
            options: self.options,
            let_inits: self.let_inits,
            expected_type: self.expected_type.clone(),
            expected_sequence_array_len: self.expected_sequence_array_len,
            bound_path_stack: self.bound_path_stack.clone(),
            const_path_stack: self.const_path_stack.clone(),
            macro_depth: self.macro_depth,
            panic_freedom_effect: effect,
        }
    }
}

pub(crate) fn desugar_build_ctx<'a, 'e>(
    scope: &'a TemporalScope,
    options: &'a LiftOptions,
    let_inits: &'a BTreeMap<String, &'e Expr>,
) -> SugarBuildCtx<'a, 'e> {
    SugarBuildCtx::new(scope, options, let_inits)
}

pub(crate) fn build_expr(expr: &Expr, fcx: &SugarBuildCtx, role: SugarRole) -> Box<dyn Sugar> {
    catalog::build_expr_role(expr, fcx, role)
}

pub(crate) fn reduce_expr(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    role: SugarRole,
    ctx: &SugarCtx,
) -> Outcome {
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
/// TOTAL — every shape news either a lawful sugar node or the loud factory-gap node.
/// RECURSIVE — composite term recognizers build their operands with `build_term`.
pub(crate) fn build_term(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Term)
}

pub(crate) fn reduce_term(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Outcome {
    reduce_expr(expr, fcx, SugarRole::Term, ctx)
}

/// Compatibility COMPOSITE wrapper: ask the unified candidate catalog, then return the
/// first candidate whose old source-position role is `Composite`, else the structural
/// gap sentinel. Total: an unowned shape becomes the loud factory-gap node; recognizers
/// must not manufacture that node from their own failed construction.
pub(crate) fn build_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_expr(expr, fcx, SugarRole::Composite)
}

pub(crate) fn reduce_composite(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Outcome {
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

pub(crate) fn reduce_constraint(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Outcome {
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

/// Fragment-based variant of `has_tuple_producer`. The `as_expr()` escape lives HERE
/// (inside `factory.rs`, ratchet-excluded) so recognize bodies that call this stay clean.
pub(crate) fn has_tuple_producer_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> bool {
    match frag.as_expr() {
        Some(expr) => has_tuple_producer(expr, fcx),
        None => false,
    }
}

/// Fragment-based variant of `has_composite`. The `as_expr()` escape lives HERE
/// (inside `factory.rs`, ratchet-excluded) so recognize bodies that call this stay clean.
pub(crate) fn has_composite_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> bool {
    match frag.as_expr() {
        Some(expr) => has_composite(expr, fcx),
        None => false,
    }
}

/// Fragment-based variant of `build_term`. The `as_expr()` escape lives HERE
/// (inside `factory.rs`, ratchet-excluded) so recognize bodies that call this stay clean.
/// Used by transparent-passthrough recognizers that return a child Sugar directly.
pub(crate) fn build_term_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_term(
        frag.as_expr().expect("build_term_frag: non-expr fragment"),
        fcx,
    )
}

/// Fragment-based variant of `build_composite`. The `as_expr()` escape lives HERE
/// (inside `factory.rs`, ratchet-excluded) so recognize bodies that call this stay clean.
/// Used by transparent-passthrough recognizers that return a child Sugar directly.
pub(crate) fn build_composite_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    build_composite(
        frag.as_expr()
            .expect("build_composite_frag: non-expr fragment"),
        fcx,
    )
}

/// Fragment-based variant of `build_literal_string_term_node`. The `as_expr()` escape
/// lives HERE (inside `factory.rs`, ratchet-excluded) so recognize bodies that call
/// this stay clean. Used by macro recognizers (concat!, string_add, to_string) whose
/// struct holds a `SugarBody<LiteralStringFloor>` with no raw syn fields.
pub(crate) fn build_literal_string_term_node_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Box<dyn Sugar> {
    crate::sugar::format::build_literal_string_term_node(
        frag.as_expr()
            .expect("build_literal_string_term_node_frag: non-expr fragment"),
        fcx,
    )
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

    #[allow(dead_code)]
    pub(crate) fn stmt(
        stmt: &Stmt,
        requested_role: SugarRole,
        selected: Option<&'static str>,
        candidates: Vec<FactoryCandidateAudit>,
    ) -> Self {
        Self {
            ast_kind: "stmt",
            site: stmt.to_token_stream().to_string(),
            line: stmt.span().start().line,
            span: Some(factory_audit_span(stmt.span())),
            requested_role: format!("{requested_role:?}"),
            selected,
            candidates,
        }
    }

    fn audit_result(&self, outcome: &Outcome) -> FactoryAudit {
        let (disposition, output, reason) = self.disposition_outcome(outcome);
        let emitted_formula = emitted_formula_jcs(outcome);
        self.audit_with(disposition, output, reason, emitted_formula)
    }

    fn audit_with(
        &self,
        disposition: FactoryDisposition,
        output: &'static str,
        reason: Option<String>,
        emitted_formula: Option<String>,
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
            emitted_formula,
        }
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
            Outcome::Complete(Desugared::LiteralString(_)) => {
                (FactoryDisposition::Warranted, "literal-string", None)
            }
            Outcome::Complete(Desugared::LiteralCStr(_)) => {
                (FactoryDisposition::Warranted, "literal-cstr", None)
            }
            Outcome::Complete(Desugared::FormatValue(_)) => {
                (FactoryDisposition::Warranted, "format-value", None)
            }
            Outcome::Complete(Desugared::TupleComponents(_)) => {
                (FactoryDisposition::Warranted, "tuple-components", None)
            }
            Outcome::Complete(Desugared::TermSeq(_)) => {
                (FactoryDisposition::Warranted, "term-sequence", None)
            }
            Outcome::Complete(Desugared::Seq(seq)) if seq.is_empty() => (
                FactoryDisposition::Support,
                "empty-sequence",
                Some("inert: empty sequence; no obligation emitted".to_string()),
            ),
            Outcome::Complete(Desugared::Seq(_)) => (FactoryDisposition::Warranted, "sequence", None),
            // Statement-composition floor variants: the factory marks them Support
            // (inert) here; BlockSugar will consume and emit a Constraints internally.
            Outcome::Complete(Desugared::StmtSupport) => {
                (FactoryDisposition::Support, "stmt-support", None)
            }
            Outcome::Complete(Desugared::StmtBound { .. }) => {
                (FactoryDisposition::Support, "stmt-bound", None)
            }
            Outcome::Complete(Desugared::StmtReturn(_)) => {
                (FactoryDisposition::Warranted, "stmt-return", None)
            }
            Outcome::Complete(Desugared::StmtGuarded(_)) => {
                (FactoryDisposition::Warranted, "stmt-guarded", None)
            }
            Outcome::Complete(Desugared::StmtBlock { .. }) => {
                (FactoryDisposition::Warranted, "stmt-block", None)
            }
            Outcome::Incomplete(effect) => {
                let reason = effect.reason();
                match refusal_disposition(&reason) {
                    Disposition::Refused => (FactoryDisposition::Refused, "effect", Some(reason)),
                    Disposition::Inactive => (
                        FactoryDisposition::Support,
                        "inactive",
                        Some(format!("inert: {reason}")),
                    ),
                    Disposition::Unclassified => {
                        panic!(
                            "incomplete Outcome has an unclassified Effect: {reason}; all Incomplete Outcomes must carry a named terminal Effect"
                        )
                    }
                }
            }
        }
    }

    pub(crate) fn unresolved_reason(&self) -> String {
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

fn emitted_formula_jcs(outcome: &Outcome) -> Option<String> {
    let Outcome::Complete(Desugared::Constraints { atom, .. }) = outcome else {
        return None;
    };
    Some(encode_jcs(formula_to_value(atom.as_ref()).as_ref()))
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
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let outcome = self.inner.reduce(ctx);
        let audit = self.seed.audit_result(&outcome);
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
        outcome
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
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

        let audit = seed.audit_result(&outcome);

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
    fn named_effect_stays_incomplete_outcome() {
        let seed = FactoryAuditSeed {
            ast_kind: "expr",
            site: "&mut x".to_string(),
            line: 7,
            span: None,
            requested_role: "Term".to_string(),
            selected: Some("reference_term"),
            candidates: Vec::new(),
        };

        let outcome = Outcome::Incomplete(Effect::TemporalRead {
            boundary: "&mut x".to_string(),
        });

        let audit = seed.audit_result(&outcome);
        assert_eq!(audit.disposition, FactoryDisposition::Refused);
        assert_eq!(audit.output, "effect");
    }
}
