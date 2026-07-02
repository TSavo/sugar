// SPDX-License-Identifier: Apache-2.0
//
// Proof-file conformance checker.
//
// This is the Rust CLI/reference workflow for the bootstrap target:
// `.proof` bytes -> structured proof-file-format conformance report.
// It deliberately stays at the substrate boundary. Metadata is decoded
// and reported because it is signed bytes, but it is not interpreted as
// normative core logic.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Serialize;
use serde_json::Value as Json;
use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::{ed25519_verify_bytes, MemberView, ProofGraph};

use crate::cbor_decode::CborValue;
use sugar_proof_envelope::decode_for_conformance;

const HASH_TAG_PREFIX: &str = "blake3-512:";

pub const PFCP_R1_FILENAME_CID: &str = "PFCP-R1-FILENAME-CID";
pub const PFCP_R2_DETERMINISTIC_CBOR: &str = "PFCP-R2-DETERMINISTIC-CBOR";
pub const PFCP_R3_ROOT_CATALOG: &str = "PFCP-R3-ROOT-CATALOG";
pub const PFCP_R4_MEMBERS_MAP: &str = "PFCP-R4-MEMBERS-MAP";
pub const PFCP_R5_MEMBER_CID: &str = "PFCP-R5-MEMBER-CID";
pub const PFCP_R6_MEMBER_SIGNATURE: &str = "PFCP-R6-MEMBER-SIGNATURE";
pub const PFCP_R7_METADATA_NON_NORMATIVE: &str = "PFCP-R7-METADATA-NON-NORMATIVE";
pub const PFCP_R8_NO_ENCLOSING_FILE_CID_CLAIM: &str = "PFCP-R8-NO-ENCLOSING-FILE-CID-CLAIM";
pub const PFCP_R9_CATALOG_SIGNATURE: &str = "PFCP-R9-CATALOG-SIGNATURE";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProofFileConformanceError {
    pub rule_id: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProofFileConformanceReport {
    pub kind: String,
    pub schema_version: String,
    pub proof_path: String,
    pub file_cid: String,
    pub filename_cid: Option<String>,
    pub member_count: usize,
    pub metadata_count: usize,
    pub warnings: Vec<String>,
    pub errors: Vec<ProofFileConformanceError>,
}

impl ProofFileConformanceReport {
    pub fn ok(&self) -> bool {
        self.errors.is_empty()
    }

    fn push_error(&mut self, rule_id: &str, message: impl Into<String>) {
        self.errors.push(ProofFileConformanceError {
            rule_id: rule_id.to_string(),
            message: message.into(),
        });
    }

    fn push_warning(&mut self, message: impl Into<String>) {
        self.warnings.push(message.into());
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ProofFormatConformanceWitness {
    pub kind: String,
    pub schema_version: String,
    pub claim_kind: String,
    pub result: bool,
    pub subject_cid: String,
    pub format_proof_cid: Option<String>,
    pub grammar_cid: String,
    pub invariant_set_cid: String,
    pub verifier_cid: String,
    pub policy_cid: String,
    pub report: ProofFileConformanceReport,
}

impl ProofFormatConformanceWitness {
    pub fn from_report(
        report: ProofFileConformanceReport,
        grammar_cid: impl Into<String>,
        invariant_set_cid: impl Into<String>,
        verifier_cid: impl Into<String>,
        policy_cid: impl Into<String>,
    ) -> Self {
        Self {
            kind: "ProofFormatConformanceWitness".into(),
            schema_version: "0.1".into(),
            claim_kind: "proof-format-conformance".into(),
            result: report.ok(),
            subject_cid: report.file_cid.clone(),
            format_proof_cid: None,
            grammar_cid: grammar_cid.into(),
            invariant_set_cid: invariant_set_cid.into(),
            verifier_cid: verifier_cid.into(),
            policy_cid: policy_cid.into(),
            report,
        }
    }

    pub fn with_format_proof_cid(mut self, format_proof_cid: impl Into<String>) -> Self {
        self.format_proof_cid = Some(format_proof_cid.into());
        self
    }
}

pub fn validate_proof_file(path: &Path) -> ProofFileConformanceReport {
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(e) => {
            let mut report = empty_report(path, "");
            report.push_error("PFCP-R0-READ", format!("read {}: {e}", path.display()));
            return report;
        }
    };
    validate_proof_bytes(path, &bytes)
}

pub fn validate_proof_bytes(path: &Path, bytes: &[u8]) -> ProofFileConformanceReport {
    let file_cid = blake3_512_of(bytes);
    let mut report = empty_report(path, &file_cid);

    check_filename_cid(path, &file_cid, &mut report);

    // Catalog-level CBOR validation (PFCP-R2, PFCP-R3, PFCP-R7, PFCP-R8, PFCP-R9).
    // ProofGraph::read() does not expose catalog-level fields (signer, declaredAt,
    // signature, kind, metadata), so cbor_decode::decode is retained here for those
    // checks and for the deterministic re-encoding comparison.
    let catalog = match decode_for_conformance(bytes) {
        Ok(catalog) => catalog,
        Err(e) => {
            report.push_error(
                PFCP_R2_DETERMINISTIC_CBOR,
                format!("CBOR decode failed: {e}"),
            );
            return report;
        }
    };

    let canonical = encode_cbor_value(&catalog);
    if canonical != bytes {
        report.push_error(
            PFCP_R2_DETERMINISTIC_CBOR,
            "file bytes are not the deterministic CBOR encoding of the decoded catalog",
        );
    }

    let root = match catalog.as_map() {
        Some(root) => root,
        None => {
            report.push_error(PFCP_R3_ROOT_CATALOG, "catalog root is not a CBOR map");
            return report;
        }
    };

    if root.get("kind").and_then(CborValue::as_tstr) != Some("catalog") {
        report.push_error(
            PFCP_R3_ROOT_CATALOG,
            "root `kind` is not the literal `catalog`",
        );
    }

    match root.get("metadata") {
        Some(CborValue::Map(meta)) => {
            report.metadata_count = meta.len();
            if map_contains_string(meta, &file_cid) {
                report.push_error(
                    PFCP_R8_NO_ENCLOSING_FILE_CID_CLAIM,
                    "catalog metadata contains the enclosing file CID",
                );
            }
            report.push_warning(format!(
                "{}: metadata is signed and CID-participating, but non-normative for core verification",
                PFCP_R7_METADATA_NON_NORMATIVE
            ));
        }
        Some(_) => {
            report.push_error(PFCP_R7_METADATA_NON_NORMATIVE, "metadata is not a text map");
        }
        None => {}
    }

    if root.get("members").and_then(CborValue::as_map).is_none() {
        report.push_error(PFCP_R4_MEMBERS_MAP, "catalog has no `members` map");
        return report;
    }

    // Parse the typed graph for member-level validation.  ProofGraph::read() gives
    // typed MemberView iterators that replace the manual val.as_bstr() / from_utf8 /
    // pointer("/header/...") bypasses in the old code.
    let graph = match ProofGraph::read(bytes) {
        Ok(g) => g,
        Err(e) => {
            report.push_error(PFCP_R4_MEMBERS_MAP, format!("typed graph read failed: {e}"));
            return report;
        }
    };

    report.member_count = graph.members_view().count();

    validate_catalog_signature(root, &graph, &mut report);

    for view in graph.members_view() {
        validate_member_view(&view, &file_cid, &mut report);
    }

    report
}

fn validate_catalog_signature(
    root: &BTreeMap<String, CborValue>,
    graph: &ProofGraph,
    report: &mut ProofFileConformanceReport,
) {
    let Some(signer) = root.get("signer").and_then(CborValue::as_tstr) else {
        report.push_error(
            PFCP_R9_CATALOG_SIGNATURE,
            "catalog signer is missing or not text",
        );
        return;
    };
    if root
        .get("declaredAt")
        .and_then(CborValue::as_tstr)
        .is_none()
    {
        report.push_error(
            PFCP_R9_CATALOG_SIGNATURE,
            "catalog declaredAt is missing or not text",
        );
        return;
    }
    let Some(signature) = root.get("signature").and_then(CborValue::as_bstr) else {
        report.push_error(
            PFCP_R9_CATALOG_SIGNATURE,
            "catalog signature is missing or not a byte string",
        );
        return;
    };
    let signer_key = if signer.starts_with("ed25519:") {
        signer.to_string()
    } else if signer.starts_with(HASH_TAG_PREFIX) {
        match authority_key_for_catalog_signer(signer, graph) {
            Ok(key) => key,
            Err(error) => {
                report.push_error(PFCP_R9_CATALOG_SIGNATURE, error);
                return;
            }
        }
    } else {
        report.push_error(
            PFCP_R9_CATALOG_SIGNATURE,
            format!("catalog signer `{signer}` is neither an inline ed25519 key nor a CID authority memento"),
        );
        return;
    };

    let mut unsigned = root.clone();
    unsigned.remove("signature");
    let unsigned_bytes = encode_cbor_value(&CborValue::Map(unsigned));
    if !ed25519_verify_bytes(&signer_key, signature, &unsigned_bytes) {
        report.push_error(
            PFCP_R9_CATALOG_SIGNATURE,
            "catalog signature does not verify over the unsigned catalog body",
        );
    }
}

fn authority_key_for_catalog_signer(signer: &str, graph: &ProofGraph) -> Result<String, String> {
    let view = graph
        .members_view()
        .find(|v| v.cid().as_str() == signer)
        .ok_or_else(|| format!("catalog signer authority `{signer}` is not in members"))?;
    if view.kind().as_deref() != Some("authority") {
        return Err(format!(
            "catalog signer `{signer}` does not resolve to an authority memento"
        ));
    }
    let key = view
        .field("key")
        .ok_or_else(|| format!("catalog signer authority `{signer}` is missing header.key"))?;
    if !key.starts_with("ed25519:") {
        return Err(format!(
            "catalog signer authority `{signer}` header.key is not an inline ed25519 key"
        ));
    }
    Ok(key)
}

fn empty_report(path: &Path, file_cid: &str) -> ProofFileConformanceReport {
    ProofFileConformanceReport {
        kind: "ProofFileConformanceReport".into(),
        schema_version: "0.1".into(),
        proof_path: path.display().to_string(),
        file_cid: file_cid.to_string(),
        filename_cid: filename_cid(path),
        member_count: 0,
        metadata_count: 0,
        warnings: Vec::new(),
        errors: Vec::new(),
    }
}

fn filename_cid(path: &Path) -> Option<String> {
    let filename = path.file_name()?.to_str()?;
    let stem = filename.strip_suffix(".proof").unwrap_or(filename);
    if stem.starts_with(HASH_TAG_PREFIX) {
        Some(stem.to_string())
    } else if stem.len() == 128 && stem.bytes().all(|b| b.is_ascii_hexdigit()) {
        Some(format!("{HASH_TAG_PREFIX}{stem}"))
    } else {
        None
    }
}

fn check_filename_cid(path: &Path, file_cid: &str, report: &mut ProofFileConformanceReport) {
    let filename = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or_default();
    let stem = filename.strip_suffix(".proof").unwrap_or(filename);
    let candidate = stem.strip_prefix(HASH_TAG_PREFIX).unwrap_or(stem);
    if candidate.len() != 128 || !candidate.bytes().all(|b| b.is_ascii_hexdigit()) {
        report.push_error(
            PFCP_R1_FILENAME_CID,
            format!("filename `{filename}` does not carry a blake3-512 CID"),
        );
        return;
    }
    let file_hex = file_cid.strip_prefix(HASH_TAG_PREFIX).unwrap_or(file_cid);
    if candidate != file_hex {
        report.push_error(
            PFCP_R1_FILENAME_CID,
            format!("filename CID {candidate} != content hash {file_hex}"),
        );
    }
}

fn validate_member_view(
    view: &MemberView<'_>,
    enclosing_file_cid: &str,
    report: &mut ProofFileConformanceReport,
) {
    let cid = view.cid().as_str().to_string();

    if !cid.starts_with(HASH_TAG_PREFIX) {
        report.push_error(
            PFCP_R5_MEMBER_CID,
            format!("member key `{cid}` does not use blake3-512"),
        );
        return;
    }

    let env: Json = match serde_json::from_slice(view.bytes()) {
        Ok(env) => env,
        Err(e) => {
            report.push_error(
                PFCP_R5_MEMBER_CID,
                format!("member {cid}: JSON parse failed: {e}"),
            );
            return;
        }
    };

    let derived = sugar_proof_envelope::recompute_member_cid(&env);
    if derived != cid {
        report.push_error(
            PFCP_R5_MEMBER_CID,
            format!("member key {cid} derives to {derived}"),
        );
    }

    if json_contains_string(&env, enclosing_file_cid) {
        report.push_error(
            PFCP_R8_NO_ENCLOSING_FILE_CID_CLAIM,
            format!("member {cid} contains the enclosing file CID"),
        );
    }

    if let Err(e) = verify_member_signature(&env) {
        report.push_error(PFCP_R6_MEMBER_SIGNATURE, format!("member {cid}: {e}"));
    }
}

pub(crate) fn verify_member_signature(env: &Json) -> Result<(), String> {
    sugar_proof_envelope::verify_member_signature(env)
}

fn json_contains_string(value: &Json, needle: &str) -> bool {
    match value {
        Json::String(s) => s == needle,
        Json::Array(items) => items.iter().any(|item| json_contains_string(item, needle)),
        Json::Object(map) => map.values().any(|item| json_contains_string(item, needle)),
        _ => false,
    }
}

fn map_contains_string(map: &BTreeMap<String, CborValue>, needle: &str) -> bool {
    map.values()
        .any(|value| cbor_contains_string(value, needle))
}

fn cbor_contains_string(value: &CborValue, needle: &str) -> bool {
    match value {
        CborValue::Tstr(s) => s == needle,
        CborValue::Array(items) => items.iter().any(|item| cbor_contains_string(item, needle)),
        CborValue::Map(map) => map_contains_string(map, needle),
        _ => false,
    }
}

fn encode_cbor_value(value: &CborValue) -> Vec<u8> {
    let mut out = Vec::new();
    encode_cbor_into(value, &mut out);
    out
}

fn encode_cbor_into(value: &CborValue, out: &mut Vec<u8>) {
    match value {
        CborValue::Uint(n) => encode_uint(0, *n, out),
        CborValue::Bstr(bytes) => {
            encode_uint(2, bytes.len() as u64, out);
            out.extend_from_slice(bytes);
        }
        CborValue::Tstr(s) => {
            encode_uint(3, s.len() as u64, out);
            out.extend_from_slice(s.as_bytes());
        }
        CborValue::Array(items) => {
            encode_uint(4, items.len() as u64, out);
            for item in items {
                encode_cbor_into(item, out);
            }
        }
        CborValue::Map(map) => {
            encode_uint(5, map.len() as u64, out);
            let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = map
                .iter()
                .map(|(key, value)| {
                    let key_value = CborValue::Tstr(key.clone());
                    (encode_cbor_value(&key_value), encode_cbor_value(value))
                })
                .collect();
            pairs.sort_by(|a, b| a.0.cmp(&b.0));
            for (key, value) in pairs {
                out.extend_from_slice(&key);
                out.extend_from_slice(&value);
            }
        }
    }
}

fn encode_uint(major: u8, n: u64, out: &mut Vec<u8>) {
    let head = major << 5;
    match n {
        0..=23 => out.push(head | n as u8),
        24..=0xff => {
            out.push(head | 24);
            out.push(n as u8);
        }
        0x100..=0xffff => {
            out.push(head | 25);
            out.extend_from_slice(&(n as u16).to_be_bytes());
        }
        0x1_0000..=0xffff_ffff => {
            out.push(head | 26);
            out.extend_from_slice(&(n as u32).to_be_bytes());
        }
        _ => {
            out.push(head | 27);
            out.extend_from_slice(&n.to_be_bytes());
        }
    }
}
