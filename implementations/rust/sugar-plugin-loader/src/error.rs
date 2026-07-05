// SPDX-License-Identifier: MIT OR Apache-2.0
//
// §8 Error model.
//
// `LoadError` maps cleanly to §8.1 `failure-reason-kind` values.
// The loader converts a `LoadError` into a `PluginLoadFailureMemento` and
// either records it (when `critical = false`) or returns it as an Err
// (when `critical = true`), allowing callers to refuse the run.

use thiserror::Error;

use crate::types::FailureReasonKind;

/// Structured error returned by `load_plugin_from_file` and
/// `load_plugin_from_rpc`.  Each variant maps 1-to-1 to a
/// `FailureReasonKind` (§8.1).
#[derive(Debug, Error)]
pub enum LoadError {
    /// The file path resolved to nothing (§8.1 `file-not-found`).
    #[error("file not found: {path}")]
    FileNotFound { path: String },

    /// The JSON could not be parsed or the top-level envelope/header
    /// fields are missing (§8.1 `parse-error`).
    #[error("parse error: {detail}")]
    ParseError { detail: String },

    /// Shape validation failed (§8.1 `validation-error`).
    /// Full CDDL-driven validation is out-of-scope for PEP 1.7.0 v0;
    /// only the required-field shape check is performed.
    #[error("validation error: {detail}")]
    ValidationError { detail: String },

    /// The JSON-RPC server timed out (§8.1 `rpc-timeout`).
    #[error("rpc timeout: {detail}")]
    RpcTimeout { detail: String },

    /// The JSON-RPC server returned an error or non-JSON output
    /// (§8.1 `rpc-error`).
    #[error("rpc error: {detail}")]
    RpcError { detail: String },

    /// The plugin's `protocol_versions` does not contain a token the
    /// runtime accepts (§5 / §8.1 `protocol-version-mismatch`).
    #[error("protocol version mismatch: plugin speaks {plugin_versions:?}, runtime accepts {runtime_versions:?}")]
    ProtocolVersionMismatch {
        plugin_versions: Vec<String>,
        runtime_versions: Vec<String>,
    },

    /// The Ed25519 signature over the header+metadata was invalid
    /// (§8.1 `signature-invalid`).
    #[error("signature invalid: {detail}")]
    SignatureInvalid { detail: String },

    /// The asserted `header.cid` does not match the computed CID (§8.1
    /// `cid-mismatch`).
    #[error("cid mismatch: asserted {asserted}, computed {computed}")]
    CidMismatch { asserted: String, computed: String },

    /// The registry already contains a plugin with this (kind, cid) pair
    /// and the duplicate-CID collision rule fires (§9.2).
    #[error("duplicate cid collision: kind={kind} cid={cid}")]
    DuplicateCidCollision { kind: String, cid: String },
}

impl LoadError {
    /// Map to the canonical `FailureReasonKind` string for the memento.
    pub fn reason_kind(&self) -> FailureReasonKind {
        match self {
            Self::FileNotFound { .. } => FailureReasonKind::FileNotFound,
            Self::ParseError { .. } => FailureReasonKind::ParseError,
            Self::ValidationError { .. } => FailureReasonKind::ValidationError,
            Self::RpcTimeout { .. } => FailureReasonKind::RpcTimeout,
            Self::RpcError { .. } => FailureReasonKind::RpcError,
            Self::ProtocolVersionMismatch { .. } => FailureReasonKind::ProtocolVersionMismatch,
            Self::SignatureInvalid { .. } => FailureReasonKind::SignatureInvalid,
            Self::CidMismatch { .. } => FailureReasonKind::CidMismatch,
            Self::DuplicateCidCollision { .. } => FailureReasonKind::DuplicateCidCollision,
        }
    }

    /// Human-readable detail for the `reason_detail` field.
    pub fn reason_detail(&self) -> String {
        self.to_string()
    }
}
