// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use clap::Parser;
use serde::Serialize;
use serde_json::Value;
use sugar_canonicalizer::blake3_512_of;
use sugar_claim_envelope::{
    body_discharge_policy_from_object_with_default, BodyDischargePolicyWarning,
};
use sugar_proof_envelope::proof_filename;
use sugar_verifier::load_all_proofs::{self, ProofBytes};
use sugar_verifier::types::{EffectSiteAnnotation, LoadError, MementoPool};
use tracing::{error, info, warn};

use crate::floor_runtime_check::{
    algebra_gaps_by_boundary_from_reasons, floor_runtime_check, FloorCheckMode, FloorCheckStatus,
    FloorRuntimeCheck, FloorSignals,
};
use crate::panic_annotations_runtime::{
    annotation_runtime_check_with_mementos, AnnotationCheckMode, PanicCensusRow,
};

#[derive(Parser, Debug, Clone)]
pub struct SelfCheckArgs {
    /// Target crate directory. Defaults to implementations/rust/sugar-cli.
    #[arg(long)]
    pub target: Option<PathBuf>,
    /// Emit stable machine-readable JSON.
    #[arg(long)]
    pub json: bool,
    /// Opt in to the rust-analyzer oracle for target minting.
    #[arg(long)]
    pub oracle: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct LiftScoreboard {
    fn_contracts: usize,
    body_discharge_eligible: usize,
    body_discharge_ineligible: BTreeMap<String, usize>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BridgeScoreboard {
    emitted: usize,
    lift_gaps: BTreeMap<String, usize>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct OracleScoreboard {
    requested: bool,
    engaged: bool,
    attempted: u64,
    resolved: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DischargeSplit {
    panic_safe: usize,
    reflexive: usize,
    vacuous: usize,
    undecidable: usize,
    false_pass: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Site {
    file: String,
    line: usize,
    callee: String,
    reason: String,
}

fn log_body_discharge_policy_warnings(
    context: &str,
    contract: &str,
    warnings: &[BodyDischargePolicyWarning],
) {
    for warning in warnings {
        match warning {
            BodyDischargePolicyWarning::Disagreement {
                legacy_eligible,
                legacy_reason,
                policy_eligible,
                policy_reason,
            } => warn!(
                context = %context,
                contract = %contract,
                legacy_eligible = *legacy_eligible,
                legacy_reason = ?legacy_reason,
                policy_eligible = *policy_eligible,
                policy_reason = ?policy_reason,
                "body-discharge-disagreement: dischargePolicy/bodyDischarge* disagree; using legacy bodyDischarge*"
            ),
            BodyDischargePolicyWarning::Malformed { reason } => warn!(
                context = %context,
                contract = %contract,
                reason = %reason,
                "body-discharge-malformed: ignoring malformed dischargePolicy"
            ),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct PanicCensusEntry {
    file: String,
    line: usize,
    callee: String,
    #[serde(skip)]
    callsite_bundle_cid: Option<String>,
    status: String,
    reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    category: Option<String>,
    #[serde(rename = "tierToClose", skip_serializing_if = "Option::is_none")]
    tier_to_close: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SelfCheckScoreboard {
    target: String,
    #[serde(rename = "catalogCid")]
    catalog_cid: String,
    lift: LiftScoreboard,
    bridges: BridgeScoreboard,
    oracle: OracleScoreboard,
    silently_dropped: usize,
    dropped_sites: Vec<Site>,
    #[serde(rename = "totalCallsites")]
    total_callsites: u64,
    discharge_split: DischargeSplit,
    panic_census: Vec<PanicCensusEntry>,
}

struct MintOutput {
    proof_file: PathBuf,
    json: Value,
}

#[derive(Debug, Default)]
struct StagedDependencyImportsGuard {
    staged_files: Vec<PathBuf>,
}

#[derive(Debug, Clone)]
struct PanicSiteAnnotation {
    file: String,
    line: usize,
    callee: String,
    status: String,
    category: String,
    tier_to_close: String,
    reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ImportsProofSetSnapshot {
    entries: BTreeSet<String>,
    directory_present: bool,
}

pub fn run(args: SelfCheckArgs) -> u8 {
    match run_inner(&args) {
        Ok(scoreboard) => {
            emit_scoreboard(&scoreboard, args.json);
            let mut failed = false;
            if scoreboard.silently_dropped > 0 {
                failed = true;
                eprintln!(
                    "SELF-CHECK INVARIANT VIOLATION: silentlyDropped={} but it must be 0",
                    scoreboard.silently_dropped
                );
                for site in &scoreboard.dropped_sites {
                    eprintln!(
                        "  dropped: {}:{} {}, reason: {}",
                        site.file, site.line, site.callee, site.reason
                    );
                }
            }
            if scoreboard.discharge_split.false_pass > 0 {
                failed = true;
                eprintln!(
                    "SELF-CHECK INVARIANT VIOLATION: falsePass={} but it must be 0",
                    scoreboard.discharge_split.false_pass
                );
                for site in scoreboard
                    .panic_census
                    .iter()
                    .filter(|site| site.reason.contains("false pass"))
                {
                    eprintln!(
                        "  false pass: {}:{} {}, reason: {}",
                        site.file, site.line, site.callee, site.reason
                    );
                }
            }
            if scoreboard.oracle.requested
                && scoreboard.oracle.attempted > 0
                && !scoreboard.oracle.engaged
            {
                failed = true;
                eprintln!(
                    "self-check --oracle requested but the oracle resolved 0/{} receivers; the census is SYNTACTIC-ONLY (sugar-ra-oracle unreachable or rust-analyzer not ready). Set SUGAR_RA_ORACLE_BIN and run doctor.",
                    scoreboard.oracle.attempted
                );
            }
            if failed {
                crate::EXIT_VERIFY_FAIL
            } else {
                crate::EXIT_OK
            }
        }
        Err(error) => {
            eprintln!("self-check failed: {error}");
            crate::EXIT_VERIFY_FAIL
        }
    }
}

fn run_inner(args: &SelfCheckArgs) -> Result<SelfCheckScoreboard, String> {
    let repo_root = discover_repo_root()?;
    let target_abs = resolve_target(&repo_root, args.target.as_ref())?;
    let target_rel = repo_relative(&repo_root, &target_abs);
    let bin = std::env::current_exe().map_err(|e| format!("resolve current executable: {e}"))?;
    let scratch = std::env::temp_dir()
        .join("sugar-self-check")
        .join(sanitize_path_component(&target_rel));
    recreate_dir(&scratch)?;

    let imports = target_abs.join(".sugar").join("imports");
    recreate_imports(&imports)?;

    let libsugar = repo_root.join("implementations/rust/libsugar");
    let dependency_specs = [("libsugar", libsugar.as_path())];
    let mut dependency_proofs = BTreeMap::new();
    for (name, dep) in dependency_specs {
        if same_path(dep, &target_abs) {
            continue;
        }
        let dep_rel = repo_relative(&repo_root, dep);
        let staged_imports = stage_dependency_imports_for_mint(
            name,
            dep,
            dependency_import_requirements(name),
            &dependency_proofs,
        )?;
        info!(
            dependency = name,
            project = %dep_rel,
            "self-check: minting dependency proof"
        );
        let out_dir = scratch.join(format!("dep-{name}"));
        let minted = mint_project(
            &bin,
            &repo_root,
            dep,
            &out_dir,
            dependency_mint_uses_oracle(args.oracle),
        )?;
        drop(staged_imports);
        copy_proof_to_imports(&minted.proof_file, &imports)?;
        dependency_proofs.insert(name.to_string(), minted.proof_file.clone());
        let imports_proof_count = count_proof_files(&imports)?;
        info!(
            dependency = name,
            proof_file = %minted.proof_file.display(),
            imports_proof_count,
            "self-check: dependency proof ready"
        );
    }
    let rpc_dependency_proof_count = stage_rpc_dependency_proofs_to_imports(
        &target_abs,
        &imports,
        crate::kit_dispatch::dependency_proofs_via_rpc,
    )?;
    info!(
        rpc_dependency_proof_count,
        imports = %imports.display(),
        "self-check: RPC dependency proofs staged"
    );
    let imports_snapshot = snapshot_imports_proof_set(&imports)?;
    info!(
        imports = %imports.display(),
        imports_proof_count = imports_snapshot.len(),
        imports_proofs = %imports_snapshot.path_list(),
        "self-check: imports proof set snapshotted"
    );

    let target_out = scratch.join("target");
    info!(
        target = %target_rel,
        oracle = args.oracle,
        "self-check: minting target"
    );
    let target_mint = mint_project(&bin, &repo_root, &target_abs, &target_out, args.oracle)?;
    let target_proof_count = count_proof_files(&target_out)?;
    let imports_proof_count = count_proof_files(&imports)?;
    info!(
        target_proof_count,
        imports_proof_count,
        with_dir = %target_out.display(),
        imports = %imports.display(),
        "self-check: target proof ready; starting prove"
    );
    assert_imports_proof_set_unchanged(&imports, &imports_snapshot, "target mint")?;
    let prove_result = prove_project(&bin, &repo_root, &target_abs, &target_out);
    let imports_result = assert_imports_proof_set_unchanged(&imports, &imports_snapshot, "prove");
    let prove_json = match (prove_result, imports_result) {
        (Ok(json), Ok(())) => json,
        (Ok(_), Err(imports_error)) => return Err(imports_error),
        (Err(prove_error), Ok(())) => return Err(prove_error),
        (Err(prove_error), Err(imports_error)) => {
            return Err(format!("{imports_error}; prove also failed: {prove_error}"));
        }
    };
    info!("self-check: prove complete; building scoreboard");

    let annotation_mementos = load_effect_site_annotation_mementos(&target_abs, &target_out)?;
    let scoreboard = build_scoreboard_with_runtime_annotations_and_mementos(
        &target_rel,
        &target_abs,
        &target_mint.json,
        &prove_json,
        &annotation_mementos,
        AnnotationCheckMode::Strict,
    )?;
    enforce_floor_runtime_checks(&scoreboard, &prove_json)?;
    info!(
        oracle_requested = scoreboard.oracle.requested,
        oracle_engaged = scoreboard.oracle.engaged,
        oracle_attempted = scoreboard.oracle.attempted,
        oracle_resolved = scoreboard.oracle.resolved,
        silently_dropped = scoreboard.silently_dropped,
        dropped_sites = scoreboard.dropped_sites.len(),
        total_callsites = scoreboard.total_callsites,
        panic_census = scoreboard.panic_census.len(),
        panic_safe = scoreboard.discharge_split.panic_safe,
        false_pass = scoreboard.discharge_split.false_pass,
        reflexive = scoreboard.discharge_split.reflexive,
        vacuous = scoreboard.discharge_split.vacuous,
        undecidable = scoreboard.discharge_split.undecidable,
        "self-check: scoreboard built"
    );
    Ok(scoreboard)
}

fn floor_signals_from_scoreboard(
    scoreboard: &SelfCheckScoreboard,
    prove_json: &Value,
) -> FloorSignals {
    FloorSignals {
        silently_dropped: scoreboard.silently_dropped as u64,
        false_pass: scoreboard.discharge_split.false_pass as u64,
        dropped_sites_count: scoreboard.dropped_sites.len(),
        panic_census_unnamed_count: scoreboard
            .panic_census
            .iter()
            .filter(|row| {
                row.status != "proven" && row.category.is_none() && row.tier_to_close.is_none()
            })
            .count(),
        total_callsites: scoreboard.total_callsites,
        discharge_split_present: prove_json
            .get("dischargeSplit")
            .map_or(false, |value| !value.is_null()),
        monoid_fold_gaps_by_element_type: monoid_fold_gaps_by_element_type_from_entries(
            &scoreboard.panic_census,
        ),
        algebra_gaps_by_boundary: algebra_gaps_by_boundary_from_reasons(
            scoreboard
                .panic_census
                .iter()
                .map(|entry| entry.reason.as_str()),
        ),
    }
}

fn enforce_floor_runtime_checks(
    scoreboard: &SelfCheckScoreboard,
    prove_json: &Value,
) -> Result<(), String> {
    let checks = floor_runtime_check(
        floor_signals_from_scoreboard(scoreboard, prove_json),
        FloorCheckMode::Strict,
    );
    log_floor_runtime_checks(&checks);
    let failures = checks
        .iter()
        .filter(|check| check.status == FloorCheckStatus::Fail)
        .map(|check| format!("{}: {}", check.id, check.detail))
        .collect::<Vec<_>>();
    if failures.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "floor runtime check failed: {}",
            failures.join("; ")
        ))
    }
}

fn log_floor_runtime_checks(checks: &[FloorRuntimeCheck]) {
    for check in checks {
        info!(
            check_id = %check.id,
            check_name = %check.name,
            check_domain = %check.domain,
            check_status = ?check.status,
            check_severity = ?check.severity,
            check_detail = %check.detail,
            "self-check: floor runtime check complete"
        );
    }
}

fn discover_repo_root() -> Result<PathBuf, String> {
    let cwd = std::env::current_dir().map_err(|e| format!("read current directory: {e}"))?;
    for candidate in cwd.ancestors() {
        if candidate.join("implementations/rust/Cargo.toml").is_file()
            && candidate
                .join("docs/self-application/GOAL-sugar-proves-sugar.md")
                .is_file()
        {
            return candidate
                .canonicalize()
                .map_err(|e| format!("canonicalize repo root {}: {e}", candidate.display()));
        }
    }
    Err("could not locate sugar repo root from current directory".to_string())
}

fn resolve_target(repo_root: &Path, target: Option<&PathBuf>) -> Result<PathBuf, String> {
    let target = target
        .cloned()
        .unwrap_or_else(|| PathBuf::from("implementations/rust/sugar-cli"));
    let abs = if target.is_absolute() {
        target
    } else {
        repo_root.join(target)
    };
    if !abs.exists() {
        return Err(format!("target does not exist: {}", abs.display()));
    }
    if !abs.join(".sugar/config.toml").is_file() {
        return Err(format!(
            "target is not a sugar kit, missing {}",
            abs.join(".sugar/config.toml").display()
        ));
    }
    abs.canonicalize()
        .map_err(|e| format!("canonicalize target {}: {e}", abs.display()))
}

fn recreate_dir(path: &Path) -> Result<(), String> {
    if path.exists() {
        fs::remove_dir_all(path).map_err(|e| format!("remove {}: {e}", path.display()))?;
    }
    fs::create_dir_all(path).map_err(|e| format!("mkdir {}: {e}", path.display()))
}

fn recreate_imports(path: &Path) -> Result<(), String> {
    fs::create_dir_all(path).map_err(|e| format!("mkdir {}: {e}", path.display()))?;
    for entry in fs::read_dir(path).map_err(|e| format!("read {}: {e}", path.display()))? {
        let entry = entry.map_err(|e| format!("read {} entry: {e}", path.display()))?;
        if entry.path().extension() == Some(OsStr::new("proof")) {
            fs::remove_file(entry.path())
                .map_err(|e| format!("remove {}: {e}", entry.path().display()))?;
        }
    }
    Ok(())
}

fn count_proof_files(path: &Path) -> Result<usize, String> {
    if !path.exists() {
        return Ok(0);
    }
    let mut count = 0usize;
    for entry in fs::read_dir(path).map_err(|e| format!("read {}: {e}", path.display()))? {
        let entry = entry.map_err(|e| format!("read {} entry: {e}", path.display()))?;
        if entry.path().extension() == Some(OsStr::new("proof")) {
            count += 1;
        }
    }
    Ok(count)
}

fn proof_files_in(path: &Path) -> Result<Vec<PathBuf>, String> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let mut files = Vec::new();
    for entry in fs::read_dir(path).map_err(|e| format!("read {}: {e}", path.display()))? {
        let entry = entry.map_err(|e| format!("read {} entry: {e}", path.display()))?;
        let path = entry.path();
        if path.extension() == Some(OsStr::new("proof")) {
            files.push(path);
        }
    }
    files.sort();
    Ok(files)
}

fn load_effect_site_annotation_mementos(
    target_abs: &Path,
    target_out: &Path,
) -> Result<Vec<EffectSiteAnnotation>, String> {
    let target_proofs = proof_files_in(target_out)?;
    let pool = load_all_proofs::run_with_files(target_abs, &target_proofs);
    effect_site_annotations_from_pool(pool)
}

fn effect_site_annotations_from_pool(
    pool: MementoPool,
) -> Result<Vec<EffectSiteAnnotation>, String> {
    let annotation_errors = pool
        .load_errors
        .iter()
        .filter(|error| is_effect_site_annotation_load_error(error))
        .map(|error| format!("{}: {}", error.proof_path, error.reason))
        .collect::<Vec<_>>();
    if !annotation_errors.is_empty() {
        let errors = annotation_errors.join("; ");
        return Err(format!(
            "effect-site annotation proof load failed: {errors}"
        ));
    }
    Ok(pool
        .panic_effect_site_annotations
        .values()
        .cloned()
        .collect())
}

fn is_effect_site_annotation_load_error(error: &LoadError) -> bool {
    error.reason.starts_with("[effect-site-annotation]")
        || error
            .reason
            .starts_with("[effect-site-annotation-duplicate]")
}

impl ImportsProofSetSnapshot {
    fn len(&self) -> usize {
        self.entries.len()
    }

    fn path_list(&self) -> String {
        format_imports_path_list(self.entries.iter())
    }
}

fn snapshot_imports_proof_set(path: &Path) -> Result<ImportsProofSetSnapshot, String> {
    if !path.exists() {
        return Ok(ImportsProofSetSnapshot {
            entries: BTreeSet::new(),
            directory_present: false,
        });
    }
    let mut entries = BTreeSet::new();
    for entry in fs::read_dir(path).map_err(|e| format!("read {}: {e}", path.display()))? {
        let entry = entry.map_err(|e| format!("read {} entry: {e}", path.display()))?;
        if entry.path().extension() == Some(OsStr::new("proof")) {
            let file_name = entry.file_name().into_string().map_err(|name| {
                format!("non-utf8 proof filename in {}: {name:?}", path.display())
            })?;
            entries.insert(file_name);
        }
    }
    Ok(ImportsProofSetSnapshot {
        entries,
        directory_present: true,
    })
}

fn assert_imports_proof_set_unchanged(
    imports: &Path,
    before: &ImportsProofSetSnapshot,
    phase: &str,
) -> Result<(), String> {
    let after = snapshot_imports_proof_set(imports)?;
    if &after == before {
        info!(
            imports = %imports.display(),
            phase,
            imports_proof_count = before.len(),
            imports_proofs = %before.path_list(),
            "self-check: imports proof set unchanged"
        );
        return Ok(());
    }

    let added = after
        .entries
        .difference(&before.entries)
        .cloned()
        .collect::<Vec<_>>();
    let removed = before
        .entries
        .difference(&after.entries)
        .cloned()
        .collect::<Vec<_>>();
    let message = format!(
        "self-check refused: {} mutated during {phase}; before ({}) proof files: [{}]; after ({}) proof files: [{}]; added: [{}]; removed: [{}]{}",
        imports.display(),
        before.len(),
        before.path_list(),
        after.len(),
        after.path_list(),
        format_imports_path_list(added.iter()),
        format_imports_path_list(removed.iter()),
        imports_directory_status_note(before, &after)
    );
    error!(
        imports = %imports.display(),
        phase,
        before_count = before.len(),
        after_count = after.len(),
        before = %before.path_list(),
        after = %after.path_list(),
        added = %format_imports_path_list(added.iter()),
        removed = %format_imports_path_list(removed.iter()),
        before_directory_present = before.directory_present,
        after_directory_present = after.directory_present,
        "self-check: imports proof set mutated during measurement"
    );
    Err(message)
}

fn format_imports_path_list<'a>(items: impl Iterator<Item = &'a String>) -> String {
    items.cloned().collect::<Vec<_>>().join(", ")
}

fn imports_directory_status_note(
    before: &ImportsProofSetSnapshot,
    after: &ImportsProofSetSnapshot,
) -> &'static str {
    match (before.directory_present, after.directory_present) {
        (true, false) => "; imports directory disappeared",
        (false, true) => "; imports directory appeared",
        _ => "",
    }
}

fn mint_project(
    bin: &Path,
    repo_root: &Path,
    project: &Path,
    out_dir: &Path,
    oracle: bool,
) -> Result<MintOutput, String> {
    fs::create_dir_all(out_dir).map_err(|e| format!("mkdir {}: {e}", out_dir.display()))?;
    let mut cmd = Command::new(bin);
    cmd.current_dir(repo_root)
        .arg("mint")
        .arg("--project")
        .arg(project)
        .arg("--out")
        .arg(out_dir)
        .arg("--json")
        .arg("--quiet")
        .env("RUST_LOG", "info,sugar_walk_rpc=info");
    if oracle {
        cmd.env("SUGAR_RESOLVE_ORACLE", "rust-analyzer");
    } else {
        cmd.env_remove("SUGAR_RESOLVE_ORACLE");
    }
    let output = cmd
        .stdout(Stdio::piped())
        .stderr(child_stderr()?)
        .output()
        .map_err(|e| format!("run mint for {}: {e}", project.display()))?;
    if !output.status.success() {
        return Err(command_failure("mint", project, &output));
    }
    let json = parse_json_stdout("mint", project, &output)?;
    let proof_file = json
        .get("proofFile")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| format!("mint for {} did not report proofFile", project.display()))?;
    if !proof_file.is_file() {
        return Err(format!(
            "mint for {} reported missing proofFile {}",
            project.display(),
            proof_file.display()
        ));
    }
    Ok(MintOutput { proof_file, json })
}

fn dependency_mint_uses_oracle(self_check_oracle: bool) -> bool {
    self_check_oracle
}

fn prove_project(
    bin: &Path,
    repo_root: &Path,
    target: &Path,
    with_dir: &Path,
) -> Result<Value, String> {
    let output = Command::new(bin)
        .current_dir(repo_root)
        .arg("prove")
        .arg(target)
        .arg("--with")
        .arg(with_dir)
        .arg("--json")
        .stdout(Stdio::piped())
        .stderr(child_stderr()?)
        .output()
        .map_err(|e| format!("run prove for {}: {e}", target.display()))?;
    let json = parse_json_stdout("prove", target, &output)?;
    let rows = json
        .get("rows")
        .and_then(|v| v.as_array())
        .map_or(0, Vec::len);
    let total_callsites = json
        .get("totalCallsites")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let split = json.get("dischargeSplit");
    info!(
        total_callsites,
        rows,
        panic_safe = split.map_or(0, |v| usize_field(v, "panicSafe")),
        false_pass = split.map_or(0, |v| usize_field(v, "falsePass")),
        reflexive = split.map_or(0, |v| usize_field(v, "reflexive")),
        vacuous = split.map_or(0, |v| usize_field(v, "vacuous")),
        undecidable = split.map_or(0, |v| usize_field(v, "undecidable")),
        "self-check: prove JSON parsed"
    );
    let total = json
        .get("totalCallsites")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    if total == 0 {
        return Err(format!(
            "prove for {} reported zero callsites, refusing a vacuous self-check",
            target.display()
        ));
    }
    Ok(json)
}

fn child_stderr() -> Result<Stdio, String> {
    let Ok(path) = std::env::var("SUGAR_LOG_FILE") else {
        return Ok(Stdio::inherit());
    };
    let file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| format!("open SUGAR_LOG_FILE {path} for child stderr: {e}"))?;
    Ok(Stdio::from(file))
}

fn copy_proof_to_imports(proof_file: &Path, imports: &Path) -> Result<(), String> {
    let file_name = proof_file
        .file_name()
        .ok_or_else(|| format!("proof path has no file name: {}", proof_file.display()))?;
    let dest = imports.join(file_name);
    fs::copy(proof_file, &dest).map_err(|e| {
        format!(
            "copy dependency proof {} to {}: {e}",
            proof_file.display(),
            dest.display()
        )
    })?;
    Ok(())
}

fn dependency_import_requirements(_dependency_name: &str) -> &'static [&'static str] {
    // The rust-std shim (Product-B synthesized std panic-freedom contracts) was
    // the only cross-dependency import requirement; it is deleted. Self-check now
    // mints each dependency without staging a std-shim proof.
    &[]
}

fn stage_dependency_imports_for_mint(
    dependency_name: &str,
    dependency_root: &Path,
    required_dependencies: &[&str],
    dependency_proofs: &BTreeMap<String, PathBuf>,
) -> Result<StagedDependencyImportsGuard, String> {
    let imports = dependency_root.join(".sugar").join("imports");
    let mut guard = StagedDependencyImportsGuard::default();
    for required_name in required_dependencies {
        let proof_file = dependency_proofs.get(*required_name).ok_or_else(|| {
            format!(
                "self-check dependency `{dependency_name}` requires `{required_name}` proof before minting; dependency order is incomplete"
            )
        })?;
        guard.stage_proof(&imports, proof_file, dependency_name, required_name)?;
    }
    Ok(guard)
}

impl StagedDependencyImportsGuard {
    fn stage_proof(
        &mut self,
        imports: &Path,
        proof_file: &Path,
        dependency_name: &str,
        required_name: &str,
    ) -> Result<(), String> {
        fs::create_dir_all(imports).map_err(|e| format!("mkdir {}: {e}", imports.display()))?;
        let file_name = proof_file
            .file_name()
            .ok_or_else(|| format!("proof path has no file name: {}", proof_file.display()))?;
        let dest = imports.join(file_name);
        if dest.exists() {
            let existing = fs::read(&dest).map_err(|e| format!("read {}: {e}", dest.display()))?;
            let incoming =
                fs::read(proof_file).map_err(|e| format!("read {}: {e}", proof_file.display()))?;
            if existing != incoming {
                return Err(format!(
                    "self-check refused to stage `{required_name}` proof for `{dependency_name}`: {} already exists with different bytes",
                    dest.display()
                ));
            }
            info!(
                dependency = dependency_name,
                required_dependency = required_name,
                proof_file = %proof_file.display(),
                imports = %imports.display(),
                "self-check: dependency import already staged"
            );
            return Ok(());
        }
        fs::copy(proof_file, &dest).map_err(|e| {
            format!(
                "stage dependency proof {} to {}: {e}",
                proof_file.display(),
                dest.display()
            )
        })?;
        self.staged_files.push(dest.clone());
        info!(
            dependency = dependency_name,
            required_dependency = required_name,
            proof_file = %proof_file.display(),
            staged_proof = %dest.display(),
            "self-check: staged dependency import for dependency mint"
        );
        Ok(())
    }
}

impl Drop for StagedDependencyImportsGuard {
    fn drop(&mut self) {
        for path in self.staged_files.iter().rev() {
            match fs::remove_file(path) {
                Ok(()) => {
                    info!(
                        staged_proof = %path.display(),
                        "self-check: removed staged dependency import"
                    );
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => {
                    warn!(
                        staged_proof = %path.display(),
                        %error,
                        "self-check: failed to remove staged dependency import"
                    );
                }
            }
        }
    }
}

fn stage_rpc_dependency_proofs_to_imports<F>(
    target_abs: &Path,
    imports: &Path,
    resolve: F,
) -> Result<usize, String>
where
    F: FnOnce(&Path) -> Result<Vec<ProofBytes>, String>,
{
    let proofs = resolve(target_abs)?;
    let mut count = 0usize;
    for proof in proofs {
        let derived_cid = blake3_512_of(&proof.bytes);
        if proof.expected_cid.as_ref() != derived_cid.as_str() {
            return Err(format!(
                "RPC dependency proof {} CID mismatch: expected {}, derived {}",
                proof.label, proof.expected_cid, derived_cid
            ));
        }
        let cid = proof.expected_cid;
        let dest = imports.join(proof_filename(&cid));
        fs::write(&dest, &proof.bytes).map_err(|e| {
            format!(
                "write RPC dependency proof {} to {}: {e}",
                proof.label,
                dest.display()
            )
        })?;
        count += 1;
    }
    Ok(count)
}

#[cfg(test)]
// DEPRECATED (#1783): legacy lift-diagnostic panic-site annotation join.
// Production self-check uses panic_annotations_runtime with target-local
// .sugar/residue.toml after prove produces panicCensus. Retain this
// test-only route until the old tests are migrated or deleted.
fn build_scoreboard(
    target_rel: &str,
    mint_json: &Value,
    prove_json: &Value,
) -> Result<SelfCheckScoreboard, String> {
    let catalog_cid = mint_json
        .get("filenameCid")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("target mint JSON missing filenameCid")?
        .to_string();
    let lift_json = mint_json
        .get("lift")
        .ok_or("target mint JSON missing lift result")?;
    let (lift, bridges, dropped_sites, unbridged_panic_sites) = lift_scoreboards(lift_json);
    let panic_annotations = panic_site_annotations(lift_json)?;
    let oracle = oracle_scoreboard(mint_json);
    let discharge_split = discharge_split(prove_json);
    let panic_census = panic_census(prove_json, unbridged_panic_sites, panic_annotations)?;
    let silently_dropped = dropped_sites.len();
    let total_callsites = total_callsites(prove_json);

    Ok(SelfCheckScoreboard {
        target: target_rel.to_string(),
        catalog_cid,
        lift,
        bridges,
        oracle,
        silently_dropped,
        dropped_sites,
        total_callsites,
        discharge_split,
        panic_census,
    })
}

#[cfg(test)]
fn build_scoreboard_with_runtime_annotations(
    target_rel: &str,
    target_path: &Path,
    mint_json: &Value,
    prove_json: &Value,
    doctor_mode: AnnotationCheckMode,
) -> Result<SelfCheckScoreboard, String> {
    build_scoreboard_with_runtime_annotations_and_mementos(
        target_rel,
        target_path,
        mint_json,
        prove_json,
        &[],
        doctor_mode,
    )
}

fn build_scoreboard_with_runtime_annotations_and_mementos(
    target_rel: &str,
    target_path: &Path,
    mint_json: &Value,
    prove_json: &Value,
    memento_annotations: &[EffectSiteAnnotation],
    doctor_mode: AnnotationCheckMode,
) -> Result<SelfCheckScoreboard, String> {
    let catalog_cid = mint_json
        .get("filenameCid")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("target mint JSON missing filenameCid")?
        .to_string();
    let lift_json = mint_json
        .get("lift")
        .ok_or("target mint JSON missing lift result")?;
    let (lift, bridges, dropped_sites, unbridged_panic_sites) = lift_scoreboards(lift_json);
    let oracle = oracle_scoreboard(mint_json);
    let discharge_split = discharge_split(prove_json);
    let raw_panic_census = panic_census(prove_json, unbridged_panic_sites, BTreeMap::new())?;
    let projected_rows: Vec<PanicCensusRow> = raw_panic_census
        .iter()
        .map(panic_census_row_from_entry)
        .collect();
    let annotation_outcome = annotation_runtime_check_with_mementos(
        target_path,
        &projected_rows,
        memento_annotations,
        doctor_mode,
    )
    .map_err(|error| {
        format!(
            "panic annotation runtime check failed: {}; evidence={}",
            error, error.check.evidence
        )
    })?;
    let annotation_check = &annotation_outcome.check;
    info!(
        check_id = %annotation_check.id,
        check_name = %annotation_check.name,
        check_domain = %annotation_check.domain,
        check_status = ?annotation_check.status,
        check_severity = ?annotation_check.severity,
        check_detail = %annotation_check.detail,
        "self-check: panic annotation runtime check complete"
    );
    let panic_census = annotation_outcome
        .rows
        .iter()
        .map(panic_census_entry_from_row)
        .collect();
    let silently_dropped = dropped_sites.len();
    let total_callsites = total_callsites(prove_json);

    Ok(SelfCheckScoreboard {
        target: target_rel.to_string(),
        catalog_cid,
        lift,
        bridges,
        oracle,
        silently_dropped,
        dropped_sites,
        total_callsites,
        discharge_split,
        panic_census,
    })
}

fn total_callsites(prove_json: &Value) -> u64 {
    prove_json
        .get("totalCallsites")
        .and_then(Value::as_u64)
        .unwrap_or(0)
}

fn panic_census_row_from_entry(entry: &PanicCensusEntry) -> PanicCensusRow {
    PanicCensusRow {
        file: entry.file.clone(),
        line: entry.line,
        callee: entry.callee.clone(),
        callsite_bundle_cid: entry.callsite_bundle_cid.clone(),
        status: entry.status.clone(),
        reason: entry.reason.clone(),
        category: entry.category.clone(),
        tier_to_close: entry.tier_to_close.clone(),
    }
}

fn panic_census_entry_from_row(row: &PanicCensusRow) -> PanicCensusEntry {
    PanicCensusEntry {
        file: row.file.clone(),
        line: row.line,
        callee: row.callee.clone(),
        callsite_bundle_cid: row.callsite_bundle_cid.clone(),
        status: row.status.clone(),
        reason: row.reason.clone(),
        category: row.category.clone(),
        tier_to_close: row.tier_to_close.clone(),
    }
}

fn lift_scoreboards(lift_json: &Value) -> (LiftScoreboard, BridgeScoreboard, Vec<Site>, Vec<Site>) {
    let mut fn_contracts = 0usize;
    let mut body_discharge_eligible = 0usize;
    let mut body_discharge_ineligible = BTreeMap::new();
    let mut bridges_emitted = 0usize;

    if let Some(ir) = lift_json.get("ir").and_then(|v| v.as_array()) {
        for entry in ir {
            match entry.get("kind").and_then(|v| v.as_str()) {
                Some("function-contract") => {
                    fn_contracts += 1;
                    let body_policy = body_discharge_policy_from_object_with_default(entry, false);
                    let contract = entry
                        .get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("<unnamed>");
                    log_body_discharge_policy_warnings(
                        "self-check-lift-scoreboard",
                        contract,
                        &body_policy.warnings,
                    );
                    if body_policy.body_discharge_eligible {
                        body_discharge_eligible += 1;
                    } else {
                        let reason = body_policy
                            .body_discharge_refusal_reason
                            .unwrap_or_else(|| "unspecified".to_string());
                        *body_discharge_ineligible.entry(reason).or_insert(0) += 1;
                    }
                }
                Some("bridge") => bridges_emitted += 1,
                _ => {}
            }
        }
    }

    let mut lift_gaps = BTreeMap::new();
    let mut dropped_sites = Vec::new();
    let mut unbridged_panic_sites = Vec::new();
    if let Some(diagnostics) = lift_json.get("diagnostics").and_then(|v| v.as_array()) {
        for diagnostic in diagnostics {
            let kind = diagnostic.get("kind").and_then(|v| v.as_str());
            let reason = diagnostic
                .get("reason")
                .and_then(|v| v.as_str())
                .unwrap_or("unspecified");
            if kind == Some("lift-gap") {
                *lift_gaps.entry(reason.to_string()).or_insert(0) += 1;
            }
            if kind == Some("lift-gap") && reason == "body-discharge-ineligible" {
                dropped_sites.push(site_from_diagnostic(diagnostic, reason));
            }
            if diagnostic
                .get("panicSite")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
                || reason == "panic-site-unproven"
            {
                unbridged_panic_sites.push(site_from_diagnostic(diagnostic, reason));
            }
        }
    }
    dropped_sites.sort_by(site_cmp);
    unbridged_panic_sites.sort_by(site_cmp);

    (
        LiftScoreboard {
            fn_contracts,
            body_discharge_eligible,
            body_discharge_ineligible,
        },
        BridgeScoreboard {
            emitted: bridges_emitted,
            lift_gaps,
        },
        dropped_sites,
        unbridged_panic_sites,
    )
}

fn discharge_split(prove_json: &Value) -> DischargeSplit {
    let mut split = DischargeSplit {
        panic_safe: 0,
        reflexive: 0,
        vacuous: 0,
        undecidable: 0,
        false_pass: 0,
    };
    let Some(rows) = prove_json.get("rows").and_then(|v| v.as_array()) else {
        if let Some(ds) = prove_json.get("dischargeSplit") {
            split.panic_safe = usize_field(ds, "panicSafe");
            split.reflexive = usize_field(ds, "reflexive");
            split.vacuous = usize_field(ds, "vacuous");
            split.undecidable = usize_field(ds, "undecidable");
            split.false_pass = usize_field(ds, "falsePass");
        }
        return split;
    };

    for row in rows {
        let status = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if status != "discharged" {
            split.undecidable += 1;
            continue;
        }
        let method = row.get("dischargeMethod").and_then(|v| v.as_str());
        let panic_site = row
            .get("panicSite")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if panic_site && method != Some("panic-safe") {
            split.false_pass += 1;
            continue;
        }
        match method {
            Some("panic-safe") if panic_site => split.panic_safe += 1,
            Some("reflexive") => split.reflexive += 1,
            Some("vacuous") => split.vacuous += 1,
            _ => {}
        }
    }
    split
}

#[cfg(test)]
fn panic_site_annotations(
    lift_json: &Value,
) -> Result<BTreeMap<(String, usize, String), PanicSiteAnnotation>, String> {
    let mut annotations = BTreeMap::new();
    let Some(diagnostics) = lift_json.get("diagnostics").and_then(|v| v.as_array()) else {
        return Ok(annotations);
    };
    for diagnostic in diagnostics {
        if diagnostic.get("kind").and_then(|v| v.as_str()) != Some("panic-site-annotation") {
            continue;
        }
        let file = required_annotation_string(diagnostic, "file")?;
        let line = diagnostic
            .get("line")
            .and_then(|v| v.as_u64())
            .ok_or_else(|| format!("panic-site annotation for {file} missing numeric line"))?
            as usize;
        let callee = required_annotation_string(diagnostic, "callee")?;
        let status = required_annotation_string(diagnostic, "status")?;
        if status != "residue" && status != "unproven" {
            return Err(format!(
                "panic-site annotation for {}:{} {} has invalid status `{}`",
                file, line, callee, status
            ));
        }
        let category = required_annotation_string(diagnostic, "category")?;
        let tier_to_close = required_annotation_string(diagnostic, "tierToClose")?;
        let reason = required_annotation_string(diagnostic, "reason")?;
        let key = (file.clone(), line, callee.clone());
        if annotations
            .insert(
                key,
                PanicSiteAnnotation {
                    file: file.clone(),
                    line,
                    callee: callee.clone(),
                    status,
                    category,
                    tier_to_close,
                    reason,
                },
            )
            .is_some()
        {
            return Err(format!(
                "duplicate panic-site annotation for {}:{} {}",
                file, line, callee
            ));
        }
    }
    Ok(annotations)
}

#[cfg(test)]
fn required_annotation_string(diagnostic: &Value, field: &str) -> Result<String, String> {
    diagnostic
        .get(field)
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .ok_or_else(|| format!("panic-site annotation missing {field}"))
}

fn panic_census(
    prove_json: &Value,
    unbridged: Vec<Site>,
    annotations: BTreeMap<(String, usize, String), PanicSiteAnnotation>,
) -> Result<Vec<PanicCensusEntry>, String> {
    let mut by_site: BTreeMap<(Option<String>, String, usize, String), PanicCensusEntry> =
        BTreeMap::new();
    if let Some(rows) = prove_json.get("rows").and_then(|v| v.as_array()) {
        for row in rows {
            if !row
                .get("panicSite")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
            {
                continue;
            }
            let file = row
                .get("file")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();
            let line = row.get("line").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let callee = row
                .get("callee")
                .and_then(|v| v.as_str())
                .or_else(|| row.get("bridge").and_then(|v| v.as_str()))
                .unwrap_or("unknown")
                .to_string();
            let callsite_bundle_cid = row
                .get("callsiteBundleCid")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string);
            let method = row.get("dischargeMethod").and_then(|v| v.as_str());
            let row_status = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
            let (status, reason) = if row_status == "discharged" && method == Some("panic-safe") {
                ("proven".to_string(), row_reason(row))
            } else if row_status == "discharged" {
                (
                    "unproven".to_string(),
                    format!(
                        "false pass: panic site discharged with method {}",
                        method.unwrap_or("unspecified")
                    ),
                )
            } else {
                ("unproven".to_string(), row_reason(row))
            };
            let key = (
                callsite_bundle_cid.clone(),
                file.clone(),
                line,
                callee.clone(),
            );
            if by_site
                .insert(
                    key,
                    PanicCensusEntry {
                        file,
                        line,
                        callee,
                        callsite_bundle_cid,
                        status,
                        reason,
                        category: None,
                        tier_to_close: None,
                    },
                )
                .is_some()
            {
                return Err("duplicate panic census row after bundle scoping".to_string());
            }
        }
    }

    for site in unbridged {
        by_site
            .entry((None, site.file.clone(), site.line, site.callee.clone()))
            .or_insert(PanicCensusEntry {
                file: site.file,
                line: site.line,
                callee: site.callee,
                callsite_bundle_cid: None,
                status: "unproven".to_string(),
                reason: site.reason,
                category: None,
                tier_to_close: None,
            });
    }

    for (key, annotation) in annotations {
        let scoped_key = (None, key.0, key.1, key.2);
        let Some(entry) = by_site.get_mut(&scoped_key) else {
            return Err(format!(
                "stale panic-site annotation for {}:{} {}",
                annotation.file, annotation.line, annotation.callee
            ));
        };
        if entry.status == "proven" {
            return Err(format!(
                "proven panic-site annotation for {}:{} {}",
                annotation.file, annotation.line, annotation.callee
            ));
        }
        entry.status = annotation.status;
        entry.category = Some(annotation.category);
        entry.tier_to_close = Some(annotation.tier_to_close);
        entry.reason = annotation.reason;
    }

    let mut census: Vec<_> = by_site.into_values().collect();
    census.sort_by(|a, b| {
        (&a.file, a.line, &a.callee, &a.callsite_bundle_cid).cmp(&(
            &b.file,
            b.line,
            &b.callee,
            &b.callsite_bundle_cid,
        ))
    });
    Ok(census)
}

fn row_reason(row: &Value) -> String {
    row.get("reason")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("no reason reported")
        .to_string()
}

fn monoid_fold_gaps_by_element_type_from_entries(
    entries: &[PanicCensusEntry],
) -> BTreeMap<String, u64> {
    let mut counts = BTreeMap::new();
    for entry in entries {
        if let Some(element_type) = monoid_fold_gap_element_type(&entry.reason) {
            *counts.entry(element_type).or_insert(0) += 1;
        }
    }
    counts
}

fn monoid_fold_gap_element_type(reason: &str) -> Option<String> {
    if !reason.contains("MonoidFold") {
        return None;
    }
    let (_, tail) = reason.split_once("element_type=")?;
    let element_type = tail
        .split(',')
        .next()
        .unwrap_or("")
        .trim()
        .trim_matches('`');
    (!element_type.is_empty()).then(|| element_type.to_string())
}

fn site_from_diagnostic(diagnostic: &Value, fallback_reason: &str) -> Site {
    Site {
        file: diagnostic
            .get("file")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        line: diagnostic
            .get("line")
            .or_else(|| diagnostic.get("start_line"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize,
        callee: diagnostic
            .get("callee")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string(),
        reason: diagnostic
            .get("detail")
            .and_then(|v| v.as_str())
            .or_else(|| diagnostic.get("reason").and_then(|v| v.as_str()))
            .unwrap_or(fallback_reason)
            .to_string(),
    }
}

fn emit_scoreboard(scoreboard: &SelfCheckScoreboard, json: bool) {
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(scoreboard).expect("serialize self-check scoreboard")
        );
        return;
    }

    let ineligible_total: usize = scoreboard
        .lift
        .body_discharge_ineligible
        .values()
        .copied()
        .sum();
    let lift_gap_total: usize = scoreboard.bridges.lift_gaps.values().copied().sum();
    println!("Sugar self-check");
    println!("target: {}", scoreboard.target);
    println!("catalogCid: {}", scoreboard.catalog_cid);
    println!(
        "lift: {} fn-contracts, {} body-discharge-eligible, {} ineligible",
        scoreboard.lift.fn_contracts, scoreboard.lift.body_discharge_eligible, ineligible_total
    );
    if !scoreboard.lift.body_discharge_ineligible.is_empty() {
        println!(
            "lift refusals: {}",
            format_breakdown(&scoreboard.lift.body_discharge_ineligible)
        );
    }
    println!(
        "bridges: {} emitted, {} lift-gaps",
        scoreboard.bridges.emitted, lift_gap_total
    );
    if !scoreboard.bridges.lift_gaps.is_empty() {
        println!(
            "lift gaps: {}",
            format_breakdown(&scoreboard.bridges.lift_gaps)
        );
    }
    println!(
        "oracle: requested={}, engaged={}, attempted={}, resolved={}",
        scoreboard.oracle.requested,
        scoreboard.oracle.engaged,
        scoreboard.oracle.attempted,
        scoreboard.oracle.resolved
    );
    println!("silentlyDropped: {}", scoreboard.silently_dropped);
    println!("totalCallsites: {}", scoreboard.total_callsites);
    println!(
        "dischargeSplit: panicSafe={}, reflexive={}, vacuous={}, undecidable={}, falsePass={}",
        scoreboard.discharge_split.panic_safe,
        scoreboard.discharge_split.reflexive,
        scoreboard.discharge_split.vacuous,
        scoreboard.discharge_split.undecidable,
        scoreboard.discharge_split.false_pass
    );
    println!("panicCensus: {} site(s)", scoreboard.panic_census.len());
    let monoid_fold_gaps = monoid_fold_gaps_by_element_type_from_entries(&scoreboard.panic_census);
    if !monoid_fold_gaps.is_empty() {
        println!(
            "monoidFoldCarrierEmbeddingGaps: {}",
            monoid_fold_gaps
                .iter()
                .map(|(element_type, count)| format!("{element_type}={count}"))
                .collect::<Vec<_>>()
                .join(", ")
        );
    }
    let algebra_gaps = algebra_gaps_by_boundary_from_reasons(
        scoreboard
            .panic_census
            .iter()
            .map(|entry| entry.reason.as_str()),
    );
    if !algebra_gaps.is_empty() {
        println!(
            "algebraGapsByBoundary: {}",
            algebra_gaps
                .iter()
                .map(|(boundary, count)| format!("{boundary}={count}"))
                .collect::<Vec<_>>()
                .join(", ")
        );
    }
    for site in &scoreboard.panic_census {
        println!(
            "  {}:{} {} {}, reason: {}",
            site.file, site.line, site.callee, site.status, site.reason
        );
    }
}

fn format_breakdown(map: &BTreeMap<String, usize>) -> String {
    map.iter()
        .map(|(reason, count)| format!("{reason}={count}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn parse_json_stdout(command: &str, project: &Path, output: &Output) -> Result<Value, String> {
    serde_json::from_slice(&output.stdout).map_err(|e| {
        format!(
            "{command} for {} did not emit JSON stdout: {e}\nstdout:\n{}\nstderr:\n{}",
            project.display(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        )
    })
}

fn command_failure(command: &str, project: &Path, output: &Output) -> String {
    format!(
        "{command} for {} exited with {}\nstdout:\n{}\nstderr:\n{}",
        project.display(),
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    )
}

fn repo_relative(repo_root: &Path, path: &Path) -> String {
    path.strip_prefix(repo_root)
        .unwrap_or(path)
        .display()
        .to_string()
        .replace('\\', "/")
}

fn sanitize_path_component(path: &str) -> String {
    path.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect()
}

fn same_path(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => false,
    }
}

fn site_cmp(left: &Site, right: &Site) -> std::cmp::Ordering {
    (&left.file, left.line, &left.callee, &left.reason).cmp(&(
        &right.file,
        right.line,
        &right.callee,
        &right.reason,
    ))
}

fn usize_field(value: &Value, key: &str) -> usize {
    value.get(key).and_then(|v| v.as_u64()).unwrap_or(0) as usize
}

fn oracle_scoreboard(mint_json: &Value) -> OracleScoreboard {
    let mint_oracle = mint_json.get("oracle");
    let lift = mint_json.get("lift");
    let requested = mint_oracle
        .and_then(|v| v.get("requested"))
        .and_then(Value::as_bool)
        .or_else(|| {
            lift.and_then(|v| v.get("oracle_requested"))
                .and_then(Value::as_bool)
        })
        .unwrap_or(false);
    let attempted = mint_oracle
        .and_then(|v| v.get("attempted"))
        .and_then(Value::as_u64)
        .or_else(|| {
            lift.and_then(|v| v.get("receivers_attempted"))
                .and_then(Value::as_u64)
        })
        .unwrap_or(0);
    let resolved = mint_oracle
        .and_then(|v| v.get("resolved"))
        .and_then(Value::as_u64)
        .or_else(|| {
            lift.and_then(|v| v.get("receivers_resolved"))
                .and_then(Value::as_u64)
        })
        .unwrap_or(0);
    OracleScoreboard {
        requested,
        engaged: requested && resolved > 0,
        attempted,
        resolved,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::{self, Write};
    use std::sync::{Arc, Mutex};
    use tracing_subscriber::fmt::MakeWriter;

    #[derive(Clone, Default)]
    struct SharedLog(Arc<Mutex<Vec<u8>>>);

    struct SharedLogWriter(Arc<Mutex<Vec<u8>>>);

    impl Write for SharedLogWriter {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.0.lock().expect("log lock").extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    impl<'a> MakeWriter<'a> for SharedLog {
        type Writer = SharedLogWriter;

        fn make_writer(&'a self) -> Self::Writer {
            SharedLogWriter(self.0.clone())
        }
    }

    fn capture_warn_log(f: impl FnOnce()) -> String {
        let log = SharedLog::default();
        let subscriber = tracing_subscriber::fmt()
            .with_max_level(tracing::Level::WARN)
            .with_writer(log.clone())
            .with_ansi(false)
            .without_time()
            .finish();
        tracing::subscriber::with_default(subscriber, f);
        let bytes = log.0.lock().expect("log lock").clone();
        String::from_utf8(bytes).expect("log is utf8")
    }

    fn mint_json(requested: bool, attempted: u64, resolved: u64) -> Value {
        json!({
            "filenameCid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "oracle": {
                "requested": requested,
                "reachable": resolved > 0,
                "attempted": attempted,
                "resolved": resolved
            },
            "lift": {
                "kind": "ir-document",
                "ir": [],
                "diagnostics": []
            }
        })
    }

    fn mint_json_with_diagnostics(diagnostics: Vec<Value>) -> Value {
        json!({
            "filenameCid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "oracle": {
                "requested": true,
                "reachable": true,
                "attempted": 1,
                "resolved": 1
            },
            "lift": {
                "kind": "ir-document",
                "ir": [],
                "diagnostics": diagnostics
            }
        })
    }

    fn prove_json() -> Value {
        json!({
            "rows": []
        })
    }

    fn panic_row(
        file: &str,
        line: usize,
        callee: &str,
        status: &str,
        method: Option<&str>,
    ) -> Value {
        let mut row = json!({
            "file": file,
            "line": line,
            "callee": callee,
            "panicSite": true,
            "status": status,
            "reason": "synthetic panic row"
        });
        if let Some(method) = method {
            row.as_object_mut()
                .expect("row object")
                .insert("dischargeMethod".to_string(), json!(method));
        }
        row
    }

    fn panic_row_with_bundle(
        bundle: &str,
        file: &str,
        line: usize,
        callee: &str,
        status: &str,
        method: Option<&str>,
    ) -> Value {
        let mut row = panic_row(file, line, callee, status, method);
        row.as_object_mut()
            .expect("row object")
            .insert("callsiteBundleCid".to_string(), json!(bundle));
        row
    }

    fn panic_site_annotation(
        file: &str,
        line: usize,
        callee: &str,
        status: &str,
        category: &str,
        tier_to_close: &str,
    ) -> Value {
        json!({
            "kind": "panic-site-annotation",
            "file": file,
            "line": line,
            "callee": callee,
            "status": status,
            "category": category,
            "tierToClose": tier_to_close,
            "reason": "synthetic annotation reason"
        })
    }

    fn load_error(reason: &str) -> LoadError {
        LoadError {
            proof_path: "synthetic.proof".to_string(),
            reason: reason.to_string(),
        }
    }

    #[test]
    fn effect_site_annotation_scan_tolerates_unrelated_load_errors() {
        let mut pool = MementoPool::default();
        pool.load_errors.push(load_error(
            "duplicate contract name `read_response` resolves to two CIDs",
        ));

        let annotations = effect_site_annotations_from_pool(pool).expect("unrelated errors");

        assert!(annotations.is_empty());
    }

    #[test]
    fn effect_site_annotation_scan_fails_on_tagged_annotation_errors() {
        let mut pool = MementoPool::default();
        pool.load_errors.push(load_error(
            "[effect-site-annotation] blake3-512:abc: missing or invalid `callee`",
        ));

        let err =
            effect_site_annotations_from_pool(pool).expect_err("annotation load errors must fail");

        assert!(err.contains("[effect-site-annotation]"), "{err}");
        assert!(err.contains("callee"), "{err}");
    }

    #[test]
    fn effect_site_annotation_scan_reports_only_tagged_errors_when_mixed() {
        let mut pool = MementoPool::default();
        pool.load_errors.push(load_error(
            "duplicate contract name `string_field` resolves to two CIDs",
        ));
        pool.load_errors.push(load_error(
            "[effect-site-annotation-duplicate] for (bundle, src/lib.rs, 10, method:unwrap)",
        ));

        let err =
            effect_site_annotations_from_pool(pool).expect_err("tagged mixed error must fail");

        assert!(err.contains("[effect-site-annotation-duplicate]"), "{err}");
        assert!(!err.contains("string_field"), "{err}");
    }

    #[test]
    fn lift_scoreboard_accepts_discharge_policy_body_reduction_allowed() {
        let lift_json = json!({
            "ir": [{
                "kind": "function-contract",
                "name": "total",
                "dischargePolicy": {
                    "bodyReduction": {
                        "status": "allowed"
                    }
                }
            }]
        });

        let (lift, _, _, _) = lift_scoreboards(&lift_json);

        assert_eq!(lift.fn_contracts, 1);
        assert_eq!(lift.body_discharge_eligible, 1);
        assert!(lift.body_discharge_ineligible.is_empty());
    }

    #[test]
    fn lift_scoreboard_accepts_discharge_policy_body_reduction_refused() {
        let lift_json = json!({
            "ir": [{
                "kind": "function-contract",
                "name": "axiom",
                "dischargePolicy": {
                    "bodyReduction": {
                        "status": "refused",
                        "reason": "totality-axiom"
                    }
                }
            }]
        });

        let (lift, _, _, _) = lift_scoreboards(&lift_json);

        assert_eq!(lift.fn_contracts, 1);
        assert_eq!(lift.body_discharge_eligible, 0);
        assert_eq!(
            lift.body_discharge_ineligible.get("totality-axiom"),
            Some(&1)
        );
    }

    #[test]
    fn lift_scoreboard_keeps_legacy_body_discharge_fields_on_disagreement() {
        let lift_json = json!({
            "ir": [{
                "kind": "function-contract",
                "name": "legacy_wins",
                "bodyDischargeEligible": false,
                "bodyDischargeRefusalReason": "legacy-refusal",
                "dischargePolicy": {
                    "bodyReduction": {
                        "status": "allowed"
                    }
                }
            }]
        });

        let (lift, _, _, _) = lift_scoreboards(&lift_json);

        assert_eq!(lift.body_discharge_eligible, 0);
        assert_eq!(
            lift.body_discharge_ineligible.get("legacy-refusal"),
            Some(&1)
        );
    }

    #[test]
    fn lift_scoreboard_warns_once_for_body_discharge_policy_disagreement() {
        let lift_json = json!({
            "ir": [{
                "kind": "function-contract",
                "name": "legacy_wins",
                "bodyDischargeEligible": false,
                "bodyDischargeRefusalReason": "legacy-refusal",
                "dischargePolicy": {
                    "bodyReduction": {
                        "status": "allowed"
                    }
                }
            }]
        });

        let logs = capture_warn_log(|| {
            let _ = lift_scoreboards(&lift_json);
        });

        assert_eq!(
            logs.matches("body-discharge-disagreement").count(),
            1,
            "one policy disagreement must warn once; logs:\n{logs}"
        );
    }

    #[test]
    fn lift_scoreboard_warns_for_malformed_body_discharge_policy() {
        let lift_json = json!({
            "ir": [{
                "kind": "function-contract",
                "name": "malformed_policy",
                "bodyDischargeEligible": true,
                "dischargePolicy": {
                    "bodyReduction": {
                        "status": 42
                    }
                }
            }]
        });

        let logs = capture_warn_log(|| {
            let _ = lift_scoreboards(&lift_json);
        });

        assert!(
            logs.contains("body-discharge-malformed"),
            "malformed policy must warn with tag; logs:\n{logs}"
        );
    }

    #[test]
    fn dependency_mints_inherit_self_check_oracle_request() {
        assert!(
            dependency_mint_uses_oracle(true),
            "self-check --oracle must mint local dependency proofs with the same oracle setting"
        );
        assert!(
            !dependency_mint_uses_oracle(false),
            "self-check without --oracle must keep dependency mints syntactic-only"
        );
    }

    fn write_import(path: &Path, file_name: &str) {
        fs::write(path.join(file_name), format!("contents for {file_name}")).expect("write import");
    }

    #[test]
    fn imports_snapshot_sorts_proof_files_and_ignores_other_files() {
        let dir = tempfile::tempdir().expect("tempdir");
        write_import(dir.path(), "b.proof");
        write_import(dir.path(), "notes.txt");
        write_import(dir.path(), "a.proof");

        let snapshot = snapshot_imports_proof_set(dir.path()).expect("snapshot");

        assert!(snapshot.directory_present);
        assert_eq!(snapshot.len(), 2);
        assert_eq!(snapshot.path_list(), "a.proof, b.proof");
    }

    #[test]
    fn imports_unchanged_snapshot_passes() {
        let dir = tempfile::tempdir().expect("tempdir");
        write_import(dir.path(), "a.proof");
        let snapshot = snapshot_imports_proof_set(dir.path()).expect("snapshot");

        assert_imports_proof_set_unchanged(dir.path(), &snapshot, "test phase")
            .expect("unchanged imports should pass");
    }

    #[test]
    fn imports_removed_file_fails_closed() {
        let dir = tempfile::tempdir().expect("tempdir");
        write_import(dir.path(), "a.proof");
        write_import(dir.path(), "b.proof");
        let snapshot = snapshot_imports_proof_set(dir.path()).expect("snapshot");

        fs::remove_file(dir.path().join("b.proof")).expect("remove proof");

        let err = assert_imports_proof_set_unchanged(dir.path(), &snapshot, "after prove")
            .expect_err("removed import should fail closed");
        assert!(
            err.contains("mutated during after prove"),
            "unexpected error: {err}"
        );
        assert!(
            err.contains("before (2) proof files"),
            "unexpected error: {err}"
        );
        assert!(
            err.contains("after (1) proof files"),
            "unexpected error: {err}"
        );
        assert!(
            err.contains("removed: [b.proof]"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn imports_added_file_fails_closed() {
        let dir = tempfile::tempdir().expect("tempdir");
        write_import(dir.path(), "a.proof");
        let snapshot = snapshot_imports_proof_set(dir.path()).expect("snapshot");

        write_import(dir.path(), "extra.proof");

        let err = assert_imports_proof_set_unchanged(dir.path(), &snapshot, "after prove")
            .expect_err("added import should fail closed");
        assert!(
            err.contains("added: [extra.proof]"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn imports_directory_removed_fails_closed() {
        let dir = tempfile::tempdir().expect("tempdir");
        let imports = dir.path().join("imports");
        fs::create_dir_all(&imports).expect("create imports");
        write_import(&imports, "a.proof");
        let snapshot = snapshot_imports_proof_set(&imports).expect("snapshot");

        fs::remove_dir_all(&imports).expect("remove imports");

        let err = assert_imports_proof_set_unchanged(&imports, &snapshot, "after prove")
            .expect_err("removed imports directory should fail closed");
        assert!(
            err.contains("imports directory disappeared"),
            "unexpected error: {err}"
        );
        assert!(
            err.contains("removed: [a.proof]"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn self_check_stages_rpc_dependency_proof_bytes_without_using_source_path() {
        let dir = tempfile::tempdir().expect("tempdir");
        let imports = dir.path().join("imports");
        fs::create_dir_all(&imports).expect("create imports");
        let target = dir.path().join("target");
        let bytes = b"rpc dependency proof bytes".to_vec();
        let cid = sugar_canonicalizer::blake3_512_of(&bytes);
        let source_path_label = dir.path().join("package-internal").join("vendor.proof");

        let count = stage_rpc_dependency_proofs_to_imports(&target, &imports, |_| {
            Ok(vec![
                sugar_verifier::load_all_proofs::ProofBytes::try_from_parts(
                    source_path_label.display().to_string(),
                    cid.clone(),
                    bytes.clone(),
                    sugar_verifier::Speaker::vendor(source_path_label.display().to_string()),
                )
                .expect("test proof CID must parse"),
            ])
        })
        .expect("stage rpc dependency proofs");

        assert_eq!(count, 1);
        // Staged under the colon-free, prefix-retained on-disk name
        // (Windows-safe); `blake3-512:<hex>` -> `blake3-512_<hex>.proof`.
        let staged_name = proof_filename(&cid);
        assert!(!staged_name.contains(':'), "staged name must be colon-free");
        let staged = imports.join(&staged_name);
        assert_eq!(fs::read(&staged).expect("read staged proof"), bytes);
        let snapshot = snapshot_imports_proof_set(&imports).expect("snapshot");
        assert_eq!(
            snapshot.path_list(),
            staged_name,
            "self-check must stage proof bytes by CID, not by kit source path"
        );
    }

    #[test]
    fn dependency_import_staging_copies_required_proof_and_drop_removes_it() {
        let dir = tempfile::tempdir().expect("tempdir");
        let dependency_root = dir.path().join("libsugar");
        let proof_dir = dir.path().join("proofs");
        fs::create_dir_all(&proof_dir).expect("create proof dir");
        let proof = proof_dir.join("shim-std.proof");
        fs::write(&proof, b"shim std proof bytes").expect("write proof");
        let mut proofs = BTreeMap::new();
        proofs.insert("shim-std".to_string(), proof.clone());

        let guard =
            stage_dependency_imports_for_mint("libsugar", &dependency_root, &["shim-std"], &proofs)
                .expect("stage dependency import");

        let staged = dependency_root
            .join(".sugar")
            .join("imports")
            .join("shim-std.proof");
        assert_eq!(
            fs::read(&staged).expect("read staged proof"),
            b"shim std proof bytes"
        );

        drop(guard);
        assert!(
            !staged.exists(),
            "drop guard must remove proof staged by this self-check run"
        );
    }

    #[test]
    fn dependency_import_staging_preserves_existing_identical_proof() {
        let dir = tempfile::tempdir().expect("tempdir");
        let dependency_root = dir.path().join("libsugar");
        let imports = dependency_root.join(".sugar").join("imports");
        fs::create_dir_all(&imports).expect("create imports");
        let existing = imports.join("shim-std.proof");
        fs::write(&existing, b"same proof bytes").expect("write existing proof");
        let proof = dir.path().join("shim-std.proof");
        fs::write(&proof, b"same proof bytes").expect("write incoming proof");
        let mut proofs = BTreeMap::new();
        proofs.insert("shim-std".to_string(), proof);

        let guard =
            stage_dependency_imports_for_mint("libsugar", &dependency_root, &["shim-std"], &proofs)
                .expect("identical pre-existing proof should be accepted");

        drop(guard);
        assert_eq!(
            fs::read(&existing).expect("existing proof remains"),
            b"same proof bytes",
            "drop guard must not delete an import that existed before staging"
        );
    }

    #[test]
    fn dependency_import_staging_refuses_existing_different_proof() {
        let dir = tempfile::tempdir().expect("tempdir");
        let dependency_root = dir.path().join("libsugar");
        let imports = dependency_root.join(".sugar").join("imports");
        fs::create_dir_all(&imports).expect("create imports");
        fs::write(imports.join("shim-std.proof"), b"old bytes").expect("write existing proof");
        let proof = dir.path().join("shim-std.proof");
        fs::write(&proof, b"new bytes").expect("write incoming proof");
        let mut proofs = BTreeMap::new();
        proofs.insert("shim-std".to_string(), proof);

        let err =
            stage_dependency_imports_for_mint("libsugar", &dependency_root, &["shim-std"], &proofs)
                .expect_err("different pre-existing proof must fail closed");
        assert!(
            err.contains("already exists with different bytes"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn dependency_import_staging_requires_declared_dependency_proof() {
        let dir = tempfile::tempdir().expect("tempdir");
        let dependency_root = dir.path().join("libsugar");
        let proofs = BTreeMap::new();

        let err =
            stage_dependency_imports_for_mint("libsugar", &dependency_root, &["shim-std"], &proofs)
                .expect_err("missing required dependency proof must fail closed");
        assert!(
            err.contains("requires `shim-std` proof before minting"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn build_scoreboard_sets_oracle_engaged_from_requested_and_resolved() {
        let cases = [
            (false, 0, false),
            (false, 1, false),
            (true, 0, false),
            (true, 1, true),
        ];

        for (requested, resolved, expected_engaged) in cases {
            let scoreboard =
                build_scoreboard("target", &mint_json(requested, 7, resolved), &prove_json())
                    .expect("scoreboard");
            assert_eq!(scoreboard.oracle.requested, requested);
            assert_eq!(scoreboard.oracle.attempted, 7);
            assert_eq!(scoreboard.oracle.resolved, resolved);
            assert_eq!(
                scoreboard.oracle.engaged, expected_engaged,
                "requested={requested}, resolved={resolved}"
            );
        }
    }

    #[test]
    fn build_scoreboard_emits_total_callsites_for_release_gate_floor() {
        let prove = json!({
            "totalCallsites": 1,
            "rows": []
        });
        let scoreboard =
            build_scoreboard("target", &mint_json(true, 7, 7), &prove).expect("scoreboard");
        let rendered = serde_json::to_value(&scoreboard).expect("scoreboard json");

        assert_eq!(scoreboard.total_callsites, 1);
        assert_eq!(rendered["totalCallsites"], 1);
    }

    #[test]
    fn panic_census_applies_residue_annotation_to_unproven_site() {
        let mint = mint_json_with_diagnostics(vec![panic_site_annotation(
            "src/kit_dispatch.rs",
            106,
            "expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
        )]);
        let prove = json!({
            "rows": [panic_row("src/kit_dispatch.rs", 106, "expect", "undecidable", None)]
        });

        let scoreboard = build_scoreboard("target", &mint, &prove).expect("scoreboard");
        let rendered = serde_json::to_value(&scoreboard).expect("scoreboard json");
        let row = &rendered["panicCensus"][0];

        assert_eq!(row["status"], "residue");
        assert_eq!(row["category"], "lock_poisoning_residue");
        assert_eq!(row["tierToClose"], "irreducible");
        assert_eq!(row["reason"], "synthetic annotation reason");
    }

    #[test]
    fn panic_census_applies_tier_to_close_annotation_without_proving_site() {
        let mint = mint_json_with_diagnostics(vec![panic_site_annotation(
            "src/kit_dispatch.rs",
            2416,
            "expect",
            "unproven",
            "D-lib",
            "generic fixture tier",
        )]);
        let prove = json!({
            "rows": [panic_row("src/kit_dispatch.rs", 2416, "expect", "undecidable", None)]
        });

        let scoreboard = build_scoreboard("target", &mint, &prove).expect("scoreboard");
        let rendered = serde_json::to_value(&scoreboard).expect("scoreboard json");
        let row = &rendered["panicCensus"][0];

        assert_eq!(row["status"], "unproven");
        assert_eq!(row["category"], "D-lib");
        assert_eq!(row["tierToClose"], "generic fixture tier");
    }

    #[test]
    fn panic_census_rejects_duplicate_annotation_keys() {
        let mint = mint_json_with_diagnostics(vec![
            panic_site_annotation(
                "src/kit_dispatch.rs",
                106,
                "expect",
                "residue",
                "lock_poisoning_residue",
                "irreducible",
            ),
            panic_site_annotation(
                "src/kit_dispatch.rs",
                106,
                "expect",
                "unproven",
                "D-lib",
                "future tier",
            ),
        ]);
        let prove = json!({
            "rows": [panic_row("src/kit_dispatch.rs", 106, "expect", "undecidable", None)]
        });

        let err = build_scoreboard("target", &mint, &prove)
            .expect_err("duplicate annotations must fail closed");
        assert!(
            err.contains("duplicate panic-site annotation"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn panic_census_rejects_stale_annotation_without_matching_site() {
        let mint = mint_json_with_diagnostics(vec![panic_site_annotation(
            "src/kit_dispatch.rs",
            9999,
            "expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
        )]);
        let prove = json!({
            "rows": [panic_row("src/kit_dispatch.rs", 106, "expect", "undecidable", None)]
        });

        let err = build_scoreboard("target", &mint, &prove)
            .expect_err("stale annotations must fail closed");
        assert!(
            err.contains("stale panic-site annotation"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn panic_census_rejects_annotation_on_proven_site() {
        let mint = mint_json_with_diagnostics(vec![panic_site_annotation(
            "src/kit_dispatch.rs",
            106,
            "expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
        )]);
        let prove = json!({
            "rows": [panic_row(
                "src/kit_dispatch.rs",
                106,
                "expect",
                "discharged",
                Some("panic-safe")
            )]
        });

        let err = build_scoreboard("target", &mint, &prove)
            .expect_err("annotations on proven sites must fail closed");
        assert!(
            err.contains("proven panic-site annotation"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn panic_census_rejects_annotation_missing_tier_to_close() {
        let mut annotation = panic_site_annotation(
            "src/kit_dispatch.rs",
            106,
            "expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
        );
        annotation
            .as_object_mut()
            .expect("annotation object")
            .remove("tierToClose");
        let mint = mint_json_with_diagnostics(vec![annotation]);
        let prove = json!({
            "rows": [panic_row("src/kit_dispatch.rs", 106, "expect", "undecidable", None)]
        });

        let err = build_scoreboard("target", &mint, &prove)
            .expect_err("missing tierToClose must fail closed");
        assert!(err.contains("tierToClose"), "unexpected error: {err}");
    }

    #[test]
    fn panic_census_annotation_preserves_panic_safe_count() {
        let mut rows = Vec::new();
        for line in 1..=21 {
            rows.push(panic_row(
                "src/proven.rs",
                line,
                "unwrap",
                "discharged",
                Some("panic-safe"),
            ));
        }
        rows.push(panic_row(
            "src/kit_dispatch.rs",
            106,
            "expect",
            "undecidable",
            None,
        ));
        let mint = mint_json_with_diagnostics(vec![panic_site_annotation(
            "src/kit_dispatch.rs",
            106,
            "expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
        )]);
        let prove = json!({ "rows": rows });

        let scoreboard = build_scoreboard("target", &mint, &prove).expect("scoreboard");

        assert_eq!(scoreboard.discharge_split.panic_safe, 21);
        assert_eq!(scoreboard.discharge_split.false_pass, 0);
    }

    fn write_self_check_residue_manifest(target: &Path, body: &str) {
        let sugar = target.join(".sugar");
        fs::create_dir_all(&sugar).expect("create .sugar");
        fs::write(sugar.join("residue.toml"), body).expect("write residue manifest");
    }

    #[test]
    fn build_scoreboard_applies_runtime_doctor_annotations_from_target_manifest() {
        let td = tempfile::tempdir().expect("tempdir");
        write_self_check_residue_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/kit_dispatch.rs"
line = 106
callee = "expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "runtime doctor annotation"
"#,
        );
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "rows": [panic_row("src/kit_dispatch.rs", 106, "expect", "undecidable", None)]
        });

        let scoreboard = build_scoreboard_with_runtime_annotations(
            "target",
            td.path(),
            &mint,
            &prove,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect("scoreboard");
        let rendered = serde_json::to_value(&scoreboard).expect("scoreboard json");
        let row = &rendered["panicCensus"][0];

        assert_eq!(row["status"], "residue");
        assert_eq!(row["category"], "lock_poisoning_residue");
        assert_eq!(row["tierToClose"], "irreducible");
        assert_eq!(row["reason"], "runtime doctor annotation");
    }

    #[test]
    fn runtime_doctor_annotation_receives_post_prove_panic_census_projection() {
        let td = tempfile::tempdir().expect("tempdir");
        write_self_check_residue_manifest(
            td.path(),
            r#"
[[tier_to_close]]
file = "src/generated_by_prove.rs"
line = 44
callee = "method:unwrap"
category = "D-lib"
tier_to_close = "future totality proof"
reason = "this row exists only in prove output"
"#,
        );
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "rows": [panic_row(
                "src/generated_by_prove.rs",
                44,
                "method:unwrap",
                "undecidable",
                None
            )]
        });

        let scoreboard = build_scoreboard_with_runtime_annotations(
            "target",
            td.path(),
            &mint,
            &prove,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect("scoreboard");

        assert_eq!(
            scoreboard.panic_census[0].category.as_deref(),
            Some("D-lib")
        );
        assert_eq!(
            scoreboard.panic_census[0].tier_to_close.as_deref(),
            Some("future totality proof")
        );
    }

    #[test]
    fn self_check_scoreboard_does_not_serialize_callsite_bundle_cid_in_panic_census() {
        let td = tempfile::tempdir().expect("tempdir");
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "rows": [{
                "file": "src/generated_by_prove.rs",
                "line": 44,
                "callee": "method:unwrap",
                "panicSite": true,
                "status": "undecidable",
                "reason": "synthetic panic row",
                "callsiteBundleCid": "blake3-512:dependency-bundle"
            }]
        });
        let annotations = vec![sugar_verifier::types::EffectSiteAnnotation {
            effect_kind: "panic-freedom".to_string(),
            file: "src/generated_by_prove.rs".to_string(),
            line: 44,
            callee: "method:unwrap".to_string(),
            status: "unproven".to_string(),
            category: "D-lib".to_string(),
            tier_to_close: "future totality proof".to_string(),
            reason: "dependency memento annotation".to_string(),
            memento_cid: "blake3-512:annotation".to_string(),
            bundle_cid: "blake3-512:dependency-bundle".to_string(),
        }];

        let scoreboard = build_scoreboard_with_runtime_annotations_and_mementos(
            "target",
            td.path(),
            &mint,
            &prove,
            &annotations,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect("scoreboard");
        let rendered = serde_json::to_value(&scoreboard).expect("scoreboard json");
        let row = &rendered["panicCensus"][0];

        assert_eq!(row["category"], "D-lib");
        assert!(
            row.get("callsiteBundleCid").is_none(),
            "self-check panicCensus must not expose prove-row bundle metadata"
        );
    }

    #[test]
    fn panic_census_preserves_bundle_scoped_duplicate_sites_for_runtime_join() {
        let td = tempfile::tempdir().expect("tempdir");
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "rows": [
                panic_row_with_bundle(
                    "blake3-512:bundle-a",
                    "src/lib.rs",
                    25,
                    "method:unwrap",
                    "undecidable",
                    None
                ),
                panic_row_with_bundle(
                    "blake3-512:bundle-b",
                    "src/lib.rs",
                    25,
                    "method:unwrap",
                    "undecidable",
                    None
                )
            ]
        });

        let scoreboard = build_scoreboard_with_runtime_annotations(
            "target",
            td.path(),
            &mint,
            &prove,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect("scoreboard");

        assert_eq!(
            scoreboard.panic_census.len(),
            2,
            "bundle-scoped panic sites must not collapse before runtime annotation join"
        );
        let bundles: std::collections::BTreeSet<_> = scoreboard
            .panic_census
            .iter()
            .filter_map(|entry| entry.callsite_bundle_cid.as_deref())
            .collect();
        assert_eq!(
            bundles,
            std::collections::BTreeSet::from(["blake3-512:bundle-a", "blake3-512:bundle-b",])
        );
    }

    #[test]
    fn runtime_doctor_annotation_drift_fails_self_check_scoreboard_build() {
        let td = tempfile::tempdir().expect("tempdir");
        write_self_check_residue_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/missing.rs"
line = 99
callee = "method:unwrap"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "stale annotation"
"#,
        );
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "rows": [panic_row("src/live.rs", 1, "method:unwrap", "undecidable", None)]
        });

        let err = build_scoreboard_with_runtime_annotations(
            "target",
            td.path(),
            &mint,
            &prove,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect_err("strict runtime annotation drift must fail");

        assert!(
            err.contains("panic annotation runtime check failed") && err.contains("src/missing.rs"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn runtime_floor_check_receives_post_scoreboard_projection() {
        let td = tempfile::tempdir().expect("tempdir");
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "totalCallsites": 1,
            "dischargeSplit": {
                "panicSafe": 0,
                "reflexive": 0,
                "vacuous": 0,
                "undecidable": 1,
                "falsePass": 0
            },
            "rows": [panic_row("src/live.rs", 1, "method:unwrap", "undecidable", None)]
        });
        let scoreboard = build_scoreboard_with_runtime_annotations(
            "target",
            td.path(),
            &mint,
            &prove,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect("scoreboard");

        let signals = floor_signals_from_scoreboard(&scoreboard, &prove);

        assert_eq!(signals.silently_dropped, 0);
        assert_eq!(signals.false_pass, 0);
        assert_eq!(signals.dropped_sites_count, 0);
        assert_eq!(signals.panic_census_unnamed_count, 1);
        assert_eq!(signals.total_callsites, 1);
        assert!(signals.discharge_split_present);
    }

    #[test]
    fn runtime_floor_check_fails_self_check_on_hard_floor_violation() {
        let td = tempfile::tempdir().expect("tempdir");
        let mint = mint_json_with_diagnostics(vec![]);
        let prove = json!({
            "totalCallsites": 1,
            "dischargeSplit": {
                "panicSafe": 0,
                "reflexive": 1,
                "vacuous": 0,
                "undecidable": 0,
                "falsePass": 1
            },
            "rows": [panic_row("src/live.rs", 1, "method:unwrap", "discharged", Some("reflexive"))]
        });
        let scoreboard = build_scoreboard_with_runtime_annotations(
            "target",
            td.path(),
            &mint,
            &prove,
            crate::panic_annotations_runtime::AnnotationCheckMode::Strict,
        )
        .expect("scoreboard");

        let err = enforce_floor_runtime_checks(&scoreboard, &prove)
            .expect_err("falsePass must fail the runtime floor");

        assert!(
            err.contains("floor runtime check failed") && err.contains("floor.false_pass.zero"),
            "unexpected error: {err}"
        );
    }
}
