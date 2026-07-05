// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 3: resolve_target. Look up the CallSite's bridge.targetCid in
// the pool; return the target contract memento's `pre` formula as the
// discharge target. Mirrors .../verifier/resolve_target.cpp.
//
// Forward-pin gate (BridgeDeclaration.ConsequentBundlePinned, NORMATIVE):
// after locating the consequent contract member, refuse to consume it
// unless its containing `.proof` bundle CID matches the bridge's
// `targetProofCid`. See protocol/specs/2026-04-30-ir-formal-grammar.md
// § "Bridge target pinning: the shim-poisoning vector".

use serde_json::{json, Value as Json};
use tracing::{debug, warn};

use crate::types::{BridgePin, CallSite, MemberKind, MementoPool, ResolvedProperty};

pub fn run(cs: &CallSite, pool: &MementoPool) -> Result<ResolvedProperty, String> {
    debug!(
        bridge = %cs.bridge_ir_name,
        target_cid = ?cs.bridge_target_cid,
        "resolve_target: resolving bridge target contract"
    );
    let Some(target_cid) = cs.bridge_target_cid.as_ref() else {
        warn!(
            bridge = %cs.bridge_ir_name,
            "resolve_target: callsite has no targetContractCid"
        );
        return Err(format!(
            "NoBridgeTarget: callsite {} has no targetContractCid",
            cs.bridge_ir_name
        ));
    };
    let env = pool.stored_member(target_cid).ok_or_else(|| {
        warn!(
            bridge = %cs.bridge_ir_name,
            target_cid = %target_cid,
            "resolve_target: bridge target CID not in pool"
        );
        format!("bridge target CID {} not in pool", target_cid)
    })?;
    if env.kind() != MemberKind::Contract {
        warn!(
            bridge = %cs.bridge_ir_name,
            target_cid = %target_cid,
            "resolve_target: target memento is not a contract"
        );
        return Err("target memento is not a contract memento".into());
    }
    // Shape-agnostic body: v1.2 layered -> `header`, v1.1 flat -> `evidence.body`.
    let verified = pool
        .verified_contract_by_cid(target_cid)
        .expect("target member kind was checked above");
    let body = verified
        .body()
        .filter(|v| v.is_object())
        .cloned()
        .ok_or("contract memento has no body/header object")?;

    // Forward pin: BridgeDeclaration.ConsequentBundlePinned.
    //
    //     ∀b: BridgeDeclaration, P: ProofBundle →
    //       AcceptedAsConsequentFor(P, b) ⇒ Cid(P) = b.targetProofCid
    //
    // If the bridge pins a target proof CID, the contract member we just
    // resolved MUST come from that bundle. Bundles whose contract
    // members happen to share `targetContractCid` MUST NOT be
    // substituted for the pinned bundle. See protocol/specs/2026-04-30-
    // ir-formal-grammar.md § "Bridge target pinning: the shim-poisoning
    // vector".
    match &cs.bridge_pin {
        BridgePin::Cross(expected_bundle) => {
            debug!(
                bridge = %cs.bridge_ir_name,
                pinned_bundle = %expected_bundle,
                "resolve_target: enforcing ConsequentBundlePinned"
            );
            let bundle_members = pool.bundle_members.get(expected_bundle).ok_or_else(|| {
                warn!(
                    bridge = %cs.bridge_ir_name,
                    pinned_bundle = %expected_bundle,
                    "resolve_target: pinned bundle not in pool (BridgeTargetProofCidMismatch)"
                );
                format!(
                    "BridgeTargetProofCidMismatch: pinned bundle {} not in pool",
                    expected_bundle
                )
            })?;
            if !bundle_members.contains(target_cid) {
                warn!(
                    bridge = %cs.bridge_ir_name,
                    target_cid = %target_cid,
                    pinned_bundle = %expected_bundle,
                    "resolve_target: pin mismatch: contract not in pinned bundle"
                );
                return Err(format!(
                    "BridgeTargetProofCidMismatch: contract {} is not a member of pinned bundle {}",
                    target_cid, expected_bundle
                ));
            }
        }
        BridgePin::SelfPinned => {
            // Self-pinned: a bridge with no `targetProofCid` commits to a
            // target that is a co-member of its OWN bundle (it was minted
            // into the same `.proof` as its target, by the same mint run; it
            // cannot reference its own not-yet-computed bundle CID). Enforce
            // that co-membership. This is NOT a back-compat escape hatch:
            // there is no unenforced path. A cross-bundle target that arrives
            // with no pin (e.g. a same-named dependency contract trying to
            // pose as the local one) is refused here.
            let self_bundle = cs.bridge_self_bundle_cid.as_ref().ok_or_else(|| {
                format!(
                    "BridgeSelfPinUnresolvable: bridge {} has no targetProofCid and no known \
                     source bundle, so same-bundle co-membership cannot be enforced",
                    cs.bridge_ir_name
                )
            })?;
            let bundle_members = pool.bundle_members.get(self_bundle).ok_or_else(|| {
                format!(
                    "BridgeSelfPinUnresolvable: self bundle {} of bridge {} not in pool",
                    self_bundle, cs.bridge_ir_name
                )
            })?;
            if !bundle_members.contains(target_cid) {
                return Err(format!(
                    "BridgeTargetProofCidMismatch: self-pinned bridge {} target {} is not a \
                     co-member of its own bundle {}",
                    cs.bridge_ir_name, target_cid, self_bundle
                ));
            }
        }
    }

    // A body-derived contract emits its precondition as a BARE predicate over
    // a named formal (e.g. `encoding >= 0`). The discharge stages
    // (`instantiate`, `build_implication_obligation`) require it quantified, so
    // the actual passed at the callsite can be substituted for the formal.
    // Synthesize `forall (formal). pre` here from the contract's own
    // `formals`/`formalSorts`. Single-formal: the callsite model tracks a
    // single arg term, so we bind the first formal. An already-quantified pre
    // (hand-built bundles) passes through untouched.
    let ir_formula = body
        .get("pre")
        .cloned()
        .map(|pre| wrap_pre_forall(pre, &body));
    let formal_names = formal_names(&body);
    let formal_sorts = formal_sorts(&body);
    // A target carrying a `formals` array is a body-derived op-contract
    // (body-bearing). The caller must NOT vacuous-pass such a target if its
    // obligation was not reduced + discharged; it must refuse. Surface the
    // marker here, where the body is already in hand.
    //
    // PRESENCE, not non-emptiness, is the marker: a zero-arg body-derived
    // contract carries `formals: []` (a body, no parameters) and is still
    // body-bearing. Gating on `!is_empty()` would let `formals: []` + a
    // non-equation post + no pre slip back into the vacuous-discharge branch.
    // A genuinely non-body-bearing target (e.g. a LIA refinement contract)
    // carries no `formals` key at all, so it stays on the legitimate path.
    let target_is_body_bearing = body.get("formals").and_then(|v| v.as_array()).is_some();
    // A post-only contract whose `post` field is present makes an
    // obligation-carrying claim about its output value. The vacuous discharge
    // shortcut ("no pre => nothing to prove") is NOT legitimate here because
    // the `post` asserts a specific value (e.g. `eq(out, "AAAA")`). If this
    // marker is set the caller MUST NOT emit a vacuous Discharged; it must
    // return Undecidable. The vacuous path is only for truly claim-free
    // targets (no pre AND no post).
    let target_has_post = body.get("post").is_some();
    debug!(
        bridge = %cs.bridge_ir_name,
        target_cid = %target_cid,
        body_bearing = target_is_body_bearing,
        has_pre = ir_formula.is_some(),
        has_post = target_has_post,
        "resolve_target: accepted"
    );
    Ok(ResolvedProperty {
        cid: target_cid.to_string(),
        ir_formula,
        ir_kit_version: String::new(),
        formal_names,
        formal_sorts,
        target_is_body_bearing,
        target_has_post,
    })
}

fn formal_names(body: &Json) -> Vec<String> {
    body.get("formals")
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

fn formal_sorts(body: &Json) -> Vec<Json> {
    body.get("formalSorts")
        .and_then(|v| v.as_array())
        .map(|items| items.to_vec())
        .unwrap_or_default()
}

/// Wrap a bare precondition formula in `forall (firstFormal: sort). pre` so the
/// discharge stages can substitute the callsite's actual for the formal. If the
/// pre is already a `forall`, or the contract carries no `formals`, it is
/// returned unchanged (no double-wrap; nothing to quantify).
fn wrap_pre_forall(pre: Json, body: &Json) -> Json {
    if pre.get("kind").and_then(|v| v.as_str()) == Some("forall") {
        return pre;
    }
    let Some(name) = body
        .get("formals")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())
    else {
        return pre;
    };
    // The formal's sort is already canonical (the lifter emits the canonical
    // primitive set; integers are `Int`). Use it directly; default to `Int`
    // when a contract omits formalSorts.
    let sort = body
        .get("formalSorts")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .cloned()
        .unwrap_or_else(|| json!({"kind": "primitive", "name": "Int"}));
    json!({"kind": "forall", "name": name, "sort": sort, "body": pre})
}
