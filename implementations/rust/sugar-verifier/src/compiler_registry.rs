// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Manifest-backed ProofIR compiler registry for the verifier.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use sugar_ir_compiler::{
    manifest, registry::Registry, subprocess::LazyJsonRpcCompiler, Capabilities, PROTOCOL_VERSION,
};
use tracing::warn;

/// Build a dialect-keyed registry from built-in compilers plus compiler manifests.
///
/// The bundled SMT-LIB compiler is registered first so the verifier runner
/// supports the default `smt-lib-v2.6` solver seat even in ad-hoc example
/// project roots with no manifests. Manifest entries register afterward, so
/// user/project compiler manifests can still override the built-in dialect.
///
/// Project manifests live at `.sugar/ir-compilers/<name>/manifest.toml`.
/// Ancestor manifests live at any parent `.sugar/ir-compilers/<name>/manifest.toml`.
/// User manifests live at `~/.config/sugar/ir-compilers/<name>/manifest.toml`.
/// Project entries are registered last and override ancestor/user entries for
/// the same dialect.
pub fn build(project_root: &Path) -> Registry {
    let mut registry = Registry::new();
    registry.register(Arc::new(sugar_ir_compiler_smt_lib::SmtLibCompiler::new()));
    let mut roots = Vec::new();
    if let Some(home_root) = manifest::default_root() {
        roots.push(DiscoveryRoot {
            path: home_root,
            relative_base: RelativeBase::ManifestDir,
        });
    }
    roots.extend(ancestor_roots(project_root));

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

fn ancestor_roots(project_root: &Path) -> Vec<DiscoveryRoot> {
    let project_root = if project_root.is_absolute() {
        project_root.to_path_buf()
    } else {
        std::env::current_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
            .join(project_root)
    };
    let mut roots = Vec::new();
    let mut current = Some(project_root.as_path());
    while let Some(path) = current {
        roots.push(DiscoveryRoot {
            path: path.join(".sugar").join("ir-compilers"),
            relative_base: RelativeBase::ProjectRoot(path.to_path_buf()),
        });
        current = path.parent();
    }
    roots.reverse();
    roots
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
    fn build_registers_builtin_smt_lib_compiler() {
        let root = std::env::temp_dir().join(format!(
            "sugar-ir-compiler-registry-builtin-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();

        let registry = build(&root);
        assert!(
            registry.get(sugar_ir_compiler_smt_lib::DIALECT).is_some(),
            "verifier runner must support the default SMT-LIB dialect without a manifest"
        );

        let _ = std::fs::remove_dir_all(&root);
    }

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

    #[test]
    fn ancestor_manifest_registers_for_nested_project() {
        let root = std::env::temp_dir().join(format!(
            "sugar-ir-compiler-registry-ancestor-{}",
            std::process::id()
        ));
        let project = root.join("examples").join("demo");
        let manifest_dir = root.join(".sugar").join("ir-compilers").join("fake");
        std::fs::create_dir_all(&manifest_dir).unwrap();
        std::fs::create_dir_all(&project).unwrap();
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

        let registry = build(&project);
        assert!(registry.get("fake-dialect").is_some());

        let _ = std::fs::remove_dir_all(&root);
    }
}
