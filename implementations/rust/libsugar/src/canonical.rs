// SPDX-License-Identifier: MIT OR Apache-2.0

use std::sync::Arc;

use serde::Serialize;
use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, json_to_value, Value as CValue};

use crate::{Result, SugarError};

const LEGACY_CONCEPT_PREFIX: &str = "concept:";

pub fn serializable_jcs<T: Serialize>(value: &T) -> Result<String> {
    let json = serde_json::to_value(value)
        .map_err(|e| SugarError::Message(format!("serialize JSON: {e}")))?;
    json_jcs(&json)
}

pub fn serializable_cid<T: Serialize>(value: &T) -> Result<String> {
    let jcs = serializable_jcs(value)?;
    Ok(blake3_512_of(jcs.as_bytes()))
}

pub fn json_jcs(value: &Json) -> Result<String> {
    let canonical = json_to_cvalue(value)?;
    Ok(encode_jcs(&canonical))
}

pub fn json_cid(value: &Json) -> Result<String> {
    let jcs = json_jcs(value)?;
    Ok(blake3_512_of(jcs.as_bytes()))
}

/// Canonical operation identity: an op CID is the JSON CID of the op shape.
pub fn op_cid_from_shape(shape: &Json) -> Result<String> {
    json_cid(shape)
}

pub fn local_operator_shape(name: &str) -> Json {
    serde_json::json!({
        "kind": "local-operator",
        "name": bare_local_operator_name(name),
    })
}

pub fn local_op_cid(name: &str) -> Result<String> {
    op_cid_from_shape(&local_operator_shape(name))
}

pub fn bare_local_operator_name(name: &str) -> &str {
    // sugar-audit: default-ok(absent-legacy-concept-prefix-means-the-name-is-already-bare)
    name.strip_prefix(LEGACY_CONCEPT_PREFIX).unwrap_or(name)
}

pub fn is_blake3_512_cid(value: &str) -> bool {
    sugar_canonicalizer::is_blake3_512_cid(value)
}

/// #3901: shared refuse door — same membrane as feed / claim-envelope mint.
fn json_to_cvalue(value: &Json) -> Result<Arc<CValue>> {
    json_to_value(value).map_err(|err| {
        SugarError::Message(format!(
            "non-integer JSON number cannot be canonicalized: {err}"
        ))
    })
}

#[cfg(test)]
mod concept_excision_tests {
    use super::*;

    // INVARIANCE that makes the concept:* op-prefix excision CID-safe: the
    // legacy `concept:` prefix is stripped before hashing, so a debared op
    // name produces the byte-identical op CID. This locks the property the
    // walk_rpc literal debare (increment 1 of the concept-hub amputation)
    // relies on -- removing the prefix moves zero proof bytes. When the prefix
    // and its strip are finally deleted, this test goes with them.
    #[test]
    fn legacy_concept_prefix_is_cid_neutral() {
        for op in [
            "literal",
            "comment",
            "add",
            "json-parse",
            "sql-query",
            "http-request",
        ] {
            let prefixed = local_op_cid(&format!("concept:{op}")).expect("prefixed");
            let bare = local_op_cid(op).expect("bare");
            assert_eq!(prefixed, bare, "concept:{op} must hash identically to {op}");
            assert!(bare.starts_with("blake3-512:"));
        }
    }
}
