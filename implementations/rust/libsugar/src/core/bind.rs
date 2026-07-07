// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value as Json};
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_types::{IrFormula, IrTerm, Sort};
use thiserror::Error;

use super::primitives::address;
use super::traits::{Kit, KitError};
use super::types::{
    memento_from_parts, Cid, Contract, Dialect, DomainClaim, DomainKind, Input, Term, Verdict,
};

const CONCEPT_BIND_RESULT: &str = "concept:bind-result";
const CONCEPT_OP_APPLICATION: &str = "concept:op-application";
const CONCEPT_SEQ: &str = "concept:seq";

/// Options for the substrate bind pass.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindOptions {
    /// Source language hint for diagnostics and named-term metadata.
    pub lang: String,
}

impl Default for BindOptions {
    fn default() -> Self {
        Self {
            lang: "auto".to_string(),
        }
    }
}

/// Core Kit adapter for the existing substrate binder.
#[derive(Debug, Clone, Default)]
pub struct BindKit {
    options: BindOptions,
}

impl BindKit {
    /// Build a bind Kit using the supplied binder options.
    pub fn new(options: BindOptions) -> Self {
        Self { options }
    }

    fn bind_term_from_input(&self, input: &Input) -> Result<DomainClaim, BindError> {
        let Input::Term(term) = input else {
            return Err(BindError::Failed(
                "bind kit expects Input::Term".to_string(),
            ));
        };
        let term_json = term_json_from_term(term)?;
        let realize_sidecar_hint = realize_sidecar_hint(term_json)?;
        let hashed_term = strip_realize_sidecar_from_lift_term(term.clone());
        let named = bind_term_document(term_json, &self.options)?;
        let named_cid = named_term_document_cid(&named)?;
        let payload = bind_result_payload(term.clone(), &named)?;
        let payload_value = serde_json::to_value(&payload).map_err(|error| {
            BindError::Failed(format!("serialize bind result payload: {error}"))
        })?;
        let payload_cid = address(&payload);
        let mut contract = bind_response_contract(&payload_value, &payload_cid);
        contract.concept_hint = realize_sidecar_hint;

        Ok(DomainClaim {
            domain: DomainKind::Other("bind".to_string()),
            contract,
            artifacts: vec![named_cid.clone()],
            from: vec![address(&hashed_term)],
            premises: vec![],
            to: payload_cid,
            witness: None,
            payload: Some(payload),
            verdict: Verdict::Unresolved,
            attestation: None,
        })
    }
}

impl Kit for BindKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other("bind-default".to_string())
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        self.bind_term_from_input(input)
            .map_err(|error| KitError::Transformation(error.to_string()))
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        Ok(claim)
    }

    fn parse(&self, input: &Input) -> Result<Term, KitError> {
        self.transform(input)?
            .payload
            .ok_or_else(|| KitError::Serialization("bind claim missing term payload".to_string()))
    }

    fn serialize(&self, term: &Term) -> Result<Input, KitError> {
        Ok(Input::Term(term.clone()))
    }
}

/// Errors from the substrate bind Kit.
#[derive(Debug, Error)]
pub enum BindError {
    /// Binding the term document failed.
    #[error("{0}")]
    Failed(String),
}

impl From<String> for BindError {
    fn from(value: String) -> Self {
        Self::Failed(value)
    }
}

fn is_zero_u64(value: &u64) -> bool {
    *value == 0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BindLiftEntry {
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub file: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub fn_name: String,
    #[serde(default, skip_serializing_if = "is_zero_u64")]
    pub fn_line: u64,
    #[serde(default)]
    pub attr_pre: Option<String>,
    #[serde(default)]
    pub attr_post: Option<String>,
    #[serde(default)]
    pub concept_annotation: Option<String>,
    /// Fully-qualified library symbol this sugar binding IS, e.g. `numpy.add`
    /// (the symbol-keyed identity; the join key the linker resolves call-edges
    /// against and the recognizer stamps as `target_symbol`). When present it
    /// supersedes concept-derived naming; concept was the legacy hub key and is
    /// being retired (see SHARED-LANGUAGE.md). Absent → legacy concept path,
    /// byte-identical for existing shims.
    #[serde(default)]
    pub symbol: Option<String>,
    #[serde(default)]
    pub param_names: Vec<String>,
    #[serde(default)]
    pub param_types: Vec<String>,
    #[serde(default)]
    pub return_type: String,
    /// Source-language visibility ("pub", "pub(crate)", or empty for
    /// private). Propagated from lift into NamedTerm for source metadata.
    #[serde(default)]
    pub visibility: String,
    /// Generic parameter declarations from source (e.g. `<A: AdapterLifter>`).
    #[serde(default)]
    pub generic_params: String,
    /// Original param types as written in source. param_types is the
    /// substituted form; this is the byte-identical form.
    #[serde(default)]
    pub original_param_types: Vec<String>,
    /// Sort CIDs lifted from the source's type expressions via the kit's
    /// source-alias table (#1370). These are the substrate-honest
    /// cross-language type pins.
    #[serde(default)]
    pub param_sort_cids: Vec<String>,
    #[serde(default)]
    pub return_sort_cid: String,
    #[serde(default)]
    pub operand_bindings: Vec<Json>,
    #[serde(
        default,
        rename = "procMacroInvocations",
        alias = "proc_macro_invocations"
    )]
    pub proc_macro_invocations: Vec<Json>,
    #[serde(default)]
    pub source_function_name: Option<String>,
    /// Realize-sidecar-only source signature types. These intentionally do NOT
    /// feed the CID-bearing `param_types` / `return_type` fields: A9 (#1075)
    /// erased declared types from the canonical lift term so the same algebra
    /// lifted from untyped Python and typed Rust binds byte-identically
    /// (seam 4 federation). The realizer still needs the source types to match
    /// signature-keyed body templates, so the lifter emits them here; bind
    /// forwards them through the realize sidecar (CID-invisible, stripped by
    /// `strip_realize_sidecar_from_lift_term`) and `merge_realize_sidecar`
    /// injects them into the realize spec.
    #[serde(default, rename = "realize_param_types", alias = "realizeParamTypes")]
    pub realize_param_types: Vec<String>,
    #[serde(default, rename = "realize_return_type", alias = "realizeReturnType")]
    pub realize_return_type: String,
    #[serde(default, rename = "op_cid", alias = "opCid")]
    pub op_cid: String,
    #[serde(default)]
    pub term_shape: Json,
    #[serde(default)]
    pub term_shape_cid: String,
    #[serde(default)]
    pub witnesses: Vec<BindContractWitness>,
    /// Doc comment lines from rust source (only `///` after the
    /// native library-binding declaration). Propagated end-to-end so
    /// realize can reproduce them on emit.
    #[serde(default, rename = "docLines", alias = "doc_lines")]
    pub doc_lines: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BindContractWitness {
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub predicate: Option<Json>,
    #[serde(default)]
    pub predicate_text: Option<String>,
    #[serde(default)]
    pub source_kind: String,
    #[serde(default)]
    pub confidence_basis_points: Option<u16>,
    #[serde(default)]
    pub line: Option<u64>,
    #[serde(default)]
    pub col: Option<u64>,
    #[serde(default)]
    pub extension_fields: BTreeMap<String, Json>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NamedTermDocument {
    #[serde(rename = "candidateClusterManifest", default)]
    pub candidate_cluster_manifest: CandidateClusterManifest,
    pub kind: String,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "sourceLanguage")]
    pub source_language: String,
    pub terms: Vec<NamedTerm>,
    /// Boundary entries carried alongside sugar terms.
    #[serde(
        default,
        rename = "boundaryEntries",
        skip_serializing_if = "Vec::is_empty"
    )]
    pub boundary_entries: Vec<Json>,
    /// Trait declarations lifted from rust source. Each carries the
    /// trait name + per-method signatures. The target plugin uses these
    /// to emit native interface declarations (java interface, etc.)
    /// matching the rust trait — no hand-written interface code.
    #[serde(default, rename = "traitDecls", skip_serializing_if = "Vec::is_empty")]
    pub trait_decls: Vec<Json>,
    /// Module-level item declarations: const, struct, enum. The target
    /// plugin uses these to emit native equivalents (java static
    /// constants, classes/records, sealed interfaces).
    #[serde(default, rename = "moduleItems", skip_serializing_if = "Vec::is_empty")]
    pub module_items: Vec<Json>,
    #[serde(rename = "workspaceRoot", skip_serializing_if = "Option::is_none")]
    pub workspace_root: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CandidateClusterManifest {
    pub clusters: Vec<CandidateCluster>,
    pub kind: String,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "totalCandidates")]
    pub total_candidates: u64,
}

impl Default for CandidateClusterManifest {
    fn default() -> Self {
        Self {
            clusters: Vec::new(),
            kind: "candidate-cluster-manifest".to_string(),
            schema_version: "1".to_string(),
            total_candidates: 0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CandidateCluster {
    #[serde(rename = "candidateCids")]
    pub candidate_cids: Vec<String>,
    #[serde(rename = "candidateCount")]
    pub candidate_count: u64,
    #[serde(rename = "opCluster")]
    pub op_cluster: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NamedTerm {
    #[serde(rename = "opCid", alias = "op_cid")]
    pub op_cid: String,
    #[serde(rename = "dischargeVerdict")]
    pub discharge_verdict: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub file: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub function: String,
    #[serde(
        default,
        rename = "fnNameSugar",
        skip_serializing_if = "Option::is_none"
    )]
    pub fn_name_sugar: Option<String>,
    pub name: String,
    #[serde(rename = "paramTypes")]
    pub param_types: Vec<String>,
    pub params: Vec<String>,
    #[serde(rename = "returnType")]
    pub return_type: String,
    /// Source-language visibility ("pub", "pub(crate)", or empty for private).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub visibility: String,
    /// Generic parameter declarations as a single string (e.g.
    /// `<A: AdapterLifter>`). Empty if the function has no generics.
    #[serde(
        default,
        rename = "genericParams",
        skip_serializing_if = "String::is_empty"
    )]
    pub generic_params: String,
    /// Original param types as written in source (no trait-bound
    /// substitution). `param_types` carries the substituted form for
    /// body-template matching; this carries the byte-identical form for
    /// signature emission.
    #[serde(
        default,
        rename = "originalParamTypes",
        skip_serializing_if = "Vec::is_empty"
    )]
    pub original_param_types: Vec<String>,
    /// Substrate-honest cross-language type pins.
    #[serde(
        default,
        rename = "paramSortCids",
        skip_serializing_if = "Vec::is_empty"
    )]
    pub param_sort_cids: Vec<String>,
    #[serde(
        default,
        rename = "returnSortCid",
        skip_serializing_if = "String::is_empty"
    )]
    pub return_sort_cid: String,
    #[serde(rename = "siteMementoCid")]
    pub site_memento_cid: String,
    #[serde(rename = "termShape")]
    pub term_shape: Json,
    #[serde(rename = "termShapeCid")]
    pub term_shape_cid: String,
    pub witnesses: Vec<NamedWitness>,
    /// Doc comment lines (`///` body, without prefix or trailing newline)
    /// that appear AFTER the native library-binding declaration. Threaded
    /// through to realize so cycle output preserves source doc comments.
    /// Empty when the source had no post-sugar docs.
    #[serde(default, rename = "docLines", skip_serializing_if = "Vec::is_empty")]
    pub doc_lines: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NamedWitness {
    pub predicate: Json,
    #[serde(rename = "predicateText")]
    pub predicate_text: String,
    pub role: String,
    #[serde(rename = "sourceKind")]
    pub source_kind: String,
}

/// Bind a lifted ProofIR term document into a named-term document.
pub fn bind_term_document(
    term_json: &Json,
    options: &BindOptions,
) -> Result<NamedTermDocument, BindError> {
    let entries = bind_lift_entries(term_json)?;
    let source_language = source_language(term_json, options);
    let workspace_root = workspace_root(term_json);

    let mut seen_names: BTreeSet<String> = BTreeSet::new();
    let mut terms = Vec::with_capacity(entries.len());
    for (idx, entry) in entries.into_iter().enumerate() {
        let term_shape_cid = if entry.term_shape_cid.trim().is_empty() {
            crate::canonical::json_cid(&entry.term_shape)
                .map_err(|e| format!("cid term shape for {}: {e}", entry.fn_name))?
        } else {
            entry.term_shape_cid.clone()
        };
        let op_cid = entry_op_cid(&entry, &term_shape_cid)?;
        let base_name = entry_display_name(&entry, idx + 1, &op_cid);
        let name = unique_name(&base_name, &mut seen_names);
        let site_memento_cid = site_cid(&entry, &name, &term_shape_cid)?;
        let witnesses = named_witnesses(&entry);
        let fn_name = entry.fn_name;
        terms.push(NamedTerm {
            op_cid,
            discharge_verdict: if witnesses.is_empty() {
                "loudly-bounded-lossy".to_string()
            } else {
                "exact".to_string()
            },
            file: entry.file,
            function: fn_name.clone(),
            fn_name_sugar: if fn_name.is_empty() {
                None
            } else {
                Some(fn_name)
            },
            name,
            param_types: entry.param_types,
            params: entry.param_names,
            return_type: if entry.return_type.is_empty() {
                "()".to_string()
            } else {
                entry.return_type
            },
            visibility: entry.visibility,
            generic_params: entry.generic_params,
            original_param_types: entry.original_param_types,
            param_sort_cids: entry.param_sort_cids,
            return_sort_cid: entry.return_sort_cid,
            site_memento_cid,
            term_shape: entry.term_shape,
            term_shape_cid,
            witnesses,
            doc_lines: entry.doc_lines,
        });
    }

    let candidate_cluster_manifest = candidate_cluster_manifest(&terms);

    Ok(NamedTermDocument {
        candidate_cluster_manifest,
        kind: "named-term-document".to_string(),
        schema_version: "1".to_string(),
        source_language,
        terms,
        boundary_entries: Vec::new(),
        trait_decls: Vec::new(),
        module_items: Vec::new(),
        workspace_root,
    })
}

/// Return the canonical named-term document CID emitted by `cmd_bind`.
pub fn named_term_document_cid(named: &NamedTermDocument) -> Result<Cid, BindError> {
    let canonical = bind_payload_named_term_document(named);
    let cid = crate::canonical::serializable_cid(&canonical)
        .map_err(|error| BindError::Failed(format!("cid named term JSON: {error}")))?;
    Cid::try_from(cid).map_err(|error| BindError::Failed(error.to_string()))
}

fn bind_payload_named_term_document(named: &NamedTermDocument) -> NamedTermDocument {
    let mut canonical = named.clone();
    for term in &mut canonical.terms {
        term.function.clear();
        term.fn_name_sugar = None;
    }
    canonical
}

fn bind_payload_wire_named_term_document(named: &NamedTermDocument) -> NamedTermDocument {
    let mut wire = named.clone();
    for term in &mut wire.terms {
        term.function.clear();
        // fn_name_sugar is preserved: it carries the source fn name as a
        // non-CID-affecting annotation on the citation (Option C sugar layer)
        //
        // #1075 federation: the wire op-tree is arg[1] of the federated
        // concept:bind-result payload (the cross-language CID). Source-language
        // realize-only display metadata — visibility, generic_params, doc_lines
        // — must NOT ride it, or typed-Rust (`pub fn add ...`) and untyped-Python
        // (`def add ...`) bind to different CIDs. These are NOT lost: the full
        // NamedTermDocument (with them intact) is addressed separately as the
        // bind claim's `artifacts[0]` (named_cid). Parallel to the
        // bind-lift-entry strip in strip_realize_sidecar_from_lift_term.
        //
        // NOTE: the signature TYPES (param_types/return_type/original_param_types)
        // are deliberately NOT cleared here. After the layer-1 sidecar migration
        // the rust + python lifters both emit the bare types empty on
        // bind-lift-entry, so NamedTerm.param_types is already [] for the
        // federated `add` algebra — clearing it would be a CID no-op there. But
        // some downstream bind payload readers consume these fields directly; for
        // a function that DID carry source types, clearing them here would degrade
        // its emitted signature (i64 -> int int-inference fallback).
        term.visibility.clear();
        term.generic_params.clear();
        term.doc_lines.clear();
    }
    wire
}

pub fn concept_bind_result_cid() -> Cid {
    // Computed from the pinned SHAPE, never a pinned hash. The address is
    // whatever json_cid(grammar_op_shape) produces, by construction -- there is
    // no magic-number literal to drift from its preimage.
    GrammarOpRegistry
        .cid(CONCEPT_BIND_RESULT)
        .expect("concept:bind-result is a language primitive")
}

/// Resolve a grammar primitive's address from the code shape-authority. `Some`
/// iff `name` is a language primitive (op-application / seq / ite / bind-result);
/// the address is `json_cid` of its pinned shape, computed, never frozen.
/// Consumers derive handles from this; they never store a copy.
pub fn grammar_op_cid(name: &str) -> Option<Cid> {
    GrammarOpRegistry.cid(name)
}

pub fn bind_result_payload(
    _original_term: Term,
    named: &NamedTermDocument,
) -> Result<Term, BindError> {
    // Wire form: function cleared (preserving #1093) but fn_name_sugar kept as
    // source metadata without affecting the named-term-document CID (see
    // named_term_document_cid / bind_payload_named_term_document).
    let wire_named = bind_payload_wire_named_term_document(named);
    let value = serde_json::to_value(&wire_named)
        .map_err(|error| BindError::Failed(format!("serialize bind result payload: {error}")))?;
    Ok(Term::Const {
        value,
        sort: primitive_sort("NamedTermDocument"),
    })
}

/// Strip realize-sidecar metadata (attr_pre, attr_post, concept_annotation,
/// operand_bindings, proc_macro_invocations, source_function_name) from a
/// lift-output `Term::Const`. Used to compute the canonical content CID that
/// `lift.to` and `bind.from` both target, so adding a comment that shifts
/// `fn_line` does not invalidate the proof chain.
pub fn strip_realize_sidecar_from_lift_term(term: Term) -> Term {
    let Term::Const { mut value, sort } = term else {
        return term;
    };
    if let Some(entries) = value.get_mut("ir").and_then(Json::as_array_mut) {
        for entry in entries {
            if let Some(object) = entry.as_object_mut() {
                object.remove("attr_pre");
                object.remove("attrPre");
                object.remove("attr_post");
                object.remove("attrPost");
                object.remove("concept_annotation");
                object.remove("conceptAnnotation");
                object.remove("operand_bindings");
                object.remove("operandBindings");
                object.remove("proc_macro_invocations");
                object.remove("procMacroInvocations");
                object.remove("source_function_name");
                object.remove("sourceFunctionName");
                object.remove("realize_param_types");
                object.remove("realizeParamTypes");
                object.remove("realize_return_type");
                object.remove("realizeReturnType");
                object.remove("realize_original_param_types");
                object.remove("realizeOriginalParamTypes");
                // #1075/A9 federation: the bind-lift-entry is the cross-language
                // boundary surface and must hash to the SAME bytes whether
                // lifted from typed Rust or untyped Python. The Python lifter
                // emits only {kind, param_names, term_shape, term_shape_cid,
                // operand_bindings, realize_*, source_function_name, witnesses};
                // Rust additionally carries visibility/generic_params/doc_lines
                // for the Java boundary realize path. Those are realize-only
                // metadata (read off the UN-stripped lift IR by cmd_lower, never
                // off this hashed term) so they ride CID-invisible here too,
                // scoped to bind-lift-entry to leave sugar-entry CIDs untouched.
                if object.get("kind").and_then(Json::as_str) == Some("bind-lift-entry") {
                    object.remove("visibility");
                    object.remove("generic_params");
                    object.remove("genericParams");
                    object.remove("doc_lines");
                    object.remove("docLines");
                }
            }
        }
    }
    Term::Const { value, sort }
}

pub fn named_term_document_from_bind_payload(
    payload: &Term,
) -> Result<NamedTermDocument, BindError> {
    match payload {
        Term::Const { value, .. } => serde_json::from_value(value.clone())
            .map_err(|error| BindError::Failed(format!("parse named term JSON: {error}"))),
        _ => Err(BindError::Failed(
            "bind payload is not named-term JSON".to_string(),
        )),
    }
}

fn term_json_from_term(term: &Term) -> Result<&Json, BindError> {
    match term {
        Term::Const { value, .. } => Ok(value),
        _ => Err(BindError::Failed(
            "bind kit expects a ProofIR JSON const term".to_string(),
        )),
    }
}

fn bind_response_contract(payload: &Json, payload_cid: &Cid) -> Contract {
    let pre = IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    };
    let post = IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![
            IrTerm::Var {
                name: "result".to_string(),
            },
            IrTerm::Const {
                value: payload.clone(),
                sort: primitive_sort("Term"),
            },
        ],
    };

    memento_from_parts(
        "bind::default::bind-result-document".to_string(),
        vec!["term".to_string()],
        vec![primitive_sort("LiftPluginResponse")],
        primitive_sort("Term"),
        pre,
        post,
        Some(payload_cid.as_str().to_string()),
    )
}

// ============================================================
// Bridge writer (PR-22, #1440).
// ============================================================
//
// A harvested call `double(3)` is dischargeable through verify ONLY when
// three things are in the pool:
//   1. a body-derived op-contract for `double` (post = result == *(x, 2)),
//   2. a bridge `sourceSymbol "double" -> targetContractCid <op-contract>`,
//   3. (transitively) the proof bundle the bridge pins.
// The bridge's CID commits to the op-contract CID (it is in `inputCids`),
// and the bundle commits to both; that is the proofchain rollup.
//
// This writer is the production source of (1) and (2): it takes the
// `FunctionContractMemento` walk already builds for a function (which
// carries `fn_name`, `formals`, `formal_sorts`, and the BODY-DERIVED
// `post`), and emits both member envelopes in the v1.1-flat
// `evidence.body` shape that `enumerate_callsites` / `resolve_target` /
// `body_discharge::CatalogResolver` consume. The op-contract member CID is
// the bridge's `targetContractCid`, so verify resolves the chain.

/// One v1.1-flat member envelope plus its re-derivable member CID
/// (`blake3_512(JCS(envelope))`, the same identity `load_all_proofs`
/// recomputes for a member with no `cid` / `producerSignature` field).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BridgeMember {
    /// The member CID = `blake3-512:<hex>`.
    pub cid: Cid,
    /// The member envelope JSON (no `cid` / `producerSignature` — those are
    /// added by the proof-envelope builder when the bundle is assembled).
    pub envelope: Json,
}

/// The pair of members a function bind produces for body-discharge: the
/// body-derived op-contract and the bridge that points a harvested call at
/// it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FunctionBridgeMembers {
    /// The body-derived op-contract member (carries `formals` + `post`).
    pub op_contract: BridgeMember,
    /// The bridge member (`sourceSymbol -> targetContractCid`).
    pub bridge: BridgeMember,
}

/// Re-derive a v1.1-flat member CID for an envelope, matching
/// `sugar_verifier::load_all_proofs::compute_member_cid`: strip any
/// `cid` / `producerSignature`, JCS-encode, BLAKE3-512.
fn flat_member_cid(envelope: &Json) -> Cid {
    let mut stripped = envelope.clone();
    if let Json::Object(map) = &mut stripped {
        map.remove("cid");
        map.remove("producerSignature");
    }
    let canonical = sugar_canonicalizer::encode_jcs(&json_to_canonical_value(&stripped));
    Cid::from_hash_output(blake3_512_of(canonical.as_bytes()))
}

/// Convert a `serde_json::Value` into the canonicalizer's `Value` so the
/// JCS bytes line up with every other minter in the tree.
fn json_to_canonical_value(j: &Json) -> std::sync::Arc<sugar_canonicalizer::Value> {
    use sugar_canonicalizer::Value as CV;
    match j {
        Json::Null => CV::null(),
        Json::Bool(b) => CV::boolean(*b),
        Json::Number(n) => CV::integer(
            n.as_i64()
                .map(i128::from)
                .or_else(|| n.as_u64().map(i128::from))
                .unwrap_or(0),
        ),
        Json::String(s) => CV::string(s.clone()),
        Json::Array(items) => CV::array(items.iter().map(json_to_canonical_value).collect()),
        Json::Object(map) => CV::object(
            map.iter()
                .map(|(k, v)| (k.clone(), json_to_canonical_value(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

/// Build the body-discharge members (op-contract + bridge) for a function
/// contract. `target_proof_cid` is the `.proof` bundle CID the bridge pins
/// (`BridgeDeclaration.targetProofCid`); pass the CID of the bundle these
/// members will be assembled into. `source_layer` / `target_layer` name
/// the language axes (e.g. `"rust"` -> `"rust-kit"`).
///
/// The op-contract carries the function's BODY-DERIVED `post` (the
/// `FunctionContractMemento`'s `post`, which walk lifts from the body's
/// trailing expression), plus `formals` / `formalSorts` so the resolver
/// can name the value slots. This is the lift-half of walk (verification
/// substrate); it does NOT touch the lower/cycle/carrier machinery.
pub fn bind_function_bridge(
    contract: &Contract,
    source_layer: &str,
    target_layer: &str,
    target_proof_cid: Option<&str>,
) -> Result<FunctionBridgeMembers, BindError> {
    let post_json = serde_json::to_value(&contract.post)
        .map_err(|e| BindError::Failed(format!("serialize body-derived post: {e}")))?;
    let formals: Vec<Json> = contract
        .formals
        .iter()
        .map(|f| Json::String(f.clone()))
        .collect();
    let formal_sorts: Vec<Json> = contract
        .formal_sorts
        .iter()
        .map(|s| serde_json::to_value(s).unwrap_or(Json::Null))
        .collect();

    let op_contract_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": contract.fn_name,
                "formals": formals,
                "formalSorts": formal_sorts,
                "post": post_json
            }
        }
    });
    let op_contract_cid = flat_member_cid(&op_contract_env);

    let mut bridge_body = serde_json::Map::new();
    bridge_body.insert(
        "sourceSymbol".into(),
        Json::String(contract.fn_name.clone()),
    );
    bridge_body.insert("sourceLayer".into(), Json::String(source_layer.to_string()));
    bridge_body.insert(
        "targetContractCid".into(),
        Json::String(op_contract_cid.as_str().to_string()),
    );
    bridge_body.insert("targetLayer".into(), Json::String(target_layer.to_string()));
    if let Some(tpc) = target_proof_cid {
        bridge_body.insert("targetProofCid".into(), Json::String(tpc.to_string()));
    }
    let bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": Json::Object(bridge_body)
        }
    });
    let bridge_cid = flat_member_cid(&bridge_env);

    Ok(FunctionBridgeMembers {
        op_contract: BridgeMember {
            cid: op_contract_cid,
            envelope: op_contract_env,
        },
        bridge: BridgeMember {
            cid: bridge_cid,
            envelope: bridge_env,
        },
    })
}

fn bind_lift_entries(term_json: &Json) -> Result<Vec<BindLiftEntry>, BindError> {
    if term_json.get("kind").and_then(Json::as_str) == Some("named-term-document") {
        return Err(BindError::Failed(
            "input is already named; bind expects ProofIR term JSON from lift".to_string(),
        ));
    }
    let ir = term_json
        .get("ir")
        .and_then(Json::as_array)
        .ok_or_else(|| BindError::Failed("ProofIR document missing `ir` array".to_string()))?;
    let mut out = Vec::new();
    for item in ir {
        let kind = item.get("kind").and_then(Json::as_str).unwrap_or("");
        // Accept BOTH `bind-lift-entry` (contracts) and
        // `library-sugar-binding-entry` (@sugar functions). The latter
        // was historically skipped, which meant @sugar functions never
        // got lifted into named terms — bind dropped them silently.
        // Now both kinds flow through; BindLiftEntry's #[serde(default)]
        // on fields lets the deserializer succeed for either shape.
        if kind != "bind-lift-entry" && kind != "library-sugar-binding-entry" {
            continue;
        }
        // For library-sugar-binding-entry the function name field is
        // `source_function_name`. Patch a synthetic `fn_name` so the
        // common deserialization path works.
        let mut patched = item.clone();
        if kind == "library-sugar-binding-entry" {
            if let Some(obj) = patched.as_object_mut() {
                if !obj.contains_key("fn_name") {
                    if let Some(sfn) = obj.get("source_function_name").cloned() {
                        obj.insert("fn_name".to_string(), sfn);
                    }
                }
            }
        }
        let entry = serde_json::from_value::<BindLiftEntry>(patched)
            .map_err(|e| BindError::Failed(format!("parse {kind}: {e}")))?;
        out.push(entry);
    }
    Ok(out)
}

fn realize_sidecar_hint(term_json: &Json) -> Result<Option<String>, BindError> {
    let entries = bind_lift_entries(term_json)?;
    let mut sidecar_terms = Vec::new();
    for entry in entries {
        if entry.operand_bindings.is_empty()
            && entry.proc_macro_invocations.is_empty()
            && entry.source_function_name.is_none()
            && entry.realize_param_types.is_empty()
            && entry.realize_return_type.is_empty()
        {
            continue;
        }
        sidecar_terms.push(json!({
            "function": entry.fn_name,
            "operand_bindings": entry.operand_bindings,
            "proc_macro_invocations": entry.proc_macro_invocations,
            "source_function_name": entry.source_function_name,
            "realize_param_types": entry.realize_param_types,
            "realize_return_type": entry.realize_return_type,
        }));
    }
    if sidecar_terms.is_empty() {
        return Ok(None);
    }
    let sidecar = json!({
        "kind": "sugar-realize-sidecar",
        "terms": sidecar_terms,
    });
    serde_json::to_string(&sidecar)
        .map(|text| Some(format!("sugar-realize-sidecar:{text}")))
        .map_err(|error| BindError::Failed(format!("serialize realize sidecar: {error}")))
}

fn source_language(term_json: &Json, options: &BindOptions) -> String {
    term_json
        .get("sourceLanguage")
        .or_else(|| term_json.get("surface"))
        .and_then(Json::as_str)
        .map(str::to_string)
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| {
            if options.lang == "auto" {
                "unknown".to_string()
            } else {
                options.lang.clone()
            }
        })
}

fn workspace_root(term_json: &Json) -> Option<String> {
    term_json
        .get("workspaceRoot")
        .or_else(|| term_json.get("workspace_root"))
        .and_then(Json::as_str)
        .map(str::to_string)
}

fn entry_op_cid(entry: &BindLiftEntry, term_shape_cid: &str) -> Result<String, BindError> {
    if !entry.op_cid.trim().is_empty() {
        return Ok(entry.op_cid.clone());
    }
    if let Some(op_cid) = entry
        .term_shape
        .get("op_cid")
        .and_then(Json::as_str)
        .filter(|s| !s.trim().is_empty())
    {
        return Ok(op_cid.to_string());
    }
    if !term_shape_cid.trim().is_empty() {
        return Ok(term_shape_cid.to_string());
    }
    Err(BindError::Failed(format!(
        "bind entry `{}` lacks op_cid and term_shape_cid",
        entry.fn_name
    )))
}

fn entry_display_name(entry: &BindLiftEntry, ordinal: usize, op_cid: &str) -> String {
    if let Some(symbol) = entry.symbol.as_ref().filter(|s| !s.trim().is_empty()) {
        return symbol.clone();
    }
    format!(
        "op-{}-{ordinal}",
        op_cid
            .chars()
            .skip("blake3-512:".len())
            .take(12)
            .collect::<String>()
    )
}

fn unique_name(label: &str, seen: &mut BTreeSet<String>) -> String {
    let base = label.strip_prefix("concept:").unwrap_or(label).to_string();
    if seen.insert(base.clone()) {
        return base;
    }
    for idx in 2usize.. {
        let candidate = format!("{base}-{idx}");
        if seen.insert(candidate.clone()) {
            return candidate;
        }
    }
    unreachable!("unbounded unique-name loop")
}

fn named_witnesses(entry: &BindLiftEntry) -> Vec<NamedWitness> {
    let mut witnesses = Vec::new();
    if entry.witnesses.is_empty() {
        if let Some(pre) = entry.attr_pre.as_deref() {
            witnesses.push(named_witness("pre", pre, "annotation"));
        }
        if let Some(post) = entry.attr_post.as_deref() {
            witnesses.push(named_witness("post", post, "annotation"));
        }
        return witnesses;
    }
    entry
        .witnesses
        .iter()
        .map(|witness| {
            let predicate_text = witness
                .predicate_text
                .clone()
                .or_else(|| witness.predicate.as_ref().map(Json::to_string))
                .unwrap_or_else(|| "true".to_string());
            NamedWitness {
                predicate: witness
                    .predicate
                    .clone()
                    .unwrap_or_else(|| json!({"kind": "text", "text": predicate_text})),
                predicate_text,
                role: if witness.role.trim().is_empty() {
                    "unknown".to_string()
                } else {
                    witness.role.clone()
                },
                source_kind: if witness.source_kind.trim().is_empty() {
                    "unspecified".to_string()
                } else {
                    witness.source_kind.clone()
                },
            }
        })
        .collect()
}

fn named_witness(role: &str, predicate_text: &str, source_kind: &str) -> NamedWitness {
    NamedWitness {
        predicate: json!({"kind": "text", "text": predicate_text}),
        predicate_text: predicate_text.to_string(),
        role: role.to_string(),
        source_kind: source_kind.to_string(),
    }
}

// Grammar lives in CODE, pinned by SHAPE, never on disk. An IR grammar
// primitive (op-application / seq / ite / bind-result) is the LANGUAGE, not a
// promoted concept -- and a thing is one or the other, never both. So its
// identity is the `json_cid` of its pure, name-free, positional structural
// shape, computed here from a shape compiled into the binary. There is no disk
// load and no catalog: the language is always present because it is the code.
struct GrammarOpRegistry;

impl GrammarOpRegistry {
    fn cid(&self, name: &str) -> Option<Cid> {
        let shape = grammar_op_shape(name)?;
        let cid = crate::canonical::op_cid_from_shape(&shape).ok()?;
        Cid::try_from(cid.as_str()).ok()
    }
}

/// The pure, name-free, positional structural shape of an IR grammar primitive.
/// Grammar is the language: pinned by shape in code, addressed by `json_cid` of
/// this shape. `fn_name`, `operator`, formal parameter names, `wp_note` prose,
/// and the memento envelope are all sugar and are ABSENT FROM THE PREIMAGE BY
/// CONSTRUCTION -- born pure, never stripped. Slot references are positional.
fn grammar_op_shape(name: &str) -> Option<Json> {
    use serde_json::json;
    let sort = |n: &str| json!({ "kind": "ctor", "name": n, "args": [] });
    let slot = |i: usize| json!({ "kind": "slot", "index": i });
    let pre = json!({ "kind": "atomic", "name": "true", "args": [] });
    let shape = match name {
        CONCEPT_OP_APPLICATION => json!({
            "kind": "grammar-op",
            "formalSorts": [sort("Cid"), sort("List<Term>")],
            "returnSort": sort("Term"),
            "pre": pre,
            "post": {
                "arity": ["Cid", "List<Term>"],
                "result": "Term",
                "slotTerms": [slot(0), slot(1)]
            },
            "effects": []
        }),
        CONCEPT_SEQ => json!({
            "kind": "grammar-op",
            "formalSorts": [sort("Stmt"), sort("Stmt")],
            "returnSort": sort("Stmt"),
            "pre": pre,
            "post": {
                "arity": ["Stmt", "Stmt"],
                "result": "Stmt",
                "wpRule": {
                    "kind": "apply",
                    "fn": "wp_slot_0",
                    "args": [{
                        "kind": "apply",
                        "fn": "wp_slot_1",
                        "args": [{ "kind": "var", "name": "Q" }]
                    }]
                }
            },
            "effects": [{ "kind": "effect-polymorphic", "rule": "union(slot_0.effects, slot_1.effects)" }]
        }),
        "concept:ite" => json!({
            "kind": "grammar-op",
            "formalSorts": [sort("Bool"), sort("Expr"), sort("Expr")],
            "returnSort": sort("Expr"),
            "pre": pre,
            "post": {
                "arity": ["Bool", "Expr", "Expr"],
                "result": "Expr"
            },
            "effects": [{ "kind": "effect-polymorphic", "rule": "union branch value effects" }]
        }),
        CONCEPT_BIND_RESULT => json!({
            "kind": "grammar-op",
            "formalSorts": [sort("Term"), sort("Term")],
            "returnSort": sort("BoundTerm"),
            "pre": pre,
            "post": {
                "arity": ["Term", "Term"],
                "result": "BoundTerm",
                "slotTerms": [slot(0), slot(1)]
            },
            "effects": []
        }),
        _ => return None,
    };
    Some(shape)
}

fn candidate_cluster_manifest(terms: &[NamedTerm]) -> CandidateClusterManifest {
    let mut by_op: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for term in terms {
        by_op
            .entry(term.op_cid.clone())
            .or_default()
            .push(term.term_shape_cid.clone());
    }
    let clusters = by_op
        .into_iter()
        .map(|(op_cluster, mut candidate_cids)| {
            candidate_cids.sort();
            CandidateCluster {
                candidate_count: candidate_cids.len() as u64,
                candidate_cids,
                op_cluster,
            }
        })
        .collect();
    CandidateClusterManifest {
        clusters,
        kind: "candidate-cluster-manifest".to_string(),
        schema_version: "1".to_string(),
        total_candidates: terms.len() as u64,
    }
}

fn site_cid(_entry: &BindLiftEntry, name: &str, term_shape_cid: &str) -> Result<String, BindError> {
    let value = json!({
        "name": name,
        "termShapeCid": term_shape_cid,
    });
    crate::canonical::json_cid(&value).map_err(|e| BindError::Failed(e.to_string()))
}

fn primitive_sort(name: &str) -> Sort {
    Sort::Primitive {
        name: name.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A `double(x) = x*2` function contract, as walk's
    /// `build_function_contract` would produce: body-derived
    /// `post = (result == *(x, 2))`, one formal `x`.
    fn double_contract() -> Contract {
        use crate::compose::{EffectSet, Locus};
        let post = IrFormula::Atomic {
            name: "=".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "result".to_string(),
                },
                IrTerm::Ctor {
                    name: "*".to_string(),
                    args: vec![
                        IrTerm::Var {
                            name: "x".to_string(),
                        },
                        IrTerm::Const {
                            value: json!(2),
                            sort: primitive_sort("Int"),
                        },
                    ],
                },
            ],
        };
        Contract {
            fn_name: "double".to_string(),
            formals: vec!["x".to_string()],
            formal_sorts: vec![primitive_sort("Int")],
            formal_regions: vec![],
            return_sort: primitive_sort("Int"),
            return_region: None,
            pre: IrFormula::Atomic {
                name: "true".to_string(),
                args: vec![],
            },
            post,
            body_cid: None,
            effects: EffectSet::empty(),
            locus: Locus::default(),
            canonical_bytes: vec![],
            cid: "blake3-512:test".to_string(),
            auto_minted_mementos: vec![],
            panic_loci: vec![],
            concept_hint: None,
        }
    }

    #[test]
    fn bind_function_bridge_emits_op_contract_and_pinned_bridge() {
        let contract = double_contract();
        let members =
            bind_function_bridge(&contract, "rust", "rust-kit", Some("blake3-512:bundle"))
                .expect("bind_function_bridge");

        // Op-contract carries the body-derived post + formals.
        let oc = sugar_proof_envelope::member_body(&members.op_contract.envelope).unwrap();
        assert_eq!(oc.get("contractName").unwrap(), "double");
        assert_eq!(oc.get("formals").unwrap(), &json!(["x"]));
        // post is `result == *(x, 2)`.
        let value_expr = oc.pointer("/post/args/1").unwrap();
        assert_eq!(value_expr.get("name").unwrap(), "*");

        // The bridge points at the op-contract member CID and pins the bundle.
        let br = sugar_proof_envelope::member_body(&members.bridge.envelope).unwrap();
        assert_eq!(br.get("sourceSymbol").unwrap(), "double");
        assert_eq!(
            br.get("targetContractCid").unwrap().as_str().unwrap(),
            members.op_contract.cid.as_str(),
            "bridge.targetContractCid must equal the op-contract member CID (proofchain rollup)"
        );
        assert_eq!(br.get("targetProofCid").unwrap(), "blake3-512:bundle");

        // CIDs are content-addressed and stable.
        assert_eq!(
            members.op_contract.cid,
            super::flat_member_cid(&members.op_contract.envelope)
        );
        assert!(members.op_contract.cid.as_str().starts_with("blake3-512:"));
    }

    #[test]
    fn bind_names_lifted_entries_without_plugin_dispatch() {
        let term = json!({
            "kind": "ir-document",
            "workspaceRoot": "/tmp/demo",
            "ir": [{
                "kind": "bind-lift-entry",
                "file": "src/lib.rs",
                "fn_name": "f",
                "concept_annotation": "demo",
                "op_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "param_names": ["x"],
                "param_types": ["i64"],
                "return_type": "i64",
                "term_shape": {"kind": "op", "name": "demo"},
                "witnesses": [{
                    "role": "post",
                    "predicate_text": "out == x",
                    "source_kind": "annotation"
                }]
            }]
        });
        let named = bind_term_document(
            &term,
            &BindOptions {
                lang: "rust".to_string(),
            },
        )
        .expect("bind succeeds");
        assert_eq!(named.kind, "named-term-document");
        assert_eq!(
            named.terms[0].op_cid,
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
        assert_eq!(named.terms[0].function, "f");
    }

    #[test]
    fn symbol_keyed_binding_keeps_symbol_as_display_name() {
        // The numpy sugar shim declares `symbol`; op_cid is identity, and the
        // symbol remains display/join metadata for call-edge resolution.
        let term = json!({
            "kind": "ir-document",
            "workspaceRoot": "/tmp/numpy-shim",
            "ir": [{
                "kind": "library-sugar-binding-entry",
                "file": "sugar_shim_numpy/__init__.py",
                "source_function_name": "add",
                "symbol": "numpy.add",
                "op_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "target_library_tag": "numpy",
                "param_names": ["x", "y"],
                "param_types": ["", ""],
                "return_type": "",
                "term_shape": {"kind": "op", "name": "add"},
                "witnesses": []
            }]
        });
        let named = bind_term_document(
            &term,
            &BindOptions {
                lang: "python".to_string(),
            },
        )
        .expect("bind succeeds");
        assert_eq!(
            named.terms[0].name, "numpy.add",
            "symbol-keyed binding must keep its fully-qualified symbol as display name"
        );
        assert_eq!(
            named.terms[0].op_cid,
            "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        );
    }

    #[test]
    fn bind_claim_cid_ignores_realize_sidecar_symbols() {
        fn bind_claim(lhs: &str, rhs: &str) -> DomainClaim {
            let term = json!({
                "kind": "ir-document",
                "workspaceRoot": "/tmp/demo",
                "ir": [{
                    "kind": "bind-lift-entry",
                    "file": "src/lib.rs",
                "fn_name": "add",
                "concept_annotation": "add",
                "op_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "param_names": ["x", "y"],
                    "param_types": ["i64", "i64"],
                    "return_type": "i64",
                    "term_shape": {
                        "kind": "op",
                        "name": "add",
                        "args": [
                            {"kind": "var", "name": "left"},
                            {"kind": "var", "name": "right"}
                        ]
                    },
                    "operand_bindings": [
                        {"position": [0], "symbol": lhs},
                        {"position": [1], "symbol": rhs}
                    ],
                    "source_function_name": "add"
                }]
            });
            let input = Input::Term(Term::Const {
                value: term,
                sort: sugar_ir_types::Sort::Primitive {
                    name: "json".to_string(),
                },
            });
            BindKit::new(BindOptions {
                lang: "rust".to_string(),
            })
            .bind_term_from_input(&input)
            .expect("bind succeeds")
        }

        let xy = bind_claim("x", "y");
        let yx = bind_claim("y", "x");

        assert_ne!(xy.contract.concept_hint, yx.contract.concept_hint);
        assert_eq!(xy.to, yx.to, "bind-result payload CID must ignore sidecar");
        assert_eq!(xy.cid(), yx.cid(), "bind claim CID must ignore sidecar");
    }

    #[test]
    fn site_cid_ignores_source_file_provenance() {
        let entry = BindLiftEntry {
            fn_name: "deposit".to_string(),
            ..serde_json::from_value(json!({})).expect("default entry deserializes")
        };
        let mut entry_with_file = entry.clone();
        entry_with_file.file = "src/lib.rs".to_string();
        let mut entry_with_source_function = entry.clone();
        entry_with_source_function.fn_name = "depositSource".to_string();
        let term_shape_cid = "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";

        assert_eq!(
            site_cid(&entry, "concept:deposit", term_shape_cid).expect("site cid"),
            site_cid(&entry_with_file, "concept:deposit", term_shape_cid).expect("site cid")
        );
        assert_eq!(
            site_cid(&entry, "concept:deposit", term_shape_cid).expect("site cid"),
            site_cid(
                &entry_with_source_function,
                "concept:deposit",
                term_shape_cid
            )
            .expect("site cid")
        );
    }

    #[test]
    fn bind_payload_cid_ignores_source_function_name() {
        fn lifted_add(fn_name: &str) -> Term {
            Term::Const {
                value: json!({
                    "kind": "ir-document",
                    "sourceLanguage": "rust",
                    "ir": [{
                        "kind": "bind-lift-entry",
                        "fn_name": fn_name,
                        "concept_annotation": "add",
                        "param_names": ["x", "y"],
                        "param_types": ["i64", "i64"],
                        "return_type": "i64",
                        "term_shape": {"kind": "bin", "op": "+"},
                        "witnesses": []
                    }]
                }),
                sort: primitive_sort("LiftPluginResponse"),
            }
        }

        let kit = BindKit::new(BindOptions {
            lang: "rust".to_string(),
        });

        let add_claim = kit
            .transform(&Input::Term(lifted_add("add")))
            .expect("bind add succeeds");
        let adder_claim = kit
            .transform(&Input::Term(lifted_add("adder")))
            .expect("bind adder succeeds");

        // The named-term-document CID (artifacts) must be stable across renames (#1093)
        assert_eq!(
            add_claim.artifacts, adder_claim.artifacts,
            "source function name must not affect the named-term-document CID"
        );
        // The payload CID (to) and payload bytes legitimately differ because fn_name_sugar
        // rides in the wire citations as a non-CID-affecting annotation at the citation level.
        // Verify that the recovered named-term-document has function="" in both cases,
        // which is the load-bearing #1093 invariant.
        let add_payload = add_claim.payload.as_ref().expect("add claim has payload");
        let adder_payload = adder_claim
            .payload
            .as_ref()
            .expect("adder claim has payload");
        let add_named = named_term_document_from_bind_payload(add_payload)
            .expect("recover add named term document");
        let adder_named = named_term_document_from_bind_payload(adder_payload)
            .expect("recover adder named term document");
        assert!(
            add_named.terms[0].function.is_empty(),
            "recovered function must be empty for add (fn name lives in fn_name_sugar)"
        );
        assert!(
            adder_named.terms[0].function.is_empty(),
            "recovered function must be empty for adder (fn name lives in fn_name_sugar)"
        );
        assert_eq!(
            add_named.terms[0].fn_name_sugar.as_deref(),
            Some("add"),
            "fn_name_sugar carries the source function name in the wire form"
        );
        assert_eq!(
            adder_named.terms[0].fn_name_sugar.as_deref(),
            Some("adder"),
            "fn_name_sugar carries the source function name in the wire form"
        );
    }

    #[test]
    fn named_term_document_cid_ignores_source_function_name() {
        fn document(function: &str) -> NamedTermDocument {
            NamedTermDocument {
                candidate_cluster_manifest: CandidateClusterManifest::default(),
                kind: "named-term-document".to_string(),
                schema_version: "1".to_string(),
                source_language: "rust".to_string(),
                terms: vec![NamedTerm {
                    op_cid: "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string(),
                    discharge_verdict: "loudly-bounded-lossy".to_string(),
                    file: String::new(),
                    function: function.to_string(),
                    fn_name_sugar: None,
                    name: "add".to_string(),
                    param_types: vec!["i64".to_string(), "i64".to_string()],
                    params: vec!["x".to_string(), "y".to_string()],
                    return_type: "i64".to_string(),
                    visibility: String::new(),
                    generic_params: String::new(),
                    original_param_types: vec![],
                    param_sort_cids: vec![],
                    return_sort_cid: String::new(),
                    site_memento_cid: "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222".to_string(),
                    term_shape: json!({"kind": "bin", "op": "+"}),
                    term_shape_cid: "blake3-512:33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333".to_string(),
                    witnesses: vec![],
                    doc_lines: vec![],
                }],
                boundary_entries: vec![],
                trait_decls: vec![],
                module_items: vec![],
                workspace_root: None,
            }
        }

        assert_eq!(
            named_term_document_cid(&document("add")).expect("add document cid"),
            named_term_document_cid(&document("adder")).expect("adder document cid")
        );
    }

    #[test]
    fn named_term_document_omits_empty_source_provenance_fields() {
        let document = NamedTermDocument {
            candidate_cluster_manifest: CandidateClusterManifest::default(),
            kind: "named-term-document".to_string(),
            schema_version: "1".to_string(),
            source_language: "rust".to_string(),
            terms: vec![NamedTerm {
                op_cid: "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string(),
                discharge_verdict: "loudly-bounded-lossy".to_string(),
                file: String::new(),
                function: String::new(),
                fn_name_sugar: None,
                name: "concept:deposit".to_string(),
                param_types: vec!["i64".to_string()],
                params: vec!["balance".to_string()],
                return_type: "i64".to_string(),
                visibility: String::new(),
                generic_params: String::new(),
                original_param_types: vec![],
                param_sort_cids: vec![],
                return_sort_cid: String::new(),
                site_memento_cid: "blake3-512:22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222".to_string(),
                term_shape: json!({}),
                term_shape_cid: "blake3-512:33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333".to_string(),
                witnesses: vec![],
                doc_lines: vec![],
            }],
            boundary_entries: vec![],
            trait_decls: vec![],
            module_items: vec![],
            workspace_root: None,
        };

        let value = serde_json::to_value(&document).expect("named term document serializes");

        assert!(
            value["terms"][0].get("file").is_none(),
            "empty file provenance should not serialize into named term JSON: {value}"
        );
        assert!(
            value["terms"][0].get("function").is_none(),
            "empty function provenance should not serialize into named term JSON: {value}"
        );
    }

    #[test]
    fn bind_lift_entry_omits_default_fn_line_when_serialized() {
        let entry: BindLiftEntry =
            serde_json::from_value(json!({"fn_name": "deposit"})).expect("entry deserializes");

        let value = serde_json::to_value(&entry).expect("bind lift entry serializes");

        assert!(
            value.get("fn_line").is_none(),
            "default fn_line should not serialize: {value}"
        );
    }
}
