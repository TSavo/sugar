// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Part 6 conformance gates for the `sugar.enumerate` tree
// (`protocol/specs/2026-07-08-enumeration-protocol.md`), against a real
// spawned python kit (`sugar_lift_py_tests.lift_rpc`).
//
// Gate A -- fold == blob (Campaign A floor): folding the enumeration tree
// over the fixture must match whole-project `Kit::lift` IR for:
//   - facts (inv/post formulas + warrants)
//   - universes (`kind="function-contract"` member names)
//   - bridge_source_symbols (`call:` / `method:` identities)
// Fold path: source_files → functions → call_sites →
//   (assertions → facts | universe | bridge_source_symbol).
//
// Gate B -- scan/seek coherence: for every level, `plural()[i]` and
// `singular(plural()[i].memento)` must return a byte-identical node.
//
// Skips (not fails) when `python3`/`blake3` are unavailable, matching the
// existing `sugar-cli` python integration tests' convention
// (`python_blake3_available` in `sugar-cli/tests/cli_surface.rs`).

use std::collections::BTreeSet;
use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::Dialect;
use serde_json::{json, Value};
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::kit_path::LiftTermTable;
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
        method: None,
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

/// Whole-project `Kit::lift` payload as JSON (`DomainClaim.payload` Const).
fn whole_project_lift_payload(kit: &Kit, workspace_root: &Path) -> Value {
    let request = json!({
        "workspace_root": workspace_root.display().to_string(),
        "source_paths": ["."],
    });
    let claim = kit.lift(request).expect("Kit::lift");
    match claim.payload {
        Some(libsugar::core::Term::Const { value, .. }) => value,
        other => panic!("expected Term::Const lift payload, got {other:?}"),
    }
}

fn ir_items(payload: &Value) -> Vec<Value> {
    payload
        .get("ir")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn is_bridge_identity(sym: &str) -> bool {
    sym.starts_with("call:") || sym.starts_with("method:")
}

/// Fact set from batch `payload.ir` kind=contract inv/post + warrants.
fn facts_from_blob(payload: &Value) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
    let term_table = LiftTermTable::decode(payload).expect("batch term table");
    for item in ir_items(payload) {
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
        let resolved = term_table
            .resolve_value(formula)
            .expect("batch fact refs resolve at the IrFormula boundary");
        out.push(fact_key(memento, &resolved));
    }
    out.sort();
    out
}

/// Universe member names from batch `kind="function-contract"` rows.
fn universes_from_blob(payload: &Value) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for item in ir_items(payload) {
        if item.get("kind").and_then(Value::as_str) != Some("function-contract") {
            continue;
        }
        if let Some(name) = item.get("name").and_then(Value::as_str) {
            if !name.is_empty() {
                out.insert(name.to_string());
            }
        }
    }
    out
}

/// First-class `call:` / `method:` identities from batch IR + callEdges.
fn bridge_source_symbols_from_blob(payload: &Value) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for item in ir_items(payload) {
        if let Some(sym) = item.get("bridgeSourceSymbol").and_then(Value::as_str) {
            if is_bridge_identity(sym) {
                out.insert(sym.to_string());
            }
        }
    }
    if let Some(edges) = payload.get("callEdges").and_then(Value::as_array) {
        for edge in edges {
            if let Some(sym) = edge.get("targetSymbol").and_then(Value::as_str) {
                if is_bridge_identity(sym) {
                    out.insert(sym.to_string());
                }
            }
        }
    }
    out
}

/// Fact set by walking the enumeration tree end to end.
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

/// Universe member names folded from successful `CallSite::universe()` links.
/// Uses stamped `SourceMemento.function_name` (batch contract `name`).
fn universes_from_tree(kit: &Kit, workspace_root: &Path) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for file in kit.source_files(workspace_root).expect("source_files") {
        for function in file.functions().expect("functions") {
            for call_site in function.call_sites().expect("call_sites") {
                if let Ok(Some(universe)) = call_site.universe() {
                    let name = universe.source_memento().function_name.clone();
                    if !name.is_empty() {
                        out.insert(name);
                    }
                }
            }
        }
    }
    out
}

/// First-class bridge identities folded from `CallSite.bridge_source_symbol`.
fn bridge_source_symbols_from_tree(kit: &Kit, workspace_root: &Path) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for file in kit.source_files(workspace_root).expect("source_files") {
        for function in file.functions().expect("functions") {
            for call_site in function.call_sites().expect("call_sites") {
                if let Some(sym) = call_site.bridge_source_symbol() {
                    if is_bridge_identity(sym) {
                        out.insert(sym.to_string());
                    }
                }
            }
        }
    }
    out
}

/// Campaign A floor: fold of enumerate levels equals batch IR for
/// facts + universes + bridge_source_symbols (not inv/post only).
fn assert_fold_matches_blob(kit: &Kit, project: &Path) {
    let payload = whole_project_lift_payload(kit, project);

    let facts_blob = facts_from_blob(&payload);
    let facts_fold = facts_from_tree(kit, project);
    assert!(
        !facts_blob.is_empty(),
        "fixture must produce at least one fact via Kit::lift"
    );
    assert_eq!(
        facts_fold, facts_blob,
        "fold facts must equal blob facts (fold == blob)"
    );

    let universes_blob = universes_from_blob(&payload);
    let universes_fold = universes_from_tree(kit, project);
    assert!(
        !universes_blob.is_empty(),
        "fixture must produce at least one function-contract / universe via Kit::lift"
    );
    assert_eq!(
        universes_fold, universes_blob,
        "fold universes must equal blob function-contract names (fold == blob). \
         fold={universes_fold:?} blob={universes_blob:?}"
    );

    let idents_blob = bridge_source_symbols_from_blob(&payload);
    let idents_fold = bridge_source_symbols_from_tree(kit, project);
    assert!(
        !idents_blob.is_empty(),
        "fixture must produce at least one call:/method: bridge symbol via Kit::lift"
    );
    assert_eq!(
        idents_fold, idents_blob,
        "fold bridge_source_symbols must equal blob identities (fold == blob). \
         fold={idents_fold:?} blob={idents_blob:?}"
    );

    eprintln!(
        "fold==blob ok: facts={} universes={universes_fold:?} \
         bridge_source_symbols={idents_fold:?}",
        facts_fold.len()
    );
}

#[test]
fn enumeration_fold_matches_whole_project_lift() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping enumeration conformance test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");
    assert_fold_matches_blob(&kit, &project);
}

/// Same floor under the `enumerate_` filter prefix used by Campaign A CI.
#[test]
fn enumerate_fold_matches_batch_facts_universes_identities() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping enumeration conformance test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");
    assert_fold_matches_blob(&kit, &project);
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

                let registry = sugar_linker::Registry::new();
                let plan = sugar_linker::solver_api::SolverPlan::Single(
                    sugar_linker::solver_api::SolverSeat::Z3,
                );
                let implication = call_site
                    .implication(&registry, &plan)
                    .expect("implication demand must answer one node");
                assert_eq!(
                    implication.audit_row().get("kind").and_then(Value::as_str),
                    Some("implication")
                );
                assert!(
                    matches!(
                        implication
                            .audit_row()
                            .get("status")
                            .and_then(Value::as_str),
                        Some("discharged" | "failed" | "unjoined")
                    ),
                    "implication demand must return a named disposition"
                );

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
