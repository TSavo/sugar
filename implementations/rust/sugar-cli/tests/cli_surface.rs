// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use libsugar::core::{address, Input, Path as CorePath, PathAlgebra, PathDocument, Verb};
use serde_json::json;

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
fn materialize_does_not_expose_source_lang_discovery_mode() {
    let help = Command::new(sugar_bin())
        .arg("materialize")
        .arg("--help")
        .output()
        .expect("spawn sugar materialize --help");
    let stdout = String::from_utf8_lossy(&help.stdout);
    let stderr = String::from_utf8_lossy(&help.stderr);
    assert!(
        help.status.success(),
        "sugar materialize --help failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        !stdout.contains("--source-lang"),
        "`materialize --source-lang` is the legacy CLI-side cross-language discovery mode; source language discovery must be kit-owned over RPC\nstdout:\n{stdout}"
    );

    let rejected = Command::new(sugar_bin())
        .arg("materialize")
        .arg("--library")
        .arg("python-requests")
        .arg("--source-dir")
        .arg(".")
        .arg("--target")
        .arg("python")
        .arg("--source-lang")
        .arg("rust")
        .output()
        .expect("spawn sugar materialize --source-lang");
    let stderr = String::from_utf8_lossy(&rejected.stderr);
    assert!(
        !rejected.status.success(),
        "`sugar materialize --source-lang` must be rejected at the CLI boundary"
    );
    assert!(
        stderr.contains("unexpected argument")
            || stderr.contains("unrecognized")
            || stderr.contains("unknown"),
        "stderr should reject --source-lang at clap boundary\n{stderr}"
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
    let bridge = pool.bridges_by_symbol.get("callee").unwrap_or_else(|| {
        panic!(
            "consumer bridge should be indexed by sourceSymbol=callee; got {:?}",
            pool.bridges_by_symbol.keys().collect::<Vec<_>>()
        )
    });
    let target_cid = sugar_verifier::types::memento_body_field(bridge, "targetContractCid")
        .and_then(|v| v.as_str())
        .expect("bridge targetContractCid");
    let target = pool
        .mementos
        .get(target_cid)
        .unwrap_or_else(|| panic!("bridge target cid {target_cid} must resolve in same proof"));
    assert_eq!(
        sugar_verifier::types::memento_kind(target).as_deref(),
        Some("contract")
    );
    let implication_count = pool
        .mementos
        .values()
        .filter(|env| sugar_verifier::types::memento_kind(env).as_deref() == Some("implication"))
        .count();
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
  elif [[ "$line" == *'"method":"lift"'* ]]; then
    printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"function-contract","name":"encoded_len","outBinding":"out","post":{"kind":"atomic","name":"=","args":[{"kind":"var","name":"out"},{"kind":"ctor","name":"call:encoded_len","args":[{"kind":"var","name":"n"},{"kind":"var","name":"padded"}]}]},"sourceWarrants":[{"kind":"source-memento","file":"src/encode.rs","sourceFunctionName":"encoded_len","source_function_name":"encoded_len","span":{"start_line":97,"start_col":0,"end_line":122,"end_col":1},"paramNames":["bytes_len","padding"],"param_names":["bytes_len","padding"],"source_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","template_cid":"blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}],"sourceLedger":{"source_loci":1,"source_warranted":1,"source_inactive":0,"source_support":0,"source_refused":0,"source_unresolved":0},"sourceAudits":[{"role":"rust-fn-contracts","universe_kind":"function-contract","totals":{"source_loci":1,"source_warranted":1,"source_inactive":0,"source_support":0,"source_refused":0,"source_unresolved":0},"loci":[{"file":"src/encode.rs","role":"rust-fn-contracts","universe_kind":"function-contract","ast_path":"encoded_len","sourceFunctionName":"encoded_len","line":97,"col":0}]}],"factoryAudits":[],"sourceMementos":[{"kind":"source-memento","file":"src/encode.rs","sourceFunctionName":"encoded_len","source_function_name":"encoded_len","span":{"start_line":97,"start_col":0,"end_line":122,"end_col":1},"paramNames":["bytes_len","padding"],"param_names":["bytes_len","padding"],"source_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","template_cid":"blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],"factoryAuditSummary":{"emittedRows":0,"statusCounts":{"warranted":0,"refused":0,"support":0,"unresolved":0},"unresolvedSites":[],"factoryWalk":[]},"diagnostics":[]}}'
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
    printf '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"bridge","name":"dig:encoded_len","sourceSymbol":"encoded_len","targetContractCid":"%s","targetLayer":"rust-fn-contracts"}],"sourceLedger":{"source_loci":0,"source_warranted":0,"source_inactive":0,"source_support":0,"source_refused":0,"source_unresolved":0},"sourceAudits":[],"factoryAudits":[],"sourceMementos":[],"factoryAuditSummary":{"emittedRows":0,"statusCounts":{"warranted":0,"refused":0,"support":0,"unresolved":0},"unresolvedSites":[],"factoryWalk":[]},"diagnostics":[]}}\n' "$cid"
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
    return int(raw)

def test_parse_value_scope():
    actual = parse_int("42")
    assert actual == 42

def test_direct_parse():
    assert parse_int("42") == 42

def test_two_callsites():
    assert parse_int("42") == parse_int("042")
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
            "name = \"python-lift\"\ncommand = [\"env\", \"PYTHONPATH={}\", \"python3\", \"-m\", \"sugar_lift_py_tests.lsp\"]\nworking_dir = \".\"\n",
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
    // EUF argument-carrying lift (post-BINDING-EUF-change): same-arg callsites
    // across tests AND across the binding/direct forms collapse to one EUF-keyed
    // base (per concrete arg). The fixture has:
    //   test_parse_value_scope: actual = parse_int("42") via variable binding
    //     -> NOW EUF-keyed (concrete 1-arg binding-form substitution):
    //        parse_int#euf#...(s:'42')   [coalesces with the direct forms below]
    //   test_direct_parse: parse_int("42") == 42
    //     -> EUF-keyed (s:'42'): parse_int#euf#...(s:'42')
    //   test_two_callsites: parse_int("42") == parse_int("042")
    //     -> EUF-keyed: parse_int#euf#...(s:'42') + parse_int#euf#...(s:'042')
    // After within-file EUF coalesce: TWO unique bases — (s:'42') and (s:'042').
    //   (s:'42') gathers THREE consistent ``== 42`` assertions (binding + direct
    //   + two_callsites arg0) into one conjoined ::assertion (all SAT -> PROVEN).
    // => 2 ::facts + 2 ::assertion = 4 contracts.
    // Implications: 4 (one facts->assertion edge per callsite OCCURRENCE: three
    //   to the (s:'42') base + one to the (s:'042') base).
    assert_eq!(
        ir.len(),
        4,
        "expected callsite fact + assertion contracts: {report:#}"
    );
    assert_eq!(
        implications.len(),
        4,
        "expected one implication per lifted callsite occurrence: {report:#}"
    );
    let names: Vec<_> = ir
        .iter()
        .map(|decl| decl["name"].as_str().unwrap_or_default())
        .collect();
    // All names start with "parse_int" (now all #euf#-arg-keyed for concrete args)
    assert!(
        names.iter().all(|name| name.starts_with("parse_int")),
        "all names must start with parse_int: {names:?}"
    );
    for test_name in [
        "test_parse_value_scope",
        "test_direct_parse",
        "test_two_callsites",
    ] {
        assert!(names.iter().all(|name| !name.contains(test_name)));
    }
    assert_eq!(
        names
            .iter()
            .filter(|name| name.ends_with("::facts"))
            .count(),
        2,
        "expected 2 ::facts contracts: {names:?}"
    );
    assert_eq!(
        names
            .iter()
            .filter(|name| name.ends_with("::assertion"))
            .count(),
        2,
        "expected 2 ::assertion contracts: {names:?}"
    );
    for implication in implications {
        let antecedent = implication["antecedent"].as_str().unwrap_or_default();
        let consequent = implication["consequent"].as_str().unwrap_or_default();
        assert!(antecedent.ends_with("::facts"));
        assert!(consequent.ends_with("::assertion"));
        assert!(names.contains(&antecedent));
        assert!(names.contains(&consequent));
    }
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
    if x < 10:
        raise ValueError("x must be >= 10")
    return x

def caller():
    y = 42
    return f(y)
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
            "name = \"python-lift\"\ncommand = [\"env\", \"PYTHONPATH={}\", \"python3\", \"-m\", \"sugar_lift_py_tests.lsp\"]\nworking_dir = \".\"\n",
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
        3,
        "expected callsite, let, and entry WP edges: {report:#}"
    );
    assert_eq!(
        implications.len(),
        3,
        "expected one pre->post implication per WP edge: {report:#}"
    );

    let names: Vec<_> = ir
        .iter()
        .map(|decl| decl["name"].as_str().unwrap_or_default())
        .collect();
    assert!(names.iter().all(|name| name.starts_with("f@app.py:")));
    assert!(names.iter().any(|name| name.ends_with("::callsite")));
    assert!(names.iter().any(|name| name.ends_with("::let:y")));
    assert!(names.iter().any(|name| name.ends_with("::entry")));

    let let_edge = ir
        .iter()
        .find(|decl| {
            decl["name"]
                .as_str()
                .unwrap_or_default()
                .ends_with("::let:y")
        })
        .expect("let edge");
    assert_eq!(let_edge["pre"]["name"], "≥");
    assert_eq!(let_edge["pre"]["args"][0]["value"], 42);
    assert_eq!(let_edge["post"]["name"], "≥");
    assert_eq!(let_edge["post"]["args"][0]["name"], "y");

    for implication in implications {
        let antecedent = implication["antecedent"].as_str().unwrap_or_default();
        let consequent = implication["consequent"].as_str().unwrap_or_default();
        assert_eq!(antecedent, consequent);
        assert!(names.contains(&antecedent));
        assert_eq!(implication["antecedentSlot"], "pre");
        assert_eq!(implication["consequentSlot"], "post");
        assert_eq!(implication["prover"], "python-wp-walk");
    }
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
import unittest

def checked(x):
    if x < 10:
        raise ValueError("x must be >= 10")
    return x

def composed_ok():
    y = 42
    return checked(y)

class CheckedContracts(unittest.TestCase):
    def test_checked_returns_42(self):
        actual = checked(42)
        self.assertEqual(actual, 42)

    def test_checked_does_not_return_42(self):
        actual = checked(42)
        self.assertNotEqual(actual, 42)
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
            "name = \"python-lift\"\ncommand = [\"env\", \"PYTHONPATH={}\", \"python3\", \"-m\", \"sugar_lift_py_tests.lsp\"]\nworking_dir = \".\"\n",
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

    let production: Vec<_> = ir
        .iter()
        .filter(|decl| {
            let name = decl["name"].as_str().unwrap_or_default();
            name.starts_with("checked@app.py:")
                && (name.ends_with("::callsite")
                    || name.ends_with("::let:y")
                    || name.ends_with("::entry"))
        })
        .collect();
    assert_eq!(
        production.len(),
        3,
        "expected production callsite, let, and entry WP edges: {report:#}"
    );
    let let_edge = production
        .iter()
        .copied()
        .find(|decl| {
            decl["name"]
                .as_str()
                .unwrap_or_default()
                .ends_with("::let:y")
        })
        .expect("let edge");
    assert_eq!(let_edge["pre"]["name"], "≥");
    assert_eq!(let_edge["pre"]["args"][0]["value"], 42);
    assert_eq!(let_edge["pre"]["args"][1]["value"], 10);

    // BINDING-FORM EUF SUBSTITUTION (post-fix): both unittest methods bind
    // ``actual = checked(42)`` (a CONCRETE 1-arg call) then assert contradictory
    // values (``== 42`` and ``!= 42``).  The bound assertion subject is now the
    // EUF ctor ``callresult_checked_a1(42)`` (not the per-method SSA var), so the
    // two cross-method assertions coalesce by name into ONE
    // ``checked#euf#...::assertion`` whose inv conjoins both equalities — a
    // contradiction that fires UNSAT (REFUSED) at prove time.  That is the
    // "contracts conflict" this test asserts, now as a single coalesced
    // contradictory contract rather than two independent location-keyed ones.
    let test_assertions: Vec<_> = ir
        .iter()
        .filter(|decl| {
            let name = decl["name"].as_str().unwrap_or_default();
            name.starts_with("checked#euf#") && name.ends_with("::assertion")
        })
        .collect();
    assert_eq!(
        test_assertions.len(),
        1,
        "concrete-arg binding cross-method must coalesce into ONE EUF assertion: {report:#}"
    );
    // No location-keyed ::assertion survives for the concrete-arg binding.
    assert_eq!(
        ir.iter()
            .filter(|decl| {
                let name = decl["name"].as_str().unwrap_or_default();
                name.starts_with("checked@app.py:") && name.ends_with("::assertion")
            })
            .count(),
        0,
        "no location-keyed ::assertion should survive concrete-arg binding: {report:#}"
    );
    // The coalesced inv is an ``and`` of the two contradictory equalities.
    let coalesced = &test_assertions[0]["inv"];
    assert_eq!(coalesced["kind"], "and");
    let mut assertion_ops: Vec<_> = coalesced["operands"]
        .as_array()
        .expect("and operands")
        .iter()
        .map(|op| op["name"].as_str().unwrap_or_default())
        .collect();
    assertion_ops.sort_unstable();
    assert_eq!(assertion_ops, vec!["=", "≠"]);

    let wp_implications = implications
        .iter()
        .filter(|imp| imp["prover"] == "python-wp-walk")
        .count();
    let test_implications = implications
        .iter()
        .filter(|imp| imp["prover"] == "python-test-value-scope")
        .count();
    assert_eq!(wp_implications, 3);
    // Both value-scope facts-implies-assertion edges now point at the SAME
    // coalesced EUF assertion name (one edge per call-site occurrence).
    assert_eq!(test_implications, 2);
}
