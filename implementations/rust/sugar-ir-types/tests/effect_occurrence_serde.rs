// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip serde and classification tests for EffectOccurrence.
//
// Source of truth:
//   protocol/specs/2026-05-13-effect-occurrence-memento.md

use serde_json::{json, Value};
use sugar_ir_types::{Classification, EffectOccurrence, OccurrenceKind, OccurrenceRole};

fn fixture(kind: &str, args: Value, discharge_key: &str, locator: Value, role: &str) -> String {
    json!({
        "args": args,
        "discharge_key": discharge_key,
        "locator": locator,
        "occurrence_kind": kind,
        "role": role,
        "signature_cid": format!("blake3-512:{}-signature", kind.to_ascii_lowercase()),
    })
    .to_string()
}

fn round_trip(s: &str) -> EffectOccurrence {
    let occurrence: EffectOccurrence = serde_json::from_str(s).expect("parse EffectOccurrence");
    let serialized = serde_json::to_string(&occurrence).expect("serialize EffectOccurrence");
    let reparsed: EffectOccurrence = serde_json::from_str(&serialized).expect("re-parse");
    assert_eq!(occurrence, reparsed);
    occurrence
}

#[test]
fn occurrence_kind_round_trips_canonical_and_extension_labels() {
    let canonical = [
        (OccurrenceKind::Reads, "Reads"),
        (OccurrenceKind::Writes, "Writes"),
        (OccurrenceKind::Io, "Io"),
        (OccurrenceKind::Panics, "Panics"),
        (OccurrenceKind::OpaqueLoop, "OpaqueLoop"),
        (OccurrenceKind::UnresolvedCall, "UnresolvedCall"),
        (OccurrenceKind::AtomicAccess, "AtomicAccess"),
        (OccurrenceKind::EarlyReturn, "EarlyReturn"),
        (OccurrenceKind::Unsafe, "Unsafe"),
        (OccurrenceKind::ClosureCapture, "ClosureCapture"),
        (OccurrenceKind::PinnedReference, "PinnedReference"),
        (OccurrenceKind::RawPointerProvenance, "RawPointerProvenance"),
        (OccurrenceKind::PossibleAliasing, "PossibleAliasing"),
        (OccurrenceKind::Drop, "Drop"),
    ];

    for (variant, wire) in canonical {
        assert_eq!(OccurrenceKind::from_str(wire), Some(variant.clone()));
        assert_eq!(variant.to_string(), wire);
        let encoded = serde_json::to_string(&variant).expect("serialize kind");
        assert_eq!(encoded, format!("\"{}\"", wire));
        let decoded: OccurrenceKind = serde_json::from_str(&encoded).expect("decode kind");
        assert_eq!(decoded, variant);
    }

    let extension: OccurrenceKind =
        serde_json::from_str("\"rust:BorrowActivation\"").expect("decode extension");
    assert_eq!(
        extension,
        OccurrenceKind::Extension("rust:BorrowActivation".to_string())
    );
    assert_eq!(extension.to_string(), "rust:BorrowActivation");
}

#[test]
fn occurrence_kind_rejects_bare_unknown() {
    // Per spec §3 + admissibility-spine namespaced-extensions rule, a bare
    // unknown (no `:` separator) MUST fail closed at deserialization. The
    // classifier and CCP rely on knowing whether an occurrence is
    // admissible; a bare unknown that silently became Extension(s) would
    // fall through with no policy gate.
    let result: Result<OccurrenceKind, _> = serde_json::from_str("\"WeirdKind\"");
    assert!(
        result.is_err(),
        "bare unknown occurrence_kind should fail closed, got {:?}",
        result
    );

    // Empty-segment namespaced strings ("acme:" or ":kind") also fail.
    let result_empty_ns: Result<OccurrenceKind, _> = serde_json::from_str("\":kind\"");
    assert!(result_empty_ns.is_err());
    let result_empty_kind: Result<OccurrenceKind, _> = serde_json::from_str("\"acme:\"");
    assert!(result_empty_kind.is_err());
}

#[test]
fn occurrence_role_round_trips_canonical_labels() {
    let canonical = [
        (OccurrenceRole::Pre, "pre"),
        (OccurrenceRole::Post, "post"),
        (OccurrenceRole::Invariant, "invariant"),
        (OccurrenceRole::Body, "body"),
        (OccurrenceRole::Exceptional, "exceptional"),
    ];

    for (variant, wire) in canonical {
        let encoded = serde_json::to_string(&variant).expect("serialize role");
        assert_eq!(encoded, format!("\"{}\"", wire));
        let decoded: OccurrenceRole = serde_json::from_str(&encoded).expect("decode role");
        assert_eq!(decoded, variant);
    }
}

#[test]
fn spec_section_3_examples_round_trip() {
    let examples = [
        fixture(
            "Reads",
            json!({"target": "x"}),
            "read:x",
            json!({"column": 12, "file": "src/lib.rs", "line": 42}),
            "body",
        ),
        fixture(
            "Writes",
            json!({"target": "x"}),
            "write:x",
            json!({"column": 8, "file": "src/lib.rs", "line": 43}),
            "body",
        ),
        fixture(
            "Io",
            json!({"channel": "filesystem", "operation": "read"}),
            "io:filesystem:read",
            json!({"file": "src/fs.rs", "symbol": "load_config"}),
            "body",
        ),
        fixture(
            "Panics",
            json!({"condition": "index_out_of_bounds", "mode": "panic"}),
            "panic:index_out_of_bounds",
            json!({"column": 16, "file": "src/lib.rs", "line": 51}),
            "exceptional",
        ),
        fixture(
            "OpaqueLoop",
            json!({"loop_cid": "blake3-512:loop-site"}),
            "opaque-loop:blake3-512:loop-site",
            json!({"block": "bb7", "file": "src/lib.rs", "line": 64}),
            "invariant",
        ),
        fixture(
            "UnresolvedCall",
            json!({"name": "ops.decrypt", "resolution": "indirect"}),
            "unresolved-call:ops.decrypt",
            json!({"file": "src/crypto.c", "line": 88}),
            "body",
        ),
        fixture(
            "AtomicAccess",
            json!({"kind": "Rmw", "ordering": "SeqCst", "target": "counter"}),
            "atomic:counter:Rmw:SeqCst",
            json!({"column": 20, "file": "src/lib.rs", "line": 101}),
            "body",
        ),
        fixture(
            "EarlyReturn",
            json!({"try_cid": "blake3-512:try-site"}),
            "early-return:blake3-512:try-site",
            json!({"column": 24, "file": "src/parse.rs", "line": 22}),
            "exceptional",
        ),
        fixture(
            "Unsafe",
            json!({"kind": "unsafe-block"}),
            "unsafe:unsafe-block",
            json!({"file": "src/ffi.rs", "line": 30}),
            "body",
        ),
        fixture(
            "ClosureCapture",
            json!({"body_fn_cid": "blake3-512:closure-body", "n_captures": 2}),
            "closure-capture:blake3-512:closure-body:2",
            json!({"file": "src/iter.rs", "line": 17}),
            "body",
        ),
        fixture(
            "PinnedReference",
            json!({"target": "self.buf"}),
            "pinned-reference:self.buf",
            json!({"file": "src/future.rs", "line": 88}),
            "body",
        ),
        fixture(
            "RawPointerProvenance",
            json!({"mutable": true, "target": "buf"}),
            "raw-pointer-provenance:buf:mut",
            json!({"file": "src/alloc.rs", "line": 41}),
            "body",
        ),
        fixture(
            "PossibleAliasing",
            json!({"formals": ["dst", "src"]}),
            "possible-aliasing:dst,src",
            json!({"file": "src/copy.rs", "line": 14}),
            "pre",
        ),
        fixture(
            "Drop",
            json!({"name": "std::vec::Vec<u8>"}),
            "drop:std::vec::Vec<u8>",
            json!({"file": "src/buf.rs", "line": 73}),
            "body",
        ),
    ];

    for example in examples {
        round_trip(&example);
    }
}

#[test]
fn classify_matches_section_4_table() {
    let cases = [
        ("Reads", json!({"target": "x"}), Classification::Block),
        ("Writes", json!({"target": "x"}), Classification::Block),
        (
            "Io",
            json!({"channel": "filesystem", "operation": "read"}),
            Classification::Block,
        ),
        (
            "Panics",
            json!({"condition": "index_out_of_bounds", "mode": "panic"}),
            Classification::Block,
        ),
        (
            "OpaqueLoop",
            json!({"loop_cid": "blake3-512:loop-site"}),
            Classification::MementoRequired,
        ),
        (
            "UnresolvedCall",
            json!({"name": "ops.decrypt", "resolution": "indirect"}),
            Classification::MementoRequired,
        ),
        (
            "AtomicAccess",
            json!({"kind": "Rmw", "ordering": null, "target": "counter"}),
            Classification::MementoRequired,
        ),
        (
            "AtomicAccess",
            json!({"kind": "Rmw", "ordering": "SeqCst", "target": "counter"}),
            Classification::InformationalDischargeable,
        ),
        (
            "EarlyReturn",
            json!({"try_cid": "blake3-512:try-site"}),
            Classification::MementoRequired,
        ),
        (
            "Unsafe",
            json!({"kind": "unsafe-block"}),
            Classification::Block,
        ),
        (
            "ClosureCapture",
            json!({"body_fn_cid": "blake3-512:closure-body", "n_captures": 2}),
            Classification::MementoRequired,
        ),
        (
            "PinnedReference",
            json!({"target": "self.buf"}),
            Classification::MementoRequired,
        ),
        (
            "RawPointerProvenance",
            json!({"mutable": true, "target": "buf"}),
            Classification::MementoRequired,
        ),
        (
            "PossibleAliasing",
            json!({"formals": ["dst", "src"]}),
            Classification::MementoRequired,
        ),
        (
            "Drop",
            json!({"drop_kind": "UserCode", "name": "std::fs::File"}),
            Classification::MementoRequired,
        ),
        (
            "Drop",
            json!({"drop_kind": "Trivial", "name": "u64"}),
            Classification::InformationalDischargeable,
        ),
        (
            "Drop",
            json!({"drop_kind": "Structural", "name": "std::vec::Vec<u8>"}),
            Classification::InformationalDischargeable,
        ),
    ];

    for (kind, args, classification) in cases {
        let occurrence = round_trip(&fixture(kind, args, "key", json!({}), "body"));
        assert_eq!(occurrence.classify(), classification, "{kind}");
    }
}

#[test]
fn occurrence_kind_rejects_multi_colon() {
    // Spec: extension labels are `<namespace>:<kind>` with EXACTLY one colon.
    let result: Result<OccurrenceKind, _> = serde_json::from_str("\"a:b:c\"");
    assert!(
        result.is_err(),
        "multi-colon should fail closed, got {:?}",
        result
    );
}
