// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Plugin manifest discovery.
//
// Walks ~/.config/sugar/ir-compilers/<name>/manifest.toml and
// returns the parsed entries. Manifest format is intentionally tiny so
// the loader can hand-parse it without pulling a TOML dep into the
// workspace; it accepts string fields and quoted arrays.

use std::fs;
use std::path::{Path, PathBuf};

/// One discovered plugin manifest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Manifest {
    pub name: String,
    pub version: String,
    pub protocol_version: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub dialects: Vec<String>,
    pub manifest_dir: Option<PathBuf>,
}

/// Walk a directory of plugin manifests. Missing root is not an error;
/// returns an empty Vec.
pub fn discover(root: impl AsRef<Path>) -> Vec<Manifest> {
    let root = root.as_ref();
    if !root.exists() {
        return Vec::new();
    }
    let mut out = Vec::new();
    let entries = match fs::read_dir(root) {
        Ok(e) => e,
        Err(_) => return out,
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if !p.is_dir() {
            continue;
        }
        let manifest_path = p.join("manifest.toml");
        if !manifest_path.exists() {
            continue;
        }
        let body = match fs::read_to_string(&manifest_path) {
            Ok(b) => b,
            Err(_) => continue,
        };
        if let Some(mut m) = parse(&body) {
            m.manifest_dir = Some(p);
            out.push(m);
        }
    }
    out
}

/// Default discovery root: `~/.config/sugar/ir-compilers/`.
pub fn default_root() -> Option<PathBuf> {
    std::env::var_os("HOME").map(|h| {
        let mut p = PathBuf::from(h);
        p.push(".config");
        p.push("sugar");
        p.push("ir-compilers");
        p
    })
}

/// Hand-rolled mini-TOML parser. Accepts:
/// - `key = "string"`
/// - `key = ["a", "b"]`
/// - `# comment` lines
///
/// Anything else is silently ignored.
pub fn parse(body: &str) -> Option<Manifest> {
    let mut name = None;
    let mut version = None;
    let mut protocol_version = None;
    let mut command = Vec::new();
    let mut working_dir = None;
    let mut dialects = Vec::new();

    for line in body.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (key, value) = match line.split_once('=') {
            Some((k, v)) => (k.trim(), v.trim()),
            None => continue,
        };
        if value.starts_with('"') && value.ends_with('"') && value.len() >= 2 {
            let s = value[1..value.len() - 1].to_string();
            match key {
                "name" => name = Some(s),
                "version" => version = Some(s),
                "protocol_version" => protocol_version = Some(s),
                "working_dir" => working_dir = Some(PathBuf::from(s)),
                _ => {}
            }
        } else if value.starts_with('[') && value.ends_with(']') {
            let inner = &value[1..value.len() - 1];
            let mut values = Vec::new();
            for tok in inner.split(',') {
                let t = tok.trim();
                if t.starts_with('"') && t.ends_with('"') && t.len() >= 2 {
                    values.push(t[1..t.len() - 1].to_string());
                }
            }
            match key {
                "command" => command = values,
                "dialects" => dialects = values,
                _ => {}
            }
        }
    }

    if command.is_empty() {
        return None;
    }

    Some(Manifest {
        name: name?,
        version: version?,
        protocol_version: protocol_version?,
        command,
        working_dir,
        dialects,
        manifest_dir: None,
    })
}
