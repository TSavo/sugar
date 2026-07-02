// SPDX-License-Identifier: Apache-2.0
//
// ra_daemon_client.rs: thin client for the resident rust-analyzer host inside
// the `sugar-linkerd` daemon.
//
// The implication lifter (`walk_rpc`) used to COLD-SPAWN rust-analyzer inside
// every mint, paying the ~260s workspace index each time. This client instead
// asks the persistent daemon, which keeps ONE warm rust-analyzer session per
// workspace root indexed once and reused across mints, fronted by a
// content-addressed per-file resolution cache (specs #1705/#1706/#1707). The
// first ever mint of a cold workspace waits once for the daemon's
// rust-analyzer readiness signal, then resolves from that indexed session. A
// later mint with unchanged files resolves from the cache with NO RA spawn.
//
// Refuse-floor (supra omnia rectum, spec §1.R2): if the daemon is unreachable,
// the spawn times out, or readiness fails, this client returns an EMPTY map. The
// caller leaves `callee_crate = None` and the call falls back to Tier 1/2a. It
// waits only on linkerd's LSP-backed readiness signal and NEVER guesses an edge.
//
// std-only and synchronous, mirroring `sugar-lsp-rust/src/daemon_client.rs`:
// the parent binary speaks line-framed NDJSON; no async runtime is needed.

use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value as Json};
use tracing::{debug, info, warn};

/// One position to resolve, in the daemon's wire shape.
#[derive(Debug, Clone)]
pub struct DaemonQuery {
    pub file: String,
    pub line: u32,
    pub col: u32,
}

/// One resolved position: the receiver-defining crate plus the best-effort
/// receiver-type stem (`option`/`result`/`slice`/...). The stem is what lets a
/// panic site key on the rust-std shim's disambiguated partial; `None` when the
/// crate was definite but the type was not disambiguable (the caller then keeps
/// the crate and refuses to disambiguate, never guesses).
#[derive(Debug, Clone)]
pub struct DaemonResolution {
    pub krate: String,
    pub type_stem: Option<String>,
    /// The resolved method's receiver/param mutability (source-audit datum):
    /// "mutating" | "refclean" | "unknown". Defaults to "unknown" (a cache hit,
    /// an older daemon, or a missing field) so the source-audit stays conservative.
    pub effect: String,
}

#[derive(Debug, Clone, Default)]
pub struct DaemonResolutionBatch {
    pub reachable: bool,
    pub ready: bool,
    pub resolutions: HashMap<(String, u32, u32), DaemonResolution>,
    pub refusal: Option<String>,
}

impl DaemonResolutionBatch {
    fn refuse(&mut self, reason: impl Into<String>) {
        self.ready = false;
        self.resolutions.clear();
        self.refusal = Some(reason.into());
    }
}

#[derive(Debug, Clone, Default)]
pub struct DaemonReadiness {
    pub ready: bool,
    pub phase: Option<String>,
    pub detail: Option<String>,
}

/// Ask the resident daemon to resolve a batch of method-call positions in
/// `workspace_root` to their receiver-defining crate AND receiver-type stem.
///
/// Returns a map from `(file, line, col)` to the resolution. Positions the
/// daemon refuses are simply ABSENT from the map: the caller treats absence as
/// refusal and falls back to the syntactic tiers. A daemon that is unreachable
/// or cannot reach readiness yields an empty map.
pub fn resolve_receiver_crates(
    workspace_root: &Path,
    queries: &[DaemonQuery],
) -> DaemonResolutionBatch {
    let mut batch = DaemonResolutionBatch::default();
    if queries.is_empty() {
        return batch;
    }

    let project_cid = project_cid_from_workspace(workspace_root);
    let socket_path = daemon_socket_path(&project_cid);

    let mut stream = match connect_or_spawn(&socket_path, &project_cid) {
        Ok(s) => s,
        Err(e) => {
            // Unreachable daemon is a refuse, not an error: the syntactic tiers
            // still produce a sound (if smaller) bridge set.
            batch.refuse(format!("connect/spawn sugar-linkerd: {e}"));
            warn!(
                socket = %socket_path.display(),
                error = %e,
                "ra-daemon: could not connect/spawn sugar-linkerd; refusing all \
                 method-call resolutions to the syntactic tiers"
            );
            return batch;
        }
    };
    batch.reachable = true;

    let timeout_ms = ready_timeout_ms();
    match request_readiness(&mut stream, workspace_root, timeout_ms) {
        Ok(readiness) if readiness.ready => {
            batch.ready = true;
            info!(
                phase = ?readiness.phase,
                detail = ?readiness.detail,
                "ra-daemon: rust-analyzer readiness gate passed"
            );
        }
        Ok(readiness) => {
            batch.refuse(format!(
                "readiness not passed: phase={:?} detail={:?}",
                readiness.phase, readiness.detail
            ));
            warn!(
                phase = ?readiness.phase,
                detail = ?readiness.detail,
                "ra-daemon: rust-analyzer readiness gate did not pass; refusing all method-call resolutions"
            );
            return batch;
        }
        Err(error) => {
            batch.refuse(error.clone());
            warn!(
                error = %error,
                "ra-daemon: rust-analyzer readiness RPC failed; refusing all method-call resolutions"
            );
            return batch;
        }
    }

    let q_json: Vec<Json> = queries
        .iter()
        .map(|q| json!({ "file": q.file, "line": q.line, "col": q.col }))
        .collect();

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "resolveReceiverCrate",
        "params": {
            "workspaceRoot": workspace_root.to_string_lossy(),
            "timeoutMs": timeout_ms,
            "queries": q_json,
        }
    });

    let resp = match send_one(&mut stream, &req) {
        Ok(r) => r,
        Err(e) => {
            batch.refuse(format!("resolveReceiverCrate transport: {e}"));
            warn!(error = %e, "ra-daemon: resolveReceiverCrate transport failed; refusing");
            return batch;
        }
    };

    if let Some(err_obj) = resp.get("error") {
        batch.refuse(format!(
            "resolveReceiverCrate returned RPC error: {err_obj}"
        ));
        warn!(error = %err_obj, "ra-daemon: daemon returned RPC error; refusing");
        return batch;
    }

    let (ready, resolutions) = match parse_resolve_response(&resp) {
        Ok(parsed) => parsed,
        Err(error) => {
            batch.refuse(format!("malformed resolveReceiverCrate response: {error}"));
            warn!(
                error = %error,
                "ra-daemon: malformed resolveReceiverCrate response; refusing whole batch"
            );
            return batch;
        }
    };
    let resolved_count = resolutions.len();

    if !ready && resolved_count == 0 {
        // Readiness passed, but RA still reported not-ready during resolution
        // and nothing was cache-resolved. Refuse rather than caching partial
        // answers or guessing edges.
        batch.refuse(
            "resolveReceiverCrate reported not-ready after readiness gate with no cached answers",
        );
        info!(
            queries = queries.len(),
            "ra-daemon: resolution returned not-ready after readiness gate; \
             refusing to the syntactic tiers"
        );
        return batch;
    }

    batch.ready = ready;
    batch.resolutions = resolutions;

    info!(
        ready,
        resolved = batch.resolutions.len(),
        queries = queries.len(),
        "ra-daemon: resolveReceiverCrate complete"
    );
    batch
}

fn request_readiness(
    stream: &mut UnixStream,
    workspace_root: &Path,
    timeout_ms: u64,
) -> Result<DaemonReadiness, String> {
    let req = json!({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "rustAnalyzerReady",
        "params": {
            "workspaceRoot": workspace_root.to_string_lossy(),
            "timeoutMs": timeout_ms,
        }
    });
    let resp = send_one(stream, &req).map_err(|e| format!("rustAnalyzerReady transport: {e}"))?;
    if let Some(error) = resp.get("error") {
        return Err(format!("rustAnalyzerReady returned RPC error: {error}"));
    }
    let result = required_field(&resp, "result", "rustAnalyzerReady response")?;
    Ok(DaemonReadiness {
        ready: required_bool_field(result, "ready", "rustAnalyzerReady.result")?,
        phase: optional_string_field(result, "phase", "rustAnalyzerReady.result")?,
        detail: optional_string_field(result, "detail", "rustAnalyzerReady.result")?,
    })
}

fn ready_timeout_ms() -> u64 {
    const DEFAULT_TIMEOUT_MS: u64 = 300_000;
    match std::env::var("SUGAR_ORACLE_READY_TIMEOUT_MS") {
        Ok(raw) => match raw.parse::<u64>() {
            Ok(value) if value > 0 => value,
            Ok(_) | Err(_) => DEFAULT_TIMEOUT_MS,
        },
        Err(_) => DEFAULT_TIMEOUT_MS,
    }
}

/// Parse a `"<file>:<line>:<col>"` position key back into its parts. The file
/// path itself may contain colons on exotic systems, so split from the RIGHT:
/// the last two colon-separated fields are line and col, the rest is the file.
fn parse_pos_key(key: &str) -> Result<(String, u32, u32), String> {
    let col_idx = key
        .rfind(':')
        .ok_or_else(|| "missing column separator".to_string())?;
    let (head, col_str) = key.split_at(col_idx);
    let col: u32 = col_str[1..]
        .parse()
        .map_err(|err| format!("invalid column {:?}: {err}", &col_str[1..]))?;
    let line_idx = head
        .rfind(':')
        .ok_or_else(|| "missing line separator".to_string())?;
    let (file, line_str) = head.split_at(line_idx);
    let line: u32 = line_str[1..]
        .parse()
        .map_err(|err| format!("invalid line {:?}: {err}", &line_str[1..]))?;
    if file.is_empty() {
        return Err("missing file path".to_string());
    }
    Ok((file.to_string(), line, col))
}

fn parse_resolve_response(
    resp: &Json,
) -> Result<(bool, HashMap<(String, u32, u32), DaemonResolution>), String> {
    let result = required_field(resp, "result", "resolveReceiverCrate response")?;
    let ready = required_bool_field(result, "ready", "resolveReceiverCrate.result")?;
    let resolved = required_object_field(result, "resolved", "resolveReceiverCrate.result")?;
    let mut resolutions = HashMap::new();
    for (key, val) in resolved {
        let (file, line, col) = parse_pos_key(key)
            .map_err(|err| format!("resolveReceiverCrate.result.resolved[{key:?}]: {err}"))?;
        let (krate, type_stem, effect) = parse_resolution_value(key, val)?;
        resolutions.insert(
            (file, line, col),
            DaemonResolution {
                krate,
                type_stem,
                effect,
            },
        );
    }
    Ok((ready, resolutions))
}

fn parse_resolution_value(
    key: &str,
    val: &Json,
) -> Result<(String, Option<String>, String), String> {
    let context = format!("resolveReceiverCrate.result.resolved[{key:?}]");
    match val {
        Json::String(krate) if !krate.is_empty() => {
            Ok((krate.to_string(), None, "unknown".to_string()))
        }
        Json::String(_) => Err(format!("{context}.crate must not be empty")),
        Json::Object(_) => {
            let krate = required_nonempty_string_field(val, "crate", &context)?.to_string();
            let type_stem = optional_string_field(val, "type", &context)?;
            let effect = match optional_string_field(val, "effect", &context)? {
                Some(effect) => effect,
                None => "unknown".to_string(),
            };
            Ok((krate, type_stem, effect))
        }
        other => Err(format!(
            "{context} must be object or string, got {}",
            json_kind(other)
        )),
    }
}

fn required_field<'a>(value: &'a Json, field: &str, context: &str) -> Result<&'a Json, String> {
    value
        .get(field)
        .ok_or_else(|| format!("{context}.{field} missing"))
}

fn required_bool_field(value: &Json, field: &str, context: &str) -> Result<bool, String> {
    match value.get(field) {
        Some(Json::Bool(v)) => Ok(*v),
        Some(other) => Err(format!(
            "{context}.{field} must be bool, got {}",
            json_kind(other)
        )),
        None => Err(format!("{context}.{field} missing")),
    }
}

fn required_object_field<'a>(
    value: &'a Json,
    field: &str,
    context: &str,
) -> Result<&'a serde_json::Map<String, Json>, String> {
    match value.get(field) {
        Some(Json::Object(map)) => Ok(map),
        Some(other) => Err(format!(
            "{context}.{field} must be object, got {}",
            json_kind(other)
        )),
        None => Err(format!("{context}.{field} missing")),
    }
}

fn required_nonempty_string_field<'a>(
    value: &'a Json,
    field: &str,
    context: &str,
) -> Result<&'a str, String> {
    match value.get(field) {
        Some(Json::String(s)) if !s.is_empty() => Ok(s.as_str()),
        Some(Json::String(_)) => Err(format!("{context}.{field} must not be empty")),
        Some(other) => Err(format!(
            "{context}.{field} must be string, got {}",
            json_kind(other)
        )),
        None => Err(format!("{context}.{field} missing")),
    }
}

fn optional_string_field(
    value: &Json,
    field: &str,
    context: &str,
) -> Result<Option<String>, String> {
    match value.get(field) {
        Some(Json::String(s)) => Ok(Some(s.to_string())),
        Some(Json::Null) | None => Ok(None),
        Some(other) => Err(format!(
            "{context}.{field} must be string or null, got {}",
            json_kind(other)
        )),
    }
}

fn json_kind(value: &Json) -> &'static str {
    match value {
        Json::Null => "null",
        Json::Bool(_) => "bool",
        Json::Number(_) => "number",
        Json::String(_) => "string",
        Json::Array(_) => "array",
        Json::Object(_) => "object",
    }
}

/// Deterministic project CID from the absolute workspace root, so two mints of
/// the SAME project share ONE warm daemon (the entire point of residency). We
/// canonicalize first so `.` / symlink variants of the same root collapse.
fn project_cid_from_workspace(workspace_root: &Path) -> String {
    let canonical =
        std::fs::canonicalize(workspace_root).unwrap_or_else(|_| workspace_root.to_path_buf());
    let mut h = std::collections::hash_map::DefaultHasher::new();
    canonical.to_string_lossy().hash(&mut h);
    // Prefix so it is visibly the RA-resolution daemon, distinct from any
    // linker-protocol daemon keyed by a different cid.
    format!("ra-{:016x}", h.finish())
}

/// Socket path for the RA-resolution daemon. Mirrors the linkerd default
/// (`${XDG_RUNTIME_DIR}/sugar/linkerd-<cid>.sock`) so a single daemon binary
/// serves it. An override is available for tests.
fn daemon_socket_path(project_cid: &str) -> PathBuf {
    if let Ok(p) = std::env::var("SUGAR_LINKERD_SOCKET") {
        if !p.is_empty() {
            return PathBuf::from(p);
        }
    }
    let base = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| std::env::temp_dir().to_string_lossy().into_owned());
    PathBuf::from(base)
        .join("sugar")
        .join(format!("linkerd-{project_cid}.sock"))
}

/// Connect to the daemon, spawning `sugar-linkerd` detached if not running.
/// Mirrors `sugar-lsp-rust/src/daemon_client.rs::connect_or_spawn`.
fn connect_or_spawn(socket_path: &Path, project_cid: &str) -> std::io::Result<UnixStream> {
    if let Ok(stream) = UnixStream::connect(socket_path) {
        return Ok(stream);
    }

    let snap_path = {
        let mut p = socket_path.to_path_buf();
        let file_name = p
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "linkerd".to_string());
        p.set_file_name(format!("{file_name}.snap"));
        p
    };

    if let Some(parent) = socket_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    // Inherit SUGAR_RESOLVE_ORACLE / SUGAR_RUST_ANALYZER so the daemon's
    // RA host honours the same opt-in as the cold path did.
    let binary = std::env::var("SUGAR_LINKERD_BIN").unwrap_or_else(|_| "sugar-linkerd".into());
    debug!(binary = %binary, socket = %socket_path.display(), "ra-daemon: spawning sugar-linkerd");
    // The daemon detaches its stdio. For diagnosis, SUGAR_LINKERD_LOG can
    // redirect the daemon's stderr to a file (otherwise it is discarded so the
    // detached daemon never writes onto the mint's JSON-RPC stdout).
    let stderr_sink = match std::env::var("SUGAR_LINKERD_LOG") {
        Ok(p) if !p.is_empty() => std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&p)
            .map(Stdio::from)
            .unwrap_or_else(|_| Stdio::null()),
        _ => Stdio::null(),
    };
    Command::new(&binary)
        .args([
            "--socket",
            &socket_path.to_string_lossy(),
            "--project-cid",
            project_cid,
            "--idle-timeout-ms",
            "300000",
            "--snapshot",
            &snap_path.to_string_lossy(),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(stderr_sink)
        .spawn()
        .map_err(|e| {
            std::io::Error::new(
                std::io::ErrorKind::Other,
                format!("failed to spawn {binary}: {e}"),
            )
        })?;

    // Poll for the socket (max 5s). RA itself indexes asynchronously inside the
    // daemon AFTER it binds, so binding is fast even on a cold workspace.
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        std::thread::sleep(Duration::from_millis(50));
        if let Ok(stream) = UnixStream::connect(socket_path) {
            return Ok(stream);
        }
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!(
                    "sugar-linkerd did not bind {} within 5s",
                    socket_path.display()
                ),
            ));
        }
    }
}

/// Send one JSON-RPC request line and read one response line.
fn send_one(stream: &mut UnixStream, req: &Json) -> std::io::Result<Json> {
    let line = serde_json::to_string(req).map_err(|e| {
        std::io::Error::new(std::io::ErrorKind::InvalidData, format!("json encode: {e}"))
    })?;
    writeln!(stream, "{line}")?;
    stream.flush()?;

    let mut reader = BufReader::new(stream.try_clone()?);
    let mut resp_line = String::new();
    let n = reader.read_line(&mut resp_line)?;
    if n == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::UnexpectedEof,
            "daemon closed connection without responding",
        ));
    }
    serde_json::from_str(resp_line.trim()).map_err(|e| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("json decode daemon response: {e}"),
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Mutex, OnceLock};
    use std::thread;

    static TEST_SOCKET_COUNTER: AtomicUsize = AtomicUsize::new(0);
    static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

    #[test]
    fn pos_key_roundtrips() {
        assert_eq!(
            parse_pos_key("/a/b/c.rs:12:7").unwrap(),
            ("/a/b/c.rs".to_string(), 12, 7)
        );
    }

    #[test]
    fn pos_key_tolerates_colon_in_path() {
        assert_eq!(
            parse_pos_key("/weird:dir/c.rs:3:0").unwrap(),
            ("/weird:dir/c.rs".to_string(), 3, 0)
        );
    }

    #[test]
    fn project_cid_is_stable_for_same_root() {
        let a = project_cid_from_workspace(Path::new("/tmp"));
        let b = project_cid_from_workspace(Path::new("/tmp"));
        assert_eq!(a, b);
        assert!(a.starts_with("ra-"));
    }

    #[test]
    fn resolve_response_missing_ready_refuses_whole_batch() {
        let key = "/tmp/ra-client-missing-ready.rs:0:0";
        let batch = resolve_with_fake_daemon(
            json!({
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "resolved": {
                        key: { "crate": "alloc", "type": "vec", "effect": "mutating" }
                    }
                }
            }),
            &[DaemonQuery {
                file: "/tmp/ra-client-missing-ready.rs".to_string(),
                line: 0,
                col: 0,
            }],
        );

        assert!(batch.reachable);
        assert!(
            !batch.ready,
            "malformed daemon response must not preserve a ready=true observation"
        );
        assert!(
            batch.resolutions.is_empty(),
            "missing ready must refuse the whole resolution batch, not use content"
        );
    }

    #[test]
    fn resolve_response_bad_position_key_refuses_whole_batch() {
        let good_key = "/tmp/ra-client-good.rs:0:0";
        let batch = resolve_with_fake_daemon(
            json!({
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "ready": true,
                    "resolved": {
                        good_key: { "crate": "alloc", "type": "vec", "effect": "mutating" },
                        "not-a-position-key": { "crate": "core", "type": "option" }
                    }
                }
            }),
            &[DaemonQuery {
                file: "/tmp/ra-client-good.rs".to_string(),
                line: 0,
                col: 0,
            }],
        );

        assert!(batch.reachable);
        assert!(
            !batch.ready,
            "malformed daemon map keys must clear the ready observation"
        );
        assert!(
            batch.resolutions.is_empty(),
            "one malformed entry must refuse the whole batch, not keep partial answers"
        );
    }

    fn resolve_with_fake_daemon(
        resolve_response: Json,
        queries: &[DaemonQuery],
    ) -> DaemonResolutionBatch {
        let env_lock = ENV_LOCK.get_or_init(|| Mutex::new(())).lock().unwrap();
        let counter = TEST_SOCKET_COUNTER.fetch_add(1, Ordering::Relaxed);
        let test_dir = std::env::temp_dir().join(format!(
            "sugar-ra-daemon-client-{}-{counter}",
            std::process::id()
        ));
        std::fs::create_dir_all(&test_dir).unwrap();
        let socket_path = test_dir.join("linkerd.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();

        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            writeln!(
                stream,
                "{}",
                serde_json::to_string(&json!({
                    "jsonrpc": "2.0",
                    "id": 0,
                    "result": { "ready": true, "phase": "ready", "detail": "test" }
                }))
                .unwrap()
            )
            .unwrap();
            line.clear();
            reader.read_line(&mut line).unwrap();
            writeln!(
                stream,
                "{}",
                serde_json::to_string(&resolve_response).unwrap()
            )
            .unwrap();
        });

        let previous_socket = std::env::var_os("SUGAR_LINKERD_SOCKET");
        std::env::set_var("SUGAR_LINKERD_SOCKET", &socket_path);
        let batch = resolve_receiver_crates(Path::new("/tmp"), queries);
        match previous_socket {
            Some(value) => std::env::set_var("SUGAR_LINKERD_SOCKET", value),
            None => std::env::remove_var("SUGAR_LINKERD_SOCKET"),
        }
        handle.join().unwrap();
        drop(env_lock);
        let _ = std::fs::remove_dir_all(&test_dir);
        batch
    }
}
