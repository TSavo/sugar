// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `WitnessDischargeConfig` -- SEAM 6 of the compiler-shape plan
// (`~/.claude/plans/sugar-compiler-liftshift.md`, "SEAM 6").
//
// Shared home for the witness-discharge configuration both `cmd_prove` and
// `cmd_verify` need before running the verifier pipeline: the discharge
// command is declared in the KIT'S MANIFEST (alongside its lift `command`),
// resolved through the SAME `find_manifest` dispatch lift uses, no bespoke
// config. Before this seam `cmd_verify::run_artifact_project_verify` called
// `crate::cmd_prove::configure_witness_discharge_env_with_plan` directly --
// a face-to-face reach-in. Both faces now call the ONE function in this
// module instead.
//
// This is an ENV-FALLBACK model, not full plumbing: `sugar-verifier`'s
// `consistency.rs` still reads `SUGAR_WITNESS_PROJECT_DIR` /
// `SUGAR_WITNESS_RESOLVERS` from the process environment directly (see the
// `TODO(SEAM 7)` markers left at those two read sites -- full typed
// plumbing through every verifier call site is deferred). This struct is
// the face-side computation of what the env WOULD carry; `apply_env`
// stages it into the process environment with the EXACT caller-wins
// precedence the pre-SEAM-6 code had.
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::component_plan::{self, ComponentPlan, PlannedLiftManifest};
use crate::project_config::ProjectConfig;

/// Typed capture of the `SUGAR_WITNESS_*` env-var channel.
///
/// - `project_dir` -> `SUGAR_WITNESS_PROJECT_DIR`
/// - `resolvers` -> `SUGAR_WITNESS_RESOLVERS` (JSON-encoded array)
/// - `discharge_commands` -> one `SUGAR_WITNESS_DISCHARGE_<TOOL>` per entry,
///   keyed by the already-formatted env var name (uppercased,
///   non-alphanumeric replaced with `_`)
#[derive(Debug, Clone, Default)]
pub struct WitnessDischargeConfig {
    pub project_dir: Option<PathBuf>,
    pub resolvers: Vec<Value>,
    pub discharge_commands: BTreeMap<String, String>,
}

impl WitnessDischargeConfig {
    /// Compute the config from the project's manifest-declared lift
    /// plugins, mirroring the pre-SEAM-6
    /// `configure_witness_discharge_env_with_plan` logic exactly, but as a
    /// pure computation (no env mutation here).
    pub fn from_plan(
        project_root: &Path,
        cfg_doc: &ProjectConfig,
        component_plan: Option<&ComponentPlan>,
    ) -> WitnessDischargeConfig {
        let project_dir = Some(
            project_root
                .canonicalize()
                .unwrap_or_else(|_| project_root.to_path_buf()),
        );

        let planned_plugins;
        let plugins: Vec<&crate::project_config::PluginEntry> =
            if cfg_doc.plugins.iter().any(|p| p.is_lift_plugin()) {
                cfg_doc
                    .plugins
                    .iter()
                    .filter(|p| p.is_lift_plugin())
                    .collect()
            } else {
                planned_plugins = component_plan
                    .map(|plan| plan.plugins.clone())
                    .unwrap_or_else(|| component_plan::planned_lift_plugins(project_root));
                planned_plugins
                    .iter()
                    .filter(|p| p.is_lift_plugin())
                    .collect()
            };

        let mut resolvers: Vec<Value> = Vec::new();
        let mut discharge_commands: BTreeMap<String, String> = BTreeMap::new();
        for plugin in plugins {
            let manifest =
                match find_manifest_with_plan(project_root, &plugin.surface, component_plan) {
                    Ok(m) => m,
                    Err(_) => continue,
                };
            if !manifest.resolve_witness_command.is_empty() {
                let working_dir = manifest_working_dir(project_root, &manifest);
                resolvers.push(json!({
                    "argv": manifest.resolve_witness_command,
                    "working_dir": working_dir.display().to_string(),
                    "method": manifest
                        .resolve_witness_method
                        .clone()
                        .unwrap_or_else(|| "sugar.plugin.resolve_witness".to_string()),
                }));
            }
            if manifest.discharge_command.is_empty() {
                continue;
            }
            let Some(tool) = manifest.witness_tool.as_deref() else {
                continue;
            };
            let key = format!(
                "SUGAR_WITNESS_DISCHARGE_{}",
                tool.to_uppercase()
                    .replace(|c: char| !c.is_ascii_alphanumeric(), "_")
            );
            discharge_commands
                .entry(key)
                .or_insert_with(|| manifest.discharge_command.join(" "));
        }

        WitnessDischargeConfig {
            project_dir,
            resolvers,
            discharge_commands,
        }
    }

    /// Apply this config to the process environment, PRESERVING the exact
    /// precedence the pre-SEAM-6 code had: a pre-existing caller-set env var
    /// ALWAYS wins over the derived value (`var_os(...).is_none()` guard on
    /// every write). Do not invert this -- it is what lets a caller override
    /// any single derived setting without disabling the rest.
    pub fn apply_env(&self) {
        if let Some(project_dir) = &self.project_dir {
            if std::env::var_os("SUGAR_WITNESS_PROJECT_DIR").is_none() {
                std::env::set_var("SUGAR_WITNESS_PROJECT_DIR", project_dir);
            }
        }
        for (key, argv) in &self.discharge_commands {
            if std::env::var_os(key).is_none() {
                std::env::set_var(key, argv);
            }
        }
        if !self.resolvers.is_empty() && std::env::var_os("SUGAR_WITNESS_RESOLVERS").is_none() {
            if let Ok(encoded) = serde_json::to_string(&self.resolvers) {
                std::env::set_var("SUGAR_WITNESS_RESOLVERS", encoded);
            }
        }
    }
}

/// Shared entry point: compute the config from the project's manifest plan
/// and apply it to the environment. Both `cmd_prove::build_prove_artifact_with_options`
/// and `cmd_verify::run_artifact_project_verify` call this ONE function --
/// this is what closes the SEAM 6 face-to-face coupling (`cmd_verify` used
/// to call `cmd_prove::configure_witness_discharge_env_with_plan` directly).
pub(crate) fn configure_witness_discharge_env_with_plan(
    project_root: &Path,
    cfg_doc: &ProjectConfig,
    component_plan: Option<&ComponentPlan>,
) {
    WitnessDischargeConfig::from_plan(project_root, cfg_doc, component_plan).apply_env();
}

// The witness-discharge path loads the lift surface manifest at
// `<project>/.sugar/lift/<surface>/manifest.toml` to read its
// `discharge_command` + `witness_tool`. No hardcoded `sugar-lift-<kit>`.
// (Relocated from `cmd_prove.rs` alongside `configure_witness_discharge_env_with_plan`;
// these helpers exist ONLY to serve it.)

fn find_manifest_with_plan(
    project_root: &Path,
    surface: &str,
    plan: Option<&ComponentPlan>,
) -> Result<PlannedLiftManifest, String> {
    let project_local = project_root
        .join(".sugar")
        .join("lift")
        .join(surface)
        .join("manifest.toml");
    if project_local.exists() {
        return parse_authored_lift_manifest(&project_local, surface);
    }
    if let Some(home) = std::env::var_os("HOME") {
        let user_global = PathBuf::from(home)
            .join(".config")
            .join("sugar")
            .join("lift")
            .join(surface)
            .join("manifest.toml");
        if user_global.exists() {
            return parse_authored_lift_manifest(&user_global, surface);
        }
    }
    if let Some(plan) = plan {
        if let Some(planned) = plan
            .lift_manifests
            .iter()
            .find(|manifest| manifest.surface == surface)
        {
            return Ok(planned.clone());
        }
    } else if let Some(planned) = component_plan::planned_lift_manifest(project_root, surface) {
        return Ok(planned);
    }
    Err(format!(
        "no plugin manifest for surface `{surface}` (looked in .sugar/lift/{surface}/manifest.toml, ~/.config/sugar/lift/{surface}/manifest.toml, and discovered Sugar components)"
    ))
}

fn parse_authored_lift_manifest(path: &Path, surface: &str) -> Result<PlannedLiftManifest, String> {
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
    let array_field = |key: &str| -> Vec<String> {
        toml.get(key)
            .and_then(toml::Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(toml::Value::as_str)
                    .map(str::to_string)
                    .filter(|value| !value.is_empty())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default()
    };
    let manifest = PlannedLiftManifest {
        surface: surface.to_string(),
        name: string_field("name").unwrap_or_else(|| surface.to_string()),
        version: string_field("version"),
        protocol_version: string_field("protocol_version")
            .or_else(|| string_field("protocolVersion")),
        command: array_field("command"),
        working_dir: string_field("working_dir").map(PathBuf::from),
        method: string_field("method"),
        phase: string_field("phase"),
        discharge_command: array_field("discharge_command")
            .into_iter()
            .chain(array_field("dischargeCommand"))
            .collect(),
        witness_tool: string_field("witness_tool").or_else(|| string_field("witnessTool")),
        resolve_witness_command: array_field("resolve_witness_command")
            .into_iter()
            .chain(array_field("resolveWitnessCommand"))
            .collect(),
        resolve_witness_method: string_field("resolve_witness_method")
            .or_else(|| string_field("resolveWitnessMethod")),
    };
    if manifest.command.is_empty() {
        return Err(format!("manifest {} has no `command`", path.display()));
    }
    Ok(manifest)
}

fn manifest_working_dir(project_root: &Path, manifest: &PlannedLiftManifest) -> PathBuf {
    manifest
        .working_dir
        .as_ref()
        .map(|path| {
            if path.is_absolute() {
                path.clone()
            } else {
                project_root.join(path)
            }
        })
        .unwrap_or_else(|| project_root.to_path_buf())
}
