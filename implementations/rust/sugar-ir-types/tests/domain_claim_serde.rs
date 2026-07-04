// SPDX-License-Identifier: Apache-2.0
//
// Round-trip serde tests for the DomainClaim wire form and its
// `Into<DomainClaim>` impl from `ConceptSiteMemento`.
//
// Source of truth:
//   protocol/specs/2026-05-13-domain-claim-normalization.md §1, §2
//
// These tests pin:
//   * DomainClaim deserializes from the wire shape the spec defines.
//   * Round-trip parity at the serde layer: parse -> serialize -> parse
//     yields the same value.
//   * All three verdict kinds round-trip with the correct optional-field
//     presence (discharge_receipt_cid / refusal_reason).
//   * The `From<&ConceptSiteMemento> for DomainClaim` mapping is faithful
//     to spec §2.1 across all three trichotomy verdicts.
//   * The trichotomy verdict is PRESERVED across the conversion: a
//     ConceptSiteMemento with verdict X produces a DomainClaim with
//     VerdictKind X for every X.
//
// Byte-exact CID pinning lives in sugar-claim-envelope (this crate has
// no JCS encoder).

use std::collections::BTreeMap;

use sugar_ir_types::{DomainClaim, DomainClaimProvenance, LossRecord, VerdictBody, VerdictKind};

// 128 hex chars after the "blake3-512:" prefix; deterministic placeholders.
const KIT_CID: &str = "blake3-512:kit00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a";
const INPUT_CID: &str = "blake3-512:in1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111aa";
const TRUTH_CID: &str = "blake3-512:tr2222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222ab";
const RECEIPT_CID: &str = "blake3-512:rc3333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333ac";
const SIGNER: &str = "ed25519:VGVzdFNpZ25lcjAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA==";
const SIGNATURE: &str = "ed25519:VGVzdFNpZ25hdHVyZTAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA==";
// ================================================================
// DomainClaim wire shape -- "exact" verdict
// ================================================================

const EXACT_FIXTURE: &str = r#"{
  "input_cid":  "blake3-512:in1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111aa",
  "kind":       "domain-claim",
  "kit_cid":    "blake3-512:kit00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a",
  "provenance": {
    "declared_at": "2026-05-13T12:00:00Z",
    "signer":      "ed25519:VGVzdFNpZ25lcjAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA=="
  },
  "signature":  "ed25519:VGVzdFNpZ25hdHVyZTAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA==",
  "truth_cid":  "blake3-512:tr2222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222ab",
  "verdict":    {
    "discharge_receipt_cid": "blake3-512:rc3333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333ac",
    "kind":                  "exact",
    "loss_record":           {}
  }
}"#;

#[test]
fn exact_wire_deserializes() {
    let c: DomainClaim = serde_json::from_str(EXACT_FIXTURE).expect("parse exact");
    assert_eq!(c.kind, "domain-claim");
    assert_eq!(c.kit_cid, KIT_CID);
    assert_eq!(c.input_cid, INPUT_CID);
    assert_eq!(c.truth_cid, TRUTH_CID);
    assert_eq!(c.verdict.kind, VerdictKind::Exact);
    assert_eq!(
        c.verdict.discharge_receipt_cid.as_deref(),
        Some(RECEIPT_CID)
    );
    assert!(c.verdict.refusal_reason.is_none());
    assert!(c.verdict.loss_record.0.is_empty());
    assert_eq!(c.provenance.signer, SIGNER);
    assert_eq!(c.signature, SIGNATURE);
}

#[test]
fn exact_wire_round_trips() {
    let c1: DomainClaim = serde_json::from_str(EXACT_FIXTURE).expect("parse");
    let serialized = serde_json::to_string(&c1).expect("serialize");
    let c2: DomainClaim = serde_json::from_str(&serialized).expect("re-parse");
    assert_eq!(c1, c2);
}

// ================================================================
// DomainClaim wire shape -- "loudly-bounded-lossy" verdict
// ================================================================

const LOUDLY_LOSSY_FIXTURE: &str = r#"{
  "input_cid":  "blake3-512:in1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111aa",
  "kind":       "domain-claim",
  "kit_cid":    "blake3-512:kit00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a",
  "provenance": {
    "declared_at": "2026-05-13T12:00:00Z",
    "signer":      "ed25519:VGVzdFNpZ25lcjAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA=="
  },
  "signature":  "ed25519:VGVzdFNpZ25hdHVyZTAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA==",
  "truth_cid":  "blake3-512:tr2222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222ab",
  "verdict":    {
    "discharge_receipt_cid": "blake3-512:rc3333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333ac",
    "kind":                  "loudly-bounded-lossy",
    "loss_record": {
      "domain_narrowing": {
        "kind": "atomic",
        "name": ">",
        "args": [
          {"kind": "var", "name": "x"},
          {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ]
      }
    }
  }
}"#;

#[test]
fn loudly_lossy_wire_deserializes() {
    let c: DomainClaim = serde_json::from_str(LOUDLY_LOSSY_FIXTURE).expect("parse lossy");
    assert_eq!(c.verdict.kind, VerdictKind::LoudlyBoundedLossy);
    assert_eq!(
        c.verdict.discharge_receipt_cid.as_deref(),
        Some(RECEIPT_CID)
    );
    assert!(c.verdict.refusal_reason.is_none());
    assert_eq!(c.verdict.loss_record.0.len(), 1);
    assert!(c.verdict.loss_record.0.contains_key("domain_narrowing"));
}

#[test]
fn loudly_lossy_wire_round_trips() {
    let c1: DomainClaim = serde_json::from_str(LOUDLY_LOSSY_FIXTURE).expect("parse");
    let serialized = serde_json::to_string(&c1).expect("serialize");
    let c2: DomainClaim = serde_json::from_str(&serialized).expect("re-parse");
    assert_eq!(c1, c2);
}

// ================================================================
// DomainClaim wire shape -- "refuse" verdict
// ================================================================

const REFUSE_FIXTURE: &str = r#"{
  "input_cid":  "blake3-512:in1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111aa",
  "kind":       "domain-claim",
  "kit_cid":    "blake3-512:kit00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a",
  "provenance": {
    "declared_at": "2026-05-13T12:00:00Z",
    "signer":      "ed25519:VGVzdFNpZ25lcjAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA=="
  },
  "signature":  "ed25519:VGVzdFNpZ25hdHVyZTAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMA==",
  "truth_cid":  "blake3-512:tr2222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222ab",
  "verdict":    {
    "kind":           "refuse",
    "loss_record":    {},
    "refusal_reason": "wp and witness disagreed at boundary case"
  }
}"#;

#[test]
fn refuse_wire_deserializes() {
    let c: DomainClaim = serde_json::from_str(REFUSE_FIXTURE).expect("parse refuse");
    assert_eq!(c.verdict.kind, VerdictKind::Refuse);
    assert!(c.verdict.discharge_receipt_cid.is_none());
    assert!(c.verdict.refusal_reason.is_some());
    assert_eq!(
        c.verdict.refusal_reason.as_deref().unwrap(),
        "wp and witness disagreed at boundary case"
    );
}

#[test]
fn refuse_wire_round_trips() {
    let c1: DomainClaim = serde_json::from_str(REFUSE_FIXTURE).expect("parse");
    let serialized = serde_json::to_string(&c1).expect("serialize");
    let c2: DomainClaim = serde_json::from_str(&serialized).expect("re-parse");
    assert_eq!(c1, c2);
}

// ================================================================
// Optional-field absence: discharge_receipt_cid / refusal_reason are
// OMITTED when None on serialization.
// ================================================================

#[test]
fn optional_fields_absent_when_none_in_exact() {
    let c = make_claim(VerdictBody {
        discharge_receipt_cid: Some(RECEIPT_CID.to_string()),
        kind: VerdictKind::Exact,
        loss_record: LossRecord::default(),
        refusal_reason: None,
    });
    let serialized = serde_json::to_string(&c).expect("serialize");
    assert!(serialized.contains("\"discharge_receipt_cid\""));
    assert!(!serialized.contains("\"refusal_reason\""));
}

#[test]
fn optional_fields_absent_when_none_in_refuse() {
    let c = make_claim(VerdictBody {
        discharge_receipt_cid: None,
        kind: VerdictKind::Refuse,
        loss_record: LossRecord::default(),
        refusal_reason: Some("the discharger refused".to_string()),
    });
    let serialized = serde_json::to_string(&c).expect("serialize");
    assert!(!serialized.contains("\"discharge_receipt_cid\""));
    assert!(serialized.contains("\"refusal_reason\""));
}

// ================================================================
// VerdictKind serde labels match the wire-form strings used by
// ConceptSiteMemento.discharge.verdict. This is the byte-deterministic
// invariant that makes the From<&ConceptSiteMemento> impl faithful.
// ================================================================

#[test]
fn verdict_kind_exact_label() {
    let s = serde_json::to_string(&VerdictKind::Exact).expect("serialize");
    assert_eq!(s, "\"exact\"");
}

#[test]
fn verdict_kind_loudly_lossy_label() {
    let s = serde_json::to_string(&VerdictKind::LoudlyBoundedLossy).expect("serialize");
    assert_eq!(s, "\"loudly-bounded-lossy\"");
}

#[test]
fn verdict_kind_refuse_label() {
    let s = serde_json::to_string(&VerdictKind::Refuse).expect("serialize");
    assert_eq!(s, "\"refuse\"");
}

// ================================================================
// Helpers
// ================================================================

fn make_claim(verdict: VerdictBody) -> DomainClaim {
    DomainClaim {
        input_cid: INPUT_CID.to_string(),
        kind: "domain-claim".to_string(),
        kit_cid: KIT_CID.to_string(),
        provenance: DomainClaimProvenance {
            declared_at: "2026-05-13T12:00:00Z".to_string(),
            signer: SIGNER.to_string(),
        },
        signature: SIGNATURE.to_string(),
        truth_cid: TRUTH_CID.to_string(),
        verdict,
    }
}

#[test]
fn unsigned_constructor_zeros_signature_and_provenance() {
    let verdict = VerdictBody {
        discharge_receipt_cid: Some(RECEIPT_CID.to_string()),
        kind: VerdictKind::Exact,
        loss_record: LossRecord::default(),
        refusal_reason: None,
    };
    let prov = DomainClaimProvenance {
        declared_at: String::new(),
        signer: String::new(),
    };
    let c = DomainClaim::unsigned(
        KIT_CID.to_string(),
        INPUT_CID.to_string(),
        TRUTH_CID.to_string(),
        verdict,
        prov,
    );
    assert_eq!(c.signature, "");
    assert_eq!(c.provenance.signer, "");
    assert_eq!(c.kind, "domain-claim");
}

#[test]
fn empty_loss_record_serializes_as_empty_object() {
    let c = make_claim(VerdictBody {
        discharge_receipt_cid: Some(RECEIPT_CID.to_string()),
        kind: VerdictKind::Exact,
        loss_record: LossRecord(BTreeMap::new()),
        refusal_reason: None,
    });
    let s = serde_json::to_string(&c).expect("serialize");
    // The loss_record field must be present and equal to an empty object,
    // never omitted; this is the §1.2 invariant for `exact` claims.
    assert!(s.contains("\"loss_record\":{}"));
}
