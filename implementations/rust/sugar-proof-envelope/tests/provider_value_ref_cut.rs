use sugar_proof_envelope::decode_import_signature_v2;

#[test]
fn provider_value_ref_default_is_not_in_the_derived_contract_schema() {
    let wire = serde_json::json!({
        "parameters": [{
            "name": "match",
            "sort": {"kind": "primitive", "name": "String"},
            "passing": {"kind": "keyword-only"},
            "required": false,
            "default": {
                "kind": "provider-value-ref",
                "valueRefCid": format!("blake3-512:{}", "1".repeat(128)),
                "sort": {"kind": "primitive", "name": "String"}
            }
        }]
    });

    let error = decode_import_signature_v2(&wire).expect_err("provider authority is cut");
    assert!(error.contains("malformed ImportSignatureV2"), "{error}");
}
