// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `WitnessDischargeConfig` -- SEAM 6 of the compiler-shape plan
// (`~/.claude/plans/sugar-compiler-liftshift.md`, "SEAM 6").
//
// Shared home for the witness-discharge configuration both `cmd_prove` and
// `cmd_verify` need before running the verifier pipeline: the discharge
// command is declared in the KIT'S MANIFEST (alongside its lift `command`),
// resolved through the SAME `find_manifest` dispatch lift uses, no bespoke
// config. Both faces call `witness_discharge_for_plan` in this module.
//
// #3809 witness-as-verb: this struct converts to
// `sugar_verifier::WitnessDischargeContext` and is passed as a typed
// argument into the verifier. Step 3 retires `SUGAR_WITNESS_PROJECT_DIR` /
// `SUGAR_WITNESS_RESOLVERS` as a live config channel — typed context is the
// sole surface for project_dir + resolvers. Verdict inputs are
// content-addressed (packageCid + contract + resolver body).
// Optional `SUGAR_WITNESS_DISCHARGE_<TOOL>` staging remains for showcase lie
// scripts that pollute process env; the package-recompute path never reads it.
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use owo_colors::OwoColorize;
use serde_json::{json, Value};

use crate::component_plan::{self, ComponentPlan, PlannedLiftManifest};
use crate::project_config::ProjectConfig;

/// Typed witness-discharge config (project_dir + resolvers + optional lie-env keys).
///
/// - `project_dir` / `resolvers` → typed `WitnessDischargeContext` only (step 3;
///   no `SUGAR_WITNESS_PROJECT_DIR` / `SUGAR_WITNESS_RESOLVERS` staging)
/// - `discharge_commands` → optional `SUGAR_WITNESS_DISCHARGE_<TOOL>` process
///   pollution for showcase lie scripts (not a package-recompute input)
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
                    Err(err) => {
                        eprintln!(
                            "{}: {}",
                            "warn".yellow().bold(),
                            manifest_lookup_warning(&plugin.surface, &err)
                        );
                        continue;
                    }
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

    /// Stage optional `SUGAR_WITNESS_DISCHARGE_<TOOL>` process env for
    /// showcase lie scripts. Does **not** stage `PROJECT_DIR` / `RESOLVERS`
    /// (retired step 3 — those flow only via [`Self::to_verifier_context`]).
    /// Pre-existing caller-set values win (`var_os(...).is_none()` guard).
    pub fn apply_env(&self) {
        for (key, argv) in &self.discharge_commands {
            if std::env::var_os(key).is_none() {
                std::env::set_var(key, argv);
            }
        }
    }

    /// Typed context for `sugar_verifier` discharge (sole project_dir/resolvers channel).
    pub fn to_verifier_context(&self) -> sugar_verifier::consistency::WitnessDischargeContext {
        use sugar_verifier::consistency::{WitnessDischargeContext, WitnessResolverSpec};
        let resolvers = self
            .resolvers
            .iter()
            .filter_map(|item| {
                let argv = item
                    .get("argv")
                    .and_then(|v| v.as_array())
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(|value| value.as_str().map(str::to_string))
                            .filter(|value| !value.is_empty())
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                if argv.is_empty() {
                    return None;
                }
                let working_dir = item
                    .get("working_dir")
                    .or_else(|| item.get("workingDir"))
                    .and_then(|v| v.as_str())
                    .map(std::path::PathBuf::from)
                    .unwrap_or_else(|| std::path::PathBuf::from("."));
                let method = item
                    .get("method")
                    .and_then(|v| v.as_str())
                    .unwrap_or("sugar.plugin.resolve_witness")
                    .to_string();
                Some(WitnessResolverSpec {
                    argv,
                    working_dir,
                    method,
                })
            })
            .collect();
        WitnessDischargeContext {
            project_dir: self.project_dir.clone(),
            resolvers,
        }
    }
}

/// Compute typed verifier context from the project's manifest plan.
/// `project_dir` + resolvers flow typed-only (step 3); optional DISCHARGE_*
/// process pollution for showcase lie scripts is staged as a side effect.
pub(crate) fn witness_discharge_for_plan(
    project_root: &Path,
    cfg_doc: &ProjectConfig,
    component_plan: Option<&ComponentPlan>,
) -> sugar_verifier::consistency::WitnessDischargeContext {
    let config = WitnessDischargeConfig::from_plan(project_root, cfg_doc, component_plan);
    config.apply_env(); // DISCHARGE_* only; not PROJECT_DIR/RESOLVERS
    config.to_verifier_context()
}

// The witness-discharge path loads the lift surface manifest at
// `<project>/.sugar/lift/<surface>/manifest.toml` to read its
// `discharge_command` + `witness_tool`. No hardcoded `sugar-lift-<kit>`.
// Helpers below serve WitnessDischargeConfig::from_plan / witness_discharge_for_plan.
// (Legacy configure_witness_discharge_env_with_plan deleted -- superseded by
// witness_discharge_for_plan in b34b7fbb6 Part of #3809 witness-as-verb step 3.)

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

/// The loud-loss diagnostic for a plugin whose manifest lookup failed:
/// the discharge/resolver commands for this plugin are OMITTED from the
/// witness-discharge config, and the omission must say so (#3872). Names
/// the plugin surface and carries the lookup error verbatim.
fn manifest_lookup_warning(surface: &str, err: &str) -> String {
    format!(
        "skipping witness-discharge config for plugin `{surface}`: manifest lookup failed: {err}"
    )
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project_config::PluginEntry;

    fn plugin(surface: &str) -> PluginEntry {
        PluginEntry {
            kind: Some("lift".to_string()),
            surface: surface.to_string(),
            ..PluginEntry::default()
        }
    }

    /// #3872: the warn-emission function names the plugin surface and
    /// carries the lookup error, so the omitted discharge command says so.
    #[test]
    fn manifest_lookup_warning_names_surface_and_error() {
        let msg = manifest_lookup_warning("rust-kit-3872", "no plugin manifest for surface");
        assert!(msg.contains("rust-kit-3872"), "must name plugin.surface: {msg}");
        assert!(
            msg.contains("no plugin manifest for surface"),
            "must carry the lookup error: {msg}"
        );
        assert!(msg.contains("skipping"), "must say the plugin was omitted: {msg}");
    }

    /// Err arm: a plugin whose manifest lookup fails contributes nothing —
    /// from_plan continues past it (and warns on stderr at line 85; the
    /// warning text itself is asserted above).
    #[test]
    fn from_plan_skips_plugin_with_failed_manifest_lookup() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = ProjectConfig {
            plugins: vec![plugin("no-such-surface-3872")],
            ..ProjectConfig::default()
        };
        let plan = ComponentPlan::default();
        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));
        assert!(config.discharge_commands.is_empty());
        assert!(config.resolvers.is_empty());
    }

    /// Ok arm (discrimination pair): the same box with a real manifest on
    /// disk produces the discharge command — proving the Err arm's empty
    /// result is the lookup failure, not a dead pipeline.
    #[test]
    fn from_plan_collects_discharge_command_when_manifest_resolves() {
        let dir = tempfile::tempdir().unwrap();
        let surface_dir = dir.path().join(".sugar").join("lift").join("kit-3872");
        std::fs::create_dir_all(&surface_dir).unwrap();
        std::fs::write(
            surface_dir.join("manifest.toml"),
            "command = [\"lifter\"]\ndischarge_command = [\"discharge\", \"--fast\"]\nwitness_tool = \"z3\"\n",
        )
        .unwrap();
        let cfg = ProjectConfig {
            plugins: vec![plugin("kit-3872")],
            ..ProjectConfig::default()
        };
        let plan = ComponentPlan::default();
        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));
        assert_eq!(
            config.discharge_commands.get("SUGAR_WITNESS_DISCHARGE_Z3"),
            Some(&"discharge --fast".to_string())
        );
    }
}
