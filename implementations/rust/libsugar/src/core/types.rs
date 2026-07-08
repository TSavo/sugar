// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::{BTreeMap, BTreeSet};
use std::convert::TryFrom;
use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{de, Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value as JsonValue;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_types::{IrFormula, IrTerm, LetBinding, Sort};
use thiserror::Error;

use crate::compose::{
    build_memento_value, jcs_bytes_of_value, AliasingMemento, AliasingStatus, AtomicKind, Effect,
    EffectSet, FunctionContractMemento, Locus,
};

use super::traits::Canonical;

/// A flat BLAKE3-512 content identifier: `blake3-512:<128 lowercase hex>`.
///
/// `Cid` is the algebra's address type. It has no internal structure beyond
/// the hash algorithm tag and hex digest; any semantic meaning comes from the
/// catalog entry found by `resolve`.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Cid(String);

impl Cid {
    /// Parse and validate a BLAKE3-512 CID string.
    pub fn parse(value: impl Into<String>) -> Result<Self, CidError> {
        let value = value.into();
        if !sugar_canonicalizer::is_blake3_512_cid(&value) {
            return Err(CidError::Invalid(value));
        }
        Ok(Self(value))
    }

    pub(crate) fn from_hash_output(value: String) -> Self {
        debug_assert!(Self::parse(value.clone()).is_ok());
        Self(value)
    }

    /// Borrow the self-identifying CID string.
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Consume the CID into its string form.
    pub fn into_string(self) -> String {
        self.0
    }
}

impl fmt::Display for Cid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl Serialize for Cid {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.0)
    }
}

impl<'de> Deserialize<'de> for Cid {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(de::Error::custom)
    }
}

impl TryFrom<String> for Cid {
    type Error = CidError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl TryFrom<&str> for Cid {
    type Error = CidError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl From<Cid> for String {
    fn from(value: Cid) -> Self {
        value.0
    }
}

/// CID parse/shape errors.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum CidError {
    /// The string does not match `blake3-512:<128 hex>`.
    #[error("invalid BLAKE3-512 CID: {0}")]
    Invalid(String),
}

/// Faithful algebra term over operation CIDs.
///
/// This is the paper-16 stratum: cross-compilers can carry it and verifiers
/// may discard it once the lossy contract projection is durable. We introduce
/// `core::Term` instead of extending generated `IrTerm` because `IrTerm::Ctor`
/// is generated from the protocol CDDL and still carries only a bare name.
/// Conversions are provided: `From<IrTerm>` synthesizes a deterministic
/// name-derived op CID for compatibility, while `From<Term> for IrTerm`
/// crosses back into the historical IR by delegating to the single lowering
/// seam [`crate::wp::lower_term`], which *records* the discarded op CID as an
/// [`OpCidProjection`] rather than silently dropping it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Term {
    /// Operation application grounded by the content ID of the operation.
    #[serde(rename = "op")]
    Op {
        #[serde(rename = "opCid")]
        op_cid: Cid,
        name: String,
        args: Vec<Term>,
    },
    /// Named variable.
    #[serde(rename = "var")]
    Var { name: String },
    /// JSON constant with an IR sort.
    #[serde(rename = "const")]
    Const { value: JsonValue, sort: Sort },
    /// Unit value; encoded as `Ctor("unit")` when converted to `IrTerm`.
    #[serde(rename = "unit")]
    Unit,
}

/// One operation node yielded by [`Term::walk`].
pub struct TermNode<'a> {
    /// Borrowed operation CID from the term.
    pub op_cid: &'a Cid,
    /// Borrowed operation name from the term.
    pub op_name: &'a str,
    /// Slot path from the root term to this operation node.
    pub term_position: Vec<usize>,
}

/// Borrowing pre-order iterator over operation nodes in a [`Term`].
pub struct TermWalkIter<'a> {
    root: Option<&'a Term>,
    stack: Vec<TermWalkFrame<'a>>,
    term_position: Vec<usize>,
}

struct TermWalkFrame<'a> {
    args: &'a [Term],
    next_index: usize,
}

impl Term {
    /// Walk operation nodes in pre-order.
    ///
    /// The yielded `term_position` is a slot path from the root term: `[]` for
    /// the root op, `[0]` for the first op child, and `[0, 2]` for the third
    /// op child under the first child. `Term::Const`, `Term::Var`, and
    /// `Term::Unit` carry no operation CID, so the iterator skips those leaves
    /// instead of manufacturing sentinel operation IDs.
    pub fn walk(&self) -> TermWalkIter<'_> {
        TermWalkIter {
            root: Some(self),
            stack: Vec::new(),
            term_position: Vec::new(),
        }
    }
}

impl<'a> Iterator for TermWalkIter<'a> {
    type Item = TermNode<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        loop {
            let term = if let Some(root) = self.root.take() {
                root
            } else {
                self.next_child()?
            };

            match term {
                Term::Op { op_cid, name, args } => {
                    self.stack.push(TermWalkFrame {
                        args,
                        next_index: 0,
                    });
                    return Some(TermNode {
                        op_cid,
                        op_name: name.as_str(),
                        term_position: self.term_position.clone(),
                    });
                }
                Term::Const { .. } | Term::Var { .. } | Term::Unit => {
                    if !self.stack.is_empty() {
                        self.term_position.pop();
                    }
                }
            }
        }
    }
}

impl<'a> TermWalkIter<'a> {
    fn next_child(&mut self) -> Option<&'a Term> {
        loop {
            let frame = self.stack.last_mut()?;
            if frame.next_index < frame.args.len() {
                let index = frame.next_index;
                frame.next_index += 1;
                self.term_position.push(index);
                return Some(&frame.args[index]);
            }

            self.stack.pop();
            self.term_position.pop();
        }
    }
}

/// Declared child ordering policy for one operation in a language signature.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ArityShape {
    /// Child order is semantic and index-bearing.
    Positional { arity: usize },
    /// Child slots are named; order in the source vector only assigns slots.
    Named { slots: Vec<AritySlot> },
    /// Child order is not semantic; children are sorted by child CID.
    Set {
        /// Uniform member sort for this set.
        #[serde(default, skip_serializing_if = "slot_sort_is_default")]
        member_sort: SlotSort,
    },
}

/// Evaluation status declared for a child slot.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SlotEvaluation {
    /// The child participates in normal evaluation.
    #[default]
    Evaluated,
    /// The child is structurally present but its side effects do not fire.
    Unevaluated,
}

/// Declared kind of value addressed by a child slot.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SlotSort {
    /// A normal algebra term.
    #[default]
    Term,
    /// A type-level child.
    Type,
    /// An identifier/designator child.
    Identifier,
    /// A literal payload child.
    Literal,
}

/// One named child slot in an operation arity declaration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AritySlot {
    /// Canonical slot name.
    pub name: String,
    /// Whether the algebra evaluates this child.
    #[serde(default, skip_serializing_if = "slot_evaluation_is_default")]
    pub evaluation: SlotEvaluation,
    /// The kind of child addressed by this slot.
    #[serde(default, skip_serializing_if = "slot_sort_is_default")]
    pub slot_sort: SlotSort,
    /// Optional nested shape for this slot's child value.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub shape: Option<Box<ArityShape>>,
}

impl AritySlot {
    /// Construct an evaluated slot.
    pub fn evaluated(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            evaluation: SlotEvaluation::Evaluated,
            slot_sort: SlotSort::Term,
            shape: None,
        }
    }

    /// Construct an unevaluated slot.
    pub fn unevaluated(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            evaluation: SlotEvaluation::Unevaluated,
            slot_sort: SlotSort::Term,
            shape: None,
        }
    }

    /// Attach an explicit slot sort.
    pub fn with_slot_sort(mut self, slot_sort: SlotSort) -> Self {
        self.slot_sort = slot_sort;
        self
    }

    /// Attach a nested shape to this slot.
    pub fn with_shape(mut self, shape: ArityShape) -> Self {
        self.shape = Some(Box::new(shape));
        self
    }
}

impl ArityShape {
    /// Construct a positional child shape.
    pub fn positional(arity: usize) -> Self {
        Self::Positional { arity }
    }

    /// Construct a named-record child shape.
    pub fn named<const N: usize>(slots: [&str; N]) -> Self {
        Self::Named {
            slots: slots.into_iter().map(AritySlot::evaluated).collect(),
        }
    }

    /// Construct a named-record shape with explicit slot evaluation.
    pub fn named_slots<const N: usize>(slots: [AritySlot; N]) -> Self {
        Self::Named {
            slots: slots.into_iter().collect(),
        }
    }

    /// Construct an unordered-set child shape.
    pub fn set() -> Self {
        Self::Set {
            member_sort: SlotSort::Term,
        }
    }

    /// Construct an unordered-set child shape with a uniform member sort.
    pub fn set_of(member_sort: SlotSort) -> Self {
        Self::Set { member_sort }
    }
}

/// One operation entry inside a language signature catalog.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OperationSignature {
    /// Operation memento CID.
    pub op_cid: Cid,
    /// Child ordering policy declared by the catalog.
    pub arity_shape: ArityShape,
}

/// A resolved language signature with declared operation child shapes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanguageSignature {
    cid: Cid,
    operations: BTreeMap<String, OperationSignature>,
}

impl LanguageSignature {
    /// Create an empty signature entry addressed by `cid`.
    pub fn new(cid: Cid) -> Self {
        Self {
            cid,
            operations: BTreeMap::new(),
        }
    }

    /// Borrow the language-signature CID.
    pub fn cid(&self) -> &Cid {
        &self.cid
    }

    /// Add or replace one operation shape declaration.
    pub fn with_operation(
        mut self,
        name: impl Into<String>,
        op_cid: Cid,
        arity_shape: ArityShape,
    ) -> Self {
        self.operations.insert(
            name.into(),
            OperationSignature {
                op_cid,
                arity_shape,
            },
        );
        self
    }

    /// Return one operation declaration.
    pub fn operation(&self, name: &str) -> Option<&OperationSignature> {
        self.operations.get(name)
    }

    /// Compute a shape-aware CID for a term in this language signature.
    pub fn term_cid(&self, term: &Term) -> Result<Cid, SignatureCatalogError> {
        let value = self.term_value(term)?;
        Ok(Cid::from_hash_output(blake3_512_of(
            encode_jcs(value.as_ref()).as_bytes(),
        )))
    }

    fn term_value(&self, term: &Term) -> Result<Arc<CValue>, SignatureCatalogError> {
        match term {
            Term::Op { op_cid, name, args } => {
                let operation = self.operations.get(name).ok_or_else(|| {
                    SignatureCatalogError::UnknownOperation { name: name.clone() }
                })?;
                if &operation.op_cid != op_cid {
                    return Err(SignatureCatalogError::OperationCidMismatch {
                        name: name.clone(),
                        expected: operation.op_cid.clone(),
                        actual: op_cid.clone(),
                    });
                }
                let children = self.children_value(args, &operation.arity_shape)?;
                Ok(CValue::object([
                    ("kind", CValue::string("op")),
                    (
                        "signatureCid",
                        CValue::string(self.cid.as_str().to_string()),
                    ),
                    ("opCid", CValue::string(op_cid.as_str().to_string())),
                    ("name", CValue::string(name.clone())),
                    ("arityShape", arity_shape_value(&operation.arity_shape)),
                    ("children", children),
                ]))
            }
            Term::Var { name } => Ok(CValue::object([
                ("kind", CValue::string("var")),
                ("name", CValue::string(name.clone())),
            ])),
            Term::Const { value, sort } => Ok(CValue::object([
                ("kind", CValue::string("const")),
                ("value", json_to_cvalue(value.clone())),
                (
                    "sort",
                    json_to_cvalue(serde_json::to_value(sort).expect("sort serializes")),
                ),
            ])),
            Term::Unit => Ok(CValue::object([("kind", CValue::string("unit"))])),
        }
    }

    fn children_value(
        &self,
        args: &[Term],
        shape: &ArityShape,
    ) -> Result<Arc<CValue>, SignatureCatalogError> {
        match shape {
            ArityShape::Positional { arity } => {
                require_arity(*arity, args.len(), shape)?;
                Ok(CValue::array(
                    args.iter()
                        .map(|arg| self.term_value(arg))
                        .collect::<Result<Vec<_>, _>>()?,
                ))
            }
            ArityShape::Named { slots } => {
                require_arity(slots.len(), args.len(), shape)?;
                Ok(CValue::object(
                    slots
                        .iter()
                        .zip(args)
                        .map(|(slot, arg)| {
                            self.term_value(arg).map(|value| (slot.name.clone(), value))
                        })
                        .collect::<Result<Vec<_>, _>>()?,
                ))
            }
            ArityShape::Set { .. } => {
                let mut children = args
                    .iter()
                    .map(|arg| {
                        let value = self.term_value(arg)?;
                        let cid = Cid::from_hash_output(blake3_512_of(
                            encode_jcs(value.as_ref()).as_bytes(),
                        ));
                        Ok((cid, value))
                    })
                    .collect::<Result<Vec<_>, SignatureCatalogError>>()?;
                children.sort_by(|left, right| left.0.cmp(&right.0));
                Ok(CValue::array(
                    children.into_iter().map(|(_, value)| value).collect(),
                ))
            }
        }
    }
}

/// Errors from shape-aware language signature use.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum SignatureCatalogError {
    /// A term names an operation not present in the signature.
    #[error("language signature is missing operation `{name}`")]
    UnknownOperation { name: String },
    /// The term's op CID does not match the catalog entry for the name.
    #[error("operation `{name}` CID mismatch: expected {expected}, got {actual}")]
    OperationCidMismatch {
        name: String,
        expected: Cid,
        actual: Cid,
    },
    /// The number of supplied children does not match the declared shape.
    #[error("arity shape {shape:?} expected {expected} children, got {actual}")]
    ArityMismatch {
        shape: ArityShape,
        expected: usize,
        actual: usize,
    },
}

fn require_arity(
    expected: usize,
    actual: usize,
    shape: &ArityShape,
) -> Result<(), SignatureCatalogError> {
    if expected == actual {
        Ok(())
    } else {
        Err(SignatureCatalogError::ArityMismatch {
            shape: shape.clone(),
            expected,
            actual,
        })
    }
}

fn arity_shape_value(shape: &ArityShape) -> Arc<CValue> {
    match shape {
        ArityShape::Positional { arity } => CValue::object([
            ("kind", CValue::string("positional")),
            ("arity", CValue::integer(*arity as i128)),
        ]),
        ArityShape::Named { slots } => CValue::object([
            ("kind", CValue::string("named")),
            (
                "slots",
                CValue::array(
                    slots
                        .iter()
                        .map(|slot| {
                            let mut fields = vec![("name", CValue::string(slot.name.clone()))];
                            if slot.evaluation == SlotEvaluation::Unevaluated {
                                fields.push(("evaluation", CValue::string("unevaluated")));
                            }
                            if slot.slot_sort != SlotSort::Term {
                                fields.push((
                                    "slot_sort",
                                    CValue::string(match slot.slot_sort {
                                        SlotSort::Term => "term",
                                        SlotSort::Type => "type",
                                        SlotSort::Identifier => "identifier",
                                        SlotSort::Literal => "literal",
                                    }),
                                ));
                            }
                            if let Some(shape) = &slot.shape {
                                fields.push(("shape", arity_shape_value(shape)));
                            }
                            CValue::object(fields)
                        })
                        .collect(),
                ),
            ),
        ]),
        ArityShape::Set { member_sort } => {
            let mut fields = vec![("kind", CValue::string("set"))];
            if *member_sort != SlotSort::Term {
                fields.push((
                    "member_sort",
                    CValue::string(match member_sort {
                        SlotSort::Term => "term",
                        SlotSort::Type => "type",
                        SlotSort::Identifier => "identifier",
                        SlotSort::Literal => "literal",
                    }),
                ));
            }
            CValue::object(fields)
        }
    }
}

fn slot_evaluation_is_default(evaluation: &SlotEvaluation) -> bool {
    *evaluation == SlotEvaluation::Evaluated
}

fn slot_sort_is_default(slot_sort: &SlotSort) -> bool {
    *slot_sort == SlotSort::Term
}

impl From<IrTerm> for Term {
    fn from(value: IrTerm) -> Self {
        match value {
            IrTerm::Var { name } => Term::Var { name },
            IrTerm::Const { value, sort } => Term::Const { value, sort },
            IrTerm::Ctor { name, args } => Term::Op {
                op_cid: operation_name_cid(&name),
                name,
                args: args.into_iter().map(Term::from).collect(),
            },
            IrTerm::Lambda {
                param_name,
                param_sort,
                body,
            } => Term::Op {
                op_cid: operation_name_cid("lambda"),
                name: "lambda".to_string(),
                args: vec![
                    Term::Const {
                        value: serde_json::json!({
                            "paramName": param_name,
                            "paramSort": param_sort,
                        }),
                        sort: Sort::Primitive {
                            name: "Metadata".to_string(),
                        },
                    },
                    Term::from(*body),
                ],
            },
            IrTerm::Let { bindings, body } => {
                let mut args: Vec<Term> = bindings
                    .into_iter()
                    .map(|binding| Term::Op {
                        op_cid: operation_name_cid("let-binding"),
                        name: binding.name,
                        args: vec![Term::from(binding.bound_term)],
                    })
                    .collect();
                args.push(Term::from(*body));
                Term::Op {
                    op_cid: operation_name_cid("let"),
                    name: "let".to_string(),
                    args,
                }
            }
        }
    }
}

impl From<Term> for IrTerm {
    fn from(value: Term) -> Self {
        // Structural lowering is the degenerate case of the single
        // term-lowering seam `wp::lower_term` run against a resolver that
        // knows no contracts ([`crate::wp::EmptyOpResolver`]): every `Op`
        // falls to the bare `Ctor` form, and the faithful op-CID texture is
        // *recorded* as an `OpCidProjection` and then loudly projected away,
        // never silently dropped via `..`. Because no contract can ever be
        // found, neither `OpaqueCall` nor `ArityMismatch` can fire, so the
        // lowering is total and the `expect` is unreachable.
        crate::wp::lower_term(&value, &crate::wp::EmptyOpResolver)
            .expect("structural lowering against the empty resolver is total")
    }
}

/// One recorded op-CID projection: the faithful operation content-ID that the
/// single lowering seam [`crate::wp::lower_term`] discards when it lowers a
/// [`Term::Op`] into the historical [`IrTerm::Ctor`], which carries only a
/// bare name.
///
/// This is the paper-16 texture the paper-9 [`Boundary`] is licensed to drop.
/// Materializing it here turns what used to be a silent `..` pattern-drop into
/// an auditable record: [`crate::wp::lower_term_projected`] returns the full
/// list of op CIDs a lowering had to project away.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpCidProjection {
    /// The bare operation name that survives into [`IrTerm::Ctor`].
    pub name: String,
    /// The faithful operation content-ID that is projected away.
    pub op_cid: Cid,
}

/// The lossy formula stratum reused from `sugar-ir-types`.
///
/// `IrFormula` already has the required shape (`And`, `Or`, `Not`, `Implies`,
/// `Atomic`, `Forall`, `Exists`, `Choice`) and is the type accepted by the
/// existing WP/composition code. It remains the durable paper-9 projection;
/// faithful op-CID texture lives in [`Term`] and may be discarded.
pub type Formula = IrFormula;

/// A function-contract projection reused from `libsugar::compose`.
///
/// `FunctionContractMemento` is a superset of the requested `Contract` fields:
/// it carries formals, formal sorts, return sort, pre/post formulas, effects,
/// plus existing CID/canonical-byte/locus metadata. Reusing it preserves the
/// established API and lets core composition delegate to the CCP algebra.
pub type Contract = FunctionContractMemento;

/// Content-addressed witness for a resolved claim.
///
/// This is the durable evidence object set by primitive 7. The initial pass
/// stores proof trees, counterexample models, and unknown transcripts as JSON.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Witness {
    /// Proof tree or SMT-LIB transcript establishing truth.
    #[serde(rename = "proof")]
    Proof { tree: JsonValue },
    /// Model establishing refutation.
    #[serde(rename = "counterexample")]
    Counterexample { model: JsonValue },
    /// Solver/checker transcript for an unknown result.
    #[serde(rename = "unknown")]
    Unknown { transcript: JsonValue },
    /// Chain-integrity evidence produced by ProveKit.
    #[serde(rename = "chain-integrity")]
    ChainIntegrity(ChainIntegrityWitness),
    /// Chain-integrity failure evidence produced by ProveKit.
    #[serde(rename = "chain-integrity-failure")]
    ChainIntegrityFailure(ChainIntegrityFailureWitness),
}

/// Evidence that a claim's premise chain reaches the configured root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChainIntegrityWitness {
    /// Root claim CID reached by the walk.
    pub walked_chain_root_cid: Cid,
    /// Premise CIDs visited during the walk.
    pub walked_steps: Vec<Cid>,
    /// Witness schema version.
    pub schema_version: u32,
}

/// Evidence that a claim's premise chain broke before reaching the root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChainIntegrityFailureWitness {
    /// Root claim CID the walk tried to reach.
    pub walked_chain_root_cid: Cid,
    /// Premise CIDs visited before the break.
    pub walked_steps_before_break: Vec<Cid>,
    /// Serialized [`ChainBreak`](super::walks::ChainBreak) variant name.
    pub break_kind: String,
    /// Human-readable diagnostic detail for the break.
    pub break_detail: String,
    /// Witness schema version.
    pub schema_version: u32,
}

/// Resolution state of a claim.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Verdict {
    /// No discharge has been attempted or recorded.
    Unresolved,
    /// A witness proves the claim.
    Proved,
    /// A witness refutes the claim; this is a finding.
    Refuted,
    /// Discharge ran but could not decide the claim.
    Unknown,
}

/// Semantic domain kind carried by claims.
///
/// The plugin trait is also named `Domain`, so the field type is `DomainKind`
/// to keep Rust's namespace clear while preserving the design's axis.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DomainKind {
    /// Function contract / weakest-precondition domain.
    FunctionContract,
    /// Protocol-evolution paths.
    ProtocolEvolution,
    /// Supply graph paths.
    SupplyGraph,
    /// Bug-pattern findings.
    BugPattern,
    /// License/compliance paths.
    License,
    /// Hardware or machine-code paths.
    Hardware,
    /// Forward-compatible catch-all.
    Other(String),
}

/// Dialect accepted or emitted by a kit.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Dialect {
    /// C source or C-family AST.
    C,
    /// Rust source input.
    Rust,
    /// x86-64 assembly or machine-code view.
    X86_64,
    /// AArch64 assembly or machine-code view.
    AArch64,
    /// WebAssembly.
    Wasm,
    /// JVM bytecode.
    JvmBytecode,
    /// Coq terms/scripts.
    Coq,
    /// SMT-LIB text.
    SmtLib,
    /// Forward-compatible catch-all.
    Other(String),
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub enum ConformanceDeclaration {
    /// Kit emits target source and pins the fixture directory that proves it.
    Carrier { fixtures_path: PathBuf },
    /// Kit does not emit target source; `reason` records the audit premise.
    NonCarrier { reason: &'static str },
}

/// Boundary knob for `Domain::project`.
///
/// This is the paper-9 knob: it decides which faithful texture is discarded
/// when projecting a term into a durable contract. The initial implementation
/// only exposes a named default boundary; richer policies can grow here
/// without changing the primitive signatures.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Boundary {
    /// Human-readable policy name.
    pub name: String,
    /// Whether a projection is expected to discard the faithful term.
    pub discard_faithful_term: bool,
}

impl Default for Boundary {
    fn default() -> Self {
        Self {
            name: "paper-9-default".to_string(),
            discard_faithful_term: false,
        }
    }
}

/// Ed25519 attestation attached by primitive 8, `sign`.
///
/// The attestation is authoring metadata. It is verified when present but is
/// excluded from [`DomainClaim`]'s canonical bytes so verification remains
/// author-independent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Attestation {
    /// Self-identifying public key, `ed25519:<base64>`.
    pub signer: String,
    /// Self-identifying signature, `ed25519:<base64>`.
    pub signature: String,
    /// CID of the unsigned claim bytes covered by the signature.
    #[serde(rename = "signedCid")]
    pub signed_cid: Cid,
}

/// Central IPath type: a domain-specific path from input CIDs to an output CID.
///
/// A `DomainClaim` is unresolved when no witness is present, and resolved when
/// `witness` and `verdict` agree. Faithful language-specific terms live in
/// addressed artifacts owned by kits; the primitive carries only their CIDs.
#[derive(Debug, Clone)]
pub struct DomainClaim {
    /// Domain polymorphism axis.
    pub domain: DomainKind,
    /// Durable lossy projection.
    pub contract: Contract,
    /// Kit-owned artifacts used to derive this claim.
    pub artifacts: Vec<Cid>,
    /// Input endpoint CIDs.
    pub from: Vec<Cid>,
    /// Immediate input claim CIDs used to derive this claim.
    pub premises: Vec<Cid>,
    /// Output endpoint CID.
    pub to: Cid,
    /// Optional content-addressed witness.
    pub witness: Option<Witness>,
    /// Optional faithful term payload materialized by transform kits.
    pub payload: Option<Term>,
    /// Current discharge verdict.
    pub verdict: Verdict,
    /// Optional signer attestation, excluded from claim identity.
    pub attestation: Option<Attestation>,
}

impl DomainClaim {
    /// Return `address(self)`: the signer-independent CID of this path value.
    pub fn cid(&self) -> Cid {
        super::primitives::address(self)
    }

    /// Return the canonical bytes used by [`DomainClaim::cid`].
    pub fn canonical_bytes(&self) -> Vec<u8> {
        <Self as Canonical>::canonical_bytes(self)
    }

    /// Clone the claim without courtesy-layer attestation metadata.
    pub fn unsigned(&self) -> Self {
        let mut clone = self.clone();
        clone.attestation = None;
        clone
    }

    /// Union this claim with another claim in the same domain.
    pub fn union(&self, other: &Self) -> Result<Self, super::primitives::ComposeError> {
        super::primitives::compose(self, other)
    }
}

/// A proved domain claim.
///
/// `Truth` is self-verifying by the `verify` verb: resolve the claim bytes,
/// recompute the address, check any signature, then re-walk the witness in
/// `Domain::discharge(Check)` mode.
#[derive(Debug, Clone)]
pub struct Truth(DomainClaim);

/// A refuted domain claim.
///
/// A `Refutation` is the finding type. It is also valid input to a fresh
/// transform.
#[derive(Debug, Clone)]
pub struct Refutation(DomainClaim);

impl Truth {
    /// Borrow the proved claim.
    pub fn claim(&self) -> &DomainClaim {
        &self.0
    }

    /// Consume the wrapper and return the proved claim.
    pub fn into_claim(self) -> DomainClaim {
        self.0
    }
}

impl Refutation {
    /// Borrow the refuted claim.
    pub fn claim(&self) -> &DomainClaim {
        &self.0
    }

    /// Consume the wrapper and return the refuted claim.
    pub fn into_claim(self) -> DomainClaim {
        self.0
    }
}

impl TryFrom<DomainClaim> for Truth {
    type Error = VerdictCoercionError;

    fn try_from(value: DomainClaim) -> Result<Self, Self::Error> {
        if value.verdict == Verdict::Proved {
            Ok(Self(value))
        } else {
            Err(VerdictCoercionError::ExpectedProved {
                actual: value.verdict,
            })
        }
    }
}

impl TryFrom<DomainClaim> for Refutation {
    type Error = VerdictCoercionError;

    fn try_from(value: DomainClaim) -> Result<Self, Self::Error> {
        if value.verdict == Verdict::Refuted {
            Ok(Self(value))
        } else {
            Err(VerdictCoercionError::ExpectedRefuted {
                actual: value.verdict,
            })
        }
    }
}

/// Error when coercing a raw claim into a verdict-refined newtype.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum VerdictCoercionError {
    /// `Truth` requires `Verdict::Proved`.
    #[error("expected proved claim, got {actual:?}")]
    ExpectedProved { actual: Verdict },
    /// `Refutation` requires `Verdict::Refuted`.
    #[error("expected refuted claim, got {actual:?}")]
    ExpectedRefuted { actual: Verdict },
}

/// A composed transformation path.
///
/// A path is a set of algebra steps. Each step names a kit transform, its
/// input, and the step names it depends on. Executing a command is still one
/// `Kit(Input) -> DomainClaim`; `Input::Path` carries the algebra needed for
/// that kit to compose subordinate transforms when necessary.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Path {
    /// Algebra steps available to the transform.
    pub algebra: Vec<PathAlgebra>,
}

impl Path {
    /// Return `address(self)`: the CID of this language-neutral composition value.
    pub fn cid(&self) -> Cid {
        super::primitives::address(self)
    }

    /// Find one named algebra step.
    pub fn step(&self, name: &str) -> Option<&PathAlgebra> {
        self.algebra.iter().find(|step| step.name == name)
    }

    /// Return algebra steps in dependency order.
    pub fn ordered_steps(&self) -> Result<Vec<&PathAlgebra>, PathError> {
        let mut steps = BTreeMap::new();
        for step in &self.algebra {
            if steps.insert(step.name.clone(), step).is_some() {
                return Err(PathError::DuplicateStep {
                    name: step.name.clone(),
                });
            }
        }

        let mut incoming = BTreeMap::new();
        let mut outgoing: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for step in &self.algebra {
            let mut dependencies = BTreeSet::new();
            for dependency in &step.depends_on {
                if !steps.contains_key(dependency) {
                    return Err(PathError::MissingDependency {
                        step: step.name.clone(),
                        dependency: dependency.clone(),
                    });
                }
                dependencies.insert(dependency.clone());
                outgoing
                    .entry(dependency.clone())
                    .or_default()
                    .insert(step.name.clone());
            }
            incoming.insert(step.name.clone(), dependencies);
        }

        let mut ready: BTreeSet<String> = incoming
            .iter()
            .filter_map(|(name, dependencies)| {
                if dependencies.is_empty() {
                    Some(name.clone())
                } else {
                    None
                }
            })
            .collect();
        let mut ordered = Vec::with_capacity(self.algebra.len());

        while let Some(name) = ready.iter().next().cloned() {
            ready.remove(&name);
            ordered.push(*steps.get(&name).expect("ready step exists"));

            for dependent in outgoing.get(&name).into_iter().flatten() {
                let dependencies = incoming
                    .get_mut(dependent)
                    .expect("dependent step has incoming set");
                dependencies.remove(&name);
                if dependencies.is_empty() {
                    ready.insert(dependent.clone());
                }
            }
        }

        if ordered.len() != self.algebra.len() {
            let step = incoming
                .iter()
                .find_map(|(name, dependencies)| {
                    if dependencies.is_empty() {
                        None
                    } else {
                        Some(name.clone())
                    }
                })
                .unwrap_or_default();
            return Err(PathError::Cycle { step });
        }

        Ok(ordered)
    }

    /// Return steps that no other step depends on.
    pub fn terminal_steps(&self) -> Vec<&PathAlgebra> {
        let dependencies: BTreeSet<&str> = self
            .algebra
            .iter()
            .flat_map(|step| step.depends_on.iter().map(String::as_str))
            .collect();
        let mut terminals: Vec<&PathAlgebra> = self
            .algebra
            .iter()
            .filter(|step| !dependencies.contains(step.name.as_str()))
            .collect();
        terminals.sort_by(|left, right| left.name.cmp(&right.name));
        terminals
    }
}

/// Primitive selector for one path-algebra step.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Verb {
    /// Transform input material into a domain claim.
    Transform,
    /// Prove or otherwise discharge an existing domain claim.
    Prove,
}

impl Verb {
    /// Return whether this is the wire-default path verb.
    pub fn is_default(&self) -> bool {
        matches!(self, Self::Transform)
    }
}

impl Default for Verb {
    fn default() -> Self {
        Self::Transform
    }
}

/// One algebra step inside a [`Path`].
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PathAlgebra {
    /// Stable step name inside the path.
    pub name: String,
    /// Kit transform to apply.
    pub kit: String,
    /// Kit primitive to dispatch for this step.
    #[serde(default, skip_serializing_if = "Verb::is_default")]
    pub verb: Verb,
    /// Input artifact CIDs to that transform.
    pub inputs: Vec<Cid>,
    /// Names of prerequisite algebra steps.
    pub depends_on: Vec<String>,
}

/// Invalid path algebra.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum PathError {
    /// Two steps share the same stable name.
    #[error("path contains duplicate step `{name}`")]
    DuplicateStep { name: String },
    /// A step names a prerequisite that does not exist in the path.
    #[error("path step `{step}` depends on missing step `{dependency}`")]
    MissingDependency { step: String, dependency: String },
    /// The dependency graph contains a cycle.
    #[error("path dependency cycle includes step `{step}`")]
    Cycle { step: String },
}

/// Stable top-level kind for serialized path documents.
pub const PATH_DOCUMENT_KIND: &str = "sugar-path/v1";

/// Serializable, language-neutral path plus the materialized input catalog it
/// needs to execute.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PathDocument {
    /// Wire kind/version for disk and cross-runtime transport.
    pub kind: String,
    /// The CID-able path algebra.
    pub path: Path,
    /// Materialized inputs keyed by the CIDs referenced from path steps.
    #[serde(default)]
    pub inputs: Vec<PathInputBinding>,
}

impl PathDocument {
    /// Build a path document and address each materialized input.
    pub fn from_path_and_inputs(path: Path, inputs: Vec<Input>) -> Result<Self, PathDocumentError> {
        let mut bindings = Vec::with_capacity(inputs.len());
        for input in inputs {
            bindings.push(PathInputBinding {
                cid: super::primitives::address(&input),
                input: PathInputMaterial::try_from_input(input)?,
            });
        }
        Ok(Self {
            kind: PATH_DOCUMENT_KIND.to_string(),
            path,
            inputs: bindings,
        })
    }

    /// Validate and materialize the typed input catalog entries.
    pub fn materialized_inputs(&self) -> Result<Vec<(Cid, Input)>, PathDocumentError> {
        if self.kind != PATH_DOCUMENT_KIND {
            return Err(PathDocumentError::InvalidKind {
                expected: PATH_DOCUMENT_KIND,
                actual: self.kind.clone(),
            });
        }

        let mut out = Vec::with_capacity(self.inputs.len());
        let mut materialized = BTreeMap::new();
        for binding in &self.inputs {
            let input = binding.input.to_input()?;
            let actual = super::primitives::address(&input);
            if actual != binding.cid {
                return Err(PathDocumentError::InputCidMismatch {
                    expected: binding.cid.clone(),
                    actual,
                });
            }
            materialized.insert(binding.cid.clone(), input.clone());
            out.push((binding.cid.clone(), input));
        }
        let mut seen = BTreeSet::new();
        validate_path_input_closure(&self.path, &materialized, &mut seen)?;
        Ok(out)
    }
}

/// One materialized input entry in a [`PathDocument`].
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PathInputBinding {
    /// CID referenced from `PathAlgebra.inputs`.
    pub cid: Cid,
    /// Materialized input value.
    pub input: PathInputMaterial,
}

/// Disk-safe materialized [`Input`] used by path documents.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "kebab-case")]
pub enum PathInputMaterial {
    /// Dialect-specific source bytes.
    Source { dialect: Dialect, bytes: Vec<u8> },
    /// JSON command/spec input.
    Spec { value: JsonValue },
    /// Raw claim input.
    Claim { claim: PathDomainClaimMaterial },
    /// Proved claim input.
    Truth { claim: PathDomainClaimMaterial },
    /// Refuted finding input.
    Refutation { claim: PathDomainClaimMaterial },
    /// Faithful term input.
    Term { term: Term },
    /// Composed path input.
    Path { path: Path },
}

impl PathInputMaterial {
    fn try_from_input(input: Input) -> Result<Self, PathDocumentError> {
        match input {
            Input::Source { dialect, bytes } => Ok(Self::Source { dialect, bytes }),
            Input::Spec(value) => Ok(Self::Spec { value }),
            Input::Claim(claim) => Ok(Self::Claim {
                claim: PathDomainClaimMaterial::from_claim(&claim),
            }),
            Input::Truth(truth) => Ok(Self::Truth {
                claim: PathDomainClaimMaterial::from_claim(truth.claim()),
            }),
            Input::Refutation(refutation) => Ok(Self::Refutation {
                claim: PathDomainClaimMaterial::from_claim(refutation.claim()),
            }),
            Input::Term(term) => Ok(Self::Term { term }),
            Input::Path(path) => Ok(Self::Path { path: *path }),
        }
    }

    fn to_input(&self) -> Result<Input, PathDocumentError> {
        match self {
            Self::Source { dialect, bytes } => Ok(Input::Source {
                dialect: dialect.clone(),
                bytes: bytes.clone(),
            }),
            Self::Spec { value } => Ok(Input::Spec(value.clone())),
            Self::Claim { claim } => Ok(Input::Claim(claim.to_claim())),
            Self::Truth { claim } => {
                let claim = claim.to_claim();
                Truth::try_from(claim).map(Input::Truth).map_err(|error| {
                    PathDocumentError::InvalidInputMaterial {
                        kind: "truth",
                        reason: error.to_string(),
                    }
                })
            }
            Self::Refutation { claim } => {
                let claim = claim.to_claim();
                Refutation::try_from(claim)
                    .map(Input::Refutation)
                    .map_err(|error| PathDocumentError::InvalidInputMaterial {
                        kind: "refutation",
                        reason: error.to_string(),
                    })
            }
            Self::Term { term } => Ok(Input::Term(term.clone())),
            Self::Path { path } => Ok(Input::Path(Box::new(path.clone()))),
        }
    }
}

/// Disk-safe materialized domain claim inside a path document.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PathDomainClaimMaterial {
    /// Domain polymorphism axis.
    pub domain: DomainKind,
    /// Durable lossy projection.
    pub contract: PathContractMaterial,
    /// Kit-owned artifacts used to derive this claim.
    pub artifacts: Vec<Cid>,
    /// Input endpoint CIDs.
    pub from: Vec<Cid>,
    /// Immediate input claim CIDs used to derive this claim.
    pub premises: Vec<Cid>,
    /// Output endpoint CID.
    pub to: Cid,
    /// Optional content-addressed witness.
    pub witness: Option<Witness>,
    /// Current discharge verdict.
    pub verdict: Verdict,
    /// Optional signer attestation, excluded from claim identity.
    pub attestation: Option<Attestation>,
}

impl PathDomainClaimMaterial {
    fn from_claim(claim: &DomainClaim) -> Self {
        Self {
            domain: claim.domain.clone(),
            contract: PathContractMaterial::from_contract(&claim.contract),
            artifacts: claim.artifacts.clone(),
            from: claim.from.clone(),
            premises: claim.premises.clone(),
            to: claim.to.clone(),
            witness: claim.witness.clone(),
            verdict: claim.verdict,
            attestation: claim.attestation.clone(),
        }
    }

    fn to_claim(&self) -> DomainClaim {
        DomainClaim {
            domain: self.domain.clone(),
            contract: self.contract.to_contract(),
            artifacts: self.artifacts.clone(),
            from: self.from.clone(),
            premises: self.premises.clone(),
            to: self.to.clone(),
            witness: self.witness.clone(),
            verdict: self.verdict,
            attestation: self.attestation.clone(),
            payload: None,
        }
    }
}

pub(crate) fn domain_claim_from_canonical_bytes(bytes: &[u8]) -> Result<DomainClaim, String> {
    let value: JsonValue = serde_json::from_slice(bytes)
        .map_err(|error| format!("parse DomainClaim canonical JSON: {error}"))?;
    domain_claim_from_json_value(value)
}

fn domain_claim_from_json_value(value: JsonValue) -> Result<DomainClaim, String> {
    let object = value
        .as_object()
        .ok_or_else(|| "DomainClaim canonical JSON is not an object".to_string())?;
    let contract_value = object
        .get("contract")
        .cloned()
        .ok_or_else(|| "DomainClaim canonical JSON missing contract".to_string())?;
    let contract_cid = crate::canonical::json_cid(&contract_value)
        .map_err(|error| format!("address DomainClaim contract: {error}"))?;
    let contract = PathContractMaterial {
        cid: contract_cid,
        value: contract_value,
        formal_regions: vec![],
        return_region: None,
        concept_hint: None,
    }
    .to_contract();

    Ok(DomainClaim {
        domain: required_field(object, "domain")?,
        contract,
        artifacts: required_field(object, "artifacts")?,
        from: required_field(object, "from")?,
        premises: required_field(object, "premises")?,
        to: required_field(object, "to")?,
        witness: optional_field(object, "witness")?,
        payload: optional_field(object, "payload")?,
        verdict: required_field(object, "verdict")?,
        attestation: optional_field(object, "attestation")?,
    })
}

fn required_field<T>(object: &serde_json::Map<String, JsonValue>, field: &str) -> Result<T, String>
where
    T: de::DeserializeOwned,
{
    let value = object
        .get(field)
        .cloned()
        .ok_or_else(|| format!("DomainClaim canonical JSON missing {field}"))?;
    serde_json::from_value(value)
        .map_err(|error| format!("decode DomainClaim field {field}: {error}"))
}

fn optional_field<T>(
    object: &serde_json::Map<String, JsonValue>,
    field: &str,
) -> Result<Option<T>, String>
where
    T: de::DeserializeOwned,
{
    match object.get(field) {
        Some(JsonValue::Null) | None => Ok(None),
        Some(value) => serde_json::from_value(value.clone())
            .map(Some)
            .map_err(|error| format!("decode DomainClaim field {field}: {error}")),
    }
}

/// Disk-safe materialized function-contract projection inside a path document.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PathContractMaterial {
    /// Original contract CID metadata.
    pub cid: String,
    /// Canonical function-contract JSON value.
    pub value: JsonValue,
    /// Non-canonical formal region metadata.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub formal_regions: Vec<Option<String>>,
    /// Non-canonical return region metadata.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub return_region: Option<String>,
    /// Human-supplied concept hint retained outside canonical identity.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub concept_hint: Option<String>,
}

impl PathContractMaterial {
    fn from_contract(contract: &Contract) -> Self {
        let canonical_bytes = <Contract as Canonical>::canonical_bytes(contract);
        let value = serde_json::from_slice(&canonical_bytes)
            .expect("function contract canonical bytes parse as JSON");
        Self {
            cid: contract.cid.clone(),
            value,
            formal_regions: contract.formal_regions.clone(),
            return_region: contract.return_region.clone(),
            concept_hint: contract.concept_hint.clone(),
        }
    }

    fn to_contract(&self) -> Contract {
        let object = self.value.as_object();
        let canonical_bytes = jcs_bytes_for_json(self.value.clone());
        let formals = string_vec_field(object, "formals");
        let formal_regions = if self.formal_regions.len() == formals.len() {
            self.formal_regions.clone()
        } else {
            vec![None; formals.len()]
        };
        FunctionContractMemento {
            fn_name: string_field(object, "fnName").unwrap_or_default(),
            formal_regions,
            formals,
            formal_sorts: parse_vec_field(object, "formalSorts"),
            return_sort: parse_field(object, "returnSort").unwrap_or_else(any_sort),
            return_region: self.return_region.clone(),
            pre: parse_field(object, "pre").unwrap_or_else(formula_true),
            post: parse_field(object, "post").unwrap_or_else(formula_true),
            body_cid: optional_string_field(object, "bodyCid"),
            effects: parse_effect_set(object.and_then(|object| object.get("effects"))),
            locus: parse_locus(object.and_then(|object| object.get("locus"))),
            canonical_bytes,
            cid: self.cid.clone(),
            auto_minted_mementos: parse_aliasing_mementos(
                object.and_then(|object| object.get("autoMintedMementos")),
            ),
            panic_loci: vec![],
            concept_hint: self.concept_hint.clone(),
        }
    }
}

fn string_field(
    object: Option<&serde_json::Map<String, JsonValue>>,
    field: &str,
) -> Option<String> {
    object?
        .get(field)?
        .as_str()
        .map(std::string::ToString::to_string)
}

fn optional_string_field(
    object: Option<&serde_json::Map<String, JsonValue>>,
    field: &str,
) -> Option<String> {
    match object?.get(field)? {
        JsonValue::String(value) => Some(value.clone()),
        JsonValue::Null => None,
        _ => None,
    }
}

fn string_vec_field(
    object: Option<&serde_json::Map<String, JsonValue>>,
    field: &str,
) -> Vec<String> {
    object
        .and_then(|object| object.get(field))
        .and_then(JsonValue::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(std::string::ToString::to_string))
                .collect()
        })
        .unwrap_or_default()
}

fn parse_field<T>(object: Option<&serde_json::Map<String, JsonValue>>, field: &str) -> Option<T>
where
    T: de::DeserializeOwned,
{
    object
        .and_then(|object| object.get(field))
        .cloned()
        .and_then(|value| serde_json::from_value(value).ok())
}

fn parse_vec_field<T>(object: Option<&serde_json::Map<String, JsonValue>>, field: &str) -> Vec<T>
where
    T: de::DeserializeOwned,
{
    object
        .and_then(|object| object.get(field))
        .and_then(JsonValue::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| serde_json::from_value(item.clone()).ok())
                .collect()
        })
        .unwrap_or_default()
}

fn parse_effect_set(value: Option<&JsonValue>) -> EffectSet {
    let effects = value
        .and_then(JsonValue::as_array)
        .map(|items| items.iter().filter_map(parse_effect).collect())
        .unwrap_or_default();
    EffectSet { effects }
}

fn parse_effect(value: &JsonValue) -> Option<Effect> {
    let object = value.as_object();
    match string_field(object, "kind")?.as_str() {
        "reads" => Some(Effect::Reads {
            target: string_field(object, "target")?,
        }),
        "writes" => Some(Effect::Writes {
            target: string_field(object, "target")?,
        }),
        "io" => Some(Effect::Io),
        "unsafe" => Some(Effect::Unsafe),
        "panics" => Some(Effect::Panics),
        "unresolved_call" => Some(Effect::UnresolvedCall {
            name: string_field(object, "name")?,
        }),
        "opaque_loop" => Some(Effect::OpaqueLoop {
            loop_cid: string_field(object, "loopCid")?,
        }),
        "early_return" => Some(Effect::EarlyReturn {
            try_cid: string_field(object, "tryCid")?,
        }),
        "closure_capture" => Some(Effect::ClosureCapture {
            body_fn_cid: string_field(object, "bodyFnCid")?,
            n_captures: usize_field(object, "nCaptures")?,
        }),
        "pinned_reference" => Some(Effect::PinnedReference {
            target: string_field(object, "target")?,
        }),
        "raw_ptr_provenance" => Some(Effect::RawPointerProvenance {
            target: string_field(object, "target")?,
            mutable: bool_field(object, "mutable")?,
        }),
        "atomic_access" => Some(Effect::AtomicAccess {
            target: string_field(object, "target")?,
            kind: parse_atomic_kind(&string_field(object, "atomicKind")?)?,
            ordering: optional_string_field(object, "ordering"),
        }),
        "possible_aliasing" => Some(Effect::PossibleAliasing {
            formals: string_vec_field(object, "formals"),
        }),
        "drop" => Some(Effect::Drop {
            name: string_field(object, "name")?,
        }),
        _ => None,
    }
}

fn parse_atomic_kind(value: &str) -> Option<AtomicKind> {
    match value {
        "load" => Some(AtomicKind::Load),
        "store" => Some(AtomicKind::Store),
        "rmw" => Some(AtomicKind::Rmw),
        "cas" => Some(AtomicKind::Cas),
        _ => None,
    }
}

fn parse_locus(value: Option<&JsonValue>) -> Locus {
    let object = value.and_then(JsonValue::as_object);
    Locus {
        file: optional_string_field(object, "file"),
        line: usize_field(object, "line").unwrap_or(0),
        col: usize_field(object, "col").unwrap_or(0),
    }
}

fn parse_aliasing_mementos(value: Option<&JsonValue>) -> Vec<AliasingMemento> {
    value
        .and_then(JsonValue::as_array)
        .map(|items| items.iter().filter_map(parse_aliasing_memento).collect())
        .unwrap_or_default()
}

fn parse_aliasing_memento(value: &JsonValue) -> Option<AliasingMemento> {
    let object = value.as_object();
    if string_field(object, "kind")? != "aliasing-memento" {
        return None;
    }
    let status = match string_field(object, "status")?.as_str() {
        "Disjoint" => AliasingStatus::Disjoint,
        "MaybeAlias" => AliasingStatus::MaybeAlias,
        _ => return None,
    };
    Some(AliasingMemento {
        formal_a: string_field(object, "formal_a")?,
        formal_b: string_field(object, "formal_b")?,
        status,
    })
}

fn usize_field(object: Option<&serde_json::Map<String, JsonValue>>, field: &str) -> Option<usize> {
    object?
        .get(field)?
        .as_u64()
        .and_then(|value| usize::try_from(value).ok())
}

fn bool_field(object: Option<&serde_json::Map<String, JsonValue>>, field: &str) -> Option<bool> {
    object?.get(field)?.as_bool()
}

fn validate_path_input_closure(
    path: &Path,
    materialized: &BTreeMap<Cid, Input>,
    seen: &mut BTreeSet<Cid>,
) -> Result<(), PathDocumentError> {
    for step in &path.algebra {
        for cid in &step.inputs {
            let Some(input) = materialized.get(cid) else {
                return Err(PathDocumentError::MissingMaterializedInput { cid: cid.clone() });
            };
            if !seen.insert(cid.clone()) {
                continue;
            }
            if let Input::Path(path) = input {
                validate_path_input_closure(path, materialized, seen)?;
            }
        }
    }
    Ok(())
}

/// Serialized path document validation errors.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum PathDocumentError {
    /// The top-level `kind` is not the current path document kind.
    #[error("path document kind `{actual}` is not `{expected}`")]
    InvalidKind {
        /// Expected kind.
        expected: &'static str,
        /// Actual kind.
        actual: String,
    },
    /// A materialized input's bytes do not address to its declared CID.
    #[error("path input declared as `{expected}` materialized as `{actual}`")]
    InputCidMismatch {
        /// Declared CID.
        expected: Cid,
        /// Actual CID after canonicalization.
        actual: Cid,
    },
    /// A path step references an input CID that is not in the materialized catalog.
    #[error("path input `{cid}` is referenced but not materialized")]
    MissingMaterializedInput {
        /// Referenced input CID.
        cid: Cid,
    },
    /// The materialized input payload is not valid for its path input kind.
    #[error("path materialized `{kind}` input is invalid: {reason}")]
    InvalidInputMaterial {
        /// Materialized input kind.
        kind: &'static str,
        /// Precise refusal reason.
        reason: String,
    },
    /// The input variant is not yet part of the disk-safe path catalog.
    #[error("path documents do not support materialized `{kind}` inputs")]
    UnsupportedInputMaterial {
        /// Input variant name.
        kind: String,
    },
}

/// Closed input universe for transforms.
///
/// A source file, a spec, a raw claim, a `Truth`, a `Refutation`, or a faithful
/// term can all be transformed again. This closure is what lets proofs,
/// findings, and synthesized completions re-enter the algebra.
#[derive(Debug, Clone)]
pub enum Input {
    /// Dialect-specific source bytes.
    Source { dialect: Dialect, bytes: Vec<u8> },
    /// JSON spec input; `mint` is `transform` over this variant.
    Spec(JsonValue),
    /// Raw claim input.
    Claim(DomainClaim),
    /// Proved claim input.
    Truth(Truth),
    /// Refuted finding input.
    Refutation(Refutation),
    /// Faithful term input.
    Term(Term),
    /// Composed path input.
    Path(Box<Path>),
}

impl Canonical for String {
    fn canonical_bytes(&self) -> Vec<u8> {
        jcs_bytes_for_json(JsonValue::String(self.clone()))
    }
}

impl Canonical for &str {
    fn canonical_bytes(&self) -> Vec<u8> {
        jcs_bytes_for_json(JsonValue::String((*self).to_string()))
    }
}

impl Canonical for Cid {
    fn canonical_bytes(&self) -> Vec<u8> {
        jcs_bytes_for_json(JsonValue::String(self.0.clone()))
    }
}

impl Canonical for Term {
    fn canonical_bytes(&self) -> Vec<u8> {
        jcs_bytes_for_serialize(self)
    }
}

impl Canonical for IrFormula {
    fn canonical_bytes(&self) -> Vec<u8> {
        jcs_bytes_for_serialize(self)
    }
}

impl Canonical for FunctionContractMemento {
    fn canonical_bytes(&self) -> Vec<u8> {
        if !self.canonical_bytes.is_empty() {
            self.canonical_bytes.clone()
        } else {
            jcs_bytes_of_value(&build_memento_value(self))
        }
    }
}

impl Canonical for Witness {
    fn canonical_bytes(&self) -> Vec<u8> {
        jcs_bytes_for_serialize(self)
    }
}

impl Canonical for DomainClaim {
    fn canonical_bytes(&self) -> Vec<u8> {
        let value = domain_claim_to_value(self);
        encode_jcs(&value).into_bytes()
    }
}

impl Canonical for Path {
    fn canonical_bytes(&self) -> Vec<u8> {
        encode_jcs(&path_to_value(self)).into_bytes()
    }
}

impl Canonical for Input {
    fn canonical_bytes(&self) -> Vec<u8> {
        encode_jcs(&input_to_value(self)).into_bytes()
    }
}

pub(crate) fn jcs_bytes_for_serialize<T: Serialize>(value: &T) -> Vec<u8> {
    let json = serde_json::to_value(value).expect("core value serializes to JSON");
    jcs_bytes_for_json(json)
}

pub(crate) fn jcs_bytes_for_json(value: JsonValue) -> Vec<u8> {
    encode_jcs(&json_to_cvalue(value)).into_bytes()
}

pub(crate) fn json_to_cvalue(value: JsonValue) -> Arc<CValue> {
    match value {
        JsonValue::Null => CValue::null(),
        JsonValue::Bool(value) => CValue::boolean(value),
        JsonValue::Number(number) => {
            if let Some(value) = number.as_i64() {
                CValue::integer(i128::from(value))
            } else if let Some(value) = number.as_u64() {
                // u64 always fits the i128 carrier -- no fallback needed.
                CValue::integer(i128::from(value))
            } else {
                CValue::object([(
                    "__sugar_non_i64_number__",
                    CValue::string(number.to_string()),
                )])
            }
        }
        JsonValue::String(value) => CValue::string(value),
        JsonValue::Array(items) => CValue::array(items.into_iter().map(json_to_cvalue).collect()),
        JsonValue::Object(map) => CValue::object(
            map.into_iter()
                .map(|(key, value)| (key, json_to_cvalue(value))),
        ),
    }
}

pub(crate) fn contract_to_cvalue(contract: &Contract) -> Arc<CValue> {
    let bytes = <Contract as Canonical>::canonical_bytes(contract);
    match serde_json::from_slice::<JsonValue>(&bytes) {
        Ok(value) => json_to_cvalue(value),
        Err(_) => build_memento_value(contract),
    }
}

pub(crate) fn formula_true() -> IrFormula {
    IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    }
}

pub(crate) fn any_sort() -> Sort {
    Sort::Primitive {
        name: "Any".to_string(),
    }
}

pub(crate) fn memento_from_parts(
    fn_name: String,
    formals: Vec<String>,
    formal_sorts: Vec<Sort>,
    return_sort: Sort,
    pre: IrFormula,
    post: IrFormula,
    body_cid: Option<String>,
) -> Contract {
    let effects = crate::compose::EffectSet::empty();
    let locus = Locus::unknown();
    let value = crate::compose::build_value(
        &fn_name,
        &formals,
        &formal_sorts,
        &return_sort,
        &pre,
        &post,
        body_cid.as_deref(),
        &effects,
        &locus,
        &[],
    );
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = crate::compose::cid_of_value(&value);
    Contract {
        fn_name,
        formals,
        formal_sorts,
        formal_regions: vec![],
        return_sort,
        return_region: None,
        pre,
        post,
        body_cid,
        effects,
        locus,
        canonical_bytes,
        cid,
        auto_minted_mementos: vec![],
        panic_loci: vec![],
        concept_hint: None,
    }
}

fn domain_claim_to_value(claim: &DomainClaim) -> Arc<CValue> {
    let mut artifacts = claim.artifacts.clone();
    artifacts.sort();
    artifacts.dedup();
    let artifact_values: Vec<Arc<CValue>> = artifacts
        .iter()
        .map(|cid| CValue::string(cid.as_str().to_string()))
        .collect();
    let from_values: Vec<Arc<CValue>> = claim
        .from
        .iter()
        .map(|cid| CValue::string(cid.as_str().to_string()))
        .collect();
    let premise_values: Vec<Arc<CValue>> = claim
        .premises
        .iter()
        .map(|cid| CValue::string(cid.as_str().to_string()))
        .collect();
    let witness_value = match &claim.witness {
        Some(witness) => json_to_cvalue(serde_json::to_value(witness).expect("witness serializes")),
        None => CValue::null(),
    };

    let fields = vec![
        ("artifacts", CValue::array(artifact_values)),
        ("contract", contract_to_cvalue(&claim.contract)),
        (
            "domain",
            json_to_cvalue(serde_json::to_value(&claim.domain).expect("domain serializes")),
        ),
        ("from", CValue::array(from_values)),
        ("premises", CValue::array(premise_values)),
        ("to", CValue::string(claim.to.as_str().to_string())),
        (
            "verdict",
            json_to_cvalue(serde_json::to_value(claim.verdict).expect("verdict serializes")),
        ),
        ("witness", witness_value),
    ];
    // `payload` is a materialized artifact cache. Claim identity is pinned by
    // `to` and `artifacts`; including the payload here duplicates addressed
    // bytes and makes large lift responses part of the claim envelope.
    CValue::object(fields)
}

fn input_to_value(input: &Input) -> Arc<CValue> {
    match input {
        Input::Source { dialect, bytes } => CValue::object([
            ("kind", CValue::string("source")),
            (
                "dialect",
                json_to_cvalue(serde_json::to_value(dialect).expect("dialect serializes")),
            ),
            (
                "bytes",
                CValue::array(
                    bytes
                        .iter()
                        .map(|byte| CValue::integer(i128::from(*byte)))
                        .collect(),
                ),
            ),
        ]),
        Input::Spec(value) => CValue::object([
            ("kind", CValue::string("spec")),
            ("value", json_to_cvalue(value.clone())),
        ]),
        Input::Claim(claim) => CValue::object([
            ("kind", CValue::string("claim")),
            ("claim", domain_claim_to_value(claim)),
        ]),
        Input::Truth(truth) => CValue::object([
            ("kind", CValue::string("truth")),
            ("claim", domain_claim_to_value(truth.claim())),
        ]),
        Input::Refutation(refutation) => CValue::object([
            ("kind", CValue::string("refutation")),
            ("claim", domain_claim_to_value(refutation.claim())),
        ]),
        Input::Term(term) => CValue::object([
            ("kind", CValue::string("term")),
            (
                "term",
                json_to_cvalue(serde_json::to_value(term).expect("term serializes")),
            ),
        ]),
        Input::Path(path) => CValue::object([
            ("kind", CValue::string("path")),
            ("path", path_to_value(path.as_ref())),
        ]),
    }
}

fn path_to_value(path: &Path) -> Arc<CValue> {
    let mut steps: Vec<&PathAlgebra> = path.algebra.iter().collect();
    steps.sort_by(|left, right| left.name.cmp(&right.name));
    CValue::array(steps.into_iter().map(path_algebra_to_value).collect())
}

fn path_algebra_to_value(step: &PathAlgebra) -> Arc<CValue> {
    let mut depends_on = step.depends_on.clone();
    depends_on.sort();
    depends_on.dedup();
    let mut inputs = step.inputs.clone();
    inputs.sort();
    inputs.dedup();
    let mut fields = vec![
        (
            "inputs",
            CValue::array(
                inputs
                    .into_iter()
                    .map(|cid| CValue::string(cid.as_str().to_string()))
                    .collect(),
            ),
        ),
        ("kit", CValue::string(step.kit.clone())),
        ("name", CValue::string(step.name.clone())),
        (
            "dependsOn",
            CValue::array(depends_on.into_iter().map(CValue::string).collect()),
        ),
    ];
    if !step.verb.is_default() {
        fields.push((
            "verb",
            json_to_cvalue(serde_json::to_value(step.verb).expect("verb serializes")),
        ));
    }
    CValue::object(fields)
}

fn operation_name_cid(name: &str) -> Cid {
    let value = CValue::object([
        ("kind", CValue::string("operation-name")),
        ("name", CValue::string(name.to_string())),
    ]);
    Cid::from_hash_output(blake3_512_of(encode_jcs(&value).as_bytes()))
}

#[allow(dead_code)]
fn _let_binding_from_term(name: String, bound_term: Term) -> LetBinding {
    LetBinding {
        name,
        bound_term: IrTerm::from(bound_term),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cid(hex_digit: char) -> Cid {
        Cid::parse(format!("blake3-512:{}", hex_digit.to_string().repeat(128))).unwrap()
    }

    fn op(hex_digit: char, name: &str, args: Vec<Term>) -> Term {
        Term::Op {
            op_cid: cid(hex_digit),
            name: name.to_string(),
            args,
        }
    }

    fn const_term() -> Term {
        Term::Const {
            value: serde_json::json!(0),
            sort: any_sort(),
        }
    }

    fn var(name: &str) -> Term {
        Term::Var {
            name: name.to_string(),
        }
    }

    fn claim_with_payload(payload: Option<Term>) -> DomainClaim {
        let output_cid = cid('a');
        DomainClaim {
            domain: DomainKind::Other("test".to_string()),
            contract: memento_from_parts(
                "test::payload-cache".to_string(),
                vec!["x".to_string()],
                vec![any_sort()],
                any_sort(),
                formula_true(),
                formula_true(),
                Some(output_cid.as_str().to_string()),
            ),
            artifacts: vec![output_cid.clone()],
            from: vec![cid('b')],
            premises: vec![],
            to: output_cid,
            witness: None,
            payload,
            verdict: Verdict::Unresolved,
            attestation: None,
        }
    }

    #[test]
    fn domain_claim_identity_ignores_materialized_payload_cache() {
        let with_payload = claim_with_payload(Some(Term::Const {
            value: serde_json::json!({"large": "response"}),
            sort: any_sort(),
        }));
        let without_payload = claim_with_payload(None);

        assert_eq!(
            with_payload.canonical_bytes(),
            without_payload.canonical_bytes()
        );
        assert_eq!(with_payload.cid(), without_payload.cid());
    }

    #[test]
    fn walk_visits_root_op_first() {
        let term = op('1', "root", vec![]);
        let nodes: Vec<_> = term.walk().collect();

        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].op_cid, &cid('1'));
        assert_eq!(nodes[0].op_name, "root");
        assert!(nodes[0].term_position.is_empty());
    }

    #[test]
    fn walk_skips_const_leaves() {
        let term = op('1', "root", vec![const_term(), const_term()]);
        let nodes: Vec<_> = term.walk().collect();

        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].op_name, "root");
    }

    #[test]
    fn walk_skips_var_leaves() {
        let term = op('1', "root", vec![var("left"), var("right")]);
        let nodes: Vec<_> = term.walk().collect();

        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].op_name, "root");
    }

    #[test]
    fn walk_yields_nested_ops_preorder() {
        let term = op(
            '1',
            "root",
            vec![op('2', "left", vec![]), op('3', "right", vec![])],
        );
        let names: Vec<_> = term.walk().map(|node| node.op_name).collect();

        assert_eq!(names, vec!["root", "left", "right"]);
    }

    #[test]
    fn walk_yields_correct_slot_paths() {
        let term = op(
            '1',
            "root",
            vec![op('2', "left", vec![]), op('3', "right", vec![])],
        );
        let nodes: Vec<_> = term.walk().collect();

        assert_eq!(nodes[0].op_cid, &cid('1'));
        assert_eq!(nodes[0].term_position, Vec::<usize>::new());
        assert_eq!(nodes[1].op_cid, &cid('2'));
        assert_eq!(nodes[1].term_position, vec![0]);
        assert_eq!(nodes[2].op_cid, &cid('3'));
        assert_eq!(nodes[2].term_position, vec![1]);
    }

    #[test]
    fn walk_handles_deep_nesting() {
        let term = op(
            '1',
            "root",
            vec![op('2', "middle", vec![op('3', "deep", vec![])])],
        );
        let nodes: Vec<_> = term.walk().collect();

        assert_eq!(nodes[2].op_name, "deep");
        assert_eq!(nodes[2].term_position, vec![0, 0]);
    }

    #[test]
    fn walk_yields_zero_for_const_only_term() {
        let term = const_term();
        let nodes: Vec<_> = term.walk().collect();

        assert!(nodes.is_empty());
    }
}
