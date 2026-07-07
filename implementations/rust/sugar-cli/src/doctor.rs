// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar doctor: validate a kit's config/manifest wiring up front.
//
// Catches the manifest-path footgun (a declared plugin command pointing at a
// binary that does not exist) BEFORE it silently produces an empty-set
// attestation. Every failure is loud, named, and counted. No language
// semantics embedded here: doctor is language-blind and validates generic kit
// wiring only.
//
// Checks performed:
//   1. (HARD) config.toml and all manifest TOML files parse as valid TOML.
//   2. (HARD) For each declared plugin command, the binary EXISTS and is
//      executable, resolved the same way mint does: relative to the plugin's
//      working dir when the command contains a path separator; via PATH when
//      the command is a bare name.
//   3. (WARN) .sugar/imports/ file count -- zero is a warning when the kit
//      declares plugins with a non-trivial surface list.
//   4. (MODE-AWARE) When an oracle host is requested, check that it is
//      requested, locatable, ready, engaged, and convergence-accounted.
//
// Exit codes:
//   0   all checks passed (warnings may be present)
//   2   at least one HARD check failed

use std::collections::BTreeSet;
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use clap::ValueEnum;
use serde_json::{json, Value};
use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::proof_filename;
use sugar_verifier::load_all_proofs::ProofBytes;

use crate::doctor_oracle::{
    OracleHostAdapter, OracleHostEngagement, OracleHostEnv, OracleHostLocatability,
    OracleHostObservation, OracleHostReadiness, OracleResolutionConvergence,
    RustAnalyzerOracleAdapter,
};
use crate::floor_runtime_check::{
    floor_runtime_check, FloorCheckMode, FloorCheckSeverity, FloorCheckStatus, FloorRuntimeCheck,
    FloorSignals,
};
use crate::lift_plugin::{parse_manifest_at, resolved_working_dir_for};
use crate::project_config::{read_project_config, PluginEntry};

/// Status of one doctor check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckStatus {
    Pass,
    Warn,
    Fail,
}

impl CheckStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            CheckStatus::Pass => "pass",
            CheckStatus::Warn => "warn",
            CheckStatus::Fail => "fail",
        }
    }
}

/// Severity of one doctor check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckSeverity {
    Advisory,
    Hard,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum DoctorMode {
    Structural,
    Strict,
    #[value(name = "releaseGate")]
    ReleaseGate,
}

impl DoctorMode {
    pub fn as_str(self) -> &'static str {
        match self {
            DoctorMode::Structural => "structural",
            DoctorMode::Strict => "strict",
            DoctorMode::ReleaseGate => "releaseGate",
        }
    }
}

impl std::fmt::Display for DoctorMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DoctorContext {
    pub mode: DoctorMode,
    pub oracle_requested: bool,
}

impl DoctorContext {
    pub fn new(mode: DoctorMode) -> Self {
        Self {
            mode,
            oracle_requested: false,
        }
    }

    pub fn with_oracle_requested(mut self, oracle_requested: bool) -> Self {
        self.oracle_requested = oracle_requested;
        self
    }
}

impl Default for DoctorContext {
    fn default() -> Self {
        Self::new(DoctorMode::Structural)
    }
}

/// One check result.
#[derive(Debug, Clone)]
pub struct DoctorCheck {
    pub id: String,
    pub name: String,
    pub status: CheckStatus,
    pub severity: CheckSeverity,
    pub domain: String,
    pub detail: String,
    pub evidence: Value,
}

pub type Check = DoctorCheck;

#[derive(Debug, Clone)]
pub struct DoctorReport {
    pub target: PathBuf,
    pub mode: DoctorMode,
    pub checks: Vec<DoctorCheck>,
    pub ok: bool,
    pub release_ready: bool,
}

impl DoctorCheck {
    fn pass_with_evidence(
        name: impl Into<String>,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status(name, CheckStatus::Pass, detail, evidence)
    }
    fn warn_with_evidence(
        name: impl Into<String>,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status(name, CheckStatus::Warn, detail, evidence)
    }
    fn fail_with_evidence(
        name: impl Into<String>,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status(name, CheckStatus::Fail, detail, evidence)
    }
    fn pass_with_severity(
        name: impl Into<String>,
        severity: CheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status_and_severity(name, CheckStatus::Pass, severity, detail, evidence)
    }
    fn warn_with_severity(
        name: impl Into<String>,
        severity: CheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status_and_severity(name, CheckStatus::Warn, severity, detail, evidence)
    }
    fn fail_with_severity(
        name: impl Into<String>,
        severity: CheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status_and_severity(name, CheckStatus::Fail, severity, detail, evidence)
    }
    fn with_status(
        name: impl Into<String>,
        status: CheckStatus,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        let name = name.into();
        let detail = detail.into();
        let (id, domain, severity, evidence) = check_metadata(&name, &detail, evidence);
        Self {
            id,
            name,
            status,
            severity,
            domain,
            detail,
            evidence,
        }
    }
    fn with_status_and_severity(
        name: impl Into<String>,
        status: CheckStatus,
        severity: CheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        let name = name.into();
        let detail = detail.into();
        let (id, domain, _, evidence) = check_metadata(&name, &detail, evidence);
        Self {
            id,
            name,
            status,
            severity,
            domain,
            detail,
            evidence,
        }
    }
}

fn check_metadata(
    name: &str,
    detail: &str,
    evidence: Value,
) -> (String, String, CheckSeverity, Value) {
    let (id, domain, severity) = if name == "config-toml-parse" {
        ("kit.config.parse", "kit.config", CheckSeverity::Hard)
    } else if name.starts_with("manifest-toml-parse:") {
        ("kit.manifest.parse", "kit.manifest", CheckSeverity::Hard)
    } else if name.starts_with("binary-exists:") {
        (
            "kit.plugin.command.available",
            "kit.plugin",
            CheckSeverity::Hard,
        )
    } else if name == "imports-present" {
        (
            "proof.import_pool.present",
            "proof.import_pool",
            CheckSeverity::Advisory,
        )
    } else if name == "oracle-requested" {
        (
            "oracle.requested",
            "oracle.request",
            CheckSeverity::Advisory,
        )
    } else if name == "oracle-host-locatable" || name == "oracle-wiring" {
        (
            "oracle.host.locatable",
            "oracle.host",
            CheckSeverity::Advisory,
        )
    } else if name == "oracle-host-ready" {
        ("oracle.host.ready", "oracle.host", CheckSeverity::Advisory)
    } else if name == "oracle-host-engaged" {
        (
            "oracle.host.engaged",
            "oracle.host",
            CheckSeverity::Advisory,
        )
    } else if name == "oracle-resolution-converged" {
        (
            "oracle.resolution.converged",
            "oracle.resolution",
            CheckSeverity::Advisory,
        )
    } else if name.starts_with("consumer-wiring:") {
        (
            "kit.consumer_surface.contract",
            "kit.consumer_surface",
            CheckSeverity::Hard,
        )
    } else if name == "dependency-resolver-available" {
        (
            "proof.dependency_resolver.available",
            "proof.dependency_resolver",
            CheckSeverity::Advisory,
        )
    } else if name == "dependency-resolver-protocol" {
        (
            "proof.dependency_resolver.protocol",
            "proof.dependency_resolver",
            CheckSeverity::Advisory,
        )
    } else if name == "dependency-pool-stable" {
        (
            "proof.dependency_pool.stable",
            "proof.dependency_pool",
            CheckSeverity::Advisory,
        )
    } else if name == "dependency-pool-byte-consistent" {
        (
            "proof.dependency_pool.byte_consistent",
            "proof.dependency_pool",
            CheckSeverity::Hard,
        )
    } else {
        ("doctor.check", "doctor", CheckSeverity::Hard)
    };
    let mut evidence = if evidence.is_null() {
        json!({ "detail": detail })
    } else {
        evidence
    };
    if let Some(obj) = evidence.as_object_mut() {
        obj.insert("legacyName".to_string(), Value::String(name.to_string()));
    }
    (id.to_string(), domain.to_string(), severity, evidence)
}

pub fn run_report(kit_dir: &Path) -> DoctorReport {
    let checks = run_checks(kit_dir);
    report_from_checks(kit_dir, DoctorMode::Structural, checks)
}

pub fn run_report_with_context(kit_dir: &Path, context: DoctorContext) -> DoctorReport {
    if context.mode == DoctorMode::Structural && !context.oracle_requested {
        return run_report(kit_dir);
    }
    let checks = run_checks_with_context(kit_dir, context);
    report_from_checks(kit_dir, context.mode, checks)
}

#[cfg(test)]
fn run_report_with_context_and_dependency_resolver<F>(
    kit_dir: &Path,
    context: DoctorContext,
    resolver: F,
) -> DoctorReport
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
{
    let checks = run_checks_with_context_and_dependency_resolver(kit_dir, context, resolver);
    report_from_checks(kit_dir, context.mode, checks)
}

#[cfg(test)]
fn run_report_with_context_and_oracle_adapter<A>(
    kit_dir: &Path,
    context: DoctorContext,
    adapter: A,
) -> DoctorReport
where
    A: OracleHostAdapter,
{
    let checks = run_checks_with_context_and_dependency_resolver_and_oracle_adapter(
        kit_dir,
        context,
        crate::kit_dispatch::dependency_proofs_via_rpc,
        &adapter,
    );
    report_from_checks(kit_dir, context.mode, checks)
}

fn report_from_checks(kit_dir: &Path, mode: DoctorMode, checks: Vec<DoctorCheck>) -> DoctorReport {
    let ok = !checks.iter().any(|c| c.status == CheckStatus::Fail);
    DoctorReport {
        target: kit_dir.to_path_buf(),
        mode,
        release_ready: ok && mode == DoctorMode::ReleaseGate,
        checks,
        ok,
    }
}

pub fn report_from_floor_signals(
    kit_dir: &Path,
    mode: DoctorMode,
    signals: FloorSignals,
) -> DoctorReport {
    let floor_checks = floor_runtime_check(signals, floor_mode_from_doctor_mode(mode));
    let checks = floor_checks
        .into_iter()
        .map(doctor_check_from_floor_runtime)
        .collect();
    report_from_checks(kit_dir, mode, checks)
}

fn floor_mode_from_doctor_mode(mode: DoctorMode) -> FloorCheckMode {
    match mode {
        DoctorMode::Structural => FloorCheckMode::Structural,
        DoctorMode::Strict => FloorCheckMode::Strict,
        DoctorMode::ReleaseGate => FloorCheckMode::ReleaseGate,
    }
}

fn doctor_check_from_floor_runtime(check: FloorRuntimeCheck) -> DoctorCheck {
    DoctorCheck {
        id: check.id,
        name: check.name,
        status: match check.status {
            FloorCheckStatus::Pass => CheckStatus::Pass,
            FloorCheckStatus::Warn => CheckStatus::Warn,
            FloorCheckStatus::Fail => CheckStatus::Fail,
        },
        severity: match check.severity {
            FloorCheckSeverity::Advisory => CheckSeverity::Advisory,
            FloorCheckSeverity::Hard => CheckSeverity::Hard,
        },
        domain: check.domain,
        detail: check.detail,
        evidence: check.evidence,
    }
}

/// Run all checks against the target kit directory.
/// Pure function: suitable for testing without CLI overhead.
pub fn run_checks(kit_dir: &Path) -> Vec<Check> {
    run_checks_with_context(kit_dir, DoctorContext::default())
}

pub fn run_checks_with_context(kit_dir: &Path, context: DoctorContext) -> Vec<Check> {
    run_checks_with_context_and_dependency_resolver(
        kit_dir,
        context,
        crate::kit_dispatch::dependency_proofs_via_rpc,
    )
}

fn run_checks_with_context_and_dependency_resolver<F>(
    kit_dir: &Path,
    context: DoctorContext,
    resolver: F,
) -> Vec<Check>
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
{
    run_checks_with_context_and_dependency_resolver_and_oracle_adapter(
        kit_dir,
        context,
        resolver,
        &RustAnalyzerOracleAdapter,
    )
}

fn run_checks_with_context_and_dependency_resolver_and_oracle_adapter<F, A>(
    kit_dir: &Path,
    context: DoctorContext,
    resolver: F,
    oracle_adapter: &A,
) -> Vec<Check>
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
    A: OracleHostAdapter + ?Sized,
{
    let mut checks: Vec<Check> = Vec::new();

    // --- Check 1: config.toml and all manifest TOML files parse as valid TOML.
    let config_path = kit_dir.join(".sugar/config.toml");
    match std::fs::read_to_string(&config_path) {
        Err(e) => {
            checks.push(Check::fail_with_evidence(
                "config-toml-parse",
                format!("cannot read {}: {e}", config_path.display()),
                json!({"path": config_path.display().to_string()}),
            ));
            // Cannot enumerate plugins without a config; stop here.
            return checks;
        }
        Ok(text) => match text.parse::<toml::Value>() {
            Err(e) => {
                checks.push(Check::fail_with_evidence(
                    "config-toml-parse",
                    format!("{}: invalid TOML: {e}", config_path.display()),
                    json!({"path": config_path.display().to_string()}),
                ));
                // Config invalid; cannot enumerate plugins.
                return checks;
            }
            Ok(_) => {
                checks.push(Check::pass_with_evidence(
                    "config-toml-parse",
                    format!("{} parses as valid TOML", config_path.display()),
                    json!({"path": config_path.display().to_string()}),
                ));
            }
        },
    }

    // Load the structured config for plugin enumeration.
    let config = read_project_config(kit_dir);

    // Enumerate manifest TOML files for all declared plugins (check 1 continued).
    // Map: (surface, kind) -> manifest dir name ("lift", "realize", "emit").
    let manifest_entries = collect_manifest_entries(kit_dir, &config.plugins);
    for (surface, kind_dir, manifest_path) in &manifest_entries {
        let check_name = format!("manifest-toml-parse:{kind_dir}:{surface}");
        match std::fs::read_to_string(manifest_path) {
            Err(e) => {
                checks.push(Check::fail_with_evidence(
                    &check_name,
                    format!("cannot read {}: {e}", manifest_path.display()),
                    json!({
                        "kind": kind_dir,
                        "surface": surface,
                        "path": manifest_path.display().to_string(),
                    }),
                ));
            }
            Ok(text) => match text.parse::<toml::Value>() {
                Err(e) => {
                    checks.push(Check::fail_with_evidence(
                        &check_name,
                        format!("{}: invalid TOML: {e}", manifest_path.display()),
                        json!({
                            "kind": kind_dir,
                            "surface": surface,
                            "path": manifest_path.display().to_string(),
                        }),
                    ));
                }
                Ok(_) => {
                    checks.push(Check::pass_with_evidence(
                        &check_name,
                        format!("{} parses as valid TOML", manifest_path.display()),
                        json!({
                            "kind": kind_dir,
                            "surface": surface,
                            "path": manifest_path.display().to_string(),
                        }),
                    ));
                }
            },
        }
    }

    // --- Check 2: binary existence for each declared plugin.
    for (surface, kind_dir, manifest_path) in &manifest_entries {
        let check_name = format!("binary-exists:{kind_dir}:{surface}");
        let manifest = match parse_manifest_at(manifest_path) {
            Err(e) => {
                checks.push(Check::fail_with_evidence(
                    &check_name,
                    format!("cannot parse manifest: {e}"),
                    json!({
                        "kind": kind_dir,
                        "surface": surface,
                        "path": manifest_path.display().to_string(),
                    }),
                ));
                continue;
            }
            Ok(m) => m,
        };
        if manifest.command.is_empty() {
            checks.push(Check::fail_with_evidence(
                &check_name,
                format!("manifest {} declares no command", manifest_path.display()),
                json!({
                    "kind": kind_dir,
                    "surface": surface,
                    "path": manifest_path.display().to_string(),
                }),
            ));
            continue;
        }

        let cmd0 = &manifest.command[0];
        let resolved_wd = resolved_working_dir_for(kit_dir, &manifest);

        match resolve_binary(cmd0, resolved_wd.as_deref()) {
            BinaryResolution::Found(abs) => {
                checks.push(Check::pass_with_evidence(
                    &check_name,
                    format!(
                        "surface={surface} command={cmd0:?} -> {} (executable)",
                        abs.display()
                    ),
                    json!({
                        "kind": kind_dir,
                        "surface": surface,
                        "path": manifest_path.display().to_string(),
                        "command": cmd0,
                        "resolvedPath": abs.display().to_string(),
                    }),
                ));
            }
            BinaryResolution::NotFound { resolved_path } => {
                let fix = binary_fix_hint(cmd0, resolved_wd.as_deref(), kit_dir);
                checks.push(Check::fail_with_evidence(
                    &check_name,
                    format!(
                        "surface={surface} command={cmd0:?}: binary not found at {}. {fix}",
                        resolved_path
                    ),
                    json!({
                        "kind": kind_dir,
                        "surface": surface,
                        "path": manifest_path.display().to_string(),
                        "command": cmd0,
                        "resolvedPath": resolved_path,
                    }),
                ));
            }
            BinaryResolution::NotExecutable { abs } => {
                checks.push(Check::fail_with_evidence(
                    &check_name,
                    format!(
                        "surface={surface} command={cmd0:?}: file exists at {} but is not executable",
                        abs.display()
                    ),
                    json!({
                        "kind": kind_dir,
                        "surface": surface,
                        "path": manifest_path.display().to_string(),
                        "command": cmd0,
                        "resolvedPath": abs.display().to_string(),
                    }),
                ));
            }
        }
    }

    // --- Check 3: .sugar/imports/ file count (advisory).
    let imports_dir = kit_dir.join(".sugar/imports");
    let imports_check = check_imports(&imports_dir, &config.plugins);
    checks.push(imports_check);

    // --- Check 4: oracle host readiness.
    checks.extend(run_oracle_host_checks_with_adapter(context, oracle_adapter));

    // --- Check 5: consumer-surface method/phase wiring (HARD).
    // The manifest method/phase omission footgun: a consumer surface
    // (e.g. rust-implications) whose manifest omits `method`/`phase` silently
    // runs the default `lift` PRODUCER method, so its pass never fires and the
    // mint emits a degenerate attestation with no error. Five investigations
    // on 2026-05-31 lost a day to exactly this. The plugin SELF-DECLARES which
    // surfaces are consumers and what (method, phase) they require (via the
    // `initialize` capabilities) so this stays language-blind: doctor reads the
    // requirement from the kit's own plugin, not a hard-coded CLI table.
    for (surface, kind_dir, manifest_path) in &manifest_entries {
        let check_name = format!("consumer-wiring:{kind_dir}:{surface}");
        let manifest = match parse_manifest_at(manifest_path) {
            Ok(m) => m,
            Err(_) => continue, // already reported by checks 1/2
        };
        let resolved_wd = resolved_working_dir_for(kit_dir, &manifest);
        let consumer_reqs = match plugin_consumer_surfaces(&manifest, resolved_wd.as_deref()) {
            Ok(c) => c,
            Err(e) => {
                checks.push(Check::warn_with_evidence(
                    &check_name,
                    format!("could not query plugin capabilities for {surface}: {e}"),
                    json!({
                        "kind": kind_dir,
                        "surface": surface,
                        "path": manifest_path.display().to_string(),
                    }),
                ));
                continue;
            }
        };
        let Some(req) = consumer_reqs.get(surface.as_str()) else {
            // Not a consumer surface per the plugin: nothing to enforce.
            continue;
        };
        let method_ok = manifest.method.as_deref() == Some(req.0.as_str());
        let phase_ok = manifest.phase.as_deref() == Some(req.1.as_str());
        if method_ok && phase_ok {
            checks.push(Check::pass_with_evidence(
                &check_name,
                format!(
                    "consumer surface {surface} correctly wired (method={}, phase={})",
                    req.0, req.1
                ),
                json!({
                    "kind": kind_dir,
                    "surface": surface,
                    "path": manifest_path.display().to_string(),
                    "method": manifest.method,
                    "phase": manifest.phase,
                    "requiredMethod": req.0,
                    "requiredPhase": req.1,
                }),
            ));
        } else {
            checks.push(Check::fail_with_evidence(
                &check_name,
                format!(
                    "consumer surface {surface} is mis-wired: manifest {} has method={:?} phase={:?} \
                     but the plugin requires method=\"{}\" phase=\"{}\". Without these the surface \
                     silently runs the default `lift` producer and its pass never fires (degenerate \
                     attestation, no error). Add both lines to the manifest.",
                    manifest_path.display(),
                    manifest.method,
                    manifest.phase,
                    req.0,
                    req.1,
                ),
                json!({
                    "kind": kind_dir,
                    "surface": surface,
                    "path": manifest_path.display().to_string(),
                    "method": manifest.method,
                    "phase": manifest.phase,
                    "requiredMethod": req.0,
                    "requiredPhase": req.1,
                }),
            ));
        }
    }

    checks.extend(run_dependency_proof_checks_with_resolver(
        kit_dir, context, resolver,
    ));
    checks
}

pub(crate) fn oracle_requested_from_env() -> bool {
    std::env::var("SUGAR_RESOLVE_ORACLE")
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false)
}

fn run_oracle_host_checks_with_adapter<A>(context: DoctorContext, adapter: &A) -> Vec<Check>
where
    A: OracleHostAdapter + ?Sized,
{
    let env = OracleHostEnv {
        requested: context.oracle_requested,
    };
    let observation = if env.requested {
        adapter.observe(&env)
    } else {
        OracleHostObservation::not_requested()
    };

    vec![
        oracle_requested_check(&env, &observation),
        oracle_locatable_check(context.mode, &env, &observation),
        oracle_ready_check(context.mode, &env, &observation),
        oracle_engaged_check(&env, &observation),
        oracle_converged_check(&env, &observation),
    ]
}

fn not_requested_oracle_check(name: &str) -> Check {
    Check::pass_with_severity(
        name,
        CheckSeverity::Advisory,
        "oracle not requested",
        json!({"requested": false}),
    )
}

fn oracle_requested_check(env: &OracleHostEnv, observation: &OracleHostObservation) -> Check {
    if !env.requested {
        return not_requested_oracle_check("oracle-requested");
    }
    Check::pass_with_severity(
        "oracle-requested",
        CheckSeverity::Advisory,
        format!("oracle host requested ({})", observation.host),
        json!({
            "requested": true,
            "host": observation.host.as_str(),
        }),
    )
}

fn oracle_locatable_check(
    mode: DoctorMode,
    env: &OracleHostEnv,
    observation: &OracleHostObservation,
) -> Check {
    if !env.requested {
        return not_requested_oracle_check("oracle-host-locatable");
    }
    match &observation.locatability {
        OracleHostLocatability::NotRequested => not_requested_oracle_check("oracle-host-locatable"),
        OracleHostLocatability::Found {
            host_binary,
            rust_analyzer_binary,
            discovery,
        } => Check::pass_with_severity(
            "oracle-host-locatable",
            CheckSeverity::Advisory,
            format!("oracle host {} is locatable", observation.host),
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "locatable": true,
                "hostBinary": host_binary,
                "rustAnalyzerBinary": rust_analyzer_binary,
                "discovery": discovery,
            }),
        ),
        OracleHostLocatability::Missing { missing, detail } => {
            let (status, severity) = requested_oracle_missing_policy(mode);
            Check::with_status_and_severity(
                "oracle-host-locatable",
                status,
                severity,
                detail,
                json!({
                    "requested": true,
                    "host": observation.host.as_str(),
                    "locatable": false,
                    "missing": missing,
                }),
            )
        }
    }
}

fn oracle_ready_check(
    mode: DoctorMode,
    env: &OracleHostEnv,
    observation: &OracleHostObservation,
) -> Check {
    if !env.requested {
        return not_requested_oracle_check("oracle-host-ready");
    }
    match &observation.readiness {
        OracleHostReadiness::NotRequested => not_requested_oracle_check("oracle-host-ready"),
        OracleHostReadiness::Ready { detail } => Check::pass_with_severity(
            "oracle-host-ready",
            CheckSeverity::Advisory,
            detail,
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "ready": true,
                "degraded": false,
            }),
        ),
        OracleHostReadiness::Degraded { detail } => Check::warn_with_severity(
            "oracle-host-ready",
            CheckSeverity::Advisory,
            detail,
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "ready": true,
                "degraded": true,
            }),
        ),
        OracleHostReadiness::NotReady { detail } => {
            let (status, severity) = requested_oracle_missing_policy(mode);
            Check::with_status_and_severity(
                "oracle-host-ready",
                status,
                severity,
                detail,
                json!({
                    "requested": true,
                    "host": observation.host.as_str(),
                    "ready": false,
                    "degraded": false,
                }),
            )
        }
    }
}

fn oracle_engaged_check(env: &OracleHostEnv, observation: &OracleHostObservation) -> Check {
    if !env.requested {
        return not_requested_oracle_check("oracle-host-engaged");
    }
    match &observation.engagement {
        OracleHostEngagement::NotRequested => not_requested_oracle_check("oracle-host-engaged"),
        OracleHostEngagement::Engaged { detail } => Check::pass_with_severity(
            "oracle-host-engaged",
            CheckSeverity::Advisory,
            detail,
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "engaged": true,
            }),
        ),
        OracleHostEngagement::Unknown { detail } => Check::warn_with_severity(
            "oracle-host-engaged",
            CheckSeverity::Advisory,
            detail,
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "engaged": Value::Null,
            }),
        ),
    }
}

fn oracle_converged_check(env: &OracleHostEnv, observation: &OracleHostObservation) -> Check {
    if !env.requested {
        return not_requested_oracle_check("oracle-resolution-converged");
    }
    match &observation.convergence {
        OracleResolutionConvergence::NotRequested => {
            not_requested_oracle_check("oracle-resolution-converged")
        }
        OracleResolutionConvergence::Deferred { detail } => Check::pass_with_severity(
            "oracle-resolution-converged",
            CheckSeverity::Advisory,
            detail,
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "converged": Value::Null,
            }),
        ),
        OracleResolutionConvergence::Converged { detail } => Check::pass_with_severity(
            "oracle-resolution-converged",
            CheckSeverity::Advisory,
            detail,
            json!({
                "requested": true,
                "host": observation.host.as_str(),
                "converged": true,
            }),
        ),
    }
}

fn requested_oracle_missing_policy(mode: DoctorMode) -> (CheckStatus, CheckSeverity) {
    match mode {
        DoctorMode::Structural => (CheckStatus::Warn, CheckSeverity::Advisory),
        DoctorMode::Strict | DoctorMode::ReleaseGate => (CheckStatus::Fail, CheckSeverity::Hard),
    }
}

struct DependencyResolverInfo {
    kind: String,
    surface: String,
    manifest_path: PathBuf,
    command: String,
    resolved_path: Option<String>,
    unavailable_reason: Option<String>,
}

#[derive(Debug, Clone, Eq)]
struct DependencyProofFingerprint {
    derived_cid: String,
    byte_hash: String,
    byte_length: usize,
    label: String,
}

impl PartialEq for DependencyProofFingerprint {
    fn eq(&self, other: &Self) -> bool {
        self.derived_cid == other.derived_cid
            && self.byte_hash == other.byte_hash
            && self.byte_length == other.byte_length
    }
}

impl PartialOrd for DependencyProofFingerprint {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for DependencyProofFingerprint {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        (&self.derived_cid, &self.byte_hash, self.byte_length).cmp(&(
            &other.derived_cid,
            &other.byte_hash,
            other.byte_length,
        ))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DependencyProofPool {
    present: bool,
    proofs: Vec<DependencyProofFingerprint>,
}

fn run_dependency_proof_checks_with_resolver<F>(
    kit_dir: &Path,
    context: DoctorContext,
    resolver: F,
) -> Vec<Check>
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
{
    run_dependency_proof_checks_with_pass_hook(kit_dir, context, resolver, |_, _| {})
}

fn run_dependency_proof_checks_with_pass_hook<F, H>(
    kit_dir: &Path,
    context: DoctorContext,
    mut resolver: F,
    mut pass_hook: H,
) -> Vec<Check>
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
    H: FnMut(usize, &Path),
{
    let mut checks = Vec::new();
    let resolver_info = match dependency_resolver_info(kit_dir) {
        Ok(info) => info,
        Err(error) => {
            checks.push(Check::fail_with_severity(
                "dependency-resolver-available",
                CheckSeverity::Hard,
                format!("could not inspect dependency proof resolver config: {error}"),
                json!({"error": error}),
            ));
            return checks;
        }
    };

    let Some(info) = resolver_info else {
        checks.push(Check::pass_with_severity(
            "dependency-resolver-available",
            CheckSeverity::Advisory,
            "no dependency proof resolver configured",
            json!({"configured": false}),
        ));
        checks.push(pool_stable_structural_check(kit_dir));
        return checks;
    };

    let configured_evidence = json!({
        "configured": true,
        "kind": info.kind,
        "surface": info.surface,
        "path": info.manifest_path.display().to_string(),
        "command": info.command,
        "resolvedPath": info.resolved_path,
        "reason": info.unavailable_reason,
    });
    if let Some(reason) = &info.unavailable_reason {
        let (status, severity) = match context.mode {
            DoctorMode::Structural => (CheckStatus::Warn, CheckSeverity::Advisory),
            DoctorMode::Strict | DoctorMode::ReleaseGate => {
                (CheckStatus::Fail, CheckSeverity::Hard)
            }
        };
        checks.push(Check::with_status_and_severity(
            "dependency-resolver-available",
            status,
            severity,
            format!("dependency proof resolver unavailable: {reason}"),
            configured_evidence,
        ));
        if context.mode == DoctorMode::Structural {
            checks.push(pool_stable_structural_check(kit_dir));
        }
        return checks;
    }

    checks.push(Check::pass_with_severity(
        "dependency-resolver-available",
        CheckSeverity::Advisory,
        "dependency proof resolver is locatable",
        configured_evidence,
    ));

    match context.mode {
        DoctorMode::Structural => {
            checks.push(pool_stable_structural_check(kit_dir));
        }
        DoctorMode::Strict => {
            checks.push(strict_dependency_pool_check(kit_dir, &mut resolver));
        }
        DoctorMode::ReleaseGate => {
            checks.push(release_gate_dependency_pool_check(
                kit_dir,
                &mut resolver,
                &mut pass_hook,
            ));
        }
    }

    checks
}

fn dependency_resolver_info(kit_dir: &Path) -> Result<Option<DependencyResolverInfo>, String> {
    let config = read_project_config(kit_dir);
    let manifest_entries = collect_manifest_entries(kit_dir, &config.plugins);
    let Some((surface, kind, manifest_path)) = manifest_entries.into_iter().next() else {
        return Ok(None);
    };
    let manifest = parse_manifest_at(&manifest_path)
        .map_err(|e| format!("parse {}: {e}", manifest_path.display()))?;
    let Some(command) = manifest.command.first().cloned() else {
        return Ok(Some(DependencyResolverInfo {
            kind,
            surface,
            manifest_path,
            command: String::new(),
            resolved_path: None,
            unavailable_reason: Some("manifest declares no command".to_string()),
        }));
    };
    let resolved_wd = resolved_working_dir_for(kit_dir, &manifest);
    let (resolved_path, unavailable_reason) = match resolve_binary(&command, resolved_wd.as_deref())
    {
        BinaryResolution::Found(path) => (Some(path.display().to_string()), None),
        BinaryResolution::NotFound { resolved_path } => (
            Some(resolved_path.clone()),
            Some(format!("binary not found at {resolved_path}")),
        ),
        BinaryResolution::NotExecutable { abs } => (
            Some(abs.display().to_string()),
            Some(format!(
                "binary exists at {} but is not executable",
                abs.display()
            )),
        ),
    };
    Ok(Some(DependencyResolverInfo {
        kind,
        surface,
        manifest_path,
        command,
        resolved_path,
        unavailable_reason,
    }))
}

fn pool_stable_structural_check(kit_dir: &Path) -> Check {
    match proof_pool_from_imports(kit_dir) {
        Ok(pool) if !pool.present => Check::pass_with_severity(
            "dependency-pool-stable",
            CheckSeverity::Advisory,
            "no pool yet: .sugar/imports/ is absent",
            proof_pool_evidence(&pool),
        ),
        Ok(pool) => Check::pass_with_severity(
            "dependency-pool-stable",
            CheckSeverity::Advisory,
            format!(
                "current dependency proof pool fingerprint: {} proof(s)",
                pool.proofs.len()
            ),
            proof_pool_evidence(&pool),
        ),
        Err(error) => Check::warn_with_severity(
            "dependency-pool-stable",
            CheckSeverity::Advisory,
            format!("could not fingerprint dependency proof pool: {error}"),
            json!({"error": error}),
        ),
    }
}

fn strict_dependency_pool_check<F>(kit_dir: &Path, resolver: &mut F) -> Check
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
{
    let pool = match proof_pool_from_imports(kit_dir) {
        Ok(pool) => pool,
        Err(error) => {
            return Check::fail_with_severity(
                "dependency-pool-stable",
                CheckSeverity::Hard,
                format!("could not fingerprint dependency proof pool: {error}"),
                json!({"error": error}),
            );
        }
    };
    let staged = match resolver(kit_dir).and_then(proof_pool_from_rpc_proofs) {
        Ok(staged) => staged,
        Err(error) => {
            return Check::fail_with_severity(
                "dependency-resolver-protocol",
                CheckSeverity::Hard,
                format!("dependency proof resolver protocol failed: {error}"),
                json!({"error": error}),
            );
        }
    };
    if pool.proofs == staged.proofs {
        return Check::pass_with_severity(
            "dependency-pool-stable",
            CheckSeverity::Hard,
            "dependency proof pool matches resolver-staged proof set",
            json!({
                "pool": proof_pool_evidence(&pool),
                "staged": proof_pool_evidence(&staged),
                "proofs": proof_entries_json(&pool.proofs),
            }),
        );
    }
    Check::fail_with_severity(
        "dependency-pool-stable",
        CheckSeverity::Hard,
        "dependency proof pool differs from resolver-staged proof set",
        pool_diff_evidence("pool_vs_staged", &pool.proofs, &staged.proofs),
    )
}

fn release_gate_dependency_pool_check<F, H>(
    kit_dir: &Path,
    resolver: &mut F,
    pass_hook: &mut H,
) -> Check
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
    H: FnMut(usize, &Path),
{
    let scratch = std::env::temp_dir().join(format!(
        "sugar-doctor-dep-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    ));
    let pass1 = scratch.join("pass1");
    let pass2 = scratch.join("pass2");
    let pass1_before = match stage_dependency_proof_pass(kit_dir, &pass1, resolver) {
        Ok(pool) => pool,
        Err(error) => {
            let _ = fs::remove_dir_all(&scratch);
            return Check::fail_with_severity(
                "dependency-pool-byte-consistent",
                CheckSeverity::Hard,
                format!("dependency proof release gate pass 1 failed: {error}"),
                json!({"error": error, "pass": 1}),
            );
        }
    };
    pass_hook(1, &pass1);
    let pass1_after = match proof_pool_from_dir(&pass1) {
        Ok(pool) => pool,
        Err(error) => {
            let _ = fs::remove_dir_all(&scratch);
            return Check::fail_with_severity(
                "dependency-pool-byte-consistent",
                CheckSeverity::Hard,
                format!("dependency proof release gate pass 1 rescan failed: {error}"),
                json!({"error": error, "pass": 1}),
            );
        }
    };
    let pass2_before = match stage_dependency_proof_pass(kit_dir, &pass2, resolver) {
        Ok(pool) => pool,
        Err(error) => {
            let _ = fs::remove_dir_all(&scratch);
            return Check::fail_with_severity(
                "dependency-pool-byte-consistent",
                CheckSeverity::Hard,
                format!("dependency proof release gate pass 2 failed: {error}"),
                json!({"error": error, "pass": 2}),
            );
        }
    };
    pass_hook(2, &pass2);
    let pass2_after = match proof_pool_from_dir(&pass2) {
        Ok(pool) => pool,
        Err(error) => {
            let _ = fs::remove_dir_all(&scratch);
            return Check::fail_with_severity(
                "dependency-pool-byte-consistent",
                CheckSeverity::Hard,
                format!("dependency proof release gate pass 2 rescan failed: {error}"),
                json!({"error": error, "pass": 2}),
            );
        }
    };
    let _ = fs::remove_dir_all(&scratch);

    if pass1_after.proofs == pass2_after.proofs && pass1_before.proofs == pass1_after.proofs {
        return Check::pass_with_severity(
            "dependency-pool-byte-consistent",
            CheckSeverity::Hard,
            "dependency proof release gate produced byte-identical proof sets",
            json!({
                "proofs": proof_entries_json(&pass1_after.proofs),
                "pass1": proof_pool_evidence(&pass1_after),
                "pass2": proof_pool_evidence(&pass2_after),
            }),
        );
    }

    let drift_kind =
        if pass1_before.proofs != pass1_after.proofs || pass2_before.proofs != pass2_after.proofs {
            "between_passes_mutation"
        } else {
            "resolver_nondeterminism"
        };
    Check::fail_with_severity(
        "dependency-pool-byte-consistent",
        CheckSeverity::Hard,
        "dependency proof release gate produced divergent proof bytes",
        pool_diff_evidence(drift_kind, &pass1_after.proofs, &pass2_after.proofs),
    )
}

fn stage_dependency_proof_pass<F>(
    kit_dir: &Path,
    dest: &Path,
    resolver: &mut F,
) -> Result<DependencyProofPool, String>
where
    F: FnMut(&Path) -> Result<Vec<ProofBytes>, String>,
{
    fs::create_dir_all(dest).map_err(|e| format!("mkdir {}: {e}", dest.display()))?;
    let proofs = resolver(kit_dir)?;
    for proof in proofs {
        let fingerprint = fingerprint_bytes(proof.label.clone(), &proof.bytes);
        if proof.expected_cid.as_ref() != fingerprint.derived_cid.as_str() {
            return Err(format!(
                "dependency proof CID mismatch: expected {}, derived {}",
                proof.expected_cid, fingerprint.derived_cid
            ));
        }
        fs::write(
            dest.join(proof_filename(&fingerprint.derived_cid)),
            &proof.bytes,
        )
        .map_err(|e| {
            format!(
                "write staged dependency proof {}: {e}",
                fingerprint.derived_cid
            )
        })?;
    }
    proof_pool_from_dir(dest)
}

fn proof_pool_from_imports(kit_dir: &Path) -> Result<DependencyProofPool, String> {
    proof_pool_from_dir(&kit_dir.join(".sugar/imports"))
}

fn proof_pool_from_dir(path: &Path) -> Result<DependencyProofPool, String> {
    if !path.exists() {
        return Ok(DependencyProofPool {
            present: false,
            proofs: Vec::new(),
        });
    }
    let mut proofs = Vec::new();
    for entry in fs::read_dir(path).map_err(|e| format!("read {}: {e}", path.display()))? {
        let entry = entry.map_err(|e| format!("read {} entry: {e}", path.display()))?;
        if entry.path().extension() == Some(OsStr::new("proof")) {
            let label = entry.file_name().to_string_lossy().to_string();
            let bytes = fs::read(entry.path())
                .map_err(|e| format!("read {}: {e}", entry.path().display()))?;
            proofs.push(fingerprint_bytes(label, &bytes));
        }
    }
    proofs.sort();
    proofs.dedup();
    Ok(DependencyProofPool {
        present: true,
        proofs,
    })
}

fn proof_pool_from_rpc_proofs(proofs: Vec<ProofBytes>) -> Result<DependencyProofPool, String> {
    let mut fingerprints = Vec::new();
    for proof in proofs {
        let fingerprint = fingerprint_bytes(proof.label, &proof.bytes);
        if proof.expected_cid.as_ref() != fingerprint.derived_cid.as_str() {
            return Err(format!(
                "dependency proof CID mismatch: expected {}, derived {}",
                proof.expected_cid, fingerprint.derived_cid
            ));
        }
        fingerprints.push(fingerprint);
    }
    fingerprints.sort();
    fingerprints.dedup();
    Ok(DependencyProofPool {
        present: true,
        proofs: fingerprints,
    })
}

fn fingerprint_bytes(label: String, bytes: &[u8]) -> DependencyProofFingerprint {
    let byte_hash = blake3_512_of(bytes);
    DependencyProofFingerprint {
        derived_cid: byte_hash.clone(),
        byte_hash,
        byte_length: bytes.len(),
        label,
    }
}

fn proof_pool_evidence(pool: &DependencyProofPool) -> Value {
    json!({
        "poolPresent": pool.present,
        "proofCount": pool.proofs.len(),
        "proofs": proof_entries_json(&pool.proofs),
    })
}

fn proof_entries_json(proofs: &[DependencyProofFingerprint]) -> Value {
    Value::Array(
        proofs
            .iter()
            .map(|proof| {
                json!({
                    "label": proof.label,
                    "derivedCid": proof.derived_cid,
                    "byteHash": proof.byte_hash,
                    "byteLength": proof.byte_length,
                })
            })
            .collect(),
    )
}

fn pool_diff_evidence(
    drift_kind: &str,
    first: &[DependencyProofFingerprint],
    second: &[DependencyProofFingerprint],
) -> Value {
    let first_cids = first
        .iter()
        .map(|proof| proof.derived_cid.clone())
        .collect::<BTreeSet<_>>();
    let second_cids = second
        .iter()
        .map(|proof| proof.derived_cid.clone())
        .collect::<BTreeSet<_>>();
    let first_only = first_cids
        .difference(&second_cids)
        .cloned()
        .collect::<Vec<_>>();
    let second_only = second_cids
        .difference(&first_cids)
        .cloned()
        .collect::<Vec<_>>();
    let first_byte_hash = first.first().map(|proof| proof.byte_hash.clone());
    let second_byte_hash = second.first().map(|proof| proof.byte_hash.clone());
    json!({
        "driftKind": drift_kind,
        "first": proof_entries_json(first),
        "second": proof_entries_json(second),
        "firstOnlyCids": first_only,
        "secondOnlyCids": second_only,
        "firstByteHash": first_byte_hash,
        "secondByteHash": second_byte_hash,
    })
}

/// Query a plugin's `initialize` capabilities and return its declared
/// consumer-surface requirements: `surface -> (required_method, required_phase)`.
/// Language-blind: the requirement is the PLUGIN's self-declaration, not a CLI
/// table. Spawns the plugin command, sends one `initialize` JSON-RPC line, reads
/// one response line, and parses `result.capabilities.consumer_surfaces`.
fn plugin_consumer_surfaces(
    manifest: &crate::component_plan::PlannedLiftManifest,
    working_dir: Option<&Path>,
) -> Result<std::collections::HashMap<String, (String, String)>, String> {
    use std::io::{BufRead, BufReader, Write};
    use std::process::{Command, Stdio};

    if manifest.command.is_empty() {
        return Err("manifest declares no command".into());
    }
    let mut cmd = Command::new(&manifest.command[0]);
    cmd.args(&manifest.command[1..]);
    if let Some(wd) = working_dir {
        cmd.current_dir(wd);
    }
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = cmd.spawn().map_err(|e| format!("spawn: {e}"))?;
    {
        let stdin = child.stdin.as_mut().ok_or("no stdin")?;
        let req = json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}});
        let mut line = serde_json::to_vec(&req).map_err(|e| e.to_string())?;
        line.push(b'\n');
        stdin.write_all(&line).map_err(|e| format!("write: {e}"))?;
    }
    let stdout = child.stdout.take().ok_or("no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut resp_line = String::new();
    reader
        .read_line(&mut resp_line)
        .map_err(|e| format!("read: {e}"))?;
    let _ = child.kill();
    let _ = child.wait();
    let resp: Value =
        serde_json::from_str(resp_line.trim()).map_err(|e| format!("parse response: {e}"))?;
    let mut out = std::collections::HashMap::new();
    if let Some(map) = resp
        .pointer("/result/capabilities/consumer_surfaces")
        .and_then(|v| v.as_object())
    {
        for (surface, req) in map {
            let method = req.get("method").and_then(|v| v.as_str());
            let phase = req.get("phase").and_then(|v| v.as_str());
            if let (Some(m), Some(p)) = (method, phase) {
                out.insert(surface.clone(), (m.to_string(), p.to_string()));
            }
        }
    }
    Ok(out)
}

/// Collect all (surface, kind_dir, manifest_path) triples doctor should check.
///
/// Configured plugins remain the primary entrypoint. In addition, project-local
/// lift manifests may opt into authoring-surface doctor checks by declaring
/// their authoring capability in the manifest itself. That keeps doctor
/// manifest-driven and language-blind: it reads kit-owned metadata instead of a
/// Rust-side list of known kits.
fn collect_manifest_entries(
    kit_dir: &Path,
    plugins: &[PluginEntry],
) -> Vec<(String, String, PathBuf)> {
    let mut entries = Vec::new();
    let mut seen = BTreeSet::new();
    for plugin in plugins {
        let kind_dir = plugin_kind_dir(plugin);
        let manifest_path = kit_dir
            .join(".sugar")
            .join(&kind_dir)
            .join(&plugin.surface)
            .join("manifest.toml");
        seen.insert((kind_dir.clone(), plugin.surface.clone()));
        entries.push((plugin.surface.clone(), kind_dir, manifest_path));
    }

    let lift_root = kit_dir.join(".sugar").join("lift");
    let mut authoring_entries = Vec::new();
    if let Ok(read_dir) = fs::read_dir(&lift_root) {
        for entry in read_dir.flatten() {
            let Ok(file_type) = entry.file_type() else {
                continue;
            };
            if !file_type.is_dir() {
                continue;
            }
            let surface = entry.file_name().to_string_lossy().to_string();
            if surface.is_empty() {
                continue;
            }
            let key = ("lift".to_string(), surface.clone());
            if seen.contains(&key) {
                continue;
            }
            let manifest_path = entry.path().join("manifest.toml");
            if !manifest_path.is_file() {
                continue;
            }
            if manifest_file_declares_authoring_lift_surface(&manifest_path) {
                authoring_entries.push((surface, manifest_path));
            }
        }
    }
    authoring_entries.sort_by(|left, right| left.0.cmp(&right.0));
    for (surface, manifest_path) in authoring_entries {
        let key = ("lift".to_string(), surface.clone());
        if seen.insert(key) {
            entries.push((surface, "lift".to_string(), manifest_path));
        }
    }

    entries
}

fn manifest_file_declares_authoring_lift_surface(manifest_path: &Path) -> bool {
    let Ok(text) = fs::read_to_string(manifest_path) else {
        return false;
    };
    let Ok(manifest) = text.parse::<toml::Value>() else {
        return false;
    };
    let capabilities = manifest.get("capabilities");
    manifest_authoring_surfaces_nonempty(capabilities)
        && !capability_bool(capabilities, "emits_signed_mementos").unwrap_or(false)
        && manifest.get("phase").and_then(toml::Value::as_str) != Some("consumer")
}

fn manifest_authoring_surfaces_nonempty(capabilities: Option<&toml::Value>) -> bool {
    capabilities
        .and_then(|capabilities| capabilities.get("authoring_surfaces"))
        .and_then(toml::Value::as_array)
        .is_some_and(|surfaces| {
            surfaces
                .iter()
                .any(|surface| surface.as_str().is_some_and(|surface| !surface.is_empty()))
        })
}

fn capability_bool(capabilities: Option<&toml::Value>, key: &str) -> Option<bool> {
    capabilities
        .and_then(|capabilities| capabilities.get(key))
        .and_then(toml::Value::as_bool)
}

/// Map a PluginEntry's declared kind to the manifest subdirectory name.
///
/// NOTE: `is_lift_plugin()` and `is_emit_plugin()` both return `true` when
/// `kind` is absent (legacy dual-use registration). Manifests for
/// legacy/lift plugins live under `.sugar/lift/`. Only an EXPLICIT
/// `kind = "emit"` should redirect to a different dir.
fn plugin_kind_dir(plugin: &PluginEntry) -> String {
    match plugin.kind.as_deref() {
        Some(k) if k.eq_ignore_ascii_case("emit") => "emit".to_string(),
        // Explicit "lift" or absent (legacy dual-use) -> lift dir.
        _ => "lift".to_string(),
    }
}

/// How a binary path is resolved: same logic as spawn in LiftPluginKit.
/// If command[0] contains a path separator, it is joined to the working dir
/// (the OS treats it as a relative path, not a PATH search).
/// If command[0] is a bare name (no separator), the OS PATH-searches it.
enum BinaryResolution {
    Found(PathBuf),
    NotFound { resolved_path: String },
    NotExecutable { abs: PathBuf },
}

fn resolve_binary(cmd0: &str, working_dir: Option<&Path>) -> BinaryResolution {
    if cmd0.contains('/') || std::path::Path::new(cmd0).is_absolute() {
        // Relative or absolute path: resolve against working_dir (fallback: cwd).
        let base = working_dir
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
        let abs = if Path::new(cmd0).is_absolute() {
            PathBuf::from(cmd0)
        } else {
            base.join(cmd0)
        };
        // Canonicalize to resolve `..` components cleanly for reporting.
        let canonical = abs.canonicalize().unwrap_or_else(|_| abs.clone());
        if !canonical.exists() {
            return BinaryResolution::NotFound {
                resolved_path: canonical.display().to_string(),
            };
        }
        if !is_executable(&canonical) {
            return BinaryResolution::NotExecutable { abs: canonical };
        }
        BinaryResolution::Found(canonical)
    } else {
        // Bare name: PATH search via `which`.
        match which_binary(cmd0) {
            Some(found) => BinaryResolution::Found(found),
            None => BinaryResolution::NotFound {
                resolved_path: format!("{cmd0} (searched PATH)"),
            },
        }
    }
}

fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    path.metadata()
        .map(|m| m.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

/// Locate a bare-name binary via PATH, mirroring how the OS would resolve it.
fn which_binary(name: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        let candidate = dir.join(name);
        if candidate.is_file() && is_executable(&candidate) {
            return Some(candidate);
        }
    }
    None
}

/// Produce a human-readable fix hint for a missing binary.
fn binary_fix_hint(cmd0: &str, working_dir: Option<&Path>, kit_dir: &Path) -> String {
    if cmd0.contains('/') || Path::new(cmd0).is_absolute() {
        let base = working_dir.unwrap_or(kit_dir);
        let joined = base.join(cmd0);
        // Check if this looks like a Rust debug binary path.
        if cmd0.contains("target/debug") || cmd0.contains("target/release") {
            return format!(
                "The binary has not been built yet or the path depth is wrong. \
Run `cargo build` in the Rust workspace to produce the binary, then verify \
that the `..` count in {cmd0:?} matches the kit's depth relative to the \
workspace target/ directory (resolved base: {}).",
                base.display()
            );
        }
        format!(
            "Verify the path depth in {cmd0:?} is correct relative to working_dir \
(resolved: {}). If the binary has not been built, build it first.",
            joined.display()
        )
    } else {
        format!("Install or build `{cmd0}` and ensure it is on PATH.")
    }
}

/// Check .sugar/imports/ for dependency .proof files.
fn check_imports(imports_dir: &Path, plugins: &[PluginEntry]) -> Check {
    let name = "imports-present";
    if !imports_dir.exists() {
        if plugins.is_empty() {
            return Check::pass_with_evidence(
                name,
                "no declared plugins; imports dir not required",
                json!({
                    "path": imports_dir.display().to_string(),
                    "pluginCount": plugins.len(),
                }),
            );
        }
        return Check::warn_with_evidence(
            name,
            format!(
                ".sugar/imports/ does not exist. If this kit has dependencies, \
run their mints first and copy the resulting .proof files here \
({})",
                imports_dir.display()
            ),
            json!({
                "path": imports_dir.display().to_string(),
                "pluginCount": plugins.len(),
            }),
        );
    }

    let count = std::fs::read_dir(imports_dir)
        .map(|rd| {
            rd.filter_map(|e| e.ok())
                .filter(|e| {
                    e.path()
                        .extension()
                        .map(|ext| ext == "proof")
                        .unwrap_or(false)
                })
                .count()
        })
        .unwrap_or(0);

    if count == 0 && !plugins.is_empty() {
        Check::warn_with_evidence(
            name,
            format!(
                ".sugar/imports/ is empty (0 .proof files). \
If this kit depends on others, mint them and place their .proof outputs here."
            ),
            json!({
                "path": imports_dir.display().to_string(),
                "pluginCount": plugins.len(),
                "proofCount": count,
            }),
        )
    } else {
        Check::pass_with_evidence(
            name,
            format!(".sugar/imports/: {count} .proof file(s) present"),
            json!({
                "path": imports_dir.display().to_string(),
                "pluginCount": plugins.len(),
                "proofCount": count,
            }),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;
    use tempfile::TempDir;

    /// Write a minimal kit config.toml with the given plugins section.
    fn write_kit(dir: &Path, plugins_toml: &str) {
        fs::create_dir_all(dir.join(".sugar/imports")).unwrap();
        fs::write(
            dir.join(".sugar/config.toml"),
            format!("# test kit\n[authoring]\nsurface = \"test-surface\"\n{plugins_toml}"),
        )
        .unwrap();
    }

    /// Write a manifest.toml for a surface under the given kind dir.
    fn write_manifest(kit_dir: &Path, kind: &str, surface: &str, command: &str, working_dir: &str) {
        write_manifest_with_version(kit_dir, kind, surface, command, working_dir, None);
    }

    fn write_manifest_with_version(
        kit_dir: &Path,
        kind: &str,
        surface: &str,
        command: &str,
        working_dir: &str,
        version: Option<&str>,
    ) {
        let dir = kit_dir.join(".sugar").join(kind).join(surface);
        fs::create_dir_all(&dir).unwrap();
        let version_line = version
            .map(|version| format!("version = \"{version}\"\n"))
            .unwrap_or_default();
        fs::write(
            dir.join("manifest.toml"),
            format!(
                "name = \"test-{surface}\"\n{version_line}command = [{command}]\nworking_dir = \"{working_dir}\"\n"
            ),
        )
        .unwrap();
    }

    fn write_manifest_with_capabilities(
        kit_dir: &Path,
        kind: &str,
        surface: &str,
        command: &str,
        working_dir: &str,
        version: Option<&str>,
        phase: Option<&str>,
        authoring_surfaces: Option<&[&str]>,
        emits_signed_mementos: Option<bool>,
    ) {
        let dir = kit_dir.join(".sugar").join(kind).join(surface);
        fs::create_dir_all(&dir).unwrap();
        let mut text = format!("name = \"test-{surface}\"\n");
        if let Some(version) = version {
            text.push_str(&format!("version = \"{version}\"\n"));
        }
        text.push_str(&format!(
            "command = [{command}]\nworking_dir = \"{working_dir}\"\n"
        ));
        if let Some(phase) = phase {
            text.push_str(&format!("phase = \"{phase}\"\n"));
        }
        if authoring_surfaces.is_some() || emits_signed_mementos.is_some() {
            text.push_str("\n[capabilities]\n");
            if let Some(surfaces) = authoring_surfaces {
                let values = surfaces
                    .iter()
                    .map(|surface| format!("\"{surface}\""))
                    .collect::<Vec<_>>()
                    .join(", ");
                text.push_str(&format!("authoring_surfaces = [{values}]\n"));
            }
            if let Some(emits_signed_mementos) = emits_signed_mementos {
                text.push_str(&format!(
                    "emits_signed_mementos = {emits_signed_mementos}\n"
                ));
            }
        }
        fs::write(dir.join("manifest.toml"), text).unwrap();
    }

    /// Create a dummy executable file.
    fn make_executable(path: &Path) {
        write_executable_file(path, "#!/bin/sh\n");
    }

    fn write_executable_file(path: &Path, body: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        {
            let mut file = fs::File::create(path).unwrap();
            file.write_all(body.as_bytes()).unwrap();
            file.sync_all().unwrap();
        }
        let mut perms = fs::metadata(path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).unwrap();
    }

    fn make_consumer_plugin(path: &Path, surface: &str, method: &str, phase: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        let response = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "capabilities": {
                    "consumer_surfaces": {
                        surface: {
                            "method": method,
                            "phase": phase,
                        }
                    }
                }
            }
        });
        write_executable_file(
            path,
            &format!("#!/bin/sh\nread _line\nprintf '%s\\n' '{}'\n", response),
        );
    }

    fn valid_panic_freedom_declaration(_surface: &str) -> Value {
        use sugar_claim_envelope::KIT_DECLARATION_RPC_METHOD;

        json!({
            "kit": {"id": "stub-kit", "language": "rust", "version": "0.1.0"},
            "rpc": {
                "methods": [
                    {"name": "initialize", "required": true},
                    {"name": KIT_DECLARATION_RPC_METHOD, "required": true},
                    {"name": "shutdown", "required": false},
                    {"name": "sugar.plugin.lift", "required": true}
                ]
            },
            "proofResolution": {"strategy": "rpc-proof-bytes"},
            "residueCategories": []
        })
    }

    fn make_kit_declaration_plugin(path: &Path, declaration: Value) {
        make_kit_declaration_plugin_with_response(
            path,
            json!({"jsonrpc": "2.0", "id": 2, "result": declaration}).to_string(),
        );
    }

    fn make_kit_declaration_plugin_with_response(path: &Path, declaration_response: String) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        let initialize_response = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "capabilities": {
                    "consumer_surfaces": {}
                }
            }
        })
        .to_string();
        write_executable_file(
            path,
            &format!(
                "#!/bin/sh\nwhile IFS= read -r line; do\ncase \"$line\" in\n  *initialize*) printf '%s\\n' '{}';;\n  *sugar.plugin.kit_declaration*) printf '%s\\n' '{}';;\n  *shutdown*) exit 0;;\n  *) printf '%s\\n' '{{\"jsonrpc\":\"2.0\",\"id\":99,\"error\":{{\"code\":-32601,\"message\":\"unknown method\"}}}}';;\nesac\ndone\n",
                initialize_response, declaration_response
            ),
        );
    }

    #[derive(Debug, Clone)]
    struct MockOracleAdapter {
        observation: OracleHostObservation,
    }

    impl MockOracleAdapter {
        fn not_requested() -> Self {
            Self {
                observation: OracleHostObservation::not_requested(),
            }
        }

        fn ready() -> Self {
            Self {
                observation: OracleHostObservation {
                    host: "rust-analyzer".to_string(),
                    locatability: OracleHostLocatability::Found {
                        host_binary: "/bin/sugar-linkerd".to_string(),
                        rust_analyzer_binary: Some("/bin/rust-analyzer".to_string()),
                        discovery: "env".to_string(),
                    },
                    readiness: OracleHostReadiness::Ready {
                        detail: "sugar-linkerd spawned and reported rust-analyzer ready"
                            .to_string(),
                    },
                    engagement: OracleHostEngagement::Engaged {
                        detail: "oracle served requests during self-check".to_string(),
                    },
                    convergence: OracleResolutionConvergence::Converged {
                        detail:
                            "resolution readiness is gated by linkerd rustAnalyzerReady; convergence harness removed"
                                .to_string(),
                    },
                },
            }
        }

        fn ready_from_path() -> Self {
            let mut adapter = Self::ready();
            adapter.observation.locatability = OracleHostLocatability::Found {
                host_binary: "/usr/local/bin/sugar-linkerd".to_string(),
                rust_analyzer_binary: Some("/usr/local/bin/rust-analyzer".to_string()),
                discovery: "path".to_string(),
            };
            adapter
        }

        fn missing_host() -> Self {
            Self {
                observation: OracleHostObservation {
                    host: "rust-analyzer".to_string(),
                    locatability: OracleHostLocatability::Missing {
                        missing: vec!["sugar-linkerd".to_string()],
                        detail: "missing oracle host prerequisite(s): sugar-linkerd".to_string(),
                    },
                    readiness: OracleHostReadiness::NotReady {
                        detail: "oracle host is not locatable".to_string(),
                    },
                    engagement: OracleHostEngagement::Unknown {
                        detail: "engagement is observed at self-check time".to_string(),
                    },
                    convergence: OracleResolutionConvergence::Deferred {
                        detail:
                            "oracle readiness cannot be established until the host is locatable"
                                .to_string(),
                    },
                },
            }
        }

        fn spawn_failure() -> Self {
            let mut adapter = Self::ready();
            adapter.observation.readiness = OracleHostReadiness::NotReady {
                detail: "spawn failed: permission denied".to_string(),
            };
            adapter.observation.convergence = OracleResolutionConvergence::Deferred {
                detail: "resolution readiness was not reached".to_string(),
            };
            adapter
        }

        fn degraded() -> Self {
            let mut adapter = Self::ready();
            adapter.observation.readiness = OracleHostReadiness::Degraded {
                detail: "ready with degraded cache warmup".to_string(),
            };
            adapter
        }

        fn ready_with_unknown_engagement() -> Self {
            let mut adapter = Self::ready();
            adapter.observation.engagement = OracleHostEngagement::Unknown {
                detail: "oracle engagement is observed at self-check time".to_string(),
            };
            adapter
        }
    }

    impl OracleHostAdapter for MockOracleAdapter {
        fn observe(&self, _env: &OracleHostEnv) -> OracleHostObservation {
            self.observation.clone()
        }
    }

    #[test]
    fn known_good_kit_passes() {
        let td = TempDir::new().unwrap();
        let kit = td.path();

        // Create a fake binary.
        let bin = kit.join("fake-binary");
        make_executable(&bin);

        // Write manifest referencing the binary by relative path from kit root.
        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"test-surface\"\n",
        );
        write_manifest(kit, "lift", "test-surface", "\"./fake-binary\"", ".");

        let checks = run_checks(kit);

        let any_fail = checks.iter().any(|c| c.status == CheckStatus::Fail);
        assert!(
            !any_fail,
            "expected no FAIL checks but got: {:#?}",
            checks
                .iter()
                .filter(|c| c.status == CheckStatus::Fail)
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn missing_binary_fails_loudly_with_path() {
        let td = TempDir::new().unwrap();
        let kit = td.path();

        // Binary intentionally NOT created (just document where it would be for the fix hint).

        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"broken-surface\"\n",
        );
        write_manifest(
            kit,
            "lift",
            "broken-surface",
            "\"../target/debug/nonexistent-binary\"",
            ".",
        );

        let checks = run_checks(kit);

        let fail_checks: Vec<&Check> = checks
            .iter()
            .filter(|c| c.status == CheckStatus::Fail)
            .collect();

        assert!(
            !fail_checks.is_empty(),
            "expected at least one FAIL check for missing binary"
        );

        // The fail detail must name the resolved absolute path.
        let binary_fail = fail_checks
            .iter()
            .find(|c| c.name.contains("binary-exists"))
            .expect("expected a binary-exists FAIL check");

        // The resolved path should appear in the detail.
        assert!(
            binary_fail.detail.contains("nonexistent-binary"),
            "FAIL detail should name the missing binary; got: {}",
            binary_fail.detail
        );

        // The detail must not be silent (no empty detail).
        assert!(
            !binary_fail.detail.is_empty(),
            "FAIL detail must not be empty"
        );

        // Confirm overall exit code would be nonzero.
        let any_hard_fail = checks.iter().any(|c| c.status == CheckStatus::Fail);
        assert!(any_hard_fail, "any_hard_fail must be true -> exit nonzero");
    }

    #[test]
    fn invalid_config_toml_fails() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar")).unwrap();
        fs::write(kit.join(".sugar/config.toml"), b"not valid toml = [[[").unwrap();

        let checks = run_checks(kit);

        let config_fail = checks
            .iter()
            .find(|c| c.name == "config-toml-parse" && c.status == CheckStatus::Fail);
        assert!(
            config_fail.is_some(),
            "expected config-toml-parse FAIL for invalid TOML"
        );
    }

    #[test]
    fn run_report_defaults_to_structural_mode() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar")).unwrap();

        let report = run_report(kit);

        assert_eq!(report.mode, DoctorMode::Structural);
    }

    #[test]
    fn doctor_report_mode_reflects_requested_mode() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar")).unwrap();

        let strict = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_eq!(strict.mode, DoctorMode::Strict);
    }

    #[test]
    fn doctor_report_mode_reflects_release_gate() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar")).unwrap();

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::ReleaseGate));

        assert_eq!(report.mode, DoctorMode::ReleaseGate);
    }

    #[test]
    fn run_checks_with_context_preserves_default_engine_results() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar")).unwrap();

        let default_checks = run_checks(kit);
        let structural_checks =
            run_checks_with_context(kit, DoctorContext::new(DoctorMode::Structural));

        assert_eq!(default_checks.len(), structural_checks.len());
        assert_eq!(default_checks[0].id, structural_checks[0].id);
        assert_eq!(default_checks[0].status, structural_checks[0].status);
        assert_eq!(default_checks[0].severity, structural_checks[0].severity);
        assert_eq!(default_checks[0].evidence, structural_checks[0].evidence);
    }

    #[test]
    fn modes_preserve_config_check_output() {
        let td = TempDir::new().unwrap();
        fs::create_dir_all(td.path().join(".sugar")).unwrap();

        assert_modes_match_for_check(td.path(), "kit.config.parse");
    }

    #[test]
    fn modes_preserve_manifest_check_output() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"broken-surface\"\n",
        );
        let manifest_dir = kit.join(".sugar/lift/broken-surface");
        fs::create_dir_all(&manifest_dir).unwrap();
        fs::write(
            manifest_dir.join("manifest.toml"),
            b"name = \"broken\"\ncommand = [[[\n",
        )
        .unwrap();

        assert_modes_match_for_check(kit, "kit.manifest.parse");
    }

    #[test]
    fn modes_preserve_binary_check_output() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"broken-surface\"\n",
        );
        write_manifest(
            kit,
            "lift",
            "broken-surface",
            "\"../target/debug/nonexistent-binary\"",
            ".",
        );

        assert_modes_match_for_check(kit, "kit.plugin.command.available");
    }

    #[test]
    #[ignore = "Environment-dependent: passes locally but diverges in CI -- a consumer-surface \
check's structural-vs-strict status depends on whether an external kit/tool is provisioned \
in the job, not on this crate. Not a live regression guard. Tracked in #1926."]
    fn modes_preserve_consumer_surface_check_output() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("consumer-plugin");
        make_consumer_plugin(
            &plugin,
            "consumer-surface",
            "sugar.plugin.lift_implications",
            "consumer",
        );
        write_kit(
            kit,
            "[[plugins]]\nname = \"consumer\"\nkind = \"lift\"\nsurface = \"consumer-surface\"\n",
        );
        write_manifest(
            kit,
            "lift",
            "consumer-surface",
            "\"./consumer-plugin\"",
            ".",
        );

        assert_modes_match_for_check(kit, "kit.consumer_surface.contract");
    }

    fn assert_manifest_declared_authoring_surface_is_collected(surface: &str) {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin_name = format!("{surface}-plugin");
        let plugin = kit.join(&plugin_name);
        make_kit_declaration_plugin(&plugin, valid_panic_freedom_declaration(surface));
        write_kit(kit, "");
        write_manifest_with_capabilities(
            kit,
            "lift",
            surface,
            &format!("\"./{plugin_name}\""),
            ".",
            Some("0.1.0"),
            None,
            Some(&[surface]),
            Some(false),
        );

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        let available = check_by_id_and_surface(&report, "kit.plugin.command.available", surface);
        assert_eq!(available.status, CheckStatus::Pass);
    }

    #[test]
    fn doctor_collects_manifest_declared_authoring_go_source_surface() {
        assert_manifest_declared_authoring_surface_is_collected("go-source");
    }

    #[test]
    fn doctor_collects_manifest_declared_authoring_go_verify_surface() {
        assert_manifest_declared_authoring_surface_is_collected("go");
    }

    #[test]
    fn doctor_collects_manifest_declared_authoring_java_source_surface() {
        assert_manifest_declared_authoring_surface_is_collected("java-source");
    }

    #[test]
    fn doctor_excludes_lift_manifest_without_authoring_surfaces_capability() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("unclaimed-plugin");
        make_kit_declaration_plugin(&plugin, valid_panic_freedom_declaration("unclaimed-source"));
        write_kit(kit, "");
        write_manifest_with_capabilities(
            kit,
            "lift",
            "unclaimed-source",
            "\"./unclaimed-plugin\"",
            ".",
            Some("0.1.0"),
            None,
            None,
            Some(false),
        );

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_no_check_by_id_and_surface(
            &report,
            "kit.plugin.command.available",
            "unclaimed-source",
        );
    }

    #[test]
    fn doctor_excludes_lift_manifest_with_empty_authoring_surfaces_capability() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("empty-authoring-plugin");
        make_kit_declaration_plugin(
            &plugin,
            valid_panic_freedom_declaration("empty-authoring-source"),
        );
        write_kit(kit, "");
        write_manifest_with_capabilities(
            kit,
            "lift",
            "empty-authoring-source",
            "\"./empty-authoring-plugin\"",
            ".",
            Some("0.1.0"),
            None,
            Some(&[]),
            Some(false),
        );

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_no_check_by_id_and_surface(
            &report,
            "kit.plugin.command.available",
            "empty-authoring-source",
        );
    }

    #[test]
    fn doctor_excludes_consumer_phase_lift_manifest_from_authoring_collection() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("consumer-authoring-plugin");
        make_kit_declaration_plugin(
            &plugin,
            valid_panic_freedom_declaration("consumer-authoring-source"),
        );
        write_kit(kit, "");
        write_manifest_with_capabilities(
            kit,
            "lift",
            "consumer-authoring-source",
            "\"./consumer-authoring-plugin\"",
            ".",
            Some("0.1.0"),
            Some("consumer"),
            Some(&["consumer-authoring-source"]),
            Some(false),
        );

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_no_check_by_id_and_surface(
            &report,
            "kit.plugin.command.available",
            "consumer-authoring-source",
        );
    }

    #[test]
    fn doctor_excludes_signed_memento_lift_manifest_from_authoring_collection() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("signed-memento-plugin");
        make_kit_declaration_plugin(
            &plugin,
            valid_panic_freedom_declaration("signed-memento-source"),
        );
        write_kit(kit, "");
        write_manifest_with_capabilities(
            kit,
            "lift",
            "signed-memento-source",
            "\"./signed-memento-plugin\"",
            ".",
            Some("0.1.0"),
            None,
            Some(&["signed-memento-source"]),
            Some(true),
        );

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_no_check_by_id_and_surface(
            &report,
            "kit.plugin.command.available",
            "signed-memento-source",
        );
    }

    #[test]
    fn doctor_deduplicates_authoring_manifest_already_declared_as_plugin() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("dedupe-plugin");
        make_kit_declaration_plugin(&plugin, valid_panic_freedom_declaration("dedupe-source"));
        write_kit(
            kit,
            "[[plugins]]\nname = \"dedupe\"\nkind = \"lift\"\nsurface = \"dedupe-source\"\n",
        );
        write_manifest_with_capabilities(
            kit,
            "lift",
            "dedupe-source",
            "\"./dedupe-plugin\"",
            ".",
            Some("0.1.0"),
            None,
            Some(&["dedupe-source"]),
            Some(false),
        );

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_eq!(
            count_checks_by_id_and_surface(
                &report,
                "kit.plugin.command.available",
                "dedupe-source"
            ),
            1
        );
    }

    #[test]
    fn doctor_reports_manifest_declared_authoring_surface_with_missing_command() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(kit, "");
        let manifest_dir = kit.join(".sugar/lift/missing-command-source");
        fs::create_dir_all(&manifest_dir).unwrap();
        fs::write(
            manifest_dir.join("manifest.toml"),
            "name = \"missing-command-source\"\n\
             [capabilities]\n\
             authoring_surfaces = [\"missing-command-source\"]\n",
        )
        .unwrap();

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        let command = check_by_id_and_surface(
            &report,
            "kit.plugin.command.available",
            "missing-command-source",
        );
        assert_eq!(command.status, CheckStatus::Fail);
        assert!(
            command.detail.contains("no `command`"),
            "missing command should fail loudly instead of skipping: {}",
            command.detail
        );
    }

    #[test]
    fn doctor_skips_missing_lift_manifest_during_authoring_collection() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(kit, "");
        fs::create_dir_all(kit.join(".sugar/lift/missing-authoring")).unwrap();

        let report = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        assert_no_check_by_id_and_surface(
            &report,
            "kit.plugin.command.available",
            "missing-authoring",
        );
    }

    #[test]
    fn structural_dependency_resolver_available_passes_with_binary_evidence() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Structural),
            |_| Ok(Vec::new()),
        );

        let available = check_by_id_from_checks(&checks, "proof.dependency_resolver.available");
        assert_eq!(available.status, CheckStatus::Pass);
        assert_eq!(available.severity, CheckSeverity::Advisory);
        assert_eq!(
            available.evidence.get("command").and_then(Value::as_str),
            Some("./dep-resolver")
        );
        assert!(
            available
                .evidence
                .get("resolvedPath")
                .and_then(Value::as_str)
                .is_some(),
            "availability evidence should name the resolver binary: {available:#?}"
        );
    }

    #[test]
    fn structural_missing_dependency_resolver_warns_with_missing_binary_evidence() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_dependency_resolver_kit(kit, "\"./missing-dep-resolver\"");

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Structural),
            |_| Ok(Vec::new()),
        );

        let available = check_by_id_from_checks(&checks, "proof.dependency_resolver.available");
        assert_eq!(available.status, CheckStatus::Warn);
        assert_eq!(available.severity, CheckSeverity::Advisory);
        assert!(
            available.detail.contains("missing-dep-resolver"),
            "missing resolver detail should name the binary: {}",
            available.detail
        );
    }

    #[test]
    fn strict_missing_dependency_resolver_fails_hard_with_same_evidence() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_dependency_resolver_kit(kit, "\"./missing-dep-resolver\"");

        let structural = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Structural),
            |_| Ok(Vec::new()),
        );
        let strict = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Strict),
            |_| Ok(Vec::new()),
        );

        let structural_available =
            check_by_id_from_checks(&structural, "proof.dependency_resolver.available");
        let strict_available =
            check_by_id_from_checks(&strict, "proof.dependency_resolver.available");
        assert_eq!(strict_available.status, CheckStatus::Fail);
        assert_eq!(strict_available.severity, CheckSeverity::Hard);
        assert_eq!(
            structural_available.evidence, strict_available.evidence,
            "strict should harden policy over the same missing-resolver evidence"
        );
    }

    #[test]
    fn strict_no_dependency_resolver_configured_passes_when_no_dep_specs() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(kit, "");

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Strict),
            |_| Ok(Vec::new()),
        );

        let available = check_by_id_from_checks(&checks, "proof.dependency_resolver.available");
        assert_eq!(available.status, CheckStatus::Pass);
        assert_eq!(available.severity, CheckSeverity::Advisory);
        assert_eq!(
            available
                .evidence
                .get("configured")
                .and_then(Value::as_bool),
            Some(false)
        );
    }

    #[test]
    fn structural_existing_imports_pool_reports_fingerprint() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(kit, "");
        let cid = write_import_proof(kit, b"stable dependency proof");

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Structural),
            |_| Ok(Vec::new()),
        );

        let stable = check_by_id_from_checks(&checks, "proof.dependency_pool.stable");
        assert_eq!(stable.status, CheckStatus::Pass);
        assert_eq!(stable.severity, CheckSeverity::Advisory);
        assert_eq!(
            stable.evidence["proofs"][0]["derivedCid"].as_str(),
            Some(cid.as_str())
        );
        assert!(
            stable.evidence["proofs"][0]["byteHash"].as_str().is_some(),
            "fingerprint evidence should include byte hash: {stable:#?}"
        );
    }

    #[test]
    fn structural_absent_imports_pool_reports_no_pool_yet() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar")).unwrap();
        fs::write(
            kit.join(".sugar/config.toml"),
            "[authoring]\nsurface = \"test\"\n",
        )
        .unwrap();

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Structural),
            |_| Ok(Vec::new()),
        );

        let stable = check_by_id_from_checks(&checks, "proof.dependency_pool.stable");
        assert_eq!(stable.status, CheckStatus::Pass);
        assert_eq!(stable.severity, CheckSeverity::Advisory);
        assert_eq!(
            stable.evidence.get("poolPresent").and_then(Value::as_bool),
            Some(false)
        );
        assert!(
            stable.detail.contains("no pool yet"),
            "absent pool should be explicit: {}",
            stable.detail
        );
    }

    #[test]
    fn strict_pool_matching_resolver_staged_set_passes() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");
        let bytes = b"stable dependency proof".to_vec();
        let cid = write_import_proof(kit, &bytes);

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Strict),
            move |_| Ok(vec![proof_bytes("dep", &bytes)]),
        );

        let stable = check_by_id_from_checks(&checks, "proof.dependency_pool.stable");
        assert_eq!(stable.status, CheckStatus::Pass);
        assert_eq!(
            stable.evidence["proofs"][0]["derivedCid"].as_str(),
            Some(cid.as_str())
        );
    }

    #[test]
    fn strict_pool_drift_from_resolver_staged_set_fails_with_differing_cids() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");
        let old_cid = write_import_proof(kit, b"old dependency proof");
        let new_bytes = b"new dependency proof".to_vec();
        let new_cid = sugar_canonicalizer::blake3_512_of(&new_bytes);

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::Strict),
            move |_| Ok(vec![proof_bytes("dep", &new_bytes)]),
        );

        let stable = check_by_id_from_checks(&checks, "proof.dependency_pool.stable");
        assert_eq!(stable.status, CheckStatus::Fail);
        assert_eq!(stable.severity, CheckSeverity::Hard);
        let evidence = stable.evidence.to_string();
        assert!(
            evidence.contains(&old_cid),
            "should name pool CID: {evidence}"
        );
        assert!(
            evidence.contains(&new_cid),
            "should name staged CID: {evidence}"
        );
    }

    #[test]
    fn release_gate_identical_staging_passes_are_byte_consistent() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");
        let bytes = b"stable dependency proof".to_vec();
        let cid = sugar_canonicalizer::blake3_512_of(&bytes);

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::ReleaseGate),
            move |_| Ok(vec![proof_bytes("dep", &bytes)]),
        );

        let byte_consistent =
            check_by_id_from_checks(&checks, "proof.dependency_pool.byte_consistent");
        assert_eq!(byte_consistent.status, CheckStatus::Pass);
        assert_eq!(
            byte_consistent.evidence["proofs"][0]["derivedCid"].as_str(),
            Some(cid.as_str())
        );
    }

    #[test]
    fn release_gate_nondeterministic_staging_fails_with_byte_hashes() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");
        let calls = std::cell::Cell::new(0usize);
        let first_cid = sugar_canonicalizer::blake3_512_of(b"first proof");
        let second_cid = sugar_canonicalizer::blake3_512_of(b"second proof");

        let checks = run_dependency_proof_checks_with_resolver(
            kit,
            DoctorContext::new(DoctorMode::ReleaseGate),
            |_| {
                let call = calls.get();
                calls.set(call + 1);
                let bytes: &[u8] = if call == 0 {
                    b"first proof"
                } else {
                    b"second proof"
                };
                Ok(vec![proof_bytes("dep", bytes)])
            },
        );

        let byte_consistent =
            check_by_id_from_checks(&checks, "proof.dependency_pool.byte_consistent");
        assert_eq!(byte_consistent.status, CheckStatus::Fail);
        assert_eq!(byte_consistent.severity, CheckSeverity::Hard);
        let evidence = byte_consistent.evidence.to_string();
        assert_eq!(
            byte_consistent
                .evidence
                .get("driftKind")
                .and_then(Value::as_str),
            Some("resolver_nondeterminism")
        );
        assert!(
            evidence.contains(&first_cid) && evidence.contains(&second_cid),
            "release gate should name both diverging proof CIDs: {evidence}"
        );
        assert!(
            evidence.contains("firstByteHash") && evidence.contains("secondByteHash"),
            "release gate should show both hashes side by side: {evidence}"
        );
    }

    #[test]
    fn release_gate_between_pass_external_mutation_fails_with_distinct_reason() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");
        let bytes = b"stable dependency proof".to_vec();

        let checks = run_dependency_proof_checks_with_pass_hook(
            kit,
            DoctorContext::new(DoctorMode::ReleaseGate),
            move |_| Ok(vec![proof_bytes("dep", &bytes)]),
            |pass, scratch| {
                if pass == 1 {
                    let mutated = scratch.join("external-mutation.proof");
                    fs::write(mutated, b"external mutation").unwrap();
                }
            },
        );

        let byte_consistent =
            check_by_id_from_checks(&checks, "proof.dependency_pool.byte_consistent");
        assert_eq!(byte_consistent.status, CheckStatus::Fail);
        assert_eq!(byte_consistent.severity, CheckSeverity::Hard);
        assert_eq!(
            byte_consistent
                .evidence
                .get("driftKind")
                .and_then(Value::as_str),
            Some("between_passes_mutation")
        );
    }

    #[test]
    fn release_gate_dependency_proof_failure_marks_report_not_release_ready() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let resolver = kit.join("dep-resolver");
        make_executable(&resolver);
        write_dependency_resolver_kit(kit, "\"./dep-resolver\"");
        let calls = std::cell::Cell::new(0usize);

        let report = run_report_with_context_and_dependency_resolver(
            kit,
            DoctorContext::new(DoctorMode::ReleaseGate),
            |_| {
                let call = calls.get();
                calls.set(call + 1);
                let bytes: &[u8] = if call == 0 {
                    b"first proof"
                } else {
                    b"second proof"
                };
                Ok(vec![proof_bytes("dep", bytes)])
            },
        );

        assert!(
            !report.ok,
            "release-gate dep proof drift should fail report"
        );
        assert!(
            !report.release_ready,
            "release-gate dep proof drift must block release readiness"
        );
    }

    #[test]
    fn oracle_not_requested_emits_passes_for_all_oracle_checks() {
        for mode in [
            DoctorMode::Structural,
            DoctorMode::Strict,
            DoctorMode::ReleaseGate,
        ] {
            let checks = run_oracle_host_checks_with_adapter(
                DoctorContext::new(mode),
                &MockOracleAdapter::not_requested(),
            );

            assert_eq!(checks.len(), 5, "every oracle check is explicit in {mode}");
            for check in &checks {
                assert_eq!(check.status, CheckStatus::Pass, "{check:#?}");
                assert_eq!(
                    check.evidence.get("requested").and_then(Value::as_bool),
                    Some(false),
                    "not-requested evidence should be explicit: {check:#?}"
                );
                assert!(
                    check.detail.contains("oracle not requested"),
                    "not-requested detail should be uniform: {}",
                    check.detail
                );
            }
        }
    }

    #[test]
    fn oracle_requested_ready_adapter_passes_all_oracle_checks() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::ReleaseGate).with_oracle_requested(true),
            &MockOracleAdapter::ready(),
        );

        for id in [
            "oracle.requested",
            "oracle.host.locatable",
            "oracle.host.ready",
            "oracle.host.engaged",
            "oracle.resolution.converged",
        ] {
            let check = check_by_id_from_checks(&checks, id);
            assert_eq!(check.status, CheckStatus::Pass, "{id}: {check:#?}");
        }
        let locatable = check_by_id_from_checks(&checks, "oracle.host.locatable");
        assert_eq!(
            locatable.evidence.get("hostBinary").and_then(Value::as_str),
            Some("/bin/sugar-linkerd")
        );
        assert_eq!(
            locatable.evidence.get("discovery").and_then(Value::as_str),
            Some("env")
        );
    }

    #[test]
    fn structural_missing_oracle_host_warns_with_missing_binary_evidence() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Structural).with_oracle_requested(true),
            &MockOracleAdapter::missing_host(),
        );

        let locatable = check_by_id_from_checks(&checks, "oracle.host.locatable");
        assert_eq!(locatable.status, CheckStatus::Warn);
        assert_eq!(locatable.severity, CheckSeverity::Advisory);
        assert!(
            locatable.detail.contains("sugar-linkerd"),
            "missing-host detail should name the missing binary: {}",
            locatable.detail
        );
        assert_eq!(
            locatable
                .evidence
                .get("missing")
                .and_then(Value::as_array)
                .map(Vec::len),
            Some(1)
        );
    }

    #[test]
    fn strict_missing_oracle_host_fails_hard_with_same_evidence() {
        let structural = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Structural).with_oracle_requested(true),
            &MockOracleAdapter::missing_host(),
        );
        let strict = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Strict).with_oracle_requested(true),
            &MockOracleAdapter::missing_host(),
        );

        let structural_locatable = check_by_id_from_checks(&structural, "oracle.host.locatable");
        let strict_locatable = check_by_id_from_checks(&strict, "oracle.host.locatable");
        assert_eq!(strict_locatable.status, CheckStatus::Fail);
        assert_eq!(strict_locatable.severity, CheckSeverity::Hard);
        assert_eq!(
            structural_locatable.evidence, strict_locatable.evidence,
            "strict hardens policy over identical locatability evidence"
        );
    }

    #[test]
    fn release_gate_missing_oracle_host_fails_hard() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::ReleaseGate).with_oracle_requested(true),
            &MockOracleAdapter::missing_host(),
        );

        let locatable = check_by_id_from_checks(&checks, "oracle.host.locatable");
        assert_eq!(locatable.status, CheckStatus::Fail);
        assert_eq!(locatable.severity, CheckSeverity::Hard);
    }

    #[test]
    fn oracle_locatable_path_evidence_distinguishes_env_from_path_discovery() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Strict).with_oracle_requested(true),
            &MockOracleAdapter::ready_from_path(),
        );

        let locatable = check_by_id_from_checks(&checks, "oracle.host.locatable");
        assert_eq!(locatable.status, CheckStatus::Pass);
        assert_eq!(
            locatable.evidence.get("discovery").and_then(Value::as_str),
            Some("path")
        );
    }

    #[test]
    fn structural_not_ready_oracle_warns_with_spawn_failure() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Structural).with_oracle_requested(true),
            &MockOracleAdapter::spawn_failure(),
        );

        let ready = check_by_id_from_checks(&checks, "oracle.host.ready");
        assert_eq!(ready.status, CheckStatus::Warn);
        assert_eq!(ready.severity, CheckSeverity::Advisory);
        assert!(
            ready.detail.contains("spawn failed"),
            "readiness detail should name the failure mode: {}",
            ready.detail
        );
    }

    #[test]
    fn strict_not_ready_oracle_fails_hard_with_same_spawn_evidence() {
        let structural = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Structural).with_oracle_requested(true),
            &MockOracleAdapter::spawn_failure(),
        );
        let strict = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Strict).with_oracle_requested(true),
            &MockOracleAdapter::spawn_failure(),
        );

        let structural_ready = check_by_id_from_checks(&structural, "oracle.host.ready");
        let strict_ready = check_by_id_from_checks(&strict, "oracle.host.ready");
        assert_eq!(strict_ready.status, CheckStatus::Fail);
        assert_eq!(strict_ready.severity, CheckSeverity::Hard);
        assert_eq!(
            structural_ready.evidence, strict_ready.evidence,
            "strict hardens policy over identical readiness evidence"
        );
    }

    #[test]
    fn strict_degraded_oracle_readiness_stays_advisory() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::Strict).with_oracle_requested(true),
            &MockOracleAdapter::degraded(),
        );

        let ready = check_by_id_from_checks(&checks, "oracle.host.ready");
        assert_eq!(ready.status, CheckStatus::Warn);
        assert_eq!(ready.severity, CheckSeverity::Advisory);
        assert_eq!(
            ready.evidence.get("ready").and_then(Value::as_bool),
            Some(true),
            "degraded means functional but not ideal"
        );
    }

    #[test]
    fn release_gate_unknown_engagement_is_advisory() {
        let checks = run_oracle_host_checks_with_adapter(
            DoctorContext::new(DoctorMode::ReleaseGate).with_oracle_requested(true),
            &MockOracleAdapter::ready_with_unknown_engagement(),
        );

        let engaged = check_by_id_from_checks(&checks, "oracle.host.engaged");
        assert_eq!(engaged.status, CheckStatus::Warn);
        assert_eq!(engaged.severity, CheckSeverity::Advisory);
        assert!(
            engaged.detail.contains("observed at self-check time"),
            "engagement should not pretend standalone doctor observed work: {}",
            engaged.detail
        );
    }

    #[test]
    fn oracle_readiness_gate_accounts_for_resolution_convergence_in_all_modes() {
        for mode in [
            DoctorMode::Structural,
            DoctorMode::Strict,
            DoctorMode::ReleaseGate,
        ] {
            let checks = run_oracle_host_checks_with_adapter(
                DoctorContext::new(mode).with_oracle_requested(true),
                &MockOracleAdapter::ready(),
            );

            let converged = check_by_id_from_checks(&checks, "oracle.resolution.converged");
            assert_eq!(
                converged.status,
                CheckStatus::Pass,
                "{mode}: {converged:#?}"
            );
            assert_eq!(converged.severity, CheckSeverity::Advisory);
            assert!(
                converged.detail.contains("rustAnalyzerReady"),
                "convergence compatibility check should point at the readiness gate: {}",
                converged.detail
            );
            assert_eq!(
                converged.evidence.get("converged").and_then(Value::as_bool),
                Some(true)
            );
        }
    }

    #[test]
    fn oracle_failure_marks_release_gate_report_not_release_ready() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(kit, "");

        let report = run_report_with_context_and_oracle_adapter(
            kit,
            DoctorContext::new(DoctorMode::ReleaseGate).with_oracle_requested(true),
            MockOracleAdapter::spawn_failure(),
        );

        assert!(
            !report.ok,
            "release-gate oracle hard fail should fail report"
        );
        assert!(
            !report.release_ready,
            "release-gate oracle hard fail must block release readiness"
        );
    }

    #[test]
    fn invalid_manifest_toml_fails_with_substrate_id() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"broken-surface\"\n",
        );
        let manifest_dir = kit.join(".sugar/lift/broken-surface");
        fs::create_dir_all(&manifest_dir).unwrap();
        fs::write(
            manifest_dir.join("manifest.toml"),
            b"name = \"broken\"\ncommand = [[[\n",
        )
        .unwrap();

        let report = run_report(kit);

        let manifest = report
            .checks
            .iter()
            .find(|check| check.id == "kit.manifest.parse")
            .expect("manifest parse check");
        assert_eq!(manifest.status, CheckStatus::Fail);
        assert_eq!(manifest.severity, CheckSeverity::Hard);
        assert!(
            manifest.detail.contains("invalid TOML"),
            "manifest parse failure should carry parse detail: {}",
            manifest.detail
        );
    }

    #[test]
    fn nonexecutable_binary_fails() {
        let td = TempDir::new().unwrap();
        let kit = td.path();

        // Create a non-executable file.
        let bin = kit.join("non-exec");
        fs::write(&bin, b"not a script\n").unwrap();
        let mut perms = fs::metadata(&bin).unwrap().permissions();
        perms.set_mode(0o644); // not executable
        fs::set_permissions(&bin, perms).unwrap();

        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"test-surface\"\n",
        );
        write_manifest(kit, "lift", "test-surface", "\"./non-exec\"", ".");

        let checks = run_checks(kit);

        let fail = checks
            .iter()
            .find(|c| c.name.contains("binary-exists") && c.status == CheckStatus::Fail);
        assert!(
            fail.is_some(),
            "expected binary-exists FAIL for non-executable file"
        );
    }

    #[test]
    fn consumer_method_phase_mismatch_fails_with_fix_hint() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let plugin = kit.join("consumer-plugin");
        make_consumer_plugin(
            &plugin,
            "consumer-surface",
            "sugar.plugin.lift_implications",
            "consumer",
        );
        write_kit(
            kit,
            "[[plugins]]\nname = \"consumer\"\nkind = \"lift\"\nsurface = \"consumer-surface\"\n",
        );
        write_manifest(
            kit,
            "lift",
            "consumer-surface",
            "\"./consumer-plugin\"",
            ".",
        );

        let report = run_report(kit);

        let consumer = report
            .checks
            .iter()
            .find(|check| {
                check.id == "kit.consumer_surface.contract"
                    && check.detail.contains("Add both lines to the manifest")
            })
            .expect("consumer surface contract check");
        assert_eq!(consumer.status, CheckStatus::Fail);
        assert_eq!(consumer.severity, CheckSeverity::Hard);
        assert!(
            consumer.detail.contains("Add both lines to the manifest"),
            "consumer mismatch should preserve the fix hint: {}",
            consumer.detail
        );
        assert_eq!(
            consumer
                .evidence
                .get("requiredMethod")
                .and_then(Value::as_str),
            Some("sugar.plugin.lift_implications")
        );
    }

    #[test]
    fn doctor_report_ok_aggregates_check_statuses() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let bin = kit.join("fake-binary");
        make_executable(&bin);
        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"test-surface\"\n",
        );
        write_manifest(kit, "lift", "test-surface", "\"./fake-binary\"", ".");

        let report = run_report(kit);

        assert!(
            report.ok,
            "warn-only doctor report should be ok: {report:#?}"
        );

        let missing = TempDir::new().unwrap();
        fs::create_dir_all(missing.path().join(".sugar")).unwrap();

        let report = run_report(missing.path());

        assert!(!report.ok, "hard-fail doctor report must not be ok");
        assert!(
            report
                .checks
                .iter()
                .any(|check| check.status == CheckStatus::Fail),
            "hard-fail report must contain a failing check: {report:#?}"
        );
    }

    #[test]
    fn doctor_checks_populate_substrate_fields() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        let bin = kit.join("fake-binary");
        make_executable(&bin);
        write_kit(
            kit,
            "[[plugins]]\nname = \"test\"\nkind = \"lift\"\nsurface = \"test-surface\"\n",
        );
        write_manifest(kit, "lift", "test-surface", "\"./fake-binary\"", ".");

        let report = run_report(kit);

        let config = report
            .checks
            .iter()
            .find(|check| check.name == "config-toml-parse")
            .expect("config parse check");
        assert_eq!(config.id, "kit.config.parse");
        assert_eq!(config.domain, "kit.config");
        assert_eq!(config.severity, CheckSeverity::Hard);
        let config_path = config
            .evidence
            .get("path")
            .and_then(Value::as_str)
            .expect("config path evidence");
        assert!(
            config_path.ends_with(".sugar/config.toml"),
            "config check should carry config path evidence: {config:#?}"
        );

        let binary = report
            .checks
            .iter()
            .find(|check| check.name.contains("binary-exists"))
            .expect("binary availability check");
        assert_eq!(binary.id, "kit.plugin.command.available");
        assert_eq!(binary.domain, "kit.plugin");
        assert_eq!(binary.severity, CheckSeverity::Hard);
        assert_eq!(
            binary.evidence.get("command").and_then(Value::as_str),
            Some("./fake-binary"),
            "binary check should carry exact command evidence: {binary:#?}"
        );
    }

    #[test]
    fn missing_config_is_hard_report_check() {
        let td = TempDir::new().unwrap();
        fs::create_dir_all(td.path().join(".sugar")).unwrap();

        let report = run_report(td.path());

        let config = report
            .checks
            .iter()
            .find(|check| check.id == "kit.config.parse")
            .expect("config parse check");
        assert_eq!(config.status, CheckStatus::Fail);
        assert_eq!(config.severity, CheckSeverity::Hard);
        assert!(
            config.detail.contains(".sugar/config.toml"),
            "missing-config detail should name the file: {}",
            config.detail
        );
    }

    #[test]
    fn floor_report_ok_is_true_when_floor_checks_pass() {
        let td = TempDir::new().unwrap();
        let report = report_from_floor_signals(
            td.path(),
            DoctorMode::Strict,
            crate::floor_runtime_check::FloorSignals {
                silently_dropped: 0,
                false_pass: 0,
                dropped_sites_count: 0,
                panic_census_unnamed_count: 0,
                total_callsites: 1,
                discharge_split_present: true,
                monoid_fold_gaps_by_element_type: std::collections::BTreeMap::new(),
                algebra_gaps_by_boundary: std::collections::BTreeMap::new(),
            },
        );

        assert!(report.ok, "passing floor report should be ok: {report:#?}");
        assert!(report
            .checks
            .iter()
            .all(|check| check.status != CheckStatus::Fail));
    }

    #[test]
    fn floor_report_ok_is_false_when_any_floor_check_fails() {
        let td = TempDir::new().unwrap();
        let report = report_from_floor_signals(
            td.path(),
            DoctorMode::Strict,
            crate::floor_runtime_check::FloorSignals {
                silently_dropped: 0,
                false_pass: 1,
                dropped_sites_count: 0,
                panic_census_unnamed_count: 0,
                total_callsites: 1,
                discharge_split_present: true,
                monoid_fold_gaps_by_element_type: std::collections::BTreeMap::new(),
                algebra_gaps_by_boundary: std::collections::BTreeMap::new(),
            },
        );

        assert!(!report.ok, "failing floor report must not be ok");
        assert_eq!(
            check_by_id(&report, "floor.false_pass.zero").status,
            CheckStatus::Fail
        );
    }

    #[test]
    fn release_gate_floor_failure_marks_report_not_release_ready() {
        let td = TempDir::new().unwrap();
        let passing = report_from_floor_signals(
            td.path(),
            DoctorMode::ReleaseGate,
            crate::floor_runtime_check::FloorSignals {
                silently_dropped: 0,
                false_pass: 0,
                dropped_sites_count: 0,
                panic_census_unnamed_count: 0,
                total_callsites: 1,
                discharge_split_present: true,
                monoid_fold_gaps_by_element_type: std::collections::BTreeMap::new(),
                algebra_gaps_by_boundary: std::collections::BTreeMap::new(),
            },
        );
        let failing = report_from_floor_signals(
            td.path(),
            DoctorMode::ReleaseGate,
            crate::floor_runtime_check::FloorSignals {
                silently_dropped: 0,
                false_pass: 0,
                dropped_sites_count: 0,
                panic_census_unnamed_count: 0,
                total_callsites: 0,
                discharge_split_present: true,
                monoid_fold_gaps_by_element_type: std::collections::BTreeMap::new(),
                algebra_gaps_by_boundary: std::collections::BTreeMap::new(),
            },
        );

        assert!(passing.release_ready, "passing floor must be release ready");
        assert!(
            !failing.release_ready,
            "failing floor must block release readiness"
        );
    }

    fn check_by_id<'a>(report: &'a DoctorReport, id: &str) -> &'a DoctorCheck {
        report
            .checks
            .iter()
            .find(|check| check.id == id)
            .unwrap_or_else(|| panic!("{id} check in {report:#?}"))
    }

    fn check_by_id_and_surface<'a>(
        report: &'a DoctorReport,
        id: &str,
        surface: &str,
    ) -> &'a DoctorCheck {
        report
            .checks
            .iter()
            .find(|check| {
                check.id == id
                    && check.evidence.get("surface").and_then(Value::as_str) == Some(surface)
            })
            .unwrap_or_else(|| panic!("{id} check for surface={surface} in {report:#?}"))
    }

    fn count_checks_by_id_and_surface(report: &DoctorReport, id: &str, surface: &str) -> usize {
        report
            .checks
            .iter()
            .filter(|check| {
                check.id == id
                    && check.evidence.get("surface").and_then(Value::as_str) == Some(surface)
            })
            .count()
    }

    fn assert_no_check_by_id_and_surface(report: &DoctorReport, id: &str, surface: &str) {
        assert_eq!(
            count_checks_by_id_and_surface(report, id, surface),
            0,
            "unexpected {id} check for surface={surface} in {report:#?}"
        );
    }

    fn assert_modes_match_for_check(kit: &Path, id: &str) {
        let structural = run_report_with_context(kit, DoctorContext::new(DoctorMode::Structural));
        let strict = run_report_with_context(kit, DoctorContext::new(DoctorMode::Strict));

        let structural_check = check_by_id(&structural, id);
        let strict_check = check_by_id(&strict, id);

        assert_eq!(structural_check.status, strict_check.status, "{id} status");
        assert_eq!(
            structural_check.severity, strict_check.severity,
            "{id} severity"
        );
        assert_eq!(structural_check.detail, strict_check.detail, "{id} detail");
        assert_eq!(
            structural_check.evidence, strict_check.evidence,
            "{id} evidence"
        );
    }

    fn write_dependency_resolver_kit(kit: &Path, command: &str) {
        write_kit(
            kit,
            "[[plugins]]\nname = \"dep-resolver\"\nkind = \"lift\"\nsurface = \"dep-resolver\"\n",
        );
        write_manifest(kit, "lift", "dep-resolver", command, ".");
    }

    fn write_import_proof(kit: &Path, bytes: &[u8]) -> String {
        let cid = sugar_canonicalizer::blake3_512_of(bytes);
        let imports = kit.join(".sugar/imports");
        fs::create_dir_all(&imports).unwrap();
        fs::write(imports.join(format!("{cid}.proof")), bytes).unwrap();
        cid
    }

    fn proof_bytes(label: &str, bytes: &[u8]) -> sugar_verifier::load_all_proofs::ProofBytes {
        sugar_verifier::load_all_proofs::ProofBytes::try_from_parts(
            label.to_string(),
            sugar_canonicalizer::blake3_512_of(bytes),
            bytes.to_vec(),
            sugar_verifier::Speaker::vendor(label.to_string()),
        )
        .expect("test proof CID must parse")
    }

    fn check_by_id_from_checks<'a>(checks: &'a [DoctorCheck], id: &str) -> &'a DoctorCheck {
        checks
            .iter()
            .find(|check| check.id == id)
            .unwrap_or_else(|| panic!("{id} check in {checks:#?}"))
    }

    #[test]
    fn cmd_doctor_is_cli_shell_after_refactor() {
        let source = include_str!("cmd_doctor.rs");
        for forbidden in [
            "pub fn run_checks",
            "fn plugin_consumer_surfaces",
            "fn resolve_binary",
            "fn check_imports",
            "fn check_oracle_wiring",
        ] {
            assert!(
                !source.contains(forbidden),
                "cmd_doctor.rs should not contain check logic after refactor: found {forbidden}"
            );
        }
    }
}
