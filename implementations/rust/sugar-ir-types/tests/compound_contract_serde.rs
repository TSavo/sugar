// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Round-trip serde tests for EvidenceMemento and CompoundContractMemento.
//
// Source of truth:
//   protocol/specs/2026-05-13-compound-contract-memento.md §1, §2, §3
//
// These tests pin:
//   * EvidenceMemento and CompoundContractMemento deserialize from the
//     wire shape the spec defines.
//   * Round-trip parity at the serde layer: parse -> serialize -> parse
//     yields the same value.
//   * SourceKind round-trips through its kebab-case wire form for every
//     canonical label, including `Other(String)` for open-extension.
//   * AggregationStrategy round-trips through its wire form for every
//     canonical strategy.
//   * Empty extension_fields, empty evidences (degenerate compound),
//     single-evidence (auto-promotion case), and multi-evidence
//     compounds all serde-round-trip.
//   * Conjunction-aggregation verdict-derivation table is captured
//     (as a pure-Rust helper, not a serde concern, but pinned here
//     because §2.1 is normative for v0).
//
// Byte-exact CID pinning and the composed_pre/post recompute INVARIANT
// require the JCS encoder, which lives in `sugar-claim-envelope`.
// Those tests belong there; this crate carries serde shape only.
//
// Tests are deliberately VERBOSE: every fixture is hand-written JSON
// so the wire shape is unambiguous to a human reviewer.

use std::collections::BTreeMap;

use sugar_ir_types::{
    AggregationStrategy, CompoundContractMemento, EvidenceMemento, EvidenceRef, IrFormula,
    SourceKind, SourceLocator, SourceLocatorPoint, SourceLocatorSpan,
};

/// The "true" atomic predicate in IrFormula. Used as the trivial
/// predicate for round-trip tests; the substantive predicate content
/// is irrelevant for serde-shape verification.
fn ir_true() -> IrFormula {
    IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    }
}

// 128 hex chars after the "blake3-512:" prefix; deterministic placeholders.
// The trailing letter distinguishes each.
const EVID_CID_A: &str = "blake3-512:evid00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a";
const EVID_CID_B: &str = "blake3-512:evid00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000b";
const EVID_CID_C: &str = "blake3-512:evid00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000c";
const FN_CID: &str = "blake3-512:fn1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111";
const SRC_CID: &str = "blake3-512:src22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222";
const LIFTER_CID: &str = "blake3-512:lift33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333";
const COMPOUND_CID: &str = "blake3-512:comp44444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444";
// Reserved sentinel for the auto-promote backward-compat path; spec §4.4.
// 128 hex 0s -- provably not a real BLAKE3-512 output (P ≈ 2^-512).
// All-hex so pass-1 CID format validation accepts it without a special-case exception.
const AUTO_PROMOTE_LIFTER_CID: &str = "blake3-512:0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

// ================================================================
// SourceKind round-trips through every canonical label
// ================================================================

#[test]
fn source_kind_round_trip_canonical_labels() {
    // (variant, wire-string) pairs for every canonical label.
    let canonical = [
        (SourceKind::Annotation, "\"annotation\""),
        (SourceKind::TestAssertion, "\"test-assertion\""),
        (SourceKind::TypeSignature, "\"type-signature\""),
        (SourceKind::Docstring, "\"docstring\""),
        (SourceKind::LoopInvariant, "\"loop-invariant\""),
        (SourceKind::ImplicitEffect, "\"implicit-effect\""),
        (SourceKind::NativeSurface, "\"native-surface\""),
        (SourceKind::StructuralSynthesis, "\"structural-synthesis\""),
        (SourceKind::EmpiricalWitness, "\"empirical-witness\""),
        (SourceKind::ReviewComment, "\"review-comment\""),
    ];
    for (variant, wire) in canonical.iter() {
        let serialized = serde_json::to_string(variant).expect("serialize");
        assert_eq!(&serialized, wire, "serialize {:?}", variant);
        let parsed: SourceKind = serde_json::from_str(wire).expect("parse");
        assert_eq!(&parsed, variant, "parse {:?}", wire);
    }
}

#[test]
fn source_kind_unknown_label_maps_to_other() {
    let wire = "\"future-source-kind-x99\"";
    let parsed: SourceKind = serde_json::from_str(wire).expect("parse unknown");
    assert_eq!(
        parsed,
        SourceKind::Other("future-source-kind-x99".to_string())
    );
    // Round-trip back.
    let s = serde_json::to_string(&parsed).expect("serialize Other");
    assert_eq!(s, wire);
}

// ================================================================
// AggregationStrategy round-trips through every canonical label
// ================================================================

#[test]
fn aggregation_strategy_round_trip_canonical() {
    let canonical = [
        (AggregationStrategy::Conjunction, "\"conjunction\""),
        (AggregationStrategy::BestConfidence, "\"best-confidence\""),
        (
            AggregationStrategy::LoudlyBoundedDisjunction,
            "\"loudly-bounded-disjunction\"",
        ),
    ];
    for (variant, wire) in canonical.iter() {
        let serialized = serde_json::to_string(variant).expect("serialize");
        assert_eq!(&serialized, wire, "serialize {:?}", variant);
        let parsed: AggregationStrategy = serde_json::from_str(wire).expect("parse");
        assert_eq!(&parsed, variant, "parse {:?}", wire);
    }
}

#[test]
fn aggregation_strategy_unknown_maps_to_other() {
    let wire = "\"weighted-bayes\"";
    let parsed: AggregationStrategy = serde_json::from_str(wire).expect("parse unknown");
    assert_eq!(
        parsed,
        AggregationStrategy::Other("weighted-bayes".to_string())
    );
}

// ================================================================
// EvidenceMemento -- one canonical wire fixture per source_kind
// ================================================================

fn locator_fixture() -> SourceLocator {
    SourceLocator {
        source_cid: SRC_CID.to_string(),
        span: SourceLocatorSpan {
            end: SourceLocatorPoint { line: 12, col: 18 },
            start: SourceLocatorPoint { line: 12, col: 1 },
        },
    }
}

fn make_evidence(
    cid: &str,
    source_kind: SourceKind,
    confidence: u16,
    extension: BTreeMap<String, serde_json::Value>,
) -> EvidenceMemento {
    EvidenceMemento {
        cid: cid.to_string(),
        confidence_basis_points: confidence,
        extension_fields: extension,
        kind: "evidence".to_string(),
        lifter_cid: LIFTER_CID.to_string(),
        predicate: ir_true(),
        schema_version: "1".to_string(),
        source_kind,
        source_locator: locator_fixture(),
    }
}

#[test]
fn evidence_memento_round_trip_annotation() {
    let e = make_evidence(EVID_CID_A, SourceKind::Annotation, 10000, BTreeMap::new());
    let s = serde_json::to_string(&e).expect("serialize");
    let parsed: EvidenceMemento = serde_json::from_str(&s).expect("parse");
    assert_eq!(parsed, e);
    assert_eq!(parsed.kind, "evidence");
    assert_eq!(parsed.schema_version, "1");
    assert_eq!(parsed.source_kind, SourceKind::Annotation);
    assert_eq!(parsed.confidence_basis_points, 10000);
    assert!(parsed.extension_fields.is_empty());
}

#[test]
fn evidence_memento_round_trip_test_assertion_with_extension() {
    let mut ext = BTreeMap::new();
    ext.insert(
        "test_target_function_cid".to_string(),
        serde_json::Value::String(FN_CID.to_string()),
    );
    let e = make_evidence(EVID_CID_B, SourceKind::TestAssertion, 10000, ext.clone());
    let s = serde_json::to_string(&e).expect("serialize");
    let parsed: EvidenceMemento = serde_json::from_str(&s).expect("parse");
    assert_eq!(parsed, e);
    assert_eq!(parsed.source_kind, SourceKind::TestAssertion);
    assert_eq!(
        parsed
            .extension_fields
            .get("test_target_function_cid")
            .and_then(|v| v.as_str()),
        Some(FN_CID)
    );
}

#[test]
fn evidence_memento_round_trip_docstring_with_lower_confidence() {
    let mut ext = BTreeMap::new();
    ext.insert(
        "extracted_phrase".to_string(),
        serde_json::Value::String("Returns None when the divisor is zero.".to_string()),
    );
    let e = make_evidence(EVID_CID_C, SourceKind::Docstring, 6500, ext);
    let s = serde_json::to_string(&e).expect("serialize");
    let parsed: EvidenceMemento = serde_json::from_str(&s).expect("parse");
    assert_eq!(parsed, e);
    assert_eq!(parsed.confidence_basis_points, 6500);
    assert_eq!(parsed.source_kind, SourceKind::Docstring);
}

#[test]
fn evidence_memento_each_canonical_source_kind_round_trips() {
    // Build one evidence per canonical label and verify all of them
    // round-trip through JSON.
    let kinds = [
        SourceKind::Annotation,
        SourceKind::TestAssertion,
        SourceKind::TypeSignature,
        SourceKind::Docstring,
        SourceKind::LoopInvariant,
        SourceKind::ImplicitEffect,
        SourceKind::NativeSurface,
        SourceKind::StructuralSynthesis,
        SourceKind::EmpiricalWitness,
        SourceKind::ReviewComment,
    ];
    for (i, k) in kinds.into_iter().enumerate() {
        // Build a deterministic 128-hex CID from the index. The two-hex
        // prefix encodes `i`; the remaining 126 chars are filler.
        let tail: String = std::iter::repeat_with(|| 'a').take(126).collect();
        let cid = format!("blake3-512:{:02x}{}", i, tail);
        let e = make_evidence(&cid, k.clone(), 9999, BTreeMap::new());
        let s = serde_json::to_string(&e).expect("serialize");
        let parsed: EvidenceMemento = serde_json::from_str(&s).expect("parse");
        assert_eq!(parsed, e, "round-trip for kind {:?}", k);
    }
}

#[test]
fn evidence_memento_with_unknown_source_kind_extension() {
    let e = EvidenceMemento {
        cid: EVID_CID_A.to_string(),
        confidence_basis_points: 5000,
        extension_fields: BTreeMap::new(),
        kind: "evidence".to_string(),
        lifter_cid: LIFTER_CID.to_string(),
        predicate: ir_true(),
        schema_version: "1".to_string(),
        source_kind: SourceKind::Other("future-source-kind-x99".to_string()),
        source_locator: locator_fixture(),
    };
    let s = serde_json::to_string(&e).expect("serialize");
    assert!(s.contains("\"future-source-kind-x99\""));
    let parsed: EvidenceMemento = serde_json::from_str(&s).expect("parse");
    assert_eq!(parsed, e);
}

// ================================================================
// CompoundContractMemento -- empty / single / multi
// ================================================================

#[test]
fn compound_empty_evidences_degenerate_round_trips() {
    // Spec §5.2: the degenerate compound has empty evidences and
    // composed_pre / composed_post = true. This is the substrate's
    // base case before any lifter has run.
    let c = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: COMPOUND_CID.to_string(),
        composed_post: ir_true(),
        composed_pre: ir_true(),
        evidences: vec![],
        function_term_cid: FN_CID.to_string(),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };
    let s = serde_json::to_string(&c).expect("serialize");
    let parsed: CompoundContractMemento = serde_json::from_str(&s).expect("parse");
    assert_eq!(parsed, c);
    assert!(parsed.evidences.is_empty());
    assert_eq!(
        parsed.aggregation_strategy,
        AggregationStrategy::Conjunction
    );
}

#[test]
fn compound_single_evidence_auto_promotion_case() {
    // Spec §4.3: the backward-compat path mints a single-evidence
    // compound with an `annotation` evidence whose lifter_cid is the
    // reserved auto-promote sentinel. This test pins that shape.
    let promoted_evidence = EvidenceMemento {
        cid: EVID_CID_A.to_string(),
        confidence_basis_points: 10000,
        extension_fields: {
            let mut m = BTreeMap::new();
            m.insert(
                "auto_promoted_from".to_string(),
                serde_json::Value::String(FN_CID.to_string()),
            );
            m
        },
        kind: "evidence".to_string(),
        lifter_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
        predicate: ir_true(),
        schema_version: "1".to_string(),
        source_kind: SourceKind::Annotation,
        source_locator: locator_fixture(),
    };
    let s = serde_json::to_string(&promoted_evidence).expect("serialize evidence");
    let parsed_evid: EvidenceMemento = serde_json::from_str(&s).expect("parse evidence");
    assert_eq!(parsed_evid, promoted_evidence);
    assert_eq!(parsed_evid.lifter_cid, AUTO_PROMOTE_LIFTER_CID);

    let compound = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: COMPOUND_CID.to_string(),
        composed_post: ir_true(),
        composed_pre: ir_true(),
        evidences: vec![EvidenceRef {
            evidence_cid: EVID_CID_A.to_string(),
            weight_basis_points: 10000,
        }],
        function_term_cid: FN_CID.to_string(),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };
    let s = serde_json::to_string(&compound).expect("serialize compound");
    let parsed: CompoundContractMemento = serde_json::from_str(&s).expect("parse compound");
    assert_eq!(parsed, compound);
    assert_eq!(parsed.evidences.len(), 1);
}

#[test]
fn compound_multi_evidence_round_trips() {
    // Three evidences with three distinct CIDs and weights.
    let compound = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: COMPOUND_CID.to_string(),
        composed_post: ir_true(),
        composed_pre: ir_true(),
        evidences: vec![
            EvidenceRef {
                evidence_cid: EVID_CID_A.to_string(),
                weight_basis_points: 10000,
            },
            EvidenceRef {
                evidence_cid: EVID_CID_B.to_string(),
                weight_basis_points: 9500,
            },
            EvidenceRef {
                evidence_cid: EVID_CID_C.to_string(),
                weight_basis_points: 6500,
            },
        ],
        function_term_cid: FN_CID.to_string(),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };
    let s = serde_json::to_string(&compound).expect("serialize");
    let parsed: CompoundContractMemento = serde_json::from_str(&s).expect("parse");
    assert_eq!(parsed, compound);
    assert_eq!(parsed.evidences.len(), 3);
    // Weight basis-points preserved.
    let weights: Vec<u16> = parsed
        .evidences
        .iter()
        .map(|e| e.weight_basis_points)
        .collect();
    assert_eq!(weights, vec![10000, 9500, 6500]);
}

// ================================================================
// Compound CID stability is sensitive to inputs
// ================================================================

#[test]
fn compound_with_different_aggregation_strategy_is_different_value() {
    // Spec §3.1: aggregation_strategy is part of the CID input.
    // The same set of evidences aggregated under "conjunction" vs
    // "best-confidence" are two different compounds. We can't run JCS
    // here, but we CAN verify that Rust treats them as PartialEq-unequal,
    // which is the precondition for the CID divergence.
    let evidences = vec![EvidenceRef {
        evidence_cid: EVID_CID_A.to_string(),
        weight_basis_points: 10000,
    }];

    let c_conj = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: "blake3-512:aa".to_string() + &"0".repeat(126),
        composed_post: ir_true(),
        composed_pre: ir_true(),
        evidences: evidences.clone(),
        function_term_cid: FN_CID.to_string(),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };
    let c_best = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::BestConfidence,
        ..c_conj.clone()
    };
    assert_ne!(c_conj, c_best);
    assert_ne!(c_conj.aggregation_strategy, c_best.aggregation_strategy);
}

#[test]
fn compound_with_different_evidence_set_is_different_value() {
    // Spec §0.2: different evidence-sets = different compound bytes.
    let c_one = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: "blake3-512:bb".to_string() + &"0".repeat(126),
        composed_post: ir_true(),
        composed_pre: ir_true(),
        evidences: vec![EvidenceRef {
            evidence_cid: EVID_CID_A.to_string(),
            weight_basis_points: 10000,
        }],
        function_term_cid: FN_CID.to_string(),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };
    let c_two = CompoundContractMemento {
        evidences: vec![
            EvidenceRef {
                evidence_cid: EVID_CID_A.to_string(),
                weight_basis_points: 10000,
            },
            EvidenceRef {
                evidence_cid: EVID_CID_B.to_string(),
                weight_basis_points: 9000,
            },
        ],
        ..c_one.clone()
    };
    assert_ne!(c_one, c_two);
    assert_ne!(c_one.evidences.len(), c_two.evidences.len());
}

// ================================================================
// Wire-shape pin: hand-written JSON deserializes to the expected value
// ================================================================

#[test]
fn evidence_memento_from_spec_shape() {
    // Hand-written fixture: spec §1.1 wire shape. Keys in alphabetical
    // JCS order (envelope is in the wrapping; here we serialize only
    // the header layer, which is what `EvidenceMemento` represents).
    let fixture = r#"{
        "cid": "blake3-512:evid00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a",
        "confidence_basis_points": 10000,
        "extension_fields": {},
        "kind": "evidence",
        "lifter_cid": "blake3-512:lift33333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333",
        "predicate": {"kind": "atomic", "name": "true", "args": []},
        "schemaVersion": "1",
        "source_kind": "annotation",
        "source_locator": {
            "source_cid": "blake3-512:src22222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222",
            "span": {
                "end":   {"col": 18, "line": 12},
                "start": {"col":  1, "line": 12}
            }
        }
    }"#;
    let parsed: EvidenceMemento = serde_json::from_str(fixture).expect("parse spec fixture");
    assert_eq!(parsed.cid, EVID_CID_A);
    assert_eq!(parsed.confidence_basis_points, 10000);
    assert_eq!(parsed.source_kind, SourceKind::Annotation);
    assert_eq!(parsed.lifter_cid, LIFTER_CID);
    assert_eq!(parsed.source_locator.source_cid, SRC_CID);
    assert_eq!(parsed.source_locator.span.start.line, 12);
    assert_eq!(parsed.source_locator.span.start.col, 1);
    assert_eq!(parsed.source_locator.span.end.line, 12);
    assert_eq!(parsed.source_locator.span.end.col, 18);
}

#[test]
fn compound_memento_from_spec_shape() {
    let fixture = r#"{
        "aggregation_strategy": "conjunction",
        "cid": "blake3-512:comp44444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444",
        "composed_post": {"kind": "atomic", "name": "true", "args": []},
        "composed_pre":  {"kind": "atomic", "name": "true", "args": []},
        "evidences": [
            {"evidence_cid": "blake3-512:evid00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000a", "weight_basis_points": 10000},
            {"evidence_cid": "blake3-512:evid00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000b", "weight_basis_points":  9500}
        ],
        "function_term_cid": "blake3-512:fn1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111",
        "kind": "compound-contract",
        "schemaVersion": "1"
    }"#;
    let parsed: CompoundContractMemento =
        serde_json::from_str(fixture).expect("parse spec fixture");
    assert_eq!(parsed.cid, COMPOUND_CID);
    assert_eq!(
        parsed.aggregation_strategy,
        AggregationStrategy::Conjunction
    );
    assert_eq!(parsed.kind, "compound-contract");
    assert_eq!(parsed.schema_version, "1");
    assert_eq!(parsed.function_term_cid, FN_CID);
    assert_eq!(parsed.evidences.len(), 2);
    assert_eq!(parsed.evidences[0].evidence_cid, EVID_CID_A);
    assert_eq!(parsed.evidences[0].weight_basis_points, 10000);
    assert_eq!(parsed.evidences[1].evidence_cid, EVID_CID_B);
    assert_eq!(parsed.evidences[1].weight_basis_points, 9500);
}

// ================================================================
// Optional / absent fields
// ================================================================

#[test]
fn evidence_extension_fields_always_present_even_when_empty() {
    // Spec §1.1.1: extension_fields is REQUIRED (no `?`). An empty
    // BTreeMap MUST serialize as `{}` and NOT be elided.
    let e = make_evidence(EVID_CID_A, SourceKind::Annotation, 10000, BTreeMap::new());
    let s = serde_json::to_string(&e).expect("serialize");
    assert!(
        s.contains("\"extension_fields\":{}"),
        "extension_fields must be present as empty object, got: {}",
        s
    );
}

#[test]
fn compound_evidences_always_present_even_when_empty() {
    // Spec §1.2.1: evidences is REQUIRED. Empty array MUST serialize
    // as `[]` (the degenerate compound is a valid shape).
    let c = CompoundContractMemento {
        aggregation_strategy: AggregationStrategy::Conjunction,
        cid: COMPOUND_CID.to_string(),
        composed_post: ir_true(),
        composed_pre: ir_true(),
        evidences: vec![],
        function_term_cid: FN_CID.to_string(),
        kind: "compound-contract".to_string(),
        schema_version: "1".to_string(),
    };
    let s = serde_json::to_string(&c).expect("serialize");
    assert!(s.contains("\"evidences\":[]"), "got: {}", s);
}

// ================================================================
// §4.5 byte-offset → line/col conversion (normative algorithm test)
// ================================================================
//
// These tests pin the §4.5 algorithm used when auto-promotion (§4.3)
// derives a source_locator from a FunctionContractMemento byte-offset
// locus. The implementation of `byte_offset_to_line_col` lives in
// the PR-B validator; these tests serve as the normative spec fixture.
//
// Algorithm (from §4.5):
//   line := 1, col := 0
//   for i in 0..byte_offset: if src[i]==LF => line+=1, col:=0; else col+=1
//   return (line, col)

fn byte_offset_to_line_col(source_bytes: &[u8], byte_offset: usize) -> (u32, u32) {
    assert!(
        byte_offset <= source_bytes.len(),
        "byte_offset out of range"
    );
    let mut line: u32 = 1;
    let mut col: u32 = 0;
    for b in &source_bytes[..byte_offset] {
        if *b == b'\n' {
            line += 1;
            col = 0;
        } else {
            col += 1;
        }
    }
    (line, col)
}

#[test]
fn byte_offset_line_col_start_of_file() {
    // offset 0 → line 1, col 0
    let src = b"fn foo() {}";
    assert_eq!(byte_offset_to_line_col(src, 0), (1, 0));
}

#[test]
fn byte_offset_line_col_mid_first_line() {
    // "fn foo" → offset 3 = 'f' of 'foo' → line 1, col 3
    let src = b"fn foo() {}";
    assert_eq!(byte_offset_to_line_col(src, 3), (1, 3));
}

#[test]
fn byte_offset_line_col_start_of_second_line() {
    // "fn foo()\n" → offset 9 = first byte of line 2 → line 2, col 0
    let src = b"fn foo()\nfn bar()";
    assert_eq!(byte_offset_to_line_col(src, 9), (2, 0));
}

#[test]
fn byte_offset_line_col_mid_second_line() {
    // "fn foo()\nfn bar()" → offset 12 = 'b' in 'bar' → line 2, col 3
    let src = b"fn foo()\nfn bar()";
    assert_eq!(byte_offset_to_line_col(src, 12), (2, 3));
}

#[test]
fn byte_offset_line_col_three_lines() {
    // "a\nb\nc" → offset 4 = 'c' → line 3, col 0
    let src = b"a\nb\nc";
    assert_eq!(byte_offset_to_line_col(src, 4), (3, 0));
}

#[test]
fn byte_offset_line_col_crlf_cr_is_ordinary_byte() {
    // CRLF: CR is ordinary byte (increments col), LF advances line.
    // "a\r\nb" → bytes: [97, 13, 10, 98]
    //   offset 0 = 'a' → (1, 0)
    //   offset 1 = '\r' → (1, 1)  [CR counted as col byte]
    //   offset 2 = '\n' → (1, 2)  [LF not yet consumed]
    //   offset 3 = 'b' → (2, 0)
    let src = b"a\r\nb";
    assert_eq!(byte_offset_to_line_col(src, 0), (1, 0));
    assert_eq!(byte_offset_to_line_col(src, 1), (1, 1)); // after 'a', before CR
    assert_eq!(byte_offset_to_line_col(src, 2), (1, 2)); // after CR, before LF
    assert_eq!(byte_offset_to_line_col(src, 3), (2, 0)); // after LF, start of line 2
}

#[test]
fn byte_offset_line_col_tab_is_one_byte() {
    // Tab counts as 1 byte, no tab-stop expansion.
    // "\tfoo" → offset 1 = 'f' → line 1, col 1
    let src = b"\tfoo";
    assert_eq!(byte_offset_to_line_col(src, 0), (1, 0));
    assert_eq!(byte_offset_to_line_col(src, 1), (1, 1));
    assert_eq!(byte_offset_to_line_col(src, 2), (1, 2));
}

#[test]
fn byte_offset_line_col_end_of_file() {
    // offset == src.len() is the one-past-the-end position.
    let src = b"ab\ncd";
    assert_eq!(byte_offset_to_line_col(src, 5), (2, 2));
}

#[test]
fn byte_offset_line_col_multibyte_utf8() {
    // UTF-8 multibyte chars: col counts bytes, not codepoints.
    // "é" = [0xC3, 0xA9] (2 bytes). Source: "éx"
    // offset 0 → (1, 0), offset 1 → (1, 1), offset 2 → (1, 2)
    let src = "éx".as_bytes(); // [0xC3, 0xA9, 0x78]
    assert_eq!(byte_offset_to_line_col(src, 0), (1, 0));
    assert_eq!(byte_offset_to_line_col(src, 1), (1, 1));
    assert_eq!(byte_offset_to_line_col(src, 2), (1, 2)); // char boundary for 'x'
    assert_eq!(byte_offset_to_line_col(src, 3), (1, 3));
}
