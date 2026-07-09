// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: source level of the typed descent = SourceMemento[file].
//
// - Path is bare file (top of tree): MementoPath::file
// - Kit::source_files stamps SourceMementoAtPath on every SourceFile
// - Completes the descent: source → functions → call_sites → assertions → facts
//
// Does not require verdict byte-identity (no solve); kit rendezvous + enumerate only.

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::tree::Sourced;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn python_blake3_available() -> bool {
    Command::new("python3")
        .arg("-c")
        .arg("import blake3")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn write_executable(path: &Path, text: &str) {
    {
        let mut f = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path)
            .unwrap_or_else(|e| panic!("open {}: {e}", path.display()));
        f.write_all(text.as_bytes()).unwrap();
        f.sync_all().unwrap();
    }
    #[cfg(unix)]
    {
        let mut perms = fs::metadata(path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).unwrap();
    }
}

fn python_kit_manifest(dir: &Path) -> LiftManifest {
    use libsugar::core::Dialect;
    let root = repo_root();
    let py_tests_src = root.join("implementations/python/sugar-lift-py-tests/src");
    let py_source_src = root.join("implementations/python/sugar-lift-python-source/src");
    let script = dir.join("python-lift.sh");
    write_executable(
        &script,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );
    LiftManifest {
        surface: "python".to_string(),
        name: "python-lift".to_string(),
        dialect: Dialect::Other("python".to_string()),
        command: vec![script.display().to_string()],
        working_dir: None,
        method: None,
    }
}

fn stage_two_tests(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(&project).unwrap();
    fs::write(
        project.join("pair.py"),
        r#"
def test_a():
    assert len([1]) == 1

def test_b():
    assert len([1, 2]) == 2
"#,
    )
    .unwrap();
    project
}

#[test]
fn source_files_expose_source_memento_at_path() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    assert_eq!(files.len(), 1, "one source file");
    let file = &files[0];
    let at = file.memento_at_path();

    // Path is bare file — no function / leaf segment
    assert_eq!(at.path.file, "pair.py");
    assert!(at.path.function.is_none(), "source path has no function segment");
    assert!(at.path.leaf.is_none(), "source path has no leaf segment");
    assert_eq!(
        at.path_display(),
        "pair.py",
        "display form is bare file, got {}",
        at.path_display()
    );
    assert_eq!(at.path, *file.path());
    // Sealed memento is the wire currency
    assert_eq!(at.memento.file, file.source_memento().file);
    assert_eq!(at.memento.file, "pair.py");
    eprintln!(
        "RECEIPT source SourceMemento[path]={path} memento.file={file}",
        path = at.path_display(),
        file = at.memento.file
    );
}

#[test]
fn source_path_display_is_bare_file() {
    use sugar_compiler::tree::MementoPath;

    let path = MementoPath::file("pair.py");
    assert_eq!(path.display(), "pair.py");
    assert!(path.function.is_none());
    assert!(path.leaf.is_none());
    eprintln!("RECEIPT source path display = {}", path.display());
}

#[test]
fn source_seek_stamps_same_path() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    let scanned = &files[0];
    let sought = kit
        .source_file(&project, scanned.source_memento())
        .expect("source_file seek");
    assert_eq!(sought.path(), scanned.path());
    assert_eq!(
        sought.memento_at_path().path_display(),
        scanned.memento_at_path().path_display()
    );
    eprintln!(
        "RECEIPT source seek path={}",
        sought.memento_at_path().path_display()
    );
}
