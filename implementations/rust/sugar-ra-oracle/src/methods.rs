// SPDX-License-Identifier: MIT OR Apache-2.0
//
// methods.rs: the two JSON-RPC methods this oracle serves, moved verbatim out
// of sugar-linkerd/src/methods.rs (daemon-1 extraction).
//
// rustAnalyzerReady    : resident RA readiness gate.
// resolveReceiverCrate : Tier 2b callee-resolution against the resident, warm
//                        rust-analyzer host, fronted by the content-addressed
//                        per-file cache. Specs #1705/#1706/#1707 and
//                        2026-05-30-callee-resolution-tiers §2.T2b.

use std::path::PathBuf;
use std::sync::Arc;

use serde_json::Value as Json;
use tokio::sync::Mutex;
use tokio::task;
use tracing::instrument;

// -------------------------------------------------------------------
// Error codes (mirrors sugar-linkerd's R10 table; only the codes this
// oracle's two methods actually return).
// -------------------------------------------------------------------

pub const ERR_INVALID_PARAMS: i64 = -32602;

pub fn rpc_error(code: i64, message: &str, id: &Json) -> Json {
    serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message,
        }
    })
}

pub fn rpc_result(result: Json, id: &Json) -> Json {
    serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": result,
    })
}

// -------------------------------------------------------------------
// rustAnalyzerReady: resident RA readiness gate
// -------------------------------------------------------------------

/// Handle a `rustAnalyzerReady` request.
///
/// Params:
/// `{ "workspaceRoot": "/abs/path", "timeoutMs": <optional u64> }`
///
/// Returns:
/// `{ "ready": <bool>, "phase": "spawning|ready|failed", "detail": <str> }`
///
/// This is the event-backed readiness seam for proof-producing Rust-kit paths:
/// the oracle owns the resident rust-analyzer session, `RaOracle::start`
/// consumes rust-analyzer's LSP progress/serverStatus stream, and callers wait
/// here before issuing resolution queries. No CLI/verifier language semantics
/// move across this boundary.
#[instrument(skip(host, params))]
pub async fn handle_rust_analyzer_ready(
    host: Arc<crate::ra_host::RaHost>,
    params: &Json,
    id: &Json,
) -> Json {
    use std::path::PathBuf as StdPathBuf;
    use std::time::Duration;

    let workspace_root = match params.get("workspaceRoot").and_then(|v| v.as_str()) {
        Some(w) => StdPathBuf::from(w),
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'workspaceRoot'", id),
    };
    let timeout_ms = params
        .get("timeoutMs")
        .and_then(|v| v.as_u64())
        .unwrap_or(300_000);
    let timeout = Duration::from_millis(timeout_ms);
    let host_for_wait = host.clone();
    let root_for_wait = workspace_root.clone();
    let phase =
        match task::spawn_blocking(move || host_for_wait.wait_until_ready(&root_for_wait, timeout))
            .await
        {
            Ok(phase) => phase,
            Err(error) => {
                return rpc_result(
                    serde_json::json!({
                        "ready": false,
                        "phase": "failed",
                        "detail": format!("rust-analyzer readiness wait task failed: {error}"),
                    }),
                    id,
                )
            }
        };
    let ready = phase == crate::ra_host::Phase::Ready;
    let detail = match phase {
        crate::ra_host::Phase::Ready => "rust-analyzer workspace indexed and ready".to_string(),
        crate::ra_host::Phase::Failed => {
            "rust-analyzer failed to reach readiness; resolutions refuse".to_string()
        }
        crate::ra_host::Phase::Spawning => {
            format!("rust-analyzer still indexing after {timeout_ms}ms; resolutions refuse")
        }
    };
    rpc_result(
        serde_json::json!({
            "ready": ready,
            "phase": phase.as_str(),
            "detail": detail,
        }),
        id,
    )
}

// -------------------------------------------------------------------
// resolveReceiverCrate: Tier 2b callee-resolution against the resident,
// warm rust-analyzer host, fronted by the content-addressed per-file cache.
// Specs #1705/#1706/#1707 and 2026-05-30-callee-resolution-tiers §2.T2b.
// -------------------------------------------------------------------
//
// PHASE 2 (receiver TYPE -> disambiguated concept) -- DOCUMENTED TODO.
//
// Phase 1 (this code) resolves a method call's receiver-defining CRATE (`std`)
// and returns it; the lifter then keys the bridge on `(std, <bare_leaf>)`. That
// is the empirically dominant discharge-blocker: minting the rust-std shim emits
// `13 bridges, 33 lift-gaps [no-contract-for-callee=33]`. The 33 gaps are
// `get`/`push`/`trim`/`take`/`expect`/... -- callees for which the shim ALREADY
// defines a wrapper, but under a DISAMBIGUATED concept name, not the bare leaf:
//   (Option, unwrap) -> option_unwrap  (Result, unwrap) -> result_unwrap
//   (Vec/slice, get)  -> slice_get      (Vec, push)      -> vec_push
//   (str, trim)       -> str_trim       (str, starts_with) -> str_starts_with
//   (&[&str], join)   -> str_join        (Option, take)   -> option_take
//   (Option, expect)  -> option_expect
// The bare leaf `unwrap` names neither Option::unwrap nor Result::unwrap, so the
// bridge to `(std, unwrap)` matches NOTHING.
//
// THE FIX (mechanism, not yet implemented): also capture the receiver's TYPE,
// then key the bridge on the wrapper's @sugar CONCEPT, which is the canonical
// cross-impl disambiguation handle the shim already publishes
// (`concept = "library:rust-slice-get"`, etc.). rust-analyzer gives the type two
// ways, both already reachable from the warm session in `RaSession`:
//   (a) `textDocument/hover` on the receiver expression -> the rendered type
//       (`Option<i32>`, `&[u8]`, `&str`), OR
//   (b) read the RESOLVED definition's CONTAINER path from the existing
//       `textDocument/definition` result: `.../core/option.rs` in an `impl
//       Option` block -> `core::option::Option`. (b) reuses the request Phase 1
//       already makes, so it is the cheaper extension.
// Then map `(receiver_type_head, leaf)` -> concept via the table above (the head
// is `Option`/`Result`/`Vec`/`[T]`/`str`/`&[&str]`), and return the concept
// alongside the crate:
//   { resolved: { "<pos>": { "crate": "std", "concept": "library:rust-slice-get" } } }
// The lifter then prefers `concept` as the bridge key when present, reaching the
// wrapper's real (often body-bearing) precondition; absent a concept it falls
// back to today's `(crate, leaf)` key. This is purely additive: the wire shape
// stays backward-compatible (crate-only string OR {crate, concept} object), no
// substrate code changes (§2.T2b: the oracle upgrades behind the §1 obligation),
// and the refuse-floor is unchanged (no type -> no concept -> existing behavior).
// Expected effect on the shim alone: bridges 13 -> ~46, and the partial wrappers
// (unwrap/expect) contribute real dischargeable `pre`s.
//
// The content-addressed cache already keys on file content + dep-set, so it
// caches the concept the same way it caches the crate: extend `PosOutcome` from
// `Crate(String)` to also carry an optional concept. No re-architecture needed.

/// Handle a `resolveReceiverCrate` request.
///
/// Params:
/// ```json
/// { "workspaceRoot": "/abs/path",
///   "queries": [ { "file": "/abs/file.rs", "line": <0-based>, "col": <0-based> }, ... ] }
/// ```
///
/// Returns:
/// ```json
/// { "resolved": { "<file>:<line>:<col>": { "crate": "<crate>", "type": "<stem>"|null }, ... },
///   "ready": <bool> }
/// ```
/// `type` is the receiver's defining-type stem (`option`/`result`/`slice`/...),
/// the discriminator that lets a panic site key on the disambiguated rust-std
/// partial; null when the crate was definite but the type was not disambiguable.
///
/// Resolution path, per query file:
///   1. CACHE FIRST. Read the file's on-disk bytes, compute the content-address
///      key (blake3(content) + Cargo/toolchain CID). Each cached position then
///      validates its own dependency set. Valid resolved positions go straight
///      into `resolved`; valid recorded refusals stay absent; invalid/missing
///      positions alone go to RA. This is the #1706 granularity boundary.
///   2. MISS -> RA, only if the resident session is `Ready`. Each missed
///      position is classified resolved / deterministic-refuse / not-ready.
///   3. WRITE BACK only the positions that SETTLED (resolved or
///      deterministic-refuse), merging them into the existing file entry. A
///      not-ready position is NOT cached (a partial entry would wrongly suppress
///      RA later). This preserves the refuse-floor across caching.
///
/// `ready`: true unless there were cache-miss files that needed RA but the
/// session was not Ready. A `false` with an empty `resolved` is the cold-daemon
/// first-mint outcome; the caller refuses to Tier 1/2a and the next mint warms.
/// Cache hits are returned REGARDLESS of RA phase (advisor reconciliation of the
/// brief's `ready` rule with the coordinator's cache-hit-no-RA requirement).
#[instrument(skip(host, cache, cache_path, params))]
pub async fn handle_resolve_receiver_crate(
    host: Arc<crate::ra_host::RaHost>,
    cache: Arc<Mutex<crate::resolve_cache::ResolveCache>>,
    cache_path: PathBuf,
    params: &Json,
    id: &Json,
) -> Json {
    use crate::ra_host::{Phase, PosResult};
    use crate::resolve_cache::{CachedPosition, FileResolution, PosOutcome, ResolutionDeps};
    use std::collections::BTreeMap;
    use std::time::Duration;
    use sugar_walk::ra_oracle::ResolveQuery;

    let workspace_root = match params.get("workspaceRoot").and_then(|v| v.as_str()) {
        Some(w) => PathBuf::from(w),
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'workspaceRoot'", id),
    };
    let queries = match params.get("queries").and_then(|v| v.as_array()) {
        Some(q) => q,
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'queries' array", id),
    };

    // Group queries by file. RA is opened per file, and the cache is keyed per
    // file, so this grouping is the natural unit. Each entry is (line, col).
    let mut by_file: BTreeMap<String, Vec<(u32, u32)>> = BTreeMap::new();
    for q in queries {
        let (Some(file), Some(line), Some(col)) = (
            q.get("file").and_then(|v| v.as_str()),
            q.get("line").and_then(|v| v.as_u64()),
            q.get("col").and_then(|v| v.as_u64()),
        ) else {
            continue;
        };
        by_file
            .entry(file.to_string())
            .or_default()
            .push((line as u32, col as u32));
    }

    // Second key component: resolver-global inputs (Cargo.lock + toolchain).
    // Source sensitivity is checked per position through `ResolutionDeps`.
    let dep_cid = crate::resolve_cache::base_resolution_context_cid(&workspace_root);

    let mut resolved: serde_json::Map<String, Json> = serde_json::Map::new();
    // A file that misses the cache and needs RA goes here; we consult the
    // session only if it is Ready.
    let mut needs_ra: Vec<(String, Vec<u8>, Vec<(u32, u32)>)> = Vec::new();

    // -- Pass 1: cache (no RA, regardless of phase). --
    {
        let cache_guard = cache.lock().await;
        for (file, positions) in &by_file {
            let Ok(content) = std::fs::read(file) else {
                // Unreadable file: nothing to resolve; skip (refuse).
                continue;
            };
            if let Some(entry) = cache_guard.get(&content, &dep_cid) {
                let mut missing = Vec::new();
                for (line, col) in positions {
                    let pkey = format!("{line}:{col}");
                    match entry.positions.get(&pkey) {
                        Some(cached) if cached.deps.validate(&workspace_root) => {
                            if let PosOutcome::Crate {
                                krate,
                                type_stem,
                                effect,
                            } = &cached.outcome
                            {
                                // Effect is cached alongside the crate, so a hit
                                // reproduces the oracle's verdict (Mutating ->
                                // refused) with no RA spawn. An empty effect (old
                                // cache file) renders as "unknown" -> conservatively
                                // left unclassified.
                                let effect_str = if effect.is_empty() { "unknown" } else { effect };
                                resolved.insert(
                                    format!("{file}:{line}:{col}"),
                                    resolution_value(krate, type_stem.as_deref(), effect_str),
                                );
                            }
                            // Refused -> stays unresolved (refuse-floor).
                        }
                        _ => missing.push((*line, *col)),
                    }
                }
                if !missing.is_empty() {
                    needs_ra.push((file.clone(), content, missing));
                }
            } else {
                needs_ra.push((file.clone(), content, positions.clone()));
            }
        }
    }

    if needs_ra.is_empty() {
        // Everything served from cache: ready regardless of RA phase.
        return rpc_result(
            serde_json::json!({ "resolved": Json::Object(resolved), "ready": true }),
            id,
        );
    }

    // -- Pass 2: RA, after the resident session reaches readiness. --
    let session = host.session_for(&workspace_root);
    let timeout_ms = params
        .get("timeoutMs")
        .and_then(|v| v.as_u64())
        .unwrap_or(300_000);
    let session_for_wait = session.clone();
    let phase = match task::spawn_blocking(move || {
        session_for_wait.wait_until_ready(Duration::from_millis(timeout_ms))
    })
    .await
    {
        Ok(phase) => phase,
        Err(error) => {
            tracing::warn!(
                %error,
                "resolveReceiverCrate: readiness wait task failed; refusing RA-needed misses"
            );
            Phase::Failed
        }
    };
    if phase != Phase::Ready {
        // Indexing timed out or startup failed. Return cache hits gathered so
        // far with ready:false so the caller refuses RA-needed misses.
        return rpc_result(
            serde_json::json!({ "resolved": Json::Object(resolved), "ready": false }),
            id,
        );
    }

    // Resolve each missing file against the warm session, then cache-write the
    // files that fully settled.
    let mut cache_writes: Vec<(Vec<u8>, FileResolution)> = Vec::new();
    let mut n_resolved = 0usize;
    let mut n_refused = 0usize;
    let mut n_not_ready = 0usize;
    for (file, content, positions) in &needs_ra {
        // CANONICALIZE the file path for the RA query. A caller may pass a
        // non-canonical absolute path (e.g. `<root>/./src/lib.rs`): rust-analyzer
        // keys its analyzed VFS documents by canonical path, and a `file://` URI
        // with an embedded `/./` resolves to a DIFFERENT, unanalyzed document,
        // which returns a null definition (a silent refuse for every position in
        // the file). Canonicalizing here makes the URI match RA's workspace
        // document so resolution actually lands. The response key stays the
        // ORIGINAL `file` string so the caller's lookup matches what it sent.
        let ra_path = std::fs::canonicalize(file).unwrap_or_else(|_| PathBuf::from(file));
        let ra_queries: Vec<ResolveQuery> = positions
            .iter()
            .map(|(line, col)| ResolveQuery {
                abs_path: ra_path.clone(),
                lsp_line: *line,
                lsp_col: *col,
            })
            .collect();
        let results = session.resolve(ra_queries);

        let mut file_res = FileResolution::default();
        let mut all_settled = true;
        for ((line, col), r) in positions.iter().zip(results.iter()) {
            let pkey = format!("{line}:{col}");
            match r {
                PosResult::Resolved {
                    krate,
                    type_stem,
                    definition_files,
                    effect,
                } => {
                    resolved.insert(
                        format!("{file}:{line}:{col}"),
                        resolution_value(krate, type_stem.as_deref(), sig_effect_str(*effect)),
                    );
                    let deps = ResolutionDeps::from_files(&workspace_root, definition_files)
                        .unwrap_or_else(|| ResolutionDeps::workspace(&workspace_root));
                    file_res.positions.insert(
                        pkey,
                        CachedPosition::resolved(
                            krate,
                            type_stem.as_deref(),
                            sig_effect_str(*effect),
                            deps,
                        ),
                    );
                    n_resolved += 1;
                }
                PosResult::Refused => {
                    file_res.positions.insert(
                        pkey,
                        CachedPosition::refused(ResolutionDeps::workspace(&workspace_root)),
                    );
                    n_refused += 1;
                }
                PosResult::NotReady => {
                    // RA still churning on this position: do not cache the file.
                    all_settled = false;
                    n_not_ready += 1;
                }
            }
        }
        // Cache-write only a fully-settled file (every position resolved or
        // deterministically refused). A partial pass is never cached.
        if all_settled {
            cache_writes.push((content.clone(), file_res));
        }
    }

    if !cache_writes.is_empty() {
        let mut cache_guard = cache.lock().await;
        for (content, file_res) in cache_writes {
            cache_guard.merge_insert(&content, &dep_cid, file_res);
        }
        // Persist the sidecar so a fresh daemon process hits the cache and skips
        // RA entirely. Best-effort: a write failure does not break correctness
        // (a cache is never a source of truth).
        let bytes = cache_guard.to_bytes();
        let _ = persist_cache_sidecar(&cache_path, &bytes);
    }

    // `ready` is false if RA churned on any position (not-ready): the caller then
    // refuses those to Tier 1/2a and the next mint retries. Resolved/refused are
    // settled outcomes; not-ready means RA could not settle this pass.
    let ready = n_not_ready == 0;
    tracing::info!(
        ra_resolved = n_resolved,
        ra_refused = n_refused,
        ra_not_ready = n_not_ready,
        cache_hits = resolved.len() - n_resolved,
        ready,
        "resolveReceiverCrate: RA pass complete"
    );
    rpc_result(
        serde_json::json!({ "resolved": Json::Object(resolved), "ready": ready }),
        id,
    )
}

/// Build the wire value for one resolved position: an object
/// `{ "crate": "<crate>", "type": "<type_stem>"|null }`. The receiver-type stem
/// is what lets the caller key a panic site (`x.unwrap()`) on the rust-std
/// shim's disambiguated partial (`option_unwrap`) instead of the ambiguous bare
/// leaf. `type` is null when the crate was definite but the type could not be
/// disambiguated; the caller then keeps the crate and refuses to disambiguate.
fn resolution_value(krate: &str, type_stem: Option<&str>, effect: &str) -> Json {
    serde_json::json!({
        "crate": krate,
        "type": type_stem,
        // Source-audit datum: "mutating" (mutation through &mut) / "refclean" / "unknown".
        "effect": effect,
    })
}

/// Wire string for a resolved method's receiver/param mutability.
fn sig_effect_str(effect: sugar_walk::ra_oracle::SignatureEffect) -> &'static str {
    use sugar_walk::ra_oracle::SignatureEffect::*;
    match effect {
        Mutating => "mutating",
        RefClean => "refclean",
        Unknown => "unknown",
    }
}

/// Write the resolve-cache sidecar atomically (write temp + rename) so a reader
/// (a concurrently spawning daemon) never sees a half-written file.
fn persist_cache_sidecar(path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(&tmp, path)
}
