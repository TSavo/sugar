// SPDX-License-Identifier: MIT OR Apache-2.0
//
// ingest.rs — JSON ingestion module. Two boundary stubs for serde_json
// (json_parse, json_serialize) + the user-side `parse_event` function
// whose contract the lifter derives from its panic guards and early
// returns. ValidEvent is the user-authored type carried out of this
// module into persist.

use serde_json::Value;

// =============================================================================
// Boundary: concept:json-parse  →  sugar-shim-serde-json-rust
// =============================================================================
pub fn json_parse(s: &str) -> Result<Value, String> {
    serde_json::from_str(s).map_err(|e| e.to_string())
}

// =============================================================================
// Boundary: concept:json-serialize  →  sugar-shim-serde-json-rust
// =============================================================================
pub fn json_serialize(v: &Value) -> Result<String, String> {
    serde_json::to_string(v).map_err(|e| e.to_string())
}

// =============================================================================
// User-side type: the validated event the rest of the spine carries.
// =============================================================================

#[derive(Debug, Clone, PartialEq)]
pub struct ValidEvent {
    pub event_type: String,
    pub user: String,
    pub payload_text: String,
}

// =============================================================================
// User-side function: parse_event.
// Lifter-derived contract:
//   pre:  s is a UTF-8 string (rust type system)
//   post: result is Ok iff (input is well-formed JSON object)
//                       AND (input.event_type is non-empty string)
//                       AND (input.user is non-empty string)
//                       AND (input.payload exists)
// The empty-input and empty-user early-returns lift to pre-condition
// witnesses on the Ok arm.
// =============================================================================

pub fn parse_event(input: &str) -> Result<ValidEvent, String> {
    if input.is_empty() {
        return Err("ingest: empty input".into());
    }
    let v = json_parse(input)?;
    let event_type = v["event_type"]
        .as_str()
        .ok_or_else(|| "ingest: missing event_type".to_string())?
        .to_string();
    let user = v["user"]
        .as_str()
        .ok_or_else(|| "ingest: missing user".to_string())?
        .to_string();
    if user.is_empty() {
        return Err("ingest: empty user".into());
    }
    let payload_text = json_serialize(&v["payload"])?;
    Ok(ValidEvent {
        event_type,
        user,
        payload_text,
    })
}
