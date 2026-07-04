// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Wire-shape types matching §1.1 (plugin-memento CDDL) and §8.1
// (PluginLoadFailureMemento CDDL).
//
// Locked JCS key order documented per §1.1:
//   header:   cid, content, critical, kind, protocol_versions,
//             provenance_cid, schemaVersion, version
//   envelope: declaredAt, signature, signer
//   metadata: maintainer?, note?, source_url?
//
// serde field names are snake_case matching the spec wire names.

use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;

// ---------------------------------------------------------------------------
// §9.1 load_order and loaded entry types (B1 + B2 wire shape fix)
// ---------------------------------------------------------------------------

/// One entry in PluginRegistryMemento.load_order (§9.1).
/// Wire shape: `{ kind: plugin-kind, cid: cid, source: tstr }`
/// `source` is the verbatim CLI flag value (e.g. `"/path/to/spring.json"`)
/// for §9.4 audit-replay.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LoadOrderEntry {
    pub cid: String,
    pub kind: String,
    pub source: String,
}

/// One entry in PluginRegistryMemento.loaded (§9.1).
/// Wire shape: `{ kind: plugin-kind, cid: cid }`
/// The `loaded` array is sorted by cid ascending per §9.1.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct LoadedEntry {
    pub cid: String,
    pub kind: String,
}

// ---------------------------------------------------------------------------
// §1 Plugin memento
// ---------------------------------------------------------------------------

/// The envelope layer.  Holds the Ed25519 signature over JCS(header ++ metadata).
/// Per §1.2: `signature` MUST be `"ed25519:<base64>"` form; `signer` MUST be
/// `"ed25519:<base64>"` public key.  In PEP 1.7.0 v0 loader we parse and store
/// these fields; full signature verification is a TODO (§12 out-of-scope marker
/// for the skeleton).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PluginEnvelope {
    #[serde(rename = "declaredAt")]
    pub declared_at: String,
    pub signature: String,
    pub signer: String,
}

/// The header layer.  `cid` is the DERIVED content address (§6.1).
/// `content` is opaque JSON; its CDDL is defined by the consumer spec for `kind`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PluginHeader {
    pub cid: String,
    pub content: JsonValue,
    pub critical: bool,
    pub kind: String,
    pub protocol_versions: Vec<String>,
    pub provenance_cid: String,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    pub version: String,
}

/// The optional metadata layer.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct PluginMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub maintainer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_url: Option<String>,
}

/// Full plugin memento: envelope + header + metadata (§1.1).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PluginMemento {
    pub envelope: PluginEnvelope,
    pub header: PluginHeader,
    pub metadata: PluginMetadata,
}

impl PluginMemento {
    /// The CID from the header (convenience accessor).
    pub fn cid(&self) -> &str {
        &self.header.cid
    }

    /// The `kind` field (convenience accessor).
    pub fn kind(&self) -> &str {
        &self.header.kind
    }

    /// The `critical` flag (convenience accessor).
    pub fn is_critical(&self) -> bool {
        self.header.critical
    }
}

// ---------------------------------------------------------------------------
// §8.1 PluginLoadFailureMemento
// ---------------------------------------------------------------------------

/// All canonical `reason_kind` values from §8.1 plus an open-extension variant.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum FailureReasonKind {
    FileNotFound,
    ParseError,
    ValidationError,
    RpcTimeout,
    RpcError,
    ProtocolVersionMismatch,
    SignatureInvalid,
    CidMismatch,
    DuplicateCidCollision,
    CriticalLoadAborted,
    /// Open-extension: any string the spec allows as a `tstr`.
    #[serde(untagged)]
    Other(String),
}

impl std::fmt::Display for FailureReasonKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FileNotFound => f.write_str("file-not-found"),
            Self::ParseError => f.write_str("parse-error"),
            Self::ValidationError => f.write_str("validation-error"),
            Self::RpcTimeout => f.write_str("rpc-timeout"),
            Self::RpcError => f.write_str("rpc-error"),
            Self::ProtocolVersionMismatch => f.write_str("protocol-version-mismatch"),
            Self::SignatureInvalid => f.write_str("signature-invalid"),
            Self::CidMismatch => f.write_str("cid-mismatch"),
            Self::DuplicateCidCollision => f.write_str("duplicate-cid-collision"),
            Self::CriticalLoadAborted => f.write_str("critical-load-aborted"),
            Self::Other(s) => f.write_str(s),
        }
    }
}

/// Failure-memento header (§8.1).
///
/// JCS key order: cid, declared_source, failure_at, kind,
///                plugin_kind, reason_detail, reason_kind, schemaVersion
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PluginLoadFailureMementoHeader {
    pub cid: String,
    pub declared_source: String,
    pub failure_at: String,
    pub kind: String,
    pub plugin_kind: String,
    pub reason_detail: String,
    pub reason_kind: FailureReasonKind,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
}

/// Full PluginLoadFailureMemento (§8.1): envelope + header + metadata.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PluginLoadFailureMemento {
    pub envelope: PluginEnvelope,
    pub header: PluginLoadFailureMementoHeader,
    #[serde(default)]
    pub metadata: FailureMementoMetadata,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct FailureMementoMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}
