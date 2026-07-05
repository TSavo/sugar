// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 3 discrimination fixture: serde_json Value totality.
//
// Acceptance criteria:
//   f: serde_json::to_string(&serde_json::Value).unwrap()
//      -> PANIC-SAFE (Value serialization is total; is_ok(result) axiom fires)
//   f_expect: serde_json::to_string(&serde_json::Value).expect(...)
//      -> PANIC-SAFE through the same totality producer and Result precondition
//
//   g: serde_json::to_string(&MyStruct).unwrap()
//      -> UNDECIDABLE (struct Serialize may fail; no totality contract)
//      -> falsePass MUST be 0; g stays honestly unproven.
//
// The two functions share the same callee leaf (to_string) and the same
// .unwrap() shape. The ONLY discriminant is the argument type. If both
// discharge panic-safe, the disambiguation leaked to non-Value (false pass).
// If neither discharges, the disambiguation never fired (totality broken).

use serde::Serialize;
use serde_json::Value;

/// The totality case: `v` is `serde_json::Value`. The oracle resolves the
/// arg type to stem "value" -> disambiguated to serde_json_to_string_value
/// (post: is_ok(result)) -> .unwrap() discharges PANIC-SAFE.
pub fn f(v: &Value) -> String {
    serde_json::to_string(v).unwrap()
}

/// Same totality producer as `f`, but through `Result::expect`. This proves the
/// rust-std `result_expect` partial composes with the existing D-lib totality
/// path rather than only existing in the shim catalog.
pub fn f_expect(v: &Value) -> String {
    serde_json::to_string(v).expect("infallible for Value")
}

/// The non-total case: `s` is a user-defined struct. The oracle resolves the
/// arg type to a stem that is NOT "value" -> stays to_string -> no totality
/// contract -> .unwrap() stays UNDECIDABLE. This is the refuse-floor check.
#[derive(Serialize)]
pub struct MyStruct {
    pub x: i32,
    pub name: String,
}

pub fn g(s: &MyStruct) -> String {
    serde_json::to_string(s).unwrap()
}
