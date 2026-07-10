// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Library surface for sugar-lsp: in-process prove composition (#3809).
// The binary (`main.rs`) is the Language Server; integration tests and
// other faces call `prove_engine` directly for feed/solve without LSP
// transport.

pub mod auto_mode;
pub mod prove_engine;
