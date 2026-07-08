// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use sugar_ir_types::{IrFormula, IrTerm, Sort};
use sugar_walk::strip_realize_sidecar_from_lift_term;
use thiserror::Error;
use tracing::info;

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
                Err(ResidentDispatchError::Fatal(e)) => return Err(e),
                Err(ResidentDispatchError::Retry) => {
                    // Resident connection died mid-flight (broken pipe,
                    // process exited, etc). Fall through to a one-shot
                    // spawn for THIS request so the caller still gets an
                    // answer; the pool slot was already evicted by
                    // `dispatch_resident` and will be respawned next call.
                }
            }
        }

        let (initialize_response, response, mut child, mut stdin, _reader) =
            self.spawn_and_run_once(lift_params)?;
        let shutdown_req = json!({"jsonrpc": "2.0", "id": 3, "method": "shutdown"});
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

    /// Spawn a fresh child, run exactly one `initialize` + one lift call
    /// (using request ids 1/2, matching the historical one-shot protocol),
    /// and return the live child + its stdin/stdout handles so the caller
    /// decides whether to `shutdown` it (one-shot path) or keep it resident
    /// (pool path, which keeps `reader`/`stdin` alive for further requests).
    fn spawn_and_run_once(
        &self,
        lift_params: &Value,
    ) -> Result<
        (
            Value,
            Value,
            Child,
            ChildStdin,
            BufReader<std::process::ChildStdout>,
        ),
        LiftPluginKitError,
    > {
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

        Ok((initialize_response, response, child, stdin, reader))
    }

    /// Key identifying a resident slot: the exact command + working dir.
    /// Two `LiftPluginKit`s with the same command/cwd share one resident
    /// process (e.g. repeated mints of the same project/kit), matching the
    /// mission's "keyed by project root + kit" requirement.
    fn resident_key(&self) -> String {
        let mut key = self.command.join("\u{1f}");
        if let Some(dir) = &self.working_dir {
            key.push('\u{1e}');
            key.push_str(&dir.display().to_string());
        }
        key
    }

    /// Try to serve `lift_params` from a resident (already-warm) child.
    /// Spawns one on first use for this key, keyed by command+cwd, and
    /// keeps it alive across calls so `import pandas` (or any equally
    /// heavy one-time interpreter/module cost) is paid exactly once per
    /// process, not once per mint.
    ///
    /// STALENESS RULE (named explicitly, not assumed): a resident is
    /// restarted if it is older than `SUGAR_LIFT_RESIDENT_MAX_AGE_SECS`
    /// (default 30 minutes) -- long enough that a normal edit/save/mint
    /// cadence never pays the restart cost, short enough that a stale
    /// `pip install` / vendor env change during a long dev session is
    /// bounded, not permanent. The CONSUMER SOURCE is never cached here:
    /// every call sends a fresh `lift` request; the plugin process reads
    /// the file from disk each time (this pool caches the warm
    /// PROCESS/IMPORT, never the file content).
    fn dispatch_resident(
        &self,
        lift_params: &Value,
    ) -> Result<(Value, Value), ResidentDispatchError> {
        let key = self.resident_key();
        let pool = resident_pool();
        let mut guard = pool
            .lock()
            .map_err(|_| ResidentDispatchError::Fatal(LiftPluginKitError::Failed(
                "resident lifter pool poisoned".to_string(),
            )))?;

        let max_age = resident_max_age();
        let needs_fresh = match guard.get(&key) {
            None => true,
            Some(entry) => entry.started_at.elapsed() > max_age,
        };
        if needs_fresh {
            if let Some(mut old) = guard.remove(&key) {
                old.shutdown_best_effort();
            }
            let (initialize_response, child, stdin, reader, first_response) = self
                .spawn_resident(lift_params)
                .map_err(ResidentDispatchError::Fatal)?;
            guard.insert(
                key.clone(),
                ResidentLifter {
                    child,
                    stdin,
                    reader,
                    next_id: 3, // 1=initialize, 2=first lift already consumed below
                    started_at: Instant::now(),
                    initialize_response,
                    first_lift_response: Some(first_response),
                },
            );
        }

        let entry = guard.get_mut(&key).expect("just inserted or already present");
        let initialize_response = entry.initialize_response.clone();

        // On a freshly spawned resident, `spawn_resident` already performed
        // request id=2's lift as part of establishing the process (mirrors
        // the one-shot protocol exactly for the FIRST call), so skip
        // re-sending it here.
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
        if let Err(error) = writeln!(entry.stdin, "{lift_req}") {
            guard.remove(&key);
            return Err(ResidentDispatchError::retry_after(format!(
                "write lift request to resident: {error}"
            )));
        }
        match read_response(&mut entry.reader, id) {
            Ok(response) => Ok((initialize_response, response)),
            Err(error) => {
                // Resident died or desynced mid-protocol: evict it so the
                // NEXT call spawns fresh, and answer THIS call via one-shot.
                guard.remove(&key);
                Err(ResidentDispatchError::retry_after(error.to_string()))
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
    ) -> Result<
        (
            Value,
            Child,
            ChildStdin,
            BufReader<std::process::ChildStdout>,
            Value,
        ),
        LiftPluginKitError,
    > {
        let (initialize_response, first_response, child, stdin, reader) =
            self.spawn_and_run_once(lift_params)?;
        Ok((initialize_response, child, stdin, reader, first_response))
    }
}

/// One warm lift-plugin process kept alive across `dispatch` calls.
struct ResidentLifter {
    child: Child,
    stdin: ChildStdin,
    reader: BufReader<std::process::ChildStdout>,
    next_id: i64,
    started_at: Instant,
    initialize_response: Value,
    /// The first `lift` response, stashed at spawn time (spawning already
    /// drives one full `initialize`+`lift` round trip identical to the
    /// historical one-shot protocol); consumed by the first
    /// `dispatch_resident` call against a freshly (re)spawned entry.
    first_lift_response: Option<Value>,
}

impl ResidentLifter {
    /// Best-effort graceful shutdown of a resident being evicted (stale or
    /// replaced). Never blocks the caller on a hung process: errors here
    /// are swallowed, the entry is being dropped regardless.
    fn shutdown_best_effort(&mut self) {
        let shutdown_req = json!({"jsonrpc": "2.0", "id": 0, "method": "shutdown"});
        let _ = writeln!(self.stdin, "{shutdown_req}");
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for ResidentLifter {
    fn drop(&mut self) {
        self.shutdown_best_effort();
    }
}

/// Process-wide resident lifter pool, keyed by `LiftPluginKit::resident_key`
/// (command + working dir). One entry per (project, kit) pair, matching the
/// mission's "keyed by project root + kit" requirement -- multiple projects
/// or multiple distinct lift kits never share a resident process.
fn resident_pool() -> &'static Mutex<HashMap<String, ResidentLifter>> {
    static POOL: OnceLock<Mutex<HashMap<String, ResidentLifter>>> = OnceLock::new();
    POOL.get_or_init(|| Mutex::new(HashMap::new()))
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

/// Staleness bound: how long a resident process may serve requests before
/// being restarted. Default 30 minutes, overridable via
/// `SUGAR_LIFT_RESIDENT_MAX_AGE_SECS`. This is the named staleness rule
/// (mission requirement): the resident caches the warm IMPORT/process, never
/// the consumer source (each `lift` call re-reads the file from disk), so
/// the only staleness risk is an environment change (e.g. `pip install`)
/// made *after* the process started. Bounding the process age caps how long
/// such a change can go unpicked-up without requiring an explicit restart.
fn resident_max_age() -> Duration {
    std::env::var("SUGAR_LIFT_RESIDENT_MAX_AGE_SECS")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .map(Duration::from_secs)
        .unwrap_or(Duration::from_secs(30 * 60))
}

/// Outcome of a resident-path dispatch attempt.
enum ResidentDispatchError {
    /// A real failure the caller should propagate (e.g. binary missing).
    Fatal(LiftPluginKitError),
    /// The resident connection died mid-flight; already evicted from the
    /// pool. The caller should retry via a one-shot spawn for this request.
    Retry,
}

impl ResidentDispatchError {
    fn retry_after(reason: String) -> Self {
        info!(reason, "resident lifter connection lost, evicting and retrying one-shot");
        Self::Retry
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
