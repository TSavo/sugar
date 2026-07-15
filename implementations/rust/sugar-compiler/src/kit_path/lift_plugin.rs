// SPDX-License-Identifier: MIT OR Apache-2.0

use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::Deserialize;
use serde_json::{json, Value};
use sugar_ir_types::{IrFormula, IrTerm, Sort};
// BOUNDARY IMPURITY (flagged in SEAM 3b review, not fixed here): this pulls
// RUST-KIT-specific knowledge (sugar-walk) into the language-neutral kit
// dispatch engine. Lift-and-shift only -- moved byte-identical from
// sugar-cli/src/kit_path/lift_plugin.rs, where it already lived. The kits-
// are-blind asymmetry says this normalization belongs kit-side (the rust
// kit should strip its own realize-sidecar before returning a response
// across the membrane); today the neutral engine reaches into one
// language's kit to do it for every kit. No guard rule forbids
// sugar-compiler -> sugar-walk today, but once this call moves behind the
// membrane (a future purification seam), add one.
use sugar_walk::strip_realize_sidecar_from_lift_term;
use thiserror::Error;
use tracing::{info, info_span};

fn transport_millis() -> u128 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_millis()
}

fn trace_frame(direction: &'static str, frame: &str, stage: &'static str) {
    let value: Value = serde_json::from_str(frame.trim()).unwrap_or(Value::Null);
    info!(
        direction,
        bytes = frame.len(),
        message_id = ?value.get("id"),
        method = ?value.get("method").and_then(|item| item.as_str()),
        monotonic_ms = transport_millis(),
        stage,
        "lift-plugin transport frame"
    );
}

use libsugar::core::primitives::address;
use libsugar::core::traits::{Kit, KitError};
use libsugar::core::types::{
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
    question_cache: std::sync::Arc<Mutex<sugar_lift_rpc_client::QuestionCache>>,
    resident: std::sync::Arc<ResidentSlot>,
    resident_max_requests: usize,
    terminal_error: std::sync::Arc<Mutex<Option<LiftPluginKitError>>>,
}

struct ResidentSlot(Mutex<Option<ResidentLifter>>);

impl std::fmt::Debug for ResidentSlot {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ResidentSlot").finish_non_exhaustive()
    }
}

impl Drop for ResidentSlot {
    fn drop(&mut self) {
        if let Ok(slot) = self.0.get_mut() {
            drop(slot.take());
        }
    }
}

struct ResponseReader {
    lines: Receiver<Result<String, String>>,
}

impl ResponseReader {
    fn spawn(stdout: std::process::ChildStdout) -> Self {
        let (sender, lines) = mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => break,
                    Ok(_) => {
                        if sender.send(Ok(line)).is_err() {
                            break;
                        }
                    }
                    Err(error) => {
                        let _ = sender.send(Err(error.to_string()));
                        break;
                    }
                }
            }
        });
        Self { lines }
    }
}

fn stop_child_after_transport_failure(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn response_deadline() -> Duration {
    std::env::var("SUGAR_LIFT_RESPONSE_TIMEOUT_SECS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .map(Duration::from_secs)
        .unwrap_or(Duration::from_secs(120))
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
            question_cache: std::sync::Arc::new(Mutex::new(
                sugar_lift_rpc_client::QuestionCache::default(),
            )),
            resident: std::sync::Arc::new(ResidentSlot(Mutex::new(None))),
            resident_max_requests: resident_max_requests(),
            terminal_error: std::sync::Arc::new(Mutex::new(None)),
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

    /// Send one bounded request through the resident JSON-RPC session.
    pub(crate) fn request(&self, params: &Value) -> Result<Value, LiftPluginKitError> {
        let mut cache = self
            .question_cache
            .lock()
            .map_err(|_| LiftPluginKitError::Failed("RPC question cache poisoned".to_string()))?;
        cache.ask(params, || {
            self.dispatch(params).map(|(_, response)| response)
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
                        "sugar-bound-exceeded": "response-term-exceeds-byte-bound",
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
        // BOUNDARY IMPURITY: see the `use sugar_walk::...` import note above
        // -- this is the actual crossing point where the neutral engine does
        // a rust-kit-specific normalization for every kit, not just rust's.
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
        if let Some(error) = self
            .terminal_error
            .lock()
            .map_err(|_| LiftPluginKitError::Failed("terminal RPC state poisoned".to_string()))?
            .clone()
        {
            return Err(error);
        }
        if self.command.is_empty() {
            return Err(LiftPluginKitError::Failed(
                "lift plugin command is empty".to_string(),
            ));
        }

        // RESIDENT-LIFTER FAST PATH (#3774): the lift-plugin protocol is
        // already a request loop (`initialize` once, then N `lift` calls,
        // then `shutdown` -- see e.g. the python `lift_rpc.py::main`'s
        // `while True` dispatch). The bottleneck killing the pandas-demo
        // save cycle (~15s of ~35s) was never the protocol: it was THIS
        // caller spawning a fresh process and sending `shutdown` after
        // exactly one `lift`, forcing a fresh `import pandas` every mint.
        // `SUGAR_LIFT_NO_RESIDENT=1` is the escape hatch back to the old
        // one-shot-per-call behavior (kept below, byte-identical) for any
        // caller that cannot tolerate a long-lived subprocess.
        if resident_enabled() {
            match self.dispatch_resident(lift_params) {
                Ok(pair) => return Ok(pair),
                Err(ResidentDispatchError::Fatal(error)) => {
                    self.remember_terminal_error(&error)?;
                    return Err(error);
                }
            }
        }

        let (initialize_response, response, mut child, mut stdin, _reader) =
            match self.spawn_and_run_once(lift_params) {
                Ok(session) => session,
                Err(error) => {
                    self.remember_terminal_error(&error)?;
                    return Err(error);
                }
            };
        let shutdown_req = json!({"jsonrpc": "2.0", "id": 3, "method": "shutdown"});
        let shutdown_frame = format!("{shutdown_req}\n");
        trace_frame("cli_to_kit", &shutdown_frame, "write_stdin.enter");
        let _ = stdin.write_all(shutdown_frame.as_bytes());
        let _ = stdin.flush();
        drop(stdin);
        info!(
            pid = child.id(),
            monotonic_ms = transport_millis(),
            stage = "wait.enter",
            "lift-plugin blocking call"
        );
        let status = child
            .wait()
            .map_err(|error| LiftPluginKitError::Failed(format!("wait lift plugin: {error}")))?;
        info!(
            pid = child.id(),
            ?status,
            monotonic_ms = transport_millis(),
            stage = "wait.exit",
            "lift-plugin process exit"
        );
        if !status.success() {
            return Err(LiftPluginKitError::Failed(format!(
                "lift plugin exited {status}"
            )));
        }
        Ok((initialize_response, response))
    }

    fn remember_terminal_error(
        &self,
        error: &LiftPluginKitError,
    ) -> Result<(), LiftPluginKitError> {
        *self
            .terminal_error
            .lock()
            .map_err(|_| LiftPluginKitError::Failed("terminal RPC state poisoned".to_string()))? =
            Some(error.clone());
        Ok(())
    }

    /// Spawn a fresh child, run exactly one `initialize` + one lift call
    /// (using request ids 1/2, matching the historical one-shot protocol),
    /// and return the live child + its stdin/stdout handles so the caller
    /// decides whether to `shutdown` it (one-shot path) or keep it resident
    /// (pool path, which keeps `reader`/`stdin` alive for further requests).
    fn spawn_and_run_once(
        &self,
        lift_params: &Value,
    ) -> Result<(Value, Value, Child, ChildStdin, ResponseReader), LiftPluginKitError> {
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
        cmd.stderr(Stdio::piped());

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
        info!(pid = child.id(), command = ?self.command, monotonic_ms = transport_millis(), stage = "spawn", "lift-plugin process spawn");
        if let Some(stderr) = child.stderr.take() {
            let pid = child.id();
            std::thread::spawn(move || {
                let mut reader = BufReader::new(stderr);
                let mut buffer = [0_u8; 8192];
                loop {
                    match reader.read(&mut buffer) {
                        Ok(0) => {
                            info!(
                                pid,
                                monotonic_ms = transport_millis(),
                                bytes = 0,
                                stage = "stderr.eof",
                                "lift-plugin child stderr drain"
                            );
                            break;
                        }
                        Ok(n) => info!(
                            pid,
                            monotonic_ms = transport_millis(),
                            bytes = n,
                            stage = "stderr.read",
                            "lift-plugin child stderr drain"
                        ),
                        Err(error) => {
                            info!(pid, %error, monotonic_ms = transport_millis(), stage = "stderr.error", "lift-plugin child stderr drain");
                            break;
                        }
                    }
                }
            });
        }

        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| LiftPluginKitError::Failed("lift plugin stdin unavailable".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| LiftPluginKitError::Failed("lift plugin stdout unavailable".into()))?;
        let reader = ResponseReader::spawn(stdout);

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
        let init_frame = format!("{init_req}\n");
        trace_frame("cli_to_kit", &init_frame, "write_stdin.enter");
        stdin.write_all(init_frame.as_bytes()).map_err(|error| {
            LiftPluginKitError::Failed(format!("write lift initialize: {error}"))
        })?;
        info!(
            monotonic_ms = transport_millis(),
            stage = "write_stdin.exit",
            "lift-plugin blocking call"
        );
        info!(
            monotonic_ms = transport_millis(),
            stage = "stdin.flush.enter",
            "lift-plugin buffer flush"
        );
        stdin.flush().map_err(|error| {
            LiftPluginKitError::Failed(format!("flush lift initialize: {error}"))
        })?;
        info!(
            monotonic_ms = transport_millis(),
            stage = "stdin.flush.exit",
            "lift-plugin buffer flush"
        );
        let initialize_response = match read_response(&reader, 1) {
            Ok(response) => response,
            Err(error) => {
                stop_child_after_transport_failure(&mut child);
                return Err(error);
            }
        };

        let lift_req = json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": self.lift_method,
            "params": lift_params
        });
        let lift_frame = format!("{lift_req}\n");
        trace_frame("cli_to_kit", &lift_frame, "write_stdin.enter");
        stdin
            .write_all(lift_frame.as_bytes())
            .map_err(|error| LiftPluginKitError::Failed(format!("write lift request: {error}")))?;
        info!(
            monotonic_ms = transport_millis(),
            stage = "write_stdin.exit",
            "lift-plugin blocking call"
        );
        info!(
            monotonic_ms = transport_millis(),
            stage = "stdin.flush.enter",
            "lift-plugin buffer flush"
        );
        stdin
            .flush()
            .map_err(|error| LiftPluginKitError::Failed(format!("flush lift request: {error}")))?;
        info!(
            monotonic_ms = transport_millis(),
            stage = "stdin.flush.exit",
            "lift-plugin buffer flush"
        );
        let response = match read_response(&reader, 2) {
            Ok(response) => response,
            Err(error) => {
                stop_child_after_transport_failure(&mut child);
                return Err(error);
            }
        };

        Ok((initialize_response, response, child, stdin, reader))
    }

    /// Try to serve `lift_params` from a resident (already-warm) child.
    /// Spawns one on first use for this key, keyed by command+cwd, and
    /// keeps it alive across calls so `import pandas` (or any equally
    /// heavy one-time interpreter/module cost) is paid exactly once per
    /// process, not once per mint.
    ///
    /// A generation is retired between requests after its configured number
    /// of successful responses. Transport and protocol failures are terminal,
    /// never rotation or retry signals.
    fn dispatch_resident(
        &self,
        lift_params: &Value,
    ) -> Result<(Value, Value), ResidentDispatchError> {
        let mut slot = self.resident.0.lock().map_err(|_| {
            ResidentDispatchError::Fatal(LiftPluginKitError::Failed(
                "resident lifter slot poisoned".to_string(),
            ))
        })?;

        let needs_fresh = slot
            .as_ref()
            .map(|entry| entry.successful_responses >= self.resident_max_requests)
            .unwrap_or(true);
        if needs_fresh {
            if let Some(mut old) = slot.take() {
                old.shutdown_best_effort();
            }
            let (initialize_response, child, stdin, reader, first_response) = self
                .spawn_resident(lift_params)
                .map_err(ResidentDispatchError::Fatal)?;
            *slot = Some(ResidentLifter {
                child,
                stdin,
                reader,
                next_id: 3,
                initialize_response,
                first_lift_response: Some(first_response),
                successful_responses: 1,
                shutdown_allowed: true,
            });
        }

        let entry = slot.as_mut().expect("just inserted or already present");
        let initialize_response = entry.initialize_response.clone();
        if needs_fresh {
            let response = entry
                .first_lift_response
                .take()
                .expect("fresh resident carries its first lift response");
            return Ok((initialize_response, response));
        }

        let id = entry.next_id;
        entry.next_id += 1;
        let lift_req = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": self.lift_method,
            "params": lift_params
        });
        let lift_frame = format!("{lift_req}\n");
        trace_frame("cli_to_kit", &lift_frame, "write_stdin.enter");
        if let Err(error) = entry.stdin.write_all(lift_frame.as_bytes()) {
            if let Some(mut entry) = slot.take() {
                entry.abort_without_shutdown();
            }
            return Err(ResidentDispatchError::Fatal(LiftPluginKitError::Failed(
                format!("write lift request to resident: {error}"),
            )));
        }
        info!(
            monotonic_ms = transport_millis(),
            stage = "write_stdin.exit",
            "lift-plugin blocking call"
        );
        info!(
            monotonic_ms = transport_millis(),
            stage = "stdin.flush.enter",
            "lift-plugin buffer flush"
        );
        if let Err(error) = entry.stdin.flush() {
            if let Some(mut entry) = slot.take() {
                entry.abort_without_shutdown();
            }
            return Err(ResidentDispatchError::Fatal(LiftPluginKitError::Failed(
                format!("flush lift request to resident: {error}"),
            )));
        }
        info!(
            monotonic_ms = transport_millis(),
            stage = "stdin.flush.exit",
            "lift-plugin buffer flush"
        );
        match read_response(&entry.reader, id) {
            Ok(response) => {
                entry.successful_responses += 1;
                Ok((initialize_response, response))
            }
            Err(error) => {
                if let Some(mut entry) = slot.take() {
                    entry.abort_without_shutdown();
                }
                Err(ResidentDispatchError::Fatal(error))
            }
        }
    }

    /// Spawn a resident child and drive its first `initialize` + `lift`
    /// (ids 1/2), WITHOUT sending `shutdown` -- the process is left running
    /// for the pool to reuse. Returns the live child/stdin/reader plus the
    /// first lift's response (stashed into the pool entry by the caller).
    #[allow(clippy::type_complexity)]
    fn spawn_resident(
        &self,
        lift_params: &Value,
    ) -> Result<(Value, Child, ChildStdin, ResponseReader, Value), LiftPluginKitError> {
        let (initialize_response, first_response, child, stdin, reader) =
            self.spawn_and_run_once(lift_params)?;
        Ok((initialize_response, child, stdin, reader, first_response))
    }
}

/// One warm lift-plugin process kept alive across `dispatch` calls.
struct ResidentLifter {
    child: Child,
    stdin: ChildStdin,
    reader: ResponseReader,
    next_id: i64,
    initialize_response: Value,
    /// The first `lift` response, stashed at spawn time (spawning already
    /// drives one full `initialize`+`lift` round trip identical to the
    /// historical one-shot protocol); consumed by the first
    /// `dispatch_resident` call against a freshly (re)spawned entry.
    first_lift_response: Option<Value>,
    /// Successful lift responses served by this process generation.
    successful_responses: usize,
    /// Fatal protocol frames forbid shutdown-as-recovery; false means kill only.
    shutdown_allowed: bool,
}

impl ResidentLifter {
    /// Best-effort graceful shutdown of a resident being evicted (stale or
    /// replaced). Never blocks the caller on a hung process: errors here
    /// are swallowed, the entry is being dropped regardless.
    fn shutdown_best_effort(&mut self) {
        if !self.shutdown_allowed {
            let _ = self.child.kill();
            let _ = self.child.wait();
            return;
        }
        let shutdown_req = json!({"jsonrpc": "2.0", "id": 0, "method": "shutdown"});
        let _ = writeln!(self.stdin, "{shutdown_req}");
        let _ = self.child.kill();
        let _ = self.child.wait();
    }

    fn abort_without_shutdown(&mut self) {
        self.shutdown_allowed = false;
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for ResidentLifter {
    fn drop(&mut self) {
        self.shutdown_best_effort();
    }
}

/// `SUGAR_LIFT_NO_RESIDENT=1` disables the resident pool entirely (falls
/// back to spawn-per-call, byte-identical to the pre-#3774 behavior). The
/// default is resident-ON: the whole point is that a caller which never
/// sets this env var gets the warm path for free.
fn resident_enabled() -> bool {
    std::env::var("SUGAR_LIFT_NO_RESIDENT")
        .map(|v| v != "1")
        .unwrap_or(true)
}

fn resident_max_requests() -> usize {
    std::env::var("SUGAR_LIFT_RESIDENT_MAX_REQUESTS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(256)
}

/// Outcome of a resident-path dispatch attempt.
enum ResidentDispatchError {
    /// A real failure the caller should propagate (e.g. binary missing).
    Fatal(LiftPluginKitError),
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

    /// Override the JSON-RPC method used for the lift request, forwarding to
    /// the underlying `LiftPluginKit::with_method` (e.g. consumer surfaces
    /// like `rust-implications` whose manifest declares
    /// `method = "sugar.plugin.lift_implications"`). Without this, `Kit::lift`
    /// would silently call every kit's default `lift` method regardless of
    /// what its manifest declared.
    pub fn with_method(mut self, method: impl Into<String>) -> Self {
        self.transport = self.transport.with_method(method);
        self
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

fn lift_plugin_error_to_kit(error: LiftPluginKitError) -> KitError {
    match error {
        LiftPluginKitError::FatalFactoryPanic(fatal) => KitError::Terminal {
            kind: "FactoryPanic".to_string(),
            detail: json!({
                "code": fatal.code,
                "message": fatal.message,
                "stage": fatal.stage,
                "diagnostic": fatal.diagnostic,
            }),
        },
        other => KitError::Transformation(format!("lift plugin transport: {other}")),
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
            .map_err(lift_plugin_error_to_kit)?;
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
            .map_err(lift_plugin_error_to_kit)
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
#[derive(Debug, Clone, Error)]
pub enum LiftPluginKitError {
    /// The configured lifter binary was not found.
    #[error("lifter binary `{binary}` not found")]
    MissingBinary { binary: String },
    /// The JSON-RPC session failed.
    #[error("{0}")]
    Failed(String),
    /// The plugin reported its mandatory construction panic. This terminal
    /// protocol state may not be retried or converted to a normal diagnostic.
    #[error("{0}")]
    FatalFactoryPanic(FactoryPanicRpcError),
    /// The response term was no longer the deprecated JSON escape-hatch shape.
    #[error("lift plugin term no longer carries a legacy response")]
    LegacyResponseUnavailable,
}

/// Typed terminal payload emitted when the Python lift boundary reaches a
/// mandatory Factory construction gap.
#[derive(Debug, Clone, PartialEq)]
pub struct FactoryPanicRpcError {
    pub code: i64,
    pub message: String,
    pub stage: String,
    pub diagnostic: Value,
}

impl FactoryPanicRpcError {
    pub fn from_terminal_detail(detail: Value) -> Option<Self> {
        Some(Self {
            code: detail.get("code")?.as_i64()?,
            message: detail.get("message")?.as_str()?.to_string(),
            stage: detail.get("stage")?.as_str()?.to_string(),
            diagnostic: detail.get("diagnostic")?.clone(),
        })
    }
}

impl std::fmt::Display for FactoryPanicRpcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "fatal lift plugin FactoryPanic code={} stage={}: {} diagnostic={}",
            self.code, self.stage, self.message, self.diagnostic
        )
    }
}

#[derive(Debug, Deserialize)]
struct FactoryPanicRpcData {
    exception_type: String,
    stage: String,
    diagnostic: Value,
}

fn decode_rpc_error(error: &Value) -> LiftPluginKitError {
    let code = error.get("code").and_then(Value::as_i64);
    let message = error.get("message").and_then(Value::as_str);
    let data = error
        .get("data")
        .cloned()
        .and_then(|data| serde_json::from_value::<FactoryPanicRpcData>(data).ok());

    if let (Some(-32603), Some(message), Some(data)) = (code, message, data) {
        if data.exception_type == "FactoryPanic" && data.stage == "dispatch" {
            return LiftPluginKitError::FatalFactoryPanic(FactoryPanicRpcError {
                code: -32603,
                message: message.to_string(),
                stage: data.stage,
                diagnostic: data.diagnostic,
            });
        }
    }

    LiftPluginKitError::Failed(format!("lift plugin returned error: {error}"))
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

fn read_response(reader: &ResponseReader, id: i64) -> Result<Value, LiftPluginKitError> {
    read_response_with_deadline(reader, id, response_deadline())
}

fn read_response_with_deadline(
    reader: &ResponseReader,
    id: i64,
    deadline: Duration,
) -> Result<Value, LiftPluginKitError> {
    let _span = info_span!("lift_plugin_read_response", message_id = id).entered();
    trace_lift_transport_checkpoint("read_response.before_read_line", &Value::Null, 0);
    info!(
        direction = "kit_to_cli",
        message_id = id,
        monotonic_ms = transport_millis(),
        stage = "read_line.enter",
        "lift-plugin blocking call"
    );
    let line = match reader.lines.recv_timeout(deadline) {
        Ok(Ok(line)) => line,
        Ok(Err(error)) => {
            return Err(LiftPluginKitError::Failed(format!(
            "lift plugin transport read failed at stage=read_line.enter message_id={id}: {error}"
        )))
        }
        Err(RecvTimeoutError::Timeout) => {
            tracing::error!(
                stage = "read_line.enter",
                message_id = id,
                deadline_secs = deadline.as_secs(),
                "lift-plugin transport stalled without a response frame"
            );
            return Err(LiftPluginKitError::Failed(format!(
                "lift plugin transport stalled at stage=read_line.enter message_id={id} deadline_secs={}; no response frame arrived",
                deadline.as_secs()
            )));
        }
        Err(RecvTimeoutError::Disconnected) => {
            tracing::error!(
                stage = "read_line.disconnected",
                message_id = id,
                deadline_secs = deadline.as_secs(),
                "lift-plugin process ended without responding"
            );
            return Err(LiftPluginKitError::Failed(format!(
                "lift plugin transport disconnected at stage=read_line.disconnected message_id={id}: plugin process ended without responding"
            )));
        }
    };
    let n = line.len();
    trace_lift_transport_checkpoint("read_response.after_read_line", &Value::Null, n);
    info!(
        direction = "kit_to_cli",
        bytes = n,
        message_id = id,
        monotonic_ms = transport_millis(),
        stage = "read_line.exit",
        "lift-plugin transport frame"
    );
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
        return Err(decode_rpc_error(error));
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

    #[test]
    fn stalled_response_is_loud_and_names_last_transport_stage() {
        let mut child = Command::new("sh")
            .args(["-c", "sleep 1"])
            .stdout(Stdio::piped())
            .spawn()
            .expect("spawn stalled plugin stub");
        let reader = ResponseReader::spawn(child.stdout.take().expect("stub stdout"));

        let error = read_response_with_deadline(&reader, 2, Duration::from_millis(20))
            .expect_err("stalled plugin must return a bounded error");
        let detail = error.to_string();
        assert!(detail.contains("transport stalled"), "{detail}");
        assert!(detail.contains("stage=read_line.enter"), "{detail}");
        assert!(detail.contains("message_id=2"), "{detail}");
        let _ = child.kill();
        let _ = child.wait();
    }

    #[test]
    fn disconnected_response_is_loud_and_names_plugin_death() {
        let mut child = Command::new("sh")
            .args(["-c", "exit 0"])
            .stdout(Stdio::piped())
            .spawn()
            .expect("spawn exiting plugin stub");
        let reader = ResponseReader::spawn(child.stdout.take().expect("stub stdout"));

        let error = read_response_with_deadline(&reader, 7, Duration::from_secs(1))
            .expect_err("plugin death must return a transport error");
        let detail = error.to_string();
        assert!(detail.contains("transport disconnected"), "{detail}");
        assert!(detail.contains("stage=read_line.disconnected"), "{detail}");
        assert!(detail.contains("message_id=7"), "{detail}");
        assert!(
            detail.contains("process ended without responding"),
            "{detail}"
        );
        let _ = child.wait();
    }

    fn protocol_stub(log_path: &std::path::Path) -> (tempfile::TempDir, Vec<String>) {
        let temp = tempfile::tempdir().expect("tempdir for protocol stub");
        let script = temp.path().join("lift_stub.py");
        let source = r#"
import json
import os
import sys

log_path = sys.argv[1]
for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    mode = request.get("params", {}).get("mode", "none")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"{os.getpid()}:{method}:{mode}\n")
    if method == "initialize":
        response = {"jsonrpc": "2.0", "id": request["id"], "result": {"name": "stub"}}
    elif method == "lift" and mode == "fatal":
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {
                "code": -32603,
                "message": "FACTORY PANIC: write more Floor for this Construction",
                "data": {
                    "exception_type": "FactoryPanic",
                    "stage": "dispatch",
                    "diagnostic": {
                        "owner": "rpc-fixture",
                        "blame": "fixture.py:1:0",
                        "observed": "missing",
                        "requested": "value",
                        "fix": "construct the missing Floor",
                        "gap_kind": "Floor",
                        "gap_locus": "Construction"
                    }
                }
            }
        }
        print(json.dumps(response), flush=True)
        raise SystemExit(1)
    elif method == "lift":
        response = {"jsonrpc": "2.0", "id": request["id"], "result": {"kind": "ir-document", "ir": []}}
    elif method == "shutdown":
        response = {"jsonrpc": "2.0", "id": request["id"], "result": None}
        print(json.dumps(response), flush=True)
        break
    else:
        raise AssertionError(method)
    print(json.dumps(response), flush=True)
"#;
        std::fs::write(&script, source).expect("write protocol stub");
        (
            temp,
            vec![
                "python3".to_string(),
                script.to_string_lossy().into_owned(),
                log_path.to_string_lossy().into_owned(),
            ],
        )
    }

    fn protocol_log(path: &std::path::Path) -> Vec<String> {
        std::fs::read_to_string(path)
            .unwrap_or_default()
            .lines()
            .map(str::to_string)
            .collect()
    }

    #[test]
    fn factory_panic_bad_twin_is_terminal_without_retry_shutdown_artifact_or_next_request() {
        let temp = tempfile::tempdir().expect("test tempdir");
        let log_path = temp.path().join("requests.log");
        let (_stub, command) = protocol_stub(&log_path);
        let mut kit = LiftPluginKit::new("python", command, None);
        kit.resident_max_requests = 2;

        let control = kit
            .parse_session(&Input::Spec(json!({
                "workspace_root": ".",
                "mode": "control"
            })))
            .expect("control request establishes a resident process");
        assert_eq!(control.response()["kind"], "ir-document");
        assert_eq!(control.claim.artifacts.len(), 1);

        let error = kit
            .parse_session(&Input::Spec(json!({
                "workspace_root": ".",
                "mode": "fatal"
            })))
            .expect_err("typed FactoryPanic frame must terminate without a claim/artifact");
        let LiftPluginKitError::FatalFactoryPanic(fatal) = error else {
            panic!("FactoryPanic must remain typed, got {error:?}");
        };
        assert_eq!(fatal.code, -32603);
        assert_eq!(fatal.stage, "dispatch");
        assert_eq!(fatal.diagnostic["owner"], "rpc-fixture");

        let next = kit
            .parse_session(&Input::Spec(json!({
                "workspace_root": ".",
                "mode": "after-fatal"
            })))
            .expect_err("terminal kit state must refuse every later request locally");
        assert!(matches!(next, LiftPluginKitError::FatalFactoryPanic(_)));

        let frames = protocol_log(&log_path);
        assert_eq!(
            frames.len(),
            3,
            "fatal frame may not trigger retry or fallback: {frames:?}"
        );
        let pid = frames[0].split(':').next().expect("pid");
        assert_eq!(frames[0], format!("{pid}:initialize:none"));
        assert_eq!(frames[1], format!("{pid}:lift:control"));
        assert_eq!(frames[2], format!("{pid}:lift:fatal"));
        assert!(
            frames.iter().all(|frame| !frame.contains(":shutdown:")),
            "fatal teardown must kill, not send shutdown as recovery: {frames:?}"
        );
    }

    #[test]
    fn successful_control_twin_reuses_resident_and_returns_artifacts_normally() {
        let temp = tempfile::tempdir().expect("test tempdir");
        let log_path = temp.path().join("requests.log");
        let (_stub, command) = protocol_stub(&log_path);
        let kit = LiftPluginKit::new("python", command, None);

        for mode in ["control-one", "control-two"] {
            let session = kit
                .parse_session(&Input::Spec(json!({
                    "workspace_root": ".",
                    "mode": mode
                })))
                .expect("ordinary result remains reusable");
            assert_eq!(session.response()["kind"], "ir-document");
            assert_eq!(session.claim.artifacts.len(), 1);
        }

        let frames = protocol_log(&log_path);
        assert_eq!(
            frames.len(),
            3,
            "control requests should share one resident: {frames:?}"
        );
        let pid = frames[0].split(':').next().expect("pid");
        assert_eq!(frames[0], format!("{pid}:initialize:none"));
        assert_eq!(frames[1], format!("{pid}:lift:control-one"));
        assert_eq!(frames[2], format!("{pid}:lift:control-two"));
    }

    #[test]
    fn resident_rotates_only_after_bounded_successful_responses() {
        let temp = tempfile::tempdir().expect("test tempdir");
        let log_path = temp.path().join("requests.log");
        let (_stub, command) = protocol_stub(&log_path);
        let mut kit = LiftPluginKit::new("python", command, None);
        kit.resident_max_requests = 2;

        for request in 0..5 {
            let session = kit
                .parse_session(&Input::Spec(json!({
                    "workspace_root": ".",
                    "mode": format!("success-{request}")
                })))
                .expect("bounded resident generations preserve successful answers");
            assert_eq!(
                session.response(),
                &json!({"kind": "ir-document", "ir": []})
            );
        }

        let frames = protocol_log(&log_path);
        let initialize_pids: Vec<_> = frames
            .iter()
            .filter_map(|frame| {
                let (pid, rest) = frame.split_once(':')?;
                rest.starts_with("initialize:").then_some(pid)
            })
            .collect();
        let lift_pids: Vec<_> = frames
            .iter()
            .filter_map(|frame| {
                let (pid, rest) = frame.split_once(':')?;
                rest.starts_with("lift:").then_some(pid)
            })
            .collect();

        assert_eq!(
            initialize_pids.len(),
            3,
            "five successes at max=2 need three generations: {frames:?}"
        );
        assert_eq!(
            lift_pids.len(),
            5,
            "rotation may not replay or drop a request: {frames:?}"
        );
        assert_eq!(&lift_pids[0..2], &[initialize_pids[0], initialize_pids[0]]);
        assert_eq!(&lift_pids[2..4], &[initialize_pids[1], initialize_pids[1]]);
        assert_eq!(lift_pids[4], initialize_pids[2]);
    }
}
