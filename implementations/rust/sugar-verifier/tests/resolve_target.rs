// SPDX-License-Identifier: Apache-2.0
//
// Stage 3 (resolve_target) tests. Pins:
//   - looks up the bridge's targetCid in the pool's mementos
//   - kind == "contract" required (fail-closed on other kinds)
//   - reads body.pre as the discharge target
//   - fail-closed when targetCid is not in the pool
//   - fail-closed when the resolved memento has no body
//   - returns the memento's CID in `cid`
//   - forward pin (BridgeDeclaration.ConsequentBundlePinned): when the
//     CallSite carries `bridge_target_proof_cid = Some(...)`, the
//     contract member MUST live in that bundle, else reject
//   - self pin: when `bridge_target_proof_cid = None`, the target MUST be a
//     co-member of the bridge's own bundle (`bridge_self_bundle_cid`), else
//     reject. There is NO unenforced path: every bridge is pinned, either to
//     a named external bundle (Some) or to its own bundle (None).

use serde_json::{json, Value as Json};

use sugar_verifier::{resolve_target, CallSite, MementoCid, MementoPool, StoredMember};

/// Bundle the basic happy-path tests treat as the bridge's own. Registered
/// in `pool_with` and pinned by `callsite_targeting` so a no-`targetProofCid`
/// (self-pinned) callsite resolves against a co-member target.
const SELF_BUNDLE: &str = "self-bundle-under-test";

fn memento_cid(label: &str) -> MementoCid {
    MementoCid::try_parse(label.to_string()).unwrap_or_else(|_| {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(label.as_bytes()))
            .expect("test CID must parse")
    })
}

fn cid_string(label: &str) -> String {
    memento_cid(label).to_string()
}

trait TestPoolInsert {
    fn insert_unanchored_for_tests(&mut self, cid: MementoCid, envelope: Json);
    fn try_insert_unanchored_for_tests(
        &mut self,
        cid: MementoCid,
        envelope: Json,
    ) -> Result<(), String>;
}

impl TestPoolInsert for MementoPool {
    fn insert_unanchored_for_tests(&mut self, cid: MementoCid, envelope: Json) {
        self.try_insert_unanchored_for_tests(cid, envelope)
            .expect("test member must parse");
    }

    fn try_insert_unanchored_for_tests(
        &mut self,
        cid: MementoCid,
        envelope: Json,
    ) -> Result<(), String> {
        let member = StoredMember::from_envelope(cid.clone(), &envelope)
            .map_err(|err| format!("{err:?}"))?;
        self.mementos.insert(cid, member);
        Ok(())
    }
}

fn pool_with(cid: &str, env: Json) -> MementoPool {
    let mut pool = MementoPool::default();
    pool.insert_unanchored_for_tests(memento_cid(cid), env);
    // Co-member of the self bundle: lets self-pinned callsites resolve.
    // Some-pin tests add their own bundle_members and pins on top.
    pool.bundle_members
        .entry(memento_cid(SELF_BUNDLE))
        .or_default()
        .insert(memento_cid(cid));
    pool
}

fn callsite_targeting(target_cid: &str) -> CallSite {
    CallSite {
        bridge_ir_name: "parseInt".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_self_bundle_cid: Some(memento_cid(SELF_BUNDLE)),
        ..Default::default()
    }
}

fn contract_env(pre: Json) -> Json {
    json!({
        "evidence": {
            "kind": "contract",
            "body": {"pre": pre}
        }
    })
}

fn trivial_pre() -> Json {
    json!({"kind": "atomic", "name": "true", "args": []})
}

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------

#[test]
fn resolves_pre_for_contract_memento() {
    let target_cid = "blake3-512:contract1";
    let pre = json!({
        "kind": "forall",
        "name": "n",
        "sort": {"kind": "primitive", "name": "Int"},
        "body": {
            "kind": "atomic", "name": ">", "args": [
                {"kind": "var", "name": "n"},
                {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        }
    });
    let env = json!({
        "evidence": {
            "kind": "contract",
            "body": {"pre": pre.clone()}
        }
    });
    let pool = pool_with(target_cid, env);
    let cs = callsite_targeting(target_cid);
    let r = resolve_target::run(&cs, &pool).expect("resolve");
    assert_eq!(r.cid, cid_string(target_cid));
    assert_eq!(r.ir_formula, Some(pre));
}

#[test]
fn resolves_returns_none_pre_when_contract_has_no_pre() {
    let target_cid = "blake3-512:contract1";
    let env = json!({
        "evidence": {
            "kind": "contract",
            "body": {"post": {"kind": "atomic", "name": "=", "args": []}}
        }
    });
    let pool = pool_with(target_cid, env);
    let cs = callsite_targeting(target_cid);
    let r = resolve_target::run(&cs, &pool).expect("resolve");
    assert!(r.ir_formula.is_none());
}

#[test]
fn resolves_formal_names_and_sorts_for_multi_formal_precondition() {
    let target_cid = "blake3-512:contract1";
    let env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "formals": ["self", "radix"],
                "formalSorts": [
                    {"kind": "primitive", "name": "Self"},
                    {"kind": "primitive", "name": "Int"}
                ],
                "pre": {
                    "kind": "and",
                    "operands": [
                        {"kind": "atomic", "name": ">=", "args": [
                            {"kind": "var", "name": "radix"},
                            {"kind": "const", "value": 2, "sort": {"kind": "primitive", "name": "Int"}}
                        ]},
                        {"kind": "atomic", "name": "<=", "args": [
                            {"kind": "var", "name": "radix"},
                            {"kind": "const", "value": 36, "sort": {"kind": "primitive", "name": "Int"}}
                        ]}
                    ]
                }
            }
        }
    });
    let pool = pool_with(target_cid, env);
    let cs = callsite_targeting(target_cid);
    let r = resolve_target::run(&cs, &pool).expect("resolve");
    assert_eq!(r.formal_names, vec!["self", "radix"]);
    assert_eq!(
        r.formal_sorts,
        vec![
            json!({"kind": "primitive", "name": "Self"}),
            json!({"kind": "primitive", "name": "Int"})
        ]
    );
    assert_eq!(
        r.ir_formula
            .as_ref()
            .and_then(|f| f.get("name"))
            .and_then(|v| v.as_str()),
        Some("self"),
        "legacy wrapper still exposes the first formal for existing paths"
    );
}

// ---------------------------------------------------------------------------
// Fail-closed: bad inputs
// ---------------------------------------------------------------------------

#[test]
fn errors_when_target_cid_not_in_pool() {
    let pool = MementoPool::default();
    let cs = callsite_targeting("blake3-512:nope");
    let r = resolve_target::run(&cs, &pool);
    assert!(r.is_err(), "must fail-closed when target missing");
    let err = format!("{:?}", r.err().unwrap());
    assert!(err.contains("not in pool"));
}

#[test]
fn errors_when_callsite_has_no_target_contract_cid() {
    let pool = MementoPool::default();
    let cs = CallSite {
        bridge_ir_name: "parseInt".into(),
        bridge_target_cid: None,
        ..Default::default()
    };
    let r = resolve_target::run(&cs, &pool);
    assert!(r.is_err(), "missing bridge target must fail closed");
    let err = format!("{:?}", r.err().unwrap());
    assert!(err.contains("NoBridgeTarget"), "got: {err}");
    assert!(err.contains("parseInt"), "got: {err}");
}

#[test]
fn errors_when_target_kind_is_bridge_not_contract() {
    let target_cid = "blake3-512:bridge1";
    let env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {"sourceSymbol": "parseInt"}
        }
    });
    let pool = pool_with(target_cid, env);
    let cs = callsite_targeting(target_cid);
    let r = resolve_target::run(&cs, &pool);
    assert!(r.is_err());
    let err = format!("{:?}", r.err().unwrap());
    assert!(err.contains("not a contract"));
}

#[test]
fn errors_when_target_kind_is_implication() {
    let target_cid = "blake3-512:impl1";
    let env = json!({
        "evidence": {
            "kind": "implication",
            "body": {}
        }
    });
    let pool = pool_with(target_cid, env);
    let cs = callsite_targeting(target_cid);
    let r = resolve_target::run(&cs, &pool);
    assert!(r.is_err());
}

#[test]
fn errors_when_evidence_is_missing() {
    let target_cid = "blake3-512:bad1";
    let env = json!({"otherStuff": "no evidence"});
    let mut pool = MementoPool::default();
    let err = pool
        .try_insert_unanchored_for_tests(memento_cid(target_cid), env)
        .expect_err("typed test storage refuses members without a kind");
    assert!(err.contains("MissingKind"));
}

#[test]
fn errors_when_contract_body_is_missing() {
    let target_cid = "blake3-512:contract2";
    let env = json!({
        "evidence": {"kind": "contract"}
        // no body
    });
    let pool = pool_with(target_cid, env);
    let cs = callsite_targeting(target_cid);
    let r = resolve_target::run(&cs, &pool);
    assert!(r.is_err());
}

#[test]
fn errors_when_evidence_kind_is_unknown() {
    let target_cid = "blake3-512:c";
    let env = json!({
        "evidence": {"kind": "weird-kind", "body": {"pre": {}}}
    });
    let mut pool = MementoPool::default();
    let err = pool
        .try_insert_unanchored_for_tests(memento_cid(target_cid), env)
        .expect_err("typed test storage refuses unknown member kinds");
    assert!(err.contains("UnknownKind"));
    assert!(err.contains("weird-kind"));
}

// ---------------------------------------------------------------------------
// Forward pin (BridgeDeclaration.ConsequentBundlePinned, NORMATIVE).
//
// See protocol/specs/2026-04-30-ir-formal-grammar.md
// § "Bridge target pinning: the shim-poisoning vector".
// ---------------------------------------------------------------------------

/// The contract member exists in the pool, but it was loaded from a
/// different `.proof` bundle than the bridge pinned. The verifier MUST
/// reject with `BridgeTargetProofCidMismatch`. This is the
/// shim-poisoning attack from the spec.
#[test]
fn rejects_when_target_proof_cid_does_not_match_bundle() {
    let target_cid = "blake3-512:contract-shared";
    let honest_bundle = "blake3-512:node-v24-proof-honest";
    let poisoned_bundle = "blake3-512:node-v24-proof-poisoned";

    let mut pool = pool_with(target_cid, contract_env(trivial_pre()));
    // Member was loaded as part of the poisoned bundle. The honest
    // bundle is what the bridge pinned but isn't present.
    pool.bundle_members
        .entry(memento_cid(poisoned_bundle))
        .or_default()
        .insert(memento_cid(target_cid));

    let cs = CallSite {
        bridge_ir_name: "parseInt".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_target_proof_cid: Some(memento_cid(honest_bundle)),
        ..Default::default()
    };

    let r = resolve_target::run(&cs, &pool);
    let err = format!("{:?}", r.expect_err("must reject"));
    assert!(
        err.contains("BridgeTargetProofCidMismatch"),
        "expected BridgeTargetProofCidMismatch, got: {err}"
    );
}

/// Same bundle for the bridge and the contract member: accept and
/// return the resolved formula.
#[test]
fn accepts_when_target_proof_cid_matches_bundle() {
    let target_cid = "blake3-512:contract-pinned";
    let honest_bundle = "blake3-512:node-v24-proof-honest";

    let mut pool = pool_with(target_cid, contract_env(trivial_pre()));
    pool.bundle_members
        .entry(memento_cid(honest_bundle))
        .or_default()
        .insert(memento_cid(target_cid));

    let cs = CallSite {
        bridge_ir_name: "parseInt".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_target_proof_cid: Some(memento_cid(honest_bundle)),
        ..Default::default()
    };

    let r = resolve_target::run(&cs, &pool).expect("must accept matching pin");
    assert_eq!(r.cid, cid_string(target_cid));
}

/// Pinned bundle isn't loaded at all: still a mismatch, fail-closed.
#[test]
fn rejects_when_pinned_bundle_is_not_loaded() {
    let target_cid = "blake3-512:contract-orphan";
    let pool = pool_with(target_cid, contract_env(trivial_pre()));

    let cs = CallSite {
        bridge_ir_name: "parseInt".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_target_proof_cid: Some(memento_cid("never-loaded")),
        ..Default::default()
    };

    let r = resolve_target::run(&cs, &pool);
    let err = format!("{:?}", r.expect_err("must reject"));
    assert!(
        err.contains("BridgeTargetProofCidMismatch"),
        "expected BridgeTargetProofCidMismatch, got: {err}"
    );
}

/// Self-pinned bridge (no `targetProofCid`) whose target IS a co-member of
/// the bridge's own bundle: accept. This is the intra-bundle case (a bridge
/// minted into the same `.proof` as its target).
#[test]
fn accepts_self_pinned_when_target_is_co_member() {
    let target_cid = "blake3-512:contract-selfpin";
    let self_bundle = "blake3-512:my-own-bundle";

    let mut pool = MementoPool::default();
    pool.insert_unanchored_for_tests(memento_cid(target_cid), contract_env(trivial_pre()));
    pool.bundle_members
        .entry(memento_cid(self_bundle))
        .or_default()
        .insert(memento_cid(target_cid));

    let cs = CallSite {
        bridge_ir_name: "selfPinned".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_target_proof_cid: None,
        bridge_self_bundle_cid: Some(memento_cid(self_bundle)),
        ..Default::default()
    };

    let r = resolve_target::run(&cs, &pool).expect("self-pinned co-member must resolve");
    assert_eq!(r.cid, cid_string(target_cid));
}

/// Self-pinned bridge whose target is NOT a co-member of its own bundle
/// (e.g. a same-named contract from a DIFFERENT bundle trying to pose as the
/// local one): reject. There is no unenforced path for the None case.
#[test]
fn rejects_self_pinned_when_target_not_co_member() {
    let target_cid = "blake3-512:contract-foreign";
    let self_bundle = "blake3-512:my-own-bundle";
    let other_bundle = "blake3-512:some-dependency";

    let mut pool = MementoPool::default();
    pool.insert_unanchored_for_tests(memento_cid(target_cid), contract_env(trivial_pre()));
    // The target lives only in a DIFFERENT bundle, not the bridge's own.
    pool.bundle_members
        .entry(memento_cid(other_bundle))
        .or_default()
        .insert(memento_cid(target_cid));
    // The self bundle exists but does NOT contain the target.
    pool.bundle_members
        .entry(memento_cid(self_bundle))
        .or_default();

    let cs = CallSite {
        bridge_ir_name: "selfPinnedForeign".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_target_proof_cid: None,
        bridge_self_bundle_cid: Some(memento_cid(self_bundle)),
        ..Default::default()
    };

    let err = format!(
        "{:?}",
        resolve_target::run(&cs, &pool).expect_err("must reject foreign self-pin")
    );
    assert!(
        err.contains("BridgeTargetProofCidMismatch"),
        "expected BridgeTargetProofCidMismatch, got: {err}"
    );
}

/// A self-pinned bridge with no known source bundle at all (e.g. a hand-built
/// in-memory pool that never went through load_all_proofs): unresolvable, so
/// fail-closed rather than silently skipping the pin.
#[test]
fn rejects_self_pinned_when_self_bundle_unknown() {
    let target_cid = "blake3-512:contract-unbundled";
    let pool = {
        let mut p = MementoPool::default();
        p.insert_unanchored_for_tests(memento_cid(target_cid), contract_env(trivial_pre()));
        p
    };

    let cs = CallSite {
        bridge_ir_name: "noBundle".into(),
        bridge_target_cid: Some(memento_cid(target_cid)),
        bridge_target_proof_cid: None,
        bridge_self_bundle_cid: None,
        ..Default::default()
    };

    let err = format!(
        "{:?}",
        resolve_target::run(&cs, &pool).expect_err("must fail-closed with no source bundle")
    );
    assert!(
        err.contains("BridgeSelfPinUnresolvable"),
        "expected BridgeSelfPinUnresolvable, got: {err}"
    );
}
