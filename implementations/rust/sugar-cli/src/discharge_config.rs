// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `WitnessDischargeConfig` -- SEAM 6 of the compiler-shape plan
// (`~/.claude/plans/sugar-compiler-liftshift.md`, "SEAM 6").
//
// Shared home for the witness-discharge configuration both `cmd_prove` and
// `cmd_verify` need before running the verifier pipeline: the witness
// *resolver* is declared in the KIT'S MANIFEST (alongside its lift
// `command`), resolved through the SAME `find_manifest` dispatch lift uses,
// no bespoke config. Both faces call `witness_discharge_for_plan` in this
// module.
//
// #3809 witness-as-verb: this struct converts to
// `sugar_verifier::WitnessDischargeContext` and is passed as a typed
// argument into the verifier. Step 3 retires `SUGAR_WITNESS_PROJECT_DIR` /
// `SUGAR_WITNESS_RESOLVERS` as a live config channel — typed context is the
// sole surface for project_dir + resolvers. Verdict inputs are
// content-addressed (packageCid + contract + resolver body).
//
// #3860: `SUGAR_WITNESS_DISCHARGE_<TOOL>` is NOT a config channel. There is
// no production reader — package recompute settles via oracle resolve +
// authenticated package bytes. Staging those env vars was a dead write into
// the void; the writer is deleted. Showcase lie scripts may still *set* the
// env as process pollution (negative tests prove the package path ignores
// it); production code must never write or read it.
use std::path::{Path, PathBuf};

use owo_colors::OwoColorize;
use serde_json::{json, Value};

use crate::component_plan::{self, ComponentPlan, PlannedLiftManifest};
use crate::project_config::ProjectConfig;

/// Typed witness-discharge config (project_dir + resolvers only).
///
/// - `project_dir` / `resolvers` → typed `WitnessDischargeContext` only
///   (no `SUGAR_WITNESS_*` process-env staging of any kind)
/// - Manifest `discharge_command` / `witness_tool` fields are schema/plan
///   artifacts; they do **not** feed process env (#3860).
#[derive(Debug, Clone, Default)]
pub struct WitnessDischargeConfig {
    pub project_dir: Option<PathBuf>,
    pub resolvers: Vec<Value>,
}

impl WitnessDischargeConfig {
    /// Compute the config from the project's manifest-declared lift
    /// plugins. Pure computation: no env mutation.
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
            // #3860: do NOT stage SUGAR_WITNESS_DISCHARGE_<TOOL> from
            // manifest.discharge_command / witness_tool. No production
            // reader; package recompute uses resolvers above only.
        }

        WitnessDischargeConfig {
            project_dir,
            resolvers,
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
/// `project_dir` + resolvers flow typed-only. Does **not** mutate process env
/// (#3860: `SUGAR_WITNESS_DISCHARGE_<TOOL>` writer deleted; zero production readers).
pub(crate) fn witness_discharge_for_plan(
    project_root: &Path,
    cfg_doc: &ProjectConfig,
    component_plan: Option<&ComponentPlan>,
) -> sugar_verifier::consistency::WitnessDischargeContext {
    WitnessDischargeConfig::from_plan(project_root, cfg_doc, component_plan).to_verifier_context()
}

// The witness-discharge path loads the lift surface manifest at
// `<project>/.sugar/lift/<surface>/manifest.toml` to read its
// `resolve_witness_command`. No hardcoded `sugar-lift-<kit>`.
// Helpers below serve WitnessDischargeConfig::from_plan / witness_discharge_for_plan.
// (Legacy configure_witness_discharge_env_with_plan deleted -- superseded by
// witness_discharge_for_plan in b34b7fbb6 Part of #3809 witness-as-verb step 3.)
// (#3860: SUGAR_WITNESS_DISCHARGE_<TOOL> env staging deleted -- void write.)

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
        // Parsed for plan schema fidelity; not staged into process env (#3860).
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
/// the resolver commands for this plugin are OMITTED from the
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

/// Env key shape historically written by the deleted DISCHARGE_* stager.
/// Kept as a pure helper so the #3860 instrument can name the illegal key
/// without reintroducing a writer.
fn discharge_tool_env_key(tool: &str) -> String {
    format!(
        "SUGAR_WITNESS_DISCHARGE_{}",
        tool.to_uppercase()
            .replace(|c: char| !c.is_ascii_alphanumeric(), "_")
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::project_config::PluginEntry;

    fn lift_plugin(surface: &str) -> PluginEntry {
        PluginEntry {
            kind: Some("lift".to_string()),
            surface: surface.to_string(),
            ..Default::default()
        }
    }

    fn planned_manifest(surface: &str, tool: &str) -> PlannedLiftManifest {
        PlannedLiftManifest {
            surface: surface.to_string(),
            name: surface.to_string(),
            command: vec!["lift-cmd".to_string()],
            discharge_command: vec![
                "discharge".to_string(),
                "--tool".to_string(),
                tool.to_string(),
            ],
            witness_tool: Some(tool.to_string()),
            resolve_witness_command: vec!["resolve-cmd".to_string(), "--json".to_string()],
            resolve_witness_method: None,
            ..Default::default()
        }
    }

    #[test]
    fn from_plan_derives_resolvers_from_plan_manifests() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = ProjectConfig {
            plugins: vec![lift_plugin("kit-a")],
            ..Default::default()
        };
        let plan = ComponentPlan {
            plugins: vec![lift_plugin("kit-a")],
            lift_manifests: vec![planned_manifest("kit-a", "my-tool.9")],
            ..Default::default()
        };

        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));

        // project_dir is canonicalized.
        assert_eq!(config.project_dir, Some(dir.path().canonicalize().unwrap()));
        // Resolver entry carries argv + working_dir + default method.
        assert_eq!(config.resolvers.len(), 1);
        assert_eq!(
            config.resolvers[0]["argv"],
            json!(["resolve-cmd", "--json"])
        );
        assert_eq!(
            config.resolvers[0]["method"],
            json!("sugar.plugin.resolve_witness")
        );
    }

    #[test]
    fn from_plan_config_declared_lift_plugins_win_over_plan_plugins() {
        // cfg declares a lift plugin, so the plan's plugin list must be
        // IGNORED: only the cfg surface's manifest contributes.
        let dir = tempfile::tempdir().unwrap();
        let cfg = ProjectConfig {
            plugins: vec![lift_plugin("cfg-surface")],
            ..Default::default()
        };
        let plan = ComponentPlan {
            plugins: vec![lift_plugin("plan-surface")],
            lift_manifests: vec![
                planned_manifest("cfg-surface", "cfgtool"),
                planned_manifest("plan-surface", "plantool"),
            ],
            ..Default::default()
        };

        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));

        assert_eq!(config.resolvers.len(), 1);
        assert_eq!(
            config.resolvers[0]["argv"],
            json!(["resolve-cmd", "--json"])
        );
        // Only cfg-surface contributes; plantool's surface is not in cfg plugins.
        let ctx = config.to_verifier_context();
        assert_eq!(ctx.resolvers.len(), 1);
    }

    #[test]
    fn from_plan_falls_back_to_plan_plugins_when_cfg_has_no_lift_plugins() {
        // cfg has only an emit plugin (not a lift plugin), so the plan's
        // plugin list is the source.
        let dir = tempfile::tempdir().unwrap();
        let emit_only = PluginEntry {
            kind: Some("emit".to_string()),
            surface: "emit-surface".to_string(),
            ..Default::default()
        };
        let cfg = ProjectConfig {
            plugins: vec![emit_only],
            ..Default::default()
        };
        let plan = ComponentPlan {
            plugins: vec![lift_plugin("plan-surface")],
            lift_manifests: vec![planned_manifest("plan-surface", "plantool")],
            ..Default::default()
        };

        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));

        assert_eq!(config.resolvers.len(), 1);
    }

    #[test]
    fn from_plan_skips_manifests_without_resolver_but_does_not_stage_discharge_env() {
        // A manifest with no resolve_witness_command contributes no resolver.
        // Its discharge_command / witness_tool must also not stage process env.
        let dir = tempfile::tempdir().unwrap();
        let mut no_resolver = planned_manifest("kit-a", "toolless");
        no_resolver.resolve_witness_command.clear();
        let cfg = ProjectConfig {
            plugins: vec![lift_plugin("kit-a")],
            ..Default::default()
        };
        let plan = ComponentPlan {
            lift_manifests: vec![no_resolver],
            ..Default::default()
        };

        let env_key = discharge_tool_env_key("toolless");
        std::env::remove_var(&env_key);
        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));
        let _ = witness_discharge_for_plan(dir.path(), &cfg, Some(&plan));

        assert!(config.resolvers.is_empty());
        assert!(
            std::env::var_os(&env_key).is_none(),
            "discharge_command alone must not stage {env_key}"
        );
    }

    #[test]
    fn from_plan_project_local_manifest_wins_over_plan_manifest() {
        // A `.sugar/lift/<surface>/manifest.toml` in the project root takes
        // precedence over the plan's manifest for the same surface.
        let dir = tempfile::tempdir().unwrap();
        let manifest_dir = dir.path().join(".sugar").join("lift").join("kit-a");
        std::fs::create_dir_all(&manifest_dir).unwrap();
        std::fs::write(
            manifest_dir.join("manifest.toml"),
            r#"
name = "kit-a"
command = ["local-lift"]
resolve_witness_command = ["local-resolve"]
discharge_command = ["local-discharge"]
witness_tool = "localtool"
"#,
        )
        .unwrap();
        let cfg = ProjectConfig {
            plugins: vec![lift_plugin("kit-a")],
            ..Default::default()
        };
        let plan = ComponentPlan {
            lift_manifests: vec![planned_manifest("kit-a", "plantool")],
            ..Default::default()
        };

        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));

        assert_eq!(config.resolvers.len(), 1);
        assert_eq!(config.resolvers[0]["argv"], json!(["local-resolve"]));
    }

    /// #3860 instrument: `witness_discharge_for_plan` must never write
    /// `SUGAR_WITNESS_DISCHARGE_<TOOL>` — zero production readers, so a
    /// writer is a void write. Typed resolvers remain the live channel.
    ///
    /// Replacement architecture: package recompute via
    /// `WitnessDischargeContext.resolvers` only. Showcase lie scripts may
    /// still *set* the env as pollution; production code must not.
    #[test]
    fn issue_3860_discharge_tool_env_is_not_staged_by_witness_discharge_for_plan() {
        let dir = tempfile::tempdir().unwrap();
        let tool = "test3860tool";
        let env_key = discharge_tool_env_key(tool);
        std::env::remove_var(&env_key);

        let cfg = ProjectConfig {
            plugins: vec![lift_plugin("kit-3860")],
            ..Default::default()
        };
        let plan = ComponentPlan {
            plugins: vec![lift_plugin("kit-3860")],
            lift_manifests: vec![planned_manifest("kit-3860", tool)],
            ..Default::default()
        };

        let ctx = witness_discharge_for_plan(dir.path(), &cfg, Some(&plan));

        assert!(
            std::env::var_os(&env_key).is_none(),
            "#3860: production must not stage {env_key} (dead writer / void channel). \
             fix=delete apply_env / discharge_commands staging; feed \
             WitnessDischargeContext.resolvers only"
        );
        assert_eq!(
            ctx.resolvers.len(),
            1,
            "typed resolvers remain the live discharge surface"
        );
        assert_eq!(
            ctx.resolvers[0].argv,
            vec!["resolve-cmd".to_string(), "--json".to_string()]
        );
        assert!(
            ctx.project_dir.is_some(),
            "typed project_dir remains the live discharge surface"
        );

        std::env::remove_var(&env_key);
    }

    /// Discrimination pair: a caller who *already* set the pollution env
    /// keeps their value — production neither overwrites nor clears it.
    /// Showcase lie scripts rely on this "caller owns the pollution" rule.
    #[test]
    fn issue_3860_caller_set_discharge_env_survives_witness_discharge_for_plan() {
        let dir = tempfile::tempdir().unwrap();
        let tool = "test3860preset";
        let env_key = discharge_tool_env_key(tool);
        std::env::set_var(&env_key, "caller-lie-script");

        let cfg = ProjectConfig {
            plugins: vec![lift_plugin("kit-3860-preset")],
            ..Default::default()
        };
        let plan = ComponentPlan {
            plugins: vec![lift_plugin("kit-3860-preset")],
            lift_manifests: vec![planned_manifest("kit-3860-preset", tool)],
            ..Default::default()
        };

        let _ = witness_discharge_for_plan(dir.path(), &cfg, Some(&plan));

        assert_eq!(
            std::env::var(&env_key).as_deref(),
            Ok("caller-lie-script"),
            "production must not clobber caller-set pollution env"
        );
        std::env::remove_var(&env_key);
    }

    fn plugin(surface: &str) -> PluginEntry {
        PluginEntry {
            kind: Some("lift".to_string()),
            surface: surface.to_string(),
            ..PluginEntry::default()
        }
    }

    /// #3872: the warn-emission function names the plugin surface and
    /// carries the lookup error, so the omitted resolver says so.
    #[test]
    fn manifest_lookup_warning_names_surface_and_error() {
        let msg = manifest_lookup_warning("rust-kit-3872", "no plugin manifest for surface");
        assert!(
            msg.contains("rust-kit-3872"),
            "must name plugin.surface: {msg}"
        );
        assert!(
            msg.contains("no plugin manifest for surface"),
            "must carry the lookup error: {msg}"
        );
        assert!(
            msg.contains("skipping"),
            "must say the plugin was omitted: {msg}"
        );
    }

    /// Err arm: a plugin whose manifest lookup fails contributes nothing —
    /// from_plan continues past it (and warns on stderr).
    #[test]
    fn from_plan_skips_plugin_with_failed_manifest_lookup() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = ProjectConfig {
            plugins: vec![plugin("no-such-surface-3872")],
            ..ProjectConfig::default()
        };
        let plan = ComponentPlan::default();
        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));
        assert!(config.resolvers.is_empty());
    }

    /// Ok arm (discrimination pair): the same box with a real manifest on
    /// disk produces the resolver — proving the Err arm's empty result is
    /// the lookup failure, not a dead pipeline.
    #[test]
    fn from_plan_collects_resolver_when_manifest_resolves() {
        let dir = tempfile::tempdir().unwrap();
        let surface_dir = dir.path().join(".sugar").join("lift").join("kit-3872");
        std::fs::create_dir_all(&surface_dir).unwrap();
        std::fs::write(
            surface_dir.join("manifest.toml"),
            "command = [\"lifter\"]\nresolve_witness_command = [\"resolve\", \"--fast\"]\ndischarge_command = [\"discharge\", \"--fast\"]\nwitness_tool = \"z3\"\n",
        )
        .unwrap();
        let cfg = ProjectConfig {
            plugins: vec![plugin("kit-3872")],
            ..ProjectConfig::default()
        };
        let plan = ComponentPlan::default();
        let config = WitnessDischargeConfig::from_plan(dir.path(), &cfg, Some(&plan));
        assert_eq!(config.resolvers.len(), 1);
        assert_eq!(config.resolvers[0]["argv"], json!(["resolve", "--fast"]));
        // #3860: discharge_command present in manifest but never staged.
        let env_key = discharge_tool_env_key("z3");
        std::env::remove_var(&env_key);
        let _ = witness_discharge_for_plan(dir.path(), &cfg, Some(&plan));
        assert!(
            std::env::var_os(&env_key).is_none(),
            "manifest discharge_command must not stage {env_key}"
        );
    }
}
