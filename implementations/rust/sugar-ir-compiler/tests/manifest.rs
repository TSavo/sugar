// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::PathBuf;

use sugar_ir_compiler::manifest;

fn temp_dir(tag: &str) -> PathBuf {
    let mut p = std::env::temp_dir();
    p.push(format!(
        "sugar-ir-compiler-manifest-{tag}-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&p);
    fs::create_dir_all(&p).unwrap();
    p
}

#[test]
fn discover_returns_empty_when_root_missing() {
    let mut p = std::env::temp_dir();
    p.push(format!("sugar-ir-compiler-missing-{}", std::process::id()));
    let _ = fs::remove_dir_all(&p);
    let m = manifest::discover(&p);
    assert!(m.is_empty());
}

#[test]
fn discover_parses_well_formed_manifest() {
    let root = temp_dir("good");
    let plugin = root.join("smt-lib-reference");
    fs::create_dir_all(&plugin).unwrap();
    fs::write(
        plugin.join("manifest.toml"),
        r#"
# header comment
name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["/usr/local/bin/sugar-ir-smt-lib", "--rpc"]
working_dir = "/tmp"
dialects = ["smt-lib-v2.6"]
"#,
    )
    .unwrap();

    let ms = manifest::discover(&root);
    assert_eq!(ms.len(), 1);
    let m = &ms[0];
    assert_eq!(m.name, "smt-lib-reference");
    assert_eq!(m.version, "0.1.0");
    assert_eq!(m.protocol_version, "sugar-ir-compiler/1");
    assert_eq!(
        m.command,
        vec![
            "/usr/local/bin/sugar-ir-smt-lib".to_string(),
            "--rpc".to_string()
        ]
    );
    assert_eq!(m.working_dir, Some(PathBuf::from("/tmp")));
    assert_eq!(m.dialects, vec!["smt-lib-v2.6".to_string()]);

    fs::remove_dir_all(&root).ok();
}

#[test]
fn discover_skips_directories_without_manifest() {
    let root = temp_dir("skip");
    fs::create_dir_all(root.join("noisy-empty-dir")).unwrap();
    let ms = manifest::discover(&root);
    assert!(ms.is_empty());
    fs::remove_dir_all(&root).ok();
}

#[test]
fn parse_handles_multi_dialect_array() {
    let body = r#"
name = "multi"
version = "0.2"
protocol_version = "sugar-ir-compiler/1"
command = ["multi-bin"]
dialects = ["smt-lib-v2.6", "smt-lib-v2.6-bv"]
"#;
    let m = manifest::parse(body).expect("parse");
    assert_eq!(
        m.dialects,
        vec!["smt-lib-v2.6".to_string(), "smt-lib-v2.6-bv".to_string()]
    );
}

#[test]
fn parse_returns_none_when_required_field_missing() {
    let body = r#"
version = "0.1"
binary = "x"
"#;
    assert!(manifest::parse(body).is_none());
}

#[test]
fn default_root_includes_sugar_ir_compilers_segment() {
    if let Some(p) = manifest::default_root() {
        let s = p.to_string_lossy();
        assert!(s.contains("sugar"));
        assert!(s.contains("ir-compilers"));
    }
}
