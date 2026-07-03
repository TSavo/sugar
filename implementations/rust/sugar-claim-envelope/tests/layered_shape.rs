// SPDX-License-Identifier: Apache-2.0
//
// Layered shape tests for `mint_contract` / `mint_bridge` /
// `mint_implication`.
//
// Spec: protocol/specs/2026-05-03-substrate-layers-envelope-header-body.md
//
// Every newly-minted memento has exactly three top-level layers:
//
//   { "envelope": {...}, "header": {...}, "metadata": {...} }
//
// The envelope is the signed wrapper. The header is the substrate-load-
// bearing data (kind / cid / kind-specific REQUIRED fields, plus the
// derived hashes the verifier indexes by). The metadata block is opaque
// to the substrate verifier; tooling reads it.
//
// The signature covers `JCS({"header": header, "metadata": metadata})`.
// Tampering with body fields therefore invalidates the envelope; the
// metadata inherits cryptographic provenance from the envelope's
// signer.
//
// schemaVersion is bumped to "2" to mark the layered shape; v1 (flat)
// remains valid as a historical artifact and is read by the verifier
// via a separate code path.

use std::sync::Arc;

use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_claim_envelope::{
    mint_bridge, mint_contract, Authoring, MintBridgeArgs, MintContractArgs,
};
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_verify_string, member_body, ContractMementoRef, Ed25519Seed,
};

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

fn contract_args() -> MintContractArgs {
    MintContractArgs {
        evidence_term: None,
        formals: Vec::new(),
        emit_empty_formals: false,
        formal_sorts: Vec::new(),
        library: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        panic_loci: Vec::new(),
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
        contract_name: "demo".into(),
        pre: Some(pre_n_gt_0()),
        post: None,
        inv: None,
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

fn json_to_value(j: &Json) -> Arc<Value> {
    match j {
        Json::Null => Value::null(),
        Json::Bool(b) => Value::boolean(*b),
        Json::Number(n) => {
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
        Json::String(s) => Value::string(s.clone()),
        Json::Array(items) => {
            let v: Vec<_> = items.iter().map(json_to_value).collect();
            Value::array(v)
        }
        Json::Object(map) => {
            let entries: Vec<(String, _)> = map
                .iter()
                .map(|(k, v)| (k.clone(), json_to_value(v)))
                .collect();
            Arc::new(Value::Object(entries))
        }
    }
}

#[test]
fn contract_memento_has_exactly_three_top_level_layers() {
    let m = mint_contract(&contract_args()).expect("mint");
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let obj = env.as_object().expect("top-level object");
    let mut keys: Vec<&str> = obj.keys().map(|k| k.as_str()).collect();
    keys.sort();
    assert_eq!(
        keys,
        vec!["envelope", "header", "metadata"],
        "spec §1: top-level layers MUST be exactly envelope/header/metadata; got {keys:?}"
    );
}

#[test]
fn contract_envelope_has_exactly_signer_declared_at_signature() {
    let m = mint_contract(&contract_args()).expect("mint");
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let envelope = env
        .pointer("/envelope")
        .expect("envelope")
        .as_object()
        .unwrap();
    let mut keys: Vec<&str> = envelope.keys().map(|k| k.as_str()).collect();
    keys.sort();
    assert_eq!(
        keys,
        vec!["declaredAt", "signature", "signer"],
        "spec §1: envelope MUST be exactly {{signer, declaredAt, signature}}; got {keys:?}"
    );
}

#[test]
fn contract_header_carries_kind_and_substrate_fields() {
    let m = mint_contract(&contract_args()).expect("mint");
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let header = member_body(&env).expect("header").as_object().unwrap();

    // Universal header fields (spec §1).
    assert_eq!(
        header.get("schemaVersion").and_then(|v| v.as_str()),
        Some("2")
    );
    assert_eq!(
        header.get("kind").and_then(|v| v.as_str()),
        Some("contract")
    );
    assert!(header
        .get("cid")
        .and_then(|v| v.as_str())
        .map(|s| s.starts_with("blake3-512:"))
        .unwrap_or(false));

    // Kind-specific REQUIRED contract fields (spec §3 example).
    assert_eq!(header.get("name").and_then(|v| v.as_str()), Some("demo"));
    assert_eq!(
        header.get("outBinding").and_then(|v| v.as_str()),
        Some("out")
    );
    assert!(
        header.get("pre").is_some(),
        "header.pre is REQUIRED for contract memento with pre clause"
    );
}

#[test]
fn contract_metadata_carries_authoring_and_producer_attribution() {
    let m = mint_contract(&contract_args()).expect("mint");
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let metadata = env
        .pointer("/metadata")
        .expect("metadata")
        .as_object()
        .unwrap();
    assert!(metadata.get("authoring").is_some(), "metadata.authoring");
    assert_eq!(
        metadata.get("producedBy").and_then(|v| v.as_str()),
        Some("rust-test@1.0")
    );
    assert!(metadata.get("producedAt").is_some(), "metadata.producedAt");
}

#[test]
fn signature_covers_header_and_metadata_via_jcs() {
    // spec §2 R2: the signature MUST verify against `JCS({header, metadata})`
    // where the unsigned message is the JCS encoding of the JSON object
    // {"header": header, "metadata": metadata}.
    let m = mint_contract(&contract_args()).expect("mint");
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let header = env.get("header").expect("header").clone();
    let metadata = env.get("metadata").expect("metadata").clone();
    let signer = sugar_proof_envelope::member_signer(&env)
        .and_then(|v| v.as_str())
        .expect("envelope.signer");
    let sig = sugar_proof_envelope::member_signature(&env)
        .and_then(|v| v.as_str())
        .expect("envelope.signature");
    let sig = sugar_proof_envelope::Signature::try_parse(sig.to_string())
        .expect("envelope signature must parse");

    let msg = Json::Object(serde_json::Map::from_iter([
        ("header".to_string(), header),
        ("metadata".to_string(), metadata),
    ]));
    let v = json_to_value(&msg);
    let bytes = encode_jcs(&v);

    assert!(
        ed25519_verify_string(signer, &sig, bytes.as_bytes()),
        "spec §2 R2: signature MUST verify against JCS({{header, metadata}})"
    );

    // Sanity: the embedded signer matches the seed-derived pubkey.
    assert_eq!(signer, ed25519_pubkey_string(&seed()));
}

#[test]
fn attestation_cid_is_blake3_of_jcs_envelope() {
    // spec §1 (substrate-layers): the envelope's CID is `hash(JCS(envelope))`.
    // This is what `MintedEnvelope.cid` returns post-PR; PR 2 adds the
    // separate `contract_cid()` that hashes the header content directly.
    let m = mint_contract(&contract_args()).expect("mint");
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let envelope = env.get("envelope").expect("envelope").clone();
    let v = json_to_value(&envelope);
    let recomputed = blake3_512_of(encode_jcs(&v).as_bytes());
    assert_eq!(
        m.cid, recomputed,
        "MintedEnvelope.cid MUST equal blake3_512(JCS(envelope))"
    );
}

#[test]
fn body_tamper_invalidates_signature() {
    // Spec §2 R2: "Any tampering with body fields invalidates the
    // signature; tooling can trust body content as having signer
    // provenance."
    let m = mint_contract(&contract_args()).expect("mint");
    let mut env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let signer = sugar_proof_envelope::member_signer(&env)
        .and_then(|v| v.as_str())
        .expect("signer")
        .to_string();
    let sig = sugar_proof_envelope::member_signature(&env)
        .and_then(|v| v.as_str())
        .expect("signature")
        .to_string();
    let sig =
        sugar_proof_envelope::Signature::try_parse(sig).expect("envelope signature must parse");

    // Tamper: rewrite metadata.producedBy.
    env.pointer_mut("/metadata")
        .and_then(|m| m.as_object_mut())
        .expect("metadata is object")
        .insert("producedBy".into(), Json::String("attacker".into()));

    let header = env.get("header").expect("header").clone();
    let metadata = env.get("metadata").expect("metadata").clone();
    let msg = Json::Object(serde_json::Map::from_iter([
        ("header".to_string(), header),
        ("metadata".to_string(), metadata),
    ]));
    let v = json_to_value(&msg);
    let bytes = encode_jcs(&v);

    assert!(
        !ed25519_verify_string(&signer, &sig, bytes.as_bytes()),
        "tampering with metadata MUST invalidate the envelope signature"
    );
}

#[test]
fn bridge_memento_has_layered_shape() {
    let args = MintBridgeArgs {
        produced_by: "rust-test@1.0".into(),
        produced_at: "2026-04-30T00:00:00.000Z".into(),
        source_symbol: "foo".into(),
        source_layer: "rust".into(),
        target_contract: ContractMementoRef::new(
            "blake3-512:0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000c0c0",
        ),
        target_layer: "ir".into(),
        ir_arg_sorts: vec!["Int".into()],
        ir_return_sort: "Int".into(),
        notes: String::new(),
        signer_seed: seed(),
        target_proof_cid: None,
        callsite: None,
    };
    let m = mint_bridge(&args);
    let env: Json = serde_json::from_slice(&m.canonical_bytes).expect("json");
    let obj = env.as_object().expect("top-level object");
    let mut keys: Vec<&str> = obj.keys().map(|k| k.as_str()).collect();
    keys.sort();
    assert_eq!(keys, vec!["envelope", "header", "metadata"]);

    let header = member_body(&env).unwrap().as_object().unwrap();
    assert_eq!(
        header.get("schemaVersion").and_then(|v| v.as_str()),
        Some("2")
    );
    assert_eq!(header.get("kind").and_then(|v| v.as_str()), Some("bridge"));
    assert_eq!(
        header.get("sourceSymbol").and_then(|v| v.as_str()),
        Some("foo")
    );
    assert_eq!(
        header.get("sourceLayer").and_then(|v| v.as_str()),
        Some("rust")
    );
    assert!(header.get("targetContractCid").is_some());
}
