// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: full typed-descent completeness receipt.
//
// Walks source → functions → call_sites → assertions → facts (+ universe when
// present) via sugar.enumerate and asserts EVERY navigable level returns a
// correctly path-indexed SourceMemento[path] node.
//
// Descent complete map:
//   source[file]
//     → functions[file[fn]]
//       → call_sites / assertions / facts[file[fn[leaf]]]
//       → universe (site-stamped path; function-contract memento)
//
// Does not require verdict byte-identity (no solve).

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

fn stage_mathy_fixture(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(&project).unwrap();
    let fixture_src = repo_root()
        .join("implementations/rust/sugar-compiler/tests/fixtures/enumerate_fixture/mathy.py");
    fs::copy(&fixture_src, project.join("mathy.py")).expect("copy mathy fixture");
    project
}

/// Full typed-tree walk: every level returns SourceMemento[path] with the
/// shape required by that level of the descent.
#[test]
fn typed_descent_complete_every_level_path_indexed() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_mathy_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let mut n_source = 0usize;
    let mut n_function = 0usize;
    let mut n_site = 0usize;
    let mut n_assertion = 0usize;
    let mut n_fact = 0usize;
    let mut n_universe = 0usize;

    let files = kit.source_files(&project).expect("source_files");
    assert!(!files.is_empty(), "descent requires at least one source file");

    for file in &files {
        let file_at = file.memento_at_path();
        // --- source: SourceMemento[file] ---
        assert!(
            file_at.path.function.is_none() && file_at.path.leaf.is_none(),
            "source path must be bare file: {}",
            file_at.path_display()
        );
        assert_eq!(file_at.path_display(), file_at.path.file);
        assert_eq!(file_at.memento.file, file.source_memento().file);
        n_source += 1;
        eprintln!("RECEIPT level=source path={}", file_at.path_display());

        for function in file.functions().expect("functions") {
            let fn_at = function.memento_at_path();
            // --- functions: SourceMemento[file[fn]] ---
            assert_eq!(fn_at.path.file, file_at.path.file, "function under parent file");
            assert!(
                fn_at.path.function.is_some(),
                "function path needs fn segment: {}",
                fn_at.path_display()
            );
            assert!(
                fn_at.path.leaf.is_none(),
                "function path has no leaf: {}",
                fn_at.path_display()
            );
            assert!(
                fn_at.path_display().starts_with(&format!("{}[", file_at.path.file)),
                "function display nests under file: {}",
                fn_at.path_display()
            );
            n_function += 1;
            eprintln!("RECEIPT level=functions path={}", fn_at.path_display());

            for site in function.call_sites().expect("call_sites") {
                let site_at = site.memento_at_path();
                // --- call_sites: SourceMemento[file[fn[site]]] ---
                assert_eq!(site_at.path.file, file_at.path.file);
                assert_eq!(
                    site_at.path.function.as_ref().map(|f| f.name.as_str()),
                    fn_at.path.function.as_ref().map(|f| f.name.as_str()),
                    "site fn segment matches parent function"
                );
                assert!(
                    site_at.path.leaf.is_some(),
                    "site path needs leaf: {}",
                    site_at.path_display()
                );
                n_site += 1;
                eprintln!("RECEIPT level=call_sites path={}", site_at.path_display());

                // --- universe: site-stamped path (when linked) ---
                if let Some(universe) = site.universe().expect("universe") {
                    let u_at = universe.memento_at_path();
                    assert_eq!(
                        u_at.path, site_at.path,
                        "universe path ≡ linking call-site path"
                    );
                    n_universe += 1;
                    eprintln!(
                        "RECEIPT level=universe path={} memento.fn={}",
                        u_at.path_display(),
                        u_at.memento.function_name
                    );
                }

                for assertion in site.assertions().expect("assertions") {
                    let a_at = assertion.memento_at_path();
                    // --- assertions: same leaf as site (factory 1:1) ---
                    assert_eq!(
                        a_at.path, site_at.path,
                        "assertion path ≡ site path (factory 1:1)"
                    );
                    n_assertion += 1;
                    eprintln!("RECEIPT level=assertions path={}", a_at.path_display());

                    for fact in assertion.facts().expect("facts") {
                        let f_at = fact.memento_at_path();
                        // --- facts: same leaf as assertion/site ---
                        assert_eq!(
                            f_at.path, a_at.path,
                            "fact path ≡ assertion path (factory 1:1)"
                        );
                        assert_eq!(f_at.path, site_at.path);
                        n_fact += 1;
                        eprintln!("RECEIPT level=facts path={}", f_at.path_display());
                    }
                }
            }
        }
    }

    eprintln!(
        "RECEIPT descent_complete counts: source={n_source} functions={n_function} \
         call_sites={n_site} assertions={n_assertion} facts={n_fact} universe={n_universe}"
    );

    assert!(n_source > 0, "source level empty");
    assert!(n_function > 0, "functions level empty");
    assert!(n_site > 0, "call_sites level empty");
    assert!(n_assertion > 0, "assertions level empty");
    assert!(n_fact > 0, "facts level empty");
    // mathy fixture has at least call:add covered
    assert!(
        n_universe > 0,
        "universe level empty (mathy expects call:add coverage)"
    );
    // Factory 1:1 site ≡ assertion
    assert_eq!(
        n_site, n_assertion,
        "factory 1:1: site count must equal assertion count"
    );
}
