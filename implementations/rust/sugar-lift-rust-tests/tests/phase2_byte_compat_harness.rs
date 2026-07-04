// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Phase 2 effect-router byte-compat harness hook (#3292).
//
// The IrTerm boundary campaign owns the reusable shell harness. Phase 2 reuses
// it with a named case set instead of forking another cmp/SHA script.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-lift-rust-tests has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn temp_root(label: &str) -> PathBuf {
    let root =
        std::env::temp_dir().join(format!("phase2-byte-compat-{label}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).expect("create temp root");
    root
}

fn write_fake_sugar(path: &Path, lift_ok: bool) {
    let lift_json = if lift_ok {
        r#"{"case":"lift","ok":true}"#
    } else {
        r#"{"case":"lift","ok":false}"#
    };
    let script = format!(
        r#"#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  verify) printf '%s\n' '{{"case":"verify","ok":true}}' ;;
  prove) printf '%s\n' '{{"case":"prove","ok":true}}' ;;
  lift) printf '%s\n' '{lift_json}' ;;
  *) exit 2 ;;
esac
"#
    );
    fs::write(path, script).expect("write fake sugar");
    let mut perms = fs::metadata(path)
        .expect("fake sugar metadata")
        .permissions();
    perms.set_mode(0o755);
    fs::set_permissions(path, perms).expect("chmod fake sugar");
}

#[test]
fn phase2_case_set_reports_zero_drift_and_selected_case_detects_drift() {
    let root = temp_root("case-selector");
    let project = root.join("project");
    let out = root.join("out");
    fs::create_dir_all(&project).expect("create project");
    let baseline = root.join("sugar-baseline");
    let changed = root.join("sugar-changed");
    write_fake_sugar(&baseline, true);
    write_fake_sugar(&changed, true);

    let script = repo_root().join("tools/irterm-boundary/byte-compat.sh");
    let zero = Command::new(&script)
        .args([
            "--project-root",
            project.to_str().unwrap(),
            "--baseline-sugar",
            baseline.to_str().unwrap(),
            "--changed-sugar",
            changed.to_str().unwrap(),
            "--out-dir",
            out.to_str().unwrap(),
            "--label",
            "phase2-zero",
            "--case-set",
            "phase2-effect-routers",
        ])
        .output()
        .unwrap_or_else(|err| panic!("run {} phase2 case set: {err}", script.display()));
    println!(
        "phase2 byte-compat zero stdout:\n{}",
        String::from_utf8_lossy(&zero.stdout)
    );
    assert!(
        zero.status.success(),
        "phase2 case set should pass with identical outputs\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&zero.stdout),
        String::from_utf8_lossy(&zero.stderr)
    );
    assert!(
        String::from_utf8_lossy(&zero.stdout).contains("R(byte-drift) = 0"),
        "phase2 byte harness must report R(byte-drift)=0\nstdout:\n{}",
        String::from_utf8_lossy(&zero.stdout)
    );

    write_fake_sugar(&changed, false);
    let drift = Command::new(&script)
        .args([
            "--project-root",
            project.to_str().unwrap(),
            "--baseline-sugar",
            baseline.to_str().unwrap(),
            "--changed-sugar",
            changed.to_str().unwrap(),
            "--out-dir",
            out.to_str().unwrap(),
            "--label",
            "phase2-lift-drift",
            "--case",
            "lift-json",
        ])
        .output()
        .unwrap_or_else(|err| panic!("run {} planted drift: {err}", script.display()));
    println!(
        "phase2 byte-compat planted drift stdout:\n{}",
        String::from_utf8_lossy(&drift.stdout)
    );
    assert!(
        !drift.status.success(),
        "selected lift-json case should fail on planted byte drift"
    );
    assert!(
        String::from_utf8_lossy(&drift.stdout).contains("R(byte-drift) = 1"),
        "planted drift should report R(byte-drift)=1\nstdout:\n{}",
        String::from_utf8_lossy(&drift.stdout)
    );
}
