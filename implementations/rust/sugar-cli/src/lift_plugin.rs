// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Lift-plugin resolver and CLI projection adapter.
//
// The transport and primitive claim construction are `libsugar::core::Kit`.
// This module only resolves the surface manifest, builds the lift request
// input, and derives compatibility response projections from typed claims.

use std::path::{Path, PathBuf};
use std::time::Instant;

use libsugar::core::{
    address, ConformanceDeclaration, Dialect, DomainClaim, HashMapInputCatalog, Input,
    Path as CorePath, PathAlgebra, Term, Verb,
};
use owo_colors::OwoColorize;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sugar_ir_types::CompositionBoundaryMemento;

use crate::component_plan::PlannedLiftManifest;
use sugar_compiler::kit_path::{
    execute_path, KitRegistry, LiftKit, LiftPluginKit, LiftPluginKitError, PathExecutionError,
};

#[derive(Debug, Clone)]
pub(crate) struct LiftPluginSession {
    pub claim: DomainClaim,
}

impl LiftPluginSession {
    pub(crate) fn from_claim(claim: DomainClaim) -> Result<Self, LiftPluginError> {
        LiftResponseProjection::from_claim(&claim)?;
        Ok(Self { claim })
    }

    pub(crate) fn response_projection(&self) -> LiftResponseProjection<'_> {
        LiftResponseProjection { claim: &self.claim }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct LiftResponseProjection<'a> {
    claim: &'a DomainClaim,
}

impl<'a> LiftResponseProjection<'a> {
    fn from_claim(claim: &'a DomainClaim) -> Result<Self, LiftPluginError> {
        let projection = Self { claim };
        projection.response_value()?;
        Ok(projection)
    }

    pub(crate) fn response_value(&self) -> Result<&'a Value, LiftPluginError> {
        response_value_from_claim(self.claim)
    }

    pub(crate) fn clone_response_for_compatibility(&self) -> Result<Value, LiftPluginError> {
        let response = self.response_value()?;
        let before = current_rss_kib();
        let cloned = response.clone();
        trace_lift_plugin_value_checkpoint_with_delta(
            "LiftResponseProjection.clone_response_for_compatibility.after_value_clone",
            &cloned,
            rss_delta_kib(before, current_rss_kib()),
        );
        Ok(cloned)
    }
}

#[derive(Debug, Clone, Default)]
pub struct LiftPluginOptions {
    pub identify_only: bool,
    pub library_bindings: bool,
    /// Per-plugin workspace_root override (from config.toml's
    /// `[[plugins]] workspace_override = ...`). When set, replaces the
    /// project root as the `workspace_root` sent in the lift request.
    /// Used so a shim can route ONE plugin at a cargo-resolved
    /// dependency's source while OTHER plugins in the same mint still
    /// see the shim's own project root.
    pub workspace_override: Option<String>,
    /// Optional `options.emit` field passed through to the plugin via
    /// the lift request. `"ir-document"` flips self-minting plugins
    /// (sugar-lift) into composable mode so their output can be
    /// merged with sibling plugins' ir-documents at mint time.
    pub emit: Option<String>,
    /// Optional explicit `options.layer` override (from config.toml's
    /// `[[plugins]] layer = ...`). When set, replaces the layer derived
    /// from `library_bindings` / `identify_only`. Used by lifters whose
    /// behavior is gated on the layer string (e.g., the TS sugar lifter
    /// only emits library-sugar-binding-entry when layer ==
    /// "library-bindings"), so per-plugin config can request the
    /// appropriate layer regardless of the global CLI flag.
    pub layer: Option<String>,
    /// Ask a reporting-capable lifter to emit only gate summary accounting
    /// instead of transporting full ProofIR/report sidecars.
    pub report_summary: bool,
    /// Contract bindings forwarded to implication consumer surfaces. Each
    /// entry is `{ "name": <contract name>, "contract_cid": <attestation cid> }`.
    pub contract_bindings: Vec<Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) enum LiftPluginDiagnosticKind {
    ManifestResolution,
    RequestEncoding,
    Transport,
    PathExecution,
    MissingResponsePayload,
    InvalidResponsePayload,
    LegacyResponseUnavailable,
}

impl LiftPluginDiagnosticKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::ManifestResolution => "manifest_resolution",
            Self::RequestEncoding => "request_encoding",
            Self::Transport => "transport",
            Self::PathExecution => "path_execution",
            Self::MissingResponsePayload => "missing_response_payload",
            Self::InvalidResponsePayload => "invalid_response_payload",
            Self::LegacyResponseUnavailable => "legacy_response_unavailable",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct LiftPluginDiagnosticPayload {
    pub kind: LiftPluginDiagnosticKind,
    pub frontend: String,
    pub input_format: String,
    pub path: String,
    pub detail: String,
    pub retirement: String,
}

impl LiftPluginDiagnosticPayload {
    fn new(
        kind: LiftPluginDiagnosticKind,
        path: impl Into<String>,
        detail: impl Into<String>,
        retirement: impl Into<String>,
    ) -> Self {
        Self {
            kind,
            frontend: "sugar-cli::lift_plugin".to_string(),
            input_format: "lift-plugin-json-rpc-v1".to_string(),
            path: path.into(),
            detail: detail.into(),
            retirement: retirement.into(),
        }
    }
}

impl std::fmt::Display for LiftPluginDiagnosticPayload {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "lift plugin diagnostic kind={} frontend={} input_format={} path={}: {}; fix={}",
            self.kind.as_str(),
            self.frontend,
            self.input_format,
            self.path,
            self.detail,
            self.retirement
        )
    }
}

#[derive(Debug, Clone)]
pub(crate) enum LiftPluginError {
    MissingBinary { binary: String },
    Refused(Box<CompositionBoundaryMemento>),
    Diagnostic(LiftPluginDiagnosticPayload),
}

impl LiftPluginError {
    fn diagnostic(
        kind: LiftPluginDiagnosticKind,
        path: impl Into<String>,
        detail: impl Into<String>,
        retirement: impl Into<String>,
    ) -> Self {
        Self::Diagnostic(LiftPluginDiagnosticPayload::new(
            kind, path, detail, retirement,
        ))
    }
}

impl From<LiftPluginKitError> for LiftPluginError {
    fn from(value: LiftPluginKitError) -> Self {
        match value {
            LiftPluginKitError::MissingBinary { binary } => Self::MissingBinary { binary },
            LiftPluginKitError::Failed(message) => Self::diagnostic(
                LiftPluginDiagnosticKind::Transport,
                "lift-plugin.transport",
                message,
                "Inspect the lifter command, stdout/stderr, and JSON-RPC framing; keep failures as LiftPluginDiagnosticPayload, not a bare string.",
            ),
            LiftPluginKitError::LegacyResponseUnavailable => Self::diagnostic(
                LiftPluginDiagnosticKind::LegacyResponseUnavailable,
                "DomainClaim.payload",
                "lift plugin term no longer carries a legacy response projection",
                "Fix the lifter to emit a Term::Const response through LiftPluginKit::claim_from_response_term, then consume it through the typed claim projection.",
            ),
        }
    }
}

impl std::fmt::Display for LiftPluginError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingBinary { binary } => write!(f, "lifter binary `{binary}` not found"),
            Self::Refused(refusal) => write!(
                f,
                "composition refused: {}: {}",
                refusal.header.failure_kind, refusal.header.failure_detail
            ),
            Self::Diagnostic(diagnostic) => diagnostic.fmt(f),
        }
    }
}

impl std::error::Error for LiftPluginError {}

pub(crate) fn dispatch_lift(
    project_root: &Path,
    surface: &str,
    options: LiftPluginOptions,
    quiet: bool,
) -> Result<LiftPluginSession, LiftPluginError> {
    let started = Instant::now();
    let manifest = find_manifest(project_root, surface).map_err(|error| {
        LiftPluginError::diagnostic(
            LiftPluginDiagnosticKind::ManifestResolution,
            format!("surface[{surface}].manifest"),
            error,
            "Declare the lift surface in .sugar/lift/<surface>/manifest.toml, .sugar/config.toml, or component planning before dispatch.",
        )
    })?;
    trace_log(format!(
        "lift rpc start surface={surface} project={} plugin={} command={:?}",
        project_root.display(),
        manifest.name,
        manifest.command
    ));
    if !quiet {
        println!(
            "{}: surface=`{}` plugin=`{}` command={:?}",
            "dispatch".green().bold(),
            surface,
            manifest.name,
            manifest.command
        );
    }

    let lift_params = build_lift_params(project_root, surface, options);
    let mut kit = LiftPluginKit::new(
        surface,
        manifest.command.clone(),
        resolved_working_dir(project_root, &manifest),
    );
    if let Some(method) = manifest.method.as_deref() {
        kit = kit.with_method(method);
    }
    trace_log(format!("lift kit parse surface={surface}"));
    let core_session = kit.parse_session(&Input::Spec(lift_params.clone()))?;
    trace_log(format!(
        "lift kit parsed surface={surface} elapsed={:?}",
        started.elapsed()
    ));
    // #3774 daemonLift phase split: per-surface plugin dispatch wall time,
    // visible in the daemon's tracing output (trace_log above is file-gated).
    tracing::info!(
        surface,
        dispatch_ms = started.elapsed().as_millis() as u64,
        "mint/lift: plugin dispatch complete"
    );
    if !quiet {
        if let Some(name) = core_session
            .initialize_response
            .get("name")
            .and_then(|value| value.as_str())
        {
            println!("{}: plugin `{}` ready", "ok".green().bold(), name);
        }
    }

    LiftPluginSession::from_claim(core_session.claim)
}

pub(crate) fn dispatch_lift_path(
    project_root: &Path,
    surface: &str,
    options: LiftPluginOptions,
    quiet: bool,
) -> Result<LiftPluginSession, LiftPluginError> {
    let started = Instant::now();
    let manifest = find_manifest(project_root, surface);
    if !quiet {
        match &manifest {
            Ok(manifest) => println!(
                "{}: surface=`{}` plugin=`{}` command={:?}",
                "dispatch".green().bold(),
                surface,
                manifest.name,
                manifest.command
            ),
            Err(error) => println!(
                "{}: surface=`{}` registry miss: {}",
                "dispatch".yellow().bold(),
                surface,
                error
            ),
        }
    }

    let lift_params = build_lift_params(project_root, surface, options);
    let dialect = dialect_for_surface(surface);
    let kit_name = lift_kit_name(surface);
    let source = Input::Source {
        dialect: dialect.clone(),
        bytes: serde_json::to_vec(&lift_params)
            .map_err(|error| {
                LiftPluginError::diagnostic(
                    LiftPluginDiagnosticKind::RequestEncoding,
                    "lift.request",
                    format!("encode lift request: {error}"),
                    "Inspect LiftPluginOptions and build_lift_params; every request value must be JSON-serializable before it enters the lift-plugin transport.",
                )
            })?,
    };
    let source_cid = address(&source);
    let mut inputs = HashMapInputCatalog::default();
    inputs.put(source_cid.clone(), source);
    let path_input = Input::Path(Box::new(CorePath {
        algebra: vec![PathAlgebra {
            name: "lift".to_string(),
            kit: kit_name.clone(),
            inputs: vec![source_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }));
    let mut registry = KitRegistry::default();
    if let Ok(manifest) = &manifest {
        registry.register(
            kit_name,
            LiftKit::new(
                dialect,
                surface,
                manifest.command.clone(),
                resolved_working_dir(project_root, manifest),
            ),
            ConformanceDeclaration::NonCarrier {
                reason: "lifts source bytes to DomainClaim; no target source produced",
            },
        );
    }

    trace_log(format!("lift path execute surface={surface}"));
    let chain = execute_path(&path_input, &registry, &inputs).map_err(lift_error_from_path)?;
    let terminal_claim = chain.terminal_claim();
    trace_lift_plugin_claim_checkpoint("dispatch_lift_path.after_execute_path", terminal_claim);
    let before = current_rss_kib();
    let claim = chain.into_terminal_claim();
    trace_lift_plugin_claim_checkpoint_with_delta(
        "dispatch_lift_path.after_terminal_claim_move",
        &claim,
        rss_delta_kib(before, current_rss_kib()),
    );
    trace_log(format!(
        "lift path executed surface={surface} elapsed={:?}",
        started.elapsed()
    ));
    trace_lift_plugin_claim_checkpoint("dispatch_lift_path.before_response_projection", &claim);
    LiftPluginSession::from_claim(claim)
}

fn lift_error_from_path(error: PathExecutionError) -> LiftPluginError {
    match error {
        PathExecutionError::Refused(refusal) => LiftPluginError::Refused(refusal),
        PathExecutionError::Kit(error) => match error {
            libsugar::core::KitError::Transformation(message)
                if message.starts_with("lift plugin transport: lifter binary `") =>
            {
                LiftPluginError::diagnostic(
                    LiftPluginDiagnosticKind::Transport,
                    "lift-plugin.transport",
                    message,
                    "Install or configure the lifter binary named by the lift manifest; missing binaries are the only transport failure mint may downgrade to an empty-set attestation.",
                )
            }
            other => LiftPluginError::diagnostic(
                LiftPluginDiagnosticKind::PathExecution,
                "lift.path",
                other.to_string(),
                "Inspect the lift PathAlgebra step and registered LiftKit; path execution failures must stay structured at the lift-plugin seam.",
            ),
        },
        other => LiftPluginError::diagnostic(
            LiftPluginDiagnosticKind::PathExecution,
            "lift.path",
            other.to_string(),
            "Inspect the lift PathAlgebra step and input catalog; path execution failures must stay structured at the lift-plugin seam.",
        ),
    }
}

fn response_value_from_claim(claim: &DomainClaim) -> Result<&Value, LiftPluginError> {
    match claim.payload.as_ref() {
        Some(Term::Const { value, .. }) => Ok(value),
        Some(term) => Err(LiftPluginError::diagnostic(
            LiftPluginDiagnosticKind::InvalidResponsePayload,
            "DomainClaim.payload",
            format!(
                "lift claim payload must be Term::Const carrying lift response JSON; found {}",
                term_shape(term)
            ),
            "Fix the lifter to emit its wire response through LiftPluginKit::claim_from_response_term, or add a typed claim projection for the new Term shape before it crosses the CLI seam.",
        )),
        None => Err(LiftPluginError::diagnostic(
            LiftPluginDiagnosticKind::MissingResponsePayload,
            "DomainClaim.payload",
            "lift claim is missing the Term::Const response payload required for typed claim projection",
            "Preserve DomainClaim.payload until the CLI derives LiftResponseProjection, then migrate consumers to the typed claim projection instead of a stored legacy_response field.",
        )),
    }
}

fn term_shape(term: &Term) -> &'static str {
    match term {
        Term::Op { .. } => "Term::Op",
        Term::Var { .. } => "Term::Var",
        Term::Const { .. } => "Term::Const",
        Term::Unit => "Term::Unit",
    }
}

fn dialect_for_surface(surface: &str) -> Dialect {
    match surface {
        "rust" => Dialect::Rust,
        "c" => Dialect::C,
        "x86-64" | "x86_64" => Dialect::X86_64,
        "aarch64" => Dialect::AArch64,
        "wasm" => Dialect::Wasm,
        "jvm-bytecode" => Dialect::JvmBytecode,
        "coq" => Dialect::Coq,
        "smt-lib" => Dialect::SmtLib,
        other => Dialect::Other(other.to_string()),
    }
}

fn lift_kit_name(surface: &str) -> String {
    format!("lift-{surface}")
}

/// Parse a manifest.toml at the given path. Exposed pub(crate) for doctor.
pub(crate) fn parse_manifest_at(path: &Path) -> Result<PlannedLiftManifest, String> {
    let surface = surface_from_manifest_path(path);
    parse_manifest(path, &surface)
}

/// Resolve the plugin working dir relative to the project root. Exposed pub(crate) for doctor.
pub(crate) fn resolved_working_dir_for(
    project_root: &Path,
    manifest: &PlannedLiftManifest,
) -> Option<PathBuf> {
    resolved_working_dir(project_root, manifest)
}

fn parse_manifest(path: &Path, surface: &str) -> Result<PlannedLiftManifest, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let toml: toml::Value = text
        .parse()
        .map_err(|e| format!("invalid TOML in {}: {e}", path.display()))?;

    let string_field = |key: &str| -> Option<String> {
        toml.get(key)
            .and_then(toml::Value::as_str)
            .map(str::to_string)
            .filter(|value| !value.is_empty())
    };
    let command = toml
        .get("command")
        .and_then(toml::Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(toml::Value::as_str)
                .map(str::to_string)
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let manifest = PlannedLiftManifest {
        surface: surface.to_string(),
        name: string_field("name").unwrap_or_default(),
        version: string_field("version"),
        protocol_version: string_field("protocol_version")
            .or_else(|| string_field("protocolVersion")),
        command,
        working_dir: string_field("working_dir").map(PathBuf::from),
        method: string_field("method"),
        phase: string_field("phase"),
        discharge_command: Vec::new(),
        witness_tool: None,
        resolve_witness_command: Vec::new(),
        resolve_witness_method: None,
    };
    if manifest.command.is_empty() {
        return Err(format!("manifest {} has no `command`", path.display()));
    }
    Ok(manifest)
}

pub(crate) fn surface_phase(project_root: &Path, surface: &str) -> String {
    find_manifest(project_root, surface)
        .ok()
        .and_then(|manifest| manifest.phase)
        .filter(|phase| phase == "consumer")
        .unwrap_or_else(|| "producer".to_string())
}

fn find_manifest(project_root: &Path, surface: &str) -> Result<PlannedLiftManifest, String> {
    let project_local = project_root
        .join(".sugar")
        .join("lift")
        .join(surface)
        .join("manifest.toml");
    if project_local.exists() {
        return parse_manifest(&project_local, surface);
    }
    if let Some(home) = std::env::var_os("HOME") {
        let user_global = PathBuf::from(home)
            .join(".config")
            .join("sugar")
            .join("lift")
            .join(surface)
            .join("manifest.toml");
        if user_global.exists() {
            return parse_manifest(&user_global, surface);
        }
    }
    if let Some(planned) = crate::component_plan::planned_lift_manifest(project_root, surface) {
        return Ok(planned);
    }
    Err(format!(
        "no plugin manifest for surface `{surface}` (looked in .sugar/lift/{surface}/manifest.toml, ~/.config/sugar/lift/{surface}/manifest.toml, and discovered Sugar components)"
    ))
}

pub(crate) fn find_manifest_for_surface(
    project_root: &Path,
    surface: &str,
) -> Result<PlannedLiftManifest, String> {
    find_manifest(project_root, surface)
}

fn resolved_working_dir(project_root: &Path, manifest: &PlannedLiftManifest) -> Option<PathBuf> {
    manifest.working_dir.as_ref().map(|working_dir| {
        if working_dir.is_absolute() {
            working_dir.clone()
        } else {
            project_root.join(working_dir)
        }
    })
}

fn surface_from_manifest_path(path: &Path) -> String {
    path.parent()
        .and_then(Path::file_name)
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_string()
}

pub fn build_lift_params(project_root: &Path, surface: &str, options: LiftPluginOptions) -> Value {
    // Per-plugin override takes precedence over the project root.
    // Substrate-honest: the plugin receives the workspace_root the
    // project config declared. Relative overrides are anchored at the
    // project root, not the shell cwd, so manifest/config wiring is stable.
    let workspace_root: PathBuf = if let Some(override_path) = options.workspace_override.as_deref()
    {
        let configured = PathBuf::from(override_path);
        let candidate = if configured.is_absolute() {
            configured
        } else {
            project_root.join(configured)
        };
        candidate.canonicalize().unwrap_or(candidate)
    } else {
        project_root
            .canonicalize()
            .unwrap_or_else(|_| project_root.to_path_buf())
    };
    // Explicit per-plugin `layer` (from config.toml) wins. Falls back
    // to the derived layer (CLI flag / identify_only) for back-compat
    // with single-surface mints.
    let layer: &str = if let Some(explicit) = options.layer.as_deref() {
        explicit
    } else if options.identify_only {
        "identify-only"
    } else if options.library_bindings {
        "library-bindings"
    } else {
        "all"
    };
    let mut options_obj = json!({
        "layer": layer,
        "identifyOnly": options.identify_only,
    });
    if let Some(emit) = options.emit.as_deref() {
        options_obj["emit"] = json!(emit);
    }
    if options.report_summary {
        options_obj["reportSummary"] = json!(true);
    }
    // Preserve the original workspace_override in the request itself,
    // so consumers of the lift_request (like MintKit::transform_session)
    // can distinguish "use the project root" from "this plugin was
    // overridden to a different workspace" — important for manifest
    // lookup, which always lives under the project root regardless of
    // where the plugin walks. The actual `workspace_root` field above
    // already encodes the final (post-override) walk root.
    if let Some(override_path) = options.workspace_override.as_deref() {
        options_obj["workspaceOverride"] = json!(override_path);
    }
    let mut params = json!({
        "surface": surface,
        "workspace_root": workspace_root,
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": options_obj,
    });
    if !options.contract_bindings.is_empty() {
        params["contract_bindings"] = Value::Array(options.contract_bindings.clone());
    }
    params
}

fn trace_log(message: impl std::fmt::Display) {
    tracing::trace!("{}", message);
}

fn current_rss_kib() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let status = std::fs::read_to_string("/proc/self/status").ok()?;
        status.lines().find_map(|line| {
            let rest = line.strip_prefix("VmRSS:")?;
            rest.split_whitespace().next()?.parse::<u64>().ok()
        })
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

fn rss_delta_kib(before: Option<u64>, after: Option<u64>) -> Option<u64> {
    Some(after?.saturating_sub(before?))
}

fn lift_response_array_len(value: &Value, keys: &[&str]) -> usize {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(Value::as_array).map(Vec::len))
        .unwrap_or(0)
}

fn trace_lift_plugin_claim_checkpoint(stage: &'static str, claim: &DomainClaim) {
    trace_lift_plugin_claim_checkpoint_with_delta(stage, claim, None);
}

fn trace_lift_plugin_claim_checkpoint_with_delta(
    stage: &'static str,
    claim: &DomainClaim,
    rss_delta_kib: Option<u64>,
) {
    let response = claim_response_value(claim).unwrap_or(&Value::Null);
    trace_lift_plugin_value_checkpoint_with_delta(stage, response, rss_delta_kib);
}

fn trace_lift_plugin_value_checkpoint_with_delta(
    stage: &'static str,
    response: &Value,
    rss_delta_kib: Option<u64>,
) {
    let rss_kib = current_rss_kib();
    tracing::info!(
        stage = stage,
        rss_kib = rss_kib.unwrap_or_default(),
        rss_available = rss_kib.is_some(),
        rss_delta_kib = rss_delta_kib.unwrap_or_default(),
        contracts = lift_response_array_len(response, &["ir"]),
        source_audits = lift_response_array_len(response, &["sourceAudits", "source_audits"]),
        factory_audits = lift_response_array_len(response, &["factoryAudits", "factory_audits"]),
        assertion_surface_audits = lift_response_array_len(
            response,
            &["assertionSurfaceAudits", "assertion_surface_audits"]
        ),
        source_mementos = lift_response_array_len(response, &["sourceMementos", "source_mementos"]),
        call_edges = lift_response_array_len(response, &["callEdges", "call_edges"]),
        vendor_conjoins = lift_response_array_len(
            response,
            &[
                "vendorConjoins",
                "vendor_conjoins",
                "linkerConjoins",
                "linker_conjoins"
            ]
        ),
        "lift-plugin cli adapter memory checkpoint"
    );
}

fn claim_response_value(claim: &DomainClaim) -> Option<&Value> {
    match claim.payload.as_ref()? {
        Term::Const { value, .. } => Some(value),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use libsugar::core::{DomainKind, Term};
    use sugar_ir_types::Sort;

    #[test]
    fn lift_plugin_options_select_library_bindings_layer() {
        let request = build_lift_params(
            Path::new("."),
            "python",
            LiftPluginOptions {
                identify_only: false,
                library_bindings: true,
                ..Default::default()
            },
        );

        assert_eq!(
            request["options"]["layer"].as_str(),
            Some("library-bindings")
        );
        assert_eq!(request["options"]["identifyOnly"].as_bool(), Some(false));
    }

    #[test]
    fn lift_plugin_options_pass_report_summary_to_lifter() {
        let request = build_lift_params(
            Path::new("."),
            "rust",
            LiftPluginOptions {
                report_summary: true,
                ..Default::default()
            },
        );

        assert_eq!(request["options"]["reportSummary"].as_bool(), Some(true));
    }

    #[test]
    fn relative_workspace_override_resolves_from_project_root() {
        let temp = tempfile::tempdir().expect("tempdir");
        let project = temp.path().join("project");
        let vendor = project.join("vendor/base64-0.22.1");
        std::fs::create_dir_all(&vendor).expect("create vendor dir");

        let request = build_lift_params(
            &project,
            "rust-fn-contracts",
            LiftPluginOptions {
                workspace_override: Some("vendor/base64-0.22.1".to_string()),
                ..Default::default()
            },
        );

        assert_eq!(
            request["workspace_root"].as_str(),
            Some(
                vendor
                    .canonicalize()
                    .expect("canonical vendor")
                    .to_string_lossy()
                    .as_ref()
            )
        );
        assert_eq!(
            request["options"]["workspaceOverride"].as_str(),
            Some("vendor/base64-0.22.1"),
            "the raw config value is preserved so report visuals can rebase source mementos"
        );
    }

    #[test]
    fn lift_response_array_len_counts_camel_and_snake_case_fields() {
        let response = json!({
            "sourceAudits": [1, 2],
            "factory_audits": [3, 4, 5],
            "scalar": 9,
        });

        assert_eq!(
            lift_response_array_len(&response, &["sourceAudits", "source_audits"]),
            2
        );
        assert_eq!(
            lift_response_array_len(&response, &["factoryAudits", "factory_audits"]),
            3
        );
        assert_eq!(lift_response_array_len(&response, &["scalar"]), 0);
        assert_eq!(lift_response_array_len(&response, &["missing"]), 0);
    }

    #[test]
    fn lift_session_is_domain_claim_first_and_response_projection_round_trips() {
        let response = json!({
            "kind": "ir-document",
            "ir": [],
            "diagnostics": []
        });
        let request = build_lift_params(
            Path::new("."),
            "rust",
            LiftPluginOptions {
                identify_only: false,
                library_bindings: false,
                ..Default::default()
            },
        );

        let term = Term::Const {
            value: response.clone(),
            sort: Sort::Primitive {
                name: "LiftPluginResponse".to_string(),
            },
        };
        let kit = LiftPluginKit::new("rust", Vec::new(), None);
        let input = Input::Spec(request);
        let claim = kit
            .claim_from_response_term(&input, term)
            .expect("lift response becomes a primitive claim");
        let session = LiftPluginSession::from_claim(claim)
            .expect("claim payload becomes a lift response projection");

        assert_eq!(
            session.claim.domain,
            DomainKind::Other("lift-plugin".to_string())
        );
        assert_eq!(session.claim.from.len(), 1);
        assert!(session.claim.premises.is_empty());
        assert_eq!(session.claim.artifacts.len(), 1);
        assert_eq!(
            session
                .response_projection()
                .clone_response_for_compatibility()
                .expect("projection clones legacy-compatible response"),
            response
        );
    }

    #[test]
    fn lift_response_projection_byte_identity_rejects_planted_drift() {
        let response = json!({
            "kind": "ir-document",
            "ir": [{"kind": "fixture", "name": "stable"}],
            "diagnostics": []
        });
        let request = build_lift_params(
            Path::new("."),
            "rust",
            LiftPluginOptions {
                identify_only: false,
                library_bindings: false,
                ..Default::default()
            },
        );

        let term = Term::Const {
            value: response.clone(),
            sort: Sort::Primitive {
                name: "LiftPluginResponse".to_string(),
            },
        };
        let kit = LiftPluginKit::new("rust", Vec::new(), None);
        let input = Input::Spec(request);
        let claim = kit
            .claim_from_response_term(&input, term)
            .expect("lift response becomes a primitive claim");
        let session = LiftPluginSession::from_claim(claim)
            .expect("claim payload becomes a lift response projection");

        let projected = session
            .response_projection()
            .clone_response_for_compatibility()
            .expect("projection clones legacy-compatible response");
        let mut drifted = response.clone();
        drifted["ir"][0]["name"] = json!("planted-drift");

        assert_eq!(
            projected, response,
            "typed claim projection must be byte-identical to the plugin response"
        );
        assert_ne!(
            projected, drifted,
            "planted drift control: fixture must red if projection output changes"
        );
    }

    #[test]
    fn malformed_lift_response_payload_becomes_typed_diagnostic() {
        let response = json!({
            "kind": "ir-document",
            "ir": [],
            "diagnostics": []
        });
        let request = build_lift_params(
            Path::new("."),
            "rust",
            LiftPluginOptions {
                identify_only: false,
                library_bindings: false,
                ..Default::default()
            },
        );

        let term = Term::Const {
            value: response,
            sort: Sort::Primitive {
                name: "LiftPluginResponse".to_string(),
            },
        };
        let kit = LiftPluginKit::new("rust", Vec::new(), None);
        let input = Input::Spec(request);
        let mut claim = kit
            .claim_from_response_term(&input, term)
            .expect("lift response becomes a primitive claim");
        claim.payload = Some(Term::Var {
            name: "not-a-response-const".to_string(),
        });

        let error = LiftPluginSession::from_claim(claim)
            .expect_err("non-Const payload cannot be a lift response projection");
        match error {
            LiftPluginError::Diagnostic(diagnostic) => {
                assert_eq!(
                    diagnostic.kind,
                    LiftPluginDiagnosticKind::InvalidResponsePayload
                );
                assert_eq!(diagnostic.path, "DomainClaim.payload");
                assert!(
                    diagnostic.detail.contains("Term::Const"),
                    "diagnostic must name the expected replacement shape: {diagnostic:?}"
                );
                assert!(
                    diagnostic.retirement.contains("typed claim projection"),
                    "diagnostic must tell a cold agent where the fix lives: {diagnostic:?}"
                );
            }
            other => panic!("expected typed diagnostic, got {other:?}"),
        }
    }
}
