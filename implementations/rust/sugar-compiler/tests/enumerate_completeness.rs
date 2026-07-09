// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Campaign A / Task 0 — RED instrument: `sugar.enumerate` is incomplete vs
// the old batch `Kit::lift` drive.
//
// Measures remaining work `R` for:
//   R_universe_not_modeled — CallSite::universe() returns NotModeled while
//                            batch IR carries matching function-contract /
//                            builtin-universe rows
//   R_universe_missing     — fold of enumerate levels does not surface the
//                            universe member names present in batch payload.ir
//   R_identity_missing     — batch bridge symbols (`call:len`, `method:…`)
//                            are not first-class on the tree's call-site
//                            audit / memento (ambiguous bare names do not count)
//
// Stays red until Campaign A closes those gaps. Skips (not fails) when
// python3/blake3 are unavailable — same convention as enumerate_conformance.

use std::collections::BTreeSet;
use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::Dialect;
use serde_json::{json, Value};
use sugar_compiler::kit::{Kit, KitError, LiftManifest};
use sugar_compiler::tree::{EnumerateError, Sourced};

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

/// Whole-project `Kit::lift` payload as JSON (`DomainClaim.payload` Const value).
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

/// Universe rows from batch IR: `kind="function-contract"` (body/operator
/// universes, including `len::builtin-universe`). Name is the member key.
fn universe_names_from_batch_ir(payload: &Value) -> BTreeSet<String> {
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

/// Bridge / identity symbols batch IR exposes for join (`call:…` / `method:…`).
/// Sourced from function-contract `bridgeSourceSymbol` and callEdges `targetSymbol`.
fn identity_symbols_from_batch(payload: &Value) -> BTreeSet<String> {
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

fn is_bridge_identity(sym: &str) -> bool {
    sym.starts_with("call:") || sym.starts_with("method:")
}

fn is_universe_not_modeled(err: &KitError) -> bool {
    matches!(
        err,
        KitError::Enumerate(EnumerateError::NotModeled {
            level: "universe",
            ..
        })
    )
}

/// Walk the tree; for every call site, try `universe()`. Collects
/// NotModeled hits and any universe **member names** that succeed.
/// Names are function-contract style (`len::builtin-universe`,
/// `mathy::add::callable`), not bridge identities. `Ok(None)` is a
/// legitimate gap (no universe sugar for that callee), not NotModeled.
fn universe_probe_from_tree(
    kit: &Kit,
    workspace_root: &Path,
) -> (usize /* call_sites */, usize /* not_modeled */, BTreeSet<String>) {
    let mut call_sites = 0usize;
    let mut not_modeled = 0usize;
    let mut names = BTreeSet::new();
    for file in kit.source_files(workspace_root).expect("source_files") {
        for function in file.functions().expect("functions") {
            for call_site in function.call_sites().expect("call_sites") {
                call_sites += 1;
                match call_site.universe() {
                    Ok(Some(universe)) => {
                        // Member names must match batch function-contract
                        // `name` keys. Collect from memento JSON including
                        // non-bridge name strings (stamped `function_name` /
                        // `source_function_name` / any string equal to a
                        // batch universe name). Do NOT filter through
                        // is_bridge_identity — those are call:/method: forms
                        // for failure mode 3 only.
                        collect_universe_member_name_strings(
                            &universe.source_memento().to_json(),
                            &mut names,
                        );
                    }
                    Ok(None) => {
                        // Legitimate gap: call site has no linked universe.
                    }
                    Err(err) if is_universe_not_modeled(&err) => {
                        not_modeled += 1;
                    }
                    Err(err) => panic!(
                        "CallSite::universe unexpected error (not NotModeled): {err}"
                    ),
                }
            }
        }
    }
    (call_sites, not_modeled, names)
}

/// First-class identity strings visible on a tree call-site node: audit
/// fields + memento JSON values that are already `call:` / `method:` forms.
/// Does NOT dig into fact FOL for EUF ctor heads — those are formula shape,
/// not call-site bridge identity (Task 2 / Campaign A).
fn identity_symbols_from_tree(kit: &Kit, workspace_root: &Path) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for file in kit.source_files(workspace_root).expect("source_files") {
        for function in file.functions().expect("functions") {
            for call_site in function.call_sites().expect("call_sites") {
                collect_bridge_identity_strings(&call_site.source_memento().to_json(), &mut out);
                if let Some(audit) = call_site.audit_row() {
                    for candidate in [
                        audit.selected.as_deref(),
                        audit.reason.as_deref(),
                        Some(audit.requested_role.as_str()),
                        Some(audit.ast_kind.as_str()),
                        Some(audit.status.as_str()),
                        Some(audit.verdict.as_str()),
                    ]
                    .into_iter()
                    .flatten()
                    {
                        if is_bridge_identity(candidate) {
                            out.insert(candidate.to_string());
                        }
                    }
                }
            }
        }
    }
    out
}

/// Universe member-name candidates from a successful `Universe` memento.
///
/// Matches the same keys batch uses (`function-contract` `name` values like
/// `len::builtin-universe`). Collects:
/// - explicit name-ish object fields Task 1 may populate (`name`,
///   `function_name`, `source_function_name`, `universe_name`, `member_name`)
/// - every non-empty string leaf in the memento JSON (so a dedicated field
///   or nested audit still greening `R_universe_missing` without rewriting
///   this instrument)
///
/// Intentionally does **not** apply `is_bridge_identity` — bridge `call:` /
/// `method:` strings are failure mode 3 only.
fn collect_universe_member_name_strings(value: &Value, out: &mut BTreeSet<String>) {
    const NAME_KEYS: &[&str] = &[
        "name",
        "function_name",
        "source_function_name",
        "universe_name",
        "member_name",
    ];
    match value {
        Value::String(s) if !s.is_empty() => {
            out.insert(s.clone());
        }
        Value::Array(items) => {
            for item in items {
                collect_universe_member_name_strings(item, out);
            }
        }
        Value::Object(map) => {
            for key in NAME_KEYS {
                if let Some(s) = map.get(*key).and_then(Value::as_str) {
                    if !s.is_empty() {
                        out.insert(s.to_string());
                    }
                }
            }
            for v in map.values() {
                collect_universe_member_name_strings(v, out);
            }
        }
        _ => {}
    }
}

/// Walk JSON for `call:` / `method:` bridge identity strings only.
fn collect_bridge_identity_strings(value: &Value, out: &mut BTreeSet<String>) {
    match value {
        Value::String(s) if is_bridge_identity(s) => {
            out.insert(s.clone());
        }
        Value::Array(items) => {
            for item in items {
                collect_bridge_identity_strings(item, out);
            }
        }
        Value::Object(map) => {
            for v in map.values() {
                collect_bridge_identity_strings(v, out);
            }
        }
        _ => {}
    }
}

/// Failure mode 1: `CallSite::universe()` is `NotModeled` while batch IR
/// contains function-contract / builtin-universe rows for the fixture.
#[test]
fn enumerate_universe_level_not_modeled_while_batch_has_universes() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping enumerate completeness test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let payload = whole_project_lift_payload(&kit, &project);
    let batch_universes = universe_names_from_batch_ir(&payload);
    assert!(
        !batch_universes.is_empty(),
        "fixture must produce at least one function-contract / universe row via Kit::lift; got ir={:?}",
        ir_items(&payload)
            .iter()
            .map(|i| i.get("kind").cloned())
            .collect::<Vec<_>>()
    );
    assert!(
        batch_universes.iter().any(|n| n.contains("builtin-universe")
            || n.contains("::callable")
            || n.contains("universe")),
        "expected a builtin-universe or body-callable universe in batch, got {batch_universes:?}"
    );

    let (call_sites, not_modeled, tree_names) = universe_probe_from_tree(&kit, &project);
    assert!(
        call_sites > 0,
        "fixture must enumerate at least one call site"
    );

    let r_universe_not_modeled = not_modeled;
    eprintln!(
        "R_universe_not_modeled={r_universe_not_modeled} \
         (call_sites={call_sites}, batch_universes={batch_universes:?}, tree_names={tree_names:?})"
    );
    assert_eq!(
        r_universe_not_modeled, 0,
        "CallSite::universe() must not be NotModeled when batch IR has universe rows. \
         R_universe_not_modeled={r_universe_not_modeled} (of {call_sites} call sites). \
         Batch universe names: {batch_universes:?}. \
         Replacement: serve sugar.enumerate level=universe from function-contract IR \
         and implement CallSite::universe via enumerate_rpc (Campaign A Task 1)."
    );
}

/// Failure mode 2: fold of enumerate levels misses universe member names
/// that batch `payload.ir` already carries.
#[test]
fn enumerate_fold_missing_batch_universe_member_names() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping enumerate completeness test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let payload = whole_project_lift_payload(&kit, &project);
    let batch_universes = universe_names_from_batch_ir(&payload);
    assert!(
        !batch_universes.is_empty(),
        "fixture must produce batch universe member names"
    );

    let (_call_sites, _not_modeled, tree_universes) = universe_probe_from_tree(&kit, &project);
    let missing: BTreeSet<_> = batch_universes
        .difference(&tree_universes)
        .cloned()
        .collect();
    let r_universe_missing = missing.len();
    eprintln!(
        "R_universe_missing={r_universe_missing} missing={missing:?} \
         batch={batch_universes:?} tree={tree_universes:?}"
    );
    assert!(
        missing.is_empty(),
        "enumerate fold must include every batch IR universe member name. \
         R_universe_missing={r_universe_missing} missing={missing:?}. \
         Batch={batch_universes:?} tree={tree_universes:?}. \
         Replacement: level=universe nodes named from function-contract rows; \
         fold source_files→…→universe equals blob IR universe set (Campaign A)."
    );
}

/// Failure mode 3: batch emits first-class `call:` / `method:` bridge
/// symbols; the tree call-site audit/memento does not carry them yet.
#[test]
fn enumerate_callsite_identity_carries_bridge_symbol() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping enumerate completeness test");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let payload = whole_project_lift_payload(&kit, &project);
    let batch_idents = identity_symbols_from_batch(&payload);
    // Fixture must pin at least one of the plan's explicit examples.
    let required: BTreeSet<String> = batch_idents
        .iter()
        .filter(|s| {
            s.as_str() == "call:len"
                || s.as_str() == "method:sum"
                || s.starts_with("method:")
                || s.starts_with("call:")
        })
        .cloned()
        .collect();
    assert!(
        required.iter().any(|s| s == "call:len" || s == "method:sum" || s.starts_with("method:")),
        "fixture batch IR must emit call:len and/or a method:… bridge symbol \
         (plan: method:sum or call:len); got batch_idents={batch_idents:?}"
    );

    let tree_idents = identity_symbols_from_tree(&kit, &project);
    let missing: BTreeSet<_> = required.difference(&tree_idents).cloned().collect();
    let r_identity_missing = missing.len();
    eprintln!(
        "R_identity_missing={r_identity_missing} missing={missing:?} \
         batch={batch_idents:?} tree={tree_idents:?}"
    );
    assert!(
        missing.is_empty(),
        "tree call-site audit/memento must carry batch bridge symbols \
         (call:/method: forms — not bare names). \
         R_identity_missing={r_identity_missing} missing={missing:?}. \
         Batch={batch_idents:?} tree={tree_idents:?}. \
         Replacement: put bridgeSourceSymbol on enumerate call_sites audit and \
         decode CallSite.bridge_source_symbol (Campaign A Task 2)."
    );
}
