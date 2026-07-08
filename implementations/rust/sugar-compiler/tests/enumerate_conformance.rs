// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Part 6 conformance gates for the `sugar.enumerate` tree
// (`protocol/specs/2026-07-08-enumeration-protocol.md`), against a real
// spawned python kit (`sugar_lift_py_tests.lift_rpc`).
//
// Gate A -- fold == blob: folding the enumeration tree
// (`source_files -> functions -> call_sites -> assertions -> facts`) over
// the fixture must produce the SAME fact set (memento + formula content) as
// the existing whole-project `Kit::lift`'s `DomainClaim.payload` (the raw
// `ir` entries the lift RPC response embeds verbatim as `Term::Const`).
//
// Gate B -- scan/seek coherence: for every level, `plural()[i]` and
// `singular(plural()[i].memento)` must return a byte-identical node.
//
// Skips (not fails) when `python3`/`blake3` are unavailable, matching the
// existing `sugar-cli` python integration tests' convention
// (`python_blake3_available` in `sugar-cli/tests/cli_surface.rs`).

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::Dialect;
use serde_json::{json, Value};
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
        .map(|output| output.status.success())
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
        f.write_all(text.as_bytes())
            .unwrap_or_else(|e| panic!("write {}: {e}", path.display()));
        f.sync_all()
            .unwrap_or_else(|e| panic!("sync {}: {e}", path.display()));
    }
    #[cfg(unix)]
    {
        let mut perms = fs::metadata(path)
            .unwrap_or_else(|e| panic!("stat {}: {e}", path.display()))
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms)
            .unwrap_or_else(|e| panic!("chmod {}: {e}", path.display()));
    }
}

/// Spawn the shipping python kit (`sugar_lift_py_tests.lift_rpc`) via the
/// SAME `python3 -m sugar_lift_py_tests.lift_rpc --rpc` + `PYTHONPATH`
/// recipe `sugar-cli/tests/cli_surface.rs` already uses.
fn python_kit_manifest(dir: &Path) -> LiftManifest {
    let py_tests_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-py-tests")
        .join("src");
    let py_source_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-python-source")
        .join("src");
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
    }
}

fn stage_fixture(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(&project).expect("mkdir project");
    let fixture_src = repo_root()
        .join("implementations")
        .join("rust")
        .join("sugar-compiler")
        .join("tests")
        .join("fixtures")
        .join("enumerate_fixture")
        .join("mathy.py");
    fs::copy(&fixture_src, project.join("mathy.py")).expect("copy fixture");
    project
}

/// Serialize a `Value` with object keys sorted, so two JSON encodings of the
/// SAME structural content (which may insert object keys in a different
/// order -- e.g. the wire's raw dict order vs `serde_json::to_value`'s
/// struct-field order) compare byte-identical as strings.
fn canonical_string(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut entries: Vec<(&String, &Value)> = map.iter().collect();
            entries.sort_by(|a, b| a.0.cmp(b.0));
            let body = entries
                .iter()
                .map(|(k, v)| format!("{k:?}:{}", canonical_string(v)))
                .collect::<Vec<_>>()
                .join(",");
            format!("{{{body}}}")
        }
        Value::Array(items) => {
            let body = items
                .iter()
                .map(canonical_string)
                .collect::<Vec<_>>()
                .join(",");
            format!("[{body}]")
        }
        other => other.to_string(),
    }
}

/// Normalize a fact for order/container-insensitive comparison: (file,
/// span, formula-as-canonical-string).
fn fact_key(memento: &Value, formula: &Value) -> (String, String, String) {
    let file = memento
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let span = memento.get("span").cloned().unwrap_or(Value::Null);
    (file, canonical_string(&span), canonical_string(formula))
}

/// Extract the fact set from a whole-project `Kit::lift`'s
/// `DomainClaim.payload` (a `Term::Const{value, ..}` carrying the RPC
/// response's raw `ir` array verbatim -- see `kit_path/lift_plugin.rs`'s
/// `claim_from_response_term`).
fn facts_from_whole_project_lift(
    kit: &Kit,
    workspace_root: &Path,
) -> Vec<(String, String, String)> {
    let request = json!({
        "workspace_root": workspace_root.display().to_string(),
        "source_paths": ["."],
    });
    let claim = kit.lift(request).expect("Kit::lift");
    let value = match claim.payload {
        Some(libsugar::core::Term::Const { value, .. }) => value,
        other => panic!("expected Term::Const lift payload, got {other:?}"),
    };
    let ir = value
        .get("ir")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut out = Vec::new();
    for item in &ir {
        if item.get("kind").and_then(Value::as_str) != Some("contract") {
            continue;
        }
        let formula = item
            .get("inv")
            .filter(|v| !v.is_null())
            .or_else(|| item.get("post").filter(|v| !v.is_null()));
        let Some(formula) = formula else { continue };
        let warrants = item
            .get("sourceWarrants")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let Some(memento) = warrants.first() else {
            continue;
        };
        out.push(fact_key(memento, formula));
    }
    out.sort();
    out
}

/// Extract the SAME fact set by walking the enumeration tree end to end.
fn facts_from_tree(kit: &Kit, workspace_root: &Path) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
    for file in kit.source_files(workspace_root).expect("source_files") {
        for function in file.functions().expect("functions") {
            for call_site in function.call_sites().expect("call_sites") {
                for assertion in call_site.assertions().expect("assertions") {
                    for fact in assertion.facts().expect("facts") {
                        let memento_json = fact.source_memento().to_json();
                        let payload_json =
                            serde_json::to_value(fact.payload()).expect("encode IrFormula");
                        out.push(fact_key(&memento_json, &payload_json));
                    }
                }
            }
        }
    }
    out.sort();
    out
}

#[test]
fn enumeration_fold_matches_whole_project_lift() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping enumeration conformance test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let manifest = python_kit_manifest(dir.path());
    let kit = Kit::rendezvous(manifest).expect("rendezvous with python kit");

    let from_lift = facts_from_whole_project_lift(&kit, &project);
    let from_tree = facts_from_tree(&kit, &project);

    assert!(
        !from_lift.is_empty(),
        "fixture must produce at least one fact via Kit::lift"
    );
    assert_eq!(
        from_tree, from_lift,
        "enumeration tree's fact set must equal Kit::lift's fact set (fold == blob)"
    );
}

#[test]
fn scan_seek_coherence_at_every_level() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping scan/seek coherence test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let manifest = python_kit_manifest(dir.path());
    let kit = Kit::rendezvous(manifest).expect("rendezvous with python kit");

    // source_files: plural vs singular.
    let files = kit.source_files(&project).expect("source_files scan");
    assert!(
        !files.is_empty(),
        "fixture must have at least one source file"
    );
    for file in &files {
        let seeked = kit
            .source_file(&project, file.source_memento())
            .expect("source_file seek");
        assert_eq!(
            seeked.source_memento(),
            file.source_memento(),
            "source_files scan/seek coherence"
        );
    }

    // functions: plural vs singular, per file.
    for file in &files {
        let functions = file.functions().expect("functions scan");
        for function in &functions {
            let seeked = file
                .function(function.source_memento())
                .expect("function seek");
            assert_eq!(
                seeked.source_memento(),
                function.source_memento(),
                "functions scan/seek coherence"
            );
            assert_eq!(seeked.audit_row(), function.audit_row());

            // call_sites: plural vs singular, per function.
            let call_sites = function.call_sites().expect("call_sites scan");
            for call_site in &call_sites {
                let seeked_cs = function
                    .call_site(call_site.source_memento())
                    .expect("call_site seek");
                assert_eq!(
                    seeked_cs.source_memento(),
                    call_site.source_memento(),
                    "call_sites scan/seek coherence"
                );
                assert_eq!(seeked_cs.audit_row(), call_site.audit_row());

                // assertions: plural vs singular, per call site.
                let assertions = call_site.assertions().expect("assertions scan");
                for assertion in &assertions {
                    let seeked_assertion = call_site
                        .assertion(assertion.source_memento())
                        .expect("assertion seek");
                    assert_eq!(
                        seeked_assertion.source_memento(),
                        assertion.source_memento(),
                        "assertions scan/seek coherence"
                    );
                    assert_eq!(seeked_assertion.audit_row(), assertion.audit_row());

                    // facts: this level is seek-only in the granularity
                    // landed (an assertion's own memento IS the fact
                    // lookup key already -- Section 4 of the protocol
                    // spec). Coherence here means re-seeking through the
                    // freshly-seeked assertion node reproduces the same
                    // fact set as the originally-scanned assertion node.
                    let facts_from_scanned = assertion.facts().expect("facts via scanned node");
                    let facts_from_seeked =
                        seeked_assertion.facts().expect("facts via seeked node");
                    assert_eq!(
                        facts_from_scanned
                            .iter()
                            .map(|f| (f.source_memento().clone(), f.payload().clone()))
                            .collect::<Vec<_>>(),
                        facts_from_seeked
                            .iter()
                            .map(|f| (f.source_memento().clone(), f.payload().clone()))
                            .collect::<Vec<_>>(),
                        "facts scan/seek coherence"
                    );
                }
            }
        }
    }
}
