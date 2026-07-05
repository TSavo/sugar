// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip serde tests for the v1.4 BridgeDeclaration types.
//
// Source of truth:
//   protocol/specs/2026-05-03-bridge-target-dimensionality.md
//   protocol/specs/2026-05-03-substrate-layers-envelope-header-body.md
//   protocol/sugar-ir.cddl  (BridgeDeclarationV14, BridgeTarget, ...)
//
// These tests pin:
//   * The Rust IR types deserialize from the spec sample wire shape.
//   * The tagged-union `target` field discriminates on `kind` and
//     accepts both `"contract"` and `"contractSet"` variants.
//   * Round-trip parity at the serde layer: parse -> serialize -> parse
//     yields the same value. (Byte-equality round-trip lives in
//     `sugar-claim-envelope/tests/bridge_v14_roundtrip.rs` because
//     this crate has no JCS encoder.)

use sugar_ir_types::{
    BridgeDeclarationV14, BridgeEnvelope, BridgeHeaderV14, BridgeMetadataV14, BridgeTarget,
};

const CANONICAL_FIXTURE_JSON: &str = r#"{
  "envelope": {
    "signer": "ed25519:pubkey-fixture-bytes",
    "declaredAt": "2026-05-03T00:00:00.000Z",
    "signature": "ed25519:signature-fixture-bytes"
  },
  "header": {
    "schemaVersion": "1",
    "kind": "bridge",
    "name": "rust-canonical-bridge-fixture",
    "sourceSymbol": "parseInt",
    "sourceLayer": "rust-kit",
    "sourceContractCid": "blake3-512:source0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
    "target": {
      "kind": "contract",
      "cid": "blake3-512:target0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    }
  },
  "metadata": {
    "targetLayer": "rust-kit",
    "producedBy": "sugar-canonical-reference@v1.4",
    "producedAt": "2026-05-03T00:00:00.000Z"
  }
}"#;

#[test]
fn bridge_v14_deserializes_from_spec_shape() {
    let bridge: BridgeDeclarationV14 =
        serde_json::from_str(CANONICAL_FIXTURE_JSON).expect("parse v1.4 bridge");

    assert_eq!(bridge.envelope.signer, "ed25519:pubkey-fixture-bytes");
    assert_eq!(bridge.envelope.declared_at, "2026-05-03T00:00:00.000Z");
    assert_eq!(bridge.header.schema_version, "1");
    assert_eq!(bridge.header.kind, "bridge");
    assert_eq!(bridge.header.name, "rust-canonical-bridge-fixture");
    assert_eq!(bridge.header.source_symbol, "parseInt");
    assert_eq!(bridge.header.source_layer, "rust-kit");

    match &bridge.header.target {
        BridgeTarget::Contract { cid } => {
            assert!(cid.starts_with("blake3-512:target"));
        }
        BridgeTarget::ContractSet { .. } => panic!("expected Contract variant"),
    }

    // Spec §1.R3: header carries contract-axis only; witness/binary
    // metadata is OMITTED here (None), per spec §1.R2 (no null, no
    // placeholder strings).
    assert!(bridge.metadata.target_witness_cid.is_none());
    assert!(bridge.metadata.target_binary_cid.is_none());
    assert_eq!(bridge.metadata.target_layer.as_deref(), Some("rust-kit"),);
    assert_eq!(
        bridge.metadata.produced_by.as_deref(),
        Some("sugar-canonical-reference@v1.4"),
    );
}

#[test]
fn bridge_v14_target_discriminates_on_kind() {
    let contract_set_json = r#"{
        "envelope": {
            "signer": "ed25519:s",
            "declaredAt": "2026-05-03T00:00:00.000Z",
            "signature": "ed25519:sig"
        },
        "header": {
            "schemaVersion": "1",
            "kind": "bridge",
            "name": "n",
            "sourceSymbol": "s",
            "sourceLayer": "rust-kit",
            "sourceContractCid": "blake3-512:0000",
            "target": {
                "kind": "contractSet",
                "cid": "blake3-512:set000"
            }
        },
        "metadata": {}
    }"#;

    let bridge: BridgeDeclarationV14 =
        serde_json::from_str(contract_set_json).expect("parse contractSet variant");

    match &bridge.header.target {
        BridgeTarget::ContractSet { cid } => {
            assert_eq!(cid, "blake3-512:set000");
        }
        BridgeTarget::Contract { .. } => panic!("expected ContractSet variant"),
    }
}

#[test]
fn bridge_v14_serde_round_trip_preserves_value() {
    // Parse -> serialize -> parse -> compare. This exercises the serde
    // layer's parity property: round-tripping a v1.4 bridge through
    // serde_json gives back an equal BridgeDeclarationV14.
    //
    // Note: this is NOT a JCS byte-equality test (serde_json's default
    // emit is not JCS-canonical). The canonical-bytes round-trip lives
    // in `sugar-claim-envelope/tests/bridge_v14_roundtrip.rs`.

    let bridge_in: BridgeDeclarationV14 =
        serde_json::from_str(CANONICAL_FIXTURE_JSON).expect("parse #1");
    let serialized = serde_json::to_string(&bridge_in).expect("serialize");
    let bridge_out: BridgeDeclarationV14 = serde_json::from_str(&serialized).expect("parse #2");
    assert_eq!(bridge_in, bridge_out);
}

#[test]
fn bridge_v14_omits_none_metadata_fields_on_serialize() {
    // Spec §1.R2: absent metadata fields are OMITTED, not null and not
    // stringified placeholders. The generated `BridgeMetadataV14`
    // struct uses `#[serde(skip_serializing_if = "Option::is_none")]`
    // for every field; this test pins that behavior.

    let bridge = BridgeDeclarationV14 {
        envelope: BridgeEnvelope {
            signer: "ed25519:s".into(),
            declared_at: "2026-05-03T00:00:00.000Z".into(),
            signature: "ed25519:sig".into(),
        },
        header: BridgeHeaderV14 {
            schema_version: "1".into(),
            kind: "bridge".into(),
            name: "n".into(),
            source_symbol: "s".into(),
            source_layer: "rust-kit".into(),
            source_contract_cid: "blake3-512:src".into(),
            target: BridgeTarget::Contract {
                cid: "blake3-512:tgt".into(),
            },
        },
        metadata: BridgeMetadataV14 {
            target_witness_cid: None,
            target_binary_cid: None,
            target_layer: None,
            target_contract_set_cid: None,
            produced_by: None,
            produced_at: None,
        },
    };

    let serialized = serde_json::to_string(&bridge).expect("serialize");
    // None of the optional metadata fields should appear when None.
    assert!(!serialized.contains("targetWitnessCid"));
    assert!(!serialized.contains("targetBinaryCid"));
    assert!(!serialized.contains("targetContractSetCid"));
    assert!(!serialized.contains("producedBy"));
    assert!(!serialized.contains("producedAt"));
    // No `null` literals leaking in.
    assert!(!serialized.contains("null"));
}
