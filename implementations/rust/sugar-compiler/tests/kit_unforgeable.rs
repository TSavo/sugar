// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `Kit` unforgeability (SEAM 3b, Part 5 §2 of the compiler-shape plan):
// the only way to mint a `Kit` is a successful `Kit::rendezvous`. This
// trybuild harness asserts a user crate cannot construct `Kit { .. }`
// directly, cannot call a constructor other than `rendezvous`, and cannot
// get one via `Default`/`Deserialize`. If a future edit adds a public
// field, a `Kit::new`, or a derived `Default`/`Deserialize`, these
// compile-fail cases start compiling and this test goes red.
//
// `LiftManifest` field privacy (#3855): fields are private; the only public
// builder is `LiftManifest::resolved(...)`. The compile-fail case
// `lift_manifest_struct_literal.rs` pins that door.
//
// Strong `Kit::lift` request (#3855 residual): `lift` takes `LiftRequest`, not
// `serde_json::Value`. The compile-fail case `lift_request_is_not_value.rs`
// pins that the free-form blob no longer types at the Kit boundary.

#[test]
fn kit_has_no_forging_constructor() {
    let t = trybuild::TestCases::new();
    t.compile_fail("tests/kit_unforgeable_fail/*.rs");
}
