// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar package`: package-shaped supply-chain receipt helpers.

use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use owo_colors::OwoColorize;
use sugar_canonicalizer::blake3_512_of;

use crate::lift_plugin::{self, LiftPluginError, LiftPluginOptions};
use crate::project_config::{read_project_config, read_user_config};
use crate::{OutputFlags, EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

#[derive(Parser, Debug, Clone)]
pub struct PackageArgs {
    #[command(subcommand)]
    pub cmd: PackageCmd,
}

#[derive(Subcommand, Debug, Clone)]
pub enum PackageCmd {
    /// Inspect a package through the configured lift plugin.
    Inspect(PackageInspectArgs),
    /// Mint a release proof pinning a shippable artifact's binaryCid.
    Attest(PackageAttestArgs),
    /// Attest + verify every artifact declared in a release manifest.
    Release(PackageReleaseArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct PackageInspectArgs {
    /// Package project root containing .sugar/config.toml.
    pub project: PathBuf,
    #[command(flatten)]
    pub out: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct PackageAttestArgs {
    /// The shippable artifact to pin (npm tarball, firmware image, ...).
    #[arg(long)]
    pub artifact: PathBuf,
    /// Package name recorded in the release proof.
    #[arg(long)]
    pub name: String,
    /// Package version recorded in the release proof.
    #[arg(long)]
    pub version: String,
    /// Where to write the `.proof` release attestation.
    #[arg(long)]
    pub out: PathBuf,
    #[command(flatten)]
    pub out_flags: OutputFlags,
}

#[derive(Parser, Debug, Clone)]
pub struct PackageReleaseArgs {
    /// Release manifest (TOML) declaring the shippable artifacts to pin.
    #[arg(long)]
    pub manifest: PathBuf,
    /// Base directory for resolving relative artifact paths. Defaults to the
    /// manifest's own directory.
    #[arg(long)]
    pub root: Option<PathBuf>,
    /// Directory to read/write per-artifact receipts. Defaults to
    /// `<manifest-dir>/.sugar/release`.
    #[arg(long)]
    pub receipts: Option<PathBuf>,
    /// Verify against existing receipts only; do not (re)attest. This is the
    /// consumer/gate side: fail if any artifact's bytes no longer match its
    /// pinned binaryCid.
    #[arg(long)]
    pub verify_only: bool,
    #[command(flatten)]
    pub out_flags: OutputFlags,
}

/// A release manifest: the declared set of a project's shippable artifacts.
/// This is the config that arms the coarse pin -- the durable record of what a
/// project pins about itself, rather than an ad-hoc per-invocation flag.
#[derive(Debug, serde::Deserialize)]
struct ReleaseManifest {
    /// Optional default version applied to artifacts without their own.
    version: Option<String>,
    #[serde(default)]
    artifact: Vec<ManifestArtifact>,
    /// Optional coverage gate: makes the manifest's completeness STRUCTURAL,
    /// not sworn. With it, every binary the workspace builds must be either
    /// pinned (an `[[artifact]]`) or explicitly excluded -- a new bin that is
    /// neither fails the release, so a shippable artifact can never be
    /// silently left unpinned.
    coverage: Option<Coverage>,
    /// Optional dependency-vector pin: content-addresses the COMPLETE Cargo.lock
    /// dependency closure (every `[[package]]`), so the supply chain is pinned
    /// TOTAL, not sworn. Conjunctive -- a changed/added/removed dep moves the CID
    /// (N-1 of N pinned is zero, the xz-class hole closed).
    dependencies: Option<DependencyPin>,
}

#[derive(Debug, serde::Deserialize)]
struct DependencyPin {
    /// Cargo.lock whose `[[package]]` entries are the dependency vectors to pin
    /// (relative to the release manifest's root).
    lockfile: String,
}

#[derive(Debug, serde::Deserialize)]
struct ManifestArtifact {
    name: String,
    path: PathBuf,
    version: Option<String>,
}

#[derive(Debug, serde::Deserialize)]
struct Coverage {
    /// Cargo manifest whose workspace bin targets define the shippable
    /// universe (relative to the release manifest's root).
    cargo_manifest: String,
    /// Bin targets deliberately NOT pinned (internal rpc/test/dev bins, or
    /// deliverables not pinned by this manifest). Each is an explicit
    /// decision; the gate fails on any bin that is neither pinned nor here.
    #[serde(default)]
    exclude: Vec<String>,
}

/// Content-address the COMPLETE dependency closure from a Cargo.lock: one
/// canonical line per `[[package]]` (`name\tversion\tsource\tchecksum`), sorted,
/// blake3-512 over the join. CONJUNCTIVE by construction -- the CID is over EVERY
/// dependency, so adding, removing, or version/checksum-changing ANY one moves the
/// CID (N-1 of N pinned is zero: a single unpinned dep is the xz-class hole, and
/// here there is no such hole because the pin is the whole set at once). Returns
/// `(cid, vector_count)`. Path/workspace deps carry no source/checksum; their
/// identity is `(name, version)` with empty trailing fields -- still pinned, never
/// dropped. Pure given the file bytes, so it is unit-testable without a registry.
fn dependency_vectors_cid(lockfile: &Path) -> Result<(String, usize), String> {
    let text = std::fs::read_to_string(lockfile)
        .map_err(|e| format!("read lockfile {}: {e}", lockfile.display()))?;
    dependency_vectors_cid_of_text(&text)
        .map_err(|e| format!("lockfile {}: {e}", lockfile.display()))
}

fn dependency_vectors_cid_of_text(text: &str) -> Result<(String, usize), String> {
    let parsed: toml::Value = toml::from_str(text).map_err(|e| format!("parse: {e}"))?;
    let packages = parsed
        .get("package")
        .and_then(|p| p.as_array())
        .ok_or_else(|| "no [[package]] entries".to_string())?;
    let mut lines: Vec<String> = Vec::with_capacity(packages.len());
    for pkg in packages {
        let field = |k: &str| pkg.get(k).and_then(|v| v.as_str()).unwrap_or("");
        lines.push(format!(
            "{}\t{}\t{}\t{}",
            field("name"),
            field("version"),
            field("source"),
            field("checksum"),
        ));
    }
    // Sort so the CID is canonical (lockfile package order is not guaranteed
    // stable across cargo versions); dups are kept (a real duplicate vector is a
    // distinct row, so a count-preserving swap still moves the CID).
    lines.sort();
    let canonical = lines.join("\n");
    Ok((blake3_512_of(canonical.as_bytes()), lines.len()))
}

/// Read the pinned `dependencyVectorsCid` from a DependencyVectorsReceipt.
fn read_pinned_dep_vectors_cid(receipt_path: &Path) -> Result<String, String> {
    let text = std::fs::read_to_string(receipt_path).map_err(|e| {
        format!(
            "read dependency-vectors receipt {}: {e}",
            receipt_path.display()
        )
    })?;
    let receipt: serde_json::Value = serde_json::from_str(&text).map_err(|e| {
        format!(
            "parse dependency-vectors receipt {}: {e}",
            receipt_path.display()
        )
    })?;
    receipt
        .get("dependencyVectorsCid")
        .and_then(|v| v.as_str())
        .map(String::from)
        .ok_or_else(|| {
            format!(
                "receipt {} missing dependencyVectorsCid",
                receipt_path.display()
            )
        })
}

/// Name the build-environment IO that determines an artifact's `binaryCid` but is
/// NOT the source itself: the toolchain, the host target, the build profile, and
/// the source commit. Together with the pinned dependency vectors, these are the
/// COMPLETE input set, so a stranger can reproduce the `binaryCid` under the NAMED
/// conditions (recomputable, not sworn). This is the "name every IO" half: each
/// input is reported with its value, or the explicit string `"unavailable"` if the
/// tool that reports it is absent -- NEVER silently omitted (a missing input read
/// as present is a silence read wrong). It carries no raw clock: every field is
/// rederivable/checkable (a stranger can run `rustc -vV`, check out the commit), so
/// there is no unsigned IO baked in. Testimony, not a pin: a different builder's
/// environment is fine; the receipt states the conditions THIS `binaryCid`
/// reproduces under.
/// Extract a `key: value` field from `rustc -vV` output (e.g. `release: 1.96.0`).
/// Pure, so the parsing is unit-tested without a toolchain.
fn parse_rustc_field(vv: &str, key: &str) -> Option<String> {
    vv.lines()
        .find_map(|l| l.strip_prefix(key).map(|v| v.trim().to_string()))
}

fn gather_build_inputs(root: &Path) -> serde_json::Value {
    let rustc_vv = std::process::Command::new("rustc")
        .arg("-vV")
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).into_owned());
    let from_rustc = |key: &str| -> String {
        rustc_vv
            .as_ref()
            .and_then(|s| parse_rustc_field(s, key))
            .unwrap_or_else(|| "unavailable".to_string())
    };
    let git_commit = std::process::Command::new("git")
        .current_dir(root)
        .args(["rev-parse", "HEAD"])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|| "unavailable".to_string());
    serde_json::json!({
        "rustcVersion": from_rustc("release: "),
        "hostTarget": from_rustc("host: "),
        "profile": "release",
        "gitCommit": git_commit,
    })
}

/// The accounting: workspace bins that are neither pinned nor excluded. A
/// non-empty result means the manifest's coverage is incomplete -- a bin can
/// ship unpinned. Pure, so the totality logic is unit-tested without cargo.
fn coverage_gaps(workspace_bins: &[String], pinned: &[String], excluded: &[String]) -> Vec<String> {
    let accounted: std::collections::BTreeSet<&str> = pinned
        .iter()
        .chain(excluded.iter())
        .map(String::as_str)
        .collect();
    let mut gaps: Vec<String> = workspace_bins
        .iter()
        .filter(|b| !accounted.contains(b.as_str()))
        .cloned()
        .collect();
    gaps.sort();
    gaps.dedup();
    gaps
}

/// Enumerate the workspace's own bin targets (the shippable universe) from
/// `cargo metadata --no-deps`. This is the STRUCTURAL source of truth -- the
/// set of binaries the build can produce -- not a hand-list.
fn workspace_bin_targets(cargo_manifest: &Path) -> Result<Vec<String>, String> {
    let out = std::process::Command::new("cargo")
        .args(["metadata", "--no-deps", "--format-version", "1"])
        .arg("--manifest-path")
        .arg(cargo_manifest)
        .output()
        .map_err(|e| format!("run cargo metadata: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "cargo metadata failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    let meta: serde_json::Value =
        serde_json::from_slice(&out.stdout).map_err(|e| format!("parse cargo metadata: {e}"))?;
    let mut bins = Vec::new();
    for pkg in meta["packages"].as_array().into_iter().flatten() {
        for target in pkg["targets"].as_array().into_iter().flatten() {
            let is_bin = target["kind"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|k| k.as_str() == Some("bin"));
            if is_bin {
                if let Some(name) = target["name"].as_str() {
                    bins.push(name.to_string());
                }
            }
        }
    }
    Ok(bins)
}

pub fn run(args: PackageArgs) -> u8 {
    match args.cmd {
        PackageCmd::Inspect(args) => run_inspect(args),
        PackageCmd::Attest(args) => run_attest(args),
        PackageCmd::Release(args) => run_release(args),
    }
}

/// The JSON PackageReleaseReceipt the admission gate consumes (top-level
/// `binaryCid`). Shared by single `attest` and manifest `release`.
fn release_receipt(name: &str, version: &str, binary_cid: &str, bytes: usize) -> serde_json::Value {
    serde_json::json!({
        "kind": "PackageReleaseReceipt",
        "package": {"name": name, "version": version},
        "binaryCid": binary_cid,
        "bytes": bytes,
    })
}

/// `sugar package release --manifest M`: the config-driven dogfood. Reads the
/// manifest, and for each declared artifact either attests it (content-address
/// its bytes, write a receipt) or, with `--verify-only`, checks its current
/// bytes against the pinned binaryCid in an existing receipt. Fail-closed: a
/// missing/unreadable artifact or receipt, or any binaryCid mismatch, fails
/// the whole release. This is the producer that ARMS the artifact rail from a
/// declared manifest -- a sound gate with no producer is a silence read wrong.
fn run_release(args: PackageReleaseArgs) -> u8 {
    let manifest_text = match std::fs::read_to_string(&args.manifest) {
        Ok(t) => t,
        Err(e) => {
            eprintln!(
                "{}: read manifest {}: {e}",
                "error".red().bold(),
                args.manifest.display()
            );
            return EXIT_USER_ERROR;
        }
    };
    let manifest: ReleaseManifest = match toml::from_str(&manifest_text) {
        Ok(m) => m,
        Err(e) => {
            eprintln!(
                "{}: parse manifest {}: {e}",
                "error".red().bold(),
                args.manifest.display()
            );
            return EXIT_USER_ERROR;
        }
    };
    if manifest.artifact.is_empty() {
        eprintln!(
            "{}: manifest {} declares no [[artifact]] entries",
            "error".red().bold(),
            args.manifest.display()
        );
        return EXIT_USER_ERROR;
    }

    let manifest_dir = args
        .manifest
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let root = args.root.clone().unwrap_or_else(|| manifest_dir.clone());
    let receipts = args
        .receipts
        .clone()
        .unwrap_or_else(|| manifest_dir.join(".sugar").join("release"));

    if !args.verify_only {
        if let Err(e) = std::fs::create_dir_all(&receipts) {
            eprintln!(
                "{}: mkdir {}: {e}",
                "error".red().bold(),
                receipts.display()
            );
            return EXIT_USER_ERROR;
        }
    }

    let mut results = Vec::new();
    let mut all_ok = true;
    for art in &manifest.artifact {
        let version = art
            .version
            .clone()
            .or_else(|| manifest.version.clone())
            .unwrap_or_else(|| "unversioned".to_string());
        let artifact_path = root.join(&art.path);
        let receipt_path = receipts.join(format!("{}.release.json", art.name));

        let outcome = release_one(
            &art.name,
            &version,
            &artifact_path,
            &receipt_path,
            args.verify_only,
        );
        if let Err(reason) = &outcome {
            all_ok = false;
            if !args.out_flags.json && !args.out_flags.quiet {
                eprintln!("  {} {}: {}", "FAIL".red().bold(), art.name, reason);
            }
        } else if !args.out_flags.json && !args.out_flags.quiet {
            let verb = if args.verify_only {
                "verified"
            } else {
                "attested"
            };
            println!("  {} {} ({verb})", "ok".green(), art.name);
        }
        results.push(serde_json::json!({
            "name": art.name,
            "ok": outcome.is_ok(),
            "binaryCid": outcome.as_ref().ok(),
            "reason": outcome.err(),
        }));
    }

    // Coverage gate: make the manifest's completeness STRUCTURAL. Enumerate
    // the workspace's bin targets and fail on any that is neither pinned nor
    // excluded -- so a newly-added shippable binary can never be silently left
    // out of the manifest.
    let mut coverage_json = serde_json::Value::Null;
    if let Some(cov) = &manifest.coverage {
        let cargo_manifest = root.join(&cov.cargo_manifest);
        match workspace_bin_targets(&cargo_manifest) {
            Ok(bins) => {
                let pinned: Vec<String> =
                    manifest.artifact.iter().map(|a| a.name.clone()).collect();
                let gaps = coverage_gaps(&bins, &pinned, &cov.exclude);
                coverage_json = serde_json::json!({
                    "ok": gaps.is_empty(),
                    "workspaceBins": bins.len(),
                    "pinned": pinned.len(),
                    "excluded": cov.exclude.len(),
                    "unaccounted": gaps,
                });
                if !gaps.is_empty() {
                    all_ok = false;
                    if !args.out_flags.json && !args.out_flags.quiet {
                        eprintln!(
                            "  {} coverage: {} workspace bin(s) neither pinned nor excluded: {}",
                            "FAIL".red().bold(),
                            gaps.len(),
                            gaps.join(", ")
                        );
                    }
                }
            }
            Err(e) => {
                all_ok = false;
                coverage_json = serde_json::json!({"ok": false, "error": e});
                if !args.out_flags.json && !args.out_flags.quiet {
                    eprintln!("  {} coverage: {e}", "FAIL".red().bold());
                }
            }
        }
    }

    // Dependency-vector pin: make the SUPPLY CHAIN total. Content-address the
    // complete Cargo.lock dependency closure; a changed/added/removed dep moves
    // the CID (conjunctive, N-1 of N is zero). attest writes the pin receipt;
    // verify-only re-derives and fails closed on any drift -- the xz-class hole
    // becomes a loud mismatch instead of a silent acceptance.
    let mut dependencies_json = serde_json::Value::Null;
    if let Some(dep) = &manifest.dependencies {
        let lockfile = root.join(&dep.lockfile);
        let receipt_path = receipts.join("dependency-vectors.release.json");
        match dependency_vectors_cid(&lockfile) {
            Ok((cid, count)) => {
                let outcome: Result<(), String> = if args.verify_only {
                    match read_pinned_dep_vectors_cid(&receipt_path) {
                        Ok(pinned) if pinned == cid => Ok(()),
                        Ok(pinned) => Err(format!(
                            "dependencyVectorsCid mismatch (pinned {pinned}, observed {cid}) \
                             -- the dependency closure drifted"
                        )),
                        Err(e) => Err(e),
                    }
                } else {
                    let receipt = serde_json::json!({
                        "kind": "DependencyVectorsReceipt",
                        "lockfile": dep.lockfile,
                        "vectorCount": count,
                        "dependencyVectorsCid": cid,
                    });
                    serde_json::to_string_pretty(&receipt)
                        .map_err(|e| format!("serialize dependency-vectors receipt: {e}"))
                        .and_then(|s| {
                            std::fs::write(&receipt_path, s)
                                .map_err(|e| format!("write {}: {e}", receipt_path.display()))
                        })
                };
                match outcome {
                    Ok(()) => {
                        dependencies_json = serde_json::json!({
                            "ok": true,
                            "vectorCount": count,
                            "dependencyVectorsCid": cid,
                        });
                        if !args.out_flags.json && !args.out_flags.quiet {
                            let verb = if args.verify_only {
                                "verified"
                            } else {
                                "attested"
                            };
                            println!(
                                "  {} dependency-vectors ({count} pinned, {verb})",
                                "ok".green()
                            );
                        }
                    }
                    Err(reason) => {
                        all_ok = false;
                        dependencies_json = serde_json::json!({"ok": false, "error": reason});
                        if !args.out_flags.json && !args.out_flags.quiet {
                            eprintln!("  {} dependency-vectors: {reason}", "FAIL".red().bold());
                        }
                    }
                }
            }
            Err(e) => {
                all_ok = false;
                dependencies_json = serde_json::json!({"ok": false, "error": e});
                if !args.out_flags.json && !args.out_flags.quiet {
                    eprintln!("  {} dependency-vectors: {e}", "FAIL".red().bold());
                }
            }
        }
    }

    // Build-input testimony: NAME every input that determines the artifacts'
    // binaryCid but is not the source itself -- toolchain, host target, profile,
    // source commit. With the dependency vectors pinned above, this completes the
    // input set, so the binaryCid is reproducible under the NAMED conditions
    // (recomputable, not sworn). Testimony, not a gate: attest records the
    // conditions; verify-only reads them back (a different builder's env is fine,
    // the receipt states what THIS binaryCid reproduces under). Every field is
    // rederivable -- no unsigned clock baked in.
    let build_inputs_path = receipts.join("build-inputs.release.json");
    let build_inputs_json = if args.verify_only {
        match std::fs::read_to_string(&build_inputs_path) {
            Ok(t) => serde_json::from_str::<serde_json::Value>(&t)
                .ok()
                .and_then(|v| v.get("buildInputs").cloned())
                .unwrap_or(serde_json::Value::Null),
            Err(_) => serde_json::Value::Null,
        }
    } else {
        let inputs = gather_build_inputs(&root);
        let receipt = serde_json::json!({"kind": "BuildInputsReceipt", "buildInputs": inputs});
        if let Ok(s) = serde_json::to_string_pretty(&receipt) {
            let _ = std::fs::write(&build_inputs_path, s);
        }
        inputs
    };
    if !args.out_flags.json && !args.out_flags.quiet {
        if let Some(obj) = build_inputs_json.as_object() {
            let get = |k: &str| obj.get(k).and_then(|v| v.as_str()).unwrap_or("?");
            println!(
                "  {} build-inputs (rustc {}, {}, commit {})",
                "ok".green(),
                get("rustcVersion"),
                get("hostTarget"),
                &get("gitCommit").chars().take(12).collect::<String>(),
            );
        }
    }

    if args.out_flags.json {
        println!(
            "{}",
            serde_json::json!({
                "ok": all_ok,
                "mode": if args.verify_only { "verify" } else { "attest" },
                "artifacts": results,
                "coverage": coverage_json,
                "dependencies": dependencies_json,
                "buildInputs": build_inputs_json,
            })
        );
    } else if all_ok && !args.out_flags.quiet {
        let verb = if args.verify_only {
            "verified"
        } else {
            "attested + verified"
        };
        println!(
            "{}: {} artifact(s) {verb}",
            "package release".green().bold(),
            manifest.artifact.len()
        );
    }

    if all_ok {
        EXIT_OK
    } else {
        EXIT_VERIFY_FAIL
    }
}

/// Attest (or verify-only) one manifest artifact. Returns its binaryCid on
/// success. Attest mode also verifies the receipt it just wrote by re-reading
/// the bytes, so a `release` run proves the produce->consume round-trip.
fn release_one(
    name: &str,
    version: &str,
    artifact_path: &Path,
    receipt_path: &Path,
    verify_only: bool,
) -> Result<String, String> {
    let bytes = std::fs::read(artifact_path)
        .map_err(|e| format!("read artifact {}: {e}", artifact_path.display()))?;
    let observed = blake3_512_of(&bytes);

    if verify_only {
        let receipt_text = std::fs::read_to_string(receipt_path)
            .map_err(|e| format!("read receipt {}: {e}", receipt_path.display()))?;
        let receipt: serde_json::Value = serde_json::from_str(&receipt_text)
            .map_err(|e| format!("parse receipt {}: {e}", receipt_path.display()))?;
        let pinned = receipt
            .get("binaryCid")
            .and_then(|v| v.as_str())
            .ok_or_else(|| format!("receipt {} missing binaryCid", receipt_path.display()))?;
        if pinned != observed {
            return Err(format!(
                "binaryCid mismatch (pinned {}, observed {})",
                &pinned[..pinned.len().min(23)],
                &observed[..observed.len().min(23)]
            ));
        }
        return Ok(observed);
    }

    let receipt = release_receipt(name, version, &observed, bytes.len());
    std::fs::write(
        receipt_path,
        serde_json::to_string_pretty(&receipt).expect("serialize release receipt"),
    )
    .map_err(|e| format!("write receipt {}: {e}", receipt_path.display()))?;
    // Round-trip: re-read the bytes and confirm the gate would accept.
    let reread = std::fs::read(artifact_path)
        .map_err(|e| format!("re-read artifact {}: {e}", artifact_path.display()))?;
    if blake3_512_of(&reread) != observed {
        return Err("artifact changed during attestation".to_string());
    }
    Ok(observed)
}

/// `sugar package attest`: arm the coarse supply-chain pin. Reads the
/// shippable artifact, content-addresses its bytes, and writes a JSON
/// PackageReleaseReceipt whose top-level `binaryCid` the admission gate
/// (`sugar verify --artifact --proof`) checks. This is the production producer
/// of binaryCid-bearing receipts -- without it the artifact rail is sound but
/// unarmed (no receipt pins a binary), so contract-free byte changes pass
/// unnoticed. The receipt is the JSON shape the gate already consumes
/// (`run_admission_gate_with` reads `proof["binaryCid"]`), not the CBOR
/// `.proof` envelope.
fn run_attest(args: PackageAttestArgs) -> u8 {
    let bytes = match std::fs::read(&args.artifact) {
        Ok(b) => b,
        Err(e) => {
            eprintln!(
                "{}: read artifact {}: {e}",
                "error".red().bold(),
                args.artifact.display()
            );
            return EXIT_USER_ERROR;
        }
    };
    let binary_cid = blake3_512_of(&bytes);

    let receipt = release_receipt(&args.name, &args.version, &binary_cid, bytes.len());

    if let Some(parent) = args.out.parent() {
        if let Err(e) = std::fs::create_dir_all(parent) {
            eprintln!("{}: mkdir {}: {e}", "error".red().bold(), parent.display());
            return EXIT_USER_ERROR;
        }
    }
    if let Err(e) = std::fs::write(
        &args.out,
        serde_json::to_string_pretty(&receipt).expect("serialize release receipt"),
    ) {
        eprintln!(
            "{}: write {}: {e}",
            "error".red().bold(),
            args.out.display()
        );
        return EXIT_USER_ERROR;
    }

    if args.out_flags.json {
        println!(
            "{}",
            serde_json::json!({
                "ok": true,
                "binaryCid": binary_cid,
                "receipt": args.out,
            })
        );
    } else if !args.out_flags.quiet {
        println!("{}", "package attest".green().bold());
        println!("  binaryCid : {binary_cid}");
        println!("  receipt   : {}", args.out.display());
    }
    EXIT_OK
}

fn run_inspect(args: PackageInspectArgs) -> u8 {
    if !args.project.exists() {
        eprintln!(
            "{}: package project not found: {}",
            "error".red().bold(),
            args.project.display()
        );
        return EXIT_USER_ERROR;
    }

    let project_cfg = read_project_config(&args.project);
    let user_cfg = read_user_config();
    let surface = match project_cfg
        .surface_for("lift")
        .or_else(|| user_cfg.surface_for("lift"))
    {
        Some(surface) => surface,
        None => {
            eprintln!(
                "{}: no package inspection lifter configured. Set [authoring] surface or [authoring.lift] surface in .sugar/config.toml.",
                "error".red().bold()
            );
            return EXIT_USER_ERROR;
        }
    };

    match lift_plugin::dispatch_lift(
        &args.project,
        &surface,
        LiftPluginOptions {
            identify_only: true,
            library_bindings: false,
            ..Default::default()
        },
        args.out.quiet,
    ) {
        Ok(session) => {
            let projection = session.response_projection();
            let response = match projection.response_value() {
                Ok(response) => response,
                Err(error) => {
                    eprintln!("{}: {error}", "error".red().bold());
                    return EXIT_VERIFY_FAIL;
                }
            };
            let kind = response
                .get("kind")
                .and_then(|value| value.as_str())
                .unwrap_or("unknown");
            if kind != "package-inspection-document" {
                eprintln!(
                    "{}: package inspect returned `{kind}`; expected `package-inspection-document` from identify-only lifter",
                    "error".red().bold()
                );
                return EXIT_VERIFY_FAIL;
            }
            if args.out.json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(response).expect("serialize package inspection")
                );
            } else if !args.out.quiet {
                print_package_summary(response);
            }
            EXIT_OK
        }
        Err(LiftPluginError::MissingBinary { binary }) => {
            eprintln!(
                "{}: package inspection lifter binary `{binary}` not found",
                "error".red().bold()
            );
            EXIT_USER_ERROR
        }
        Err(LiftPluginError::Refused(refusal)) => {
            eprintln!(
                "{}: {}: {}",
                "error".red().bold(),
                refusal.header.failure_kind,
                refusal.header.failure_detail
            );
            EXIT_VERIFY_FAIL
        }
        Err(LiftPluginError::FatalFactoryPanic(error)) => {
            eprintln!("{}: {error}", "error".red().bold());
            EXIT_VERIFY_FAIL
        }
        Err(LiftPluginError::Diagnostic(error)) => {
            eprintln!("{}: {error}", "error".red().bold());
            EXIT_VERIFY_FAIL
        }
    }
}

fn print_package_summary(report: &serde_json::Value) {
    println!("{}", "package inspect".green().bold());
    println!(
        "  ecosystem : {}",
        report
            .get("ecosystem")
            .and_then(|value| value.as_str())
            .unwrap_or("unknown")
    );
    println!(
        "  name      : {}",
        report
            .pointer("/package/name")
            .and_then(|value| value.as_str())
            .unwrap_or("unknown")
    );
    println!(
        "  version   : {}",
        report
            .pointer("/package/version")
            .and_then(|value| value.as_str())
            .unwrap_or("unknown")
    );
    println!(
        "  binaryCid : {}",
        report
            .pointer("/artifact/binaryCid")
            .and_then(|value| value.as_str())
            .unwrap_or("unknown")
    );
}

#[cfg(test)]
mod tests {
    use super::{coverage_gaps, dependency_vectors_cid_of_text};

    fn v(xs: &[&str]) -> Vec<String> {
        xs.iter().map(|s| s.to_string()).collect()
    }

    const LOCK_A: &str = r#"
version = 4
[[package]]
name = "anyhow"
version = "1.0.86"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaa"
[[package]]
name = "serde"
version = "1.0.203"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbb"
[[package]]
name = "sugar-cli"
version = "0.1.0"
"#;

    #[test]
    fn dep_vectors_cid_is_deterministic_and_order_independent() {
        // Same packages, different source order -> same CID (sorted canonical).
        let reordered = r#"
version = 4
[[package]]
name = "serde"
version = "1.0.203"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbb"
[[package]]
name = "sugar-cli"
version = "0.1.0"
[[package]]
name = "anyhow"
version = "1.0.86"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaa"
"#;
        let (cid_a, n_a) = dependency_vectors_cid_of_text(LOCK_A).expect("parse");
        let (cid_b, n_b) = dependency_vectors_cid_of_text(reordered).expect("parse");
        assert_eq!(n_a, 3);
        assert_eq!(n_b, 3);
        assert_eq!(cid_a, cid_b, "package order must not change the CID");
        assert!(cid_a.starts_with("blake3-512:"));
    }

    #[test]
    fn a_changed_dependency_moves_the_cid_conjunctive() {
        // The whole point: bump ONE dep's version/checksum -> the CID moves (N-1
        // of N pinned is zero; a single quiet dep change cannot pass).
        let bumped = LOCK_A.replace("1.0.86", "1.0.99");
        let (cid_a, _) = dependency_vectors_cid_of_text(LOCK_A).expect("parse");
        let (cid_b, _) = dependency_vectors_cid_of_text(&bumped).expect("parse");
        assert_ne!(
            cid_a, cid_b,
            "a version bump must move the dependency-vectors CID"
        );

        // Removing a dep also moves it (the closure is not the same set).
        let removed = r#"
version = 4
[[package]]
name = "serde"
version = "1.0.203"
checksum = "bbbb"
"#;
        let (cid_c, n_c) = dependency_vectors_cid_of_text(removed).expect("parse");
        assert_ne!(cid_a, cid_c, "removing a dep must move the CID");
        assert_eq!(n_c, 1);
    }

    #[test]
    fn lockfile_without_packages_is_a_named_error() {
        let err = dependency_vectors_cid_of_text("version = 4\n").unwrap_err();
        assert!(err.contains("no [[package]] entries"), "{err}");
    }

    #[test]
    fn rustc_field_parse_reads_release_and_host() {
        let vv = "rustc 1.96.0 (abc 2026-01-01)\n\
                  binary: rustc\n\
                  commit-hash: abc\n\
                  host: x86_64-apple-darwin\n\
                  release: 1.96.0\n\
                  LLVM version: 19.1.0\n";
        assert_eq!(
            super::parse_rustc_field(vv, "release: ").as_deref(),
            Some("1.96.0")
        );
        assert_eq!(
            super::parse_rustc_field(vv, "host: ").as_deref(),
            Some("x86_64-apple-darwin")
        );
        // A field the output does not carry is None (-> the caller names it
        // "unavailable", never silently present).
        assert_eq!(super::parse_rustc_field(vv, "nonesuch: "), None);
    }

    #[test]
    fn coverage_complete_when_every_bin_is_pinned_or_excluded() {
        let bins = v(&["sugar", "sugar-lift", "coretests_sweep", "witness_rpc"]);
        let pinned = v(&["sugar", "sugar-lift"]);
        let excluded = v(&["coretests_sweep", "witness_rpc"]);
        assert!(coverage_gaps(&bins, &pinned, &excluded).is_empty());
    }

    #[test]
    fn a_new_bin_neither_pinned_nor_excluded_is_a_gap() {
        // The whole point: add a shippable bin, forget the manifest -> FAIL.
        let bins = v(&["sugar", "sugar-lift", "sugar-newcli"]);
        let pinned = v(&["sugar", "sugar-lift"]);
        let excluded = v(&[]);
        assert_eq!(
            coverage_gaps(&bins, &pinned, &excluded),
            v(&["sugar-newcli"])
        );
    }

    #[test]
    fn gaps_are_sorted_and_deduped() {
        let bins = v(&["z-bin", "a-bin", "z-bin"]);
        assert_eq!(coverage_gaps(&bins, &[], &[]), v(&["a-bin", "z-bin"]));
    }

    #[test]
    fn extra_pins_or_excludes_not_in_workspace_do_not_create_gaps() {
        // A pinned/excluded name that no longer exists as a bin is harmless;
        // only UNACCOUNTED workspace bins are gaps.
        let bins = v(&["sugar"]);
        let pinned = v(&["sugar", "ghost-removed-bin"]);
        assert!(coverage_gaps(&bins, &pinned, &[]).is_empty());
    }
}
