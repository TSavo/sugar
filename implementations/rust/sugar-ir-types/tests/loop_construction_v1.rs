use sugar_ir_types::loop_construction::{LoopConstructionGraphV1, LoopWireError};

const PYTHON_GRAPH: &[u8] = include_bytes!("fixtures/python_loop_construction_v1.json");

#[test]
fn python_loop_construction_round_trips_through_closed_rust_decoder() {
    let decoded = LoopConstructionGraphV1::decode(PYTHON_GRAPH)
        .expect("Python-authenticated LoopConstructionV1 must decode");
    let reserialized = serde_json::to_vec(&decoded).expect("closed graph serializes");
    assert_eq!(
        LoopConstructionGraphV1::decode(&reserialized).unwrap(),
        decoded
    );
}

#[test]
fn unknown_loop_record_variant_stays_typed_loud() {
    let mut wire: serde_json::Value = serde_json::from_slice(PYTHON_GRAPH).unwrap();
    wire["records"][0]["kind"] = serde_json::Value::String("future-loop-record".into());
    let error = LoopConstructionGraphV1::decode(&serde_json::to_vec(&wire).unwrap())
        .expect_err("unknown closed variant must not enter the graph");
    assert!(matches!(error, LoopWireError::Malformed(_)));
}

#[test]
fn stale_python_loop_cid_stays_typed_loud() {
    let mut wire: serde_json::Value = serde_json::from_slice(PYTHON_GRAPH).unwrap();
    wire["root"]["loopConstructionCid"] = serde_json::Value::String("blake3-512:stale".into());
    assert!(matches!(
        LoopConstructionGraphV1::decode(&serde_json::to_vec(&wire).unwrap()),
        Err(LoopWireError::CidMismatch(_))
    ));
}
