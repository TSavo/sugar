// SPDX-License-Identifier: Apache-2.0
//
// Round-trip, CID recompute, and fail-closed validation tests for
// ObservationWrapperMemento.

use std::sync::Arc;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_types::{
    EffectOccurrence, InvariantViolation, ObservationWrapperMemento, OccurrenceKind, OccurrenceRole,
};

const ARTIFACT_CID: &str = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const OBJECT_FCM_CID: &str = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const PRESERVATION_CID: &str = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const PROVENANCE_CID: &str = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
const WRAPPER_FCM_CID: &str = "blake3-512:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";

fn observer_effect() -> EffectOccurrence {
    EffectOccurrence {
        args: json!({
            "channel": "filesystem",
            "operation": "write"
        }),
        discharge_key: "io:filesystem:write".to_string(),
        locator: json!({
            "file": "src/wrapper.rs",
            "symbol": "observe"
        }),
        occurrence_kind: OccurrenceKind::Io,
        role: OccurrenceRole::Body,
        signature_cid: "blake3-512:io-signature".to_string(),
    }
}

fn object_effect() -> EffectOccurrence {
    EffectOccurrence {
        args: json!({
            "target": "state"
        }),
        discharge_key: "read:state".to_string(),
        locator: json!({
            "file": "src/object.rs",
            "line": 7
        }),
        occurrence_kind: OccurrenceKind::Reads,
        role: OccurrenceRole::Body,
        signature_cid: "blake3-512:mem-read-signature".to_string(),
    }
}

fn wrapper() -> ObservationWrapperMemento {
    ObservationWrapperMemento {
        emitted_artifact_cid: ARTIFACT_CID.to_string(),
        mode: "monitor".to_string(),
        object_fcm_cid: OBJECT_FCM_CID.to_string(),
        observer_effects: vec![observer_effect()],
        preservation_claim_cid: PRESERVATION_CID.to_string(),
        provenance_cid: PROVENANCE_CID.to_string(),
        wrapper_fcm_cid: WRAPPER_FCM_CID.to_string(),
    }
}

fn object_effects() -> Vec<EffectOccurrence> {
    vec![object_effect()]
}

fn wrapper_effects() -> Vec<EffectOccurrence> {
    vec![object_effect(), observer_effect()]
}

fn to_cvalue(value: &Json) -> Arc<CValue> {
    match value {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => CValue::integer(i128::from(
            n.as_i64().expect("test fixture numbers fit i64"),
        )),
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(to_cvalue).collect()),
        Json::Object(map) => CValue::object(
            map.iter()
                .map(|(key, value)| (key.clone(), to_cvalue(value)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn cid_for(wrapper: &ObservationWrapperMemento) -> String {
    let json = serde_json::to_value(wrapper).expect("serialize to json value");
    let canonical = to_cvalue(&json);
    blake3_512_of(encode_jcs(&canonical).as_bytes())
}

#[test]
fn observation_wrapper_round_trip_and_cid_recompute() {
    let m = wrapper();
    let s = serde_json::to_string(&m).expect("serialize");
    let parsed: ObservationWrapperMemento = serde_json::from_str(&s).expect("parse");

    assert_eq!(parsed, m);
    assert_eq!(
        cid_for(&parsed),
        "blake3-512:7bd75a0ba904f26aeae3ddb138f6c52bb676190bb7b3b014d5d7db1c6ca7ac48209d6a5651af9ba07488939cf80dd72406978eba369c0b58cce4d32df1a703b4"
    );
}

#[test]
fn validate_accepts_well_formed_wrapper() {
    assert_eq!(
        wrapper().validate(&object_effects(), &wrapper_effects(), &[]),
        Ok(())
    );
}

#[test]
fn validate_accepts_core_observation_modes() {
    for mode in ["witness", "monitor", "emitter", "gate"] {
        let mut m = wrapper();
        m.mode = mode.to_string();
        assert_eq!(
            m.validate(&object_effects(), &wrapper_effects(), &[]),
            Ok(()),
            "{mode} must be a core observation mode"
        );
    }
}

#[test]
fn validate_accepts_namespaced_extension_mode_when_allowed() {
    let mut m = wrapper();
    m.mode = "acme:probe".to_string();

    assert_eq!(
        m.validate(&object_effects(), &wrapper_effects(), &["acme:probe"]),
        Ok(())
    );
}

#[test]
fn validate_rejects_unimplemented_namespaced_extension_mode() {
    let mut m = wrapper();
    m.mode = "acme:probe".to_string();

    // Per spec §7, namespaced extension modes MUST fail closed when not on the
    // caller's allowlist, even if syntactically well-formed.
    assert_eq!(
        m.validate(&object_effects(), &wrapper_effects(), &[]),
        Err(InvariantViolation::UnimplementedExtensionMode {
            mode: "acme:probe".to_string()
        })
    );
}

#[test]
fn validate_rejects_unknown_mode() {
    let mut m = wrapper();
    m.mode = "probe".to_string();

    assert_eq!(
        m.validate(&object_effects(), &wrapper_effects(), &[]),
        Err(InvariantViolation::UnknownMode {
            mode: "probe".to_string()
        })
    );
}

#[test]
fn validate_rejects_missing_preservation_claim() {
    let mut m = wrapper();
    m.preservation_claim_cid.clear();

    assert_eq!(
        m.validate(&object_effects(), &wrapper_effects(), &[]),
        Err(InvariantViolation::MissingPreservationClaim)
    );
}

#[test]
fn validate_rejects_empty_observer_effects() {
    let mut m = wrapper();
    m.observer_effects.clear();

    // Spec CDDL: observer_effects = [+ effect-occurrence] (non-empty).
    // An empty list would otherwise trivially pass the dual-invariant loops.
    assert_eq!(
        m.validate(&object_effects(), &wrapper_effects(), &[]),
        Err(InvariantViolation::EmptyObserverEffects)
    );
}

#[test]
fn validate_rejects_observer_effect_on_object() {
    let effect = observer_effect();
    let object = vec![effect.clone()];

    assert_eq!(
        wrapper().validate(&object, &wrapper_effects(), &[]),
        Err(InvariantViolation::ObserverEffectOnObject { effect })
    );
}

#[test]
fn validate_rejects_observer_effect_missing_from_wrapper() {
    let effect = observer_effect();
    let wrapper_only_object = vec![object_effect()];

    assert_eq!(
        wrapper().validate(&object_effects(), &wrapper_only_object, &[]),
        Err(InvariantViolation::ObserverEffectMissingFromWrapper { effect })
    );
}

#[test]
fn validate_rejects_multi_colon_mode_even_if_in_allowlist() {
    // Even if a caller mistakenly puts `a:b:c` in the allowlist, the
    // classifier MUST reject it because it isn't a well-formed
    // `<namespace>:<kind>` (exactly one colon).
    let mut m = wrapper();
    m.mode = "a:b:c".to_string();

    assert_eq!(
        m.validate(&object_effects(), &wrapper_effects(), &["a:b:c"]),
        Err(InvariantViolation::UnknownMode {
            mode: "a:b:c".to_string()
        })
    );
}
