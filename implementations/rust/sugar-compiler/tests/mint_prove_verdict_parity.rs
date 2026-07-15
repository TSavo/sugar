// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Task 9 (#3809): mint+prove **verdict** parity with prove_from_kit.
//
// Construction parity is mint_fold_parity (R_total=0). This instrument pins
// **discharge row status multiset**:
//   mint side  = CLI `sugar mint` → sealed `.proof` → `solve_project` (disk)
//   fold side  = `prove_from_kit` over the same sources
// Status multisets must match. Labels (property names) may only get more
// correct — not asserted equal.
//
// Note: production `sugar prove` may itself route through prove_from_kit
// (Task 9 face cutover). The mint half of this instrument deliberately uses
// disk `solve_project` so we compare mint-constructed members vs fold, not
// CLI prove vs itself.
//
// Skips when python3/blake3, z3, or the sugar CLI binary is unavailable.

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
use sugar_compiler::orchestrate::{prove_from_kit, solve_project};
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
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

/// Locate a built `sugar` CLI binary (workspace target or CARGO_BIN_EXE).
fn sugar_bin() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("CARGO_BIN_EXE_sugar") {
        let pb = PathBuf::from(p);
        if pb.is_file() {
            return Some(pb);
        }
    }
    let repo = repo_root();
    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    let output = Command::new(repo.join("bin/sugarbin"))
        .arg("--profile")
        .arg(profile)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let path = String::from_utf8(output.stdout).ok()?;
    let path = PathBuf::from(path.trim());
    path.is_file().then_some(path)
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

fn stage_enumerate_project(dir: &Path) -> PathBuf {
    let project = dir.join("project");
    fs::create_dir_all(project.join(".sugar/lift/python")).expect("mkdir lift");
    let fixture_src = repo_root()
        .join("implementations")
        .join("rust")
        .join("sugar-compiler")
        .join("tests")
        .join("fixtures")
        .join("enumerate_fixture")
        .join("mathy.py");
    fs::copy(&fixture_src, project.join("mathy.py")).expect("copy fixture");

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
    let plugin = dir.join("python-lift.sh");
    write_executable(
        &plugin,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );

    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"
emit = "ir-document"
"#,
    )
    .expect("config");
    fs::write(
        project.join(".sugar/lift/python/manifest.toml"),
        format!(
            "name = \"python-lift\"\ncommand = [\"{}\"]\nworking_dir = \".\"\n",
            plugin.display()
        ),
    )
    .expect("manifest");

    project
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
    let script = dir.join("kit-python-lift.sh");
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

/// Status multiset: map status string → count (order-independent).
fn status_multiset_from_strs(
    statuses: impl IntoIterator<Item = String>,
) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    for s in statuses {
        *m.entry(s).or_default() += 1;
    }
    m
}

/// Mint via CLI into `project`, then discharge the sealed `.proof` via
/// production `solve_project` (disk load — not CLI prove, which may fold).
fn mint_disk_solve_status_multiset(sugar: &Path, project: &Path) -> BTreeMap<String, usize> {
    let mint = Command::new(sugar)
        .arg("mint")
        .arg("--project")
        .arg(project)
        .arg("--out")
        .arg(project)
        .arg("--json")
        .arg("--quiet")
        .current_dir(project)
        .output()
        .expect("spawn sugar mint");
    assert!(
        mint.status.success(),
        "sugar mint failed:\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&mint.stdout),
        String::from_utf8_lossy(&mint.stderr)
    );

    let proofs: Vec<_> = walkdir_proofs(project);
    assert!(
        !proofs.is_empty(),
        "sugar mint must write at least one .proof under {}",
        project.display()
    );

    let proven = solve_project(runner_cfg(project), test_compilers())
        .expect("solve_project over mint .proofs");
    status_multiset_from_strs(
        proven
            .artifact
            .report
            .rows
            .iter()
            .map(|row| row.status.as_str().to_string()),
    )
}

fn walkdir_proofs(project: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![project.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|e| e.to_str()) == Some("proof") {
                out.push(p);
            }
        }
    }
    out
}

fn prove_from_kit_status_multiset(kit_dir: &Path, project: &Path) -> BTreeMap<String, usize> {
    let kit = Kit::rendezvous(python_kit_manifest(kit_dir)).expect("rendezvous");
    let speaker = Speaker::consumer("mint-prove-verdict-parity:consumer");
    let proven = prove_from_kit(
        &kit,
        project,
        speaker,
        runner_cfg(project),
        test_compilers(),
    )
    .expect("prove_from_kit");
    status_multiset_from_strs(
        proven
            .artifact
            .report
            .rows
            .iter()
            .map(|row| row.status.as_str().to_string()),
    )
}

/// Task 9 discharge gate: mint+prove status multiset ≡ prove_from_kit.
#[test]
fn mint_prove_verdict_parity_enumerate_fixture() {
    if !python_blake3_available() {
        eprintln!("skip: python3/blake3 unavailable");
        return;
    }
    if !z3_available() {
        eprintln!("skip: z3 unavailable");
        return;
    }
    let Some(sugar) = sugar_bin() else {
        eprintln!(
            "skip: sugar CLI binary not found under target/{{debug,release}}/sugar \
             (build sugar-cli first for mint+prove face of this instrument)"
        );
        return;
    };

    let dir = tempfile::tempdir().expect("tempdir");
    let project = stage_enumerate_project(dir.path());

    let mint_statuses = mint_disk_solve_status_multiset(&sugar, &project);
    let kit_statuses = prove_from_kit_status_multiset(dir.path(), &project);

    let mint_total: usize = mint_statuses.values().sum();
    let kit_total: usize = kit_statuses.values().sum();

    // Measured R: absolute multiset distance + cardinality gap.
    let mut all_keys: std::collections::BTreeSet<_> = mint_statuses.keys().cloned().collect();
    all_keys.extend(kit_statuses.keys().cloned());
    let mut r_status_diff = 0usize;
    for k in &all_keys {
        let a = mint_statuses.get(k).copied().unwrap_or(0);
        let b = kit_statuses.get(k).copied().unwrap_or(0);
        r_status_diff += a.abs_diff(b);
    }
    let r_row_count = mint_total.abs_diff(kit_total);
    let r_total = r_status_diff + r_row_count;

    eprintln!(
        "mint_prove_verdict_parity (enumerate fixture):\n\
         \tmint_status_multiset={mint_statuses:?}\n\
         \tkit_status_multiset={kit_statuses:?}\n\
         \tmint_rows={mint_total} kit_rows={kit_total}\n\
         \tR_status_diff={r_status_diff} R_row_count={r_row_count} R_total={r_total}"
    );

    assert_eq!(
        mint_statuses, kit_statuses,
        "Task 9 verdict parity: CLI mint+prove status multiset must equal \
         prove_from_kit (labels may differ; statuses must not).\n\
         R_total={r_total} R_status_diff={r_status_diff} R_row_count={r_row_count}\n\
         mint={mint_statuses:?}\n\
         kit={kit_statuses:?}\n\
         replacement: emit mint-complete bridges (PR-23 auto-bridge from \
         bridgeSourceSymbol; callEdges→bridges) in feed_from_tree so fold \
         discharge joins universes the same way mint does"
    );
    assert!(
        mint_total > 0,
        "enumerate fixture must produce at least one prove row"
    );
}
