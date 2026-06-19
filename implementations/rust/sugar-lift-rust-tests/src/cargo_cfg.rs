// SPDX-License-Identifier: Apache-2.0
//
// Cargo/rustc configuration facts for the Rust assertion lifter.
//
// This is a Rust kit concern: the language-agnostic CLI sends workspace
// coordinates, and the kit reads the Rust build surface into cfg facts before
// Sugar resolution runs.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde_json::Value;
use tracing::{debug, info, warn};

use crate::{LiftOptions, TargetCfg};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CargoFeatureSelection {
    pub all_features: bool,
    pub no_default_features: bool,
    pub features: Vec<String>,
}

impl Default for CargoFeatureSelection {
    fn default() -> Self {
        Self {
            all_features: false,
            no_default_features: false,
            features: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CargoCfgOptions {
    pub manifest_path: Option<PathBuf>,
    pub disable_auto_discovery: bool,
    pub features_override: Option<CargoFeatureSelection>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RustBuildCfgReport {
    pub manifest_path: Option<PathBuf>,
    pub rustc_fact_count: usize,
    pub cargo_feature_count: usize,
    pub facts: Vec<String>,
}

pub fn cargo_cfg_options_from_lifter_args(args: &[String]) -> Result<CargoCfgOptions, String> {
    let mut out = CargoCfgOptions::default();
    let mut override_features = Vec::new();
    let mut saw_feature_override = false;
    let mut all_features = false;
    let mut no_default_features = false;
    let mut i = 0usize;
    while i < args.len() {
        match args[i].as_str() {
            "--cargo-manifest" => {
                let path = args.get(i + 1).ok_or("--cargo-manifest requires a path")?;
                out.manifest_path = Some(PathBuf::from(path));
                i += 2;
            }
            "--no-cargo-cfg" => {
                out.disable_auto_discovery = true;
                i += 1;
            }
            "--features-override" => {
                let raw = args
                    .get(i + 1)
                    .ok_or("--features-override requires a comma-separated feature list")?;
                override_features.extend(parse_feature_list(raw));
                saw_feature_override = true;
                i += 2;
            }
            "--feature-override" => {
                let feature = args
                    .get(i + 1)
                    .ok_or("--feature-override requires a feature name")?;
                override_features.push(feature.clone());
                saw_feature_override = true;
                i += 2;
            }
            "--all-features" => {
                all_features = true;
                i += 1;
            }
            "--no-default-features" => {
                no_default_features = true;
                i += 1;
            }
            _ => {
                i += 1;
            }
        }
    }

    if all_features && (saw_feature_override || no_default_features) {
        return Err(
            "--all-features cannot be combined with --features-override or --no-default-features"
                .to_string(),
        );
    }
    if all_features || no_default_features || saw_feature_override {
        out.features_override = Some(CargoFeatureSelection {
            all_features,
            no_default_features: no_default_features || saw_feature_override,
            features: override_features,
        });
    }
    Ok(out)
}

fn parse_feature_list(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|feature| !feature.is_empty())
        .map(str::to_string)
        .collect()
}

pub fn lift_options_from_rust_build_cfg(
    workspace_root: &Path,
    options: &CargoCfgOptions,
) -> Result<(LiftOptions, RustBuildCfgReport), String> {
    let manifest_path = cargo_manifest_for_workspace(workspace_root, options);
    let mut facts = rustc_cfg_facts()?;
    let rustc_fact_count = facts.len();
    let mut cargo_feature_count = 0usize;

    if let Some(manifest_path) = manifest_path.as_deref() {
        let selection = options
            .features_override
            .clone()
            .unwrap_or_else(CargoFeatureSelection::default);
        let feature_facts = cargo_feature_cfg_facts_from_manifest_path(manifest_path, &selection)?;
        cargo_feature_count = feature_facts.len();
        facts.extend(feature_facts);
        info!(
            target: "sugar_lift_rust_tests::cargo_cfg",
            manifest = %manifest_path.display(),
            features = cargo_feature_count,
            all_features = selection.all_features,
            no_default_features = selection.no_default_features,
            override_features = ?options.features_override.as_ref().map(|s| &s.features),
            "rust kit cargo feature cfg loaded"
        );
    } else if let Some(selection) = &options.features_override {
        let override_facts = feature_override_cfg_facts(selection);
        cargo_feature_count = override_facts.len();
        facts.extend(override_facts);
        info!(
            target: "sugar_lift_rust_tests::cargo_cfg",
            features = cargo_feature_count,
            "rust kit feature override cfg loaded without cargo manifest"
        );
    }

    let target_cfg = TargetCfg::from_rustc_cfg_facts(facts.iter().map(String::as_str))
        .map_err(|e| format!("invalid rust build cfg facts: {e}"))?;
    Ok((
        LiftOptions::for_target_cfg(target_cfg),
        RustBuildCfgReport {
            manifest_path,
            rustc_fact_count,
            cargo_feature_count,
            facts,
        },
    ))
}

fn rustc_cfg_facts() -> Result<Vec<String>, String> {
    let output = std::process::Command::new("rustc")
        .args(["--print", "cfg"])
        .output()
        .map_err(|e| format!("run `rustc --print cfg`: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "`rustc --print cfg` failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(str::to_string)
        .collect())
}

pub fn cargo_manifest_for_workspace(
    workspace_root: &Path,
    options: &CargoCfgOptions,
) -> Option<PathBuf> {
    if let Some(path) = &options.manifest_path {
        return Some(if path.is_absolute() {
            path.clone()
        } else {
            workspace_root.join(path)
        });
    }
    if options.disable_auto_discovery {
        return None;
    }
    discover_cargo_manifest(workspace_root)
}

pub fn discover_cargo_manifest(corpus: &Path) -> Option<PathBuf> {
    let mut dir = if corpus.is_file() {
        corpus.parent()?.to_path_buf()
    } else {
        corpus.to_path_buf()
    };
    loop {
        let candidate = dir.join("Cargo.toml");
        if candidate.is_file() {
            return Some(candidate);
        }
        if !dir.pop() {
            return None;
        }
    }
}

pub fn cargo_feature_cfg_facts_from_manifest_path(
    manifest_path: &Path,
    selection: &CargoFeatureSelection,
) -> Result<Vec<String>, String> {
    match cargo_feature_cfg_facts_from_cargo_metadata(manifest_path, selection) {
        Ok(facts) => Ok(facts),
        Err(error) => {
            warn!(
                target: "sugar_lift_rust_tests::cargo_cfg",
                manifest = %manifest_path.display(),
                error = %error,
                "cargo metadata failed; falling back to direct Cargo.toml feature parse"
            );
            let text = std::fs::read_to_string(manifest_path).map_err(|e| {
                format!(
                    "cannot read cargo manifest {}: {e}",
                    manifest_path.display()
                )
            })?;
            cargo_feature_cfg_facts_from_manifest_text(&text, selection)
                .map_err(|e| format!("invalid cargo manifest {}: {e}", manifest_path.display()))
        }
    }
}

fn cargo_feature_cfg_facts_from_cargo_metadata(
    manifest_path: &Path,
    selection: &CargoFeatureSelection,
) -> Result<Vec<String>, String> {
    let mut command = std::process::Command::new("cargo");
    command
        .arg("metadata")
        .arg("--format-version")
        .arg("1")
        .arg("--manifest-path")
        .arg(manifest_path)
        .arg("--no-deps");
    let output = command
        .output()
        .map_err(|e| format!("run cargo metadata: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "cargo metadata failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let metadata: Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("parse cargo metadata JSON: {e}"))?;
    let manifest_path = manifest_path
        .canonicalize()
        .unwrap_or_else(|_| manifest_path.to_path_buf());
    let package = metadata
        .get("packages")
        .and_then(Value::as_array)
        .and_then(|packages| {
            packages.iter().find(|package| {
                package
                    .get("manifest_path")
                    .and_then(Value::as_str)
                    .map(PathBuf::from)
                    .map(|path| path.canonicalize().unwrap_or(path) == manifest_path)
                    .unwrap_or(false)
            })
        })
        .ok_or_else(|| {
            format!(
                "cargo metadata did not describe manifest {}",
                manifest_path.display()
            )
        })?;
    cargo_feature_cfg_facts_from_package_metadata(package, selection)
}

fn cargo_feature_cfg_facts_from_package_metadata(
    package: &Value,
    selection: &CargoFeatureSelection,
) -> Result<Vec<String>, String> {
    let Some(features) = package.get("features").and_then(Value::as_object) else {
        return Ok(Vec::new());
    };
    let mut graph = BTreeMap::new();
    for (name, values) in features {
        let Some(values) = values.as_array() else {
            return Err(format!("cargo metadata feature {name} is not an array"));
        };
        let mut deps = Vec::with_capacity(values.len());
        for value in values {
            let Some(value) = value.as_str() else {
                return Err(format!(
                    "cargo metadata feature {name} entry is not a string"
                ));
            };
            deps.push(value.to_string());
        }
        graph.insert(name.clone(), deps);
    }
    Ok(feature_cfg_facts_from_graph(&graph, selection))
}

pub fn cargo_feature_cfg_facts_from_manifest_text(
    manifest: &str,
    selection: &CargoFeatureSelection,
) -> Result<Vec<String>, String> {
    let doc: toml::Value =
        toml::from_str(manifest).map_err(|e| format!("invalid TOML in Cargo manifest: {e}"))?;
    let Some(features) = doc.get("features").and_then(toml::Value::as_table) else {
        return Ok(Vec::new());
    };
    let mut graph = BTreeMap::new();
    for (name, value) in features {
        let Some(entries) = value.as_array() else {
            return Err(format!("[features].{name} must be an array"));
        };
        let mut deps = Vec::with_capacity(entries.len());
        for entry in entries {
            let Some(entry) = entry.as_str() else {
                return Err(format!("[features].{name} entries must be strings"));
            };
            deps.push(entry.to_string());
        }
        graph.insert(name.clone(), deps);
    }
    Ok(feature_cfg_facts_from_graph(&graph, selection))
}

fn feature_override_cfg_facts(selection: &CargoFeatureSelection) -> Vec<String> {
    if selection.all_features {
        return Vec::new();
    }
    selection
        .features
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .flat_map(|feature| {
            if feature == "default" {
                Vec::new()
            } else {
                vec![format!("feature={feature:?}")]
            }
        })
        .collect()
}

fn feature_cfg_facts_from_graph(
    graph: &BTreeMap<String, Vec<String>>,
    selection: &CargoFeatureSelection,
) -> Vec<String> {
    let local_features: BTreeSet<String> = graph.keys().cloned().collect();
    let mut queue = Vec::new();
    let include_default_feature_flag;
    if selection.all_features {
        include_default_feature_flag = local_features.contains("default");
        queue.extend(
            local_features
                .iter()
                .filter(|feature| feature.as_str() != "default")
                .cloned(),
        );
    } else if let Some(override_features) = selection_override_features(selection) {
        include_default_feature_flag = override_features.iter().any(|f| f == "default");
        queue.extend(override_features.into_iter().filter(|f| f != "default"));
        if include_default_feature_flag {
            queue.extend(graph.get("default").cloned().unwrap_or_default());
        }
    } else {
        include_default_feature_flag = !selection.no_default_features;
        if !selection.no_default_features {
            queue.extend(graph.get("default").cloned().unwrap_or_default());
        }
    }

    let mut enabled = BTreeSet::new();
    if include_default_feature_flag {
        enabled.insert("default".to_string());
    }
    while let Some(feature) = queue.pop() {
        if feature == "default" {
            if enabled.insert("default".to_string()) {
                queue.extend(graph.get("default").cloned().unwrap_or_default());
            }
            continue;
        }
        if !local_features.contains(&feature) {
            debug!(
                target: "sugar_lift_rust_tests::cargo_cfg",
                feature = feature,
                "ignoring non-local cargo feature dependency"
            );
            continue;
        }
        if !enabled.insert(feature.clone()) {
            continue;
        }
        if let Some(deps) = graph.get(&feature) {
            for dep in deps {
                if dep.starts_with("dep:") || dep.contains('/') {
                    continue;
                }
                if local_features.contains(dep) {
                    queue.push(dep.clone());
                }
            }
        }
    }

    enabled
        .into_iter()
        .map(|feature| format!("feature={feature:?}"))
        .collect()
}

fn selection_override_features(selection: &CargoFeatureSelection) -> Option<Vec<String>> {
    if selection.all_features || selection.no_default_features || !selection.features.is_empty() {
        Some(selection.features.clone())
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cargo_manifest_feature_closure_expands_only_local_features() {
        let manifest = r#"
[package]
name = "fixture"
version = "0.1.0"

[features]
default = ["full"]
full = ["fs", "io-util", "dep:slab", "mio/os-poll"]
fs = []
io-util = ["bytes"]
"#;
        let facts = cargo_feature_cfg_facts_from_manifest_text(
            manifest,
            &CargoFeatureSelection {
                all_features: false,
                no_default_features: false,
                features: Vec::new(),
            },
        )
        .expect("manifest parses");

        assert!(facts.contains(&r#"feature="default""#.to_string()));
        assert!(facts.contains(&r#"feature="full""#.to_string()));
        assert!(facts.contains(&r#"feature="fs""#.to_string()));
        assert!(facts.contains(&r#"feature="io-util""#.to_string()));
        assert!(!facts.contains(&r#"feature="dep:slab""#.to_string()));
        assert!(!facts.contains(&r#"feature="mio/os-poll""#.to_string()));
        assert!(!facts.contains(&r#"feature="bytes""#.to_string()));
    }

    #[test]
    fn features_override_replaces_default_feature_closure() {
        let manifest = r#"
[package]
name = "fixture"
version = "0.1.0"

[features]
default = ["defaulted"]
defaulted = []
chosen = []
"#;
        let facts = cargo_feature_cfg_facts_from_manifest_text(
            manifest,
            &CargoFeatureSelection {
                all_features: false,
                no_default_features: true,
                features: vec!["chosen".to_string()],
            },
        )
        .expect("manifest parses");

        assert_eq!(facts, vec![r#"feature="chosen""#.to_string()]);
    }

    #[test]
    fn lifter_args_parse_feature_override_without_config() {
        let args = vec![
            "--features-override".to_string(),
            "chosen,other".to_string(),
            "--cargo-manifest".to_string(),
            "Cargo.toml".to_string(),
        ];

        let options = cargo_cfg_options_from_lifter_args(&args).expect("args parse");

        assert_eq!(options.manifest_path, Some(PathBuf::from("Cargo.toml")));
        assert_eq!(
            options.features_override,
            Some(CargoFeatureSelection {
                all_features: false,
                no_default_features: true,
                features: vec!["chosen".to_string(), "other".to_string()],
            })
        );
    }

    #[test]
    fn lifter_args_reject_ambiguous_feature_override_modes() {
        let args = vec![
            "--all-features".to_string(),
            "--features-override".to_string(),
            "chosen".to_string(),
        ];

        let err = cargo_cfg_options_from_lifter_args(&args).expect_err("modes conflict");

        assert!(
            err.contains("--all-features cannot be combined"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn cargo_manifest_is_discovered_from_corpus_src_dir() {
        let root = std::env::temp_dir().join(format!(
            "sugar-cargo-manifest-discovery-{}-{}",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        ));
        let src = root.join("src");
        std::fs::create_dir_all(&src).expect("create temp src");
        std::fs::write(
            root.join("Cargo.toml"),
            "[package]\nname='fixture'\nversion='0.1.0'\n",
        )
        .expect("write Cargo.toml");

        let found = discover_cargo_manifest(&src).expect("manifest discovered");
        assert_eq!(found, root.join("Cargo.toml"));

        let _ = std::fs::remove_dir_all(root);
    }
}
