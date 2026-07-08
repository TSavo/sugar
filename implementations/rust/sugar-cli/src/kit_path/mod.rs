// SPDX-License-Identifier: MIT OR Apache-2.0

//! Kit-path execution surface, relocated from `libsugar::core` toward its
//! consumer (#evict-2-liftplugin-pathexec).
//!
//! `lift_plugin.rs` (LiftPluginKit/LiftKit transport) and `path_executor.rs`
//! (execute_path/KitRegistry dispatch) live here. `sugar-cli` already has its
//! own `src/lift_plugin.rs` (a consumer of this module's
//! `LiftKit`/`LiftPluginKit`/`execute_path`), kept separate to avoid
//! collision.
//!
//! `prove_kit.rs` (the built-in `ProveKit`, plus its only wiring point
//! `KitRegistry::register_prove`) was deleted by #evict-3-provekit after
//! interrogation: `register_prove` was called only from
//! `sugar-cli/tests/prove_kit.rs`, and no live entry point (`cmd_bind`,
//! `dispatch_lift_path`, or any other command) ever registered `ProveKit` or
//! constructed a `Verb::Prove` path step targeting it. The generic
//! `Verb::Prove` dispatch arm in `path_executor::execute_path` is unrelated
//! substrate (any `Kit` may implement `prove`, independent of `ProveKit`) and
//! stays; it remains covered by `path_executor`'s own fixture-kit tests and
//! `tests/lift_kit_path_integration.rs`'s `ProveStubKit`.

pub mod lift_plugin;
pub mod path_executor;

pub use lift_plugin::{LiftKit, LiftPluginKit, LiftPluginKitError, LiftPluginKitSession};
pub use path_executor::{execute_path, KitRegistry, PathExecutionChain, PathExecutionError};
