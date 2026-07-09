// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Task 8 (#3809): `prove_from_kit` folds the enumerate claim tree + optional
// vendor testimony into a multi-speaker pool and discharges via the production
// solve beats (`solve_project_with_pool` / Runner).
//
// Gate (this harness, not full mint CLI parity — Task 9):
//   1. fold_project → pool_from_graph_with_speaker stamps consumer on every
//      local member
//   2. prove_from_kit runs the solver path (when z3 is available)
//   3. report row statuses match seal-to-temp + solve_project over the same
//      local folded graph (disk load vs preloaded-pool face; no vendor)
//
// Skips when python3/blake3 unavailable (kit rendezvous) or z3 missing
// (solver path). Batch mint is NOT deleted.

use std::collections::BTreeSet;
use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use libsugar::core::Dialect;
use sugar_compiler::feed_from_tree;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::orchestrate::{
    pool_from_graph_with_speaker, prove_from_kit, solve_project, solve_project_with_pool,
};
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_proof_envelope::{build_proof_envelope, ProofEnvelopeInput, ProofGraph};
use sugar_verifier::types::SpeakerRole;
use sugar_verifier::{LegacyZ3Fallback, RunnerConfig, Speaker};

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

/// Sorted (property_name, status) pairs from a prove artifact — the gate
/// surface for fold→pool solve vs disk solve_project (member envelope CIDs
/// may differ across re-seal paths; verdict rows are the contract).
fn report_verdict_keys(
    proven: &sugar_compiler::orchestrate::ProvenOutcome,
) -> Vec<(String, String)> {
    let mut keys: Vec<_> = proven
        .artifact
        .report
        .rows
        .iter()
        .map(|row| {
            (
                row.callsite.property_name.clone(),
                format!("{:?}", row.status),
            )
        })
        .collect();
    keys.sort();
    keys
}

/// Seal a graph to a throwaway `.proof` under `dir` (same self-load seed
/// family as pool_from_graph_with_speaker, but written for disk `load_pool`).
fn seal_graph_to_project(graph: &ProofGraph, dir: &Path, name: &str) {
    const SEED: [u8; 32] = [0x53; 32];
    let input = ProofEnvelopeInput {
        name: name.to_string(),
        version: "1.0.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph: graph.clone(),
        signer_cid: sugar_proof_envelope::ed25519_pubkey_string(&SEED),
        signer_seed: SEED,
        declared_at: "1970-01-01T00:00:00.000Z".to_string(),
        manifest: None,
    };
    let sealed = build_proof_envelope(&input);
    let stem = sealed.cid.replace(':', "_");
    fs::write(dir.join(format!("{stem}.proof")), &sealed.bytes).expect("write sealed proof");
}

/// Intermediate gate: fold + consumer pool intake stamps every member
/// Consumer, and fold yields at least one claim member on the fixture.
#[test]
fn fold_project_loads_with_consumer_speaker() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");
    let speaker = Speaker::consumer("prove-from-kit:consumer");

    let graph = feed_from_tree::fold_project(&kit, &project, Some(&speaker)).expect("fold_project");
    assert!(
        graph.members().count() > 0,
        "enumerate fixture must fold at least one claim member"
    );

    let pool = pool_from_graph_with_speaker(&graph, speaker.clone()).expect("pool load");
    // Multiple facts under the same function name (`test_add`) are distinct
    // claim members (different FOL / CIDs). The pool's name→cid index records
    // that as load_errors but still indexes every memento — not a signature
    // or staging failure. Only hard graph-read / signature rejects would
    // empty the member set.
    let hard_load_errors: Vec<_> = pool
        .load_errors
        .iter()
        .filter(|e| !e.reason.contains("duplicate contract name"))
        .collect();
    assert!(
        hard_load_errors.is_empty(),
        "local fold must not hard-fail pool load (signature/graph): {hard_load_errors:?}"
    );
    assert_eq!(
        pool.mementos.len(),
        graph.members().count(),
        "every folded member must land in the pool (name collisions annotate, they do not drop mementos); errors={:?}",
        pool.load_errors
    );

    for cid in pool.mementos.keys() {
        let s = pool
            .member_speaker(cid)
            .unwrap_or_else(|| panic!("member {cid} must be attributed at intake"));
        assert_eq!(
            s.role,
            SpeakerRole::Consumer,
            "local fold members must stamp Consumer (got {s:?} on {cid})"
        );
        assert_eq!(s.id, "prove-from-kit:consumer");
    }
}

/// Full door: prove_from_kit discharges the enumerate fixture; verdict rows
/// match solve_project_with_pool over the same consumer pool (identity of
/// the thin face vs the preloaded-pool beats).
#[test]
fn prove_from_kit_runs_solver_path_on_enumerate_fixture() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    if !z3_available() {
        eprintln!("skip: z3 unavailable (solver path)");
        return;
    }

    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_fixture(dir.path());
    let kit = Kit::rendezvous(python_kit_manifest(dir.path())).expect("rendezvous");
    let speaker = Speaker::consumer("prove-from-kit:consumer");
    let cfg = runner_cfg(&project);
    let compilers = test_compilers();

    let proven = prove_from_kit(
        &kit,
        &project,
        speaker.clone(),
        cfg.clone(),
        compilers.clone(),
    )
    .expect("prove_from_kit must stage + discharge the enumerate fixture");

    eprintln!(
        "prove_from_kit instrument:\n\
         \toutcome_class={:?}\n\
         \treport_rows={}\n\
         \tload_errors={}\n\
         \tlink_errors={}\n\
         \tlink_derivation_error={:?}\n\
         \texit_code={}",
        proven.outcome_class,
        proven.artifact.report.rows.len(),
        proven.artifact.report.load_errors.len(),
        proven.link_errors.len(),
        proven.link_derivation_error,
        proven.outcome_class.exit_code(),
    );

    // Production path always returns an artifact (annotate-not-block).
    // Fixture may be Undecided/Verified depending on ambient discharge;
    // what we pin is that the door ran end-to-end over the folded pool.

    // Same local pool, same beats: prove_from_kit without vendor must match
    // explicit fold → pool_from_graph_with_speaker → solve_project_with_pool.
    let local = feed_from_tree::fold_project(&kit, &project, Some(&speaker)).expect("fold");
    let pool = pool_from_graph_with_speaker(&local, speaker.clone()).expect("pool");
    let direct = solve_project_with_pool(cfg.clone(), compilers.clone(), pool)
        .expect("solve_project_with_pool");

    assert_eq!(
        proven.outcome_class, direct.outcome_class,
        "prove_from_kit (local-only; testimony unavailable on py-tests kit) must \
         match explicit fold→pool→solve_project_with_pool"
    );
    assert_eq!(
        report_verdict_keys(&proven),
        report_verdict_keys(&direct),
        "report verdict rows must match the explicit preloaded-pool path"
    );

    // Disk face over the same sealed local graph: seal → solve_project must
    // agree on verdict row statuses (member content, not envelope CID).
    let disk_dir = tempfile::tempdir().expect("disk project");
    seal_graph_to_project(&local, disk_dir.path(), "enumerate-local");
    let disk_proven =
        solve_project(runner_cfg(disk_dir.path()), compilers).expect("solve_project disk");

    let from_kit_statuses: BTreeSet<_> = report_verdict_keys(&proven)
        .into_iter()
        .map(|(_, status)| status)
        .collect();
    let disk_statuses: BTreeSet<_> = report_verdict_keys(&disk_proven)
        .into_iter()
        .map(|(_, status)| status)
        .collect();

    eprintln!(
        "disk parity:\n\
         \tfrom_kit_rows={}\n\
         \tdisk_rows={}\n\
         \tfrom_kit_status_set={from_kit_statuses:?}\n\
         \tdisk_status_set={disk_statuses:?}\n\
         \tdisk_outcome={:?}",
        proven.artifact.report.rows.len(),
        disk_proven.artifact.report.rows.len(),
        disk_proven.outcome_class,
    );

    // Same local claim set → same status multiset is the near-term gate.
    // Full property-name identity with mint-produced .proofs is Task 9.
    assert_eq!(
        proven.outcome_class, disk_proven.outcome_class,
        "preloaded-pool prove_from_kit and disk solve_project over the same \
         sealed fold graph must classify the same"
    );
    assert_eq!(
        report_verdict_keys(&proven),
        report_verdict_keys(&disk_proven),
        "verdict rows (property_name, status) must match disk solve_project \
         over the same folded local graph"
    );
}

/// Multi-speaker residual of Task 7: when a second graph is loaded as vendor
/// and merged, roles stay distinct through solve_project_with_pool (no second map).
#[test]
fn multi_speaker_pool_survives_solve_project_with_pool() {
    if !z3_available() {
        eprintln!("skip: z3 unavailable");
        return;
    }

    let fixture = |name: &str| -> ProofGraph {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("implementations/rust")
            .join("sugar-proof-envelope/tests/fixtures")
            .join(name);
        let bytes = fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
        ProofGraph::read(&bytes).unwrap_or_else(|e| panic!("read graph: {e}"))
    };

    let vendor = Speaker::vendor("the-vendor");
    let consumer = Speaker::consumer("me");
    let mut pool =
        pool_from_graph_with_speaker(&fixture("base64_vendor.proof"), vendor).expect("vendor");
    pool.merge(
        pool_from_graph_with_speaker(&fixture("base64_consumer.proof"), consumer)
            .expect("consumer"),
    );

    let mut vendor_n = 0usize;
    let mut consumer_n = 0usize;
    for cid in pool.mementos.keys() {
        match pool.member_speaker(cid).map(|s| s.role) {
            Some(SpeakerRole::Vendor) => vendor_n += 1,
            Some(SpeakerRole::Consumer) => consumer_n += 1,
            None => panic!("unattributed {cid}"),
        }
    }
    assert!(
        vendor_n > 0 && consumer_n > 0,
        "need both roles before solve"
    );

    let dir = tempfile::tempdir().expect("temp project root");
    let proven = solve_project_with_pool(runner_cfg(dir.path()), test_compilers(), pool)
        .expect("solve_project_with_pool over multi-speaker pool");

    // Attribution is pool state; discharge must not panic/drop the pool.
    // Outcome class is free (fixtures may be residue/undecided).
    eprintln!(
        "multi_speaker solve: outcome={:?} rows={} vendors={vendor_n} consumers={consumer_n}",
        proven.outcome_class,
        proven.artifact.report.rows.len(),
    );
}
