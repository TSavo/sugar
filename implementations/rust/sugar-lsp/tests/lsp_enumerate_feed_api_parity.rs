// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809 golden: LSP feed(buffer) verdict rows == API enumerate→solve rows.
//
// Proves the unification: `solve_buffer` (enumerate→fold→one-solve) produces
// the same status multiset / sorted `row_to_json` wire blobs as
// `prove_from_kit` (the CLI/API composition) over the same staged surface.
//
// Byte-identical where both paths discharge the same pool shape. Skips when
// python3+blake3 (kit rendezvous) or z3 is unavailable.

use std::collections::BTreeMap;
use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use libsugar::core::Dialect;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::orchestrate::prove_from_kit;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_verifier::report::row_to_json;
use sugar_verifier::{LegacyZ3Fallback, RunnerConfig, Speaker};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .expect("repo root")
}

fn python_blake3_available() -> bool {
    Command::new("python3")
        .arg("-c")
        .arg("import blake3")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
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
        f.write_all(text.as_bytes()).expect("write");
        f.sync_all().expect("sync");
    }
    #[cfg(unix)]
    {
        let mut perms = fs::metadata(path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod");
    }
}

fn python_kit_manifest(dir: &Path) -> LiftManifest {
    let py_tests_src = repo_root().join("implementations/python/sugar-lift-py-tests/src");
    let py_source_src = repo_root().join("implementations/python/sugar-lift-python-source/src");
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

fn stage_enumerate_fixture(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(&project).expect("mkdir project");
    let fixture_src = repo_root()
        .join("implementations/rust/sugar-compiler/tests/fixtures/enumerate_fixture/mathy.py");
    fs::copy(&fixture_src, project.join("mathy.py")).expect("copy mathy.py");

    // Project config + lift manifest for LSP rendezvous (same kit as API).
    fs::create_dir_all(project.join(".sugar")).expect("mkdir .sugar");
    fs::write(
        project.join(".sugar/config.toml"),
        "[[plugins]]\nsurface = \"python\"\n",
    )
    .expect("config.toml");
    let lift_dir = project.join(".sugar/lift/python");
    fs::create_dir_all(&lift_dir).expect("mkdir lift");
    let py_tests_src = repo_root().join("implementations/python/sugar-lift-py-tests/src");
    let py_source_src = repo_root().join("implementations/python/sugar-lift-python-source/src");
    let wrapper = lift_dir.join("python-lift.sh");
    write_executable(
        &wrapper,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );
    fs::write(
        lift_dir.join("manifest.toml"),
        format!(
            "name = \"python\"\ncommand = [\"/bin/sh\", \"{}\"]\nworking_dir = \".\"\n",
            wrapper.display()
        ),
    )
    .expect("manifest.toml");

    project
}

fn test_compilers() -> CompilerRegistry {
    let mut compilers = CompilerRegistry::new();
    compilers.register(Arc::new(sugar_ir_compiler_smt_lib::SmtLibCompiler::new()));
    compilers
}

fn runner_cfg(project_root: &Path) -> RunnerConfig {
    RunnerConfig {
        project_root: project_root.to_path_buf(),
        legacy_z3_fallback: Some(LegacyZ3Fallback::compat("z3")),
        ..Default::default()
    }
}

/// Sorted status multiset from row_to_json wire rows.
fn status_multiset(rows: &[serde_json::Value]) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    for row in rows {
        let status = row
            .get("status")
            .or_else(|| row.get("verdict"))
            .and_then(|v| v.as_str())
            .unwrap_or("?")
            .to_string();
        *m.entry(status).or_default() += 1;
    }
    m
}

/// Redact face-stamped packaging CIDs that differ only by who sealed the
/// feed envelope (`Speaker` id → `ProofEnvelopeInput.name` → proof CID).
///
/// Claim FOL, property CIDs, statuses, loci, and linkedPosts join keys stay.
/// `linkedPosts[].targetProofCid` is the sealed proof package CID — LSP seals
/// as `sugar-lsp`, API/`prove_from_kit` seals as `sugar-cli:prove` — not a
/// composition divergence.
fn redact_face_stamps(mut row: serde_json::Value) -> serde_json::Value {
    if let Some(posts) = row
        .pointer_mut("/verification/linkedPosts")
        .and_then(|v| v.as_array_mut())
    {
        for post in posts {
            if let Some(obj) = post.as_object_mut() {
                if obj.contains_key("targetProofCid") {
                    obj.insert(
                        "targetProofCid".to_string(),
                        serde_json::json!("<face-stamped-proof-cid>"),
                    );
                }
            }
        }
    }
    row
}

/// Sorted row_to_json blobs (canonical golden surface after face-stamp redact).
fn sorted_row_blobs(rows: &[serde_json::Value]) -> Vec<String> {
    let mut blobs: Vec<String> = rows
        .iter()
        .map(|r| serde_json::to_string(&redact_face_stamps(r.clone())).expect("serialize row"))
        .collect();
    blobs.sort();
    blobs
}

/// Status multiset from a ProvenOutcome report (API path).
fn api_status_multiset(
    proven: &sugar_compiler::orchestrate::ProvenOutcome,
) -> BTreeMap<String, usize> {
    let rows: Vec<_> = proven
        .artifact
        .report
        .rows
        .iter()
        .map(|row| row_to_json(row))
        .collect();
    status_multiset(&rows)
}

fn api_sorted_blobs(proven: &sugar_compiler::orchestrate::ProvenOutcome) -> Vec<String> {
    let rows: Vec<_> = proven
        .artifact
        .report
        .rows
        .iter()
        .map(|row| row_to_json(row))
        .collect();
    sorted_row_blobs(&rows)
}

#[test]
fn lsp_feed_buffer_rows_match_api_enumerate_solve() {
    if !python_blake3_available() {
        eprintln!("skip: python3+blake3 unavailable for kit rendezvous");
        return;
    }
    if !z3_available() {
        eprintln!("skip: z3 unavailable");
        return;
    }

    let tmp = tempfile::tempdir().expect("tempdir");
    let project = stage_enumerate_fixture(tmp.path());
    let source = fs::read_to_string(project.join("mathy.py")).expect("read mathy.py");
    let file = project.join("mathy.py");

    // --- API path: prove_from_kit (enumerate→fold→solve_project_with_pool) ---
    let kit_dir = tmp.path().join("kit-stage");
    fs::create_dir_all(&kit_dir).expect("kit-stage");
    let manifest = python_kit_manifest(&kit_dir);
    let kit = Kit::rendezvous(manifest).expect("rendezvous python kit");
    let speaker = Speaker::consumer("sugar-cli:prove");
    let cfg = runner_cfg(&project);
    let compilers = test_compilers();
    let proven = prove_from_kit(&kit, &project, speaker, cfg, compilers)
        .expect("prove_from_kit must discharge enumerate fixture");
    let api_statuses = api_status_multiset(&proven);
    let api_blobs = api_sorted_blobs(&proven);
    assert!(
        !api_statuses.is_empty(),
        "API path must produce at least one verdict row"
    );

    // --- LSP path: solve_buffer (same feed door + resident-base solve) ---
    let ctx = sugar_lsp::prove_engine::build_prove_context_for(&project);
    let outcome = sugar_lsp::prove_engine::solve_buffer(&ctx, &file, &source);
    assert!(
        !outcome.degraded,
        "LSP feed must not degrade: {:?}",
        outcome.degraded_reason
    );
    assert!(
        !outcome.rows.is_empty(),
        "LSP path must produce at least one verdict row"
    );
    let lsp_statuses = status_multiset(&outcome.rows);
    let lsp_blobs = sorted_row_blobs(&outcome.rows);

    assert_eq!(
        lsp_statuses, api_statuses,
        "status multiset must match\n  LSP={lsp_statuses:?}\n  API={api_statuses:?}"
    );
    assert_eq!(
        lsp_blobs,
        api_blobs,
        "row_to_json wire blobs must be byte-identical (sorted)\n  LSP count={}\n  API count={}",
        lsp_blobs.len(),
        api_blobs.len()
    );
}
