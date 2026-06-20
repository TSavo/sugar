// SPDX-License-Identifier: Apache-2.0
//
// Zero-config component rendezvous.
//
// The CLI owns generic discovery and composition. Components own language and
// tool semantics over RPC: "does this workspace look like mine, and what
// surfaces/manifests do I contribute?" Authored project/user manifests still
// override this path; component planning is the default only when no explicit
// config exists.

use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};

use serde::Deserialize;
use serde_json::{json, Value};
use tracing::{debug, info, warn};

use crate::project_config::PluginEntry;

pub(crate) const COMPONENT_PROTOCOL_VERSION: &str = "sugar-component/1";
pub(crate) const COMPONENT_PLAN_RPC_METHOD: &str = "sugar.component.plan";

#[derive(Debug, Clone, Default)]
pub(crate) struct WorkspaceCensus {
    pub languages: Vec<LanguageEvidence>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LanguageEvidence {
    pub language: String,
    pub path: String,
    pub reason: String,
}

#[derive(Debug, Clone, Default)]
pub(crate) struct ComponentPlan {
    pub plugins: Vec<PluginEntry>,
    pub lift_manifests: Vec<PlannedLiftManifest>,
    pub diagnostics: Vec<ComponentDiagnostic>,
    pub census: WorkspaceCensus,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ComponentDiagnostic {
    pub level: DiagnosticLevel,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum DiagnosticLevel {
    Info,
    Warning,
    Error,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct PlannedLiftManifest {
    pub surface: String,
    pub name: String,
    pub version: Option<String>,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub method: Option<String>,
    pub phase: Option<String>,
    pub discharge_command: Vec<String>,
    pub witness_tool: Option<String>,
    pub resolve_witness_command: Vec<String>,
    pub resolve_witness_method: Option<String>,
}

#[derive(Debug, Clone)]
struct ComponentRegistration {
    name: String,
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    source: PathBuf,
}

#[derive(Debug, Deserialize)]
struct ComponentManifest {
    name: String,
    protocol_version: String,
    command: Vec<String>,
    #[serde(default)]
    working_dir: Option<PathBuf>,
}

pub(crate) fn plan_workspace(project_root: &Path) -> ComponentPlan {
    let project_root = absolute_path(project_root);
    let census = census_workspace(&project_root);
    let mut plan = ComponentPlan {
        census,
        ..Default::default()
    };
    let components = discover_components(&project_root);
    info!(
        project = %project_root.display(),
        components = components.len(),
        languages = ?plan.census.languages.iter().map(|e| e.language.as_str()).collect::<Vec<_>>(),
        "component plan discovery complete"
    );
    for component in components {
        match request_component_plan(&component, &project_root, &plan.census) {
            Ok(Some(result)) => {
                info!(
                    component = component.name,
                    plugins = result.plugins.len(),
                    manifests = result.lift_manifests.len(),
                    "component claimed workspace"
                );
                plan.plugins.extend(result.plugins);
                plan.lift_manifests.extend(result.lift_manifests);
                plan.diagnostics.extend(result.diagnostics);
            }
            Ok(None) => {
                debug!(
                    component = component.name,
                    source = %component.source.display(),
                    "component declined workspace"
                );
            }
            Err(error) => {
                warn!(
                    component = component.name,
                    source = %component.source.display(),
                    error,
                    "component plan failed"
                );
                plan.diagnostics.push(ComponentDiagnostic {
                    level: DiagnosticLevel::Warning,
                    message: format!(
                        "component `{}` could not be queried from {}: {error}",
                        component.name,
                        component.source.display()
                    ),
                });
            }
        }
    }

    dedupe_plugins(&mut plan.plugins);
    dedupe_manifests(&mut plan.lift_manifests);
    if plan.plugins.is_empty() {
        if let Some(message) = missing_kit_message_from_census(&plan.census) {
            plan.diagnostics.push(ComponentDiagnostic {
                level: DiagnosticLevel::Error,
                message,
            });
        }
    }
    plan
}

#[allow(dead_code)] // Used by the CLI binary; the library test target does not compile cmd_prove.
pub(crate) fn planned_lift_plugins(project_root: &Path) -> Vec<PluginEntry> {
    plan_workspace(project_root).plugins
}

pub(crate) fn planned_lift_manifest(
    project_root: &Path,
    surface: &str,
) -> Option<PlannedLiftManifest> {
    plan_workspace(project_root)
        .lift_manifests
        .into_iter()
        .find(|manifest| manifest.surface == surface)
}

#[allow(dead_code)] // Used by the CLI binary; the library test target does not compile witness_verify.
pub(crate) fn planned_lift_manifests(project_root: &Path) -> Vec<PlannedLiftManifest> {
    plan_workspace(project_root).lift_manifests
}

fn census_workspace(project_root: &Path) -> WorkspaceCensus {
    let mut languages = Vec::new();
    if project_root.join("Cargo.toml").is_file() {
        languages.push(LanguageEvidence {
            language: "rust".to_string(),
            path: "Cargo.toml".to_string(),
            reason: "Cargo package manifest".to_string(),
        });
    }
    WorkspaceCensus { languages }
}

fn missing_kit_message_from_census(census: &WorkspaceCensus) -> Option<String> {
    let evidence = census.languages.first()?;
    let display_language = title_case_ascii(&evidence.language);
    Some(format!(
        "{display_language} workspace detected at {}, but no Sugar {display_language} kit component claimed it. Try: apt install sugar-kit-{}, then try again.",
        evidence.path,
        evidence.language
    ))
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

fn discover_components(project_root: &Path) -> Vec<ComponentRegistration> {
    let mut manifests = BTreeMap::<String, ComponentRegistration>::new();
    for root in component_roots(project_root) {
        debug!(root = %root.display(), "component discovery root");
        for manifest_path in manifest_paths_under(&root) {
            match parse_component_manifest(&manifest_path) {
                Ok(component) => {
                    manifests.insert(component.name.clone(), component);
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
    }
    manifests.into_values().collect()
}

fn component_roots(project_root: &Path) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    roots.extend(system_component_roots());
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
        command: manifest.command,
        working_dir: manifest.working_dir.map(|dir| {
            if dir.is_absolute() {
                dir
            } else {
                manifest_dir.join(dir)
            }
        }),
        source: path.to_path_buf(),
    })
}

fn request_component_plan(
    component: &ComponentRegistration,
    project_root: &Path,
    census: &WorkspaceCensus,
) -> Result<Option<ComponentPlanResult>, String> {
    let mut child = spawn_component(component)?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "component stdin unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "component stdout unavailable".to_string())?;
    let mut reader = BufReader::new(stdout);

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
    let _ = read_response(&mut reader, 1)?;

    let req = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": COMPONENT_PLAN_RPC_METHOD,
        "params": {
            "workspace_root": project_root.display().to_string(),
            "workspace_evidence": {
                "languages": census.languages.iter().map(|language| json!({
                    "language": language.language,
                    "path": language.path,
                    "reason": language.reason,
                })).collect::<Vec<_>>(),
            },
            "intent": "lift",
        }
    });
    writeln!(stdin, "{req}").map_err(|error| format!("write component plan: {error}"))?;
    let response = read_response(&mut reader, 2)?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    if let Some(error) = response.get("error") {
        if rpc_error_is_method_not_supported(error) {
            return Ok(None);
        }
        return Err(format!("component plan RPC error: {error}"));
    }
    let result = response.get("result").cloned().unwrap_or(Value::Null);
    parse_component_plan_result(component, result)
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

fn read_response(reader: &mut impl BufRead, id: i64) -> Result<Value, String> {
    let mut line = String::new();
    let n = reader
        .read_line(&mut line)
        .map_err(|error| format!("read response: {error}"))?;
    if n == 0 {
        return Err("component closed stdout before responding".to_string());
    }
    let value: Value = serde_json::from_str(line.trim())
        .map_err(|error| format!("parse JSON-RPC response: {error}; raw={}", line.trim()))?;
    if value.get("id").and_then(Value::as_i64) != Some(id) {
        return Err(format!("expected response id {id}, got {value}"));
    }
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
    diagnostics: Vec<ComponentDiagnostic>,
}

fn parse_component_plan_result(
    component: &ComponentRegistration,
    value: Value,
) -> Result<Option<ComponentPlanResult>, String> {
    let decision = value
        .get("decision")
        .and_then(Value::as_str)
        .unwrap_or("claim");
    match decision {
        "decline" => return Ok(None),
        "claim" => {}
        "refuse" => {
            let reason = value
                .get("reason")
                .and_then(Value::as_str)
                .unwrap_or("component refused workspace");
            return Err(reason.to_string());
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
    let diagnostics = value
        .get("diagnostics")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(diagnostic_from_value).collect())
        .unwrap_or_default();
    Ok(Some(ComponentPlanResult {
        plugins,
        lift_manifests,
        diagnostics,
    }))
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

#[allow(dead_code)] // Used by the CLI binary; the library test target does not compile witness_verify.
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

#[cfg(test)]
mod tests {
    use super::*;

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
    fn parses_claimed_component_plan() {
        let component = ComponentRegistration {
            name: "rust-test".to_string(),
            command: vec!["does-not-run".to_string()],
            working_dir: None,
            source: PathBuf::from("manifest.toml"),
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
        let result = parse_component_plan_result(&component, value)
            .unwrap()
            .unwrap();
        assert_eq!(result.plugins.len(), 1);
        assert_eq!(result.plugins[0].surface, "rust-test-assertions");
        assert_eq!(result.plugins[0].emit.as_deref(), Some("ir-document"));
        assert_eq!(result.lift_manifests.len(), 1);
        assert_eq!(result.lift_manifests[0].surface, "rust-test-assertions");
    }
}
