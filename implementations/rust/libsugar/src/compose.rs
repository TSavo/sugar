// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Contract Composition Protocol (CCP) reference implementation.
//
// Per the spec at protocol/specs/2026-05-09-contract-composition-protocol.md
// (sections 2, 5, 9), this module is the single canonical home for the
// compose primitive. Every per-language lifter (Rust walk, C kernel-doc,
// future Java / Go / TypeScript / Python lifters) calls into THIS function
// either directly (Rust linkage), via the C ABI wrapper in `ffi`, or via
// subprocess transports.
//
// CCP §5 mandates:
//   1. Pure. No state, no I/O, no clock, no random.
//   2. Deterministic. Identical inputs produce identical outputs byte-for-byte.
//   3. Schema-versioned. The CCP version tag is part of the canonical bytes.
//   4. Reference-only. No mutation of inputs.
//
// CCP §9 codifies the eight algebra rules. The implementation here MUST
// follow them byte-for-byte. Any change to the algebra requires a CCP
// version bump.
//
// This module was extracted from `sugar-walk/src/contract.rs` so the
// algebra becomes a workspace-level primitive callable from any consumer.
// Walk continues to host the AST-walking helpers that BUILD a
// FunctionContractMemento from a syn::ItemFn; the algebra that COMPOSES
// mementos lives here.
//
// Internal helpers (substitute_in_formula and the JCS / CID glue) are
// duplicated from walk's wp.rs and canonical.rs so this module is
// self-contained and walk can keep its existing module layout untouched.
// Both copies are pure formula manipulations over identical types from
// sugar-ir-types; byte-equivalent output is guaranteed by construction.

use std::collections::BTreeMap;
use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_ir_types::{
    composition_refusal_compose_input_cid, composition_refusal_header_cid,
    composition_refusal_signature, AggregationStrategy, BlockingEffect, CompositionBoundaryMemento,
    CompositionRefusalEnvelope, CompositionRefusalHeader, CompositionRefusalMetadata,
    CompoundContractMemento, EffectOccurrence, EvidenceMemento, EvidenceRef, IrFormula, IrTerm,
    OccurrenceKind, OccurrenceRole, Sort, SourceKind, SourceLocator, SourceLocatorPoint,
    SourceLocatorSpan,
};

/// CCP version tag carried inside the composed memento body. Bumped only
/// when the algebra changes in a CID-affecting way.
pub const CCP_VERSION: &str = "1.0.0";

// ============================================================
// Effect set
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Effect {
    /// Reads a named state cell (global, capture, mut binding).
    Reads { target: String },
    /// Writes a named state cell.
    Writes { target: String },
    /// Performs IO (println!, file I/O, network, syscall).
    Io,
    /// Contains an unsafe block.
    Unsafe,
    /// May panic on inputs satisfying the precondition.
    Panics,
    /// Calls a function whose effect-set is unknown to the lifter.
    UnresolvedCall { name: String },
    /// Contains a loop whose invariant has not been supplied. The
    /// `loop_cid` is the JCS-byte BLAKE3-512 hash of the loop's
    /// LLBC body block; it identifies the loop independent of the
    /// containing function. A separate `LoopInvariantMemento`
    /// keyed by this loop_cid supplies the invariant + decreasing
    /// function; the substrate refuses to compose this contract
    /// downstream until that memento is present and verified.
    OpaqueLoop { loop_cid: String },
    /// Contains a `?` operator (Try-branch with early return). The
    /// `try_cid` is the content hash of the Switch::Match block that
    /// implements the Try-branch shape. A separate
    /// `TryBranchMemento` (or specific Result/Option-shape spec)
    /// supplies the success-path/failure-path contract pair.
    EarlyReturn { try_cid: String },
    /// Constructs a closure value. The closure body is itself a
    /// regular fun_decl. This effect records the link between the
    /// CAPTURING site (this function) and the body fn.
    ClosureCapture {
        body_fn_cid: String,
        n_captures: usize,
    },
    /// Accepts a `Pin<P>` formal parameter. Opaque until a
    /// PinProjectionMemento supplies the projection safety proof.
    PinnedReference { target: String },
    /// Accepts or dereferences a raw pointer in a formal parameter
    /// position. Always co-present with `Effect::Unsafe`.
    RawPointerProvenance { target: String, mutable: bool },
    /// Calls an atomic intrinsic (core::sync::atomic::Atomic*).
    AtomicAccess {
        target: String,
        kind: AtomicKind,
        ordering: Option<String>,
    },
    /// Emitted when a function has formal parameters that are shared
    /// references (&T) to types with interior mutability.
    PossibleAliasing {
        /// Sorted lexicographically for JCS byte-determinism.
        formals: Vec<String>,
    },
    /// Calls `drop_in_place`. Drops can run user-defined `Drop::drop`,
    /// allocate, panic, or perform arbitrary side effects.
    Drop { name: String },
}

/// Operation class for `Effect::AtomicAccess`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AtomicKind {
    Load,
    Store,
    Rmw,
    Cas,
}

impl AtomicKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            AtomicKind::Load => "load",
            AtomicKind::Store => "store",
            AtomicKind::Rmw => "rmw",
            AtomicKind::Cas => "cas",
        }
    }
}

#[derive(Debug, Clone)]
pub struct AliasingMemento {
    pub formal_a: String,
    pub formal_b: String,
    pub status: AliasingStatus,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AliasingStatus {
    Disjoint,
    MaybeAlias,
}

impl AliasingStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            AliasingStatus::Disjoint => "Disjoint",
            AliasingStatus::MaybeAlias => "MaybeAlias",
        }
    }
}

impl AliasingMemento {
    pub fn to_jcs_value(&self) -> Arc<Value> {
        debug_assert!(
            self.formal_a <= self.formal_b,
            "AliasingMemento invariants violated: formal_a ({}) must be <= formal_b ({})",
            self.formal_a,
            self.formal_b
        );
        Value::object([
            ("kind", Value::string("aliasing-memento")),
            ("formal_a", Value::string(self.formal_a.clone())),
            ("formal_b", Value::string(self.formal_b.clone())),
            ("status", Value::string(self.status.as_str())),
        ])
    }
}

impl Effect {
    fn to_value(&self) -> Arc<Value> {
        match self {
            Effect::Reads { target } => Value::object([
                ("kind", Value::string("reads")),
                ("target", Value::string(target.clone())),
            ]),
            Effect::Writes { target } => Value::object([
                ("kind", Value::string("writes")),
                ("target", Value::string(target.clone())),
            ]),
            Effect::Io => Value::object([("kind", Value::string("io"))]),
            Effect::Unsafe => Value::object([("kind", Value::string("unsafe"))]),
            Effect::Panics => Value::object([("kind", Value::string("panics"))]),
            Effect::UnresolvedCall { name } => Value::object([
                ("kind", Value::string("unresolved_call")),
                ("name", Value::string(name.clone())),
            ]),
            Effect::OpaqueLoop { loop_cid } => Value::object([
                ("kind", Value::string("opaque_loop")),
                ("loopCid", Value::string(loop_cid.clone())),
            ]),
            Effect::EarlyReturn { try_cid } => Value::object([
                ("kind", Value::string("early_return")),
                ("tryCid", Value::string(try_cid.clone())),
            ]),
            Effect::ClosureCapture {
                body_fn_cid,
                n_captures,
            } => Value::object([
                ("kind", Value::string("closure_capture")),
                ("bodyFnCid", Value::string(body_fn_cid.clone())),
                ("nCaptures", Value::integer(*n_captures as i128)),
            ]),
            Effect::PinnedReference { target } => Value::object([
                ("kind", Value::string("pinned_reference")),
                ("target", Value::string(target.clone())),
            ]),
            Effect::RawPointerProvenance { target, mutable } => Value::object([
                ("kind", Value::string("raw_ptr_provenance")),
                ("mutable", Value::boolean(*mutable)),
                ("target", Value::string(target.clone())),
            ]),
            Effect::AtomicAccess {
                target,
                kind,
                ordering,
            } => {
                let mut fields: Vec<(&str, Arc<Value>)> = vec![
                    ("kind", Value::string("atomic_access")),
                    ("atomicKind", Value::string(kind.as_str())),
                    ("target", Value::string(target.clone())),
                ];
                if let Some(ord) = ordering {
                    fields.push(("ordering", Value::string(ord.clone())));
                }
                Value::object(fields)
            }
            Effect::PossibleAliasing { formals } => {
                let formals_arr: Vec<Arc<Value>> =
                    formals.iter().map(|f| Value::string(f.clone())).collect();
                Value::object([
                    ("kind", Value::string("possible_aliasing")),
                    ("formals", Value::array(formals_arr)),
                ])
            }
            Effect::Drop { name } => Value::object([
                ("kind", Value::string("drop")),
                ("name", Value::string(name.clone())),
            ]),
        }
    }

    fn sort_key(&self) -> String {
        // Stable string for sorting effects in the canonical encoding.
        match self {
            Effect::Reads { target } => format!("0:reads:{}", target),
            Effect::Writes { target } => format!("1:writes:{}", target),
            Effect::Io => "2:io".to_string(),
            Effect::Unsafe => "3:unsafe".to_string(),
            Effect::Panics => "4:panics".to_string(),
            Effect::UnresolvedCall { name } => format!("5:unresolved:{}", name),
            Effect::OpaqueLoop { loop_cid } => format!("6:opaque_loop:{}", loop_cid),
            Effect::EarlyReturn { try_cid } => format!("7:early_return:{}", try_cid),
            Effect::ClosureCapture {
                body_fn_cid,
                n_captures,
            } => format!("8:closure_capture:{}:{}", body_fn_cid, n_captures),
            Effect::PinnedReference { target } => format!("9:pinned_reference:{}", target),
            Effect::RawPointerProvenance { target, mutable } => {
                format!("10:raw_ptr_provenance:{}:{}", target, mutable)
            }
            Effect::AtomicAccess {
                target,
                kind,
                ordering,
            } => format!(
                "11:atomic_access:{}:{}:{}",
                target,
                kind.as_str(),
                ordering.as_deref().unwrap_or("")
            ),
            Effect::PossibleAliasing { formals } => {
                format!("13:possible_aliasing:{}", formals.join(","))
            }
            Effect::Drop { name } => format!("14:drop:{}", name),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct EffectSet {
    pub effects: Vec<Effect>,
}

impl EffectSet {
    pub fn empty() -> Self {
        Self { effects: vec![] }
    }
    pub fn is_pure(&self) -> bool {
        self.effects.is_empty()
    }
    pub fn add(&mut self, e: Effect) {
        if !self.effects.iter().any(|x| x == &e) {
            self.effects.push(e);
        }
    }
    fn to_value(&self) -> Arc<Value> {
        let mut sorted = self.effects.clone();
        sorted.sort_by_key(|a| a.sort_key());
        let items: Vec<Arc<Value>> = sorted.iter().map(|e| e.to_value()).collect();
        Value::array(items)
    }
}

// ============================================================
// Locus (data type only; the syn-driven `from_span` constructor lives
// in walk's locus.rs and produces a libsugar Locus).
// ============================================================

/// One source location. `file` is whatever the caller passed in; if
/// None, the locus is from in-memory source or untracked input.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Locus {
    pub file: Option<String>,
    pub line: usize,
    pub col: usize,
}

impl Locus {
    /// Empty/unknown locus.
    pub fn unknown() -> Self {
        Self::default()
    }

    pub fn is_unknown(&self) -> bool {
        self.file.is_none() && self.line == 0 && self.col == 0
    }

    pub fn to_value(&self) -> Arc<Value> {
        Value::object([
            (
                "file",
                match &self.file {
                    Some(p) => Value::string(p.clone()),
                    None => Value::null(),
                },
            ),
            ("line", Value::integer(self.line as i128)),
            ("col", Value::integer(self.col as i128)),
        ])
    }
}

// ============================================================
// FunctionContractMemento
// ============================================================

#[derive(Debug, Clone)]
pub struct FunctionContractMemento {
    pub fn_name: String,
    pub formals: Vec<String>,
    pub formal_sorts: Vec<Sort>,
    pub formal_regions: Vec<Option<String>>,
    pub return_sort: Sort,
    pub return_region: Option<String>,
    pub pre: IrFormula,
    pub post: IrFormula,
    pub body_cid: Option<String>,
    pub effects: EffectSet,
    pub locus: Locus,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
    pub auto_minted_mementos: Vec<AliasingMemento>,
    /// Per-occurrence panic-leaf source loci. METADATA ONLY: these are emitted
    /// into contract envelope headers for verifier attribution, but they do
    /// NOT participate in `canonical_bytes` or `cid` derivation. This shape is
    /// the same `panicLoci` header shape emitted by walk_rpc/cmd_mint and
    /// consumed by the verifier; keep those surfaces in lock-step.
    pub panic_loci: Vec<Arc<Value>>,
    /// Human-supplied concept name extracted from a `// concept: <name>` (or
    /// `/// concept: <name>`) annotation immediately preceding the function.
    ///
    /// - `None`  -- no annotation found
    /// - `Some("UNNAMED-CONCEPT-N")` -- placeholder emitted by the substrate
    /// - `Some("<real-name>")` -- human-supplied name ready for catalog binding
    ///
    /// METADATA ONLY: this field does NOT participate in `canonical_bytes`
    /// or `cid` derivation.  The shape identity is stable regardless of
    /// annotation changes.
    pub concept_hint: Option<String>,
}

impl FunctionContractMemento {
    pub fn is_pure(&self) -> bool {
        self.effects.is_pure()
    }

    /// Extract the term-side of `result = <expr>` from the post, used
    /// when composing this contract's result into another contract's
    /// pre/post. Returns None if the post doesn't have a recognizable
    /// `result = ...` equation.
    pub fn result_value(&self) -> Option<IrTerm> {
        find_result_equation(&self.post, "result")
    }

    /// Short tag used to namespace this contract's `result` variable
    /// when composing. Uses the CID's hex tail.
    pub fn result_var_name(&self) -> String {
        let tail: String = self
            .cid
            .chars()
            .rev()
            .take(12)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect();
        format!("result__{}", tail)
    }

    /// Check that every `Effect::PossibleAliasing` pair of formals has a
    /// matching AliasingMemento in `auto_minted_mementos`. Returns
    /// `Ok(())` if aliasing is fully discharged or no PossibleAliasing
    /// effects are present. Returns the first undischarged pair as an error.
    pub fn check_aliasing_discharged(&self) -> Result<(), OpacityError> {
        for effect in &self.effects.effects {
            if let Effect::PossibleAliasing { formals } = effect {
                if formals.len() < 2 {
                    continue;
                }
                for i in 0..formals.len() {
                    for j in (i + 1)..formals.len() {
                        let a = &formals[i];
                        let b = &formals[j];
                        let covered = self.auto_minted_mementos.iter().any(|m| {
                            (m.formal_a == *a && m.formal_b == *b)
                                || (m.formal_a == *b && m.formal_b == *a)
                        });
                        if !covered {
                            return Err(OpacityError::AliasingNotDischarged {
                                formal_a: a.clone(),
                                formal_b: b.clone(),
                            });
                        }
                    }
                }
            }
        }
        Ok(())
    }
}

/// Build the canonical `Value` for a `FunctionContractMemento`. Used
/// by callers that need to recompute the memento's canonical bytes / CID
/// after replacing fields like the pre/post formulas.
pub fn build_memento_value(c: &FunctionContractMemento) -> Arc<Value> {
    build_value(
        &c.fn_name,
        &c.formals,
        &c.formal_sorts,
        &c.return_sort,
        &c.pre,
        &c.post,
        c.body_cid.as_deref(),
        &c.effects,
        &c.locus,
        &c.auto_minted_mementos,
    )
}

/// Construct the canonical Value tree for a function-contract memento.
/// Public so walk's AST-side builders can compute their own CIDs without
/// having to round-trip through a memento struct first.
#[allow(clippy::too_many_arguments)] // reason: schema-shaped public API used by sugar-walk, which this pass must not edit.
pub fn build_value(
    fn_name: &str,
    formals: &[String],
    formal_sorts: &[Sort],
    return_sort: &Sort,
    pre: &IrFormula,
    post: &IrFormula,
    body_cid: Option<&str>,
    effects: &EffectSet,
    locus: &Locus,
    auto_minted_mementos: &[AliasingMemento],
) -> Arc<Value> {
    let formals_arr: Vec<Arc<Value>> = formals.iter().map(|n| Value::string(n.clone())).collect();
    let formal_sorts_arr: Vec<Arc<Value>> = formal_sorts.iter().map(sort_to_value).collect();
    let body_cid_val: Arc<Value> = match body_cid {
        Some(c) => Value::string(c.to_string()),
        None => Value::null(),
    };
    Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("function-contract")),
        ("fnName", Value::string(fn_name.to_string())),
        ("formals", Value::array(formals_arr)),
        ("formalSorts", Value::array(formal_sorts_arr)),
        ("returnSort", sort_to_value(return_sort)),
        ("pre", formula_to_canonical(pre)),
        ("post", formula_to_canonical(post)),
        ("bodyCid", body_cid_val),
        ("effects", effects.to_value()),
        ("locus", locus.to_value()),
        (
            "autoMintedMementos",
            aliasing_mementos_to_value(auto_minted_mementos),
        ),
    ])
}

/// Canonical JCS array for a set of AliasingMementos. Entries are sorted
/// lexicographically by (formal_a, formal_b) for byte-determinism. Empty
/// list is always included as `[]` (never omitted) so the CID is
/// consistent across deployments.
fn aliasing_mementos_to_value(mementos: &[AliasingMemento]) -> Arc<Value> {
    let mut sorted: Vec<&AliasingMemento> = mementos.iter().collect();
    sorted.sort_by(|a, b| {
        a.formal_a
            .cmp(&b.formal_a)
            .then_with(|| a.formal_b.cmp(&b.formal_b))
    });
    let items: Vec<Arc<Value>> = sorted.iter().map(|m| m.to_jcs_value()).collect();
    Value::array(items)
}

/// Canonical encoding of a `Sort`. Public so external lifters that
/// build their own canonical bytes can match libsugar's encoding
/// byte-for-byte.
pub fn sort_to_value(s: &Sort) -> Arc<Value> {
    match s {
        Sort::Primitive { name } => Value::object([
            ("kind", Value::string("primitive")),
            ("name", Value::string(name.clone())),
        ]),
        Sort::Function { .. } | Sort::Dependent { .. } => Value::object([
            ("kind", Value::string("opaque")),
            (
                "reason",
                Value::string("function-or-dependent-sort-not-yet-modeled"),
            ),
        ]),
        Sort::Region { name } => Value::object([
            ("kind", Value::string("region")),
            ("name", Value::string(name.clone())),
        ]),
    }
}

// ============================================================
// Opacity discharge
// ============================================================

/// Trait for querying whether a discharge memento is present for a
/// given opacity effect. Implemented by `MementoPool` in
/// `sugar-verifier`; in-crate tests use a mock.
pub trait OpacityMementoLookup {
    fn has_loop_invariant(&self, loop_cid: &str) -> bool;
    fn has_try_branch(&self, try_cid: &str) -> bool;
    fn has_closure_binding(&self, body_fn_cid: &str) -> bool;
    fn has_drop_contract(&self, type_name: &str) -> bool;
    fn has_aliasing_memento(&self, formal_a: &str, formal_b: &str) -> bool;
    fn lookup_pin_invariant(
        &self,
        function_cid: &str,
        target: &str,
    ) -> Option<PinInvariantMementoView>;
}

/// A no-op pool that never has any discharge mementos.
pub struct EmptyOpacityPool;
impl OpacityMementoLookup for EmptyOpacityPool {
    fn has_loop_invariant(&self, _: &str) -> bool {
        false
    }
    fn has_try_branch(&self, _: &str) -> bool {
        false
    }
    fn has_closure_binding(&self, _: &str) -> bool {
        false
    }
    fn has_drop_contract(&self, _: &str) -> bool {
        false
    }
    fn has_aliasing_memento(&self, _: &str, _: &str) -> bool {
        false
    }
    fn lookup_pin_invariant(
        &self,
        _function_cid: &str,
        _target: &str,
    ) -> Option<PinInvariantMementoView> {
        None
    }
}

/// Lightweight pool lookup type for PinInvariantMemento.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinInvariantMementoView {
    pub function_cid: String,
    pub pinned_target: String,
    pub invariant: String,
}

/// Error returned when composition is refused because an opacity effect
/// is not discharged by a memento in the pool.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OpacityError {
    LoopNotDischarged { loop_cid: String },
    EarlyReturnNotDischarged { try_cid: String },
    ClosureCaptureNotDischarged { body_fn_cid: String },
    UnresolvedCallNotDischarged { name: String },
    AliasingNotDischarged { formal_a: String, formal_b: String },
    DropNotDischarged { name: String },
    PinInvariantNotDischarged { target: String },
}

impl std::fmt::Display for OpacityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::LoopNotDischarged { loop_cid } =>
                write!(f, "opacity: OpaqueLoop(loopCid={loop_cid}) has no LoopInvariantMemento in pool"),
            Self::EarlyReturnNotDischarged { try_cid } =>
                write!(f, "opacity: EarlyReturn(tryCid={try_cid}) has no TryBranchMemento in pool"),
            Self::ClosureCaptureNotDischarged { body_fn_cid } =>
                write!(f, "opacity: ClosureCapture(bodyFnCid={body_fn_cid}) has no ClosureBindingMemento in pool"),
            Self::UnresolvedCallNotDischarged { name } =>
                write!(f, "opacity: UnresolvedCall({name}) has no discharge memento kind"),
            Self::AliasingNotDischarged { formal_a, formal_b } =>
                write!(f, "aliasing: PossibleAliasing pair ({formal_a}, {formal_b}) has no AliasingMemento in auto_minted_mementos"),
            Self::DropNotDischarged { name } =>
                write!(f, "opacity: Drop({name}) has no lifted drop function in pool"),
            Self::PinInvariantNotDischarged { target } =>
                write!(f, "opacity: PinnedReference(target={target}) has no PinInvariantMemento in pool"),
        }
    }
}

impl EffectSet {
    /// Check whether all opacity effects in this set are discharged by
    /// the given pool. Returns `Ok(())` iff:
    ///   - there are no opacity effects at all, OR
    ///   - every opacity effect has a corresponding memento in `pool`.
    pub fn check_opacity_effects(
        &self,
        pool: &dyn OpacityMementoLookup,
        function_cid: Option<&str>,
    ) -> Result<(), OpacityError> {
        for effect in &self.effects {
            match effect {
                Effect::OpaqueLoop { loop_cid } => {
                    if !pool.has_loop_invariant(loop_cid) {
                        return Err(OpacityError::LoopNotDischarged {
                            loop_cid: loop_cid.clone(),
                        });
                    }
                }
                Effect::EarlyReturn { try_cid } => {
                    if !pool.has_try_branch(try_cid) {
                        return Err(OpacityError::EarlyReturnNotDischarged {
                            try_cid: try_cid.clone(),
                        });
                    }
                }
                Effect::ClosureCapture { body_fn_cid, .. } => {
                    if !pool.has_closure_binding(body_fn_cid) {
                        return Err(OpacityError::ClosureCaptureNotDischarged {
                            body_fn_cid: body_fn_cid.clone(),
                        });
                    }
                }
                Effect::UnresolvedCall { name } => {
                    return Err(OpacityError::UnresolvedCallNotDischarged { name: name.clone() });
                }
                Effect::Drop { name } => {
                    if !pool.has_drop_contract(name) {
                        return Err(OpacityError::DropNotDischarged { name: name.clone() });
                    }
                }
                Effect::PossibleAliasing { .. } => {}
                Effect::PinnedReference { target } => {
                    let fc = match function_cid {
                        Some(cid) if !cid.is_empty() => cid,
                        _ => {
                            return Err(OpacityError::PinInvariantNotDischarged {
                                target: target.clone(),
                            })
                        }
                    };
                    match pool.lookup_pin_invariant(fc, target) {
                        Some(view) if !view.invariant.is_empty() => { /* discharged */ }
                        _ => {
                            return Err(OpacityError::PinInvariantNotDischarged {
                                target: target.clone(),
                            })
                        }
                    }
                }
                Effect::Reads { .. }
                | Effect::Writes { .. }
                | Effect::Io
                | Effect::Unsafe
                | Effect::Panics
                | Effect::RawPointerProvenance { .. }
                | Effect::AtomicAccess { .. } => {}
            }
        }
        Ok(())
    }
}

// ============================================================
// Composition
// ============================================================

#[derive(Debug, Clone)]
pub struct ComposedFunctionContract {
    pub component_cids: Vec<String>,
    pub formal_idx: usize,
    pub pre: IrFormula,
    pub post: IrFormula,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

/// Compose two function contracts: the inner contract's result feeds
/// the outer contract's `formal_idx`-th formal.
///
/// Refuses (returns None) if either contract is impure.
pub fn compose_function_contracts(
    outer: &FunctionContractMemento,
    inner: &FunctionContractMemento,
    formal_idx: usize,
) -> Option<ComposedFunctionContract> {
    if !outer.is_pure() || !inner.is_pure() {
        return None;
    }
    if formal_idx >= outer.formals.len() {
        return None;
    }

    let inner_result_name = inner.result_var_name();
    let inner_post_renamed = substitute_in_formula(
        inner.post.clone(),
        "result",
        &IrTerm::Var {
            name: inner_result_name.clone(),
        },
    );

    let inner_value = find_result_equation(&inner_post_renamed, &inner_result_name)?;

    let outer_formal = &outer.formals[formal_idx];
    let outer_pre_substituted =
        substitute_in_formula(outer.pre.clone(), outer_formal, &inner_value);
    let outer_post_substituted =
        substitute_in_formula(outer.post.clone(), outer_formal, &inner_value);

    let pre = IrFormula::And {
        operands: vec![
            inner.pre.clone(),
            IrFormula::Implies {
                operands: vec![inner_post_renamed.clone(), outer_pre_substituted],
            },
        ],
    };
    let post = outer_post_substituted;

    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("composed-function-contract")),
        (
            "components",
            Value::array(vec![
                Value::string(outer.cid.clone()),
                Value::string(inner.cid.clone()),
            ]),
        ),
        ("formalIdx", Value::integer(formal_idx as i128)),
        ("pre", formula_to_canonical(&pre)),
        ("post", formula_to_canonical(&post)),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    Some(ComposedFunctionContract {
        component_cids: vec![outer.cid.clone(), inner.cid.clone()],
        formal_idx,
        pre,
        post,
        canonical_bytes,
        cid,
    })
}

/// Compose two function contracts with opacity discharge checking.
pub fn compose_function_contracts_checked(
    outer: &FunctionContractMemento,
    inner: &FunctionContractMemento,
    formal_idx: usize,
    pool: &dyn OpacityMementoLookup,
) -> Result<Option<ComposedFunctionContract>, OpacityError> {
    outer
        .effects
        .check_opacity_effects(pool, Some(&outer.cid))?;
    inner
        .effects
        .check_opacity_effects(pool, Some(&inner.cid))?;

    outer.check_aliasing_discharged()?;
    inner.check_aliasing_discharged()?;

    let outer_non_opacity_pure = outer.effects.effects.iter().all(|e| {
        matches!(
            e,
            Effect::OpaqueLoop { .. }
                | Effect::EarlyReturn { .. }
                | Effect::ClosureCapture { .. }
                | Effect::UnresolvedCall { .. }
                | Effect::PossibleAliasing { .. }
                | Effect::Drop { .. }
                | Effect::PinnedReference { .. }
        )
    });
    let inner_non_opacity_pure = inner.effects.effects.iter().all(|e| {
        matches!(
            e,
            Effect::OpaqueLoop { .. }
                | Effect::EarlyReturn { .. }
                | Effect::ClosureCapture { .. }
                | Effect::UnresolvedCall { .. }
                | Effect::PossibleAliasing { .. }
                | Effect::Drop { .. }
                | Effect::PinnedReference { .. }
        )
    });
    if !outer_non_opacity_pure || !inner_non_opacity_pure {
        return Ok(None);
    }

    if formal_idx >= outer.formals.len() {
        return Ok(None);
    }

    let inner_result_name = inner.result_var_name();
    let inner_post_renamed = substitute_in_formula(
        inner.post.clone(),
        "result",
        &IrTerm::Var {
            name: inner_result_name.clone(),
        },
    );
    let inner_value = match find_result_equation(&inner_post_renamed, &inner_result_name) {
        Some(t) => t,
        None => return Ok(None),
    };
    let outer_formal = &outer.formals[formal_idx];
    let outer_pre_substituted =
        substitute_in_formula(outer.pre.clone(), outer_formal, &inner_value);
    let outer_post_substituted =
        substitute_in_formula(outer.post.clone(), outer_formal, &inner_value);
    let pre = IrFormula::And {
        operands: vec![
            inner.pre.clone(),
            IrFormula::Implies {
                operands: vec![inner_post_renamed, outer_pre_substituted],
            },
        ],
    };
    let post = outer_post_substituted;
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("composed-function-contract")),
        (
            "components",
            Value::array(vec![
                Value::string(outer.cid.clone()),
                Value::string(inner.cid.clone()),
            ]),
        ),
        ("formalIdx", Value::integer(formal_idx as i128)),
        ("pre", formula_to_canonical(&pre)),
        ("post", formula_to_canonical(&post)),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);
    Ok(Some(ComposedFunctionContract {
        component_cids: vec![outer.cid.clone(), inner.cid.clone()],
        formal_idx,
        pre,
        post,
        canonical_bytes,
        cid,
    }))
}

/// Compose with the inner being an already-composed contract.
pub fn compose_with_composed(
    outer: &FunctionContractMemento,
    inner: &ComposedFunctionContract,
    formal_idx: usize,
) -> Option<ComposedFunctionContract> {
    if !outer.is_pure() {
        return None;
    }
    if formal_idx >= outer.formals.len() {
        return None;
    }

    let inner_value = find_result_equation(&inner.post, "result").or_else(|| {
        // Fallback: scan for any result__-prefixed equation.
        find_namespaced_result(&inner.post)
    })?;

    let outer_formal = &outer.formals[formal_idx];
    let outer_pre_substituted =
        substitute_in_formula(outer.pre.clone(), outer_formal, &inner_value);
    let outer_post_substituted =
        substitute_in_formula(outer.post.clone(), outer_formal, &inner_value);

    let pre = IrFormula::And {
        operands: vec![
            inner.pre.clone(),
            IrFormula::Implies {
                operands: vec![inner.post.clone(), outer_pre_substituted],
            },
        ],
    };
    let post = outer_post_substituted;

    let mut components = vec![outer.cid.clone()];
    components.extend(inner.component_cids.iter().cloned());
    let component_values: Vec<Arc<Value>> = components
        .iter()
        .map(|c| Value::string(c.clone()))
        .collect();
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("composed-function-contract")),
        ("components", Value::array(component_values)),
        ("formalIdx", Value::integer(formal_idx as i128)),
        ("pre", formula_to_canonical(&pre)),
        ("post", formula_to_canonical(&post)),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    Some(ComposedFunctionContract {
        component_cids: components,
        formal_idx,
        pre,
        post,
        canonical_bytes,
        cid,
    })
}

/// One step in an N-deep chain composition. The contract receives the
/// previous step's result at `formal_idx`. The first step's formal_idx
/// is unused (it's the chain's source).
#[derive(Debug, Clone, Copy)]
pub struct ChainStep<'a> {
    pub contract: &'a FunctionContractMemento,
    pub formal_idx: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CompositionError {
    ChainTooShort {
        len: usize,
    },
    ImpureInput {
        atom_index: usize,
        atom_cid: String,
    },
    FormalIndexOutOfRange {
        atom_index: usize,
        formal_idx: usize,
        formals_len: usize,
        atom_cid: String,
    },
    MissingResultEquation {
        atom_index: usize,
        atom_cid: String,
    },
}

impl CompositionError {
    fn failure_kind(&self) -> &'static str {
        match self {
            Self::ImpureInput { .. } => "impure-input",
            Self::ChainTooShort { .. } | Self::FormalIndexOutOfRange { .. } => "ordering-conflict",
            Self::MissingResultEquation { .. } => "unsatisfiable-precondition",
        }
    }

    fn failure_detail(&self) -> String {
        match self {
            Self::ChainTooShort { len } => {
                format!("chain has {len} atoms; at least 2 atoms are required")
            }
            Self::ImpureInput {
                atom_index,
                atom_cid,
            } => format!("impure atom {atom_cid} at chain index {atom_index}"),
            Self::FormalIndexOutOfRange {
                atom_index,
                formal_idx,
                formals_len,
                atom_cid,
            } => format!(
                "atom {atom_cid} at chain index {atom_index} uses formal_idx {formal_idx}, but has {formals_len} formals"
            ),
            Self::MissingResultEquation {
                atom_index,
                atom_cid,
            } => format!(
                "atom {atom_cid} at chain index {atom_index} has no deterministic result equation"
            ),
        }
    }
}

/// Compose a chain of pure function contracts left-to-right. Each
/// step's contract receives the previous step's result at its
/// `formal_idx`-th formal. Returns a canonical refusal memento if any
/// contract is impure or the chain cannot be composed.
///
/// Per CCP §2 + §9: this is the canonical primitive named in the spec.
/// The chain's overall CID is derivable from its component CIDs in
/// order; re-composing the same chain produces the same CID
/// byte-for-byte. Cross-language consumers (C lifter via FFI, future
/// JSON-RPC subprocess) call into this function.
pub fn compose_chain_contracts(
    steps: &[ChainStep<'_>],
) -> Result<ComposedFunctionContract, CompositionBoundaryMemento> {
    compose_chain_contracts_internal(steps)
        .map_err(|error| composition_error_to_refusal(steps, error))
}

fn compose_chain_contracts_internal(
    steps: &[ChainStep<'_>],
) -> Result<ComposedFunctionContract, CompositionError> {
    if steps.len() < 2 {
        return Err(CompositionError::ChainTooShort { len: steps.len() });
    }
    for (atom_index, step) in steps.iter().enumerate() {
        if !step.contract.is_pure() {
            return Err(CompositionError::ImpureInput {
                atom_index,
                atom_cid: step.contract.cid.clone(),
            });
        }
    }
    if steps[1].formal_idx >= steps[1].contract.formals.len() {
        return Err(CompositionError::FormalIndexOutOfRange {
            atom_index: 1,
            formal_idx: steps[1].formal_idx,
            formals_len: steps[1].contract.formals.len(),
            atom_cid: steps[1].contract.cid.clone(),
        });
    }
    if steps[0].contract.result_value().is_none() {
        return Err(CompositionError::MissingResultEquation {
            atom_index: 0,
            atom_cid: steps[0].contract.cid.clone(),
        });
    }
    let mut acc =
        compose_function_contracts(steps[1].contract, steps[0].contract, steps[1].formal_idx)
            .ok_or_else(|| CompositionError::MissingResultEquation {
                atom_index: 0,
                atom_cid: steps[0].contract.cid.clone(),
            })?;
    for (atom_index, step) in steps.iter().enumerate().skip(2) {
        if step.formal_idx >= step.contract.formals.len() {
            return Err(CompositionError::FormalIndexOutOfRange {
                atom_index,
                formal_idx: step.formal_idx,
                formals_len: step.contract.formals.len(),
                atom_cid: step.contract.cid.clone(),
            });
        }
        acc = compose_with_composed(step.contract, &acc, step.formal_idx).ok_or_else(|| {
            CompositionError::MissingResultEquation {
                atom_index: atom_index - 1,
                atom_cid: steps[atom_index - 1].contract.cid.clone(),
            }
        })?;
    }
    Ok(acc)
}

fn composition_error_to_refusal(
    steps: &[ChainStep<'_>],
    error: CompositionError,
) -> CompositionBoundaryMemento {
    let atoms_cids: Vec<String> = steps.iter().map(|s| s.contract.cid.clone()).collect();
    let effect_set_cids: Vec<String> = steps
        .iter()
        .map(|s| effect_set_cid(&s.contract.effects))
        .collect();
    let compose_input_cid =
        composition_refusal_compose_input_cid(&atoms_cids, &effect_set_cids, CCP_VERSION);
    let effect_occurrences = effect_occurrences_for_steps(steps);
    let blocking_effects = blocking_effects_for_steps(steps);

    let mut header = CompositionRefusalHeader {
        atoms_cids,
        blocking_effects: if blocking_effects.is_empty() {
            None
        } else {
            Some(blocking_effects)
        },
        ccp_version: CCP_VERSION.to_string(),
        cid: String::new(),
        compose_input_cid,
        effect_occurrences: if effect_occurrences.is_empty() {
            None
        } else {
            Some(effect_occurrences)
        },
        effect_set_cids,
        failure_detail: error.failure_detail(),
        failure_kind: error.failure_kind().to_string(),
        incompatible_pair: None,
        kind: "composition-refusal".to_string(),
        missing_memento_requirements: None,
        schema_version: "1".to_string(),
    };
    header.cid = composition_refusal_header_cid(&header);
    let metadata = CompositionRefusalMetadata::default();
    let signature = composition_refusal_signature(&header, &metadata);
    CompositionBoundaryMemento {
        envelope: CompositionRefusalEnvelope {
            declared_at: "1970-01-01T00:00:00Z".to_string(),
            signature,
            signer: "substrate:libsugar".to_string(),
        },
        header,
        metadata,
    }
}

fn effect_set_cid(effect_set: &EffectSet) -> String {
    cid_of_value(&effect_set.to_value())
}

fn effect_occurrences_for_steps(steps: &[ChainStep<'_>]) -> Vec<EffectOccurrence> {
    steps
        .iter()
        .flat_map(|step| {
            step.contract
                .effects
                .effects
                .iter()
                .enumerate()
                .map(move |(idx, effect)| {
                    let occurrence_kind = OccurrenceKind::from_str(effect_occurrence_kind(effect))
                        .expect("canonical effect kind");
                    let discharge_key = effect_discharge_key(effect);
                    EffectOccurrence {
                        args: effect_args_json(effect),
                        discharge_key,
                        locator: serde_json::json!({
                            "atom_cid": step.contract.cid,
                            "effect_index": idx,
                        }),
                        occurrence_kind,
                        // Per EffectOccurrence #793 spec §2: declared-effects-of-the-contract
                        // carry role "body". The composer doesn't see a narrower position
                        // unless the producing lifter records it.
                        role: OccurrenceRole::Body,
                        signature_cid: cid_of_value(&effect.to_value()),
                    }
                })
        })
        .collect()
}

fn blocking_effects_for_steps(steps: &[ChainStep<'_>]) -> Vec<BlockingEffect> {
    steps
        .iter()
        .flat_map(|step| {
            step.contract
                .effects
                .effects
                .iter()
                .map(move |effect| BlockingEffect {
                    atom_cid: step.contract.cid.clone(),
                    classification: effect_classification(effect).to_string(),
                    discharge_key: effect_discharge_key(effect),
                    occurrence_kind: effect_occurrence_kind(effect).to_string(),
                })
        })
        .collect()
}

/// Canonical occurrence-kind labels per `EffectOccurrence` spec §3 (#793).
/// MUST be PascalCase; CCP refusal mementos that compose with the
/// EffectOccurrence type need byte-identical kind names.
fn effect_occurrence_kind(effect: &Effect) -> &'static str {
    match effect {
        Effect::Reads { .. } => "Reads",
        Effect::Writes { .. } => "Writes",
        Effect::Io => "Io",
        Effect::Unsafe => "Unsafe",
        Effect::Panics => "Panics",
        Effect::UnresolvedCall { .. } => "UnresolvedCall",
        Effect::OpaqueLoop { .. } => "OpaqueLoop",
        Effect::EarlyReturn { .. } => "EarlyReturn",
        Effect::ClosureCapture { .. } => "ClosureCapture",
        Effect::PinnedReference { .. } => "PinnedReference",
        Effect::RawPointerProvenance { .. } => "RawPointerProvenance",
        Effect::AtomicAccess { .. } => "AtomicAccess",
        Effect::PossibleAliasing { .. } => "PossibleAliasing",
        Effect::Drop { .. } => "Drop",
    }
}

/// Per-occurrence classification per `2026-05-06-effect-discharge-classification.md`
/// and `EffectOccurrence` spec §4 (#793). The blocking-effect record carries this
/// so refusal consumers can see WHY a given effect blocked composition, not just
/// that some effect did.
///
/// - `block` (UnconditionallyBlocked): Reads/Writes/Io/Panics/Unsafe at v1
/// - `memento-required`: OpaqueLoop / UnresolvedCall / EarlyReturn / ClosureCapture
///   / PinnedReference / RawPointerProvenance / PossibleAliasing / non-trivial Drop
///   / AtomicAccess with `ordering: None`
/// - `informational-dischargeable`: AtomicAccess with concrete `ordering`
fn effect_classification(effect: &Effect) -> &'static str {
    match effect {
        Effect::Reads { .. }
        | Effect::Writes { .. }
        | Effect::Io
        | Effect::Unsafe
        | Effect::Panics => "block",
        Effect::OpaqueLoop { .. }
        | Effect::UnresolvedCall { .. }
        | Effect::EarlyReturn { .. }
        | Effect::ClosureCapture { .. }
        | Effect::PinnedReference { .. }
        | Effect::RawPointerProvenance { .. }
        | Effect::PossibleAliasing { .. }
        | Effect::Drop { .. } => "memento-required",
        Effect::AtomicAccess { ordering, .. } => {
            if ordering.is_some() {
                "informational-dischargeable"
            } else {
                "memento-required"
            }
        }
    }
}

/// Canonical discharge-key shape per `EffectOccurrence` spec §3 (#793).
/// Format: `<occurrence-kind-lowercase-segment>:<payload-segments>`. The
/// segments here match the §3 examples (e.g. `read:x`, `opaque-loop:<cid>`,
/// `raw-pointer-provenance:<target>:<mut>`) so a refusal memento composes
/// byte-identically with an EffectOccurrence minted by a lifter.
fn effect_discharge_key(effect: &Effect) -> String {
    match effect {
        Effect::Reads { target } => format!("read:{target}"),
        Effect::Writes { target } => format!("write:{target}"),
        Effect::Io => "io".to_string(),
        Effect::Unsafe => "unsafe".to_string(),
        Effect::Panics => "panic".to_string(),
        Effect::UnresolvedCall { name } => format!("unresolved-call:{name}"),
        Effect::OpaqueLoop { loop_cid } => format!("opaque-loop:{loop_cid}"),
        Effect::EarlyReturn { try_cid } => format!("early-return:{try_cid}"),
        Effect::ClosureCapture {
            body_fn_cid,
            n_captures,
        } => format!("closure-capture:{body_fn_cid}:{n_captures}"),
        Effect::PinnedReference { target } => format!("pinned-reference:{target}"),
        Effect::RawPointerProvenance { target, mutable } => {
            format!(
                "raw-pointer-provenance:{target}:{}",
                if *mutable { "mut" } else { "const" }
            )
        }
        Effect::AtomicAccess {
            target,
            kind,
            ordering,
        } => format!(
            "atomic:{target}:{}:{}",
            kind.as_str(),
            ordering.as_deref().unwrap_or("null")
        ),
        Effect::PossibleAliasing { formals } => format!("possible-aliasing:{}", formals.join(",")),
        Effect::Drop { name } => format!("drop:{name}"),
    }
}

fn effect_args_json(effect: &Effect) -> serde_json::Value {
    match effect {
        Effect::Reads { target }
        | Effect::Writes { target }
        | Effect::PinnedReference { target } => serde_json::json!({ "target": target }),
        Effect::Io | Effect::Unsafe | Effect::Panics => serde_json::json!({}),
        Effect::UnresolvedCall { name } | Effect::Drop { name } => {
            serde_json::json!({ "name": name })
        }
        Effect::OpaqueLoop { loop_cid } => serde_json::json!({ "loop_cid": loop_cid }),
        Effect::EarlyReturn { try_cid } => serde_json::json!({ "try_cid": try_cid }),
        Effect::ClosureCapture {
            body_fn_cid,
            n_captures,
        } => serde_json::json!({
            "body_fn_cid": body_fn_cid,
            "n_captures": n_captures,
        }),
        Effect::RawPointerProvenance { target, mutable } => {
            serde_json::json!({ "target": target, "mutable": mutable })
        }
        Effect::AtomicAccess {
            target,
            kind,
            ordering,
        } => serde_json::json!({
            "target": target,
            "kind": kind.as_str(),
            "ordering": ordering,
        }),
        Effect::PossibleAliasing { formals } => serde_json::json!({ "formals": formals }),
    }
}

fn find_namespaced_result(formula: &IrFormula) -> Option<IrTerm> {
    match formula {
        IrFormula::Atomic { name, args } if name == "=" && args.len() == 2 => {
            for (var_arg, value_arg) in [(&args[0], &args[1]), (&args[1], &args[0])] {
                if let IrTerm::Var { name: n } = var_arg {
                    if n.starts_with("result__") {
                        return Some(value_arg.clone());
                    }
                }
            }
            None
        }
        IrFormula::And { operands } => operands.iter().find_map(find_namespaced_result),
        _ => None,
    }
}

/// Find a top-level `<var> = <expr>` equation in a formula and return
/// the expr term. Used to extract a function's result-value from its
/// post for composition.
fn find_result_equation(formula: &IrFormula, var_name: &str) -> Option<IrTerm> {
    match formula {
        IrFormula::Atomic { name, args } if name == "=" && args.len() == 2 => {
            if let IrTerm::Var { name: n } = &args[0] {
                if n == var_name {
                    return Some(args[1].clone());
                }
            }
            if let IrTerm::Var { name: n } = &args[1] {
                if n == var_name {
                    return Some(args[0].clone());
                }
            }
            None
        }
        IrFormula::And { operands } => operands
            .iter()
            .find_map(|f| find_result_equation(f, var_name)),
        _ => None,
    }
}

// ============================================================
// JCS / CID helpers (canonical encoding glue)
//
// Duplicated from walk's canonical.rs so this module is self-contained.
// Both impls operate over identical types from sugar-ir-types and
// produce byte-equivalent output by construction. CCP §5 requires the
// compose primitive be the single canonical home; the wp / canonical
// modules in walk persist for the rest of walk's pipeline.
// ============================================================

use serde_json::Value as JsonValue;

fn serde_to_canonical(j: JsonValue) -> Arc<Value> {
    match j {
        JsonValue::Null => Value::null(),
        JsonValue::Bool(b) => Value::boolean(b),
        JsonValue::Number(n) => match n
            .as_i64()
            .map(i128::from)
            .or_else(|| n.as_u64().map(i128::from))
        {
            Some(i) => Value::integer(i),
            None => Value::object(vec![(
                "__sugar_non_i64_number__".to_string(),
                Value::string(n.to_string()),
            )]),
        },
        JsonValue::String(s) => Value::string(s),
        JsonValue::Array(items) => {
            let mapped: Vec<Arc<Value>> = items.into_iter().map(serde_to_canonical).collect();
            Value::array(mapped)
        }
        JsonValue::Object(map) => {
            let entries: Vec<(String, Arc<Value>)> = map
                .into_iter()
                .map(|(k, v)| (k, serde_to_canonical(v)))
                .collect();
            Value::object(entries)
        }
    }
}

/// Canonicalize an `IrFormula` into a JCS-canonicalizer Value tree.
pub fn formula_to_canonical(f: &IrFormula) -> Arc<Value> {
    let serde =
        serde_json::to_value(f).expect("IrFormula serializes (sugar-ir-types is generated)");
    serde_to_canonical(serde)
}

/// Compute the BLAKE3-512 CID of a canonicalizer Value, JCS-encoded.
/// Returns the spec's `"blake3-512:<hex>"` self-identifying string.
pub fn cid_of_value(v: &Value) -> String {
    blake3_512_of(encode_jcs(v).as_bytes())
}

/// Encode a canonicalizer Value to JCS bytes.
pub fn jcs_bytes_of_value(v: &Value) -> Vec<u8> {
    encode_jcs(v).into_bytes()
}

// ============================================================
// Substitution (capture-avoiding) over IrFormula / IrTerm.
//
// Moved to `libsugar::wp` (spec 2026-05-13-wp-as-formula.md §2.2):
// that module is now the single canonical home for the substitution
// algebra, consumed here, by `sugar-walk`'s `wp.rs`, by the wp
// evaluator, and by the transport / desugaring discharge. The previous
// in-module copy (duplicated from walk's `wp.rs`) is gone; `compose`
// re-exports the canonical functions so callers that imported
// `libsugar::compose::substitute_in_formula` keep working.
// ============================================================

pub use crate::wp::{free_vars_formula, free_vars_term, substitute_in_formula, substitute_in_term};

// ============================================================
// DomainClaim projection for FunctionContractMemento (PR-B of #717)
//
// Bare `FunctionContractMemento`s have no inline discharge. They MUST
// be wrapped in a `ConceptSiteMemento` (the binding) or a
// `CompoundContractMemento` (PR #716) before reaching the verifier
// surface. This impl is intentionally always-Err so the type system
// encodes the invariant: the call-site is forced to handle the error
// and either reject the bare contract or promote it through a binding
// (spec §2.3, §6.1).
// ============================================================

impl TryFrom<&FunctionContractMemento> for sugar_ir_types::DomainClaim {
    type Error = sugar_ir_types::DomainClaimConversionError;

    fn try_from(_m: &FunctionContractMemento) -> Result<Self, Self::Error> {
        Err(sugar_ir_types::DomainClaimConversionError::UnboundContract)
    }
}

// ============================================================
// FCM auto-promotion to CompoundContractMemento (PR-B of #716)
//
// Source of truth: protocol/specs/2026-05-13-compound-contract-memento.md §4.3
//
// Backward-compat path: when a consumer encounters a bare
// FunctionContractMemento it MUST auto-promote it to a single-evidence
// CompoundContractMemento before passing it downstream. Two calls with
// byte-identical FCM inputs MUST produce identical output bytes and
// therefore identical CIDs (§4.4 mint-idempotency invariant).
//
// `source_locator` derivation from FCM `Locus`:
//   FCM carries a single point {file, line, col} -- not a CID-bearing
//   source artifact reference. For determinism, we use:
//     source_cid = the all-zeros sentinel CID (same token as lifter_cid;
//                  both signal "auto-promote" provenance)
//     span.start = span.end = {line: locus.line, col: locus.col}
//   A zero locus (unknown) maps to {line:0, col:0}, which is distinct
//   from any real source point and is stable across validators.
// ============================================================

/// The all-zeros sentinel CID used for the `lifter_cid` (and for
/// `source_locator.source_cid`) of auto-promoted evidence.
///
/// Per compound spec §4.4: `blake3-512:` followed by 128 hex `0`s.
/// Provably not a real BLAKE3-512 hash (P ≈ 2^-512). Pass-1 CID
/// validation accepts it without a special-case exception ("128-hex"
/// is satisfied by 128 hex `0` digits).
pub const AUTO_PROMOTE_LIFTER_CID: &str =
    "blake3-512:0000000000000000000000000000000000000000000000000000000000000000\
     0000000000000000000000000000000000000000000000000000000000000000";

/// Compute the CID for an `EvidenceMemento` per compound spec §3.1.
///
/// The CID is BLAKE3-512 of the JCS-canonical bytes of the header with
/// the `cid` field elided. We build the canonical Value directly from
/// the struct fields, omitting `cid`, rather than serializing the struct
/// (which would include `cid`) and then patching.
fn evidence_cid(
    confidence_basis_points: u16,
    extension_fields: &BTreeMap<String, serde_json::Value>,
    lifter_cid: &str,
    predicate: &IrFormula,
    source_kind: &SourceKind,
    source_locator: &SourceLocator,
) -> String {
    // Build extension_fields as canonical Value (BTreeMap order = JCS order).
    let ext_entries: Vec<(String, Arc<Value>)> = extension_fields
        .iter()
        .map(|(k, v)| {
            let canonical_v = serde_to_canonical(v.clone());
            (k.clone(), canonical_v)
        })
        .collect();

    // source_kind wire form is a bare JSON string.
    let source_kind_str: String = source_kind.clone().into();

    // source_locator: {source_cid, span:{end:{col,line},start:{col,line}}}
    // Locked JCS key order: source_cid, span. Span: end, start. Point: col, line.
    let sloc_value = Value::object(vec![
        (
            "source_cid".to_string(),
            Value::string(source_locator.source_cid.clone()),
        ),
        (
            "span".to_string(),
            Value::object(vec![
                (
                    "end".to_string(),
                    Value::object(vec![
                        (
                            "col".to_string(),
                            Value::integer(i128::from(source_locator.span.end.col)),
                        ),
                        (
                            "line".to_string(),
                            Value::integer(i128::from(source_locator.span.end.line)),
                        ),
                    ]),
                ),
                (
                    "start".to_string(),
                    Value::object(vec![
                        (
                            "col".to_string(),
                            Value::integer(i128::from(source_locator.span.start.col)),
                        ),
                        (
                            "line".to_string(),
                            Value::integer(i128::from(source_locator.span.start.line)),
                        ),
                    ]),
                ),
            ]),
        ),
    ]);

    // Locked JCS key order (alphabetical, cid elided):
    //   confidence_basis_points, extension_fields, kind, lifter_cid,
    //   predicate, schemaVersion, source_kind, source_locator.
    let header = Value::object(vec![
        (
            "confidence_basis_points".to_string(),
            Value::integer(i128::from(confidence_basis_points)),
        ),
        ("extension_fields".to_string(), Value::object(ext_entries)),
        ("kind".to_string(), Value::string("evidence".to_string())),
        (
            "lifter_cid".to_string(),
            Value::string(lifter_cid.to_string()),
        ),
        ("predicate".to_string(), formula_to_canonical(predicate)),
        ("schemaVersion".to_string(), Value::string("1".to_string())),
        ("source_kind".to_string(), Value::string(source_kind_str)),
        ("source_locator".to_string(), sloc_value),
    ]);

    cid_of_value(&header)
}

/// Compute the CID for a `CompoundContractMemento` per compound spec §3.1.
///
/// The CID is BLAKE3-512 of the JCS-canonical bytes of the header with
/// the `cid` field elided.
fn compound_cid(
    aggregation_strategy: &AggregationStrategy,
    composed_post: &IrFormula,
    composed_pre: &IrFormula,
    evidences: &[EvidenceRef],
    function_term_cid: &str,
) -> String {
    let strategy_str: String = aggregation_strategy.clone().into();

    // evidences array: sorted by evidence_cid ascending at JCS time.
    // The JCS encoder sorts; we build the array as-is and rely on the
    // canonicalizer's Value::object sort. For arrays, order is insertion
    // order -- we sort here for determinism before passing to JCS.
    let mut sorted_evidences: Vec<&EvidenceRef> = evidences.iter().collect();
    sorted_evidences.sort_by(|a, b| a.evidence_cid.cmp(&b.evidence_cid));

    let evidences_arr: Vec<Arc<Value>> = sorted_evidences
        .iter()
        .map(|er| {
            // Locked JCS key order: evidence_cid, weight_basis_points.
            Value::object(vec![
                (
                    "evidence_cid".to_string(),
                    Value::string(er.evidence_cid.clone()),
                ),
                (
                    "weight_basis_points".to_string(),
                    Value::integer(i128::from(er.weight_basis_points)),
                ),
            ])
        })
        .collect();

    // Locked JCS key order (alphabetical, cid elided):
    //   aggregation_strategy, composed_post, composed_pre, evidences,
    //   function_term_cid, kind, schemaVersion.
    let header = Value::object(vec![
        (
            "aggregation_strategy".to_string(),
            Value::string(strategy_str),
        ),
        (
            "composed_post".to_string(),
            formula_to_canonical(composed_post),
        ),
        (
            "composed_pre".to_string(),
            formula_to_canonical(composed_pre),
        ),
        ("evidences".to_string(), Value::array(evidences_arr)),
        (
            "function_term_cid".to_string(),
            Value::string(function_term_cid.to_string()),
        ),
        (
            "kind".to_string(),
            Value::string("compound-contract".to_string()),
        ),
        ("schemaVersion".to_string(), Value::string("1".to_string())),
    ]);

    cid_of_value(&header)
}

/// Auto-promote a bare `FunctionContractMemento` to a single-evidence
/// `CompoundContractMemento` per compound spec §4.3.
///
/// Returns `(EvidenceMemento, CompoundContractMemento)`. Callers MUST
/// store the `EvidenceMemento` in their pool so downstream verifiers can
/// resolve the `EvidenceRef` in the compound's `evidences` list.
///
/// This is the canonical backward-compat path. Every call with the same
/// FCM bytes produces the same output bytes and the same CIDs
/// (mint-idempotency invariant, spec §4.4).
///
/// The promoted Compound has:
/// - One `EvidenceMemento` with:
///   - `source_kind = "annotation"`
///   - `predicate = And { operands: [pre, post] }` (the FCM's pre /\ post)
///   - `confidence_basis_points = 10000`
///   - `lifter_cid` = `AUTO_PROMOTE_LIFTER_CID` (all-zeros sentinel)
///   - `extension_fields = { "auto_promoted_from": <fcm.cid> }`
///   - `source_locator` derived from the FCM's `locus` (see module comment)
/// - `aggregation_strategy = "conjunction"`
/// - `function_term_cid` = `fcm.cid`
/// - `composed_pre = fcm.pre`, `composed_post = fcm.post`
///   (single-evidence conjunction collapses to the evidence's separated
///   pre/post, which are the FCM's own pre and post)
pub fn promote_fcm_to_compound(
    fcm: &FunctionContractMemento,
) -> (EvidenceMemento, CompoundContractMemento) {
    // Build the predicate: pre /\ post.
    // Per spec §4.3, the evidence predicate is `pre /\ post` packaged per §6.
    // §6.1 pre/post separation: the evidence holds both; when the compound
    // aggregates under conjunction, composed_pre = conjunct of separated pres
    // = fcm.pre (one evidence), composed_post = fcm.post.
    //
    // We represent `pre /\ post` as `And { operands: [pre, post] }`.
    // Edge case: if both pre and post are trivially `And { operands: [] }`
    // (i.e., `true`), the predicate collapses to `And { operands: [] }` as
    // well, which is still the spec-correct encoding. We never emit an empty
    // operand list for a degenerate conjunction -- the spec doesn't special-
    // case this and neither do we.
    let predicate = IrFormula::And {
        operands: vec![fcm.pre.clone(), fcm.post.clone()],
    };

    // source_locator: deterministically derived from FCM locus.
    // FCM locus has no source_cid; use the all-zeros sentinel.
    // Span start == end == {line: locus.line, col: locus.col} (1-based line,
    // 0-indexed col per compound spec §1.1.1).
    let point = SourceLocatorPoint {
        line: fcm.locus.line as u32,
        col: fcm.locus.col as u32,
    };
    let source_locator = SourceLocator {
        source_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
        span: SourceLocatorSpan {
            start: point.clone(),
            end: point,
        },
    };

    let mut extension_fields = BTreeMap::new();
    extension_fields.insert(
        "auto_promoted_from".to_string(),
        serde_json::Value::String(fcm.cid.clone()),
    );

    let evidence_cid_str = evidence_cid(
        10000,
        &extension_fields,
        AUTO_PROMOTE_LIFTER_CID,
        &predicate,
        &SourceKind::Annotation,
        &source_locator,
    );

    let evidence = EvidenceMemento {
        cid: evidence_cid_str.clone(),
        confidence_basis_points: 10000,
        extension_fields,
        kind: "evidence".to_string(),
        lifter_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
        predicate,
        schema_version: "1".to_string(),
        source_kind: SourceKind::Annotation,
        source_locator,
    };

    let evidence_ref = EvidenceRef {
        evidence_cid: evidence_cid_str,
        weight_basis_points: 10000,
    };

    let evidences = vec![evidence_ref];
    let composed_pre = fcm.pre.clone();
    let composed_post = fcm.post.clone();
    let function_term_cid = fcm.cid.clone();

    let cid_str = compound_cid(
        &AggregationStrategy::Conjunction,
        &composed_post,
        &composed_pre,
        &evidences,
        &function_term_cid,
    );

    let compound = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: cid_str,
        composed_post,
        composed_pre,
        evidences,
        function_term_cid,
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };

    (evidence, compound)
}

// Provide Into<CompoundContractMemento> for &FunctionContractMemento so
// callers can use the ergonomic `.into()` syntax. The EvidenceMemento
// is discarded; use promote_fcm_to_compound directly when pool storage
// is required.
impl From<&FunctionContractMemento> for CompoundContractMemento {
    fn from(fcm: &FunctionContractMemento) -> CompoundContractMemento {
        promote_fcm_to_compound(fcm).1
    }
}

#[cfg(test)]
mod fcm_auto_promote_tests {
    use super::*;
    use sugar_ir_types::{IrFormula, IrTerm, Sort};

    /// Build a minimal FCM with non-trivial pre and post.
    fn fcm_with_pre_post(
        fn_name: &str,
        pre: IrFormula,
        post: IrFormula,
        cid: &str,
        line: usize,
        col: usize,
    ) -> FunctionContractMemento {
        FunctionContractMemento {
            fn_name: fn_name.to_string(),
            formals: vec!["x".to_string()],
            formal_sorts: vec![Sort::Primitive {
                name: "Int".to_string(),
            }],
            formal_regions: vec![None],
            return_sort: Sort::Primitive {
                name: "Int".to_string(),
            },
            return_region: None,
            pre,
            post,
            body_cid: None,
            effects: EffectSet::default(),
            locus: Locus {
                file: Some("src/lib.rs".to_string()),
                line,
                col,
            },
            canonical_bytes: vec![],
            cid: cid.to_string(),
            auto_minted_mementos: vec![],
            panic_loci: vec![],
            concept_hint: None,
        }
    }

    fn trivial_formula() -> IrFormula {
        IrFormula::And { operands: vec![] }
    }

    fn nontrivial_pre() -> IrFormula {
        // x >= 0
        IrFormula::Atomic {
            name: ">=".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "x".to_string(),
                },
                IrTerm::Const {
                    value: serde_json::Value::Number(serde_json::Number::from(0)),
                    sort: Sort::Primitive {
                        name: "Int".to_string(),
                    },
                },
            ],
        }
    }

    fn nontrivial_post() -> IrFormula {
        // result >= x
        IrFormula::Atomic {
            name: ">=".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "result".to_string(),
                },
                IrTerm::Var {
                    name: "x".to_string(),
                },
            ],
        }
    }

    // ----------------------------------------------------------------
    // FCM with non-trivial pre + post → Compound with one evidence
    // ----------------------------------------------------------------
    #[test]
    fn nontrivial_fcm_promotes_to_single_evidence_compound() {
        let fcm = fcm_with_pre_post(
            "add_one",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:aaaa",
            10,
            4,
        );
        let (_ev, compound) = promote_fcm_to_compound(&fcm);
        assert_eq!(compound.evidences.len(), 1);
        assert_eq!(
            compound.aggregation_strategy,
            AggregationStrategy::Conjunction
        );
        assert_eq!(compound.kind, "compound-contract");
        assert_eq!(compound.schema_version, "1");
        assert_eq!(compound.function_term_cid, "blake3-512:aaaa");
    }

    #[test]
    fn nontrivial_fcm_compound_composed_pre_post_match_fcm() {
        let fcm = fcm_with_pre_post(
            "add_one",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:aaaa",
            10,
            4,
        );
        let (_ev, compound) = promote_fcm_to_compound(&fcm);
        assert_eq!(compound.composed_pre, nontrivial_pre());
        assert_eq!(compound.composed_post, nontrivial_post());
    }

    // ----------------------------------------------------------------
    // FCM with empty pre/post → Compound with one evidence whose
    // predicate is And { operands: [true, true] }
    //
    // NOTE: spec §4.3 is unconditional ("Mint one EvidenceMemento");
    // even a trivially-true FCM produces one evidence, not zero.
    // The compound verdict is "exact" by §5.2 vacuous-all-exact rule
    // only when evidences is EMPTY; with one evidence, the verdict
    // follows that evidence's individual verdict.
    // ----------------------------------------------------------------
    #[test]
    fn trivial_fcm_promotes_to_single_evidence_not_zero() {
        let fcm = fcm_with_pre_post(
            "noop",
            trivial_formula(),
            trivial_formula(),
            "blake3-512:bbbb",
            1,
            0,
        );
        let (_ev, compound) = promote_fcm_to_compound(&fcm);
        // §4.3 is unconditional: always one evidence, never empty.
        assert_eq!(compound.evidences.len(), 1);
    }

    #[test]
    fn trivial_fcm_compound_composed_pre_post_are_trivial() {
        let fcm = fcm_with_pre_post(
            "noop",
            trivial_formula(),
            trivial_formula(),
            "blake3-512:bbbb",
            1,
            0,
        );
        let (_ev, compound) = promote_fcm_to_compound(&fcm);
        assert_eq!(compound.composed_pre, trivial_formula());
        assert_eq!(compound.composed_post, trivial_formula());
    }

    // ----------------------------------------------------------------
    // Determinism: two FCMs with identical bytes → identical Compound CIDs
    // ----------------------------------------------------------------
    #[test]
    fn identical_fcms_produce_identical_compound_cids() {
        let fcm1 = fcm_with_pre_post(
            "check_bound",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:cccc",
            42,
            8,
        );
        let fcm2 = fcm1.clone();
        let (_ev1, c1) = promote_fcm_to_compound(&fcm1);
        let (_ev2, c2) = promote_fcm_to_compound(&fcm2);
        assert_eq!(c1.cid, c2.cid);
        assert_eq!(c1.evidences[0].evidence_cid, c2.evidences[0].evidence_cid);
    }

    // ----------------------------------------------------------------
    // lifter_cid sentinel: verify via EvidenceMemento (returned in tuple)
    // ----------------------------------------------------------------
    #[test]
    fn auto_promotion_uses_all_zeros_sentinel_lifter_cid() {
        let fcm = fcm_with_pre_post(
            "sentinel_test",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:dddd",
            5,
            2,
        );
        let (ev, compound) = promote_fcm_to_compound(&fcm);

        // The EvidenceMemento's lifter_cid must be the all-zeros sentinel.
        assert_eq!(ev.lifter_cid, AUTO_PROMOTE_LIFTER_CID);

        // The compound's evidence ref CID is a valid blake3-512 CID.
        assert!(
            compound.evidences[0]
                .evidence_cid
                .starts_with("blake3-512:"),
            "evidence CID should be a valid blake3-512 CID"
        );

        // Verify the sentinel constant itself is the spec-mandated form.
        assert_eq!(
            AUTO_PROMOTE_LIFTER_CID,
            "blake3-512:00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        );
        assert_eq!(
            AUTO_PROMOTE_LIFTER_CID.len(),
            "blake3-512:".len() + 128,
            "sentinel must be blake3-512: prefix + exactly 128 hex chars"
        );
        // All chars after prefix must be '0'.
        let hex_part = &AUTO_PROMOTE_LIFTER_CID["blake3-512:".len()..];
        assert!(hex_part.chars().all(|c| c == '0'));
    }

    // ----------------------------------------------------------------
    // source_kind is "annotation" (verified via the returned EvidenceMemento)
    // ----------------------------------------------------------------
    #[test]
    fn auto_promotion_source_kind_is_annotation() {
        let fcm = fcm_with_pre_post(
            "annotation_test",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:1234",
            2,
            0,
        );
        let (ev, _compound) = promote_fcm_to_compound(&fcm);
        assert_eq!(ev.source_kind, SourceKind::Annotation);
        // Also verify the wire form.
        let wire: String = ev.source_kind.into();
        assert_eq!(wire, "annotation");
    }

    // ----------------------------------------------------------------
    // extension_fields contains auto_promoted_from = fcm.cid
    // ----------------------------------------------------------------
    #[test]
    fn extension_fields_contain_auto_promoted_from() {
        let fcm = fcm_with_pre_post(
            "ext_fields_test",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:abcd",
            1,
            0,
        );
        let (ev, _compound) = promote_fcm_to_compound(&fcm);
        let from = ev
            .extension_fields
            .get("auto_promoted_from")
            .expect("auto_promoted_from must be present");
        assert_eq!(
            from,
            &serde_json::Value::String("blake3-512:abcd".to_string())
        );
    }

    // ----------------------------------------------------------------
    // Round-trip: serialize → deserialize → re-serialize bytes are identical
    // ----------------------------------------------------------------
    #[test]
    fn compound_round_trips_via_json() {
        let fcm = fcm_with_pre_post(
            "round_trip",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:eeee",
            3,
            1,
        );
        let (_ev, compound) = promote_fcm_to_compound(&fcm);

        let json1 = serde_json::to_string(&compound).expect("serialize");
        let deser: CompoundContractMemento = serde_json::from_str(&json1).expect("deserialize");
        let json2 = serde_json::to_string(&deser).expect("re-serialize");

        assert_eq!(json1, json2, "round-trip must produce identical bytes");
    }

    // ----------------------------------------------------------------
    // Into ergonomics: From<&FCM> for CompoundContractMemento
    // ----------------------------------------------------------------
    #[test]
    fn into_compound_matches_promote_fn() {
        let fcm = fcm_with_pre_post(
            "into_test",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:ffff",
            7,
            0,
        );
        let (_ev, via_fn) = promote_fcm_to_compound(&fcm);
        let via_into: CompoundContractMemento = (&fcm).into();
        assert_eq!(via_fn.cid, via_into.cid);
    }

    // ----------------------------------------------------------------
    // CID symmetry: evidence_cid() and compound_cid() must produce
    // the SAME CID as serde_json::to_value(&struct) → strip cid →
    // serde_to_canonical → cid_of_value. This is the correctness
    // invariant that prevents every downstream consumer from rejecting
    // the output as tampered or malformed.
    // ----------------------------------------------------------------

    #[test]
    fn evidence_cid_is_symmetric_with_serde_roundtrip() {
        let fcm = fcm_with_pre_post(
            "symmetry_test",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:sym1",
            11,
            3,
        );
        let (ev, _compound) = promote_fcm_to_compound(&fcm);

        // Recompute CID via serde path: serialize → remove cid → canonical → CID.
        let mut as_value = serde_json::to_value(&ev).expect("EvidenceMemento serializes");
        as_value
            .as_object_mut()
            .expect("EvidenceMemento serializes as object")
            .remove("cid");
        let recomputed = cid_of_value(&serde_to_canonical(as_value));

        assert_eq!(
            recomputed, ev.cid,
            "evidence CID computed by evidence_cid() must match CID derived \
             from serde_json::to_value path (symmetry invariant)"
        );
    }

    #[test]
    fn compound_cid_is_symmetric_with_serde_roundtrip() {
        let fcm = fcm_with_pre_post(
            "compound_symmetry",
            nontrivial_pre(),
            nontrivial_post(),
            "blake3-512:sym2",
            15,
            7,
        );
        let (_ev, compound) = promote_fcm_to_compound(&fcm);

        // Recompute CID via serde path: serialize → remove cid → canonical → CID.
        let mut as_value =
            serde_json::to_value(&compound).expect("CompoundContractMemento serializes");
        as_value
            .as_object_mut()
            .expect("CompoundContractMemento serializes as object")
            .remove("cid");
        let recomputed = cid_of_value(&serde_to_canonical(as_value));

        assert_eq!(
            recomputed, compound.cid,
            "compound CID computed by compound_cid() must match CID derived \
             from serde_json::to_value path (symmetry invariant)"
        );
    }
}

#[cfg(test)]
mod domain_claim_fcm_tests {
    use super::*;
    use sugar_ir_types::{DomainClaimConversionError, IrFormula};

    /// Build a minimal but valid `FunctionContractMemento` for testing.
    /// `pre` and `post` use `And { operands: [] }` which is the canonical
    /// encoding of the trivial `true` formula.
    fn minimal_fcm() -> FunctionContractMemento {
        FunctionContractMemento {
            fn_name: "test_fn".to_string(),
            formals: vec![],
            formal_sorts: vec![],
            formal_regions: vec![],
            return_sort: sugar_ir_types::Sort::Primitive {
                name: "bool".to_string(),
            },
            return_region: None,
            pre: IrFormula::And { operands: vec![] },
            post: IrFormula::And { operands: vec![] },
            body_cid: None,
            effects: EffectSet::default(),
            locus: Locus {
                file: Some("test.rs".to_string()),
                line: 1,
                col: 0,
            },
            canonical_bytes: vec![],
            cid: "blake3-512:000000".to_string(),
            auto_minted_mementos: vec![],
            panic_loci: vec![],
            concept_hint: None,
        }
    }

    #[test]
    fn bare_fcm_returns_unbound_contract_error() {
        let fcm = minimal_fcm();
        let result = sugar_ir_types::DomainClaim::try_from(&fcm);
        assert_eq!(result, Err(DomainClaimConversionError::UnboundContract));
    }

    #[test]
    fn bare_fcm_error_is_deterministic() {
        let fcm = minimal_fcm();
        let r1 = sugar_ir_types::DomainClaim::try_from(&fcm);
        let r2 = sugar_ir_types::DomainClaim::try_from(&fcm);
        assert_eq!(r1, r2);
    }

    #[test]
    fn unbound_contract_display_is_informative() {
        let msg = DomainClaimConversionError::UnboundContract.to_string();
        assert!(
            msg.contains("unbound") || msg.contains("bare") || msg.contains("FunctionContract"),
            "display message should be informative, got: {msg:?}"
        );
        assert!(
            msg.contains("ConceptSiteMemento") || msg.contains("CompoundContract"),
            "display message should mention the binding type, got: {msg:?}"
        );
    }

    #[test]
    fn unbound_contract_error_variant_matches() {
        let fcm = minimal_fcm();
        let err = sugar_ir_types::DomainClaim::try_from(&fcm).unwrap_err();
        // Pattern-match to confirm the correct variant -- won't compile if
        // the variant is renamed or removed.
        assert!(matches!(err, DomainClaimConversionError::UnboundContract));
    }
}
