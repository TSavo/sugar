// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::{address, Input, Path as CorePath, PathAlgebra, PathDocument, Verb};
use serde_json::json;
use sugar_verifier::MementoCid;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

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

/// Spawn `cmd` and retry up to 5 times if the CLI subprocess reports
/// ETXTBSY ("Text file busy", os error 26) in stderr.
///
/// The root cause is a Linux kernel race: `exec` refuses a file that still
/// has an open writer fd anywhere on the system (e.g. the parallel test
/// runner's cargo worker just finished writing the plugin script).
/// `write_executable` closes + syncs before returning, but a belt-and-braces
/// retry catches any residual races.
fn output_retrying_etxtbsy(cmd: &mut Command) -> std::process::Output {
    const MAX_ATTEMPTS: u32 = 5;
    for attempt in 0..MAX_ATTEMPTS {
        let out = cmd.output().expect("spawn sugar");
        let stderr = String::from_utf8_lossy(&out.stderr);
        let is_etxtbsy = !out.status.success()
            && (stderr.contains("Text file busy") || stderr.contains("os error 26"));
        if !is_etxtbsy {
            return out;
        }
        std::thread::sleep(std::time::Duration::from_millis(
            20 * u64::from(attempt + 1),
        ));
    }
    cmd.output().expect("spawn sugar (final attempt)")
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
fn lift_identify_only_delegates_from_project_config() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/identify");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        "[authoring.lift]\nsurface = \"identify\"\n",
    )
    .expect("write config");
    let plugin = dir.path().join("identify-plugin.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"identify","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"identity-document","identities":[{"domain":"software","claim":"checked_add_u8.postcondition"}]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"identify\"\ncommand = [\"{}\"]\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg(&project)
            .arg("--identify-only")
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar lift --identify-only failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value =
        serde_json::from_str(&stdout).expect("identify-only lift JSON parses");
    assert_eq!(report["kind"], "identity-document");
    let identities = report["identities"].as_array().expect("identities array");
    assert_eq!(identities.len(), 1);
    assert!(identities.iter().any(|identity| {
        identity["domain"] == "software" && identity["claim"] == "checked_add_u8.postcondition"
    }));
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
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"stalled-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
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
    assert!(stderr.contains("kind=transport"), "{stderr}");
    assert!(stderr.contains("transport stalled"), "{stderr}");
    assert!(stderr.contains("stage=read_line.enter"), "{stderr}");
    assert!(
        !stdout.contains("recovered-construction-audit"),
        "stall minted a frontier: {stdout}"
    );
}

#[test]
fn lift_library_bindings_delegates_layer_to_lifter() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/library-bindings");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        "[authoring.lift]\nsurface = \"library-bindings\"\n",
    )
    .expect("write config");
    let plugin = dir.path().join("library-bindings-plugin.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"library-bindings","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    if [[ "$line" != *'"layer":"library-bindings"'* ]]; then
      printf 'expected library-bindings layer, saw: %s\n' "$line" >&2
      exit 42
    fi
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"body_source":{"file":"src/shims/requests.py","source_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","span":{"start_line":1,"start_col":0,"end_line":6,"end_col":0}},"op_cid":"blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","kind":"library-sugar-binding-entry","loss_record_contribution":{"form":"literal","value":{"entries":[]}},"param_names":["url"],"param_types":["str"],"return_type":"int","signature_shape_cid":"blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source_function_name":"fetch_status","target_language":"python","target_library_tag":"requests","term_shape":null,"term_shape_cid":null}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"library-bindings\"\ncommand = [\"{}\"]\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg(&project)
            .arg("--library-bindings")
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar lift --library-bindings failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value =
        serde_json::from_str(&stdout).expect("library-bindings lift JSON parses");
    assert_eq!(report["kind"], "ir-document");
    assert_eq!(report["ir"][0]["kind"], "library-sugar-binding-entry");
    assert_eq!(report["ir"][0]["target_library_tag"], "requests");
}

#[test]
fn lift_identify_only_rejects_non_identity_response() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/bad-identify");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        "[authoring.lift]\nsurface = \"bad-identify\"\n",
    )
    .expect("write config");
    let plugin = dir.path().join("bad-identify-plugin.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"bad-identify","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"bad-identify\"\ncommand = [\"{}\"]\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg(&project)
            .arg("--identify-only")
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        !output.status.success(),
        "identify-only must reject a full ir-document response\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stderr.contains("identify-only") && stderr.contains("identity-document"),
        "stderr should explain the response-shape violation\nstderr:\n{stderr}"
    );
}

#[test]
fn mint_uses_lift_surface_from_project_config() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/mint-lift");
    let out_dir = dir.path().join("out");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        "[authoring.lift]\nsurface = \"mint-lift\"\n",
    )
    .expect("write config");
    let plugin = dir.path().join("mint-lift-plugin.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"mint-lift","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"contract","name":"demo.contract","outBinding":"out","post":{"kind":"atomic","name":"demo_true","args":[]}}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"mint-lift\"\ncommand = [\"{}\"]\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("mint")
            .arg("--project")
            .arg(&project)
            .arg("--out")
            .arg(&out_dir)
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "mint should compose through [authoring.lift], not require [authoring.must]\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("mint JSON parses");
    assert_eq!(report["surface"], "mint-lift");
    assert_eq!(report["lift"]["kind"], "ir-document");
    assert!(report["filenameCid"]
        .as_str()
        .unwrap_or_default()
        .starts_with("blake3-512:"));
}

#[test]
fn mint_conjoins_producer_contracts_consumer_bridges_and_implications_in_one_proof() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let producer_manifest = project.join(".sugar/lift/producer");
    let consumer_manifest = project.join(".sugar/lift/consumer");
    let out_dir = dir.path().join("out");
    fs::create_dir_all(&producer_manifest).expect("create producer manifest dir");
    fs::create_dir_all(&consumer_manifest).expect("create consumer manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "producer"
surface = "producer"
emit = "ir-document"

[[plugins]]
name = "consumer"
surface = "consumer"
"#,
    )
    .expect("write project config");

    let producer = dir.path().join("producer.sh");
    write_executable(
        &producer,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"producer","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"contract","name":"callee@src/lib.rs:1:1","outBinding":"out","pre":{"kind":"atomic","name":"producer_pre","args":[]},"post":{"kind":"atomic","name":"producer_post","args":[]}}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );

    let consumer = dir.path().join("consumer.sh");
    write_executable(
        &consumer,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"consumer","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf 'consumer must be dispatched via lift_implications, not lift: %s\n' "$line" >&2
    exit 44
  elif [[ "$line" == *'"method":"sugar.plugin.lift_implications"'* ]]; then
    if [[ "$line" != *'"contract_bindings"'* || "$line" != *'"name":"callee@src/lib.rs:1:1"'* ]]; then
      printf 'consumer did not receive producer contract_bindings: %s\n' "$line" >&2
      exit 45
    fi
    cid="${line#*\"contract_cid\":\"}"
    cid="${cid%%\"*}"
    if [[ "$cid" != blake3-512:* ]]; then
      printf 'consumer received invalid contract cid: %s\n' "$line" >&2
      exit 46
    fi
    printf '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"bridge","name":"intra-body:rust:callee@src/lib.rs:2:4","schemaVersion":"1","sourceContractCid":"%s","sourceLayer":"rust","sourceSymbol":"callee","target":{"cid":"%s","kind":"contract"},"targetContractCid":"%s","targetLayer":"rust-tests"}],"diagnostics":[],"implications":[{"name":"manifest-post-implies-pre","antecedent":"callee@src/lib.rs:1:1","antecedentSlot":"post","consequent":"callee@src/lib.rs:1:1","consequentSlot":"pre","prover":"stub-consumer"}]}}\n' "$cid" "$cid" "$cid"
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );

    fs::write(
        producer_manifest.join("manifest.toml"),
        format!(
            "name = \"producer\"\ncommand = [\"{}\"]\n",
            producer.display()
        ),
    )
    .expect("write producer manifest");
    fs::write(
        consumer_manifest.join("manifest.toml"),
        format!(
            "name = \"consumer\"\ncommand = [\"{}\"]\nmethod = \"sugar.plugin.lift_implications\"\nphase = \"consumer\"\n",
            consumer.display()
        ),
    )
    .expect("write consumer manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("mint")
            .arg("--project")
            .arg(&project)
            .arg("--out")
            .arg(&out_dir)
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "mint conjoin should run producers, forward contract_bindings to consumers, and emit one proof\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );

    let proof_files: Vec<PathBuf> = fs::read_dir(&out_dir)
        .expect("read out dir")
        .filter_map(|entry| {
            let path = entry.expect("out dir entry").path();
            (path.extension().and_then(|s| s.to_str()) == Some("proof")).then_some(path)
        })
        .collect();
    assert_eq!(
        proof_files.len(),
        1,
        "producer + consumer conjoin must write one proof, got {proof_files:?}"
    );

    let pool = sugar_verifier::load_all_proofs::run_with_files(
        Path::new("/no-such-project"),
        &proof_files,
    );
    assert!(
        pool.load_errors.is_empty(),
        "conjoined proof must load cleanly: {:?}",
        pool.load_errors
    );
    let bridge = pool.bridge_member_for_symbol("callee").unwrap_or_else(|| {
        panic!(
            "consumer bridge should be indexed by sourceSymbol=callee; got {:?}",
            pool.bridges_by_symbol.keys().collect::<Vec<_>>()
        )
    });
    let target_cid = bridge
        .field("targetContractCid")
        .and_then(|v| v.as_str())
        .expect("bridge must have targetContractCid");
    let target_cid =
        MementoCid::try_parse(target_cid.to_string()).expect("bridge target CID must parse");
    assert!(
        pool.stored_member(&target_cid).is_some(),
        "bridge target cid {target_cid} must resolve in same proof"
    );
    assert!(
        pool.stored_member(&target_cid)
            .is_some_and(|member| member.kind() == sugar_verifier::MemberKind::Contract),
        "bridge target must be a contract"
    );
    let implication_count = pool.implication_members().count();
    assert_eq!(
        implication_count, 1,
        "consumer top-level implications should mint through manifest RPC"
    );
}

#[test]
fn lift_report_runs_configured_producers_and_implication_consumers() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let producer_manifest = project.join(".sugar/lift/rust-fn-contracts");
    let consumer_manifest = project.join(".sugar/lift/rust-implications");
    fs::create_dir_all(&producer_manifest).expect("create producer manifest dir");
    fs::create_dir_all(&consumer_manifest).expect("create consumer manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "rust-fn-contracts"
kind = "lift"
surface = "rust-fn-contracts"
emit = "ir-document"
workspace_override = "vendor/base64-0.22.1"

[[plugins]]
name = "rust-implications"
kind = "lift"
surface = "rust-implications"
"#,
    )
    .expect("write project config");

    let producer = dir.path().join("producer.sh");
    write_executable(
        &producer,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"producer","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"function-contract","name":"encoded_len","outBinding":"out","post":{"kind":"atomic","name":"=","args":[{"kind":"var","name":"out"},{"kind":"ctor","name":"call:encoded_len","args":[{"kind":"var","name":"n"},{"kind":"var","name":"padded"}]}]},"sourceWarrants":[{"kind":"source-memento","file":"src/encode.rs","sourceFunctionName":"encoded_len","source_function_name":"encoded_len","span":{"start_line":97,"start_col":0,"end_line":122,"end_col":1},"paramNames":["bytes_len","padding"],"param_names":["bytes_len","padding"],"source_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","template_cid":"blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}],"sourceLedger":{"source_loci":1,"source_warranted":1,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"sourceAudits":[{"role":"rust-fn-contracts","universe_kind":"function-contract","totals":{"source_loci":1,"source_warranted":1,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"loci":[{"file":"src/encode.rs","role":"rust-fn-contracts","universe_kind":"function-contract","ast_path":"encoded_len","sourceFunctionName":"encoded_len","line":97,"col":0}]}],"factoryAudits":[],"sourceMementos":[{"kind":"source-memento","file":"src/encode.rs","sourceFunctionName":"encoded_len","source_function_name":"encoded_len","span":{"start_line":97,"start_col":0,"end_line":122,"end_col":1},"paramNames":["bytes_len","padding"],"param_names":["bytes_len","padding"],"source_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","template_cid":"blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],"factoryAuditSummary":{"emittedRows":0,"statusCounts":{"warranted":0,"incomplete":0,"support":0,"unresolved":0},"unresolvedSites":[],"factoryWalk":[]},"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );

    let consumer = dir.path().join("consumer.sh");
    write_executable(
        &consumer,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"consumer","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf 'consumer must be dispatched via lift_implications, not lift: %s\n' "$line" >&2
    exit 44
  elif [[ "$line" == *'"method":"sugar.plugin.lift_implications"'* ]]; then
    if [[ "$line" != *'"contract_bindings"'* || "$line" != *'"name":"encoded_len"'* ]]; then
      printf 'consumer did not receive encoded_len contract_bindings: %s\n' "$line" >&2
      exit 45
    fi
    cid="${line#*\"contract_cid\":\"}"
    cid="${cid%%\"*}"
    if [[ "$cid" != blake3-512:* ]]; then
      printf 'consumer received invalid contract cid: %s\n' "$line" >&2
      exit 46
    fi
    printf '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"bridge","name":"dig:encoded_len","sourceSymbol":"encoded_len","targetContractCid":"%s","targetLayer":"rust-fn-contracts"}],"sourceLedger":{"source_loci":0,"source_warranted":0,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"sourceAudits":[],"factoryAudits":[],"sourceMementos":[],"factoryAuditSummary":{"emittedRows":0,"statusCounts":{"warranted":0,"incomplete":0,"support":0,"unresolved":0},"unresolvedSites":[],"factoryWalk":[]},"diagnostics":[]}}\n' "$cid"
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );

    fs::write(
        producer_manifest.join("manifest.toml"),
        format!(
            "name = \"rust-fn-contracts\"\ncommand = [\"{}\"]\n",
            producer.display()
        ),
    )
    .expect("write producer manifest");
    fs::write(
        consumer_manifest.join("manifest.toml"),
        format!(
            "name = \"rust-implications\"\ncommand = [\"{}\"]\nmethod = \"sugar.plugin.lift_implications\"\nphase = \"consumer\"\n",
            consumer.display()
        ),
    )
    .expect("write consumer manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "lift report must run configured producer plus implication consumer\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("report JSON parses");
    let names = report["contracts"]
        .as_array()
        .expect("contracts array")
        .iter()
        .filter_map(|entry| entry["name"].as_str())
        .collect::<Vec<_>>();
    assert!(
        names.contains(&"encoded_len"),
        "report must include the body-dig emitted encoded_len post universe: {names:?}"
    );
    assert!(
        names.contains(&"dig:encoded_len"),
        "report must include the implication-lifted dig bridge: {names:?}"
    );
    let source_files = report["sourceMementos"]
        .as_array()
        .expect("sourceMementos array")
        .iter()
        .filter_map(|entry| entry["file"].as_str())
        .collect::<Vec<_>>();
    assert!(
        source_files.contains(&"vendor/base64-0.22.1/src/encode.rs"),
        "body-dig source mementos must be rebased through the configured workspace_override: {source_files:?}"
    );
    let encoded_len_contract = report["contracts"]
        .as_array()
        .expect("contracts array")
        .iter()
        .find(|entry| entry["name"].as_str() == Some("encoded_len"))
        .expect("encoded_len contract");
    assert_eq!(
        encoded_len_contract["sourceWarrants"][0]["file"].as_str(),
        Some("vendor/base64-0.22.1/src/encode.rs"),
        "body-dig source warrants must name the replacement sugar's source line in the visual frame"
    );
}

#[test]
fn lift_report_runs_single_surface_implication_pass_with_contract_bindings() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python"
kind = "lift"
surface = "python"
emit = "ir-document"
"#,
    )
    .expect("write project config");

    let plugin = dir.path().join("python.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"python","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    if [[ "$line" == *'"contract_bindings"'* ]]; then
      if [[ "$line" != *'"name":"callee"'* ]]; then
        printf 'single-surface implication pass did not receive callee contract binding: %s\n' "$line" >&2
        exit 45
      fi
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[],"sourceLedger":{"source_loci":0,"source_warranted":0,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"sourceAudits":[],"sourceMementos":[],"diagnostics":[],"implications":[{"name":"caller-post-implies-callee-pre","antecedent":"caller","antecedentSlot":"post","consequent":"callee","consequentSlot":"pre","prover":"single-plugin-implications"}]}}'
    else
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"contract","name":"app.py::tests::t_caller::assertion","outBinding":"out","post":{"kind":"atomic","name":"t_caller_fact","args":[]}},{"kind":"contract","name":"caller","outBinding":"out","post":{"kind":"atomic","name":"caller_post","args":[]}},{"kind":"contract","name":"callee","outBinding":"out","pre":{"kind":"atomic","name":"callee_pre","args":[]},"post":{"kind":"atomic","name":"callee_post","args":[]}}],"sourceLedger":{"source_loci":1,"source_warranted":1,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"sourceAudits":[],"sourceMementos":[],"diagnostics":[],"callEdges":[{"kind":"call-edge","schemaVersion":"1","sourceContract":"caller","targetSymbol":"call:callee","targetContract":null,"targetContractCid":null,"callSiteLocus":{"file":"app.py","line":2,"column":11}}]}}'
    fi
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!("name = \"python\"\ncommand = [\"{}\"]\n", plugin.display()),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "lift report should run the single configured report plugin and its implication pass\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("report JSON parses");
    let call_edges = report["callEdges"].as_array().expect("callEdges array");
    assert!(
        call_edges.iter().any(|edge| {
            edge["kind"].as_str() == Some("implication")
                && edge["sourceContract"].as_str() == Some("caller")
                && edge["targetContract"].as_str() == Some("callee")
                && edge["prover"].as_str() == Some("single-plugin-implications")
        }),
        "single-surface report must include the implication memento edge after the bindings-backed pass; callEdges={call_edges:#?}"
    );
}

#[test]
fn lift_visual_report_header_names_observed_occurrences_and_demanded_questions() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python"
kind = "lift"
surface = "python"
emit = "ir-document"
"#,
    )
    .expect("write project config");

    let plugin = dir.path().join("python.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"python","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    if [[ "$line" == *'"contract_bindings"'* ]]; then
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[],"sourceLedger":{"source_loci":0,"source_warranted":0,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"sourceAudits":[],"sourceMementos":[],"diagnostics":[],"implications":[{"name":"caller-post-implies-callee-pre","antecedent":"caller","antecedentSlot":"post","consequent":"callee","consequentSlot":"pre","prover":"single-plugin-implications"}]}}'
    else
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","planMementos":[{"kind":"component-plan","planning":{"source":"test-plan"},"planAtoms":[]}],"ir":[{"kind":"contract","name":"app.py::tests::t_caller::assertion","outBinding":"out","post":{"kind":"atomic","name":"t_caller_fact","args":[]}},{"kind":"contract","name":"caller","outBinding":"out","post":{"kind":"atomic","name":"caller_post","args":[]}},{"kind":"contract","name":"callee","outBinding":"out","pre":{"kind":"atomic","name":"callee_pre","args":[]},"post":{"kind":"atomic","name":"callee_post","args":[]}}],"sourceLedger":{"source_loci":1,"source_warranted":1,"source_inactive":0,"source_support":0,"source_boundary":0,"source_unresolved":0},"sourceAudits":[],"sourceMementos":[],"diagnostics":[],"callEdges":[{"kind":"call-edge","schemaVersion":"1","sourceContract":"caller","targetSymbol":"call:callee","targetContract":"callee","targetContractCid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","callSiteLocus":{"file":"app.py","line":2,"column":11}},{"kind":"call-edge","schemaVersion":"1","sourceContract":"caller","targetSymbol":"call:missing","targetContract":null,"targetContractCid":null,"callSiteLocus":{"file":"app.py","line":3,"column":11}}]}}'
    fi
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!("name = \"python\"\ncommand = [\"{}\"]\n", plugin.display()),
    )
    .expect("write manifest");

    let json_output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );
    let json_stdout = String::from_utf8_lossy(&json_output.stdout);
    let json_stderr = String::from_utf8_lossy(&json_output.stderr);
    assert!(
        json_output.status.success(),
        "lift report JSON should succeed\nstdout:\n{json_stdout}\nstderr:\n{json_stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&json_stdout).expect("report JSON parses");
    let observed_occurrences = report["callEdges"]
        .as_array()
        .expect("callEdges observed-occurrence array");
    let demanded_questions = report["demandedQuestions"]
        .as_array()
        .expect("demandedQuestions array");
    let demanded_resolved = demanded_questions
        .iter()
        .filter(|question| question["status"].as_str() != Some("unjoined"))
        .count();
    let demanded_dangling = demanded_questions.len() - demanded_resolved;

    let visual_output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--visual")
            .arg(&project),
    );
    let visual = String::from_utf8_lossy(&visual_output.stdout);
    let visual_stderr = String::from_utf8_lossy(&visual_output.stderr);
    assert!(
        visual_output.status.success(),
        "lift visual report should succeed\nstdout:\n{visual}\nstderr:\n{visual_stderr}"
    );
    let header = visual
        .lines()
        .find(|line| line.starts_with("report sections:"))
        .unwrap_or_else(|| panic!("visual report must include report sections header: {visual}"));

    assert!(
        header.contains(&format!(
            "observed occurrences total={}",
            observed_occurrences.len()
        )),
        "header observed-occurrence census must equal report.callEdges rows; header={header}; observedOccurrences={observed_occurrences:#?}"
    );
    assert!(
        header.contains(&format!(
            "demanded questions total={}",
            demanded_questions.len()
        )),
        "header demanded-question census must equal report.demandedQuestions rows; header={header}; demandedQuestions={demanded_questions:#?}"
    );
    assert!(
        header.contains(&format!(
            "demanded questions resolved={demanded_resolved}"
        )),
        "header must name resolved demanded questions; header={header}; demandedQuestions={demanded_questions:#?}"
    );
    assert!(
        header.contains(&format!(
            "demanded questions dangling={demanded_dangling}"
        )),
        "header must name dangling demanded questions; header={header}; demandedQuestions={demanded_questions:#?}"
    );
    assert!(
        !header.contains("call edges total=") && !header.contains("implications="),
        "header must not alias observed occurrences and demanded questions under old units; header={header}"
    );
}

#[test]
fn lift_report_python_assertions_join_source_guard_preconditions() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping Python guard precondition report test");
        return;
    }
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::write(
        project.join("guarded.py"),
        r#"def guarded(x):
    if x < 2:
        raise ValueError('too small')
    return x

def complex_guard(x: int) -> int:
    if expensive(x):
        raise ValueError('not flat')
    return x

def expensive(x: int) -> bool:
    return x < 0
"#,
    )
    .expect("write guarded.py");
    fs::write(
        project.join("test_guarded.py"),
        r#"from guarded import guarded

def test_guarded():
    assert guarded(5) == 5
"#,
    )
    .expect("write test_guarded.py");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python-audit-lift"
kind = "lift"
surface = "python"
emit = "ir-document"
"#,
    )
    .expect("write project config");

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
    let plugin = dir.path().join("python-lift.sh");
    write_executable(
        &plugin,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"python-audit-lift\"\ncommand = [\"{}\"]\nworking_dir = \".\"\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "lift report must join source guard preconditions into the assertion report path\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("report JSON parses");
    let contracts = report["contracts"].as_array().expect("contracts array");
    let contract_names = contracts
        .iter()
        .filter_map(|contract| {
            contract["name"]
                .as_str()
                .or_else(|| contract["fnName"].as_str())
        })
        .collect::<Vec<_>>();
    let guarded = contracts
        .iter()
        .find(|contract| {
            contract["name"].as_str() == Some("guarded.guarded")
                || contract["fnName"].as_str() == Some("guarded.guarded")
        })
        .unwrap_or_else(|| {
            panic!(
                "source-lifter function contract for guarded must be minted; names={contract_names:?}; report={report:#?}"
            )
        });
    assert_eq!(
        guarded["pre"]["name"].as_str(),
        Some("≥"),
        "guarded contract must carry the negated if-raise guard as its precondition: {guarded:#?}"
    );
    let call_edges = report["callEdges"].as_array().expect("callEdges array");
    assert!(
        call_edges.iter().any(|edge| {
            edge["kind"].as_str() == Some("implication")
                && edge["targetContract"].as_str() == Some("guarded.guarded")
                && edge["sourceSlot"].as_str() == Some("inv")
                && edge["targetSlot"].as_str() == Some("pre")
                && edge["prover"].as_str() == Some("python-implications")
        }),
        "report must render the post-to-pre implication edge once the source precondition binding exists; callEdges={call_edges:#?}"
    );
    let diagnostics = report["diagnostics"].as_array().expect("diagnostics array");
    assert!(
        diagnostics.iter().any(|diagnostic| {
            diagnostic["kind"].as_str() == Some("precondition-guard-skipped")
                && diagnostic["function"].as_str() == Some("guarded.complex_guard")
        }),
        "non-flat if-raise guard residual must surface as a diagnostic, not disappear; diagnostics={diagnostics:#?}"
    );
}

#[test]
fn lift_report_python_public_reexport_joins_set_module_guard_precondition() {
    if !python_blake3_available() {
        eprintln!("python3/blake3 not on PATH: skipping Python public reexport guard implication report test");
        return;
    }
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::create_dir_all(project.join("lib")).expect("create lib dir");
    fs::write(
        project.join("__init__.py"),
        "from .lib._npyio_impl import load\n",
    )
    .expect("write __init__.py");
    fs::write(
        project.join("lib").join("_npyio_impl.py"),
        r#"def set_module(module):
    def decorator(func):
        func.__module__ = module
        return func
    return decorator

@set_module('project')
def load(file, encoding='ASCII'):
    if encoding not in ('ASCII', 'latin1', 'bytes'):
        raise ValueError("unsupported encoding")
    return file
"#,
    )
    .expect("write lib/_npyio_impl.py");
    fs::write(
        project.join("test_io.py"),
        r#"import project as np

def test_load():
    assert np.load("data.npy") == "data.npy"
"#,
    )
    .expect("write test_io.py");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python-audit-lift"
kind = "lift"
surface = "python"
emit = "ir-document"
"#,
    )
    .expect("write project config");

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
    let plugin = dir.path().join("python-lift.sh");
    write_executable(
        &plugin,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"python-audit-lift\"\ncommand = [\"{}\"]\nworking_dir = \".\"\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "lift report must join public reexport assertion edges to source guard preconditions\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("report JSON parses");
    let contracts = report["contracts"].as_array().expect("contracts array");
    let load = contracts
        .iter()
        .find(|contract| {
            contract["name"].as_str() == Some("lib._npyio_impl.load")
                || contract["fnName"].as_str() == Some("lib._npyio_impl.load")
        })
        .expect("source-lifter contract for lib._npyio_impl.load must be minted");
    assert_eq!(
        load["bridgeSourceSymbol"].as_str(),
        Some("project.load"),
        "load contract must carry the public re-export bridge symbol: {load:#?}"
    );
    assert_eq!(
        load["pre"]["kind"].as_str(),
        Some("or"),
        "load contract must carry the negated encoding membership guard: {load:#?}"
    );
    let call_edges = report["callEdges"].as_array().expect("callEdges array");
    assert!(
        call_edges.iter().any(|edge| {
            edge["kind"].as_str() == Some("implication")
                && edge["targetContract"].as_str() == Some("lib._npyio_impl.load")
                && edge["targetSlot"].as_str() == Some("pre")
                && edge["prover"].as_str() == Some("python-implications")
        }),
        "report must render the public reexport post-to-pre implication edge; callEdges={call_edges:#?}"
    );
}

#[test]
fn lift_report_python_public_constructor_reexport_joins_guard_precondition() {
    if !python_blake3_available() {
        eprintln!(
            "python3/blake3 not on PATH: skipping Python constructor reexport guard implication report test"
        );
        return;
    }
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::create_dir_all(project.join("_core")).expect("create _core dir");
    fs::write(project.join("__init__.py"), "from ._core import finfo\n")
        .expect("write __init__.py");
    fs::write(
        project.join("_core").join("__init__.py"),
        "from .getlimits import *\n",
    )
    .expect("write _core/__init__.py");
    fs::write(
        project.join("_core").join("getlimits.py"),
        r#"__all__ = ["finfo"]

class finfo:
    def __new__(cls, dtype):
        if dtype is None:
            raise TypeError("dtype required")
        return dtype
"#,
    )
    .expect("write _core/getlimits.py");
    fs::write(
        project.join("test_getlimits.py"),
        r#"import project as np

def test_finfo():
    assert np.finfo("f8") == "f8"
"#,
    )
    .expect("write test_getlimits.py");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python-audit-lift"
kind = "lift"
surface = "python"
emit = "ir-document"
"#,
    )
    .expect("write project config");

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
    let plugin = dir.path().join("python-lift.sh");
    write_executable(
        &plugin,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display()
        ),
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"python-audit-lift\"\ncommand = [\"{}\"]\nworking_dir = \".\"\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "lift report must join public constructor reexport assertion edges to source guard preconditions\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("report JSON parses");
    let contracts = report["contracts"].as_array().expect("contracts array");
    let constructor = contracts
        .iter()
        .find(|contract| {
            contract["name"].as_str() == Some("_core.getlimits.finfo.__new__")
                || contract["fnName"].as_str() == Some("_core.getlimits.finfo.__new__")
        })
        .expect("source-lifter contract for _core.getlimits.finfo.__new__ must be minted");
    assert_eq!(
        constructor["bridgeSourceSymbol"].as_str(),
        Some("project.finfo"),
        "constructor contract must carry the public class re-export bridge symbol: {constructor:#?}"
    );
    assert_eq!(
        constructor["pre"]["name"].as_str(),
        Some("≠"),
        "constructor contract must carry the negated None guard: {constructor:#?}"
    );
    let call_edges = report["callEdges"].as_array().expect("callEdges array");
    assert!(
        call_edges.iter().any(|edge| {
            edge["kind"].as_str() == Some("implication")
                && edge["targetContract"].as_str() == Some("_core.getlimits.finfo.__new__")
                && edge["targetSlot"].as_str() == Some("pre")
                && edge["prover"].as_str() == Some("python-implications")
        }),
        "report must render the constructor reexport post-to-pre implication edge; callEdges={call_edges:#?}"
    );
}

#[test]
fn lift_report_rehydrates_assertion_surface_audits_from_minted_proof() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let fact_manifest = project.join(".sugar/lift/python-test-assertions");
    let body_manifest = project.join(".sugar/lift/python-body-universes");
    fs::create_dir_all(&fact_manifest).expect("create fact manifest dir");
    fs::create_dir_all(&body_manifest).expect("create body manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python-test-assertions"
kind = "lift"
surface = "python-test-assertions"
emit = "ir-document"

[[plugins]]
name = "python-body-universes"
kind = "lift"
surface = "python-body-universes"
emit = "ir-document"
"#,
    )
    .expect("write project config");

    let fact_source = json!({
        "kind": "source-memento",
        "file": "test_encoder.py",
        "sourceFunctionName": "test_encode_len",
        "source_function_name": "test_encode_len",
        "span": {"start_line": 4, "start_col": 0, "end_line": 5, "end_col": 33},
        "source_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "template_cid": "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "contractName": "test_encoder::test_encode_len::fact",
        "claimName": "test_encoder::test_encode_len::fact",
        "role": "unit-test-fact"
    });
    let body_source = json!({
        "kind": "source-memento",
        "file": "encoder.py",
        "sourceFunctionName": "encode_len",
        "source_function_name": "encode_len",
        "span": {"start_line": 1, "start_col": 0, "end_line": 3, "end_col": 19},
        "paramNames": ["payload"],
        "param_names": ["payload"],
        "source_cid": "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "template_cid": "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "contractName": "encode_len",
        "claimName": "encode_len",
        "role": "body-universe"
    });
    let fact_formula = json!({
        "kind": "atomic",
        "name": "=",
        "args": [
            {"kind": "ctor", "name": "call:encode_len", "args": [{"kind": "str", "value": "abc"}]},
            {"kind": "int", "value": 4}
        ]
    });
    let body_formula = json!({
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "var", "name": "out"},
            {"kind": "int", "value": 0}
        ]
    });
    let fact_response = json!({
        "kind": "ir-document",
        "ir": [{
            "kind": "contract",
            "name": "test_encoder::test_encode_len::fact",
            "outBinding": "out",
            "inv": fact_formula,
            "sourceWarrants": [fact_source]
        }],
        "sourceLedger": {
            "source_loci": 1,
            "source_warranted": 1,
            "source_inactive": 0,
            "source_support": 0,
            "source_boundary": 0,
            "source_unresolved": 0
        },
        "sourceAudits": [],
        "factoryAudits": [],
        "factoryAuditSummary": {
            "emittedRows": 0,
            "statusCounts": {"warranted": 0, "incomplete": 0, "support": 0, "unresolved": 0},
            "unresolvedSites": [],
            "factoryWalk": []
        },
        "assertionSurfaceAudits": [{
            "kind": "assertion-surface-audit",
            "surface": "python-unittest",
            "assertionSource": "test_encoder::test_encode_len",
            "file": "test_encoder.py",
            "line": 5,
            "col": 4,
            "sourceStatus": "warranted",
            "status": "facts-emitted",
            "facts": [{
                "kind": "warranted",
                "contract": "test_encoder::test_encode_len::fact",
                "claim": "assert encode_len('abc') == 4",
                "claimCount": 1,
                "sourcePath": "test_encoder.py",
                "sourceMemento": fact_source,
                "sourceMementos": [fact_source]
            }],
            "supportFacts": [],
            "sourceMemento": fact_source
        }],
        "sourceMementos": [fact_source],
        "diagnostics": []
    });
    let body_response = json!({
        "kind": "ir-document",
        "ir": [{
            "kind": "function-contract",
            "name": "encode_len",
            "outBinding": "out",
            "formals": ["payload"],
            "formalSorts": [{"kind": "named", "name": "String"}],
            "post": body_formula,
            "sourceWarrants": [body_source]
        }],
        "sourceLedger": {
            "source_loci": 1,
            "source_warranted": 1,
            "source_inactive": 0,
            "source_support": 0,
            "source_boundary": 0,
            "source_unresolved": 0
        },
        "sourceAudits": [],
        "factoryAudits": [],
        "factoryAuditSummary": {
            "emittedRows": 1,
            "statusCounts": {"warranted": 1, "incomplete": 0, "support": 0, "unresolved": 0},
            "unresolvedSites": [],
            "factoryWalk": [{
                "kind": "factory-walk-row",
                "file": "encoder.py",
                "line": 2,
                "col": 4,
                "status": "warranted",
                "verdict": "complete",
                "selected": "return",
                "output": "post",
                "sourceFunctionName": "encode_len",
                "contractName": "encode_len",
                "claimName": "encode_len",
                "emittedFormula": body_formula,
                "sourceMemento": body_source
            }]
        },
        "sourceMementos": [body_source],
        "diagnostics": []
    });

    let fact_response_path = dir.path().join("fact-response.json");
    let body_response_path = dir.path().join("body-response.json");
    fs::write(
        &fact_response_path,
        serde_json::to_string(&fact_response).expect("serialize fact response"),
    )
    .expect("write fact response");
    fs::write(
        &body_response_path,
        serde_json::to_string(&body_response).expect("serialize body response"),
    )
    .expect("write body response");

    fn write_response_plugin(script: &Path, response_path: &Path, name: &str) {
        let response = response_path.display().to_string().replace('\'', "'\\''");
        write_executable(
            script,
            &format!(
                r#"#!/usr/bin/env bash
set -euo pipefail
response='{response}'
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{{"jsonrpc":"2.0","id":1,"result":{{"name":"{name}","protocol_version":"pep/1.7.0","capabilities":{{}}}}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{{"jsonrpc":"2.0","id":2,"result":{{"kit":{{"id":"test-fixture","language":"bash","version":"0.0.0"}},"rpc":{{"methods":[{{"name":"lift","required":true}}]}},"proofResolution":{{"strategy":"none"}},"residueCategories":[]}}}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":2,"result":'
    cat "$response"
    printf '}}\n'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{{"jsonrpc":"2.0","id":3,"result":null}}'
    exit 0
  fi
done
"#
            ),
        );
    }

    let fact_plugin = dir.path().join("fact-plugin.sh");
    let body_plugin = dir.path().join("body-plugin.sh");
    write_response_plugin(&fact_plugin, &fact_response_path, "python-test-assertions");
    write_response_plugin(&body_plugin, &body_response_path, "python-body-universes");
    fs::write(
        fact_manifest.join("manifest.toml"),
        format!(
            "name = \"python-test-assertions\"\ncommand = [\"{}\"]\n",
            fact_plugin.display()
        ),
    )
    .expect("write fact manifest");
    fs::write(
        body_manifest.join("manifest.toml"),
        format!(
            "name = \"python-body-universes\"\ncommand = [\"{}\"]\n",
            body_plugin.display()
        ),
    )
    .expect("write body manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("lift")
            .arg("--report")
            .arg("--json")
            .arg(&project),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "lift report must mint then render from the proof-only report path\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("report JSON parses");
    let assertion_audits = report["assertionSurfaceAudits"]
        .as_array()
        .expect("assertionSurfaceAudits array");
    assert_eq!(
        assertion_audits.len(),
        1,
        "unit-test assertion audit must survive mint into the proof-only report: {report:#}"
    );
    assert_eq!(
        assertion_audits[0]["facts"][0]["contract"].as_str(),
        Some("test_encoder::test_encode_len::fact")
    );
    assert!(
        report["contracts"]
            .as_array()
            .expect("contracts array")
            .iter()
            .any(|entry| entry["name"].as_str() == Some("encode_len")),
        "body universe should also be reconstructed from the same proof: {report:#}"
    );
    assert_eq!(
        report["factoryWalk"]
            .as_array()
            .expect("factoryWalk array")
            .len(),
        1,
        "factory walk should still be proof-only evidence: {report:#}"
    );
}

#[test]
fn mint_ignores_emit_only_plugin_registrations() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let lift_manifest = project.join(".sugar/lift/test-lift");
    let out_dir = dir.path().join("out");
    fs::create_dir_all(&lift_manifest).expect("create lift manifest dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "java-testng-emitter"
kind = "emit"
surface = "java-testng"
emit = "testng"

[[plugins]]
name = "test-lift"
kind = "lift"
surface = "test-lift"
emit = "ir-document"
"#,
    )
    .expect("write project config");

    let plugin = dir.path().join("test-lift.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"test-lift","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"contract","name":"demo.contract","outBinding":"out","post":{"kind":"atomic","name":"demo_true","args":[]}}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        lift_manifest.join("manifest.toml"),
        format!(
            "name = \"test-lift\"\ncommand = [\"{}\"]\n",
            plugin.display()
        ),
    )
    .expect("write lift manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("mint")
            .arg("--project")
            .arg(&project)
            .arg("--out")
            .arg(&out_dir)
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "mint should ignore kind=emit registrations instead of resolving .sugar/lift/java-testng\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("mint JSON parses");
    assert_eq!(report["surface"], "test-lift");
    assert_eq!(report["lift"]["kind"], "ir-document");
}

#[test]
fn mint_surfaces_structured_lift_gap_diagnostics_from_consumer_surfaces() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let producer_manifest = project.join(".sugar/lift/producer");
    let consumer_manifest = project.join(".sugar/lift/consumer");
    let out_dir = dir.path().join("out");
    fs::create_dir_all(&producer_manifest).expect("create producer manifest dir");
    fs::create_dir_all(&consumer_manifest).expect("create consumer manifest dir");
    fs::create_dir_all(project.join("src")).expect("create src dir");
    fs::write(
        project.join("src/lib.rs"),
        "pub fn caller() -> Option<i32> { Some(1) }\n",
    )
    .expect("write source");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "producer"
surface = "producer"
emit = "ir-document"

[[plugins]]
name = "consumer"
surface = "consumer"
"#,
    )
    .expect("write project config");

    let producer = dir.path().join("producer.sh");
    write_executable(
        &producer,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"producer","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"contract","name":"caller@src/lib.rs:1:1","outBinding":"out","post":{"kind":"atomic","name":"caller_post","args":[]}}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );

    let consumer = dir.path().join("consumer.sh");
    write_executable(
        &consumer,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"consumer","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"sugar.plugin.lift_implications"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[],"diagnostics":[{"kind":"lift-gap","reason":"no-contract-for-callee","callee":"Some","file":"src/lib.rs","line":1,"col":34}]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );

    fs::write(
        producer_manifest.join("manifest.toml"),
        format!(
            "name = \"producer\"\ncommand = [\"{}\"]\n",
            producer.display()
        ),
    )
    .expect("write producer manifest");
    fs::write(
        consumer_manifest.join("manifest.toml"),
        format!(
            "name = \"consumer\"\ncommand = [\"{}\"]\nmethod = \"sugar.plugin.lift_implications\"\nphase = \"consumer\"\n",
            consumer.display()
        ),
    )
    .expect("write consumer manifest");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("mint")
            .arg("--project")
            .arg(&project)
            .arg("--out")
            .arg(&out_dir),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "mint should succeed while surfacing non-fatal lift gaps\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stdout.contains("lift-gap") && stdout.contains("no-contract-for-callee"),
        "structured lift-gap diagnostic should be visible in mint output\nstdout:\n{stdout}"
    );
    assert!(
        stdout.contains("Some") && stdout.contains("src/lib.rs:1:34"),
        "diagnostic should name the uncovered Rust callee and locus\nstdout:\n{stdout}"
    );
}

#[test]
fn mint_uses_path_document_from_project_config() {
    let dir = tempfile::tempdir().expect("create tempdir");
    let project = dir.path().join("project");
    let manifest_dir = project.join(".sugar/lift/path-lift");
    let path_dir = project.join(".sugar/paths");
    let out_dir = dir.path().join("path-out");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    fs::create_dir_all(&path_dir).expect("create path dir");

    let plugin = dir.path().join("path-lift-plugin.sh");
    write_executable(
        &plugin,
        r#"#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  if [[ "$line" == *'"method":"initialize"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"path-lift","protocol_version":"pep/1.7.0","capabilities":{}}}'
  elif [[ "$line" == *'"method":"sugar.plugin.kit_declaration"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"test-fixture","language":"bash","version":"0.0.0"},"rpc":{"methods":[{"name":"lift","required":true}]},"proofResolution":{"strategy":"none"},"residueCategories":[]}}'
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"contract","name":"path.config.contract","outBinding":"out","post":{"kind":"atomic","name":"path_config_true","args":[]}}],"diagnostics":[]}}'
  elif [[ "$line" == *'"method":"shutdown"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
    exit 0
  fi
done
"#,
    );
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"path-lift\"\ncommand = [\"{}\"]\n",
            plugin.display()
        ),
    )
    .expect("write manifest");

    let lift_input = Input::Spec(json!({
        "surface": "path-lift",
        "workspace_root": project.canonicalize().unwrap_or_else(|_| project.clone()),
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {
            "layer": "all",
            "identifyOnly": false
        }
    }));
    let mint_input = Input::Spec(json!({
        "projectRoot": project.display().to_string(),
        "surface": "path-lift",
        "outDir": out_dir.display().to_string(),
        "options": {
            "quiet": true
        }
    }));
    let lift_input_cid = address(&lift_input);
    let mint_input_cid = address(&mint_input);
    let path = CorePath {
        algebra: vec![
            PathAlgebra {
                name: "lift".to_string(),
                kit: "lift-plugin:path-lift".to_string(),
                inputs: vec![lift_input_cid],
                depends_on: vec![],
                verb: Verb::Transform,
            },
            PathAlgebra {
                name: "mint".to_string(),
                kit: "sugar-mint".to_string(),
                inputs: vec![mint_input_cid],
                depends_on: vec!["lift".to_string()],
                verb: Verb::Transform,
            },
        ],
    };
    let document = PathDocument::from_path_and_inputs(path, vec![lift_input, mint_input])
        .expect("build path document");
    fs::write(
        path_dir.join("mint.json"),
        serde_json::to_string_pretty(&document).expect("serialize path document"),
    )
    .expect("write path document");
    fs::write(
        project.join(".sugar/config.toml"),
        "[paths.mint]\nfile = \".sugar/paths/mint.json\"\n",
    )
    .expect("write config");

    let output = output_retrying_etxtbsy(
        Command::new(sugar_bin())
            .arg("mint")
            .arg("--project")
            .arg(&project)
            .arg("--json")
            .arg("--quiet"),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "mint should load PathDocument from [paths.mint], not require [authoring.lift]\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("mint JSON parses");
    assert_eq!(report["surface"], "path-lift");
    assert_eq!(
        report["proofFile"]
            .as_str()
            .map(|value| value.contains("path-out")),
        Some(true)
    );
    assert_eq!(report["lift"]["kind"], "ir-document");
}

#[test]
fn lift_python_emits_contracts_and_callsite_implications() {
    if !python_blake3_available() {
        eprintln!("skipping python lift integration: python3 module `blake3` is unavailable");
        return;
    }
    let root = repo_root();
    let project = tempfile::tempdir().expect("create tempdir");
    fs::write(
        project.path().join("test_parser.py"),
        r#"
def parse_int(raw):
    if raw > 0:
        return 42
    return 0

def test_parse_value_scope():
    actual = parse_int(5)
    assert actual == 42

def test_direct_parse():
    assert parse_int(5) == 42
"#,
    )
    .expect("write python fixture");
    fs::create_dir_all(project.path().join(".sugar")).expect("create config dir");
    fs::write(
        project.path().join(".sugar/config.toml"),
        r#"[authoring.lift]
surface = "python"
"#,
    )
    .expect("write config");
    let manifest_dir = project.path().join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    let python_src = root.join("implementations/python/sugar-lift-py-tests/src");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"python-lift\"\ncommand = [\"env\", \"PYTHONPATH={}\", \"python3\", \"-m\", \"sugar_lift_py_tests.lift_rpc\", \"--rpc\"]\nworking_dir = \".\"\n",
            python_src.display()
        ),
    )
    .expect("write manifest");

    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg(project.path())
        .arg("--json")
        .arg("--quiet")
        .current_dir(&root)
        .output()
        .expect("spawn sugar lift python");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar lift python failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("lift JSON parses");
    assert_eq!(report["kind"], "ir-document");
    let ir = report["ir"].as_array().expect("ir array");
    let implications = report["implications"]
        .as_array()
        .expect("implications array");
    // Current batch lift emits one callable universe for the callee and merges
    // same-semantic-CID equality facts into one EUF assertion with unioned
    // warrants. A call-to-call RHS is not a literal expected value under
    // return-sort truth: the LHS call carries the dug Int return sort, while the
    // unresolved RHS `call:` ctor remains LegacyCtor and the construction law
    // correctly refuses Eq(Int, LegacyCtor).
    assert_eq!(
        ir.len(),
        2,
        "expected one callable universe plus one merged literal-call assertion: {report:#}"
    );
    assert_eq!(
        implications.len(),
        0,
        "literal call lift composes without explicit implication rows: {report:#}"
    );
    let names: Vec<_> = ir
        .iter()
        .map(|decl| decl["name"].as_str().unwrap_or_default())
        .collect();
    assert!(
        names.iter().all(|name| {
            *name == "test_parser::parse_int::callable"
                || *name == "parse_int#euf#c:call:parse_int(i:5)::assertion"
        }),
        "unexpected literal-call contract names: {names:?}"
    );
    assert_eq!(
        names
            .iter()
            .filter(|name| **name == "test_parser::parse_int::callable")
            .count(),
        1,
        "expected one callable universe for the literal-call callee: {names:?}"
    );
    let euf_assertions: Vec<_> = ir
        .iter()
        .filter(|decl| {
            let name = decl["name"].as_str().unwrap_or_default();
            name == "parse_int#euf#c:call:parse_int(i:5)::assertion"
        })
        .collect();
    assert_eq!(
        euf_assertions.len(),
        1,
        "same semantic literal-call facts must merge into one EUF assertion: {report:#}"
    );
    let assertion = euf_assertions[0];
    assert_eq!(assertion["inv"]["name"], "=");
    assert_eq!(assertion["inv"]["args"][0]["name"], "call:parse_int");
    assert_eq!(
        assertion["inv"]["args"][0]["args"][0]["sort"]["name"],
        "Int"
    );
    assert_eq!(assertion["inv"]["args"][0]["args"][0]["value"], 5);
    assert_eq!(assertion["inv"]["args"][1]["sort"]["name"], "Int");
    assert_eq!(assertion["inv"]["args"][1]["value"], 42);
    let source_warrants = assertion["sourceWarrants"]
        .as_array()
        .expect("source warrants");
    assert_eq!(source_warrants.len(), 2);
    let source_functions: Vec<_> = source_warrants
        .iter()
        .map(|warrant| warrant["sourceFunctionName"].as_str().unwrap_or_default())
        .collect();
    assert_eq!(
        source_functions,
        vec!["test_parse_value_scope", "test_direct_parse"]
    );
    let proof_warrants = assertion["proofirProvenance"]["warrants"]
        .as_array()
        .expect("proofir warrants");
    assert_eq!(proof_warrants.len(), 2);
    let proof_warrant_lines: Vec<_> = proof_warrants
        .iter()
        .map(|warrant| {
            (
                warrant["kind"].as_str().unwrap_or_default(),
                warrant["locus"]["line"].as_i64().unwrap_or_default(),
            )
        })
        .collect();
    assert_eq!(proof_warrant_lines, vec![("Stated", 9), ("Stated", 12)]);
}

#[test]
fn lift_python_emits_production_wp_callsite_implications() {
    if !python_blake3_available() {
        eprintln!("skipping python lift integration: python3 module `blake3` is unavailable");
        return;
    }
    let root = repo_root();
    let project = tempfile::tempdir().expect("create tempdir");
    fs::write(
        project.path().join("app.py"),
        r#"
def f(x):
    if x > 0:
        return 42
    return 0

def test_f():
    assert f(42) == 42
"#,
    )
    .expect("write python fixture");
    fs::create_dir_all(project.path().join(".sugar")).expect("create config dir");
    fs::write(
        project.path().join(".sugar/config.toml"),
        r#"[authoring.lift]
surface = "python"
"#,
    )
    .expect("write config");
    let manifest_dir = project.path().join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    let python_src = root.join("implementations/python/sugar-lift-py-tests/src");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"python-lift\"\ncommand = [\"env\", \"PYTHONPATH={}\", \"python3\", \"-m\", \"sugar_lift_py_tests.lift_rpc\", \"--rpc\"]\nworking_dir = \".\"\n",
            python_src.display()
        ),
    )
    .expect("write manifest");

    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg(project.path())
        .arg("--json")
        .arg("--quiet")
        .current_dir(&root)
        .output()
        .expect("spawn sugar lift python");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar lift python failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("lift JSON parses");
    assert_eq!(report["kind"], "ir-document");
    let ir = report["ir"].as_array().expect("ir array");
    let implications = report["implications"]
        .as_array()
        .expect("implications array");
    assert_eq!(
        ir.len(),
        2,
        "expected callable universe plus literal-call assertion: {report:#}"
    );
    assert_eq!(
        implications.len(),
        0,
        "literal call lift composes without explicit implication rows: {report:#}"
    );

    let names: Vec<_> = ir
        .iter()
        .map(|decl| decl["name"].as_str().unwrap_or_default())
        .collect();
    assert_eq!(
        names,
        vec!["app::f::callable", "f#euf#c:call:f(i:42)::assertion"]
    );

    let callable = ir
        .iter()
        .find(|decl| decl["kind"] == "function-contract")
        .expect("callable universe");
    assert_eq!(callable["post"]["kind"], "and");
    assert_eq!(callable["post"]["operands"].as_array().unwrap().len(), 2);

    let assertion = ir
        .iter()
        .find(|decl| decl["kind"] == "contract")
        .expect("literal-call assertion");
    assert_eq!(assertion["inv"]["name"], "=");
    assert_eq!(assertion["inv"]["args"][0]["name"], "call:f");
    assert_eq!(assertion["inv"]["args"][0]["args"][0]["value"], 42);
    assert_eq!(assertion["inv"]["args"][1]["value"], 42);
}

#[test]
fn lift_python_shows_production_composes_but_unittest_contracts_conflict() {
    if !python_blake3_available() {
        eprintln!("skipping python lift integration: python3 module `blake3` is unavailable");
        return;
    }
    let root = repo_root();
    let project = tempfile::tempdir().expect("create tempdir");
    fs::write(
        project.path().join("app.py"),
        r#"
def checked(x):
    if x > 0:
        return 1
    return 0

def composed_ok():
    assert checked(5) == 1

def test_checked_returns_1():
    actual = checked(5)
    assert actual == 1

def test_checked_does_not_return_1():
    actual = checked(5)
    assert actual != 1
"#,
    )
    .expect("write python fixture");
    fs::create_dir_all(project.path().join(".sugar")).expect("create config dir");
    fs::write(
        project.path().join(".sugar/config.toml"),
        r#"[authoring.lift]
surface = "python"
"#,
    )
    .expect("write config");
    let manifest_dir = project.path().join(".sugar/lift/python");
    fs::create_dir_all(&manifest_dir).expect("create manifest dir");
    let python_src = root.join("implementations/python/sugar-lift-py-tests/src");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"python-lift\"\ncommand = [\"env\", \"PYTHONPATH={}\", \"python3\", \"-m\", \"sugar_lift_py_tests.lift_rpc\", \"--rpc\"]\nworking_dir = \".\"\n",
            python_src.display()
        ),
    )
    .expect("write manifest");

    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg(project.path())
        .arg("--json")
        .arg("--quiet")
        .current_dir(&root)
        .output()
        .expect("spawn sugar lift python");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "sugar lift python failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    let report: serde_json::Value = serde_json::from_str(&stdout).expect("lift JSON parses");
    let ir = report["ir"].as_array().expect("ir array");
    let implications = report["implications"]
        .as_array()
        .expect("implications array");

    let callable_contracts: Vec<_> = ir
        .iter()
        .filter(|decl| {
            let name = decl["name"].as_str().unwrap_or_default();
            name == "app::checked::callable"
        })
        .collect();
    assert_eq!(
        callable_contracts.len(),
        1,
        "expected one callable universe for the supported checked(...) equalities: {report:#}"
    );

    let euf_assertions: Vec<_> = ir
        .iter()
        .filter(|decl| {
            let name = decl["name"].as_str().unwrap_or_default();
            name == "checked#euf#c:call:checked(i:5)::assertion"
        })
        .collect();
    assert_eq!(
        euf_assertions.len(),
        1,
        "same semantic checked(5) == 1 facts must merge into one EUF assertion: {report:#}"
    );
    let euf_assertion = euf_assertions[0];
    assert_eq!(euf_assertion["inv"]["name"], "=");
    assert_eq!(euf_assertion["inv"]["args"][0]["name"], "call:checked");
    assert_eq!(
        euf_assertion["inv"]["args"][0]["args"][0]["sort"]["name"],
        "Int"
    );
    assert_eq!(euf_assertion["inv"]["args"][0]["args"][0]["value"], 5);
    assert_eq!(euf_assertion["inv"]["args"][1]["sort"]["name"], "Int");
    assert_eq!(euf_assertion["inv"]["args"][1]["value"], 1);
    let source_warrants = euf_assertion["sourceWarrants"]
        .as_array()
        .expect("source warrants");
    assert_eq!(source_warrants.len(), 2);
    let source_functions: Vec<_> = source_warrants
        .iter()
        .map(|warrant| warrant["sourceFunctionName"].as_str().unwrap_or_default())
        .collect();
    assert_eq!(
        source_functions,
        vec!["composed_ok", "test_checked_returns_1"]
    );
    let proof_warrants = euf_assertion["proofirProvenance"]["warrants"]
        .as_array()
        .expect("proofir warrants");
    assert_eq!(proof_warrants.len(), 2);
    let proof_warrant_lines: Vec<_> = proof_warrants
        .iter()
        .map(|warrant| {
            (
                warrant["kind"].as_str().unwrap_or_default(),
                warrant["locus"]["line"].as_i64().unwrap_or_default(),
            )
        })
        .collect();
    assert_eq!(proof_warrant_lines, vec![("Stated", 8), ("Stated", 12)]);

    let negative_assertions: Vec<_> = ir
        .iter()
        .filter(|decl| {
            let name = decl["name"].as_str().unwrap_or_default();
            name.ends_with("::assertion") && decl["inv"]["name"] == "≠"
        })
        .collect();
    assert_eq!(
        negative_assertions.len(),
        1,
        "negative bound-name comparison remains a location-keyed assertion: {report:#}"
    );
    assert_eq!(implications.len(), 0);
}
