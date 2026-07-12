// SPDX-License-Identifier: MIT OR Apache-2.0
//
// prove_engine.rs: THE TERMINUS -- prove an open buffer IN-PROCESS by
// linking the engine directly into sugar-lsp. No daemon RPC, no subprocess
// solver.
//
// #3809 composition (one path with CLI prove / the enumeration protocol):
//
//   1. `build_prove_context_for`: load the VENDOR-ONLY base pool from
//      `.sugar/imports`, build solver plan/registry, compilers, and base
//      `ConsistencyIndex` ONCE. Held resident in the LanguageServer.
//   2. `solve_buffer`: stage the edited buffer into a source overlay, then
//      FEED claims via the SAME door as `sugar prove` kit face:
//        rendezvous kit → `sugar.enumerate` walk → `feed_from_tree::fold_project`
//        → `pool_from_graph_with_speaker` (consumer speaker)
//      Then discharge through THE resident-base SOLVE door
//      (`verify_consistency_scoped_with_base_index` — zero project FS for
//      claim facts). NO parallel `mint_project_scratch_proof` feed.
//
// Mint remains the door for sealed `.proof` publish / vendor cache seal
// (auto_mode); it is not the LSP solve feed.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use libsugar::core::Dialect;
use serde_json::Value as Json;
use sugar_compiler::feed_from_tree;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::orchestrate::pool_from_graph_with_speaker;
use sugar_verifier::consistency::ConsistencyIndex;
use sugar_verifier::solvers::{SolverHandle, SolverPlan, SolverSeat};
use sugar_verifier::Speaker;

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
        if entry
            .path()
            .extension()
            .map(|e| e == "proof")
            .unwrap_or(false)
        {
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

    // #3809 PR A: LSP is a client of the solve API — load [solvers] here and
    // feed solvers_config; solve never opens config.toml.
    let solvers_config = sugar_verifier::SolversConfig::load(project_root)
        .ok()
        .flatten();
    let legacy_z3_fallback =
        which_on_path("z3").map(|_| sugar_verifier::LegacyZ3Fallback::compat("z3"));
    let cfg = sugar_verifier::RunnerConfig {
        project_root: project_root.to_path_buf(),
        legacy_z3_fallback,
        solvers_config,
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
/// `.sugar/runs|cache|witnesses`, and dot/target dirs.
///
/// The overlay is the workspace_root the kit sees for `sugar.enumerate` —
/// same staging role as before mint-as-feed, now the enumerate→fold mount.
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
            copy_tree(
                &ir_compilers_dir,
                &overlay_root.join(".sugar").join("ir-compilers"),
            )?;
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

/// Result of one `solve_buffer` call: rendered rows (wire-identical to
/// `sugar prove --json` / the daemon's `proveConsistency`, via the SAME
/// `sugar_verifier::report::row_to_json`), plus whether the overlay feed
/// degraded to the resident base pool alone (and why).
pub struct SolveOutcome {
    pub rows: Vec<Json>,
    pub degraded: bool,
    pub degraded_reason: Option<String>,
    /// Client-side auto-lift log lines (#4007); empty when disabled/no imports.
    pub auto_logs: Vec<String>,
    /// Best-effort kit lift-report JSON (factoryWalk + liftCoverage) for report mode.
    pub report_lift: Option<Json>,
}

/// Dialect for a lift surface name (mirrors CLI `try_rendezvous_prove_kit`).
fn dialect_for_surface(surface: &str) -> Dialect {
    match surface {
        "rust" => Dialect::Rust,
        "c" => Dialect::C,
        "python" => Dialect::Other("python".into()),
        other => Dialect::Other(other.to_string()),
    }
}

/// Rendezvous the first configured lift kit for `project_root`.
///
/// Same selection shape as CLI prove Task 9: project config lift plugins +
/// manifest resolution, then `Kit::rendezvous` (live kit_declaration handshake).
fn try_rendezvous_lift_kit(project_root: &Path) -> Result<Kit, String> {
    let cfg = sugar_cli::project_config::read_project_config(project_root);
    let mut last_err: Option<String> = None;
    for plugin in cfg.plugins.iter().filter(|p| p.is_lift_plugin()) {
        let planned = match sugar_cli::lift_plugin::find_manifest_for_surface(
            project_root,
            &plugin.surface,
        ) {
            Ok(m) => m,
            Err(e) => {
                last_err = Some(e);
                continue;
            }
        };
        if planned.command.is_empty() {
            last_err = Some(format!(
                "empty lift command for surface `{}`",
                planned.surface
            ));
            continue;
        }
        let working_dir =
            sugar_cli::lift_plugin::absolute_working_dir_for_manifest(project_root, &planned);
        let manifest = LiftManifest {
            surface: planned.surface.clone(),
            name: planned.name.clone(),
            dialect: dialect_for_surface(&planned.surface),
            command: planned.command.clone(),
            working_dir,
            method: planned.method.clone(),
        };
        match Kit::rendezvous(manifest) {
            Ok(kit) => return Ok(kit),
            Err(e) => {
                last_err = Some(e.to_string());
                continue;
            }
        }
    }
    Err(last_err.unwrap_or_else(|| {
        "no lift kit configured (no [[plugins]] lift surfaces with a resolvable manifest)"
            .to_string()
    }))
}

/// #3809: consumer feed half — enumerate→fold→pool, NOT batch mint.
///
/// Walk `sugar.enumerate` via `fold_project`, stamp consumer speaker at pool
/// intake (`pool_from_graph_with_speaker`). Same construction as the lift
/// front of `prove_from_kit` / `fold_kit_to_pool` for the local graph (vendor
/// testimony stays on the resident base index, not re-merged here).
pub fn feed_overlay_pool(
    overlay_root: &Path,
) -> Result<sugar_verifier::types::MementoPool, String> {
    let kit = try_rendezvous_lift_kit(overlay_root)?;
    let speaker = Speaker::consumer("sugar-lsp");
    let graph = feed_from_tree::fold_project(&kit, overlay_root, Some(&speaker))
        .map_err(|e| format!("enumerate→fold feed failed: {e}"))?;
    pool_from_graph_with_speaker(&graph, speaker)
        .map_err(|e| format!("fold→pool speaker stamp failed: {e}"))
}

/// #3802 consumer-testimony half of the soundness floor.
///
/// Call on the pure enumerate→fold pool **before** dependency-bridge injection
/// (injection loads vendor members, which must not count as consumer testimony).
pub fn assess_consumer_overlay_testimony(
    pool: &sugar_verifier::types::MementoPool,
) -> Result<(), String> {
    use sugar_verifier::types::MemberKind;

    let contracts = pool.member_count_by_kind(MemberKind::Contract);
    let sources = pool.member_count_by_kind(MemberKind::SourceMemento);
    if contracts == 0 && sources == 0 {
        return Err(
            "overlay produced no consumer testimony; falling back to resident disk-pool"
                .to_string(),
        );
    }

    // Consistency candidates are the anchored claims the scoped solve door
    // can actually discharge. Contracts that are not candidates (setup
    // bindings, pre-bearing shells) do not count as testimony for this guard.
    let index = sugar_verifier::consistency::build_consistency_index(pool);
    if index.candidate_count() == 0 {
        return Err(
            "overlay produced no consumer-anchored consistency candidates; falling back to resident disk-pool"
                .to_string(),
        );
    }
    Ok(())
}

/// #3808 binding half of the soundness floor.
///
/// Call **after** `inject_dependency_bridges_into_pool`. When the project
/// declares import deps whose contracts need post/universe bridges, the
/// overlay must carry at least one Bridge or LibrarySugarBindingEntry.
pub fn assess_overlay_vendor_bindings(
    pool: &sugar_verifier::types::MementoPool,
    project_root: &Path,
) -> Result<(), String> {
    use sugar_verifier::types::MemberKind;

    if !sugar_cli::cmd_mint::project_declares_import_dependencies(project_root) {
        return Ok(());
    }
    let dep_bindings = sugar_cli::cmd_mint::contract_bindings_from_dependency_proofs(project_root);
    if !sugar_cli::cmd_mint::dependency_bindings_need_bridges(&dep_bindings) {
        // Case-1 (same-name sworn conjoins) does not need bridges.
        return Ok(());
    }
    let bridges = pool.member_count_by_kind(MemberKind::Bridge);
    let bindings = pool.member_count_by_kind(MemberKind::LibrarySugarBindingEntry);
    if bridges == 0 && bindings == 0 {
        return Err(
            "overlay produced no vendor bindings despite declared dependencies; falling back to resident disk-pool"
                .to_string(),
        );
    }
    Ok(())
}

/// Combined soundness check for tests that hold a fully prepared overlay pool
/// (consumer feed + dependency bridges already applied).
pub fn assess_overlay_soundness(
    pool: &sugar_verifier::types::MementoPool,
    project_root: &Path,
) -> Result<(), String> {
    assess_consumer_overlay_testimony(pool)?;
    assess_overlay_vendor_bindings(pool, project_root)
}

/// Solve one edited buffer against the resident base index: stage the
/// SOURCE-OVERLAY, FEED consumer claims via enumerate→fold (one composition
/// with the API), and drive THE resident-base SOLVE door
/// ([`sugar_verifier::consistency::verify_consistency_scoped_with_base_index`]).
/// Warmth is derived (base index already resident) — zero project FS for
/// claim facts. `ctx` is never mutated (caller owns rebuild).
pub fn solve_buffer(ctx: &ProveContext, file: &Path, source: &str) -> SolveOutcome {
    // #4007 Auto mode (LSP client): lift importable vendor source into a
    // working base pool, then rebuild the consistency index from that pool.
    // Solve still only sees mementos — site-packages is never opened inside
    // the solve door.
    let mut auto_logs: Vec<String> = Vec::new();
    let owned_auto_index: Option<sugar_verifier::consistency::ConsistencyIndex> =
        if crate::auto_mode::auto_lift_enabled() {
            let mut working_base_pool = ctx.pool.clone();
            auto_logs = crate::auto_mode::auto_lift_imports_into_pool(
                &ctx.project_root,
                source,
                &mut working_base_pool,
            );
            Some(sugar_verifier::consistency::build_consistency_index(
                &working_base_pool,
            ))
        } else {
            None
        };
    let working_index: &sugar_verifier::consistency::ConsistencyIndex =
        owned_auto_index.as_ref().unwrap_or(&ctx.consistency_index);

    let overlay_root =
        std::env::temp_dir()
            .join("sugar-lsp-lift-src")
            .join(sugar_canonicalizer::blake3_512_hex(
                ctx.project_root.display().to_string().as_bytes(),
            ));

    if let Err(err) = build_source_overlay_project(&ctx.project_root, &overlay_root, file, source) {
        return SolveOutcome {
            rows: Vec::new(),
            degraded: true,
            degraded_reason: Some(format!(
                "source-overlay build failed; falling back to resident disk-pool: {err}"
            )),
            auto_logs,
            report_lift: None,
        };
    }

    // #3809: one feed -- enumerate→fold→pool. No mint_project_scratch_proof.
    // #3802/#3808 soundness floor: never return un-degraded when the overlay
    // produced no real anchored testimony, or declared deps but no vendor
    // bindings/bridges (case-2 universe laws would silently vanish).
    let (overlay_pool, degraded, degraded_reason) = match feed_overlay_pool(&overlay_root) {
        Ok(mut pool) => {
            // Consumer testimony first -- before injection loads vendor members
            // that must not masquerade as consumer-anchored candidates (#3802).
            if let Err(reason) = assess_consumer_overlay_testimony(&pool) {
                (
                    sugar_verifier::types::MementoPool::default(),
                    true,
                    Some(reason),
                )
            } else {
                // #3808 root cause: stage consumer→vendor bridges from the
                // resident import set (in-process; overlay tree deliberately
                // excludes `.sugar/imports`). Case-2 ambient-post specialization
                // needs these bridges so target contract bodies resolve.
                let _injected = sugar_cli::cmd_mint::inject_dependency_bridges_into_pool(
                    &ctx.project_root,
                    &mut pool,
                );
                if let Err(reason) = assess_overlay_vendor_bindings(&pool, &ctx.project_root) {
                    (
                        sugar_verifier::types::MementoPool::default(),
                        true,
                        Some(reason),
                    )
                } else {
                    (pool, false, None)
                }
            }
        }
        Err(err) => (
            sugar_verifier::types::MementoPool::default(),
            true,
            Some(format!(
                "enumerate→fold feed failed; falling back to resident disk-pool: {err}"
            )),
        ),
    };

    // #3809: one solve door; base index is client-fed (imports + auto-lift mementos).
    let results = sugar_verifier::consistency::verify_consistency_scoped_with_base_index(
        working_index,
        &overlay_pool,
        &ctx.plan,
        &ctx.registry,
        &ctx.compilers,
        &ctx.project_root,
        &ctx.project_root,
    );

    // #4148: if declared deps need vendor bridges and any ambient vendor post
    // was dropped during specialization (open after substitution, decode fail),
    // the vendor law never reached the solve -- degrade to cold. Over-degrade is
    // safe; silent un-degraded green on a vacuous refuse is not.
    let (degraded, degraded_reason) = if !degraded {
        match assess_dropped_ambient_posts(&results, &ctx.project_root) {
            Ok(()) => (false, None),
            Err(reason) => (true, Some(reason)),
        }
    } else {
        (degraded, degraded_reason)
    };

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

    // Report mode surfaces: best-effort kit lift report on the overlay
    // (factory dig green→red + Minority yellow). Failures stay silent in payload.
    let report_out = overlay_root.join(".sugar").join("report-mode-out");
    let _ = std::fs::create_dir_all(&report_out);
    let report_lift =
        match sugar_cli::cmd_mint::report_lift_response_for_project(&overlay_root, &report_out) {
            Ok(v) => Some(v),
            Err(err) => {
                tracing::debug!(error = %err, "report-mode lift snapshot skipped");
                None
            }
        };

    SolveOutcome {
        rows,
        degraded,
        degraded_reason,
        auto_logs,
        report_lift,
    }
}

/// #4148 post-survival half of the soundness floor.
///
/// Under declared deps that need bridges, any dropped ambient vendor post means
/// the overlay did not apply the vendor law it was handed. Force degrade so
/// the extension falls back cold -- never un-degraded vacuous refuse.
pub fn assess_dropped_ambient_posts(
    results: &[sugar_verifier::consistency::ConsistencyResult],
    project_root: &Path,
) -> Result<(), String> {
    if !sugar_cli::cmd_mint::project_declares_import_dependencies(project_root) {
        return Ok(());
    }
    let dep_bindings = sugar_cli::cmd_mint::contract_bindings_from_dependency_proofs(project_root);
    if !sugar_cli::cmd_mint::dependency_bindings_need_bridges(&dep_bindings) {
        return Ok(());
    }
    let dropped: Vec<_> = results
        .iter()
        .flat_map(|r| r.dropped_ambient_posts.iter())
        .collect();
    if dropped.is_empty() {
        return Ok(());
    }
    let n = dropped.len();
    let reasons: Vec<&str> = dropped
        .iter()
        .map(|d| d.reason.label())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    Err(format!(
        "overlay dropped {n} vendor post(s) as not-closed after specialization \
         (reasons: {}); the vendor law never reached the solve -- falling back to resident disk-pool",
        reasons.join(", ")
    ))
}
