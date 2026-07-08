// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-ra-oracle: the resident rust-analyzer oracle for the Rust lift
// pipeline, extracted from `sugar-linkerd` (daemon-1 of the linkerd
// retirement: the daemon's NON-editor job gets a new home before the daemon
// crate itself is deleted).
//
// This crate hosts ONLY the two RPCs `sugar_walk::ra_daemon_client` needs from
// the resident daemon:
//   - `rustAnalyzerReady`     (readiness gate over the warm RA session)
//   - `resolveReceiverCrate`  (callee-crate resolution, cache-fronted)
//
// It speaks the SAME NDJSON JSON-RPC 2.0 wire protocol over a Unix domain
// socket that `sugar-linkerd` already serves these two methods on, and accepts
// the SAME four CLI flags `ra_daemon_client::connect_or_spawn` already passes
// (`--socket`, `--project-cid`, `--idle-timeout-ms`, `--snapshot`), so
// repointing the client (a later step) is a binary-name/env-var change, not a
// protocol change.
//
// Deliberately NOT here: the editor warm-prove machinery (`ProveContext`,
// `proveConsistency`, `parseFile`, the linker union/cache). That machinery
// dies with `sugar-linkerd` when the daemon is retired; it has no bearing on
// the Rust lift pipeline's oracle path.

pub mod methods;
pub mod ra_host;
pub mod resolve_cache;
pub mod server;
