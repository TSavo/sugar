// SPDX-License-Identifier: Apache-2.0
//
// assertion_lift frontier instrument (#3142).
//
// This is an IDD instrument, not a drain. The assertion_lift integration target
// has a known red frontier; this test pins the current red set by mechanism so
// later slices can ratchet fixed rows down and notice new regressions loudly.

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::path::Path;
use std::process::Command;
use std::sync::OnceLock;

use serde_json::json;

const EXPECTED_RED: &[(&str, &str)] = &[
    (
        "alias_deref_mutated_read_refuses_not_false_refutation",
        "floor-gap:mutable-alias-state",
    ),
    (
        "alias_receiver_identity_is_ambiguous_and_skipped",
        "floor-gap:mutable-alias-state",
    ),
    (
        "bounded_next_binding_bad_remaining_len_refutes",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "bounded_next_binding_snapshots_return_and_advances_receiver_state",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "broad_functional_warrant_carries_const_bound_assertions",
        "floor-gap:macro-visible-source",
    ),
    (
        "catch_unwind_array_map_drop_on_panic_side_effect_is_named_refused",
        "floor-gap:runtime-boundary-refusal",
    ),
    (
        "chained_next_next_len_bad_twin_refutes",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "chained_next_next_len_over_literal_iterator_grounds_remaining_len",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "closure_capture_mut_local_post_closure_read_refuses_not_false_refutation",
        "floor-gap:mutable-alias-state",
    ),
    (
        "closure_driver_invocation_recurses_body_per_temporal_callsite",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "emit_value_contract_guard_return_non_value_tail_refused",
        "factory-structural-gap:missing-term-or-composite",
    ),
    (
        "emit_value_contract_let_prefix_refuses_mut_and_letelse",
        "floor-gap:emit-value-contract",
    ),
    (
        "emit_value_contract_let_prefix_warrants_and_composes",
        "floor-gap:emit-value-contract",
    ),
    (
        "emit_value_contract_let_prefix_with_control_flow_tail",
        "floor-gap:emit-value-contract",
    ),
    (
        "emit_value_contract_refuses_unemittable_bodies",
        "floor-gap:emit-value-contract",
    ),
    (
        "emit_value_contract_tuple_destructuring_let",
        "floor-gap:emit-value-contract",
    ),
    (
        "forloop_runtime_body_read_refuses_with_named_body_effect",
        "floor-gap:runtime-boundary-refusal",
    ),
    (
        "forloop_runtime_valued_accumulator_refuses_with_named_accum_effect",
        "floor-gap:runtime-boundary-refusal",
    ),
    (
        "iter_scan_last_over_literal_digs_with_teeth",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "iter_scan_sum_over_literal_digs_with_teeth",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "iterator_clone_binding_uses_runtime_iterator_source_floor",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "kmerge_size_hint_decomposes_after_delayed_tuple_producer_desugar",
        "factory-structural-gap:missing-term-or-composite",
    ),
    (
        "kmerge_size_hint_wrong_component_is_unsat",
        "factory-structural-gap:missing-term-or-composite",
    ),
    (
        "let_initializer_assertion_macro_lifts_and_binds_success_payload",
        "floor-gap:macro-visible-source",
    ),
    (
        "let_initializer_learns_assertion_shape_after_dropping_macro_name",
        "floor-gap:macro-visible-source",
    ),
    (
        "literal_empty_domain_named_refused_with_twin",
        "floor-gap:literal-domain-edge",
    ),
    (
        "literal_runtime_element_named_refused_with_twin",
        "floor-gap:literal-domain-edge",
    ),
    (
        "literal_slice_chunk_window_zip_collects_ground_with_teeth",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "macro_expansion_terminal_runtime_effect_is_refused_not_support_only",
        "floor-gap:macro-visible-source",
    ),
    (
        "mut_borrow_deref_after_mutation_is_not_falsely_discharged",
        "floor-gap:mutable-alias-state",
    ),
    (
        "nested_macro_terminal_effect_is_not_swallowed_as_inert",
        "floor-gap:macro-visible-source",
    ),
    (
        "opaque_mut_borrow_call_read_refuses_not_false_refutation",
        "floor-gap:mutable-alias-state",
    ),
    (
        "peekable_runtime_nth_after_peek_is_named_refused_not_work",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "peekable_runtime_slice_source_is_named_refused_not_work",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "reversed_literal_range_terminals_and_step_collect_have_teeth",
        "floor-gap:iterator-temporal-state",
    ),
    (
        "rpc_source_peekable_mut_if_let_guard_refuses_stale_read_as_mutable_view",
        "other:rpc-plugin-closed-stdout",
    ),
    (
        "rpc_source_peekable_runtime_cycle_iter_nth_refuses_named_composite_floor",
        "other:rpc-plugin-closed-stdout",
    ),
    (
        "rpc_source_refuses_runtime_searcher_state_machine_with_literal_twin",
        "other:rpc-plugin-closed-stdout",
    ),
    (
        "rpc_source_refuses_type_inferred_parse_result_with_literal_twin",
        "other:euf-string-or-parser-shape",
    ),
    (
        "rpc_source_replays_full_cycle_fixture_without_shadowing_cycle_domain",
        "other:rpc-plugin-closed-stdout",
    ),
    (
        "runtime_if_guard_stays_refused_not_fake_complete",
        "floor-gap:runtime-boundary-refusal",
    ),
    (
        "search_asserts_style_macro_with_runtime_searcher_bails",
        "factory-structural-gap:missing-term-or-composite",
    ),
    (
        "slice_accessor_runtime_source_or_index_refuses_named_boundary",
        "floor-gap:runtime-boundary-refusal",
    ),
    (
        "slice_chunk_window_count_runtime_source_refuses_named_boundary",
        "floor-gap:slice-chunk-window-terminal",
    ),
    (
        "slice_chunk_window_runtime_source_refuses_named_boundary",
        "floor-gap:runtime-boundary-refusal",
    ),
    (
        "slice_mut_index_methods_refuse_runtime_mutable_slice_sources",
        "floor-gap:mutable-alias-state",
    ),
    (
        "starts_with_over_opaque_receiver_lifts",
        "other:euf-string-or-parser-shape",
    ),
    (
        "temporal_closure_adaptor_runtime_boundaries_decline",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "temporal_closure_adaptor_terminals_compose_to_literal_floor_with_teeth",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "temporal_nested_map_curry_dispatch_reduces_inner_floor_before_materializing",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "top_level_scanner_discovers_vendor_surface_by_macro_body_shape",
        "floor-gap:macro-visible-source",
    ),
];

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
struct FrontierKey {
    test: String,
    class: String,
}

#[derive(Clone, Debug)]
struct FrontierRow {
    key: FrontierKey,
    excerpt: String,
}

#[derive(Clone, Debug)]
struct FrontierReport {
    rows: Vec<FrontierRow>,
    expected: Vec<FrontierKey>,
    status_code: Option<i32>,
    summary: Option<String>,
}

static REPORT: OnceLock<FrontierReport> = OnceLock::new();

fn report() -> &'static FrontierReport {
    REPORT.get_or_init(run_assertion_lift_frontier)
}

fn run_assertion_lift_frontier() -> FrontierReport {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let workspace_dir = manifest_dir
        .parent()
        .expect("sugar-lift-rust-tests crate has a workspace parent");
    let cargo = env::var_os("CARGO").unwrap_or_else(|| "cargo".into());
    let output = Command::new(cargo)
        .current_dir(workspace_dir)
        .env("NO_COLOR", "1")
        .env("CLICOLOR", "0")
        .env("TERM", "dumb")
        // The target owns a few RPC subprocess tests whose failure identities can
        // flap under parallel test scheduling. The frontier is a ratchet, so run
        // the child target serially and pin the stable R vector.
        .args([
            "test",
            "-p",
            "sugar-lift-rust-tests",
            "--test",
            "assertion_lift",
            "--color",
            "never",
            "--",
            "--nocapture",
            "--test-threads=1",
        ])
        .output()
        .expect("run assertion_lift frontier target");

    let mut text = String::from_utf8_lossy(&output.stdout).into_owned();
    text.push_str(&String::from_utf8_lossy(&output.stderr));
    let text = strip_ansi(&text);
    let failure_names = parse_final_failure_list(&text);
    let expected = expected_keys();
    let rows = failure_names
        .into_iter()
        .map(|test| FrontierRow {
            key: FrontierKey {
                class: expected_class_for(&test)
                    .unwrap_or("unclassified-new-red")
                    .to_string(),
                test: test.clone(),
            },
            excerpt: panic_excerpt(&text, &test),
        })
        .collect();

    FrontierReport {
        rows,
        expected,
        status_code: output.status.code(),
        summary: parse_test_summary(&text),
    }
}

fn expected_keys() -> Vec<FrontierKey> {
    let mut keys = EXPECTED_RED
        .iter()
        .map(|(test, class)| FrontierKey {
            test: (*test).to_string(),
            class: (*class).to_string(),
        })
        .collect::<Vec<_>>();
    keys.sort();
    keys
}

fn expected_class_for(test: &str) -> Option<&'static str> {
    EXPECTED_RED
        .iter()
        .find_map(|(name, class)| (*name == test).then_some(*class))
}

fn observed_keys(rows: &[FrontierRow]) -> Vec<FrontierKey> {
    let mut keys = rows.iter().map(|row| row.key.clone()).collect::<Vec<_>>();
    keys.sort();
    keys
}

fn parse_final_failure_list(text: &str) -> Vec<String> {
    let lines = text.lines().collect::<Vec<_>>();
    let start = lines
        .iter()
        .enumerate()
        .rev()
        .find_map(|(index, line)| (line.trim() == "failures:").then_some(index + 1))
        .expect("assertion_lift output must contain a final failures list");

    let mut failures = Vec::new();
    for line in &lines[start..] {
        if let Some(name) = line.strip_prefix("    ") {
            let name = name.trim();
            if !name.is_empty() {
                failures.push(name.to_string());
            }
        } else if !failures.is_empty() {
            break;
        }
    }
    failures
}

fn parse_test_summary(text: &str) -> Option<String> {
    text.lines()
        .rev()
        .find(|line| line.contains("test result:"))
        .map(str::to_string)
}

fn panic_excerpt(text: &str, test: &str) -> String {
    let marker = format!("thread '{test}'");
    let lines = text.lines().collect::<Vec<_>>();
    let Some(start) = lines.iter().position(|line| line.contains(&marker)) else {
        return String::new();
    };
    let mut excerpt = Vec::new();
    for line in &lines[start..] {
        if line.starts_with("test ") && line.contains(" ... ") && !excerpt.is_empty() {
            break;
        }
        if !line.trim().is_empty() {
            excerpt.push(trim_excerpt_line(line.trim()));
        }
        if excerpt.len() == 4 {
            break;
        }
    }
    excerpt.join("\n")
}

fn trim_excerpt_line(line: &str) -> String {
    const MAX: usize = 280;
    let mut chars = line.chars();
    let head = chars.by_ref().take(MAX).collect::<String>();
    if chars.next().is_some() {
        format!("{head}...")
    } else {
        head
    }
}

fn strip_ansi(text: &str) -> String {
    let mut stripped = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\u{1b}' && chars.peek() == Some(&'[') {
            chars.next();
            for next in chars.by_ref() {
                if next.is_ascii_alphabetic() {
                    break;
                }
            }
        } else {
            stripped.push(ch);
        }
    }
    stripped
}

impl FrontierReport {
    fn observed_keys(&self) -> Vec<FrontierKey> {
        observed_keys(&self.rows)
    }

    fn is_zero(&self) -> bool {
        self.rows.is_empty()
    }

    fn classes(&self) -> BTreeMap<String, Vec<String>> {
        let mut classes = BTreeMap::<String, Vec<String>>::new();
        for row in &self.rows {
            classes
                .entry(row.key.class.clone())
                .or_default()
                .push(row.key.test.clone());
        }
        classes
    }

    fn unexpected(&self) -> Vec<FrontierKey> {
        let expected = self.expected.iter().cloned().collect::<BTreeSet<_>>();
        self.observed_keys()
            .into_iter()
            .filter(|key| !expected.contains(key))
            .collect()
    }

    fn missing(&self) -> Vec<FrontierKey> {
        let observed = self.observed_keys().into_iter().collect::<BTreeSet<_>>();
        self.expected
            .iter()
            .filter(|key| !observed.contains(*key))
            .cloned()
            .collect()
    }

    fn to_json(&self) -> String {
        let classes = self
            .classes()
            .into_iter()
            .map(|(class, tests)| {
                json!({
                    "class": class,
                    "count": tests.len(),
                    "tests": tests,
                })
            })
            .collect::<Vec<_>>();
        let rows = self
            .rows
            .iter()
            .map(|row| {
                json!({
                    "test": row.key.test,
                    "class": row.key.class,
                    "excerpt": row.excerpt,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string_pretty(&json!({
            "target": "assertion_lift",
            "total": self.rows.len(),
            "is_zero": self.is_zero(),
            "status_code": self.status_code,
            "summary": self.summary,
            "classes": classes,
            "unexpected": keys_to_json(self.unexpected()),
            "missing": keys_to_json(self.missing()),
            "rows": rows,
        }))
        .expect("frontier report is JSON serializable")
    }

    fn to_expected_red_literal(&self) -> String {
        let mut keys = self.observed_keys();
        keys.sort();
        let mut out = String::from("const EXPECTED_RED: &[(&str, &str)] = &[\n");
        for key in keys {
            out.push_str(&format!("    ({:?}, {:?}),\n", key.test, key.class));
        }
        out.push_str("];\n");
        out
    }
}

fn keys_to_json(keys: Vec<FrontierKey>) -> Vec<serde_json::Value> {
    keys.into_iter()
        .map(|key| {
            json!({
                "test": key.test,
                "class": key.class,
            })
        })
        .collect()
}

#[test]
fn assertion_lift_frontier_matches_expected_multiset() {
    let report = report();
    assert_eq!(
        report.status_code,
        Some(101),
        "assertion_lift should stay red while this frontier is nonzero\n{}",
        report.to_json()
    );
    assert_eq!(
        report.observed_keys(),
        report.expected,
        "assertion_lift frontier changed\n{}\n\nPasteable EXPECTED_RED:\n{}",
        report.to_json(),
        report.to_expected_red_literal()
    );
}

#[test]
fn assertion_lift_frontier_is_red_report_only() {
    let report = report();
    eprintln!("{}", report.to_json());
    assert!(
        !report.is_zero(),
        "assertion_lift frontier unexpectedly reached stable zero"
    );
}

#[test]
#[ignore = "red target: run with --ignored after assertion_lift drains to require stable zero"]
fn assertion_lift_frontier_stable_zero_target() {
    let report = report();
    assert!(report.is_zero(), "{}", report.to_json());
}
