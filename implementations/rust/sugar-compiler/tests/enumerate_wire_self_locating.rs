// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: sugar.enumerate wire returns self-locating SourceMemento per node.
//
// Envelope is dissolved: node = { memento, audit, payload }; the memento IS
// the locator (file + function_name + span + source_cid / template_cid).
// Nesting is reconstructed from enumeration structure (parent → children),
// not a second path type.
//
// Degenerate-by-design (protocol):
//   - source_files: file-only (no single body CID for a whole file)
//   - enclosing-only functions: file + name, no body contract warrant
//
// Full self-locating required for body-level nodes:
//   call_sites / assertions / facts (and function-contract / universe rows
//   that carry a source warrant).
//
// Drive: Kit::rendezvous → sugar.enumerate RPC at each level (real kit).

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::SourceMemento;
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
    LiftManifest::resolved(
        "python".to_string(),
        "python-lift".to_string(),
        Dialect::Other("python".to_string()),
        vec![script.display().to_string()],
        None,
        None,
    )
}

fn stage_mathy(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(&project).unwrap();
    let src = repo_root()
        .join("implementations/rust/sugar-compiler/tests/fixtures/enumerate_fixture/mathy.py");
    fs::copy(&src, project.join("mathy.py")).expect("copy mathy");
    project
}

fn has_file(m: &SourceMemento) -> bool {
    !m.file.is_empty()
}

fn span_non_degenerate(m: &SourceMemento) -> bool {
    !(m.span.start_line == 0
        && m.span.start_col == 0
        && m.span.end_line == 0
        && m.span.end_col == 0)
}

fn has_source_cid(m: &SourceMemento) -> bool {
    !m.source_cid.is_empty() && m.source_cid.starts_with("blake3-")
}

/// Body-level self-locating: file + non-degenerate span + content-address CID.
fn assert_body_self_locating(level: &str, m: &SourceMemento) {
    assert!(has_file(m), "{level}: missing file");
    assert!(
        span_non_degenerate(m),
        "{level}: span must be non-degenerate for body locus (got {:?})",
        m.span
    );
    assert!(
        has_source_cid(m),
        "{level}: source_cid must pin content (got {:?})",
        m.source_cid
    );
    eprintln!(
        "RECEIPT wire self-locating level={level} file={} fn={} span={}:{}-{}:{} cid={}",
        m.file,
        m.source_function_name().unwrap_or(m.function_name.as_str()),
        m.span.start_line,
        m.span.start_col,
        m.span.end_line,
        m.span.end_col,
        &m.source_cid[..m.source_cid.len().min(24)]
    );
}

#[test]
fn enumerate_wire_mementos_are_self_locating_e2e() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_mathy(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    // --- source_files: file-only degenerate (protocol) ---
    let files = kit.source_files(&project).expect("source_files");
    assert!(!files.is_empty());
    for file in &files {
        let m = file.source_memento();
        assert!(has_file(m), "source_files must carry file");
        // No requirement for span/cid on whole-file locator
        eprintln!("RECEIPT wire source file-only memento file={}", m.file);
    }

    let mut n_body_sites = 0usize;
    let mut n_assertions = 0usize;
    let mut n_facts = 0usize;
    let mut n_universes = 0usize;
    let mut n_fn_contracts = 0usize;

    for file in &files {
        let file_m = file.source_memento();

        // --- functions ---
        for function in file.functions().expect("functions") {
            let fn_m = function.source_memento();
            assert!(has_file(fn_m));
            assert_eq!(fn_m.file, file_m.file, "function under parent file");
            let fn_name = fn_m
                .source_function_name()
                .unwrap_or(fn_m.function_name.as_str())
                .to_string();
            assert!(!fn_name.is_empty(), "function memento names a function");

            if span_non_degenerate(fn_m) && has_source_cid(fn_m) {
                // function-contract row with full warrant
                n_fn_contracts += 1;
                assert_body_self_locating("functions(contract)", fn_m);
            } else {
                // enclosing-only: file+name, degenerate span — still locates by name
                eprintln!(
                    "RECEIPT wire functions(enclosing-only) file={} fn={} (no body warrant)",
                    fn_m.file, fn_name
                );
            }

            // --- call_sites ---
            for site in function.call_sites().expect("call_sites") {
                let site_m = site.source_memento();
                assert_eq!(site_m.file, file_m.file, "site under parent file");
                // Nesting reconstructable: site names enclosing function when present
                if let Some(site_fn) = site_m.source_function_name() {
                    assert_eq!(
                        site_fn, fn_name,
                        "site function_name reconstructs parent nest"
                    );
                }
                assert_body_self_locating("call_sites", site_m);
                n_body_sites += 1;

                // --- universe (when linked) ---
                if let Some(universe) = site.universe().expect("universe") {
                    let u_m = universe.source_memento();
                    assert!(has_file(u_m), "universe memento has file");
                    // Universe is self-locating (function-contract warrant);
                    // linkage to site is tree structure, not shared path field.
                    if span_non_degenerate(u_m) && has_source_cid(u_m) {
                        assert_body_self_locating("universe", u_m);
                        n_universes += 1;
                    }
                }

                // --- assertions ---
                for assertion in site.assertions().expect("assertions") {
                    let a_m = assertion.source_memento();
                    assert_body_self_locating("assertions", a_m);
                    // Factory 1:1: same self-locating locus as site
                    assert_eq!(a_m.file, site_m.file);
                    assert_eq!(a_m.span, site_m.span);
                    assert_eq!(a_m.source_cid, site_m.source_cid);
                    n_assertions += 1;

                    // --- facts ---
                    for fact in assertion.facts().expect("facts") {
                        let f_m = fact.source_memento();
                        assert_body_self_locating("facts", f_m);
                        assert_eq!(f_m.file, a_m.file);
                        assert_eq!(f_m.span, a_m.span);
                        assert_eq!(f_m.source_cid, a_m.source_cid);
                        n_facts += 1;
                    }
                }
            }
        }
    }

    eprintln!(
        "RECEIPT enumerate_wire_self_locating counts: \
         body_sites={n_body_sites} assertions={n_assertions} facts={n_facts} \
         universes={n_universes} fn_contracts={n_fn_contracts}"
    );

    assert!(
        n_body_sites > 0,
        "expected body-level call sites with full memento"
    );
    assert!(n_assertions > 0, "expected assertions");
    assert!(n_facts > 0, "expected facts");
    assert!(n_universes > 0, "mathy must link at least one universe");
    assert!(
        n_fn_contracts > 0,
        "mathy must expose function-contract with cid"
    );
    assert_eq!(n_body_sites, n_assertions, "factory 1:1 site≡assertion");
}

#[test]
fn pair_call_site_wire_memento_has_cid_and_span() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = dir.path().join("project");
    fs::create_dir_all(&project).unwrap();
    fs::write(
        project.join("pair.py"),
        "def test_a():\n    assert len([1]) == 1\n",
    )
    .unwrap();
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");
    let files = kit.source_files(&project).expect("source_files");
    let mut found = false;
    for file in &files {
        for function in file.functions().expect("functions") {
            for site in function.call_sites().expect("call_sites") {
                assert_body_self_locating("call_sites", site.source_memento());
                found = true;
            }
        }
    }
    assert!(found, "pair.py must yield a self-locating call site");
}
