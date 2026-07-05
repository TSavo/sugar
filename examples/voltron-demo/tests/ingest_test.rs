// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Unit tests for ingest. Each test exercises a specific contract
// branch the lifter derives from parse_event's body. The lifter
// will see these tests as witnesses for the contract claims:
//   - happy path establishes the Ok-branch post-condition
//   - the empty-input and missing-field tests pin the Err branches

use voltron_demo::ingest::{parse_event, ValidEvent};

#[test]
fn parse_event_happy_path_returns_valid_event() {
    let input = r#"{"event_type":"signup","user":"alice","payload":{"age":30}}"#;
    let event = parse_event(input).expect("happy path must succeed");
    assert_eq!(event.event_type, "signup");
    assert_eq!(event.user, "alice");
    // payload re-serialized via the JSON shim; not asserting exact bytes
    // (key order is non-canonical per the shim's loss declaration), just
    // that the seam round-tripped.
    assert!(event.payload_text.contains("30"));
}

#[test]
fn parse_event_rejects_empty_input() {
    let err = parse_event("").expect_err("empty input must be rejected");
    assert!(err.contains("empty input"));
}

#[test]
fn parse_event_rejects_missing_user_field() {
    let input = r#"{"event_type":"signup","payload":{}}"#;
    let err = parse_event(input).expect_err("missing user must be rejected");
    assert!(err.contains("missing user"));
}

#[test]
fn parse_event_rejects_empty_user_field() {
    let input = r#"{"event_type":"signup","user":"","payload":{}}"#;
    let err = parse_event(input).expect_err("empty user must be rejected");
    assert!(err.contains("empty user"));
}

#[test]
fn valid_event_user_is_never_empty_on_ok_arm() {
    // The lifter's post-condition: parse_event(_).Ok.user != ""
    // Pin it with two independent inputs.
    for input in [
        r#"{"event_type":"signup","user":"alice","payload":{}}"#,
        r#"{"event_type":"login","user":"bob","payload":{"k":"v"}}"#,
    ] {
        let ValidEvent { user, .. } = parse_event(input).expect("must succeed");
        assert!(!user.is_empty(), "post-condition violated for {input}");
    }
}
