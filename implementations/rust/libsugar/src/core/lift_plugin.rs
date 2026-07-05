// SPDX-License-Identifier: MIT OR Apache-2.0

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::{json, Value};
use sugar_ir_types::{IrFormula, IrTerm, Sort};
use thiserror::Error;
use tracing::info;

use super::bind::strip_realize_sidecar_from_lift_term;
use super::primitives::address;
use super::traits::{Kit, KitError};
use super::types::{
    memento_from_parts, Cid, Contract, Dialect, DomainClaim, DomainKind, Input, Term, Verdict,
};

/// Serialized-byte bound for a lift-plugin response term. A response that serializes past
/// this is treated as unbounded and REFUSED before it is deep-cloned / content-addressed
/// (finite-or-refuse). Generous: a normal full-corpus coretests response serializes to
/// well under 100 MB; this only catches a runaway no kit-level bound caught first.
const RESPONSE_TERM_SERIALIZED_BYTE_BOUND: usize = 256 * 1024 * 1024;

/// `true` iff `value` serializes to more than `cap` bytes. Streams through a counting
/// writer that errors past `cap`, so it is O(cap) time, O(1) memory, and never
/// materializes the huge serialization (the OOM we are guarding against). Response depth
/// is bounded by serde_json's parse recursion limit, so the recursive serializer cannot
/// stack-overflow here.
fn json_serialized_exceeds(value: &Value, cap: usize) -> bool {
    struct CapWriter {
        written: usize,
        cap: usize,
    }
    impl Write for CapWriter {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.written = self.written.saturating_add(buf.len());
            if self.written > self.cap {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::Other,
                    "cap exceeded",
                ));
            }
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut writer = CapWriter { written: 0, cap };
    serde_json::to_writer(&mut writer, value).is_err()
}

/// Core Kit adapter for a lift-plugin-protocol subprocess.
///
/// This is the primitive-facing transport: `Kit::transform` sends an
/// `Input::Spec` lift request to a JSON-RPC lifter and returns a claim whose
/// artifact vector points at the lifter response. CLI code may still render
/// the old response shape through the session escape hatch while downstream
/// code moves to addresses and claims.
#[derive(Debug, Clone)]
pub struct LiftPluginKit {
    surface: String,
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    lift_method: String,
}

/// Source-shaped Lift Kit adapter over the existing lift-plugin transport.
#[derive(Debug, Clone)]
pub struct LiftKit {
    dialect: Dialect,
    transport: LiftPluginKit,
}

impl LiftPluginKit {
    /// Build a lift-plugin Kit from an already-resolved command.
    pub fn new(
        surface: impl Into<String>,
        command: Vec<String>,
        working_dir: Option<PathBuf>,
    ) -> Self {
        Self {
            surface: surface.into(),
            command,
            working_dir,
            lift_method: "lift".to_string(),
        }
    }

    /// Override the JSON-RPC method used for the lift request. The default
    /// method remains `lift`; multi-surface kits can expose a second route
    /// such as `sugar.plugin.lift_implications` while keeping the same
    /// transport.
    pub fn with_method(mut self, method: impl Into<String>) -> Self {
        let method = method.into();
        self.lift_method = if method.is_empty() {
            "lift".to_string()
        } else {
            method
        };
        self
    }

    /// Run the plugin transport and retain protocol metadata.
    pub fn parse_session(&self, input: &Input) -> Result<LiftPluginKitSession, LiftPluginKitError> {
        let request = lift_request_from_input(input)?;
        trace_lift_transport_checkpoint("parse_session.before_dispatch", &Value::Null, 0);
        let (initialize_response, response) = self.dispatch(request)?;
        trace_lift_transport_checkpoint("parse_session.after_dispatch", &response, 0);
        let before = current_rss_kib();
        let response_term = response_term(response.clone());
        trace_lift_transport_checkpoint_with_delta(
            "parse_session.after_response_clone_to_term",
            &response,
            0,
            rss_delta_kib(before, current_rss_kib()),
        );
        trace_lift_transport_checkpoint(
            "parse_session.before_claim_from_response_term",
            &response,
            0,
        );
        let claim = self.claim_from_response_term(input, response_term)?;
        trace_lift_transport_checkpoint(
            "parse_session.after_claim_from_response_term",
            &response,
            0,
        );
        Ok(LiftPluginKitSession {
            initialize_response,
            legacy_response: response,
            claim,
        })
    }

    /// Promote a lift-plugin response term into the first-class primitive claim.
    pub fn claim_from_response_term(
        &self,
        input: &Input,
        response_term: Term,
    ) -> Result<DomainClaim, LiftPluginKitError> {
        // FINITE-OR-REFUSE backstop: a lift kit's response term must be bounded. An
        // unbounded one (a self-referential static, a signed-zero float refinement, any
        // runaway expansion) would be deep-cloned + content-addressed below and OOM. We do
        // NOT deep-clone an unbounded term to discover it is unbounded: a streaming,
        // early-exit byte count (O(1) memory; response depth is bounded by serde's parse
        // recursion limit, so no stack risk) decides it, and on exceed we swap the response
        // for a small refusal marker (the lift is refused, never truncated). The per-file
        // emit bound in the rust-test-assertions kit catches this earlier and per-file; this
        // is the kit-agnostic last-resort net so no kit can OOM the transport.
        let response_term = match response_term {
            Term::Const { value, sort }
                if json_serialized_exceeds(&value, RESPONSE_TERM_SERIALIZED_BYTE_BOUND) =>
            {
                Term::Const {
                    value: serde_json::json!({
                        "sugar-refused": "response-term-exceeds-byte-bound",
                        "reason": format!(
                            "lift response term exceeds serialized byte bound ({RESPONSE_TERM_SERIALIZED_BYTE_BOUND}) -- unbounded, refused before clone/address (finite-or-refuse)"
                        ),
                    }),
                    sort,
                }
            }
            other => other,
        };
        let response = match &response_term {
            Term::Const { value, .. } => value,
            _ => {
                return Err(LiftPluginKitError::Failed(
                    "lift kit returned a non-response term".to_string(),
                ))
            }
        };
        // Substrate identity rule: lift's `to` CID must be stable against
        // realize-sidecar noise (attr_pre, attr_post, concept_annotation,
        // operand_bindings, source_function_name, proc_macro_invocations).
        // Adding a comment that shifts `fn_line` is irrelevant variation, so
        // the canonical content address strips the sidecar before hashing.
        // The `payload` field still carries the raw response (with sidecar)
        // for downstream consumers that need realize-time metadata.
        trace_lift_transport_checkpoint("claim_from_response_term.start", response, 0);
        let before = current_rss_kib();
        let canonical_term = strip_realize_sidecar_from_lift_term(response_term.clone());
        trace_lift_transport_checkpoint_with_delta(
            "claim_from_response_term.after_strip_sidecar_clone",
            response,
            0,
            rss_delta_kib(before, current_rss_kib()),
        );
        let before = current_rss_kib();
        let response_cid = address(&canonical_term);
        trace_lift_transport_checkpoint_with_delta(
            "claim_from_response_term.after_address_canonical_term",
            response,
            0,
            rss_delta_kib(before, current_rss_kib()),
        );
        let before = current_rss_kib();
        let contract = lift_response_contract(&self.surface, response, &response_cid);
        trace_lift_transport_checkpoint_with_delta(
            "claim_from_response_term.after_lift_response_contract",
            response,
            0,
            rss_delta_kib(before, current_rss_kib()),
        );

        Ok(DomainClaim {
            domain: DomainKind::Other("lift-plugin".to_string()),
            contract,
            artifacts: vec![response_cid.clone()],
            from: vec![address(input)],
            premises: vec![],
            to: response_cid,
            witness: None,
            payload: Some(response_term),
            verdict: Verdict::Unresolved,
            attestation: None,
        })
    }

    #[deprecated(
        note = "lift plugin kits emit Term values; move this caller to consume the term directly"
    )]
    pub fn legacy_response_from_term(term: &Term) -> Result<&Value, LiftPluginKitError> {
        legacy_response_from_term(term)
    }

    fn dispatch(&self, lift_params: &Value) -> Result<(Value, Value), LiftPluginKitError> {
        if self.command.is_empty() {
            return Err(LiftPluginKitError::Failed(
                "lift plugin command is empty".to_string(),
            ));
        }

        let mut cmd = Command::new(&self.command[0]);
        if self.command.len() > 1 {
            cmd.args(&self.command[1..]);
        }
        if !self.command.iter().any(|arg| arg == "--rpc") {
            cmd.arg("--rpc");
        }
        if let Some(working_dir) = &self.working_dir {
            cmd.current_dir(working_dir);
        }
        cmd.stdin(Stdio::piped());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::inherit());

        let mut child = match cmd.spawn() {
            Ok(child) => child,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Err(LiftPluginKitError::MissingBinary {
                    binary: self.command[0].clone(),
                });
            }
            Err(error) => {
                return Err(LiftPluginKitError::Failed(format!(
                    "spawn {:?}: {error}",
                    self.command
                )));
            }
        };

        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| LiftPluginKitError::Failed("lift plugin stdin unavailable".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| LiftPluginKitError::Failed("lift plugin stdout unavailable".into()))?;
        let mut reader = BufReader::new(stdout);

        let init_req = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "client": {"name": "libsugar", "version": env!("CARGO_PKG_VERSION")},
                "protocol_version": "pep/1.7.0",
                "workspace_root": lift_params.get("workspace_root").cloned().unwrap_or_else(|| json!(".")),
                "config_path": lift_params.get("config_path").cloned().unwrap_or_else(|| json!(".sugar/config.toml"))
            }
        });
        writeln!(stdin, "{init_req}").map_err(|error| {
            LiftPluginKitError::Failed(format!("write lift initialize: {error}"))
        })?;
        let initialize_response = read_response(&mut reader, 1)?;

        let lift_req = json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": self.lift_method,
            "params": lift_params
        });
        writeln!(stdin, "{lift_req}")
            .map_err(|error| LiftPluginKitError::Failed(format!("write lift request: {error}")))?;
        let response = read_response(&mut reader, 2)?;

        let shutdown_req = json!({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "shutdown"
        });
        let _ = writeln!(stdin, "{shutdown_req}");
        drop(stdin);

        let status = child
            .wait()
            .map_err(|error| LiftPluginKitError::Failed(format!("wait lift plugin: {error}")))?;
        if !status.success() {
            return Err(LiftPluginKitError::Failed(format!(
                "lift plugin exited {status}"
            )));
        }

        Ok((initialize_response, response))
    }
}

impl LiftKit {
    /// Build a source Lift Kit from an already-resolved lift-plugin command.
    pub fn new(
        dialect: Dialect,
        surface: impl Into<String>,
        command: Vec<String>,
        working_dir: Option<PathBuf>,
    ) -> Self {
        Self {
            dialect,
            transport: LiftPluginKit::new(surface, command, working_dir),
        }
    }

    fn lift_params_from_source(&self, input: &Input) -> Result<Value, LiftPluginKitError> {
        let Input::Source { dialect, bytes } = input else {
            return Err(LiftPluginKitError::Failed(
                "lift kit expects Input::Source".to_string(),
            ));
        };
        if dialect != &self.dialect {
            return Err(LiftPluginKitError::Failed(format!(
                "lift kit expected source dialect {:?}, got {:?}",
                self.dialect, dialect
            )));
        }
        serde_json::from_slice(bytes).map_err(|error| {
            LiftPluginKitError::Failed(format!(
                "lift source bytes must encode lift-plugin request JSON: {error}"
            ))
        })
    }
}

impl Kit for LiftKit {
    fn dialect(&self) -> Dialect {
        self.dialect.clone()
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        let lift_params = self
            .lift_params_from_source(input)
            .map_err(|error| KitError::Transformation(error.to_string()))?;
        let spec_input = Input::Spec(lift_params);
        let mut claim = self
            .transport
            .parse_session(&spec_input)
            .map(|session| session.claim)
            .map_err(|error| KitError::Transformation(format!("lift plugin transport: {error}")))?;
        claim.from = vec![address(input)];
        Ok(claim)
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        Ok(claim)
    }

    fn parse(&self, input: &Input) -> Result<Term, KitError> {
        self.transform(input)?
            .payload
            .ok_or_else(|| KitError::Serialization("lift claim missing term payload".to_string()))
    }

    fn serialize(&self, term: &Term) -> Result<Input, KitError> {
        Ok(Input::Term(term.clone()))
    }
}

impl Kit for LiftPluginKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other(format!("lift-plugin:{}", self.surface))
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        self.parse_session(input)
            .map(|session| session.claim)
            .map_err(|error| KitError::Transformation(format!("lift plugin transport: {error}")))
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        Ok(claim)
    }

    fn parse(&self, input: &Input) -> Result<Term, KitError> {
        self.parse_session(input)
            .map(|session| response_term(session.legacy_response))
            .map_err(|error| KitError::Serialization(format!("lift plugin transport: {error}")))
    }

    fn serialize(&self, term: &Term) -> Result<Input, KitError> {
        let response = legacy_response_from_term(term)
            .map_err(|error| KitError::Serialization(error.to_string()))?;
        Ok(Input::Spec(response.clone()))
    }
}

/// Result of one lift-plugin Kit parse.
#[derive(Debug, Clone)]
pub struct LiftPluginKitSession {
    /// The initialize response from the plugin.
    pub initialize_response: Value,
    /// The legacy JSON-RPC lift response retained outside the primitive claim.
    pub legacy_response: Value,
    /// The primitive claim produced by `Kit::transform`.
    pub claim: DomainClaim,
}

impl LiftPluginKitSession {
    /// Borrow the materialized lift-plugin response retained outside the primitive claim.
    pub fn response(&self) -> &Value {
        &self.legacy_response
    }

    #[deprecated(
        note = "lift plugin kits emit DomainClaim values; move this caller to consume `claim` directly"
    )]
    pub fn legacy_response(&self) -> Result<&Value, LiftPluginKitError> {
        Ok(&self.legacy_response)
    }
}

/// Errors from the lift-plugin Kit transport.
#[derive(Debug, Error)]
pub enum LiftPluginKitError {
    /// The configured lifter binary was not found.
    #[error("lifter binary `{binary}` not found")]
    MissingBinary { binary: String },
    /// The JSON-RPC session failed.
    #[error("{0}")]
    Failed(String),
    /// The response term was no longer the deprecated JSON escape-hatch shape.
    #[error("lift plugin term no longer carries a legacy response")]
    LegacyResponseUnavailable,
}

fn lift_request_from_input(input: &Input) -> Result<&Value, LiftPluginKitError> {
    match input {
        Input::Spec(value) => Ok(value),
        _ => Err(LiftPluginKitError::Failed(
            "lift plugin kit expects Input::Spec lift parameters".to_string(),
        )),
    }
}

fn response_term(response: Value) -> Term {
    Term::Const {
        value: response,
        sort: primitive_sort("LiftPluginResponse"),
    }
}

fn lift_response_contract(surface: &str, response: &Value, response_cid: &Cid) -> Contract {
    let response_kind = response
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let fn_name = format!("lift::{surface}::{response_kind}");
    let pre = IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    };
    let post = IrFormula::Atomic {
        name: "lift_result_cid".to_string(),
        args: vec![
            IrTerm::Var {
                name: "result".to_string(),
            },
            IrTerm::Const {
                value: json!(response_cid.as_str()),
                sort: primitive_sort("Cid"),
            },
        ],
    };

    memento_from_parts(
        fn_name,
        vec!["request".to_string()],
        vec![primitive_sort("LiftPluginRequest")],
        primitive_sort("LiftPluginResponse"),
        pre,
        post,
        Some(response_cid.as_str().to_string()),
    )
}

fn primitive_sort(name: &str) -> Sort {
    Sort::Primitive {
        name: name.to_string(),
    }
}

fn legacy_response_from_term(term: &Term) -> Result<&Value, LiftPluginKitError> {
    match term {
        Term::Const { value, .. } => Ok(value),
        _ => Err(LiftPluginKitError::LegacyResponseUnavailable),
    }
}

fn read_response(reader: &mut impl BufRead, id: i64) -> Result<Value, LiftPluginKitError> {
    let mut line = String::new();
    trace_lift_transport_checkpoint("read_response.before_read_line", &Value::Null, 0);
    let n = reader
        .read_line(&mut line)
        .map_err(|error| LiftPluginKitError::Failed(format!("read lift response: {error}")))?;
    trace_lift_transport_checkpoint("read_response.after_read_line", &Value::Null, n);
    if n == 0 {
        return Err(LiftPluginKitError::Failed(
            "lift plugin closed stdout before responding".to_string(),
        ));
    }
    let before = current_rss_kib();
    let value: Value = serde_json::from_str(line.trim()).map_err(|error| {
        LiftPluginKitError::Failed(format!(
            "parse lift JSON-RPC response: {error}\n  raw: {line}"
        ))
    })?;
    trace_lift_transport_checkpoint_with_delta(
        "read_response.after_parse_json_rpc",
        value.get("result").unwrap_or(&Value::Null),
        line.len(),
        rss_delta_kib(before, current_rss_kib()),
    );
    if value.get("id").and_then(Value::as_i64) != Some(id) {
        return Err(LiftPluginKitError::Failed(format!(
            "lift response id mismatch: expected {id}, got {value:?}"
        )));
    }
    if let Some(error) = value.get("error") {
        return Err(LiftPluginKitError::Failed(format!(
            "lift plugin returned error: {error}"
        )));
    }
    let result = value
        .get("result")
        .ok_or_else(|| LiftPluginKitError::Failed("lift response missing `result`".into()))?;
    let before = current_rss_kib();
    let result = result.clone();
    trace_lift_transport_checkpoint_with_delta(
        "read_response.after_result_clone",
        &result,
        line.len(),
        rss_delta_kib(before, current_rss_kib()),
    );
    Ok(result)
}

fn current_rss_kib() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let status = std::fs::read_to_string("/proc/self/status").ok()?;
        status.lines().find_map(|line| {
            let rest = line.strip_prefix("VmRSS:")?;
            rest.split_whitespace().next()?.parse::<u64>().ok()
        })
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

fn rss_delta_kib(before: Option<u64>, after: Option<u64>) -> Option<u64> {
    Some(after?.saturating_sub(before?))
}

fn lift_response_array_len(value: &Value, keys: &[&str]) -> usize {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(Value::as_array).map(Vec::len))
        .unwrap_or(0)
}

fn trace_lift_transport_checkpoint(stage: &'static str, response: &Value, line_bytes: usize) {
    trace_lift_transport_checkpoint_with_delta(stage, response, line_bytes, None);
}

fn trace_lift_transport_checkpoint_with_delta(
    stage: &'static str,
    response: &Value,
    line_bytes: usize,
    rss_delta_kib: Option<u64>,
) {
    let rss_kib = current_rss_kib();
    info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        rss_delta_kib = rss_delta_kib.unwrap_or_default(),
        line_bytes = line_bytes,
        contracts = lift_response_array_len(response, &["ir"]),
        source_audits = lift_response_array_len(response, &["sourceAudits", "source_audits"]),
        factory_audits = lift_response_array_len(response, &["factoryAudits", "factory_audits"]),
        assertion_surface_audits = lift_response_array_len(
            response,
            &["assertionSurfaceAudits", "assertion_surface_audits"]
        ),
        source_mementos = lift_response_array_len(response, &["sourceMementos", "source_mementos"]),
        call_edges = lift_response_array_len(response, &["callEdges", "call_edges"]),
        vendor_conjoins = lift_response_array_len(
            response,
            &[
                "vendorConjoins",
                "vendor_conjoins",
                "linkerConjoins",
                "linker_conjoins"
            ]
        ),
        "lift-plugin transport memory checkpoint"
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lift_response_array_len_accepts_camel_and_snake_case() {
        let response = json!({
            "sourceAudits": [1, 2],
            "factory_audits": [3, 4, 5],
            "scalar": 9,
        });

        assert_eq!(
            lift_response_array_len(&response, &["sourceAudits", "source_audits"]),
            2
        );
        assert_eq!(
            lift_response_array_len(&response, &["factoryAudits", "factory_audits"]),
            3
        );
        assert_eq!(lift_response_array_len(&response, &["scalar"]), 0);
        assert_eq!(lift_response_array_len(&response, &["missing"]), 0);
    }
}
