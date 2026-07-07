// SPDX-License-Identifier: MIT OR Apache-2.0
//
// server.rs: JSON-RPC NDJSON dispatch loop.
//
// Binds a Unix domain socket, accepts clients, dispatches NDJSON
// JSON-RPC 2.0 messages to method handlers, and manages daemon lifecycle:
//
//   - Socket permissions: 0600 (owner-only) per R2.
//   - Idle timeout: shuts down after `idle_timeout` with zero clients per R4.
//     On test builds the caller supplies a short timeout.
//   - Snapshot persistence: writes cache to XDG_CACHE_HOME on shutdown per R14.
//   - Multi-client: concurrent connections share one `Arc<Mutex<ProjectState>>`.
//     The mutex serialises all link() calls (R8's conformance item 3).
//
// UID rejection (R2): On Linux and macOS we read the peer's UID via
// `UnixStream::peer_cred()` and disconnect if it doesn't match `getuid()`.
// On other platforms (Windows, BSD without peer_cred) we skip the check
// and document the gap.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::{Mutex, Notify};
use tracing::{debug, error, info, warn};

use crate::methods::{
    handle_flush_cache, handle_get_diagnostics, handle_parse_file, handle_project_status,
    handle_resolve_receiver_crate, handle_rust_analyzer_ready, rpc_error, shutdown_response,
    ERR_METHOD_NOT_FOUND,
};
use crate::ra_host::RaHost;
use crate::resolve_cache::ResolveCache;
use crate::snapshot;
use crate::state::ProjectState;

/// Configuration for the daemon server.
pub struct ServerConfig {
    /// Path of the Unix domain socket to bind.
    pub socket_path: PathBuf,
    /// Path to write the snapshot on shutdown.
    pub snapshot_path: PathBuf,
    /// Idle timeout: shut down if zero clients for this duration.
    pub idle_timeout: Duration,
    /// LRU cache capacity (R12).
    pub cache_cap: usize,
    /// Workspace root used to discover the solver `SolversConfig` (the same
    /// discovery `sugar prove` uses).
    pub project_root: PathBuf,
    /// When false, force the pure-`link()` structural mode even if a solver is
    /// resolvable (`--no-solvers`). Used to exercise the honest degraded mode.
    pub solvers_enabled: bool,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            socket_path: default_socket_path("default"),
            snapshot_path: default_snapshot_path("default"),
            idle_timeout: Duration::from_secs(300), // 5 min per R4
            cache_cap: 1024,
            project_root: std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")),
            solvers_enabled: true,
        }
    }
}

/// Build the solver context the daemon links with, mirroring the CLI's
/// `build_plan_and_registry`: the kit-declared `SolversConfig` wins verbatim;
/// otherwise fall back to a default single-z3 registry when `z3` is on PATH.
/// Returns `None` (structural / degraded mode) when solvers are disabled or no
/// solver is resolvable. z3 presence is detected the same way `sugar prove`
/// relies on it — the `z3` binary reachable on PATH.
fn build_solver_context(config: &ServerConfig) -> Option<crate::state::SolverContext> {
    use sugar_linker::solver_api::{registry, SolverPlan, SolverSeat, SolversConfig};

    if !config.solvers_enabled {
        info!("solvers disabled (--no-solvers): running in structural (degraded) discharge mode");
        return None;
    }

    // (1) Kit author's declared solver config wins, verbatim — identical to the
    // CLI verify/prove path.
    if let Ok(Some(sc)) = SolversConfig::load(&config.project_root) {
        let registry = registry::build(&sc);
        let plan = SolverPlan::from_config(&sc);
        let seats: Vec<String> = registry.keys().map(|s| format!("{s:?}")).collect();
        info!(seats = ?seats, "semantic discharge: built solver registry from workspace SolversConfig");
        return Some(crate::state::SolverContext {
            registry,
            plan,
            seats,
        });
    }

    // (2) No kit config: default single-z3, but only if z3 is actually on PATH
    // so the reported mode is honest (an unreachable solver would surface every
    // obligation as undecidable — a silent structural mode wearing a semantic
    // label).
    if let Some(z3_path) = which_on_path("z3") {
        let registry = registry::build_default_z3(&z3_path.to_string_lossy());
        let plan = SolverPlan::Single(SolverSeat::Z3);
        info!(z3 = %z3_path.display(), "semantic discharge: default single-z3 registry (no SolversConfig found)");
        return Some(crate::state::SolverContext {
            registry,
            plan,
            seats: vec!["z3".to_string()],
        });
    }

    info!("no solver resolvable (no SolversConfig, no z3 on PATH): structural (degraded) mode");
    None
}

/// Minimal PATH scan for an executable, so we can report an HONEST capability
/// (z3 present vs absent) without a new dependency.
fn which_on_path(bin: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let candidate = dir.join(bin);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Compute the socket path for a given projectCid per R1.
pub fn default_socket_path(project_cid: &str) -> PathBuf {
    let base = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| std::env::temp_dir().to_string_lossy().into_owned());
    PathBuf::from(base)
        .join("sugar")
        .join(format!("linkerd-{project_cid}.sock"))
}

/// Compute the snapshot path for a given projectCid per R14.
pub fn default_snapshot_path(project_cid: &str) -> PathBuf {
    let base = std::env::var("XDG_CACHE_HOME").unwrap_or_else(|_| dirs_next_cache_home());
    PathBuf::from(base)
        .join("sugar")
        .join("linkerd")
        .join(project_cid)
        .join("snapshot.bin")
}

/// Path to the resolve-cache sidecar, derived from the snapshot path: the
/// snapshot's directory with file name `resolve-cache.json`. Deriving it from
/// the same per-project snapshot path guarantees that two daemons (or two
/// successive daemon processes) for the same project share one cache file.
fn resolve_cache_sidecar_path(snapshot_path: &std::path::Path) -> PathBuf {
    let mut p = snapshot_path.to_path_buf();
    p.set_file_name("resolve-cache.json");
    p
}

/// Load the persisted resolve cache, or start empty. A cache is never a source
/// of truth: an unreadable/missing file simply means a cold cache (every lookup
/// misses and re-asks rust-analyzer), which is always correct.
fn load_resolve_cache(path: &std::path::Path) -> ResolveCache {
    match std::fs::read(path) {
        Ok(bytes) => {
            let cache = ResolveCache::from_bytes(&bytes);
            info!(
                path = %path.display(),
                entries = cache.len(),
                "resolve-cache: loaded content-addressed callee-resolution cache"
            );
            cache
        }
        Err(_) => {
            info!(
                path = %path.display(),
                "resolve-cache: no cache file; starting cold (cache misses re-ask rust-analyzer)"
            );
            ResolveCache::new()
        }
    }
}

fn dirs_next_cache_home() -> String {
    // Fallback: ~/.cache on Unix, %LOCALAPPDATA% on Windows.
    if let Some(home) = std::env::var_os("HOME") {
        let mut p = PathBuf::from(home);
        p.push(".cache");
        return p.to_string_lossy().into_owned();
    }
    std::env::temp_dir().to_string_lossy().into_owned()
}

/// Run the daemon with the given config.
///
/// Loads snapshot if available, binds socket, accepts connections,
/// and shuts down cleanly on idle timeout or `shutdown` RPC.
pub async fn run(config: ServerConfig) -> anyhow::Result<()> {
    // Build the solver context once at startup (semantic vs structural mode).
    let solver_ctx = build_solver_context(&config);

    // Load snapshot if available (R14).
    let mut base = match snapshot::load(&config.snapshot_path) {
        Ok(Some(s)) => {
            info!(
                "warm-start: loaded snapshot from {}",
                config.snapshot_path.display()
            );
            s
        }
        Ok(None) => {
            info!("cold-start: no snapshot found");
            ProjectState::new(config.cache_cap)
        }
        Err(e) => {
            warn!("snapshot load failed ({e}); starting cold");
            ProjectState::new(config.cache_cap)
        }
    };
    // Attach the solver wiring (re-derives any restored streams under the mode).
    base.attach_solvers(solver_ctx);
    let state = Arc::new(Mutex::new(base));

    // Resident rust-analyzer host: one warm session per workspace root, shared
    // across all clients. Created empty; sessions spawn lazily on the first
    // rustAnalyzerReady or resolveReceiverCrate for a workspace.
    let ra_host = Arc::new(RaHost::new());

    // Content-addressed callee-resolution cache (#1705/#1706), persisted in a
    // sidecar next to the snapshot so a FRESH daemon process hits the cache and
    // skips rust-analyzer entirely on unchanged inputs.
    let resolve_cache_path = resolve_cache_sidecar_path(&config.snapshot_path);
    let resolve_cache = Arc::new(Mutex::new(load_resolve_cache(&resolve_cache_path)));

    // Remove stale socket if present.
    let _ = std::fs::remove_file(&config.socket_path);

    // Create parent directories.
    if let Some(parent) = config.socket_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    // Set umask so the socket is created 0600.
    // We do this by setting the socket perms after bind on platforms
    // where umask manipulation is undesirable.
    let listener = UnixListener::bind(&config.socket_path)?;

    // Set socket file permissions to 0600 (R2).
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&config.socket_path, std::fs::Permissions::from_mode(0o600))?;
    }

    info!("listening on {}", config.socket_path.display());

    let client_count = Arc::new(AtomicUsize::new(0));
    let shutdown_notify = Arc::new(Notify::new());

    // Idle-timeout watcher task.
    {
        let client_count = client_count.clone();
        let shutdown_notify = shutdown_notify.clone();
        let idle_timeout = config.idle_timeout;
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(idle_timeout).await;
                if client_count.load(Ordering::SeqCst) == 0 {
                    info!("idle timeout: shutting down");
                    shutdown_notify.notify_one();
                    return;
                }
            }
        });
    }

    let snapshot_path = config.snapshot_path.clone();
    let socket_path = config.socket_path.clone();

    loop {
        tokio::select! {
            accept_result = listener.accept() => {
                match accept_result {
                    Ok((stream, _addr)) => {
                        // Enforce owner-only connection (R2, R16).
                        #[cfg(any(target_os = "linux", target_os = "macos"))]
                        {
                            match stream.peer_cred() {
                                Ok(cred) if cred.uid() != unsafe { libc::getuid() } => {
                                    warn!("rejected connection from uid {}", cred.uid());
                                    continue;
                                }
                                Err(e) => {
                                    warn!("peer_cred() failed: {e}; rejecting connection");
                                    continue;
                                }
                                Ok(_) => {} // same uid: allow
                            }
                        }

                        let state = state.clone();
                        let client_count = client_count.clone();
                        let shutdown_notify = shutdown_notify.clone();
                        let snapshot_path = snapshot_path.clone();
                        let socket_path = socket_path.clone();
                        let ra_host = ra_host.clone();
                        let resolve_cache = resolve_cache.clone();
                        let resolve_cache_path = resolve_cache_path.clone();

                        client_count.fetch_add(1, Ordering::SeqCst);
                        tokio::spawn(async move {
                            handle_client(
                                stream,
                                state,
                                shutdown_notify,
                                snapshot_path,
                                socket_path,
                                ra_host,
                                resolve_cache,
                                resolve_cache_path,
                            )
                            .await;
                            client_count.fetch_sub(1, Ordering::SeqCst);
                        });
                    }
                    Err(e) => {
                        error!("accept error: {e}");
                    }
                }
            }
            _ = shutdown_notify.notified() => {
                info!("shutdown signal received: writing snapshot and exiting");
                {
                    let st = state.lock().await;
                    if let Err(e) = snapshot::save(&config.snapshot_path, &st) {
                        warn!("snapshot write failed: {e}");
                    }
                }
                // Remove socket file.
                let _ = std::fs::remove_file(&config.socket_path);
                return Ok(());
            }
        }
    }
}

/// Handle a single client connection: read NDJSON requests, dispatch, write responses.
#[allow(clippy::too_many_arguments)]
async fn handle_client(
    stream: UnixStream,
    state: Arc<Mutex<ProjectState>>,
    shutdown_notify: Arc<Notify>,
    snapshot_path: PathBuf,
    _socket_path: PathBuf,
    ra_host: Arc<RaHost>,
    resolve_cache: Arc<Mutex<ResolveCache>>,
    resolve_cache_path: PathBuf,
) {
    let (reader_half, mut writer_half) = stream.into_split();
    let mut lines = BufReader::new(reader_half).lines();

    while let Ok(Some(line)) = lines.next_line().await {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let request: Json = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                let err_resp = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": null,
                    "error": { "code": -32700, "message": format!("parse error: {e}") }
                });
                let _ = write_response(&mut writer_half, &err_resp).await;
                continue;
            }
        };

        let id = request.get("id").cloned().unwrap_or(Json::Null);
        let method = request
            .get("method")
            .and_then(|m| m.as_str())
            .unwrap_or("")
            .to_string();
        let params = request
            .get("params")
            .cloned()
            .unwrap_or(serde_json::json!({}));

        debug!("method={method} id={id}");

        let response = match method.as_str() {
            "parseFile" => handle_parse_file(state.clone(), &params, &id).await,
            "getDiagnostics" => handle_get_diagnostics(state.clone(), &params, &id).await,
            "projectStatus" => handle_project_status(state.clone(), &params, &id).await,
            "rustAnalyzerReady" => handle_rust_analyzer_ready(ra_host.clone(), &params, &id).await,
            "flushCache" => handle_flush_cache(state.clone(), &params, &id).await,
            "resolveReceiverCrate" => {
                handle_resolve_receiver_crate(
                    ra_host.clone(),
                    resolve_cache.clone(),
                    resolve_cache_path.clone(),
                    &params,
                    &id,
                )
                .await
            }
            "shutdown" => {
                // Write snapshot, then signal the accept loop to exit.
                {
                    let st = state.lock().await;
                    if let Err(e) = snapshot::save(&snapshot_path, &st) {
                        warn!("snapshot write on shutdown: {e}");
                    }
                }
                let resp = shutdown_response(&id);
                let _ = write_response(&mut writer_half, &resp).await;
                shutdown_notify.notify_one();
                return;
            }
            _ => rpc_error(
                ERR_METHOD_NOT_FOUND,
                &format!("method not found: {method}"),
                &id,
            ),
        };

        if let Err(e) = write_response(&mut writer_half, &response).await {
            warn!("write response error: {e}");
            return;
        }
    }
}

async fn write_response(
    writer: &mut tokio::net::unix::OwnedWriteHalf,
    value: &Json,
) -> std::io::Result<()> {
    let mut bytes = serde_json::to_vec(value).unwrap_or_default();
    bytes.push(b'\n');
    writer.write_all(&bytes).await
}

// Re-export Json for server.rs-internal use.
use serde_json::Value as Json;

// -------------------------------------------------------------------
// Convenience re-exports used by tests.
// -------------------------------------------------------------------

#[cfg(unix)]
extern crate libc;
