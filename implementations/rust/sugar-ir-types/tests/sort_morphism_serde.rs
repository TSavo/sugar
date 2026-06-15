// SPDX-License-Identifier: Apache-2.0
//
// Round-trip serde and CID recompute tests for SortMorphismMemento.
//
// Source of truth:
//   protocol/specs/2026-05-13-sort-morphism-memento.md §1, §7, §9

use serde_json::{json, Value as JsonValue};
use std::sync::Arc;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CanonValue};
use sugar_ir_types::{MorphismDirection, SortMorphismMemento};

const RUST_SIG_CID: &str = "blake3-512:11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
const JAVA_SIG_CID: &str = "blake3-512:55555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555";
const PYTHON_SIG_CID: &str = "blake3-512:77777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777";
const RUST_I64_SORT_CID: &str = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const JAVA_LONG_SORT_CID: &str = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const PYTHON_INT_SORT_CID: &str = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const RUST_I32_SORT_CID: &str = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
const RUST_I16_SORT_CID: &str = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";

#[test]
fn rust_i64_java_long_round_trips_and_recomputes_cid() {
    let json = rust_i64_java_long_json();
    let m: SortMorphismMemento = serde_json::from_value(json).expect("parse rust i64 to java long");

    assert_eq!(m.header.direction, MorphismDirection::Bidirectional);
    assert_eq!(m.header.kind, "sort-morphism");
    assert_eq!(m.header.precision_loss, "none");
    assert_eq!(m.header.range_loss, "none");
    assert_eq!(m.header.representation_constraints.len(), 3);
    assert!(m.header.runtime_guards.is_empty());

    assert_round_trip_and_cid(&m);
}

#[test]
fn rust_i64_python_int_round_trips_and_recomputes_cid() {
    let json = rust_i64_python_int_json();
    let m: SortMorphismMemento =
        serde_json::from_value(json).expect("parse rust i64 to python int");

    assert_eq!(m.header.direction, MorphismDirection::LeftToRight);
    assert_eq!(m.header.precision_loss, "none");
    assert_eq!(m.header.range_loss, "widening");
    assert_eq!(m.header.representation_constraints.len(), 1);
    assert!(m.header.runtime_guards.is_empty());

    assert_round_trip_and_cid(&m);
}

#[test]
fn rust_i32_rust_i16_round_trips_and_recomputes_cid() {
    let json = rust_i32_rust_i16_json();
    let m: SortMorphismMemento = serde_json::from_value(json).expect("parse rust i32 to rust i16");

    assert_eq!(m.header.direction, MorphismDirection::LeftToRight);
    assert_eq!(m.header.precision_loss, "none");
    assert_eq!(m.header.range_loss, "narrowing");
    assert_eq!(m.header.runtime_guards.len(), 1);
    assert_eq!(
        m.header.runtime_guards[0].failure_mode.as_deref(),
        Some("panic")
    );

    assert_round_trip_and_cid(&m);
}

fn assert_round_trip_and_cid(m: &SortMorphismMemento) {
    let serialized = serde_json::to_string(m).expect("serialize");
    let reparsed: SortMorphismMemento = serde_json::from_str(&serialized).expect("re-parse");
    assert_eq!(*m, reparsed);
    assert_eq!(m.header.cid, recompute_sort_morphism_cid(m));
}

fn with_cid(mut value: JsonValue) -> JsonValue {
    let m: SortMorphismMemento =
        serde_json::from_value(value.clone()).expect("fixture parses before cid pinning");
    let cid = recompute_sort_morphism_cid(&m);
    value["header"]["cid"] = JsonValue::String(cid);
    value
}

fn rust_i64_java_long_json() -> JsonValue {
    with_cid(json!({
      "envelope": {
        "declaredAt": "2026-05-13T17:00:00Z",
        "signature": "ed25519:UNSIGNED_DEV_ONLY",
        "signer": "ed25519:foundation-v0"
      },
      "header": {
        "cid": "",
        "direction": "bidirectional",
        "kind": "sort-morphism",
        "precision_loss": "none",
        "range_loss": "none",
        "representation_constraints": [
          {"kind": "bit-width-equal", "param": 64},
          {"kind": "signedness-equal", "param": "signed"},
          {"kind": "two's-complement", "param": true}
        ],
        "runtime_guards": [],
        "schemaVersion": "1",
        "source_language_signature_cid": RUST_SIG_CID,
        "source_sort_cid": RUST_I64_SORT_CID,
        "target_language_signature_cid": JAVA_SIG_CID,
        "target_sort_cid": JAVA_LONG_SORT_CID
      },
      "metadata": {
        "note": "Both sorts denote signed 64-bit two's-complement integers under their respective pinned language signatures (rust 1.75 LP64 / java 17).",
        "source_url": "menagerie/rust-language-signature/specs/sort_int.spec.json"
      }
    }))
}

fn rust_i64_python_int_json() -> JsonValue {
    with_cid(json!({
      "envelope": {
        "declaredAt": "2026-05-13T17:05:00Z",
        "signature": "ed25519:UNSIGNED_DEV_ONLY",
        "signer": "ed25519:foundation-v0"
      },
      "header": {
        "cid": "",
        "direction": "left-to-right",
        "kind": "sort-morphism",
        "precision_loss": "none",
        "range_loss": "widening",
        "representation_constraints": [
          {"kind": "two's-complement", "param": {"source_bits": 64}}
        ],
        "runtime_guards": [],
        "schemaVersion": "1",
        "source_language_signature_cid": RUST_SIG_CID,
        "source_sort_cid": RUST_I64_SORT_CID,
        "target_language_signature_cid": PYTHON_SIG_CID,
        "target_sort_cid": PYTHON_INT_SORT_CID
      },
      "metadata": {
        "note": "The reverse direction is narrowing and requires a separate guarded morphism. The current Python draft signature records Python values in sort_value.spec.json; a precise int sort can refine that target CID.",
        "source_url": "menagerie/python-language-signature/specs/sort_value.spec.json"
      }
    }))
}

fn rust_i32_rust_i16_json() -> JsonValue {
    with_cid(json!({
      "envelope": {
        "declaredAt": "2026-05-13T17:10:00Z",
        "signature": "ed25519:UNSIGNED_DEV_ONLY",
        "signer": "ed25519:foundation-v0"
      },
      "header": {
        "cid": "",
        "direction": "left-to-right",
        "kind": "sort-morphism",
        "precision_loss": "none",
        "range_loss": "narrowing",
        "representation_constraints": [
          {"kind": "two's-complement", "param": {"source_bits": 32, "target_bits": 16}}
        ],
        "runtime_guards": [
          {
            "failure_mode": "panic",
            "kind": "range-check",
            "predicate": "source_value >= -32768 && source_value <= 32767"
          }
        ],
        "schemaVersion": "1",
        "source_language_signature_cid": RUST_SIG_CID,
        "source_sort_cid": RUST_I32_SORT_CID,
        "target_language_signature_cid": RUST_SIG_CID,
        "target_sort_cid": RUST_I16_SORT_CID
      },
      "metadata": {
        "note": "The range-check makes failed narrowing explicit. A consumer that cannot emit or prove the guard must refuse. Source and target language signatures are identical (both rust 1.75) since this is an intra-language morphism.",
        "source_url": "menagerie/rust-language-signature/specs/sort_int.spec.json"
      }
    }))
}

fn recompute_sort_morphism_cid(m: &SortMorphismMemento) -> String {
    let header = json!({
        "direction": m.header.direction,
        "kind": m.header.kind,
        "precision_loss": m.header.precision_loss,
        "range_loss": m.header.range_loss,
        "representation_constraints": m.header.representation_constraints,
        "runtime_guards": m.header.runtime_guards,
        "schemaVersion": m.header.schema_version,
        "source_language_signature_cid": m.header.source_language_signature_cid,
        "source_sort_cid": m.header.source_sort_cid,
        "target_language_signature_cid": m.header.target_language_signature_cid,
        "target_sort_cid": m.header.target_sort_cid
    });
    let canonical = json_to_canonical(&header);
    blake3_512_of(encode_jcs(&canonical).as_bytes())
}

fn json_to_canonical(value: &JsonValue) -> Arc<CanonValue> {
    match value {
        JsonValue::Null => CanonValue::null(),
        JsonValue::Bool(b) => CanonValue::boolean(*b),
        JsonValue::Number(n) => {
            if let Some(i) = n.as_i64() {
                CanonValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                CanonValue::integer(i128::from(u))
            } else {
                panic!("fixture numbers must be integers")
            }
        }
        JsonValue::String(s) => CanonValue::string(s.clone()),
        JsonValue::Array(values) => {
            CanonValue::array(values.iter().map(json_to_canonical).collect())
        }
        JsonValue::Object(map) => {
            let entries: Vec<_> = map
                .iter()
                .map(|(key, value)| (key.clone(), json_to_canonical(value)))
                .collect();
            CanonValue::object(entries)
        }
    }
}
