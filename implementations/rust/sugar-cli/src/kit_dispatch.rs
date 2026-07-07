// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Kit-agnostic dispatcher for plugin surfaces.
// cmd_emit / cmd_bind call into here to invoke per-language plugins via
// PEP 1.7.0 (`2026-05-12-plugin-protocol.md`); none of those
// commands carry language-specific code, no `if source_lang == "rust"` and
// no `TargetStyle::*` arms.
//
// Dispatch surfaces:
//
//   1. `dispatch_emit(workspace_root, target_lang, framework, plan)`
//      Resolves a `kind = "emit"` plugin by `.sugar/emit/<surface>/manifest.toml`,
//      where surfaces are target/framework packages such as `go-testing`.
//      Invokes `sugar.plugin.invoke` with the neutral EmitPlan. The kit owns
//      all target/framework syntax; the CLI owns only dispatch/composition.
//
// Kit unavailability is a `kit-plugin-unavailable` gap, not a hidden error.
// Per Supra omnia, rectum the dispatcher refuses loudly with a gap record
// the caller turns into a `GapRecord` and propagates downstream.

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Mutex, OnceLock};

use sugar_canonicalizer::blake3_512_of;
use sugar_plugin_loader::{
    cid::compute_plugin_cid, write_plugin_registry_memento, PluginEnvelope, PluginHeader,
    PluginMemento, PluginMetadata, PluginRegistry, PluginRegistryMemento,
};
use sugar_verifier::load_all_proofs::ProofBytes;

use crate::project_config::read_project_config;

const REGISTRY_SEALED_AT: &str = "1970-01-01T00:00:00.000Z";
const REGISTRY_MANIFEST_KINDS: &[&str] = &["lift", "emit"];
const PEP_1_7_0: &str = "pep/1.7.0";

static RUN_PLUGIN_REGISTRIES: OnceLock<Mutex<BTreeMap<PathBuf, RunPluginRegistry>>> =
    OnceLock::new();
static KIT_DISPATCH_DIAGNOSTICS: OnceLock<Mutex<Vec<String>>> = OnceLock::new();

#[derive(Debug, Clone)]
pub struct SealedPluginRegistry {
    pub memento: PluginRegistryMemento,
    pub path: PathBuf,
}

#[derive(Debug, Clone)]
struct RunPluginRegistry {
    sealed: SealedPluginRegistry,
    plugins: Vec<ManifestPluginRegistration>,
}

#[derive(Debug, Clone)]
struct ManifestPluginRegistration {
    kind: String,
    surface: String,
    source: String,
    parsed: ParsedManifest,
    memento: PluginMemento,
}

pub fn reset_kit_dispatch_registry_cache_for_tests() {
    if let Some(cache) = RUN_PLUGIN_REGISTRIES.get() {
        cache.lock().expect("registry cache lock").clear();
    }
    let _ = drain_kit_dispatch_diagnostics();
}

pub fn drain_kit_dispatch_diagnostics() -> Vec<String> {
    let diagnostics = KIT_DISPATCH_DIAGNOSTICS.get_or_init(|| Mutex::new(Vec::new()));
    let mut diagnostics = diagnostics.lock().expect("diagnostics lock");
    std::mem::take(&mut *diagnostics)
}

fn run_plugin_registry_for_project(workspace_root: &Path) -> Result<RunPluginRegistry, String> {
    let key = registry_cache_key(workspace_root);
    let cache = RUN_PLUGIN_REGISTRIES.get_or_init(|| Mutex::new(BTreeMap::new()));
    if let Some(registry) = cache
        .lock()
        .expect("registry cache lock")
        .get(&key)
        .cloned()
    {
        return Ok(registry);
    }

    let registry = build_run_plugin_registry(&key)?;
    cache
        .lock()
        .expect("registry cache lock")
        .insert(key, registry.clone());
    Ok(registry)
}

fn registry_cache_key(workspace_root: &Path) -> PathBuf {
    std::fs::canonicalize(workspace_root).unwrap_or_else(|_| {
        if workspace_root.is_absolute() {
            workspace_root.to_path_buf()
        } else {
            std::env::current_dir()
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(workspace_root)
        }
    })
}

fn build_run_plugin_registry(workspace_root: &Path) -> Result<RunPluginRegistry, String> {
    let plugins = scan_manifest_plugins(workspace_root)?;
    let mut registry = PluginRegistry::new();
    for plugin in &plugins {
        registry
            .register(plugin.memento.clone(), &plugin.source)
            .map_err(|error| format!("register {}: {error}", plugin.source))?;
    }
    let memento = registry.emit_registry_memento(REGISTRY_SEALED_AT);
    let path = write_plugin_registry_memento(workspace_root, &memento)
        .map_err(|error| format!("write sealed PluginRegistryMemento: {error}"))?;
    Ok(RunPluginRegistry {
        sealed: SealedPluginRegistry { memento, path },
        plugins,
    })
}

fn scan_manifest_plugins(workspace_root: &Path) -> Result<Vec<ManifestPluginRegistration>, String> {
    let mut plugins = Vec::new();
    let configured_emit_surfaces = configured_emit_surface_names(workspace_root);
    for kind in REGISTRY_MANIFEST_KINDS {
        let kind_dir = workspace_root.join(".sugar").join(kind);
        let Ok(entries) = std::fs::read_dir(&kind_dir) else {
            continue;
        };
        let mut surfaces = entries
            .flatten()
            .filter_map(|entry| {
                let path = entry.path();
                if !path.is_dir() {
                    return None;
                }
                let surface = path.file_name()?.to_str()?.to_string();
                Some((surface, path))
            })
            .collect::<Vec<_>>();
        surfaces.sort_by(|a, b| a.0.cmp(&b.0));
        for (surface, path) in surfaces {
            if *kind == "emit" && !configured_emit_surfaces.contains(&surface) {
                continue;
            }
            let manifest_path = path.join("manifest.toml");
            if !manifest_path.exists() {
                continue;
            }
            let parsed = parse_manifest(&manifest_path)?;
            let source = registry_source(workspace_root, &manifest_path);
            let memento = manifest_plugin_memento(
                workspace_root,
                *kind,
                &surface,
                &source,
                &manifest_path,
                &parsed,
            )?;
            plugins.push(ManifestPluginRegistration {
                kind: (*kind).to_string(),
                surface,
                source,
                parsed,
                memento,
            });
        }
    }
    Ok(plugins)
}

fn registry_source(workspace_root: &Path, path: &Path) -> String {
    path.strip_prefix(workspace_root)
        .unwrap_or(path)
        .display()
        .to_string()
}

fn manifest_plugin_memento(
    workspace_root: &Path,
    kind: &str,
    surface: &str,
    source: &str,
    manifest_path: &Path,
    parsed: &ParsedManifest,
) -> Result<PluginMemento, String> {
    let manifest_bytes = std::fs::read(manifest_path)
        .map_err(|error| format!("read {}: {error}", manifest_path.display()))?;
    let working_dir = parsed
        .working_dir
        .as_ref()
        .map(|path| path.display().to_string());
    let content = json!({
        "kind": "manifest-plugin",
        "plugin_kind": kind,
        "surface": surface,
        "manifest_path": source,
        "manifest_cid": blake3_512_of(&manifest_bytes),
        "name": parsed.name.clone(),
        "command": parsed.command.clone(),
        "working_dir": working_dir,
        "library_tag": parsed.library_tag.clone(),
        "capability_kind": parsed.capability_kind.clone(),
        "workspace_relative": manifest_path.starts_with(workspace_root),
    });
    let mut protocol_versions = parsed.protocol_versions.clone();
    if protocol_versions.is_empty() {
        protocol_versions.push(PEP_1_7_0.to_string());
    }
    protocol_versions.sort();
    protocol_versions.dedup();
    let mut header = PluginHeader {
        cid: String::new(),
        content,
        critical: false,
        kind: kind.to_string(),
        protocol_versions,
        provenance_cid: blake3_512_of(&manifest_bytes),
        schema_version: "1".to_string(),
        version: "0.1.0".to_string(),
    };
    header.cid = compute_plugin_cid(&header);
    Ok(PluginMemento {
        envelope: PluginEnvelope {
            declared_at: REGISTRY_SEALED_AT.to_string(),
            signature: "ed25519:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA".to_string(),
            signer: "ed25519:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=".to_string(),
        },
        header,
        metadata: PluginMetadata::default(),
    })
}

fn registry_authorizes_plugin(
    registry: &RunPluginRegistry,
    plugin: &ManifestPluginRegistration,
) -> bool {
    registry
        .sealed
        .memento
        .header
        .load_order
        .iter()
        .any(|entry| {
            entry.kind == plugin.kind
                && entry.cid == plugin.memento.cid()
                && entry.source == plugin.source
        })
}

/// Ask every configured kit plugin for dependency proof catalogs resolved from
/// the project's package-manager graph. The substrate stays language-blind:
/// this function only iterates configured plugin commands and consumes proof
/// bytes over RPC. The CLI never follows package-system `.proof` paths.
pub fn dependency_proofs_via_rpc(workspace_root: &Path) -> Result<Vec<ProofBytes>, String> {
    let registry = run_plugin_registry_for_project(workspace_root)?;
    let mut commands: BTreeMap<String, ResolvedCommand> = BTreeMap::new();
    for plugin in registry
        .plugins
        .iter()
        .filter(|plugin| registry_authorizes_plugin(&registry, plugin))
    {
        let command = resolved_command_from_manifest(workspace_root, &plugin.parsed);
        if command.argv.is_empty() {
            continue;
        }
        commands
            .entry(command_key(&command))
            .or_insert_with(|| command);
    }

    let mut proofs = Vec::new();
    for command in commands.values() {
        let Some(mut resolved) = dependency_proofs_for_command(workspace_root, command)? else {
            continue;
        };
        proofs.append(&mut resolved);
    }
    proofs.sort_by(|a, b| {
        (a.expected_cid.as_str(), a.label.as_str())
            .cmp(&(b.expected_cid.as_str(), b.label.as_str()))
    });
    proofs.dedup_by(|a, b| a.expected_cid == b.expected_cid && a.bytes == b.bytes);
    Ok(proofs)
}

fn command_key(command: &ResolvedCommand) -> String {
    format!("{:?}\u{0}{:?}", command.argv, command.working_dir)
}

fn rpc_error_is_method_not_supported(error: &Value, method: &str) -> bool {
    let code = error.get("code").and_then(Value::as_i64);
    if code == Some(-32601) {
        return true;
    }
    let Some(message) = error.get("message").and_then(Value::as_str) else {
        return false;
    };
    let message = message.to_ascii_lowercase();
    (code == Some(-32602) || code == Some(-32603))
        && message.contains("unknown method")
        && message.contains(method)
}

fn dependency_proofs_for_command(
    workspace_root: &Path,
    cmd_spec: &ResolvedCommand,
) -> Result<Option<Vec<ProofBytes>>, String> {
    let mut command = Command::new(&cmd_spec.argv[0]);
    if cmd_spec.argv.len() > 1 {
        command.args(&cmd_spec.argv[1..]);
    }
    if !cmd_spec.argv.iter().any(|a| a == "--rpc") {
        command.arg("--rpc");
    }
    if let Some(wd) = &cmd_spec.working_dir {
        command.current_dir(wd);
    }
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::inherit());

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            record_dependency_proof_diagnostic(format!(
                "dependency proof resolver unavailable for {:?}: {error}",
                cmd_spec.argv
            ));
            return Ok(None);
        }
    };
    let mut stdin = child
        .stdin
        .take()
        .ok_or("dependency proof kit stdin unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or("dependency proof kit stdout unavailable".to_string())?;
    let mut reader = BufReader::new(stdout);

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.resolve_dependency_proofs",
        "params": {
            "project_root": workspace_root.display().to_string(),
        },
    });
    writeln!(stdin, "{req}").map_err(|e| format!("write resolve_dependency_proofs: {e}"))?;

    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| format!("read resolve_dependency_proofs response: {e}"))?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sugar.plugin.shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    if line.trim().is_empty() {
        record_dependency_proof_diagnostic(format!(
            "dependency proof resolver {:?} closed without a response",
            cmd_spec.argv
        ));
        return Ok(None);
    }

    let response: Value = serde_json::from_str(line.trim()).map_err(|e| {
        format!(
            "resolve_dependency_proofs response not valid JSON: {e}; raw={}",
            line.trim()
        )
    })?;
    if let Some(error) = response.get("error") {
        if rpc_error_is_method_not_supported(error, "sugar.plugin.resolve_dependency_proofs") {
            record_dependency_proof_diagnostic(format!(
                "dependency proof resolver {:?} does not implement sugar.plugin.resolve_dependency_proofs",
                cmd_spec.argv
            ));
            return Ok(None);
        }
        return Err(format!("dependency proof resolver error: {error}"));
    }

    let result = response.get("result").cloned().unwrap_or(Value::Null);
    let proofs = result
        .get("proofs")
        .or_else(|| result.get("proofs_base64"))
        .or_else(|| result.get("proofBytes"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut out = Vec::new();
    for proof in proofs {
        match decode_dependency_proof_entry(cmd_spec, &proof) {
            Ok(Some(decoded)) => out.push(decoded),
            Ok(None) => continue,
            Err(error) => return Err(error),
        }
    }

    let legacy_paths = result
        .get("proof_paths")
        .or_else(|| result.get("proofPaths"))
        .or_else(|| result.get("paths"))
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    if legacy_paths > 0 {
        record_dependency_proof_diagnostic(format!(
            "dependency proof resolver {:?} returned legacy proof_paths; ignoring paths because package proof bytes must cross RPC",
            cmd_spec.argv
        ));
    }

    out.sort_by(|a, b| {
        (a.expected_cid.as_str(), a.label.as_str())
            .cmp(&(b.expected_cid.as_str(), b.label.as_str()))
    });
    out.dedup_by(|a, b| a.expected_cid == b.expected_cid && a.bytes == b.bytes);
    Ok(Some(out))
}

fn decode_dependency_proof_entry(
    cmd_spec: &ResolvedCommand,
    proof: &Value,
) -> Result<Option<ProofBytes>, String> {
    let Some(object) = proof.as_object() else {
        record_dependency_proof_diagnostic(format!(
            "dependency proof resolver {:?} returned a non-object proof entry: {proof}",
            cmd_spec.argv
        ));
        return Ok(None);
    };
    let label_field = object
        .get("source")
        .or_else(|| object.get("label"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let Some(expected_cid) = object
        .get("cid")
        .or_else(|| object.get("proof_cid"))
        .or_else(|| object.get("proofCid"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        let label = label_field
            .as_deref()
            .unwrap_or("<unlabeled dependency proof>");
        return Err(format!(
            "dependency proof resolver `{}` kit returned dependency proof without a content address for label `{label}`",
            cmd_spec.plugin_name
        ));
    };
    let Some(bytes_base64) = object
        .get("bytes_base64")
        .or_else(|| object.get("bytesBase64"))
        .and_then(Value::as_str)
    else {
        record_dependency_proof_diagnostic(format!(
            "dependency proof resolver {:?} returned a proof entry without bytes_base64: {proof}",
            cmd_spec.argv
        ));
        return Ok(None);
    };
    let bytes = match BASE64.decode(bytes_base64) {
        Ok(bytes) => bytes,
        Err(error) => {
            record_dependency_proof_diagnostic(format!(
                "dependency proof resolver {:?} returned invalid bytes_base64: {error}",
                cmd_spec.argv
            ));
            return Ok(None);
        }
    };
    let label = label_field.unwrap_or_else(|| expected_cid.clone());

    // #3813: a kit's package-manager dependency catalog IS vendor testimony.
    // Stamp the Vendor role INTO the ProofBytes here, at the one point that
    // knows where these bytes came from, so the pool intake downstream never
    // has to guess (the loader honors `ProofBytes::speaker`; it no longer
    // hardcodes Consumer). The speaker id is the kit/package label the
    // entry already carries.
    let speaker = sugar_verifier::Speaker::vendor(label.clone());
    match ProofBytes::try_from_parts(label, expected_cid, bytes, speaker) {
        Ok(proof) => Ok(Some(proof)),
        Err(error) => {
            record_dependency_proof_diagnostic(format!(
                "dependency proof resolver {:?} returned invalid expected_cid: {error}",
                cmd_spec.argv
            ));
            Ok(None)
        }
    }
}

fn record_dependency_proof_diagnostic(message: String) {
    tracing::warn!("{}", message);
    KIT_DISPATCH_DIAGNOSTICS
        .get_or_init(|| Mutex::new(Vec::new()))
        .lock()
        .expect("diagnostics lock")
        .push(message);
}

fn resolved_command_from_manifest(
    workspace_root: &Path,
    parsed: &ParsedManifest,
) -> ResolvedCommand {
    let workspace_root = absolute_workspace_root(workspace_root);
    let mut argv = parsed.command.clone();
    if let Some(program) = argv.first_mut() {
        let path = Path::new(program);
        if path.is_relative() && path.components().count() > 1 {
            *program = workspace_root.join(path).to_string_lossy().into_owned();
        }
    }
    let working_dir = parsed
        .working_dir
        .clone()
        .map(|wd| {
            if wd.is_absolute() {
                wd
            } else {
                workspace_root.join(wd)
            }
        })
        .or_else(|| Some(workspace_root));
    ResolvedCommand {
        plugin_name: parsed.name.clone(),
        argv,
        working_dir,
    }
}

fn absolute_workspace_root(workspace_root: &Path) -> PathBuf {
    if workspace_root.is_absolute() {
        return workspace_root.to_path_buf();
    }
    std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join(workspace_root)
}

fn record_fallback_diagnostic(kind: &str, surface: &str) {
    let message =
        format!("deprecated kit_dispatch filesystem fallback: kind={kind} surface={surface}");
    tracing::warn!("{}", message);
    KIT_DISPATCH_DIAGNOSTICS
        .get_or_init(|| Mutex::new(Vec::new()))
        .lock()
        .expect("diagnostics lock")
        .push(message);
}

/// Refusal raised when a kit cannot be reached.
/// or returns an unusable response. Callers turn this into a
/// `kit-plugin-unavailable` gap record and proceed loudly-bounded-lossy per
/// `body-template-memento.md` §5.
#[derive(Debug)]
pub struct KitUnavailable {
    pub kit_kind: &'static str,
    pub language: String,
    pub detail: String,
}

impl std::fmt::Display for KitUnavailable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "kit-plugin-unavailable: no {} plugin for language `{}` ({})",
            self.kit_kind, self.language, self.detail
        )
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ResolvedCommand {
    pub(crate) plugin_name: String,
    pub(crate) argv: Vec<String>,
    pub(crate) working_dir: Option<PathBuf>,
}

#[derive(Debug, Clone)]
struct ParsedManifest {
    name: String,
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    library_tag: Option<String>,
    protocol_versions: Vec<String>,
    capability_kind: Option<String>,
}

fn parse_manifest(path: &Path) -> Result<ParsedManifest, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let mut name = String::new();
    let mut command: Vec<String> = Vec::new();
    let mut working_dir: Option<PathBuf> = None;
    let mut library_tag: Option<String> = None;
    let mut protocol_versions: Vec<String> = Vec::new();
    let mut capability_kind: Option<String> = None;
    let mut section = String::new();
    let strip = |l: &str| -> String {
        match l.find('#') {
            Some(pos) => l[..pos].trim().to_string(),
            None => l.trim().to_string(),
        }
    };
    let lines: Vec<&str> = text.lines().collect();
    let mut idx = 0;
    while idx < lines.len() {
        let line = strip(lines[idx]);
        idx += 1;
        if line.is_empty() {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            section = line
                .trim_start_matches('[')
                .trim_end_matches(']')
                .trim()
                .to_string();
            continue;
        }
        let Some(eq) = line.find('=') else { continue };
        let key = line[..eq].trim().to_string();
        let mut val = line[eq + 1..].trim().to_string();
        // Multi-line array value (TOML `key = [` then elements on later lines):
        // accumulate continuation lines until the closing `]`, mirroring
        // cmd_prove::parse_manifest. Without this a multi-line `command` parses
        // empty and dependency-proof resolution is silently skipped.
        if val.starts_with('[') && !val.contains(']') {
            while idx < lines.len() && !val.contains(']') {
                val.push(' ');
                val.push_str(&strip(lines[idx]));
                idx += 1;
            }
        }
        let key = key.as_str();
        let val = val.as_str();
        match (section.as_str(), key) {
            ("", "name") => name = val.trim_matches('"').to_string(),
            ("", "working_dir") => working_dir = Some(PathBuf::from(val.trim_matches('"'))),
            ("", "protocol_versions") => protocol_versions = parse_toml_string_array(val),
            ("", "library_tag") => {
                let tag = val.trim_matches('"').to_string();
                validate_library_tag(&tag).map_err(|detail| {
                    format!(
                        "manifest {} has invalid `library_tag` `{tag}`: {detail}",
                        path.display()
                    )
                })?;
                library_tag = Some(tag);
            }
            ("", "command") => command = parse_toml_string_array(val),
            ("capabilities", "kind") => capability_kind = Some(val.trim_matches('"').to_string()),
            _ => {}
        }
    }
    if command.is_empty() {
        return Err(format!("manifest {} has no `command`", path.display()));
    }
    Ok(ParsedManifest {
        name,
        command,
        working_dir,
        library_tag,
        protocol_versions,
        capability_kind,
    })
}

/// Parse a TOML inline string array like `["a", "b", "c"]`.
///
/// Quote-aware: commas inside `"..."` are NOT separators.
fn parse_toml_string_array(value: &str) -> Vec<String> {
    let inner = value.trim().trim_matches(|c| c == '[' || c == ']');
    let mut out: Vec<String> = Vec::new();
    let mut current = String::new();
    let mut in_quote = false;
    let mut escape = false;
    for ch in inner.chars() {
        if escape {
            current.push(ch);
            escape = false;
            continue;
        }
        match ch {
            '\\' if in_quote => {
                current.push(ch);
                escape = true;
            }
            '"' => {
                in_quote = !in_quote;
                current.push(ch);
            }
            ',' if !in_quote => {
                let trimmed = current.trim().trim_matches('"').to_string();
                if !trimmed.is_empty() {
                    out.push(trimmed);
                }
                current.clear();
            }
            _ => current.push(ch),
        }
    }
    let trimmed = current.trim().trim_matches('"').to_string();
    if !trimmed.is_empty() {
        out.push(trimmed);
    }
    out
}

fn validate_library_tag(tag: &str) -> Result<(), &'static str> {
    let mut chars = tag.chars();
    let Some(first) = chars.next() else {
        return Err("expected [a-z][a-z0-9-]*");
    };
    if !first.is_ascii_lowercase() {
        return Err("expected [a-z][a-z0-9-]*");
    }
    if !chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-') {
        return Err("expected [a-z][a-z0-9-]*");
    }
    Ok(())
}

fn read_response(reader: &mut impl BufRead, id: i64) -> Result<Value, String> {
    let mut line = String::new();
    let n = reader
        .read_line(&mut line)
        .map_err(|e| format!("read response: {e}"))?;
    if n == 0 {
        return Err("lift kit closed stdout before responding".to_string());
    }
    let value: Value = serde_json::from_str(line.trim())
        .map_err(|e| format!("parse JSON-RPC response: {e}; raw={}", line.trim()))?;
    if value.get("id").and_then(Value::as_i64) != Some(id) {
        return Err(format!(
            "response id mismatch: expected {id}, got {value:?}"
        ));
    }
    if let Some(err) = value.get("error") {
        return Err(format!("kit returned error: {err}"));
    }
    value
        .get("result")
        .cloned()
        .ok_or_else(|| "response missing `result`".to_string())
}

// Emit dispatch (PEP 1.7.0 kind = "emit", method `sugar.plugin.invoke`)
// ============================================================================

/// Result of dispatching to an emit kit. The raw kit result is intentionally
/// preserved: emitter packages own their result schema beyond the common
/// `{source, extension, emitted_artifact_cid, ...}` fields consumed by the CLI.
#[derive(Debug, Clone)]
pub struct EmitDispatchResult {
    pub surface: String,
    pub source: String,
    pub result: Value,
}

#[derive(Debug, Clone)]
struct EmitCandidate {
    surface: String,
    command: ResolvedCommand,
    source: String,
}

/// Dispatch a neutral EmitPlan to a target/framework emitter kit.
///
/// This is deliberately not a Go/Java/Python parser. The substrate resolves an
/// emit manifest and sends JSON to the kit; the kit owns framework syntax and
/// target-language source generation.
pub fn dispatch_emit(
    workspace_root: &Path,
    target_lang: &str,
    framework: &str,
    plan: &Value,
) -> Result<EmitDispatchResult, KitUnavailable> {
    let candidate = resolve_emit_command(workspace_root, target_lang, framework)?;
    invoke_emit(target_lang, framework, &candidate, plan).map_err(|detail| KitUnavailable {
        kit_kind: "emit",
        language: target_lang.to_string(),
        detail,
    })
}

/// Ask the same configured emit kit to validate the emitted artifact using
/// its native ecosystem. The CLI supplies paths and normalized context over
/// RPC; the selected kit owns every target-language and framework decision.
pub fn dispatch_emit_check(
    workspace_root: &Path,
    target_lang: &str,
    framework: &str,
    plan: &Value,
    out_dir: &Path,
    artifact_path: &Path,
    emit_result: &Value,
) -> Result<Value, KitUnavailable> {
    let candidate = resolve_emit_command(workspace_root, target_lang, framework)?;
    invoke_emit_check(
        target_lang,
        framework,
        &candidate,
        plan,
        out_dir,
        artifact_path,
        emit_result,
    )
    .map_err(|detail| KitUnavailable {
        kit_kind: "emit",
        language: target_lang.to_string(),
        detail,
    })
}

fn resolve_emit_command(
    workspace_root: &Path,
    target_lang: &str,
    framework: &str,
) -> Result<EmitCandidate, KitUnavailable> {
    let registry_candidates = registry_emit_candidates(workspace_root, target_lang, framework)
        .map_err(|detail| KitUnavailable {
            kit_kind: "emit",
            language: target_lang.to_string(),
            detail,
        })?;
    if let Some(candidate) = select_emit_candidate(&registry_candidates, target_lang, framework) {
        return Ok(candidate);
    }

    record_fallback_diagnostic("emit", &format!("{target_lang}-{framework}"));
    let live_candidates =
        project_emit_candidates(workspace_root, target_lang, framework).map_err(|detail| {
            KitUnavailable {
                kit_kind: "emit",
                language: target_lang.to_string(),
                detail,
            }
        })?;
    if let Some(candidate) = select_emit_candidate(&live_candidates, target_lang, framework) {
        return Ok(candidate);
    }

    let registered = live_candidates
        .iter()
        .chain(registry_candidates.iter())
        .map(|candidate| format!("{} from {}", candidate.surface, candidate.source))
        .collect::<Vec<_>>();
    let registered = if registered.is_empty() {
        "none".to_string()
    } else {
        registered.join(", ")
    };
    Err(KitUnavailable {
        kit_kind: "emit",
        language: target_lang.to_string(),
        detail: format!(
            "no emit plugin for target `{target_lang}` and framework `{framework}`. \
             expected a project [[plugins]] registration in .sugar/config.toml \
             and a .sugar/emit/{target_lang}-{framework}/manifest.toml. \
             registered: {registered}"
        ),
    })
}

fn registry_emit_candidates(
    workspace_root: &Path,
    target_lang: &str,
    framework: &str,
) -> Result<Vec<EmitCandidate>, String> {
    let configured = configured_emit_surfaces(workspace_root, target_lang, framework);
    if configured.is_empty() {
        return Ok(Vec::new());
    }
    let registry = run_plugin_registry_for_project(workspace_root)?;
    let mut candidates = registry
        .plugins
        .iter()
        .filter(|plugin| registry_authorizes_plugin(&registry, plugin))
        .filter(|plugin| plugin.kind == "emit")
        .filter(|plugin| configured.contains(&plugin.surface))
        .filter(|plugin| emit_surface_matches(&plugin.surface, target_lang, framework))
        .map(|plugin| EmitCandidate {
            surface: plugin.surface.clone(),
            command: resolved_command_from_manifest(workspace_root, &plugin.parsed),
            source: plugin.source.clone(),
        })
        .collect::<Vec<_>>();
    candidates.sort_by(|a, b| a.surface.cmp(&b.surface).then(a.source.cmp(&b.source)));
    Ok(candidates)
}

fn project_emit_candidates(
    workspace_root: &Path,
    target_lang: &str,
    framework: &str,
) -> Result<Vec<EmitCandidate>, String> {
    let configured = configured_emit_surfaces(workspace_root, target_lang, framework);
    if configured.is_empty() {
        return Ok(Vec::new());
    }

    let mut out = Vec::new();
    for surface in configured {
        let path = workspace_root.join(".sugar").join("emit").join(&surface);
        let manifest = path.join("manifest.toml");
        if !manifest.exists() {
            continue;
        }
        let parsed = parse_manifest(&manifest)?;
        out.push(EmitCandidate {
            surface,
            command: resolved_command_from_manifest(workspace_root, &parsed),
            source: manifest.display().to_string(),
        });
    }
    Ok(out)
}

fn configured_emit_surface_names(workspace_root: &Path) -> BTreeSet<String> {
    read_project_config(workspace_root)
        .plugins
        .into_iter()
        .filter(|plugin| plugin.is_emit_plugin())
        .filter_map(|plugin| {
            let surface = plugin.surface.trim().to_string();
            (!surface.is_empty()).then_some(surface)
        })
        .collect()
}

fn configured_emit_surfaces(
    workspace_root: &Path,
    target_lang: &str,
    framework: &str,
) -> Vec<String> {
    let exact_surface = format!("{target_lang}-{framework}");
    let mut surfaces = read_project_config(workspace_root)
        .plugins
        .into_iter()
        .filter(|plugin| plugin.is_emit_plugin())
        .filter_map(|plugin| {
            let surface = plugin.surface.trim().to_string();
            if surface.is_empty() || !emit_surface_matches(&surface, target_lang, framework) {
                return None;
            }
            if let Some(emit) = plugin.emit.as_deref() {
                let emit = emit.trim();
                if emit != framework && emit != exact_surface && emit != surface {
                    return None;
                }
            }
            Some(surface)
        })
        .collect::<Vec<_>>();
    surfaces.sort();
    surfaces.dedup();
    surfaces
}

fn select_emit_candidate(
    candidates: &[EmitCandidate],
    target_lang: &str,
    framework: &str,
) -> Option<EmitCandidate> {
    let exact_surface = format!("{target_lang}-{framework}");
    candidates
        .iter()
        .find(|candidate| candidate.surface == exact_surface)
        .cloned()
        .or_else(|| {
            if candidates.len() == 1 {
                candidates.first().cloned()
            } else {
                None
            }
        })
}

fn emit_surface_matches(surface: &str, target_lang: &str, framework: &str) -> bool {
    if framework.is_empty() {
        return surface == target_lang;
    }
    surface == format!("{target_lang}-{framework}")
}

fn invoke_emit(
    target_lang: &str,
    framework: &str,
    candidate: &EmitCandidate,
    plan: &Value,
) -> Result<EmitDispatchResult, String> {
    if candidate.command.argv.is_empty() {
        return Err("empty command".to_string());
    }
    let mut command = Command::new(&candidate.command.argv[0]);
    if candidate.command.argv.len() > 1 {
        command.args(&candidate.command.argv[1..]);
    }
    if !candidate.command.argv.iter().any(|arg| arg == "--rpc") {
        command.arg("--rpc");
    }
    if let Some(wd) = &candidate.command.working_dir {
        command.current_dir(wd);
    }
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(
        if std::env::var("SUGAR_PLUGIN_STDERR").as_deref() == Ok("null") {
            Stdio::null()
        } else {
            Stdio::inherit()
        },
    );

    let mut child = command
        .spawn()
        .map_err(|e| format!("spawn emit kit: {e}"))?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "emit kit stdin unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "emit kit stdout unavailable".to_string())?;
    let mut reader = BufReader::new(stdout);

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.invoke",
        "params": plan,
    });
    writeln!(stdin, "{req}").map_err(|e| format!("write emit request: {e}"))?;
    let result = read_response(&mut reader, 1).map_err(|e| {
        format!(
            "emit kit `{}` for {target_lang}/{framework}: {e}",
            candidate.surface
        )
    })?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sugar.plugin.shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    let source = result
        .get("source")
        .and_then(Value::as_str)
        .ok_or_else(|| "emit response missing result.source".to_string())?
        .to_string();
    Ok(EmitDispatchResult {
        surface: candidate.surface.clone(),
        source,
        result,
    })
}

fn invoke_emit_check(
    target_lang: &str,
    framework: &str,
    candidate: &EmitCandidate,
    plan: &Value,
    out_dir: &Path,
    artifact_path: &Path,
    emit_result: &Value,
) -> Result<Value, String> {
    if candidate.command.argv.is_empty() {
        return Err("empty command".to_string());
    }
    let mut command = Command::new(&candidate.command.argv[0]);
    if candidate.command.argv.len() > 1 {
        command.args(&candidate.command.argv[1..]);
    }
    if !candidate.command.argv.iter().any(|arg| arg == "--rpc") {
        command.arg("--rpc");
    }
    if let Some(wd) = &candidate.command.working_dir {
        command.current_dir(wd);
    }
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(
        if std::env::var("SUGAR_PLUGIN_STDERR").as_deref() == Ok("null") {
            Stdio::null()
        } else {
            Stdio::inherit()
        },
    );

    let mut child = command
        .spawn()
        .map_err(|e| format!("spawn emit kit check: {e}"))?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "emit kit stdin unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "emit kit stdout unavailable".to_string())?;
    let mut reader = BufReader::new(stdout);

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.check",
        "params": {
            "plan": plan,
            "out_dir": out_dir,
            "artifact_path": artifact_path,
            "emit_result": emit_result,
        },
    });
    writeln!(stdin, "{req}").map_err(|e| format!("write emit check request: {e}"))?;
    let result = read_response(&mut reader, 1).map_err(|e| {
        format!(
            "emit kit `{}` check for {target_lang}/{framework}: {e}",
            candidate.surface
        )
    })?;

    let shutdown = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sugar.plugin.shutdown",
    });
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    Ok(result)
}

// Per #1270 Tier 1.4: configure_java_runtime + java_home_from_maven removed.
// JVM-runtime discovery is the user's environment concern (set JAVA_HOME),
// not the kit-agnostic dispatcher's job. The dispatcher does not know that
// "java" is a runtime invocation; it just executes whatever the kit's
// manifest declares as its launcher.

// ============================================================================
// Emit witness dispatch (ORP witness emitter)
// ============================================================================

pub fn dispatch_emit_witness(
    workspace_root: &Path,
    surface: &str,
    plan: &Value,
) -> Result<Value, String> {
    let resolved = resolve_emit_surface_command(workspace_root, surface)?;
    rpc_emit_witness(workspace_root, surface, &resolved, plan)
}

fn resolve_emit_surface_command(
    workspace_root: &Path,
    surface: &str,
) -> Result<ResolvedCommand, String> {
    let configured = configured_emit_surface_names(workspace_root);
    if !configured.contains(surface) {
        return Err(format!(
            "no emit plugin registration for surface `{surface}` in .sugar/config.toml"
        ));
    }

    let registry = run_plugin_registry_for_project(workspace_root)?;
    if let Some(plugin) = registry
        .plugins
        .iter()
        .filter(|plugin| registry_authorizes_plugin(&registry, plugin))
        .find(|plugin| plugin.kind == "emit" && plugin.surface == surface)
    {
        return Ok(resolved_command_from_manifest(
            workspace_root,
            &plugin.parsed,
        ));
    }

    record_fallback_diagnostic("emit", surface);
    let manifest = workspace_root
        .join(".sugar")
        .join("emit")
        .join(surface)
        .join("manifest.toml");
    if !manifest.exists() {
        return Err(format!(
            "no emit plugin for surface `{surface}`; expected {}",
            manifest.display()
        ));
    }
    let parsed = parse_manifest(&manifest)?;
    Ok(resolved_command_from_manifest(workspace_root, &parsed))
}

fn rpc_emit_witness(
    workspace_root: &Path,
    surface: &str,
    cmd_spec: &ResolvedCommand,
    plan: &Value,
) -> Result<Value, String> {
    if cmd_spec.argv.is_empty() {
        return Err("empty command".to_string());
    }
    let mut command = Command::new(&cmd_spec.argv[0]);
    if cmd_spec.argv.len() > 1 {
        command.args(&cmd_spec.argv[1..]);
    }
    if !cmd_spec.argv.iter().any(|a| a == "--rpc") {
        command.arg("--rpc");
    }
    if let Some(wd) = &cmd_spec.working_dir {
        command.current_dir(wd);
    }
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());

    let mut child = command
        .spawn()
        .map_err(|e| format!("spawn emit kit: {e}"))?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or("emit kit stdin unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or("emit kit stdout unavailable".to_string())?;
    let stderr = child.stderr.take();
    let stderr_handle = stderr.map(|mut h| {
        std::thread::spawn(move || {
            let mut buf = String::new();
            let _ = std::io::Read::read_to_string(&mut h, &mut buf);
            buf
        })
    });
    let mut reader = BufReader::new(stdout);

    let emit_req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.invoke",
        "params": {
            "surface": surface,
            "workspace_root": workspace_root.display().to_string(),
            "plan": plan
        }
    });
    writeln!(stdin, "{emit_req}").map_err(|e| format!("write emit witness request: {e}"))?;
    let response = read_response(&mut reader, 1);
    if let Err(message) = &response {
        let _ = writeln!(
            stdin,
            "{{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"sugar.plugin.shutdown\"}}"
        );
        drop(stdin);
        let _ = child.wait();
        let stderr_text = stderr_handle
            .and_then(|h| h.join().ok())
            .unwrap_or_default();
        return Err(if stderr_text.is_empty() {
            message.clone()
        } else {
            format!("{message}\nemit kit stderr:\n{stderr_text}")
        });
    }
    let response = response?;

    let shutdown_req = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sugar.plugin.shutdown"
    });
    let _ = writeln!(stdin, "{shutdown_req}");
    drop(stdin);
    let _ = child.wait();
    let _ = stderr_handle.and_then(|h| h.join().ok());
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn optional_rpc_method_refusal_accepts_legacy_unknown_method_error() {
        assert!(rpc_error_is_method_not_supported(
            &json!({"code": -32601, "message": "method not found"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
        assert!(rpc_error_is_method_not_supported(
            &json!({"code": -32602, "message": "unknown method: sugar.plugin.resolve_dependency_proofs"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
        assert!(rpc_error_is_method_not_supported(
            &json!({"code": -32603, "message": "unknown method: sugar.plugin.resolve_dependency_proofs"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
        assert!(!rpc_error_is_method_not_supported(
            &json!({"code": -32602, "message": "invalid params"}),
            "sugar.plugin.resolve_dependency_proofs"
        ));
    }

    #[test]
    fn resolved_manifest_command_paths_are_project_root_anchored() {
        let project_root = PathBuf::from("relative-project-root");
        let parsed = ParsedManifest {
            name: "python-tests".to_string(),
            command: vec!["./lift-shim.sh".to_string()],
            working_dir: Some(PathBuf::from(".")),
            library_tag: None,
            protocol_versions: Vec::new(),
            capability_kind: None,
        };

        let resolved = resolved_command_from_manifest(&project_root, &parsed);
        assert!(Path::new(&resolved.argv[0]).is_absolute());
        assert_eq!(
            PathBuf::from(&resolved.argv[0]),
            std::env::current_dir()
                .expect("cwd")
                .join(&project_root)
                .join("./lift-shim.sh")
        );
        assert!(resolved
            .working_dir
            .as_ref()
            .expect("working dir")
            .is_absolute());
    }

    #[test]
    fn library_tag_validation_accepts_stable_identifier_shape() {
        assert!(validate_library_tag("urllib").is_ok());
        assert!(validate_library_tag("apache-httpclient").is_ok());
        assert!(validate_library_tag("httpx2").is_ok());
        assert!(validate_library_tag("").is_err());
        assert!(validate_library_tag("Requests").is_err());
        assert!(validate_library_tag("urllib.request").is_err());
        assert!(validate_library_tag("1requests").is_err());
    }
}
