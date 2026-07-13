// SPDX-License-Identifier: MIT OR Apache-2.0
//
// SEAM 4 of the compiler-shape plan (`~/.claude/plans/sugar-compiler-liftshift.md`):
// `Kit::testimony` and `Kit::source`, the two resolve verbs. Both are
// LIFT-AND-SHIFT of an existing RPC mechanic -- no wire protocol change.
//
// `resolve_testimony` is `dependency_proofs_via_rpc` /
// `dependency_proofs_for_command` / `decode_dependency_proof_entry`
// (`sugar-cli/src/kit_dispatch.rs:262-504`), moved here as ONE function so
// `Kit::testimony` (a single already-rendezvous'd kit) and
// `kit_dispatch::dependency_proofs_via_rpc` (the CLI's multi-plugin
// aggregator, which has no single `Kit` to hold -- it fans out across
// every configured plugin command) call the SAME typed core rather than
// each re-implementing the RPC + decode. This is the one path, re-homed,
// not a second one: kit_dispatch keeps its per-plugin loop (constructing a
// `LiftManifest`/rendezvous per plugin would add a live handshake round-trip
// the aggregator never performed and no stub kit in the corpus answers --
// out of scope for this seam, flagged rather than silently changed) but the
// blob-decoding body underneath is this function, called once per command.
//
// `resolve_source` is new client-side plumbing for a wire method
// (`sugar.plugin.resolve_source_memento`) that already exists SERVER-side
// (`sugar-walk/src/bin/walk_rpc.rs:284`) but had no Rust RPC client before
// this seam -- the `cmd_lift.rs:3652` region the plan cites turned out, on
// inspection, to be pure report-rendering over an already-resolved
// `sourceOracle` JSON field (produced by a kit's OWN walk), not a client
// call site. So there is no existing client mechanic to lift; this wires
// the SAME transport pattern `resolve_testimony` uses against the SAME
// wire shape `resolve_source_memento_rpc` already answers -- zero protocol
// invention.

use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Command, Stdio};

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde_json::{json, Value};

use sugar_proof_envelope::Speaker;
use sugar_verifier::load_all_proofs::ProofBytes;
use sugar_walk::source_oracle::{SourceMemento, SrcSpan};

/// Failure to even hold a conversation with the resolver kit -- distinct
/// from the kit answering with a substantive protocol error (`RpcError`)
/// or an honest "I don't do that" (folded into `TestimonyOutcome::Unavailable`
/// / `SourceRefusal::Unavailable`, never here).
#[derive(Debug, thiserror::Error)]
pub enum TestimonyError {
    #[error("dependency proof resolver `{plugin}` has an empty command")]
    EmptyCommand { plugin: String },
    #[error("dependency proof resolver `{plugin}` stdin unavailable")]
    StdinUnavailable { plugin: String },
    #[error("dependency proof resolver `{plugin}` stdout unavailable")]
    StdoutUnavailable { plugin: String },
    #[error("write resolve_dependency_proofs request to `{plugin}`: {source}")]
    Write {
        plugin: String,
        #[source]
        source: std::io::Error,
    },
    #[error("read resolve_dependency_proofs response from `{plugin}`: {source}")]
    Read {
        plugin: String,
        #[source]
        source: std::io::Error,
    },
    #[error(
        "resolve_dependency_proofs response from `{plugin}` not valid JSON: {source}; raw={raw}"
    )]
    InvalidJson {
        plugin: String,
        #[source]
        source: serde_json::Error,
        raw: String,
    },
    #[error("dependency proof resolver `{plugin}` error: {error}")]
    RpcError { plugin: String, error: Value },
    #[error("dependency proof resolver `{plugin}` kit returned dependency proof without a content address for label `{label}`")]
    MissingContentAddress { plugin: String, label: String },
}

/// The testimony verb's answer. A kit that simply does not implement
/// `resolve_dependency_proofs` (or never spawns, or closes without a
/// response) is a LINK-class absence -- there is no vendor testimony to
/// fold in, not a protocol failure -- so it is a variant of the success
/// type, never flattened into `TestimonyError` or a bare `String`.
#[derive(Debug, Clone)]
pub enum TestimonyOutcome {
    Proofs(Vec<ProofBytes>),
    Unavailable { plugin: String, reason: String },
}

/// Any proof entry a resolver returned but could not be decoded into a
/// well-formed `ProofBytes` (invalid `bytes_base64`, non-object entry, bad
/// CID shape) is dropped with a diagnostic rather than failing the whole
/// resolve -- the same tolerance `decode_dependency_proof_entry` had.
/// Callers that want those diagnostics get them back alongside the proofs.
#[derive(Debug)]
pub struct TestimonyResolution {
    pub outcome: TestimonyOutcome,
    pub diagnostics: Vec<String>,
}

/// Resolve one command's vendor testimony: spawn it, ask
/// `sugar.plugin.resolve_dependency_proofs`, decode every returned proof
/// entry into a content-addressed, speaker-stamped `ProofBytes`.
///
/// Moved from `kit_dispatch::dependency_proofs_for_command` +
/// `decode_dependency_proof_entry` verbatim (the `--rpc` flag injection,
/// the `sugar.plugin.shutdown` courtesy call, the `proof_paths` legacy-field
/// diagnostic, the CID/label sort+dedup) -- only the diagnostic sink
/// changed from a process-global `KIT_DISPATCH_DIAGNOSTICS` mutex to a
/// returned `Vec<String>`, since this function no longer lives next to that
/// static.
pub fn resolve_testimony(
    plugin_name: &str,
    command: &[String],
    working_dir: Option<&Path>,
    workspace_root: &Path,
) -> Result<TestimonyResolution, TestimonyError> {
    let mut diagnostics = Vec::new();
    if command.is_empty() {
        return Err(TestimonyError::EmptyCommand {
            plugin: plugin_name.to_string(),
        });
    }
    let mut cmd = Command::new(&command[0]);
    if command.len() > 1 {
        cmd.args(&command[1..]);
    }
    if !command.iter().any(|a| a == "--rpc") {
        cmd.arg("--rpc");
    }
    if let Some(wd) = working_dir {
        cmd.current_dir(wd);
    }
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::inherit());

    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(error) => {
            return Ok(TestimonyResolution {
                outcome: TestimonyOutcome::Unavailable {
                    plugin: plugin_name.to_string(),
                    reason: format!(
                        "dependency proof resolver unavailable for {command:?}: {error}"
                    ),
                },
                diagnostics,
            });
        }
    };
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| TestimonyError::StdinUnavailable {
            plugin: plugin_name.to_string(),
        })?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| TestimonyError::StdoutUnavailable {
            plugin: plugin_name.to_string(),
        })?;
    let mut reader = BufReader::new(stdout);

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.resolve_dependency_proofs",
        "params": {
            "project_root": workspace_root.display().to_string(),
        },
    });
    writeln!(stdin, "{req}").map_err(|source| TestimonyError::Write {
        plugin: plugin_name.to_string(),
        source,
    })?;

    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|source| TestimonyError::Read {
            plugin: plugin_name.to_string(),
            source,
        })?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sugar.plugin.shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    if line.trim().is_empty() {
        return Ok(TestimonyResolution {
            outcome: TestimonyOutcome::Unavailable {
                plugin: plugin_name.to_string(),
                reason: format!("dependency proof resolver {command:?} closed without a response"),
            },
            diagnostics,
        });
    }

    let response: Value =
        serde_json::from_str(line.trim()).map_err(|source| TestimonyError::InvalidJson {
            plugin: plugin_name.to_string(),
            source,
            raw: line.trim().to_string(),
        })?;
    if let Some(error) = response.get("error") {
        if rpc_error_is_method_not_supported(error, "sugar.plugin.resolve_dependency_proofs") {
            return Ok(TestimonyResolution {
                outcome: TestimonyOutcome::Unavailable {
                    plugin: plugin_name.to_string(),
                    reason: format!(
                        "dependency proof resolver {command:?} does not implement sugar.plugin.resolve_dependency_proofs"
                    ),
                },
                diagnostics,
            });
        }
        return Err(TestimonyError::RpcError {
            plugin: plugin_name.to_string(),
            error: error.clone(),
        });
    }

    let result = response.get("result").cloned().unwrap_or(Value::Null);
    let proofs = result
        .get("proofs")
        .or_else(|| result.get("proofs_base64"))
        .or_else(|| result.get("proofBytes"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut out = Vec::new();
    for proof in proofs {
        match decode_dependency_proof_entry(plugin_name, command, &proof, &mut diagnostics)? {
            Some(decoded) => out.push(decoded),
            None => continue,
        }
    }

    let legacy_paths = result
        .get("proof_paths")
        .or_else(|| result.get("proofPaths"))
        .or_else(|| result.get("paths"))
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    if legacy_paths > 0 {
        diagnostics.push(format!(
            "dependency proof resolver {command:?} returned legacy proof_paths; ignoring paths because package proof bytes must cross RPC"
        ));
    }

    out.sort_by(|a: &ProofBytes, b: &ProofBytes| {
        (a.expected_cid.as_str(), a.label.as_str())
            .cmp(&(b.expected_cid.as_str(), b.label.as_str()))
    });
    out.dedup_by(|a, b| a.expected_cid == b.expected_cid && a.bytes == b.bytes);

    Ok(TestimonyResolution {
        outcome: TestimonyOutcome::Proofs(out),
        diagnostics,
    })
}

fn rpc_error_is_method_not_supported(error: &Value, method: &str) -> bool {
    let code = error.get("code").and_then(Value::as_i64);
    if code == Some(-32601) {
        return true;
    }
    let Some(message) = error.get("message").and_then(Value::as_str) else {
        return false;
    };
    let message = message.to_ascii_lowercase();
    (code == Some(-32602) || code == Some(-32603))
        && message.contains("unknown method")
        && message.contains(method)
}

fn decode_dependency_proof_entry(
    plugin_name: &str,
    command: &[String],
    proof: &Value,
    diagnostics: &mut Vec<String>,
) -> Result<Option<ProofBytes>, TestimonyError> {
    let Some(object) = proof.as_object() else {
        diagnostics.push(format!(
            "dependency proof resolver {command:?} returned a non-object proof entry: {proof}"
        ));
        return Ok(None);
    };
    let label_field = object
        .get("source")
        .or_else(|| object.get("label"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let Some(expected_cid) = object
        .get("cid")
        .or_else(|| object.get("proof_cid"))
        .or_else(|| object.get("proofCid"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        let label = label_field
            .clone()
            .unwrap_or_else(|| "<unlabeled dependency proof>".to_string());
        return Err(TestimonyError::MissingContentAddress {
            plugin: plugin_name.to_string(),
            label,
        });
    };
    let Some(bytes_base64) = object
        .get("bytes_base64")
        .or_else(|| object.get("bytesBase64"))
        .and_then(Value::as_str)
    else {
        diagnostics.push(format!(
            "dependency proof resolver {command:?} returned a proof entry without bytes_base64: {proof}"
        ));
        return Ok(None);
    };
    let bytes = match BASE64.decode(bytes_base64) {
        Ok(bytes) => bytes,
        Err(error) => {
            diagnostics.push(format!(
                "dependency proof resolver {command:?} returned invalid bytes_base64: {error}"
            ));
            return Ok(None);
        }
    };
    let label = label_field.unwrap_or_else(|| expected_cid.clone());

    // #3813: a kit's package-manager dependency catalog IS vendor testimony.
    // Stamp the Vendor role INTO the ProofBytes here, at the one point that
    // knows where these bytes came from.
    let speaker = Speaker::vendor(label.clone());
    match ProofBytes::try_from_parts(label, expected_cid, bytes, speaker) {
        Ok(proof) => Ok(Some(proof)),
        Err(error) => {
            diagnostics.push(format!(
                "dependency proof resolver {command:?} returned invalid expected_cid: {error}"
            ));
            Ok(None)
        }
    }
}

/// One line of resolved source, 1-indexed to match `SrcSpan`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceLine {
    pub line: usize,
    pub source: String,
}

/// What `resolve_source_memento_rpc` (`walk_rpc.rs:284`) answers: the
/// memento's own file/span echoed back, the resolved term text, and the
/// surrounding lines. Deliberately NOT `sugar_walk::source_oracle::ResolvedSource`
/// -- that type's `fragment: SourceFragment` carries an `ast_template` the
/// wire response never sends (the oracle's in-process answer is richer than
/// its RPC answer); a Kit-side caller only ever gets what crossed the wire.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedSource {
    pub file: String,
    pub span: SrcSpan,
    pub source: String,
    pub lines: Vec<SourceLine>,
}

/// Exact-or-refuse, typed: a `SourceOracleRefusal` (the memento's pinned
/// source_cid no longer matches what's on disk -- CID drift, an honest
/// index miss) is a LINK-class failure, never conflated with a transport
/// problem or a solver verdict.
#[derive(Debug, thiserror::Error)]
pub enum SourceRefusal {
    #[error("source oracle `{plugin}` stdin unavailable")]
    StdinUnavailable { plugin: String },
    #[error("source oracle `{plugin}` stdout unavailable")]
    StdoutUnavailable { plugin: String },
    #[error("write resolve_source_memento request to `{plugin}`: {source}")]
    Write {
        plugin: String,
        #[source]
        source: std::io::Error,
    },
    #[error("read resolve_source_memento response from `{plugin}`: {source}")]
    Read {
        plugin: String,
        #[source]
        source: std::io::Error,
    },
    #[error("resolve_source_memento response from `{plugin}` not valid JSON: {source}; raw={raw}")]
    InvalidJson {
        plugin: String,
        #[source]
        source: serde_json::Error,
        raw: String,
    },
    /// The kit answered but refused the lookup: CID drift, moved/renamed
    /// function, or an unpinned memento. This is `SourceOracleRefusal`'s
    /// `.reason` crossing the wire, exact-or-refuse preserved.
    #[error("source oracle `{plugin}` refused: {reason}")]
    Refused { plugin: String, reason: String },
    /// A LINK-class absence distinct from `Refused`: the kit doesn't
    /// implement `resolve_source_memento` at all, never spawned, or closed
    /// without a response. Named separately so a caller can tell "no such
    /// verb" apart from "looked and the source drifted."
    #[error("source oracle `{plugin}` unavailable: {reason}")]
    Unavailable { plugin: String, reason: String },
    #[error("resolve_source_memento response from `{plugin}` malformed: {reason}")]
    MalformedResponse { plugin: String, reason: String },
}

/// Resolve one `SourceMemento` against a live kit process: spawn `command`,
/// ask `sugar.plugin.resolve_source_memento` (the wire method
/// `walk_rpc.rs:250` already answers), and decode the response into a
/// strong `ResolvedSource`. Exact-or-refuse: a CID mismatch on the kit side
/// crosses the wire as an RPC error and becomes `SourceRefusal::Refused`,
/// never a silently-empty success.
pub fn resolve_source(
    plugin_name: &str,
    command: &[String],
    working_dir: Option<&Path>,
    workspace_root: &Path,
    memento: &SourceMemento,
) -> Result<ResolvedSource, SourceRefusal> {
    let mut cmd = Command::new(&command[0]);
    if command.len() > 1 {
        cmd.args(&command[1..]);
    }
    if !command.iter().any(|a| a == "--rpc") {
        cmd.arg("--rpc");
    }
    if let Some(wd) = working_dir {
        cmd.current_dir(wd);
    }
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::inherit());

    let mut child = cmd.spawn().map_err(|error| SourceRefusal::Unavailable {
        plugin: plugin_name.to_string(),
        reason: format!("source oracle unavailable for {command:?}: {error}"),
    })?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| SourceRefusal::StdinUnavailable {
            plugin: plugin_name.to_string(),
        })?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| SourceRefusal::StdoutUnavailable {
            plugin: plugin_name.to_string(),
        })?;
    let mut reader = BufReader::new(stdout);

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.resolve_source_memento",
        "params": {
            "workspace_root": workspace_root.display().to_string(),
            "sourceMemento": memento.to_json(),
        },
    });
    writeln!(stdin, "{req}").map_err(|source| SourceRefusal::Write {
        plugin: plugin_name.to_string(),
        source,
    })?;

    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|source| SourceRefusal::Read {
            plugin: plugin_name.to_string(),
            source,
        })?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sugar.plugin.shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    if line.trim().is_empty() {
        return Err(SourceRefusal::Unavailable {
            plugin: plugin_name.to_string(),
            reason: format!("source oracle {command:?} closed without a response"),
        });
    }

    let response: Value =
        serde_json::from_str(line.trim()).map_err(|source| SourceRefusal::InvalidJson {
            plugin: plugin_name.to_string(),
            source,
            raw: line.trim().to_string(),
        })?;
    if let Some(error) = response.get("error") {
        if rpc_error_is_method_not_supported(error, "sugar.plugin.resolve_source_memento") {
            return Err(SourceRefusal::Unavailable {
                plugin: plugin_name.to_string(),
                reason: format!(
                    "source oracle {command:?} does not implement sugar.plugin.resolve_source_memento"
                ),
            });
        }
        let reason = error
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("resolve_source_memento refused")
            .to_string();
        return Err(SourceRefusal::Refused {
            plugin: plugin_name.to_string(),
            reason,
        });
    }

    let result = response.get("result").cloned().unwrap_or(Value::Null);
    decode_resolved_source(plugin_name, &result)
}

fn decode_resolved_source(
    plugin_name: &str,
    result: &Value,
) -> Result<ResolvedSource, SourceRefusal> {
    let malformed = |reason: &str| SourceRefusal::MalformedResponse {
        plugin: plugin_name.to_string(),
        reason: reason.to_string(),
    };
    // Two live server dialects answer this method (macroscope on #3856):
    // walk_rpc's flat `{file, span, ...}` and rust_test_assertions_rpc's
    // status-keyed `{status: resolved|drifted|absent, ...}`. Decode BOTH,
    // typed; a drifted/absent status maps to the same honest refusals the
    // flat dialect signals via RPC error. Wire unification is follow-up.
    if let Some(status) = result.get("status").and_then(Value::as_str) {
        match status {
            "resolved" => { /* fall through to field decode below */ }
            "drifted" => {
                return Err(SourceRefusal::Refused {
                    plugin: plugin_name.to_string(),
                    reason: result
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("source drifted from sworn memento")
                        .to_string(),
                });
            }
            "absent" => {
                return Err(SourceRefusal::Refused {
                    plugin: plugin_name.to_string(),
                    reason: result
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("source absent for memento")
                        .to_string(),
                });
            }
            other => {
                return Err(malformed(&format!("unknown status `{other}`")));
            }
        }
        // status:"resolved" in the status dialect carries the span inside
        // `memento` rather than a top-level `span`.
        if result.get("span").is_none() {
            if let Some(memento) = result.get("memento") {
                let file = memento
                    .get("file")
                    .and_then(Value::as_str)
                    .ok_or_else(|| malformed("status dialect: missing `memento.file`"))?
                    .to_string();
                let span_value = memento
                    .get("span")
                    .ok_or_else(|| malformed("status dialect: missing `memento.span`"))?;
                return decode_span_and_source(plugin_name, result, file, span_value);
            }
            return Err(malformed(
                "status dialect: resolved without span or memento",
            ));
        }
    }
    let file = result
        .get("file")
        .and_then(Value::as_str)
        .ok_or_else(|| malformed("missing `file`"))?
        .to_string();
    let span_value = result
        .get("span")
        .ok_or_else(|| malformed("missing `span`"))?;
    decode_span_and_source(plugin_name, result, file, span_value)
}

fn decode_span_and_source(
    plugin_name: &str,
    result: &Value,
    file: String,
    span_value: &Value,
) -> Result<ResolvedSource, SourceRefusal> {
    let malformed = |reason: &str| SourceRefusal::MalformedResponse {
        plugin: plugin_name.to_string(),
        reason: reason.to_string(),
    };
    let span = SrcSpan {
        start_line: span_value
            .get("start_line")
            .and_then(Value::as_u64)
            .ok_or_else(|| malformed("missing `span.start_line`"))? as usize,
        start_col: span_value
            .get("start_col")
            .and_then(Value::as_u64)
            .ok_or_else(|| malformed("missing `span.start_col`"))? as usize,
        end_line: span_value
            .get("end_line")
            .and_then(Value::as_u64)
            .ok_or_else(|| malformed("missing `span.end_line`"))? as usize,
        end_col: span_value
            .get("end_col")
            .and_then(Value::as_u64)
            .ok_or_else(|| malformed("missing `span.end_col`"))? as usize,
    };
    let source = result
        .get("source")
        .or_else(|| result.get("bodyText"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let lines = result
        .get("sourceLines")
        .or_else(|| result.get("source_lines"))
        .and_then(Value::as_array)
        .map(|lines| {
            lines
                .iter()
                .filter_map(|line| {
                    let number = line.get("line").and_then(Value::as_u64)? as usize;
                    let source = line.get("source").and_then(Value::as_str)?.to_string();
                    Some(SourceLine {
                        line: number,
                        source,
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    Ok(ResolvedSource {
        file,
        span,
        source,
        lines,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    // Moved from `sugar-cli/src/kit_dispatch.rs`'s
    // `optional_rpc_method_refusal_accepts_legacy_unknown_method_error`
    // alongside the helper it exercises (SEAM 4).
    #[test]
    fn optional_rpc_method_refusal_accepts_legacy_unknown_method_error() {
        assert!(rpc_error_is_method_not_supported(
            &json!({"code": -32601, "message": "method not found"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
        assert!(rpc_error_is_method_not_supported(
            &json!({"code": -32602, "message": "unknown method: sugar.plugin.resolve_dependency_proofs"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
        assert!(rpc_error_is_method_not_supported(
            &json!({"code": -32603, "message": "unknown method: sugar.plugin.resolve_dependency_proofs"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
        assert!(!rpc_error_is_method_not_supported(
            &json!({"code": -32602, "message": "invalid params"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
    }
}

#[cfg(test)]
mod dialect_tests {
    use super::*;
    use serde_json::json;

    /// The status dialect (rust_test_assertions_rpc): resolved carries the
    /// span inside `memento`, drifted/absent map to typed refusals.
    #[test]
    fn status_dialect_resolved_decodes_via_memento_span() {
        let result = json!({
            "status": "resolved",
            "source": "assert np.add(2, 3) == 5",
            "bodyText": "assert np.add(2, 3) == 5",
            "memento": {
                "file": "tests/test_x.py",
                "span": {"start_line": 3, "start_col": 4, "end_line": 3, "end_col": 30},
            }
        });
        let resolved = decode_resolved_source("rust-test-assertions", &result)
            .expect("status:resolved must decode");
        assert_eq!(resolved.file, "tests/test_x.py");
        assert_eq!(resolved.span.start_line, 3);
        assert_eq!(resolved.source, "assert np.add(2, 3) == 5");
    }

    #[test]
    fn status_dialect_drifted_is_a_typed_refusal() {
        let result = json!({"status": "drifted", "reason": "source CID mismatch"});
        match decode_resolved_source("rust-test-assertions", &result) {
            Err(SourceRefusal::Refused { reason, .. }) => {
                assert!(reason.contains("mismatch"));
            }
            other => panic!("drifted must refuse, got {other:?}"),
        }
    }

    #[test]
    fn flat_dialect_still_decodes() {
        let result = json!({
            "file": "src/lib.rs",
            "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 10},
            "source": "fn x() {}",
        });
        let resolved = decode_resolved_source("walk", &result).expect("flat dialect must decode");
        assert_eq!(resolved.file, "src/lib.rs");
    }

    #[test]
    fn empty_command_is_a_typed_error_not_a_panic() {
        let err = resolve_testimony("empty", &[], None, Path::new("."))
            .expect_err("empty command must refuse");
        assert!(matches!(err, TestimonyError::EmptyCommand { .. }));
    }
}
