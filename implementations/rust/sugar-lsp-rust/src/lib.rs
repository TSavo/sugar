// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Library surface for sugar-lsp-rust.
//
// Exposes `daemon_client` so the main sugar-lsp tower-lsp server can
// depend on this crate and call `connect_or_spawn` / `send_parse_file`
// without duplicating the implementation.
//
// The `[[bin]]` target (`src/main.rs`) speaks the per-language NDJSON
// plugin protocol (initialize / parse / shutdown).  This `[lib]` target
// exposes the daemon-client primitives for the LSP server that routes
// through `sugar-linkerd`.

pub mod daemon_client;
pub mod forward_propagator;
