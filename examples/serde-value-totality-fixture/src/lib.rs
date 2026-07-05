// SPDX-License-Identifier: MIT OR Apache-2.0
//
// serde-value-totality-fixture: Phase 2 Tier D-lib source-code exhibit.
//
// This fixture contains the production pattern that the D-lib tier closes:
// `serde_json::to_string(v).unwrap()` with `v: &serde_json::Value`.
//
// WHY THIS IS PANIC-SAFE:
//   `serde_json::to_string::<serde_json::Value>` is TOTAL -- it always
//   returns Ok. The Value type invariants guarantee it:
//
//     1. Map keys: always String (enforced by Value::Object's IndexMap<String,..>)
//     2. Numbers: always finite (Number::from_f64 rejects NaN/Inf at construction)
//     3. No IO: writes to an in-memory buffer, no syscall can fail
//     4. No custom Serialize: Value uses serde_json's own infallible serializer
//
//   The D-lib mechanism: the `serde_json_to_string_value` contract in the
//   serde-json-rust shim carries `post = is_ok(result)` (the strengthened
//   totality postcondition). When the verifier processes the `.unwrap()` call,
//   `body_discharge::callee_post_guard_fact` detects that the arg_term is a ctor
//   whose bridge-target contract has `post = is_ok(result)`, and injects
//   `is_ok(arg_term)` into the guard context. The existing `(and guard_facts) =>
//   pre` discharge path then fires: `is_ok(arg_term) => is_ok(arg_term)` is a
//   tautology, and the site reports PANIC-SAFE.
//
// DISCRIMINATION CONTROL:
//   `render_generic` calls `serde_json::to_string(&x).unwrap()` with
//   `x: &str` -- a non-Value type. The generic to_string CAN fail for
//   arbitrary T (e.g. map keys that are not strings). No totality contract
//   is supplied for this call, so the site stays UNDECIDABLE (unproven).
//   This confirms the Value-specialization is real and does not leak to
//   arbitrary T.
//
// The deterministic tests for both verdicts live in
// sugar-cli/src/cmd_verify.rs (where verify_one_claim is accessible),
// mirroring the panic-freedom-fixture test pattern.

/// The positive site: `serde_json::to_string(&v).unwrap()` with `v: Value`.
///
/// This CANNOT PANIC: Value serialization is always Ok. The D-lib totality
/// contract on `to_string::<Value>` supplies `is_ok(result)` as a guard fact,
/// discharging the `unwrap`'s `is_ok` precondition.
pub fn render(v: &serde_json::Value) -> String {
    serde_json::to_string(v).unwrap()
}

/// The positive site for pretty-printing: same argument, same soundness.
pub fn render_pretty(v: &serde_json::Value) -> String {
    serde_json::to_string_pretty(v).unwrap()
}

/// The DISCRIMINATION CONTROL: `to_string` on a non-Value type.
///
/// The generic `serde_json::to_string::<str>` has no totality contract in
/// the shim. The site stays UNDECIDABLE -- the verifier cannot prove it
/// panic-safe. This is the refuse-floor: a non-total site must NOT be
/// vacuous-passed.
///
/// Note: `str` happens to serialize fine at runtime, but soundness requires
/// a SOUND contract, not a runtime observation. No contract is supplied for
/// non-Value to_string, so it honestly stays undecidable.
pub fn render_generic(x: &str) -> String {
    // Control: no totality contract -> UNDECIDABLE (never PANIC-SAFE).
    serde_json::to_string(x).unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn render_produces_valid_json() {
        let v = json!({"key": "value", "n": 42});
        let s = render(&v);
        let reparsed: serde_json::Value = serde_json::from_str(&s).unwrap();
        assert_eq!(reparsed, v);
    }

    #[test]
    fn render_pretty_produces_valid_json() {
        let v = json!({"a": 1});
        let s = render_pretty(&v);
        assert!(s.contains('\n'), "pretty output should contain newlines");
        let reparsed: serde_json::Value = serde_json::from_str(&s).unwrap();
        assert_eq!(reparsed, v);
    }

    #[test]
    fn render_generic_string_compiles_and_runs() {
        // The control function is runtime-safe for str -- but the VERIFIER
        // cannot prove it panic-safe because no totality contract exists for
        // non-Value to_string. This test confirms the code compiles and the
        // discrimination is about contract presence, not runtime safety.
        let s = render_generic("hello");
        assert_eq!(s, "\"hello\"");
    }
}
