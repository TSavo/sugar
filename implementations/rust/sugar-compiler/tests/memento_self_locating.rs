// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: SourceMemento is already self-locating (file + function_name + span + CIDs).
//
// Collapsed MementoPath / SourceMementoAtPath (#3942–#3947).
//
// Asserts:
// - the source_files level returns a self-locating file memento, and seeking
//   it returns the same file
// - the locus display is derived on demand from the memento alone
//
// No solve; kit rendezvous + enumerate only. The levels below source_files
// that this file once descended (functions, call_sites, assertions, facts)
// are not driven from Rust: the one whole-tree walk is mint's (#7757 entry 5).

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::SourceMemento;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::tree::{memento_locus_display, Sourced};

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
    LiftManifest::resolved(
        "python".to_string(),
        "python-lift".to_string(),
        Dialect::Other("python".to_string()),
        vec![script.display().to_string()],
        None,
        None,
    )
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
fn source_returns_self_locating_file_memento() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    assert_eq!(files.len(), 1);
    let m = files[0].source_memento();
    assert_eq!(m.file, "pair.py");
    // File-level memento: no function segment required
    assert!(
        m.function_name.is_empty() || m.source_function_name().is_none(),
        "source file memento is file-level, got fn={}",
        m.function_name
    );
    eprintln!(
        "RECEIPT source memento file={} locus={}",
        m.file,
        memento_locus_display(m)
    );

    let sought = kit.source_file(&project, m).expect("source_file seek");
    assert_eq!(sought.source_memento().file, m.file);
}

#[test]
fn memento_locus_display_on_demand() {
    use libsugar::core::SrcSpan;

    let file_only = SourceMemento {
        file: "a.py".into(),
        function_name: String::new(),
        span: SrcSpan {
            start_line: 0,
            start_col: 0,
            end_line: 0,
            end_col: 0,
        },
        param_names: vec![],
        source_cid: String::new(),
        template_cid: String::new(),
    };
    assert_eq!(memento_locus_display(&file_only), "a.py");

    let with_fn = SourceMemento {
        file: "a.py".into(),
        function_name: "f".into(),
        span: SrcSpan {
            start_line: 2,
            start_col: 4,
            end_line: 2,
            end_col: 20,
        },
        param_names: vec![],
        source_cid: "blake3-512:cc".into(),
        template_cid: "blake3-512:dd".into(),
    };
    let d = memento_locus_display(&with_fn);
    assert!(d.starts_with("a.py[f"), "got {d}");
    assert!(d.contains("2:4-2:20"), "got {d}");
    eprintln!("RECEIPT locus display = {d}");
}
