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
// Speaker attribution is Task 7 (`fold_project`'s speaker is accepted and
// ignored until pool intake stamps first-writer-wins).

use std::path::Path;
use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{encode_jcs, Value as CValue};
use sugar_claim_envelope::{mint_contract_with_body_cid, Authoring, MintContractArgs};
use sugar_proof_envelope::{
    ClaimContractMemento, ContractBody, Ed25519Seed, FlatAtom, ProofGraph,
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
    Mint {
        what: &'static str,
        detail: String,
    },
    #[error(
        "feed_from_tree::{what}: {detail} — \
         replacement: carry the missing field on the tree node or refuse at enumerate"
    )]
    Incomplete {
        what: &'static str,
        detail: String,
    },
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

/// Push one claim-contract member: register body slots, mint layered
/// envelope with bodyCid, `push_claim_contract`.
fn push_claim_with_slots(
    graph: &mut ProofGraph,
    contract_name: &str,
    slots: Vec<(&str, Json)>,
    source_warrants: Vec<Arc<CValue>>,
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
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        bridge_source_symbol: None,
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
        out_binding: "result".into(),
        produced_by: FEED_PRODUCED_BY.into(),
        produced_at: FEED_PRODUCED_AT.into(),
        input_cids: Vec::new(),
        authoring: Authoring::KitAuthor {
            author: FEED_PRODUCED_BY.into(),
            note: Some("feed_from_tree fragment".into()),
        },
        signer_seed: FEED_SIGNER_SEED,
    };

    let minted = mint_contract_with_body_cid(&args, Some(&body_cid)).map_err(|e| FeedError::Mint {
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

/// Re-emit mint bytes with `header.contractName` filled from the contract
/// name (mint already put `header.name`). Preserves all other header fields
/// including `bodyCid` and `sourceWarrants`.
fn claim_memento_with_contract_name(
    minted_bytes: Vec<u8>,
    contract_name: &str,
) -> Result<ClaimContractMemento, FeedError> {
    let mut envelope: Json = serde_json::from_slice(&minted_bytes).map_err(|e| FeedError::Mint {
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
    if !header.contains_key("contractName") {
        header.insert(
            "contractName".to_string(),
            Json::String(contract_name.to_string()),
        );
    }
    // Re-JCS the full envelope so member bytes stay order-stable.
    let bytes = encode_jcs(&json_to_cvalue(&envelope)).into_bytes();
    Ok(ClaimContractMemento::new(bytes))
}

/// Build a single-member graph from one enumerated claim node.
///
/// Same contract member shape mint uses for `kind="contract"` rows: inv
/// formula from the fact payload, source warrants from the fact memento.
pub fn graph_from_fact(fact: &Fact) -> Result<ProofGraph, FeedError> {
    let formula = serde_json::to_value(fact.payload()).map_err(|e| FeedError::Mint {
        what: "graph_from_fact",
        detail: format!("IrFormula serialize: {e}"),
    })?;
    let warrant = fact.source_memento().to_json();
    let contract_name = {
        let name = &fact.source_memento().function_name;
        if name.is_empty() {
            // Stable placeholder when the memento carries no function name;
            // FOL identity for parity is (warrant file, span, formula).
            "feed::fact".to_string()
        } else {
            name.clone()
        }
    };

    let mut graph = ProofGraph::new();
    push_claim_with_slots(
        &mut graph,
        &contract_name,
        vec![("inv", formula)],
        vec![json_to_cvalue(&warrant)],
    )?;
    Ok(graph)
}

/// Build a graph fragment from one enumerated universe (function-contract).
///
/// Member key is the memento's `function_name` (Task 1 stamps the batch
/// `name`, e.g. `mathy::add::callable`, `len::builtin-universe`). Body is
/// pre-only `true` so feed recovery that keys facts on inv|post does not
/// invent extra claim FOL; universe identity is the contract name.
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
    // pre-only: typed-member recovery of inv|post stays empty → no extra facts.
    push_claim_with_slots(&mut graph, &name, vec![("pre", true_formula())], Vec::new())?;
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

/// Brief alias for `fold_claim_tree` (speaker attribution is Task 7).
///
/// `speaker` is accepted and ignored until pool intake stamps speakers
/// (`pool_from_graph_with_speaker` / utterance first-writer-wins).
pub fn fold_project(
    kit: &Kit,
    workspace_root: &Path,
    _speaker: Option<&str>,
) -> Result<ProofGraph, FeedError> {
    // TODO(Task 7): stamp speaker attribution at pool intake; do not invent
    // a second speaker field on members here.
    fold_claim_tree(kit, workspace_root)
}
