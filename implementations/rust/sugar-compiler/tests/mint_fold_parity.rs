// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Task 9 (#3809 / #3867): mint-produced claim shape vs fold_project construction.
//
// This is construction parity (not CLI cutover, not verdict discharge quality).
// Axes (measured R, both directions):
//   R_fact_fol_missing / R_fact_fol_extra
//       — (warrant file, span, inv|post FOL) from batch IR kind=contract
//         vs fold graph fact members
//   R_fact_name_missing / R_fact_name_extra
//       — IR contract `name` vs fold contractName (unique locus names)
//   R_fact_slot_missing / R_fact_slot_extra
//       — (name, slot∈{pre,post,inv}) presence pairs
//   R_universe_name_missing / R_universe_name_extra
//       — function-contract names
//   R_universe_formals_missing / R_universe_formals_extra
//       — (name, formals-joined) for function-contracts with formals
//   R_universe_body_missing / R_universe_body_extra
//       — (name, slot, FOL) for function-contract body slots
//
// Green only when construction carries mint-complete shape. Does NOT point
// CLI mint/prove at prove_from_kit. Pandas: skipped when no local lightweight
// fixture is available without external sugar-pandas-demo (enumerate hard-pinned).
//
// Skips (not fails) when python3/blake3 unavailable.

use std::collections::BTreeSet;
use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::Dialect;
use serde_json::{json, Value};
use sugar_compiler::feed_from_tree;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_proof_envelope::{typed_member::Member, ProofGraph};
use sugar_verifier::Speaker;

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

fn stage_enumerate_fixture(dir: &Path) -> PathBuf {
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

fn fact_key(memento: &Value, formula: &Value) -> (String, String, String) {
    let file = memento
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let span = memento.get("span").cloned().unwrap_or(Value::Null);
    (file, canonical_string(&span), canonical_string(formula))
}

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

// ── Mint IR extractors ─────────────────────────────────────────────────────

fn mint_fact_fols(payload: &Value) -> BTreeSet<(String, String, String)> {
    let mut out = BTreeSet::new();
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
        out.insert(fact_key(memento, formula));
    }
    out
}

fn mint_fact_names(payload: &Value) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for item in ir_items(payload) {
        if item.get("kind").and_then(Value::as_str) != Some("contract") {
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

fn mint_fact_slots(payload: &Value) -> BTreeSet<(String, String)> {
    let mut out = BTreeSet::new();
    for item in ir_items(payload) {
        if item.get("kind").and_then(Value::as_str) != Some("contract") {
            continue;
        }
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if name.is_empty() {
            continue;
        }
        for slot in ["pre", "post", "inv"] {
            if item.get(slot).is_some_and(|v| !v.is_null()) {
                out.insert((name.clone(), slot.to_string()));
            }
        }
    }
    out
}

fn mint_universe_names(payload: &Value) -> BTreeSet<String> {
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

fn mint_universe_formals(payload: &Value) -> BTreeSet<(String, String)> {
    let mut out = BTreeSet::new();
    for item in ir_items(payload) {
        if item.get("kind").and_then(Value::as_str) != Some("function-contract") {
            continue;
        }
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if name.is_empty() {
            continue;
        }
        let formals = item
            .get("formals")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect::<Vec<_>>()
                    .join(",")
            })
            .unwrap_or_default();
        // Only measure rows that declare formals (mint always does for fn-contracts).
        if item.get("formals").is_some() {
            out.insert((name, formals));
        }
    }
    out
}

fn mint_universe_bodies(payload: &Value) -> BTreeSet<(String, String, String)> {
    let mut out = BTreeSet::new();
    for item in ir_items(payload) {
        if item.get("kind").and_then(Value::as_str) != Some("function-contract") {
            continue;
        }
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if name.is_empty() {
            continue;
        }
        for slot in ["pre", "post", "inv"] {
            if let Some(formula) = item.get(slot).filter(|v| !v.is_null()) {
                out.insert((name.clone(), slot.to_string(), canonical_string(formula)));
            }
        }
    }
    out
}

// ── Fold graph extractors ──────────────────────────────────────────────────

/// Universe / function-contract members: formals present (Task 9 mint-complete
/// shape), or legacy name-shell keys (`…::callable`, `…::builtin-universe`).
/// Fact assertion names like `add#euf#…::assertion` contain `::` but are not
/// universes — do not classify them as such.
fn is_universe_member(c: &sugar_proof_envelope::typed_member::ContractMember) -> bool {
    if c.formals.is_some() {
        return true;
    }
    let name = c.contract_name.as_str();
    if name.ends_with("::assertion") || name.contains("#euf#") {
        return false;
    }
    name.contains("::callable")
        || name.contains("::builtin-universe")
        || name.ends_with("::universe")
}

fn fold_fact_fols(graph: &ProofGraph) -> BTreeSet<(String, String, String)> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
        if c.formals.is_some() {
            continue; // universe / function-contract
        }
        let formula = c
            .inv
            .as_ref()
            .filter(|v| !v.is_null())
            .cloned()
            .or_else(|| c.post.as_ref().filter(|v| !v.is_null()).cloned())
            .or_else(|| {
                graph
                    .contract_slot_json(&cid, "inv")
                    .or_else(|| graph.contract_slot_json(&cid, "post"))
            });
        let Some(formula) = formula else { continue };
        if let Some(warrants) = c.source_warrants.as_ref() {
            if let Some(memento) = warrants.first() {
                out.insert(fact_key(memento, &formula));
            }
        }
    }
    out
}

fn fold_fact_names(graph: &ProofGraph) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
        if c.formals.is_some() {
            continue;
        }
        // Assertion-shaped: has inv/post and warrants (or any non-universe name).
        let has_body = c.inv.as_ref().is_some_and(|v| !v.is_null())
            || c.post.as_ref().is_some_and(|v| !v.is_null())
            || graph.contract_slot_json(&cid, "inv").is_some()
            || graph.contract_slot_json(&cid, "post").is_some();
        if has_body {
            out.insert(c.contract_name.clone());
        }
    }
    out
}

fn fold_fact_slots(graph: &ProofGraph) -> BTreeSet<(String, String)> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
        if c.formals.is_some() {
            continue;
        }
        let name = &c.contract_name;
        for slot in ["pre", "post", "inv"] {
            let present = match slot {
                "pre" => {
                    c.pre.as_ref().is_some_and(|v| !v.is_null())
                        || graph.contract_slot_json(&cid, "pre").is_some()
                }
                "post" => {
                    c.post.as_ref().is_some_and(|v| !v.is_null())
                        || graph.contract_slot_json(&cid, "post").is_some()
                }
                "inv" => {
                    c.inv.as_ref().is_some_and(|v| !v.is_null())
                        || graph.contract_slot_json(&cid, "inv").is_some()
                }
                _ => false,
            };
            if present {
                out.insert((name.clone(), slot.to_string()));
            }
        }
    }
    out
}

fn fold_universe_names(graph: &ProofGraph) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
        if is_universe_member(c) {
            out.insert(c.contract_name.clone());
        }
    }
    out
}

fn fold_universe_formals(graph: &ProofGraph) -> BTreeSet<(String, String)> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
        if let Some(formals) = c.formals.as_ref() {
            out.insert((c.contract_name.clone(), formals.join(",")));
        }
    }
    out
}

fn fold_universe_bodies(graph: &ProofGraph) -> BTreeSet<(String, String, String)> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
        if !is_universe_member(c) {
            continue;
        }
        let name = &c.contract_name;
        for slot in ["pre", "post", "inv"] {
            let formula = match slot {
                "pre" => c
                    .pre
                    .as_ref()
                    .filter(|v| !v.is_null())
                    .cloned()
                    .or_else(|| graph.contract_slot_json(&cid, "pre")),
                "post" => c
                    .post
                    .as_ref()
                    .filter(|v| !v.is_null())
                    .cloned()
                    .or_else(|| graph.contract_slot_json(&cid, "post")),
                "inv" => c
                    .inv
                    .as_ref()
                    .filter(|v| !v.is_null())
                    .cloned()
                    .or_else(|| graph.contract_slot_json(&cid, "inv")),
                _ => None,
            };
            if let Some(formula) = formula {
                // Ignore pre-only true shells so residual shell debt stays named.
                if slot == "pre" {
                    if let Some(kind) = formula.get("kind").and_then(Value::as_str) {
                        if kind == "atomic"
                            && formula.get("name").and_then(Value::as_str) == Some("true")
                        {
                            continue;
                        }
                    }
                }
                out.insert((name.clone(), slot.to_string(), canonical_string(&formula)));
            }
        }
    }
    out
}

fn set_diff<T: Clone + Ord>(
    expected: &BTreeSet<T>,
    actual: &BTreeSet<T>,
) -> (BTreeSet<T>, BTreeSet<T>) {
    let missing = expected.difference(actual).cloned().collect();
    let extra = actual.difference(expected).cloned().collect();
    (missing, extra)
}

/// Primary instrument: mint IR claim shape vs fold_project on enumerate fixture.
#[test]
fn mint_fold_parity_enumerate_fixture() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping mint_fold_parity instrument");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_enumerate_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let mint_payload = whole_project_lift_payload(&kit, &project);
    let folded = feed_from_tree::fold_project(
        &kit,
        &project,
        Some(&Speaker::consumer("consumer:mint-fold-parity")),
    )
    .expect("fold_project");

    let mint_fol = mint_fact_fols(&mint_payload);
    let fold_fol = fold_fact_fols(&folded);
    let (fol_missing, fol_extra) = set_diff(&mint_fol, &fold_fol);

    let mint_names = mint_fact_names(&mint_payload);
    let fold_names = fold_fact_names(&folded);
    let (name_missing, name_extra) = set_diff(&mint_names, &fold_names);

    let mint_slots = mint_fact_slots(&mint_payload);
    let fold_slots = fold_fact_slots(&folded);
    let (slot_missing, slot_extra) = set_diff(&mint_slots, &fold_slots);

    let mint_u = mint_universe_names(&mint_payload);
    let fold_u = fold_universe_names(&folded);
    let (u_name_missing, u_name_extra) = set_diff(&mint_u, &fold_u);

    let mint_formals = mint_universe_formals(&mint_payload);
    let fold_formals = fold_universe_formals(&folded);
    let (formals_missing, formals_extra) = set_diff(&mint_formals, &fold_formals);

    let mint_bodies = mint_universe_bodies(&mint_payload);
    let fold_bodies = fold_universe_bodies(&folded);
    let (body_missing, body_extra) = set_diff(&mint_bodies, &fold_bodies);

    let r_fact_fol_missing = fol_missing.len();
    let r_fact_fol_extra = fol_extra.len();
    let r_fact_name_missing = name_missing.len();
    let r_fact_name_extra = name_extra.len();
    let r_fact_slot_missing = slot_missing.len();
    let r_fact_slot_extra = slot_extra.len();
    let r_universe_name_missing = u_name_missing.len();
    let r_universe_name_extra = u_name_extra.len();
    let r_universe_formals_missing = formals_missing.len();
    let r_universe_formals_extra = formals_extra.len();
    let r_universe_body_missing = body_missing.len();
    let r_universe_body_extra = body_extra.len();

    let r_total = r_fact_fol_missing
        + r_fact_fol_extra
        + r_fact_name_missing
        + r_fact_name_extra
        + r_fact_slot_missing
        + r_fact_slot_extra
        + r_universe_name_missing
        + r_universe_name_extra
        + r_universe_formals_missing
        + r_universe_formals_extra
        + r_universe_body_missing
        + r_universe_body_extra;

    eprintln!(
        "mint_fold_parity (enumerate fixture):\n\
         \tR_fact_fol_missing={r_fact_fol_missing} R_fact_fol_extra={r_fact_fol_extra}\n\
         \tR_fact_name_missing={r_fact_name_missing} R_fact_name_extra={r_fact_name_extra}\n\
         \tR_fact_slot_missing={r_fact_slot_missing} R_fact_slot_extra={r_fact_slot_extra}\n\
         \tR_universe_name_missing={r_universe_name_missing} R_universe_name_extra={r_universe_name_extra}\n\
         \tR_universe_formals_missing={r_universe_formals_missing} R_universe_formals_extra={r_universe_formals_extra}\n\
         \tR_universe_body_missing={r_universe_body_missing} R_universe_body_extra={r_universe_body_extra}\n\
         \tR_total={r_total}\n\
         \tmint_facts={} fold_facts={} mint_universes={} fold_universes={}\n\
         \tfol_missing={fol_missing:?}\n\
         \tfol_extra={fol_extra:?}\n\
         \tname_missing={name_missing:?}\n\
         \tname_extra={name_extra:?}\n\
         \tslot_missing={slot_missing:?}\n\
         \tslot_extra={slot_extra:?}\n\
         \tu_name_missing={u_name_missing:?}\n\
         \tu_name_extra={u_name_extra:?}\n\
         \tformals_missing={formals_missing:?}\n\
         \tformals_extra={formals_extra:?}\n\
         \tbody_missing={body_missing:?}\n\
         \tbody_extra={body_extra:?}",
        mint_fol.len(),
        fold_fol.len(),
        mint_u.len(),
        fold_u.len(),
    );

    assert!(
        !mint_fol.is_empty(),
        "fixture must produce at least one mint fact"
    );
    assert!(
        !mint_u.is_empty(),
        "fixture must produce at least one mint universe"
    );

    assert!(
        r_total == 0,
        "mint vs fold construction parity failed (Task 9).\n\
         Replacement: align graph_from_fact/graph_from_universe with mint IR→member\n\
         (unique names, post vs inv slots, real universe formals+body).\n\
         R_total={r_total}\n\
         R_fact_fol_missing={r_fact_fol_missing} R_fact_fol_extra={r_fact_fol_extra}\n\
         R_fact_name_missing={r_fact_name_missing} R_fact_name_extra={r_fact_name_extra}\n\
         R_fact_slot_missing={r_fact_slot_missing} R_fact_slot_extra={r_fact_slot_extra}\n\
         R_universe_name_missing={r_universe_name_missing} R_universe_name_extra={r_universe_name_extra}\n\
         R_universe_formals_missing={r_universe_formals_missing} R_universe_formals_extra={r_universe_formals_extra}\n\
         R_universe_body_missing={r_universe_body_missing} R_universe_body_extra={r_universe_body_extra}\n\
         name_missing={name_missing:?}\n\
         formals_missing={formals_missing:?}\n\
         body_missing={body_missing:?}"
    );
}

/// Pandas slice: only when a local in-repo showcase exists and pandas is
/// importable. Otherwise document skip and keep enumerate hard-pinned.
#[test]
fn mint_fold_parity_pandas_slice_or_skip() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping pandas mint_fold_parity");
        return;
    }
    // Lightweight local guard-shape fixture (no sugar-pandas-demo checkout).
    // Requires `import pandas` — skip if the package is not installed.
    let pandas_ok = Command::new("python3")
        .arg("-c")
        .arg("import pandas")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);
    if !pandas_ok {
        eprintln!(
            "mint_fold_parity pandas: SKIP — pandas not importable; \
             enumerate fixture is the hard pin (Task 9). \
             Install pandas or add a pandas-free local IR fixture to unskip."
        );
        return;
    }

    let local_fixture = repo_root()
        .join("examples")
        .join("python-guard-shapes")
        .join("test_empty_container_pandas_ok.py");
    if !local_fixture.is_file() {
        eprintln!(
            "mint_fold_parity pandas: SKIP — no local fixture at {}; \
             enumerate remains the hard pin.",
            local_fixture.display()
        );
        return;
    }

    let dir = tempfile::tempdir().expect("tempdir");
    let project = dir.path().join("project");
    fs::create_dir_all(&project).expect("mkdir");
    fs::copy(
        &local_fixture,
        project.join("test_empty_container_pandas_ok.py"),
    )
    .expect("copy pandas fixture");
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let mint_payload = whole_project_lift_payload(&kit, &project);
    let mint_fol = mint_fact_fols(&mint_payload);
    let mint_u = mint_universe_names(&mint_payload);
    if mint_fol.is_empty() && mint_u.is_empty() {
        eprintln!(
            "mint_fold_parity pandas: SKIP — local fixture lifted zero contracts \
             (likely no sugar for this surface yet); enumerate remains hard pin."
        );
        return;
    }

    let folded = feed_from_tree::fold_project(
        &kit,
        &project,
        Some(&Speaker::consumer("consumer:mint-fold-pandas")),
    )
    .expect("fold_project pandas slice");

    let fold_fol = fold_fact_fols(&folded);
    let (fol_missing, fol_extra) = set_diff(&mint_fol, &fold_fol);
    let mint_names = mint_fact_names(&mint_payload);
    let fold_names = fold_fact_names(&folded);
    let (name_missing, name_extra) = set_diff(&mint_names, &fold_names);
    let mint_u_set = mint_u;
    let fold_u = fold_universe_names(&folded);
    let (u_missing, u_extra) = set_diff(&mint_u_set, &fold_u);
    let mint_formals = mint_universe_formals(&mint_payload);
    let fold_formals = fold_universe_formals(&folded);
    let (formals_missing, formals_extra) = set_diff(&mint_formals, &fold_formals);
    let mint_bodies = mint_universe_bodies(&mint_payload);
    let fold_bodies = fold_universe_bodies(&folded);
    let (body_missing, body_extra) = set_diff(&mint_bodies, &fold_bodies);

    let r_total = fol_missing.len()
        + fol_extra.len()
        + name_missing.len()
        + name_extra.len()
        + u_missing.len()
        + u_extra.len()
        + formals_missing.len()
        + formals_extra.len()
        + body_missing.len()
        + body_extra.len();

    eprintln!(
        "mint_fold_parity (pandas local slice):\n\
         \tR_total={r_total}\n\
         \tfol_missing={} fol_extra={} name_missing={} name_extra={}\n\
         \tu_missing={} u_extra={} formals_missing={} body_missing={}",
        fol_missing.len(),
        fol_extra.len(),
        name_missing.len(),
        name_extra.len(),
        u_missing.len(),
        u_extra.len(),
        formals_missing.len(),
        body_missing.len(),
    );

    assert!(
        r_total == 0,
        "pandas mint vs fold construction parity failed.\n\
         R_total={r_total}\n\
         fol_missing={fol_missing:?}\n\
         name_missing={name_missing:?}\n\
         formals_missing={formals_missing:?}\n\
         body_missing={body_missing:?}"
    );
}
