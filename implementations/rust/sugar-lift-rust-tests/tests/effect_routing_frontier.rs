// SPDX-License-Identifier: Apache-2.0
//
// Phase 2 effect-router frontier auditor (#3292).
//
// This is the measuring instrument only: it names the current control-flow
// constructs that have not yet been routed through RouteRaisesOperation. Later
// slices drain rows; this test keeps the current R vector pinned while they do.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct ExpectedUnroutedConstruct {
    key: &'static str,
    family: &'static str,
    owner: &'static str,
    replacement: &'static str,
}

const EXPECTED_UNROUTED_CONSTRUCTS: &[ExpectedUnroutedConstruct] = &[
    ExpectedUnroutedConstruct {
        key: "drop-effect-family-missing",
        family: "drop",
        owner: "Phase2-S6",
        replacement: "decide Drop/finally-fallthrough effect shape and route/refuse it explicitly",
    },
    ExpectedUnroutedConstruct {
        key: "early-return-control-flow-unrouted",
        family: "early-return",
        owner: "Phase2-S5",
        replacement: "route early-return/control-flow effects through RouteRaisesOperation handlers",
    },
    ExpectedUnroutedConstruct {
        key: "panic-family-unrouted",
        family: "panic",
        owner: "Phase2-S5",
        replacement: "route PanicMacro/LiteralPanic through RouteRaisesOperation handlers",
    },
    ExpectedUnroutedConstruct {
        key: "question-mark-opaque-irterm-op",
        family: "question-mark-try",
        owner: "#3196",
        replacement: "route Expr::Try through term_boundary into the Phase 2 router; do not fix in #3292",
    },
    ExpectedUnroutedConstruct {
        key: "spine-pub-crate-unreachable",
        family: "route-raises-spine",
        owner: "Phase2-S3",
        replacement: "promote RouteRaisesOperation and its closed visitor traits to sugar-floor-algebra public API",
    },
];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct ObservedUnroutedConstruct {
    key: String,
    family: String,
    file: String,
    line: usize,
    evidence: String,
    owner: String,
    replacement: String,
}

impl ObservedUnroutedConstruct {
    fn to_json(&self) -> Value {
        json!({
            "key": self.key,
            "family": self.family,
            "file": self.file,
            "line": self.line,
            "evidence": self.evidence,
            "owner": self.owner,
            "replacement": self.replacement,
        })
    }
}

impl ExpectedUnroutedConstruct {
    fn to_json(&self) -> Value {
        json!({
            "key": self.key,
            "family": self.family,
            "owner": self.owner,
            "replacement": self.replacement,
        })
    }
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-lift-rust-tests has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn read_source(root: &Path, rel: &str) -> String {
    fs::read_to_string(root.join(rel)).unwrap_or_else(|err| panic!("read {rel}: {err}"))
}

fn line_containing(source: &str, needle: &str) -> usize {
    source
        .lines()
        .enumerate()
        .find_map(|(idx, line)| line.contains(needle).then_some(idx + 1))
        .unwrap_or_else(|| panic!("source did not contain expected needle {needle:?}"))
}

fn push_row(
    rows: &mut Vec<ObservedUnroutedConstruct>,
    key: &str,
    family: &str,
    file: &str,
    line: usize,
    evidence: &str,
    owner: &str,
    replacement: &str,
) {
    rows.push(ObservedUnroutedConstruct {
        key: key.to_string(),
        family: family.to_string(),
        file: file.to_string(),
        line,
        evidence: evidence.to_string(),
        owner: owner.to_string(),
        replacement: replacement.to_string(),
    });
}

fn source_uses_route_raises_spine(source: &str) -> bool {
    source.contains("accept_route_raises") || source.contains("RouteRaisesOperation::new")
}

fn source_has_unrouted_panic_family(source: &str) -> bool {
    source.contains("Effect::PanicMacro") && !source_uses_route_raises_spine(source)
}

fn collect_unrouted_constructs(root: &Path) -> Vec<ObservedUnroutedConstruct> {
    let mut rows = Vec::new();

    let route_spine =
        "implementations/rust/sugar-lift-rust-tests/src/sugar/route_raises_operation.rs";
    let route_spine_source = read_source(root, route_spine);
    let shared_spine = "implementations/rust/sugar-floor-algebra/src/route_raises_operation.rs";
    if route_spine_source.contains("pub(crate) struct RouteRaisesOperation")
        || !root.join(shared_spine).exists()
    {
        push_row(
            &mut rows,
            "spine-pub-crate-unreachable",
            "route-raises-spine",
            route_spine,
            line_containing(&route_spine_source, "pub(crate) struct RouteRaisesOperation"),
            "RouteRaisesOperation exists only as a pub(crate) test-crate spine",
            "Phase2-S3",
            "promote RouteRaisesOperation and its closed visitor traits to sugar-floor-algebra public API",
        );
    }

    let emit = "implementations/rust/sugar-walk/src/emit.rs";
    let emit_source = read_source(root, emit);
    if emit_source.contains("Expr::Try(try_expr)")
        && emit_source.contains("AlgebraTerm::op(\n            \"try\"")
    {
        push_row(
            &mut rows,
            "question-mark-opaque-irterm-op",
            "question-mark-try",
            emit,
            line_containing(&emit_source, "Expr::Try(try_expr)"),
            "Expr::Try lowers to opaque AlgebraTerm::op(\"try\", ...) on the IrTerm side",
            "#3196",
            "route Expr::Try through term_boundary into the Phase 2 router; do not fix in #3292",
        );
    }

    let panic_macro = "implementations/rust/sugar-lift-rust-tests/src/sugar/panic_macro.rs";
    let panic_source = read_source(root, panic_macro);
    if source_has_unrouted_panic_family(&panic_source) {
        push_row(
            &mut rows,
            "panic-family-unrouted",
            "panic",
            panic_macro,
            line_containing(&panic_source, "Effect::PanicMacro"),
            "PanicMacroSugar emits a raise-like effect but no router consumes it",
            "Phase2-S5",
            "route PanicMacro/LiteralPanic through RouteRaisesOperation handlers",
        );
    }

    let control_flow =
        "implementations/rust/sugar-lift-rust-tests/src/sugar/statement_control_flow.rs";
    let control_source = read_source(root, control_flow);
    if control_source.contains("Effect::ControlFlow")
        && !source_uses_route_raises_spine(&control_source)
    {
        push_row(
            &mut rows,
            "early-return-control-flow-unrouted",
            "early-return",
            control_flow,
            line_containing(&control_source, "Effect::ControlFlow"),
            "statement control-flow emits ControlFlow but has no router consumer",
            "Phase2-S5",
            "route early-return/control-flow effects through RouteRaisesOperation handlers",
        );
    }

    let algebra_lib = "implementations/rust/sugar-floor-algebra/src/lib.rs";
    let algebra_source = read_source(root, algebra_lib);
    if !algebra_source.contains("Drop") {
        push_row(
            &mut rows,
            "drop-effect-family-missing",
            "drop",
            algebra_lib,
            line_containing(&algebra_source, "pub enum Effect"),
            "Drop has no effect-family entry in the shared algebra",
            "Phase2-S6",
            "decide Drop/finally-fallthrough effect shape and route/refuse it explicitly",
        );
    }

    rows.sort();
    rows
}

fn expected_by_key() -> BTreeMap<&'static str, &'static ExpectedUnroutedConstruct> {
    EXPECTED_UNROUTED_CONSTRUCTS
        .iter()
        .map(|expected| (expected.key, expected))
        .collect()
}

fn observed_by_key(
    observed: &[ObservedUnroutedConstruct],
) -> BTreeMap<&str, &ObservedUnroutedConstruct> {
    observed.iter().map(|row| (row.key.as_str(), row)).collect()
}

fn vector_by_family(observed: &[ObservedUnroutedConstruct]) -> BTreeMap<String, usize> {
    let mut vector = BTreeMap::new();
    for row in observed {
        *vector.entry(row.family.clone()).or_insert(0) += 1;
    }
    vector
}

fn coordinated_floor_projection_rows(root: &Path) -> Value {
    let gate = read_source(
        root,
        "implementations/rust/sugar-lift-rust-tests/tests/floor_projection_gate.rs",
    );
    let has_route_module = gate.contains("src/sugar/route_raises_operation.rs");
    let has_guard_raise_row =
        gate.contains("enclosing_fn: \"guard_raise\"") && gate.contains("RouteRaisesOperation");
    json!({
        "floorProjectionGateRouteRaisesModuleAllowed": has_route_module,
        "floorProjectionGateOwnsBlockSugarGuardRaise": has_guard_raise_row,
        "note": "block_sugar::guard_raise remains counted by floor_projection_gate, not by R(control-flow-constructs-unrouted)",
    })
}

fn report_json(
    root: &Path,
    observed: &[ObservedUnroutedConstruct],
    unexpected: &[ObservedUnroutedConstruct],
    missing: &[&ExpectedUnroutedConstruct],
    metadata_mismatches: &[(&ObservedUnroutedConstruct, &ExpectedUnroutedConstruct)],
) -> Value {
    json!({
        "R(control-flow-constructs-unrouted)": observed.len(),
        "vectorByFamily": vector_by_family(observed),
        "coordinatedFloorProjectionRows": coordinated_floor_projection_rows(root),
        "expected": EXPECTED_UNROUTED_CONSTRUCTS.iter().map(ExpectedUnroutedConstruct::to_json).collect::<Vec<_>>(),
        "observed": observed.iter().map(ObservedUnroutedConstruct::to_json).collect::<Vec<_>>(),
        "unexpected": unexpected.iter().map(ObservedUnroutedConstruct::to_json).collect::<Vec<_>>(),
        "missing": missing.iter().map(|row| row.to_json()).collect::<Vec<_>>(),
        "metadataMismatches": metadata_mismatches.iter().map(|(observed, expected)| {
            json!({
                "observed": observed.to_json(),
                "expected": expected.to_json(),
            })
        }).collect::<Vec<_>>(),
    })
}

fn assert_frontier_matches_expected(root: &Path, observed: &[ObservedUnroutedConstruct]) {
    let expected = expected_by_key();
    let observed_map = observed_by_key(observed);
    let unexpected = observed
        .iter()
        .filter(|row| !expected.contains_key(row.key.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    let missing = EXPECTED_UNROUTED_CONSTRUCTS
        .iter()
        .filter(|expected| !observed_map.contains_key(expected.key))
        .collect::<Vec<_>>();
    let metadata_mismatches = observed
        .iter()
        .filter_map(|row| {
            expected.get(row.key.as_str()).and_then(|expected| {
                (row.family != expected.family
                    || row.owner != expected.owner
                    || row.replacement != expected.replacement)
                    .then_some((row, *expected))
            })
        })
        .collect::<Vec<_>>();

    if !unexpected.is_empty() || !missing.is_empty() || !metadata_mismatches.is_empty() {
        panic!(
            "effect-routing frontier changed\n{}",
            serde_json::to_string_pretty(&report_json(
                root,
                observed,
                &unexpected,
                &missing,
                &metadata_mismatches,
            ))
            .expect("effect-routing report serializes")
        );
    }
}

#[test]
fn effect_routing_frontier_matches_expected_multiset() {
    let root = repo_root();
    let observed = collect_unrouted_constructs(&root);
    assert_frontier_matches_expected(&root, &observed);
}

#[test]
#[ignore = "red-by-design: Phase 2 drains this frontier in later slices"]
fn effect_routing_frontier_is_zero() {
    let root = repo_root();
    let observed = collect_unrouted_constructs(&root);
    assert!(
        observed.is_empty(),
        "Phase 2 effect-routing frontier still has R={} row(s): {}",
        observed.len(),
        serde_json::to_string_pretty(&report_json(&root, &observed, &observed, &[], &[]))
            .expect("effect-routing report serializes")
    );
}

#[test]
fn collector_does_not_flag_routed_raise_spine_usage() {
    let source = r#"
        fn routed() {
            let _ = floor.accept_route_raises(RouteRaisesOperation::new(vec![&handler], "test"));
        }
    "#;
    assert!(
        source_uses_route_raises_spine(source),
        "sanctioned RouteRaisesOperation use should be recognized as routed"
    );
    assert!(
        !source_has_unrouted_panic_family(source),
        "routed raise usage must not be counted as an unrouted panic-family construct"
    );
}

#[test]
fn collector_names_planted_unrouted_panic_family_construct() {
    let source = r#"
        fn planted() -> Outcome {
            Outcome::Incomplete(Effect::PanicMacro { boundary: "panic!()".into() })
        }
    "#;
    assert!(
        source_has_unrouted_panic_family(source),
        "a planted panic-family construct without RouteRaisesOperation must be named"
    );
}
