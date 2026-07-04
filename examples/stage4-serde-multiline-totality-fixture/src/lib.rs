// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 4 discrimination fixture: multi-line serde_json Value totality.
//
// Acceptance criteria:
//   f/f_split/f_spanning: serde_json::to_string(&serde_json::Value).unwrap()
//      -> PANIC-SAFE (Value serialization is total; is_ok(result) axiom fires)
//
//   g/g_split/h_adjacent_cross_talk: serde_json::to_string(&MyStruct).unwrap()
//      -> UNDECIDABLE (struct Serialize may fail; no totality contract)
//      -> falsePass MUST be 0; non-Value sites stay honestly unproven.
//
// The split-line cases prove panic-locus lookup uses the receiver producer
// line, not the `.unwrap()` line. The adjacent case proves lookup does not grab
// a nearby totality producer for a distinct non-total receiver.

use serde::Serialize;
use serde_json::Value;

/// Baseline totality case: producer and panic leaf are on the same line.
pub fn f(v: &Value) -> String {
    serde_json::to_string(v).unwrap()
}

/// The receiver producer call and `.unwrap()` are on different source lines.
pub fn f_split(v: &Value) -> String {
    serde_json::to_string(v)
        .unwrap()
}

/// The receiver producer call itself spans multiple lines.
pub fn f_spanning(v: &Value) -> String {
    serde_json::to_string(
        v,
    )
    .unwrap()
}

#[derive(Serialize)]
pub struct MyStruct {
    pub x: i32,
    pub name: String,
}

/// Baseline non-total case: must stay undecidable.
pub fn g(s: &MyStruct) -> String {
    serde_json::to_string(s).unwrap()
}

/// Split-line non-total case. Fixing producer-line lookup must not broaden into
/// "all split-line to_string unwraps are safe."
pub fn g_split(s: &MyStruct) -> String {
    serde_json::to_string(s)
        .unwrap()
}

/// Adjacent cross-talk probe: a known-total producer is immediately above a
/// split-line non-total producer. The first unwrap must discharge, and the
/// second must stay undecidable.
pub fn h_adjacent_cross_talk(v: &Value, s: &MyStruct) -> (String, String) {
    (
        serde_json::to_string(v).unwrap(),
        serde_json::to_string(s)
            .unwrap(),
    )
}
