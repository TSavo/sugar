// SPDX-License-Identifier: MIT OR Apache-2.0

use std::io;
use std::path::{Path, PathBuf};

use crate::PluginRegistryMemento;

pub const PLUGIN_REGISTRY_MEMENTO_FILE: &str = "plugin-registry-memento.json";

pub fn plugin_registry_memento_path(
    project_root: &Path,
    registry: &PluginRegistryMemento,
) -> PathBuf {
    project_root
        .join(".sugar")
        .join("runs")
        .join(registry.cid())
        .join(PLUGIN_REGISTRY_MEMENTO_FILE)
}

pub fn write_plugin_registry_memento(
    project_root: &Path,
    registry: &PluginRegistryMemento,
) -> io::Result<PathBuf> {
    let path = plugin_registry_memento_path(project_root, registry);
    let parent = path.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "plugin registry memento path has no parent",
        )
    })?;
    std::fs::create_dir_all(parent)?;
    let json = serde_json::to_string_pretty(registry).map_err(io::Error::other)?;
    std::fs::write(&path, format!("{json}\n"))?;
    Ok(path)
}

pub fn read_plugin_registry_memento(path: &Path) -> io::Result<PluginRegistryMemento> {
    let raw = std::fs::read_to_string(path)?;
    serde_json::from_str(&raw).map_err(io::Error::other)
}
