// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

/// Write `text` to `path` and mark it executable.
///
/// Uses explicit `sync_all` + drop before `set_permissions` to ensure the
/// kernel writer-fd is fully closed before the caller spawns the script.
/// This prevents ETXTBSY (os error 26) races on Linux where `exec` refuses
/// a file that still has an open writer fd.
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
        // f is dropped here, fd closed before chmod
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

#[test]
fn sugar_cli_does_not_expose_zoo_subcommand() {
    let output = Command::new(sugar_bin())
        .arg("--help")
        .output()
        .expect("spawn sugar --help");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        !stdout.contains("zoo"),
        "`sugar zoo` must remain a repo harness, not a public CLI subcommand\nstdout:\n{stdout}"
    );
}

#[test]
fn prove_cli_does_not_expose_manual_proofir_or_solver_text_flags() {
    let help = Command::new(sugar_bin())
        .arg("prove")
        .arg("--help")
        .output()
        .expect("spawn sugar prove --help");
    let stdout = String::from_utf8_lossy(&help.stdout);
    let stderr = String::from_utf8_lossy(&help.stderr);
    assert!(
        help.status.success(),
        "sugar prove --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    for forbidden in ["--formula", "--target", "--output"] {
        assert!(
            !stdout.contains(forbidden),
            "`prove {forbidden}` is a manual ProofIR/solver-data surface and must stay retired\nstdout:\n{stdout}"
        );
    }

    let rejected = Command::new(sugar_bin())
        .arg("prove")
        .arg("--formula")
        .arg("formula.json")
        .arg("--json")
        .output()
        .expect("spawn sugar prove --formula");
    let stderr = String::from_utf8_lossy(&rejected.stderr);
    assert!(
        !rejected.status.success(),
        "`prove --formula` must be rejected as an unknown flag"
    );
    assert!(
        stderr.contains("unexpected argument '--formula'")
            || stderr.contains("unrecognized")
            || stderr.contains("unknown"),
        "stderr should reject --formula at clap boundary\n{stderr}"
    );
}

#[test]
fn prove_empty_project_is_not_a_successful_proof() {
    let project = tempfile::tempdir().expect("create tempdir");
    let output = Command::new(sugar_bin())
        .arg("prove")
        .arg(project.path())
        .arg("--json")
        .output()
        .expect("spawn sugar prove empty project");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let report: serde_json::Value = serde_json::from_str(&stdout)
        .unwrap_or_else(|e| panic!("prove JSON parse failed: {e}\nstdout: {stdout}"));

    assert_eq!(report["totalCallsites"], 0, "report: {report}");
    assert_eq!(report["violations"], 0, "report: {report}");
    assert!(
        !output.status.success(),
        "prove must not report success when it checked zero callsites: {report}"
    );
}

#[test]
fn sugar_cli_does_not_expose_legacy_witness_subcommand() {
    let help = Command::new(sugar_bin())
        .arg("--help")
        .output()
        .expect("spawn sugar --help");
    let stdout = String::from_utf8_lossy(&help.stdout);
    let stderr = String::from_utf8_lossy(&help.stderr);
    assert!(
        help.status.success(),
        "sugar --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        !stdout
            .lines()
            .any(|line| line.trim_start().starts_with("witness ")),
        "`sugar witness` is the legacy manual ProofIR property route and must stay retired\nstdout:\n{stdout}"
    );

    let rejected = Command::new(sugar_bin())
        .arg("witness")
        .arg("blake3-512:deadbeef")
        .arg("property.ir.json")
        .output()
        .expect("spawn sugar witness");
    let stderr = String::from_utf8_lossy(&rejected.stderr);
    assert!(
        !rejected.status.success(),
        "`sugar witness <contract> <property.ir.json>` must be rejected at the CLI boundary"
    );
    assert!(
        stderr.contains("unrecognized subcommand")
            || stderr.contains("unknown")
            || stderr.contains("invalid value"),
        "stderr should reject legacy witness at clap boundary\n{stderr}"
    );
}

#[test]
fn sugar_cli_does_not_expose_legacy_proof_artifact_subcommand() {
    let help = Command::new(sugar_bin())
        .arg("--help")
        .output()
        .expect("spawn sugar --help");
    let stdout = String::from_utf8_lossy(&help.stdout);
    let stderr = String::from_utf8_lossy(&help.stderr);
    assert!(
        help.status.success(),
        "sugar --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stdout
            .lines()
            .any(|line| line.trim_start().starts_with("dump ")),
        "`sugar dump` is the supported diagnostic .proof inspection surface\nstdout:\n{stdout}"
    );
    assert!(
        !stdout
            .lines()
            .any(|line| line.trim_start().starts_with("proof ")),
        "`sugar proof` is a legacy .proof conformance command family and must stay retired\nstdout:\n{stdout}"
    );

    let rejected = Command::new(sugar_bin())
        .arg("proof")
        .arg("inspect")
        .arg("artifact.proof")
        .output()
        .expect("spawn sugar proof inspect");
    let stderr = String::from_utf8_lossy(&rejected.stderr);
    assert!(
        !rejected.status.success(),
        "`sugar proof inspect` must be rejected at the CLI boundary"
    );
    assert!(
        stderr.contains("unrecognized subcommand")
            || stderr.contains("unknown")
            || stderr.contains("invalid value"),
        "stderr should reject legacy proof at clap boundary\n{stderr}"
    );
}

#[test]
fn sugar_cli_does_not_expose_legacy_link_subcommand() {
    let help = Command::new(sugar_bin())
        .arg("--help")
        .output()
        .expect("spawn sugar --help");
    let stdout = String::from_utf8_lossy(&help.stdout);
    let stderr = String::from_utf8_lossy(&help.stderr);
    assert!(
        help.status.success(),
        "sugar --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        !stdout
            .lines()
            .any(|line| line.trim_start().starts_with("link ")),
        "`sugar link` is the legacy Rust/Go-specific implication linker and must stay retired; implications now lift through project-registered kits and compose in mint/prove\nstdout:\n{stdout}"
    );

    let rejected = Command::new(sugar_bin())
        .arg("link")
        .arg("project")
        .output()
        .expect("spawn sugar link");
    let stderr = String::from_utf8_lossy(&rejected.stderr);
    assert!(
        !rejected.status.success(),
        "`sugar link` must be rejected at the CLI boundary"
    );
    assert!(
        stderr.contains("unrecognized subcommand")
            || stderr.contains("unknown")
            || stderr.contains("invalid value"),
        "stderr should reject legacy link at clap boundary\n{stderr}"
    );
}

#[test]
fn sugar_cli_does_not_expose_retired_materialize_or_recognize_subcommands() {
    // #3816 / #3809: materialize and recognize were deleted with their kit
    // handlers. Ingress is lift of native source; egress is emit. No source-
    // rewriting verb and no tag-scanning verb remain on the CLI surface.
    let help = Command::new(sugar_bin())
        .arg("--help")
        .output()
        .expect("spawn sugar --help");
    let stdout = String::from_utf8_lossy(&help.stdout);
    let stderr = String::from_utf8_lossy(&help.stderr);
    assert!(
        help.status.success(),
        "sugar --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    for retired in ["materialize ", "recognize "] {
        assert!(
            !stdout
                .lines()
                .any(|line| line.trim_start().starts_with(retired)),
            "`sugar {retired}` must stay retired after the verb purge\nstdout:\n{stdout}"
        );
    }

    for (verb, args) in [
        ("materialize", vec!["project"]),
        ("recognize", vec!["project"]),
    ] {
        let rejected = Command::new(sugar_bin())
            .arg(verb)
            .args(&args)
            .output()
            .unwrap_or_else(|_| panic!("spawn sugar {verb}"));
        let stderr = String::from_utf8_lossy(&rejected.stderr);
        assert!(
            !rejected.status.success(),
            "`sugar {verb}` must be rejected at the CLI boundary"
        );
        assert!(
            stderr.contains("unrecognized subcommand")
                || stderr.contains("unknown")
                || stderr.contains("invalid value"),
            "stderr should reject retired {verb} at clap boundary\n{stderr}"
        );
    }
}

#[test]
fn allow_failed_components_cannot_absorb_a_stalled_lift_transport() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/stalled");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        "[authoring.lift]\nsurface = \"stalled\"\n",
    )
    .expect("write config");
    let plugin = dir.path().join("stalled-plugin.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"stalled","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"stalled-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"sugar.enumerate","required":true}]},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"sugar.enumerate"'* ]]; then
    sleep 30
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!("name = \"stalled\"\ncommand = [\"{}\"]\n", plugin.display()),
    )
    .expect("write manifest");

    let output = Command::new(sugar_bin())
        .args(["lift", "--allow-failed-components"])
        .arg(&project)
        .env("SUGAR_LIFT_RESPONSE_TIMEOUT_SECS", "1")
        .output()
        .expect("run stalled lift");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        !output.status.success(),
        "transport stall was absorbed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(stderr.contains("transport stalled"), "{stderr}");
    assert!(stderr.contains("stage=read_line.enter"), "{stderr}");
    assert!(
        !stdout.contains("recovered-construction-audit"),
        "stall minted a frontier: {stdout}"
    );
}
