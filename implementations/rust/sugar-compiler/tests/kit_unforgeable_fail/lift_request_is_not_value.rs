// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `Kit::lift` takes a strong `LiftRequest` (#3855), not free-form
// `serde_json::Value`. Assigning the method to a Value-accepting function
// pointer must fail to compile — the type system is the instrument.
fn main() {
    let _f: fn(
        &sugar_compiler::kit::Kit,
        serde_json::Value,
    ) -> Result<libsugar::core::DomainClaim, sugar_compiler::kit::KitError> =
        sugar_compiler::kit::Kit::lift;
}
