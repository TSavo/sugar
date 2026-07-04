// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Unit tests for persist. The lifter derives a post-condition from
// insert_event's body that the rowid is positive (via the panic guard);
// these tests are its witnesses.

use voltron_demo::ingest::ValidEvent;
use voltron_demo::persist::{insert_event, install_schema, open_in_memory};

fn fixture_event(user: &str) -> ValidEvent {
    ValidEvent {
        event_type: "signup".into(),
        user: user.into(),
        payload_text: r#"{"k":1}"#.into(),
    }
}

#[test]
fn install_schema_creates_events_table() {
    let conn = open_in_memory().expect("open must succeed");
    install_schema(&conn).expect("install_schema must succeed");
    // Inserting validates the schema exists with the right shape.
    let event = fixture_event("alice");
    let rowid = insert_event(&conn, &event).expect("insert into installed schema");
    assert_eq!(rowid, 1);
}

#[test]
fn insert_event_returns_monotonically_increasing_rowid() {
    let conn = open_in_memory().expect("open");
    install_schema(&conn).expect("schema");
    let r1 = insert_event(&conn, &fixture_event("alice")).expect("r1");
    let r2 = insert_event(&conn, &fixture_event("bob")).expect("r2");
    let r3 = insert_event(&conn, &fixture_event("carol")).expect("r3");
    assert!(r1 < r2 && r2 < r3, "rowid monotonic: {r1} < {r2} < {r3}");
    assert_eq!(r1, 1);
    assert_eq!(r2, 2);
    assert_eq!(r3, 3);
}

#[test]
fn insert_event_post_rowid_is_always_positive() {
    // The lifter's post-condition: insert_event(_,_).Ok > 0
    // Pin it with several inputs.
    let conn = open_in_memory().expect("open");
    install_schema(&conn).expect("schema");
    for user in ["a", "bb", "ccc", "dddd"] {
        let rowid = insert_event(&conn, &fixture_event(user)).expect("ok");
        assert!(rowid > 0, "post-condition rowid > 0 violated: {rowid}");
    }
}
