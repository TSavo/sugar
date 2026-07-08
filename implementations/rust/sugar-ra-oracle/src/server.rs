// SPDX-License-Identifier: MIT OR Apache-2.0
//
// server.rs: JSON-RPC NDJSON dispatch loop for the rust-analyzer oracle.
//
// A trimmed sibling of sugar-linkerd's server.rs (daemon-1 extraction): binds
// the SAME kind of Unix domain socket, speaks the SAME NDJSON JSON-RPC 2.0
// framing, and answers ONLY the two RPCs the Rust lift pipeline's
// `ra_daemon_client` needs:
//
//   rustAnalyzerReady     : resident RA readiness gate.
//   resolveReceiverCrate  : cache-fronted callee-crate resolution.
//   shutdown              : (not called by ra_daemon_client today, kept for
//                            operator/test convenience -- no snapshot to
//                            write, since this crate carries no editor state)
//
// Socket permissions (0600, owner-only) and idle-timeout shutdown mirror
// sugar-linkerd's R2/R4 so an operator sees identical daemon lifecycle
// behavior regardless of which binary is serving the oracle.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::{Mutex, Notify};
use tracing::{debug, error, info, warn};

use crate::methods::{
    handle_resolve_receiver_crate, handle_rust_analyzer_ready, rpc_error, rpc_result,
};
use crate::ra_host::RaHost;
use crate::resolve_cache::ResolveCache;

const ERR_METHOD_NOT_FOUND: i64 = -32601;

/// Configuration for the oracle server. Mirrors the subset of
/// sugar-linkerd's `ServerConfig` this oracle actually needs: the socket +
/// snapshot paths and the idle timeout. `project_cid`/`--project-root` and
/// solver wiring are editor-prove concerns and stay behind in sugar-linkerd.
pub struct ServerConfig {
    /// Path of the Unix domain socket to bind.
    pub socket_path: PathBuf,
    /// Path used to derive the resolve-cache sidecar (same-directory
    /// `resolve-cache.json`), so a fresh oracle process for the same project
    /// shares its cache with the previous one. Named `snapshot_path` (not
    /// `cache_path`) to keep the CLI flag identical to sugar-linkerd's
    /// (`--snapshot`), which is what `ra_daemon_client::connect_or_spawn`
    /// already passes.
    pub snapshot_path: PathBuf,
    /// Idle timeout: shut down if zero clients for this duration.
    pub idle_timeout: Duration,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            socket_path: default_socket_path("default"),
            snapshot_path: default_snapshot_path("default"),
            idle_timeout: Duration::from_secs(300), // 5 min, mirrors linkerd R4
        }
    }
}

/// Compute the socket path for a given projectCid. Identical formula to
/// The socket formula matches what sugar-walk::ra_daemon_client probes
/// (`ra-oracle-<cid>.sock`) so a manually started oracle and (while it
/// still exists) editor daemon do not collide on one socket namespace only by
/// accident of a shared default -- callers key ordinarily by their own
/// project_cid prefix (`ra_daemon_client` uses an `ra-`-prefixed cid).
pub fn default_socket_path(project_cid: &str) -> PathBuf {
    let base = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| std::env::temp_dir().to_string_lossy().into_owned());
    PathBuf::from(base)
        .join("sugar")
        .join(format!("ra-oracle-{project_cid}.sock"))
}

/// Compute the snapshot path for a given projectCid. Identical formula to
/// sugar-linkerd's `default_snapshot_path`.
pub fn default_snapshot_path(project_cid: &str) -> PathBuf {
    let base = std::env::var("XDG_CACHE_HOME").unwrap_or_else(|_| dirs_next_cache_home());
    PathBuf::from(base)
        .join("sugar")
        .join("ra-oracle")
        .join(project_cid)
        .join("snapshot.bin")
}

fn dirs_next_cache_home() -> String {
    if let Some(home) = std::env::var_os("HOME") {
        let mut p = PathBuf::from(home);
        p.push(".cache");
        return p.to_string_lossy().into_owned();
    }
    std::env::temp_dir().to_string_lossy().into_owned()
}

/// Path to the resolve-cache sidecar, derived from the snapshot path: the
/// snapshot's directory with file name `resolve-cache.json`. Deriving it from
/// the same per-project snapshot path guarantees that two oracle processes (or
/// an oracle process and a legacy linkerd daemon) for the same project share
/// one cache file.
fn resolve_cache_sidecar_path(snapshot_path: &std::path::Path) -> PathBuf {
    let mut p = snapshot_path.to_path_buf();
    p.set_file_name("resolve-cache.json");
    p
}

/// Load the persisted resolve cache, or start empty. A cache is never a
/// source of truth: an unreadable/missing file simply means a cold cache
/// (every lookup misses and re-asks rust-analyzer), which is always correct.
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

/// Run the oracle server with the given config. Binds the socket, accepts
/// connections, and shuts down cleanly on idle timeout or `shutdown` RPC.
pub async fn run(config: ServerConfig) -> anyhow::Result<()> {
    // Resident rust-analyzer host: one warm session per workspace root, shared
    // across all clients. Created empty; sessions spawn lazily on the first
    // rustAnalyzerReady or resolveReceiverCrate for a workspace.
    let ra_host = Arc::new(RaHost::new());

    // Content-addressed callee-resolution cache (#1705/#1706), persisted in a
    // sidecar next to the snapshot path so a FRESH oracle process hits the
    // cache and skips rust-analyzer entirely on unchanged inputs.
    let resolve_cache_path = resolve_cache_sidecar_path(&config.snapshot_path);
    let resolve_cache = Arc::new(Mutex::new(load_resolve_cache(&resolve_cache_path)));

    // Remove stale socket if present.
    let _ = std::fs::remove_file(&config.socket_path);

    if let Some(parent) = config.socket_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let listener = UnixListener::bind(&config.socket_path)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&config.socket_path, std::fs::Permissions::from_mode(0o600))?;
    }

    info!("sugar-ra-oracle listening on {}", config.socket_path.display());

    let client_count = Arc::new(AtomicUsize::new(0));
    let shutdown_notify = Arc::new(Notify::new());

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

    let socket_path = config.socket_path.clone();

    loop {
        tokio::select! {
            accept_result = listener.accept() => {
                match accept_result {
                    Ok((stream, _addr)) => {
                        // Enforce owner-only connection, mirroring linkerd's R2/R16.
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
                                Ok(_) => {}
                            }
                        }

                        let client_count = client_count.clone();
                        let shutdown_notify = shutdown_notify.clone();
                        let ra_host = ra_host.clone();
                        let resolve_cache = resolve_cache.clone();
                        let resolve_cache_path = resolve_cache_path.clone();

                        client_count.fetch_add(1, Ordering::SeqCst);
                        tokio::spawn(async move {
                            handle_client(
                                stream,
                                shutdown_notify,
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
                info!("shutdown signal received: exiting");
                let _ = std::fs::remove_file(&socket_path);
                return Ok(());
            }
        }
    }
}

/// Handle a single client connection: read NDJSON requests, dispatch, write responses.
async fn handle_client(
    stream: UnixStream,
    shutdown_notify: Arc<Notify>,
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
            "rustAnalyzerReady" => handle_rust_analyzer_ready(ra_host.clone(), &params, &id).await,
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
                let resp = rpc_result(Json::Null, &id);
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

use serde_json::Value as Json;

#[cfg(unix)]
extern crate libc;
