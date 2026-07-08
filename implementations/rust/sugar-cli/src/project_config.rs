// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Project / user configuration for lift-plugin and solver routing.
//
// Sugar does not auto-detect the authoring surface. Projects and
// users can set a default `[authoring] surface = ...`, and commands can
// override it with sections such as `[authoring.lift] surface = ...`.
//
// Same shape as `.npmrc` / `.cargo/config.toml`: declarative files
// at known paths. The user is in charge.

use std::path::{Path, PathBuf};

/// One entry in `.sugar/config.toml`'s `[[plugins]]` array.
///
/// Each entry declares one project-enabled plugin. `kind = "lift"` routes
/// to `.sugar/lift/<surface>/manifest.toml`; `kind = "emit"` routes
/// to `.sugar/emit/<surface>/manifest.toml`. Omitted kind preserves
/// legacy lift/emit dual-use registrations.
#[derive(Debug, Clone, Default)]
pub struct PluginEntry {
    /// Human label for diagnostics. Optional; falls back to `surface`.
    pub name: Option<String>,
    /// Plugin role in the project registry. Explicit values are
    /// "lift" and "emit"; absent means legacy dual-use registration.
    pub kind: Option<String>,
    /// Plugin surface. The command decides whether this resolves under
    /// `.sugar/lift` or `.sugar/emit` from `kind`.
    pub surface: String,
    /// Optional absolute path the plugin should treat as its
    /// `workspace_root`. Use case: a shim that lifts from a
    /// cargo-resolved dependency's source instead of from its own
    /// project root. Defaults to the project root (the directory
    /// containing `.sugar/config.toml`).
    pub workspace_override: Option<String>,
    /// Optional `options.emit` value passed through to the plugin.
    /// `"ir-document"` opts a self-minting plugin (sugar-lift) into
    /// composable mode for multi-plugin merge; `"proof-envelope"` is
    /// the default self-mint shape.
    pub emit: Option<String>,
    /// Optional `options.layer` value passed through to the plugin.
    /// Used to opt the sugar/boundary lane into emitting
    /// `library-sugar-binding-entry` + `refusal-memento` (vs the
    /// default bind-IR shape). Recognized values per
    /// `lift-plugin-protocol.md`: "all", "library-bindings",
    /// "identify-only". Per-plugin so the sugar lane and the contract
    /// lane can request different layers from their respective
    /// language-kit lifters.
    pub layer: Option<String>,
}

/// One project- or user-configured shortcut for `sugar --kit`.
///
/// This is deliberately data, not a Rust-side catalog. A kit alias names a
/// project root plus the lift surface/lang key that should be used when the
/// shortcut is selected.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct KitAliasEntry {
    pub alias: String,
    pub project: String,
    pub surface: String,
    pub lang: String,
}

/// One configured witness source. `kind = "report"` names the built-in prove
/// report witness. `kind = "command"` runs `command` in the project root (or
/// `working_dir`) and captures stdout/stderr/exit status as witness evidence.
/// `kind = "file"` pins arbitrary bytes by path: a compiler log, a program
/// transcript, an image, a poem, any external artifact the config names.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct WitnessEntry {
    pub name: String,
    pub kind: String,
    pub command: Vec<String>,
    pub working_dir: Option<String>,
    pub path: Option<String>,
}

impl PluginEntry {
    pub fn display_name(&self) -> &str {
        self.name.as_deref().unwrap_or(self.surface.as_str())
    }

    pub fn is_lift_plugin(&self) -> bool {
        self.kind
            .as_deref()
            .map(|kind| kind.eq_ignore_ascii_case("lift"))
            .unwrap_or(true)
    }

    pub fn is_emit_plugin(&self) -> bool {
        self.kind
            .as_deref()
            .map(|kind| kind.eq_ignore_ascii_case("emit"))
            .unwrap_or(true)
    }
}

/// #1358 / #1355: Per-shim or per-consumer-project platform profile.
/// Declares the five-axis realization tuple (language, family, library,
/// version) plus the concept-level binding the shim's lifted bindings
/// declare on a per-function basis. Any axis may be absent
/// (None) — absent means the axis FLOATS and resolves against the
/// consumer's profile at realization time (per #1355 dispatch model).
///
/// Declared inline in `.sugar/config.toml`:
/// ```toml
/// [platform_profile]
/// language = "rust"
/// family = "concept:family:sql"
/// library = "rusqlite"
/// version = "0.39.0"
/// ```
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PlatformProfile {
    pub language: Option<String>,
    pub family: Option<String>,
    pub library: Option<String>,
    pub version: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct ProjectConfig {
    /// Project's declared lift plugins, in array-of-tables form
    /// (`[[plugins]]` in TOML). Empty if the project still uses the
    /// legacy single-surface `[authoring] surface = ...` form.
    pub plugins: Vec<PluginEntry>,

    /// Project/user configured kit aliases (`[[kits]]`). These power
    /// `--kit=<alias>` without baking language/package knowledge into
    /// the Rust CLI.
    pub kits: Vec<KitAliasEntry>,

    pub surface_default: Option<String>,
    pub surface_lift: Option<String>,

    /// Solver configuration. v1 captures the shape; the verifier
    /// itself still runs Z3 only. Future work routes through this.
    pub solver_default: Option<String>,
    pub solver_chain: Vec<String>,
    pub solver_portfolio: Vec<String>,
    pub solver_mode: Option<String>, // "first-wins" | "consensus"

    /// Extra contract directories loaded by `sugar prove`.
    /// e.g., an OpenAPI spec project whose .proof files are
    /// consumed alongside the main project.
    pub callees: Vec<String>,

    /// Serialized command path documents, keyed by command.
    pub path_mint: Option<String>,

    /// #1358 / #1355: realization tuple for this project. Used by
    /// `cmd_mint` to stamp every emitted memento.
    pub platform_profile: Option<PlatformProfile>,

    /// Configured witness sources consumed by `sugar prove --emit-witnesses`.
    pub witnesses: Vec<WitnessEntry>,

    /// Local trust anchors for verifier Tier-2 implication cache entries.
    /// Empty means implication cache hits are skipped.
    pub trusted_implication_signers: Vec<String>,
}

impl ProjectConfig {
    pub fn surface_for(&self, cmd: &str) -> Option<String> {
        let per_cmd = match cmd {
            "lift" => self.surface_lift.clone(),
            _ => None,
        };
        per_cmd.or_else(|| self.surface_default.clone())
    }

    pub fn path_for(&self, cmd: &str) -> Option<String> {
        match cmd {
            "mint" => self.path_mint.clone(),
            _ => None,
        }
    }
}

pub fn read_project_config(project_root: &Path) -> ProjectConfig {
    read_config_file(&project_root.join(".sugar/config.toml"))
}

pub fn read_user_config() -> ProjectConfig {
    let p = match user_config_path() {
        Some(p) => p,
        None => return ProjectConfig::default(),
    };
    read_config_file(&p)
}

fn user_config_path() -> Option<PathBuf> {
    if let Ok(xdg) = std::env::var("XDG_CONFIG_HOME") {
        if !xdg.is_empty() {
            return Some(PathBuf::from(xdg).join("sugar/config.toml"));
        }
    }
    let home = std::env::var("HOME").ok()?;
    Some(PathBuf::from(home).join(".config/sugar/config.toml"))
}

fn read_config_file(path: &Path) -> ProjectConfig {
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(_) => return ProjectConfig::default(),
    };
    parse_config(&text)
}

fn parse_config(text: &str) -> ProjectConfig {
    let mut cfg = ProjectConfig::default();
    let mut section: Option<String> = None;
    // In-flight `[[plugins]]` entry. Pushed to `cfg.plugins` on each new
    // `[[plugins]]` header or at end-of-file. Stays None while the parser
    // is in any other (single-bracket) section.
    let mut current_plugin: Option<PluginEntry> = None;
    // In-flight `[[kits]]` entry. Pushed to `cfg.kits` on each new
    // array-of-tables header or at end-of-file.
    let mut current_kit: Option<KitAliasEntry> = None;
    let mut current_witness: Option<WitnessEntry> = None;
    for raw_line in text.lines() {
        let line = strip_comment(raw_line).trim();
        if line.is_empty() {
            continue;
        }
        // Array-of-tables header: `[[plugins]]`. Each occurrence starts a
        // new entry; the previous entry (if any) is finalized into
        // `cfg.plugins`. The substrate's intent: one [[plugins]] block per
        // declared lift kit.
        if let Some(inner) = line.strip_prefix("[[").and_then(|s| s.strip_suffix("]]")) {
            if let Some(prev) = current_plugin.take() {
                if !prev.surface.is_empty() {
                    cfg.plugins.push(prev);
                }
            }
            if let Some(prev) = current_kit.take() {
                if !prev.alias.is_empty()
                    && !prev.project.is_empty()
                    && !prev.surface.is_empty()
                    && !prev.lang.is_empty()
                {
                    cfg.kits.push(prev);
                }
            }
            if let Some(prev) = current_witness.take() {
                if !prev.name.is_empty() && !prev.kind.is_empty() {
                    cfg.witnesses.push(prev);
                }
            }
            let header = inner.trim().to_lowercase();
            if header == "plugins" {
                current_plugin = Some(PluginEntry::default());
                section = Some("plugins.entry".to_string());
            } else if header == "kits" {
                current_kit = Some(KitAliasEntry::default());
                section = Some("kits.entry".to_string());
            } else if header == "witnesses" {
                current_witness = Some(WitnessEntry::default());
                section = Some("witnesses.entry".to_string());
            } else {
                section = Some(header);
            }
            continue;
        }
        if let Some(s) = line.strip_prefix('[').and_then(|s| s.strip_suffix(']')) {
            if let Some(prev) = current_plugin.take() {
                if !prev.surface.is_empty() {
                    cfg.plugins.push(prev);
                }
            }
            if let Some(prev) = current_kit.take() {
                if !prev.alias.is_empty()
                    && !prev.project.is_empty()
                    && !prev.surface.is_empty()
                    && !prev.lang.is_empty()
                {
                    cfg.kits.push(prev);
                }
            }
            if let Some(prev) = current_witness.take() {
                if !prev.name.is_empty() && !prev.kind.is_empty() {
                    cfg.witnesses.push(prev);
                }
            }
            section = Some(s.trim().to_lowercase());
            continue;
        }
        let Some(eq) = line.find('=') else { continue };
        let key = line[..eq].trim();
        let val = line[eq + 1..].trim().trim_matches('"').to_string();
        match (section.as_deref(), key) {
            (Some("authoring"), "surface") => cfg.surface_default = Some(val),
            (Some("authoring.lift"), "surface") => cfg.surface_lift = Some(val),
            (Some("solvers"), "default") => cfg.solver_default = Some(val),
            (Some("solvers"), "chain") => {
                cfg.solver_chain = parse_string_array(&val);
            }
            (Some("solvers"), "portfolio") => {
                cfg.solver_portfolio = parse_string_array(&val);
            }
            (Some("solvers"), "mode") => cfg.solver_mode = Some(val),
            (None, "trusted_implication_signers")
            | (Some("verify"), "trusted_implication_signers") => {
                cfg.trusted_implication_signers = parse_string_array(&val);
            }
            (Some("verify"), "callees") => {
                cfg.callees = parse_string_array(&val);
            }
            (Some("paths.mint"), "file") => cfg.path_mint = Some(val),
            // #1358 / #1355: [platform_profile] section
            (Some("platform_profile"), "language") => {
                cfg.platform_profile
                    .get_or_insert_with(PlatformProfile::default)
                    .language = Some(val);
            }
            (Some("platform_profile"), "family") => {
                cfg.platform_profile
                    .get_or_insert_with(PlatformProfile::default)
                    .family = Some(val);
            }
            (Some("platform_profile"), "library") => {
                cfg.platform_profile
                    .get_or_insert_with(PlatformProfile::default)
                    .library = Some(val);
            }
            (Some("platform_profile"), "version") => {
                cfg.platform_profile
                    .get_or_insert_with(PlatformProfile::default)
                    .version = Some(val);
            }
            (Some("plugins.entry"), "name") => {
                if let Some(entry) = current_plugin.as_mut() {
                    entry.name = Some(val);
                }
            }
            (Some("plugins.entry"), "kind") => {
                if let Some(entry) = current_plugin.as_mut() {
                    entry.kind = Some(val);
                }
            }
            (Some("plugins.entry"), "surface") => {
                if let Some(entry) = current_plugin.as_mut() {
                    entry.surface = val;
                }
            }
            (Some("plugins.entry"), "workspace_override") => {
                if let Some(entry) = current_plugin.as_mut() {
                    entry.workspace_override = Some(val);
                }
            }
            (Some("plugins.entry"), "emit") => {
                if let Some(entry) = current_plugin.as_mut() {
                    entry.emit = Some(val);
                }
            }
            (Some("plugins.entry"), "layer") => {
                if let Some(entry) = current_plugin.as_mut() {
                    entry.layer = Some(val);
                }
            }
            (Some("kits.entry"), "alias") => {
                if let Some(entry) = current_kit.as_mut() {
                    entry.alias = val;
                }
            }
            (Some("kits.entry"), "project") => {
                if let Some(entry) = current_kit.as_mut() {
                    entry.project = val;
                }
            }
            (Some("kits.entry"), "surface") => {
                if let Some(entry) = current_kit.as_mut() {
                    entry.surface = val;
                }
            }
            (Some("kits.entry"), "lang") => {
                if let Some(entry) = current_kit.as_mut() {
                    entry.lang = val;
                }
            }
            (Some("witnesses.entry"), "name") => {
                if let Some(entry) = current_witness.as_mut() {
                    entry.name = val;
                }
            }
            (Some("witnesses.entry"), "kind") => {
                if let Some(entry) = current_witness.as_mut() {
                    entry.kind = val;
                }
            }
            (Some("witnesses.entry"), "command") => {
                if let Some(entry) = current_witness.as_mut() {
                    entry.command = parse_string_array(&val);
                }
            }
            (Some("witnesses.entry"), "working_dir") => {
                if let Some(entry) = current_witness.as_mut() {
                    entry.working_dir = Some(val);
                }
            }
            (Some("witnesses.entry"), "path") => {
                if let Some(entry) = current_witness.as_mut() {
                    entry.path = Some(val);
                }
            }
            _ => {}
        }
    }
    // Flush the final in-flight entry.
    if let Some(prev) = current_plugin.take() {
        if !prev.surface.is_empty() {
            cfg.plugins.push(prev);
        }
    }
    if let Some(prev) = current_kit.take() {
        if !prev.alias.is_empty()
            && !prev.project.is_empty()
            && !prev.surface.is_empty()
            && !prev.lang.is_empty()
        {
            cfg.kits.push(prev);
        }
    }
    if let Some(prev) = current_witness.take() {
        if !prev.name.is_empty() && !prev.kind.is_empty() {
            cfg.witnesses.push(prev);
        }
    }
    cfg
}

fn parse_string_array(raw: &str) -> Vec<String> {
    // raw shape: `["z3", "cvc5"]` (already trimmed of surrounding quotes
    // by the parser; we re-handle here because the array form skipped that).
    // Be tolerant: split on comma, strip brackets and quotes.
    raw.trim_matches(|c: char| c == '[' || c == ']' || c == '"')
        .split(',')
        .map(|s| s.trim().trim_matches('"').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn strip_comment(s: &str) -> &str {
    if let Some(pos) = s.find('#') {
        &s[..pos]
    } else {
        s
    }
}

/// Surface menu shown by `sugar init`.
pub const KNOWN_SURFACES: &[&str] = &[
    "default",
    "rust-sugar-decorator",
    "rust-invariant-file",
    "rust-contracts-crate",
    "rust-kani",
    "rust-prusti",
    "rust-creusot",
    "rust-flux",
    "rust-verus",
    "rust-proptest",
    "rust-quickcheck",
    "python-pydantic",
    "python-deal",
    "python-hypothesis",
    "python-source",
    "ruby-source",
    "php-source",
    "java-source",
    "java-bean-validation",
    "java-jml",
    "jvm-bytecode",
    "csharp",
    "csharp-source",
    "cpp-26-contracts",
    "cpp-boost-contract",
    "cpp-source",
    "clr-bytecode",
    "swift-source",
    "zig-source",
];

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------
    // #1358 / #1355: [platform_profile] section parsing
    // -----------------------------------------------------------------

    #[test]
    fn parses_full_platform_profile_section() {
        let raw = r#"
[platform_profile]
language = "rust"
family = "concept:family:sql"
library = "rusqlite"
version = "0.39.0"
"#;
        let cfg = parse_config(raw);
        let profile = cfg.platform_profile.expect("platform_profile parsed");
        assert_eq!(profile.language.as_deref(), Some("rust"));
        assert_eq!(profile.family.as_deref(), Some("concept:family:sql"));
        assert_eq!(profile.library.as_deref(), Some("rusqlite"));
        assert_eq!(profile.version.as_deref(), Some("0.39.0"));
    }

    #[test]
    fn parses_trusted_implication_signers() {
        let raw = r#"
trusted_implication_signers = ["ed25519:alpha", "ed25519:beta"]
"#;
        let cfg = parse_config(raw);
        assert_eq!(
            cfg.trusted_implication_signers,
            vec!["ed25519:alpha".to_string(), "ed25519:beta".to_string()]
        );
    }

    #[test]
    fn parses_partial_platform_profile_with_floating_axes() {
        // Per #1355: any axis may float. Profile must parse cleanly when
        // only some axes are pinned.
        let raw = r#"
[platform_profile]
language = "rust"
family = "concept:family:hash"
"#;
        let cfg = parse_config(raw);
        let profile = cfg.platform_profile.expect("platform_profile parsed");
        assert_eq!(profile.language.as_deref(), Some("rust"));
        assert_eq!(profile.family.as_deref(), Some("concept:family:hash"));
        assert!(profile.library.is_none(), "library floats");
        assert!(profile.version.is_none(), "version floats");
    }

    #[test]
    fn absent_platform_profile_section_yields_none() {
        // Back-compat: configs without [platform_profile] still parse.
        let cfg = parse_config("[authoring]\nsurface = \"kani\"\n");
        assert!(cfg.platform_profile.is_none());
    }

    #[test]
    fn parses_surface_default() {
        let cfg = parse_config("[authoring]\nsurface = \"python-source\"\n");
        assert_eq!(cfg.surface_for("lift").as_deref(), Some("python-source"));
    }

    #[test]
    fn lift_surface_overrides_default() {
        let cfg = parse_config(
            "[authoring]\nsurface = \"python-source\"\n[authoring.lift]\nsurface = \"rust\"",
        );
        assert_eq!(cfg.surface_for("lift").as_deref(), Some("rust"));
    }

    #[test]
    fn comments_and_blanks_ignored() {
        let raw = "
        # comment
        [authoring]
        # mid
        surface = \"kani\"  # trailing
        ";
        let cfg = parse_config(raw);
        assert_eq!(cfg.surface_for("lift").as_deref(), Some("kani"));
    }

    #[test]
    fn parses_mint_path_file() {
        let cfg = parse_config("[paths.mint]\nfile = \".sugar/paths/mint.json\"\n");
        assert_eq!(
            cfg.path_for("mint").as_deref(),
            Some(".sugar/paths/mint.json")
        );
        assert_eq!(cfg.path_for("prove"), None);
    }

    #[test]
    fn parses_plugin_kind_for_dispatch_filtering() {
        let cfg = parse_config(
            r#"[[plugins]]
name = "java-testng-emitter"
kind = "emit"
surface = "java-testng"
emit = "testng"

[[plugins]]
name = "java-testng-lifter"
kind = "lift"
surface = "java-testng"
emit = "ir-document"

[[plugins]]
name = "rust-tests-lifter"
kind = "lift"
surface = "rust-tests"
"#,
        );
        assert_eq!(cfg.plugins.len(), 3);
        assert!(cfg.plugins[0].is_emit_plugin());
        assert!(!cfg.plugins[0].is_lift_plugin());
        assert!(cfg.plugins[1].is_lift_plugin());
        assert!(!cfg.plugins[1].is_emit_plugin());
        assert!(cfg.plugins[2].is_lift_plugin());
        assert!(!cfg.plugins[2].is_emit_plugin());
    }

    #[test]
    fn parses_kit_alias_entries() {
        let cfg = parse_config(
            r#"[[kits]]
alias = "rust-local"
project = "implementations/rust"
surface = "rust-contracts-crate"
lang = "rust"

[[kits]]
alias = "third-party"
project = "/opt/sugar/kits/third-party"
surface = "third-party-surface"
lang = "third-party"
"#,
        );

        assert_eq!(cfg.kits.len(), 2);
        assert_eq!(cfg.kits[0].alias, "rust-local");
        assert_eq!(cfg.kits[0].project, "implementations/rust");
        assert_eq!(cfg.kits[0].surface, "rust-contracts-crate");
        assert_eq!(cfg.kits[0].lang, "rust");
        assert_eq!(cfg.kits[1].alias, "third-party");
        assert_eq!(cfg.kits[1].project, "/opt/sugar/kits/third-party");
        assert_eq!(cfg.kits[1].surface, "third-party-surface");
        assert_eq!(cfg.kits[1].lang, "third-party");
    }

    #[test]
    fn parses_witness_entries() {
        let cfg = parse_config(
            r#"[[witnesses]]
name = "prove-report"
kind = "report"

[[witnesses]]
name = "unit-test-green"
kind = "command"
command = ["cargo", "test", "--lib"]

[[witnesses]]
name = "poem"
kind = "file"
path = "witnesses/poem.txt"
"#,
        );

        assert_eq!(cfg.witnesses.len(), 3);
        assert_eq!(cfg.witnesses[0].name, "prove-report");
        assert_eq!(cfg.witnesses[0].kind, "report");
        assert_eq!(
            cfg.witnesses[1].command,
            vec!["cargo".to_string(), "test".to_string(), "--lib".to_string()]
        );
        assert_eq!(cfg.witnesses[2].path.as_deref(), Some("witnesses/poem.txt"));
    }

    #[test]
    fn parses_kit_aliases_independently_from_project_plugins() {
        let cfg = parse_config(
            r#"[[kits]]
alias = "java"
project = "implementations/java"
surface = "java-testng"
lang = "java"

[[plugins]]
name = "java-testng-lifter"
kind = "lift"
surface = "java-testng"
"#,
        );

        assert_eq!(cfg.kits.len(), 1);
        assert_eq!(cfg.plugins.len(), 1);
        assert_eq!(cfg.kits[0].alias, "java");
        assert_eq!(cfg.plugins[0].surface, "java-testng");
    }

    #[test]
    fn missing_file_yields_default() {
        let p = std::env::temp_dir().join("sugar-no-such-config.toml");
        let _ = std::fs::remove_file(&p);
        let cfg = read_config_file(&p);
        assert!(cfg.surface_default.is_none());
    }

    #[test]
    fn known_lists_include_anchor_entries() {
        assert!(KNOWN_SURFACES.contains(&"default"));
        assert!(KNOWN_SURFACES.contains(&"php-source"));
        assert!(KNOWN_SURFACES.contains(&"ruby-source"));
        assert!(KNOWN_SURFACES.contains(&"csharp-source"));
        assert!(KNOWN_SURFACES.contains(&"swift-source"));
        assert!(KNOWN_SURFACES.contains(&"zig-source"));
        assert!(KNOWN_SURFACES.contains(&"clr-bytecode"));
    }
}
