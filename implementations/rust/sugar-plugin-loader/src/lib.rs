// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-plugin-loader — PEP 1.7.0 runtime engine.
//
// Implements:
//   §3  File interface
//   §4  JSON-RPC interface  (stdio and http stubs)
//   §6  Content-addressing rules
//   §8  Error model  (PluginLoadFailureMemento)
//   §9  Registry semantics  (PluginRegistry + PluginRegistryMemento)
//
// The three built-in plugin kinds (§2.1) have no concrete implementations
// in this PR.  This crate is loader infrastructure only.  Consumer plugin
// crates (#735 sugar, #736 comment-sugar, #738 loss-function, etc.) will
// depend on this crate.

pub mod cid;
pub mod error;
pub mod loader;
pub mod persistence;
pub mod registry;
pub mod types;

pub use error::LoadError;
pub use loader::{load_plugin_from_file, load_plugin_from_rpc};
pub use persistence::{
    plugin_registry_memento_path, read_plugin_registry_memento, write_plugin_registry_memento,
    PLUGIN_REGISTRY_MEMENTO_FILE,
};
pub use registry::{PluginRegistry, PluginRegistryMemento};
pub use types::{
    LoadOrderEntry, LoadedEntry, PluginEnvelope, PluginHeader, PluginLoadFailureMemento,
    PluginMemento, PluginMetadata,
};
