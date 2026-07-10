// SPDX-License-Identifier: MIT OR Apache-2.0
//
// prove_engine.rs: THE TERMINUS -- prove an open buffer IN-PROCESS by
// linking the engine directly into sugar-lsp. No daemon RPC, no subprocess
// solver.
//
// This module is a from-scratch composition of the SAME public primitives
// `sugar-linkerd`'s `server.rs::build_prove_context_for` and
// `methods.rs::handle_prove_consistency` compose -- never a reimplementation
// of the verifier's own logic, and never an import of `sugar-linkerd` (which
// ships no `[lib]` target and stays untouched per the lane's DO-NOT-TOUCH
// list). Every stage below calls straight into `sugar_verifier` /
// `sugar_cli`'s public API:
//
//   1. `build_prove_context_for`: load the VENDOR-ONLY base pool from
//      `.sugar/imports` (`sugar_verifier::load_all_proofs::run`), build the
//      solver plan/registry (`sugar_verifier::RunnerConfig` +
//      `build_plan_and_registry_pub`), the IR-compiler registry
//      (`compiler_registry::build`), and the base `ConsistencyIndex`
//      (`consistency::build_consistency_index`) ONCE. Held resident in the
//      `LanguageServer` struct (warm because the LSP process lives).
//   2. `solve_buffer`: on didOpen/didSave/didChange(debounced), mint a
//      SOURCE-OVERLAY scratch proof of the edited buffer
//      (`sugar_cli::cmd_mint::mint_project_scratch_proof`), load its bytes
//      into an overlay `MementoPool`
//      (`sugar_verifier::load_all_proofs::{ProofBytes, load_proof_bytes_into_pool}`),
//      then solve through THE resident-base SOLVE door
//      (`consistency::verify_consistency_scoped_with_base_index` — derived
//      pool_only, zero project FS reads) and render rows via
//      `sugar_verifier::report::row_to_json`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use serde_json::Value as Json;
use sugar_verifier::consistency::ConsistencyIndex;
use sugar_verifier::solvers::{SolverHandle, SolverPlan, SolverSeat};

/// Resident context for in-process proving, mirroring
/// `sugar-linkerd::state::ProveContext` field for field: the SAME
/// pool/plan/registry/compilers/manifest/index construction, built by
/// composing `sugar_verifier`'s public API directly rather than importing
/// the daemon crate (which has no lib target).
pub struct ProveContext {
    pub pool: sugar_verifier::types::MementoPool,
    pub plan: SolverPlan,
    pub registry: std::collections::HashMap<SolverSeat, SolverHandle>,
    pub compilers: sugar_ir_compiler::registry::Registry,
    pub project_root: PathBuf,
    /// Coarse invalidation manifest: every `.proof` path under
    /// `project_root/.sugar/imports` mapped to its mtime AS OF the last
    /// (re)build. `solve_buffer` re-stats this cheaply before each call; any
    /// drift (a fresh vendor import landing) triggers a full rebuild.
    pub proof_manifest: BTreeMap<PathBuf, SystemTime>,
    pub consistency_index: ConsistencyIndex,
}

/// Coarse `.proof` manifest scan: every `*.proof` file under `root` mapped to
/// its mtime. Mirrors `sugar-linkerd::server::scan_proof_manifest`'s filter
/// (extension == "proof") exactly -- duplicated because that function is
/// private to a binary crate with no lib target, never a divergent
/// reimplementation of the LOADING logic itself.
pub fn scan_proof_manifest(root: &Path) -> BTreeMap<PathBuf, SystemTime> {
    let mut out = BTreeMap::new();
    if !root.exists() {
        return out;
    }
    for entry in walkdir::WalkDir::new(root)
        .follow_links(true)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }
        if entry.path().extension().map(|e| e == "proof").unwrap_or(false) {
            if let Ok(meta) = entry.metadata() {
                if let Ok(mtime) = meta.modified() {
                    out.insert(entry.path().to_path_buf(), mtime);
                }
            }
        }
    }
    out
}

/// Minimal PATH scan for an executable, so the default single-z3 fallback is
/// an HONEST capability (z3 present vs absent), mirroring
/// `sugar-linkerd::server::which_on_path`.
fn which_on_path(bin: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let candidate = dir.join(bin);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Build the resident `ProveContext` for `project_root`: same construction
/// `sugar_verifier::runner::Runner::new`/`cmd_prove` use
/// (`load_pool` + `build_plan_and_registry_pub` + `compiler_registry::build`),
/// scoped to the VENDOR-ONLY `.sugar/imports` pool (never the consumer's own
/// on-disk `.proof`/`.sugar/runs` -- the per-buffer overlay is the SOLE
/// consumer testimony, so loading a stale consumer proof alongside it would
/// double-testify and the green/red flip would never flip).
pub fn build_prove_context_for(project_root: &Path) -> ProveContext {
    let imports_root = project_root.join(".sugar").join("imports");

    let pool = sugar_verifier::load_all_proofs::run(&imports_root);

    // Solver plan/registry: kit-declared `.sugar/config.toml` `[solvers]`
    // wins verbatim (via `build_plan_and_registry_pub`'s own precedence);
    // otherwise fall back to a default single-z3 registry when z3 is
    // reachable on PATH, exactly as `sugar-linkerd::server::build_solver_context`
    // does for its own solver wiring.
    let legacy_z3_fallback = which_on_path("z3").map(|_| sugar_verifier::LegacyZ3Fallback::compat("z3"));
    let cfg = sugar_verifier::RunnerConfig {
        project_root: project_root.to_path_buf(),
        legacy_z3_fallback,
        ..Default::default()
    };
    let (plan, registry) = sugar_verifier::runner::build_plan_and_registry_pub(&cfg);

    let compilers = sugar_verifier::compiler_registry::build(project_root);
    let proof_manifest = scan_proof_manifest(&imports_root);
    let consistency_index = sugar_verifier::consistency::build_consistency_index(&pool);

    ProveContext {
        pool,
        plan,
        registry,
        compilers,
        project_root: project_root.to_path_buf(),
        proof_manifest,
        consistency_index,
    }
}

/// Build (or refresh) the SOURCE-OVERLAY lift project for a solve request: a
/// stable per-project directory holding the project's lift surface --
/// `.sugar/config.toml`, `.sugar/lift/**`, `.sugar/ir-compilers/**` -- and its
/// source files, with the request's buffer content substituted at
/// `request_file`'s project-relative path. Deliberately EXCLUDED:
/// `.sugar/imports` (the vendor pool is resident already), any `*.proof`,
/// `.sugar/runs|cache|witnesses`, and dot/target dirs. Mirrors
/// `sugar-linkerd::methods::build_source_overlay_project` (private to a
/// binary crate with no lib target; duplicated here rather than imported).
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
        let lift_dir = project_root.join(".sugar").join("lift");
        if lift_dir.is_dir() {
            copy_tree(&lift_dir, &overlay_root.join(".sugar").join("lift"))?;
        }
        let ir_compilers_dir = project_root.join(".sugar").join("ir-compilers");
        if ir_compilers_dir.is_dir() {
            copy_tree(&ir_compilers_dir, &overlay_root.join(".sugar").join("ir-compilers"))?;
        }
        let comps = project_root.join(".sugar").join("components");
        if comps.is_dir() {
            copy_tree(&comps, &overlay_root.join(".sugar").join("components"))?;
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

    let rel = request_file.strip_prefix(project_root).unwrap_or(request_file);
    let dst = overlay_root.join(rel);
    if let Some(parent) = dst.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(&dst, source).map_err(|e| e.to_string())?;
    Ok(())
}

/// Result of one `solve_buffer` call: rendered rows (wire-identical to
/// `sugar prove --json` / the daemon's `proveConsistency`, via the SAME
/// `sugar_verifier::report::row_to_json`), plus whether the overlay mint
/// degraded to the resident base pool alone (and why).
pub struct SolveOutcome {
    pub rows: Vec<Json>,
    pub degraded: bool,
    pub degraded_reason: Option<String>,
}

/// Solve one edited buffer against the resident base index: mint the
/// SOURCE-OVERLAY scratch proof, load it into a small overlay pool, and
/// drive THE resident-base SOLVE door
/// ([`sugar_verifier::consistency::verify_consistency_scoped_with_base_index`]),
/// scoped to `file`. Warmth is derived (base index already resident) — zero
/// project FS. `ctx` is never mutated (caller owns rebuild).
pub fn solve_buffer(ctx: &ProveContext, file: &Path, source: &str) -> SolveOutcome {
    let scratch_dir = std::env::temp_dir().join("sugar-lsp-lift-scratch").join(
        sugar_canonicalizer::blake3_512_hex(ctx.project_root.display().to_string().as_bytes()),
    );
    let overlay_root = std::env::temp_dir().join("sugar-lsp-lift-src").join(
        sugar_canonicalizer::blake3_512_hex(ctx.project_root.display().to_string().as_bytes()),
    );

    if let Err(err) = build_source_overlay_project(&ctx.project_root, &overlay_root, file, source) {
        return SolveOutcome {
            rows: Vec::new(),
            degraded: true,
            degraded_reason: Some(format!(
                "source-overlay build failed; falling back to resident disk-pool: {err}"
            )),
        };
    }

    let _ = std::fs::remove_dir_all(&scratch_dir);
    if let Err(err) = std::fs::create_dir_all(&scratch_dir) {
        return SolveOutcome {
            rows: Vec::new(),
            degraded: true,
            degraded_reason: Some(format!("cannot create lsp scratch dir: {err}")),
        };
    }

    let mint_result = sugar_cli::cmd_mint::mint_project_scratch_proof(&overlay_root, &scratch_dir, false);

    let (overlay_pool, degraded, degraded_reason) = match mint_result {
        Ok(Some(scratch)) => {
            let mut overlay_pool = sugar_verifier::types::MementoPool::default();
            match sugar_verifier::load_all_proofs::ProofBytes::try_from_parts(
                "sugar-lsp-overlay",
                scratch.cid,
                scratch.bytes,
                sugar_verifier::Speaker::consumer("sugar-lsp-overlay"),
            ) {
                Ok(staged) => {
                    sugar_verifier::load_all_proofs::load_proof_bytes_into_pool(
                        &[staged],
                        &mut overlay_pool,
                    );
                    use sugar_verifier::types::MemberKind;
                    let contracts = overlay_pool.member_count_by_kind(MemberKind::Contract);
                    let sources = overlay_pool.member_count_by_kind(MemberKind::SourceMemento);
                    if contracts == 0 && sources == 0 {
                        (
                            sugar_verifier::types::MementoPool::default(),
                            true,
                            Some("overlay produced no consumer testimony; falling back to resident disk-pool".to_string()),
                        )
                    } else {
                        (overlay_pool, false, None)
                    }
                }
                Err(err) => (
                    sugar_verifier::types::MementoPool::default(),
                    true,
                    Some(format!("stage scratch proof bytes failed: {err}")),
                ),
            }
        }
        Ok(None) => (
            sugar_verifier::types::MementoPool::default(),
            true,
            Some("overlay mint produced no catalog (no [[plugins]] lift entries declared, or lifter contributed nothing); falling back to resident disk-pool".to_string()),
        ),
        Err(err) => (
            sugar_verifier::types::MementoPool::default(),
            true,
            Some(format!("overlay mint failed; falling back to resident disk-pool: {err}")),
        ),
    };

    // #3809: one solve door; resident base index derives pool-only (zero FS).
    let results = sugar_verifier::consistency::verify_consistency_scoped_with_base_index(
        &ctx.consistency_index,
        &overlay_pool,
        &ctx.plan,
        &ctx.registry,
        &ctx.compilers,
        &ctx.project_root,
        &ctx.project_root,
    );

    let rows: Vec<Json> = results
        .iter()
        .map(|cr| {
            let mut report = sugar_verifier::types::Report::default();
            sugar_verifier::report::add_consistency_with_verification(
                &cr.contract_cid,
                &cr.property_name,
                cr.verdict,
                &cr.reason,
                cr.verification.as_ref().map(|v| v.to_json()),
                cr.locus.clone(),
                &mut report,
            );
            sugar_verifier::report::row_to_json(&report.rows[0])
        })
        .collect();

    SolveOutcome {
        rows,
        degraded,
        degraded_reason,
    }
}
