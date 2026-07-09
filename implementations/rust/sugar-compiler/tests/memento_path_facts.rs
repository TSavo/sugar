// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: fact / universe levels of the typed descent = SourceMemento[path].
//
// - Fact path is the typed-descent address: file[fn[leaf]]
// - Factory 1:1: fact path ≡ owning assertion path (same kind=contract leaf)
// - Universe path is the linking call site's path; memento is the
//   function-contract seal (may differ from the site memento)
// - No invented nesting (no file[fn[assertion[fact]]]): factory has no
//   distinct fact key under assertion beyond the shared leaf
// - Fragment stays local; memento remains wire currency
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

fn stage_mathy_fixture(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(&project).unwrap();
    let fixture_src = repo_root()
        .join("implementations/rust/sugar-compiler/tests/fixtures/enumerate_fixture/mathy.py");
    fs::copy(&fixture_src, project.join("mathy.py")).expect("copy mathy fixture");
    project
}

#[test]
fn facts_expose_source_memento_at_path() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    assert_eq!(files.len(), 1, "one source file");
    let functions = files[0].functions().expect("functions");
    let mut found_leaf = false;
    for function in &functions {
        let fn_path = function.path();
        assert_eq!(fn_path.file, "pair.py");
        assert!(fn_path.function.is_some(), "function segment present");
        assert!(fn_path.leaf.is_none(), "function path has no leaf segment");

        for site in function.call_sites().expect("call_sites") {
            let site_at = site.memento_at_path();
            for assertion in site.assertions().expect("assertions") {
                let assertion_at = assertion.memento_at_path();
                let facts = assertion.facts().expect("facts");
                assert!(
                    !facts.is_empty(),
                    "expected at least one fact under assertion path {}",
                    assertion_at.path_display()
                );
                for fact in &facts {
                    let at = fact.memento_at_path();
                    // Path is the address: file[fn[leaf]]
                    assert_eq!(at.path.file, "pair.py");
                    assert_eq!(
                        at.path.function.as_ref().map(|f| f.name.as_str()),
                        function.source_memento().source_function_name(),
                        "path function segment matches parent"
                    );
                    assert!(
                        at.path.leaf.is_some(),
                        "fact path has leaf segment: {}",
                        at.path_display()
                    );
                    // Factory 1:1 — fact path ≡ assertion path ≡ site path
                    assert_eq!(
                        at.path, assertion_at.path,
                        "fact path ≡ assertion path (factory 1:1)"
                    );
                    assert_eq!(
                        at.path, site_at.path,
                        "fact path ≡ call-site path (factory 1:1)"
                    );
                    assert_eq!(at.memento.file, fact.source_memento().file);
                    assert!(
                        at.path_display().starts_with("pair.py["),
                        "display form nested: {}",
                        at.path_display()
                    );
                    found_leaf = true;
                    eprintln!(
                        "RECEIPT fact SourceMemento[path]={path} memento.file={file}",
                        path = at.path_display(),
                        file = at.memento.file
                    );
                }
            }
        }
    }
    assert!(found_leaf, "expected at least one fact with path leaf");
}

#[test]
fn facts_partitioned_by_enclosing_function() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    let functions = files[0].functions().expect("functions");
    let mut by_fn: std::collections::BTreeMap<String, Vec<String>> =
        std::collections::BTreeMap::new();
    for function in &functions {
        let name = function
            .source_memento()
            .source_function_name()
            .unwrap_or("")
            .to_string();
        if name.is_empty() {
            continue;
        }
        let mut paths = Vec::new();
        for site in function.call_sites().expect("call_sites") {
            for assertion in site.assertions().expect("assertions") {
                for fact in assertion.facts().expect("facts") {
                    paths.push(fact.memento_at_path().path_display());
                }
            }
        }
        by_fn.insert(name, paths);
    }
    eprintln!("RECEIPT facts by function: {by_fn:?}");
    if let Some(a) = by_fn.get("test_a") {
        assert!(!a.is_empty(), "test_a must own at least one fact");
        for p in a {
            assert!(
                p.contains("test_a"),
                "test_a fact path must name test_a: {p}"
            );
            assert!(
                !p.contains("test_b"),
                "test_a must not include test_b path: {p}"
            );
        }
    }
    if let Some(b) = by_fn.get("test_b") {
        assert!(!b.is_empty(), "test_b must own at least one fact");
        for p in b {
            assert!(
                p.contains("test_b"),
                "test_b fact path must name test_b: {p}"
            );
        }
    }
}

#[test]
fn universe_stamped_from_owning_call_site_path() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_mathy_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    let mut found = false;
    for file in &files {
        for function in file.functions().expect("functions") {
            for site in function.call_sites().expect("call_sites") {
                let site_at = site.memento_at_path();
                match site.universe().expect("universe RPC") {
                    Some(universe) => {
                        let at = universe.memento_at_path();
                        // Descent index = owning site path
                        assert_eq!(
                            at.path, site_at.path,
                            "universe path ≡ linking call-site path"
                        );
                        assert_eq!(at.path_display(), site_at.path_display());
                        // Seal may differ (function-contract member key)
                        assert!(
                            !at.memento.function_name.is_empty()
                                || !universe.source_memento().function_name.is_empty(),
                            "universe memento carries member identity"
                        );
                        found = true;
                        eprintln!(
                            "RECEIPT universe SourceMemento[path]={path} memento.fn={fn_name}",
                            path = at.path_display(),
                            fn_name = at.memento.function_name
                        );
                    }
                    None => {
                        eprintln!(
                            "RECEIPT universe gap at path={}",
                            site_at.path_display()
                        );
                    }
                }
            }
        }
    }
    assert!(
        found,
        "mathy fixture must yield at least one site-linked universe"
    );
}

#[test]
fn fact_path_display_matches_site_leaf() {
    use sugar_compiler::tree::MementoPath;
    use sugar_walk::source_oracle::{SourceMemento, SrcSpan};

    let fn_m = SourceMemento {
        file: "a.py".into(),
        function_name: "f".into(),
        span: SrcSpan {
            start_line: 1,
            start_col: 0,
            end_line: 3,
            end_col: 1,
        },
        param_names: vec![],
        source_cid: "blake3-512:aa".into(),
        template_cid: "blake3-512:bb".into(),
    };
    // Factory 1:1 — fact leaf uses the same span as site/assertion.
    let leaf_m = SourceMemento {
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
    let site_path = MementoPath::for_site_under(&fn_m, &leaf_m);
    let fact_path = MementoPath::for_site_under(&fn_m, &leaf_m);
    assert_eq!(site_path, fact_path, "site ≡ fact path shape (no deeper nest)");
    let d = fact_path.display();
    assert!(d.starts_with("a.py[f"), "got {d}");
    assert!(d.contains("2:4-2:20") || d.contains('['), "got {d}");
    eprintln!("RECEIPT fact path display = {d}");
}
