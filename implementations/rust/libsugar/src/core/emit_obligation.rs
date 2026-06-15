// SPDX-License-Identifier: Apache-2.0
//
// Shared obligation-emission primitives for the lift / materialize /
// recognize / test-lifter verbs.
//
// Each verb that authors substrate evidence into a .proof envelope produces
// one or both of two memento shapes:
//
//   - A **bridge memento** — the resolve-half: `sourceSymbol -> targetContractCid`,
//     wrapped as `{evidence: {kind: "bridge", body: BridgeHeaderV14 +
//     targetContractCid + targetLayer}}`. cmd_materialize emits this from
//     carrier comments; cmd_recognize emits this from AST template matches;
//     the rust-tests lifter emits one for each test call.
//
//   - An **implication contract memento** — the enumerate-half: a `contract`
//     kind whose post atomic contains a `ctor(name=<function>)` term that
//     `enumerate_callsites` finds. cmd_recognize emits this for each tag;
//     the rust-tests lifter emits one per test assertion; cmd_materialize
//     could emit one per carrier comment.
//
// Before this module existed, each verb authored its own copy of the
// memento shape + canonicalization + content-address machinery. They drifted.
// T's directive: "Voltron means lift+materialize+recognize+verify share
// machinery." This module is the shared API; verbs call into it.
//
// Filed as #1579. Closes the duplication between cmd_recognize and
// cmd_materialize.

use std::sync::Arc;

use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CanonicalValue};
use sugar_ir_types::{BridgeHeaderV14, BridgeTarget};

/// Build the bridge memento body (without the outer evidence wrapping).
/// The same shape both cmd_materialize's `materialize_bridge_body` and
/// cmd_recognize's `recognize_bridge_body_with_target` historically built
/// in parallel; collapsed here to one canonical authoring path.
///
/// `target_contract_cid` is the CID the discharger resolves through —
/// it should be a `contract` kind memento that lives in the union pool
/// (either the vendor's published contract or a sibling implication
/// contract minted by the same verb).
pub fn build_bridge_body(
    verb_tag: &str,
    function_name: &str,
    source_layer: &str,
    target_layer: &str,
    target_contract_cid: &str,
) -> Value {
    let header = BridgeHeaderV14 {
        schema_version: "1".to_string(),
        kind: "bridge".to_string(),
        name: format!("{verb_tag}:{source_layer}:{function_name}"),
        source_symbol: function_name.to_string(),
        source_layer: source_layer.to_string(),
        source_contract_cid: target_contract_cid.to_string(),
        target: BridgeTarget::Contract {
            cid: target_contract_cid.to_string(),
        },
    };
    let mut value = serde_json::to_value(header).expect("BridgeHeaderV14 serializes");
    if let Value::Object(map) = &mut value {
        map.insert(
            "targetContractCid".to_string(),
            Value::String(target_contract_cid.to_string()),
        );
        map.insert(
            "targetLayer".to_string(),
            Value::String(target_layer.to_string()),
        );
    }
    value
}

/// Build the implication contract memento body (without the outer
/// evidence wrapping). The post atomic carries a `ctor(name=<function>,
/// args=[<var per param>])` term that `enumerate_callsites` finds when
/// walking contract formulas in the pool.
///
/// Param names are the user's literal source-side identifiers — the
/// substrate alpha-normalizes them at CID time, but having the user
/// spelling in the memento makes the receipt readable.
pub fn build_implication_contract_body(
    verb_tag: &str,
    function_name: &str,
    op_cid: Option<&str>,
    param_source_texts: &[&str],
) -> Value {
    let arg_terms: Vec<Value> = param_source_texts
        .iter()
        .map(|s| json!({ "kind": "var", "name": *s }))
        .collect();
    let ctor = json!({
        "kind": "ctor",
        "name": function_name,
        "args": arg_terms,
    });
    let post = json!({
        "kind": "atomic",
        "args": [ctor],
    });
    let mut body = json!({
        "contractName": format!("{verb_tag}-callsite:{function_name}"),
        "post": post,
    });
    if let Some(cid) = op_cid {
        body["op_cid"] = json!(cid);
    }
    body
}

/// Wrap a body into the canonical evidence envelope and content-address it.
/// Returns (cid, canonical_bytes). The bytes are JCS-canonical JSON; the
/// cid is `blake3-512:` + hex of the bytes.
pub fn member_envelope_canonical(
    evidence_kind: &str,
    body: &Value,
) -> Result<(String, Vec<u8>), String> {
    let envelope = json!({
        "evidence": {
            "kind": evidence_kind,
            "body": body,
        }
    });
    let canonical = canonical_value_of_json(&envelope)?;
    let bytes = encode_jcs(canonical.as_ref());
    let cid = blake3_512_of(bytes.as_bytes());
    Ok((cid, bytes.into_bytes()))
}

/// Recursive serde_json::Value → sugar_canonicalizer::Value mapping.
/// Errors on non-integer numbers (the substrate doesn't admit floats).
pub fn canonical_value_of_json(value: &Value) -> Result<Arc<CanonicalValue>, String> {
    match value {
        Value::Null => Ok(CanonicalValue::null()),
        Value::Bool(b) => Ok(CanonicalValue::boolean(*b)),
        Value::Number(n) => n
            .as_i64()
            .map(|v| v as i128)
            .or_else(|| n.as_u64().map(|v| v as i128))
            .map(CanonicalValue::integer)
            .ok_or_else(|| format!("memento contains non-integer number `{n}`")),
        Value::String(s) => Ok(CanonicalValue::string(s)),
        Value::Array(values) => values
            .iter()
            .map(canonical_value_of_json)
            .collect::<Result<Vec<_>, _>>()
            .map(CanonicalValue::array),
        Value::Object(entries) => entries
            .iter()
            .map(|(k, v)| canonical_value_of_json(v).map(|v| (k.clone(), v)))
            .collect::<Result<Vec<_>, _>>()
            .map(CanonicalValue::object),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bridge_body_carries_source_symbol_and_target_cid() {
        let body = build_bridge_body(
            "recognize",
            "json_parse",
            "rust",
            "serde_json",
            "blake3-512:abc",
        );
        assert_eq!(body["sourceSymbol"], "json_parse");
        assert_eq!(body["sourceLayer"], "rust");
        assert_eq!(body["targetContractCid"], "blake3-512:abc");
        assert_eq!(body["targetLayer"], "serde_json");
        assert_eq!(body["target"]["cid"], "blake3-512:abc");
        assert_eq!(body["name"], "recognize:rust:json_parse");
        assert_eq!(body["kind"], "bridge");
    }

    #[test]
    fn implication_contract_post_atomic_has_ctor_named_for_function() {
        let body = build_implication_contract_body(
            "recognize",
            "json_parse",
            Some("blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            &["input"],
        );
        assert_eq!(body["contractName"], "recognize-callsite:json_parse");
        assert_eq!(
            body["op_cid"],
            "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
        let post = &body["post"];
        assert_eq!(post["kind"], "atomic");
        let args = post["args"].as_array().expect("atomic args");
        assert_eq!(args.len(), 1);
        let ctor = &args[0];
        assert_eq!(ctor["kind"], "ctor");
        assert_eq!(ctor["name"], "json_parse");
        let ctor_args = ctor["args"].as_array().expect("ctor args");
        assert_eq!(ctor_args.len(), 1);
        assert_eq!(ctor_args[0]["kind"], "var");
        assert_eq!(ctor_args[0]["name"], "input");
    }

    #[test]
    fn implication_contract_omits_op_cid_when_absent() {
        let body = build_implication_contract_body("recognize", "f", None, &[]);
        assert!(body.get("op_cid").is_none());
    }

    #[test]
    fn member_envelope_canonical_is_deterministic_for_equal_bodies() {
        let body = json!({"k": "v"});
        let (cid_a, bytes_a) = member_envelope_canonical("contract", &body).unwrap();
        let (cid_b, bytes_b) = member_envelope_canonical("contract", &body).unwrap();
        assert_eq!(cid_a, cid_b);
        assert_eq!(bytes_a, bytes_b);
        assert!(cid_a.starts_with("blake3-512:"));
    }

    #[test]
    fn member_envelope_canonical_differs_when_evidence_kind_differs() {
        let body = json!({"k": "v"});
        let (cid_bridge, _) = member_envelope_canonical("bridge", &body).unwrap();
        let (cid_contract, _) = member_envelope_canonical("contract", &body).unwrap();
        assert_ne!(cid_bridge, cid_contract);
    }
}
