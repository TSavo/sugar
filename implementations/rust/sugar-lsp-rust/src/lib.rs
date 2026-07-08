// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Library surface for sugar-lsp-rust.
//
// The `[[bin]]` target (`src/main.rs`) speaks the per-language NDJSON
// plugin protocol (initialize / parse / shutdown).  This `[lib]` target
// exposes the forward-propagation floor used by both the bin and its tests.
//
// (This crate previously also exposed a `daemon_client` module for a
// `sugar-lsp-rust --daemon-socket` mode that routed through the now-retired
// `sugar-linkerd` daemon; nothing ever depended on this lib export, and the
// mode is retired along with the daemon. See daemon-3-delete.)

pub mod forward_propagator;
