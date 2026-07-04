// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-linkerd: long-running JSON-RPC daemon for the Sugar
// linker, implementing spec `protocol/specs/2026-05-04-linker-daemon-protocol.md`.
//
// Usage:
//   sugar-linkerd --project-cid <cid>
//                    [--socket <path>]
//                    [--snapshot <path>]
//                    [--idle-timeout-ms <ms>]
//                    [--cache-cap <n>]
//
// Spec reference:
//   R1:  socket at ${XDG_RUNTIME_DIR}/sugar/linkerd-<projectCid>.sock
//   R2:  0600 permissions; reject non-owner UIDs.
//   R3:  NDJSON encoding, one JSON-RPC 2.0 message per line.
//   R4:  idle timeout 5 min; warm-start from snapshot.
//   R5-R9: five RPC methods.
//   R12-R14: LRU cache + snapshot persistence.
//   R15: one daemon per projectCid.
//   R16: no network listener.

mod methods;
mod ra_host;
mod resolve_cache;
mod server;
mod snapshot;
mod state;

use std::path::PathBuf;
use std::time::Duration;

use server::{default_snapshot_path, default_socket_path, ServerConfig};
use tracing::info;

fn main() -> anyhow::Result<()> {
    // Structured logging.
    init_tracing();

    // Parse arguments (hand-rolled to avoid a heavy CLI dep in the daemon).
    let args: Vec<String> = std::env::args().collect();
    let mut project_cid = String::from("default");
    let mut socket_path: Option<PathBuf> = None;
    let mut snapshot_path: Option<PathBuf> = None;
    let mut idle_timeout_ms: u64 = 5 * 60 * 1000; // 5 min default
    let mut cache_cap: usize = 1024;

    let mut i = 1usize;
    while i < args.len() {
        match args[i].as_str() {
            "--project-cid" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    project_cid = v.clone();
                }
            }
            "--socket" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    socket_path = Some(PathBuf::from(v));
                }
            }
            "--snapshot" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    snapshot_path = Some(PathBuf::from(v));
                }
            }
            "--idle-timeout-ms" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    idle_timeout_ms = v.parse().unwrap_or(idle_timeout_ms);
                }
            }
            "--cache-cap" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    cache_cap = v.parse().unwrap_or(cache_cap);
                }
            }
            _ => {}
        }
        i += 1;
    }

    let config = ServerConfig {
        socket_path: socket_path.unwrap_or_else(|| default_socket_path(&project_cid)),
        snapshot_path: snapshot_path.unwrap_or_else(|| default_snapshot_path(&project_cid)),
        idle_timeout: Duration::from_millis(idle_timeout_ms),
        cache_cap,
    };

    info!(
        project_cid = %project_cid,
        socket = %config.socket_path.display(),
        idle_timeout_ms = %idle_timeout_ms,
        "sugar-linkerd starting"
    );

    // Windows gap: Unix sockets are not supported on Windows.
    // Named pipe support (\\.\pipe\...) will be added in a follow-up.
    #[cfg(not(unix))]
    {
        eprintln!("error: sugar-linkerd requires a Unix platform (Unix domain sockets).");
        eprintln!("Windows named pipe support is planned; see spec R1.");
        std::process::exit(1);
    }

    // Run the async server on a multi-threaded tokio runtime.
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(server::run(config))?;

    Ok(())
}

fn init_tracing() {
    let filter = tracing_subscriber::EnvFilter::from_default_env()
        .add_directive("sugar_linkerd=info".parse().unwrap())
        // Surface the resident rust-analyzer host's own index progress
        // (it lives in sugar_walk::ra_oracle) so an operator watching
        // the daemon sees the one-time workspace index, not silence.
        .add_directive("sugar_walk::ra_oracle=info".parse().unwrap());
    if let Ok(path) = std::env::var("SUGAR_LOG_FILE") {
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            Ok(file) => {
                tracing_subscriber::fmt()
                    .with_writer(file)
                    .with_ansi(false)
                    .with_env_filter(filter)
                    .init();
            }
            Err(error) => {
                eprintln!(
                    "warning: could not open SUGAR_LOG_FILE {path}: {error}; logging to stderr"
                );
                tracing_subscriber::fmt()
                    .with_writer(std::io::stderr)
                    .with_env_filter(filter)
                    .init();
            }
        }
    } else {
        tracing_subscriber::fmt()
            .with_writer(std::io::stderr)
            .with_env_filter(filter)
            .init();
    }
}
