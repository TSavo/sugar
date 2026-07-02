// SPDX-License-Identifier: Apache-2.0
//
// Soundness regression: a lone opaque equality `=(call:foo(x), literal)` with
// NO constraining universe (no `formals`, no `pre` on the target contract)
// must NOT vacuously discharge.
//
// MOTIVATION (the "vacuous door"):
//
// A "publisher post-only" vendor contract carries a `post` asserting a
// specific output value (e.g. `eq(out, "AAAA")`). It has NO `formals` and
// NO `pre`. When the consumer's assertion contract contains `inv =
// eq(call:encodeVendor("abc"), "AAAA")`, `enumerate_callsites` emits a
// callsite for that `call:` ctor.
//
// Before this fix, `work_one` in `runner.rs` would:
//   1. `extract_body_obligation` → None (no `formals` → CatalogResolver::lookup fails)
//   2. `resolve_target` → ir_formula = None, target_is_body_bearing = false
//   3. Fall through to the vacuous branch → `Discharged` ("no precondition")
//
// This is a FALSE DISCHARGE: "encodeVendor(abc)==AAAA" passes even when the
// correct encoding is "YWJj". A false claim should never be vacuously green.
//
// THE FIX: when `ir_formula` is None but the target has a `post`, the vacuous
// shortcut is blocked. A lone opaque equality lacks a constraining universe
// and must return Undecidable, not Discharged.
//
// This test is the regression net. It constructs the exact shape from the
// REPRO and asserts the verdict is NOT Discharged.

use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, BridgeMemento, ContractBody, ContractMemento,
    Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};
use sugar_verifier::{load_all_proofs::ProofBytes, ObligationVerdict, Runner, RunnerConfig};

// ─── IR formula builder helpers ──────────────────────────────────────────────

fn cv_str(s: impl Into<String>) -> Arc<CValue> {
    CValue::string(s.into())
}

fn cv_obj(fields: Vec<(&str, Arc<CValue>)>) -> Arc<CValue> {
    CValue::object(fields.into_iter().map(|(k, v)| (k.to_string(), v)))
}

fn cv_arr(items: Vec<Arc<CValue>>) -> Arc<CValue> {
    CValue::array(items)
}

/// `{kind:"const", value:<s>, sort:{kind:"primitive",name:"String"}}`
fn ir_string_const(s: &str) -> Arc<CValue> {
    cv_obj(vec![
        ("kind", cv_str("const")),
        ("value", cv_str(s)),
        (
            "sort",
            cv_obj(vec![
                ("kind", cv_str("primitive")),
                ("name", cv_str("String")),
            ]),
        ),
    ])
}

/// `{kind:"var", name:<n>}`
fn ir_var(n: &str) -> Arc<CValue> {
    cv_obj(vec![("kind", cv_str("var")), ("name", cv_str(n))])
}

/// `{kind:"ctor", name:<name>, args:[arg0]}`
fn ir_ctor1(name: &str, arg0: Arc<CValue>) -> Arc<CValue> {
    cv_obj(vec![
        ("kind", cv_str("ctor")),
        ("name", cv_str(name)),
        ("args", cv_arr(vec![arg0])),
    ])
}

/// `{kind:"atomic", name:"=", args:[lhs, rhs]}`
fn ir_eq(lhs: Arc<CValue>, rhs: Arc<CValue>) -> Arc<CValue> {
    cv_obj(vec![
        ("kind", cv_str("atomic")),
        ("name", cv_str("=")),
        ("args", cv_arr(vec![lhs, rhs])),
    ])
}

// ─── Bridge builder ──────────────────────────────────────────────────────────

/// Build raw bridge envelope bytes for `sourceSymbol -> targetContractCid`.
/// Uses the v1.1-flat `evidence.body` shape so `sugar_proof_envelope::member_body`
/// and `member_field` work on it the same as on a real minted bridge.
fn raw_bridge_bytes(source_symbol: &str, target_cid: &str, signer_seed: Ed25519Seed) -> Vec<u8> {
    let body = cv_obj(vec![
        ("sourceSymbol", cv_str(source_symbol)),
        ("sourceLayer", cv_str("test")),
        ("targetContractCid", cv_str(target_cid)),
        ("targetLayer", cv_str("test-kit")),
    ]);
    let evidence = cv_obj(vec![("kind", cv_str("bridge")), ("body", body.clone())]);
    let envelope_preimage = cv_obj(vec![
        ("kind", cv_str("bridge")),
        ("sourceSymbol", cv_str(source_symbol)),
        ("targetContractCid", cv_str(target_cid)),
    ]);
    let sig_input = encode_jcs(&envelope_preimage);
    let signature = sugar_proof_envelope::ed25519_sign_string(&signer_seed, sig_input.as_bytes());
    let pubkey = ed25519_pubkey_string(&signer_seed);
    let envelope = cv_obj(vec![
        ("signer", cv_str(&pubkey)),
        ("declaredAt", cv_str("2026-06-28T00:00:00.000Z")),
        ("signature", cv_str(&signature)),
    ]);
    let value = cv_obj(vec![("envelope", envelope), ("evidence", evidence)]);
    encode_jcs(&value).into_bytes()
}

// ─── Proof bundle builder ─────────────────────────────────────────────────────

/// Build a proof bundle containing:
///   - VENDOR contract: post = eq(out, literal), NO formals, NO pre
///     (the "publisher post-only" / "no formals" shape — the door)
///   - CONSUMER contract: inv = eq(call:encodeVendor("abc"), literal)
///   - BRIDGE: call:encodeVendor -> vendor_contract_cid
///
/// `literal` is the value asserted. "YWJj" = true base64; "AAAA" = false.
fn build_lone_opaque_proof_bundle(literal: &str) -> ProofBytes {
    let signer_seed: Ed25519Seed = [0x77u8; 32];
    let declared_at = "2026-06-28T00:00:00.000Z";
    let mut graph = ProofGraph::new();

    // Shared metadata atom (empty) — must be registered before any contracts
    // that use it.
    let metadata = graph.register_atom(FlatAtom::empty_metadata());

    // ── Vendor contract: post = eq(out, literal), NO formals, NO pre ─────────
    // Uses ContractBody::new(post_atom) so the graph contains a proper bodyCid
    // + body map entry that load_all_proofs accepts.
    let vendor_post = ir_eq(ir_var("out"), ir_string_const(literal));
    let vendor_post_atom = graph.register_atom(FlatAtom::new(vendor_post));
    let vendor_body = graph.register_body(ContractBody::new(&vendor_post_atom));
    let vendor_contract = ContractMemento::new_with_metadata_at(
        "vendor::encodeVendor",
        &vendor_body,
        &metadata,
        signer_seed,
        declared_at,
    );
    let vendor_cid = vendor_contract.cid().as_str().to_string();
    graph.register_contract(vendor_contract);

    // ── Consumer contract: inv = eq(call:encodeVendor("abc"), literal) ────────
    let consumer_inv = ir_eq(
        ir_ctor1("call:encodeVendor", ir_string_const("abc")),
        ir_string_const(literal),
    );
    let consumer_inv_atom = graph.register_atom(FlatAtom::new(consumer_inv));
    let consumer_body = graph.register_body(ContractBody::new_inv(&consumer_inv_atom));
    let consumer_contract = ContractMemento::new_with_metadata_at(
        "consumer::test_encodeVendor",
        &consumer_body,
        &metadata,
        signer_seed,
        declared_at,
    );
    graph.register_contract(consumer_contract);

    // ── Bridge: call:encodeVendor -> vendor_cid ───────────────────────────────
    // We build a v1.1-flat bridge envelope manually so we don't need
    // sugar_claim_envelope as a test dependency.
    let bridge_bytes = raw_bridge_bytes("call:encodeVendor", &vendor_cid, signer_seed);
    let bridge_memento = BridgeMemento::new(bridge_bytes);
    graph.push_bridge(bridge_memento);

    // ── Seal into a .proof bundle ─────────────────────────────────────────────
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: format!("@test/lone-opaque-{literal}"),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        graph,
        signer_cid,
        signer_seed,
        declared_at: declared_at.into(),
    });

    ProofBytes {
        label: format!("lone-opaque-{literal}.proof"),
        expected_cid: built.cid,
        bytes: built.bytes,
    }
}

// ─── Runner helper ───────────────────────────────────────────────────────────

fn run_with_bundle(literal: &str) -> Vec<(String, ObligationVerdict)> {
    let bundle = build_lone_opaque_proof_bundle(literal);
    let tmp = std::env::temp_dir().join(format!(
        "lone-opaque-door-{}-{}",
        literal,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&tmp).expect("create tmp dir");

    let runner = Runner::new(RunnerConfig {
        project_root: tmp,
        z3_path: "z3".into(),
        extra_proofs: vec![bundle],
        ..Default::default()
    });
    let (report, _stats) = runner.run_with_tiers();

    if report.rows.is_empty() {
        // Surface load errors if any
        for err in &report.load_errors {
            eprintln!(
                "[lone_opaque diag] load_error: {} — {}",
                err.proof_path, err.reason
            );
        }
    }

    report
        .rows
        .iter()
        .map(|r| (r.callsite.bridge_ir_name.clone(), r.status))
        .collect()
}

// ─── The teeth test ───────────────────────────────────────────────────────────

/// THE TEETH TEST.
///
/// A lone opaque equality `=(call:encodeVendor("abc"), "AAAA")` with a
/// vendor contract that has a `post` but no `formals` and no `pre` must
/// NOT vacuously discharge. Before the fix it returned Discharged for BOTH
/// the true and false claim — the door was open.
///
/// After the fix: the target's `post` is detected, the vacuous branch is
/// blocked, and the verdict is Undecidable (no universe to confirm or refute).
#[test]
fn lone_opaque_equality_without_universe_must_not_vacuous_discharge() {
    // FALSE claim: encodeVendor("abc") == "AAAA" — wrong value.
    // This is the case that caught the regression: a false assertion
    // must NEVER discharge.
    let false_rows = run_with_bundle("AAAA");
    assert!(
        !false_rows.is_empty(),
        "expected at least one callsite row for the false claim (check load_errors above)"
    );
    for (name, verdict) in &false_rows {
        assert_ne!(
            *verdict,
            ObligationVerdict::Discharged,
            "CARDINAL SIN (vacuous door): false claim `=(call:{}(\"abc\"), \"AAAA\")` \
             vacuously discharged — lone opaque equality must be Undecidable, not Discharged",
            name
        );
    }

    // TRUE claim: encodeVendor("abc") == "YWJj" — real base64 encoding.
    // Also must not vacuously discharge (no universe to verify it at this tier).
    let true_rows = run_with_bundle("YWJj");
    assert!(
        !true_rows.is_empty(),
        "expected at least one callsite row for the true claim"
    );
    for (name, verdict) in &true_rows {
        assert_ne!(
            *verdict,
            ObligationVerdict::Discharged,
            "vacuous door (true variant): `=(call:{}(\"abc\"), \"YWJj\")` vacuously \
             discharged — without a constraining universe no claim should discharge \
             via the vacuous path",
            name
        );
    }
}
