// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-ra-oracle: resident rust-analyzer oracle for the Rust lift pipeline.
//
// Extracted from sugar-linkerd (daemon-1 of the linkerd retirement): this
// binary serves ONLY the two RPCs `sugar_walk::ra_daemon_client` needs
// (`rustAnalyzerReady`, `resolveReceiverCrate`), over the SAME NDJSON
// JSON-RPC 2.0 Unix-socket wire protocol sugar-linkerd already speaks for
// these methods.
//
// Usage:
//   sugar-ra-oracle --project-cid <cid>
//                    [--socket <path>]
//                    [--snapshot <path>]
//                    [--idle-timeout-ms <ms>]
//
// The four flags are intentionally identical (name and meaning) to the ones
// `sugar-linkerd` accepts, and to the ones
// `sugar_walk::ra_daemon_client::connect_or_spawn` already passes when it
// spawns the daemon -- so repointing that client at this binary (a later
// step) is a binary-name/env-var change, not a protocol or CLI change.

use std::path::PathBuf;
use std::time::Duration;

use sugar_ra_oracle::server::{default_snapshot_path, default_socket_path, ServerConfig};
use tracing::info;

fn main() -> anyhow::Result<()> {
    init_tracing();

    // Hand-rolled arg parsing, mirroring sugar-linkerd's main.rs (avoids a
    // heavy CLI dep in a small resident daemon).
    let args: Vec<String> = std::env::args().collect();
    let mut project_cid = String::from("default");
    let mut socket_path: Option<PathBuf> = None;
    let mut snapshot_path: Option<PathBuf> = None;
    let mut idle_timeout_ms: u64 = 5 * 60 * 1000; // 5 min default

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
            // Flags sugar-linkerd also accepts but this oracle has no use for
            // (editor-prove/link concerns): accepted and ignored so a caller
            // that still passes the full linkerd flag set (pre-repoint) does
            // not fail to spawn this binary.
            "--cache-cap" | "--project-root" => {
                i += 1;
            }
            "--no-solvers" => {}
            _ => {}
        }
        i += 1;
    }

    let config = ServerConfig {
        socket_path: socket_path.unwrap_or_else(|| default_socket_path(&project_cid)),
        snapshot_path: snapshot_path.unwrap_or_else(|| default_snapshot_path(&project_cid)),
        idle_timeout: Duration::from_millis(idle_timeout_ms),
    };

    info!(
        project_cid = %project_cid,
        socket = %config.socket_path.display(),
        idle_timeout_ms = %idle_timeout_ms,
        "sugar-ra-oracle starting"
    );

    #[cfg(not(unix))]
    {
        eprintln!("error: sugar-ra-oracle requires a Unix platform (Unix domain sockets).");
        std::process::exit(1);
    }

    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(sugar_ra_oracle::server::run(config))?;

    Ok(())
}

fn init_tracing() {
    let filter = tracing_subscriber::EnvFilter::from_default_env()
        .add_directive("sugar_ra_oracle=info".parse().unwrap())
        // Surface the resident rust-analyzer host's own index progress (it
        // lives in sugar_walk::ra_oracle) so an operator watching the oracle
        // sees the one-time workspace index, not silence.
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
