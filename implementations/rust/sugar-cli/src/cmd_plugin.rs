// SPDX-License-Identifier: MIT OR Apache-2.0
//
// PEP 1.7.0 plugin flag plumbing.
//
// This module owns the PluginFlags struct and the `build_registry` function.
//
// Flag dispatch (§7):
//   --plugin <kind>:<source>     canonical form; multi-load via repeated flags.
//   --sugar <source>             ≡ --plugin sugar:<source>
//   --loss-function <source>     ≡ --plugin loss-function:<source>  (§3.1 spec-canonical alias)
//   --loss-fn <source>           alias for --loss-function (ergonomic short form)
//   --lifter <source>            ≡ --plugin lift:<source>   (wire kind = "lift")
//   --no-default-plugins         legacy no-op; no implicit plugins exist.
//   --no-default-plugin <kind>   legacy no-op; no implicit plugins exist.
//   --strict-plugins             promote every plugin load failure to refuse.
//   --plugin-registry-out <path> write PluginRegistryMemento JSON to <path>.
//
// Source detection (§3.1): strings beginning with "stdio:", "http://",
// "https://", or "tcp://" are RPC; everything else is a file path.
//
// Flag order is the tie-break order preserved in PluginRegistryMemento.load_order
// (§9.1).  The CLI does not append implicit plugins; configured manifests and
// explicit RPC/file sources are the registry inputs.
//
// B4: CLI flag ORDER is recovered via clap ArgMatches::indices_of so that
// interleaved --plugin / --sugar / --loss-function / --lifter flags appear in
// their true argv order, not two-pass (--plugin first, aliases second).

use std::path::{Path, PathBuf};

use sugar_plugin_loader::{
    error::LoadError,
    load_plugin_from_file, load_plugin_from_rpc,
    registry::{mint_failure_memento, PluginRegistry},
    PluginRegistryMemento,
};

/// PEP 1.7.0 plugin flags (§7).  Flatten into any subcommand that consumes
/// the plugin registry:
///   ```ignore
///   #[command(flatten)]
///   pub plugins: PluginFlags,
///   ```
#[derive(Debug, Clone, Default)]
pub struct PluginFlags {
    /// Canonical plugin flag.  Loads one plugin of the declared kind from the
    /// source.  Repeat for multiple plugins; flag order is preserved in the
    /// registry's load_order (§9.1).
    ///
    /// Source detection (§3.1):
    ///   - `stdio:<cmd>`  → JSON-RPC over stdio.
    ///   - `http://...`   → JSON-RPC over HTTP (stub for PEP 1.7.0 v0).
    ///   - Everything else → file path.
    ///
    /// Example: `--plugin sugar:/path/to/spring.json`
    ///          `--plugin sugar:rpc://localhost:8765`
    pub plugins: Vec<String>,

    /// Alias: `--sugar <source>` ≡ `--plugin sugar:<source>`.
    pub sugar: Vec<String>,

    /// Alias: `--loss-function <source>` ≡ `--plugin loss-function:<source>`.
    /// `--loss-fn` is a second alias (ergonomic short form).
    pub loss_fn: Vec<String>,

    /// Alias: `--lifter <source>` ≡ `--plugin lift:<source>`.
    /// Note: the wire `kind` value is `"lift"`, not `"lifter"` (§2.1).
    pub lifter: Vec<String>,

    /// Legacy compatibility no-op: no implicit plugin registration exists.
    pub no_default_plugins: bool,

    /// Legacy compatibility no-op: no implicit plugin registration exists.
    pub no_default_plugin: Vec<String>,

    /// Promote EVERY plugin load failure to a refuse (overrides individual
    /// `critical = false` declarations) (§7).
    pub strict_plugins: bool,

    /// After the registry seals (§9), write the PluginRegistryMemento JSON to
    /// this path.
    pub plugin_registry_out: Option<PathBuf>,

    /// B4: interleaved ordered list of `(kind, source, verbatim)` reflecting
    /// true argv insertion order across all alias flags.
    /// Populated by `from_arg_matches_ref`; not serialized or parsed by clap
    /// as a flag (it's a derived field reconstructed from arg indices).
    ordered: Vec<(String, String, String)>,
}

// ---------------------------------------------------------------------------
// B4: Manual Args + FromArgMatches impl to recover interleaved flag order
// ---------------------------------------------------------------------------
//
// We cannot use `#[derive(Parser)]` for PluginFlags because derive does not
// expose the ArgMatches to the struct after parsing, so we cannot call
// `indices_of` to reconstruct interleaved order.  Instead we implement
// `clap::Args` and `clap::FromArgMatches` manually.  The `augment_args` and
// `augment_args_for_update` methods register the flags with clap.  The
// `from_arg_matches_ref` method reads them back in argv index order.

impl clap::Args for PluginFlags {
    fn augment_args(cmd: clap::Command) -> clap::Command {
        Self::augment_args_for_update(cmd)
    }

    fn augment_args_for_update(cmd: clap::Command) -> clap::Command {
        use clap::{Arg, ArgAction};
        cmd
            .arg(Arg::new("plugin")
                .long("plugin")
                .value_name("KIND:SOURCE")
                .action(ArgAction::Append)
                .help("Canonical plugin flag: --plugin <kind>:<source>"))
            .arg(Arg::new("sugar")
                .long("sugar")
                .value_name("SOURCE")
                .action(ArgAction::Append)
                .help("Alias: --sugar <source> ≡ --plugin sugar:<source>"))
            .arg(Arg::new("loss_fn")
                .long("loss-function")
                .alias("loss-fn")
                .value_name("SOURCE")
                .action(ArgAction::Append)
                .help("Alias: --loss-function <source> ≡ --plugin loss-function:<source>; --loss-fn is a short alias"))
            .arg(Arg::new("lifter")
                .long("lifter")
                .value_name("SOURCE")
                .action(ArgAction::Append)
                .help("Alias: --lifter <source> ≡ --plugin lift:<source>"))
            .arg(Arg::new("no_default_plugins")
                .long("no-default-plugins")
                .action(ArgAction::SetTrue)
                .help("Legacy compatibility no-op: plugins are manifest/config driven"))
            .arg(Arg::new("no_default_plugin")
                .long("no-default-plugin")
                .value_name("KIND")
                .action(ArgAction::Append)
                .help("Legacy compatibility no-op: plugins are manifest/config driven"))
            .arg(Arg::new("strict_plugins")
                .long("strict-plugins")
                .action(ArgAction::SetTrue)
                .help("Promote EVERY plugin load failure to a refuse"))
            .arg(Arg::new("plugin_registry_out")
                .long("plugin-registry-out")
                .value_name("PATH")
                .help("Write PluginRegistryMemento JSON to this path after sealing"))
    }
}

impl clap::FromArgMatches for PluginFlags {
    fn from_arg_matches(matches: &clap::ArgMatches) -> Result<Self, clap::Error> {
        let mut s = Self::default();
        s.update_from_arg_matches(matches)?;
        Ok(s)
    }

    fn update_from_arg_matches(&mut self, matches: &clap::ArgMatches) -> Result<(), clap::Error> {
        // Scalar flags.
        self.no_default_plugins = matches.get_flag("no_default_plugins");
        self.strict_plugins = matches.get_flag("strict_plugins");
        self.plugin_registry_out = matches
            .get_one::<String>("plugin_registry_out")
            .map(PathBuf::from);
        self.no_default_plugin = matches
            .get_many::<String>("no_default_plugin")
            .into_iter()
            .flatten()
            .cloned()
            .collect();

        // B4: reconstruct interleaved order via indices_of.
        // Each flag kind has its own index-space entry in ArgMatches.
        // We collect (argv_index, kind, source, verbatim) across all four
        // flag names, then sort by argv_index to recover true flag order.
        let mut ordered_raw: Vec<(usize, String, String, String)> = Vec::new();

        // --plugin KIND:SOURCE
        if let Some(indices) = matches.indices_of("plugin") {
            let values: Vec<_> = matches
                .get_many::<String>("plugin")
                .into_iter()
                .flatten()
                .collect();
            for (idx, raw) in indices.zip(values) {
                if let Some((kind, source)) = raw.split_once(':') {
                    ordered_raw.push((idx, kind.to_string(), source.to_string(), raw.to_string()));
                }
            }
        }

        // --sugar SOURCE  (kind = "sugar"; verbatim = "sugar:<source>")
        if let Some(indices) = matches.indices_of("sugar") {
            let values: Vec<_> = matches
                .get_many::<String>("sugar")
                .into_iter()
                .flatten()
                .collect();
            for (idx, src) in indices.zip(values) {
                ordered_raw.push((
                    idx,
                    "sugar".to_string(),
                    src.to_string(),
                    format!("sugar:{src}"),
                ));
            }
        }

        // --loss-function / --loss-fn SOURCE  (kind = "loss-function")
        if let Some(indices) = matches.indices_of("loss_fn") {
            let values: Vec<_> = matches
                .get_many::<String>("loss_fn")
                .into_iter()
                .flatten()
                .collect();
            for (idx, src) in indices.zip(values) {
                ordered_raw.push((
                    idx,
                    "loss-function".to_string(),
                    src.to_string(),
                    format!("loss-function:{src}"),
                ));
            }
        }

        // --lifter SOURCE  (kind = "lift")
        if let Some(indices) = matches.indices_of("lifter") {
            let values: Vec<_> = matches
                .get_many::<String>("lifter")
                .into_iter()
                .flatten()
                .collect();
            for (idx, src) in indices.zip(values) {
                // wire kind = "lift" (§2.1)
                ordered_raw.push((
                    idx,
                    "lift".to_string(),
                    src.to_string(),
                    format!("lift:{src}"),
                ));
            }
        }

        // Sort by argv_index to recover true interleaved order (§3.2 + §9.1).
        ordered_raw.sort_by_key(|(idx, _, _, _)| *idx);

        // Populate individual vecs for API compatibility and the ordered vec.
        self.plugins.clear();
        self.sugar.clear();
        self.loss_fn.clear();
        self.lifter.clear();
        self.ordered.clear();

        for (_, kind, source, verbatim) in ordered_raw {
            match kind.as_str() {
                "sugar" => self.sugar.push(source.clone()),
                "loss-function" => self.loss_fn.push(source.clone()),
                "lift" => self.lifter.push(source.clone()),
                _ => self.plugins.push(verbatim.clone()),
            }
            self.ordered.push((kind, source, verbatim));
        }

        Ok(())
    }
}

impl PluginFlags {
    /// Return the plugins in their true argv insertion order (§3.2 + §9.1).
    /// Implicit plugins are not a registry input; callers must provide explicit
    /// plugin sources or rely on manifest-scanned project config.
    fn ordered_plugins(&self) -> &[(String, String, String)] {
        &self.ordered
    }

    /// Load all plugins declared via flags, register them, seal the registry,
    /// optionally write the PluginRegistryMemento to disk, and return it.
    ///
    /// If `strict_plugins` is set, the first load failure refuses (returns Err).
    /// Otherwise, failures are recorded in the registry and the run continues.
    ///
    /// `sealed_at` should be an ISO-8601 UTC timestamp.
    ///
    /// N2: `--no-default-plugins` and `--no-default-plugin <kind>` are legacy
    /// compatibility flags. They are parsed without error, but there are no
    /// implicit plugins for them to suppress.
    pub fn build_registry(
        &self,
        sealed_at: &str,
    ) -> Result<PluginRegistryMemento, PluginLoadRefusal> {
        self.build_registry_inner(sealed_at)
    }

    pub fn build_registry_for_project(
        &self,
        _project_root: &Path,
        sealed_at: &str,
    ) -> Result<PluginRegistryMemento, PluginLoadRefusal> {
        self.build_registry_inner(sealed_at)
    }

    fn build_registry_inner(
        &self,
        sealed_at: &str,
    ) -> Result<PluginRegistryMemento, PluginLoadRefusal> {
        let mut registry = PluginRegistry::new();

        // Walk flags in true argv order (B4: insertion order, not type-grouped).
        for (kind, source, verbatim) in self.ordered_plugins() {
            let result = load_one(source);
            match result {
                Ok(plugin) => {
                    // Validate: plugin's declared kind matches the CLI flag kind.
                    if plugin.kind() != kind {
                        let err = LoadError::ValidationError {
                            detail: format!(
                                "plugin at `{source}` declares kind '{}' but flag expects kind '{kind}'",
                                plugin.kind()
                            ),
                        };
                        let f = mint_failure_memento(verbatim, kind, &err, sealed_at);
                        if plugin.is_critical() || self.strict_plugins {
                            return Err(PluginLoadRefusal {
                                failure: f,
                                source: verbatim.clone(),
                            });
                        }
                        registry.record_failure(f);
                        continue;
                    }
                    let critical = plugin.is_critical();
                    // B1: pass verbatim source for audit-replay (§9.4).
                    if let Err(dup_err) = registry.register(plugin, source) {
                        let f = mint_failure_memento(verbatim, kind, &dup_err, sealed_at);
                        if critical || self.strict_plugins {
                            return Err(PluginLoadRefusal {
                                failure: f,
                                source: verbatim.clone(),
                            });
                        }
                        registry.record_failure(f);
                    }
                }
                Err(err) => {
                    let f = mint_failure_memento(verbatim, kind, &err, sealed_at);
                    if self.strict_plugins {
                        return Err(PluginLoadRefusal {
                            failure: f,
                            source: verbatim.clone(),
                        });
                    }
                    registry.record_failure(f);
                }
            }
        }

        // N2: legacy compatibility flags. There are no implicit/default
        // plugins in the CLI registry; config/manifest/RPC is the entrypoint.
        if !self.no_default_plugins {
            for _suppressed_kind in &self.no_default_plugin {
                // No-op: no implicit plugins to suppress.
            }
        }

        let memento = registry.emit_registry_memento(sealed_at);

        // Write registry memento to disk if requested (§7).
        if let Some(ref out_path) = self.plugin_registry_out {
            let json =
                serde_json::to_string_pretty(&memento).expect("registry memento serialization");
            std::fs::write(out_path, json).unwrap_or_else(|e| {
                eprintln!(
                    "plugin-loader: could not write registry to {}: {e}",
                    out_path.display()
                );
            });
        }

        Ok(memento)
    }

    /// Reload successfully declared plugins of `kind` in true CLI order and
    /// return their full memento JSON. Consumers use this when the downstream
    /// kit needs the plugin content, not just the sealed registry CID.
    pub fn payloads_for_kind(&self, kind: &str) -> Vec<serde_json::Value> {
        self.ordered_plugins()
            .iter()
            .filter(|(declared_kind, _, _)| declared_kind == kind)
            .filter_map(|(_, source, _)| load_one(source).ok())
            .filter(|plugin| plugin.kind() == kind)
            .filter_map(|plugin| serde_json::to_value(plugin).ok())
            .collect()
    }
}

/// A plugin load failure that refused the run (critical = true or
/// --strict-plugins was set).
#[derive(Debug)]
pub struct PluginLoadRefusal {
    pub failure: sugar_plugin_loader::types::PluginLoadFailureMemento,
    pub source: String,
}

impl std::fmt::Display for PluginLoadRefusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "plugin load refused for '{}': {} ({})",
            self.source, self.failure.header.reason_detail, self.failure.header.reason_kind
        )
    }
}

/// Source detection per §3.1: determine whether the source is RPC or file,
/// then dispatch accordingly.
fn load_one(source: &str) -> Result<sugar_plugin_loader::types::PluginMemento, LoadError> {
    if source.starts_with("stdio:")
        || source.starts_with("http://")
        || source.starts_with("https://")
        || source.starts_with("tcp://")
    {
        load_plugin_from_rpc(source)
    } else {
        load_plugin_from_file(std::path::Path::new(source))
    }
}
