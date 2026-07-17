// SPDX-License-Identifier: MIT OR Apache-2.0

//! Kit-path execution surface. Originally relocated from `libsugar::core`
//! toward its then-consumer, `sugar-cli` (#evict-2-liftplugin-pathexec).
//! Moved again in SEAM 3b (compiler-shape plan) from
//! `sugar-cli/src/kit_path/` to here as the legal home for the `Kit` noun
//! (`sugar_compiler::kit::Kit`) that wraps this engine.
//!
//! #3855 purification: realize-sidecar strip and SourceMemento live in
//! libsugar; this module must not import `sugar-walk` (instrument:
//! `kit_path_has_no_sugar_walk_import`). Crate ban: arch-guard.
//!
//! `lift_plugin.rs` (LiftPluginKit/LiftKit transport) and `path_executor.rs`
//! (execute_path/KitRegistry dispatch) live here. `sugar-cli::lift_plugin`
//! (a distinct file, `sugar-cli/src/lift_plugin.rs`) is the FACE ADAPTER: a
//! consumer of this module's `LiftKit`/`LiftPluginKit`/`execute_path`,
//! kept separate to avoid collision.
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
pub mod term_table;

pub use lift_plugin::{
    FactoryPanicRpcError, LiftKit, LiftPluginKit, LiftPluginKitError, LiftPluginKitSession,
};
pub use path_executor::{execute_path, KitRegistry, PathExecutionChain, PathExecutionError};
pub use term_table::{LiftTermKind, LiftTermNode, LiftTermTable};
