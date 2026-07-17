// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3855 instrument: kit_path is the language-neutral kit dispatch engine.
// Realize-sidecar strip and SourceMemento live in libsugar; this module must
// not re-import sugar-walk (rust-kit knowledge). Crate-level ban is
// sugar-arch-guard `sugar_compiler_never_reaches_sugar_walk`.
//
// R axis: kit_path_sugar_walk_imports
// Green only at stable zero. Replacement: keep strip/locators in libsugar;
// never reintroduce sugar_walk into kit_path.

use std::fs;
use std::path::PathBuf;

#[test]
fn kit_path_has_no_sugar_walk_import() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/kit_path");
    let mut offenders = Vec::new();
    for entry in fs::read_dir(&root).expect("read kit_path") {
        let entry = entry.expect("dir entry");
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("rs") {
            continue;
        }
        let text = fs::read_to_string(&path).unwrap_or_else(|e| {
            panic!("read {}: {e}", path.display());
        });
        for (idx, line) in text.lines().enumerate() {
            let trimmed = line.trim_start();
            if trimmed.starts_with("//") {
                continue;
            }
            if line.contains("sugar_walk") || line.contains("sugar-walk") {
                offenders.push(format!("{}:{}: {}", path.display(), idx + 1, line.trim()));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "kit_path must not import sugar-walk (#3855 purification). \
         Realize-sidecar strip lives in libsugar::core::strip_realize_sidecar_from_lift_term. \
         Offenders (R = {}):\n  {}",
        offenders.len(),
        offenders.join("\n  ")
    );
}
