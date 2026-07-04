// SPDX-License-Identifier: MIT OR Apache-2.0
//
// §6 Content-addressing rules.
//
// §6.1: CID = "blake3-512:" ++ hex(BLAKE3-512(<cid_input>))
// where cid_input = JCS({ content, critical, kind, protocol_versions,
//                         provenance_cid, schemaVersion, version })
//
// Note: the `cid` field itself is ELIDED from the input map.
// `protocol_versions` MUST be sorted ascending lexicographically (§6.1).
//
// §8.3: Failure-memento CID input:
//   JCS({ declared_source, failure_at, kind, plugin_kind,
//         reason_detail, reason_kind, schemaVersion })

use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};

use crate::types::{LoadOrderEntry, LoadedEntry, PluginHeader, PluginLoadFailureMementoHeader};

/// Compute the content CID for a plugin header per §6.1.
///
/// `protocol_versions` are sorted ascending before JCS.
pub fn compute_plugin_cid(header: &PluginHeader) -> String {
    // Sort protocol_versions ascending (§6.1).
    let mut pv = header.protocol_versions.clone();
    pv.sort();
    let pv_values: Vec<Arc<Value>> = pv.iter().map(|s| Value::string(s.clone())).collect();

    // Build the content value.  serde_json::Value -> sugar_canonicalizer::Value.
    let content_v = serde_json_to_value(&header.content);

    // JCS key order: alphabetical (JCS enforces at emit; we build in any order).
    let input_v = Value::object([
        ("content", content_v),
        ("critical", Value::boolean(header.critical)),
        ("kind", Value::string(header.kind.clone())),
        ("protocol_versions", Value::array(pv_values)),
        (
            "provenance_cid",
            Value::string(header.provenance_cid.clone()),
        ),
        (
            "schemaVersion",
            Value::string(header.schema_version.clone()),
        ),
        ("version", Value::string(header.version.clone())),
    ]);

    blake3_512_of(encode_jcs(&input_v).as_bytes())
}

/// Compute the failure-memento CID per §8.3.
pub fn compute_failure_cid(header: &PluginLoadFailureMementoHeader) -> String {
    let input_v = Value::object([
        (
            "declared_source",
            Value::string(header.declared_source.clone()),
        ),
        ("failure_at", Value::string(header.failure_at.clone())),
        ("kind", Value::string("plugin-load-failure".to_string())),
        ("plugin_kind", Value::string(header.plugin_kind.clone())),
        ("reason_detail", Value::string(header.reason_detail.clone())),
        ("reason_kind", Value::string(header.reason_kind.to_string())),
        ("schemaVersion", Value::string("1".to_string())),
    ]);
    blake3_512_of(encode_jcs(&input_v).as_bytes())
}

/// Convert serde_json::Value to sugar_canonicalizer::Value.
///
/// Float numbers are converted to their Display string because JCS does not
/// support IEEE 754 doubles directly in the way we need; the plugin content
/// spec does not use floats, so this case is a safety net only.
pub fn serde_json_to_value(v: &serde_json::Value) -> Arc<Value> {
    match v {
        serde_json::Value::Null => Value::null(),
        serde_json::Value::Bool(b) => Value::boolean(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::integer(i128::from(i))
            } else {
                Value::string(n.to_string())
            }
        }
        serde_json::Value::String(s) => Value::string(s.clone()),
        serde_json::Value::Array(arr) => {
            Value::array(arr.iter().map(serde_json_to_value).collect())
        }
        serde_json::Value::Object(obj) => {
            Value::object(obj.iter().map(|(k, v)| (k.clone(), serde_json_to_value(v))))
        }
    }
}

// ---------------------------------------------------------------------------
// Registry-memento CID (§9.3): JCS over all header fields except `cid`.
// ---------------------------------------------------------------------------

use crate::registry::PluginRegistryMementoHeader;

/// Compute the CID for a PluginRegistryMemento per §9.3.
///
/// `load_order` encodes `{kind, cid, source}` objects per §9.1 B1.
/// `loaded` encodes `{kind, cid}` objects sorted by cid ascending per §9.1 B2.
pub fn compute_registry_cid(header: &PluginRegistryMementoHeader) -> String {
    // loaded: array of {kind, cid} objects already sorted by cid ascending.
    let loaded_v: Vec<Arc<Value>> = header
        .loaded
        .iter()
        .map(|e: &LoadedEntry| {
            Value::object([
                ("cid", Value::string(e.cid.clone())),
                ("kind", Value::string(e.kind.clone())),
            ])
        })
        .collect();

    let failures_v: Vec<Arc<Value>> = header
        .failures
        .iter()
        .map(|cid| Value::string(cid.clone()))
        .collect();

    // load_order: array of {kind, cid, source} objects in insertion order.
    let load_order_v: Vec<Arc<Value>> = header
        .load_order
        .iter()
        .map(|e: &LoadOrderEntry| {
            Value::object([
                ("cid", Value::string(e.cid.clone())),
                ("kind", Value::string(e.kind.clone())),
                ("source", Value::string(e.source.clone())),
            ])
        })
        .collect();

    let rpv_v: Vec<Arc<Value>> = header
        .runtime_protocol_versions
        .iter()
        .map(|s| Value::string(s.clone()))
        .collect();

    let mut fields = vec![(
        "built_in_count",
        Value::integer(header.built_in_count as i128),
    )];
    fields.extend([
        ("failures", Value::array(failures_v)),
        ("kind", Value::string("plugin-registry".to_string())),
        ("load_order", Value::array(load_order_v)),
        ("loaded", Value::array(loaded_v)),
        ("runtime_protocol_versions", Value::array(rpv_v)),
        ("schemaVersion", Value::string("1".to_string())),
        ("sealed_at", Value::string(header.sealed_at.clone())),
    ]);
    let input_v = Value::object(fields);

    blake3_512_of(encode_jcs(&input_v).as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{FailureReasonKind, PluginHeader};

    #[test]
    fn cid_elides_cid_field() {
        // Two headers identical except one has cid="something" and the other has
        // cid="something-else" - they MUST produce the same CID because `cid`
        // is not part of the input.
        let h1 = PluginHeader {
            cid: "blake3-512:aaaaaa".to_string(),
            content: serde_json::json!({}),
            critical: false,
            kind: "test:dummy".to_string(),
            protocol_versions: vec!["pep/1.7.0".to_string()],
            provenance_cid: "blake3-512:provenance".to_string(),
            schema_version: "1".to_string(),
            version: "0.1.0".to_string(),
        };
        let h2 = PluginHeader {
            cid: "blake3-512:bbbbbb".to_string(),
            ..h1.clone()
        };
        assert_eq!(compute_plugin_cid(&h1), compute_plugin_cid(&h2));
    }

    #[test]
    fn protocol_versions_sort_is_applied() {
        // Un-sorted vs sorted protocol_versions must produce the same CID.
        let sorted = PluginHeader {
            cid: String::new(),
            content: serde_json::json!({"x": 1}),
            critical: false,
            kind: "test:dummy".to_string(),
            protocol_versions: vec!["pep/1.5.0".to_string(), "pep/1.7.0".to_string()],
            provenance_cid: "blake3-512:p".to_string(),
            schema_version: "1".to_string(),
            version: "1.0.0".to_string(),
        };
        let unsorted = PluginHeader {
            protocol_versions: vec!["pep/1.7.0".to_string(), "pep/1.5.0".to_string()],
            ..sorted.clone()
        };
        assert_eq!(compute_plugin_cid(&sorted), compute_plugin_cid(&unsorted));
    }

    #[test]
    fn failure_cid_is_deterministic() {
        let h = PluginLoadFailureMementoHeader {
            cid: String::new(),
            declared_source: "sugar:./missing.json".to_string(),
            failure_at: "2026-05-12T00:00:00.000Z".to_string(),
            kind: "plugin-load-failure".to_string(),
            plugin_kind: "sugar".to_string(),
            reason_detail: "no such file or directory".to_string(),
            reason_kind: FailureReasonKind::FileNotFound,
            schema_version: "1".to_string(),
        };
        let c1 = compute_failure_cid(&h);
        let c2 = compute_failure_cid(&h);
        assert_eq!(c1, c2);
        assert!(c1.starts_with("blake3-512:"));
    }
}
