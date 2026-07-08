// SPDX-License-Identifier: MIT OR Apache-2.0

//! Kit-path execution surface, relocated from `libsugar::core` toward its
//! consumer (#evict-2-liftplugin-pathexec).
//!
//! `lift_plugin.rs` (LiftPluginKit/LiftKit transport), `path_executor.rs`
//! (execute_path/KitRegistry dispatch), and `prove_kit.rs` (the built-in
//! ProveKit that `path_executor::execute_path` dispatches to) live here as a
//! unit: `path_executor.rs` depends on `prove_kit::ProveKit` directly, so
//! they move together. `sugar-cli` already has its own `src/lift_plugin.rs`
//! (a consumer of this module's `LiftKit`/`LiftPluginKit`/`execute_path`),
//! kept separate to avoid collision.

pub mod lift_plugin;
pub mod path_executor;
pub mod prove_kit;

pub use lift_plugin::{LiftKit, LiftPluginKit, LiftPluginKitError, LiftPluginKitSession};
pub use path_executor::{execute_path, KitRegistry, PathExecutionChain, PathExecutionError};
pub use prove_kit::ProveKit;
