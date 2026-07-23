use sugar_ir_types::binding_provenance::{BindingProvenanceError, SubstitutionTraceV1};

fn canonical(value: serde_json::Value) -> sugar_canonicalizer::Value {
    match value {
        serde_json::Value::Null => sugar_canonicalizer::Value::Null,
        serde_json::Value::Bool(value) => sugar_canonicalizer::Value::Bool(value),
        serde_json::Value::Number(value) => {
            sugar_canonicalizer::Value::Integer(value.as_i64().map(i128::from).unwrap())
        }
        serde_json::Value::String(value) => sugar_canonicalizer::Value::String(value),
        serde_json::Value::Array(values) => sugar_canonicalizer::Value::Array(
            values
                .into_iter()
                .map(canonical)
                .map(std::sync::Arc::new)
                .collect(),
        ),
        serde_json::Value::Object(values) => sugar_canonicalizer::Value::Object(
            values
                .into_iter()
                .map(|(key, value)| (key, std::sync::Arc::new(canonical(value))))
                .collect(),
        ),
    }
}

fn seal(mut value: serde_json::Value, field: &str) -> serde_json::Value {
    let cid = sugar_canonicalizer::blake3_512_of(
        sugar_canonicalizer::encode_jcs(&canonical(value.clone())).as_bytes(),
    );
    value
        .as_object_mut()
        .unwrap()
        .insert(field.into(), cid.into());
    value
}

#[test]
fn authenticated_trace_round_trips_through_closed_variants() {
    let site = serde_json::json!({
        "file":"arbitrary.py","span":{"start":20,"end":25},
        "source_cid":"blake3-512:source","cid":"blake3-512:fragment"
    });
    let coordinate = seal(
        serde_json::json!({
            "kind":"binding-coordinate","schemaVersion":"1",
            "scopeOwnerCid":"blake3-512:scope","bindingSite":site,
            "projectionPath":["targets",0]
        }),
        "bindingCoordinateCid",
    );
    let testimony = seal(
        serde_json::json!({
            "kind":"constructed-value-testimony","schemaVersion":"1",
            "sourceFragmentCid":"blake3-512:fragment",
            "semanticValueCid":"blake3-512:value"
        }),
        "constructedValueTestimonyCid",
    );
    let record = seal(
        serde_json::json!({
            "kind":"substitution-trace-record","schemaVersion":"1",
            "statementSource":site,"preEntries":[],
            "postEntries":[{"coordinate":coordinate,"state":{"kind":"bound","testimony":testimony}}]
        }),
        "recordCid",
    );
    let trace = seal(
        serde_json::json!({
            "kind":"substitution-trace","schemaVersion":"1",
            "scopeOwnerCid":"blake3-512:scope","records":[record]
        }),
        "traceCid",
    );
    let bytes = serde_json::to_vec(&trace).unwrap();
    let decoded = SubstitutionTraceV1::decode(&bytes).unwrap();
    assert_eq!(serde_json::to_value(decoded).unwrap(), trace);
}

#[test]
fn closed_decoder_rejects_unknown_state_variant() {
    let raw = br#"{
      "kind":"substitution-trace","schemaVersion":"1","scopeOwnerCid":"blake3-512:x",
      "records":[{"kind":"substitution-trace-record","schemaVersion":"1",
        "statementSource":{"file":"x.py","span":{"start":0,"end":1},"source_cid":"blake3-512:s","cid":"blake3-512:f"},
        "preEntries":[],"postEntries":[{"coordinate":{
          "kind":"binding-coordinate","schemaVersion":"1","scopeOwnerCid":"blake3-512:x",
          "bindingSite":{"file":"x.py","span":{"start":0,"end":1},"source_cid":"blake3-512:s","cid":"blake3-512:f"},
          "projectionPath":["target",0],"bindingCoordinateCid":"blake3-512:c"},
          "state":{"kind":"future-state","value":"x"}}],"recordCid":"blake3-512:r"}],
      "traceCid":"blake3-512:t"}"#;
    let error = SubstitutionTraceV1::decode(raw).unwrap_err();
    assert!(matches!(error, BindingProvenanceError::Malformed(_)));
}

#[test]
fn stale_trace_cid_is_loud() {
    let raw = br#"{
      "kind":"substitution-trace","schemaVersion":"1","scopeOwnerCid":"blake3-512:x",
      "records":[],"traceCid":"blake3-512:stale"}"#;
    assert_eq!(
        SubstitutionTraceV1::decode(raw).unwrap_err(),
        BindingProvenanceError::CidMismatch("traceCid")
    );
}
