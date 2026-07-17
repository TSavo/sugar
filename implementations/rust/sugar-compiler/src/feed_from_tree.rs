// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Campaign B (plan: one-protocol enumerate + feed): fold the typed enumerate
// tree into a `ProofGraph` via `feed`.
//
// Construction mirrors mint's IR→member path (`mint_contract_with_body_cid`
// + `ContractBody::from_slots` + `ClaimContractMemento` + `push_claim_contract`)
// without depending on sugar-cli. `ProofGraph::feed` is the merge; content
// CIDs make walk order irrelevant.
//
// Speaker attribution lives at pool intake (`orchestrate::pool_from_graph_with_speaker`
// stamps `MementoPool.member_speaker`, first-writer-wins — same as utterance).
// `fold_project` accepts a `Speaker` so the walk face and pool load share one
// typed identity; the graph itself still carries content only.

use std::path::Path;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{encode_jcs, json_to_value, Value as CValue};
use sugar_claim_envelope::{
    body_discharge_default_for_kind, body_discharge_policy_from_fields_with_default, mint_bridge,
    mint_contract_with_body_cid, Authoring, MintBridgeArgs, MintContractArgs,
};
use sugar_proof_envelope::Speaker;
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_sign_string, BridgeMemento, ClaimContractMemento, ContractBody,
    ContractMementoRef, Ed25519Seed, FlatAtom, ProofGraph, SourceMemento,
};

use crate::kit::{Kit, KitError};
use crate::tree::{Fact, Sourced, Universe};

/// Deterministic kit-author seed for feed fragments (content-addressed;
/// not a sealed production mint identity).
const FEED_SIGNER_SEED: Ed25519Seed = [0x66; 32];
const FEED_PRODUCED_AT: &str = "2026-07-08T00:00:00.000Z";
const FEED_PRODUCED_BY: &str = "sugar-compiler/feed_from_tree";

/// Failures while turning an enumerate tree node into a `ProofGraph` fragment.
#[derive(Debug, thiserror::Error)]
pub enum FeedError {
    #[error(
        "feed_from_tree mint failed ({what}): {detail} — \
         check Fact/Universe payload + warrants shape against mint's \
         kind=contract / function-contract construction"
    )]
    Mint { what: &'static str, detail: String },
    #[error(
        "feed_from_tree::{what}: {detail} — \
         replacement: carry the missing field on the tree node or refuse at enumerate"
    )]
    Incomplete { what: &'static str, detail: String },
    #[error(transparent)]
    Kit(#[from] KitError),
}

/// serde_json → canonical Value for content-addressed feed members.
///
/// #3901: ONE door shared with mint / claim-envelope / libsugar::canonical —
/// `sugar_canonicalizer::json_to_value`. Integer numbers widen losslessly;
/// non-integers are a typed `FeedError::Incomplete` refusal. Never a local
/// Number arm (`unwrap_or(0)`, float→string, float→null).
fn json_to_cvalue(j: &Json) -> Result<Arc<CValue>, FeedError> {
    json_to_value(j).map_err(|err| FeedError::Incomplete {
        what: "json_to_cvalue",
        detail: format!(
            "{err} — non-integer JSON number cannot enter a content-addressed \
             feed atom (refusing silent zero); use sugar_canonicalizer::json_to_value"
        ),
    })
}

fn true_formula() -> Json {
    json!({"kind": "atomic", "name": "true", "args": []})
}

/// Optional IR fields that mint threads onto function-contract / claim members.
#[derive(Clone)]
struct ClaimExtras {
    formals: Vec<String>,
    /// When IR had an explicit `formals` field (even `[]`), emit empty formals.
    emit_empty_formals: bool,
    /// Sorts parallel to `formals`. Carried, never silently dropped (#3901).
    formal_sorts: Vec<Arc<CValue>>,
    bridge_source_symbol: Option<String>,
    out_binding: String,
    /// Must track mint's body-discharge policy. Default **false**: never claim
    /// body-discharge eligibility on synthetic shells or inv-only assertions
    /// without IR policy (PR #3897 High).
    body_discharge_eligible: bool,
    body_discharge_refusal_reason: Option<String>,
    proofir_provenance: Option<Arc<CValue>>,
}

impl Default for ClaimExtras {
    fn default() -> Self {
        Self {
            formals: Vec::new(),
            emit_empty_formals: false,
            formal_sorts: Vec::new(),
            bridge_source_symbol: None,
            // Match mint IR default for this kit (`outBinding: "out"`).
            out_binding: "out".into(),
            body_discharge_eligible: false,
            body_discharge_refusal_reason: Some(
                "feed_from_tree: body discharge not claimed (no IR policy)".into(),
            ),
            proofir_provenance: None,
        }
    }
}

/// Read mint's body-discharge policy fields from an IR row.
///
/// #3901: default eligibility is derived from the IR `kind` via
/// [`body_discharge_default_for_kind`] — never a free bool that can diverge
/// from mint. Assertions (`contract`) default false; `function-contract`
/// default true. Explicit IR directive still wins.
fn body_policy_from_ir(ir: &Json) -> (bool, Option<String>) {
    let kind = ir.get("kind").and_then(Json::as_str).unwrap_or("contract");
    let default_eligible = body_discharge_default_for_kind(kind);
    let policy = body_discharge_policy_from_fields_with_default(
        ir.get("bodyDischargeEligible")
            .or_else(|| ir.get("body_discharge_eligible")),
        ir.get("bodyDischargeRefusalReason")
            .or_else(|| ir.get("body_discharge_refusal_reason")),
        ir.get("dischargePolicy"),
        default_eligible,
    );
    (
        policy.body_discharge_eligible,
        policy.body_discharge_refusal_reason,
    )
}

/// Push one claim-contract member: register body slots, mint layered
/// envelope with bodyCid, `push_claim_contract`.
fn push_claim_with_slots(
    graph: &mut ProofGraph,
    contract_name: &str,
    slots: Vec<(&str, Json)>,
    source_warrants: Vec<Arc<CValue>>,
    extras: ClaimExtras,
) -> Result<(), FeedError> {
    if slots.is_empty() {
        return Err(FeedError::Incomplete {
            what: "push_claim_with_slots",
            detail: "contract body requires at least one of pre/post/inv".into(),
        });
    }

    let mut registered: Vec<(String, sugar_proof_envelope::AtomMemento)> = Vec::new();
    for (slot, formula) in &slots {
        let atom = graph.register_atom(FlatAtom::new(json_to_cvalue(formula)?));
        registered.push(((*slot).to_string(), atom));
    }
    let slot_refs: Vec<(&str, &sugar_proof_envelope::AtomMemento)> = registered
        .iter()
        .map(|(slot, atom)| (slot.as_str(), atom))
        .collect();
    let body = graph.register_body(ContractBody::from_slots(slot_refs));
    let body_cid = body.cid().as_str().to_string();

    let mut pre = None;
    let mut post = None;
    let mut inv = None;
    for (slot, formula) in &slots {
        let v = json_to_cvalue(formula)?;
        match *slot {
            "pre" => pre = Some(v),
            "post" => post = Some(v),
            "inv" => inv = Some(v),
            other => {
                return Err(FeedError::Incomplete {
                    what: "push_claim_with_slots",
                    detail: format!("unknown body slot `{other}` (expected pre|post|inv)"),
                });
            }
        }
    }

    // Capture for PR-23 auto-bridge after the claim is stamped (attestation
    // CID is the re-signed member's CID, not pre-stamp mint.cid).
    // Auto-bridge only when body-discharge eligible (same law as mint PR-23).
    let auto_bridge_symbol = if extras.body_discharge_eligible {
        extras.bridge_source_symbol.clone()
    } else {
        None
    };

    let args = MintContractArgs {
        evidence_term: None,
        formals: extras.formals,
        emit_empty_formals: extras.emit_empty_formals,
        // #3901: formal sorts are load-bearing for mint CID + linker ABI.
        // Never hardcode empty — carry whatever IR provided (or leave empty
        // only when IR genuinely omitted them).
        formal_sorts: extras.formal_sorts,
        library: None,
        bridge_source_symbol: extras.bridge_source_symbol,
        body_discharge_eligible: extras.body_discharge_eligible,
        body_discharge_refusal_reason: extras.body_discharge_refusal_reason,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants,
        proofir_provenance: extras.proofir_provenance,
        contract_name: contract_name.to_string(),
        pre,
        post,
        inv,
        out_binding: extras.out_binding,
        produced_by: FEED_PRODUCED_BY.into(),
        produced_at: FEED_PRODUCED_AT.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: FEED_PRODUCED_BY.into(),
            note: Some("feed_from_tree fragment".into()),
        },
        signer_seed: FEED_SIGNER_SEED,
    };

    let minted =
        mint_contract_with_body_cid(&args, Some(&body_cid)).map_err(|e| FeedError::Mint {
            what: "mint_contract_with_body_cid",
            detail: e.to_string(),
        })?;
    // mint_contract emits header.`name` but typed ContractMember requires
    // header.`contractName` (ContractMemento's dual-field shape). Stamp the
    // same string so feed recovery via typed_members_iter can read names.
    let memento = claim_memento_with_contract_name(minted.canonical_bytes, contract_name)?;
    // Member identity after contractName re-sign — bridge target must match
    // the pool index key (`pool.mementos`), not the pre-stamp mint CID.
    let attestation_cid = memento.cid().as_str().to_string();
    graph.push_claim_contract(memento);

    // PR-23 production bridge-writer (parity with sugar-cli mint_ir_document):
    // a body-bearing function-contract with bridgeSourceSymbol must also emit
    // a co-member Bridge so verify/prove can join callsite → universe body.
    // Without this, fold construction matches claim FOL but discharge stays
    // Refused while mint+prove discharges via linkedPosts.
    if let Some(source_symbol) = auto_bridge_symbol {
        let bridge = mint_bridge(&MintBridgeArgs {
            produced_by: FEED_PRODUCED_BY.into(),
            produced_at: FEED_PRODUCED_AT.into(),
            source_symbol,
            source_layer: "source".into(),
            target_contract: ContractMementoRef::new(attestation_cid),
            target_layer: "kit".into(),
            ir_arg_sorts: vec![],
            ir_return_sort: String::new(),
            notes: "auto-minted body-discharge bridge (feed_from_tree PR-23)".into(),
            signer_seed: FEED_SIGNER_SEED,
            // Self-pinned: target is a co-member of this feed fragment /
            // folded graph (same law as mint: no external bundle pin).
            target_proof_cid: None,
            callsite: None,
        });
        graph.push_bridge(BridgeMemento::new(bridge.canonical_bytes));
    }
    Ok(())
}

/// Mint-parity: lower each IR `sourceWarrants[]` entry to a lean
/// `source-memento` graph member keyed by `contractName`.
///
/// Consistency locus preference (#3809 cut #5) indexes **source-memento
/// members** (not embedded warrants on claim bodies). Without co-members,
/// consumer feed has `sources=0`, the row anchors on the vendor locus, and
/// editor-scope diagnostics for the open buffer vanish.
fn push_source_mementos_from_warrants(
    graph: &mut ProofGraph,
    warrants: &[Json],
    contract_name: &str,
) -> Result<(), FeedError> {
    for decl in warrants {
        push_one_source_memento(graph, decl, contract_name)?;
    }
    Ok(())
}

fn push_one_source_memento(
    graph: &mut ProofGraph,
    decl: &Json,
    contract_name: &str,
) -> Result<(), FeedError> {
    // Accept either a bare source-memento object or a wrapped `{source_memento: ...}`.
    let mut body = decl
        .get("source_memento")
        .or_else(|| decl.get("sourceMemento"))
        .cloned()
        .unwrap_or_else(|| decl.clone());
    let body_obj = body.as_object_mut().ok_or_else(|| FeedError::Incomplete {
        what: "push_source_memento",
        detail: "source warrant must be a JSON object".into(),
    })?;
    body_obj
        .entry("kind".to_string())
        .or_insert_with(|| json!("source-memento"));
    if body_obj.get("kind").and_then(Json::as_str) != Some("source-memento") {
        return Err(FeedError::Incomplete {
            what: "push_source_memento",
            detail: format!(
                "source warrant kind must be source-memento, got {:?}",
                body_obj.get("kind")
            ),
        });
    }
    for forbidden in ["body_text", "ast_template", "bodyText", "astTemplate"] {
        if body_obj.contains_key(forbidden) {
            return Err(FeedError::Incomplete {
                what: "push_source_memento",
                detail: format!(
                    "source-memento must be lean; forbidden inline field `{forbidden}`"
                ),
            });
        }
    }
    // Stamp claim identity so consistency locus map keys match the claim name.
    body_obj
        .entry("contractName".to_string())
        .or_insert_with(|| json!(contract_name));
    body_obj
        .entry("claimName".to_string())
        .or_insert_with(|| json!(contract_name));
    // Wire/tree SourceMemento uses function_name; mint also accepts source_function_name.
    if !body_obj.contains_key("source_function_name") {
        if let Some(fn_name) = body_obj
            .get("function_name")
            .or_else(|| body_obj.get("sourceFunctionName"))
            .cloned()
        {
            body_obj.insert("source_function_name".to_string(), fn_name);
        }
    }

    let source_cid = body_obj
        .get("source_cid")
        .or_else(|| body_obj.get("sourceCid"))
        .and_then(Json::as_str)
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| FeedError::Incomplete {
            what: "push_source_memento",
            detail: "source-memento missing non-empty source_cid".into(),
        })?
        .to_string();

    let mut header = serde_json::Map::new();
    header.insert("kind".to_string(), json!("source-memento"));
    header.insert("sourceCid".to_string(), json!(source_cid));
    for (header_field, body_field) in [
        ("claimName", "claimName"),
        ("contractName", "contractName"),
        ("eufName", "eufName"),
        ("file", "file"),
        ("role", "role"),
        ("sourceFunctionName", "source_function_name"),
        ("universeKind", "universe_kind"),
    ] {
        if let Some(value) = body_obj.get(body_field).cloned() {
            header.insert(header_field.to_string(), value);
        }
    }

    let envelope = json!({
        "body": body,
        "header": Json::Object(header),
        "schemaVersion": "1",
    });
    let bytes = encode_jcs(json_to_cvalue(&envelope)?.as_ref()).into_bytes();
    graph.push_source(SourceMemento::new(bytes));
    Ok(())
}

/// Body slots present on an IR contract/function-contract row.
fn slots_from_ir_row(ir: &Json) -> Vec<(&'static str, Json)> {
    let mut slots = Vec::new();
    for (key, name) in [("pre", "pre"), ("post", "post"), ("inv", "inv")] {
        if let Some(v) = ir.get(key).filter(|v| !v.is_null()) {
            slots.push((name, v.clone()));
        }
    }
    slots
}

fn formals_from_ir_row(ir: &Json) -> (Vec<String>, bool) {
    match ir.get("formals") {
        Some(Json::Array(arr)) => {
            let formals = arr
                .iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect::<Vec<_>>();
            let present = true;
            (formals, present)
        }
        _ => (Vec::new(), false),
    }
}

/// IR `formalSorts` / `formal_sorts` → mint `formal_sorts` carrier (#3901).
///
/// Silent drop was the open class: formals names rode through while sorts
/// were hardcoded `Vec::new()` at `push_claim_with_slots`. Mint CIDs and
/// linker ABI both read sorts; dropping them forges a different contract.
fn formal_sorts_from_ir_row(ir: &Json) -> Result<Vec<Arc<CValue>>, FeedError> {
    let Some(arr) = ir
        .get("formalSorts")
        .or_else(|| ir.get("formal_sorts"))
        .and_then(Json::as_array)
    else {
        return Ok(Vec::new());
    };
    let mut out = Vec::with_capacity(arr.len());
    for item in arr {
        out.push(json_to_cvalue(item)?);
    }
    Ok(out)
}

/// Warrants for a universe: prefer non-empty IR `sourceWarrants`, else the
/// self-locating memento. Empty provenance on a function-contract is a
/// provenance hole (#3901) — same fallback law as [`warrants_for_fact`].
fn warrants_for_universe(u: &Universe) -> Result<(Vec<Json>, Vec<Arc<CValue>>), FeedError> {
    if let Some(ir) = u.ir_row() {
        if let Some(arr) = ir
            .get("sourceWarrants")
            .or_else(|| ir.get("source_warrants"))
            .and_then(Json::as_array)
        {
            if !arr.is_empty() {
                let mut cvals = Vec::with_capacity(arr.len());
                for w in arr {
                    cvals.push(json_to_cvalue(w)?);
                }
                return Ok((arr.clone(), cvals));
            }
        }
    }
    let memento_json = u.source_memento().to_json();
    let cval = json_to_cvalue(&memento_json)?;
    Ok((vec![memento_json], vec![cval]))
}

fn bridge_from_ir_row(ir: &Json) -> Option<String> {
    ir.get("bridgeSourceSymbol")
        .or_else(|| ir.get("bridge_source_symbol"))
        .and_then(Json::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

fn out_binding_from_ir_row(ir: &Json) -> String {
    ir.get("outBinding")
        .or_else(|| ir.get("out_binding"))
        .and_then(Json::as_str)
        .filter(|s| !s.is_empty())
        .unwrap_or("out")
        .to_string()
}

fn proofir_provenance_variants(ir: &Json) -> Result<Vec<Option<Arc<CValue>>>, FeedError> {
    let Some(provenance) = ir
        .get("proofirProvenance")
        .or_else(|| ir.get("proofir_provenance"))
    else {
        return Ok(vec![None]);
    };
    let Some(object) = provenance.as_object() else {
        return Ok(vec![Some(json_to_cvalue(provenance)?)]);
    };
    let Some(warrants) = object.get("warrants").and_then(Json::as_array) else {
        return Ok(vec![Some(json_to_cvalue(provenance)?)]);
    };
    let mut kinds = Vec::new();
    for warrant in warrants {
        let Some(kind @ ("Stated" | "Derived")) = warrant.get("kind").and_then(Json::as_str) else {
            continue;
        };
        if !kinds.contains(&kind) {
            kinds.push(kind);
        }
    }
    if kinds.len() <= 1 {
        return Ok(vec![Some(json_to_cvalue(provenance)?)]);
    }
    kinds
        .into_iter()
        .map(|kind| {
            let mut narrowed = object.clone();
            narrowed.insert(
                "warrants".into(),
                Json::Array(
                    warrants
                        .iter()
                        .filter(|warrant| warrant.get("kind").and_then(Json::as_str) == Some(kind))
                        .cloned()
                        .collect(),
                ),
            );
            Ok(Some(json_to_cvalue(&Json::Object(narrowed))?))
        })
        .collect()
}

/// Mint-aligned unique claim name: prefer IR `name` (already locus-unique on
/// the batch path), else span-keyed function locus so duplicate `test_add`
/// facts do not collide under one contractName at pool load.
fn contract_name_for_fact(fact: &Fact) -> String {
    if let Some(ir) = fact.ir_row() {
        if let Some(name) = ir.get("name").and_then(Json::as_str) {
            if !name.is_empty() {
                return name.to_string();
            }
        }
    }
    let m = fact.source_memento();
    let base = if m.function_name.is_empty() {
        "feed::fact"
    } else {
        m.function_name.as_str()
    };
    // Span-keyed when IR name is absent — unique per fact locus.
    if m.span.start_line == 0 && m.span.end_line == 0 {
        format!("{base}@{}", m.file)
    } else {
        format!(
            "{base}@{}:{}:{}",
            m.file, m.span.start_line, m.span.start_col
        )
    }
}

/// Re-emit mint bytes with `header.contractName` filled from the contract
/// name (mint already put `header.name`). Preserves all other header fields
/// including `bodyCid` and `sourceWarrants`.
///
/// When `contractName` is inserted, the layered envelope is **re-signed** with
/// [`FEED_SIGNER_SEED`]: the Ed25519 covers JCS(`{header, metadata}`), so a
/// post-mint header mutation without re-sign fails `verify_member_signature`
/// at pool load (`pool_from_graph_with_speaker` / prove). That broke Task 8's
/// fold→solve path while Task 6 only inspected in-graph typed recovery.
fn claim_memento_with_contract_name(
    minted_bytes: Vec<u8>,
    contract_name: &str,
) -> Result<ClaimContractMemento, FeedError> {
    let mut envelope: Json =
        serde_json::from_slice(&minted_bytes).map_err(|e| FeedError::Mint {
            what: "claim_memento_with_contract_name",
            detail: format!("minted bytes are not JSON: {e}"),
        })?;
    let header = envelope
        .get_mut("header")
        .and_then(Json::as_object_mut)
        .ok_or_else(|| FeedError::Mint {
            what: "claim_memento_with_contract_name",
            detail: "minted envelope missing header object".into(),
        })?;
    let stamped = if !header.contains_key("contractName") {
        header.insert(
            "contractName".to_string(),
            Json::String(contract_name.to_string()),
        );
        true
    } else {
        false
    };
    if stamped {
        // Spec R2: signature covers JCS({header, metadata}). Re-sign so pool
        // load accepts these members (same seed as mint_contract_with_body_cid).
        let header_json = envelope
            .get("header")
            .cloned()
            .ok_or_else(|| FeedError::Mint {
                what: "claim_memento_with_contract_name",
                detail: "header missing after stamp".into(),
            })?;
        let metadata_json = envelope
            .get("metadata")
            .cloned()
            .ok_or_else(|| FeedError::Mint {
                what: "claim_memento_with_contract_name",
                detail: "minted envelope missing metadata object".into(),
            })?;
        let signing_value = json!({
            "header": header_json,
            "metadata": metadata_json,
        });
        let signing_canonical = encode_jcs(json_to_cvalue(&signing_value)?.as_ref());
        let signature = ed25519_sign_string(&FEED_SIGNER_SEED, signing_canonical.as_bytes());
        let signer = ed25519_pubkey_string(&FEED_SIGNER_SEED);
        let env_obj = envelope
            .get_mut("envelope")
            .and_then(Json::as_object_mut)
            .ok_or_else(|| FeedError::Mint {
                what: "claim_memento_with_contract_name",
                detail: "minted envelope missing envelope object".into(),
            })?;
        env_obj.insert("signature".to_string(), Json::String(signature));
        env_obj.insert("signer".to_string(), Json::String(signer));
    }
    // Re-JCS the full envelope so member bytes stay order-stable.
    let bytes = encode_jcs(json_to_cvalue(&envelope)?.as_ref()).into_bytes();
    Ok(ClaimContractMemento::new(bytes))
}

/// Build a single-member graph from one enumerated claim node.
///
/// Aligns with mint's `kind="contract"` path: body slots from the IR row
/// when present (post vs inv preserved), else inv from the fact payload;
/// unique contract name from IR `name` or span locus; warrants from the
/// fact memento / IR sourceWarrants.
pub fn graph_from_fact(fact: &Fact) -> Result<ProofGraph, FeedError> {
    let payload_formula = serde_json::to_value(fact.payload()).map_err(|e| FeedError::Mint {
        what: "graph_from_fact",
        detail: format!("IrFormula serialize: {e}"),
    })?;
    let contract_name = contract_name_for_fact(fact);

    // Prefer full IR slots (preserves post vs inv). Fall back to inv-only
    // payload when the tree node has no IR row (older kit / thin audit).
    let slots: Vec<(&str, Json)> = match fact.ir_row().map(slots_from_ir_row) {
        Some(from_ir) if !from_ir.is_empty() => from_ir,
        _ => vec![("inv", payload_formula)],
    };

    let (warrant_jsons, warrants) = warrants_for_fact(fact)?;
    // Assertion contracts (kind=contract / inv-only claims): default from kind.
    let extras = match fact.ir_row() {
        Some(ir) => {
            let (formals, formals_present) = formals_from_ir_row(ir);
            let (eligible, reason) = body_policy_from_ir(ir);
            ClaimExtras {
                emit_empty_formals: formals_present && formals.is_empty(),
                formals,
                formal_sorts: formal_sorts_from_ir_row(ir)?,
                bridge_source_symbol: bridge_from_ir_row(ir),
                out_binding: out_binding_from_ir_row(ir),
                body_discharge_eligible: eligible,
                body_discharge_refusal_reason: reason,
                proofir_provenance: None,
            }
        }
        None => ClaimExtras::default(),
    };

    let mut graph = ProofGraph::new();
    let provenance_variants = fact
        .ir_row()
        .map(proofir_provenance_variants)
        .transpose()?
        .unwrap_or_else(|| vec![None]);
    for proofir_provenance in provenance_variants {
        let mut variant_extras = extras.clone();
        variant_extras.proofir_provenance = proofir_provenance;
        push_claim_with_slots(
            &mut graph,
            &contract_name,
            slots.clone(),
            warrants.clone(),
            variant_extras,
        )?;
    }
    // Co-member source-mementos (mint parity) — editor locus map keys.
    push_source_mementos_from_warrants(&mut graph, &warrant_jsons, &contract_name)?;
    Ok(graph)
}

/// Returns (JSON warrants for source co-members, CValue warrants for claim slots).
fn warrants_for_fact(fact: &Fact) -> Result<(Vec<Json>, Vec<Arc<CValue>>), FeedError> {
    if let Some(ir) = fact.ir_row() {
        if let Some(arr) = ir
            .get("sourceWarrants")
            .or_else(|| ir.get("source_warrants"))
            .and_then(Json::as_array)
        {
            if !arr.is_empty() {
                let mut cvals = Vec::with_capacity(arr.len());
                for w in arr {
                    cvals.push(json_to_cvalue(w)?);
                }
                return Ok((arr.clone(), cvals));
            }
        }
    }
    let memento_json = fact.source_memento().to_json();
    let cval = json_to_cvalue(&memento_json)?;
    Ok((vec![memento_json], vec![cval]))
}

/// Build a graph fragment from one enumerated universe (function-contract).
///
/// Member key is the memento's `function_name` (Task 1 stamps the batch
/// `name`, e.g. `mathy::add::callable`, `len::builtin-universe`). When the
/// wire audit carries the full IR row, body slots + formals + bridge match
/// mint's function-contract construction. Otherwise fall back to a pre-only
/// `true` shell so name identity still folds.
pub fn graph_from_universe(u: &Universe) -> Result<ProofGraph, FeedError> {
    let name = u.source_memento().function_name.clone();
    if name.is_empty() {
        return Err(FeedError::Incomplete {
            what: "graph_from_universe",
            detail: "Universe memento.function_name is empty; Task 1 stamps \
                     batch function-contract `name` onto function_name"
                .into(),
        });
    }

    let mut graph = ProofGraph::new();

    // #3901: never mint empty provenance. Prefer IR warrants; fall back to
    // the universe's self-locating memento (same law as graph_from_fact).
    let (warrant_jsons, warrants) = warrants_for_universe(u)?;

    if let Some(ir) = u.ir_row() {
        let mut slots = slots_from_ir_row(ir);
        if slots.is_empty() {
            // IR without body still needs a slot; use payload post if any.
            if let Some(payload) = u.payload() {
                slots.push(("post", payload.clone()));
            } else {
                slots.push(("pre", true_formula()));
            }
        }
        let (formals, formals_present) = formals_from_ir_row(ir);
        // Function-contracts: kind-derived default eligible; IR can refuse.
        let (eligible, reason) = body_policy_from_ir(ir);
        let extras = ClaimExtras {
            emit_empty_formals: formals_present && formals.is_empty(),
            formals,
            formal_sorts: formal_sorts_from_ir_row(ir)?,
            bridge_source_symbol: bridge_from_ir_row(ir),
            out_binding: out_binding_from_ir_row(ir),
            body_discharge_eligible: eligible,
            body_discharge_refusal_reason: reason,
            proofir_provenance: None,
        };
        push_claim_with_slots(&mut graph, &name, slots, warrants, extras)?;
        push_source_mementos_from_warrants(&mut graph, &warrant_jsons, &name)?;
        return Ok(graph);
    }

    // No IR row: name shell only — never body-discharge eligible (no policy).
    // Still carry memento warrants (provenance hole closed).
    let shell_extras = ClaimExtras {
        body_discharge_eligible: false,
        body_discharge_refusal_reason: Some(
            "feed_from_tree: universe shell without IR row is not body-discharge eligible".into(),
        ),
        ..ClaimExtras::default()
    };
    let slots = if let Some(payload) = u.payload() {
        vec![("post", payload.clone())]
    } else {
        vec![("pre", true_formula())]
    };
    push_claim_with_slots(&mut graph, &name, slots, warrants, shell_extras)?;
    push_source_mementos_from_warrants(&mut graph, &warrant_jsons, &name)?;
    Ok(graph)
}

/// Fold the full claim walk (facts + universes) into one graph.
///
/// Walk: source_files → functions → call_sites → (universe? + assertions → facts).
/// Each node becomes a fragment via `graph_from_*`; `ProofGraph::feed` merges.
pub fn fold_claim_tree(kit: &Kit, workspace_root: &Path) -> Result<ProofGraph, FeedError> {
    let mut g = ProofGraph::empty();
    for file in kit.source_files(workspace_root)? {
        for function in file.functions()? {
            for site in function.call_sites()? {
                if let Some(u) = site.universe()? {
                    g = g.feed(graph_from_universe(&u)?);
                }
                for assertion in site.assertions()? {
                    for fact in assertion.facts()? {
                        g = g.feed(graph_from_fact(&fact)?);
                    }
                }
            }
        }
    }
    Ok(g)
}

/// Brief alias for `fold_claim_tree`.
///
/// `speaker` is the typed identity the caller will stamp at pool intake via
/// [`crate::orchestrate::pool_from_graph_with_speaker`] — the graph returns
/// content only (no second attribution map on members). Pass the same
/// `Speaker` through fold and load so client vs vendor roles stay coherent
/// for multi-speaker merges (first-writer-wins on `member_speaker`).
pub fn fold_project(
    kit: &Kit,
    workspace_root: &Path,
    speaker: Option<&Speaker>,
) -> Result<ProofGraph, FeedError> {
    // Attribution is a pool-intake fact, not a graph field. The speaker is
    // accepted here so the walk face types match the load door; stamping
    // happens in `pool_from_graph_with_speaker`.
    let _ = speaker;
    fold_claim_tree(kit, workspace_root)
}

#[cfg(test)]
mod json_to_cvalue_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn json_to_cvalue_accepts_i64_and_u64_integers() {
        let i = json_to_cvalue(&json!(42)).expect("i64");
        assert_eq!(
            encode_jcs(i.as_ref()),
            encode_jcs(CValue::integer(42).as_ref())
        );
        // u64 that fits i128 but not i64
        let big = u64::MAX;
        let u = json_to_cvalue(&Json::Number(serde_json::Number::from(big))).expect("u64");
        assert_eq!(
            encode_jcs(u.as_ref()),
            encode_jcs(CValue::integer(i128::from(big)).as_ref())
        );
    }

    #[test]
    fn json_to_cvalue_refuses_float_with_typed_incomplete() {
        let err = json_to_cvalue(&json!(3.14)).expect_err("float must refuse");
        match err {
            FeedError::Incomplete { what, detail } => {
                assert_eq!(what, "json_to_cvalue");
                assert!(
                    detail.contains("non-integer") && detail.contains("3.14"),
                    "expected loud non-integer refusal, got: {detail}"
                );
            }
            other => panic!("expected FeedError::Incomplete, got {other}"),
        }
    }

    #[test]
    fn json_to_cvalue_refuses_nested_float_in_formula() {
        let formula = json!({
            "kind": "atomic",
            "name": "eq",
            "args": [{"kind": "const", "value": 1.5}]
        });
        let err = json_to_cvalue(&formula).expect_err("nested float");
        assert!(
            matches!(
                err,
                FeedError::Incomplete {
                    what: "json_to_cvalue",
                    ..
                }
            ),
            "got {err}"
        );
    }
}

/// #3901 silent-loss instruments at the feed→prove_from_kit boundary.
///
/// Axes:
///   R_formal_sorts_dropped — IR formalSorts must reach the claim member
///   R_universe_empty_warrants — bare / warrant-less IR must not mint empty
///     provenance (fall back to self-locating memento)
///   R_claim_envelope_failopen_number — mint/feed share refuse door
///     (`sugar_canonicalizer::json_to_value`); claim-envelope must not
///     float→string / float→null while feed refuses (see also
///     sugar-canonicalizer dual_number_encoder_3901_tests)
#[cfg(test)]
mod silent_loss_3901_tests {
    use super::*;
    use libsugar::core::{SourceMemento, SrcSpan};
    use serde_json::json;
    use sugar_proof_envelope::typed_member::Member;

    fn test_memento(function_name: &str) -> SourceMemento {
        SourceMemento {
            file: "fixture.py".into(),
            function_name: function_name.into(),
            span: SrcSpan {
                start_line: 1,
                start_col: 0,
                end_line: 2,
                end_col: 0,
            },
            param_names: vec!["x".into()],
            source_cid: "blake3-512:feed-test-source".into(),
            template_cid: "blake3-512:feed-test-template".into(),
        }
    }

    fn first_contract(graph: &ProofGraph) -> sugar_proof_envelope::typed_member::ContractMember {
        for (cid, member_res) in graph.typed_members_iter() {
            let member = member_res.unwrap_or_else(|e| panic!("typed member {cid}: {e}"));
            if let Member::Contract(c) = member.as_ref() {
                return c.clone();
            }
        }
        panic!("expected at least one contract member");
    }

    /// R_formal_sorts_dropped: IR formalSorts must not be hardcoded away.
    #[test]
    fn graph_from_universe_carries_formal_sorts_from_ir() {
        let ir = json!({
            "kind": "function-contract",
            "name": "mathy::add::callable",
            "formals": ["a", "b"],
            "formalSorts": [
                {"kind": "primitive", "name": "Int"},
                {"kind": "primitive", "name": "Int"}
            ],
            "post": {"kind": "atomic", "name": "true", "args": []},
            "bridgeSourceSymbol": "call:add",
            "bodyDischargeEligible": true
        });
        let u = Universe::for_feed_test(test_memento("mathy::add::callable"), Some(ir), None);
        let graph = graph_from_universe(&u).expect("graph_from_universe");
        let c = first_contract(&graph);
        let sorts = c.formal_sorts.as_ref().unwrap_or_else(|| {
            panic!(
                "R_formal_sorts_dropped=1 — formalSorts present on IR but absent on \
                 feed claim member (name={}). Replacement: ClaimExtras.formal_sorts \
                 from formal_sorts_from_ir_row into MintContractArgs.",
                c.contract_name
            )
        });
        assert_eq!(
            sorts.len(),
            2,
            "R_formal_sorts_dropped: expected 2 formalSorts, got {sorts:?}"
        );
        assert_eq!(sorts[0]["kind"], json!("primitive"));
        assert_eq!(sorts[0]["name"], json!("Int"));
        assert_eq!(
            c.formals.as_ref().map(|f| f.as_slice()),
            Some(["a".to_string(), "b".to_string()].as_slice())
        );
        eprintln!(
            "R_formal_sorts_dropped=0 — name={} formal_sorts={}",
            c.contract_name,
            sorts.len()
        );
    }

    /// R_universe_empty_warrants: IR omitting sourceWarrants must still seal
    /// with memento provenance (never empty sourceWarrants).
    #[test]
    fn graph_from_universe_falls_back_to_memento_when_ir_omits_warrants() {
        let ir = json!({
            "kind": "function-contract",
            "name": "shell::fn::callable",
            "formals": ["x"],
            "formalSorts": [{"kind": "primitive", "name": "Int"}],
            "post": {"kind": "atomic", "name": "true", "args": []}
            // deliberately no sourceWarrants
        });
        let u = Universe::for_feed_test(test_memento("shell::fn::callable"), Some(ir), None);
        let graph = graph_from_universe(&u).expect("graph_from_universe");
        let c = first_contract(&graph);
        let warrants = c.source_warrants.as_ref().unwrap_or_else(|| {
            panic!(
                "R_universe_empty_warrants=1 — IR omitted sourceWarrants and feed \
                 minted empty provenance (name={}). Replacement: warrants_for_universe \
                 memento fallback.",
                c.contract_name
            )
        });
        assert!(
            !warrants.is_empty(),
            "R_universe_empty_warrants=1 — sourceWarrants present but empty on {name}",
            name = c.contract_name
        );
        // Co-member source-memento must exist for locus map keys.
        let source_members = graph
            .typed_members_iter()
            .filter(|(_, m)| {
                matches!(
                    m.as_ref().map(|mm| mm.as_ref()),
                    Ok(Member::SourceMemento(_))
                )
            })
            .count();
        assert!(
            source_members >= 1,
            "R_universe_empty_warrants: expected ≥1 source-memento co-member, got 0"
        );
        eprintln!(
            "R_universe_empty_warrants=0 — name={} warrants={} sources={}",
            c.contract_name,
            warrants.len(),
            source_members
        );
    }

    /// Bare shell (no IR row) must also carry memento warrants.
    #[test]
    fn graph_from_universe_shell_without_ir_carries_memento_warrants() {
        let u = Universe::for_feed_test(test_memento("bare::shell::callable"), None, None);
        let graph = graph_from_universe(&u).expect("shell graph_from_universe");
        let c = first_contract(&graph);
        let warrants = c.source_warrants.as_ref().unwrap_or_else(|| {
            panic!(
                "R_universe_empty_warrants=1 — bare shell sealed with no warrants \
                 (name={}). Replacement: warrants_for_universe memento fallback.",
                c.contract_name
            )
        });
        assert!(
            !warrants.is_empty(),
            "bare shell must not mint empty provenance: {name}",
            name = c.contract_name
        );
        eprintln!(
            "R_universe_empty_warrants=0 (shell) — name={} warrants={}",
            c.contract_name,
            warrants.len()
        );
    }

    /// R_body_discharge_default_ignores_kind: feed defaults must track
    /// [`body_discharge_default_for_kind`] — assertion IR without directive
    /// is ineligible; function-contract IR without directive is eligible.
    #[test]
    fn body_discharge_default_tracks_ir_kind() {
        use sugar_ir_types::IrFormula;

        // kind=contract, no bodyDischargeEligible → ineligible
        let true_atom = json!({"kind": "atomic", "name": "true", "args": []});
        let payload: IrFormula = serde_json::from_value(true_atom.clone()).expect("true IrFormula");
        let fact_ir = json!({
            "kind": "contract",
            "name": "assert_at_locus",
            "inv": true_atom
        });
        let fact = Fact::for_feed_test(test_memento("assert_at_locus"), payload, Some(fact_ir));
        let fact_graph = graph_from_fact(&fact).expect("graph_from_fact");
        let fact_c = first_contract(&fact_graph);
        assert_eq!(
            fact_c.body_discharge_eligible,
            Some(false),
            "R_body_discharge_default_ignores_kind=1 — feed fact (kind=contract) \
             without directive must seal bodyDischargeEligible=false (got {:?}). \
             Replacement: body_policy_from_ir → body_discharge_default_for_kind.",
            fact_c.body_discharge_eligible
        );

        // kind=function-contract, no directive → eligible (omitted true)
        let u_ir = json!({
            "kind": "function-contract",
            "name": "mathy::add::callable",
            "formals": ["a"],
            "formalSorts": [{"kind": "primitive", "name": "Int"}],
            "post": {"kind": "atomic", "name": "true", "args": []}
        });
        let u = Universe::for_feed_test(test_memento("mathy::add::callable"), Some(u_ir), None);
        let u_graph = graph_from_universe(&u).expect("graph_from_universe");
        let u_c = first_contract(&u_graph);
        // true is omitted from metadata → None means eligible
        assert!(
            u_c.body_discharge_eligible.is_none() || u_c.body_discharge_eligible == Some(true),
            "R_body_discharge_default_ignores_kind=1 — function-contract without \
             directive must be eligible (omitted or true), got {:?}",
            u_c.body_discharge_eligible
        );

        eprintln!(
            "R_body_discharge_default_ignores_kind=0 — feed fact→false, \
             function-contract→eligible"
        );
    }

    /// R_claim_envelope_failopen_number: feed and the shared door must agree
    /// on integer trees and both refuse floats (mint uses the same door).
    #[test]
    fn feed_and_shared_door_agree_on_integers_and_refuse_floats() {
        let tree = json!({
            "kind": "atomic",
            "name": "eq",
            "args": [
                {"kind": "const", "value": 42},
                {"kind": "const", "value": 0}
            ]
        });
        let feed = json_to_cvalue(&tree).expect("feed integers");
        let door = json_to_value(&tree).expect("shared door integers");
        assert_eq!(
            encode_jcs(feed.as_ref()),
            encode_jcs(door.as_ref()),
            "R_claim_envelope_failopen_number: feed must byte-match \
             sugar_canonicalizer::json_to_value on integer trees"
        );

        let float = json!({"value": 1.5});
        let feed_err = json_to_cvalue(&float).expect_err("feed float");
        assert!(
            matches!(
                feed_err,
                FeedError::Incomplete {
                    what: "json_to_cvalue",
                    ..
                }
            ),
            "feed must refuse float: {feed_err}"
        );
        let door_err = json_to_value(&float).expect_err("door float");
        assert!(
            door_err.to_string().contains("non-integer"),
            "shared door must refuse float: {door_err}"
        );
        eprintln!(
            "R_claim_envelope_failopen_number=0 — feed≡json_to_value on ints; both refuse float"
        );
    }
}
