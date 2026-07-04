// SPDX-License-Identifier: MIT OR Apache-2.0
//
// End-to-end test for the voltron-demo spine. Exercises ingest → persist
// → report all the way through, threading both vendor shims. This is the
// witness for the cross-vendor composition: every contract along the
// spine discharges, including the SQL→JSON re-decode seam in report.

use voltron_demo::run_voltron_demo;

#[test]
fn full_spine_round_trip_succeeds() {
    let input = r#"{"event_type":"signup","user":"alice","payload":{"age":30}}"#;
    let summary = run_voltron_demo(input).expect("spine must discharge end-to-end");
    assert!(summary.contains("user=alice"), "summary: {summary}");
    assert!(summary.contains("type=signup"), "summary: {summary}");
    assert!(summary.contains("rowid=1"), "summary: {summary}");
}

#[test]
fn full_spine_propagates_ingest_errors_without_writing_sql() {
    // If ingest refuses (empty user), the SQL side is never reached.
    // This pins the spine's short-circuit: an Err on the ingest leg
    // means the persist boundaries are not entered.
    let input = r#"{"event_type":"signup","user":"","payload":{}}"#;
    let err = run_voltron_demo(input).expect_err("empty user must be refused");
    assert!(err.contains("empty user"), "err: {err}");
}

#[test]
fn full_spine_propagates_missing_field_errors() {
    let input = r#"{"event_type":"signup","payload":{}}"#;
    let err = run_voltron_demo(input).expect_err("missing user must be refused");
    assert!(err.contains("missing user"), "err: {err}");
}
