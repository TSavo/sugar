// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Hover type-resolution fixture. The single production function does the exact
// shape the sugar-cli panic census is dominated by:
//
//     serde_json::to_string(value).unwrap()
//
// The `.unwrap()` RECEIVER is `serde_json::to_string(value)` -- a workspace-local
// call expression whose type is std `Result<String, serde_json::Error>`. The old
// definition-file-stem heuristic derives the receiver-type stem from the file the
// method DEFINITION lands in; for a method called on a workspace-local receiver
// expression that path can yield nothing or the wrong file. The hover refinement
// asks rust-analyzer for the receiver's OWN type at the `unwrap` ident position,
// which renders `core::result::Result<...>` directly.
//
// The probe (`sugar-walk`'s `hover_probe` bin) drives `resolve_typed_classified`
// at the `unwrap` ident below and asserts `stem_source == "hover"` (the
// discrimination: that hover FIRED, not merely that the final stem happens to be
// "result"), printing the raw hover markdown so the live rust-analyzer output is
// seen rather than assumed.

use serde_json::Value;

/// Serialize `value` and unwrap. The `.unwrap()` is the panic leaf under test.
pub fn render(value: &Value) -> String {
    serde_json::to_string(value).unwrap()
}
