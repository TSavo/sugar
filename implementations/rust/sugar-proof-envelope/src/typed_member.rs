// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Typed per-kind Member model for sugar-proof-envelope.
//
// Architecture: ONE normalizer (`normalize`) handles all three wire shapes:
//   v1.1-flat   : root has `evidence` key  → fields come from `evidence.body`
//   v1.2-layered: root has `envelope` key  → fields from `header`, `metadata`,
//                                            `envelope.header`, `envelope.metadata`
//   lean        : root has `header`/`body` → fields from `header`, `body`, `metadata`
//
// All typed parsing funnels through `normalize`. No other function replicates
// the shape-ladder logic.

use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs};
use sugar_ir_types::Sort;

use crate::proof_graph::{AtomCid, ContractBodyCid, MementoCid};

// ─── Error ───────────────────────────────────────────────────────────────────

#[derive(Debug, thiserror::Error)]
pub enum MemberError {
    #[error("member JSON parse error: {0}")]
    JsonParse(String),

    #[error("member has no kind discriminator (checked header.kind, envelope.header.kind, evidence.kind)")]
    MissingKind,

    #[error("unknown member kind: `{kind}` (known kinds: {known})")]
    UnknownKind { kind: String, known: &'static str },

    #[error("member kind `{0}` is known, but no typed Member wrapper is registered")]
    UnsupportedTypedWrapper(MemberKind),

    #[error("{kind}: required string field `{field}` is absent or not a string")]
    MissingRequiredField { kind: String, field: String },

    #[error("{kind}: required array field `{field}` is absent or not an array")]
    MissingRequiredArray { kind: String, field: String },

    #[error(
        "{kind}: field `{field}` has invalid CID format (expected blake3-512: prefix): `{raw}`"
    )]
    InvalidCidFormat {
        kind: String,
        field: String,
        raw: String,
    },

    #[error("context-manager-contract: {0}")]
    InvalidContextManagerContract(String),

    #[error("CID not present in graph: {0}")]
    UnknownCid(String),
}

// ─── Member kind ────────────────────────────────────────────────────────────

pub const KNOWN_MEMBER_KINDS: &str = "aliasing-memento, assertion-surface-memento, authority, bridge, closure-binding, context-manager-contract, contract, effect-site-annotation, factory-walk-memento, implication, library-sugar-binding-entry, loop-invariant, pin-invariant, plan-memento, proof-run, source-memento, stage-receipt, try-branch, witness, witness-memento";

/// Wire member kind. Strings enter and leave only at serde/display boundaries;
/// production branching should match this enum exhaustively.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum MemberKind {
    AliasingMemento,
    AssertionSurfaceMemento,
    Authority,
    Bridge,
    ClosureBinding,
    Contract,
    ContextManagerContract,
    EffectSiteAnnotation,
    FactoryWalkMemento,
    Implication,
    LibrarySugarBindingEntry,
    LoopInvariant,
    PinInvariant,
    PlanMemento,
    ProofRun,
    SourceMemento,
    StageReceipt,
    TryBranch,
    Witness,
    WitnessMemento,
}

impl MemberKind {
    pub fn as_str(self) -> &'static str {
        match self {
            MemberKind::AliasingMemento => "aliasing-memento",
            MemberKind::AssertionSurfaceMemento => "assertion-surface-memento",
            MemberKind::Authority => "authority",
            MemberKind::Bridge => "bridge",
            MemberKind::ClosureBinding => "closure-binding",
            MemberKind::Contract => "contract",
            MemberKind::ContextManagerContract => "context-manager-contract",
            MemberKind::EffectSiteAnnotation => "effect-site-annotation",
            MemberKind::FactoryWalkMemento => "factory-walk-memento",
            MemberKind::Implication => "implication",
            MemberKind::LibrarySugarBindingEntry => "library-sugar-binding-entry",
            MemberKind::LoopInvariant => "loop-invariant",
            MemberKind::PinInvariant => "pin-invariant",
            MemberKind::PlanMemento => "plan-memento",
            MemberKind::ProofRun => "proof-run",
            MemberKind::SourceMemento => "source-memento",
            MemberKind::StageReceipt => "stage-receipt",
            MemberKind::TryBranch => "try-branch",
            MemberKind::Witness => "witness",
            MemberKind::WitnessMemento => "witness-memento",
        }
    }
}

impl fmt::Display for MemberKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for MemberKind {
    type Err = MemberError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "aliasing-memento" => Ok(MemberKind::AliasingMemento),
            "assertion-surface-memento" => Ok(MemberKind::AssertionSurfaceMemento),
            "authority" => Ok(MemberKind::Authority),
            "bridge" => Ok(MemberKind::Bridge),
            "closure-binding" => Ok(MemberKind::ClosureBinding),
            "contract" => Ok(MemberKind::Contract),
            "context-manager-contract" => Ok(MemberKind::ContextManagerContract),
            "effect-site-annotation" => Ok(MemberKind::EffectSiteAnnotation),
            "factory-walk-memento" => Ok(MemberKind::FactoryWalkMemento),
            "implication" => Ok(MemberKind::Implication),
            "library-sugar-binding-entry" => Ok(MemberKind::LibrarySugarBindingEntry),
            "loop-invariant" => Ok(MemberKind::LoopInvariant),
            "pin-invariant" => Ok(MemberKind::PinInvariant),
            "plan-memento" => Ok(MemberKind::PlanMemento),
            "proof-run" => Ok(MemberKind::ProofRun),
            "source-memento" => Ok(MemberKind::SourceMemento),
            "stage-receipt" => Ok(MemberKind::StageReceipt),
            "try-branch" => Ok(MemberKind::TryBranch),
            "witness" => Ok(MemberKind::Witness),
            "witness-memento" => Ok(MemberKind::WitnessMemento),
            other => Err(MemberError::UnknownKind {
                kind: other.to_string(),
                known: KNOWN_MEMBER_KINDS,
            }),
        }
    }
}

// ─── Normalizer ──────────────────────────────────────────────────────────────

/// Normalized view of a member envelope, regardless of wire shape.
/// The `layers` are searched in priority order; first match wins.
/// This is the ONE place where shape-ladder knowledge lives.
struct NormalizedBody<'a> {
    kind: MemberKind,
    layers: Vec<&'a serde_json::Map<String, Json>>,
}

impl<'a> NormalizedBody<'a> {
    fn get(&self, name: &str) -> Option<&'a Json> {
        for layer in &self.layers {
            if let Some(v) = layer.get(name) {
                return Some(v);
            };
        }
        None
    }
}

/// The single normalizer. Given the parsed JSON of a member envelope, return
/// a `NormalizedBody` that abstracts all three wire shapes.
fn normalize(v: &Json) -> Result<NormalizedBody<'_>, MemberError> {
    // v1.2-layered: has "envelope" key
    if v.get("envelope").is_some() {
        let kind = v
            .pointer("/header/kind")
            .or_else(|| v.pointer("/envelope/header/kind"))
            .and_then(Json::as_str)
            .ok_or(MemberError::MissingKind)?;
        let mut layers: Vec<&serde_json::Map<String, Json>> = Vec::new();
        if let Some(h) = v.get("header").and_then(Json::as_object) {
            layers.push(h);
        }
        if let Some(m) = v.get("metadata").and_then(Json::as_object) {
            layers.push(m);
        }
        if let Some(eh) = v.pointer("/envelope/header").and_then(Json::as_object) {
            layers.push(eh);
        }
        if let Some(em) = v.pointer("/envelope/metadata").and_then(Json::as_object) {
            layers.push(em);
        }
        return Ok(NormalizedBody {
            kind: kind.parse()?,
            layers,
        });
    }
    // lean: has "header" or "body" but no "envelope"
    if v.get("header").is_some() || v.get("body").is_some() {
        let kind = v
            .pointer("/header/kind")
            .and_then(Json::as_str)
            .ok_or(MemberError::MissingKind)?;
        let mut layers: Vec<&serde_json::Map<String, Json>> = Vec::new();
        if let Some(h) = v.get("header").and_then(Json::as_object) {
            layers.push(h);
        }
        if let Some(b) = v.get("body").and_then(Json::as_object) {
            layers.push(b);
        }
        if let Some(m) = v.get("metadata").and_then(Json::as_object) {
            layers.push(m);
        }
        return Ok(NormalizedBody {
            kind: kind.parse()?,
            layers,
        });
    }
    // v1.1-flat: has "evidence" key, fields in evidence.body
    if v.get("evidence").is_some() {
        let kind = v
            .pointer("/evidence/kind")
            .and_then(Json::as_str)
            .ok_or(MemberError::MissingKind)?;
        let mut layers: Vec<&serde_json::Map<String, Json>> = Vec::new();
        if let Some(b) = v.pointer("/evidence/body").and_then(Json::as_object) {
            layers.push(b);
        }
        // Some v1.1 shapes also carry top-level fields outside evidence.body
        if let Some(obj) = v.as_object() {
            layers.push(obj);
        }
        return Ok(NormalizedBody {
            kind: kind.parse()?,
            layers,
        });
    }
    Err(MemberError::MissingKind)
}

// ─── Field extractors ────────────────────────────────────────────────────────

fn get_str(nb: &NormalizedBody<'_>, name: &str) -> Option<String> {
    nb.get(name).and_then(Json::as_str).map(str::to_string)
}

fn get_bool(nb: &NormalizedBody<'_>, name: &str) -> Option<bool> {
    nb.get(name).and_then(Json::as_bool)
}

fn get_i64(nb: &NormalizedBody<'_>, name: &str) -> Option<i64> {
    nb.get(name).and_then(Json::as_i64)
}

fn get_json(nb: &NormalizedBody<'_>, name: &str) -> Option<Json> {
    nb.get(name).cloned()
}

fn get_vec_str(nb: &NormalizedBody<'_>, name: &str) -> Option<Vec<String>> {
    nb.get(name).and_then(Json::as_array).map(|arr| {
        arr.iter()
            .filter_map(Json::as_str)
            .map(str::to_string)
            .collect()
    })
}

fn get_vec_json(nb: &NormalizedBody<'_>, name: &str) -> Option<Vec<Json>> {
    nb.get(name)
        .and_then(Json::as_array)
        .map(|arr| arr.to_vec())
}

fn require_str(nb: &NormalizedBody<'_>, name: &str, kind: &str) -> Result<String, MemberError> {
    get_str(nb, name).ok_or_else(|| MemberError::MissingRequiredField {
        kind: kind.to_string(),
        field: name.to_string(),
    })
}

fn require_i64(nb: &NormalizedBody<'_>, name: &str, kind: &str) -> Result<i64, MemberError> {
    get_i64(nb, name).ok_or_else(|| MemberError::MissingRequiredField {
        kind: kind.to_string(),
        field: name.to_string(),
    })
}

fn require_vec_str(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<Vec<String>, MemberError> {
    get_vec_str(nb, name).ok_or_else(|| MemberError::MissingRequiredArray {
        kind: kind.to_string(),
        field: name.to_string(),
    })
}

fn require_memento_cid(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<MementoCid, MemberError> {
    let s = require_str(nb, name, kind)?;
    MementoCid::try_parse(s).map_err(|raw| MemberError::InvalidCidFormat {
        kind: kind.to_string(),
        field: name.to_string(),
        raw,
    })
}

fn get_memento_cid(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<Option<MementoCid>, MemberError> {
    match get_str(nb, name) {
        None => Ok(None),
        Some(s) => {
            MementoCid::try_parse(s)
                .map(Some)
                .map_err(|raw| MemberError::InvalidCidFormat {
                    kind: kind.to_string(),
                    field: name.to_string(),
                    raw,
                })
        }
    }
}

fn require_vec_memento_cid(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<Vec<MementoCid>, MemberError> {
    let strs = require_vec_str(nb, name, kind)?;
    strs.into_iter()
        .map(|s| {
            MementoCid::try_parse(s).map_err(|raw| MemberError::InvalidCidFormat {
                kind: kind.to_string(),
                field: name.to_string(),
                raw,
            })
        })
        .collect()
}

fn get_vec_memento_cid(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<Option<Vec<MementoCid>>, MemberError> {
    match get_vec_str(nb, name) {
        None => Ok(None),
        Some(strs) => strs
            .into_iter()
            .map(|s| {
                MementoCid::try_parse(s).map_err(|raw| MemberError::InvalidCidFormat {
                    kind: kind.to_string(),
                    field: name.to_string(),
                    raw,
                })
            })
            .collect::<Result<Vec<_>, _>>()
            .map(Some),
    }
}

fn require_atom_cid(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<AtomCid, MemberError> {
    let s = require_str(nb, name, kind)?;
    Ok(AtomCid::from_raw(s))
}

fn get_atom_cid(nb: &NormalizedBody<'_>, name: &str) -> Option<AtomCid> {
    get_str(nb, name).map(AtomCid::from_raw)
}

fn require_vec_atom_cid(
    nb: &NormalizedBody<'_>,
    name: &str,
    kind: &str,
) -> Result<Vec<AtomCid>, MemberError> {
    let strs = require_vec_str(nb, name, kind)?;
    Ok(strs.into_iter().map(AtomCid::from_raw).collect())
}

fn get_vec_atom_cid(nb: &NormalizedBody<'_>, name: &str) -> Option<Vec<AtomCid>> {
    get_vec_str(nb, name).map(|v| v.into_iter().map(AtomCid::from_raw).collect())
}

// ─── Per-kind structs ────────────────────────────────────────────────────────

/// kind = "contract"
#[derive(Debug, Clone)]
pub struct ContractMember {
    pub cid: MementoCid,
    pub name: String,
    pub contract_name: String,
    pub body_cid: ContractBodyCid,
    // kit-output fields: absent on minimal Rust-built members → Option
    pub out_binding: Option<String>,
    pub verdict: Option<String>,
    pub binding_hash: Option<String>,
    pub property_hash: Option<String>,
    pub input_cids: Option<Vec<MementoCid>>,
    // optional
    pub pre: Option<Json>,
    pub post: Option<Json>,
    pub inv: Option<Json>,
    pub formals: Option<Vec<String>>,
    pub formal_sorts: Option<Vec<Json>>,
    pub panic_loci: Option<Vec<Json>>,
    pub class_shapes: Option<Vec<Json>>,
    pub source_warrants: Option<Vec<Json>>,
    pub evidence: Option<Json>,
    pub post_hash: Option<String>,
    pub pre_hash: Option<String>,
    pub inv_hash: Option<String>,
    pub library: Option<String>,
    pub body_discharge_eligible: Option<bool>,
    pub body_discharge_refusal_reason: Option<String>,
    pub discharge_policy: Option<Json>,
}

impl ContractMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "contract";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            name: require_str(nb, "name", K)?,
            contract_name: require_str(nb, "contractName", K)?,
            body_cid: ContractBodyCid::from_raw(require_str(nb, "bodyCid", K)?),
            out_binding: get_str(nb, "outBinding"),
            verdict: get_str(nb, "verdict"),
            binding_hash: get_str(nb, "bindingHash"),
            property_hash: get_str(nb, "propertyHash"),
            input_cids: get_vec_memento_cid(nb, "inputCids", K)?,
            pre: get_json(nb, "pre"),
            post: get_json(nb, "post"),
            inv: get_json(nb, "inv"),
            formals: get_vec_str(nb, "formals"),
            formal_sorts: get_vec_json(nb, "formalSorts"),
            panic_loci: get_vec_json(nb, "panicLoci"),
            class_shapes: get_vec_json(nb, "classShapes"),
            source_warrants: get_vec_json(nb, "sourceWarrants"),
            evidence: get_json(nb, "evidence"),
            post_hash: get_str(nb, "postHash"),
            pre_hash: get_str(nb, "preHash"),
            inv_hash: get_str(nb, "invHash"),
            library: get_str(nb, "library"),
            body_discharge_eligible: get_bool(nb, "bodyDischargeEligible"),
            body_discharge_refusal_reason: get_str(nb, "bodyDischargeRefusalReason"),
            discharge_policy: get_json(nb, "dischargePolicy"),
        })
    }
}

/// kind = "bridge"
#[derive(Debug, Clone)]
pub struct BridgeMember {
    pub cid: MementoCid,
    pub source_symbol: String,
    pub target_contract_cid: MementoCid,
    // kit-output fields: absent on minimal members → Option
    pub source_layer: Option<String>,
    pub target_layer: Option<String>,
    pub ir_arg_sorts: Option<Vec<String>>,
    pub ir_return_sort: Option<String>,
    pub verdict: Option<String>,
    pub binding_hash: Option<String>,
    pub property_hash: Option<String>,
    pub input_cids: Option<Vec<MementoCid>>,
    pub target_proof_cid: Option<MementoCid>,
    pub callsite: Option<Json>,
    pub source_contract_cid: Option<MementoCid>,
    pub name: Option<String>,
}

impl BridgeMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "bridge";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            source_symbol: require_str(nb, "sourceSymbol", K)?,
            target_contract_cid: require_memento_cid(nb, "targetContractCid", K)?,
            source_layer: get_str(nb, "sourceLayer"),
            target_layer: get_str(nb, "targetLayer"),
            ir_arg_sorts: get_vec_str(nb, "irArgSorts"),
            ir_return_sort: get_str(nb, "irReturnSort"),
            verdict: get_str(nb, "verdict"),
            binding_hash: get_str(nb, "bindingHash"),
            property_hash: get_str(nb, "propertyHash"),
            input_cids: get_vec_memento_cid(nb, "inputCids", K)?,
            target_proof_cid: get_memento_cid(nb, "targetProofCid", K)?,
            callsite: get_json(nb, "callsite"),
            source_contract_cid: get_memento_cid(nb, "sourceContractCid", K)?,
            name: get_str(nb, "name"),
        })
    }
}

/// kind = "implication"
#[derive(Debug, Clone)]
pub struct ImplicationMember {
    pub cid: MementoCid,
    pub antecedent_cid: MementoCid,
    pub consequent_cid: MementoCid,
    // kit-output fields: absent on minimal members → Option
    pub antecedent_hash: Option<String>,
    pub consequent_hash: Option<String>,
    pub antecedent_slot: Option<String>,
    pub consequent_slot: Option<String>,
    pub verdict: Option<String>,
    pub binding_hash: Option<String>,
    pub property_hash: Option<String>,
    pub input_cids: Option<Vec<MementoCid>>,
    pub prover: Option<String>,
    pub prover_run_ms: Option<i64>,
    pub smt_lib_input: Option<String>,
    pub proof_witness: Option<String>,
}

impl ImplicationMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "implication";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            antecedent_cid: require_memento_cid(nb, "antecedentCid", K)?,
            consequent_cid: require_memento_cid(nb, "consequentCid", K)?,
            antecedent_hash: get_str(nb, "antecedentHash"),
            consequent_hash: get_str(nb, "consequentHash"),
            antecedent_slot: get_str(nb, "antecedentSlot"),
            consequent_slot: get_str(nb, "consequentSlot"),
            verdict: get_str(nb, "verdict"),
            binding_hash: get_str(nb, "bindingHash"),
            property_hash: get_str(nb, "propertyHash"),
            input_cids: get_vec_memento_cid(nb, "inputCids", K)?,
            prover: get_str(nb, "prover"),
            prover_run_ms: get_i64(nb, "proverRunMs"),
            smt_lib_input: get_str(nb, "smtLibInput"),
            proof_witness: get_str(nb, "proofWitness"),
        })
    }
}

/// kind = "authority"
#[derive(Debug, Clone)]
pub struct AuthorityMember {
    pub cid: MementoCid,
    pub principal: String,
    pub key: String,
    pub scope_kind: String,
    pub scope: String,
    // kit-output fields: absent on minimal members → Option
    pub verdict: Option<String>,
    pub input_cids: Option<Vec<MementoCid>>,
    pub parent_authority_cid: Option<MementoCid>,
    pub authority_claim: Option<String>,
}

impl AuthorityMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "authority";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            principal: require_str(nb, "principal", K)?,
            key: require_str(nb, "key", K)?,
            scope_kind: require_str(nb, "scopeKind", K)?,
            scope: require_str(nb, "scope", K)?,
            verdict: get_str(nb, "verdict"),
            input_cids: get_vec_memento_cid(nb, "inputCids", K)?,
            parent_authority_cid: get_memento_cid(nb, "parentAuthorityCid", K)?,
            authority_claim: get_str(nb, "authorityClaim"),
        })
    }
}

/// kind = "witness"
#[derive(Debug, Clone)]
pub struct WitnessClaimMember {
    pub cid: MementoCid,
    pub claim_kind: String,
    pub claim_body_cid: AtomCid,
    // kit-output fields: absent on minimal members → Option
    pub verdict: Option<String>,
    pub verifier_cid: Option<AtomCid>,
    pub policy_cid: Option<AtomCid>,
    pub evidence_root_cid: Option<AtomCid>,
    pub input_cids: Option<Vec<MementoCid>>,
    pub claim_body: Option<Json>,
    pub evidence: Option<Json>,
}

impl WitnessClaimMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "witness";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            claim_kind: require_str(nb, "claimKind", K)?,
            claim_body_cid: require_atom_cid(nb, "claimBodyCid", K)?,
            verdict: get_str(nb, "verdict"),
            verifier_cid: get_atom_cid(nb, "verifierCid"),
            policy_cid: get_atom_cid(nb, "policyCid"),
            evidence_root_cid: get_atom_cid(nb, "evidenceRootCid"),
            input_cids: get_vec_memento_cid(nb, "inputCids", K)?,
            claim_body: get_json(nb, "claimBody"),
            evidence: get_json(nb, "evidence"),
        })
    }
}

/// kind = "witness-memento"
#[derive(Debug, Clone)]
pub struct WitnessMementoMember {
    pub witness_cid: AtomCid,
    pub signer: String,
    pub witness_kind: String,
}

impl WitnessMementoMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "witness-memento";
        Ok(Self {
            witness_cid: require_atom_cid(nb, "witnessCid", K)?,
            signer: require_str(nb, "signer", K)?,
            witness_kind: require_str(nb, "witnessKind", K)?,
        })
    }
}

/// kind = "source-memento"
#[derive(Debug, Clone)]
pub struct SourceMementoMember {
    pub source_cid: AtomCid,
    // all optional
    pub contract_name: Option<String>,
    pub claim_name: Option<String>,
    pub euf_name: Option<String>,
    pub file: Option<String>,
    pub role: Option<String>,
    pub source_function_name: Option<String>,
    pub universe_kind: Option<String>,
}

impl SourceMementoMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "source-memento";
        Ok(Self {
            source_cid: require_atom_cid(nb, "sourceCid", K)?,
            contract_name: get_str(nb, "contractName"),
            claim_name: get_str(nb, "claimName"),
            euf_name: get_str(nb, "eufName"),
            file: get_str(nb, "file"),
            role: get_str(nb, "role"),
            source_function_name: get_str(nb, "sourceFunctionName"),
            universe_kind: get_str(nb, "universeKind"),
        })
    }
}

/// kind = "plan-memento"
#[derive(Debug, Clone)]
pub struct PlanMementoMember {
    pub plan_cid: AtomCid,
    // optional
    pub expected_output_cids: Option<Vec<MementoCid>>,
    pub plan_atoms: Option<Vec<Json>>,
    pub plan_atom_cids: Option<Vec<AtomCid>>,
}

impl PlanMementoMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "plan-memento";
        Ok(Self {
            plan_cid: require_atom_cid(nb, "planCid", K)?,
            expected_output_cids: get_vec_memento_cid(nb, "expectedOutputCids", K)?,
            plan_atoms: get_vec_json(nb, "planAtoms"),
            plan_atom_cids: get_vec_atom_cid(nb, "planAtomCids"),
        })
    }
}

/// kind = "factory-walk-memento"  (all fields optional per Scope)
#[derive(Debug, Clone)]
pub struct FactoryWalkMementoMember {
    pub file: Option<String>,
    pub line: Option<i64>,
    pub status: Option<String>,
    pub verdict: Option<String>,
    pub output: Option<Json>,
    pub selected: Option<Json>,
    pub source_function_name: Option<String>,
    pub contract_name: Option<String>,
    pub claim_name: Option<String>,
}

impl FactoryWalkMementoMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        Ok(Self {
            file: get_str(nb, "file"),
            line: get_i64(nb, "line"),
            status: get_str(nb, "status"),
            verdict: get_str(nb, "verdict"),
            output: get_json(nb, "output"),
            selected: get_json(nb, "selected"),
            source_function_name: get_str(nb, "sourceFunctionName"),
            contract_name: get_str(nb, "contractName"),
            claim_name: get_str(nb, "claimName"),
        })
    }
}

/// kind = "assertion-surface-memento"  (all fields optional per Scope)
#[derive(Debug, Clone)]
pub struct AssertionSurfaceMementoMember {
    pub surface: Option<String>,
    pub file: Option<String>,
    pub line: Option<i64>,
    pub col: Option<i64>,
    pub status: Option<String>,
    pub source_status: Option<String>,
    pub assertion_source: Option<String>,
    pub source_cid: Option<AtomCid>,
    pub claim_name: Option<String>,
    pub contract_name: Option<String>,
    pub source_function_name: Option<String>,
}

impl AssertionSurfaceMementoMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        Ok(Self {
            surface: get_str(nb, "surface"),
            file: get_str(nb, "file"),
            line: get_i64(nb, "line"),
            col: get_i64(nb, "col"),
            status: get_str(nb, "status"),
            source_status: get_str(nb, "sourceStatus"),
            assertion_source: get_str(nb, "assertionSource"),
            source_cid: get_atom_cid(nb, "sourceCid"),
            claim_name: get_str(nb, "claimName"),
            contract_name: get_str(nb, "contractName"),
            source_function_name: get_str(nb, "sourceFunctionName"),
        })
    }
}

/// kind = "library-sugar-binding-entry"
#[derive(Debug, Clone)]
pub struct LibrarySugarBindingEntryMember {
    pub body_source_cid: AtomCid,
    pub signature_shape_cid: AtomCid,
    pub target_language: String,
    pub target_library_tag: String,
    // optional
    pub symbol: Option<String>,
    pub op_cid: Option<AtomCid>,
}

impl LibrarySugarBindingEntryMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "library-sugar-binding-entry";
        Ok(Self {
            body_source_cid: require_atom_cid(nb, "bodySourceCid", K)?,
            signature_shape_cid: require_atom_cid(nb, "signatureShapeCid", K)?,
            target_language: require_str(nb, "targetLanguage", K)?,
            target_library_tag: require_str(nb, "targetLibraryTag", K)?,
            symbol: get_str(nb, "symbol"),
            op_cid: get_atom_cid(nb, "opCid"),
        })
    }
}

/// kind = "effect-site-annotation"
#[derive(Debug, Clone)]
pub struct EffectSiteAnnotationMember {
    pub cid: MementoCid,
    pub effect_kind: String,
    pub file: String,
    pub line: i64,
    pub callee: String,
    pub status: String,
    pub category: String,
    pub tier_to_close: String,
    pub reason: String,
    pub input_cids: Vec<MementoCid>,
}

impl EffectSiteAnnotationMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "effect-site-annotation";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            effect_kind: require_str(nb, "effectKind", K)?,
            file: require_str(nb, "file", K)?,
            line: require_i64(nb, "line", K)?,
            callee: require_str(nb, "callee", K)?,
            status: require_str(nb, "status", K)?,
            category: require_str(nb, "category", K)?,
            tier_to_close: require_str(nb, "tierToClose", K)?,
            reason: require_str(nb, "reason", K)?,
            input_cids: require_vec_memento_cid(nb, "inputCids", K)?,
        })
    }
}

/// kind = "proof-run"
/// Note: snake_case field names match the wire encoding for this kind.
#[derive(Debug, Clone)]
pub struct ProofRunMember {
    pub cid: MementoCid,
    pub verdict: String,
    pub sealed_at: String,
    pub proof_envelope_cid: MementoCid,
    pub link_bundle_cid: MementoCid,
    pub verifier_pipeline_cid: AtomCid,
    pub plugin_registry_cid: AtomCid,
    pub input_artifact_cids: Vec<AtomCid>,
    pub output_artifact_cids: Vec<AtomCid>,
    pub input_run_cids: Vec<MementoCid>,
    pub stage_receipt_cids: Vec<MementoCid>,
}

impl ProofRunMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "proof-run";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            verdict: require_str(nb, "verdict", K)?,
            sealed_at: require_str(nb, "sealed_at", K)?,
            proof_envelope_cid: require_memento_cid(nb, "proof_envelope_cid", K)?,
            link_bundle_cid: require_memento_cid(nb, "link_bundle_cid", K)?,
            verifier_pipeline_cid: require_atom_cid(nb, "verifier_pipeline_cid", K)?,
            plugin_registry_cid: require_atom_cid(nb, "plugin_registry_cid", K)?,
            input_artifact_cids: require_vec_atom_cid(nb, "input_artifact_cids", K)?,
            output_artifact_cids: require_vec_atom_cid(nb, "output_artifact_cids", K)?,
            input_run_cids: require_vec_memento_cid(nb, "input_run_cids", K)?,
            stage_receipt_cids: require_vec_memento_cid(nb, "stage_receipt_cids", K)?,
        })
    }
}

/// kind = "stage-receipt"
/// Note: snake_case field names match the wire encoding for this kind.
#[derive(Debug, Clone)]
pub struct StageReceiptMember {
    pub cid: MementoCid,
    pub stage_name: String,
    pub verdict: String,
    pub started_at: String,
    pub finished_at: String,
    pub input_cids: Vec<AtomCid>,
    pub output_cids: Vec<AtomCid>,
    pub refusal_cids: Vec<AtomCid>,
    // optional
    pub diagnostics: Option<Vec<Json>>,
}

impl StageReceiptMember {
    fn from_normalized(nb: &NormalizedBody<'_>) -> Result<Self, MemberError> {
        const K: &str = "stage-receipt";
        Ok(Self {
            cid: require_memento_cid(nb, "cid", K)?,
            stage_name: require_str(nb, "stage_name", K)?,
            verdict: require_str(nb, "verdict", K)?,
            started_at: require_str(nb, "started_at", K)?,
            finished_at: require_str(nb, "finished_at", K)?,
            input_cids: require_vec_atom_cid(nb, "input_cids", K)?,
            output_cids: require_vec_atom_cid(nb, "output_cids", K)?,
            refusal_cids: require_vec_atom_cid(nb, "refusal_cids", K)?,
            diagnostics: get_vec_json(nb, "diagnostics"),
        })
    }
}

// ─── Member enum + parse entrypoint ──────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContextManagerContractMember {
    pub payload_cid: MementoCid,
    pub bridge_source_symbol: String,
    pub import_signature: ImportSignatureV2,
    pub semantics: ContextManagerSemanticsV1,
    pub source_warrants: Vec<String>,
    pub input_cids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImportSignatureV2 {
    pub parameters: Vec<CallParameterV1>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CallParameterV1 {
    pub name: String,
    pub sort: Sort,
    pub passing: ParameterPassingV1,
    pub required: bool,
    pub default: ParameterDefaultV1,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
#[serde(deny_unknown_fields)]
pub enum ParameterPassingV1 {
    #[serde(rename = "positional-only")]
    PositionalOnly,
    #[serde(rename = "positional-or-keyword")]
    PositionalOrKeyword,
    #[serde(rename = "keyword-only")]
    KeywordOnly,
    #[serde(rename = "variadic-positional")]
    VariadicPositional,
    #[serde(rename = "variadic-keyword")]
    VariadicKeyword,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
#[serde(deny_unknown_fields)]
pub enum ParameterDefaultV1 {
    #[serde(rename = "no-default")]
    NoDefault,
    #[serde(rename = "literal-default")]
    LiteralDefault { value: Json },
    #[serde(rename = "provider-value-ref")]
    ProviderValueRef {
        #[serde(rename = "valueRefCid")]
        value_ref_cid: String,
        sort: Sort,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ContextManagerSemanticsV1 {
    ProtocolResource(ResourceSemanticsV1),
    EffectBoundary(EffectBoundarySemanticsV1),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceSemanticsV1 {
    pub enter: EnterResultContractV1,
    pub exit: ExitContractV1,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TotalCompletionV1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnterResultContractV1 {
    pub completion: TotalCompletionV1,
    pub sort: Sort,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExitContractV1 {
    pub completion: TotalCompletionV1,
    pub disposition: ExitDispositionV1,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExitDispositionV1 {
    NeverSuppresses,
    ReturnTruthiness,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectBoundaryModeV1 {
    Expects,
    Suppresses,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectKindV1 {
    Raise,
    Warning,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FormalSelectorV1 {
    FormalArgument {
        parameter_index: u32,
    },
    OptionalFormalArgument {
        parameter_index: u32,
    },
    VariadicPositionalElement {
        parameter_index: u32,
        element_index: u32,
    },
    VariadicKeywordEntry {
        parameter_index: u32,
        keyword: String,
    },
}
impl FormalSelectorV1 {
    pub fn parameter_index(&self) -> u32 {
        match self {
            Self::FormalArgument { parameter_index }
            | Self::OptionalFormalArgument { parameter_index }
            | Self::VariadicPositionalElement {
                parameter_index, ..
            }
            | Self::VariadicKeywordEntry {
                parameter_index, ..
            } => *parameter_index,
        }
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MessagePatternProjectionV1 {
    None,
    OptionalFormalArgument {
        parameter_index: u32,
    },
    VariadicPositionalElement {
        parameter_index: u32,
        element_index: u32,
    },
    VariadicKeywordEntry {
        parameter_index: u32,
        keyword: String,
    },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectBoundaryBindingV1 {
    None,
    ExceptionInfo,
    WarningObservation,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectBoundarySemanticsV1 {
    pub mode: EffectBoundaryModeV1,
    pub effect_kind: EffectKindV1,
    pub expected_type_operand: FormalSelectorV1,
    pub message_pattern_operand: MessagePatternProjectionV1,
    pub binding: EffectBoundaryBindingV1,
}

fn formal_selector_v1_to_json(value: &FormalSelectorV1) -> Json {
    match value {
        FormalSelectorV1::FormalArgument { parameter_index } => {
            serde_json::json!({"kind":"formal-argument","parameterIndex":parameter_index})
        }
        FormalSelectorV1::OptionalFormalArgument { parameter_index } => {
            serde_json::json!({"kind":"optional-formal-argument","parameterIndex":parameter_index})
        }
        FormalSelectorV1::VariadicPositionalElement {
            parameter_index,
            element_index,
        } => {
            serde_json::json!({"kind":"variadic-positional-element","parameterIndex":parameter_index,"elementIndex":element_index})
        }
        FormalSelectorV1::VariadicKeywordEntry {
            parameter_index,
            keyword,
        } => {
            serde_json::json!({"kind":"variadic-keyword-entry","parameterIndex":parameter_index,"keyword":keyword})
        }
    }
}

pub fn context_manager_semantics_v1_to_json(value: &ContextManagerSemanticsV1) -> Json {
    match value {
        ContextManagerSemanticsV1::ProtocolResource(value) => serde_json::json!({
            "kind": "protocol-resource",
            "schemaVersion": "1",
            "enter": {
                "completion": {"kind": "total"},
                "result": {
                    "kind": "projection",
                    "projection": "enter-result",
                    "sort": value.enter.sort,
                },
            },
            "exit": {
                "completion": {"kind": "total"},
                "disposition": {"kind": match value.exit.disposition {
                    ExitDispositionV1::NeverSuppresses => "never-suppresses",
                    ExitDispositionV1::ReturnTruthiness => "return-truthiness",
                }},
            },
        }),
        ContextManagerSemanticsV1::EffectBoundary(value) => serde_json::json!({
            "kind": "effect-boundary", "schemaVersion": "1",
            "mode": {"kind": match value.mode { EffectBoundaryModeV1::Expects => "expects", EffectBoundaryModeV1::Suppresses => "suppresses" }},
            "matcher": {
                "effectKind": {"kind": match value.effect_kind { EffectKindV1::Raise => "raise", EffectKindV1::Warning => "warning" }},
                "expectedTypeOperand": formal_selector_v1_to_json(&value.expected_type_operand),
                "messagePatternOperand": match &value.message_pattern_operand {
                    MessagePatternProjectionV1::None => serde_json::json!({"kind":"none"}),
                    MessagePatternProjectionV1::OptionalFormalArgument { parameter_index } => serde_json::json!({"kind":"optional-formal-argument", "parameterIndex":parameter_index}),
                    MessagePatternProjectionV1::VariadicPositionalElement { parameter_index, element_index } => serde_json::json!({"kind":"variadic-positional-element","parameterIndex":parameter_index,"elementIndex":element_index}),
                    MessagePatternProjectionV1::VariadicKeywordEntry { parameter_index, keyword } => serde_json::json!({"kind":"variadic-keyword-entry","parameterIndex":parameter_index,"keyword":keyword}),
                },
            },
            "binding": {"kind": match value.binding { EffectBoundaryBindingV1::None => "none", EffectBoundaryBindingV1::ExceptionInfo => "exception-info", EffectBoundaryBindingV1::WarningObservation => "warning-observation" }},
        }),
    }
}

pub fn import_signature_v2_to_json(value: &ImportSignatureV2) -> Json {
    serde_json::json!({"parameters": value.parameters})
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ContextManagerHeader {
    #[serde(rename = "schemaVersion")]
    schema_version: String,
    kind: String,
    cid: String,
    #[serde(rename = "payloadCid")]
    payload_cid: String,
    #[serde(rename = "bridgeSourceSymbol")]
    bridge_source_symbol: String,
    #[serde(rename = "importSignature")]
    import_signature: ImportSignatureWire,
    payload: Json,
    #[serde(rename = "sourceWarrants")]
    source_warrants: Vec<String>,
    #[serde(rename = "inputCids")]
    input_cids: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ImportSignatureWire {
    parameters: Vec<CallParameterV1>,
}
fn exact_object<'a>(
    value: &'a Json,
    keys: &[&str],
    owner: &str,
) -> Result<&'a serde_json::Map<String, Json>, String> {
    let object = value
        .as_object()
        .ok_or_else(|| format!("{owner} must be an object"))?;
    let actual = object
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    let expected = keys
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    if actual != expected {
        return Err(format!("malformed {owner}: exact fields required"));
    }
    Ok(object)
}

fn closed_tag(value: &Json, allowed: &[&str], owner: &str) -> Result<String, String> {
    let object = exact_object(value, &["kind"], owner)?;
    let kind = object["kind"]
        .as_str()
        .ok_or_else(|| format!("{owner} kind must be a string"))?;
    if !allowed.contains(&kind) {
        return Err(format!("unknown {owner}: {kind}"));
    }
    Ok(kind.to_string())
}

fn nonnegative_u32(value: &Json, owner: &str) -> Result<u32, String> {
    value
        .as_u64()
        .filter(|v| *v <= u32::MAX as u64)
        .map(|v| v as u32)
        .ok_or_else(|| format!("{owner} must be a nonnegative u32"))
}

fn decode_formal_selector(value: &Json, allow_optional: bool) -> Result<FormalSelectorV1, String> {
    let kind = value
        .get("kind")
        .and_then(Json::as_str)
        .ok_or_else(|| "formal selector kind must be a string".to_string())?;
    match kind {
        "formal-argument" if !allow_optional => {
            let row = exact_object(value, &["kind", "parameterIndex"], "formal selector")?;
            Ok(FormalSelectorV1::FormalArgument {
                parameter_index: nonnegative_u32(&row["parameterIndex"], "parameterIndex")?,
            })
        }
        "optional-formal-argument" if allow_optional => {
            let row = exact_object(value, &["kind", "parameterIndex"], "formal selector")?;
            Ok(FormalSelectorV1::OptionalFormalArgument {
                parameter_index: nonnegative_u32(&row["parameterIndex"], "parameterIndex")?,
            })
        }
        "variadic-positional-element" => {
            let row = exact_object(
                value,
                &["kind", "parameterIndex", "elementIndex"],
                "formal selector",
            )?;
            Ok(FormalSelectorV1::VariadicPositionalElement {
                parameter_index: nonnegative_u32(&row["parameterIndex"], "parameterIndex")?,
                element_index: nonnegative_u32(&row["elementIndex"], "elementIndex")?,
            })
        }
        "variadic-keyword-entry" => {
            let row = exact_object(
                value,
                &["kind", "parameterIndex", "keyword"],
                "formal selector",
            )?;
            let keyword = row["keyword"]
                .as_str()
                .filter(|v| !v.is_empty())
                .ok_or_else(|| "variadic keyword selector requires a keyword".to_string())?;
            Ok(FormalSelectorV1::VariadicKeywordEntry {
                parameter_index: nonnegative_u32(&row["parameterIndex"], "parameterIndex")?,
                keyword: keyword.to_string(),
            })
        }
        other => Err(format!("unknown formal selector: {other}")),
    }
}

fn selector_parameter<'a>(
    selector: &FormalSelectorV1,
    signature: &'a ImportSignatureV2,
) -> Result<&'a CallParameterV1, String> {
    let parameter = signature
        .parameters
        .get(selector.parameter_index() as usize)
        .ok_or_else(|| "selector is outside ImportSignatureV2".to_string())?;
    match selector {
        FormalSelectorV1::FormalArgument { .. }
        | FormalSelectorV1::OptionalFormalArgument { .. }
            if matches!(
                parameter.passing,
                ParameterPassingV1::VariadicPositional | ParameterPassingV1::VariadicKeyword
            ) =>
        {
            Err("fixed selector cannot address a variadic parameter".into())
        }
        FormalSelectorV1::VariadicPositionalElement { .. }
            if parameter.passing != ParameterPassingV1::VariadicPositional =>
        {
            Err("variadic element selector requires *args".into())
        }
        FormalSelectorV1::VariadicKeywordEntry { .. }
            if parameter.passing != ParameterPassingV1::VariadicKeyword =>
        {
            Err("variadic keyword selector requires **kwargs".into())
        }
        _ => Ok(parameter),
    }
}

fn validate_literal_default(value: &Json) -> Result<Option<Sort>, String> {
    let object = value
        .as_object()
        .ok_or_else(|| "literal default must be an exact typed term".to_string())?;
    if object.len() == 3 && value == &serde_json::json!({"kind":"ctor","name":"None","args":[]}) {
        return Ok(None);
    }
    if object.len() != 3 || object.get("kind") != Some(&Json::String("const".into())) {
        return Err("literal default must be None or an exact typed constant".into());
    }
    let sort: Sort = serde_json::from_value(
        object
            .get("sort")
            .cloned()
            .ok_or_else(|| "literal default lacks sort testimony".to_string())?,
    )
    .map_err(|e| format!("literal default has malformed sort testimony: {e}"))?;
    let literal = object
        .get("value")
        .ok_or_else(|| "literal default lacks a value".to_string())?;
    let valid = match sort {
        Sort::Primitive { ref name } if name == "Bool" => literal.is_boolean(),
        Sort::Primitive { ref name } if name == "Int" => {
            literal.as_i64().is_some() || literal.as_u64().is_some()
        }
        Sort::Primitive { ref name } if name == "String" => literal.is_string(),
        _ => false,
    };
    if !valid {
        return Err("literal default sort/value mismatch".into());
    }
    Ok(Some(sort))
}

fn validate_import_signature(signature: &ImportSignatureV2) -> Result<(), String> {
    let mut names = std::collections::BTreeSet::new();
    let mut variadic_positional = false;
    let mut variadic_keyword = false;
    let mut rank = 0_u8;
    for parameter in &signature.parameters {
        if parameter.name.is_empty() || !names.insert(parameter.name.clone()) {
            return Err("ImportSignatureV2 parameter names must be nonempty and unique".into());
        }
        let next_rank = match parameter.passing {
            ParameterPassingV1::PositionalOnly => 0,
            ParameterPassingV1::PositionalOrKeyword => 1,
            ParameterPassingV1::VariadicPositional => {
                if std::mem::replace(&mut variadic_positional, true) {
                    return Err(
                        "ImportSignatureV2 permits at most one variadic positional parameter"
                            .into(),
                    );
                }
                2
            }
            ParameterPassingV1::KeywordOnly => 3,
            ParameterPassingV1::VariadicKeyword => {
                if std::mem::replace(&mut variadic_keyword, true) {
                    return Err(
                        "ImportSignatureV2 permits at most one variadic keyword parameter".into(),
                    );
                }
                4
            }
        };
        if next_rank < rank {
            return Err("ImportSignatureV2 parameters are not in Python passing order".into());
        }
        rank = next_rank;
        let is_variadic = matches!(
            parameter.passing,
            ParameterPassingV1::VariadicPositional | ParameterPassingV1::VariadicKeyword
        );
        if is_variadic
            && parameter.sort
                != (Sort::Primitive {
                    name: "Value".into(),
                })
        {
            return Err("variadic parameters require primitive Value sort".into());
        }
        if is_variadic && (parameter.required || parameter.default != ParameterDefaultV1::NoDefault)
        {
            return Err(
                "variadic parameters are optional operand packs with no scalar default".into(),
            );
        }
        match &parameter.default {
            value
                if !is_variadic
                    && parameter.required
                    && value != &ParameterDefaultV1::NoDefault =>
            {
                return Err("required parameters must have no-default testimony".into());
            }
            ParameterDefaultV1::NoDefault if !is_variadic && !parameter.required => {
                return Err(
                    "optional fixed parameters require authenticated default testimony".into(),
                )
            }
            ParameterDefaultV1::LiteralDefault { value } => {
                if let Some(literal_sort) = validate_literal_default(value)? {
                    if literal_sort != parameter.sort {
                        return Err("literal default sort must equal parameter sort".into());
                    }
                }
            }
            ParameterDefaultV1::ProviderValueRef {
                value_ref_cid,
                sort,
            } => {
                MementoCid::try_parse(value_ref_cid.clone())
                    .map_err(|_| "provider default valueRefCid must be a CID".to_string())?;
                if sort != &parameter.sort {
                    return Err("provider default sort must equal parameter sort".into());
                }
            }
            ParameterDefaultV1::NoDefault => {}
        }
    }
    Ok(())
}

/// Decode and validate the complete authenticated provider call signature.
/// Serde's closed enums and `deny_unknown_fields` make unknown variants/fields loud;
/// the second phase enforces Python parameter order and default testimony.
pub fn decode_import_signature_v2(value: &Json) -> Result<ImportSignatureV2, String> {
    let signature: ImportSignatureV2 = serde_json::from_value(value.clone())
        .map_err(|e| format!("malformed ImportSignatureV2: {e}"))?;
    validate_import_signature(&signature)?;
    Ok(signature)
}

pub fn decode_context_manager_semantics_v1(
    value: &Json,
    signature: &ImportSignatureV2,
) -> Result<ContextManagerSemanticsV1, String> {
    let root = value
        .as_object()
        .ok_or_else(|| "context-manager semantics must be an object".to_string())?;
    match root.get("kind").and_then(Json::as_str) {
        Some("protocol-resource") => {
            let root = exact_object(
                value,
                &["kind", "schemaVersion", "enter", "exit"],
                "protocol-resource semantics",
            )?;
            if root["schemaVersion"] != "1" {
                return Err("unknown protocol-resource schema".into());
            }
            let enter = exact_object(
                &root["enter"],
                &["completion", "result"],
                "protocol-resource enter",
            )?;
            closed_tag(&enter["completion"], &["total"], "enter completion")?;
            let result = exact_object(
                &enter["result"],
                &["kind", "projection", "sort"],
                "enter result",
            )?;
            if result["kind"] != "projection" || result["projection"] != "enter-result" {
                return Err("unknown enter projection".into());
            }
            let sort: Sort = serde_json::from_value(result["sort"].clone())
                .map_err(|e| format!("malformed enter sort: {e}"))?;
            let exit = exact_object(
                &root["exit"],
                &["completion", "disposition"],
                "protocol-resource exit",
            )?;
            closed_tag(&exit["completion"], &["total"], "exit completion")?;
            let disposition = match closed_tag(
                &exit["disposition"],
                &["never-suppresses", "return-truthiness"],
                "exit disposition",
            )?
            .as_str()
            {
                "never-suppresses" => ExitDispositionV1::NeverSuppresses,
                "return-truthiness" => ExitDispositionV1::ReturnTruthiness,
                unexpected => return Err(format!("unknown exit disposition: {unexpected}")),
            };
            Ok(ContextManagerSemanticsV1::ProtocolResource(
                ResourceSemanticsV1 {
                    enter: EnterResultContractV1 {
                        completion: TotalCompletionV1,
                        sort,
                    },
                    exit: ExitContractV1 {
                        completion: TotalCompletionV1,
                        disposition,
                    },
                },
            ))
        }
        Some("effect-boundary") => {
            let root = exact_object(
                value,
                &["kind", "schemaVersion", "mode", "matcher", "binding"],
                "effect-boundary semantics",
            )?;
            if root["schemaVersion"] != "1" {
                return Err("unknown effect-boundary schema".into());
            }
            let mode = match closed_tag(
                &root["mode"],
                &["expects", "suppresses"],
                "effect-boundary mode",
            )?
            .as_str()
            {
                "expects" => EffectBoundaryModeV1::Expects,
                "suppresses" => EffectBoundaryModeV1::Suppresses,
                other => return Err(format!("unknown effect-boundary mode: {other}")),
            };
            let binding = match closed_tag(
                &root["binding"],
                &["none", "exception-info", "warning-observation"],
                "effect-boundary binding",
            )?
            .as_str()
            {
                "none" => EffectBoundaryBindingV1::None,
                "exception-info" => EffectBoundaryBindingV1::ExceptionInfo,
                "warning-observation" => EffectBoundaryBindingV1::WarningObservation,
                other => return Err(format!("unknown effect-boundary binding: {other}")),
            };
            let matcher = exact_object(
                &root["matcher"],
                &["effectKind", "expectedTypeOperand", "messagePatternOperand"],
                "effect-boundary matcher",
            )?;
            let effect_kind =
                match closed_tag(&matcher["effectKind"], &["raise", "warning"], "effect kind")?
                    .as_str()
                {
                    "raise" => EffectKindV1::Raise,
                    "warning" => EffectKindV1::Warning,
                    other => return Err(format!("unknown effect kind: {other}")),
                };
            let expected_type_operand =
                decode_formal_selector(&matcher["expectedTypeOperand"], false)?;
            let expected_parameter = selector_parameter(&expected_type_operand, signature)?;
            if expected_parameter.sort
                != (Sort::Primitive {
                    name: "Value".into(),
                })
            {
                return Err("expected-type selector requires Value testimony".into());
            }
            let message = matcher["messagePatternOperand"]
                .as_object()
                .ok_or_else(|| "message pattern operand must be an object".to_string())?;
            let message_pattern_operand = match message.get("kind").and_then(Json::as_str) {
                Some("none") => {
                    exact_object(
                        &matcher["messagePatternOperand"],
                        &["kind"],
                        "message pattern operand",
                    )?;
                    MessagePatternProjectionV1::None
                }
                Some(
                    "optional-formal-argument"
                    | "variadic-positional-element"
                    | "variadic-keyword-entry",
                ) => {
                    let selector = decode_formal_selector(&matcher["messagePatternOperand"], true)?;
                    if selector.parameter_index() == expected_type_operand.parameter_index() {
                        return Err("effect-boundary selectors must be distinct".into());
                    }
                    let parameter = selector_parameter(&selector, signature)?;
                    match &selector {
                        FormalSelectorV1::OptionalFormalArgument { .. }
                            if parameter.required
                                || !matches!(
                                    parameter.passing,
                                    ParameterPassingV1::PositionalOrKeyword
                                        | ParameterPassingV1::KeywordOnly
                                )
                                || !matches!(&parameter.sort, Sort::Primitive { name } if name == "String" || name == "Value") =>
                        {
                            return Err("message selector requires an optional keyword-bindable String-or-Value formal".into());
                        }
                        FormalSelectorV1::VariadicPositionalElement { .. }
                        | FormalSelectorV1::VariadicKeywordEntry { .. }
                            if parameter.sort
                                != (Sort::Primitive {
                                    name: "Value".into(),
                                }) =>
                        {
                            return Err(
                                "variadic message selector requires a Value operand pack".into()
                            );
                        }
                        _ => {}
                    }
                    match selector {
                        FormalSelectorV1::OptionalFormalArgument { parameter_index } => {
                            MessagePatternProjectionV1::OptionalFormalArgument { parameter_index }
                        }
                        FormalSelectorV1::VariadicPositionalElement {
                            parameter_index,
                            element_index,
                        } => MessagePatternProjectionV1::VariadicPositionalElement {
                            parameter_index,
                            element_index,
                        },
                        FormalSelectorV1::VariadicKeywordEntry {
                            parameter_index,
                            keyword,
                        } => MessagePatternProjectionV1::VariadicKeywordEntry {
                            parameter_index,
                            keyword,
                        },
                        FormalSelectorV1::FormalArgument { .. } => {
                            return Err("message selector cannot be a required formal".into())
                        }
                    }
                }
                Some(other) => return Err(format!("unknown message pattern operand: {other}")),
                None => return Err("message pattern operand kind must be a string".into()),
            };
            Ok(ContextManagerSemanticsV1::EffectBoundary(
                EffectBoundarySemanticsV1 {
                    mode,
                    effect_kind,
                    expected_type_operand,
                    message_pattern_operand,
                    binding,
                },
            ))
        }
        Some(other) => Err(format!(
            "unknown context-manager semantics variant: {other}"
        )),
        None => Err("context-manager semantics kind must be a string".into()),
    }
}

impl ContextManagerContractMember {
    fn from_value(value: &Json) -> Result<Self, MemberError> {
        let root = value.as_object().ok_or_else(|| {
            MemberError::InvalidContextManagerContract("layered member must be an object".into())
        })?;
        if root.len() != 3
            || !root.contains_key("envelope")
            || !root.contains_key("header")
            || !root.contains_key("metadata")
            || !root.get("envelope").is_some_and(Json::is_object)
        {
            return Err(MemberError::InvalidContextManagerContract(
                "expected only envelope, header, and metadata layers".into(),
            ));
        }
        let _metadata = value
            .get("metadata")
            .and_then(Json::as_object)
            .ok_or_else(|| {
                MemberError::InvalidContextManagerContract("layered metadata is missing".into())
            })?;
        let raw_header = value.get("header").cloned().ok_or_else(|| {
            MemberError::InvalidContextManagerContract("layered header is missing".into())
        })?;
        let header: ContextManagerHeader =
            serde_json::from_value(raw_header.clone()).map_err(|e| {
                MemberError::InvalidContextManagerContract(format!("malformed header: {e}"))
            })?;
        if header.schema_version != "1.2" || header.kind != "context-manager-contract" {
            return Err(MemberError::InvalidContextManagerContract(
                "schemaVersion/kind mismatch".into(),
            ));
        }
        if header.bridge_source_symbol.is_empty() {
            return Err(MemberError::InvalidContextManagerContract(
                "bridgeSourceSymbol must be non-empty".into(),
            ));
        }
        let signature = ImportSignatureV2 {
            parameters: header.import_signature.parameters,
        };
        validate_import_signature(&signature)
            .map_err(MemberError::InvalidContextManagerContract)?;
        let semantics = decode_context_manager_semantics_v1(&header.payload, &signature)
            .map_err(|detail| MemberError::InvalidContextManagerContract(detail))?;
        let payload = header.payload.clone();
        let derived = blake3_512_of(
            encode_jcs(&crate::proof_graph::json_to_canonical_value(&payload)).as_bytes(),
        );
        if derived != header.cid || derived != header.payload_cid {
            return Err(MemberError::InvalidContextManagerContract(format!(
                "payload CID mismatch: cid={} payloadCid={} derived={derived}",
                header.cid, header.payload_cid
            )));
        }
        let payload_cid = MementoCid::try_parse(header.payload_cid.clone()).map_err(|raw| {
            MemberError::InvalidCidFormat {
                kind: "context-manager-contract".into(),
                field: "payloadCid".into(),
                raw,
            }
        })?;
        let mut sorted_warrants = header.source_warrants.clone();
        if sorted_warrants
            .iter()
            .any(|cid| AtomCid::try_parse(cid.clone()).is_err())
        {
            return Err(MemberError::InvalidContextManagerContract(
                "sourceWarrants contain a malformed CID".into(),
            ));
        }
        sorted_warrants.sort();
        if header.input_cids != sorted_warrants {
            return Err(MemberError::InvalidContextManagerContract(
                "inputCids do not equal sorted sourceWarrants".into(),
            ));
        }
        Ok(Self {
            payload_cid,
            bridge_source_symbol: header.bridge_source_symbol,
            import_signature: signature,
            semantics,
            source_warrants: header.source_warrants,
            input_cids: header.input_cids,
        })
    }
}

/// Decode a CM contract from a member already authenticated and normalized by
/// `MementoPool`. This is the compiler/linker catalog boundary: it retains the
/// typed fields needed for prebinding without reopening source or exposing a
/// raw envelope to tree construction.
pub fn context_manager_contract_from_stored(
    member: &crate::StoredMember,
) -> Result<ContextManagerContractMember, MemberError> {
    if member.kind() != MemberKind::ContextManagerContract {
        return Err(MemberError::InvalidContextManagerContract(
            "stored member has the wrong contract kind".into(),
        ));
    }
    let names = [
        "schemaVersion",
        "kind",
        "cid",
        "payloadCid",
        "bridgeSourceSymbol",
        "importSignature",
        "payload",
        "sourceWarrants",
        "inputCids",
    ];
    let mut header = serde_json::Map::new();
    for name in names {
        let value = member.field(name).ok_or_else(|| {
            MemberError::InvalidContextManagerContract(format!(
                "authenticated stored member is missing `{name}`"
            ))
        })?;
        header.insert(name.into(), value.clone());
    }
    ContextManagerContractMember::from_value(&serde_json::json!({
        "envelope": {},
        "header": header,
        "metadata": {},
    }))
}

/// Typed, parsed member. One variant per known kind.
#[derive(Debug, Clone)]
pub enum Member {
    Contract(ContractMember),
    ContextManagerContract(ContextManagerContractMember),
    Bridge(BridgeMember),
    Implication(ImplicationMember),
    Authority(AuthorityMember),
    /// Corresponds to wire kind `"witness"` (the claim witness, not the
    /// memento wrapper).
    WitnessClaim(WitnessClaimMember),
    WitnessMemento(WitnessMementoMember),
    SourceMemento(SourceMementoMember),
    PlanMemento(PlanMementoMember),
    FactoryWalkMemento(FactoryWalkMementoMember),
    AssertionSurfaceMemento(AssertionSurfaceMementoMember),
    LibrarySugarBindingEntry(LibrarySugarBindingEntryMember),
    EffectSiteAnnotation(EffectSiteAnnotationMember),
    ProofRun(ProofRunMember),
    StageReceipt(StageReceiptMember),
}

impl Member {
    /// Parse an already-deserialized member envelope `Value` into a typed `Member`.
    ///
    /// This is the core dispatch.  `parse` delegates here after deserializing
    /// raw bytes; callers that already hold a `serde_json::Value` (e.g. after
    /// reading a JSON array of members) can call this directly without
    /// re-serializing to bytes.
    ///
    /// Returns `Err` when:
    /// - No kind discriminator can be extracted.
    /// - The kind is known but a required field is missing or has the wrong type.
    /// - A CID-typed field does not carry the `blake3-512:` tag.
    ///
    /// Unknown kinds surface as `MemberError::UnknownKind` so callers can choose
    /// to skip or fail.
    pub fn from_value(value: &Json) -> Result<Self, MemberError> {
        let nb = normalize(value)?;
        match nb.kind {
            MemberKind::Contract => Ok(Member::Contract(ContractMember::from_normalized(&nb)?)),
            MemberKind::ContextManagerContract => Ok(Member::ContextManagerContract(
                ContextManagerContractMember::from_value(value)?,
            )),
            MemberKind::Bridge => Ok(Member::Bridge(BridgeMember::from_normalized(&nb)?)),
            MemberKind::Implication => Ok(Member::Implication(ImplicationMember::from_normalized(
                &nb,
            )?)),
            MemberKind::Authority => Ok(Member::Authority(AuthorityMember::from_normalized(&nb)?)),
            MemberKind::Witness => Ok(Member::WitnessClaim(WitnessClaimMember::from_normalized(
                &nb,
            )?)),
            MemberKind::WitnessMemento => Ok(Member::WitnessMemento(
                WitnessMementoMember::from_normalized(&nb)?,
            )),
            MemberKind::SourceMemento => Ok(Member::SourceMemento(
                SourceMementoMember::from_normalized(&nb)?,
            )),
            MemberKind::PlanMemento => Ok(Member::PlanMemento(PlanMementoMember::from_normalized(
                &nb,
            )?)),
            MemberKind::FactoryWalkMemento => Ok(Member::FactoryWalkMemento(
                FactoryWalkMementoMember::from_normalized(&nb)?,
            )),
            MemberKind::AssertionSurfaceMemento => Ok(Member::AssertionSurfaceMemento(
                AssertionSurfaceMementoMember::from_normalized(&nb)?,
            )),
            MemberKind::LibrarySugarBindingEntry => Ok(Member::LibrarySugarBindingEntry(
                LibrarySugarBindingEntryMember::from_normalized(&nb)?,
            )),
            MemberKind::EffectSiteAnnotation => Ok(Member::EffectSiteAnnotation(
                EffectSiteAnnotationMember::from_normalized(&nb)?,
            )),
            MemberKind::ProofRun => Ok(Member::ProofRun(ProofRunMember::from_normalized(&nb)?)),
            MemberKind::StageReceipt => Ok(Member::StageReceipt(
                StageReceiptMember::from_normalized(&nb)?,
            )),
            MemberKind::AliasingMemento
            | MemberKind::ClosureBinding
            | MemberKind::LoopInvariant
            | MemberKind::PinInvariant
            | MemberKind::TryBranch => Err(MemberError::UnsupportedTypedWrapper(nb.kind)),
        }
    }

    /// Parse raw member bytes (JCS-JSON) into a typed `Member`.
    ///
    /// Deserializes the bytes as JSON, then delegates to [`Member::from_value`].
    ///
    /// Returns `Err` when:
    /// - The bytes are not valid JSON.
    /// - No kind discriminator can be extracted.
    /// - The kind is known but a required field is missing or has the wrong type.
    /// - A CID-typed field does not carry the `blake3-512:` tag.
    ///
    /// Unknown kinds are surfaced as `MemberError::UnknownKind` so callers can
    /// choose to skip or fail.
    pub fn parse(bytes: &[u8]) -> Result<Self, MemberError> {
        let v: Json =
            serde_json::from_slice(bytes).map_err(|e| MemberError::JsonParse(e.to_string()))?;
        Self::from_value(&v)
    }

    /// The wire kind string for this member.
    pub fn kind(&self) -> MemberKind {
        match self {
            Member::Contract(_) => MemberKind::Contract,
            Member::ContextManagerContract(_) => MemberKind::ContextManagerContract,
            Member::Bridge(_) => MemberKind::Bridge,
            Member::Implication(_) => MemberKind::Implication,
            Member::Authority(_) => MemberKind::Authority,
            Member::WitnessClaim(_) => MemberKind::Witness,
            Member::WitnessMemento(_) => MemberKind::WitnessMemento,
            Member::SourceMemento(_) => MemberKind::SourceMemento,
            Member::PlanMemento(_) => MemberKind::PlanMemento,
            Member::FactoryWalkMemento(_) => MemberKind::FactoryWalkMemento,
            Member::AssertionSurfaceMemento(_) => MemberKind::AssertionSurfaceMemento,
            Member::LibrarySugarBindingEntry(_) => MemberKind::LibrarySugarBindingEntry,
            Member::EffectSiteAnnotation(_) => MemberKind::EffectSiteAnnotation,
            Member::ProofRun(_) => MemberKind::ProofRun,
            Member::StageReceipt(_) => MemberKind::StageReceipt,
        }
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;

    fn cid(fill: char) -> String {
        format!("blake3-512:{}", fill.to_string().repeat(128))
    }

    // Shared authority payload used for the 3-shape test.
    fn authority_fields() -> serde_json::Value {
        serde_json::json!({
            "kind": "authority",
            "cid": cid('a'),
            "principal": "test-principal",
            "key": "test-key",
            "scopeKind": "library",
            "scope": "my-lib",
            "verdict": "discharged",
            "inputCids": [cid('1'), cid('2')]
        })
    }

    fn assert_authority_fields(m: &AuthorityMember) {
        assert_eq!(m.cid.as_str(), cid('a'));
        assert_eq!(m.principal, "test-principal");
        assert_eq!(m.key, "test-key");
        assert_eq!(m.scope_kind, "library");
        assert_eq!(m.scope, "my-lib");
        assert_eq!(m.verdict.as_deref(), Some("discharged"));
        let cids = m
            .input_cids
            .as_ref()
            .expect("inputCids present in full wire");
        assert_eq!(cids.len(), 2);
        assert_eq!(cids[0].as_str(), cid('1'));
        assert_eq!(cids[1].as_str(), cid('2'));
        assert!(m.parent_authority_cid.is_none());
        assert!(m.authority_claim.is_none());
    }

    // ── (a) All 3 wire shapes parse to the same typed struct ─────────────────

    #[test]
    fn normalizer_v12_layered_shape() {
        let fields = authority_fields();
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:test",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": fields,
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let m = Member::parse(&bytes).expect("layered shape parses");
        match &m {
            Member::Authority(a) => assert_authority_fields(a),
            other => panic!("expected Authority, got {:?}", other.kind()),
        }
    }

    #[test]
    fn normalizer_lean_shape() {
        let fields = authority_fields();
        let wire = serde_json::json!({
            "header": fields,
            "schemaVersion": "1"
        });
        let bytes = wire.to_string().into_bytes();
        let m = Member::parse(&bytes).expect("lean shape parses");
        match &m {
            Member::Authority(a) => assert_authority_fields(a),
            other => panic!("expected Authority, got {:?}", other.kind()),
        }
    }

    #[test]
    fn normalizer_v11_flat_shape() {
        let fields = authority_fields();
        let wire = serde_json::json!({
            "evidence": {
                "kind": "authority",
                "body": {
                    "cid": cid('a'),
                    "principal": "test-principal",
                    "key": "test-key",
                    "scopeKind": "library",
                    "scope": "my-lib",
                    "verdict": "discharged",
                    "inputCids": [cid('1'), cid('2')]
                }
            },
            "signer": "ed25519:test",
            "producerSignature": "ed25519:sig"
        });
        let _ = fields; // used above for clarity
        let bytes = wire.to_string().into_bytes();
        let m = Member::parse(&bytes).expect("v1.1 flat shape parses");
        match &m {
            Member::Authority(a) => assert_authority_fields(a),
            other => panic!("expected Authority, got {:?}", other.kind()),
        }
    }

    // ── (b) Known kind, missing required field → Err ──────────────────────────

    #[test]
    fn fail_loud_on_missing_required_field() {
        // bridge missing targetContractCid (and several others)
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:s",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": {
                "kind": "bridge",
                "cid": cid('b'),
                "sourceSymbol": "my_fn",
                "sourceLayer": "rust"
                // targetContractCid and many others absent
            },
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let result = Member::parse(&bytes);
        assert!(
            result.is_err(),
            "bridge with missing required fields must return Err"
        );
        let err = result.unwrap_err();
        let msg = err.to_string();
        // Must name the kind and the field in the error.
        assert!(
            msg.contains("bridge"),
            "error message must name the kind: {msg}"
        );
    }

    #[test]
    fn fail_loud_on_missing_required_field_contract() {
        let wire = serde_json::json!({
            "header": {
                "kind": "contract",
                "cid": cid('c'),
                "name": "my::fn"
                // contractName and bodyCid are required structural minimum and are missing
            }
        });
        let bytes = wire.to_string().into_bytes();
        let result = Member::parse(&bytes);
        assert!(result.is_err());
    }

    #[test]
    fn fail_loud_on_missing_required_field_implication() {
        let wire = serde_json::json!({
            "header": {
                "kind": "implication",
                "cid": cid('c'),
                "verdict": "discharged"
                // missing many required fields
            }
        });
        let result = Member::parse(&wire.to_string().as_bytes());
        assert!(result.is_err());
    }

    #[test]
    fn fail_loud_on_invalid_cid_format() {
        // authority with a required MementoCid field carrying a non-blake3 value
        let wire = serde_json::json!({
            "header": {
                "kind": "authority",
                "cid": "NOT-A-BLAKE3-CID",
                "principal": "p",
                "key": "k",
                "scopeKind": "library",
                "scope": "s",
                "verdict": "discharged",
                "inputCids": [cid('0')]
            }
        });
        let result = Member::parse(&wire.to_string().into_bytes());
        assert!(result.is_err());
        let err = result.unwrap_err();
        let msg = err.to_string();
        assert!(
            msg.contains("blake3-512") || msg.contains("invalid CID"),
            "error must explain CID format requirement: {msg}"
        );
    }

    // ── (c) Typed CID-ref fields are newtypes, not String ───────────────────

    #[test]
    fn cid_ref_fields_are_typed_newtypes_not_strings() {
        // bridge: target_contract_cid must be MementoCid, not String
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:s",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": {
                "kind": "bridge",
                "cid": cid('b'),
                "sourceSymbol": "my_fn",
                "sourceLayer": "rust",
                "targetContractCid": cid('c'),
                "targetLayer": "rust",
                "irArgSorts": ["Int"],
                "irReturnSort": "Bool",
                "verdict": "discharged",
                "bindingHash": "bh",
                "propertyHash": "ph",
                "inputCids": [cid('1')]
            },
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let m = Member::parse(&bytes).expect("bridge parses");
        match &m {
            Member::Bridge(b) => {
                // Compile-time assertion: these are the newtype, not &str / String.
                let _: &MementoCid = &b.cid;
                let _: &MementoCid = &b.target_contract_cid;
                let _: &Option<Vec<MementoCid>> = &b.input_cids;
                assert_eq!(b.cid.as_str(), cid('b'));
                assert_eq!(b.target_contract_cid.as_str(), cid('c'));
                assert_eq!(b.input_cids.as_ref().unwrap()[0].as_str(), cid('1'));
            }
            other => panic!("expected Bridge, got {:?}", other.kind()),
        }
    }

    #[test]
    fn atom_cid_ref_fields_are_typed_newtypes() {
        // witness: claimBodyCid, verifierCid, policyCid, evidenceRootCid → AtomCid
        let wire = serde_json::json!({
            "header": {
                "kind": "witness",
                "cid": cid('d'),
                "claimKind": "assertion",
                "claimBodyCid": "atom:claim",
                "verdict": "discharged",
                "verifierCid": "atom:verifier",
                "policyCid": "atom:policy",
                "evidenceRootCid": "atom:evidence",
                "inputCids": [cid('1')]
            }
        });
        let bytes = wire.to_string().into_bytes();
        let m = Member::parse(&bytes).expect("witness parses");
        match &m {
            Member::WitnessClaim(wc) => {
                let _: &AtomCid = &wc.claim_body_cid;
                let _: &Option<AtomCid> = &wc.verifier_cid;
                let _: &Option<AtomCid> = &wc.policy_cid;
                let _: &Option<AtomCid> = &wc.evidence_root_cid;
                let _: &MementoCid = &wc.cid;
                assert_eq!(wc.claim_body_cid.as_str(), "atom:claim");
                assert_eq!(wc.verifier_cid.as_ref().unwrap().as_str(), "atom:verifier");
            }
            other => panic!("expected WitnessClaim, got {:?}", other.kind()),
        }
    }

    // ── Source-memento round-trip (lean shape, AtomCid required) ────────────

    #[test]
    fn source_memento_lean_shape_parses() {
        let wire = serde_json::json!({
            "header": {
                "kind": "source-memento",
                "sourceCid": "atom:sourcehash"
            },
            "schemaVersion": "1"
        });
        let bytes = wire.to_string().into_bytes();
        let m = Member::parse(&bytes).expect("source-memento parses");
        match &m {
            Member::SourceMemento(s) => {
                let _: &AtomCid = &s.source_cid;
                assert_eq!(s.source_cid.as_str(), "atom:sourcehash");
                assert!(s.contract_name.is_none());
            }
            other => panic!("expected SourceMemento, got {:?}", other.kind()),
        }
    }

    #[test]
    fn source_memento_missing_required_source_cid_is_err() {
        let wire = serde_json::json!({
            "header": {
                "kind": "source-memento",
                "contractName": "some::fn"
                // sourceCid missing
            }
        });
        let result = Member::parse(&wire.to_string().into_bytes());
        assert!(result.is_err());
        let msg = result.unwrap_err().to_string();
        assert!(
            msg.contains("source-memento") || msg.contains("sourceCid"),
            "{msg}"
        );
    }

    // ── factory-walk-memento and assertion-surface-memento (all-optional) ────

    #[test]
    fn factory_walk_memento_all_optional_parses_empty() {
        let wire = serde_json::json!({
            "header": { "kind": "factory-walk-memento" }
        });
        let m = Member::parse(&wire.to_string().into_bytes()).expect("all-optional parses");
        assert!(matches!(m, Member::FactoryWalkMemento(_)));
        match m {
            Member::FactoryWalkMemento(fw) => {
                assert!(fw.file.is_none());
                assert!(fw.verdict.is_none());
            }
            _ => unreachable!(),
        }
    }

    // ── Unknown kind → UnknownKind error ─────────────────────────────────────

    #[test]
    fn unknown_kind_returns_err() {
        let wire = serde_json::json!({
            "header": { "kind": "totally-unknown-kind-xyz" }
        });
        let result = Member::parse(&wire.to_string().into_bytes());
        assert!(matches!(result, Err(MemberError::UnknownKind { .. })));
    }

    #[test]
    fn unknown_kind_error_names_known_kinds() {
        let wire = serde_json::json!({
            "header": { "kind": "totally-unknown-kind-xyz" }
        });
        let result = Member::parse(&wire.to_string().into_bytes());
        let msg = result.unwrap_err().to_string();
        assert!(
            msg.contains("totally-unknown-kind-xyz"),
            "error must name the unknown kind: {msg}"
        );
        assert!(
            msg.contains("contract") && msg.contains("stage-receipt"),
            "error must list known member kinds: {msg}"
        );
    }

    #[test]
    fn known_member_kind_strings_round_trip_through_enum() {
        let cases = [
            ("aliasing-memento", MemberKind::AliasingMemento),
            (
                "assertion-surface-memento",
                MemberKind::AssertionSurfaceMemento,
            ),
            ("authority", MemberKind::Authority),
            ("bridge", MemberKind::Bridge),
            ("closure-binding", MemberKind::ClosureBinding),
            ("contract", MemberKind::Contract),
            (
                "context-manager-contract",
                MemberKind::ContextManagerContract,
            ),
            ("effect-site-annotation", MemberKind::EffectSiteAnnotation),
            ("factory-walk-memento", MemberKind::FactoryWalkMemento),
            ("implication", MemberKind::Implication),
            (
                "library-sugar-binding-entry",
                MemberKind::LibrarySugarBindingEntry,
            ),
            ("loop-invariant", MemberKind::LoopInvariant),
            ("pin-invariant", MemberKind::PinInvariant),
            ("plan-memento", MemberKind::PlanMemento),
            ("proof-run", MemberKind::ProofRun),
            ("source-memento", MemberKind::SourceMemento),
            ("stage-receipt", MemberKind::StageReceipt),
            ("try-branch", MemberKind::TryBranch),
            ("witness", MemberKind::Witness),
            ("witness-memento", MemberKind::WitnessMemento),
        ];

        for (raw, expected) in cases {
            let parsed: MemberKind = raw.parse().expect("known member kind parses");
            assert_eq!(parsed, expected);
            assert_eq!(parsed.to_string(), raw);
        }
    }

    // ── Invalid JSON → JsonParse error ────────────────────────────────────────

    #[test]
    fn invalid_json_returns_err() {
        let result = Member::parse(b"not json at all {{{");
        assert!(matches!(result, Err(MemberError::JsonParse(_))));
    }

    // ── ProofGraph typed_member: lazy + memoized ──────────────────────────────

    #[test]
    fn proof_graph_typed_member_is_lazy_and_memoized() {
        use sugar_canonicalizer::encode_jcs;

        use crate::proof_graph::{ProofGraph, SourceMemento};

        // Push a source-memento (requires only sourceCid) directly.
        let wire = serde_json::json!({
            "header": {
                "kind": "source-memento",
                "sourceCid": "atom:abc123"
            },
            "schemaVersion": "1"
        });
        let bytes: Vec<u8> = {
            // Use the same JCS encoding path the normalizer expects.
            let s = serde_json::to_string(&wire).unwrap();
            s.into_bytes()
        };
        let source = SourceMemento::new(bytes.clone());
        let source_cid = source.cid().clone();

        let mut graph = ProofGraph::new();
        graph.push_source(source);

        // typed_member returns Some(Ok(Arc<Member::SourceMemento>)).
        let result = graph
            .typed_member(&source_cid)
            .expect("source-memento exists in graph");
        let arc_member = result.expect("source-memento parses to typed Member");
        assert!(
            matches!(*arc_member, Member::SourceMemento(_)),
            "expected SourceMemento, got {:?}",
            arc_member.kind()
        );

        // Second call returns the same Arc (pointer equality proves memoization).
        let arc2 = graph.typed_member(&source_cid).unwrap().unwrap();
        assert!(
            Arc::ptr_eq(&arc_member, &arc2),
            "memoized: same Arc pointer"
        );

        // typed_members_iter covers the one member.
        let all: Vec<_> = graph.typed_members_iter().collect();
        assert_eq!(all.len(), 1);
        assert!(all[0].1.is_ok(), "member in iterator parses ok");

        let _ = encode_jcs; // suppress unused import warning
    }

    // ── typed_member returns None for unknown CID ─────────────────────────────

    #[test]
    fn typed_member_returns_none_for_unknown_cid() {
        use crate::proof_graph::ProofGraph;
        let graph = ProofGraph::new();
        let ghost = MementoCid::try_parse(cid('9')).expect("valid blake3-512 cid");
        assert!(graph.typed_member(&ghost).is_none());
    }

    // ── Rust-builder parse tests: every kind's builder → Member::parse → Ok ──
    //
    // These are the tests that would have caught the over-strict required-field
    // bug.  Each constructs a MINIMAL member via the builder in proof_graph.rs,
    // takes its bytes, and asserts Member::parse returns Ok with the correct
    // typed variant.  The model must be universal: no escape hatch.

    #[test]
    fn contract_memento_rust_builder_parses() {
        use crate::proof_graph::{AtomMemento, ContractBody, ContractMemento, FlatAtom};

        let atom = FlatAtom::result_eq_int(0);
        let post = AtomMemento::new(&atom);
        let body = ContractBody::new(&post);
        let contract = ContractMemento::new("my::func", &body, [0x01; 32]);

        let m = Member::parse(contract.bytes())
            .expect("Rust-built ContractMemento (no verdict/outBinding/inputCids) must parse");
        match &m {
            Member::Contract(c) => {
                assert_eq!(c.name, "my::func");
                assert_eq!(c.contract_name, "my::func");
                assert!(c.body_cid.as_str().starts_with("blake3-512:"));
                // kit-output fields are absent on the minimal builder → None
                assert!(c.verdict.is_none(), "verdict absent on Rust-built minimal");
                assert!(
                    c.out_binding.is_none(),
                    "outBinding absent on Rust-built minimal"
                );
                assert!(c.binding_hash.is_none());
                assert!(c.property_hash.is_none());
                assert!(c.input_cids.is_none());
            }
            other => panic!("expected Contract, got {:?}", other.kind()),
        }
    }

    #[test]
    fn bridge_memento_minimal_bytes_parse() {
        use crate::proof_graph::BridgeMemento;

        // Structural minimum: kind + cid + sourceSymbol + targetContractCid.
        // No sourceLayer, targetLayer, irArgSorts, verdict, bindingHash, inputCids.
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:s",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": {
                "kind": "bridge",
                "cid": cid('b'),
                "sourceSymbol": "my_fn",
                "targetContractCid": cid('c')
            },
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let memento = BridgeMemento::new(bytes);
        let m = Member::parse(memento.bytes())
            .expect("minimal BridgeMemento (no sourceLayer/verdict/inputCids) must parse");
        match &m {
            Member::Bridge(b) => {
                assert_eq!(b.source_symbol, "my_fn");
                assert_eq!(b.target_contract_cid.as_str(), cid('c'));
                assert!(
                    b.source_layer.is_none(),
                    "sourceLayer absent on minimal bridge"
                );
                assert!(b.verdict.is_none(), "verdict absent on minimal bridge");
                assert!(b.input_cids.is_none());
            }
            other => panic!("expected Bridge, got {:?}", other.kind()),
        }
    }

    #[test]
    fn implication_memento_minimal_bytes_parse() {
        use crate::proof_graph::ImplicationMemento;

        // Structural minimum: kind + cid + antecedentCid + consequentCid.
        // No antecedentHash, consequentSlot, verdict, prover, proverRunMs, inputCids.
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:s",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": {
                "kind": "implication",
                "cid": cid('e'),
                "antecedentCid": cid('a'),
                "consequentCid": cid('b')
            },
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let memento = ImplicationMemento::new(bytes);
        let m = Member::parse(memento.bytes())
            .expect("minimal ImplicationMemento (no verdict/prover/inputCids) must parse");
        match &m {
            Member::Implication(imp) => {
                assert_eq!(imp.antecedent_cid.as_str(), cid('a'));
                assert_eq!(imp.consequent_cid.as_str(), cid('b'));
                assert!(
                    imp.verdict.is_none(),
                    "verdict absent on minimal implication"
                );
                assert!(imp.prover.is_none(), "prover absent on minimal implication");
                assert!(imp.prover_run_ms.is_none());
                assert!(imp.input_cids.is_none());
            }
            other => panic!("expected Implication, got {:?}", other.kind()),
        }
    }

    #[test]
    fn authority_memento_minimal_bytes_parse() {
        use crate::proof_graph::AuthorityMemento;

        // Identity minimum: kind + cid + principal + key + scopeKind + scope.
        // No verdict, no inputCids.
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:s",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": {
                "kind": "authority",
                "cid": cid('f'),
                "principal": "my-principal",
                "key": "my-key",
                "scopeKind": "library",
                "scope": "my-lib"
            },
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let memento = AuthorityMemento::new(bytes);
        let m = Member::parse(memento.bytes())
            .expect("minimal AuthorityMemento (no verdict/inputCids) must parse");
        match &m {
            Member::Authority(a) => {
                assert_eq!(a.principal, "my-principal");
                assert_eq!(a.scope_kind, "library");
                assert!(a.verdict.is_none(), "verdict absent on minimal authority");
                assert!(
                    a.input_cids.is_none(),
                    "inputCids absent on minimal authority"
                );
            }
            other => panic!("expected Authority, got {:?}", other.kind()),
        }
    }

    #[test]
    fn witness_claim_memento_minimal_bytes_parse() {
        use crate::proof_graph::WitnessClaimMemento;

        // Identity minimum: kind + cid + claimKind + claimBodyCid.
        // No verdict, no verifierCid, no policyCid, no evidenceRootCid, no inputCids.
        let wire = serde_json::json!({
            "envelope": {
                "signer": "ed25519:s",
                "declaredAt": "2026-01-01T00:00:00Z",
                "signature": "ed25519:sig"
            },
            "header": {
                "kind": "witness",
                "cid": cid('d'),
                "claimKind": "assertion",
                "claimBodyCid": "atom:claim"
            },
            "metadata": {}
        });
        let bytes = wire.to_string().into_bytes();
        let memento = WitnessClaimMemento::new(bytes);
        let m = Member::parse(memento.bytes())
            .expect("minimal WitnessClaimMemento (no verdict/verifier/policy/evidence) must parse");
        match &m {
            Member::WitnessClaim(wc) => {
                assert_eq!(wc.claim_kind, "assertion");
                assert_eq!(wc.claim_body_cid.as_str(), "atom:claim");
                assert!(wc.verdict.is_none());
                assert!(wc.verifier_cid.is_none());
                assert!(wc.policy_cid.is_none());
                assert!(wc.evidence_root_cid.is_none());
                assert!(wc.input_cids.is_none());
            }
            other => panic!("expected WitnessClaim, got {:?}", other.kind()),
        }
    }

    #[test]
    fn witness_memento_minimal_bytes_parse() {
        use crate::proof_graph::WitnessMemento;

        let wire = serde_json::json!({
            "header": {
                "kind": "witness-memento",
                "witnessCid": "atom:wid",
                "signer": "ed25519:s",
                "witnessKind": "assertion"
            }
        });
        let bytes = wire.to_string().into_bytes();
        let memento = WitnessMemento::new(bytes);
        let m = Member::parse(memento.bytes()).expect("minimal WitnessMemento must parse");
        match &m {
            Member::WitnessMemento(wm) => {
                assert_eq!(wm.witness_cid.as_str(), "atom:wid");
                assert_eq!(wm.witness_kind, "assertion");
            }
            other => panic!("expected WitnessMemento, got {:?}", other.kind()),
        }
    }

    #[test]
    fn plan_memento_minimal_bytes_parse() {
        use crate::proof_graph::PlanMemento;

        // plan_cid is the identity; expected_output_cids is now optional.
        let wire = serde_json::json!({
            "header": {
                "kind": "plan-memento",
                "planCid": "atom:planid"
            }
        });
        let bytes = wire.to_string().into_bytes();
        let memento = PlanMemento::new(bytes);
        let m = Member::parse(memento.bytes())
            .expect("minimal PlanMemento (no expectedOutputCids) must parse");
        match &m {
            Member::PlanMemento(pm) => {
                assert_eq!(pm.plan_cid.as_str(), "atom:planid");
                assert!(pm.expected_output_cids.is_none());
            }
            other => panic!("expected PlanMemento, got {:?}", other.kind()),
        }
    }

    // ── from_value agrees with parse(bytes) ──────────────────────────────────

    /// `Member::from_value` and `Member::parse(bytes)` must produce identical
    /// results for the same envelope.  Both paths share `normalize()` and the
    /// per-kind dispatch; the only difference is that `parse` first deserialises
    /// raw bytes.  This test exercises a full authority envelope (lean shape) so
    /// that CID newtypes, required string fields, and optional arrays are all
    /// exercised.
    #[test]
    fn from_value_and_parse_bytes_agree() {
        let wire = serde_json::json!({
            "header": {
                "kind": "authority",
                "cid": cid('a'),
                "principal": "test-principal",
                "key": "test-key",
                "scopeKind": "library",
                "scope": "my-lib",
                "verdict": "discharged",
                "inputCids": [cid('1'), cid('2')]
            },
            "schemaVersion": "1"
        });

        // Path A: from already-parsed Value.
        let from_val =
            Member::from_value(&wire).expect("from_value: authority lean shape must parse");

        // Path B: serialize to bytes then parse.
        let bytes = wire.to_string().into_bytes();
        let from_bytes =
            Member::parse(&bytes).expect("parse(bytes): authority lean shape must parse");

        // Both must produce the same kind.
        assert_eq!(from_val.kind(), from_bytes.kind());

        // Both must carry identical field values — unpack both.
        let (a_val, a_bytes) = match (&from_val, &from_bytes) {
            (Member::Authority(a), Member::Authority(b)) => (a, b),
            _ => panic!("expected Authority from both paths"),
        };

        assert_eq!(a_val.cid.as_str(), a_bytes.cid.as_str());
        assert_eq!(a_val.principal, a_bytes.principal);
        assert_eq!(a_val.key, a_bytes.key);
        assert_eq!(a_val.scope_kind, a_bytes.scope_kind);
        assert_eq!(a_val.scope, a_bytes.scope);
        assert_eq!(a_val.verdict, a_bytes.verdict);
        let cids_val = a_val.input_cids.as_ref().expect("inputCids present");
        let cids_bytes = a_bytes.input_cids.as_ref().expect("inputCids present");
        assert_eq!(cids_val.len(), cids_bytes.len());
        for (cv, cb) in cids_val.iter().zip(cids_bytes.iter()) {
            assert_eq!(cv.as_str(), cb.as_str());
        }
    }
}
