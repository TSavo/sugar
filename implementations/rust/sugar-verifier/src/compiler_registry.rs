// SPDX-License-Identifier: Apache-2.0
//
// Manifest-backed ProofIR compiler registry for the verifier.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use sugar_ir_compiler::{
    manifest, registry::Registry, subprocess::LazyJsonRpcCompiler, Capabilities, PROTOCOL_VERSION,
};
use tracing::warn;

/// Build a dialect-keyed registry from compiler manifests.
///
/// Project manifests live at `.sugar/ir-compilers/<name>/manifest.toml`.
/// User manifests live at `~/.config/sugar/ir-compilers/<name>/manifest.toml`.
/// Project entries are registered last and override user entries for the same
/// dialect.
pub fn build(project_root: &Path) -> Registry {
    let mut registry = Registry::new();
    let mut roots = Vec::new();
    if let Some(home_root) = manifest::default_root() {
        roots.push(DiscoveryRoot {
            path: home_root,
            relative_base: RelativeBase::ManifestDir,
        });
    }
    roots.push(DiscoveryRoot {
        path: project_root.join(".sugar").join("ir-compilers"),
        relative_base: RelativeBase::ProjectRoot(project_root.to_path_buf()),
    });

    for root in roots {
        for entry in manifest::discover(&root.path) {
            if entry.protocol_version != PROTOCOL_VERSION {
                warn!(
                    name = %entry.name,
                    protocol = %entry.protocol_version,
                    expected = %PROTOCOL_VERSION,
                    "skipping IR compiler manifest with incompatible protocol"
                );
                continue;
            }
            if entry.dialects.is_empty() {
                warn!(
                    name = %entry.name,
                    "skipping IR compiler manifest with no dialects"
                );
                continue;
            }
            let working_dir = resolve_working_dir(&root.relative_base, &entry);
            let caps = Capabilities {
                name: entry.name.clone(),
                version: entry.version.clone(),
                protocol_version: entry.protocol_version.clone(),
                dialects: entry.dialects.clone(),
                supported_sorts: vec![],
                supported_predicates: vec![],
            };
            registry.register(Arc::new(LazyJsonRpcCompiler::new(
                entry.command.clone(),
                working_dir,
                caps,
            )));
        }
    }

    registry
}

struct DiscoveryRoot {
    path: PathBuf,
    relative_base: RelativeBase,
}

enum RelativeBase {
    ProjectRoot(PathBuf),
    ManifestDir,
}

fn resolve_working_dir(base: &RelativeBase, entry: &manifest::Manifest) -> Option<PathBuf> {
    let working_dir = entry.working_dir.as_ref()?;
    if working_dir.is_absolute() {
        return Some(working_dir.clone());
    }
    match base {
        RelativeBase::ProjectRoot(root) => Some(root.join(working_dir)),
        RelativeBase::ManifestDir => entry
            .manifest_dir
            .as_ref()
            .map(|dir| dir.join(working_dir))
            .or_else(|| Some(working_dir.clone())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_manifest_registers_lazy_compiler_without_spawning() {
        let root =
            std::env::temp_dir().join(format!("sugar-ir-compiler-registry-{}", std::process::id()));
        let manifest_dir = root.join(".sugar").join("ir-compilers").join("fake");
        std::fs::create_dir_all(&manifest_dir).unwrap();
        std::fs::write(
            manifest_dir.join("manifest.toml"),
            r#"
name = "fake"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["definitely-not-started-during-build"]
working_dir = "implementations/rust"
dialects = ["fake-dialect"]
"#,
        )
        .unwrap();

        let registry = build(&root);
        assert!(registry.get("fake-dialect").is_some());

        let _ = std::fs::remove_dir_all(&root);
    }
}
