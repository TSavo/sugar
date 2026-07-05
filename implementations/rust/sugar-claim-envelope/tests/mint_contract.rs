// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Tests for `mint_contract`. Pins:
//   - error when all of pre/post/inv are None (EmptyContract)
//   - error when out_binding is empty (EmptyOutBinding)
//   - every (pre, post, inv) combination accepted; produces stable
//     bindingHash + propertyHash for the same input
//   - preHash / postHash / invHash are DERIVED from the stored canonical formula bytes
//     (caller can't supply them; recomputation catches forgery)
//   - propertyHash = BLAKE3-512(JCS({canonical pre?, post?, inv?, outBinding}))
//   - bindingHash  = BLAKE3-512(JCS({producerId, contractName, propertyHash}))
//   - CID is "blake3-512:" + 128 hex chars

use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_claim_envelope::{
    contract_cid, mint_contract, Authoring, ClaimEnvelopeError, MintContractArgs, MintedEnvelope,
};
use sugar_proof_envelope::{member_field, Ed25519Seed};

fn seed() -> Ed25519Seed {
    [0x42u8; 32]
}

fn pre_n_gt_0() -> Arc<Value> {
    Value::object([
        ("kind", Value::string("forall")),
        ("name", Value::string("n")),
        (
            "sort",
            Value::object([
                ("kind", Value::string("primitive")),
                ("name", Value::string("Int")),
            ]),
        ),
        (
            "body",
            Value::object([
                ("kind", Value::string("atomic")),
                ("name", Value::string(">")),
                (
                    "args",
                    Value::array(vec![
                        Value::object([
                            ("kind", Value::string("var")),
                            ("name", Value::string("n")),
                        ]),
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
            ]),
        ),
    ])
}

fn post_out_eq_0() -> Arc<Value> {
    // Body: out = 0
    Value::object([
        ("kind", Value::string("atomic")),
        ("name", Value::string("=")),
        (
            "args",
            Value::array(vec![
                Value::object([
                    ("kind", Value::string("var")),
                    ("name", Value::string("out")),
                ]),
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
    ])
}

fn inv_true() -> Arc<Value> {
    // True formula
    Value::object([
        ("kind", Value::string("and")),
        ("operands", Value::array(vec![])),
    ])
}

/// A binder-free pre `n > 0` (the body of `pre_n_gt_0` without the `forall`).
/// Canonicalization is the identity on this (no binder, no let), so its bytes
/// survive the propertyHash derivation unchanged.
fn pre_n_gt_0_unquantified() -> Arc<Value> {
    Value::object([
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
    ])
}

/// `forall <var>: Int. (<var> > 0)` -- a quantified pre with a configurable
/// bound-variable name, for alpha-invariance checks.
fn forall_gt_0(var: &str) -> Arc<Value> {
    Value::object([
        ("kind", Value::string("forall")),
        ("name", Value::string(var)),
        (
            "sort",
            Value::object([
                ("kind", Value::string("primitive")),
                ("name", Value::string("Int")),
            ]),
        ),
        (
            "body",
            Value::object([
                ("kind", Value::string("atomic")),
                ("name", Value::string(">")),
                (
                    "args",
                    Value::array(vec![
                        Value::object([
                            ("kind", Value::string("var")),
                            ("name", Value::string(var)),
                        ]),
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
            ]),
        ),
    ])
}

fn args_with(
    pre: Option<Arc<Value>>,
    post: Option<Arc<Value>>,
    inv: Option<Arc<Value>>,
) -> MintContractArgs {
    MintContractArgs {
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
        contract_name: "demo".into(),
        pre,
        post,
        inv,
        out_binding: "out".into(),
        produced_by: "rust-test@1.0".into(),
        produced_at: "2026-04-30T00:00:00.000Z".into(),
        input_cids: vec![],
        authoring: Authoring::KitAuthor {
            author: "rust-test@1.0".into(),
            note: None,
        },
        signer_seed: seed(),
    }
}

// ---------------------------------------------------------------------------
// Failure modes
// ---------------------------------------------------------------------------

#[test]
fn errors_when_all_three_clauses_are_none() {
    let args = args_with(None, None, None);
    let r = mint_contract(&args);
    match r {
        Err(ClaimEnvelopeError::EmptyContract) => {}
        other => panic!("expected EmptyContract, got {other:?}"),
    }
}

#[test]
fn errors_when_out_binding_is_empty() {
    let mut args = args_with(Some(pre_n_gt_0()), None, None);
    args.out_binding = String::new();
    let r = mint_contract(&args);
    match r {
        Err(ClaimEnvelopeError::EmptyOutBinding) => {}
        other => panic!("expected EmptyOutBinding, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Combination matrix: pre / post / inv individually + together
// ---------------------------------------------------------------------------

#[test]
fn pre_only_succeeds() {
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

#[test]
fn post_only_succeeds() {
    let m = mint_contract(&args_with(None, Some(post_out_eq_0()), None)).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

#[test]
fn inv_only_succeeds() {
    let m = mint_contract(&args_with(None, None, Some(inv_true()))).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

#[test]
fn pre_post_succeeds() {
    let m =
        mint_contract(&args_with(Some(pre_n_gt_0()), Some(post_out_eq_0()), None)).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

#[test]
fn pre_inv_succeeds() {
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, Some(inv_true()))).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

#[test]
fn post_inv_succeeds() {
    let m = mint_contract(&args_with(None, Some(post_out_eq_0()), Some(inv_true()))).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

#[test]
fn pre_post_inv_all_present_succeeds() {
    let m = mint_contract(&args_with(
        Some(pre_n_gt_0()),
        Some(post_out_eq_0()),
        Some(inv_true()),
    ))
    .expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
}

// ---------------------------------------------------------------------------
// CID shape
// ---------------------------------------------------------------------------

#[test]
fn cid_is_blake3_512_prefixed_and_correct_length() {
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    assert!(m.cid.starts_with("blake3-512:"));
    assert_eq!(m.cid.len(), "blake3-512:".len() + 128);
}

#[test]
fn cid_matches_blake3_of_jcs_envelope() {
    // Layered shape: the attestation CID is BLAKE3-512(JCS(envelope))
    // where `envelope` is the embedded {signer, declaredAt, signature}
    // sub-object after signing. Verifiers re-derive the CID from the
    // envelope alone; the trust root is the envelope hash, not a
    // strip-and-rehash of the whole memento.
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let signed_text = std::str::from_utf8(&m.canonical_bytes).expect("utf8");
    let signed_json: serde_json::Value = serde_json::from_str(signed_text).expect("json parse");
    let envelope = signed_json
        .get("envelope")
        .expect("envelope present")
        .clone();
    let v = json_to_value(&envelope);
    let recomputed = blake3_512_of(encode_jcs(&v).as_bytes());
    assert_eq!(
        m.cid, recomputed,
        "cid must equal blake3_512(JCS(envelope))"
    );
}

fn json_to_value(j: &serde_json::Value) -> Arc<Value> {
    match j {
        serde_json::Value::Null => Value::null(),
        serde_json::Value::Bool(b) => Value::boolean(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                Value::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                Value::integer(f as i128)
            } else {
                Value::integer(0)
            }
        }
        serde_json::Value::String(s) => Value::string(s.clone()),
        serde_json::Value::Array(items) => {
            let v: Vec<_> = items.iter().map(json_to_value).collect();
            Value::array(v)
        }
        serde_json::Value::Object(map) => {
            let entries: Vec<(String, _)> = map
                .iter()
                .map(|(k, v)| (k.clone(), json_to_value(v)))
                .collect();
            Arc::new(Value::Object(entries))
        }
    }
}

// ---------------------------------------------------------------------------
// preHash / postHash / invHash are DERIVED from stored canonical formula bytes
// ---------------------------------------------------------------------------

fn parse_envelope(m: &MintedEnvelope) -> serde_json::Value {
    serde_json::from_slice(&m.canonical_bytes).expect("json parse")
}

#[test]
fn source_warrants_round_trip_without_changing_contract_cid() {
    let mut args = args_with(None, None, Some(inv_true()));
    let cid_without_warrant = contract_cid(&args);
    args.source_warrants = vec![Value::object([
        ("kind", Value::string("source-memento")),
        ("role", Value::string("java.strong-universe")),
        ("file", Value::string("src/Codec.java")),
        ("source_function_name", Value::string("encode")),
        (
            "source_cid",
            Value::string(format!("blake3-512:{}", "a".repeat(128))),
        ),
        (
            "template_cid",
            Value::string(format!("blake3-512:{}", "b".repeat(128))),
        ),
        (
            "span",
            Value::object([
                ("start_line", Value::integer(10)),
                ("start_col", Value::integer(4)),
                ("end_line", Value::integer(14)),
                ("end_col", Value::integer(5)),
            ]),
        ),
    ])];

    assert_eq!(
        contract_cid(&args),
        cid_without_warrant,
        "source warrants are provenance, not logical contract identity"
    );

    let minted = mint_contract(&args).expect("mint");
    assert_eq!(minted.contract_cid, cid_without_warrant);
    let env = parse_envelope(&minted);
    let warrants = member_field(&env, "sourceWarrants")
        .and_then(|v| v.as_array())
        .expect("sourceWarrants header array");
    assert_eq!(warrants.len(), 1);
    assert_eq!(warrants[0]["kind"], "source-memento");
    assert_eq!(warrants[0]["file"], "src/Codec.java");
    assert!(warrants[0].get("body_text").is_none());
    assert!(warrants[0].get("ast_template").is_none());
}

// preHash / postHash / invHash are pure tooling-convenience derivations
// from the stored canonical formula bytes (the verifier doesn't read them; consumers
// can reconstruct them locally). Layered shape places them in
// `metadata`, where opaque-to-substrate body fields live.

#[test]
fn pre_hash_is_blake3_of_jcs_encoded_pre() {
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let env = parse_envelope(&m);
    let metadata = env.pointer("/metadata").expect("metadata").clone();
    let pre_hash = metadata
        .get("preHash")
        .and_then(|v| v.as_str())
        .expect("preHash present");
    let expected = blake3_512_of(
        encode_jcs(&json_to_value(
            member_field(&env, "pre").expect("canonical header pre"),
        ))
        .as_bytes(),
    );
    assert_eq!(pre_hash, expected);
}

#[test]
fn post_hash_is_blake3_of_jcs_encoded_post() {
    let m = mint_contract(&args_with(None, Some(post_out_eq_0()), None)).expect("mint");
    let env = parse_envelope(&m);
    let metadata = env.pointer("/metadata").expect("metadata").clone();
    let post_hash = metadata
        .get("postHash")
        .and_then(|v| v.as_str())
        .expect("postHash");
    let expected = blake3_512_of(encode_jcs(&post_out_eq_0()).as_bytes());
    assert_eq!(post_hash, expected);
}

#[test]
fn inv_hash_is_blake3_of_jcs_encoded_inv() {
    let m = mint_contract(&args_with(None, None, Some(inv_true()))).expect("mint");
    let env = parse_envelope(&m);
    let metadata = env.pointer("/metadata").expect("metadata").clone();
    let inv_hash = metadata
        .get("invHash")
        .and_then(|v| v.as_str())
        .expect("invHash");
    let expected = blake3_512_of(encode_jcs(&inv_true()).as_bytes());
    assert_eq!(inv_hash, expected);
}

#[test]
fn omitted_clauses_omit_their_hash_fields() {
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let env = parse_envelope(&m);
    let metadata = env.pointer("/metadata").expect("metadata");
    assert!(
        metadata.get("preHash").is_some(),
        "preHash should be present"
    );
    assert!(
        metadata.get("postHash").is_none(),
        "postHash should be absent"
    );
    assert!(
        metadata.get("invHash").is_none(),
        "invHash should be absent"
    );
}

// ---------------------------------------------------------------------------
// propertyHash + bindingHash derivation
// ---------------------------------------------------------------------------

#[test]
fn property_hash_is_blake3_of_jcs_pre_post_inv_outbinding() {
    // Binder-free, let-free slots: canonicalization is the identity on every
    // slot, so the propertyHash is still exactly BLAKE3-512(JCS of the raw
    // slots) -- the derivation shape this test pins (slots, insertion order,
    // JCS, blake3). (A quantified/let-bearing slot is alpha-normalized first;
    // that path is pinned by `property_hash_alpha_invariant_under_pre_rename`.)
    let pre = pre_n_gt_0_unquantified();
    let m = mint_contract(&args_with(
        Some(pre.clone()),
        Some(post_out_eq_0()),
        Some(inv_true()),
    ))
    .expect("mint");
    let env = parse_envelope(&m);
    let claimed = member_field(&env, "propertyHash")
        .and_then(|v| v.as_str())
        .expect("propertyHash");

    // Recompute: hash(JCS({pre, post, inv, outBinding})) with insertion
    // order pre, post, inv, outBinding (matches mint.rs).
    let v = Arc::new(Value::Object(vec![
        ("pre".into(), pre),
        ("post".into(), post_out_eq_0()),
        ("inv".into(), inv_true()),
        ("outBinding".into(), Value::string("out")),
    ]));
    let expected = blake3_512_of(encode_jcs(&v).as_bytes());
    assert_eq!(claimed, expected);
}

/// The propertyHash IS the behavior identity, so it must be invariant under
/// renaming a bound variable: `forall n. n>0` and `forall m. m>0` are the same
/// proposition and MUST share a propertyHash. Canonicalization (binder ->
/// `$b<depth>`) makes this hold; without it the surface name would leak into
/// the content address. This is WHY pre/post/inv are canonicalized before
/// hashing.
#[test]
fn property_hash_alpha_invariant_under_pre_rename() {
    let m_n = mint_contract(&args_with(Some(forall_gt_0("n")), None, None)).expect("mint n");
    let m_m = mint_contract(&args_with(Some(forall_gt_0("m")), None, None)).expect("mint m");

    let ph = |m: &MintedEnvelope| {
        let env = parse_envelope(m);
        member_field(&env, "propertyHash")
            .and_then(|v| v.as_str())
            .expect("propertyHash")
            .to_string()
    };
    assert_eq!(
        ph(&m_n),
        ph(&m_m),
        "alpha-equivalent quantified pres must share a propertyHash"
    );

    // And the whole contract identity (header.cid) is alpha-invariant too.
    let env_n = parse_envelope(&m_n);
    let env_m = parse_envelope(&m_m);
    assert_eq!(
        member_field(&env_n, "cid")
            .and_then(|v| v.as_str())
            .unwrap(),
        member_field(&env_m, "cid")
            .and_then(|v| v.as_str())
            .unwrap(),
        "alpha-equivalent contracts must share a header CID"
    );
}

#[test]
fn binding_hash_is_blake3_of_jcs_producer_id_contract_name_property_hash() {
    let m = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let env = parse_envelope(&m);
    let property_hash = member_field(&env, "propertyHash")
        .and_then(|v| v.as_str())
        .unwrap();
    let claimed = member_field(&env, "bindingHash")
        .and_then(|v| v.as_str())
        .expect("bindingHash");

    let v = Value::object([
        ("producerId", Value::string("rust-test@1.0")),
        ("contractName", Value::string("demo")),
        ("propertyHash", Value::string(property_hash)),
    ]);
    let expected = blake3_512_of(encode_jcs(&v).as_bytes());
    assert_eq!(claimed, expected);
}

// ---------------------------------------------------------------------------
// Determinism + sensitivity
// ---------------------------------------------------------------------------

#[test]
fn same_inputs_produce_same_cid() {
    let a = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let b = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    assert_eq!(a.cid, b.cid);
    assert_eq!(a.canonical_bytes, b.canonical_bytes);
}

#[test]
fn changing_pre_changes_cid() {
    let a = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    // Different pre formula
    let other_pre = Value::object([
        ("kind", Value::string("atomic")),
        ("name", Value::string("=")),
        ("args", Value::array(vec![])),
    ]);
    let b = mint_contract(&args_with(Some(other_pre), None, None)).expect("mint");
    assert_ne!(a.cid, b.cid);
}

#[test]
fn changing_contract_name_changes_binding_hash() {
    let a = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let mut args_b = args_with(Some(pre_n_gt_0()), None, None);
    args_b.contract_name = "other".into();
    let b = mint_contract(&args_b).expect("mint");

    let env_a = parse_envelope(&a);
    let env_b = parse_envelope(&b);
    let bh_a = member_field(&env_a, "bindingHash")
        .and_then(|v| v.as_str())
        .unwrap();
    let bh_b = member_field(&env_b, "bindingHash")
        .and_then(|v| v.as_str())
        .unwrap();
    assert_ne!(bh_a, bh_b);
}

#[test]
fn changing_producer_id_changes_binding_hash_but_not_property_hash() {
    let a = mint_contract(&args_with(Some(pre_n_gt_0()), None, None)).expect("mint");
    let mut args_b = args_with(Some(pre_n_gt_0()), None, None);
    args_b.produced_by = "other-kit@2.0".into();
    let b = mint_contract(&args_b).expect("mint");

    let env_a = parse_envelope(&a);
    let env_b = parse_envelope(&b);
    let ph_a = member_field(&env_a, "propertyHash")
        .and_then(|v| v.as_str())
        .unwrap();
    let ph_b = member_field(&env_b, "propertyHash")
        .and_then(|v| v.as_str())
        .unwrap();
    assert_eq!(ph_a, ph_b, "propertyHash must be producer-independent");
    let bh_a = member_field(&env_a, "bindingHash")
        .and_then(|v| v.as_str())
        .unwrap();
    let bh_b = member_field(&env_b, "bindingHash")
        .and_then(|v| v.as_str())
        .unwrap();
    assert_ne!(bh_a, bh_b, "bindingHash must depend on producerId");
}

// ---------------------------------------------------------------------------
// Authoring blocks round-trip
// ---------------------------------------------------------------------------

#[test]
fn authoring_kit_author_round_trips() {
    let mut args = args_with(Some(pre_n_gt_0()), None, None);
    args.authoring = Authoring::KitAuthor {
        author: "alice".into(),
        note: Some("hand-authored".into()),
    };
    let m = mint_contract(&args).expect("mint");
    let env = parse_envelope(&m);
    let auth = env.pointer("/metadata/authoring").expect("authoring");
    assert_eq!(
        auth.get("producerKind").and_then(|v| v.as_str()),
        Some("kit-author")
    );
    assert_eq!(auth.get("author").and_then(|v| v.as_str()), Some("alice"));
    assert_eq!(
        auth.get("note").and_then(|v| v.as_str()),
        Some("hand-authored")
    );
}

#[test]
fn authoring_lift_round_trips() {
    let mut args = args_with(Some(pre_n_gt_0()), None, None);
    args.authoring = Authoring::Lift {
        lifter: "lift-kit@1.0".into(),
        evidence: "lifted from rust source".into(),
        source_cid: Some("blake3-512:source".into()),
    };
    let m = mint_contract(&args).expect("mint");
    let env = parse_envelope(&m);
    let auth = env.pointer("/metadata/authoring").expect("authoring");
    assert_eq!(
        auth.get("producerKind").and_then(|v| v.as_str()),
        Some("lift")
    );
    assert_eq!(
        auth.get("lifter").and_then(|v| v.as_str()),
        Some("lift-kit@1.0")
    );
    assert_eq!(
        auth.get("sourceCid").and_then(|v| v.as_str()),
        Some("blake3-512:source")
    );
}

#[test]
fn authoring_llm_round_trips() {
    let mut args = args_with(Some(pre_n_gt_0()), None, None);
    args.authoring = Authoring::Llm {
        llm: "claude".into(),
        llm_version: "opus-4.7".into(),
        prompt_cid: "blake3-512:prompt".into(),
        confidence: 0.9,
        rationale: Some("inferred from docs".into()),
    };
    let m = mint_contract(&args).expect("mint");
    let env = parse_envelope(&m);
    let auth = env.pointer("/metadata/authoring").expect("authoring");
    assert_eq!(
        auth.get("producerKind").and_then(|v| v.as_str()),
        Some("llm")
    );
    assert_eq!(auth.get("llm").and_then(|v| v.as_str()), Some("claude"));
    // confidence was scaled by 1000 and stored as integer
    assert_eq!(auth.get("confidence").and_then(|v| v.as_i64()), Some(900));
}
