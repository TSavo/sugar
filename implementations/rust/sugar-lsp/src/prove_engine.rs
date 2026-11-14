// SPDX-License-Identifier: MIT OR Apache-2.0
//
// prove_engine.rs: prove an open buffer in-process through the two doors the
// CLI uses (item 35 on #7757; lifting and proving are never conflated).
//
//   1. Stage the edited buffer into a source overlay of the project: its
//      sources, its `.sugar` lift surface and the `.proof` files mint staged
//      directly in `.sugar/imports`.
//   2. Mint the overlay through `sugar mint`'s door
//      (`sugar_cli::cmd_mint::mint_project`), which writes the minted `.proof`
//      at the overlay root.
//   3. Prove the overlay through `sugar prove`'s door
//      (`sugar_cli::prove_door::build_prove_outcome_with_options`), which
//      reads that `.proof` and the staged imports and nothing else.
//   4. Report prove's rows (`sugar_cli::prove_door::prove_rows`).
//
// The LSP starts no kit of its own, folds nothing into a pool of its own,
// mints no bridges and no vendor proofs, and walks nothing below
// `.sugar/imports`.

use std::path::{Path, PathBuf};

use serde_json::Value as Json;

/// What the LSP holds between solves: the project it proves. Every solve
/// reads the project's staged imports afresh through the prove door, so
/// there is nothing else to keep resident.
pub struct ProveContext {
    pub project_root: PathBuf,
}

pub fn build_prove_context_for(project_root: &Path) -> ProveContext {
    ProveContext {
        project_root: project_root.to_path_buf(),
    }
}

/// The `.proof` files directly in `dir` (not below it).
fn proof_files_in(dir: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.is_file() && path.extension().is_some_and(|ext| ext == "proof"))
        .collect()
}

/// Build (or refresh) the source overlay for a solve: a stable per-project
/// directory holding the project's sources and its `.sugar` lift surface,
/// with the request's buffer substituted at `request_file`'s project-relative
/// path. On every call the overlay's `.sugar/imports` is replaced by the
/// `.proof` files directly in the project's `.sugar/imports`, and the
/// overlay's root `.proof` files (an earlier solve's mint) are removed, so
/// the prove door reads exactly this buffer's mint plus the staged imports.
pub fn build_source_overlay_project(
    project_root: &Path,
    overlay_root: &Path,
    request_file: &Path,
    source: &str,
) -> Result<(), String> {
    fn copy_tree(from: &Path, to: &Path) -> Result<(), String> {
        std::fs::create_dir_all(to).map_err(|e| e.to_string())?;
        for entry in std::fs::read_dir(from).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            let name = entry.file_name();
            let src = entry.path();
            let dst = to.join(&name);
            if src.is_dir() {
                copy_tree(&src, &dst)?;
            } else {
                std::fs::copy(&src, &dst).map_err(|e| e.to_string())?;
            }
        }
        Ok(())
    }

    std::fs::create_dir_all(overlay_root).map_err(|e| e.to_string())?;

    let populated_marker = overlay_root.join(".sugar-overlay-populated");
    if !populated_marker.exists() {
        let cfg = project_root.join(".sugar").join("config.toml");
        if cfg.exists() {
            std::fs::create_dir_all(overlay_root.join(".sugar")).map_err(|e| e.to_string())?;
            std::fs::copy(&cfg, overlay_root.join(".sugar").join("config.toml"))
                .map_err(|e| e.to_string())?;
        }
        for dir in ["lift", "ir-compilers", "components"] {
            let from = project_root.join(".sugar").join(dir);
            if from.is_dir() {
                copy_tree(&from, &overlay_root.join(".sugar").join(dir))?;
            }
        }

        fn copy_sources(from: &Path, to: &Path, depth: usize) -> Result<(), String> {
            if depth > 6 {
                return Ok(());
            }
            std::fs::create_dir_all(to).map_err(|e| e.to_string())?;
            for entry in std::fs::read_dir(from).map_err(|e| e.to_string())? {
                let entry = entry.map_err(|e| e.to_string())?;
                let name_os = entry.file_name();
                let name = name_os.to_string_lossy().to_string();
                let src = entry.path();
                if src.is_dir() {
                    if name == ".sugar"
                        || name == ".git"
                        || name == "target"
                        || name == "__pycache__"
                        || name == ".vscode"
                        || name == "node_modules"
                    {
                        continue;
                    }
                    copy_sources(&src, &to.join(&name), depth + 1)?;
                } else {
                    if name.ends_with(".proof") || name.ends_with(".witness") {
                        continue;
                    }
                    std::fs::copy(&src, to.join(&name)).map_err(|e| e.to_string())?;
                }
            }
            Ok(())
        }
        copy_sources(project_root, overlay_root, 0)?;
        std::fs::write(&populated_marker, "").map_err(|e| e.to_string())?;
    }

    // The staged imports, as the project has them now (directly in
    // `.sugar/imports`, never below it).
    let overlay_imports = overlay_root.join(".sugar").join("imports");
    if overlay_imports.exists() {
        std::fs::remove_dir_all(&overlay_imports).map_err(|e| e.to_string())?;
    }
    let project_imports = project_root.join(".sugar").join("imports");
    let staged = proof_files_in(&project_imports);
    if !staged.is_empty() {
        std::fs::create_dir_all(&overlay_imports).map_err(|e| e.to_string())?;
        for proof in staged {
            if let Some(name) = proof.file_name() {
                std::fs::copy(&proof, overlay_imports.join(name)).map_err(|e| e.to_string())?;
            }
        }
    }

    // An earlier solve's mint is not this buffer's proof.
    for stale in proof_files_in(overlay_root) {
        std::fs::remove_file(&stale).map_err(|e| e.to_string())?;
    }

    let rel = request_file
        .strip_prefix(project_root)
        .unwrap_or(request_file);
    let dst = overlay_root.join(rel);
    if let Some(parent) = dst.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(&dst, source).map_err(|e| e.to_string())?;
    Ok(())
}

/// Result of one `solve_buffer` call: prove's rows for the buffer, or why
/// mint or prove refused it (then `rows` is empty).
pub struct SolveOutcome {
    pub rows: Vec<Json>,
    pub failure: Option<String>,
}

impl SolveOutcome {
    fn failed(reason: String) -> Self {
        SolveOutcome {
            rows: Vec::new(),
            failure: Some(reason),
        }
    }
}

/// Where the overlay for `project_root` lives.
pub fn overlay_root_for(project_root: &Path) -> PathBuf {
    std::env::temp_dir()
        .join("sugar-lsp-lift-src")
        .join(sugar_canonicalizer::blake3_512_hex(
            project_root.display().to_string().as_bytes(),
        ))
}

/// Mint `project_root` through `sugar mint`'s door (`sugar mint --project
/// <root> --quiet`), writing the minted `.proof` at the root.
pub fn mint_through_the_mint_door(project_root: &Path) -> Result<(), String> {
    let args = sugar_cli::cmd_mint::MintArgs {
        project: Some(project_root.to_path_buf()),
        kit: None,
        surface: None,
        library_bindings: false,
        out: None,
        // Quiet: stdout is the LSP's JSON-RPC channel.
        flags: sugar_cli::OutputFlags {
            json: false,
            quiet: true,
        },
    };
    sugar_cli::cmd_mint::mint_project(&args)
        .map(|_| ())
        .map_err(|(_, message)| format!("mint refused the buffer: {message}"))
}

/// Prove `project_root` through `sugar prove`'s door (`sugar prove --project
/// <root>`) and return prove's rows.
pub fn prove_through_the_prove_door(project_root: &Path) -> Result<Vec<Json>, String> {
    let options = sugar_cli::component_plan::ComponentPlanOptions {
        allow_failed_components: false,
    };
    let proven = sugar_cli::prove_door::build_prove_outcome_with_options(project_root, "z3", options)
        .map_err(|error| format!("prove refused the buffer: {error}"))?;
    Ok(sugar_cli::prove_door::prove_rows(&proven.artifact.report))
}

/// Solve one edited buffer: stage it into the overlay, mint the overlay
/// through the mint door, prove it through the prove door, and report
/// prove's rows.
pub fn solve_buffer(ctx: &ProveContext, file: &Path, source: &str) -> SolveOutcome {
    let overlay_root = overlay_root_for(&ctx.project_root);
    if let Err(err) = build_source_overlay_project(&ctx.project_root, &overlay_root, file, source) {
        return SolveOutcome::failed(format!("source-overlay build failed: {err}"));
    }
    if let Err(reason) = mint_through_the_mint_door(&overlay_root) {
        return SolveOutcome::failed(reason);
    }
    match prove_through_the_prove_door(&overlay_root) {
        Ok(rows) => SolveOutcome {
            rows,
            failure: None,
        },
        Err(reason) => SolveOutcome::failed(reason),
    }
}
