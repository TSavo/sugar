//! Cross-language byte-exactness proof for the parameter-contract crux.
//!
//! Python (`caller_parameter_contract.ParameterOwnedContractV1.mint`) emits the
//! fixture; this test deserializes it under `deny_unknown_fields` and runs the
//! full `validate()`, which re-derives `contractCid` from `semanticDecl` (JCS)
//! and re-checks that the four ownership sub-fields inside `semanticDecl` equal
//! the sibling fields byte-for-byte. If Python's JCS or wire shape diverged from
//! Rust's, this fails. This is the crux the prior passes could have botched.

use sugar_linker::caller_parameter::ParameterOwnedContractV1;

#[test]
fn python_emitted_owned_contract_validates_cross_language() {
    let raw = include_str!("fixtures/owned_contract_encodebase64.json");
    let owned: ParameterOwnedContractV1 = serde_json::from_str(raw)
        .expect("Python fixture must deserialize under deny_unknown_fields");
    owned.validate().expect(
        "Python-emitted ParameterOwnedContractV1 must pass Rust validate() byte-identically",
    );
    assert_eq!(owned.formal_declarations.len(), 1);
    assert_eq!(
        owned.formal_declarations[0].coordinate.declared_name,
        "value"
    );
    assert_eq!(owned.declared_demand_cids.len(), 1);
}
