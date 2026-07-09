// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Campaign B red instrument: tree-fold feed must match the claim set the
// enumerate walk (and batch mint IR) already knows about the fixture.
//
// Axes (Task 6 green):
//   R_feed_fact_missing     — fold graph missing fact FOL keys from the tree
//   R_feed_universe_missing — fold graph missing universe member names
//   R_feed_members          — fold graph claim-contract member count
//
// Door: `feed_from_tree::{graph_from_fact, graph_from_universe,
// fold_claim_tree}` builds the same member content mint builds for
// kind=contract / function-contract rows, then `ProofGraph::feed` merges.
//
// Skips (not fails) when python3/blake3 are unavailable.

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
use sugar_compiler::tree::Sourced;
use sugar_proof_envelope::{ProofGraph, typed_member::Member};
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

/// Serialize a `Value` with object keys sorted for order-insensitive compare.
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

/// Fact key: (file, span, formula) — same shape as enumerate_conformance.
fn fact_key(memento: &Value, formula: &Value) -> (String, String, String) {
    let file = memento
        .get("file")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let span = memento.get("span").cloned().unwrap_or(Value::Null);
    (file, canonical_string(&span), canonical_string(formula))
}

/// Expected fact FOL set by walking the enumeration tree (Campaign A floor).
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

/// Expected universe names from successful `CallSite::universe()` links.
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

/// Whole-project `Kit::lift` payload — today's mint IR source of truth.
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

/// Fact FOL keys from batch mint IR (`kind=contract` inv/post + warrants).
/// This is the content mint would load into claim-contract members.
fn facts_from_mint_ir(payload: &Value) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
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
        out.push(fact_key(memento, formula));
    }
    out.sort();
    out
}

/// Universe names from batch mint IR (`kind=function-contract`).
fn universes_from_mint_ir(payload: &Value) -> BTreeSet<String> {
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

/// Claim-contract fact FOL keys recovered from a folded `ProofGraph`.
///
/// Mint-with-bodyCid embeds pre/post/inv in the graph body map, not the
/// layered header, so recovery prefers header inv|post then falls back to
/// `ProofGraph::contract_slot_json` for the body-linked atom.
/// Keys use (warrant file, warrant span, inv|post formula) when warrants
/// exist; otherwise (contract_name, "", formula).
fn facts_from_feed_graph(graph: &ProofGraph) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        let Member::Contract(c) = member.as_ref() else {
            continue;
        };
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
                out.push(fact_key(memento, &formula));
                continue;
            }
        }
        // No warrant — count under contract name (partial / universe-shaped).
        out.push((
            c.contract_name.clone(),
            String::new(),
            canonical_string(&formula),
        ));
    }
    out.sort();
    out
}

/// Universe / function-contract names recovered from fold graph members.
/// Task 6 stamps batch universe keys onto `contract_name` (e.g.
/// `mathy::add::callable`, `len::builtin-universe`).
fn universes_from_feed_graph(graph: &ProofGraph) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for (cid, member_res) in graph.typed_members_iter() {
        let member = match member_res {
            Ok(m) => m,
            Err(e) => panic!("typed member {cid:?}: {e}"),
        };
        match member.as_ref() {
            Member::Contract(c) => {
                // function-contract rows mint as contracts whose name is the
                // universe member key (e.g. `mathy::add::callable`). Without
                // a distinct kind on the typed path yet, Task 6 uses
                // contract_name; accept names that look like universe keys.
                if c.contract_name.contains("::") {
                    out.insert(c.contract_name.clone());
                }
            }
            _ => {}
        }
    }
    out
}

fn member_cids(graph: &ProofGraph) -> BTreeSet<String> {
    graph
        .members()
        .map(|(cid, _)| cid.as_str().to_string())
        .collect()
}

/// Walk facts (+ universes), fold via `feed_from_tree`, compare claim FOL /
/// universe names to mint IR on the same fixture (Campaign B green).
#[test]
fn walk_and_feed_matches_minted_member_cids() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping feed_from_tree instrument");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    // Floor from Campaign A: tree walk and batch mint IR agree on facts +
    // universes. The feed fold must match that same set.
    let tree_facts = facts_from_tree(&kit, &project);
    let tree_universes = universes_from_tree(&kit, &project);
    let mint_payload = whole_project_lift_payload(&kit, &project);
    let mint_facts = facts_from_mint_ir(&mint_payload);
    let mint_universes = universes_from_mint_ir(&mint_payload);

    assert!(
        !tree_facts.is_empty(),
        "fixture must produce at least one fact via enumerate tree walk"
    );
    assert_eq!(
        tree_facts, mint_facts,
        "precondition: tree facts must equal mint-IR facts (Campaign A floor)"
    );
    assert!(
        !tree_universes.is_empty(),
        "fixture must produce at least one universe via CallSite::universe()"
    );
    assert_eq!(
        tree_universes, mint_universes,
        "precondition: tree universes must equal mint-IR function-contract names"
    );

    // The door under test: tree → ProofGraph via feed.
    // Speaker is typed through fold_project for pool intake (Task 7); graph
    // content is unchanged — stamp happens in pool_from_graph_with_speaker.
    let folded = feed_from_tree::fold_project(
        &kit,
        &project,
        Some(&Speaker::consumer("consumer:test")),
    )
    .expect("fold_project");
    let folded_alias = feed_from_tree::fold_claim_tree(&kit, &project).expect("fold_claim_tree");
    assert_eq!(
        member_cids(&folded),
        member_cids(&folded_alias),
        "fold_project and fold_claim_tree must be the same door"
    );

    let feed_facts = facts_from_feed_graph(&folded);
    let feed_universes = universes_from_feed_graph(&folded);
    let feed_member_cids = member_cids(&folded);

    let expected_facts: BTreeSet<_> = mint_facts.iter().cloned().collect();
    let actual_facts: BTreeSet<_> = feed_facts.iter().cloned().collect();
    let missing_facts: BTreeSet<_> = expected_facts.difference(&actual_facts).cloned().collect();
    let extra_facts: BTreeSet<_> = actual_facts.difference(&expected_facts).cloned().collect();

    let missing_universes: BTreeSet<_> = mint_universes
        .difference(&feed_universes)
        .cloned()
        .collect();

    let r_feed_fact_missing = missing_facts.len();
    let r_feed_universe_missing = missing_universes.len();
    let r_feed_members = feed_member_cids.len();

    eprintln!(
        "feed_from_tree instrument:\n\
         \tR_feed_fact_missing={r_feed_fact_missing}\n\
         \tR_feed_universe_missing={r_feed_universe_missing}\n\
         \tR_feed_members={r_feed_members}\n\
         \texpected_facts={}\n\
         \tactual_facts={}\n\
         \tmissing_facts={missing_facts:?}\n\
         \textra_facts={extra_facts:?}\n\
         \texpected_universes={mint_universes:?}\n\
         \tactual_universes={feed_universes:?}\n\
         \tmissing_universes={missing_universes:?}\n\
         \tmember_cids={feed_member_cids:?}",
        expected_facts.len(),
        actual_facts.len(),
    );

    assert!(
        r_feed_fact_missing == 0 && extra_facts.is_empty() && r_feed_universe_missing == 0,
        "feed fold must match mint IR claim set.\n\
         R_feed_fact_missing={r_feed_fact_missing}\n\
         R_feed_universe_missing={r_feed_universe_missing}\n\
         R_feed_members={r_feed_members}\n\
         missing_facts={missing_facts:?}\n\
         extra_facts={extra_facts:?}\n\
         missing_universes={missing_universes:?}"
    );
    assert!(
        r_feed_members >= expected_facts.len(),
        "fold must emit at least one member per fact (got {r_feed_members}, facts {})",
        expected_facts.len()
    );
}

/// Unit: `graph_from_fact` returns a fragment whose inv slot matches the
/// fact payload (Task 6 green; replaces the Task 5 NotImplemented pin).
#[test]
fn graph_from_fact_builds_claim_fragment() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping graph_from_fact unit check");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");

    let mut first_fact = None;
    'outer: for file in kit.source_files(&project).expect("source_files") {
        for function in file.functions().expect("functions") {
            for call_site in function.call_sites().expect("call_sites") {
                for assertion in call_site.assertions().expect("assertions") {
                    for fact in assertion.facts().expect("facts") {
                        first_fact = Some(fact);
                        break 'outer;
                    }
                }
            }
        }
    }
    let fact = first_fact.expect("fixture must yield at least one fact");
    let fragment = feed_from_tree::graph_from_fact(&fact).expect("graph_from_fact");
    let keys = facts_from_feed_graph(&fragment);
    assert_eq!(
        keys.len(),
        1,
        "single fact must yield exactly one claim FOL key, got {keys:?}"
    );
    let payload_json = serde_json::to_value(fact.payload()).expect("encode IrFormula");
    let expected = fact_key(&fact.source_memento().to_json(), &payload_json);
    assert_eq!(keys[0], expected, "fragment FOL must match fact payload+warrant");
    eprintln!("R_graph_from_fact=0 — fragment members={:?}", member_cids(&fragment));
}
