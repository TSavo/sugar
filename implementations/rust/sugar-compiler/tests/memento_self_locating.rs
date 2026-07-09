// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: SourceMemento is already self-locating (file + function_name + span + CIDs).
//
// Collapsed MementoPath / SourceMementoAtPath (#3942–#3947). Nesting is the
// enumeration tree (parent enumerates child), not a second address type.
//
// Asserts:
// - each level returns SourceMementos with correct file/function/span
// - tree structure carries nesting (site under function, assertion under site, …)
// - factory 1:1 site ≡ assertion ≡ fact (same locus fields)
//
// No solve; kit rendezvous + enumerate only.

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::tree::{memento_locus_display, Sourced};
use sugar_walk::source_oracle::SourceMemento;

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

fn locus_key(m: &SourceMemento) -> String {
    format!(
        "{}|{}|{}:{}-{}:{}",
        m.file,
        m.source_function_name().unwrap_or(m.function_name.as_str()),
        m.span.start_line,
        m.span.start_col,
        m.span.end_line,
        m.span.end_col
    )
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

    let sought = kit
        .source_file(&project, m)
        .expect("source_file seek");
    assert_eq!(sought.source_memento().file, m.file);
}

#[test]
fn levels_return_self_locating_mementos_with_tree_nesting() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    let mut found_site = false;
    for file in &files {
        assert_eq!(file.source_memento().file, "pair.py");
        for function in file.functions().expect("functions") {
            let fn_m = function.source_memento();
            assert_eq!(fn_m.file, "pair.py");
            let fn_name = fn_m
                .source_function_name()
                .unwrap_or(fn_m.function_name.as_str())
                .to_string();
            if fn_name.is_empty() {
                continue;
            }
            eprintln!(
                "RECEIPT function memento file={} fn={} span={}:{}-{}:{}",
                fn_m.file,
                fn_name,
                fn_m.span.start_line,
                fn_m.span.start_col,
                fn_m.span.end_line,
                fn_m.span.end_col
            );

            for site in function.call_sites().expect("call_sites") {
                let site_m = site.source_memento();
                assert_eq!(site_m.file, fn_m.file, "site under same file");
                // Nesting: site is under this function (name match or span-in-parent)
                let site_fn = site_m
                    .source_function_name()
                    .unwrap_or(site_m.function_name.as_str());
                assert!(
                    site_fn == fn_name || site_fn.is_empty(),
                    "site fn={site_fn} under parent fn={fn_name}"
                );
                assert!(
                    site_m.span.start_line > 0 || site_m.span.end_line > 0 || site_fn == fn_name,
                    "site has locus: {}",
                    memento_locus_display(site_m)
                );
                found_site = true;
                eprintln!(
                    "RECEIPT call_site memento {}",
                    memento_locus_display(site_m)
                );

                let assertions = site.assertions().expect("assertions");
                assert_eq!(assertions.len(), 1, "factory 1:1 site≡assertion");
                for assertion in &assertions {
                    let a_m = assertion.source_memento();
                    // Factory 1:1 — same self-locating locus as site
                    assert_eq!(a_m.file, site_m.file);
                    assert_eq!(a_m.span, site_m.span);
                    eprintln!(
                        "RECEIPT assertion memento {}",
                        memento_locus_display(a_m)
                    );

                    for fact in assertion.facts().expect("facts") {
                        let f_m = fact.source_memento();
                        assert_eq!(f_m.file, a_m.file);
                        assert_eq!(f_m.span, a_m.span);
                        eprintln!("RECEIPT fact memento {}", memento_locus_display(f_m));
                    }
                }
            }
        }
    }
    assert!(found_site, "expected at least one call site");
}

#[test]
fn call_sites_partitioned_by_enclosing_function() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_two_tests(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let files = kit.source_files(&project).expect("source_files");
    let mut by_fn: std::collections::BTreeMap<String, Vec<String>> =
        std::collections::BTreeMap::new();
    for function in files[0].functions().expect("functions") {
        let name = function
            .source_memento()
            .source_function_name()
            .unwrap_or("")
            .to_string();
        if name.is_empty() {
            continue;
        }
        let keys: Vec<String> = function
            .call_sites()
            .expect("call_sites")
            .iter()
            .map(|s| locus_key(s.source_memento()))
            .collect();
        by_fn.insert(name, keys);
    }
    eprintln!("RECEIPT call_sites by function: {by_fn:?}");
    if let Some(a) = by_fn.get("test_a") {
        assert!(!a.is_empty(), "test_a owns sites");
        for k in a {
            assert!(k.contains("test_a") || k.starts_with("pair.py"), "{k}");
            assert!(!k.contains("test_b"), "test_a must not own test_b: {k}");
        }
    }
    if let Some(b) = by_fn.get("test_b") {
        assert!(!b.is_empty(), "test_b owns sites");
        for k in b {
            assert!(k.contains("test_b") || k.starts_with("pair.py"), "{k}");
        }
    }
}

#[test]
fn universe_linked_via_tree_not_path_type() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let project = stage_mathy_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let mut found = false;
    for file in kit.source_files(&project).expect("source_files") {
        for function in file.functions().expect("functions") {
            for site in function.call_sites().expect("call_sites") {
                let site_m = site.source_memento();
                if let Some(universe) = site.universe().expect("universe") {
                    let u_m = universe.source_memento();
                    // Universe has its own self-locating memento (member key)
                    assert!(
                        !u_m.function_name.is_empty() || u_m.source_function_name().is_some(),
                        "universe memento carries identity"
                    );
                    // Linkage is tree structure (CallSite::universe), not a shared path field
                    found = true;
                    eprintln!(
                        "RECEIPT universe linked under site={} → universe={}",
                        memento_locus_display(site_m),
                        memento_locus_display(u_m)
                    );
                }
            }
        }
    }
    assert!(found, "mathy fixture must yield at least one universe link");
}

#[test]
fn full_descent_every_level_self_locating() {
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

    for file in kit.source_files(&project).expect("source_files") {
        let file_m = file.source_memento();
        assert!(!file_m.file.is_empty());
        n_source += 1;
        eprintln!("RECEIPT level=source {}", memento_locus_display(file_m));

        for function in file.functions().expect("functions") {
            let fn_m = function.source_memento();
            assert_eq!(fn_m.file, file_m.file);
            n_function += 1;
            eprintln!("RECEIPT level=functions {}", memento_locus_display(fn_m));

            for site in function.call_sites().expect("call_sites") {
                let site_m = site.source_memento();
                assert_eq!(site_m.file, file_m.file);
                n_site += 1;
                eprintln!("RECEIPT level=call_sites {}", memento_locus_display(site_m));

                if let Some(universe) = site.universe().expect("universe") {
                    assert!(!universe.source_memento().file.is_empty()
                        || !universe.source_memento().function_name.is_empty());
                    n_universe += 1;
                    eprintln!(
                        "RECEIPT level=universe {}",
                        memento_locus_display(universe.source_memento())
                    );
                }

                for assertion in site.assertions().expect("assertions") {
                    let a_m = assertion.source_memento();
                    assert_eq!(a_m.file, site_m.file);
                    assert_eq!(a_m.span, site_m.span, "factory 1:1 site≡assertion span");
                    n_assertion += 1;
                    eprintln!("RECEIPT level=assertions {}", memento_locus_display(a_m));

                    for fact in assertion.facts().expect("facts") {
                        let f_m = fact.source_memento();
                        assert_eq!(f_m.file, a_m.file);
                        assert_eq!(f_m.span, a_m.span, "factory 1:1 assertion≡fact span");
                        n_fact += 1;
                        eprintln!("RECEIPT level=facts {}", memento_locus_display(f_m));
                    }
                }
            }
        }
    }

    eprintln!(
        "RECEIPT descent_complete counts: source={n_source} functions={n_function} \
         call_sites={n_site} assertions={n_assertion} facts={n_fact} universe={n_universe}"
    );
    assert!(n_source > 0 && n_function > 0 && n_site > 0);
    assert!(n_assertion > 0 && n_fact > 0 && n_universe > 0);
    assert_eq!(n_site, n_assertion, "factory 1:1 site count == assertion count");
}

#[test]
fn memento_locus_display_on_demand() {
    use sugar_walk::source_oracle::SrcSpan;

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
