// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Zero-config component rendezvous.
//
// The CLI owns generic discovery and composition. Components own language and
// tool semantics over RPC: "does this workspace look like mine, and what
// surfaces/manifests do I contribute?" Authored project/user manifests still
// override this path; component planning is the default only when no explicit
// config exists.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Arc};
use std::time::Duration;

use libsugar::core::ComponentRegistry;
use serde::Deserialize;
use serde_json::{json, Value};
use sugar_canonicalizer::{blake3_512_of, encode_jcs, json_to_value, Value as CValue};
use sugar_ir_compiler::{
    registry::Registry as CompilerRegistry, subprocess::LazyJsonRpcCompiler, Capabilities,
    PROTOCOL_VERSION as IR_COMPILER_PROTOCOL_VERSION,
};
use tracing::{debug, info, warn};

use crate::project_config::{read_project_config, PluginEntry, ProjectConfig};

pub const COMPONENT_PROTOCOL_VERSION: &str = "sugar-component/1";
pub const COMPONENT_PLAN_RPC_METHOD: &str = "sugar.component.plan";
const COMPONENT_PLAN_TIMEOUT_ENV: &str = "SUGAR_COMPONENT_PLAN_TIMEOUT_SECS";
// Component planning is metadata-only; the verifier's 120s timeout is for solver work.
const COMPONENT_PLAN_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ComponentPlanOptions {
    pub allow_failed_components: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanIntent {
    Lift,
    Prove,
    Verify,
}

impl PlanIntent {
    pub fn as_str(self) -> &'static str {
        match self {
            PlanIntent::Lift => "lift",
            PlanIntent::Prove => "prove",
            PlanIntent::Verify => "verify",
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct WorkspaceCensus {
    pub languages: Vec<LanguageEvidence>,
    pub items: Vec<ForensicItem>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanguageEvidence {
    pub language: String,
    pub path: String,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ForensicItem {
    pub id: String,
    pub kind: String,
    pub path: String,
    pub language_hint: Option<String>,
    pub reason: String,
}

#[derive(Debug, Clone, Default)]
pub struct ComponentPlan {
    pub plugins: Vec<PluginEntry>,
    pub lift_manifests: Vec<PlannedLiftManifest>,
    pub ir_compilers: Vec<PlannedIrCompiler>,
    pub diagnostics: Vec<ComponentDiagnostic>,
    pub census: WorkspaceCensus,
    pub selected_components: Vec<PlannedComponent>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComponentDiagnostic {
    pub level: DiagnosticLevel,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DiagnosticLevel {
    Info,
    Warning,
    Error,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PlannedLiftManifest {
    pub surface: String,
    pub name: String,
    pub version: Option<String>,
    pub protocol_version: Option<String>,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub method: Option<String>,
    pub phase: Option<String>,
    pub discharge_command: Vec<String>,
    pub witness_tool: Option<String>,
    pub resolve_witness_command: Vec<String>,
    pub resolve_witness_method: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PlannedComponent {
    pub name: String,
    pub version: Option<String>,
    pub protocol_version: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub source: PathBuf,
    pub source_cid: String,
}

impl PlannedComponent {
    fn from_registration(component: &ComponentRegistration) -> Self {
        Self {
            name: component.name.clone(),
            version: component.version.clone(),
            protocol_version: component.protocol_version.clone(),
            command: component.command.clone(),
            working_dir: component.working_dir.clone(),
            source: component.source.clone(),
            source_cid: component.source_cid.clone(),
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PlannedIrCompiler {
    pub name: String,
    pub version: Option<String>,
    pub protocol_version: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub dialects: Vec<String>,
    pub supported_sorts: Vec<String>,
    pub supported_predicates: Vec<String>,
}

#[derive(Debug, Clone)]
struct ComponentRegistration {
    name: String,
    version: Option<String>,
    protocol_version: String,
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    source: PathBuf,
    source_cid: String,
}

#[derive(Debug, Clone)]
#[allow(dead_code)] // minted by plan_artifact_memento; threaded by cmd_prove (binary) and plan-artifact unit tests
pub(crate) struct PlanArtifactMemento {
    pub plan_cid: String,
    pub member_cid: String,
    pub member_bytes: Vec<u8>,
}

#[derive(Debug, Deserialize)]
struct ComponentManifest {
    name: String,
    #[serde(default)]
    version: Option<String>,
    protocol_version: String,
    command: Vec<String>,
    #[serde(default)]
    working_dir: Option<PathBuf>,
}

#[derive(Debug, Default)]
struct DiscoveredComponents {
    components: Vec<ComponentRegistration>,
    diagnostics: Vec<ComponentDiagnostic>,
}

#[derive(Debug, Clone)]
enum ComponentPlanOutcome {
    Claimed {
        result: ComponentPlanResult,
        languages: BTreeSet<String>,
    },
    Declined {
        languages: BTreeSet<String>,
        reason: Option<String>,
    },
    Failed {
        error: String,
    },
}

#[derive(Debug, Clone)]
enum ComponentPlanDecision {
    Claim(ComponentPlanResult),
    Decline(ComponentDecline),
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct ComponentDecline {
    languages: BTreeSet<String>,
    reason: Option<String>,
}

pub fn plan_workspace(project_root: &Path, intent: PlanIntent) -> ComponentPlan {
    plan_workspace_with_options(project_root, intent, ComponentPlanOptions::default())
}

/// Process-wide memo for `plan_workspace_with_options` (#3774 daemonLift
/// trim). The dominant per-save cost in the daemon's overlay mint was this
/// function: it SPAWNS every registered component binary and runs an
/// initialize/plan/shutdown JSON-RPC handshake (~1.1s/call on the pandas
/// demo) to answer a question whose inputs are stable across saves. The
/// cache key is a fingerprint of EVERYTHING the subprocess round-trip
/// depends on: project root, intent, options, the full workspace census
/// (languages + forensic items), and each discovered component registration
/// INCLUDING its binary's mtime -- so editing the workspace surface, adding
/// a component, or rebuilding a component binary all miss the cache and
/// re-run the real handshake. The census + discovery walk still runs fresh
/// on every call (it is the cheap part and it feeds the key); only the
/// subprocess RPCs are memoized. One-shot CLI processes are unaffected
/// (cold cache per process); the long-lived daemon is the beneficiary.
fn component_plan_cache() -> &'static std::sync::Mutex<HashMap<String, ComponentPlan>> {
    static CACHE: std::sync::OnceLock<std::sync::Mutex<HashMap<String, ComponentPlan>>> =
        std::sync::OnceLock::new();
    CACHE.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

pub fn plan_workspace_with_options(
    project_root: &Path,
    intent: PlanIntent,
    options: ComponentPlanOptions,
) -> ComponentPlan {
    let project_root = absolute_path(project_root);
    let census = census_workspace(&project_root);
    let project_config = read_project_config(&project_root);
    let authored_lift_languages = authored_lift_languages(&project_config);
    let mut plan = ComponentPlan {
        census,
        ..Default::default()
    };
    let discovered = discover_components(&project_root);
    let components = discovered.components;
    plan.diagnostics.extend(discovered.diagnostics);

    let cache_key = {
        let mut key = format!(
            "root={}\nintent={}\noptions={:?}\ncensus={:?}\n",
            project_root.display(),
            intent.as_str(),
            options,
            plan.census,
        );
        for component in &components {
            let binary_mtime = component
                .command
                .first()
                .and_then(|bin| std::fs::metadata(bin).ok())
                .and_then(|meta| meta.modified().ok());
            key.push_str(&format!("component={component:?} mtime={binary_mtime:?}\n"));
        }
        key.push_str(&format!(
            "authored_lift_languages={authored_lift_languages:?}\nplugins={:?}\n",
            project_config.plugins
        ));
        blake3_512_of(key.as_bytes())
    };
    if let Ok(cache) = component_plan_cache().lock() {
        if let Some(cached) = cache.get(&cache_key) {
            debug!(
                project = %project_root.display(),
                intent = intent.as_str(),
                "component plan served from process cache (fingerprint hit)"
            );
            return cached.clone();
        }
    }
    let census_languages = census_languages(&plan.census);
    let mut claimed_languages = BTreeSet::new();
    let mut declined_languages = BTreeSet::new();
    info!(
        project = %project_root.display(),
        intent = intent.as_str(),
        components = components.len(),
        languages = ?plan.census.languages.iter().map(|e| e.language.as_str()).collect::<Vec<_>>(),
        "component plan discovery complete"
    );
    for component in components {
        match request_component_plan(&component, &project_root, &plan.census, intent) {
            ComponentPlanOutcome::Claimed { result, languages } => {
                info!(
                    component = component.name,
                    plugins = result.plugins.len(),
                    manifests = result.lift_manifests.len(),
                    ir_compilers = result.ir_compilers.len(),
                    "component claimed workspace"
                );
                claimed_languages.extend(languages);
                plan.selected_components
                    .push(PlannedComponent::from_registration(&component));
                plan.plugins.extend(result.plugins);
                plan.lift_manifests.extend(result.lift_manifests);
                plan.ir_compilers.extend(result.ir_compilers);
                plan.diagnostics.extend(result.diagnostics);
            }
            ComponentPlanOutcome::Declined { languages, reason } => {
                debug!(
                    component = component.name,
                    source = %component.source.display(),
                    reason = reason.as_deref().unwrap_or("component declined workspace"),
                    "component declined workspace"
                );
                declined_languages.extend(languages);
            }
            ComponentPlanOutcome::Failed { error } => {
                warn!(
                    component = component.name,
                    source = %component.source.display(),
                    error,
                    "component plan failed"
                );
                // A missing/unbuilt component binary is "not enrolled", not a
                // workspace fault. examples-gate builds only sugar +
                // sugar-ir-smt-lib (#3747): coq/lean/maude manifests still
                // discover and spawn-fail. Treating that as Error made prove
                // emit setup-error JSON with zero rows; harnesses read MISSING
                // consistency rows. Soften unavailable binaries always; other
                // plan failures still honor --allow-failed-components.
                let level =
                    if options.allow_failed_components || component_binary_unavailable(&error) {
                        DiagnosticLevel::Warning
                    } else {
                        DiagnosticLevel::Error
                    };
                plan.diagnostics.push(ComponentDiagnostic {
                    level,
                    message: failed_component_message(&component, &error),
                });
            }
        }
    }

    dedupe_plugins(&mut plan.plugins);
    dedupe_manifests(&mut plan.lift_manifests);
    dedupe_ir_compilers(&mut plan.ir_compilers);
    order_component_plugins(&mut plan.plugins);
    for language in census_languages {
        if !claimed_languages.contains(&language)
            && !declined_languages.contains(&language)
            && !authored_lift_languages.contains(&language)
        {
            if let Some(message) = missing_kit_message_for_language(&plan.census, &language) {
                plan.diagnostics.push(ComponentDiagnostic {
                    level: DiagnosticLevel::Error,
                    message,
                });
            }
        }
    }
    if let Ok(mut cache) = component_plan_cache().lock() {
        cache.insert(cache_key, plan.clone());
    }
    plan
}

/// An authored lift plugin is the user's explicit owner for the declared
/// platform language. Component discovery is the zero-config fallback and
/// must not reject that workspace merely because no installed component also
/// claims it.
fn authored_lift_languages(config: &ProjectConfig) -> BTreeSet<String> {
    if !config.plugins.iter().any(PluginEntry::is_lift_plugin) {
        return BTreeSet::new();
    }
    config
        .platform_profile
        .as_ref()
        .and_then(|profile| profile.language.as_ref())
        .filter(|language| !language.trim().is_empty())
        .cloned()
        .into_iter()
        .collect()
}

#[allow(dead_code)] // called by discharge_config in the binary module tree
pub(crate) fn planned_lift_plugins(project_root: &Path) -> Vec<PluginEntry> {
    plan_workspace(project_root, PlanIntent::Lift).plugins
}

#[allow(dead_code)] // called by cmd_lift/cmd_prove/cmd_verify/witness_verify in the binary module tree
pub(crate) fn first_error_diagnostic(plan: &ComponentPlan) -> Option<&ComponentDiagnostic> {
    plan.diagnostics
        .iter()
        .find(|diagnostic| matches!(diagnostic.level, DiagnosticLevel::Error))
}

#[allow(dead_code)] // called by cmd_lift/cmd_prove/cmd_verify in the binary module tree
pub(crate) fn warning_diagnostics(
    plan: &ComponentPlan,
) -> impl Iterator<Item = &ComponentDiagnostic> {
    plan.diagnostics
        .iter()
        .filter(|diagnostic| matches!(diagnostic.level, DiagnosticLevel::Warning))
}

pub(crate) fn planned_lift_manifest(
    project_root: &Path,
    surface: &str,
) -> Option<PlannedLiftManifest> {
    plan_workspace(project_root, PlanIntent::Lift)
        .lift_manifests
        .into_iter()
        .find(|manifest| manifest.surface == surface)
}

#[allow(dead_code)] // feeds compiler_registry / compiler_registry_from_plan for cmd_prove/cmd_verify (binary)
pub(crate) fn planned_ir_compilers(project_root: &Path) -> Vec<PlannedIrCompiler> {
    plan_workspace(project_root, PlanIntent::Prove).ir_compilers
}

/// Verifier-backed [`ComponentRegistry`] implementation.
///
/// This is the concrete, injected implementation of the SEAM 3a inversion
/// point defined in `libsugar::core::traits::ComponentRegistry`: it wraps
/// `sugar_verifier::compiler_registry::build`, so the dependency on
/// `sugar-verifier` lives here (in `sugar-cli`, above `libsugar`) rather
/// than inside the census path calling the verifier crate directly.
#[allow(dead_code)] // used as ComponentRegistry by cmd_prove/cmd_verify in the binary module tree
pub(crate) struct VerifierComponentRegistry;

impl ComponentRegistry for VerifierComponentRegistry {
    type Registry = CompilerRegistry;

    fn build(&self, project_root: &Path) -> CompilerRegistry {
        sugar_verifier::compiler_registry::build(project_root)
    }
}

#[allow(dead_code)] // entry for full-plan compiler registry; pair of compiler_registry_from_plan (cmd_prove/cmd_verify binary)
pub(crate) fn compiler_registry(
    project_root: &Path,
    registry_builder: &dyn ComponentRegistry<Registry = CompilerRegistry>,
) -> CompilerRegistry {
    let mut registry = registry_builder.build(project_root);
    register_planned_ir_compilers(
        &mut registry,
        project_root,
        planned_ir_compilers(project_root),
    );
    registry
}

#[allow(dead_code)] // called by cmd_prove/cmd_verify in the binary module tree
pub(crate) fn compiler_registry_from_plan(
    project_root: &Path,
    plan: &ComponentPlan,
    registry_builder: &dyn ComponentRegistry<Registry = CompilerRegistry>,
) -> CompilerRegistry {
    let mut registry = registry_builder.build(project_root);
    register_planned_ir_compilers(&mut registry, project_root, plan.ir_compilers.clone());
    registry
}

#[allow(dead_code)] // private helper of compiler_registry{,_from_plan}; also unit-tested in this module
fn register_planned_ir_compilers(
    registry: &mut CompilerRegistry,
    project_root: &Path,
    compilers: Vec<PlannedIrCompiler>,
) {
    for compiler in compilers {
        if compiler.protocol_version != IR_COMPILER_PROTOCOL_VERSION {
            warn!(
                compiler = compiler.name,
                protocol = compiler.protocol_version,
                expected = IR_COMPILER_PROTOCOL_VERSION,
                "skipping component IR compiler with incompatible protocol"
            );
            continue;
        }
        if compiler.command.is_empty() {
            warn!(
                compiler = compiler.name,
                "skipping component IR compiler without command"
            );
            continue;
        }
        let dialects = compiler
            .dialects
            .iter()
            .filter(|dialect| registry.get(dialect).is_none())
            .cloned()
            .collect::<Vec<_>>();
        if dialects.is_empty() {
            continue;
        }
        let caps = Capabilities {
            name: compiler.name.clone(),
            version: compiler
                .version
                .clone()
                .unwrap_or_else(|| "0.0.0".to_string()),
            protocol_version: compiler.protocol_version.clone(),
            dialects,
            supported_sorts: compiler.supported_sorts.clone(),
            supported_predicates: compiler.supported_predicates.clone(),
        };
        let working_dir =
            resolve_project_relative_working_dir(project_root, compiler.working_dir.as_ref());
        registry.register(Arc::new(LazyJsonRpcCompiler::new(
            compiler.command.clone(),
            working_dir,
            caps,
        )));
    }
}

fn census_workspace(project_root: &Path) -> WorkspaceCensus {
    let mut languages = Vec::new();
    let mut items = Vec::new();
    if project_root.join("Cargo.toml").is_file() {
        languages.push(LanguageEvidence {
            language: "rust".to_string(),
            path: "Cargo.toml".to_string(),
            reason: "Cargo package manifest".to_string(),
        });
        items.push(ForensicItem {
            id: "file:Cargo.toml".to_string(),
            kind: "package-manifest".to_string(),
            path: "Cargo.toml".to_string(),
            language_hint: Some("rust".to_string()),
            reason: "Cargo package manifest".to_string(),
        });
    }
    collect_forensic_items(project_root, project_root, &mut items);
    dedupe_forensic_items(&mut items);
    let mut seen_languages = languages
        .iter()
        .map(|evidence| evidence.language.clone())
        .collect::<BTreeSet<_>>();
    for item in &items {
        let Some(language) = item.language_hint.as_deref() else {
            continue;
        };
        if seen_languages.insert(language.to_string()) {
            languages.push(LanguageEvidence {
                language: language.to_string(),
                path: item.path.clone(),
                reason: item.reason.clone(),
            });
        }
    }
    WorkspaceCensus { languages, items }
}

fn collect_forensic_items(project_root: &Path, dir: &Path, items: &mut Vec<ForensicItem>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = entry.file_name();
        let file_name = file_name.to_string_lossy();
        if path.is_dir() {
            if matches!(
                file_name.as_ref(),
                ".git" | ".sugar" | "target" | "__pycache__" | ".pytest_cache"
            ) {
                continue;
            }
            collect_forensic_items(project_root, &path, items);
            continue;
        }
        let Some(rel) = rel_path(project_root, &path) else {
            continue;
        };
        match file_name.as_ref() {
            "Cargo.toml" => items.push(ForensicItem {
                id: format!("file:{rel}"),
                kind: "package-manifest".to_string(),
                path: rel,
                language_hint: Some("rust".to_string()),
                reason: "Cargo package manifest".to_string(),
            }),
            "pom.xml" | "build.gradle" | "build.gradle.kts" => items.push(ForensicItem {
                id: format!("file:{rel}"),
                kind: "package-manifest".to_string(),
                path: rel,
                language_hint: Some("java".to_string()),
                reason: "Java package manifest".to_string(),
            }),
            "pyproject.toml" | "pytest.ini" | "setup.cfg" | "setup.py" => {
                items.push(ForensicItem {
                    id: format!("file:{rel}"),
                    kind: "package-manifest".to_string(),
                    path: rel,
                    language_hint: Some("python".to_string()),
                    reason: "Python package/test manifest".to_string(),
                });
            }
            _ => {
                let language = match path.extension().and_then(|ext| ext.to_str()) {
                    Some("rs") => Some("rust"),
                    Some("java") => Some("java"),
                    Some("py") => Some("python"),
                    _ => None,
                };
                if let Some(language) = language {
                    items.push(ForensicItem {
                        id: format!("file:{rel}"),
                        kind: "source-file".to_string(),
                        path: rel,
                        language_hint: Some(language.to_string()),
                        reason: format!("{language} source file"),
                    });
                }
            }
        }
    }
}

fn rel_path(root: &Path, path: &Path) -> Option<String> {
    Some(
        path.strip_prefix(root)
            .ok()?
            .display()
            .to_string()
            .replace('\\', "/"),
    )
}

fn dedupe_forensic_items(items: &mut Vec<ForensicItem>) {
    items.sort_by(|a, b| a.id.cmp(&b.id));
    items.dedup_by(|a, b| a.id == b.id);
}

fn forensic_item_to_json(item: &ForensicItem) -> Value {
    json!({
        "id": item.id,
        "kind": item.kind,
        "path": item.path,
        "language_hint": item.language_hint,
        "reason": item.reason,
    })
}

#[allow(dead_code)] // exercised by rust_census_yields_missing_kit_suggestion unit test only today
fn missing_kit_message_from_census(census: &WorkspaceCensus) -> Option<String> {
    let evidence = census.languages.first()?;
    Some(missing_kit_message(evidence))
}

fn missing_kit_message_for_language(census: &WorkspaceCensus, language: &str) -> Option<String> {
    census
        .languages
        .iter()
        .find(|evidence| evidence.language == language)
        .map(missing_kit_message)
}

fn missing_kit_message(evidence: &LanguageEvidence) -> String {
    let display_language = title_case_ascii(&evidence.language);
    format!(
        "{display_language} workspace detected at {}, but no Sugar {display_language} kit component claimed it. Try: apt install sugar-kit-{}, then try again.",
        evidence.path,
        evidence.language
    )
}

fn failed_component_message(component: &ComponentRegistration, error: &str) -> String {
    format!(
        "component `{}` failed while querying plan; manifest path: {}; command: {:?}; skipped component contribution: {error}",
        component.name,
        component.source.display(),
        component.command
    )
}

/// True when the plan RPC never started because the component binary is not
/// installed/built. Distinct from a crashed or protocol-broken component: the
/// contribution is simply absent. Must not hard-fail prove/lift when unused
/// optional components (e.g. ir-compiler-coq under examples-gate) are missing.
fn component_binary_unavailable(error: &str) -> bool {
    let lower = error.to_ascii_lowercase();
    lower.contains("no such file or directory")
        || lower.contains("os error 2")
        || lower.contains("the system cannot find the file")
        || lower.contains("cannot find the path specified")
        || (lower.contains("spawn ") && lower.contains("not found"))
}

fn title_case_ascii(value: &str) -> String {
    let mut chars = value.chars();
    let Some(first) = chars.next() else {
        return String::new();
    };
    let mut out = String::new();
    out.push(first.to_ascii_uppercase());
    out.extend(chars);
    out
}

/// Discover component manifests in precedence order: system roots, the user
/// root, ancestor project roots, then `SUGAR_COMPONENT_PATH`. Later roots
/// override earlier roots by component name; duplicate names inside a single
/// root are conflicts instead of precedence.
fn discover_components(project_root: &Path) -> DiscoveredComponents {
    let mut manifests = BTreeMap::<String, ComponentRegistration>::new();
    let mut diagnostics = Vec::new();
    for root in component_roots(project_root) {
        debug!(root = %root.display(), "component discovery root");
        let mut root_manifests = BTreeMap::<String, ComponentRegistration>::new();
        let mut root_collisions = BTreeMap::<String, Vec<PathBuf>>::new();
        for manifest_path in manifest_paths_under(&root) {
            match parse_component_manifest(&manifest_path) {
                Ok(component) => {
                    let name = component.name.clone();
                    if let Some(existing) = root_manifests.remove(&name) {
                        root_collisions
                            .entry(name)
                            .or_insert_with(|| vec![existing.source])
                            .push(component.source);
                    } else if let Some(paths) = root_collisions.get_mut(&name) {
                        paths.push(component.source);
                    } else {
                        root_manifests.insert(name, component);
                    }
                }
                Err(error) => {
                    warn!(
                        manifest = %manifest_path.display(),
                        error,
                        "skipping component manifest"
                    );
                }
            }
        }
        diagnostics.extend(
            root_collisions
                .iter()
                .map(|(name, paths)| same_root_component_collision_diagnostic(name, &root, paths)),
        );
        for (name, component) in root_manifests {
            if let Some(previous) = manifests.insert(name, component.clone()) {
                diagnostics.push(component_override_diagnostic(&previous, &component));
            }
        }
    }
    DiscoveredComponents {
        components: manifests.into_values().collect(),
        diagnostics,
    }
}

fn same_root_component_collision_diagnostic(
    name: &str,
    root: &Path,
    manifests: &[PathBuf],
) -> ComponentDiagnostic {
    let manifest_list = manifests
        .iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");
    ComponentDiagnostic {
        level: DiagnosticLevel::Error,
        message: format!(
            "component `{name}` is declared more than once in discovery root {}; colliding manifests: {manifest_list}; refusing ambiguous component registration",
            root.display()
        ),
    }
}

fn component_override_diagnostic(
    losing: &ComponentRegistration,
    winning: &ComponentRegistration,
) -> ComponentDiagnostic {
    let level = if manifests_carry_different_versions(losing, winning) {
        DiagnosticLevel::Warning
    } else {
        DiagnosticLevel::Info
    };
    ComponentDiagnostic {
        level,
        message: format!(
            "component `{}` discovery override: losing manifest {}; winning manifest {}; later discovery roots take precedence",
            winning.name,
            losing.source.display(),
            winning.source.display()
        ),
    }
}

fn manifests_carry_different_versions(
    losing: &ComponentRegistration,
    winning: &ComponentRegistration,
) -> bool {
    matches!(
        (&losing.version, &winning.version),
        (Some(losing_version), Some(winning_version)) if losing_version != winning_version
    )
}

fn component_roots(project_root: &Path) -> Vec<PathBuf> {
    // ONE DOOR for hermetic isolation: when `SUGAR_HOME` is set it is the
    // exclusive non-project install root. System paths, the binary's own
    // repo-relative kit tree, `~/.config/sugar/components`, and ancestor
    // project roots are all suppressed. Witness harnesses (and any other
    // caller that needs a private pool) point `SUGAR_HOME` at the staged
    // `project/.sugar` so mint/prove cannot see a sibling test's components
    // or a polluted checkout `.sugar`. Project-local components and an
    // explicit `SUGAR_COMPONENT_PATH` remain available so a staged project
    // can still declare its own surface and pin extra roots deliberately.
    if let Some(home) = std::env::var_os("SUGAR_HOME") {
        let mut roots = vec![
            PathBuf::from(home).join("components"),
            project_root.join(".sugar").join("components"),
        ];
        if let Some(paths) = std::env::var_os("SUGAR_COMPONENT_PATH") {
            roots.extend(std::env::split_paths(&paths));
        }
        return dedupe_paths(roots);
    }

    let mut roots = Vec::new();
    roots.extend(system_component_roots());
    roots.extend(exe_relative_component_roots());
    if let Some(home) = std::env::var_os("HOME") {
        roots.push(
            PathBuf::from(home)
                .join(".config")
                .join("sugar")
                .join("components"),
        );
    }
    roots.extend(ancestor_component_roots(project_root));
    if let Some(paths) = std::env::var_os("SUGAR_COMPONENT_PATH") {
        roots.extend(std::env::split_paths(&paths));
    }
    dedupe_paths(roots)
}

fn system_component_roots() -> Vec<PathBuf> {
    vec![
        PathBuf::from("/etc/sugar/components"),
        PathBuf::from("/usr/local/share/sugar/components"),
        PathBuf::from("/usr/share/sugar/components"),
    ]
}

/// THE ONE DOOR TEST fix: a raw `git clone <vendor>; cd <vendor>; sugar lift`
/// has no `.sugar/components` of its own and no ancestor that does either. The
/// kit components sugar ships (`.sugar/components/*` in this repo's own tree)
/// still exist; they were only ever discoverable relative to the WORKSPACE
/// being lifted, not relative to the running binary. A `sugar` binary built
/// from a checkout at `<repo>/implementations/rust/target/<profile>/sugar`
/// (the shape every sugarbin-published binary has) carries its own kit
/// components five directories up, at `<repo>/.sugar/components`. Walk that
/// path from `current_exe()` so any vendor tree gets the same kit discovery
/// a `sugar` run from inside this repo gets, with zero ceremony from the user.
fn exe_relative_component_roots() -> Vec<PathBuf> {
    let Ok(exe) = std::env::current_exe() else {
        return Vec::new();
    };
    // Canonicalize so symlinked binaries (e.g. a PATH shim into the shelf)
    // still resolve back to the real checkout that owns the components.
    let exe = std::fs::canonicalize(&exe).unwrap_or(exe);
    let mut roots = Vec::new();
    // <repo>/implementations/rust/target/<profile>/sugar -> <repo>
    if let Some(repo_root) = exe
        .parent() // <profile>/
        .and_then(Path::parent) // target/
        .and_then(Path::parent) // rust/
        .and_then(Path::parent) // implementations/
        .and_then(Path::parent)
    // <repo>
    {
        roots.push(repo_root.join(".sugar").join("components"));
    }
    // A relocatable install layout: components/ shipped next to the binary
    // (<install>/bin/sugar -> <install>/share/sugar/components).
    if let Some(install_root) = exe.parent().and_then(Path::parent) {
        roots.push(install_root.join("share").join("sugar").join("components"));
    }
    roots
}

fn ancestor_component_roots(project_root: &Path) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    let mut current = Some(project_root);
    while let Some(path) = current {
        roots.push(path.join(".sugar").join("components"));
        current = path.parent();
    }
    roots.reverse();
    roots
}

fn manifest_paths_under(root: &Path) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    let direct = root.join("manifest.toml");
    if direct.is_file() {
        paths.push(direct);
    }
    let Ok(entries) = std::fs::read_dir(root) else {
        return paths;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let manifest = path.join("manifest.toml");
            if manifest.is_file() {
                paths.push(manifest);
            }
        }
    }
    paths.sort();
    paths
}

fn parse_component_manifest(path: &Path) -> Result<ComponentRegistration, String> {
    let text = std::fs::read_to_string(path).map_err(|error| format!("read: {error}"))?;
    let source_cid = blake3_512_of(text.as_bytes());
    let manifest: ComponentManifest =
        toml::from_str(&text).map_err(|error| format!("invalid TOML: {error}"))?;
    if manifest.protocol_version != COMPONENT_PROTOCOL_VERSION {
        return Err(format!(
            "unsupported protocol_version `{}` (expected {COMPONENT_PROTOCOL_VERSION})",
            manifest.protocol_version
        ));
    }
    if manifest.name.trim().is_empty() {
        return Err("name must not be empty".to_string());
    }
    if manifest.command.is_empty() {
        return Err("command must not be empty".to_string());
    }
    let manifest_dir = path.parent().unwrap_or_else(|| Path::new("."));
    Ok(ComponentRegistration {
        name: manifest.name,
        version: manifest.version,
        protocol_version: manifest.protocol_version,
        command: manifest.command,
        working_dir: manifest.working_dir.map(|dir| {
            if dir.is_absolute() {
                dir
            } else {
                manifest_dir.join(dir)
            }
        }),
        source: path.to_path_buf(),
        source_cid,
    })
}

fn request_component_plan(
    component: &ComponentRegistration,
    project_root: &Path,
    census: &WorkspaceCensus,
    intent: PlanIntent,
) -> ComponentPlanOutcome {
    match request_component_plan_inner(component, project_root, census, intent) {
        Ok(ComponentPlanDecision::Claim(result)) => {
            let languages =
                languages_covered_by_plan(component, &result, &census_languages(census));
            ComponentPlanOutcome::Claimed { result, languages }
        }
        Ok(ComponentPlanDecision::Decline(decline)) => ComponentPlanOutcome::Declined {
            languages: decline.languages,
            reason: decline.reason,
        },
        Err(error) => ComponentPlanOutcome::Failed { error },
    }
}

fn request_component_plan_inner(
    component: &ComponentRegistration,
    project_root: &Path,
    census: &WorkspaceCensus,
    intent: PlanIntent,
) -> Result<ComponentPlanDecision, String> {
    let mut child = spawn_component(component)?;
    let outcome = (|| {
        let timeout = component_plan_timeout()?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| "component stdin unavailable".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "component stdout unavailable".to_string())?;
        let responses = spawn_response_reader(stdout);

        let init = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "client": {"name": "sugar-cli-component-planner", "version": env!("CARGO_PKG_VERSION")},
                "protocol_version": COMPONENT_PROTOCOL_VERSION,
            }
        });
        writeln!(stdin, "{init}").map_err(|error| format!("write initialize: {error}"))?;
        let _ = read_response_with_timeout(&responses, &mut child, 1, "initialize", timeout)?;

        let req = json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": COMPONENT_PLAN_RPC_METHOD,
            "params": {
                "workspace_root": project_root.display().to_string(),
                "project_forensics": {
                    "items": census.items.iter().map(forensic_item_to_json).collect::<Vec<_>>(),
                },
                "workspace_evidence": {
                    "languages": census.languages.iter().map(|language| json!({
                        "language": language.language,
                        "path": language.path,
                        "reason": language.reason,
                    })).collect::<Vec<_>>(),
                    "items": census.items.iter().map(forensic_item_to_json).collect::<Vec<_>>(),
                },
                "intent": intent.as_str(),
            }
        });
        writeln!(stdin, "{req}").map_err(|error| format!("write component plan: {error}"))?;
        let response = read_response_with_timeout(
            &responses,
            &mut child,
            2,
            COMPONENT_PLAN_RPC_METHOD,
            timeout,
        )?;

        let shutdown = json!({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "shutdown",
        });
        writeln!(stdin, "{shutdown}").map_err(|error| format!("write shutdown: {error}"))?;
        let _ = read_response_with_timeout(&responses, &mut child, 3, "shutdown", timeout)?;
        drop(stdin);
        let _ = child.wait();

        if let Some(error) = response.get("error") {
            if rpc_error_is_method_not_supported(error) {
                return Ok(ComponentPlanDecision::Decline(ComponentDecline::default()));
            }
            return Err(format!("component plan RPC error: {error}"));
        }
        let result = response.get("result").cloned().unwrap_or(Value::Null);
        parse_component_plan_result(component, result)
    })();
    if outcome.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    outcome
}

fn spawn_component(component: &ComponentRegistration) -> Result<Child, String> {
    const ETXTBSY: i32 = 26;
    const ATTEMPTS: usize = 5;
    const BACKOFF: std::time::Duration = std::time::Duration::from_millis(20);

    let mut last_etxtbsy = None;
    for attempt in 0..ATTEMPTS {
        let mut command = Command::new(&component.command[0]);
        command.args(&component.command[1..]);
        if let Some(working_dir) = &component.working_dir {
            command.current_dir(working_dir);
        }
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(error) if error.raw_os_error() == Some(ETXTBSY) && attempt + 1 < ATTEMPTS => {
                last_etxtbsy = Some(error);
                std::thread::sleep(BACKOFF);
            }
            Err(error) => return Err(format!("spawn {:?}: {error}", component.command)),
        }
    }
    Err(format!(
        "spawn {:?}: {}",
        component.command,
        last_etxtbsy
            .map(|error| error.to_string())
            .unwrap_or_else(|| "executable busy".to_string())
    ))
}

fn component_plan_timeout() -> Result<Duration, String> {
    let Some(raw) = std::env::var_os(COMPONENT_PLAN_TIMEOUT_ENV) else {
        return Ok(COMPONENT_PLAN_TIMEOUT);
    };
    let raw = raw
        .into_string()
        .map_err(|_| format!("{COMPONENT_PLAN_TIMEOUT_ENV} must be valid UTF-8"))?;
    let secs = raw.parse::<u64>().map_err(|error| {
        format!("invalid {COMPONENT_PLAN_TIMEOUT_ENV}={raw:?}: expected seconds: {error}")
    })?;
    if secs == 0 {
        return Err(format!(
            "invalid {COMPONENT_PLAN_TIMEOUT_ENV}={raw:?}: timeout must be at least 1s"
        ));
    }
    if secs >= 300 {
        return Err(format!(
            "invalid {COMPONENT_PLAN_TIMEOUT_ENV}={raw:?}: timeout must be less than 300s"
        ));
    }
    Ok(Duration::from_secs(secs))
}

fn spawn_response_reader(
    stdout: std::process::ChildStdout,
) -> mpsc::Receiver<Result<Value, String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        loop {
            match read_response(&mut reader) {
                Ok(value) => {
                    if tx.send(Ok(value)).is_err() {
                        break;
                    }
                }
                Err(error) => {
                    let _ = tx.send(Err(error));
                    break;
                }
            }
        }
    });
    rx
}

fn read_response_with_timeout(
    responses: &mpsc::Receiver<Result<Value, String>>,
    child: &mut Child,
    id: i64,
    exchange: &str,
    timeout: Duration,
) -> Result<Value, String> {
    let value = match responses.recv_timeout(timeout) {
        Ok(Ok(value)) => value,
        Ok(Err(error)) => return Err(format!("{exchange}: {error}")),
        Err(mpsc::RecvTimeoutError::Timeout) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "component plan RPC {exchange} timed out after {}s",
                timeout.as_secs()
            ));
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
            return Err(format!(
                "component response reader stopped before {exchange} response"
            ));
        }
    };
    if value.get("id").and_then(Value::as_i64) != Some(id) {
        return Err(format!("expected response id {id}, got {value}"));
    }
    Ok(value)
}

fn read_response(reader: &mut impl BufRead) -> Result<Value, String> {
    let mut line = String::new();
    let n = reader
        .read_line(&mut line)
        .map_err(|error| format!("read response: {error}"))?;
    if n == 0 {
        return Err("component closed stdout before responding".to_string());
    }
    let value: Value = serde_json::from_str(line.trim())
        .map_err(|error| format!("parse JSON-RPC response: {error}; raw={}", line.trim()))?;
    Ok(value)
}

fn rpc_error_is_method_not_supported(error: &Value) -> bool {
    let code = error.get("code").and_then(Value::as_i64);
    if code == Some(-32601) {
        return true;
    }
    if code != Some(-32602) {
        return false;
    }
    error
        .get("message")
        .and_then(Value::as_str)
        .map(|message| {
            let message = message.to_ascii_lowercase();
            message.contains("unknown method") && message.contains(COMPONENT_PLAN_RPC_METHOD)
        })
        .unwrap_or(false)
}

#[derive(Debug, Clone, Default)]
struct ComponentPlanResult {
    plugins: Vec<PluginEntry>,
    lift_manifests: Vec<PlannedLiftManifest>,
    ir_compilers: Vec<PlannedIrCompiler>,
    diagnostics: Vec<ComponentDiagnostic>,
}

fn parse_component_plan_result(
    component: &ComponentRegistration,
    value: Value,
) -> Result<ComponentPlanDecision, String> {
    let decision = value
        .get("decision")
        .and_then(Value::as_str)
        .unwrap_or("claim");
    match decision {
        "decline" => {
            return Ok(ComponentPlanDecision::Decline(
                component_decline_from_value(&value),
            ))
        }
        "claim" => {}
        "refuse" => {
            let mut decline = component_decline_from_value(&value);
            if decline.reason.is_none() {
                decline.reason = Some("component refused workspace".to_string());
            }
            return Ok(ComponentPlanDecision::Decline(decline));
        }
        other => return Err(format!("invalid component decision `{other}`")),
    }

    let plugins = value
        .get("plugins")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(plugin_entry_from_value)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let lift_manifests = value
        .get("lift_manifests")
        .or_else(|| value.get("liftManifests"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| planned_lift_manifest_from_value(component, item))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let ir_compilers = value
        .get("ir_compilers")
        .or_else(|| value.get("irCompilers"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| planned_ir_compiler_from_value(component, item))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let diagnostics = value
        .get("diagnostics")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(diagnostic_from_value).collect())
        .unwrap_or_default();
    Ok(ComponentPlanDecision::Claim(ComponentPlanResult {
        plugins,
        lift_manifests,
        ir_compilers,
        diagnostics,
    }))
}

fn component_decline_from_value(value: &Value) -> ComponentDecline {
    ComponentDecline {
        languages: explicit_languages_from_value(value),
        reason: string_field(value, "reason"),
    }
}

fn plugin_entry_from_value(value: &Value) -> Option<PluginEntry> {
    let surface = value.get("surface").and_then(Value::as_str)?.to_string();
    Some(PluginEntry {
        name: string_field(value, "name"),
        kind: string_field(value, "kind"),
        surface,
        workspace_override: string_field(value, "workspace_override")
            .or_else(|| string_field(value, "workspaceOverride")),
        emit: string_field(value, "emit"),
        layer: string_field(value, "layer"),
    })
}

fn planned_lift_manifest_from_value(
    component: &ComponentRegistration,
    value: &Value,
) -> Option<PlannedLiftManifest> {
    let surface = value.get("surface").and_then(Value::as_str)?.to_string();
    let command = string_array_field(value, "command");
    if command.is_empty() {
        warn!(
            component = component.name,
            surface, "component returned a lift manifest without a command"
        );
        return None;
    }
    Some(PlannedLiftManifest {
        surface,
        name: string_field(value, "name").unwrap_or_else(|| component.name.clone()),
        version: string_field(value, "version"),
        protocol_version: string_field(value, "protocol_version")
            .or_else(|| string_field(value, "protocolVersion")),
        command,
        working_dir: string_field(value, "working_dir")
            .or_else(|| string_field(value, "workingDir"))
            .map(PathBuf::from),
        method: string_field(value, "method"),
        phase: string_field(value, "phase"),
        discharge_command: string_array_field(value, "discharge_command")
            .or_else_empty(|| string_array_field(value, "dischargeCommand")),
        witness_tool: string_field(value, "witness_tool")
            .or_else(|| string_field(value, "witnessTool")),
        resolve_witness_command: string_array_field(value, "resolve_witness_command")
            .or_else_empty(|| string_array_field(value, "resolveWitnessCommand")),
        resolve_witness_method: string_field(value, "resolve_witness_method")
            .or_else(|| string_field(value, "resolveWitnessMethod")),
    })
}

fn planned_ir_compiler_from_value(
    component: &ComponentRegistration,
    value: &Value,
) -> Option<PlannedIrCompiler> {
    let command = string_array_field(value, "command");
    if command.is_empty() {
        warn!(
            component = component.name,
            "component returned an IR compiler without a command"
        );
        return None;
    }
    let dialects = string_array_field(value, "dialects");
    if dialects.is_empty() {
        warn!(
            component = component.name,
            "component returned an IR compiler without dialects"
        );
        return None;
    }
    Some(PlannedIrCompiler {
        name: string_field(value, "name").unwrap_or_else(|| component.name.clone()),
        version: string_field(value, "version"),
        protocol_version: string_field(value, "protocol_version")
            .or_else(|| string_field(value, "protocolVersion"))
            .unwrap_or_else(|| IR_COMPILER_PROTOCOL_VERSION.to_string()),
        command,
        working_dir: string_field(value, "working_dir")
            .or_else(|| string_field(value, "workingDir"))
            .map(PathBuf::from),
        dialects,
        supported_sorts: string_array_field(value, "supported_sorts")
            .or_else_empty(|| string_array_field(value, "supportedSorts")),
        supported_predicates: string_array_field(value, "supported_predicates")
            .or_else_empty(|| string_array_field(value, "supportedPredicates")),
    })
}

trait VecStringExt {
    fn or_else_empty(self, f: impl FnOnce() -> Vec<String>) -> Vec<String>;
}

impl VecStringExt for Vec<String> {
    fn or_else_empty(self, f: impl FnOnce() -> Vec<String>) -> Vec<String> {
        if self.is_empty() {
            f()
        } else {
            self
        }
    }
}

fn diagnostic_from_value(value: &Value) -> Option<ComponentDiagnostic> {
    let message = value.get("message").and_then(Value::as_str)?.to_string();
    let level = match value
        .get("level")
        .and_then(Value::as_str)
        .unwrap_or("warning")
    {
        "info" => DiagnosticLevel::Info,
        "error" => DiagnosticLevel::Error,
        _ => DiagnosticLevel::Warning,
    };
    Some(ComponentDiagnostic { level, message })
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_string)
        .filter(|value| !value.is_empty())
}

fn string_array_field(value: &Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .filter(|item| !item.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn census_languages(census: &WorkspaceCensus) -> BTreeSet<String> {
    census
        .languages
        .iter()
        .map(|evidence| normalize_language(&evidence.language))
        .filter(|language| !language.is_empty())
        .collect()
}

fn normalize_language(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn explicit_languages_from_value(value: &Value) -> BTreeSet<String> {
    let mut languages = BTreeSet::new();
    for key in ["language", "surface"] {
        if let Some(value) = string_field(value, key) {
            insert_language_tokens(&mut languages, &value);
        }
    }
    for key in ["languages", "surfaces"] {
        for value in string_array_field(value, key) {
            insert_language_tokens(&mut languages, &value);
        }
    }
    languages
}

fn languages_covered_by_plan(
    component: &ComponentRegistration,
    result: &ComponentPlanResult,
    known_languages: &BTreeSet<String>,
) -> BTreeSet<String> {
    let mut texts = Vec::new();
    texts.push(component.name.clone());
    texts.push(component.source.display().to_string());
    texts.extend(component.command.iter().cloned());
    for plugin in &result.plugins {
        push_optional_text(&mut texts, &plugin.name);
        push_optional_text(&mut texts, &plugin.kind);
        texts.push(plugin.surface.clone());
        push_optional_text(&mut texts, &plugin.workspace_override);
        push_optional_text(&mut texts, &plugin.emit);
        push_optional_text(&mut texts, &plugin.layer);
    }
    for manifest in &result.lift_manifests {
        texts.push(manifest.surface.clone());
        texts.push(manifest.name.clone());
        texts.extend(manifest.command.iter().cloned());
        push_optional_text(&mut texts, &manifest.method);
        push_optional_text(&mut texts, &manifest.phase);
    }
    for compiler in &result.ir_compilers {
        texts.push(compiler.name.clone());
        texts.extend(compiler.command.iter().cloned());
        texts.extend(compiler.dialects.iter().cloned());
    }
    languages_covered_by_texts(known_languages, &texts)
}

fn push_optional_text(texts: &mut Vec<String>, value: &Option<String>) {
    if let Some(value) = value {
        texts.push(value.clone());
    }
}

fn languages_covered_by_texts(
    known_languages: &BTreeSet<String>,
    texts: &[String],
) -> BTreeSet<String> {
    known_languages
        .iter()
        .filter(|language| {
            texts
                .iter()
                .any(|text| text_covers_language(text, language))
        })
        .cloned()
        .collect()
}

fn text_covers_language(text: &str, language: &str) -> bool {
    text.split(|ch: char| !ch.is_ascii_alphanumeric())
        .filter(|token| !token.is_empty())
        .any(|token| language_token_matches(&token.to_ascii_lowercase(), language))
}

fn insert_language_tokens(languages: &mut BTreeSet<String>, value: &str) {
    for token in value
        .split(|ch: char| !ch.is_ascii_alphanumeric())
        .filter(|token| !token.is_empty())
    {
        languages.insert(token.to_ascii_lowercase());
    }
}

fn language_token_matches(token: &str, language: &str) -> bool {
    if token == language {
        return true;
    }
    token
        .strip_prefix(language)
        .is_some_and(|suffix| !suffix.is_empty() && suffix.chars().all(|ch| ch.is_ascii_digit()))
}

fn dedupe_plugins(plugins: &mut Vec<PluginEntry>) {
    let mut seen = BTreeSet::new();
    plugins.retain(|plugin| {
        seen.insert((
            plugin.kind.clone().unwrap_or_default(),
            plugin.surface.clone(),
            plugin.name.clone().unwrap_or_default(),
        ))
    });
}

fn order_component_plugins(plugins: &mut [PluginEntry]) {
    plugins.sort_by_key(|plugin| {
        (
            component_plugin_order(&plugin.surface),
            plugin.surface.clone(),
            plugin.name.clone().unwrap_or_default(),
        )
    });
}

fn component_plugin_order(surface: &str) -> u8 {
    match surface {
        "rust-test-assertions" => 10,
        "rust-fn-contracts" => 20,
        "rust-implications" => 30,
        "rust-cargo-test-witness" => 40,
        _ if surface.contains("witness") => 40,
        _ if surface.contains("implication") => 30,
        _ => 20,
    }
}

fn dedupe_manifests(manifests: &mut Vec<PlannedLiftManifest>) {
    let mut seen = BTreeSet::new();
    manifests.retain(|manifest| {
        seen.insert((
            manifest.surface.clone(),
            manifest.name.clone(),
            manifest.command.clone(),
        ))
    });
}

fn dedupe_ir_compilers(compilers: &mut Vec<PlannedIrCompiler>) {
    let mut seen = BTreeSet::new();
    compilers.retain(|compiler| {
        seen.insert((
            compiler.name.clone(),
            compiler.command.clone(),
            compiler.dialects.clone(),
        ))
    });
}

fn dedupe_paths(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for path in paths {
        if seen.insert(path.clone()) {
            out.push(path);
        }
    }
    out
}

fn absolute_path(path: &Path) -> PathBuf {
    if path.is_absolute() {
        return path.to_path_buf();
    }
    std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join(path)
}

#[allow(dead_code)] // called by planned ir-compiler path and witness_verify in the binary module tree
pub(crate) fn resolve_project_relative_working_dir(
    project_root: &Path,
    working_dir: Option<&PathBuf>,
) -> Option<PathBuf> {
    working_dir.map(|working_dir| {
        if working_dir.is_absolute() {
            working_dir.clone()
        } else {
            project_root.join(working_dir)
        }
    })
}

#[allow(dead_code)] // called by cmd_prove plan-artifact mint in the binary module tree + plan-artifact unit tests
pub(crate) fn plan_artifact_memento(
    project_root: &Path,
    intent: PlanIntent,
    options: ComponentPlanOptions,
    plan: &ComponentPlan,
) -> Option<PlanArtifactMemento> {
    if !plan_affects_run(plan) {
        return None;
    }
    let body = plan_artifact_body(project_root, intent, options, plan);
    let plan_cid = jcs_cid(&body);
    let envelope = json!({
        "body": body,
        "header": {
            "kind": "plan-memento",
            "planCid": plan_cid,
        },
        "schemaVersion": "1",
    });
    let member_bytes = jcs_bytes(&envelope).into_bytes();
    let member_cid = blake3_512_of(&member_bytes);
    Some(PlanArtifactMemento {
        plan_cid,
        member_cid,
        member_bytes,
    })
}

#[allow(dead_code)] // called by plan-artifact unit tests; cmd_prove threads PlanArtifactMemento through it
pub(crate) fn plan_workspace_for_replay(
    project_root: &Path,
    intent: PlanIntent,
    options: ComponentPlanOptions,
    artifact: Option<&PlanArtifactMemento>,
) -> Result<ComponentPlan, String> {
    match artifact {
        Some(artifact) => component_plan_from_plan_artifact(artifact),
        None => Ok(plan_workspace_with_options(project_root, intent, options)),
    }
}

#[allow(dead_code)] // used when minting PlanArtifactMemento component source_cid (cmd_prove binary + unit tests)
pub(crate) fn file_bytes_cid(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|error| {
        format!(
            "PlanArtifact construction refusal: crime=read-selected-component; owner=component-plan seam; shape=component manifest `{}`; replacement=pin only readable selected component manifest bytes; error={error}",
            path.display()
        )
    })?;
    Ok(blake3_512_of(&bytes))
}

#[allow(dead_code)] // private helper of plan_artifact_memento (cmd_prove binary + unit tests)
fn plan_affects_run(plan: &ComponentPlan) -> bool {
    !(plan.selected_components.is_empty()
        && plan.plugins.is_empty()
        && plan.lift_manifests.is_empty()
        && plan.ir_compilers.is_empty())
}

#[allow(dead_code)] // private helper of plan_artifact_memento (cmd_prove binary + unit tests)
fn plan_artifact_body(
    project_root: &Path,
    intent: PlanIntent,
    options: ComponentPlanOptions,
    plan: &ComponentPlan,
) -> Value {
    json!({
        "kind": "component-plan-artifact",
        "schemaVersion": "1",
        "selectionInputs": {
            "projectRoot": absolute_path(project_root).display().to_string(),
            "intent": intent.as_str(),
            "allowFailedComponents": options.allow_failed_components,
        },
        "selectedComponents": plan
            .selected_components
            .iter()
            .map(planned_component_to_value)
            .collect::<Vec<_>>(),
        "plugins": plan.plugins.iter().map(plugin_entry_to_value).collect::<Vec<_>>(),
        "liftManifests": plan
            .lift_manifests
            .iter()
            .map(planned_lift_manifest_to_value)
            .collect::<Vec<_>>(),
        "irCompilers": plan
            .ir_compilers
            .iter()
            .map(planned_ir_compiler_to_value)
            .collect::<Vec<_>>(),
        "diagnostics": plan
            .diagnostics
            .iter()
            .map(component_diagnostic_to_value)
            .collect::<Vec<_>>(),
        "census": workspace_census_to_value(&plan.census),
    })
}

#[allow(dead_code)] // private helper of plan_workspace_for_replay (cmd_prove binary + unit tests)
fn component_plan_from_plan_artifact(
    artifact: &PlanArtifactMemento,
) -> Result<ComponentPlan, String> {
    let mut graph = sugar_proof_envelope::ProofGraph::new();
    graph
        .push_plan_member_bytes(artifact.member_bytes.clone())
        .map_err(|error| match error {
            sugar_proof_envelope::PlanMemberBytesError::InvalidJson(error) => {
                plan_artifact_replay_refusal(
                    "invalid-json",
                    &format!("PlanArtifact member bytes failed JSON decode: {error}"),
                    "use plan_artifact_memento to mint canonical plan-memento bytes",
                )
            }
            sugar_proof_envelope::PlanMemberBytesError::WrongKind => plan_artifact_replay_refusal(
                "wrong-member-kind",
                "PlanArtifact replay member header kind is not `plan-memento`",
                "pass the plan-memento envelope minted by component_plan::plan_artifact_memento",
            ),
        })?;
    let plan_member = graph.plans().next().ok_or_else(|| {
        plan_artifact_replay_refusal(
            "wrong-member-kind",
            "PlanArtifact replay member header kind is not `plan-memento`",
            "pass the plan-memento envelope minted by component_plan::plan_artifact_memento",
        )
    })?;
    let member_json = plan_member.json();
    let body = member_json.get("body").ok_or_else(|| {
        plan_artifact_replay_refusal(
            "missing-body",
            "PlanArtifact replay member has no body",
            "pass the complete plan-memento envelope, not just a header",
        )
    })?;
    if body.get("kind").and_then(Value::as_str) != Some("component-plan-artifact") {
        return Err(plan_artifact_replay_refusal(
            "wrong-plan-body-kind",
            "PlanArtifact body kind is not `component-plan-artifact`",
            "use a component-plan-artifact body for component-plan replay",
        ));
    }
    let recomputed_plan_cid = jcs_cid(body);
    let header_plan_cid = plan_member.field("planCid").ok_or_else(|| {
        plan_artifact_replay_refusal(
            "missing-plan-cid",
            "PlanArtifact header lacks planCid",
            "mint a plan-memento whose header planCid addresses the body",
        )
    })?;
    if header_plan_cid.as_str() != recomputed_plan_cid {
        return Err(plan_artifact_replay_refusal(
            "plan-cid-mismatch",
            "PlanArtifact header planCid does not address the JCS body",
            "re-mint the PlanArtifact from the selected ComponentPlan instead of editing bytes",
        ));
    }
    if artifact.plan_cid != recomputed_plan_cid {
        return Err(plan_artifact_replay_refusal(
            "typed-plan-cid-mismatch",
            "PlanArtifact typed carrier plan_cid disagrees with member body",
            "thread the PlanArtifactMemento returned by plan_artifact_memento without rewriting fields",
        ));
    }
    let recomputed_member_cid = blake3_512_of(&artifact.member_bytes);
    if artifact.member_cid != recomputed_member_cid {
        return Err(plan_artifact_replay_refusal(
            "member-cid-mismatch",
            "PlanArtifact typed carrier member_cid disagrees with member bytes",
            "thread the PlanArtifactMemento returned by plan_artifact_memento without rewriting fields",
        ));
    }

    plan_from_artifact_body(body)
}

#[allow(dead_code)] // private helper of component_plan_from_plan_artifact (cmd_prove binary + unit tests)
fn plan_from_artifact_body(body: &Value) -> Result<ComponentPlan, String> {
    let selected_components = array_field(body, "selectedComponents")
        .iter()
        .map(planned_component_from_value)
        .collect::<Result<Vec<_>, _>>()?;
    let plugins = array_field(body, "plugins")
        .iter()
        .map(plugin_entry_from_artifact_value)
        .collect::<Result<Vec<_>, _>>()?;
    let lift_manifests = array_field(body, "liftManifests")
        .iter()
        .map(planned_lift_manifest_from_artifact_value)
        .collect::<Result<Vec<_>, _>>()?;
    let ir_compilers = array_field(body, "irCompilers")
        .iter()
        .map(planned_ir_compiler_from_artifact_value)
        .collect::<Result<Vec<_>, _>>()?;
    let diagnostics = array_field(body, "diagnostics")
        .iter()
        .filter_map(diagnostic_from_value)
        .collect::<Vec<_>>();
    let census = body
        .get("census")
        .map(workspace_census_from_value)
        .transpose()?
        .unwrap_or_default();
    Ok(ComponentPlan {
        plugins,
        lift_manifests,
        ir_compilers,
        diagnostics,
        census,
        selected_components,
    })
}

#[allow(dead_code)] // private helper of plan-artifact replay refusal path (unit tests)
fn plan_artifact_replay_refusal(crime: &str, shape: &str, replacement: &str) -> String {
    format!(
        "PlanArtifact replay refusal: crime={crime}; owner=component-plan seam; shape={shape}; replacement={replacement}"
    )
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn planned_component_to_value(component: &PlannedComponent) -> Value {
    json!({
        "name": component.name,
        "version": component.version,
        "protocolVersion": component.protocol_version,
        "command": component.command,
        "workingDir": component.working_dir.as_ref().map(|path| path.display().to_string()),
        "source": component.source.display().to_string(),
        "sourceCid": component.source_cid,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn planned_component_from_value(value: &Value) -> Result<PlannedComponent, String> {
    Ok(PlannedComponent {
        name: required_string(value, "name", "selected component")?,
        version: string_field(value, "version"),
        protocol_version: required_string(value, "protocolVersion", "selected component")?,
        command: string_array_field(value, "command"),
        working_dir: string_field(value, "workingDir").map(PathBuf::from),
        source: PathBuf::from(required_string(value, "source", "selected component")?),
        source_cid: required_string(value, "sourceCid", "selected component")?,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn plugin_entry_to_value(plugin: &PluginEntry) -> Value {
    json!({
        "name": plugin.name,
        "kind": plugin.kind,
        "surface": plugin.surface,
        "workspaceOverride": plugin.workspace_override,
        "emit": plugin.emit,
        "layer": plugin.layer,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn plugin_entry_from_artifact_value(value: &Value) -> Result<PluginEntry, String> {
    Ok(PluginEntry {
        name: string_field(value, "name"),
        kind: string_field(value, "kind"),
        surface: required_string(value, "surface", "PlanArtifact plugin")?,
        workspace_override: string_field(value, "workspaceOverride"),
        emit: string_field(value, "emit"),
        layer: string_field(value, "layer"),
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn planned_lift_manifest_to_value(manifest: &PlannedLiftManifest) -> Value {
    json!({
        "surface": manifest.surface,
        "name": manifest.name,
        "version": manifest.version,
        "protocolVersion": manifest.protocol_version,
        "command": manifest.command,
        "workingDir": manifest.working_dir.as_ref().map(|path| path.display().to_string()),
        "method": manifest.method,
        "phase": manifest.phase,
        "dischargeCommand": manifest.discharge_command,
        "witnessTool": manifest.witness_tool,
        "resolveWitnessCommand": manifest.resolve_witness_command,
        "resolveWitnessMethod": manifest.resolve_witness_method,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn planned_lift_manifest_from_artifact_value(value: &Value) -> Result<PlannedLiftManifest, String> {
    Ok(PlannedLiftManifest {
        surface: required_string(value, "surface", "PlanArtifact lift manifest")?,
        name: required_string(value, "name", "PlanArtifact lift manifest")?,
        version: string_field(value, "version"),
        protocol_version: string_field(value, "protocolVersion"),
        command: string_array_field(value, "command"),
        working_dir: string_field(value, "workingDir").map(PathBuf::from),
        method: string_field(value, "method"),
        phase: string_field(value, "phase"),
        discharge_command: string_array_field(value, "dischargeCommand"),
        witness_tool: string_field(value, "witnessTool"),
        resolve_witness_command: string_array_field(value, "resolveWitnessCommand"),
        resolve_witness_method: string_field(value, "resolveWitnessMethod"),
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn planned_ir_compiler_to_value(compiler: &PlannedIrCompiler) -> Value {
    json!({
        "name": compiler.name,
        "version": compiler.version,
        "protocolVersion": compiler.protocol_version,
        "command": compiler.command,
        "workingDir": compiler.working_dir.as_ref().map(|path| path.display().to_string()),
        "dialects": compiler.dialects,
        "supportedSorts": compiler.supported_sorts,
        "supportedPredicates": compiler.supported_predicates,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn planned_ir_compiler_from_artifact_value(value: &Value) -> Result<PlannedIrCompiler, String> {
    Ok(PlannedIrCompiler {
        name: required_string(value, "name", "PlanArtifact IR compiler")?,
        version: string_field(value, "version"),
        protocol_version: required_string(value, "protocolVersion", "PlanArtifact IR compiler")?,
        command: string_array_field(value, "command"),
        working_dir: string_field(value, "workingDir").map(PathBuf::from),
        dialects: string_array_field(value, "dialects"),
        supported_sorts: string_array_field(value, "supportedSorts"),
        supported_predicates: string_array_field(value, "supportedPredicates"),
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn component_diagnostic_to_value(diagnostic: &ComponentDiagnostic) -> Value {
    json!({
        "level": match diagnostic.level {
            DiagnosticLevel::Info => "info",
            DiagnosticLevel::Warning => "warning",
            DiagnosticLevel::Error => "error",
        },
        "message": diagnostic.message,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn workspace_census_to_value(census: &WorkspaceCensus) -> Value {
    json!({
        "languages": census.languages.iter().map(language_evidence_to_value).collect::<Vec<_>>(),
        "items": census.items.iter().map(forensic_item_to_value).collect::<Vec<_>>(),
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn workspace_census_from_value(value: &Value) -> Result<WorkspaceCensus, String> {
    Ok(WorkspaceCensus {
        languages: array_field(value, "languages")
            .iter()
            .map(language_evidence_from_value)
            .collect::<Result<Vec<_>, _>>()?,
        items: array_field(value, "items")
            .iter()
            .map(forensic_item_from_value)
            .collect::<Result<Vec<_>, _>>()?,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn language_evidence_to_value(evidence: &LanguageEvidence) -> Value {
    json!({
        "language": evidence.language,
        "path": evidence.path,
        "reason": evidence.reason,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn language_evidence_from_value(value: &Value) -> Result<LanguageEvidence, String> {
    Ok(LanguageEvidence {
        language: required_string(value, "language", "PlanArtifact census language")?,
        path: required_string(value, "path", "PlanArtifact census language")?,
        reason: required_string(value, "reason", "PlanArtifact census language")?,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_artifact_body (cmd_prove binary + unit tests)
fn forensic_item_to_value(item: &ForensicItem) -> Value {
    json!({
        "id": item.id,
        "kind": item.kind,
        "path": item.path,
        "languageHint": item.language_hint,
        "reason": item.reason,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn forensic_item_from_value(value: &Value) -> Result<ForensicItem, String> {
    Ok(ForensicItem {
        id: required_string(value, "id", "PlanArtifact census item")?,
        kind: required_string(value, "kind", "PlanArtifact census item")?,
        path: required_string(value, "path", "PlanArtifact census item")?,
        language_hint: string_field(value, "languageHint"),
        reason: required_string(value, "reason", "PlanArtifact census item")?,
    })
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn array_field<'a>(value: &'a Value, key: &str) -> &'a [Value] {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}

#[allow(dead_code)] // PlanArtifact serde helper for plan_from_artifact_body (cmd_prove binary + unit tests)
fn required_string(value: &Value, key: &str, shape: &str) -> Result<String, String> {
    string_field(value, key).ok_or_else(|| {
        plan_artifact_replay_refusal(
            "missing-required-field",
            &format!("{shape} missing `{key}`"),
            "replay from a complete PlanArtifact minted by component_plan::plan_artifact_memento",
        )
    })
}

#[allow(dead_code)] // PlanArtifact + report_witness JCS helper (cmd_prove binary + unit tests)
fn jcs_cid(value: &Value) -> String {
    blake3_512_of(jcs_bytes(value).as_bytes())
}

#[allow(dead_code)] // PlanArtifact JCS helper for plan_artifact_memento (cmd_prove binary + unit tests)
fn jcs_bytes(value: &Value) -> String {
    encode_jcs(json_to_cvalue(value).as_ref())
}

/// #3901: shared refuse door with mint/feed (no float→string dual).
#[allow(dead_code)] // JCS helper shared by plan-artifact path and report_witness (cmd_prove binary)
fn json_to_cvalue(value: &Value) -> Arc<CValue> {
    json_to_value(value).unwrap_or_else(|err| {
        panic!(
            "component_plan json_to_cvalue: {err} — non-integer JSON number cannot \
             enter a content-addressed plan artifact; use sugar_canonicalizer::json_to_value"
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value as Json;
    use std::ffi::{OsStr, OsString};
    use std::sync::Mutex;
    use sugar_ir_compiler::{
        CompileError, CompiledFormula, CompilerInput, FreeVar, IrCompiler, OpacityManifest,
    };

    static TEST_ENV_LOCK: Mutex<()> = Mutex::new(());

    struct EnvGuard {
        key: &'static str,
        previous: Option<OsString>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: impl AsRef<OsStr>) -> Self {
            let previous = std::env::var_os(key);
            std::env::set_var(key, value);
            Self { key, previous }
        }

        fn remove(key: &'static str) -> Self {
            let previous = std::env::var_os(key);
            std::env::remove_var(key);
            Self { key, previous }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            if let Some(previous) = self.previous.take() {
                std::env::set_var(self.key, previous);
            } else {
                std::env::remove_var(self.key);
            }
        }
    }

    struct TestCompiler {
        dialect: String,
    }

    impl IrCompiler for TestCompiler {
        fn compile_typed(
            &self,
            _ir: &sugar_ir_compiler::CompilerInput,
            dialect: &str,
        ) -> Result<CompiledFormula, CompileError> {
            if dialect != self.dialect {
                return Err(CompileError::UnsupportedDialect(dialect.to_string()));
            }
            Ok(CompiledFormula {
                preamble: "; original\n".to_string(),
                body: "(check-sat)\n".to_string(),
                free_vars: vec![FreeVar {
                    name: "x".to_string(),
                    sort: "Int".to_string(),
                }],
                opacity_manifest: OpacityManifest::default(),
                metadata: Json::Null,
            })
        }

        fn capabilities(&self) -> Capabilities {
            Capabilities {
                name: "original".to_string(),
                version: "0.1.0".to_string(),
                protocol_version: IR_COMPILER_PROTOCOL_VERSION.to_string(),
                dialects: vec![self.dialect.clone()],
                supported_sorts: vec!["Int".to_string()],
                supported_predicates: vec!["=".to_string()],
            }
        }
    }

    fn write_claiming_component(
        root: &Path,
        dir_name: &str,
        component_name: &str,
        surface: &str,
        version: Option<&str>,
    ) -> PathBuf {
        let component_dir = root.join(dir_name);
        std::fs::create_dir_all(&component_dir).unwrap();
        let script = component_dir.join("component.sh");
        let manifest = component_dir.join("manifest.toml");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
set -eu
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{{"jsonrpc":"2.0","id":1,"result":{{"name":"{component_name}","protocol_version":"sugar-component/1","capabilities":{{}}}}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{{"jsonrpc":"2.0","id":2,"result":{{"decision":"claim","plugins":[{{"name":"{surface}-lift","kind":"lift","surface":"{surface}","emit":"ir-document"}}],"diagnostics":[]}}}}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{{"jsonrpc":"2.0","id":3,"result":null}}'
      exit 0
      ;;
  esac
done
"#,
            ),
        );
        let version_line = version
            .map(|version| format!("version = \"{version}\"\n"))
            .unwrap_or_default();
        std::fs::write(
            &manifest,
            format!(
                "name = \"{component_name}\"\n{version_line}protocol_version = \"sugar-component/1\"\ncommand = [\"sh\", \"{}\"]\n",
                script.display()
            ),
        )
        .unwrap();
        manifest
    }

    fn write_executable(path: &Path, contents: &str) {
        {
            let mut file = std::fs::File::create(path).unwrap();
            file.write_all(contents.as_bytes()).unwrap();
            file.sync_all().unwrap();
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut permissions = std::fs::metadata(path).unwrap().permissions();
            permissions.set_mode(0o755);
            std::fs::set_permissions(path, permissions).unwrap();
        }
    }

    fn plan_with_component_path(
        project: &Path,
        component_path: impl AsRef<OsStr>,
    ) -> ComponentPlan {
        let _env_lock = TEST_ENV_LOCK.lock().unwrap();
        let _home = EnvGuard::set("HOME", project.join("home"));
        // Tests that exercise multi-root discovery must not inherit a host
        // SUGAR_HOME, which would collapse discovery to the exclusive door.
        let _sugar_home = EnvGuard::remove("SUGAR_HOME");
        let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", component_path);
        let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");
        plan_workspace(project, PlanIntent::Lift)
    }

    #[test]
    fn sugar_home_is_exclusive_component_discovery_door() {
        let project = tempfile::tempdir().unwrap();
        let sugar_home = tempfile::tempdir().unwrap();
        let leaked = tempfile::tempdir().unwrap();

        // Staged project-local component (the harness shape).
        write_claiming_component(
            &project.path().join(".sugar").join("components"),
            "project-local",
            "project-kit",
            "project",
            None,
        );
        // Exclusive home component.
        write_claiming_component(
            &sugar_home.path().join("components"),
            "home-kit",
            "home-kit",
            "home",
            None,
        );
        // Would leak under multi-root discovery (exe-relative / SUGAR_COMPONENT_PATH
        // sibling pollution). Must be invisible when SUGAR_HOME is set.
        write_claiming_component(leaked.path(), "leaked", "leaked-kit", "leaked", None);

        let _env_lock = TEST_ENV_LOCK.lock().unwrap();
        let _home = EnvGuard::set("HOME", project.path().join("home"));
        let _sugar_home = EnvGuard::set("SUGAR_HOME", sugar_home.path());
        let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", leaked.path());
        let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

        // With SUGAR_HOME set, SUGAR_COMPONENT_PATH is still deliberate and
        // wins for same-name collisions — but the point of this test is that
        // system/exe/ancestor roots are gone. Assert the planned components
        // are exactly the exclusive set (home + project-local + explicit path).
        let roots = component_roots(project.path());
        let root_set: std::collections::BTreeSet<_> = roots.iter().cloned().collect();
        assert!(
            root_set.contains(&sugar_home.path().join("components")),
            "SUGAR_HOME/components must be a discovery root: {roots:?}"
        );
        assert!(
            root_set.contains(&project.path().join(".sugar").join("components")),
            "project-local components must remain: {roots:?}"
        );
        assert!(
            root_set.contains(&leaked.path().to_path_buf()),
            "explicit SUGAR_COMPONENT_PATH remains available: {roots:?}"
        );
        // No ambient system / config / ancestor pollution beyond the exclusive set.
        assert_eq!(
            roots.len(),
            3,
            "exclusive door must not pull system/exe/ancestor roots: {roots:?}"
        );
    }

    #[test]
    fn later_root_override_emits_diagnostic() {
        let project = tempfile::tempdir().unwrap();
        let early_root = tempfile::tempdir().unwrap();
        let late_root = tempfile::tempdir().unwrap();
        let losing = write_claiming_component(
            early_root.path(),
            "component",
            "collision-kit",
            "early",
            None,
        );
        let winning =
            write_claiming_component(late_root.path(), "component", "collision-kit", "late", None);
        let component_path = std::env::join_paths([early_root.path(), late_root.path()]).unwrap();

        let plan = plan_with_component_path(project.path(), component_path);

        assert!(
            plan.plugins.iter().any(|plugin| plugin.surface == "late"),
            "later root should win the component-name override: {:?}",
            plan.plugins
        );
        assert!(
            !plan.plugins.iter().any(|plugin| plugin.surface == "early"),
            "earlier root should be replaced by later root: {:?}",
            plan.plugins
        );
        let diagnostic = plan
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.message.contains("collision-kit"))
            .unwrap_or_else(|| panic!("missing override diagnostic: {:?}", plan.diagnostics));
        assert_eq!(diagnostic.level, DiagnosticLevel::Info);
        assert!(
            diagnostic.message.contains(&losing.display().to_string())
                && diagnostic.message.contains(&winning.display().to_string()),
            "diagnostic should name losing and winning manifests: {:?}",
            diagnostic
        );
    }

    #[test]
    fn same_root_collision_is_an_error() {
        let project = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        let first = write_claiming_component(root.path(), "first", "collision-kit", "first", None);
        let second =
            write_claiming_component(root.path(), "second", "collision-kit", "second", None);

        let plan = plan_with_component_path(project.path(), root.path());

        assert!(
            !plan
                .plugins
                .iter()
                .any(|plugin| plugin.surface == "first" || plugin.surface == "second"),
            "same-root component-name collision should refuse that component: {:?}",
            plan.plugins
        );
        let diagnostic = plan
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.message.contains("collision-kit"))
            .unwrap_or_else(|| {
                panic!(
                    "missing same-root collision diagnostic: {:?}",
                    plan.diagnostics
                )
            });
        assert_eq!(diagnostic.level, DiagnosticLevel::Error);
        assert!(
            diagnostic.message.contains(&first.display().to_string())
                && diagnostic.message.contains(&second.display().to_string()),
            "diagnostic should name both colliding manifests: {:?}",
            diagnostic
        );
    }

    #[test]
    fn distinct_names_no_diagnostic() {
        let project = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        write_claiming_component(root.path(), "first", "first-kit", "first", None);
        write_claiming_component(root.path(), "second", "second-kit", "second", None);

        let plan = plan_with_component_path(project.path(), root.path());

        assert_eq!(plan.plugins.len(), 2);
        assert!(
            plan.diagnostics.is_empty(),
            "distinct component names should not produce discovery diagnostics: {:?}",
            plan.diagnostics
        );
    }

    #[test]
    fn rust_census_yields_missing_kit_suggestion() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join("Cargo.toml"),
            "[package]\nname='x'\nversion='0.1.0'\n",
        )
        .unwrap();
        let census = census_workspace(dir.path());
        let message = missing_kit_message_from_census(&census).unwrap();
        assert!(message.contains("Rust workspace detected"));
        assert!(message.contains("apt install sugar-kit-rust"));
    }

    #[test]
    fn rust_census_collects_batched_forensic_items_for_component_claims() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join("Cargo.toml"),
            "[package]\nname='base64-showcase-good'\nversion='0.1.0'\n",
        )
        .unwrap();
        let src = dir.path().join("src");
        std::fs::create_dir_all(&src).unwrap();
        std::fs::write(src.join("lib.rs"), "pub fn encode_base64() {}\n").unwrap();
        let vendor = dir.path().join("vendor/base64-0.22.1/src");
        std::fs::create_dir_all(&vendor).unwrap();
        std::fs::write(
            dir.path().join("vendor/base64-0.22.1/Cargo.toml"),
            "[package]\nname='base64'\nversion='0.22.1'\n",
        )
        .unwrap();
        std::fs::write(vendor.join("encode.rs"), "pub fn encoded_len() {}\n").unwrap();

        let census = census_workspace(dir.path());
        let paths = census
            .items
            .iter()
            .map(|item| item.path.as_str())
            .collect::<Vec<_>>();

        assert!(paths.contains(&"Cargo.toml"));
        assert!(paths.contains(&"src/lib.rs"));
        assert!(paths.contains(&"vendor/base64-0.22.1/Cargo.toml"));
        assert!(paths.contains(&"vendor/base64-0.22.1/src/encode.rs"));
        assert!(census.items.iter().any(|item| {
            item.kind == "source-file"
                && item.path == "src/lib.rs"
                && item.language_hint.as_deref() == Some("rust")
        }));
    }

    #[test]
    fn parses_claimed_component_plan() {
        let component = ComponentRegistration {
            name: "rust-test".to_string(),
            version: None,
            protocol_version: COMPONENT_PROTOCOL_VERSION.to_string(),
            command: vec!["does-not-run".to_string()],
            working_dir: None,
            source: PathBuf::from("manifest.toml"),
            source_cid: blake3_512_of(b"test-component"),
        };
        let value = json!({
            "decision": "claim",
            "plugins": [{
                "name": "rust-test-assertions-lift",
                "kind": "lift",
                "surface": "rust-test-assertions",
                "emit": "ir-document"
            }],
            "lift_manifests": [{
                "surface": "rust-test-assertions",
                "name": "rust-test-assertions-lift",
                "command": ["/bin/rust_test_assertions_rpc"],
                "working_dir": "."
            }]
        });
        let result = match parse_component_plan_result(&component, value).unwrap() {
            ComponentPlanDecision::Claim(result) => result,
            other => panic!("expected claim, got {other:?}"),
        };
        assert_eq!(result.plugins.len(), 1);
        assert_eq!(result.plugins[0].surface, "rust-test-assertions");
        assert_eq!(result.plugins[0].emit.as_deref(), Some("ir-document"));
        assert_eq!(result.lift_manifests.len(), 1);
        assert_eq!(result.lift_manifests[0].surface, "rust-test-assertions");
    }

    #[test]
    fn parses_claimed_component_plan_with_item_claims() {
        let component = ComponentRegistration {
            name: "rust-walk".to_string(),
            version: None,
            protocol_version: COMPONENT_PROTOCOL_VERSION.to_string(),
            command: vec!["does-not-run".to_string()],
            working_dir: None,
            source: PathBuf::from("manifest.toml"),
            source_cid: blake3_512_of(b"walk-component"),
        };
        let value = json!({
            "decision": "claim",
            "claims": [{
                "item": "file:vendor/base64-0.22.1/Cargo.toml",
                "role": "contract-producer",
                "surface": "rust-fn-contracts"
            }],
            "plugins": [{
                "name": "rust-fn-contracts-lift",
                "kind": "lift",
                "surface": "rust-fn-contracts",
                "emit": "ir-document",
                "workspace_override": "vendor/base64-0.22.1"
            }],
            "lift_manifests": [{
                "surface": "rust-fn-contracts",
                "name": "rust-fn-contracts-lift",
                "command": ["/bin/sugar-walk-rpc", "--rpc"],
                "working_dir": "."
            }]
        });

        let result = match parse_component_plan_result(&component, value).unwrap() {
            ComponentPlanDecision::Claim(result) => result,
            other => panic!("expected claim, got {other:?}"),
        };

        assert_eq!(result.plugins[0].surface, "rust-fn-contracts");
        assert_eq!(
            result.plugins[0].workspace_override.as_deref(),
            Some("vendor/base64-0.22.1")
        );
        assert_eq!(result.lift_manifests[0].surface, "rust-fn-contracts");
    }

    #[test]
    fn parses_claimed_component_plan_with_ir_compiler() {
        let component = ComponentRegistration {
            name: "smt-lib-compiler".to_string(),
            version: None,
            protocol_version: COMPONENT_PROTOCOL_VERSION.to_string(),
            command: vec!["does-not-run".to_string()],
            working_dir: None,
            source: PathBuf::from("manifest.toml"),
            source_cid: blake3_512_of(b"compiler-component"),
        };
        let value = json!({
            "decision": "claim",
            "claims": [{
                "role": "ir-compiler",
                "dialects": ["smt-lib-v2.6"]
            }],
            "ir_compilers": [{
                "name": "smt-lib-reference",
                "version": "0.1.0",
                "protocol_version": "sugar-ir-compiler/1",
                "command": ["/bin/sugar-ir-smt-lib"],
                "dialects": ["smt-lib-v2.6"],
                "supported_sorts": ["Int", "Bool"],
                "supported_predicates": ["="]
            }]
        });

        let result = match parse_component_plan_result(&component, value).unwrap() {
            ComponentPlanDecision::Claim(result) => result,
            other => panic!("expected claim, got {other:?}"),
        };

        assert!(result.plugins.is_empty());
        assert_eq!(result.ir_compilers.len(), 1);
        assert_eq!(result.ir_compilers[0].name, "smt-lib-reference");
        assert_eq!(
            result.ir_compilers[0].dialects,
            vec!["smt-lib-v2.6".to_string()]
        );
        assert_eq!(
            result.ir_compilers[0].supported_sorts,
            vec!["Int".to_string(), "Bool".to_string()]
        );
    }

    #[test]
    fn component_ir_compiler_fills_missing_dialect() {
        let mut registry = CompilerRegistry::new();
        register_planned_ir_compilers(
            &mut registry,
            Path::new("."),
            vec![PlannedIrCompiler {
                name: "smt-lib-reference".to_string(),
                version: Some("0.1.0".to_string()),
                protocol_version: IR_COMPILER_PROTOCOL_VERSION.to_string(),
                command: vec!["does-not-run-until-compile".to_string()],
                dialects: vec!["smt-lib-v2.6".to_string()],
                ..Default::default()
            }],
        );

        assert!(registry.get("smt-lib-v2.6").is_some());
    }

    #[test]
    fn component_ir_compiler_preserves_manifest_override() {
        let mut registry = CompilerRegistry::new();
        registry.register(Arc::new(TestCompiler {
            dialect: "smt-lib-v2.6".to_string(),
        }));

        register_planned_ir_compilers(
            &mut registry,
            Path::new("."),
            vec![PlannedIrCompiler {
                name: "component".to_string(),
                version: Some("0.1.0".to_string()),
                protocol_version: IR_COMPILER_PROTOCOL_VERSION.to_string(),
                command: vec!["does-not-run-because-override-wins".to_string()],
                dialects: vec!["smt-lib-v2.6".to_string()],
                ..Default::default()
            }],
        );

        let input = CompilerInput::decode_json(json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "var", "name": "v"},
                {"kind": "var", "name": "v"}
            ]
        }))
        .expect("component-plan registry fixture decodes");
        let compiled = registry
            .compile(&input, "smt-lib-v2.6")
            .expect("manifest override compiler should still be registered");
        assert_eq!(compiled.preamble, "; original\n");
    }

    #[test]
    fn component_plugins_order_like_the_handwritten_base64_graph() {
        let mut plugins = vec![
            PluginEntry {
                name: Some("rust-cargo-test-witness-lift".to_string()),
                kind: Some("lift".to_string()),
                surface: "rust-cargo-test-witness".to_string(),
                ..Default::default()
            },
            PluginEntry {
                name: Some("rust-implications-lift".to_string()),
                kind: Some("lift".to_string()),
                surface: "rust-implications".to_string(),
                ..Default::default()
            },
            PluginEntry {
                name: Some("rust-fn-contracts-lift".to_string()),
                kind: Some("lift".to_string()),
                surface: "rust-fn-contracts".to_string(),
                ..Default::default()
            },
            PluginEntry {
                name: Some("rust-test-assertions-lift".to_string()),
                kind: Some("lift".to_string()),
                surface: "rust-test-assertions".to_string(),
                ..Default::default()
            },
        ];

        order_component_plugins(&mut plugins);

        assert_eq!(
            plugins
                .iter()
                .map(|plugin| plugin.surface.as_str())
                .collect::<Vec<_>>(),
            vec![
                "rust-test-assertions",
                "rust-fn-contracts",
                "rust-implications",
                "rust-cargo-test-witness"
            ]
        );
    }

    #[test]
    fn authored_lift_plugin_claims_its_declared_platform_language() {
        let config = ProjectConfig {
            plugins: vec![PluginEntry {
                name: Some("java-test-assertions-lift".to_string()),
                kind: Some("lift".to_string()),
                surface: "java-test-assertions".to_string(),
                ..Default::default()
            }],
            platform_profile: Some(crate::project_config::PlatformProfile {
                language: Some("java".to_string()),
                ..Default::default()
            }),
            ..Default::default()
        };

        assert_eq!(
            authored_lift_languages(&config),
            BTreeSet::from(["java".to_string()])
        );
    }

    #[test]
    fn platform_language_without_authored_lift_plugin_stays_unclaimed() {
        let config = ProjectConfig {
            platform_profile: Some(crate::project_config::PlatformProfile {
                language: Some("java".to_string()),
                ..Default::default()
            }),
            ..Default::default()
        };

        assert!(authored_lift_languages(&config).is_empty());
    }

    #[test]
    fn plan_artifact_pins_selected_components_and_replay_uses_pinned_selection() {
        let project = tempfile::tempdir().unwrap();
        let component_manifest = project
            .path()
            .join(".sugar/components/rust-kit/manifest.toml");
        std::fs::create_dir_all(component_manifest.parent().unwrap()).unwrap();
        std::fs::write(
            &component_manifest,
            "name = \"rust-kit\"\nversion = \"1.2.3\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"old-component-rpc\"]\n",
        )
        .unwrap();

        let mut plan = ComponentPlan::default();
        plan.selected_components.push(PlannedComponent {
            name: "rust-kit".to_string(),
            version: Some("1.2.3".to_string()),
            protocol_version: COMPONENT_PROTOCOL_VERSION.to_string(),
            command: vec!["old-component-rpc".to_string()],
            working_dir: None,
            source: component_manifest.clone(),
            source_cid: file_bytes_cid(&component_manifest).unwrap(),
        });
        plan.plugins.push(PluginEntry {
            name: Some("rust-test-assertions-lift".to_string()),
            kind: Some("lift".to_string()),
            surface: "rust-test-assertions".to_string(),
            emit: Some("ir-document".to_string()),
            ..Default::default()
        });
        plan.lift_manifests.push(PlannedLiftManifest {
            surface: "rust-test-assertions".to_string(),
            name: "rust-test-assertions-lift".to_string(),
            version: Some("9.9.9".to_string()),
            protocol_version: Some("sugar-lift/1".to_string()),
            command: vec!["old-lift-rpc".to_string()],
            working_dir: Some(PathBuf::from("old-workdir")),
            discharge_command: vec!["old-discharge".to_string()],
            witness_tool: Some("pytest".to_string()),
            ..Default::default()
        });

        std::fs::write(
            &component_manifest,
            "name = \"rust-kit\"\nversion = \"2.0.0\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"new-component-rpc\"]\n",
        )
        .unwrap();

        let artifact = plan_artifact_memento(
            project.path(),
            PlanIntent::Prove,
            ComponentPlanOptions {
                allow_failed_components: true,
            },
            &plan,
        )
        .expect("non-empty plan mints PlanArtifact");
        let mut graph = sugar_proof_envelope::ProofGraph::new();
        graph
            .push_plan_member_bytes(artifact.member_bytes.clone())
            .expect("PlanArtifact member is a plan-memento");
        let plan_member = graph.plans().next().expect("PlanArtifact member view");
        let envelope = plan_member.json();

        assert_eq!(
            envelope
                .get("body")
                .and_then(|body| body.get("kind"))
                .and_then(Json::as_str),
            Some("component-plan-artifact")
        );
        assert_eq!(
            envelope
                .pointer("/body/selectionInputs/intent")
                .and_then(Json::as_str),
            Some("prove")
        );
        assert_eq!(
            envelope
                .pointer("/body/liftManifests/0/command/0")
                .and_then(Json::as_str),
            Some("old-lift-rpc"),
            "the artifact must pin selected manifest bytes, not rediscover after mutation"
        );

        let replayed = plan_workspace_for_replay(
            project.path(),
            PlanIntent::Prove,
            ComponentPlanOptions::default(),
            Some(&artifact),
        )
        .expect("PlanArtifact replay reconstructs pinned selection");

        assert_eq!(replayed.lift_manifests.len(), 1);
        assert_eq!(replayed.lift_manifests[0].command, vec!["old-lift-rpc"]);
        assert_eq!(replayed.selected_components.len(), 1);
        assert_eq!(
            replayed.selected_components[0].command,
            vec!["old-component-rpc"]
        );
    }

    #[test]
    fn replay_without_plan_artifact_uses_current_discovery() {
        let project = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        write_claiming_component(
            root.path(),
            "component",
            "fresh-kit",
            "fresh-surface",
            Some("1.0.0"),
        );
        let component_path = std::env::join_paths([root.path()]).unwrap();

        let _env_lock = TEST_ENV_LOCK.lock().unwrap();
        let _home = EnvGuard::set("HOME", project.path().join("home"));
        let _sugar_home = EnvGuard::remove("SUGAR_HOME");
        let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", component_path);
        let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

        let replayed = plan_workspace_for_replay(
            project.path(),
            PlanIntent::Lift,
            ComponentPlanOptions::default(),
            None,
        )
        .expect("pre-PlanArtifact replay keeps current discovery behavior");

        assert!(
            replayed
                .plugins
                .iter()
                .any(|plugin| plugin.surface == "fresh-surface"),
            "without a PlanArtifact replay must discover the current component plan: {:?}",
            replayed.plugins
        );
    }

    /// #3747 instrument: a missing component binary is not enrolled — Warning,
    /// never Error — so prove can still emit consistency rows via the compilers
    /// that *are* built (examples-gate ships only sugar-ir-smt-lib).
    #[test]
    fn missing_component_binary_is_warning_not_error() {
        let project = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        let component_dir = root.path().join("ir-compiler-coq");
        std::fs::create_dir_all(&component_dir).unwrap();
        // Point at a path that cannot spawn: binary does not exist.
        std::fs::write(
            component_dir.join("manifest.toml"),
            r#"name = "ir-compiler-coq"
version = "0.1.0"
protocol_version = "sugar-component/1"
command = ["./definitely-not-installed-sugar-ir-coq"]
"#,
        )
        .unwrap();
        let component_path = std::env::join_paths([root.path()]).unwrap();

        let _env_lock = TEST_ENV_LOCK.lock().unwrap();
        let _home = EnvGuard::set("HOME", project.path().join("home"));
        let _sugar_home = EnvGuard::remove("SUGAR_HOME");
        let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", component_path);
        let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

        let plan = plan_workspace_with_options(
            project.path(),
            PlanIntent::Prove,
            ComponentPlanOptions {
                allow_failed_components: false,
            },
        );

        let coq = plan
            .diagnostics
            .iter()
            .find(|d| d.message.contains("ir-compiler-coq"))
            .unwrap_or_else(|| {
                panic!(
                    "expected a diagnostic for the missing ir-compiler-coq binary; got {:?}",
                    plan.diagnostics
                )
            });
        assert_eq!(
            coq.level,
            DiagnosticLevel::Warning,
            "missing optional component binary must soft-skip (Warning), not hard-fail prove: {}",
            coq.message
        );
        assert!(
            first_error_diagnostic(&plan).is_none(),
            "prove must not inherit a hard Error from an unbuilt optional component: {:?}",
            plan.diagnostics
        );
        assert!(
            component_binary_unavailable(
                "spawn [\"./definitely-not-installed-sugar-ir-coq\"]: No such file or directory (os error 2)"
            ),
            "spawn ENOENT classifier must recognize Unix missing-binary text"
        );
        assert!(
            !component_binary_unavailable("component plan RPC timed out after 30s"),
            "timeout/crash failures stay hard unless --allow-failed-components"
        );
    }
}
