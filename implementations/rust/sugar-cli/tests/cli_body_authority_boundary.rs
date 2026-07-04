// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};

fn cli_src_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src")
}

fn rust_files_under(root: &Path) -> Vec<PathBuf> {
    let mut stack = vec![root.to_path_buf()];
    let mut files = Vec::new();
    while let Some(dir) = stack.pop() {
        for entry in fs::read_dir(&dir).unwrap_or_else(|err| {
            panic!("read {}: {err}", dir.display());
        }) {
            let entry = entry.expect("read dir entry");
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
                files.push(path);
            }
        }
    }
    files.sort();
    files
}

#[test]
fn cli_runtime_source_does_not_reintroduce_body_template_json_authority() {
    let forbidden = [
        "project_body_templates_for_sugar_bindings",
        "canonical-bodies",
        "body-template JSON",
        "body-template cache",
    ];
    let mut violations = Vec::new();
    for path in rust_files_under(&cli_src_root()) {
        let source = fs::read_to_string(&path).unwrap_or_else(|err| {
            panic!("read {}: {err}", path.display());
        });
        for needle in forbidden {
            if source.contains(needle) {
                violations.push(format!("{} contains `{needle}`", path.display()));
            }
        }
    }
    assert!(
        violations.is_empty(),
        "sugar-cli must not make body-template JSON/cache files runtime authority. \
         Kits own body/proof resolution and the CLI speaks RPC only:\n{}",
        violations.join("\n")
    );
}
