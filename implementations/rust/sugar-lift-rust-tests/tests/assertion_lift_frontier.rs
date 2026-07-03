// SPDX-License-Identifier: Apache-2.0
//
// assertion_lift frontier instrument (#3142).
//
// This is an IDD instrument, not a drain. The assertion_lift integration target
// has a known red frontier; this test pins the current red set by mechanism and
// owner so later slices can ratchet fixed rows down and notice new regressions
// loudly.

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::path::Path;
use std::process::Command;
use std::sync::OnceLock;

use serde_json::json;

const EXPECTED_RED: &[(&str, &str)] = &[
    (
        "catch_unwind_array_map_drop_on_panic_side_effect_is_named_refused",
        "floor-gap:runtime-boundary-refusal",
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
        "runtime_if_guard_stays_refused_not_fake_complete",
        "floor-gap:runtime-boundary-refusal",
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
        "temporal_closure_adaptor_runtime_boundaries_decline",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "temporal_closure_adaptor_terminals_compose_to_literal_floor_with_teeth",
        "floor-gap:temporal-closure-adaptor",
    ),
    (
        "top_level_scanner_discovers_vendor_surface_by_macro_body_shape",
        "floor-gap:macro-visible-source",
    ),
];

#[derive(Clone, Copy, Debug)]
struct ClassDisposition {
    bucket: &'static str,
    owner: &'static str,
    follow_up: &'static str,
    note: &'static str,
}

const CLASS_DISPOSITIONS: &[(&str, ClassDisposition)] = &[
    (
        "floor-gap:iterator-temporal-state",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3378 temporal-floor S5",
            follow_up: "iterator terminal/adaptor floors",
            note: "next/nth/peekable/scan/rev rows need counted temporal-floor standing, not derived-testimony repair",
        },
    ),
    (
        "floor-gap:literal-domain-edge",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3378 temporal-floor S5",
            follow_up: "literal iter standing/refusal",
            note: "RangeLiteral/ArrayLiteral count/refusal edges; #3407 range-bound derived testimony is no longer in this frontier",
        },
    ),
    (
        "floor-gap:macro-visible-source",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3043 rust-kit closure capstone",
            follow_up: "macro-visible assertion surface ownership",
            note: "visible macro body/source discovery rows are construction coverage, not missing-derived testimony",
        },
    ),
    (
        "floor-gap:mutable-alias-state",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3026 temporal-floor umbrella",
            follow_up: "rewrite/alias refusal through the temporal floor",
            note: "mutable alias and stale-read rows need typed temporal ownership or terminal refusal",
        },
    ),
    (
        "floor-gap:runtime-boundary-refusal",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3043 rust-kit closure capstone",
            follow_up: "runtime-boundary refusal coverage",
            note: "runtime source/body/guard rows must refuse by named boundary instead of warranting or silently dropping",
        },
    ),
    (
        "floor-gap:slice-chunk-window-terminal",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3378 temporal-floor S5",
            follow_up: "iterator terminal floor for chunk/window sources",
            note: "chunk/window terminal count is an iterator-terminal floor row",
        },
    ),
    (
        "floor-gap:temporal-closure-adaptor",
        ClassDisposition {
            bucket: "unlifted-construct",
            owner: "#3378 temporal-floor S5",
            follow_up: "adapter callback/curry rows",
            note: "closure adaptor rows need the temporal-floor counted/curry path; S3 fixed nested map but not these adapters",
        },
    ),
    (
        "ladder-demolition:tail-expr-ite",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S2",
            follow_up: "tail-position lowering through catalog/algebra boundary",
            note: "future assertion_lift reds from tail-expression ladders must route through build_term/build_expr_role, not ad hoc IrTerm construction",
        },
    ),
    (
        "ladder-demolition:predicates",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S3",
            follow_up: "predicate lifting through PredicateValue/catalog claims",
            note: "future assertion_lift reds from predicate ladders belong to the PredicateValue route, not structural re-sniffing",
        },
    ),
    (
        "ladder-demolition:guard-assertion-facts",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S4",
            follow_up: "guard/assertion fact extraction through algebra guard operations",
            note: "future guard-fact reds enter the ladder campaign with ControlFlowGuardOperation as the replacement path",
        },
    ),
    (
        "ladder-demolition:value-kind-macros",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S5",
            follow_up: "value classification and macro lowering through catalog recognizers",
            note: "future value-kind or macro reds must be classified by catalog claims instead of local match ladders",
        },
    ),
    (
        "ladder-demolition:wp-contract-seeds",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S6",
            follow_up: "contract-surface lifting through typed vocabulary/catalog claims",
            note: "future contract/seed reds belong to the typed vocabulary route, not local contract-surface walkers",
        },
    ),
    (
        "ladder-demolition:panic-loop-effects",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S7",
            follow_up: "panic/loop effects through Phase 2 routers",
            note: "future panic or loop-effect reds route through the effect algebra rather than shape-specific walkers",
        },
    ),
    (
        "ladder-demolition:patterns-types-call-edges",
        ClassDisposition {
            bucket: "ladder-demolition",
            owner: "#3027 S7",
            follow_up: "patterns, types, and call edges through catalog claims",
            note: "future pattern/type/call-edge reds route through catalog claims instead of syntactic projection ladders",
        },
    ),
];

const ZERO_BUCKETS: &[(&str, &str, &str)] = &[
    (
        "ladder-demolition",
        "#3027",
        "no current assertion_lift row is classed directly as ladder-demolition; future rows have typed dispositions for S2-S7 families",
    ),
    (
        "missing-derived-testimony",
        "#3407",
        "range_term/nonzero_assoc_const were witness-enrollment rows and were closed by #3412; no live assertion_lift row has that shape",
    ),
    (
        "genuinely-unknown",
        "none",
        "every current assertion_lift red maps to a named mechanism family",
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

fn class_disposition(class: &str) -> Option<&'static ClassDisposition> {
    CLASS_DISPOSITIONS
        .iter()
        .find_map(|(name, disposition)| (*name == class).then_some(disposition))
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

    fn buckets(&self) -> BTreeMap<String, usize> {
        let mut buckets = BTreeMap::<String, usize>::new();
        for row in &self.rows {
            let bucket = class_disposition(&row.key.class)
                .map(|disposition| disposition.bucket)
                .unwrap_or("genuinely-unknown");
            *buckets.entry(bucket.to_string()).or_default() += 1;
        }
        buckets
    }

    fn classes_without_disposition(&self) -> Vec<String> {
        self.rows
            .iter()
            .filter_map(|row| {
                class_disposition(&row.key.class)
                    .is_none()
                    .then_some(row.key.class.clone())
            })
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect()
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
                let disposition = class_disposition(&class);
                json!({
                    "class": class,
                    "bucket": disposition.map(|d| d.bucket).unwrap_or("genuinely-unknown"),
                    "owner": disposition.map(|d| d.owner).unwrap_or("unowned"),
                    "follow_up": disposition.map(|d| d.follow_up).unwrap_or("class needs triage"),
                    "note": disposition.map(|d| d.note).unwrap_or("new class has no retarget disposition"),
                    "count": tests.len(),
                    "tests": tests,
                })
            })
            .collect::<Vec<_>>();
        let buckets = self
            .buckets()
            .into_iter()
            .map(|(bucket, count)| {
                json!({
                    "bucket": bucket,
                    "count": count,
                })
            })
            .collect::<Vec<_>>();
        let zero_buckets = ZERO_BUCKETS
            .iter()
            .map(|(bucket, owner, reason)| {
                json!({
                    "bucket": bucket,
                    "count": 0,
                    "owner": owner,
                    "reason": reason,
                })
            })
            .collect::<Vec<_>>();
        let rows = self
            .rows
            .iter()
            .map(|row| {
                let disposition = class_disposition(&row.key.class);
                json!({
                    "test": row.key.test,
                    "class": row.key.class,
                    "bucket": disposition.map(|d| d.bucket).unwrap_or("genuinely-unknown"),
                    "owner": disposition.map(|d| d.owner).unwrap_or("unowned"),
                    "follow_up": disposition.map(|d| d.follow_up).unwrap_or("class needs triage"),
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
            "buckets": buckets,
            "zero_buckets": zero_buckets,
            "classes": classes,
            "classes_without_disposition": self.classes_without_disposition(),
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
    assert!(
        report.classes_without_disposition().is_empty(),
        "assertion_lift frontier classes need retarget dispositions\n{}",
        report.to_json()
    );
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
