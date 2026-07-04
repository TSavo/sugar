// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar recognize`: kit-owned source-level recognition per protocol §4.2.5.
//
// Walks user source files, asks the language kit (via the lift plugin manifest
// for the requested surface) to recognize native source against kit-owned sugar
// templates, and emits tier-`exact` tags for matches. The CLI never reads
// `.proof` files or manufactures recognizer templates; proof/package/language
// resolution belongs to the kit behind the RPC seam.
//
// This is the Tron-named verb: each kit's recognizer walks the grid for
// shapes that belong to its system. The substrate stays language-blind; only
// the kit reads AST shapes. See:
//   protocol/specs/2026-05-12-plugin-protocol.md §4.2.5
//   implementations/rust/sugar-walk/src/bin/walk_rpc.rs `recognize` handler

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use std::collections::BTreeSet;

use clap::Parser;
use libsugar::core::emit_obligation::{build_implication_contract_body, canonical_value_of_json};
use owo_colors::OwoColorize;
use serde_json::{json, Value};
use sugar_claim_envelope::{mint_bridge, MintBridgeArgs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, proof_filename, BridgeMemento, ContractBody,
    ContractMemento, ContractMementoRef, Ed25519Seed, FlatAtom, ProofEnvelopeInput, ProofGraph,
};

use crate::project_config::{read_project_config, read_user_config, PluginEntry, ProjectConfig};
use crate::{OutputFlags, EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

// Distinct signer seed for recognize-emitted bridges. Different from
// materialize's so the verifier can audit which lane authored each
// bridge in a mixed pool (both lanes emit the same body shape; the
// signer identity carries provenance).
const RECOGNIZE_BRIDGE_SIGNER_SEED: Ed25519Seed = [0x72; 32]; // 'r' for recognize
const RECOGNIZE_BRIDGE_DECLARED_AT: &str = "2026-05-28T00:00:00.000Z";

/// Arguments accepted by `sugar recognize`.
#[derive(Parser, Debug, Clone, Default)]
pub struct RecognizeArgs {
    /// Project root containing `.sugar/lift/<surface>/manifest.toml`.
    /// Defaults to current directory.
    #[arg(long)]
    pub project: Option<PathBuf>,
    /// Source paths (relative to project root) to scan for matches.
    /// Repeatable. e.g. `--source src/lib.rs --source src/ingest.rs`.
    #[arg(long = "source")]
    pub source_paths: Vec<String>,
    /// Lift surface name. If omitted, resolves from project/user config.
    #[arg(long)]
    pub surface: Option<String>,
    /// Mint bridge mementos from recognize tags into the project's
    /// `.sugar/recognize/<cid>.proof`. Without this flag, the verb
    /// is a dry-run that only prints tags. With it, the bridges land
    /// in the proof pool and become first-class citizens in `sugar
    /// prove` — same shape as materialize-authored bridges.
    #[arg(long)]
    pub write: bool,
    /// Source language (target of the kit). Today defaults to "rust".
    /// Reserved for the polyglot case once Java/Python/TS/Go kits get
    /// their own ast_template lifters.
    #[arg(long = "target", default_value = "rust")]
    pub target_language: String,
    #[command(flatten)]
    pub out: OutputFlags,
}

pub fn run(args: RecognizeArgs) -> u8 {
    let project_root = match args
        .project
        .clone()
        .map(|p| p.canonicalize().unwrap_or(p))
        .or_else(|| std::env::current_dir().ok())
    {
        Some(p) => p,
        None => {
            eprintln!("{}: cannot resolve project root", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };

    let surface = match resolve_recognize_surface(args.surface.as_deref(), &project_root) {
        Ok(surface) => surface,
        Err(e) => {
            eprintln!("{}: {e}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };
    let manifest = match find_plugin_manifest(&project_root, &surface) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("{}: {e}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };

    if !args.out.json && !args.out.quiet {
        eprintln!(
            "{}: surface=`{}` sources={}",
            "dispatch".green().bold(),
            surface,
            args.source_paths.len(),
        );
    }

    // Dispatch the recognize RPC.
    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.recognize",
        "params": {
            "project_root": project_root.to_string_lossy(),
            "source_paths": args.source_paths,
        }
    });

    let tags = match invoke_plugin(&manifest, &project_root, &req) {
        Ok(resp) => match resp.get("result").and_then(|r| r.get("tags")).cloned() {
            Some(Value::Array(a)) => a,
            _ => {
                eprintln!(
                    "{}: plugin response missing result.tags: {resp}",
                    "error".red().bold()
                );
                return EXIT_VERIFY_FAIL;
            }
        },
        Err(e) => {
            eprintln!("{}: recognize dispatch failed: {e}", "error".red().bold());
            return EXIT_VERIFY_FAIL;
        }
    };

    // Mint bridge mementos from tags when --write is set. Same shape as
    // cmd_materialize's bridge emission, written under .sugar/recognize/
    // (sibling to .sugar/materialize/ so the lanes are distinguishable
    // but the verifier picks both up via load_all_proofs).
    let mut written_proof: Option<std::path::PathBuf> = None;
    if args.write {
        match emit_bridge_envelope(&project_root, &tags, &args.target_language) {
            Ok(Some(path)) => {
                written_proof = Some(path);
            }
            Ok(None) => {
                if !args.out.quiet && !args.out.json {
                    eprintln!(
                        "{}: --write requested but no tags carry a contract_cid; nothing minted",
                        "note".yellow().bold()
                    );
                }
            }
            Err(e) => {
                eprintln!("{}: emit bridge envelope: {e}", "error".red().bold());
                return EXIT_VERIFY_FAIL;
            }
        }
    }

    if args.out.json {
        let out = json!({
            "tags": tags,
            "bridge_proof": written_proof
                .as_ref()
                .map(|p| Value::String(p.display().to_string()))
                .unwrap_or(Value::Null),
        });
        println!(
            "{}",
            serde_json::to_string_pretty(&out).unwrap_or_else(|_| out.to_string())
        );
    } else {
        println!("recognize: {} tag(s) emitted", tags.len());
        for (idx, tag) in tags.iter().enumerate() {
            let op_cid = tag.get("op_cid").and_then(|v| v.as_str()).unwrap_or("?");
            let file = tag.get("file").and_then(|v| v.as_str()).unwrap_or("?");
            let span = tag.get("span").cloned().unwrap_or(Value::Null);
            let start_line = span.get("start_line").and_then(|v| v.as_u64()).unwrap_or(0);
            let tier = tag
                .get("match_tier")
                .and_then(|v| v.as_str())
                .unwrap_or("?");
            let fn_name = tag
                .get("function_name")
                .and_then(|v| v.as_str())
                .unwrap_or("?");
            println!(
                "  [{idx}] {} @ {}:{} (fn={}, {})",
                op_cid.green(),
                file,
                start_line,
                fn_name.cyan(),
                tier.dimmed()
            );
        }
        if let Some(path) = &written_proof {
            // One bridge + one implication contract per tag with a
            // function_name (the bridge falls back to its sibling
            // contract when no shim contract matches by ctor name).
            let bridge_count = tags
                .iter()
                .filter(|t| {
                    t.get("function_name")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty())
                })
                .count();
            println!(
                "{}: minted {} bridge(s) + {} implication contract(s) into {}",
                "write".green().bold(),
                bridge_count,
                bridge_count,
                path.display()
            );
        }
    }

    EXIT_OK
}

fn resolve_recognize_surface(
    explicit: Option<&str>,
    project_root: &Path,
) -> Result<String, String> {
    if let Some(surface) = explicit
        .map(str::trim)
        .filter(|surface| !surface.is_empty())
    {
        return Ok(surface.to_string());
    }

    let project_cfg = read_project_config(project_root);
    let user_cfg = read_user_config();

    if let Some(surface) = project_cfg
        .surface_recognize
        .clone()
        .or_else(|| user_cfg.surface_recognize.clone())
    {
        return Ok(surface);
    }

    if let Some(surface) = configured_recognize_surface("project", &project_cfg)? {
        return Ok(surface);
    }
    if let Some(surface) = configured_recognize_surface("user", &user_cfg)? {
        return Ok(surface);
    }

    if let Some(surface) = project_cfg
        .surface_default
        .clone()
        .or_else(|| user_cfg.surface_default.clone())
    {
        return Ok(surface);
    }

    Err("no recognize surface configured. Set [authoring.recognize] surface, declare exactly one recognizer [[plugins]] entry with layer = \"library-bindings\", or pass --surface.".to_string())
}

fn configured_recognize_surface(
    source: &str,
    cfg: &ProjectConfig,
) -> Result<Option<String>, String> {
    let surfaces = cfg
        .plugins
        .iter()
        .filter(|plugin| plugin_is_recognizer(plugin))
        .map(|plugin| plugin.surface.trim().to_string())
        .filter(|surface| !surface.is_empty())
        .collect::<Vec<_>>();
    match surfaces.as_slice() {
        [] => Ok(None),
        [surface] => Ok(Some(surface.clone())),
        _ => Err(format!(
            "multiple {source} recognizer surfaces configured: {}. Pass --surface or set [authoring.recognize] surface.",
            surfaces.join(", ")
        )),
    }
}

fn plugin_is_recognizer(plugin: &PluginEntry) -> bool {
    if plugin
        .kind
        .as_deref()
        .is_some_and(|kind| kind.eq_ignore_ascii_case("recognize"))
    {
        return true;
    }
    plugin.is_lift_plugin()
        && plugin.layer.as_deref().is_some_and(|layer| {
            layer.eq_ignore_ascii_case("library-bindings") || layer.eq_ignore_ascii_case("all")
        })
}

// recognize_bridge_body was removed (#1579). The single-target form is
// no longer needed since the emit_bridge_envelope path always uses
// recognize_bridge_body_with_target with either a shim-matched
// contract CID or a sibling implication-contract CID. Both go through
// the shared libsugar::core::emit_obligation::build_bridge_body.

/// Build the implication contract memento for a recognize tag.
/// Delegates to libsugar's shared `build_implication_contract_body`
/// (the same function the materialize and rust-tests lift lanes will
/// eventually call). Per #1579: one canonical authoring path for the
/// substrate's implication-contract shape across all verbs.
fn recognize_implication_body(tag: &Value) -> Option<Value> {
    let function_name = tag.get("function_name").and_then(|v| v.as_str())?;
    if function_name.is_empty() {
        return None;
    }
    let op_cid = tag.get("op_cid").and_then(|v| v.as_str());
    // Collect param source-text strings into Vec<String> so we can hand
    // out &str references to the shared builder.
    let param_texts: Vec<String> = tag
        .get("param_bindings")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|b| {
                    b.get("source_text")
                        .and_then(|v| v.as_str())
                        .unwrap_or("_")
                        .to_string()
                })
                .collect()
        })
        .unwrap_or_default();
    let param_refs: Vec<&str> = param_texts.iter().map(|s| s.as_str()).collect();
    Some(build_implication_contract_body(
        "recognize",
        function_name,
        op_cid,
        &param_refs,
    ))
}

/// Mint a `.proof` envelope containing one bridge memento + one
/// implication contract memento per recognize tag. Written under
/// `<project>/.sugar/recognize/<cid>.proof`.
///
/// Two members per tag (bridge + contract):
///   - The contract memento is the ENUMERATE half: its post atomic
///     contains a ctor term named after the user's function.
///     enumerate_callsites walks contract formulas, finds the ctor,
///     looks up the bridge by name, emits a CallSite.
///   - The bridge memento is the RESOLVE half: sourceSymbol →
///     targetContractCid. The discharger resolves through the bridge
///     to a contract memento and composes pre/post.
///
/// Bridge target resolution order:
///   1. The tag's contract_cid + target_proof_cid if it cites a contract that
///      exists in a kit-resolved proof source. This is the production linkage
///      when shims mint contracts covering their sugar functions.
///   2. Fallback to the recognize-emitted SIBLING contract (the one
///      this same call just minted). Self-resolution keeps the loop
///      closed even when the shim mints no contract for that function —
///      the verdict is `discharged: vacuous` against the trivial
///      identity post the recognize lane emits.
///
/// The fallback isn't a hack; it's the lift-equivalent of "if there's
/// no upstream contract, the test author's own assertion is the
/// contract." Recognize's claim is "I see this user function
/// alpha-matches the sugar shape" — that IS a claim, content-addressed,
/// signed, and admissible by the substrate.
fn emit_bridge_envelope(
    project_root: &Path,
    tags: &[Value],
    target_language: &str,
) -> Result<Option<std::path::PathBuf>, String> {
    let proof_dir = project_root.join(".sugar").join("recognize");
    let mut proof_graph = ProofGraph::new();
    let mut proof_member_cids: BTreeSet<String> = BTreeSet::new();
    // First pass: mint each tag's implication contract so we know its
    // CID. Build a map from function_name -> recognize-contract CID for
    // bridge fallback resolution.
    let mut sibling_contract_by_function: std::collections::HashMap<String, String> =
        std::collections::HashMap::new();
    for tag in tags {
        if let Some(body) = recognize_implication_body(tag) {
            let Some(contract_name) = body
                .get("contractName")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
            else {
                continue;
            };
            let Some(post) = body.get("post") else {
                continue;
            };

            let post_atom = FlatAtom::new(canonical_value_of_json(post)?);
            let post_memento = proof_graph.register_atom(post_atom);
            let body = proof_graph.register_body(ContractBody::new(&post_memento));
            let contract = ContractMemento::new_at(
                contract_name,
                &body,
                RECOGNIZE_BRIDGE_SIGNER_SEED,
                RECOGNIZE_BRIDGE_DECLARED_AT,
            );
            proof_graph.register_atom(contract.metadata().atom().clone());
            let cid = contract.cid().as_str().to_string();
            if proof_member_cids.insert(cid.clone()) {
                proof_graph.register_contract(contract);
            }
            if let Some(fn_name) = tag.get("function_name").and_then(|v| v.as_str()) {
                sibling_contract_by_function.insert(fn_name.to_string(), cid);
            }
        }
    }
    // Second pass: mint the bridge memento for each tag with
    // targetContractCid resolved against the production binding's
    // contract_cid first (shim-minted contracts), falling back to the
    // sibling recognize-emitted contract from pass 1. When a kit supplies a
    // target_proof_cid, carry it into the bridge as targetProofCid; the kit
    // owns proof/package resolution, the CLI only copies normalized RPC data
    // into the language-neutral bridge.
    for tag in tags {
        let function_name = match tag.get("function_name").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s,
            _ => continue,
        };
        // Resolve target: shim/library contract_cid when the kit supplied one;
        // otherwise the sibling contract minted by this recognize run. The
        // targetProofCid pin is valid only for the kit-supplied contract;
        // sibling fallback is self-pinned by same-bundle co-membership.
        let tag_contract_cid = tag
            .get("contract_cid")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string());
        let target_proof_cid = tag_contract_cid.as_ref().and_then(|_| {
            tag.get("target_proof_cid")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
        });
        let target_cid =
            tag_contract_cid.or_else(|| sibling_contract_by_function.get(function_name).cloned());
        let Some(target_cid) = target_cid else {
            continue;
        };
        let library_tag = tag
            .get("library_tag")
            .and_then(|v| v.as_str())
            .unwrap_or(target_language);
        let minted_bridge = mint_bridge(&MintBridgeArgs {
            produced_by: "sugar-recognize".to_string(),
            produced_at: RECOGNIZE_BRIDGE_DECLARED_AT.to_string(),
            source_symbol: function_name.to_string(),
            source_layer: target_language.to_string(),
            target_contract: ContractMementoRef::new(target_cid),
            target_layer: library_tag.to_string(),
            ir_arg_sorts: Vec::new(),
            ir_return_sort: String::new(),
            notes: "recognize-emitted bridge".to_string(),
            signer_seed: RECOGNIZE_BRIDGE_SIGNER_SEED,
            target_proof_cid: target_proof_cid.map(str::to_string),
            callsite: None,
        });
        let bridge = BridgeMemento::new(minted_bridge.canonical_bytes);
        assert_eq!(
            bridge.cid().as_str(),
            minted_bridge.cid,
            "mint_bridge returned a CID that disagrees with BridgeMemento"
        );
        if proof_member_cids.insert(bridge.cid().as_str().to_string()) {
            proof_graph.push_bridge(bridge);
        }
    }
    if proof_member_cids.is_empty() {
        return Ok(None);
    }
    std::fs::create_dir_all(&proof_dir)
        .map_err(|e| format!("create {}: {e}", proof_dir.display()))?;
    let signer = ed25519_pubkey_string(&RECOGNIZE_BRIDGE_SIGNER_SEED);
    let proof = build_proof_envelope(&ProofEnvelopeInput {
        name: "@sugar/recognize-bridges".to_string(),
        version: "0.1.0".to_string(),
        binary_cid: None,
        metadata: None,
        graph: proof_graph,
        signer_cid: signer,
        signer_seed: RECOGNIZE_BRIDGE_SIGNER_SEED,
        declared_at: RECOGNIZE_BRIDGE_DECLARED_AT.to_string(),
    });
    let path = proof_dir.join(proof_filename(&proof.cid));
    std::fs::write(&path, &proof.bytes).map_err(|e| format!("write {}: {e}", path.display()))?;
    Ok(Some(path))
}

/// Manifest discovery: project-local then user-global. Mirrors lift_plugin's
/// `find_manifest` (which is module-private). Kept local here so recognize
/// can ship independently.
struct PluginManifest {
    command: Vec<PathBuf>,
    working_dir: Option<PathBuf>,
}

fn find_plugin_manifest(project_root: &Path, surface: &str) -> Result<PluginManifest, String> {
    let project_local = project_root
        .join(".sugar")
        .join("lift")
        .join(surface)
        .join("manifest.toml");
    if project_local.exists() {
        return parse_manifest(&project_local);
    }
    if let Some(home) = std::env::var_os("HOME") {
        let user_global = PathBuf::from(home)
            .join(".config")
            .join("sugar")
            .join("lift")
            .join(surface)
            .join("manifest.toml");
        if user_global.exists() {
            return parse_manifest(&user_global);
        }
    }
    Err(format!(
        "no plugin manifest for surface `{surface}` (looked in .sugar/lift/{surface}/manifest.toml and ~/.config/sugar/lift/{surface}/manifest.toml)"
    ))
}

fn parse_manifest(path: &Path) -> Result<PluginManifest, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("read manifest {}: {e}", path.display()))?;
    let mut command: Vec<PathBuf> = Vec::new();
    let mut working_dir: Option<PathBuf> = None;
    for raw_line in text.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some(rest) = line.strip_prefix("command") {
            // command = ["binary", "--flag"]
            if let Some(arr_text) = rest.split_once('=').map(|(_, v)| v.trim()) {
                command = parse_toml_string_array(arr_text);
            }
        } else if let Some(rest) = line.strip_prefix("working_dir") {
            if let Some(val) = rest.split_once('=').map(|(_, v)| v.trim()) {
                if let Some(s) = strip_quotes(val) {
                    working_dir = Some(PathBuf::from(s));
                }
            }
        }
    }
    if command.is_empty() {
        return Err(format!("manifest {} declares no command", path.display()));
    }
    Ok(PluginManifest {
        command,
        working_dir,
    })
}

fn parse_toml_string_array(text: &str) -> Vec<PathBuf> {
    let trimmed = text.trim().trim_start_matches('[').trim_end_matches(']');
    trimmed
        .split(',')
        .filter_map(|s| {
            let t = s.trim();
            strip_quotes(t).map(PathBuf::from)
        })
        .collect()
}

fn strip_quotes(s: &str) -> Option<&str> {
    s.strip_prefix('"').and_then(|s| s.strip_suffix('"'))
}

/// Spawn the plugin binary with the manifest's command + working_dir, send
/// the JSON-RPC request, read one JSON line response, shutdown. The lift
/// binary's dispatch (initialize / lift / shutdown / sugar.plugin.recognize)
/// accepts the recognize method directly; no preceding initialize required.
fn invoke_plugin(
    manifest: &PluginManifest,
    project_root: &Path,
    request: &Value,
) -> Result<Value, String> {
    let (program, args) = manifest
        .command
        .split_first()
        .ok_or("plugin manifest command is empty")?;

    let mut cmd = Command::new(program);
    cmd.args(args);
    if let Some(working_dir) = &manifest.working_dir {
        let resolved = if working_dir.is_absolute() {
            working_dir.clone()
        } else {
            project_root.join(working_dir)
        };
        cmd.current_dir(resolved);
    } else {
        cmd.current_dir(project_root);
    }
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| format!("spawn plugin: {e}"))?;
    {
        let stdin = child.stdin.as_mut().ok_or("plugin stdin closed")?;
        let req_line = serde_json::to_string(request).map_err(|e| e.to_string())?;
        writeln!(stdin, "{req_line}").map_err(|e| format!("write request: {e}"))?;
        // Send a shutdown so the plugin exits cleanly after answering.
        let shutdown = json!({"jsonrpc":"2.0","id":2,"method":"shutdown","params":{}});
        writeln!(stdin, "{}", serde_json::to_string(&shutdown).unwrap())
            .map_err(|e| format!("write shutdown: {e}"))?;
    }

    let stdout = child.stdout.take().ok_or("plugin stdout closed")?;
    let mut reader = BufReader::new(stdout);
    let mut response_line = String::new();
    reader
        .read_line(&mut response_line)
        .map_err(|e| format!("read response: {e}"))?;
    let _ = child.wait();
    if response_line.trim().is_empty() {
        return Err("plugin response was empty".to_string());
    }
    serde_json::from_str(&response_line).map_err(|e| {
        format!(
            "parse response: {e}; raw={}",
            response_line.trim_end_matches('\n')
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_manifest_extracts_command_and_working_dir() {
        let tmp = std::env::temp_dir().join(format!(
            "sugar-recognize-test-manifest-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&tmp).unwrap();
        let manifest_path = tmp.join("manifest.toml");
        std::fs::write(
            &manifest_path,
            r#"name = "rust-bind-lift"
command = ["../../implementations/rust/target/debug/sugar-walk-rpc", "--rpc"]
working_dir = "."
"#,
        )
        .unwrap();
        let m = parse_manifest(&manifest_path).expect("parse");
        assert_eq!(m.command.len(), 2);
        assert!(m.command[0].to_string_lossy().ends_with("sugar-walk-rpc"));
        assert_eq!(m.command[1].to_string_lossy(), "--rpc");
        assert_eq!(m.working_dir, Some(PathBuf::from(".")));
        std::fs::remove_dir_all(&tmp).ok();
    }
}
