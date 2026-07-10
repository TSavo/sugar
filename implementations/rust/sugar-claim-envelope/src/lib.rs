// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-claim-envelope
//
// `mint_contract` / `mint_bridge` / `mint_implication` build a signed
// memento in the v1.2 LAYERED shape introduced by
// `protocol/specs/2026-05-03-substrate-layers-envelope-header-body.md`:
//
//   { "envelope": {...}, "header": {...}, "metadata": {...} }
//
//   * envelope = { signer, declaredAt, signature }
//       The signature is computed over JCS({"header": header, "metadata": metadata}).
//       The envelope's CID (= attestation CID) is BLAKE3-512(JCS(envelope))
//       AFTER the signature has been embedded.
//
//   * header   = substrate-load-bearing data the verifier reads:
//                schemaVersion, kind, cid, plus kind-specific REQUIRED
//                fields (per the kind's normative spec) and the derived
//                hashes (bindingHash, propertyHash, verdict, inputCids)
//                used by the resolve/index pipeline.
//
//   * metadata = everything else (authoring attribution, lifecycle
//                strings like producedBy/producedAt, derived per-formula
//                hashes that are pure tooling convenience). Opaque to
//                the substrate verifier; signed transitively via the
//                envelope.
//
// Per spec §4: v1.1 flat-shape mementos remain valid as historical
// artifacts. New emissions adopt the layered shape and carry
// `schemaVersion: "2"` in the header. The verifier branches on
// `schemaVersion` at load time.

use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_sign_string, AuthorityMementoRef, ContractMementoRef,
    Ed25519Seed,
};

#[derive(Debug, thiserror::Error)]
pub enum ClaimEnvelopeError {
    #[error("mint_contract: at least one of pre/post/inv must be present")]
    EmptyContract,
    #[error("mint_contract: outBinding must not be empty")]
    EmptyOutBinding,
    #[error("claim-envelope: {0}")]
    Other(String),
}

#[derive(Debug, Clone)]
pub struct MintedEnvelope {
    /// JCS-canonical bytes of the full layered memento
    /// (`{envelope, header, metadata}`).
    pub canonical_bytes: Vec<u8>,
    /// The attestation CID: BLAKE3-512(JCS(envelope)) after the
    /// signature has been embedded. This identifies the SIGNED
    /// attestation and is what goes into the bundle members map.
    pub cid: String,
    /// The content CID: BLAKE3-512(JCS({name, outBinding, pre?, post?, inv?})).
    /// Signer-independent. Two distinct signers attesting to the same
    /// logical contract produce the same `contract_cid`. Only populated
    /// for contract mementos; empty string for bridges and implications.
    /// Per `protocol/specs/2026-05-03-contract-cid-vs-attestation-cid.md` §1.
    pub contract_cid: String,
}

/// The layered-shape schema version stamped into every memento header
/// emitted by this kit. Older flat mementos carry `"1"`; verifiers
/// branch on this string at load time.
pub const LAYERED_SCHEMA_VERSION: &str = "2";

/// JSON-RPC method used by kits to serve their substrate declaration.
///
/// The declaration is semantic content, not startup negotiation, so it is
/// fetched on demand instead of being embedded in `initialize.capabilities`.
pub const KIT_DECLARATION_RPC_METHOD: &str = "sugar.plugin.kit_declaration";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitDeclaration {
    pub kit: KitIdentity,
    pub rpc: KitDeclarationRpc,
    #[serde(rename = "proofResolution")]
    pub proof_resolution: KitProofResolution,
    #[serde(
        rename = "oracleHost",
        default,
        skip_serializing_if = "Option::is_none"
    )]
    pub oracle_host: Option<KitOracleHost>,
    #[serde(rename = "residueCategories")]
    pub residue_categories: Vec<KitResidueCategory>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitIdentity {
    pub id: String,
    pub language: String,
    pub version: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitDeclarationRpc {
    pub methods: Vec<KitDeclarationRpcMethod>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitDeclarationRpcMethod {
    pub name: String,
    #[serde(default)]
    pub required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitProofResolution {
    pub strategy: String,
    #[serde(rename = "rpcMethod", default, skip_serializing_if = "Option::is_none")]
    pub rpc_method: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitOracleHost {
    #[serde(rename = "hostKind")]
    pub host_kind: String,
    #[serde(default)]
    pub required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KitResidueCategory {
    pub name: String,
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum KitDeclarationError {
    #[error("kit declaration: {field} must not be empty")]
    EmptyField { field: &'static str },
    #[error(
        "kit declaration: {category} has conflicting mapping for surface={surface:?} local={local}: {first} vs {second}"
    )]
    ConflictingMapping {
        category: &'static str,
        surface: Option<String>,
        local: String,
        first: String,
        second: String,
    },
}

impl KitDeclaration {
    pub fn validate(&self) -> Result<(), KitDeclarationError> {
        require_nonempty("kit.id", &self.kit.id)?;
        require_nonempty("kit.language", &self.kit.language)?;
        require_nonempty("kit.version", &self.kit.version)?;
        if self.rpc.methods.is_empty() {
            return Err(KitDeclarationError::EmptyField {
                field: "rpc.methods",
            });
        }
        for method in &self.rpc.methods {
            require_nonempty("rpc.methods[].name", &method.name)?;
        }
        require_nonempty("proofResolution.strategy", &self.proof_resolution.strategy)?;
        if let Some(method) = &self.proof_resolution.rpc_method {
            require_nonempty("proofResolution.rpcMethod", method)?;
        }
        if let Some(oracle_host) = &self.oracle_host {
            require_nonempty("oracleHost.hostKind", &oracle_host.host_kind)?;
        }
        for category in &self.residue_categories {
            require_nonempty("residueCategories[].name", &category.name)?;
            require_nonempty("residueCategories[].status", &category.status)?;
        }
        Ok(())
    }
}

fn require_nonempty(field: &'static str, value: &str) -> Result<(), KitDeclarationError> {
    if value.trim().is_empty() {
        Err(KitDeclarationError::EmptyField { field })
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod kit_declaration_schema_tests {
    use super::{
        KitDeclaration, KitDeclarationRpc, KitDeclarationRpcMethod, KitIdentity, KitProofResolution,
    };

    fn valid_declaration() -> KitDeclaration {
        KitDeclaration {
            kit: KitIdentity {
                id: "sugar-walk-rpc".to_string(),
                language: "rust".to_string(),
                version: "0.1.0".to_string(),
            },
            rpc: KitDeclarationRpc {
                methods: vec![KitDeclarationRpcMethod {
                    name: "sugar.plugin.kit_declaration".to_string(),
                    required: true,
                }],
            },
            proof_resolution: KitProofResolution {
                strategy: "rpc-proof-bytes".to_string(),
                rpc_method: Some("sugar.plugin.resolve_dependency_proofs".to_string()),
            },
            oracle_host: None,
            residue_categories: vec![],
        }
    }

    #[test]
    fn kit_declaration_roundtrips_with_optional_defaults() {
        let declaration = valid_declaration();

        declaration.validate().expect("valid declaration");
        let encoded = serde_json::to_string(&declaration).expect("encode declaration");
        let decoded: KitDeclaration = serde_json::from_str(&encoded).expect("decode declaration");

        assert_eq!(decoded, declaration);
        assert!(decoded.oracle_host.is_none());
    }

    #[test]
    fn kit_declaration_rejects_missing_required_fields() {
        let missing_rpc = serde_json::json!({
            "kit": {"id": "sugar-walk-rpc", "language": "rust", "version": "0.1.0"},
            "proofResolution": {"strategy": "rpc-proof-bytes"},
            "residueCategories": []
        });

        let err =
            serde_json::from_value::<KitDeclaration>(missing_rpc).expect_err("rpc is required");

        assert!(
            err.to_string().contains("rpc"),
            "error should name missing field: {err}"
        );
    }
}

// ---------- DERIVED hash helpers --------------------------------------------

fn hash_value(v: &Arc<Value>) -> String {
    let bytes = encode_jcs(v);
    blake3_512_of(bytes.as_bytes())
}

fn hash_string(s: &str) -> String {
    blake3_512_of(s.as_bytes())
}

// ---------- Envelope assembly -----------------------------------------------

/// Build the JCS-canonical bytes of `{"header": header, "metadata": metadata}`.
/// This is the message the envelope's Ed25519 signature covers (spec §2 R2).
fn signing_bytes(header: &Arc<Value>, metadata: &Arc<Value>) -> Vec<u8> {
    let msg = Value::object([("header", header.clone()), ("metadata", metadata.clone())]);
    encode_jcs(&msg).into_bytes()
}

/// Assemble a layered memento, sign it, and compute the attestation CID
/// (= BLAKE3-512(JCS(envelope-with-signature))). Returns the JCS-canonical
/// bytes of the full `{envelope, header, metadata}` object alongside the CID.
/// `content_cid` is the signer-independent contract CID (empty for bridges/implications).
fn assemble_layered(
    header: Arc<Value>,
    metadata: Arc<Value>,
    declared_at: &str,
    signer_seed: &Ed25519Seed,
    content_cid: String,
) -> MintedEnvelope {
    let signer = ed25519_pubkey_string(signer_seed);
    let signing_msg = signing_bytes(&header, &metadata);
    let signature = ed25519_sign_string(signer_seed, &signing_msg);

    // Build the envelope object with the embedded signature; its JCS
    // hash is the attestation CID.
    let envelope = Value::object([
        ("signer", Value::string(signer.clone())),
        ("declaredAt", Value::string(declared_at.to_string())),
        ("signature", Value::string(signature.clone())),
    ]);
    let envelope_jcs = encode_jcs(&envelope);
    let attestation_cid = blake3_512_of(envelope_jcs.as_bytes());

    let memento = Value::object([
        ("envelope", envelope),
        ("header", header),
        ("metadata", metadata),
    ]);
    let memento_jcs = encode_jcs(&memento);

    MintedEnvelope {
        canonical_bytes: memento_jcs.into_bytes(),
        cid: attestation_cid,
        contract_cid: content_cid,
    }
}

/// Helper: build a header object from a vector of (key, value) pairs.
/// Always prepends `schemaVersion`, `kind`, `cid` in that order; the
/// kind-specific REQUIRED header fields follow.
fn build_header(
    kind: &str,
    header_cid: &str,
    kind_specific: Vec<(String, Arc<Value>)>,
) -> Arc<Value> {
    let mut entries: Vec<(String, Arc<Value>)> = Vec::with_capacity(3 + kind_specific.len());
    entries.push((
        "schemaVersion".into(),
        Value::string(LAYERED_SCHEMA_VERSION),
    ));
    entries.push(("kind".into(), Value::string(kind.to_string())));
    entries.push(("cid".into(), Value::string(header_cid.to_string())));
    entries.extend(kind_specific);
    Arc::new(Value::Object(entries))
}

// =============================================================================
// Authoring (typed union mirrored from the C++ kit)
// =============================================================================

#[derive(Debug, Clone)]
pub enum Authoring {
    KitAuthor {
        author: String,
        note: Option<String>,
    },
    Lift {
        lifter: String,
        evidence: String,
        source_cid: Option<String>,
    },
    Llm {
        llm: String,
        llm_version: String,
        prompt_cid: String,
        confidence: f64,
        rationale: Option<String>,
    },
}

fn authoring_to_value(a: &Authoring) -> Arc<Value> {
    match a {
        Authoring::KitAuthor { author, note } => {
            let mut entries: Vec<(String, Arc<Value>)> = vec![
                ("producerKind".into(), Value::string("kit-author")),
                ("author".into(), Value::string(author.clone())),
            ];
            if let Some(n) = note {
                if !n.is_empty() {
                    entries.push(("note".into(), Value::string(n.clone())));
                }
            }
            Arc::new(Value::Object(entries))
        }
        Authoring::Lift {
            lifter,
            evidence,
            source_cid,
        } => {
            let mut entries: Vec<(String, Arc<Value>)> = vec![
                ("producerKind".into(), Value::string("lift")),
                ("lifter".into(), Value::string(lifter.clone())),
                ("evidence".into(), Value::string(evidence.clone())),
            ];
            if let Some(c) = source_cid {
                if !c.is_empty() {
                    entries.push(("sourceCid".into(), Value::string(c.clone())));
                }
            }
            Arc::new(Value::Object(entries))
        }
        Authoring::Llm {
            llm,
            llm_version,
            prompt_cid,
            confidence,
            rationale,
        } => {
            let mut entries: Vec<(String, Arc<Value>)> = vec![
                ("producerKind".into(), Value::string("llm")),
                ("llm".into(), Value::string(llm.clone())),
                ("llmVersion".into(), Value::string(llm_version.clone())),
                ("promptCid".into(), Value::string(prompt_cid.clone())),
                (
                    "confidence".into(),
                    Value::integer((confidence * 1000.0) as i128),
                ),
            ];
            if let Some(r) = rationale {
                if !r.is_empty() {
                    entries.push(("rationale".into(), Value::string(r.clone())));
                }
            }
            Arc::new(Value::Object(entries))
        }
    }
}

// =============================================================================
// mint_contract
// =============================================================================

pub struct MintContractArgs {
    pub contract_name: String,
    pub pre: Option<Arc<Value>>,
    pub post: Option<Arc<Value>>,
    pub inv: Option<Arc<Value>>,
    /// Execution-witness EvidenceTerm (the `custom` discharge slot). PROVENANCE,
    /// not contract identity: carried in the header body so the verifier's
    /// witness-discharge arm can read it, but OMITTED WHEN `None` so existing
    /// contracts keep byte-identical headers/CIDs. Does not contribute to the
    /// contract CID (what is proven) -- only HOW it is discharged.
    pub evidence_term: Option<Arc<Value>>,
    pub out_binding: String,
    pub produced_by: String,
    pub produced_at: String,
    pub input_cids: Vec<String>,
    pub authoring: Authoring,
    pub signer_seed: Ed25519Seed,
    /// Formal parameter names of the function this contract describes, in
    /// declaration order. Body-derived op-contracts (the verification-spine
    /// target the `body_discharge::CatalogResolver` consumes, #1440/#1436)
    /// REQUIRE this: the resolver substitutes a harvested call's argument
    /// into the matching formal of the body-derived `post`, so without
    /// `formals` it returns `None` and the callee stays uninterpreted
    /// (Undecidable). Empty for non-function contracts (LIA tautologies,
    /// cross-language refinement targets); the field is then omitted from
    /// the header so those mementos keep their current bytes/CIDs.
    pub formals: Vec<String>,
    /// Emit `formals: []` (and `formalSorts: []`) when the vector is
    /// empty. Presence is load-bearing for zero-arg body-derived
    /// op-contracts: absent `formals` means "not body-derived", while
    /// present empty `formals` means "body-bearing function with no
    /// parameters".
    pub emit_empty_formals: bool,
    /// Sorts of the formals, parallel to `formals`. Carried alongside
    /// `formals` so the resolver can name the value slots; omitted from the
    /// header when empty.
    pub formal_sorts: Vec<Arc<Value>>,
    /// The crate / library this contract belongs to (the project's
    /// `platform_profile.library`). Carried as a metadata axis so a consumer
    /// that vendors this proof can tell THIS crate's `foo` from a same-named
    /// `foo` in another crate (the Tier-1 cross-crate disambiguation). A
    /// metadata field, not part of the contract CID: it does not change what
    /// is proven, only how a call site resolves to it. `None` omits the key.
    pub library: Option<String>,
    /// Public call spelling this contract discharges when it is consumed from
    /// another proof bundle (for example, a vendor-internal
    /// `lib._npyio_impl.load` contract reached as `numpy.load`). Metadata, not
    /// contract content: it does not contribute to `contract_cid`; it only lets
    /// an imported proof resolve the same bridge target spelling the producer
    /// used before sealing the proof.
    pub bridge_source_symbol: Option<String>,
    /// Contract-directive metadata, not contract content: this does NOT
    /// contribute to `contract_cid`. Whether this contract may be discharged
    /// by reducing against a function body. Totality axioms such as
    /// `is_ok(result)` are intentionally ineligible: they are trusted kit
    /// facts, not body-derived equations. Kits are responsible for setting
    /// this honestly; the verifier preserves and trusts the directive after a
    /// packaged proof is reloaded. Omitted when `true` to preserve legacy
    /// bytes and legacy reload behavior.
    pub body_discharge_eligible: bool,
    /// Loud reason paired with `body_discharge_eligible = false`, stored as
    /// metadata so dependency-proof consumers can preserve the same honesty
    /// boundary after reloading a packaged proof.
    pub body_discharge_refusal_reason: Option<String>,
    /// PANIC-LOCUS PRESERVATION (#1745): per-occurrence source loci for the
    /// panic-leaf calls in this function's body, each `{argTerm, file, line,
    /// col, callee}`. A panic-leaf call (`x.unwrap()`) lifts to the abstract
    /// ctor `method:unwrap` with no source span, so two functions both calling
    /// `.unwrap()` produce indistinguishable `method:unwrap` obligations whose
    /// distinct lines the verifier's per-symbol bridge index would otherwise
    /// collapse. Carried in the contract HEADER but OUTSIDE the contract content
    /// CID (emitted after `contract_cid` is computed, exactly like `inputCids`/
    /// `verdict`): the locus is developer-facing provenance, not part of what is
    /// proven, so it must not move the contract identity. Empty omits the key.
    pub panic_loci: Vec<Arc<Value>>,
    /// Python source-unit class shape catalog. This is signed, load-bearing
    /// evidence for the verifier's attribute-safety discharge arm. Empty omits
    /// the key so class-free units keep their existing bytes.
    pub class_shapes: Vec<Arc<Value>>,
    /// Source-oracle warrants for universe/generalized claims. These are lean
    /// SourceMementos: file + span + source/template CIDs, never source text.
    /// They are signed provenance carried in the contract header after the
    /// logical content CID is computed, so they do not change `contract_cid`.
    pub source_warrants: Vec<Arc<Value>>,
    /// ProofIR vocabulary provenance for typed construction sites. Like
    /// source warrants, this is signed provenance carried after the logical
    /// content CID is computed; it tells consumers whether a fact is Stated or
    /// Derived without changing what formula is proven.
    pub proofir_provenance: Option<Arc<Value>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BodyDischargePolicy {
    pub body_discharge_eligible: bool,
    pub body_discharge_refusal_reason: Option<String>,
    pub warnings: Vec<BodyDischargePolicyWarning>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BodyDischargePolicyWarning {
    Disagreement {
        legacy_eligible: bool,
        legacy_reason: Option<String>,
        policy_eligible: bool,
        policy_reason: Option<String>,
    },
    Malformed {
        reason: String,
    },
}

pub fn body_discharge_policy_from_object(entry: &JsonValue) -> BodyDischargePolicy {
    body_discharge_policy_from_object_with_default(entry, true)
}

pub fn body_discharge_policy_from_object_with_default(
    entry: &JsonValue,
    default_eligible: bool,
) -> BodyDischargePolicy {
    body_discharge_policy_from_fields_with_default(
        entry
            .get("bodyDischargeEligible")
            .or_else(|| entry.get("body_discharge_eligible")),
        entry
            .get("bodyDischargeRefusalReason")
            .or_else(|| entry.get("body_discharge_refusal_reason")),
        entry.get("dischargePolicy"),
        default_eligible,
    )
}

pub fn body_discharge_policy_from_fields(
    legacy_eligible: Option<&JsonValue>,
    legacy_reason: Option<&JsonValue>,
    discharge_policy: Option<&JsonValue>,
) -> BodyDischargePolicy {
    body_discharge_policy_from_fields_with_default(
        legacy_eligible,
        legacy_reason,
        discharge_policy,
        true,
    )
}

pub fn body_discharge_policy_from_fields_with_default(
    legacy_eligible: Option<&JsonValue>,
    legacy_reason: Option<&JsonValue>,
    discharge_policy: Option<&JsonValue>,
    default_eligible: bool,
) -> BodyDischargePolicy {
    let legacy_eligible = legacy_eligible.and_then(JsonValue::as_bool);
    let legacy_reason = legacy_reason
        .and_then(JsonValue::as_str)
        .map(str::to_string);
    let legacy_present = legacy_eligible.is_some() || legacy_reason.is_some();
    let legacy_policy = (
        legacy_eligible.unwrap_or(default_eligible),
        legacy_reason.clone(),
    );

    let (policy, mut warnings) = parse_body_reduction(discharge_policy);
    match policy {
        Some((policy_eligible, policy_reason)) if legacy_present => {
            if legacy_policy != (policy_eligible, policy_reason.clone()) {
                warnings.push(BodyDischargePolicyWarning::Disagreement {
                    legacy_eligible: legacy_policy.0,
                    legacy_reason: legacy_policy.1.clone(),
                    policy_eligible,
                    policy_reason,
                });
            }
            BodyDischargePolicy {
                body_discharge_eligible: legacy_policy.0,
                body_discharge_refusal_reason: legacy_policy.1,
                warnings,
            }
        }
        Some((policy_eligible, policy_reason)) => BodyDischargePolicy {
            body_discharge_eligible: policy_eligible,
            body_discharge_refusal_reason: policy_reason,
            warnings,
        },
        None => BodyDischargePolicy {
            body_discharge_eligible: legacy_policy.0,
            body_discharge_refusal_reason: legacy_policy.1,
            warnings,
        },
    }
}

fn parse_body_reduction(
    discharge_policy: Option<&JsonValue>,
) -> (
    Option<(bool, Option<String>)>,
    Vec<BodyDischargePolicyWarning>,
) {
    let Some(discharge_policy) = discharge_policy else {
        return (None, Vec::new());
    };
    let Some(policy_object) = discharge_policy.as_object() else {
        return (
            None,
            vec![BodyDischargePolicyWarning::Malformed {
                reason: "dischargePolicy must be an object".to_string(),
            }],
        );
    };
    let Some(body_reduction) = policy_object.get("bodyReduction") else {
        return (None, Vec::new());
    };
    let Some(body_reduction_object) = body_reduction.as_object() else {
        return (
            None,
            vec![BodyDischargePolicyWarning::Malformed {
                reason: "dischargePolicy.bodyReduction must be an object".to_string(),
            }],
        );
    };
    let Some(status) = body_reduction_object
        .get("status")
        .and_then(JsonValue::as_str)
    else {
        return (
            None,
            vec![BodyDischargePolicyWarning::Malformed {
                reason: "dischargePolicy.bodyReduction.status must be a string".to_string(),
            }],
        );
    };

    match status {
        "allowed" => (Some((true, None)), Vec::new()),
        "refused" => {
            let reason = match body_reduction_object.get("reason") {
                Some(reason) => match reason.as_str() {
                    Some(reason) => Some(reason.to_string()),
                    None => {
                        return (
                            None,
                            vec![BodyDischargePolicyWarning::Malformed {
                                reason: "dischargePolicy.bodyReduction.reason must be a string"
                                    .to_string(),
                            }],
                        )
                    }
                },
                None => None,
            };
            (Some((false, reason)), Vec::new())
        }
        other => (
            None,
            vec![BodyDischargePolicyWarning::Malformed {
                reason: format!(
                    "dischargePolicy.bodyReduction.status must be allowed or refused, got {other}"
                ),
            }],
        ),
    }
}

// =============================================================================
// mint_authority
// =============================================================================

pub struct MintAuthorityArgs {
    pub principal: String,
    pub key: String,
    pub scope_kind: String,
    pub scope: String,
    pub parent_authority: Option<AuthorityMementoRef>,
    pub produced_by: String,
    pub produced_at: String,
    pub signer_seed: Ed25519Seed,
}

fn authority_content_cid(args: &MintAuthorityArgs) -> String {
    let mut kvs: Vec<(String, Arc<Value>)> = vec![
        ("principal".into(), Value::string(args.principal.clone())),
        ("key".into(), Value::string(args.key.clone())),
        ("scopeKind".into(), Value::string(args.scope_kind.clone())),
        ("scope".into(), Value::string(args.scope.clone())),
    ];
    if let Some(parent) = &args.parent_authority {
        kvs.push(("parentAuthorityCid".into(), Value::string(parent.as_str())));
    }
    hash_value(&Arc::new(Value::Object(kvs)))
}

pub fn mint_authority(args: &MintAuthorityArgs) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    if args.principal.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_authority: principal must not be empty".into(),
        ));
    }
    if !args.key.starts_with("ed25519:") {
        return Err(ClaimEnvelopeError::Other(
            "mint_authority: key must be an inline ed25519 public key".into(),
        ));
    }
    if args.scope_kind.is_empty() || args.scope.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_authority: scopeKind and scope must not be empty".into(),
        ));
    }

    let header_cid = authority_content_cid(args);
    let mut input_cids = Vec::new();
    if let Some(parent) = &args.parent_authority {
        input_cids.push(parent.as_str().to_string());
    }
    input_cids.sort();
    let input_arr: Vec<Arc<Value>> = input_cids.into_iter().map(Value::string).collect();
    let mut kind_specific: Vec<(String, Arc<Value>)> = vec![
        ("principal".into(), Value::string(args.principal.clone())),
        ("key".into(), Value::string(args.key.clone())),
        ("scopeKind".into(), Value::string(args.scope_kind.clone())),
        ("scope".into(), Value::string(args.scope.clone())),
    ];
    if let Some(parent) = &args.parent_authority {
        kind_specific.push(("parentAuthorityCid".into(), Value::string(parent.as_str())));
    }
    kind_specific.push(("verdict".into(), Value::string("holds")));
    kind_specific.push(("inputCids".into(), Value::array(input_arr)));

    let header = build_header("authority", &header_cid, kind_specific);
    let metadata = Arc::new(Value::Object(vec![
        ("producedBy".into(), Value::string(args.produced_by.clone())),
        ("producedAt".into(), Value::string(args.produced_at.clone())),
        (
            "authorityClaim".into(),
            Value::string(format!(
                "{} controls {} for {}:{}",
                args.principal, args.key, args.scope_kind, args.scope
            )),
        ),
    ]));

    Ok(assemble_layered(
        header,
        metadata,
        &args.produced_at,
        &args.signer_seed,
        String::new(),
    ))
}

/// Compute the **content** CID of a contract (signer-independent).
///
/// Per `protocol/specs/2026-05-03-contract-cid-vs-attestation-cid.md` §1,
/// this is the BLAKE3-512 of the JCS encoding of the contract's
/// substrate-load-bearing fields: `name`, `outBinding`, and any of
/// `pre`/`post`/`inv` that are present. Two distinct signers attesting
/// to the same logical contract produce the same `contractCid`.
///
/// This value goes in `header.cid` of the minted layered memento and is
/// also available directly without minting via this public function.
///
/// Per spec naming convention (`contract_cid(decl)` for Rust).
/// JSON -> canonical `Value` (mirror of the verifier's `serde_to_canonical`).
fn json_to_cvalue(v: &JsonValue) -> Arc<Value> {
    match v {
        JsonValue::Null => Value::null(),
        JsonValue::Bool(b) => Value::boolean(*b),
        JsonValue::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                Value::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                if f == (f as i64 as f64) {
                    Value::integer(i128::from(f as i64))
                } else {
                    Value::string(f.to_string())
                }
            } else {
                Value::null()
            }
        }
        JsonValue::String(s) => Value::string(s.clone()),
        JsonValue::Array(arr) => Value::array(arr.iter().map(json_to_cvalue).collect()),
        JsonValue::Object(map) => Value::object(
            map.iter()
                .map(|(k, val)| (k.as_str(), json_to_cvalue(val)))
                .collect::<Vec<_>>(),
        ),
    }
}

/// Canonicalize a contract formula slot (pre/post/inv) to the alpha + pure-let
/// normal form BEFORE it enters a content hash. The kits emit ProofIR; the
/// substrate computes over it, so two surface formulations of the same behavior
/// (a leaked `let` binding, a renamed bound variable) must hash to the same
/// contract identity. If the value is not a parseable `IrFormula`, it is hashed
/// unchanged.
///
/// BLAST-RADIUS BOUND: when canonicalization is a no-op (the formula has no
/// `let` and no binder to normalize), the ORIGINAL `Arc<Value>` is returned
/// byte-for-byte. Only formulas the canonicalizer actually rewrites get the
/// re-serialized value. So introducing this step cannot move the content
/// address of any contract that does not contain a `let`/binder -- the regime
/// change is confined to exactly the contracts whose identity it must fix, and
/// no CID drifts on a serde round-trip artifact.
fn canon_formula_value(v: &Arc<Value>) -> Arc<Value> {
    let json: JsonValue = match serde_json::from_str(&encode_jcs(v)) {
        Ok(j) => j,
        Err(_) => return v.clone(),
    };
    let formula: sugar_ir_types::IrFormula = match serde_json::from_value(json) {
        Ok(f) => f,
        Err(_) => return v.clone(),
    };
    let canon = sugar_ir_types::canonicalize_formula(&formula);
    // No-op canonicalization -> preserve the original bytes exactly.
    if canon == formula {
        return v.clone();
    }
    match serde_json::to_value(&canon) {
        Ok(j) => json_to_cvalue(&j),
        Err(_) => v.clone(),
    }
}

/// Compute the canonical contract content CID from its identity-bearing parts.
/// This is the ONE hash that defines contract identity; both [`contract_cid`]
/// (from full mint args) and [`contract_cid_of_ir_decl`] (from a lifted IR
/// decl) funnel through it, so anything that recomputes a contract's identity
/// gets exactly the CID `mint` assigns — never a parallel identity scheme.
fn contract_cid_from_parts(
    contract_name: &str,
    out_binding: &str,
    pre: Option<&Arc<Value>>,
    post: Option<&Arc<Value>>,
    inv: Option<&Arc<Value>>,
    formals: &[String],
    formal_sorts: &[Arc<Value>],
    emit_empty_formals: bool,
) -> String {
    let mut kvs: Vec<(String, Arc<Value>)> = vec![
        ("name".into(), Value::string(contract_name.to_string())),
        ("outBinding".into(), Value::string(out_binding.to_string())),
    ];
    if let Some(pre) = pre {
        kvs.push(("pre".into(), canon_formula_value(pre)));
    }
    if let Some(post) = post {
        kvs.push(("post".into(), canon_formula_value(post)));
    }
    if let Some(inv) = inv {
        kvs.push(("inv".into(), canon_formula_value(inv)));
    }
    // Body-derived op-contracts carry their formals as part of contract
    // identity: two functions with the same `post` but different formal
    // names are different contracts (the resolver substitutes by formal
    // name). Omitted when empty unless `emit_empty_formals` marks the
    // zero-arg body-derived case, so non-function contracts keep their
    // existing content CIDs unchanged.
    if !formals.is_empty() || emit_empty_formals {
        let formals_arr: Vec<Arc<Value>> =
            formals.iter().map(|f| Value::string(f.clone())).collect();
        kvs.push(("formals".into(), Value::array(formals_arr)));
    }
    if !formal_sorts.is_empty() || emit_empty_formals {
        kvs.push(("formalSorts".into(), Value::array(formal_sorts.to_vec())));
    }
    let v = Arc::new(Value::Object(kvs));
    blake3_512_of(encode_jcs(&v).as_bytes())
}

pub fn contract_cid(args: &MintContractArgs) -> String {
    contract_cid_from_parts(
        &args.contract_name,
        &args.out_binding,
        args.pre.as_ref(),
        args.post.as_ref(),
        args.inv.as_ref(),
        &args.formals,
        &args.formal_sorts,
        args.emit_empty_formals,
    )
}

/// Recompute the canonical content CID of a lifted IR contract decl exactly as
/// `mint` would — extracting the same identity-bearing fields from the decl and
/// funneling them through [`contract_cid_from_parts`]. Consumers (e.g. the lift
/// `--report` superposition view) use this to group lifted assertions into
/// universes BY THEIR IDENTITY (the CID), so per-callsite duplicates of one
/// universe collapse while genuinely distinct universes that merely render
/// alike (the same claim at different integer widths, whose sort the FOL
/// renderer elides) stay separate. This is recompute-over-held-bytes: we hold
/// the decl, so the CID we compute is authoritative — there is no transported
/// CID to "trust but hash". Returns `None` for a decl `mint` would skip — a
/// non-contract `kind`, or one bearing no `pre`/`post`/`inv`.
pub fn contract_cid_of_ir_decl(decl: &JsonValue) -> Option<String> {
    let kind = decl.get("kind").and_then(JsonValue::as_str).unwrap_or("");
    if kind != "contract" && kind != "function-contract" {
        return None;
    }
    let contract_name = decl
        .get("name")
        .or_else(|| decl.get("symbol"))
        .or_else(|| decl.get("fn_name"))
        .or_else(|| decl.get("fnName"))
        .and_then(JsonValue::as_str)
        .unwrap_or("unnamed");
    let out_binding = decl
        .get("outBinding")
        .or_else(|| decl.get("out_binding"))
        .and_then(JsonValue::as_str)
        .unwrap_or("out");
    let pre = decl
        .get("pre")
        .or_else(|| decl.get("precondition"))
        .map(json_to_cvalue);
    let post = decl
        .get("post")
        .or_else(|| decl.get("postcondition"))
        .map(json_to_cvalue);
    let inv = decl
        .get("inv")
        .or_else(|| decl.get("invariant"))
        .map(json_to_cvalue);
    if pre.is_none() && post.is_none() && inv.is_none() {
        return None;
    }
    let formals_json = decl.get("formals").and_then(JsonValue::as_array);
    let formals: Vec<String> = formals_json
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let formal_sorts: Vec<Arc<Value>> = decl
        .get("formalSorts")
        .or_else(|| decl.get("formal_sorts"))
        .and_then(JsonValue::as_array)
        .map(|arr| arr.iter().map(json_to_cvalue).collect())
        .unwrap_or_default();
    let emit_empty_formals =
        kind == "function-contract" && formals_json.is_some() && formals.is_empty();

    Some(contract_cid_from_parts(
        contract_name,
        out_binding,
        pre.as_ref(),
        post.as_ref(),
        inv.as_ref(),
        &formals,
        &formal_sorts,
        emit_empty_formals,
    ))
}

// Keep the private alias for internal use within this module.
fn contract_content_cid(args: &MintContractArgs) -> String {
    contract_cid(args)
}

/// Compute the DERIVED `propertyHash` for a contract header.
///
/// This is the hash of the contract properties the verifier indexes:
/// present `pre`/`post`/`inv` slots plus the output binding. It is
/// intentionally separate from `contract_cid`, which also includes the
/// contract name and identifies the signer-independent contract content.
pub fn contract_property_hash(args: &MintContractArgs) -> String {
    let mut ph_kvs: Vec<(String, Arc<Value>)> = Vec::new();
    if let Some(pre) = &args.pre {
        ph_kvs.push(("pre".into(), canon_formula_value(pre)));
    }
    if let Some(post) = &args.post {
        ph_kvs.push(("post".into(), canon_formula_value(post)));
    }
    if let Some(inv) = &args.inv {
        ph_kvs.push(("inv".into(), canon_formula_value(inv)));
    }
    ph_kvs.push(("outBinding".into(), Value::string(args.out_binding.clone())));
    hash_value(&Arc::new(Value::Object(ph_kvs)))
}

/// Compute the **contract set CID** from a slice of already-computed
/// `contractCid` strings (each `blake3-512:<128 hex>` produced by
/// `contract_cid()`).
///
/// Per `protocol/specs/2026-05-03-contract-set-extension.md` §1:
///   contractSetCid := "blake3-512:" || hex(BLAKE3-512(JCS(<sorted contractCids>)))
///
/// The sort is lexicographic on the raw `blake3-512:hex` strings, making
/// the result order-independent. Two kits enumerating the same contracts
/// in different order produce byte-identical `contractSetCid` values.
pub fn compute_contract_set_cid(mut contract_cids: Vec<String>) -> String {
    contract_cids.sort();
    let arr: Vec<Arc<Value>> = contract_cids.into_iter().map(Value::string).collect();
    let v = Value::array(arr);
    let jcs = encode_jcs(&v);
    blake3_512_of(jcs.as_bytes())
}

pub fn mint_contract(args: &MintContractArgs) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    mint_contract_with_body_cid(args, None)
}

pub fn mint_contract_with_body_cid(
    args: &MintContractArgs,
    body_cid: Option<&str>,
) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    if args.pre.is_none() && args.post.is_none() && args.inv.is_none() {
        return Err(ClaimEnvelopeError::EmptyContract);
    }
    if args.out_binding.is_empty() {
        return Err(ClaimEnvelopeError::EmptyOutBinding);
    }
    let canonical_pre = args.pre.as_ref().map(canon_formula_value);
    let canonical_post = args.post.as_ref().map(canon_formula_value);
    let canonical_inv = args.inv.as_ref().map(canon_formula_value);

    // DERIVED:
    //   propertyHash = hash(JCS({pre?, post?, inv?, outBinding}))
    //   bindingHash  = hash(JCS({producerId, contractName, propertyHash}))
    //
    // These ride in the header because the verifier uses them to index
    // and resolve callsites; they are substrate-load-bearing despite
    // being derivable (see spec §1 "kind-specific REQUIRED header
    // fields").
    let property_hash = contract_property_hash(args);

    let bh_obj = Value::object([
        ("producerId", Value::string(args.produced_by.clone())),
        ("contractName", Value::string(args.contract_name.clone())),
        ("propertyHash", Value::string(property_hash.clone())),
    ]);
    let binding_hash = hash_value(&bh_obj);

    // Header: schemaVersion + kind + cid + kind-specific REQUIRED fields.
    let header_cid = contract_content_cid(args);
    let mut kind_specific: Vec<(String, Arc<Value>)> = vec![
        ("name".into(), Value::string(args.contract_name.clone())),
        ("outBinding".into(), Value::string(args.out_binding.clone())),
    ];
    if let Some(body_cid) = body_cid.filter(|cid| !cid.is_empty()) {
        kind_specific.push(("bodyCid".into(), Value::string(body_cid.to_string())));
    }
    if body_cid.is_none() {
        if let Some(pre) = &canonical_pre {
            kind_specific.push(("pre".into(), pre.clone()));
        }
        if let Some(post) = &canonical_post {
            kind_specific.push(("post".into(), post.clone()));
        }
        if let Some(inv) = &canonical_inv {
            kind_specific.push(("inv".into(), inv.clone()));
        }
    }
    // Body-derived op-contract slots: `formals` (+ `formalSorts`) ride in
    // the header so `body_discharge::CatalogResolver` (which reads the
    // header via `memento_body` for v1.2-layered mementos) can project them
    // into `OpContractInfo` value slots. Omitted when empty unless
    // `emit_empty_formals` marks a zero-arg body-derived op-contract, so
    // non-function contracts are byte-identical to their pre-#1436 form.
    if !args.formals.is_empty() || args.emit_empty_formals {
        let formals_arr: Vec<Arc<Value>> = args
            .formals
            .iter()
            .map(|f| Value::string(f.clone()))
            .collect();
        kind_specific.push(("formals".into(), Value::array(formals_arr)));
    }
    if !args.formal_sorts.is_empty() || args.emit_empty_formals {
        kind_specific.push((
            "formalSorts".into(),
            Value::array(args.formal_sorts.clone()),
        ));
    }
    kind_specific.push(("verdict".into(), Value::string("holds")));
    kind_specific.push(("bindingHash".into(), Value::string(binding_hash)));
    kind_specific.push(("propertyHash".into(), Value::string(property_hash)));
    let mut sorted_inputs: Vec<String> = args.input_cids.clone();
    sorted_inputs.sort();
    let inputs_arr: Vec<Arc<Value>> = sorted_inputs.into_iter().map(Value::string).collect();
    kind_specific.push(("inputCids".into(), Value::array(inputs_arr)));

    // PANIC-LOCUS PRESERVATION (#1745): per-occurrence panic-leaf source loci.
    // Emitted in the header so the verifier's `enumerate_callsites` (which reads
    // the contract body via `memento_body`, i.e. the header for v1.2-layered
    // mementos) can attribute each `method:unwrap` obligation to ITS OWN source
    // line. Pushed AFTER `header_cid`/`property_hash` are computed: it is
    // provenance, NOT contract identity (`contract_cid`/`contract_property_hash`
    // never read it), so it must not perturb the contract CID. Omitted when
    // empty so contracts with no panic leaf keep their existing header bytes.
    if !args.panic_loci.is_empty() {
        kind_specific.push(("panicLoci".into(), Value::array(args.panic_loci.clone())));
    }
    if !args.class_shapes.is_empty() {
        kind_specific.push((
            "classShapes".into(),
            Value::array(args.class_shapes.clone()),
        ));
    }
    if !args.source_warrants.is_empty() {
        kind_specific.push((
            "sourceWarrants".into(),
            Value::array(args.source_warrants.clone()),
        ));
    }
    if let Some(provenance) = &args.proofir_provenance {
        kind_specific.push(("proofirProvenance".into(), provenance.clone()));
    }
    // Execution-witness evidence: PROVENANCE (how-discharged), carried in the
    // body for the verifier's witness arm, omitted when None so non-witness
    // contracts stay byte-identical. Does not perturb the contract CID.
    if let Some(ev) = &args.evidence_term {
        kind_specific.push(("evidence".into(), ev.clone()));
    }

    let header = build_header("contract", &header_cid, kind_specific);

    // Metadata: producer attribution + per-formula derived hashes
    // (purely tooling convenience; not used by the substrate verifier).
    let mut metadata_kvs: Vec<(String, Arc<Value>)> = vec![
        ("authoring".into(), authoring_to_value(&args.authoring)),
        ("producedBy".into(), Value::string(args.produced_by.clone())),
        ("producedAt".into(), Value::string(args.produced_at.clone())),
    ];
    if let Some(pre) = &canonical_pre {
        metadata_kvs.push(("preHash".into(), Value::string(hash_value(pre))));
    }
    if let Some(post) = &canonical_post {
        metadata_kvs.push(("postHash".into(), Value::string(hash_value(post))));
    }
    if let Some(inv) = &canonical_inv {
        metadata_kvs.push(("invHash".into(), Value::string(hash_value(inv))));
    }
    if let Some(library) = &args.library {
        if !library.is_empty() {
            metadata_kvs.push(("library".into(), Value::string(library.clone())));
        }
    }
    if let Some(bridge_source_symbol) = &args.bridge_source_symbol {
        if !bridge_source_symbol.is_empty() {
            metadata_kvs.push((
                "bridgeSourceSymbol".into(),
                Value::string(bridge_source_symbol.clone()),
            ));
        }
    }
    if !args.body_discharge_eligible {
        metadata_kvs.push(("bodyDischargeEligible".into(), Value::boolean(false)));
    }
    if let Some(reason) = &args.body_discharge_refusal_reason {
        if !reason.is_empty() {
            metadata_kvs.push((
                "bodyDischargeRefusalReason".into(),
                Value::string(reason.clone()),
            ));
        }
    }
    let metadata = Arc::new(Value::Object(metadata_kvs));

    Ok(assemble_layered(
        header,
        metadata,
        &args.produced_at,
        &args.signer_seed,
        header_cid,
    ))
}

// =============================================================================
// mint_bridge
// =============================================================================

pub struct MintBridgeArgs {
    pub produced_by: String,
    pub produced_at: String,
    pub source_symbol: String,
    pub source_layer: String,
    pub target_contract: ContractMementoRef,
    pub target_layer: String,
    pub ir_arg_sorts: Vec<String>,
    pub ir_return_sort: String,
    pub notes: String,
    pub signer_seed: Ed25519Seed,
    /// Forward pin (BridgeDeclaration.ConsequentBundlePinned, NORMATIVE):
    /// the CID of the `.proof` bundle that is allowed to discharge this
    /// bridge's target contract. `Some(bundle)` pins a CROSS-bundle target
    /// (a dependency proof); the verifier refuses any contract member not
    /// drawn from that bundle. `None` means SELF-pinned: the target must be
    /// a co-member of this bridge's own bundle. There is no unpinned path;
    /// `None` is enforced as same-bundle membership, not skipped.
    pub target_proof_cid: Option<String>,
    /// Call-site provenance for this bridge, carried verbatim from the lifter's
    /// bridge declaration. Load-bearing: `panic_site` is how the verifier
    /// (`enumerate_callsites` -> `cmd_verify`) routes a panic-leaf bridge into
    /// the panic-safe discharge path. Dropping it (the pre-fix behavior) made
    /// every minted panic site read back `panic_site=false` and stay
    /// undecidable. `None` keeps a callsite-less bridge byte-identical to its
    /// pre-field CID (callsite is NOT part of bridge content identity).
    pub callsite: Option<BridgeCallsite>,
}

/// Call-site provenance carried into a bridge memento. Mirrors the lifter's
/// `callsite` object so the verifier reads back `panicSite`/`file`/`start_line`.
#[derive(Clone, Debug, Default)]
pub struct BridgeCallsite {
    pub panic_site: bool,
    pub file: Option<String>,
    pub line: Option<i64>,
    pub formal_actuals: Option<Arc<Value>>,
}

/// Compute the content CID of a bridge declaration (signer-independent).
fn bridge_content_cid(args: &MintBridgeArgs) -> String {
    let target_contract_cid = args.target_contract.cid().as_str();
    let arg_sorts: Vec<Arc<Value>> = args
        .ir_arg_sorts
        .iter()
        .map(|s| Value::string(s.clone()))
        .collect();
    let mut fields: Vec<(&str, Arc<Value>)> = vec![
        ("sourceSymbol", Value::string(args.source_symbol.clone())),
        ("sourceLayer", Value::string(args.source_layer.clone())),
        ("targetContractCid", Value::string(target_contract_cid)),
        ("targetLayer", Value::string(args.target_layer.clone())),
        ("irArgSorts", Value::array(arg_sorts)),
        ("irReturnSort", Value::string(args.ir_return_sort.clone())),
    ];
    // The pin is part of bridge identity: a bridge that pins bundle A and one
    // that pins bundle B (same target contract) are DIFFERENT bridges. Only
    // emit the key when Some, so a self-pinned (None) bridge's CID is the
    // pin-free identity. encode_jcs sorts keys, so insertion order is moot.
    if let Some(ref bundle) = args.target_proof_cid {
        fields.push(("targetProofCid", Value::string(bundle.clone())));
    }
    let v = Value::object(fields);
    blake3_512_of(encode_jcs(&v).as_bytes())
}

pub fn mint_bridge(args: &MintBridgeArgs) -> MintedEnvelope {
    let target_contract_cid = args.target_contract.cid().as_str();
    let arg_sorts: Vec<Arc<Value>> = args
        .ir_arg_sorts
        .iter()
        .map(|s| Value::string(s.clone()))
        .collect();

    // DERIVED per spec:
    //   bindingHash  = hash(canonical({sourceLayer, sourceSymbol}))
    //   propertyHash = hash("bridge:" || sourceSymbol)
    let bh_obj = Value::object([
        ("sourceLayer", Value::string(args.source_layer.clone())),
        ("sourceSymbol", Value::string(args.source_symbol.clone())),
    ]);
    let binding_hash = hash_value(&bh_obj);
    let property_hash = hash_string(&format!("bridge:{}", args.source_symbol));

    let header_cid = bridge_content_cid(args);
    let mut kind_specific: Vec<(String, Arc<Value>)> = vec![
        (
            "sourceSymbol".into(),
            Value::string(args.source_symbol.clone()),
        ),
        (
            "sourceLayer".into(),
            Value::string(args.source_layer.clone()),
        ),
        (
            "targetContractCid".into(),
            Value::string(target_contract_cid),
        ),
        (
            "targetLayer".into(),
            Value::string(args.target_layer.clone()),
        ),
        ("irArgSorts".into(), Value::array(arg_sorts)),
        (
            "irReturnSort".into(),
            Value::string(args.ir_return_sort.clone()),
        ),
        ("verdict".into(), Value::string("holds")),
        ("bindingHash".into(), Value::string(binding_hash)),
        ("propertyHash".into(), Value::string(property_hash)),
        (
            "inputCids".into(),
            Value::array(vec![Value::string(target_contract_cid)]),
        ),
    ];
    // Forward pin into the body so the verifier (enumerate_callsites ->
    // resolve_target) can enforce ConsequentBundlePinned. Omitted when None
    // (self-pinned: the verifier enforces same-bundle co-membership instead).
    if let Some(ref bundle) = args.target_proof_cid {
        kind_specific.push(("targetProofCid".into(), Value::string(bundle.clone())));
    }
    // Carry the lifter's call-site object so the verifier can read `panicSite`
    // (the panic-discharge routing flag) plus file/line for the scoreboard.
    // NOT folded into `bridge_content_cid`: a bridge's identity is its
    // (sourceSymbol -> targetContract) relationship, invariant across the
    // distinct call sites that share a symbol.
    if let Some(ref cs) = args.callsite {
        let mut cs_fields: Vec<(&str, Arc<Value>)> =
            vec![("panicSite", Value::boolean(cs.panic_site))];
        if let Some(ref f) = cs.file {
            cs_fields.push(("file", Value::string(f.clone())));
        }
        if let Some(line) = cs.line {
            cs_fields.push(("start_line", Value::integer(i128::from(line))));
        }
        if let Some(ref formal_actuals) = cs.formal_actuals {
            cs_fields.push(("formalActuals", formal_actuals.clone()));
        }
        kind_specific.push(("callsite".into(), Value::object(cs_fields)));
    }

    let header = build_header("bridge", &header_cid, kind_specific);

    let mut metadata_kvs: Vec<(String, Arc<Value>)> = vec![
        ("producedBy".into(), Value::string(args.produced_by.clone())),
        ("producedAt".into(), Value::string(args.produced_at.clone())),
    ];
    if !args.notes.is_empty() {
        metadata_kvs.push(("notes".into(), Value::string(args.notes.clone())));
    }
    let metadata = Arc::new(Value::Object(metadata_kvs));

    assemble_layered(
        header,
        metadata,
        &args.produced_at,
        &args.signer_seed,
        String::new(),
    )
}

// =============================================================================
// mint_implication
// =============================================================================

pub struct MintImplicationArgs {
    pub produced_by: String,
    pub produced_at: String,
    pub antecedent_hash: String,
    pub consequent_hash: String,
    pub antecedent: ContractMementoRef,
    pub consequent: ContractMementoRef,
    pub additional_inputs: Vec<AuthorityMementoRef>,
    pub antecedent_slot: String,
    pub consequent_slot: String,
    pub prover: String,
    pub prover_run_ms: i64,
    pub smt_lib_input: String,
    pub proof_witness: String,
    pub signer_seed: Ed25519Seed,
}

fn implication_content_cid(args: &MintImplicationArgs) -> String {
    let antecedent_cid = args.antecedent.cid().as_str();
    let consequent_cid = args.consequent.cid().as_str();
    let v = Value::object([
        (
            "antecedentHash",
            Value::string(args.antecedent_hash.clone()),
        ),
        (
            "consequentHash",
            Value::string(args.consequent_hash.clone()),
        ),
        ("antecedentCid", Value::string(antecedent_cid)),
        ("consequentCid", Value::string(consequent_cid)),
        (
            "antecedentSlot",
            Value::string(args.antecedent_slot.clone()),
        ),
        (
            "consequentSlot",
            Value::string(args.consequent_slot.clone()),
        ),
    ]);
    blake3_512_of(encode_jcs(&v).as_bytes())
}

pub fn mint_implication(args: &MintImplicationArgs) -> MintedEnvelope {
    let antecedent_cid = args.antecedent.cid().as_str();
    let consequent_cid = args.consequent.cid().as_str();
    // DERIVED per spec:
    //   bindingHash  = hash(canonical({antecedentHash, consequentHash}))
    //   propertyHash = hash("implication:" || antecedentHash || ":" || consequentHash)
    let bh_obj = Value::object([
        (
            "antecedentHash",
            Value::string(args.antecedent_hash.clone()),
        ),
        (
            "consequentHash",
            Value::string(args.consequent_hash.clone()),
        ),
    ]);
    let binding_hash = hash_value(&bh_obj);
    let property_hash = hash_string(&format!(
        "implication:{}:{}",
        args.antecedent_hash, args.consequent_hash
    ));

    let header_cid = implication_content_cid(args);
    let mut input_cids = vec![antecedent_cid.to_string(), consequent_cid.to_string()];
    input_cids.extend(
        args.additional_inputs
            .iter()
            .map(|input| input.as_str().to_string()),
    );
    input_cids.sort();
    let input_arr: Vec<Arc<Value>> = input_cids.into_iter().map(Value::string).collect();

    let kind_specific: Vec<(String, Arc<Value>)> = vec![
        (
            "antecedentHash".into(),
            Value::string(args.antecedent_hash.clone()),
        ),
        (
            "consequentHash".into(),
            Value::string(args.consequent_hash.clone()),
        ),
        ("antecedentCid".into(), Value::string(antecedent_cid)),
        ("consequentCid".into(), Value::string(consequent_cid)),
        (
            "antecedentSlot".into(),
            Value::string(args.antecedent_slot.clone()),
        ),
        (
            "consequentSlot".into(),
            Value::string(args.consequent_slot.clone()),
        ),
        ("verdict".into(), Value::string("holds")),
        ("bindingHash".into(), Value::string(binding_hash)),
        ("propertyHash".into(), Value::string(property_hash)),
        ("inputCids".into(), Value::array(input_arr)),
    ];

    let header = build_header("implication", &header_cid, kind_specific);

    let mut metadata_kvs: Vec<(String, Arc<Value>)> = vec![
        ("producedBy".into(), Value::string(args.produced_by.clone())),
        ("producedAt".into(), Value::string(args.produced_at.clone())),
        ("prover".into(), Value::string(args.prover.clone())),
        (
            "proverRunMs".into(),
            Value::integer(i128::from(args.prover_run_ms)),
        ),
    ];
    if !args.smt_lib_input.is_empty() {
        metadata_kvs.push((
            "smtLibInput".into(),
            Value::string(args.smt_lib_input.clone()),
        ));
    }
    if !args.proof_witness.is_empty() {
        metadata_kvs.push((
            "proofWitness".into(),
            Value::string(args.proof_witness.clone()),
        ));
    }
    let metadata = Arc::new(Value::Object(metadata_kvs));

    assemble_layered(
        header,
        metadata,
        &args.produced_at,
        &args.signer_seed,
        String::new(),
    )
}

// =============================================================================
// seal_spoken_obligation — implication = spoken Obligation (#3809)
// =============================================================================

/// Deterministic seal timestamp so attestation CID is a pure function of the
/// edge content (same post⊃pre → same signed memento under the seal seed).
pub const OBLIGATION_SEAL_PRODUCED_AT: &str = "1970-01-01T00:00:00.000Z";

/// Deterministic seal signer seed (content-addressed federation, not a secret).
pub const OBLIGATION_SEAL_SIGNER_SEED: Ed25519Seed = [0x0bu8; 32];

/// Slot names for the Obligation edge `post ⊃ pre` (Hoare composition).
pub const OBLIGATION_ANTECEDENT_SLOT: &str = "post";
pub const OBLIGATION_CONSEQUENT_SLOT: &str = "pre";

/// Content CID of a formula endpoint: JCS-blake3 of the alpha-canonical
/// [`IrFormula`]. Pure function of the formula; used as both `*Hash` and
/// endpoint CID when sealing a link-time Obligation that carries formulas
/// (not contract memento refs).
pub fn formula_endpoint_cid(formula: &sugar_ir_types::IrFormula) -> String {
    let canon = sugar_ir_types::canonicalize_formula(formula);
    let json = serde_json::to_value(&canon).expect("IrFormula serializes");
    sugar_canonicalizer::jcs_cid_of_json(&json)
}

/// Seal a link-time Obligation (`post ⊃ pre` / [`IrFormula::Implies`]) as the
/// **existing** implication memento shape via [`mint_implication`].
///
/// **Mapping (carried == checked == spoken, one seal):**
///
/// | Obligation (`as_implies` operands) | Implication memento field |
/// |------------------------------------|---------------------------|
/// | `post` (left of `post ⊃ pre`)      | antecedent: formula CID + slot `"post"` |
/// | `pre` (right of `post ⊃ pre`)      | consequent: formula CID + slot `"pre"` |
///
/// Endpoint CIDs are [`formula_endpoint_cid`] of each formula (no parallel
/// Obligation type). Header content CID and (with fixed seal seed/timestamp)
/// attestation CID are pure functions of `(post, pre)`.
///
/// Does **not** claim solver discharge: the wire still carries the mint
/// shape's `verdict` field (existing `mint_implication` convention). Real
/// discharge of `post ⊃ pre` remains the linker's job.
pub fn seal_spoken_obligation(
    post: &sugar_ir_types::IrFormula,
    pre: &sugar_ir_types::IrFormula,
) -> MintedEnvelope {
    let antecedent_cid = formula_endpoint_cid(post);
    let consequent_cid = formula_endpoint_cid(pre);
    // Hashes = formula CIDs: the formula IS the endpoint identity for a
    // formula-level Obligation seal (no separate contract memento on the edge).
    let args = MintImplicationArgs {
        produced_by: "sugar-obligation-seal".into(),
        produced_at: OBLIGATION_SEAL_PRODUCED_AT.into(),
        antecedent_hash: antecedent_cid.clone(),
        consequent_hash: consequent_cid.clone(),
        antecedent: ContractMementoRef::new(antecedent_cid),
        consequent: ContractMementoRef::new(consequent_cid),
        additional_inputs: Vec::new(),
        antecedent_slot: OBLIGATION_ANTECEDENT_SLOT.into(),
        consequent_slot: OBLIGATION_CONSEQUENT_SLOT.into(),
        prover: "obligation-seal".into(),
        prover_run_ms: 0,
        smt_lib_input: String::new(),
        proof_witness: String::new(),
        signer_seed: OBLIGATION_SEAL_SIGNER_SEED,
    };
    mint_implication(&args)
}

/// Header content CID of a sealed Obligation edge (signer-independent pure
/// function of endpoint formula CIDs + fixed slots). Prefer this over
/// [`MintedEnvelope::cid`] when asserting seal purity without signature.
pub fn spoken_obligation_content_cid(
    post: &sugar_ir_types::IrFormula,
    pre: &sugar_ir_types::IrFormula,
) -> String {
    let antecedent_cid = formula_endpoint_cid(post);
    let consequent_cid = formula_endpoint_cid(pre);
    let args = MintImplicationArgs {
        produced_by: String::new(),
        produced_at: String::new(),
        antecedent_hash: antecedent_cid.clone(),
        consequent_hash: consequent_cid.clone(),
        antecedent: ContractMementoRef::new(antecedent_cid),
        consequent: ContractMementoRef::new(consequent_cid),
        additional_inputs: Vec::new(),
        antecedent_slot: OBLIGATION_ANTECEDENT_SLOT.into(),
        consequent_slot: OBLIGATION_CONSEQUENT_SLOT.into(),
        prover: String::new(),
        prover_run_ms: 0,
        smt_lib_input: String::new(),
        proof_witness: String::new(),
        signer_seed: OBLIGATION_SEAL_SIGNER_SEED,
    };
    implication_content_cid(&args)
}

/// Build a speakable `.proof` catalog whose sole member is the sealed
/// Obligation implication. Ready for [`speak_implication`](sugar_verifier::utterance).
pub fn spoken_obligation_proof_bytes(
    post: &sugar_ir_types::IrFormula,
    pre: &sugar_ir_types::IrFormula,
) -> (MintedEnvelope, Vec<u8>, String) {
    use sugar_proof_envelope::{
        ed25519_pubkey_string, build_proof_envelope, ImplicationMemento, ProofEnvelopeInput,
        ProofGraph,
    };
    let sealed = seal_spoken_obligation(post, pre);
    let mut graph = ProofGraph::new();
    graph.push_implication(ImplicationMemento::new(sealed.canonical_bytes.clone()));
    let pubkey = ed25519_pubkey_string(&OBLIGATION_SEAL_SIGNER_SEED);
    let signer_cid = blake3_512_of(pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: "spoken-obligation".into(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed: OBLIGATION_SEAL_SIGNER_SEED,
        declared_at: OBLIGATION_SEAL_PRODUCED_AT.into(),
        manifest: None,
    });
    (sealed, built.bytes, built.cid)
}

// =============================================================================
// mint_witness
// =============================================================================

pub struct MintWitnessArgs {
    pub claim_kind: String,
    pub claim_body_cid: String,
    pub verifier_cid: String,
    pub policy_cid: String,
    pub evidence_root_cid: String,
    pub input_cids: Vec<String>,
    pub produced_by: String,
    pub produced_at: String,
    pub claim_body: Arc<Value>,
    pub evidence: Arc<Value>,
    pub signer_seed: Ed25519Seed,
}

fn witness_content_cid(args: &MintWitnessArgs) -> String {
    let mut input_cids = args.input_cids.clone();
    input_cids.sort();
    let input_arr: Vec<Arc<Value>> = input_cids.into_iter().map(Value::string).collect();
    let v = Value::object([
        ("claimKind", Value::string(args.claim_kind.clone())),
        ("claimBodyCid", Value::string(args.claim_body_cid.clone())),
        ("verifierCid", Value::string(args.verifier_cid.clone())),
        ("policyCid", Value::string(args.policy_cid.clone())),
        (
            "evidenceRootCid",
            Value::string(args.evidence_root_cid.clone()),
        ),
        ("inputCids", Value::array(input_arr)),
    ]);
    blake3_512_of(encode_jcs(&v).as_bytes())
}

pub fn mint_witness(args: &MintWitnessArgs) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    if args.claim_kind.is_empty()
        || args.claim_body_cid.is_empty()
        || args.verifier_cid.is_empty()
        || args.policy_cid.is_empty()
        || args.evidence_root_cid.is_empty()
    {
        return Err(ClaimEnvelopeError::Other(
            "mint_witness: claim kind, body CID, verifier CID, policy CID, and evidence root CID must not be empty".into(),
        ));
    }

    let header_cid = witness_content_cid(args);
    let mut sorted_inputs = args.input_cids.clone();
    sorted_inputs.sort();
    let input_arr: Vec<Arc<Value>> = sorted_inputs.into_iter().map(Value::string).collect();
    let header = build_header(
        "witness",
        &header_cid,
        vec![
            ("claimKind".into(), Value::string(args.claim_kind.clone())),
            (
                "claimBodyCid".into(),
                Value::string(args.claim_body_cid.clone()),
            ),
            ("verdict".into(), Value::string("holds")),
            (
                "verifierCid".into(),
                Value::string(args.verifier_cid.clone()),
            ),
            ("policyCid".into(), Value::string(args.policy_cid.clone())),
            (
                "evidenceRootCid".into(),
                Value::string(args.evidence_root_cid.clone()),
            ),
            ("inputCids".into(), Value::array(input_arr)),
        ],
    );

    let metadata = Arc::new(Value::Object(vec![
        ("producedBy".into(), Value::string(args.produced_by.clone())),
        ("producedAt".into(), Value::string(args.produced_at.clone())),
        ("claimBody".into(), args.claim_body.clone()),
        ("evidence".into(), args.evidence.clone()),
    ]));

    Ok(assemble_layered(
        header,
        metadata,
        &args.produced_at,
        &args.signer_seed,
        String::new(),
    ))
}

// =============================================================================
// mint_effect_site_annotation
// =============================================================================

pub struct MintEffectSiteAnnotationArgs {
    pub effect_kind: String,
    pub file: String,
    pub line: usize,
    pub callee: String,
    pub status: String,
    pub category: String,
    pub tier_to_close: String,
    pub reason: String,
    pub input_cids: Vec<String>,
    pub produced_by: String,
    pub produced_at: String,
    pub signer_seed: Ed25519Seed,
}

fn effect_site_annotation_content_cid(args: &MintEffectSiteAnnotationArgs, line: i64) -> String {
    let mut sorted_inputs = args.input_cids.clone();
    sorted_inputs.sort();
    let input_arr: Vec<Arc<Value>> = sorted_inputs.into_iter().map(Value::string).collect();
    let content = Value::object([
        ("effectKind", Value::string(args.effect_kind.clone())),
        ("file", Value::string(args.file.clone())),
        ("line", Value::integer(i128::from(line))),
        ("callee", Value::string(args.callee.clone())),
        ("status", Value::string(args.status.clone())),
        ("category", Value::string(args.category.clone())),
        ("tierToClose", Value::string(args.tier_to_close.clone())),
        ("reason", Value::string(args.reason.clone())),
        ("inputCids", Value::array(input_arr)),
    ]);
    blake3_512_of(encode_jcs(&content).as_bytes())
}

pub fn mint_effect_site_annotation(
    args: &MintEffectSiteAnnotationArgs,
) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    if args.effect_kind.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: effectKind must not be empty".into(),
        ));
    }
    if args.file.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: file must not be empty".into(),
        ));
    }
    if args.callee.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: callee must not be empty".into(),
        ));
    }
    if !matches!(args.status.as_str(), "residue" | "unproven") {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: status must be residue or unproven".into(),
        ));
    }
    if args.category.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: category must not be empty".into(),
        ));
    }
    if args.tier_to_close.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: tierToClose must not be empty".into(),
        ));
    }
    if args.reason.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: reason must not be empty".into(),
        ));
    }
    if args.produced_by.is_empty() || args.produced_at.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: producedBy and producedAt must not be empty".into(),
        ));
    }
    let line = i64::try_from(args.line).map_err(|_| {
        ClaimEnvelopeError::Other(
            "mint_effect_site_annotation: line does not fit signed 64-bit integer".into(),
        )
    })?;

    let header_cid = effect_site_annotation_content_cid(args, line);
    let mut sorted_inputs = args.input_cids.clone();
    sorted_inputs.sort();
    let input_arr: Vec<Arc<Value>> = sorted_inputs.into_iter().map(Value::string).collect();
    let header = build_header(
        "effect-site-annotation",
        &header_cid,
        vec![
            ("effectKind".into(), Value::string(args.effect_kind.clone())),
            ("file".into(), Value::string(args.file.clone())),
            ("line".into(), Value::integer(i128::from(line))),
            ("callee".into(), Value::string(args.callee.clone())),
            ("status".into(), Value::string(args.status.clone())),
            ("category".into(), Value::string(args.category.clone())),
            (
                "tierToClose".into(),
                Value::string(args.tier_to_close.clone()),
            ),
            ("reason".into(), Value::string(args.reason.clone())),
            ("inputCids".into(), Value::array(input_arr)),
        ],
    );
    let metadata = Arc::new(Value::Object(vec![
        ("producedBy".into(), Value::string(args.produced_by.clone())),
        ("producedAt".into(), Value::string(args.produced_at.clone())),
    ]));

    Ok(assemble_layered(
        header,
        metadata,
        &args.produced_at,
        &args.signer_seed,
        String::new(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_proof_envelope::{member_field, Member};

    fn dummy_seed() -> Ed25519Seed {
        [0x42; 32]
    }

    fn fixture_cid(hex: char) -> String {
        format!("blake3-512:{}", hex.to_string().repeat(128))
    }

    fn valid_effect_site_annotation_args() -> MintEffectSiteAnnotationArgs {
        MintEffectSiteAnnotationArgs {
            effect_kind: "panic-freedom".into(),
            file: "src/lib.rs".into(),
            line: 42,
            callee: "method:unwrap".into(),
            status: "residue".into(),
            category: "lock_poisoning_residue".into(),
            tier_to_close: "irreducible".into(),
            reason: "lock poisoning is runtime residue".into(),
            input_cids: vec![fixture_cid('1')],
            produced_by: "test".into(),
            produced_at: "2026-06-01T00:00:00Z".into(),
            signer_seed: dummy_seed(),
        }
    }

    #[test]
    fn body_discharge_policy_accepts_new_allowed() {
        let entry = serde_json::json!({
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "allowed"
                }
            }
        });

        let policy = body_discharge_policy_from_object(&entry);

        assert!(policy.body_discharge_eligible);
        assert_eq!(policy.body_discharge_refusal_reason, None);
        assert!(policy.warnings.is_empty());
    }

    #[test]
    fn body_discharge_policy_accepts_new_refused_with_reason() {
        let entry = serde_json::json!({
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "refused",
                    "reason": "totality-axiom"
                }
            }
        });

        let policy = body_discharge_policy_from_object(&entry);

        assert!(!policy.body_discharge_eligible);
        assert_eq!(
            policy.body_discharge_refusal_reason.as_deref(),
            Some("totality-axiom")
        );
        assert!(policy.warnings.is_empty());
    }

    #[test]
    fn body_discharge_policy_keeps_snake_case_legacy_fields() {
        let entry = serde_json::json!({
            "body_discharge_eligible": false,
            "body_discharge_refusal_reason": "legacy-snake"
        });

        let policy = body_discharge_policy_from_object(&entry);

        assert!(!policy.body_discharge_eligible);
        assert_eq!(
            policy.body_discharge_refusal_reason.as_deref(),
            Some("legacy-snake")
        );
        assert!(policy.warnings.is_empty());
    }

    #[test]
    fn body_discharge_policy_accepts_matching_legacy_and_policy_fields() {
        let entry = serde_json::json!({
            "bodyDischargeEligible": false,
            "bodyDischargeRefusalReason": "totality-axiom",
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "refused",
                    "reason": "totality-axiom"
                }
            }
        });

        let policy = body_discharge_policy_from_object(&entry);

        assert!(!policy.body_discharge_eligible);
        assert_eq!(
            policy.body_discharge_refusal_reason.as_deref(),
            Some("totality-axiom")
        );
        assert!(policy.warnings.is_empty());
    }

    #[test]
    fn body_discharge_policy_legacy_wins_on_disagreement() {
        let entry = serde_json::json!({
            "bodyDischargeEligible": false,
            "bodyDischargeRefusalReason": "legacy-refusal",
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "allowed"
                }
            }
        });

        let policy = body_discharge_policy_from_object(&entry);

        assert!(!policy.body_discharge_eligible);
        assert_eq!(
            policy.body_discharge_refusal_reason.as_deref(),
            Some("legacy-refusal")
        );
        assert!(matches!(
            policy.warnings.as_slice(),
            [BodyDischargePolicyWarning::Disagreement { .. }]
        ));
    }

    #[test]
    fn body_discharge_policy_malformed_warns_and_falls_back_to_legacy() {
        let entry = serde_json::json!({
            "bodyDischargeEligible": true,
            "dischargePolicy": {
                "bodyReduction": {
                    "status": "maybe"
                }
            }
        });

        let policy = body_discharge_policy_from_object(&entry);

        assert!(policy.body_discharge_eligible);
        assert_eq!(policy.body_discharge_refusal_reason, None);
        assert!(matches!(
            policy.warnings.as_slice(),
            [BodyDischargePolicyWarning::Malformed { .. }]
        ));
    }

    #[test]
    fn body_discharge_policy_ignores_foreign_policy_keys() {
        let entry = serde_json::json!({
            "dischargePolicy": {
                "headerReduction": {
                    "status": "refused",
                    "reason": "not-this-policy"
                }
            }
        });

        let policy = body_discharge_policy_from_object_with_default(&entry, false);

        assert!(!policy.body_discharge_eligible);
        assert_eq!(policy.body_discharge_refusal_reason, None);
        assert!(policy.warnings.is_empty());
    }

    #[test]
    fn empty_contract_rejected() {
        let args = MintContractArgs {
            evidence_term: None,
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            bridge_source_symbol: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            proofir_provenance: None,
            contract_name: "x".into(),
            pre: None,
            post: None,
            inv: None,
            out_binding: "out".into(),
            produced_by: "test".into(),
            produced_at: "2026-04-30T00:00:00.000Z".into(),
            input_cids: vec![],
            authoring: Authoring::KitAuthor {
                author: "test".into(),
                note: None,
            },
            signer_seed: dummy_seed(),
        };
        let r = mint_contract(&args);
        assert!(matches!(r, Err(ClaimEnvelopeError::EmptyContract)));
    }

    #[test]
    fn cid_is_blake3_512_prefixed() {
        let pre = Value::object([
            ("kind", Value::string("atomic")),
            ("name", Value::string(">")),
            (
                "args",
                Value::array(vec![
                    Value::object([("kind", Value::string("var")), ("name", Value::string("n"))]),
                    Value::object([
                        ("kind", Value::string("const")),
                        ("value", Value::integer(0)),
                        (
                            "sort",
                            Value::object([
                                ("kind", Value::string("primitive")),
                                ("name", Value::string("Int")),
                            ]),
                        ),
                    ]),
                ]),
            ),
        ]);
        let args = MintContractArgs {
            evidence_term: None,
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            bridge_source_symbol: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            proofir_provenance: None,
            contract_name: "parseInt".into(),
            pre: Some(pre),
            post: None,
            inv: None,
            out_binding: "out".into(),
            produced_by: "rust-kit@1.0".into(),
            produced_at: "2026-04-30T00:00:00.000Z".into(),
            input_cids: vec![],
            authoring: Authoring::KitAuthor {
                author: "rust-kit@1.0".into(),
                note: None,
            },
            signer_seed: dummy_seed(),
        };
        let m = mint_contract(&args).expect("mint");
        assert!(m.cid.starts_with("blake3-512:"));
        assert_eq!(m.cid.len(), "blake3-512:".len() + 128);
    }

    #[test]
    fn contract_property_hash_matches_minted_header() {
        let post = Value::object([
            ("kind", Value::string("atomic")),
            ("name", Value::string("ok")),
            ("args", Value::array(vec![Value::string("out")])),
        ]);
        let args = MintContractArgs {
            evidence_term: None,
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            bridge_source_symbol: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            proofir_provenance: None,
            contract_name: "checked_add_u8.postcondition".into(),
            pre: None,
            post: Some(post),
            inv: None,
            out_binding: "out".into(),
            produced_by: "test".into(),
            produced_at: "2026-04-30T00:00:00.000Z".into(),
            input_cids: vec![],
            authoring: Authoring::KitAuthor {
                author: "test".into(),
                note: None,
            },
            signer_seed: dummy_seed(),
        };

        let expected = contract_property_hash(&args);
        let m = mint_contract(&args).expect("mint");
        let env: serde_json::Value =
            serde_json::from_slice(&m.canonical_bytes).expect("parse memento");
        let actual = member_field(&env, "propertyHash")
            .and_then(|v| v.as_str())
            .expect("header.propertyHash");

        assert_eq!(actual, expected);
    }

    #[test]
    fn mint_authority_emits_key_scope_and_parent_link() {
        let authority_key = ed25519_pubkey_string(&[0x22; 32]);
        let args = MintAuthorityArgs {
            principal: "bridgeworks.software".into(),
            key: authority_key.clone(),
            scope_kind: "contract".into(),
            scope: "checked_add_u8.postcondition".into(),
            parent_authority: Some(AuthorityMementoRef::new(fixture_cid('d'))),
            produced_by: "test".into(),
            produced_at: "2026-05-08T00:00:00.000Z".into(),
            signer_seed: dummy_seed(),
        };

        let minted = mint_authority(&args).expect("mint authority");
        let env: serde_json::Value =
            serde_json::from_slice(&minted.canonical_bytes).expect("parse authority");

        let member = Member::from_value(&env).expect("parse authority member");
        let a = match &member {
            Member::Authority(a) => a,
            other => panic!("expected authority, got {}", other.kind()),
        };

        assert_eq!(member.kind().as_str(), "authority");
        assert_eq!(a.principal, "bridgeworks.software");
        assert_eq!(a.key, authority_key.as_str());
        assert_eq!(a.scope_kind, "contract");
        assert_eq!(a.scope, "checked_add_u8.postcondition");
        assert_eq!(
            a.input_cids
                .as_ref()
                .and_then(|v| v.first())
                .map(|c| c.as_str()),
            Some(fixture_cid('d').as_str())
        );
        assert!(minted.cid.starts_with("blake3-512:"));
    }

    #[test]
    fn effect_site_annotation_mints_layered_panic_annotation_header() {
        let args = valid_effect_site_annotation_args();

        let minted = mint_effect_site_annotation(&args).expect("mint annotation");
        let env: serde_json::Value =
            serde_json::from_slice(&minted.canonical_bytes).expect("parse annotation");

        let member = Member::from_value(&env).expect("parse effect-site-annotation member");
        let e = match &member {
            Member::EffectSiteAnnotation(e) => e,
            other => panic!("expected effect-site-annotation, got {}", other.kind()),
        };

        assert_eq!(member.kind().as_str(), "effect-site-annotation");
        assert_eq!(e.effect_kind, "panic-freedom");
        assert_eq!(e.file, "src/lib.rs");
        assert_eq!(e.line, 42i64);
        assert_eq!(e.callee, "method:unwrap");
        assert_eq!(e.status, "residue");
        assert_eq!(e.category, "lock_poisoning_residue");
        assert_eq!(e.tier_to_close, "irreducible");
        assert_eq!(e.reason, "lock poisoning is runtime residue");
        assert_eq!(
            e.input_cids.first().map(|c| c.as_str()),
            Some(fixture_cid('1').as_str())
        );
        assert!(minted.cid.starts_with("blake3-512:"));
    }

    #[test]
    fn effect_site_annotation_input_cids_are_order_invariant() {
        let mut first = valid_effect_site_annotation_args();
        first.input_cids = vec![fixture_cid('a'), fixture_cid('b')];
        let mut second = valid_effect_site_annotation_args();
        second.input_cids = vec![fixture_cid('b'), fixture_cid('a')];

        let first = mint_effect_site_annotation(&first).expect("mint first");
        let second = mint_effect_site_annotation(&second).expect("mint second");
        let first_env: serde_json::Value =
            serde_json::from_slice(&first.canonical_bytes).expect("parse first");
        let second_env: serde_json::Value =
            serde_json::from_slice(&second.canonical_bytes).expect("parse second");

        assert_eq!(first.cid, second.cid);
        let m1 = Member::from_value(&first_env).expect("parse first effect-site-annotation");
        let m2 = Member::from_value(&second_env).expect("parse second effect-site-annotation");
        let cid1 = match &m1 {
            Member::EffectSiteAnnotation(e) => e.cid.as_str(),
            other => panic!("expected effect-site-annotation, got {}", other.kind()),
        };
        let cid2 = match &m2 {
            Member::EffectSiteAnnotation(e) => e.cid.as_str(),
            other => panic!("expected effect-site-annotation, got {}", other.kind()),
        };
        assert_eq!(cid1, cid2);
    }

    #[test]
    fn effect_site_annotation_rejects_line_values_that_do_not_fit_i64() {
        let mut args = valid_effect_site_annotation_args();
        args.line = usize::MAX;

        let err = mint_effect_site_annotation(&args).expect_err("line overflow must fail");

        assert!(
            err.to_string().contains("line"),
            "line conversion error should identify the field: {err}"
        );
    }

    #[test]
    fn effect_site_annotation_rejects_missing_required_fields_and_invalid_status() {
        let mut args = MintEffectSiteAnnotationArgs {
            effect_kind: "panic-freedom".into(),
            file: "src/lib.rs".into(),
            line: 42,
            callee: "method:unwrap".into(),
            status: "maybe".into(),
            category: "lock_poisoning_residue".into(),
            tier_to_close: "irreducible".into(),
            reason: "lock poisoning is runtime residue".into(),
            input_cids: Vec::new(),
            produced_by: "test".into(),
            produced_at: "2026-06-01T00:00:00Z".into(),
            signer_seed: dummy_seed(),
        };

        let err = mint_effect_site_annotation(&args).expect_err("invalid status must fail");
        assert!(
            err.to_string().contains("status"),
            "error should name invalid status: {err}"
        );

        args.status = "unproven".into();
        args.effect_kind.clear();
        let err = mint_effect_site_annotation(&args).expect_err("missing effectKind must fail");
        assert!(
            err.to_string().contains("effectKind"),
            "error should name missing effectKind: {err}"
        );
    }

    // --- Reformat-invariant contract identity (the behavior-versioning keystone) ---

    /// Build a `post` slot `Arc<Value>` from an `IrFormula` by the SAME path
    /// the kits use: serialize to JSON, then into the canonical `Value`.
    fn post_value(f: &sugar_ir_types::IrFormula) -> Arc<Value> {
        json_to_cvalue(&serde_json::to_value(f).expect("formula serializes"))
    }

    fn contract_args_for_post(name: &str, post: Arc<Value>, formals: &[&str]) -> MintContractArgs {
        MintContractArgs {
            evidence_term: None,
            formals: formals.iter().map(|s| s.to_string()).collect(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            library: None,
            bridge_source_symbol: None,
            body_discharge_eligible: true,
            body_discharge_refusal_reason: None,
            panic_loci: Vec::new(),
            class_shapes: Vec::new(),
            source_warrants: Vec::new(),
            proofir_provenance: None,
            contract_name: name.into(),
            pre: None,
            post: Some(post),
            inv: None,
            out_binding: "result".into(),
            produced_by: "test".into(),
            produced_at: "2026-06-08T00:00:00.000Z".into(),
            input_cids: vec![],
            authoring: Authoring::KitAuthor {
                author: "test".into(),
                note: None,
            },
            signer_seed: dummy_seed(),
        }
    }

    /// THE behavior-versioning keystone, at the layer `sugar diff` reads: a
    /// reformat that introduces a local (`let n = x; n*2`) must hash to the
    /// SAME `contract_cid` as the inline form (`x*2`), while a real behavior
    /// change (`x*3`) must NOT. The lifter emits a faithful `let`; the envelope
    /// canonicalizes it away before hashing. End-to-end, deterministic, no
    /// external lifter or solver.
    #[test]
    fn reformat_with_local_shares_contract_cid_real_change_does_not() {
        use sugar_ir_types::{IrFormula, IrTerm, LetBinding, Sort};

        let var = |n: &str| IrTerm::Var { name: n.into() };
        let int = |v: i64| IrTerm::Const {
            value: serde_json::json!(v),
            sort: Sort::Primitive { name: "Int".into() },
        };
        let mul = |a: IrTerm, b: IrTerm| IrTerm::Ctor {
            name: "*".into(),
            args: vec![a, b],
        };
        let eq_result = |t: IrTerm| IrFormula::Atomic {
            name: "=".into(),
            args: vec![var("result"), t],
        };

        // double(x) = x*2
        let inline = eq_result(mul(var("x"), int(2)));
        // double(x) = { let n = x; n*2 } -- faithful let the rust lifter now emits
        let with_let = eq_result(IrTerm::Let {
            bindings: vec![LetBinding {
                name: "n".into(),
                bound_term: var("x"),
            }],
            body: Box::new(mul(var("n"), int(2))),
        });
        // double(x) = x*3 -- a real behavior change
        let changed = eq_result(mul(var("x"), int(3)));

        let cid_inline = contract_cid(&contract_args_for_post(
            "double",
            post_value(&inline),
            &["x"],
        ));
        let cid_let = contract_cid(&contract_args_for_post(
            "double",
            post_value(&with_let),
            &["x"],
        ));
        let cid_changed = contract_cid(&contract_args_for_post(
            "double",
            post_value(&changed),
            &["x"],
        ));

        assert_eq!(
            cid_inline, cid_let,
            "let-reformat must share the inline form's contract CID"
        );
        assert_ne!(
            cid_inline, cid_changed,
            "a real behavior change must move the contract CID"
        );
    }

    #[test]
    fn minted_contract_header_uses_canonical_formula_slots() {
        use sugar_ir_types::{IrFormula, IrTerm, LetBinding};

        let var = |n: &str| IrTerm::Var { name: n.into() };
        let call = |name: &str, args: Vec<IrTerm>| IrTerm::Ctor {
            name: name.into(),
            args,
        };
        let eq_result = |t: IrTerm| IrFormula::Atomic {
            name: "=".into(),
            args: vec![var("result"), t],
        };

        let raw_with_let = eq_result(IrTerm::Let {
            bindings: vec![LetBinding {
                name: "m".into(),
                bound_term: call("new", vec![call("producer", vec![])]),
            }],
            body: Box::new(call("consumer", vec![var("m")])),
        });
        let expected_canonical = eq_result(call(
            "consumer",
            vec![call("new", vec![call("producer", vec![])])],
        ));

        let args = contract_args_for_post("edge", post_value(&raw_with_let), &[]);
        let minted = mint_contract(&args).expect("mint");
        let env: serde_json::Value =
            serde_json::from_slice(&minted.canonical_bytes).expect("parse memento");

        assert_eq!(
            member_field(&env, "post"),
            Some(&serde_json::to_value(expected_canonical).expect("canonical formula serializes")),
            "the verifier reads header.post, so the stored formula must match the canonicalized CID/propertyHash form"
        );
    }

    /// BLAST-RADIUS BOUND: a `post` with no `let`/binder hashes to EXACTLY the
    /// same `contract_cid` whether or not the canonicalization step runs --
    /// `canon_formula_value` returns the original bytes when canonicalization is
    /// a no-op, so introducing the step cannot move any let-free contract.
    #[test]
    fn let_free_formula_is_byte_transparent() {
        let pre = Value::object([
            ("kind", Value::string("atomic")),
            ("name", Value::string(">")),
            (
                "args",
                Value::array(vec![
                    Value::object([("kind", Value::string("var")), ("name", Value::string("n"))]),
                    Value::object([
                        ("kind", Value::string("const")),
                        ("value", Value::integer(0)),
                        (
                            "sort",
                            Value::object([
                                ("kind", Value::string("primitive")),
                                ("name", Value::string("Int")),
                            ]),
                        ),
                    ]),
                ]),
            ),
        ]);
        // canon_formula_value must hand back the very same bytes.
        assert_eq!(encode_jcs(&canon_formula_value(&pre)), encode_jcs(&pre));
    }
}
