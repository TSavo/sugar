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
use sugar_canonicalizer::{encode_jcs, Value as CValue};
use sugar_claim_envelope::{mint_contract_with_body_cid, Authoring, MintContractArgs};
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_sign_string, ClaimContractMemento, ContractBody, Ed25519Seed,
    FlatAtom, ProofGraph,
};
use sugar_verifier::Speaker;

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

/// serde_json → canonical Value (same bridge mint / solve_two_reds use).
fn json_to_cvalue(j: &Json) -> Arc<CValue> {
    match j {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => CValue::integer(i128::from(n.as_i64().unwrap_or(0))),
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_cvalue).collect()),
        Json::Object(map) => CValue::object(
            map.iter()
                .map(|(k, v)| (k.clone(), json_to_cvalue(v)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn true_formula() -> Json {
    json!({"kind": "atomic", "name": "true", "args": []})
}

/// Optional IR fields that mint threads onto function-contract / claim members.
struct ClaimExtras {
    formals: Vec<String>,
    /// When IR had an explicit `formals` field (even `[]`), emit empty formals.
    emit_empty_formals: bool,
    bridge_source_symbol: Option<String>,
    out_binding: String,
}

impl Default for ClaimExtras {
    fn default() -> Self {
        Self {
            formals: Vec::new(),
            emit_empty_formals: false,
            bridge_source_symbol: None,
            // Match mint IR default for this kit (`outBinding: "out"`).
            out_binding: "out".into(),
        }
    }
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
        let atom = graph.register_atom(FlatAtom::new(json_to_cvalue(formula)));
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
        let v = json_to_cvalue(formula);
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

    let args = MintContractArgs {
        evidence_term: None,
        formals: extras.formals,
        emit_empty_formals: extras.emit_empty_formals,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: extras.bridge_source_symbol,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants,
        proofir_provenance: None,
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
    graph.push_claim_contract(memento);
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
        let signing_canonical = encode_jcs(&json_to_cvalue(&signing_value));
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
    let bytes = encode_jcs(&json_to_cvalue(&envelope)).into_bytes();
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

    let warrants = warrants_for_fact(fact);
    let extras = fact
        .ir_row()
        .map(|ir| {
            let (formals, formals_present) = formals_from_ir_row(ir);
            ClaimExtras {
                emit_empty_formals: formals_present && formals.is_empty(),
                formals,
                bridge_source_symbol: bridge_from_ir_row(ir),
                out_binding: out_binding_from_ir_row(ir),
            }
        })
        .unwrap_or_default();

    let mut graph = ProofGraph::new();
    push_claim_with_slots(&mut graph, &contract_name, slots, warrants, extras)?;
    Ok(graph)
}

fn warrants_for_fact(fact: &Fact) -> Vec<Arc<CValue>> {
    if let Some(ir) = fact.ir_row() {
        if let Some(arr) = ir
            .get("sourceWarrants")
            .or_else(|| ir.get("source_warrants"))
            .and_then(Json::as_array)
        {
            if !arr.is_empty() {
                return arr.iter().map(json_to_cvalue).collect();
            }
        }
    }
    vec![json_to_cvalue(&fact.source_memento().to_json())]
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
        let warrants = ir
            .get("sourceWarrants")
            .or_else(|| ir.get("source_warrants"))
            .and_then(Json::as_array)
            .map(|arr| arr.iter().map(json_to_cvalue).collect())
            .unwrap_or_default();
        let extras = ClaimExtras {
            emit_empty_formals: formals_present && formals.is_empty(),
            formals,
            bridge_source_symbol: bridge_from_ir_row(ir),
            out_binding: out_binding_from_ir_row(ir),
        };
        push_claim_with_slots(&mut graph, &name, slots, warrants, extras)?;
        return Ok(graph);
    }

    // No IR row: keep a name shell so walk fold still enumerates the universe.
    // pre-only so fact recovery that keys on inv|post does not invent extras.
    if let Some(payload) = u.payload() {
        push_claim_with_slots(
            &mut graph,
            &name,
            vec![("post", payload.clone())],
            Vec::new(),
            ClaimExtras::default(),
        )?;
    } else {
        push_claim_with_slots(
            &mut graph,
            &name,
            vec![("pre", true_formula())],
            Vec::new(),
            ClaimExtras::default(),
        )?;
    }
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
