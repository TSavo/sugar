// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Derive `sugar_linker::LinkerInputs` from a `MementoPool`'s REAL bridge
// data (sugar#3857). Companion to `orchestrate.rs`'s `Orchestrate::solve`,
// whose own doc comment records the finding this closes: `sugar_linker::bind`
// / `LinkerInputs` had zero production call sites, because production
// cross-kit resolution runs through an entirely different mechanism -- kit-
// pinned bridges (`bridges_by_symbol`/`bridges_by_callsite` in
// `sugar_verifier::types::MementoPool`) -- where an unresolved call is the
// ABSENCE of a bridge, not a typed `LinkerCallEdge` carrying an `Unbound`
// state.
//
// # Mechanism: how absence becomes a typed edge
//
// The pool never records "this call failed to resolve" as its own fact.
// What it records is asymmetric:
//
//   - A CALL SITE is enumerated independently of whether it resolved.
//     `sugar_verifier::enumerate_callsites::run` walks every contract
//     member's `pre`/`post`/`inv` for ctor terms naming a bridge symbol, AND
//     separately walks each contract's own per-occurrence `panicLoci`/
//     `effectLoci` entries (`{callee, file, line}`) -- these exist on the
//     CALLING contract regardless of whether a bridge for `callee` was ever
//     minted. Each occurrence becomes a `CallSite` with `bridge_target_cid:
//     Option<MementoCid>`.
//   - A BRIDGE is a separate, independently-inserted memento
//     (`MemberKind::Bridge`) that `load_all_proofs` indexes into
//     `bridges_by_symbol` / `bridges_by_callsite` ONLY if one was minted and
//     loaded for that symbol/callsite. `enumerate_callsites` looks the
//     occurrence up in that index; when nothing answers, `bridge_target_cid`
//     stays `None` and the CallSite is still emitted (see
//     `enumerate_callsites::callsite_from_panic_locus`'s
//     "surfacing an undecidable panic callsite" warning on a `None` bridge).
//
// So "unresolved in production" is not a marked state anywhere in the pool;
// it is the shape you get for free when you enumerate call sites and find
// `bridge_target_cid == None`. This module's whole job is to carry that
// `Option` through, unchanged, into `LinkerCallEdge.target_contract_cid`:
//
//   - `Some(cid)`  -> `EdgeTarget::Bound(cid)` in `sugar_linker::bind`: the
//     pool already resolved this call to a specific contract member: bind
//     re-checks that member exists in the derived contract union and mints a
//     `BoundContractCid`.
//   - `None`       -> `EdgeTarget::Unbound(ImportSignature)`, carrying the
//     call's bare symbol (`CallSite.bridge_ir_name`, e.g. `"kit:target_fn"`)
//     as an UNQUALIFIED `Symbol` (no kit is recoverable from the pool's
//     bridge model, only from the linker's own `<kit>:<name>` convention).
//     `bind`'s cross-kit join (`SymbolTable::resolve`) only ever inserts
//     QUALIFIED `Symbol`s into its `name_kit_index` (from
//     `LinkerContract::kit`/`name`, see `Symbol::qualified` in
//     `sugar-linker/src/lib.rs`), so an unqualified symbol derived here can
//     never key a hit there. The absence in the pool therefore becomes,
//     deterministically, `LinkerErrorKind::UnresolvedSymbol` at `bind` time --
//     a TYPED edge Outcome::LinkError can name, in place of the pool's own
//     silence.
//
// # Contracts
//
// `LinkerContract`s are derived one-for-one from the pool's contract members
// (`MementoPool::contract_members_with_bodies`), which already resolves the
// v1.1/v1.2 body shape ladder. `kit` has no equivalent in the pool's model
// (a contract memento does not carry a kit qualifier the way a
// `sugar-linkerd` daemon session's per-kit stream would) so it is left
// empty; this is sound rather than a gap, because the only place
// `LinkerContract::kit` participates in resolution is
// `Symbol::qualified(kit, name)` in `derive_link_bundle_inner`'s
// `name_kit_index`, and every `Symbol` this module derives for a call edge
// is unqualified (see above) -- so a real kit string here would change
// nothing observable; the CID-keyed `contracts_by_cid` index (which IS
// exercised, for the `Some(cid)` / `Bound` arm) is keyed by `contract_cid`
// alone.

use std::collections::HashSet;

use sugar_ir_types::{IrFormula, Sort};
use sugar_linker::{CallSiteLocus, LinkerCallEdge, LinkerContract, LinkerInputs};
use sugar_proof_envelope::MementoPool;
use sugar_verifier::enumerate_callsites;

/// A contract member's body carried a field this derivation could not decode
/// (sugar#3869). Malformed contract data is a typed load error naming the
/// contract, NEVER a silently-dropped element: a dropped `Sort` or
/// `IrFormula` would let bad input achieve success-with-omission -- a
/// false-green/incomplete-load vector in the compiler substrate.
#[derive(Debug, thiserror::Error)]
#[error(
    "derive_linker_inputs: contract {contract_name:?} ({contract_cid}): malformed {field}: {detail}"
)]
pub struct MalformedContractField {
    pub contract_name: String,
    pub contract_cid: String,
    pub field: &'static str,
    pub detail: String,
}

/// Derive `LinkerInputs` from the pool's own contract union and its
/// enumerated call sites, so beat 1 of `Orchestrate::solve` sees production
/// edges -- including edges the pool never resolved a bridge for.
///
/// A MISSING optional field (`formals`, `formalSorts`, `pre`, `post`) is a
/// legitimate body shape and derives to empty/`None`; a PRESENT field that
/// fails to decode is a typed `Err` (sugar#3869), never an omission.
pub fn derive_linker_inputs(pool: &MementoPool) -> Result<LinkerInputs, MalformedContractField> {
    let contracts: Vec<LinkerContract> = pool
        .contract_members_with_bodies()
        .map(|(cid, body)| {
            let contract_name = body
                .get("contractName")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_string();
            let malformed = |field: &'static str, detail: String| MalformedContractField {
                contract_name: contract_name.clone(),
                contract_cid: cid.to_string(),
                field,
                detail,
            };
            let formals: Vec<String> = body
                .get("formals")
                .and_then(|v| v.as_array())
                .map(|items| {
                    items
                        .iter()
                        .map(|item| {
                            item.as_str().map(str::to_string).ok_or_else(|| {
                                malformed("formals entry", format!("expected a string, got {item}"))
                            })
                        })
                        .collect::<Result<_, _>>()
                })
                .transpose()?
                .unwrap_or_default();
            let formal_sorts: Vec<Sort> = body
                .get("formalSorts")
                .and_then(|v| v.as_array())
                .map(|items| {
                    items
                        .iter()
                        .map(|item| {
                            serde_json::from_value::<Sort>(item.clone())
                                .map_err(|e| malformed("formalSorts entry", format!("{e}: {item}")))
                        })
                        .collect::<Result<_, _>>()
                })
                .transpose()?
                .unwrap_or_default();
            let pre_json = body
                .get("pre")
                .map(|v| {
                    serde_json::from_value::<IrFormula>(v.clone())
                        .map_err(|e| malformed("pre IrFormula", format!("{e}: {v}")))
                })
                .transpose()?;
            let post_json = body
                .get("post")
                .map(|v| {
                    serde_json::from_value::<IrFormula>(v.clone())
                        .map_err(|e| malformed("post IrFormula", format!("{e}: {v}")))
                })
                .transpose()?;
            Ok(LinkerContract {
                name: contract_name,
                // See module doc: never exercised by resolution, only by
                // `Symbol::qualified`, which this module never constructs.
                kit: String::new(),
                contract_cid: cid.to_string().into(),
                pre_json,
                post_json,
                formals,
                formal_sorts,
                euf_coordinate: None,
            })
        })
        .collect::<Result<_, _>>()?;

    // Only contract CIDs actually present in the derived union may become a
    // `Bound` edge target below. A `CallSite.bridge_target_cid` pointing at a
    // pool member that resolved to something other than a contract (or that
    // was, impossibly, dropped between enumeration and here) must not be
    // asserted as bound -- fall back to the unqualified-symbol path, which
    // `bind` will honestly refuse as `UnresolvedSymbol` rather than silently
    // trusting an unverified CID.
    let known_contract_cids: HashSet<&str> =
        contracts.iter().map(|c| c.contract_cid.as_str()).collect();

    let call_edges: Vec<LinkerCallEdge> = enumerate_callsites::run(pool)
        .into_iter()
        .map(|cs| {
            // A callsite with NO attributed contract body must still derive
            // an edge (gitar on #3866): dropping it here would re-open the
            // silent-vacuous gap one layer down -- an unbridged callee on an
            // unattributed callsite would vanish without an UnresolvedSymbol.
            // An empty source CID is bind-tolerated (resolution keys on the
            // TARGET symbol); the edge still types the absence.
            let source_contract_cid = cs
                .property_cid
                .map(|cid| cid.to_string())
                .unwrap_or_default()
                .into();
            let target_contract_cid = cs
                .bridge_target_cid
                .map(|cid| cid.to_string())
                .filter(|cid| known_contract_cids.contains(cid.as_str()))
                .map(Into::into);
            let call_site_locus = cs.file.map(|file| CallSiteLocus {
                column: cs.source_column,
                file,
                line: cs.line,
            });
            LinkerCallEdge {
                source_contract_cid,
                target_contract_cid,
                target_symbol: cs.bridge_ir_name.as_str().into(),
                call_site_locus,
                import_signature: None,
            }
        })
        .collect();

    Ok(LinkerInputs {
        contracts,
        call_edges,
    })
}
