// SPDX-License-Identifier: MIT OR Apache-2.0
//
// GENERATED FILE: DO NOT EDIT
// Source: protocol/sugar-ir.cddl
// Generator: sugar-ir-codegen

use serde::{Deserialize, Serialize};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};

// Manual extension (not codegen): CLI-side canonicalization of ProofIR for
// behavior identity. The kits emit ProofIR; the substrate computes the canonical
// form before hashing. Alpha + pure-let normal form, solver-free.
pub mod canonicalize;
pub mod membership;
pub use canonicalize::{canonicalize_formula, canonicalize_property};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Declaration {
    #[serde(rename = "contract")]
    Contract {
        name: String,
        #[serde(rename = "outBinding")]
        out_binding: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        pre: Option<IrFormula>,
        #[serde(skip_serializing_if = "Option::is_none")]
        post: Option<IrFormula>,
        #[serde(skip_serializing_if = "Option::is_none")]
        inv: Option<IrFormula>,
    },
    #[serde(rename = "bridge")]
    Bridge {
        name: String,
        #[serde(rename = "sourceSymbol")]
        source_symbol: String,
        #[serde(rename = "sourceLayer")]
        source_layer: String,
        #[serde(rename = "sourceContractCid")]
        source_contract_cid: String,
        #[serde(rename = "targetContractCid")]
        target_contract_cid: String,
        #[serde(rename = "targetProofCid")]
        target_proof_cid: String,
        #[serde(rename = "targetLayer")]
        target_layer: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        notes: Option<String>,
    },
}

pub type Document = Vec<Declaration>;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LetBinding {
    pub name: String,
    #[serde(rename = "boundTerm")]
    pub bound_term: IrTerm,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PrimitiveSort {
    pub kind: String,
    pub name: PrimitiveSortName,
}

pub type PrimitiveSortName = String;
// Known values for PrimitiveSortName:
//   "Int"
//   "Real"
//   "Bool"
//   "String"

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgeHeaderV14 {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    pub kind: String,
    pub name: String,
    #[serde(rename = "sourceSymbol")]
    pub source_symbol: String,
    #[serde(rename = "sourceLayer")]
    pub source_layer: String,
    #[serde(rename = "sourceContractCid")]
    pub source_contract_cid: String,
    pub target: BridgeTarget,
}

pub type AtomicPredicateName = String;
// Known values for AtomicPredicateName:
//   "="
//   "≠"
//   "<"
//   "≤"
//   ">"
//   "≥"
//   "true"
//   "false"
//   "bvult"
//   "bvule"
//   "bvugt"
//   "bvuge"
//   "bvslt"
//   "bvsle"
//   "bvsgt"
//   "bvsge"

pub type QuantifierKind = String;
// Known values for QuantifierKind:
//   "forall"
//   "exists"

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceCertificate {
    pub tool: String,
    pub version: String,
    #[serde(rename = "formulaHash")]
    pub formula_hash: String,
    #[serde(rename = "proofData")]
    pub proof_data: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgeMetadataV14 {
    #[serde(rename = "targetWitnessCid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_witness_cid: Option<String>,
    #[serde(rename = "targetBinaryCid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_binary_cid: Option<String>,
    #[serde(rename = "targetLayer")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_layer: Option<String>,
    #[serde(rename = "targetContractSetCid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_contract_set_cid: Option<String>,
    #[serde(rename = "producedBy")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub produced_by: Option<String>,
    #[serde(rename = "producedAt")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub produced_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum BridgeTarget {
    #[serde(rename = "contract")]
    Contract { cid: String },
    #[serde(rename = "contractSet")]
    ContractSet { cid: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceTerm {
    pub kind: String,
    #[serde(rename = "proofType")]
    pub proof_type: ProofType,
    pub certificate: EvidenceCertificate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgeEnvelope {
    pub signer: String,
    #[serde(rename = "declaredAt")]
    pub declared_at: String,
    pub signature: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum Value {
    #[serde(rename = "text")]
    Text,
    #[serde(rename = "number")]
    Number,
    #[serde(rename = "bool")]
    Bool,
    #[serde(rename = "null")]
    Null,
}

pub type ProofType = String;

// NOTE: The `Sort` enum below has been MANUALLY extended beyond the
// codegen output to add Function + Dependent variants per the v1.5.0
// grammar grow (issue #330, rust gap from PR #361), and Region per #401
// (v1.6.0 grammar grow).
// The codegen (`sugar-ir-codegen`) currently only emits the Primitive
// arm even though the CDDL spec defines a 7-way union. If you regenerate
// this file via `cargo run -p sugar-ir-codegen`, you WILL clobber the
// manual extensions. Re-apply them from this comment block down through
// the closing `}` of the `Sort` enum.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Sort {
    #[serde(rename = "primitive")]
    Primitive { name: PrimitiveSortName },
    #[serde(rename = "function")]
    Function {
        args: Vec<Sort>,
        #[serde(rename = "return")]
        ret: Box<Sort>,
    },
    #[serde(rename = "dependent")]
    Dependent {
        name: String,
        #[serde(rename = "indexVar")]
        index_var: String,
        #[serde(rename = "indexSort")]
        index_sort: Box<Sort>,
    },
    /// Lifetime / region sort for borrow-checker lifetime variables.
    /// `name` is the lifetime name, e.g. `"'a"`, `"'static"`, or a fresh
    /// region variable like `"'r0"` emitted by a source-level borrow analysis.
    ///
    /// ## Semantics
    ///
    /// Region sorts are pre-resolved in composition and MUST NOT reach the
    /// SMT or Coq backends. They exist in the IR as opaque placeholders so
    /// that lifted Rust functions with lifetime parameters can be given
    /// well-typed contracts without silently collapsing lifetimes into a
    /// primitive sort (which would break CID stability and sort-collapse
    /// invariants from #384 A.1).
    ///
    /// JCS-canonical key order: `kind`, `name` (alphabetical).
    /// Prerequisite for #384 C.9 (Outlives predicates).
    #[serde(rename = "region")]
    Region { name: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgeDeclarationV14 {
    pub envelope: BridgeEnvelope,
    pub header: BridgeHeaderV14,
    pub metadata: BridgeMetadataV14,
}

// ============================================================
// MANUAL EXTENSION BLOCK -- sort morphism memento (issue #794)
// Source of truth:
//   protocol/specs/2026-05-13-sort-morphism-memento.md §1
//
// This substrate type records transport between two pinned sort CIDs under
// pinned language-signature CIDs. It deliberately carries no language-specific
// conversion runtime.
//
// Locked JCS key order:
//   outer object: envelope, header, metadata
//   envelope: declaredAt, signature, signer
//   header: cid, direction, kind, precision_loss, range_loss,
//     representation_constraints, runtime_guards, schemaVersion,
//     source_language_signature_cid, source_sort_cid,
//     target_language_signature_cid, target_sort_cid
//   metadata: note (omitted when absent), source_url (omitted when absent)
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SortMorphismMemento {
    pub envelope: SortMorphismEnvelope,
    pub header: SortMorphismHeader,
    pub metadata: SortMorphismMetadata,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SortMorphismEnvelope {
    #[serde(rename = "declaredAt")]
    pub declared_at: String,
    pub signature: String,
    pub signer: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SortMorphismHeader {
    pub cid: String,
    pub direction: MorphismDirection,
    pub kind: String,
    #[serde(rename = "precision_loss")]
    pub precision_loss: PrecisionLoss,
    #[serde(rename = "range_loss")]
    pub range_loss: RangeLoss,
    #[serde(rename = "representation_constraints")]
    pub representation_constraints: Vec<RepresentationConstraint>,
    #[serde(rename = "runtime_guards")]
    pub runtime_guards: Vec<RuntimeGuard>,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "source_language_signature_cid")]
    pub source_language_signature_cid: String,
    #[serde(rename = "source_sort_cid")]
    pub source_sort_cid: String,
    #[serde(rename = "target_language_signature_cid")]
    pub target_language_signature_cid: String,
    #[serde(rename = "target_sort_cid")]
    pub target_sort_cid: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SortMorphismMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(rename = "source_url")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_url: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum MorphismDirection {
    #[serde(rename = "bidirectional")]
    Bidirectional,
    #[serde(rename = "left-to-right")]
    LeftToRight,
    #[serde(rename = "right-to-left")]
    RightToLeft,
}

pub type PrecisionLoss = String;
pub type RangeLoss = String;
pub type RuntimeFailureMode = String;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RepresentationConstraint {
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub param: Option<serde_json::Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeGuard {
    #[serde(rename = "failure_mode")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub failure_mode: Option<RuntimeFailureMode>,
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub predicate: Option<String>,
}

// ============================================================
// End manual extension block -- sort morphism memento (issue #794)
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum IrTerm {
    #[serde(rename = "var")]
    Var { name: String },
    #[serde(rename = "const")]
    Const {
        value: serde_json::Value,
        sort: Sort,
    },
    #[serde(rename = "ctor")]
    Ctor { name: String, args: Vec<IrTerm> },
    #[serde(rename = "lambda")]
    Lambda {
        #[serde(rename = "paramName")]
        param_name: String,
        #[serde(rename = "paramSort")]
        param_sort: Sort,
        body: Box<IrTerm>,
    },
    #[serde(rename = "let")]
    Let {
        bindings: Vec<LetBinding>,
        body: Box<IrTerm>,
    },
}

// NOTE: The `IrFormula` enum below has been MANUALLY extended beyond the
// codegen output to add the `Substitute`, `Apply`, and `DivergenceBetween`
// variants per the wp-as-formula spec
// (protocol/specs/2026-05-13-wp-as-formula.md §2.3) and the platform
// semantic tag ruling
// (docs/plans/2026-05-16-platform-semantic-tag-schema-ruling.md §2).
// `Substitute` and `Apply` are the "wp-rule schema" nodes: they appear inside a
// `wp_rule` term and are reduced away by `libsugar::wp` before any
// formula reaches a solver backend. The codegen (`sugar-ir-codegen`)
// currently emits only the generated union without these arms; if you
// regenerate this file via `cargo run -p sugar-ir-codegen`, you WILL
// clobber the manual extensions. Re-apply them from this comment block
// through the closing `}` of the `IrFormula` enum, keeping the CDDL
// (`protocol/sugar-ir.cddl`) as the source of truth.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum IrFormula {
    #[serde(rename = "atomic")]
    Atomic {
        name: AtomicPredicateName,
        args: Vec<IrTerm>,
    },
    #[serde(rename = "and")]
    And { operands: Vec<IrFormula> },
    #[serde(rename = "or")]
    Or { operands: Vec<IrFormula> },
    #[serde(rename = "not")]
    Not { operands: Vec<IrFormula> },
    #[serde(rename = "implies")]
    Implies { operands: Vec<IrFormula> },
    #[serde(rename = "forall")]
    Forall {
        name: String,
        sort: Sort,
        body: Box<IrFormula>,
    },
    #[serde(rename = "exists")]
    Exists {
        name: String,
        sort: Sort,
        body: Box<IrFormula>,
    },
    #[serde(rename = "choice")]
    Choice {
        #[serde(rename = "varName")]
        var_name: String,
        sort: Sort,
        body: Box<IrFormula>,
    },
    /// `substitute` - an explicit, capture-avoiding, single-variable
    /// substitution on a formula: `target` with `var` replaced by `term`.
    /// This is `Q[result_value := value_expr]` written as a node. It is
    /// needed because in a `wp_rule` schema the `target` is the
    /// postcondition meta-variable `Q`, not yet known; once `target` is
    /// ground the node can always be eliminated by performing the
    /// substitution. JCS-canonical key order: `kind`, `target`, `term`,
    /// `var` (alphabetical, with `kind` first by the tag convention).
    #[serde(rename = "substitute")]
    Substitute {
        target: Box<IrFormula>,
        term: IrTerm,
        var: String,
    },
    /// `apply` - application of a slot-transformer meta-variable
    /// (`wp_<slot>`) to one formula argument: `apply(wp_<slot>, X)` is
    /// "the weakest precondition of the term plugged into slot `<slot>`,
    /// with respect to X." When the evaluator instantiates `wp_<slot>`
    /// with the actual slot transformer the node reduces to a concrete
    /// formula. `fn` is the meta-variable name (`"wp_then_branch"`,
    /// `"wp_body"`, ...); `args` carries the single formula argument
    /// (a one-element list for forward compatibility). JCS-canonical key
    /// order: `args`, `fn`, `kind`.
    #[serde(rename = "apply")]
    Apply {
        args: Vec<IrFormula>,
        #[serde(rename = "fn")]
        r#fn: String,
    },
    /// `divergence-between` - characterizes a platform semantic difference
    /// by carrying the source and target formulas being compared. JCS key
    /// order: `kind`, `source`, `target`.
    #[serde(rename = "divergence-between")]
    DivergenceBetween {
        source: Box<IrFormula>,
        target: Box<IrFormula>,
    },
}

pub type ConnectiveKind = String;
// Known values for ConnectiveKind:
//   "and"
//   "or"
//   "not"
//   "implies"

pub type Term = IrTerm;
pub type Formula = IrFormula;

// ============================================================
// NOTE: Manual extension block -- abstraction layer (issue #71)
// ============================================================
//
// The types below are manually added per the convention established in
// the Sort enum above. They implement the CDDL defined in
// protocol/sugar-ir.cddl §"Abstraction layer" and are sourced from
// protocol/specs/2026-05-15-concept-hub-abstraction-layer.md §2.1-§2.4.
//
// DO NOT regenerate this file via `cargo run -p sugar-ir-codegen`
// without re-applying this block. See the Sort enum NOTE above.
//
// Key-order rule: struct field names mirror the CDDL key names exactly.
// serde_json with the default BTreeMap representation emits keys in
// lexicographic order (JCS canonical order). Fields that are
// `skip_serializing_if = "Option::is_none"` are OMITTED when None;
// the JCS bytes must match `serde_json::to_value` output exactly.
//
// "effects" is ALWAYS serialized (never skipped) even when empty,
// because it is a required field in the CDDL schema.

use std::collections::BTreeMap;

/// A map from loss-dimension name to an `ir-formula` characterizing that
/// dimension's divergence. An absent key means "no loss in that dimension."
///
/// Dimension names (§2.4 of the spec):
///   - "domain_narrowing"    -- inputs the realization cannot accept
///   - "effect_divergence"   -- inputs where observable effect set differs
///   - "structural_divergence" -- how far surface form diverges from the abstraction
///                               (always non-empty for abstraction realizations)
///   - "ub_introduction"     -- inputs where UB is introduced
///   - "value_divergence"    -- inputs where result VALUE differs
///
/// `structural_divergence` is a successor-mint addition per LSP §4.4 relative
/// to the #616 schema. Existing #616 loss-records without it read as
/// structural_divergence = None (formula = ∅). CIDs of previously-minted
/// mementos are NOT affected.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct LossRecord(pub BTreeMap<String, IrFormula>);

// ============================================================
// Manual extension block -- platform semantic tag mementos
// Source of truth:
//   docs/plans/2026-05-16-platform-semantic-tag-schema-ruling.md
//   docs/plans/2026-05-16-platform-semantics-via-loss-records.md
// ============================================================

/// A kit-minted value for one open platform semantic dimension.
///
/// Locked JCS key order:
///   cid, compare_to, dimension_name, kind, kit_cid, schemaVersion, value_name.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DimensionValueMemento {
    /// DERIVED: BLAKE3-512 over JCS(memento) with `cid` elided.
    pub cid: Cid,
    pub compare_to: IrFormula,
    #[serde(rename = "dimension_name")]
    pub dimension_name: String,
    pub kind: String,
    #[serde(rename = "kit_cid")]
    pub kit_cid: Cid,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "value_name")]
    pub value_name: String,
}

impl DimensionValueMemento {
    pub const KIND: &'static str = "platform-dimension-value";
    pub const SCHEMA_VERSION: &'static str = "1.0.0";

    pub fn new(
        kit_cid: Cid,
        dimension_name: String,
        value_name: String,
        compare_to: IrFormula,
    ) -> Self {
        let mut value = Self {
            cid: String::new(),
            compare_to,
            dimension_name,
            kind: Self::KIND.to_string(),
            kit_cid,
            schema_version: Self::SCHEMA_VERSION.to_string(),
            value_name,
        };
        value.cid = value.recompute_cid();
        value
    }

    pub fn to_jcs_string(&self) -> String {
        platform_semantic_jcs_string(self)
    }

    pub fn recompute_cid(&self) -> Cid {
        platform_semantic_cid_without_keys(self, &["cid", "kit_cid"])
    }
}

/// A flat per-kit, per-op platform semantic tag.
///
/// The `dimensions` map is intentionally open-keyed. Keys are kit-minted
/// dimension names and values are CIDs of `DimensionValueMemento` objects.
///
/// Locked JCS key order: cid, dimensions, kind, kit_cid, op_cid, schemaVersion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlatformSemanticTag {
    /// DERIVED: BLAKE3-512 over JCS(memento) with `cid` elided.
    pub cid: Cid,
    pub dimensions: BTreeMap<String, Cid>,
    pub kind: String,
    #[serde(rename = "kit_cid")]
    pub kit_cid: Cid,
    #[serde(rename = "op_cid")]
    pub op_cid: Cid,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
}

impl PlatformSemanticTag {
    pub const KIND: &'static str = "platform-semantic-tag";
    pub const SCHEMA_VERSION: &'static str = "1.0.0";

    pub fn new(kit_cid: Cid, op_cid: Cid, dimensions: BTreeMap<String, Cid>) -> Self {
        let mut tag = Self {
            cid: String::new(),
            dimensions,
            kind: Self::KIND.to_string(),
            kit_cid,
            op_cid,
            schema_version: Self::SCHEMA_VERSION.to_string(),
        };
        tag.cid = tag.recompute_cid();
        tag
    }

    pub fn to_jcs_string(&self) -> String {
        platform_semantic_jcs_string(self)
    }

    pub fn recompute_cid(&self) -> Cid {
        platform_semantic_cid_without_keys(self, &["cid", "kit_cid"])
    }
}

/// A kit-minted literal encoding declaration.
///
/// For a given (language, substrate-canonical sort), declares the concrete
/// `concept:literal { value, sort }` node the kit's bind-lift emits for a
/// representative source-language literal of that sort. Consumers can run the
/// kit's lift over `source_example` and assert the resulting term_shape contains an equivalent
/// `expected_term_shape_node`.
///
/// Locked JCS key order:
///   cid, expected_term_shape_node, kind, kit_cid, language,
///   schemaVersion, sort_cid, source_example.
///
/// Per the #1260 envelope-violation fix, `cid` and `kit_cid` are elided
/// from the content-hash; two kits with byte-identical (language, sort_cid,
/// source_example, expected_term_shape_node) tuples therefore produce
/// byte-identical CIDs.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LiteralEncodingMemento {
    /// DERIVED: BLAKE3-512 over JCS(memento) with `cid` + `kit_cid` elided.
    pub cid: Cid,
    #[serde(rename = "expected_term_shape_node")]
    pub expected_term_shape_node: ExpectedLiteralNode,
    pub kind: String,
    #[serde(rename = "kit_cid")]
    pub kit_cid: Cid,
    pub language: String,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "sort_cid")]
    pub sort_cid: Cid,
    #[serde(rename = "source_example")]
    pub source_example: String,
}

/// The literal leaf shape the kit's bind-lift is expected to emit
/// for the corresponding source_example.
///
/// Locked JCS key order: op_cid, sort, value.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExpectedLiteralNode {
    pub op_cid: String,
    pub sort: Cid,
    pub value: serde_json::Value,
}

impl LiteralEncodingMemento {
    pub const KIND: &'static str = "literal-encoding-memento";
    pub const SCHEMA_VERSION: &'static str = "1.0.0";
    pub const LITERAL_OP_NAME: &'static str = "concept:literal";

    pub fn new(
        kit_cid: Cid,
        language: String,
        sort_cid: Cid,
        source_example: String,
        decoded_value: serde_json::Value,
    ) -> Self {
        let expected_term_shape_node = ExpectedLiteralNode {
            op_cid: local_op_cid(Self::LITERAL_OP_NAME),
            sort: sort_cid.clone(),
            value: decoded_value,
        };
        let mut memento = Self {
            cid: String::new(),
            expected_term_shape_node,
            kind: Self::KIND.to_string(),
            kit_cid,
            language,
            schema_version: Self::SCHEMA_VERSION.to_string(),
            sort_cid,
            source_example,
        };
        memento.cid = memento.recompute_cid();
        memento
    }

    pub fn to_jcs_string(&self) -> String {
        platform_semantic_jcs_string(self)
    }

    pub fn recompute_cid(&self) -> Cid {
        platform_semantic_cid_without_keys(self, &["cid", "kit_cid"])
    }
}

fn local_op_cid(name: &str) -> String {
    let bare = name.strip_prefix("concept:").unwrap_or(name);
    let shape = CValue::object(vec![
        (
            "kind".to_string(),
            CValue::string("local-operator".to_string()),
        ),
        ("name".to_string(), CValue::string(bare.to_string())),
    ]);
    blake3_512_of(encode_jcs(&shape).as_bytes())
}

fn platform_semantic_jcs_string<T: Serialize>(value: &T) -> String {
    let json = serde_json::to_value(value).expect("platform semantic memento serializes to JSON");
    let canonical = canonical_value_from_json(json);
    sugar_canonicalizer::encode_jcs(&canonical)
}

fn platform_semantic_cid_without_keys<T: Serialize>(value: &T, keys: &[&str]) -> Cid {
    let mut json =
        serde_json::to_value(value).expect("platform semantic memento serializes to JSON");
    let serde_json::Value::Object(ref mut map) = json else {
        panic!("platform semantic memento did not serialize as object");
    };
    for key in keys {
        map.remove(*key);
    }
    let canonical = canonical_value_from_json(json);
    let jcs = sugar_canonicalizer::encode_jcs(&canonical);
    sugar_canonicalizer::blake3_512_of(jcs.as_bytes())
}

// ============================================================
// End manual extension block -- platform semantic tag mementos
// ============================================================

// ============================================================

// ============================================================
// Discharge verdict (the trichotomy carrier).
//
// The concept-site binding layer (ConceptSiteMemento and its code-site /
// witness-ref / provenance types) was removed with the concept hub: there
// is no cross-language transport and no binding of a callsite to a hub
// concept; contracts meet at the callsite by EUF. The Discharge verdict
// type survives because it is the substrate's trichotomy carrier
// {exact, loudly-bounded-lossy, refuse}, used throughout verification.
// ============================================================

/// The discharge verdict for a binding. Exactly one of three.
///
/// Per the spec §2 trichotomy and §1.2 verdict-consistency table.
/// Silent contract-dropping is NOT in the substrate's vocabulary.
///
/// This type is the serde wire shape only. Verdict-consistency invariants
/// are enforced by producers and validators, not by this struct.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Discharge {
    /// The discharge method: "wp" | "witness" | "wp+witness".
    pub method: String,
    /// Optional refusal reason. Serialized when `Some`; omitted when `None`.
    /// The spec requires producers and validators to use this for `refuse`.
    #[serde(rename = "refusal_reason")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refusal_reason: Option<String>,
    /// "exact" | "loudly-bounded-lossy" | "refuse".
    pub verdict: String,
    /// Optional CID of a MorphismDischargeReceipt. Serialized when `Some`;
    /// omitted when `None`. The spec requires producers and validators to omit
    /// this for `refuse`.
    #[serde(rename = "discharge_receipt_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub discharge_receipt_cid: Option<String>,
    /// Per the 2026-05-15 §2.4 five-dimension loss-record. This field is
    /// always present in the wire struct. An empty map means "no loss in any
    /// dimension"; the spec requires that shape for `exact`.
    #[serde(rename = "loss_record")]
    pub loss_record: LossRecord,
}

// ============================================================
// End manual extension block -- concept-site layer (PR-A)
// ============================================================

// ============================================================
// The parametric realization mementos (two-stage realization-across-
// languages: catalog template + per-site selection receipt) were removed
// with the concept hub -- there is no realization-across-languages; we
// meet contracts at the callsite by EUF. The `Cid` alias survives because
// it is the crate-wide content-address type used by many mementos.
// ============================================================

pub type Cid = String;

// ============================================================
// Manual extension: compound-contract layer (PR-A of compound spec)
// Source of truth:
//   protocol/specs/2026-05-13-compound-contract-memento.md §1, §2, §3
//   AMENDS protocol/specs/2026-05-12-concept-site-memento.md §1.1 and §5.4
//
// This block adds the EvidenceMemento and CompoundContractMemento
// substrate primitives. The compound is the new convergence point for
// every contract-source the substrate can lift from a user's codebase:
// annotations, test assertions, type signatures, docstrings, loop
// invariants, implicit-effect call-sites, native contract surfaces
// (JML / Zod / Spring / pydantic / OpenAPI), structurally synthesized
// wp_rules, empirical witnesses, and (future) review comments.
//
// Trichotomy is enforced at TWO levels:
//   * per-evidence: each evidence's discharge verdict against the
//     concept's wp_rule (recorded in the discharge receipt, PR-F).
//   * compound: derived from per-evidence verdicts under the recorded
//     aggregation_strategy (§2 of the spec).
//
// v0 wires only `AggregationStrategy::Conjunction`; the other two
// strategies are spec'd but `unimplemented!` here. The Rust enum carries
// all three variants so downstream callers can name them; only the
// conjunction discharge path is functional in v0.
//
// CID-determining bytes for both mementos are JCS(header) with `cid`
// elided; that JCS encoder lives in sugar-claim-envelope. Byte-pin
// tests for the compound CID belong there; THIS crate carries serde
// round-trip tests only.
// ============================================================

/// One point inside a source span: 1-based line, 0-indexed col (UTF-8 bytes; spec §1.1).
///
/// Locked JCS key order: col, line.
///
/// Note: line/col (not byte offsets) -- evidence often comes from
/// docstrings, test sources, or native contract surfaces where byte
/// offsets are unstable across re-formatting. This diverges from
/// `CodeSiteSpan` (which uses byte offsets, anchored at the function
/// boundary where formatters do not move text); see the compound spec
/// §1.1 for rationale.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceLocatorPoint {
    pub col: u32,
    pub line: u32,
}

/// A span inside a source artifact, as a (start, end) pair of
/// `SourceLocatorPoint`s.
///
/// Locked JCS key order: end, start.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceLocatorSpan {
    pub end: SourceLocatorPoint,
    pub start: SourceLocatorPoint,
}

/// Provenance for one piece of evidence: which source artifact it was
/// extracted from, and where inside that artifact.
///
/// Locked JCS key order: source_cid, span.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceLocator {
    #[serde(rename = "source_cid")]
    pub source_cid: String,
    pub span: SourceLocatorSpan,
}

/// The kind of contract-evidence source. Open enum; unknown labels
/// MUST be accepted at shape level (per spec §5.1) and are carried as
/// `Other(String)`.
///
/// Wire format: a bare JSON string (e.g., `"test-assertion"`).
///
/// Mirrors the `DivergentSemanticsTag` pattern: `#[serde(from = "String",
/// into = "String")]` with explicit kebab-case mapping. (Using
/// `#[serde(untagged)]` with all-unit variants silently ignores
/// `#[serde(rename)]` and serializes every unit variant as `null`, so we
/// must go through `String`.)
///
/// The ten canonical labels are documented in spec §10. `Other(String)`
/// is the open-extension placeholder; downstream consumers decide how
/// to treat unknown kinds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(from = "String", into = "String")]
pub enum SourceKind {
    Annotation,
    TestAssertion,
    TypeSignature,
    Docstring,
    LoopInvariant,
    ImplicitEffect,
    NativeSurface,
    StructuralSynthesis,
    EmpiricalWitness,
    ReviewComment,
    Other(String),
}

impl From<String> for SourceKind {
    fn from(s: String) -> Self {
        match s.as_str() {
            "annotation" => SourceKind::Annotation,
            "test-assertion" => SourceKind::TestAssertion,
            "type-signature" => SourceKind::TypeSignature,
            "docstring" => SourceKind::Docstring,
            "loop-invariant" => SourceKind::LoopInvariant,
            "implicit-effect" => SourceKind::ImplicitEffect,
            "native-surface" => SourceKind::NativeSurface,
            "structural-synthesis" => SourceKind::StructuralSynthesis,
            "empirical-witness" => SourceKind::EmpiricalWitness,
            "review-comment" => SourceKind::ReviewComment,
            _ => SourceKind::Other(s),
        }
    }
}

impl From<SourceKind> for String {
    fn from(k: SourceKind) -> String {
        match k {
            SourceKind::Annotation => "annotation".to_string(),
            SourceKind::TestAssertion => "test-assertion".to_string(),
            SourceKind::TypeSignature => "type-signature".to_string(),
            SourceKind::Docstring => "docstring".to_string(),
            SourceKind::LoopInvariant => "loop-invariant".to_string(),
            SourceKind::ImplicitEffect => "implicit-effect".to_string(),
            SourceKind::NativeSurface => "native-surface".to_string(),
            SourceKind::StructuralSynthesis => "structural-synthesis".to_string(),
            SourceKind::EmpiricalWitness => "empirical-witness".to_string(),
            SourceKind::ReviewComment => "review-comment".to_string(),
            SourceKind::Other(s) => s,
        }
    }
}

/// How per-evidence verdicts compose into the compound's verdict.
///
/// v0 NORMATIVE: only `Conjunction` is wired in the discharger
/// (PR-F). `BestConfidence` and `LoudlyBoundedDisjunction` are spec'd
/// (compound spec §2.2 and §2.3) and round-trip serde here, but a
/// discharger that encounters them MUST `unimplemented!` until PR-F+1.
///
/// Wire format: a bare JSON string. Same `from/into String` pattern as
/// `SourceKind`. `Other(String)` is the open-extension placeholder.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(from = "String", into = "String")]
pub enum AggregationStrategy {
    Conjunction,
    BestConfidence,
    LoudlyBoundedDisjunction,
    Other(String),
}

impl From<String> for AggregationStrategy {
    fn from(s: String) -> Self {
        match s.as_str() {
            "conjunction" => AggregationStrategy::Conjunction,
            "best-confidence" => AggregationStrategy::BestConfidence,
            "loudly-bounded-disjunction" => AggregationStrategy::LoudlyBoundedDisjunction,
            _ => AggregationStrategy::Other(s),
        }
    }
}

impl From<AggregationStrategy> for String {
    fn from(s: AggregationStrategy) -> String {
        match s {
            AggregationStrategy::Conjunction => "conjunction".to_string(),
            AggregationStrategy::BestConfidence => "best-confidence".to_string(),
            AggregationStrategy::LoudlyBoundedDisjunction => {
                "loudly-bounded-disjunction".to_string()
            }
            AggregationStrategy::Other(s) => s,
        }
    }
}

/// One piece of contract evidence from one source. Content-addressed.
///
/// Source of truth: protocol/specs/2026-05-13-compound-contract-memento.md §1.1
///
/// This is the `header` layer per the substrate envelope/header/metadata
/// layering (`2026-05-03-substrate-layers-envelope-header-body.md`); the
/// envelope (`declaredAt`, `signature`, `signer`) and metadata (`note`)
/// are carried by the wrapping envelope structures in
/// `sugar-claim-envelope`.
///
/// Locked JCS key order (alphabetical):
///   cid, confidence_basis_points, extension_fields, kind, lifter_cid,
///   predicate, schemaVersion, source_kind, source_locator.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceMemento {
    /// DERIVED: BLAKE3-512 over JCS(header) with `cid` elided.
    pub cid: String,
    /// Lifter's prior on this evidence (0..10000, basis points).
    /// 10000 for static-derived (annotations, type signatures); lower
    /// for grammar-extracted or sampled (docstrings, empirical witnesses).
    #[serde(rename = "confidence_basis_points")]
    pub confidence_basis_points: u16,
    /// Per-kind structured metadata. Keys and values participate in
    /// the CID (open-extension under deterministic addressing).
    #[serde(rename = "extension_fields")]
    pub extension_fields: BTreeMap<String, serde_json::Value>,
    /// MUST be "evidence".
    pub kind: String,
    /// CID of the lifter binary or rule-set that emitted this evidence.
    /// Reserved sentinel `blake3-512:` ++ 128 hex `0`s for the
    /// backward-compat auto-promotion path (compound spec §4.4).
    /// All-zeros is provably not a real BLAKE3-512 output (P ≈ 2^-512).
    /// Pass-1 CID validation accepts it without a special-case exception.
    #[serde(rename = "lifter_cid")]
    pub lifter_cid: String,
    /// The asserted predicate (an `IrFormula`).
    pub predicate: IrFormula,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    /// The kind of source this evidence was extracted from.
    #[serde(rename = "source_kind")]
    pub source_kind: SourceKind,
    /// Where this evidence was extracted from.
    #[serde(rename = "source_locator")]
    pub source_locator: SourceLocator,
}

/// A reference to an `EvidenceMemento` with a per-compound weight.
///
/// Under `Conjunction` (v0) the weight is informational. Under the
/// spec'd strategies (`BestConfidence`, `LoudlyBoundedDisjunction`) it
/// is consulted during verdict derivation. The weight participates in
/// the compound's CID either way (different weights = different
/// compound bytes = different CID).
///
/// Locked JCS key order: evidence_cid, weight_basis_points.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceRef {
    #[serde(rename = "evidence_cid")]
    pub evidence_cid: String,
    #[serde(rename = "weight_basis_points")]
    pub weight_basis_points: u16,
}

/// A content-addressed aggregation of `EvidenceMemento`s for one
/// function. The convergence point for every contract source the
/// substrate can lift.
///
/// Source of truth: protocol/specs/2026-05-13-compound-contract-memento.md §1.2
///
/// CID-determining: `aggregation_strategy`, `composed_post`,
/// `composed_pre`, `evidences` (sorted by evidence_cid at JCS time),
/// `function_term_cid`, `kind`, `schemaVersion`. Changing one evidence's
/// bytes rolls its CID, which rolls this compound's CID, which rolls
/// every binding citing this compound.
///
/// `composed_pre` and `composed_post` are DERIVED-AND-STORED (cached
/// truth-source duality). Validators MUST recompute under the recorded
/// strategy and reject on mismatch; that recompute requires a JCS
/// encoder and lives in sugar-claim-envelope.
///
/// Locked JCS key order (alphabetical):
///   aggregation_strategy, cid, composed_post, composed_pre, evidences,
///   function_term_cid, kind, schemaVersion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompoundContractMemento {
    /// How per-evidence verdicts compose into the compound's verdict.
    /// v0: only `Conjunction` is wired.
    #[serde(rename = "aggregation_strategy")]
    pub aggregation_strategy: AggregationStrategy,
    /// DERIVED: BLAKE3-512 over JCS(header) with `cid` elided.
    pub cid: String,
    /// DERIVED-AND-STORED: the aggregated post-condition.
    /// Validators MUST recompute and reject on mismatch.
    #[serde(rename = "composed_post")]
    pub composed_post: IrFormula,
    /// DERIVED-AND-STORED: the aggregated pre-condition.
    /// Validators MUST recompute and reject on mismatch.
    #[serde(rename = "composed_pre")]
    pub composed_pre: IrFormula,
    /// References to the constituent `EvidenceMemento`s.
    /// MUST be sorted by `evidence_cid` ascending in the JCS bytes
    /// (Rust constructors MAY preserve insertion order; the JCS encoder
    /// sorts at canonicalization time).
    /// MAY be empty (degenerate compound; composed_pre/post = `true`/`true`).
    pub evidences: Vec<EvidenceRef>,
    /// The `FunctionContractMemento.cid` of the function this compound
    /// is the contract for.
    #[serde(rename = "function_term_cid")]
    pub function_term_cid: String,
    /// MUST be "compound-contract".
    pub kind: String,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
}

// ============================================================
// End manual extension block -- compound-contract layer (PR-A)
// ============================================================

// ============================================================
// Manual extension: ProofRunMemento + StageReceipt (issue #792)
// Source of truth:
//   protocol/specs/2026-05-13-proof-run-memento.md §1 and §4
//
// Substrate-only types: carry CIDs and structured stage receipts but do
// not execute the verifier pipeline or interpret stage outputs. Wiring
// these into the actual sugar-verifier runtime is a follow-up.
//
// `header.cid` is DERIVED from JCS(header without cid) and BLAKE3-512.
// For ProofRunMemento, output_artifact_cids sorts ascending in canonical
// form; stage_receipt_cids preserves execution order. For StageReceipt,
// output_cids and refusal_cids sort ascending in canonical form.
// stage_name is `tstr`: this spec does NOT bake any stage vocabulary.
// ============================================================

/// Envelope layer for `ProofRunMemento` and `StageReceipt`.
///
/// Locked JCS key order: declaredAt, signature, signer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofRunEnvelope {
    #[serde(rename = "declaredAt")]
    pub declared_at: String,
    pub signature: String,
    pub signer: String,
}

/// Run-level verdict per `ProofRunMemento` §5.
///
/// Closed enum: admissible / refused / partial.
/// Named `ProofRunVerdict` to distinguish from `RunVerdict` (PR #799)
/// which carries the pipeline-run aggregate verdict (failed/refused/succeeded).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ProofRunVerdict {
    #[serde(rename = "admissible")]
    Admissible,
    #[serde(rename = "refused")]
    Refused,
    #[serde(rename = "partial")]
    Partial,
}

/// Stage-level verdict per `StageReceipt` §1.2.
///
/// Closed enum: ok / warned / refused / skipped. NOT the same enum as
/// `ProofRunVerdict`: `StageReceipt` records a single stage's outcome, while
/// `ProofRunMemento` records the run-aggregate outcome.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum StageVerdict {
    #[serde(rename = "ok")]
    Ok,
    #[serde(rename = "warned")]
    Warned,
    #[serde(rename = "refused")]
    Refused,
    #[serde(rename = "skipped")]
    Skipped,
}

/// Header layer for `ProofRunMemento`.
///
/// Locked JCS key order:
///   cid, input_artifact_cids, input_run_cids, kind, link_bundle_cid,
///   output_artifact_cids, plugin_registry_cid, proof_envelope_cid,
///   schemaVersion, sealed_at, stage_receipt_cids, verdict,
///   verifier_pipeline_cid.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofRunHeader {
    /// DERIVED: BLAKE3-512 over JCS(header) with `cid` elided.
    pub cid: String,
    #[serde(rename = "input_artifact_cids")]
    pub input_artifact_cids: Vec<String>,
    #[serde(rename = "input_run_cids")]
    pub input_run_cids: Vec<String>,
    /// MUST be "proof-run".
    pub kind: String,
    #[serde(rename = "link_bundle_cid")]
    pub link_bundle_cid: String,
    #[serde(rename = "output_artifact_cids")]
    pub output_artifact_cids: Vec<String>,
    #[serde(rename = "plugin_registry_cid")]
    pub plugin_registry_cid: String,
    #[serde(rename = "proof_envelope_cid")]
    pub proof_envelope_cid: String,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "sealed_at")]
    pub sealed_at: String,
    /// Execution order. NOT sorted; preserves verifier stage sequence.
    #[serde(rename = "stage_receipt_cids")]
    pub stage_receipt_cids: Vec<String>,
    pub verdict: ProofRunVerdict,
    #[serde(rename = "verifier_pipeline_cid")]
    pub verifier_pipeline_cid: String,
}

/// Metadata layer for `ProofRunMemento`.
///
/// Locked JCS key order: note, source_url.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ProofRunMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(rename = "source_url")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_url: Option<String>,
}

/// A content-addressed `sugar prove` run record.
///
/// Locked JCS key order: envelope, header, metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofRunMemento {
    pub envelope: ProofRunEnvelope,
    pub header: ProofRunHeader,
    pub metadata: ProofRunMetadata,
}

/// Header layer for `StageReceipt`.
///
/// Locked JCS key order:
///   cid, diagnostics, finished_at, input_cids, kind, output_cids,
///   refusal_cids, schemaVersion, stage_name, started_at, verdict.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StageReceiptHeader {
    /// DERIVED: BLAKE3-512 over JCS(header) with `cid` elided.
    pub cid: String,
    pub diagnostics: Vec<serde_json::Value>,
    #[serde(rename = "finished_at")]
    pub finished_at: String,
    #[serde(rename = "input_cids")]
    pub input_cids: Vec<String>,
    /// MUST be "stage-receipt".
    pub kind: String,
    #[serde(rename = "output_cids")]
    pub output_cids: Vec<String>,
    #[serde(rename = "refusal_cids")]
    pub refusal_cids: Vec<String>,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    /// `tstr`. Stage vocabulary is pinned externally by a future
    /// `VerifierPipelineMemento` (#799), NOT closed by this spec.
    #[serde(rename = "stage_name")]
    pub stage_name: String,
    #[serde(rename = "started_at")]
    pub started_at: String,
    pub verdict: StageVerdict,
}

/// Metadata layer for `StageReceipt`.
///
/// Locked JCS key order: note.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct StageReceiptMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

/// A content-addressed receipt for one verifier stage.
///
/// Locked JCS key order: envelope, header, metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StageReceipt {
    pub envelope: ProofRunEnvelope,
    pub header: StageReceiptHeader,
    pub metadata: StageReceiptMetadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProofRunCanonicalizationError {
    message: String,
}

impl ProofRunCanonicalizationError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ProofRunCanonicalizationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProofRunCanonicalizationError {}

impl From<serde_json::Error> for ProofRunCanonicalizationError {
    fn from(err: serde_json::Error) -> Self {
        Self::new(err.to_string())
    }
}

impl ProofRunMemento {
    /// Serialize the whole memento through the repo JCS encoder.
    pub fn to_jcs_string(&self) -> Result<String, ProofRunCanonicalizationError> {
        let json = serde_json::to_value(self)?;
        let canonical = proof_run_json_to_canonical(&json)?;
        Ok(sugar_canonicalizer::encode_jcs(&canonical))
    }

    /// Recompute `header.cid` per §4.
    ///
    /// Sort-vs-preserve per §2.1:
    /// - `input_artifact_cids` sorts ascending (set semantics)
    /// - `output_artifact_cids` sorts ascending (set semantics)
    /// - `stage_receipt_cids` preserves execution order (matches the
    ///   verifier-pipeline stage vocabulary)
    /// - `input_run_cids` preserves declared replay-graph order
    pub fn recompute_header_cid(&self) -> Result<String, ProofRunCanonicalizationError> {
        let mut header = serde_json::to_value(&self.header)?;
        let serde_json::Value::Object(ref mut object) = header else {
            return Err(ProofRunCanonicalizationError::new(
                "proof-run header did not serialize as an object",
            ));
        };

        object.remove("cid");
        for key in ["input_artifact_cids", "output_artifact_cids"] {
            if let Some(serde_json::Value::Array(items)) = object.get_mut(key) {
                items.sort_by(|left, right| left.as_str().cmp(&right.as_str()));
            }
        }

        let canonical = proof_run_json_to_canonical(&header)?;
        let jcs = sugar_canonicalizer::encode_jcs(&canonical);
        Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
    }
}

impl StageReceipt {
    /// Serialize the whole receipt through the repo JCS encoder.
    pub fn to_jcs_string(&self) -> Result<String, ProofRunCanonicalizationError> {
        let json = serde_json::to_value(self)?;
        let canonical = proof_run_json_to_canonical(&json)?;
        Ok(sugar_canonicalizer::encode_jcs(&canonical))
    }

    /// Recompute `header.cid` per §4.
    ///
    /// Sort-vs-preserve per §2.2:
    /// - `input_cids` sorts ascending (set semantics; "unless a
    ///   stage-specific memento records an ordered input" is a
    ///   higher-layer concern that lives outside this canonical form)
    /// - `output_cids` sorts ascending (set semantics)
    /// - `refusal_cids` sorts ascending (set semantics)
    /// - `diagnostics` preserves producer-declared order (these are
    ///   structured records, not a CID set)
    pub fn recompute_header_cid(&self) -> Result<String, ProofRunCanonicalizationError> {
        let mut header = serde_json::to_value(&self.header)?;
        let serde_json::Value::Object(ref mut object) = header else {
            return Err(ProofRunCanonicalizationError::new(
                "stage-receipt header did not serialize as an object",
            ));
        };

        object.remove("cid");
        for key in ["input_cids", "output_cids", "refusal_cids"] {
            if let Some(serde_json::Value::Array(items)) = object.get_mut(key) {
                items.sort_by(|left, right| left.as_str().cmp(&right.as_str()));
            }
        }

        let canonical = proof_run_json_to_canonical(&header)?;
        let jcs = sugar_canonicalizer::encode_jcs(&canonical);
        Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
    }
}

fn proof_run_json_to_canonical(
    value: &serde_json::Value,
) -> Result<std::sync::Arc<sugar_canonicalizer::Value>, ProofRunCanonicalizationError> {
    use sugar_canonicalizer::Value as CanonicalValue;

    match value {
        serde_json::Value::Null => Ok(CanonicalValue::null()),
        serde_json::Value::Bool(b) => Ok(CanonicalValue::boolean(*b)),
        serde_json::Value::Number(n) => {
            // i64/u64 widen losslessly into the i128 carrier; a float-tagged
            // number (the only remaining non-integer shape under default
            // serde_json) is still rejected -- proof-run mementos carry no
            // floats and no wide string-encoded ints.
            let integer = if let Some(i) = n.as_i64() {
                i128::from(i)
            } else if let Some(u) = n.as_u64() {
                i128::from(u)
            } else {
                return Err(ProofRunCanonicalizationError::new(format!(
                    "unsupported non-integer JSON number in proof-run: {n}"
                )));
            };
            Ok(CanonicalValue::integer(integer))
        }
        serde_json::Value::String(s) => Ok(CanonicalValue::string(s.clone())),
        serde_json::Value::Array(items) => {
            let converted = items
                .iter()
                .map(proof_run_json_to_canonical)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(CanonicalValue::array(converted))
        }
        serde_json::Value::Object(object) => {
            let converted = object
                .iter()
                .map(|(key, value)| Ok((key.clone(), proof_run_json_to_canonical(value)?)))
                .collect::<Result<Vec<_>, ProofRunCanonicalizationError>>()?;
            Ok(CanonicalValue::object(converted))
        }
    }
}

// ============================================================
// End manual extension block -- ProofRunMemento + StageReceipt
// ============================================================

// ============================================================
// Manual extension: observation-wrapper memento (#804)
// Source of truth:
//   protocol/specs/2026-05-13-effect-occurrence-memento.md §1
//   protocol/specs/2026-05-13-observation-wrapper-memento.md §1, §7
//
// This is substrate shape only. It records wrapper/object separation and
// exposes fail-closed validation of the frame invariants. Runtime wrapper
// emission and target syntax generation are intentionally out of scope.
//
// Locked JCS key order:
//   EffectOccurrence:
//     args, discharge_key, locator, occurrence_kind, role, signature_cid
//   ObservationWrapperMemento:
//     emitted_artifact_cid, mode, object_fcm_cid, observer_effects,
//     preservation_claim_cid, provenance_cid, wrapper_fcm_cid
// ============================================================

// ============================================================
// Manual extension: EffectOccurrence substrate object (issue #793)
// Source of truth:
//   protocol/specs/2026-05-13-effect-occurrence-memento.md
//
// EffectOccurrence is a canonical object embedded in
// FunctionContractMemento.effects. It is not a top-level memento and carries
// no envelope, metadata, cid, or evidence pointer.
//
// Key-order rule: struct field names mirror the CDDL key names exactly and
// are declared in JCS alphabetical order:
//   args, discharge_key, locator, occurrence_kind, role, signature_cid.
// The JCS encoder lives outside this crate; serde round-trip tests here pin
// the structural wire shape.
// ============================================================

/// Discharge-classification verdict for an `EffectOccurrence`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Classification {
    #[serde(rename = "block")]
    Block,
    #[serde(rename = "memento-required")]
    MementoRequired,
    #[serde(rename = "informational-dischargeable")]
    InformationalDischargeable,
}

/// The canonical v1 occurrence kind labels plus namespaced extensions.
///
/// Wire format: a bare JSON string. Unknown labels are carried as
/// `Extension(String)` so storage-compatible readers can round-trip them. The
/// public `from_str` helper returns `None` for unknown non-namespaced labels,
/// because v1 extensions are required to use `<namespace>:<kind>`. Serde
/// deserialization fails closed on bare unknowns via `TryFrom<String>`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum OccurrenceKind {
    Reads,
    Writes,
    Io,
    Panics,
    OpaqueLoop,
    UnresolvedCall,
    AtomicAccess,
    EarlyReturn,
    Unsafe,
    ClosureCapture,
    PinnedReference,
    RawPointerProvenance,
    PossibleAliasing,
    Drop,
    Extension(String),
}

impl OccurrenceKind {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "Reads" => Some(OccurrenceKind::Reads),
            "Writes" => Some(OccurrenceKind::Writes),
            "Io" => Some(OccurrenceKind::Io),
            "Panics" => Some(OccurrenceKind::Panics),
            "OpaqueLoop" => Some(OccurrenceKind::OpaqueLoop),
            "UnresolvedCall" => Some(OccurrenceKind::UnresolvedCall),
            "AtomicAccess" => Some(OccurrenceKind::AtomicAccess),
            "EarlyReturn" => Some(OccurrenceKind::EarlyReturn),
            "Unsafe" => Some(OccurrenceKind::Unsafe),
            "ClosureCapture" => Some(OccurrenceKind::ClosureCapture),
            "PinnedReference" => Some(OccurrenceKind::PinnedReference),
            "RawPointerProvenance" => Some(OccurrenceKind::RawPointerProvenance),
            "PossibleAliasing" => Some(OccurrenceKind::PossibleAliasing),
            "Drop" => Some(OccurrenceKind::Drop),
            extension => match extension.split_once(':') {
                // Per spec §3 namespaced-extensions rule, an extension
                // value MUST be `<namespace>:<kind>` with EXACTLY one
                // colon and both segments non-empty. Bare leading/trailing
                // colons (`:kind`, `acme:`) and multi-colon strings
                // (`a:b:c`) are malformed and not extensions.
                Some((ns, kind)) if !ns.is_empty() && !kind.is_empty() && !kind.contains(':') => {
                    Some(OccurrenceKind::Extension(extension.to_string()))
                }
                _ => None,
            },
        }
    }
}

// ============================================================
// Manual extension: PolicyMemento family (issue #798)
// Source of truth:
//   protocol/specs/2026-05-13-policy-memento.md §1, §3
//
// This block adds substrate-only policy declaration types. These types describe
// content-addressed policy inputs; they do not evaluate a decision payload.
//
// Per the spec, `policy_kind` is the discriminator. The five canonical kinds
// are closed over concrete structs. Extension kinds are accepted only when
// namespaced as `<namespace>:<kind>` and carried by
// `NamespacedExtensionPolicyMemento`; consumers that do not implement that
// namespace must fail closed at evaluation time.
// ============================================================

pub type PolicyRule = serde_json::Value;

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(untagged)]
pub enum PolicyMemento {
    Threshold(ThresholdPolicyMemento),
    Property(PropertyPolicyMemento),
    Signature(SignaturePolicyMemento),
    HumanAcceptance(HumanAcceptancePolicyMemento),
    ProofGate(ProofGatePolicyMemento),
    NamespacedExtension(NamespacedExtensionPolicyMemento),
}

impl<'de> Deserialize<'de> for PolicyMemento {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        use serde::de::Error;

        let value = serde_json::Value::deserialize(deserializer)?;
        let policy_kind = value
            .get("policy_kind")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| D::Error::custom("missing string policy_kind"))?;

        match policy_kind {
            "threshold" => serde_json::from_value(value)
                .map(PolicyMemento::Threshold)
                .map_err(D::Error::custom),
            "property" => serde_json::from_value(value)
                .map(PolicyMemento::Property)
                .map_err(D::Error::custom),
            "signature" => serde_json::from_value(value)
                .map(PolicyMemento::Signature)
                .map_err(D::Error::custom),
            "human_acceptance" => serde_json::from_value(value)
                .map(PolicyMemento::HumanAcceptance)
                .map_err(D::Error::custom),
            "proof_gate" => serde_json::from_value(value)
                .map(PolicyMemento::ProofGate)
                .map_err(D::Error::custom),
            other if is_namespaced_policy_kind(other) => serde_json::from_value(value)
                .map(PolicyMemento::NamespacedExtension)
                .map_err(D::Error::custom),
            other => Err(D::Error::custom(format!(
                "unknown bare policy_kind `{other}`"
            ))),
        }
    }
}

impl std::fmt::Display for OccurrenceKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            OccurrenceKind::Reads => "Reads",
            OccurrenceKind::Writes => "Writes",
            OccurrenceKind::Io => "Io",
            OccurrenceKind::Panics => "Panics",
            OccurrenceKind::OpaqueLoop => "OpaqueLoop",
            OccurrenceKind::UnresolvedCall => "UnresolvedCall",
            OccurrenceKind::AtomicAccess => "AtomicAccess",
            OccurrenceKind::EarlyReturn => "EarlyReturn",
            OccurrenceKind::Unsafe => "Unsafe",
            OccurrenceKind::ClosureCapture => "ClosureCapture",
            OccurrenceKind::PinnedReference => "PinnedReference",
            OccurrenceKind::RawPointerProvenance => "RawPointerProvenance",
            OccurrenceKind::PossibleAliasing => "PossibleAliasing",
            OccurrenceKind::Drop => "Drop",
            OccurrenceKind::Extension(s) => s,
        };
        f.write_str(s)
    }
}

impl TryFrom<String> for OccurrenceKind {
    type Error = OccurrenceKindError;

    fn try_from(s: String) -> Result<Self, Self::Error> {
        if let Some(known) = OccurrenceKind::from_str(&s) {
            return Ok(known);
        }
        // Bare unknowns fail closed per spec §3 + admissibility-spine
        // namespaced-extensions rule. Extensions MUST be
        // `<namespace>:<kind>` with both segments non-empty. A bare
        // unknown that silently became Extension(s) would fall through
        // CCP and the classifier with no policy gate.
        // Spec §3: extension labels are `<namespace>:<kind>` with EXACTLY
        // one colon. `a:b:c` is malformed.
        match s.split_once(':') {
            Some((ns, kind)) if !ns.is_empty() && !kind.is_empty() && !kind.contains(':') => {
                Ok(OccurrenceKind::Extension(s))
            }
            _ => Err(OccurrenceKindError { raw: s }),
        }
    }
}

impl From<OccurrenceKind> for String {
    fn from(k: OccurrenceKind) -> String {
        k.to_string()
    }
}

/// Returned when an `occurrence_kind` string is neither a canonical v1
/// kind nor a well-formed `<namespace>:<kind>` extension.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OccurrenceKindError {
    pub raw: String,
}

impl std::fmt::Display for OccurrenceKindError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unrecognized occurrence_kind {:?}: not a canonical v1 kind and not a well-formed `<namespace>:<kind>` extension",
            self.raw
        )
    }
}

impl std::error::Error for OccurrenceKindError {}

/// Contract position where an occurrence is relevant.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum OccurrenceRole {
    #[serde(rename = "pre")]
    Pre,
    #[serde(rename = "post")]
    Post,
    #[serde(rename = "invariant")]
    Invariant,
    #[serde(rename = "body")]
    Body,
    #[serde(rename = "exceptional")]
    Exceptional,
}

/// Canonical occurrence payload embedded in `FunctionContractMemento.effects`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EffectOccurrence {
    pub args: serde_json::Value,
    #[serde(rename = "discharge_key")]
    pub discharge_key: String,
    pub locator: serde_json::Value,
    #[serde(rename = "occurrence_kind")]
    pub occurrence_kind: OccurrenceKind,
    pub role: OccurrenceRole,
    #[serde(rename = "signature_cid")]
    pub signature_cid: String,
}

impl EffectOccurrence {
    /// Pure structural classification per the v1 EffectOccurrence table.
    pub fn classify(&self) -> Classification {
        match self.occurrence_kind {
            OccurrenceKind::Reads
            | OccurrenceKind::Writes
            | OccurrenceKind::Io
            | OccurrenceKind::Panics
            | OccurrenceKind::Unsafe => Classification::Block,
            OccurrenceKind::AtomicAccess => self.classify_atomic_access(),
            OccurrenceKind::Drop => self.classify_drop(),
            OccurrenceKind::OpaqueLoop
            | OccurrenceKind::UnresolvedCall
            | OccurrenceKind::EarlyReturn
            | OccurrenceKind::ClosureCapture
            | OccurrenceKind::PinnedReference
            | OccurrenceKind::RawPointerProvenance
            | OccurrenceKind::PossibleAliasing
            | OccurrenceKind::Extension(_) => Classification::MementoRequired,
        }
    }

    fn classify_atomic_access(&self) -> Classification {
        match self.args.get("ordering") {
            Some(ordering) if !ordering.is_null() => Classification::InformationalDischargeable,
            _ => Classification::MementoRequired,
        }
    }

    fn classify_drop(&self) -> Classification {
        let drop_kind = self
            .args
            .get("drop_kind")
            .or_else(|| self.args.get("dropKind"))
            .and_then(serde_json::Value::as_str);

        match drop_kind {
            Some("Trivial" | "trivial" | "Structural" | "structural") => {
                Classification::InformationalDischargeable
            }
            _ => Classification::MementoRequired,
        }
    }
}

// NOTE: an earlier draft of this module declared a public
// `FunctionContractMemento { effects }` stub. That name collides with the
// real FCM surface (pre/post/formals/body) defined elsewhere; if a caller
// deserialized a full FCM into the stub, serde would silently drop the
// other fields and a subsequent reserialize would lose them. To avoid the
// footgun, the wrapper-validation API now takes effect slices directly.
// The caller is responsible for extracting effects from whatever
// FCM-shaped object they hold.

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvariantViolation {
    UnknownMode { mode: String },
    UnimplementedExtensionMode { mode: String },
    MissingPreservationClaim,
    EmptyObserverEffects,
    ObserverEffectOnObject { effect: EffectOccurrence },
    ObserverEffectMissingFromWrapper { effect: EffectOccurrence },
}

/// Durable substrate object recording a wrapper relationship between an
/// unchanged object function and a wrapper function that carries observer
/// effects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObservationWrapperMemento {
    #[serde(rename = "emitted_artifact_cid")]
    pub emitted_artifact_cid: String,
    pub mode: String,
    #[serde(rename = "object_fcm_cid")]
    pub object_fcm_cid: String,
    #[serde(rename = "observer_effects")]
    pub observer_effects: Vec<EffectOccurrence>,
    #[serde(rename = "preservation_claim_cid")]
    pub preservation_claim_cid: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "wrapper_fcm_cid")]
    pub wrapper_fcm_cid: String,
}

impl ObservationWrapperMemento {
    /// Check the master-frame invariants for this wrapper against caller-supplied
    /// effect surfaces. The caller passes the object-FCM and wrapper-FCM effect
    /// arrays directly; this API intentionally avoids accepting an `FCM` struct
    /// in order to remove the footgun of silently dropping non-`effects` fields.
    ///
    /// `allowed_extension_modes` is the caller's allowlist of namespaced extension
    /// modes (e.g. `["acme:probe"]`). Per spec §7, unimplemented extension
    /// modes MUST fail closed; passing `&[]` accepts only the core
    /// witness/monitor/emitter/gate modes plus legacy dispatcher. A namespaced
    /// mode that is well-formed but absent from the allowlist returns
    /// `UnimplementedExtensionMode`.
    pub fn validate(
        &self,
        object_effects: &[EffectOccurrence],
        wrapper_effects: &[EffectOccurrence],
        allowed_extension_modes: &[&str],
    ) -> Result<(), InvariantViolation> {
        match classify_mode(&self.mode, allowed_extension_modes) {
            ModeClassification::Core | ModeClassification::AllowedExtension => {}
            ModeClassification::UnknownExtension => {
                return Err(InvariantViolation::UnimplementedExtensionMode {
                    mode: self.mode.clone(),
                });
            }
            ModeClassification::Unknown => {
                return Err(InvariantViolation::UnknownMode {
                    mode: self.mode.clone(),
                });
            }
        }

        if self.preservation_claim_cid.is_empty() {
            return Err(InvariantViolation::MissingPreservationClaim);
        }

        // Spec CDDL: observer_effects = [+ effect-occurrence] (non-empty).
        // The vacuous-truth case where the dual-invariant loops below pass on an
        // empty list must be rejected explicitly.
        if self.observer_effects.is_empty() {
            return Err(InvariantViolation::EmptyObserverEffects);
        }

        for effect in &self.observer_effects {
            if object_effects.iter().any(|object| object == effect) {
                return Err(InvariantViolation::ObserverEffectOnObject {
                    effect: effect.clone(),
                });
            }
        }

        for effect in &self.observer_effects {
            if !wrapper_effects.iter().any(|wrapper| wrapper == effect) {
                return Err(InvariantViolation::ObserverEffectMissingFromWrapper {
                    effect: effect.clone(),
                });
            }
        }

        Ok(())
    }
}

// ============================================================
// Manual extension: promotion-decision memento (issue #791)
// Source of truth:
//   protocol/specs/2026-05-13-promotion-decision-memento.md §1 and §4
//
// This block adds the substrate-only PromotionDecisionMemento. It carries
// CIDs and structured decision payloads, but does not interpret source
// language syntax or perform evidence extraction.
//
// `header.cid` is DERIVED from JCS(header without cid) and BLAKE3-512.
// `evidence_cids` are sorted for CID derivation as required by §4.
// ============================================================

/// Envelope layer for a `PromotionDecisionMemento`.
///
/// Locked JCS key order: declaredAt, signature, signer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PromotionDecisionEnvelope {
    #[serde(rename = "declaredAt")]
    pub declared_at: String,
    pub signature: String,
    pub signer: String,
}

/// Promotion gate label. Canonical labels are known, and namespaced
/// extensions are carried as strings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(from = "String", into = "String")]
pub enum PromotionGate {
    Human,
    Proof,
    Property,
    Threshold,
    Other(String),
}

impl From<String> for PromotionGate {
    fn from(s: String) -> Self {
        match s.as_str() {
            "human" => PromotionGate::Human,
            "proof" => PromotionGate::Proof,
            "property" => PromotionGate::Property,
            "threshold" => PromotionGate::Threshold,
            _ => PromotionGate::Other(s),
        }
    }
}

impl From<PromotionGate> for String {
    fn from(gate: PromotionGate) -> String {
        match gate {
            PromotionGate::Human => "human".to_string(),
            PromotionGate::Proof => "proof".to_string(),
            PromotionGate::Property => "property".to_string(),
            PromotionGate::Threshold => "threshold".to_string(),
            PromotionGate::Other(s) => s,
        }
    }
}

/// Promotion result. The v1 CDDL closes this set.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PromotionResult {
    #[serde(rename = "admitted")]
    Admitted,
    #[serde(rename = "rejected")]
    Rejected,
    #[serde(rename = "deferred")]
    Deferred,
}

/// Header layer for a `PromotionDecisionMemento`.
///
/// Locked JCS key order:
///   candidate_cid, cid, decider_cid, decision_payload, evidence_cids,
///   gate, kind, policy_cid, promoted_cid, result, schemaVersion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PromotionDecisionHeader {
    #[serde(rename = "candidate_cid")]
    pub candidate_cid: String,
    /// DERIVED: BLAKE3-512 over JCS(header) with `cid` elided.
    pub cid: String,
    #[serde(rename = "decider_cid")]
    pub decider_cid: String,
    #[serde(rename = "decision_payload")]
    pub decision_payload: serde_json::Value,
    #[serde(rename = "evidence_cids")]
    pub evidence_cids: Vec<String>,
    pub gate: PromotionGate,
    /// MUST be "promotion-decision".
    pub kind: String,
    #[serde(rename = "policy_cid")]
    pub policy_cid: String,
    #[serde(rename = "promoted_cid")]
    pub promoted_cid: String,
    pub result: PromotionResult,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
}

/// Metadata layer for a `PromotionDecisionMemento`.
///
/// Locked JCS key order: counterexample_cids, note, source_url.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct PromotionDecisionMetadata {
    #[serde(rename = "counterexample_cids")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub counterexample_cids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(rename = "source_url")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_url: Option<String>,
}

/// A content-addressed promotion decision connecting a candidate,
/// evidence set, policy, decider, and promoted artifact.
///
/// Locked JCS key order: envelope, header, metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PromotionDecisionMemento {
    pub envelope: PromotionDecisionEnvelope,
    pub header: PromotionDecisionHeader,
    pub metadata: PromotionDecisionMetadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PromotionDecisionCanonicalizationError {
    message: String,
}

impl PromotionDecisionCanonicalizationError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl std::fmt::Display for PromotionDecisionCanonicalizationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PromotionDecisionCanonicalizationError {}

impl From<serde_json::Error> for PromotionDecisionCanonicalizationError {
    fn from(err: serde_json::Error) -> Self {
        Self::new(err.to_string())
    }
}

impl PromotionDecisionMemento {
    /// Serialize the whole memento through the repo JCS encoder.
    pub fn to_jcs_string(&self) -> Result<String, PromotionDecisionCanonicalizationError> {
        let json = serde_json::to_value(self)?;
        let canonical = serde_json_to_canonical_value(&json)?;
        Ok(sugar_canonicalizer::encode_jcs(&canonical))
    }

    /// Recompute `header.cid` per §4.
    pub fn recompute_header_cid(&self) -> Result<String, PromotionDecisionCanonicalizationError> {
        let mut header = serde_json::to_value(&self.header)?;
        let serde_json::Value::Object(ref mut object) = header else {
            return Err(PromotionDecisionCanonicalizationError::new(
                "promotion header did not serialize as an object",
            ));
        };

        object.remove("cid");
        if let Some(serde_json::Value::Array(evidence_cids)) = object.get_mut("evidence_cids") {
            evidence_cids.sort_by(|left, right| left.as_str().cmp(&right.as_str()));
        }

        let canonical = serde_json_to_canonical_value(&header)?;
        let jcs = sugar_canonicalizer::encode_jcs(&canonical);
        Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
    }

    /// Check load-time invariants per spec §1 CDDL.
    ///
    /// `evidence_cids` is declared as `[+ cid]` (non-empty) in the spec.
    /// An evidence-free promotion would contradict the master-frame
    /// admissibility-spine framing (#796): every irreversible substrate
    /// claim needs a memento that says what was observed. Empty evidence
    /// is no evidence; admission MUST fail closed.
    pub fn validate(&self) -> Result<(), PromotionDecisionInvariantError> {
        if self.header.evidence_cids.is_empty() {
            return Err(PromotionDecisionInvariantError::EmptyEvidenceCids);
        }
        Ok(())
    }
}

enum ModeClassification {
    /// Core wrapper-mode from the spec: witness / monitor / emitter / gate.
    /// `dispatcher` remains accepted for legacy wrapper records.
    Core,
    /// Namespaced extension that the caller explicitly admitted via the allowlist.
    AllowedExtension,
    /// Well-formed `<namespace>:<kind>` shape but absent from the allowlist.
    UnknownExtension,
    /// Neither a core mode nor a well-formed namespaced extension.
    Unknown,
}

fn classify_mode(mode: &str, allowed_extension_modes: &[&str]) -> ModeClassification {
    if matches!(
        mode,
        "witness" | "monitor" | "emitter" | "gate" | "dispatcher"
    ) {
        return ModeClassification::Core;
    }
    // Spec: extension modes are `<namespace>:<kind>` with EXACTLY one
    // colon, both segments non-empty. `a:b:c` is not a valid namespaced
    // extension.
    match mode.split_once(':') {
        Some((namespace, extension))
            if !namespace.is_empty() && !extension.is_empty() && !extension.contains(':') =>
        {
            if allowed_extension_modes.iter().any(|m| *m == mode) {
                ModeClassification::AllowedExtension
            } else {
                ModeClassification::UnknownExtension
            }
        }
        _ => ModeClassification::Unknown,
    }
}

/// Returned when a `PromotionDecisionMemento` violates a load-time
/// invariant per `2026-05-13-promotion-decision-memento.md` §1.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PromotionDecisionInvariantError {
    /// Spec §1 CDDL: `evidence_cids: [+ cid]` (non-empty). The master
    /// frame requires every admission to cite what was observed.
    EmptyEvidenceCids,
}

impl std::fmt::Display for PromotionDecisionInvariantError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EmptyEvidenceCids => f.write_str(
                "PromotionDecisionMemento: evidence_cids is empty (spec §1 CDDL requires [+ cid]; admissibility-spine #796 forbids evidence-free admission)",
            ),
        }
    }
}

impl std::error::Error for PromotionDecisionInvariantError {}

fn serde_json_to_canonical_value(
    value: &serde_json::Value,
) -> Result<std::sync::Arc<sugar_canonicalizer::Value>, PromotionDecisionCanonicalizationError> {
    use sugar_canonicalizer::Value as CanonicalValue;

    match value {
        serde_json::Value::Null => Ok(CanonicalValue::null()),
        serde_json::Value::Bool(b) => Ok(CanonicalValue::boolean(*b)),
        serde_json::Value::Number(n) => {
            // i64/u64 widen losslessly into the i128 carrier; a float-tagged
            // number is still rejected (promotion decisions carry no floats).
            let integer = if let Some(i) = n.as_i64() {
                i128::from(i)
            } else if let Some(u) = n.as_u64() {
                i128::from(u)
            } else {
                return Err(PromotionDecisionCanonicalizationError::new(format!(
                    "unsupported non-integer JSON number in promotion decision: {n}"
                )));
            };
            Ok(CanonicalValue::integer(integer))
        }
        serde_json::Value::String(s) => Ok(CanonicalValue::string(s.clone())),
        serde_json::Value::Array(items) => {
            let converted = items
                .iter()
                .map(serde_json_to_canonical_value)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(CanonicalValue::array(converted))
        }
        serde_json::Value::Object(object) => {
            let converted = object
                .iter()
                .map(|(key, value)| Ok((key.clone(), serde_json_to_canonical_value(value)?)))
                .collect::<Result<Vec<_>, PromotionDecisionCanonicalizationError>>()?;
            Ok(CanonicalValue::object(converted))
        }
    }
}

fn is_namespaced_policy_kind(s: &str) -> bool {
    let Some((namespace, kind)) = s.split_once(':') else {
        return false;
    };

    is_policy_kind_segment(namespace) && is_policy_kind_segment(kind)
}

fn is_policy_kind_segment(segment: &str) -> bool {
    let mut chars = segment.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_alphabetic())
        && chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ThresholdPolicyMemento {
    #[serde(rename = "admission_rule")]
    pub admission_rule: PolicyRule,
    #[serde(rename = "count_field_path")]
    pub count_field_path: Vec<String>,
    #[serde(rename = "decision_payload_schema")]
    pub decision_payload_schema: serde_json::Value,
    #[serde(rename = "input_requirements")]
    pub input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    pub policy_kind: String,
    #[serde(rename = "policy_version")]
    pub policy_version: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "refusal_rule")]
    pub refusal_rule: PolicyRule,
    #[serde(rename = "score_field_path")]
    pub score_field_path: Vec<String>,
    #[serde(rename = "threshold_comparator")]
    pub threshold_comparator: String,
    #[serde(rename = "threshold_value")]
    pub threshold_value: serde_json::Number,
    #[serde(rename = "weight_field_path")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub weight_field_path: Option<Vec<String>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PropertyPolicyMemento {
    #[serde(rename = "admission_rule")]
    pub admission_rule: PolicyRule,
    #[serde(rename = "decision_payload_schema")]
    pub decision_payload_schema: serde_json::Value,
    #[serde(rename = "generator_cid")]
    pub generator_cid: String,
    #[serde(rename = "input_requirements")]
    pub input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    pub policy_kind: String,
    #[serde(rename = "policy_version")]
    pub policy_version: String,
    #[serde(rename = "property_cid")]
    pub property_cid: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "refusal_rule")]
    pub refusal_rule: PolicyRule,
    #[serde(rename = "result_field_path")]
    pub result_field_path: Vec<String>,
    #[serde(rename = "shrinker_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub shrinker_cid: Option<String>,
    #[serde(rename = "success_criteria")]
    pub success_criteria: PolicyRule,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SignaturePolicyMemento {
    #[serde(rename = "admission_rule")]
    pub admission_rule: PolicyRule,
    #[serde(rename = "allowed_signature_suites")]
    pub allowed_signature_suites: Vec<String>,
    #[serde(rename = "decision_payload_schema")]
    pub decision_payload_schema: serde_json::Value,
    #[serde(rename = "delegation_policy_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub delegation_policy_cid: Option<String>,
    #[serde(rename = "input_requirements")]
    pub input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    pub policy_kind: String,
    #[serde(rename = "policy_version")]
    pub policy_version: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "quorum_size")]
    pub quorum_size: u64,
    #[serde(rename = "refusal_rule")]
    pub refusal_rule: PolicyRule,
    #[serde(rename = "required_signers_cids")]
    pub required_signers_cids: Vec<String>,
    #[serde(rename = "signature_payload_schema")]
    pub signature_payload_schema: serde_json::Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HumanAcceptancePolicyMemento {
    #[serde(rename = "acceptance_record_schema")]
    pub acceptance_record_schema: serde_json::Value,
    #[serde(rename = "admission_rule")]
    pub admission_rule: PolicyRule,
    #[serde(rename = "conflict_policy_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub conflict_policy_cid: Option<String>,
    #[serde(rename = "decision_payload_schema")]
    pub decision_payload_schema: serde_json::Value,
    #[serde(rename = "delegation_policy_cid")]
    pub delegation_policy_cid: String,
    #[serde(rename = "input_requirements")]
    pub input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    pub policy_kind: String,
    #[serde(rename = "policy_version")]
    pub policy_version: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "refusal_rule")]
    pub refusal_rule: PolicyRule,
    #[serde(rename = "required_acceptances")]
    pub required_acceptances: u64,
    #[serde(rename = "reviewer_roster_cid")]
    pub reviewer_roster_cid: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProofGatePolicyMemento {
    #[serde(rename = "admission_rule")]
    pub admission_rule: PolicyRule,
    #[serde(rename = "checker_cid")]
    pub checker_cid: String,
    #[serde(rename = "decision_payload_schema")]
    pub decision_payload_schema: serde_json::Value,
    #[serde(rename = "input_requirements")]
    pub input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    pub policy_kind: String,
    #[serde(rename = "policy_version")]
    pub policy_version: String,
    #[serde(rename = "proof_artifact_schema")]
    pub proof_artifact_schema: serde_json::Value,
    #[serde(rename = "proof_system")]
    pub proof_system: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "refusal_rule")]
    pub refusal_rule: PolicyRule,
    #[serde(rename = "theorem_ref")]
    pub theorem_ref: String,
    #[serde(rename = "trusted_base_cid")]
    pub trusted_base_cid: String,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(try_from = "NamespacedExtensionPolicyMementoWire")]
pub struct NamespacedExtensionPolicyMemento {
    #[serde(rename = "admission_rule")]
    pub admission_rule: PolicyRule,
    #[serde(rename = "decision_payload_schema")]
    pub decision_payload_schema: serde_json::Value,
    #[serde(rename = "input_requirements")]
    pub input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    pub policy_kind: String,
    #[serde(rename = "policy_version")]
    pub policy_version: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "refusal_rule")]
    pub refusal_rule: PolicyRule,
    #[serde(flatten)]
    pub extension_fields: BTreeMap<String, serde_json::Value>,
}

impl Serialize for NamespacedExtensionPolicyMemento {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::Error;

        let mut fields = self.extension_fields.clone();
        fields.insert("admission_rule".into(), self.admission_rule.clone());
        fields.insert(
            "decision_payload_schema".into(),
            self.decision_payload_schema.clone(),
        );
        fields.insert("input_requirements".into(), self.input_requirements.clone());
        fields.insert(
            "policy_kind".into(),
            serde_json::Value::String(self.policy_kind.clone()),
        );
        fields.insert(
            "policy_version".into(),
            serde_json::Value::String(self.policy_version.clone()),
        );
        fields.insert(
            "provenance_cid".into(),
            serde_json::Value::String(self.provenance_cid.clone()),
        );
        fields.insert("refusal_rule".into(), self.refusal_rule.clone());

        fields.serialize(serializer).map_err(S::Error::custom)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct NamespacedExtensionPolicyMementoWire {
    #[serde(rename = "admission_rule")]
    admission_rule: PolicyRule,
    #[serde(rename = "decision_payload_schema")]
    decision_payload_schema: serde_json::Value,
    #[serde(rename = "input_requirements")]
    input_requirements: serde_json::Value,
    #[serde(rename = "policy_kind")]
    policy_kind: String,
    #[serde(rename = "policy_version")]
    policy_version: String,
    #[serde(rename = "provenance_cid")]
    provenance_cid: String,
    #[serde(rename = "refusal_rule")]
    refusal_rule: PolicyRule,
    #[serde(flatten)]
    extension_fields: BTreeMap<String, serde_json::Value>,
}

impl TryFrom<NamespacedExtensionPolicyMementoWire> for NamespacedExtensionPolicyMemento {
    type Error = String;

    fn try_from(wire: NamespacedExtensionPolicyMementoWire) -> Result<Self, Self::Error> {
        if !is_namespaced_policy_kind(&wire.policy_kind) {
            return Err(format!(
                "extension policy_kind `{}` is not namespaced",
                wire.policy_kind
            ));
        }

        Ok(Self {
            admission_rule: wire.admission_rule,
            decision_payload_schema: wire.decision_payload_schema,
            input_requirements: wire.input_requirements,
            policy_kind: wire.policy_kind,
            policy_version: wire.policy_version,
            provenance_cid: wire.provenance_cid,
            refusal_rule: wire.refusal_rule,
            extension_fields: wire.extension_fields,
        })
    }
}

impl From<NamespacedExtensionPolicyMemento> for NamespacedExtensionPolicyMementoWire {
    fn from(memento: NamespacedExtensionPolicyMemento) -> Self {
        Self {
            admission_rule: memento.admission_rule,
            decision_payload_schema: memento.decision_payload_schema,
            input_requirements: memento.input_requirements,
            policy_kind: memento.policy_kind,
            policy_version: memento.policy_version,
            provenance_cid: memento.provenance_cid,
            refusal_rule: memento.refusal_rule,
            extension_fields: memento.extension_fields,
        }
    }
}

// ============================================================
// Manual extension: PolicyProfileMemento family (issue #929)
// Source of truth:
//   protocol/specs/2026-05-14-policy-profile-memento.md §1
//
// A policy profile is not another gate predicate. It is the
// content-addressed bundle that chooses which concrete policy CID applies
// to each decision lane in a run: witness consensus, sugar selection, and
// emission gating. Emission decisions are required to be witnessed so the
// profile cannot hide a runtime wrapper choice behind local defaults.
// ============================================================

/// Per-profile decision lane. Canonical lanes are closed over the v1
/// profile surface; namespaced extensions are carried but must validate
/// as `<namespace>:<kind>`.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(from = "String", into = "String")]
pub enum PolicyProfileDecisionKind {
    WitnessConsensus,
    SugarSelection,
    EmissionGating,
    Other(String),
}

impl PolicyProfileDecisionKind {
    pub fn as_str(&self) -> &str {
        match self {
            Self::WitnessConsensus => "witness-consensus",
            Self::SugarSelection => "sugar-selection",
            Self::EmissionGating => "emission-gating",
            Self::Other(raw) => raw,
        }
    }
}

impl From<String> for PolicyProfileDecisionKind {
    fn from(s: String) -> Self {
        match s.as_str() {
            "witness-consensus" => Self::WitnessConsensus,
            "sugar-selection" => Self::SugarSelection,
            "emission-gating" => Self::EmissionGating,
            _ => Self::Other(s),
        }
    }
}

impl From<PolicyProfileDecisionKind> for String {
    fn from(kind: PolicyProfileDecisionKind) -> String {
        match kind {
            PolicyProfileDecisionKind::WitnessConsensus => "witness-consensus".to_string(),
            PolicyProfileDecisionKind::SugarSelection => "sugar-selection".to_string(),
            PolicyProfileDecisionKind::EmissionGating => "emission-gating".to_string(),
            PolicyProfileDecisionKind::Other(raw) => raw,
        }
    }
}

/// Threshold cited by a profile lane. The grammar is evaluated by the
/// libsugar registry because it is a consumer policy concern, not a
/// serde concern.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyProfileThreshold {
    pub axis: String,
    pub predicate: String,
}

/// One decision lane in a policy profile.
///
/// Locked JCS key order: decision_kind, emission_mode, policy_cid,
/// required, requires_witnessed_decision, thresholds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyProfileDecision {
    #[serde(rename = "decision_kind")]
    pub decision_kind: PolicyProfileDecisionKind,
    #[serde(rename = "emission_mode")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub emission_mode: Option<String>,
    #[serde(rename = "policy_cid")]
    pub policy_cid: String,
    pub required: bool,
    #[serde(rename = "requires_witnessed_decision")]
    pub requires_witnessed_decision: bool,
    pub thresholds: Vec<PolicyProfileThreshold>,
}

/// Content-addressed profile selecting concrete policies for a run.
///
/// Locked JCS key order: cid, decisions, kind, name, schemaVersion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyProfileMemento {
    /// DERIVED: BLAKE3-512 over JCS(profile) with `cid` elided and
    /// decisions sorted by `decision_kind`.
    pub cid: String,
    pub decisions: Vec<PolicyProfileDecision>,
    /// MUST be "policy-profile".
    pub kind: String,
    pub name: String,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
}

impl PolicyProfileMemento {
    pub fn recompute_cid(&self) -> Result<String, PromotionDecisionCanonicalizationError> {
        let mut profile = serde_json::to_value(self)?;
        let serde_json::Value::Object(ref mut object) = profile else {
            return Err(PromotionDecisionCanonicalizationError::new(
                "policy profile did not serialize as an object",
            ));
        };

        object.remove("cid");
        if let Some(serde_json::Value::Array(decisions)) = object.get_mut("decisions") {
            decisions.sort_by(|left, right| {
                left.get("decision_kind")
                    .and_then(serde_json::Value::as_str)
                    .cmp(
                        &right
                            .get("decision_kind")
                            .and_then(serde_json::Value::as_str),
                    )
            });
        }

        let canonical = serde_json_to_canonical_value(&profile)?;
        let jcs = sugar_canonicalizer::encode_jcs(&canonical);
        Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
    }

    pub fn validate(&self) -> Result<(), PolicyProfileValidationError> {
        if self.kind != "policy-profile" {
            return Err(PolicyProfileValidationError::InvalidKind {
                kind: self.kind.clone(),
            });
        }
        if self.schema_version != "1" {
            return Err(PolicyProfileValidationError::InvalidSchemaVersion {
                schema_version: self.schema_version.clone(),
            });
        }
        if self.name.is_empty() {
            return Err(PolicyProfileValidationError::EmptyName);
        }
        if self.decisions.is_empty() {
            return Err(PolicyProfileValidationError::EmptyDecisions);
        }

        let actual = self
            .recompute_cid()
            .map_err(|err| PolicyProfileValidationError::Canonicalization(err.to_string()))?;
        if actual != self.cid {
            return Err(PolicyProfileValidationError::CidMismatch {
                claimed: self.cid.clone(),
                actual,
            });
        }

        let mut seen = std::collections::BTreeSet::new();
        for decision in &self.decisions {
            let kind = decision.decision_kind.as_str();
            if matches!(decision.decision_kind, PolicyProfileDecisionKind::Other(_))
                && !is_namespaced_policy_kind(kind)
            {
                return Err(PolicyProfileValidationError::InvalidDecisionKind {
                    decision_kind: kind.to_string(),
                });
            }
            if !seen.insert(kind.to_string()) {
                return Err(PolicyProfileValidationError::DuplicateDecisionKind {
                    decision_kind: kind.to_string(),
                });
            }
            if decision.thresholds.is_empty() {
                return Err(PolicyProfileValidationError::EmptyThresholds {
                    decision_kind: kind.to_string(),
                });
            }
            if !is_blake3_512_cid(&decision.policy_cid) {
                return Err(PolicyProfileValidationError::InvalidPolicyCid {
                    decision_kind: kind.to_string(),
                    policy_cid: decision.policy_cid.clone(),
                });
            }
            if decision.decision_kind == PolicyProfileDecisionKind::EmissionGating
                && !decision.requires_witnessed_decision
            {
                return Err(PolicyProfileValidationError::UnwitnessedEmissionDecision);
            }
        }

        for required in [
            PolicyProfileDecisionKind::WitnessConsensus,
            PolicyProfileDecisionKind::SugarSelection,
            PolicyProfileDecisionKind::EmissionGating,
        ] {
            if !seen.contains(required.as_str()) {
                return Err(PolicyProfileValidationError::MissingDecisionKind {
                    decision_kind: required.as_str().to_string(),
                });
            }
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PolicyProfileValidationError {
    InvalidKind {
        kind: String,
    },
    InvalidSchemaVersion {
        schema_version: String,
    },
    EmptyName,
    EmptyDecisions,
    CidMismatch {
        claimed: String,
        actual: String,
    },
    Canonicalization(String),
    InvalidDecisionKind {
        decision_kind: String,
    },
    DuplicateDecisionKind {
        decision_kind: String,
    },
    MissingDecisionKind {
        decision_kind: String,
    },
    EmptyThresholds {
        decision_kind: String,
    },
    InvalidPolicyCid {
        decision_kind: String,
        policy_cid: String,
    },
    UnwitnessedEmissionDecision,
}

impl std::fmt::Display for PolicyProfileValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidKind { kind } => {
                write!(f, "PolicyProfileMemento: invalid kind `{kind}`")
            }
            Self::InvalidSchemaVersion { schema_version } => write!(
                f,
                "PolicyProfileMemento: invalid schemaVersion `{schema_version}`"
            ),
            Self::EmptyName => f.write_str("PolicyProfileMemento: name must be non-empty"),
            Self::EmptyDecisions => {
                f.write_str("PolicyProfileMemento: decisions must be non-empty")
            }
            Self::CidMismatch { claimed, actual } => write!(
                f,
                "PolicyProfileMemento: cid mismatch: claimed {claimed}, recomputed {actual}"
            ),
            Self::Canonicalization(message) => {
                write!(f, "PolicyProfileMemento: canonicalization failed: {message}")
            }
            Self::InvalidDecisionKind { decision_kind } => write!(
                f,
                "PolicyProfileMemento: invalid decision_kind `{decision_kind}`"
            ),
            Self::DuplicateDecisionKind { decision_kind } => write!(
                f,
                "PolicyProfileMemento: duplicate decision_kind `{decision_kind}`"
            ),
            Self::MissingDecisionKind { decision_kind } => write!(
                f,
                "PolicyProfileMemento: missing decision_kind `{decision_kind}`"
            ),
            Self::EmptyThresholds { decision_kind } => write!(
                f,
                "PolicyProfileMemento: decision_kind `{decision_kind}` has no thresholds"
            ),
            Self::InvalidPolicyCid {
                decision_kind,
                policy_cid,
            } => write!(
                f,
                "PolicyProfileMemento: decision_kind `{decision_kind}` has invalid policy_cid `{policy_cid}`"
            ),
            Self::UnwitnessedEmissionDecision => f.write_str(
                "PolicyProfileMemento: emission-gating decisions must require witnessed emission decisions",
            ),
        }
    }
}

impl std::error::Error for PolicyProfileValidationError {}

// ============================================================
// Manual extension: SugarSelectionPolicyMemento family (issue #889)
// Source of truth:
//   protocol/specs/2026-05-18-sugar-selection-policy-memento.md
//
// This is a content-addressed declaration of the sugar selection policy lane
// cited by PolicyProfileMemento. It codifies the sugar-dict §4 emission
// policy as a federated memento so vendors can ship policy CIDs alongside
// sugar dict CIDs.
// ============================================================

/// The sugar emission mode selected by a sugar selection policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum SugarSelectionMode {
    BestOnly,
    Inclusive,
    Strict,
}

impl SugarSelectionMode {
    pub fn as_str(&self) -> &str {
        match self {
            Self::BestOnly => "best-only",
            Self::Inclusive => "inclusive",
            Self::Strict => "strict",
        }
    }
}

impl TryFrom<String> for SugarSelectionMode {
    type Error = String;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        match value.as_str() {
            "best-only" => Ok(Self::BestOnly),
            "inclusive" => Ok(Self::Inclusive),
            "strict" => Ok(Self::Strict),
            other => Err(format!("unknown sugar selection mode `{other}`")),
        }
    }
}

impl From<SugarSelectionMode> for String {
    fn from(mode: SugarSelectionMode) -> String {
        mode.as_str().to_string()
    }
}

/// The deterministic tie-breaking strategy from sugar-dict §4.4.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum SugarSelectionTieBreaking {
    LoadOrderThenEntryIndex,
}

impl SugarSelectionTieBreaking {
    pub fn as_str(&self) -> &str {
        match self {
            Self::LoadOrderThenEntryIndex => "load-order-then-entry-index",
        }
    }
}

impl TryFrom<String> for SugarSelectionTieBreaking {
    type Error = String;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        match value.as_str() {
            "load-order-then-entry-index" => Ok(Self::LoadOrderThenEntryIndex),
            other => Err(format!("unknown sugar selection tie_breaking `{other}`")),
        }
    }
}

impl From<SugarSelectionTieBreaking> for String {
    fn from(tie_breaking: SugarSelectionTieBreaking) -> String {
        tie_breaking.as_str().to_string()
    }
}

/// Per-concept, per-language match criterion for a sugar selection policy.
///
/// Locked JCS key order: concept, language.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SugarSelectionAppliesTo {
    pub concept: String,
    pub language: String,
}

/// Content-addressed sugar selection policy.
///
/// Header fields are `cid`, `kind`, and `schemaVersion`; the remaining fields
/// declare the policy content. Field order follows JCS key order:
/// applies_to, cid, eligible_sugars, forbidden_sugars, kind, mode,
/// schemaVersion, scoring, tie_breaking.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SugarSelectionPolicyMemento {
    #[serde(rename = "applies_to")]
    pub applies_to: Vec<SugarSelectionAppliesTo>,
    /// DERIVED: BLAKE3-512 over JCS(memento) with `cid` elided.
    pub cid: String,
    #[serde(rename = "eligible_sugars")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub eligible_sugars: Option<Vec<String>>,
    #[serde(rename = "forbidden_sugars")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub forbidden_sugars: Option<Vec<String>>,
    /// MUST be "sugar-selection-policy".
    pub kind: String,
    pub mode: SugarSelectionMode,
    /// MUST be "1".
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scoring: Option<String>,
    #[serde(rename = "tie_breaking")]
    pub tie_breaking: SugarSelectionTieBreaking,
}

impl SugarSelectionPolicyMemento {
    pub fn from_jcs(jcs: &str) -> Result<Self, SugarSelectionPolicyValidationError> {
        let policy: Self = serde_json::from_str(jcs)
            .map_err(|err| SugarSelectionPolicyValidationError::Json(err.to_string()))?;
        let rendered = policy.to_jcs_string()?;
        if rendered != jcs {
            return Err(SugarSelectionPolicyValidationError::NonCanonicalJcs);
        }
        policy.validate()?;
        Ok(policy)
    }

    pub fn to_jcs_string(&self) -> Result<String, PromotionDecisionCanonicalizationError> {
        let json = serde_json::to_value(self)?;
        let canonical = serde_json_to_canonical_value(&json)?;
        Ok(sugar_canonicalizer::encode_jcs(&canonical))
    }

    pub fn recompute_cid(&self) -> Result<String, PromotionDecisionCanonicalizationError> {
        let mut policy = serde_json::to_value(self)?;
        let serde_json::Value::Object(ref mut object) = policy else {
            return Err(PromotionDecisionCanonicalizationError::new(
                "sugar selection policy did not serialize as an object",
            ));
        };

        object.remove("cid");
        let canonical = serde_json_to_canonical_value(&policy)?;
        let jcs = sugar_canonicalizer::encode_jcs(&canonical);
        Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
    }

    pub fn validate(&self) -> Result<(), SugarSelectionPolicyValidationError> {
        if self.kind != "sugar-selection-policy" {
            return Err(SugarSelectionPolicyValidationError::InvalidKind {
                kind: self.kind.clone(),
            });
        }
        if self.schema_version != "1" {
            return Err(SugarSelectionPolicyValidationError::InvalidSchemaVersion {
                schema_version: self.schema_version.clone(),
            });
        }
        if self.applies_to.is_empty() {
            return Err(SugarSelectionPolicyValidationError::EmptyAppliesTo);
        }
        for (index, criterion) in self.applies_to.iter().enumerate() {
            if criterion.concept.is_empty() {
                return Err(SugarSelectionPolicyValidationError::EmptyApplyCriterion {
                    index,
                    field: "concept",
                });
            }
            if criterion.language.is_empty() {
                return Err(SugarSelectionPolicyValidationError::EmptyApplyCriterion {
                    index,
                    field: "language",
                });
            }
        }

        if let Some(scoring) = &self.scoring {
            require_policy_cid("scoring", scoring)?;
        }
        validate_policy_cid_list("eligible_sugars", self.eligible_sugars.as_deref())?;
        validate_policy_cid_list("forbidden_sugars", self.forbidden_sugars.as_deref())?;
        reject_policy_cid_overlap(
            self.eligible_sugars.as_deref(),
            self.forbidden_sugars.as_deref(),
        )?;

        let actual = self.recompute_cid().map_err(|err| {
            SugarSelectionPolicyValidationError::Canonicalization(err.to_string())
        })?;
        if actual != self.cid {
            return Err(SugarSelectionPolicyValidationError::CidMismatch {
                claimed: self.cid.clone(),
                actual,
            });
        }

        Ok(())
    }
}

impl std::str::FromStr for SugarSelectionPolicyMemento {
    type Err = SugarSelectionPolicyValidationError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::from_jcs(s)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SugarSelectionPolicyValidationError {
    InvalidKind { kind: String },
    InvalidSchemaVersion { schema_version: String },
    EmptyAppliesTo,
    EmptyApplyCriterion { index: usize, field: &'static str },
    InvalidCid { field: &'static str, cid: String },
    DuplicateSugarCid { field: &'static str, cid: String },
    OverlappingSugarCid { cid: String },
    CidMismatch { claimed: String, actual: String },
    Canonicalization(String),
    Json(String),
    NonCanonicalJcs,
}

impl std::fmt::Display for SugarSelectionPolicyValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidKind { kind } => {
                write!(f, "SugarSelectionPolicyMemento: invalid kind `{kind}`")
            }
            Self::InvalidSchemaVersion { schema_version } => write!(
                f,
                "SugarSelectionPolicyMemento: invalid schemaVersion `{schema_version}`"
            ),
            Self::EmptyAppliesTo => {
                f.write_str("SugarSelectionPolicyMemento: applies_to must be non-empty")
            }
            Self::EmptyApplyCriterion { index, field } => write!(
                f,
                "SugarSelectionPolicyMemento: applies_to[{index}].{field} must be non-empty"
            ),
            Self::InvalidCid { field, cid } => write!(
                f,
                "SugarSelectionPolicyMemento: {field} contains invalid cid `{cid}`"
            ),
            Self::DuplicateSugarCid { field, cid } => write!(
                f,
                "SugarSelectionPolicyMemento: {field} contains duplicate cid `{cid}`"
            ),
            Self::OverlappingSugarCid { cid } => write!(
                f,
                "SugarSelectionPolicyMemento: sugar cid `{cid}` is both eligible and forbidden"
            ),
            Self::CidMismatch { claimed, actual } => write!(
                f,
                "SugarSelectionPolicyMemento: cid mismatch: claimed {claimed}, recomputed {actual}"
            ),
            Self::Canonicalization(message) => write!(
                f,
                "SugarSelectionPolicyMemento: canonicalization failed: {message}"
            ),
            Self::Json(message) => {
                write!(
                    f,
                    "SugarSelectionPolicyMemento: JSON parse failed: {message}"
                )
            }
            Self::NonCanonicalJcs => {
                f.write_str("SugarSelectionPolicyMemento: input was not canonical JCS")
            }
        }
    }
}

impl std::error::Error for SugarSelectionPolicyValidationError {}

impl From<PromotionDecisionCanonicalizationError> for SugarSelectionPolicyValidationError {
    fn from(err: PromotionDecisionCanonicalizationError) -> Self {
        Self::Canonicalization(err.to_string())
    }
}

fn require_policy_cid(
    field: &'static str,
    cid: &str,
) -> Result<(), SugarSelectionPolicyValidationError> {
    if is_blake3_512_cid(cid) {
        Ok(())
    } else {
        Err(SugarSelectionPolicyValidationError::InvalidCid {
            field,
            cid: cid.to_string(),
        })
    }
}

fn validate_policy_cid_list(
    field: &'static str,
    cids: Option<&[String]>,
) -> Result<(), SugarSelectionPolicyValidationError> {
    let Some(cids) = cids else {
        return Ok(());
    };
    let mut seen = std::collections::BTreeSet::new();
    for cid in cids {
        require_policy_cid(field, cid)?;
        if !seen.insert(cid.as_str()) {
            return Err(SugarSelectionPolicyValidationError::DuplicateSugarCid {
                field,
                cid: cid.clone(),
            });
        }
    }
    Ok(())
}

fn reject_policy_cid_overlap(
    eligible: Option<&[String]>,
    forbidden: Option<&[String]>,
) -> Result<(), SugarSelectionPolicyValidationError> {
    let (Some(eligible), Some(forbidden)) = (eligible, forbidden) else {
        return Ok(());
    };

    let eligible = eligible
        .iter()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    for cid in forbidden {
        if eligible.contains(cid.as_str()) {
            return Err(SugarSelectionPolicyValidationError::OverlappingSugarCid {
                cid: cid.clone(),
            });
        }
    }
    Ok(())
}

fn is_blake3_512_cid(s: &str) -> bool {
    sugar_canonicalizer::is_blake3_512_cid(s)
}

// ============================================================
// End manual extension block -- PolicyMemento family (#798)
// ============================================================

// ============================================================
// End manual extension block -- observation-wrapper memento (#804)
// ============================================================

// ============================================================
// End manual extension block -- promotion-decision memento
// ============================================================

// ============================================================
// End manual extension block -- EffectOccurrence substrate object
// ============================================================

// ============================================================
// Manual extension: CatalogSnapshotMemento substrate primitive (#802)
// Source of truth:
//   protocol/specs/2026-05-13-catalog-snapshot-memento.md §1, §3
//
// This block intentionally models only the durable artifact and the
// canonical set-CID helper. Snapshot replay and catalog pull-protocols
// live outside this crate.
//
// Per JCS canonicalization, serde field order MUST equal alphabetical
// order. The struct fields below are ordered exactly as the spec lists
// the canonical map keys.
// ============================================================

/// The catalog namespace named by a `CatalogSnapshotMemento`.
///
/// Wire format: a bare JSON string. The three reserved labels are carried
/// as named variants; extension catalogs round-trip through `Namespaced`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum CatalogKind {
    ConceptShapes,
    Policy,
    Realization,
    /// Namespaced extension catalog kind, e.g. `acme:custom-shapes`.
    /// MUST be of the form `<namespace>:<kind>` with both segments
    /// non-empty. Bare unknowns fail closed at deserialization.
    Namespaced(String),
}

impl TryFrom<String> for CatalogKind {
    type Error = CatalogKindError;

    fn try_from(s: String) -> Result<Self, Self::Error> {
        match s.as_str() {
            "concept-shapes" => Ok(CatalogKind::ConceptShapes),
            "policy" => Ok(CatalogKind::Policy),
            "realization" => Ok(CatalogKind::Realization),
            _ => match s.split_once(':') {
                // Spec: extension labels are `<namespace>:<kind>` with
                // EXACTLY one colon, both segments non-empty.
                Some((ns, kind)) if !ns.is_empty() && !kind.is_empty() && !kind.contains(':') => {
                    Ok(CatalogKind::Namespaced(s))
                }
                _ => Err(CatalogKindError { raw: s }),
            },
        }
    }
}

// ============================================================
// Manual extension: canonicalization-profile memento (#803)
// Source of truth:
//   protocol/specs/2026-05-13-canonicalization-profile-memento.md §1
//
// This block adds the substrate-only declaration shape for
// CanonicalizationProfileMemento. It intentionally does not execute,
// parse, or validate any canonicalization rule language. Rule descriptors
// declare documented behavior by id/version and optional payload CIDs;
// higher layers decide whether and how to run those rules.
//
// Per JCS canonicalization (2026-04-30-canonicalization-grammar.md),
// serde field order MUST equal the locked alphabetical order from the
// spec §1 inside each object. Optional rule fields are omitted from the
// serialized JSON when None. Required rule lists are emitted as arrays,
// including empty arrays.
// ============================================================

/// Scope of a canonicalization profile.
///
/// Wire format: a bare JSON string. Bare unknowns fail closed at
/// deserialization; namespaced extensions (`<namespace>:<kind>`) are
/// carried as `Namespaced(String)` per the spec §3 namespaced-extensions
/// rule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum CanonicalizationProfileKind {
    IrFormula,
    ConceptShape,
    FunctionContract,
    Namespaced(String),
}

impl TryFrom<String> for CanonicalizationProfileKind {
    type Error = CanonicalizationExtensionError;

    fn try_from(s: String) -> Result<Self, Self::Error> {
        match s.as_str() {
            "ir-formula" => Ok(CanonicalizationProfileKind::IrFormula),
            "concept-shape" => Ok(CanonicalizationProfileKind::ConceptShape),
            "function-contract" => Ok(CanonicalizationProfileKind::FunctionContract),
            _ => match s.split_once(':') {
                // Spec §3: extension labels are `<namespace>:<kind>` with
                // EXACTLY one colon, both segments non-empty.
                Some((ns, kind)) if !ns.is_empty() && !kind.is_empty() && !kind.contains(':') => {
                    Ok(CanonicalizationProfileKind::Namespaced(s))
                }
                _ => Err(CanonicalizationExtensionError {
                    field: "profile_kind",
                    raw: s,
                }),
            },
        }
    }
}

impl From<CatalogKind> for String {
    fn from(k: CatalogKind) -> String {
        match k {
            CatalogKind::ConceptShapes => "concept-shapes".to_string(),
            CatalogKind::Policy => "policy".to_string(),
            CatalogKind::Realization => "realization".to_string(),
            CatalogKind::Namespaced(s) => s,
        }
    }
}

impl From<CanonicalizationProfileKind> for String {
    fn from(k: CanonicalizationProfileKind) -> String {
        match k {
            CanonicalizationProfileKind::IrFormula => "ir-formula".to_string(),
            CanonicalizationProfileKind::ConceptShape => "concept-shape".to_string(),
            CanonicalizationProfileKind::FunctionContract => "function-contract".to_string(),
            CanonicalizationProfileKind::Namespaced(s) => s,
        }
    }
}

/// Error returned when a `CatalogKind` string is neither a canonical
/// value nor a well-formed namespaced extension. The spec requires
/// extensions to use `<namespace>:<kind>` form; bare unknowns fail closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CatalogKindError {
    pub raw: String,
}

impl std::fmt::Display for CatalogKindError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unrecognized catalog kind {:?}: not a canonical value (concept-shapes / policy / realization) and not a well-formed `<namespace>:<kind>` extension",
            self.raw
        )
    }
}

/// Behavior when a canonicalizer sees an equivalence class it does not
/// understand.
///
/// Wire format: a bare JSON string. Bare unknowns fail closed at
/// deserialization; namespaced extensions are carried as
/// `Namespaced(String)`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum UnsupportedEquivalencePolicy {
    Preserve,
    Refuse,
    Namespaced(String),
}

impl TryFrom<String> for UnsupportedEquivalencePolicy {
    type Error = CanonicalizationExtensionError;

    fn try_from(s: String) -> Result<Self, Self::Error> {
        match s.as_str() {
            "preserve" => Ok(UnsupportedEquivalencePolicy::Preserve),
            "refuse" => Ok(UnsupportedEquivalencePolicy::Refuse),
            _ => match s.split_once(':') {
                // Spec §3: extension labels are `<namespace>:<kind>` with
                // EXACTLY one colon, both segments non-empty.
                Some((ns, kind)) if !ns.is_empty() && !kind.is_empty() && !kind.contains(':') => {
                    Ok(UnsupportedEquivalencePolicy::Namespaced(s))
                }
                _ => Err(CanonicalizationExtensionError {
                    field: "unsupported_equivalence_policy",
                    raw: s,
                }),
            },
        }
    }
}

impl From<UnsupportedEquivalencePolicy> for String {
    fn from(p: UnsupportedEquivalencePolicy) -> String {
        match p {
            UnsupportedEquivalencePolicy::Preserve => "preserve".to_string(),
            UnsupportedEquivalencePolicy::Refuse => "refuse".to_string(),
            UnsupportedEquivalencePolicy::Namespaced(s) => s,
        }
    }
}

/// Returned when a `CanonicalizationProfileKind` or
/// `UnsupportedEquivalencePolicy` string is neither a reserved value nor a
/// well-formed `<namespace>:<kind>` extension. Per spec §3 +
/// admissibility-spine namespaced-extensions rule, bare unknowns fail
/// closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalizationExtensionError {
    pub field: &'static str,
    pub raw: String,
}

impl std::fmt::Display for CanonicalizationExtensionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unrecognized {} value {:?}: not a reserved label and not a well-formed `<namespace>:<kind>` extension",
            self.field, self.raw
        )
    }
}

impl std::error::Error for CatalogKindError {}

/// The first snapshot for a catalog kind.
///
/// Locked JCS key order:
///   admitted_member_set_cid, catalog_kind, catalog_root_cid, genesis,
///   policy_set_cid, promotion_decision_set_cid, provenance_cid,
///   signature, signer_cid, snapshot_time.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CatalogSnapshotGenesis {
    #[serde(rename = "admitted_member_set_cid")]
    pub admitted_member_set_cid: Cid,
    #[serde(rename = "catalog_kind")]
    pub catalog_kind: CatalogKind,
    #[serde(rename = "catalog_root_cid")]
    pub catalog_root_cid: Cid,
    pub genesis: String,
    #[serde(rename = "policy_set_cid")]
    pub policy_set_cid: Cid,
    #[serde(rename = "promotion_decision_set_cid")]
    pub promotion_decision_set_cid: Cid,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: Cid,
    pub signature: String,
    #[serde(rename = "signer_cid")]
    pub signer_cid: Cid,
    #[serde(rename = "snapshot_time")]
    pub snapshot_time: String,
}

/// A non-genesis snapshot for a catalog kind.
///
/// Locked JCS key order:
///   admitted_member_set_cid, catalog_kind, catalog_root_cid,
///   parent_snapshot_cid, policy_set_cid, promotion_decision_set_cid,
///   provenance_cid, signature, signer_cid, snapshot_time.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CatalogSnapshotSuccessor {
    #[serde(rename = "admitted_member_set_cid")]
    pub admitted_member_set_cid: Cid,
    #[serde(rename = "catalog_kind")]
    pub catalog_kind: CatalogKind,
    #[serde(rename = "catalog_root_cid")]
    pub catalog_root_cid: Cid,
    #[serde(rename = "parent_snapshot_cid")]
    pub parent_snapshot_cid: Cid,
    #[serde(rename = "policy_set_cid")]
    pub policy_set_cid: Cid,
    #[serde(rename = "promotion_decision_set_cid")]
    pub promotion_decision_set_cid: Cid,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: Cid,
    pub signature: String,
    #[serde(rename = "signer_cid")]
    pub signer_cid: Cid,
    #[serde(rename = "snapshot_time")]
    pub snapshot_time: String,
}

/// The catalog snapshot memento union.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum CatalogSnapshotMemento {
    Genesis(CatalogSnapshotGenesis),
    Successor(CatalogSnapshotSuccessor),
}

/// Compute the canonical CID for a set field in a catalog snapshot.
///
/// The input slice is sorted in-place by the UTF-8 bytes of each CID
/// string, encoded as a JCS JSON array of strings, then hashed with the
/// repository's BLAKE3-512 self-identifying CID helper.
///
/// Per the spec these are SET CIDs: duplicate strings violate the set
/// abstraction and MUST be rejected before hashing. The function takes
/// `&[Cid]` (immutable) and returns `Err(DuplicateInSetError)` when any
/// CID appears more than once. The caller may not assume the input slice
/// is mutated.
pub fn canonical_set_cid(cids: &[Cid]) -> Result<Cid, DuplicateInSetError> {
    let mut sorted: Vec<&Cid> = cids.iter().collect();
    sorted.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));

    // Reject duplicates: a set cannot contain the same element twice. After
    // sorting, duplicates appear as adjacent pairs.
    for window in sorted.windows(2) {
        if window[0] == window[1] {
            return Err(DuplicateInSetError {
                cid: window[0].clone(),
            });
        }
    }

    let values = sorted
        .iter()
        .map(|cid| sugar_canonicalizer::Value::string((*cid).clone()))
        .collect();
    let jcs = sugar_canonicalizer::encode_jcs(&sugar_canonicalizer::Value::array(values));
    Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
}

/// Error returned when `canonical_set_cid` finds a duplicate CID in its
/// input. Per spec these arrays are SET CIDs; multisets are not admissible.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DuplicateInSetError {
    /// The CID that appeared at least twice in the input slice.
    pub cid: Cid,
}

impl std::fmt::Display for DuplicateInSetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "duplicate CID in canonical set: {} (per spec these are set CIDs; multisets are not admissible)",
            self.cid
        )
    }
}

impl std::error::Error for DuplicateInSetError {}

// ============================================================
// End manual extension block -- CatalogSnapshotMemento (#802)
// ============================================================

impl std::error::Error for CanonicalizationExtensionError {}

/// A documented canonicalization behavior declaration.
///
/// Locked JCS key order:
///   description, language_signature_cid (omitted when absent),
///   reference_cid (omitted when absent), rule_id,
///   rule_payload (omitted when absent), rule_version.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CanonicalizationRuleDescriptor {
    pub description: String,
    #[serde(rename = "language_signature_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub language_signature_cid: Option<String>,
    #[serde(rename = "reference_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reference_cid: Option<String>,
    #[serde(rename = "rule_id")]
    pub rule_id: String,
    #[serde(rename = "rule_payload")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rule_payload: Option<serde_json::Value>,
    #[serde(rename = "rule_version")]
    pub rule_version: String,
}

/// Declaration of the conservative canonicalization profile applied before
/// a substrate object is content-addressed.
///
/// Source of truth: protocol/specs/2026-05-13-canonicalization-profile-memento.md §1
///
/// Locked JCS key order:
///   alpha_equivalence_rules, binder_normalization_rules,
///   formal_name_normalization_rules, formula_canonicalization_rules,
///   profile_kind, profile_version, provenance_cid, sort_alias_rules,
///   unsupported_equivalence_policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CanonicalizationProfileMemento {
    #[serde(rename = "alpha_equivalence_rules")]
    pub alpha_equivalence_rules: Vec<CanonicalizationRuleDescriptor>,
    #[serde(rename = "binder_normalization_rules")]
    pub binder_normalization_rules: Vec<CanonicalizationRuleDescriptor>,
    #[serde(rename = "formal_name_normalization_rules")]
    pub formal_name_normalization_rules: Vec<CanonicalizationRuleDescriptor>,
    #[serde(rename = "formula_canonicalization_rules")]
    pub formula_canonicalization_rules: Vec<CanonicalizationRuleDescriptor>,
    #[serde(rename = "profile_kind")]
    pub profile_kind: CanonicalizationProfileKind,
    #[serde(rename = "profile_version")]
    pub profile_version: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "sort_alias_rules")]
    pub sort_alias_rules: Vec<CanonicalizationRuleDescriptor>,
    #[serde(rename = "unsupported_equivalence_policy")]
    pub unsupported_equivalence_policy: UnsupportedEquivalencePolicy,
}

// ============================================================
// End manual extension block -- canonicalization-profile memento (#803)
// ============================================================

// ============================================================
// MANUAL EXTENSION BLOCK -- DomainClaim normalization (PR-A)
// Source of truth:
//   protocol/specs/2026-05-13-domain-claim-normalization.md §1
//
// The canonical wire-form `k(I) = t` surface for the substrate's
// verifier. Every memento type that can be verified projects onto a
// `DomainClaim` via an `Into<DomainClaim>` impl. The verifier consumes
// only `DomainClaim`s; per-memento-type dispatch moves out of the
// verifier into thin From-impls.
//
// NOTE ON NAMING COLLISION: a `DomainClaim` type also exists in
// `libsugar::core::types`. That type is the IN-MEMORY AGGREGATE used
// by libsugar primitives (`compose`, `address`, `discharge`).
// The type defined here is the WIRE FORM. The two coexist; see spec §0.1
// and the PR roadmap (§6, PR-D considers renaming the libsugar one).
//
// Per JCS canonicalization (2026-04-30-canonicalization-grammar.md),
// serde field order MUST equal alphabetical order. Optional fields are
// omitted from the serialized JSON when None.
//
// The `signature` field is REQUIRED in the wire form but is REPLACED by
// the empty string when computing the CID-determining bytes (signer-
// independent addressing). The CID computation itself lives in
// `sugar-claim-envelope` (this crate has no JCS encoder).
// ============================================================

/// The trichotomy verdict kind for a `DomainClaim`. Exactly one of three.
///
/// Source of truth: spec §1.
///
/// - `Exact`: `k(I) = t` with `loss_record` empty in every dimension.
/// - `LoudlyBoundedLossy`: `k(I) = t` modulo the loss bounded by `loss_record`.
///   `loss_record` is non-empty in at least one dimension.
/// - `Refuse`: `k(I)` cannot be shown to equal `t` under any tractable
///   loss-record. `refusal_reason` is required.
///
/// Serializes as the kebab-case wire strings `"exact"`,
/// `"loudly-bounded-lossy"`, `"refuse"`, matching
/// `ConceptSiteMemento.discharge.verdict` exactly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum VerdictKind {
    #[serde(rename = "exact")]
    Exact,
    #[serde(rename = "loudly-bounded-lossy")]
    LoudlyBoundedLossy,
    #[serde(rename = "refuse")]
    Refuse,
}

/// The verdict body of a `DomainClaim`.
///
/// Locked JCS key order: `discharge_receipt_cid` (omitted when absent),
/// `kind`, `loss_record`, `refusal_reason` (omitted when absent).
///
/// Consistency invariants (spec §1.2) -- enforced by validators, not by
/// serde:
///   * `kind == Exact`               => `loss_record` empty,
///                                       `discharge_receipt_cid` present,
///                                       `refusal_reason` absent.
///   * `kind == LoudlyBoundedLossy`  => `loss_record` non-empty,
///                                       `discharge_receipt_cid` present,
///                                       `refusal_reason` absent.
///   * `kind == Refuse`              => `discharge_receipt_cid` absent,
///                                       `refusal_reason` present.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VerdictBody {
    #[serde(rename = "discharge_receipt_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub discharge_receipt_cid: Option<String>,
    pub kind: VerdictKind,
    #[serde(rename = "loss_record")]
    pub loss_record: LossRecord,
    #[serde(rename = "refusal_reason")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refusal_reason: Option<String>,
}

/// Provenance metadata for a `DomainClaim`.
///
/// Lean by design: the rich provenance lives on the source memento. The
/// `DomainClaim` carries only the minimum required for the verifier to
/// record who staked which claim and when.
///
/// Locked JCS key order: `declared_at`, `signer`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DomainClaimProvenance {
    #[serde(rename = "declared_at")]
    pub declared_at: String,
    pub signer: String,
}

/// The canonical wire-form `k(I) = t` surface of the substrate.
///
/// Source of truth: protocol/specs/2026-05-13-domain-claim-normalization.md §1
///
/// Locked JCS key order (alphabetical):
///   `input_cid`, `kind`, `kit_cid`, `provenance`, `signature`, `truth_cid`,
///   `verdict`.
///
/// The CID-determining bytes are JCS(claim with `signature` replaced by the
/// empty string) -- see spec §3.1. CID computation lives in
/// `sugar-claim-envelope`.
///
/// Wire-name semantics (spec §1.1):
///   * `kit_cid` = `k`, the operation that produced the claim.
///   * `input_cid` = `I`, the artifact the operation was applied to.
///   * `truth_cid` = `t`, the canonical truth claim (concept, target source, ...).
///
/// `kind` is always `"domain-claim"`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DomainClaim {
    #[serde(rename = "input_cid")]
    pub input_cid: String,
    pub kind: String,
    #[serde(rename = "kit_cid")]
    pub kit_cid: String,
    pub provenance: DomainClaimProvenance,
    pub signature: String,
    #[serde(rename = "truth_cid")]
    pub truth_cid: String,
    pub verdict: VerdictBody,
}

impl DomainClaim {
    /// The canonical `kind` discriminator for a `DomainClaim` wire object.
    pub const KIND: &'static str = "domain-claim";

    /// Construct an unsigned `DomainClaim`. The `signature` field is set
    /// to the empty string; envelope-layer signers fill it in at mint
    /// time. The CID-determining bytes treat the empty-string signature
    /// as the elided placeholder (spec §3.1).
    pub fn unsigned(
        kit_cid: String,
        input_cid: String,
        truth_cid: String,
        verdict: VerdictBody,
        provenance: DomainClaimProvenance,
    ) -> Self {
        Self {
            input_cid,
            kind: Self::KIND.to_string(),
            kit_cid,
            provenance,
            signature: String::new(),
            truth_cid,
            verdict,
        }
    }
}

/// Errors that may occur projecting a memento onto the wire-form `DomainClaim`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DomainClaimConversionError {
    /// The source memento carries a verdict string not in the trichotomy.
    /// This indicates a bug in the source-memento validator (spec §2.4).
    InvalidVerdictString(String),
    /// A `RealizationDesugaringMemento` was offered standalone (not via a
    /// citing `ConceptSiteMemento`). Standalone realizations are catalog
    /// entries and are not directly verifiable through the `DomainClaim`
    /// surface (spec §2.2).
    StandaloneRealization,
    /// A bare `FunctionContractMemento` was offered directly to the verifier
    /// surface. Bare contracts have no inline discharge and MUST be wrapped
    /// in a `ConceptSiteMemento` binding or `CompoundContractMemento` (PR #716)
    /// before they can be projected onto `DomainClaim` (spec §2.3).
    UnboundContract,
}

impl std::fmt::Display for DomainClaimConversionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidVerdictString(s) => write!(
                f,
                "invalid verdict string on source memento: {s:?} \
                 (expected one of \"exact\", \"loudly-bounded-lossy\", \"refuse\")"
            ),
            Self::StandaloneRealization => write!(
                f,
                "RealizationDesugaringMemento is standalone (not cited by a \
                 ConceptSiteMemento); standalone realizations are catalog \
                 entries and do not project directly onto DomainClaim"
            ),
            Self::UnboundContract => write!(
                f,
                "FunctionContractMemento is unbound: bare contracts have no \
                 inline discharge and must be wrapped in a ConceptSiteMemento \
                 or CompoundContractMemento before projecting onto DomainClaim \
                 (spec §2.3)"
            ),
        }
    }
}

impl std::error::Error for DomainClaimConversionError {}

// ============================================================
// End manual extension block -- DomainClaim normalization (PR-A)
// ============================================================

// ============================================================
// MANUAL EXTENSION BLOCK -- ObligationReceiptMemento substrate (#800)
// Source of truth:
//   protocol/specs/2026-05-13-obligation-receipt-memento.md §1, §3.7
//
// This is a substrate-only outcome record. It describes a backend result
// after that backend has run; it does not invoke solvers, parse backend
// artifacts, or encode promotion/admission policy.
//
// Optional CID fields are explicit JSON nulls when absent so the durable
// wire shape is stable. Serde field order is locked to the JCS alphabetical
// key order used for CID construction.
// ============================================================

/// A durable substrate record for one proof-obligation backend outcome.
///
/// Locked JCS key order:
///   `artifact_cids`, `backend_cid`, `backend_version`,
///   `counterexample_cid`, `input_formula_cid`, `model_or_trace_cid`,
///   `obligation_cid`, `provenance_cid`, `receipt_kind`,
///   `tactic_script_cid`, `verdict`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObligationReceiptMemento {
    /// Durable proof, witness, log, transcript, or related artifact CIDs.
    #[serde(rename = "artifact_cids")]
    pub artifact_cids: Vec<String>,
    /// Backend, solver, checker, tactic engine, or verifier-stage CID.
    #[serde(rename = "backend_cid")]
    pub backend_cid: String,
    /// Backend-reported version string.
    #[serde(rename = "backend_version")]
    pub backend_version: String,
    /// Counterexample artifact CID when this is a counterexample receipt.
    #[serde(rename = "counterexample_cid")]
    pub counterexample_cid: Option<String>,
    /// CID of the canonical formula handed to the backend.
    #[serde(rename = "input_formula_cid")]
    pub input_formula_cid: String,
    /// Optional model, proof trace, partial trace, log, or transcript CID.
    #[serde(rename = "model_or_trace_cid")]
    pub model_or_trace_cid: Option<String>,
    /// CID of the obligation whose outcome is recorded.
    #[serde(rename = "obligation_cid")]
    pub obligation_cid: String,
    /// CID of the receipt-production provenance record.
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    /// One of the canonical receipt kinds in §3.7.
    #[serde(rename = "receipt_kind")]
    pub receipt_kind: String,
    /// Tactic or proof-script artifact CID when this is a tactic receipt.
    #[serde(rename = "tactic_script_cid")]
    pub tactic_script_cid: Option<String>,
    /// Backend or synthesis verdict string.
    pub verdict: String,
}

/// Validation failures for the §3.7 receipt-kind, verdict, and artifact matrix.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvalidReceiptError {
    /// The receipt kind has no known matrix row in this substrate crate.
    UnknownReceiptKind(String),
    /// The verdict is not allowed for this receipt kind.
    InvalidVerdictForKind {
        receipt_kind: String,
        verdict: String,
    },
    /// A CID field required by the matrix is absent.
    MissingRequiredCidField {
        receipt_kind: String,
        field: &'static str,
    },
    /// A CID field forbidden by the matrix is present.
    ForbiddenCidField {
        receipt_kind: String,
        field: &'static str,
    },
    /// `backend-disagreement` requires citations to the disagreeing receipts.
    MissingDisagreementArtifacts,
}

impl std::fmt::Display for InvalidReceiptError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownReceiptKind(kind) => {
                write!(f, "unknown obligation receipt kind: {kind:?}")
            }
            Self::InvalidVerdictForKind {
                receipt_kind,
                verdict,
            } => write!(
                f,
                "invalid obligation receipt verdict {verdict:?} for receipt_kind {receipt_kind:?}"
            ),
            Self::MissingRequiredCidField {
                receipt_kind,
                field,
            } => write!(
                f,
                "missing required CID field {field:?} for receipt_kind {receipt_kind:?}"
            ),
            Self::ForbiddenCidField {
                receipt_kind,
                field,
            } => write!(
                f,
                "forbidden CID field {field:?} is present for receipt_kind {receipt_kind:?}"
            ),
            Self::MissingDisagreementArtifacts => write!(
                f,
                "backend-disagreement receipts require non-empty artifact_cids citing the disagreeing receipts"
            ),
        }
    }
}

// ============================================================
// NOTE: Manual extension block -- PipelineMemento and RunMemento (#799)
// ============================================================
//
// Generic replayable run graph substrate per
// protocol/specs/2026-05-13-pipeline-runmemento.md §1.
//
// This block defines durable artifact shapes only. It intentionally does not
// execute pipelines, schedule runs, resolve CIDs, or replay stage receipts.
//
// Key-order rule: struct field names mirror the CDDL key names exactly in
// locked JCS alphabetical order.
//
// TODO(#792): Express ProofRunMemento as the verifier PipelineMemento profile.

/// The `pipeline_kind` scalar for a `PipelineMemento`.
///
/// Known pipeline kinds are reserved by the generic spec. Namespaced extension
/// kinds are represented as `Namespaced("<namespace>:<kind>")` so this
/// substrate type can carry profile-defined pipelines without hard-coding
/// registry support here. Bare unknowns fail closed at deserialization
/// per spec §3 + admissibility-spine namespaced-extensions rule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub enum PipelineKind {
    Bind,
    Compose,
    Link,
    Promotion,
    Realization,
    Transport,
    Verifier,
    Namespaced(String),
}

impl TryFrom<String> for PipelineKind {
    type Error = PipelineKindError;

    fn try_from(s: String) -> Result<Self, Self::Error> {
        match s.as_str() {
            "bind" => Ok(PipelineKind::Bind),
            "compose" => Ok(PipelineKind::Compose),
            "link" => Ok(PipelineKind::Link),
            "promotion" => Ok(PipelineKind::Promotion),
            "realization" => Ok(PipelineKind::Realization),
            "transport" => Ok(PipelineKind::Transport),
            "verifier" => Ok(PipelineKind::Verifier),
            _ => match s.split_once(':') {
                // Spec: extension labels are `<namespace>:<kind>` with
                // EXACTLY one colon. `a:b:c` is not a valid namespaced
                // extension; both segments must be non-empty AND the
                // kind segment must not itself contain a colon.
                Some((ns, kind)) if !ns.is_empty() && !kind.is_empty() && !kind.contains(':') => {
                    Ok(PipelineKind::Namespaced(s))
                }
                _ => Err(PipelineKindError { raw: s }),
            },
        }
    }
}

impl From<PipelineKind> for String {
    fn from(kind: PipelineKind) -> String {
        match kind {
            PipelineKind::Bind => "bind".to_string(),
            PipelineKind::Compose => "compose".to_string(),
            PipelineKind::Link => "link".to_string(),
            PipelineKind::Promotion => "promotion".to_string(),
            PipelineKind::Realization => "realization".to_string(),
            PipelineKind::Transport => "transport".to_string(),
            PipelineKind::Verifier => "verifier".to_string(),
            PipelineKind::Namespaced(s) => s,
        }
    }
}

/// Returned when a `pipeline_kind` string is neither a canonical
/// pipeline (bind / compose / link / promotion / realization / transport /
/// verifier) nor a well-formed `<namespace>:<kind>` extension. Per spec
/// §3 + admissibility-spine namespaced-extensions rule, bare unknowns
/// MUST fail closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipelineKindError {
    pub raw: String,
}

impl std::fmt::Display for PipelineKindError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unrecognized pipeline_kind {:?}: not a canonical pipeline and not a well-formed `<namespace>:<kind>` extension",
            self.raw
        )
    }
}

impl std::error::Error for PipelineKindError {}

/// The terminal `verdict` scalar for a `RunMemento`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RunVerdict {
    #[serde(rename = "failed")]
    Failed,
    #[serde(rename = "refused")]
    Refused,
    #[serde(rename = "succeeded")]
    Succeeded,
}

/// A pipeline vocabulary memento.
///
/// Locked JCS key order:
///   accepted_input_kinds, emitted_output_kinds, failure_kinds,
///   pipeline_kind, pipeline_version, provenance_cid, stage_vocabulary
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PipelineMemento {
    #[serde(rename = "accepted_input_kinds")]
    pub accepted_input_kinds: Vec<String>,
    #[serde(rename = "emitted_output_kinds")]
    pub emitted_output_kinds: Vec<String>,
    #[serde(rename = "failure_kinds")]
    pub failure_kinds: Vec<String>,
    #[serde(rename = "pipeline_kind")]
    pub pipeline_kind: PipelineKind,
    #[serde(rename = "pipeline_version")]
    pub pipeline_version: String,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "stage_vocabulary")]
    pub stage_vocabulary: Vec<String>,
}

/// A generic replayable run memento.
///
/// Locked JCS key order:
///   input_cids, output_cids, pipeline_cid, plugin_registry_cid,
///   predecessor_run_cids, provenance_cid, stage_receipt_cids, verdict
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RunMemento {
    #[serde(rename = "input_cids")]
    pub input_cids: Vec<String>,
    #[serde(rename = "output_cids")]
    pub output_cids: Vec<String>,
    #[serde(rename = "pipeline_cid")]
    pub pipeline_cid: String,
    #[serde(rename = "plugin_registry_cid")]
    pub plugin_registry_cid: String,
    #[serde(rename = "predecessor_run_cids")]
    pub predecessor_run_cids: Vec<String>,
    #[serde(rename = "provenance_cid")]
    pub provenance_cid: String,
    #[serde(rename = "stage_receipt_cids")]
    pub stage_receipt_cids: Vec<String>,
    pub verdict: RunVerdict,
}

/// Generic validation failures for `RunMemento` and `PipelineMemento`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidationError {
    /// The run does not provide one stage receipt CID per pipeline stage.
    StageReceiptLengthMismatch { expected: usize, actual: usize },
    /// A pipeline / run array declared `[+ ...]` in the spec is empty.
    /// `field` names which array.
    EmptyRequiredArray { field: &'static str },
}

impl std::fmt::Display for ValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::StageReceiptLengthMismatch { expected, actual } => write!(
                f,
                "stage_receipt_cids length mismatch: expected {expected}, got {actual}"
            ),
            Self::EmptyRequiredArray { field } => write!(
                f,
                "{field} is empty (spec §1 CDDL requires [+ ...] non-empty)"
            ),
        }
    }
}

impl std::error::Error for InvalidReceiptError {}

impl ObligationReceiptMemento {
    /// Validate the normative §3.7 receipt-kind × verdict × artifact matrix.
    ///
    /// This method deliberately stays substrate-only: it checks field
    /// presence and allowed labels, but it does not invoke solvers or inspect
    /// backend-specific artifact formats.
    pub fn validate(&self) -> Result<(), InvalidReceiptError> {
        match self.receipt_kind.as_str() {
            "discharged" => {
                self.require_verdict_in(&["unsat", "sat"])?;
                self.forbid_cid("counterexample_cid", self.counterexample_cid.is_some())?;
                if self.verdict == "sat" {
                    self.require_cid("model_or_trace_cid", self.model_or_trace_cid.is_some())?;
                }
            }
            "counterexample" => {
                self.require_verdict_in(&["sat"])?;
                self.require_cid("counterexample_cid", self.counterexample_cid.is_some())?;
            }
            "tactic" => {
                self.require_verdict_in(&["unsat", "unknown"])?;
                self.require_cid("tactic_script_cid", self.tactic_script_cid.is_some())?;
                self.forbid_cid("counterexample_cid", self.counterexample_cid.is_some())?;
            }
            "inconclusive" => {
                self.require_verdict_in(&[
                    "unknown",
                    "timeout",
                    "budget-exhausted",
                    "backend-disagreement",
                ])?;
                if self.verdict == "backend-disagreement" && self.artifact_cids.is_empty() {
                    return Err(InvalidReceiptError::MissingDisagreementArtifacts);
                }
                self.forbid_cid("counterexample_cid", self.counterexample_cid.is_some())?;
                self.forbid_cid("tactic_script_cid", self.tactic_script_cid.is_some())?;
            }
            "refused" => {
                if self.verdict != "malformed-artifact" && !is_namespaced_extension(&self.verdict) {
                    return Err(self.invalid_verdict());
                }
                self.forbid_cid("counterexample_cid", self.counterexample_cid.is_some())?;
                self.forbid_cid("model_or_trace_cid", self.model_or_trace_cid.is_some())?;
                self.forbid_cid("tactic_script_cid", self.tactic_script_cid.is_some())?;
            }
            other => {
                return Err(InvalidReceiptError::UnknownReceiptKind(other.to_string()));
            }
        }
        Ok(())
    }

    fn require_verdict_in(&self, allowed: &[&str]) -> Result<(), InvalidReceiptError> {
        if allowed.iter().any(|allowed| *allowed == self.verdict) {
            Ok(())
        } else {
            Err(self.invalid_verdict())
        }
    }

    fn require_cid(&self, field: &'static str, present: bool) -> Result<(), InvalidReceiptError> {
        if present {
            Ok(())
        } else {
            Err(InvalidReceiptError::MissingRequiredCidField {
                receipt_kind: self.receipt_kind.clone(),
                field,
            })
        }
    }

    fn forbid_cid(&self, field: &'static str, present: bool) -> Result<(), InvalidReceiptError> {
        if present {
            Err(InvalidReceiptError::ForbiddenCidField {
                receipt_kind: self.receipt_kind.clone(),
                field,
            })
        } else {
            Ok(())
        }
    }

    fn invalid_verdict(&self) -> InvalidReceiptError {
        InvalidReceiptError::InvalidVerdictForKind {
            receipt_kind: self.receipt_kind.clone(),
            verdict: self.verdict.clone(),
        }
    }
}

impl std::error::Error for ValidationError {}

impl PipelineMemento {
    /// Check load-time invariants per spec §1.1.
    ///
    /// All four arrays are declared `[+ ...]` in the CDDL:
    /// `accepted_input_kinds`, `emitted_output_kinds`, `failure_kinds`,
    /// `stage_vocabulary`. An empty pipeline cannot accept any input,
    /// emit any output, fail in any declared way, or run any stage; it
    /// is not a valid pipeline declaration.
    pub fn validate(&self) -> Result<(), ValidationError> {
        if self.accepted_input_kinds.is_empty() {
            return Err(ValidationError::EmptyRequiredArray {
                field: "accepted_input_kinds",
            });
        }
        if self.emitted_output_kinds.is_empty() {
            return Err(ValidationError::EmptyRequiredArray {
                field: "emitted_output_kinds",
            });
        }
        if self.failure_kinds.is_empty() {
            return Err(ValidationError::EmptyRequiredArray {
                field: "failure_kinds",
            });
        }
        if self.stage_vocabulary.is_empty() {
            return Err(ValidationError::EmptyRequiredArray {
                field: "stage_vocabulary",
            });
        }
        Ok(())
    }
}

impl RunMemento {
    /// Validate generic run shape against the resolved pipeline vocabulary.
    ///
    /// This substrate method only checks invariants available from the two
    /// mementos themselves. CID resolution, plugin registry checks, stage
    /// receipt body checks, and replay are higher-layer responsibilities.
    ///
    /// Enforces:
    /// 1. The pipeline itself validates (non-empty required arrays).
    /// 2. `input_cids` is non-empty (spec §1.2 CDDL `[+ cid]`).
    /// 3. `stage_receipt_cids` is non-empty (spec §1.2 CDDL `[+ cid]`).
    /// 4. `stage_receipt_cids.len() == pipeline.stage_vocabulary.len()`.
    pub fn validate(&self, pipeline: &PipelineMemento) -> Result<(), ValidationError> {
        pipeline.validate()?;

        if self.input_cids.is_empty() {
            return Err(ValidationError::EmptyRequiredArray {
                field: "input_cids",
            });
        }
        if self.stage_receipt_cids.is_empty() {
            return Err(ValidationError::EmptyRequiredArray {
                field: "stage_receipt_cids",
            });
        }

        let expected = pipeline.stage_vocabulary.len();
        let actual = self.stage_receipt_cids.len();

        if actual != expected {
            return Err(ValidationError::StageReceiptLengthMismatch { expected, actual });
        }

        Ok(())
    }
}

fn is_namespaced_extension(value: &str) -> bool {
    let Some((namespace, name)) = value.split_once('/') else {
        return false;
    };
    !namespace.is_empty() && !name.is_empty()
}

// ============================================================
// End manual extension block -- ObligationReceiptMemento substrate (#800)
// ============================================================
// ============================================================

// ============================================================
// MANUAL EXTENSION BLOCK -- CompositionBoundaryMemento
// Source of truth:
//   protocol/specs/2026-05-13-composition-refusal-memento.md §1, §4
//
// This block adds the canonical CCP refusal artifact. CID identity is
// JCS(header with `cid` elided); envelope and metadata never participate
// in the refusal CID.
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompositionRefusalEnvelope {
    #[serde(rename = "declaredAt")]
    pub declared_at: String,
    pub signature: String,
    pub signer: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BlockingEffect {
    #[serde(rename = "atom_cid")]
    pub atom_cid: String,
    pub classification: String,
    #[serde(rename = "discharge_key")]
    pub discharge_key: String,
    #[serde(rename = "occurrence_kind")]
    pub occurrence_kind: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IncompatiblePair {
    #[serde(rename = "atom_a_cid")]
    pub atom_a_cid: String,
    #[serde(rename = "atom_b_cid")]
    pub atom_b_cid: String,
    #[serde(rename = "effect_a")]
    pub effect_a: String,
    #[serde(rename = "effect_b")]
    pub effect_b: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MissingRequirement {
    #[serde(rename = "expected_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected_cid: Option<String>,
    #[serde(rename = "memento_kind")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub memento_kind: Option<String>,
    pub reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
}

/// Header layer for a CCP refusal.
///
/// Locked JCS key order (alphabetical):
///   atoms_cids, blocking_effects, ccp_version, cid, compose_input_cid,
///   effect_occurrences, effect_set_cids, failure_detail, failure_kind,
///   incompatible_pair, kind, missing_memento_requirements, schemaVersion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompositionRefusalHeader {
    #[serde(rename = "atoms_cids")]
    pub atoms_cids: Vec<String>,
    #[serde(rename = "blocking_effects")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub blocking_effects: Option<Vec<BlockingEffect>>,
    #[serde(rename = "ccp_version")]
    pub ccp_version: String,
    /// DERIVED: BLAKE3-512 over JCS(header) with `cid` elided.
    pub cid: String,
    #[serde(rename = "compose_input_cid")]
    pub compose_input_cid: String,
    #[serde(rename = "effect_occurrences")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub effect_occurrences: Option<Vec<EffectOccurrence>>,
    #[serde(rename = "effect_set_cids")]
    pub effect_set_cids: Vec<String>,
    #[serde(rename = "failure_detail")]
    pub failure_detail: String,
    /// Open string taxonomy from the composition-refusal spec.
    ///
    /// For `target-compile-failure`, `failure_detail` carries compiler stderr.
    /// For `target-behavior-divergence`, `failure_detail` carries the
    /// expected-vs-observed comparison.
    #[serde(rename = "failure_kind")]
    pub failure_kind: String,
    #[serde(rename = "incompatible_pair")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub incompatible_pair: Option<IncompatiblePair>,
    pub kind: String,
    #[serde(rename = "missing_memento_requirements")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub missing_memento_requirements: Option<Vec<MissingRequirement>>,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompositionRefusalMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(rename = "provenance_cid")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provenance_cid: Option<String>,
    #[serde(rename = "refused_at")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refused_at: Option<String>,
    #[serde(rename = "source_url")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_url: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompositionBoundaryMemento {
    pub envelope: CompositionRefusalEnvelope,
    pub header: CompositionRefusalHeader,
    pub metadata: CompositionRefusalMetadata,
}

fn canonical_value_from_json(value: serde_json::Value) -> sugar_canonicalizer::Value {
    match value {
        serde_json::Value::Null => sugar_canonicalizer::Value::Null,
        serde_json::Value::Bool(b) => sugar_canonicalizer::Value::Bool(b),
        serde_json::Value::Number(n) => sugar_canonicalizer::Value::Integer(
            n.as_i64()
                .map(i128::from)
                .or_else(|| n.as_u64().map(i128::from))
                .expect("CompositionBoundaryMemento canonical numbers must fit i64/u64"),
        ),
        serde_json::Value::String(s) => sugar_canonicalizer::Value::String(s),
        serde_json::Value::Array(items) => sugar_canonicalizer::Value::Array(
            items
                .into_iter()
                .map(canonical_value_from_json)
                .map(std::sync::Arc::new)
                .collect(),
        ),
        serde_json::Value::Object(map) => sugar_canonicalizer::Value::Object(
            map.into_iter()
                .map(|(k, v)| (k, std::sync::Arc::new(canonical_value_from_json(v))))
                .collect(),
        ),
    }
}

pub fn composition_refusal_header_cid(header: &CompositionRefusalHeader) -> String {
    let mut value =
        serde_json::to_value(header).expect("CompositionRefusalHeader serializes to JSON");
    value
        .as_object_mut()
        .expect("CompositionRefusalHeader serializes as object")
        .remove("cid");
    let canonical = canonical_value_from_json(value);
    let bytes = sugar_canonicalizer::encode_jcs(&canonical);
    sugar_canonicalizer::blake3_512_of(bytes.as_bytes())
}

pub fn composition_refusal_compose_input_cid(
    atoms_cids: &[String],
    effect_set_cids: &[String],
    ccp_version: &str,
) -> String {
    let value = serde_json::json!({
        "atoms_cids": atoms_cids,
        "ccp_version": ccp_version,
        "effect_set_cids": effect_set_cids,
    });
    let canonical = canonical_value_from_json(value);
    let bytes = sugar_canonicalizer::encode_jcs(&canonical);
    sugar_canonicalizer::blake3_512_of(bytes.as_bytes())
}

pub fn composition_refusal_signature(
    header: &CompositionRefusalHeader,
    metadata: &CompositionRefusalMetadata,
) -> String {
    let value = serde_json::json!({
        "header": header,
        "metadata": metadata,
    });
    let canonical = canonical_value_from_json(value);
    let bytes = sugar_canonicalizer::encode_jcs(&canonical);
    format!(
        "unsigned-substrate:{}",
        sugar_canonicalizer::blake3_512_of(bytes.as_bytes())
    )
}

#[cfg(test)]
mod composition_refusal_tests {
    use super::*;

    fn cid(ch: char) -> String {
        format!("blake3-512:{}", ch.to_string().repeat(128))
    }

    fn canonical_impure_refusal() -> CompositionBoundaryMemento {
        let atoms_cids = vec![cid('a'), cid('b')];
        let effect_set_cids = vec![cid('c'), cid('d')];
        let occurrence = EffectOccurrence {
            args: serde_json::json!({"target":"stdout"}),
            discharge_key: "io:stdout".to_string(),
            locator: serde_json::json!({"atom_cid": atoms_cids[1]}),
            occurrence_kind: OccurrenceKind::Io,
            role: OccurrenceRole::Body,
            signature_cid: cid('e'),
        };
        let blocking = BlockingEffect {
            atom_cid: atoms_cids[1].clone(),
            classification: "block".to_string(),
            discharge_key: occurrence.discharge_key.clone(),
            occurrence_kind: occurrence.occurrence_kind.to_string(),
        };
        let compose_input_cid =
            composition_refusal_compose_input_cid(&atoms_cids, &effect_set_cids, "1.0.0");
        let mut header = CompositionRefusalHeader {
            atoms_cids,
            blocking_effects: Some(vec![blocking]),
            ccp_version: "1.0.0".to_string(),
            cid: String::new(),
            compose_input_cid,
            effect_occurrences: Some(vec![occurrence]),
            effect_set_cids,
            failure_detail: format!("impure atom {}", cid('b')),
            failure_kind: "impure-input".to_string(),
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
                signer: "substrate:test".to_string(),
            },
            header,
            metadata,
        }
    }

    #[test]
    fn canonical_impure_refusal_round_trips_and_recomputes_cid() {
        let refusal = canonical_impure_refusal();
        let json = serde_json::to_string(&refusal).expect("serialize refusal");
        let decoded: CompositionBoundaryMemento =
            serde_json::from_str(&json).expect("deserialize refusal");

        assert_eq!(decoded, refusal);
        assert_eq!(
            composition_refusal_header_cid(&decoded.header),
            decoded.header.cid
        );
        assert_eq!(decoded.header.failure_kind, "impure-input");
    }

    #[test]
    fn same_canonical_refusal_inputs_mint_same_cid() {
        let first = canonical_impure_refusal();
        let mut second = canonical_impure_refusal();
        second.envelope.declared_at = "2026-05-13T00:00:00Z".to_string();
        second.envelope.signer = "substrate:other".to_string();
        second.metadata.note = Some("operator note outside refusal identity".to_string());

        assert_eq!(first.header.cid, second.header.cid);
    }
}

// ============================================================
// End manual extension block -- CompositionBoundaryMemento
// ============================================================

// ============================================================
// Witness memento + memento validation.
//
// The cross-language migration receipt types (MigrateReceiptEnvelope and the
// per-language migration mementos) were removed with the concept hub: there
// is no cross-language migration; contracts meet at the callsite by EUF.
// WitnessMemento survives (witnesses are kept as signed evidence), along with
// MigrationReceiptError (the shared memento-validation error -- name retained
// for now) and the require_*/migration_cid_without_keys helpers it uses.
// ============================================================

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WitnessMemento {
    pub kind: String,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "witness_for")]
    pub witness_for: String,
    pub subject: String,
    #[serde(rename = "fixture_state_cid")]
    pub fixture_state_cid: String,
    #[serde(rename = "observed_at")]
    pub observed_at: String,
    #[serde(rename = "sample_count")]
    pub sample_count: u64,
    pub measurements: serde_json::Value,
    pub outcome: String,
    #[serde(rename = "signed_by")]
    pub signed_by: Option<String>,
    pub signature: Option<String>,
    pub cid: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MigrationReceiptError {
    message: String,
}

impl MigrationReceiptError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl std::fmt::Display for MigrationReceiptError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for MigrationReceiptError {}

impl From<serde_json::Error> for MigrationReceiptError {
    fn from(err: serde_json::Error) -> Self {
        Self::new(err.to_string())
    }
}

/// The deterministic bytes a witness signature attests: the discharge CID
/// PLUS the observation timestamp. The CID is the THEOREM-mode convergence
/// handle (byte-stable across honest re-derivation); `observed_at` is a
/// TESTIMONY-mode IO event that is NOT part of the convergence hash but MUST
/// still be sworn so it cannot be peeled off or forged. Signing `{cid,
/// observed_at}` (JCS-canonical) seals the postmark to the discharge: tamper
/// the timestamp and the signature no longer verifies, while two honest
/// provers on the same obligation land on the SAME CID regardless of WHEN
/// each observed it.
///
/// Both the mint path (`sugar-cli` `cmd_verify::mint_verification_witness`)
/// and the verify path (`sugar-cli` `witness_verify`) reconstruct these exact
/// bytes; keep this the single source of truth for the payload shape.
pub fn witness_attestation_payload(cid: &str, observed_at: &str) -> Vec<u8> {
    let value = serde_json::json!({
        "cid": cid,
        "observed_at": observed_at,
    });
    // Reuse the same JCS canonicalization the migration CID preimage uses, so
    // the attested bytes are deterministic and key-order independent.
    let canonical = migration_json_to_canonical(&value)
        .expect("witness attestation payload is a string-keyed object of strings");
    sugar_canonicalizer::encode_jcs(&canonical).into_bytes()
}

impl WitnessMemento {
    pub fn recompute_cid(&self) -> Result<String, MigrationReceiptError> {
        // The CID addresses WHAT is attested -- the observation (subject,
        // fixture, measurements, outcome). It is not the substrate's job to say
        // HOW it is attested: the signer identity and the signature bytes are
        // the attestation layer, excluded from the preimage. The same
        // observation attested by a different key is the SAME CID (same WHAT),
        // a different attestation. (Excluding only "cid" was a bug: it baked
        // the HOW into the WHAT and made a self-consistent CID impossible.)
        //
        // `observed_at` is in the SAME class as signed_by/signature: a
        // TESTIMONY-mode IO event (a clock read), not part of the DISCHARGE.
        // Baking it into the preimage made the CID a clock-address -- two
        // honest provers discharging the SAME obligation produced DIFFERENT
        // witness CIDs, so the supply-chain pin never rendezvoused (#2022
        // class). It is excluded here and instead sworn OUTSIDE the CID via
        // `witness_attestation_payload` (signature covers {cid, observed_at}).
        migration_cid_without_keys(self, &["cid", "signed_by", "signature", "observed_at"])
    }

    /// The exact bytes this witness's signature attests: {cid, observed_at}
    /// JCS-canonical. The discharge CID converges; the postmark rides sealed
    /// alongside it (see [`witness_attestation_payload`]).
    pub fn attestation_payload(&self) -> Vec<u8> {
        witness_attestation_payload(&self.cid, &self.observed_at)
    }

    pub fn validate(&self) -> Result<(), MigrationReceiptError> {
        require_kind(&self.kind, "witness")?;
        require_schema(&self.schema_version)?;
        require_non_empty(&self.witness_for, "witness_for")?;
        require_non_empty(&self.subject, "subject")?;
        require_non_empty(&self.fixture_state_cid, "fixture_state_cid")?;
        require_non_empty(&self.observed_at, "observed_at")?;
        match self.outcome.as_str() {
            "pass" | "fail" | "inconclusive" => {}
            other => {
                return Err(MigrationReceiptError::new(format!(
                    "WitnessMemento outcome {other} is not pass, fail, or inconclusive"
                )));
            }
        }
        require_matching_cid(&self.cid, self.recompute_cid()?, "WitnessMemento")
    }
}

fn require_kind(actual: &str, expected: &str) -> Result<(), MigrationReceiptError> {
    if actual == expected {
        Ok(())
    } else {
        Err(MigrationReceiptError::new(format!(
            "expected kind {expected}, got {actual}"
        )))
    }
}

fn require_schema(actual: &str) -> Result<(), MigrationReceiptError> {
    if actual == "1" {
        Ok(())
    } else {
        Err(MigrationReceiptError::new(format!(
            "expected schemaVersion 1, got {actual}"
        )))
    }
}

fn require_non_empty(value: &str, field: &str) -> Result<(), MigrationReceiptError> {
    if value.is_empty() {
        Err(MigrationReceiptError::new(format!(
            "{field} must not be empty"
        )))
    } else {
        Ok(())
    }
}

fn require_matching_cid(
    expected: &str,
    actual: String,
    context: &str,
) -> Result<(), MigrationReceiptError> {
    if expected == actual {
        Ok(())
    } else {
        Err(MigrationReceiptError::new(format!(
            "{context} cid mismatch: expected {expected}, recomputed {actual}"
        )))
    }
}

fn migration_cid_without_keys<T: Serialize>(
    value: &T,
    keys: &[&str],
) -> Result<String, MigrationReceiptError> {
    let mut json = serde_json::to_value(value)?;
    let serde_json::Value::Object(ref mut map) = json else {
        return Err(MigrationReceiptError::new(
            "memento did not serialize as object",
        ));
    };
    for key in keys {
        map.remove(*key);
    }
    let canonical = migration_json_to_canonical(&json)?;
    let jcs = sugar_canonicalizer::encode_jcs(&canonical);
    Ok(sugar_canonicalizer::blake3_512_of(jcs.as_bytes()))
}

fn migration_json_to_canonical(
    value: &serde_json::Value,
) -> Result<std::sync::Arc<sugar_canonicalizer::Value>, MigrationReceiptError> {
    use sugar_canonicalizer::Value as CanonicalValue;

    match value {
        serde_json::Value::Null => Ok(CanonicalValue::null()),
        serde_json::Value::Bool(b) => Ok(CanonicalValue::boolean(*b)),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(CanonicalValue::integer(i128::from(i)))
            } else if let Some(u) = n.as_u64() {
                Ok(CanonicalValue::integer(i128::from(u)))
            } else {
                Err(MigrationReceiptError::new(format!(
                    "unsupported JSON number {n}"
                )))
            }
        }
        serde_json::Value::String(s) => Ok(CanonicalValue::string(s.clone())),
        serde_json::Value::Array(items) => {
            let converted = items
                .iter()
                .map(migration_json_to_canonical)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(CanonicalValue::array(converted))
        }
        serde_json::Value::Object(object) => {
            let converted = object
                .iter()
                .map(|(key, value)| Ok((key.clone(), migration_json_to_canonical(value)?)))
                .collect::<Result<Vec<_>, MigrationReceiptError>>()?;
            Ok(CanonicalValue::object(converted))
        }
    }
}

// ============================================================
// End witness memento + memento validation block
// ============================================================

// ============================================================
// End manual extension block -- PipelineMemento and RunMemento (#799)
// ============================================================

#[cfg(test)]
mod platform_semantic_envelope_tests {
    use super::*;

    fn cid(ch: char) -> Cid {
        format!("blake3-512:{}", ch.to_string().repeat(128))
    }

    fn structural_formula() -> IrFormula {
        IrFormula::Atomic {
            args: vec![IrTerm::Ctor {
                args: vec![],
                name: "lhs".to_string(),
            }],
            name: "shared_predicate".to_string(),
        }
    }

    // #1260: kit_cid is provenance, not content. Two DimensionValueMementos
    // minted by different kits but asserting identical content (same
    // dimension_name, value_name, compare_to formula) MUST produce the same
    // content-CID. Before #1260 they produced different CIDs because the
    // kit_cid was hashed into the content; cross-kit equivalence at
    // compare_op_with's short-circuit could not fire.
    #[test]
    fn dimension_value_memento_content_cid_independent_of_kit_cid() {
        let formula = structural_formula();
        let kit_a = cid('a');
        let kit_b = cid('b');

        let value_a = DimensionValueMemento::new(
            kit_a.clone(),
            "SharedDimension".to_string(),
            "SharedValue".to_string(),
            formula.clone(),
        );
        let value_b = DimensionValueMemento::new(
            kit_b.clone(),
            "SharedDimension".to_string(),
            "SharedValue".to_string(),
            formula.clone(),
        );

        assert_ne!(value_a.kit_cid, value_b.kit_cid, "provenance differs");
        assert_eq!(
            value_a.cid, value_b.cid,
            "identical content from different kits must yield identical content-CID"
        );
    }

    // Discrimination: identical kit_cid + identical (dimension, value) but
    // different compare_to formulas must yield distinct CIDs. Confirms the
    // CID still addresses the formula content (the actual semantic claim),
    // just not the provenance.
    #[test]
    fn dimension_value_memento_content_cid_distinguishes_compare_to_formulas() {
        let kit = cid('a');
        let formula_x = IrFormula::Atomic {
            args: vec![],
            name: "predicate_x".to_string(),
        };
        let formula_y = IrFormula::Atomic {
            args: vec![],
            name: "predicate_y".to_string(),
        };

        let value_x = DimensionValueMemento::new(
            kit.clone(),
            "Dim".to_string(),
            "Same".to_string(),
            formula_x,
        );
        let value_y =
            DimensionValueMemento::new(kit, "Dim".to_string(), "Same".to_string(), formula_y);

        assert_ne!(
            value_x.cid, value_y.cid,
            "different compare_to formulas must yield distinct content-CIDs"
        );
    }

    // #1260: same envelope-violation pattern, separately for
    // PlatformSemanticTag. Two tags minted by different kits but referencing
    // the same op_cid and the same dimensions map must produce identical
    // content-CIDs.
    #[test]
    fn platform_semantic_tag_content_cid_independent_of_kit_cid() {
        let op_cid = cid('o');
        let mut dimensions = BTreeMap::new();
        dimensions.insert("D1".to_string(), cid('v'));

        let tag_a = PlatformSemanticTag::new(cid('a'), op_cid.clone(), dimensions.clone());
        let tag_b = PlatformSemanticTag::new(cid('b'), op_cid.clone(), dimensions.clone());

        assert_ne!(tag_a.kit_cid, tag_b.kit_cid, "provenance differs");
        assert_eq!(
            tag_a.cid, tag_b.cid,
            "identical (op, dimensions) from different kits must yield identical content-CID"
        );
    }

    // Discrimination: identical kit_cid but different op_cid (the actual
    // semantic claim about which op this tag attaches to) must yield
    // distinct CIDs.
    #[test]
    fn platform_semantic_tag_content_cid_distinguishes_op_cid() {
        let kit = cid('a');
        let mut dimensions = BTreeMap::new();
        dimensions.insert("D1".to_string(), cid('v'));

        let tag_op1 = PlatformSemanticTag::new(kit.clone(), cid('o'), dimensions.clone());
        let tag_op2 = PlatformSemanticTag::new(kit, cid('p'), dimensions);

        assert_ne!(
            tag_op1.cid, tag_op2.cid,
            "different op_cids must yield distinct content-CIDs"
        );
    }
}

#[cfg(test)]
mod witness_cid_stability_tests {
    use super::*;

    fn cid(ch: char) -> String {
        format!("blake3-512:{}", ch.to_string().repeat(128))
    }

    /// Build a witness for a fixed DISCHARGE (obligation/solver/signer) but a
    /// caller-chosen `observed_at`. The CID is left blank; the test recomputes
    /// it. This is the shape the verify-mint path produces.
    fn witness_for_discharge(observed_at: &str, obligation: char) -> WitnessMemento {
        WitnessMemento {
            kind: "witness".to_string(),
            schema_version: "1".to_string(),
            witness_for: cid('p'),
            subject: cid('s'),
            fixture_state_cid: cid(obligation),
            observed_at: observed_at.to_string(),
            sample_count: 1,
            measurements: serde_json::json!({
                "solver": "z3@4.13",
                "obligation_cid": cid(obligation),
            }),
            outcome: "pass".to_string(),
            signed_by: Some("ed25519:dev".to_string()),
            signature: None,
            cid: String::new(),
        }
    }

    // #2022-class: a witness CID is a content-address of the DISCHARGE, not a
    // clock-address. Two honest provers discharging the SAME obligation at
    // DIFFERENT wall-clock times MUST land on the SAME witness CID, or the
    // supply-chain pin in a proof receipt never rendezvous across honest
    // re-derivation. RED before the fix (observed_at was in the preimage).
    #[test]
    fn witness_cid_is_stable_across_observed_at() {
        let early = witness_for_discharge("1970-01-01T00:00:00.000Z", 'a');
        let late = witness_for_discharge("2099-12-31T23:59:59.999Z", 'a');

        let cid_early = early.recompute_cid().expect("recompute early");
        let cid_late = late.recompute_cid().expect("recompute late");

        assert_eq!(
            cid_early, cid_late,
            "same discharge, different observed_at -> witness CID MUST be \
             identical (the CID addresses the discharge, not the clock)"
        );
    }

    // Discrimination: the CID still addresses the discharge content. A
    // DIFFERENT obligation (different fixture_state_cid + obligation_cid) must
    // yield a DIFFERENT CID -- excluding observed_at did NOT over-exclude the
    // discharge identity.
    #[test]
    fn witness_cid_distinguishes_distinct_discharges() {
        let a = witness_for_discharge("2026-06-11T12:00:00.000Z", 'a');
        let b = witness_for_discharge("2026-06-11T12:00:00.000Z", 'b');

        let cid_a = a.recompute_cid().expect("recompute a");
        let cid_b = b.recompute_cid().expect("recompute b");

        assert_ne!(
            cid_a, cid_b,
            "distinct discharges (different obligation) must yield distinct \
             witness CIDs"
        );
    }

    // The postmark is SEALED, not free-floating: the bytes the signature
    // attests bind BOTH the (convergent) CID and the (testimony) observed_at.
    // Tampering observed_at changes the attested payload, so a signature over
    // the original payload cannot verify against the tampered one. (The
    // signature-level discrimination is exercised end-to-end in the sugar-cli
    // witness_verify tests; here we prove the payload binds the timestamp.)
    #[test]
    fn attestation_payload_binds_observed_at() {
        let original = witness_for_discharge("2026-06-11T12:00:00.000Z", 'a');
        let mut tampered = original.clone();
        tampered.observed_at = "2026-06-11T13:00:00.000Z".to_string();

        // Same discharge -> same CID (the seal rides on a stable address)...
        assert_eq!(
            original.recompute_cid().expect("orig cid"),
            tampered.recompute_cid().expect("tampered cid"),
            "tampering only observed_at must NOT move the CID"
        );

        // ...but the attested bytes DIFFER, so the postmark cannot be peeled.
        let orig_cid = original.recompute_cid().expect("orig cid");
        let tampered_cid = tampered.recompute_cid().expect("tampered cid");
        let orig_payload = witness_attestation_payload(&orig_cid, &original.observed_at);
        let tampered_payload = witness_attestation_payload(&tampered_cid, &tampered.observed_at);

        assert_ne!(
            orig_payload, tampered_payload,
            "the signed {{cid, observed_at}} payload MUST change when observed_at \
             is tampered (postmark sealed under the signature)"
        );
    }

    // The attestation payload is deterministic and key-order independent:
    // recomputing it from the same (cid, observed_at) yields identical bytes,
    // so the mint and verify sides always agree.
    #[test]
    fn attestation_payload_is_deterministic() {
        let p1 = witness_attestation_payload(&cid('a'), "2026-06-11T12:00:00.000Z");
        let p2 = witness_attestation_payload(&cid('a'), "2026-06-11T12:00:00.000Z");
        assert_eq!(p1, p2, "attestation payload must be deterministic");
    }
}
