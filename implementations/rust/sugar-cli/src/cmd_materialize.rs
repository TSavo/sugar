// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar materialize`: source-oracle materialization.
//
// Resolves real source by reference through the language kit. The kit returns
// materialized bodies only when the on-disk source recomputes to the pinned
// SourceMemento CIDs; drift is refused.

use std::io::{BufRead, BufReader, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};

use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::{json, Value};
use walkdir::WalkDir;

use crate::{OutputFlags, EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

#[derive(Parser, Debug, Clone, Default)]
pub struct MaterializeArgs {
    /// Project root containing `.sugar/lift/<surface>/manifest.toml`.
    /// Defaults to current directory.
    #[arg(long)]
    pub project: Option<PathBuf>,
    /// Consumer source paths, relative to project root. Repeatable.
    #[arg(long = "source")]
    pub source_paths: Vec<String>,
    /// Source directory to scan for by-reference source stubs.
    #[arg(long = "source-dir")]
    pub source_dir: Option<PathBuf>,
    /// Lift surface name serving `sugar.plugin.materialize`. If omitted,
    /// resolves from the single configured lift manifest.
    #[arg(long)]
    pub surface: Option<String>,
    /// Root the frozen memento's `file` path is relative to. Defaults to the
    /// project root.
    #[arg(long = "vendor-root")]
    pub vendor_root: Option<PathBuf>,
    /// Legacy library hint accepted for command-line compatibility. Source
    /// mementos and source annotations are authoritative.
    #[arg(long)]
    pub library: Option<String>,
    /// Legacy target hint accepted for command-line compatibility.
    #[arg(long, alias = "language")]
    pub target: Option<String>,
    /// Rewrite materialized bodies in place. Omitted means dry-run.
    #[arg(long)]
    pub write: bool,
    /// Unsupported for source-oracle materialize. No target source is
    /// synthesized.
    #[arg(long = "out-dir", conflicts_with = "write")]
    pub out_dir: Option<PathBuf>,
    /// Unsupported for source-oracle materialize.
    #[arg(long = "compile-check", requires = "out_dir")]
    pub compile_check: bool,
    #[command(flatten)]
    pub out: OutputFlags,
}

pub fn run(args: MaterializeArgs) -> u8 {
    if args.out_dir.is_some() || args.compile_check {
        eprintln!(
            "{}: source-oracle materialize does not synthesize target output; use --write for in-place fills",
            "error".red().bold()
        );
        return EXIT_USER_ERROR;
    }

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

    let mut source_paths = args.source_paths.clone();
    if let Some(source_dir) = &args.source_dir {
        match source_paths_for_project(&project_root, source_dir) {
            Ok(mut scanned) => source_paths.append(&mut scanned),
            Err(error) => {
                eprintln!("{}: {error}", "error".red().bold());
                return EXIT_USER_ERROR;
            }
        }
    }
    source_paths.sort();
    source_paths.dedup();
    if source_paths.is_empty() {
        if args.out.json {
            println!("{}", json!({ "results": [] }));
        } else if !args.out.quiet {
            eprintln!(
                "{} found 0 source-oracle file(s)",
                "materialize".green().bold()
            );
        }
        return EXIT_OK;
    }

    let surface = match resolve_surface(args.surface.as_deref(), &project_root) {
        Ok(s) => s,
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

    let vendor_root = args
        .vendor_root
        .clone()
        .map(|p| p.canonicalize().unwrap_or(p))
        .unwrap_or_else(|| project_root.clone());

    if !args.out.json && !args.out.quiet {
        eprintln!(
            "{}: surface=`{}` sources={} vendor_root={}",
            "materialize".green().bold(),
            surface,
            source_paths.len(),
            vendor_root.display(),
        );
    }

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.plugin.materialize",
        "params": {
            "project_root": project_root.to_string_lossy(),
            "source_paths": source_paths,
            "vendor_root": vendor_root.to_string_lossy(),
            "write": args.write,
        }
    });

    let results = match invoke_plugin(&manifest, &project_root, &req) {
        Ok(resp) => {
            if let Some(err) = resp.get("error") {
                eprintln!("{}: materialize kit error: {err}", "error".red().bold());
                return EXIT_VERIFY_FAIL;
            }
            match resp
                .get("result")
                .and_then(|r| r.get("results"))
                .and_then(Value::as_array)
                .cloned()
            {
                Some(a) => a,
                None => {
                    eprintln!(
                        "{}: kit response missing result.results: {resp}",
                        "error".red().bold()
                    );
                    return EXIT_VERIFY_FAIL;
                }
            }
        }
        Err(e) => {
            eprintln!("{}: materialize dispatch failed: {e}", "error".red().bold());
            return EXIT_VERIFY_FAIL;
        }
    };

    // #3632: the kit's materialize outcome for an unbound/malshaped symbol is
    // named "boundary" (typed effect, not a verifier refusal).
    let is_boundary_outcome = |r: &&Value| {
        matches!(r.get("outcome").and_then(Value::as_str), Some("boundary"))
    };
    let refused = results.iter().filter(is_boundary_outcome).count();
    let materialized = results
        .iter()
        .filter(|r| r.get("outcome").and_then(Value::as_str) == Some("materialized"))
        .count();

    if args.out.json {
        let out = json!({ "results": results });
        println!(
            "{}",
            serde_json::to_string_pretty(&out).unwrap_or_else(|_| out.to_string())
        );
    } else {
        for r in &results {
            let outcome = r.get("outcome").and_then(Value::as_str).unwrap_or("?");
            let file = r.get("file").and_then(Value::as_str).unwrap_or("?");
            match outcome {
                "materialized" => {
                    let syms: Vec<String> = r
                        .get("materialized")
                        .and_then(Value::as_array)
                        .map(|a| {
                            a.iter()
                                .filter_map(|m| {
                                    m.get("symbol").and_then(Value::as_str).map(str::to_string)
                                })
                                .collect()
                        })
                        .unwrap_or_default();
                    println!(
                        "  {} {} [{}]",
                        "materialized".green().bold(),
                        file,
                        syms.join(", ")
                    );
                }
                "boundary" => {
                    let reason = r.get("reason").and_then(Value::as_str).unwrap_or("");
                    println!("  {} {}: {}", "REFUSED".red().bold(), file, reason);
                }
                other => println!("  {other} {file}"),
            }
        }
        println!(
            "materialize: {} materialized, {} refused",
            materialized, refused
        );
    }

    if refused > 0 {
        EXIT_VERIFY_FAIL
    } else {
        EXIT_OK
    }
}

fn source_paths_for_project(project_root: &Path, source_dir: &Path) -> Result<Vec<String>, String> {
    let source_dir = source_dir
        .canonicalize()
        .map_err(|error| format!("resolve source-dir {}: {error}", source_dir.display()))?;
    let mut paths = Vec::new();
    for entry in WalkDir::new(&source_dir)
        .into_iter()
        .filter_entry(|entry| should_scan_entry(entry.path()))
        .filter_map(Result::ok)
    {
        let path = entry.path();
        if !path.is_file() || !is_source_oracle_file(path) {
            continue;
        }
        let rel = path.strip_prefix(project_root).map_err(|_| {
            format!(
                "source file {} is not under project root {}",
                path.display(),
                project_root.display()
            )
        })?;
        paths.push(path_to_slash_string(rel)?);
    }
    Ok(paths)
}

fn is_source_oracle_file(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|ext| ext.to_str()),
        Some("py" | "rs")
    )
}

fn should_scan_entry(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
        return true;
    };
    !matches!(
        name,
        ".git"
            | ".mypy_cache"
            | ".next"
            | ".pytest_cache"
            | ".ruff_cache"
            | ".turbo"
            | ".venv"
            | ".vite"
            | "__pycache__"
            | "build"
            | "dist"
            | "node_modules"
            | "target"
            | "venv"
    )
}

fn path_to_slash_string(path: &Path) -> Result<String, String> {
    let mut parts = Vec::new();
    for component in path.components() {
        match component {
            Component::Normal(part) => parts.push(part.to_string_lossy().to_string()),
            Component::CurDir => {}
            other => {
                return Err(format!(
                    "source path contains unsupported component `{}`",
                    other.as_os_str().to_string_lossy()
                ));
            }
        }
    }
    Ok(parts.join("/"))
}

fn resolve_surface(explicit: Option<&str>, project_root: &Path) -> Result<String, String> {
    if let Some(surface) = explicit.map(str::trim).filter(|s| !s.is_empty()) {
        return Ok(surface.to_string());
    }
    let lift_dir = project_root.join(".sugar").join("lift");
    let mut surfaces: Vec<String> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&lift_dir) {
        for entry in entries.flatten() {
            if entry.path().join("manifest.toml").is_file() {
                if let Some(name) = entry.file_name().to_str() {
                    surfaces.push(name.to_string());
                }
            }
        }
    }
    surfaces.sort();
    match surfaces.as_slice() {
        [one] => Ok(one.clone()),
        [] => Err(format!(
            "no lift manifest under {}; pass --surface",
            lift_dir.display()
        )),
        _ => Err(format!(
            "multiple lift surfaces ({}); pass --surface",
            surfaces.join(", ")
        )),
    }
}

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
        "no plugin manifest for surface `{surface}` (looked in .sugar/lift/{surface}/manifest.toml)"
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
        .filter_map(|s| strip_quotes(s.trim()).map(PathBuf::from))
        .collect()
}

fn strip_quotes(s: &str) -> Option<&str> {
    s.strip_prefix('"').and_then(|s| s.strip_suffix('"'))
}

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
