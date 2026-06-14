// SPDX-License-Identifier: Apache-2.0
//
// methods.rs: implementations of the five JSON-RPC methods per spec R5-R9.
//
// parseFile    (R5): update kit stream + re-link + return per-file diagnostics.
// getDiagnostics (R6): return cached diagnostics for a file without re-lifting.
// projectStatus (R7): return rank-3 pin from last link() call.
// flushCache   (R8): invalidate cached derivations.
// shutdown     (R9): write cache snapshot + signal server to exit.
//
// Lifting strategy for parseFile:
//   For `rust` sources: call `sugar_lift::lift_path` in-process (fast).
//   For `go`, `csharp`, `ruby`, `java`, `swift`, `cpp`, `c`, `zig`, `php`, `scala`:
//     spawn the kit's LSP plugin binary, send a JSON-RPC `parse` request,
//     read the `{declarations, callEdges}` response, and map into
//     `LinkerContract`/`LinkerCallEdge` (see `spawn_kit_lifter`).
//   For `zig`: spawn `sugar-lsp-zig` (no args: reads stdin directly).
//     `callEdges` may be omitted from the response and is treated as empty.
//   For `python`: spawn `sugar-lsp-python` (no args), method `parse`.
//     Binary is installed from implementations/python/sugar-lift-py-tests.
//   For `java`: spawn `sugar-lsp-java --rpc`, same protocol as go/csharp/ruby.
//     Requires `mvn package` in implementations/java/sugar-lift-java-core first;
//     returns LifterUnavailable if the binary is not on PATH.
//   For `swift`: spawn `sugar-lsp-swift` (no args: reads stdin directly).
//     Binary is built via `swift build -c release` in implementations/swift.
//   For `cpp`: spawn `sugar-lsp-cpp` (no args: native binary, int main()).
//     Binary built via `g++ -std=c++17 -o sugar-lsp-cpp main.cpp`.
//   For `c`: spawn `sugar-lsp-c --rpc` (requires --rpc flag).
//     Binary built via `cc -std=c11 -o sugar-lsp-c main.c`.
//   For `php`: spawn `sugar-lsp-php` (no args: reads stdin directly).
//     Binary is installed from implementations/php/bin.
//   For `scala`: spawn `sugar-lsp-scala` (no args: reads stdin directly).
//     Wrapper lives at implementations/scala/bin/sugar-lsp-scala.
//
// Binary discovery order (for subprocess kits):
//   1. Check PATH for the named binary.
//   2. Return LifterUnavailable with a clear install hint if not found.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Arc;

use serde_json::Value as Json;
use sugar_canonicalizer::blake3_512_of;
use sugar_linker::{LinkerCallEdge, LinkerContract};
use tokio::sync::Mutex;
use tokio::task;
use tracing::instrument;

use crate::state::ProjectState;

// -------------------------------------------------------------------
// Error codes (R10)
// -------------------------------------------------------------------

pub const ERR_METHOD_NOT_FOUND: i64 = -32601;
pub const ERR_INVALID_PARAMS: i64 = -32602;
pub const ERR_KIT_NOT_IN_MANIFEST: i64 = -33001;
pub const ERR_LIFTER_UNAVAILABLE: i64 = -33002;
#[allow(dead_code)]
pub const ERR_LINKER_DISCHARGE_FAILURE: i64 = -33003;

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
// R5: parseFile
// -------------------------------------------------------------------

/// Handle a `parseFile` request.
///
/// Params: `{ "kitId": <str>, "file": <absolute path>, "source": <str> }`
/// Returns: `{ "diagnostics": [LinterError] }` filtered to `file`.
#[instrument(skip(state, params))]
pub async fn handle_parse_file(state: Arc<Mutex<ProjectState>>, params: &Json, id: &Json) -> Json {
    let kit_id = match params.get("kitId").and_then(|v| v.as_str()) {
        Some(k) => k.to_string(),
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'kitId'", id),
    };
    let file = match params.get("file").and_then(|v| v.as_str()) {
        Some(f) => f.to_string(),
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'file'", id),
    };
    let source = match params.get("source").and_then(|v| v.as_str()) {
        Some(s) => s.to_string(),
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'source'", id),
    };

    // Lift source through kit-specific lifter.
    let (contracts, call_edges) = match lift_source(&kit_id, &file, &source).await {
        Ok(result) => result,
        Err(LiftError::LifterUnavailable(msg)) => {
            return rpc_error(ERR_LIFTER_UNAVAILABLE, &msg, id)
        }
        Err(LiftError::KitNotInManifest(msg)) => {
            return rpc_error(ERR_KIT_NOT_IN_MANIFEST, &msg, id)
        }
    };

    let diagnostics = {
        let mut st = state.lock().await;
        let output = st.update_and_link(&kit_id, &file, contracts, call_edges);
        // Filter diagnostics to the file that was just parsed.
        output
            .linker_errors
            .iter()
            .filter(|e| e.file.as_deref() == Some(&file))
            .map(|e| {
                serde_json::json!({
                    "kind": "linker-error",
                    "errorKind": e.kind,
                    "targetSymbol": e.target_symbol,
                    "sourceContractCid": e.source_contract_cid,
                    "reason": e.reason,
                    "file": e.file,
                    "callSiteLocus": e.call_site_locus_json,
                })
            })
            .collect::<Vec<_>>()
    };

    rpc_result(serde_json::json!({ "diagnostics": diagnostics }), id)
}

// -------------------------------------------------------------------
// R6: getDiagnostics
// -------------------------------------------------------------------

/// Handle a `getDiagnostics` request.
///
/// Params: `{ "file": <absolute path> }`
/// Returns: `[LinterError]` from the last cached link output.
pub async fn handle_get_diagnostics(
    state: Arc<Mutex<ProjectState>>,
    params: &Json,
    id: &Json,
) -> Json {
    let file = match params.get("file").and_then(|v| v.as_str()) {
        Some(f) => f.to_string(),
        None => return rpc_error(ERR_INVALID_PARAMS, "missing 'file'", id),
    };

    let diagnostics = {
        let st = state.lock().await;
        st.diagnostics_for_file(&file)
    };

    rpc_result(Json::Array(diagnostics), id)
}

// -------------------------------------------------------------------
// R7: projectStatus
// -------------------------------------------------------------------

/// Handle a `projectStatus` request.
///
/// Params: `{}`
/// Returns: `{ contractSetCid, callEdgeSetCid, bridgeSetCid, linkBundleCid }`
pub async fn handle_project_status(
    state: Arc<Mutex<ProjectState>>,
    _params: &Json,
    id: &Json,
) -> Json {
    let status = {
        let st = state.lock().await;
        st.project_status()
    };

    match status {
        Some(s) => rpc_result(s, id),
        None => rpc_result(
            serde_json::json!({
                "contractSetCid": null,
                "callEdgeSetCid": null,
                "bridgeSetCid":   null,
                "linkBundleCid":  null,
            }),
            id,
        ),
    }
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
/// linkerd owns the resident rust-analyzer session, `RaOracle::start` consumes
/// rust-analyzer's LSP progress/serverStatus stream, and callers wait here
/// before issuing resolution queries. No CLI/verifier language semantics move
/// across this boundary.
#[instrument(skip(host, params))]
pub async fn handle_rust_analyzer_ready(
    host: Arc<crate::ra_host::RaHost>,
    params: &Json,
    id: &Json,
) -> Json {
    use std::path::PathBuf;
    use std::time::Duration;

    let workspace_root = match params.get("workspaceRoot").and_then(|v| v.as_str()) {
        Some(w) => PathBuf::from(w),
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
// R8: flushCache
// -------------------------------------------------------------------

/// Handle a `flushCache` request.
///
/// Params: `{}`
/// Returns: `null`
pub async fn handle_flush_cache(
    state: Arc<Mutex<ProjectState>>,
    _params: &Json,
    id: &Json,
) -> Json {
    {
        let mut st = state.lock().await;
        st.flush_cache();
    }
    rpc_result(Json::Null, id)
}

// -------------------------------------------------------------------
// R9: shutdown (handled in server.rs: snapshot write happens there)
// -------------------------------------------------------------------

// The shutdown method is handled directly in server.rs because it needs
// access to the snapshot path and the shutdown signal. We export the
// response-building helper here for use by server.rs.

pub fn shutdown_response(id: &Json) -> Json {
    rpc_result(Json::Null, id)
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

// -------------------------------------------------------------------
// Lifter dispatch (kit-specific)
// -------------------------------------------------------------------

enum LiftError {
    LifterUnavailable(String),
    KitNotInManifest(String),
}

/// Lift `source` for the given `kit_id` and return `(contracts, call_edges)`.
///
/// Dispatch:
/// - `rust`: in-process via `sugar_lift::lift_path`.
/// - `go`: subprocess `sugar-lsp-go` (no args), method `parse`.
/// - `csharp`: subprocess `sugar-lsp-csharp --rpc`, method `parse`.
/// - `ruby`: subprocess `sugar-lsp-ruby --rpc`, method `parse`.
/// - `zig`: subprocess `sugar-lsp-zig` (no args), method `parse`; `callEdges`
///   field may be absent from response and is treated as empty.
/// - `python`: subprocess `sugar-lsp-python` (no args), method `parse`.
/// - `java`: subprocess `sugar-lsp-java --rpc`, method `parse`; binary must be
///   installed via `mvn package` in implementations/java/sugar-lift-java-core.
/// - `swift`: subprocess `sugar-lsp-swift` (no args), method `parse`.
/// - `cpp`: subprocess `sugar-lsp-cpp` (no args), method `parse`.
/// - `c`: subprocess `sugar-lsp-c --rpc`, method `parse`.
/// - `php`: subprocess `sugar-lsp-php` (no args), method `parse`.
/// - `scala`: subprocess `sugar-lsp-scala` (no args), method `parse`.
async fn lift_source(
    kit_id: &str,
    file: &str,
    source: &str,
) -> Result<(Vec<LinkerContract>, Vec<LinkerCallEdge>), LiftError> {
    match kit_id {
        "rust" => lift_rust_source(file, source).await,

        "go" => {
            let binary = find_binary("sugar-lsp-go").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'go' binary not found on PATH; install via: \
                     cd implementations/go && go install ./cmd/sugar-lsp-go"
                        .to_string(),
                )
            })?;
            spawn_kit_lifter(&binary, &[], file, source, "go-kit").await
        }

        "csharp" => {
            let binary = find_binary("sugar-lsp-csharp").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'csharp' binary not found on PATH; install via: \
                     cd implementations/csharp && dotnet publish -c Release -o ~/.local/bin"
                        .to_string(),
                )
            })?;
            spawn_kit_lifter(&binary, &["--rpc"], file, source, "csharp-kit").await
        }

        "ruby" => {
            let binary = find_binary("sugar-lsp-ruby").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'ruby' binary not found on PATH; install via: \
                     cp implementations/ruby/bin/sugar-lsp-ruby ~/.local/bin/ && chmod +x ~/.local/bin/sugar-lsp-ruby"
                        .to_string(),
                )
            })?;
            spawn_kit_lifter(&binary, &["--rpc"], file, source, "ruby-kit").await
        }

        "zig" => {
            let binary = find_binary("sugar-lsp-zig").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'zig' binary not found on PATH; install via: \
                     cd implementations/zig/sugar-lsp-zig && zig build -Doptimize=ReleaseSafe"
                        .to_string(),
                )
            })?;
            // Note: zig lsp binary reads stdin directly (no --rpc flag needed).
            // callEdges may be omitted from its response; treated as empty.
            spawn_kit_lifter(&binary, &[], file, source, "zig-kit").await
        }

        "python" => {
            let binary = find_binary("sugar-lsp-python").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'python' binary not found on PATH; install via: \
                     cd implementations/python && \
                     pip install -e sugar-lift-py-tests"
                        .to_string(),
                )
            })?;
            spawn_kit_lifter(&binary, &[], file, source, "python-kit").await
        }

        "java" => {
            let binary = find_binary("sugar-lsp-java").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'java' binary not found on PATH; install via: \
                     cd implementations/java/sugar-lift-java-core && \
                     mvn package -q && \
                     cp target/appassembler/bin/sugar-lsp-java ~/.local/bin/"
                        .to_string(),
                )
            })?;
            spawn_kit_lifter(&binary, &["--rpc"], file, source, "java-kit").await
        }

        "swift" => {
            let binary = find_binary("sugar-lsp-swift").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'swift' binary not found on PATH; install via: \
                     cd implementations/swift && swift build -c release && \
                     cp .build/release/sugar-lsp-swift ~/.local/bin/"
                        .to_string(),
                )
            })?;
            // swift lsp binary reads stdin directly (no --rpc flag needed).
            spawn_kit_lifter(&binary, &[], file, source, "swift-kit").await
        }

        "cpp" => {
            let binary = find_binary("sugar-lsp-cpp").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'cpp' binary not found on PATH; install via: \
                     cd implementations/cpp/sugar-lsp-cpp && \
                     g++ -std=c++17 -O2 -o sugar-lsp-cpp main.cpp && \
                     cp sugar-lsp-cpp ~/.local/bin/"
                        .to_string(),
                )
            })?;
            // cpp lsp binary reads stdin directly (no --rpc flag needed).
            spawn_kit_lifter(&binary, &[], file, source, "cpp-kit").await
        }

        "c" => {
            let binary = find_binary("sugar-lsp-c").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'c' binary not found on PATH; install via: \
                     cd implementations/c/sugar-lsp-c && \
                     cc -std=c11 -Wall -o sugar-lsp-c main.c && \
                     cp sugar-lsp-c ~/.local/bin/"
                        .to_string(),
                )
            })?;
            // c lsp binary requires --rpc flag (errors without it).
            spawn_kit_lifter(&binary, &["--rpc"], file, source, "c-kit").await
        }

        "php" => {
            let binary = find_binary("sugar-lsp-php").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'php' binary not found on PATH; install via: \
                     cd implementations/php && composer install && \
                     cp bin/sugar-lsp-php ~/.local/bin/"
                        .to_string(),
                )
            })?;
            spawn_kit_lifter(&binary, &[], file, source, "php-kit").await
        }

        "scala" => {
            let binary = find_binary("sugar-lsp-scala").ok_or_else(|| {
                LiftError::LifterUnavailable(
                    "kit 'scala' binary not found on PATH; install via: \
                     cd implementations/scala && \
                     chmod +x bin/sugar-lsp-scala && \
                     ln -sf \"$PWD/bin/sugar-lsp-scala\" ~/.local/bin/sugar-lsp-scala"
                        .to_string(),
                )
            })?;
            // scala wrapper runs the Scala source daemon in --rpc mode.
            spawn_kit_lifter(&binary, &[], file, source, "scala-kit").await
        }

        other => Err(LiftError::KitNotInManifest(format!(
            "unknown kitId '{other}'; valid kits: rust, go, cpp, csharp, python, ruby, swift, ts, zig, java, c, php, scala"
        ))),
    }
}

// -------------------------------------------------------------------
// Binary discovery
// -------------------------------------------------------------------

/// Find a binary by name, checking PATH only.
///
/// Returns `Some(path)` if the binary is found and executable, `None` otherwise.
fn find_binary(name: &str) -> Option<String> {
    // Use `which`-style lookup: search each PATH component.
    if let Ok(path_var) = std::env::var("PATH") {
        for dir in path_var.split(':') {
            let candidate = PathBuf::from(dir).join(name);
            if candidate.is_file() {
                // Check executable bit.
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    if let Ok(meta) = candidate.metadata() {
                        if meta.permissions().mode() & 0o111 != 0 {
                            return Some(candidate.display().to_string());
                        }
                    }
                }
                #[cfg(not(unix))]
                {
                    return Some(candidate.display().to_string());
                }
            }
        }
    }
    None
}

// -------------------------------------------------------------------
// Subprocess lifter
// -------------------------------------------------------------------

/// Spawn a kit lifter as a subprocess, send a JSON-RPC `parse` request,
/// and parse the response into `(LinkerContract[], LinkerCallEdge[])`.
///
/// Protocol:
///   1. Send `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`.
///   2. Read and discard the initialize response.
///   3. Send `{"jsonrpc":"2.0","id":2,"method":"parse","params":{"path":file,"source":source}}`.
///   4. Read one response line.
///   5. Parse `result.declarations` (array of IR declarations) into `LinkerContract`.
///   6. Parse `result.callEdges` (array of call-edge mementos) into `LinkerCallEdge`.
///   7. Send shutdown and close stdin.
///
/// Field name mapping (kit → LinkerCallEdge):
///   - `sourceContractCid` → `source_contract_cid`
///   - `targetContractCid` → `target_contract_cid`
///   - `targetSymbol`      → `target_symbol`
///   - `callSiteLocus`     → `call_site_locus_json`
///   - `evidenceTerm`      → `evidence_term_json`
///
/// CID strategy for declarations:
///   The daemon computes a stable `contract_cid` from the declaration's
///   `{name, outBinding?, pre?, post?, inv?}` fields using BLAKE3-512(JCS(...)).
///   This may differ from the CID a kit computed into its own call-edge mementos
///   (each kit uses its own serialisation formula for cross-kit CID computation).
///   Cross-kit linker resolution works via `targetSymbol` lookup rather than CID
///   matching, so this discrepancy does not break bridge derivation for targets.
///   Source-contract post-condition lookup will return None for cross-kit sources
///   (discharge checking is skipped, not errored): acceptable MVP behaviour.
///
/// Missing fields:
///   - `callEdges` absent from response: treated as empty (zig case).
///   - `declarations` absent: treated as empty.
async fn spawn_kit_lifter(
    binary: &str,
    args: &[&str],
    file: &str,
    source: &str,
    kit_label: &str,
) -> Result<(Vec<LinkerContract>, Vec<LinkerCallEdge>), LiftError> {
    let binary = binary.to_string();
    let args: Vec<String> = args.iter().map(|s| s.to_string()).collect();
    let file = file.to_string();
    let source = source.to_string();
    let kit_label = kit_label.to_string();

    task::spawn_blocking(move || {
        let mut child = Command::new(&binary)
            .args(&args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| LiftError::LifterUnavailable(format!("spawn {binary}: {e}")))?;

        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| LiftError::LifterUnavailable("no stdin handle".to_string()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| LiftError::LifterUnavailable("no stdout handle".to_string()))?;
        let mut reader = BufReader::new(stdout);

        // 1. Send initialize.
        let init_req = serde_json::json!({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        });
        let init_line = serde_json::to_string(&init_req).unwrap() + "\n";
        stdin.write_all(init_line.as_bytes()).map_err(|e| {
            LiftError::LifterUnavailable(format!("write initialize to {binary}: {e}"))
        })?;

        // 2. Read initialize response (discard).
        let mut init_resp = String::new();
        reader.read_line(&mut init_resp).map_err(|e| {
            LiftError::LifterUnavailable(format!("read initialize from {binary}: {e}"))
        })?;

        // 3. Send parse request.
        let parse_req = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "parse",
            "params": { "path": file, "source": source }
        });
        let parse_line = serde_json::to_string(&parse_req).unwrap() + "\n";
        stdin
            .write_all(parse_line.as_bytes())
            .map_err(|e| LiftError::LifterUnavailable(format!("write parse to {binary}: {e}")))?;

        // 4. Read parse response.
        let mut resp_line = String::new();
        reader
            .read_line(&mut resp_line)
            .map_err(|e| LiftError::LifterUnavailable(format!("read parse from {binary}: {e}")))?;

        // Send shutdown and drop stdin to let the subprocess exit cleanly.
        let shutdown_req = serde_json::json!({
            "jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}
        });
        let shutdown_line = serde_json::to_string(&shutdown_req).unwrap() + "\n";
        let _ = stdin.write_all(shutdown_line.as_bytes());
        drop(stdin);
        let _ = child.wait();

        // 5. Parse response.
        let resp: Json = serde_json::from_str(resp_line.trim()).map_err(|e| {
            LiftError::LifterUnavailable(format!("parse JSON from {binary}: {e}; raw: {resp_line}"))
        })?;

        if let Some(err) = resp.get("error") {
            return Err(LiftError::LifterUnavailable(format!(
                "{binary} returned RPC error: {err}"
            )));
        }

        let result = resp.get("result").ok_or_else(|| {
            LiftError::LifterUnavailable(format!("{binary} response missing 'result' field"))
        })?;

        // 6. Extract declarations array.
        let decls_json = extract_array_field(result, "declarations");
        let contracts = decls_json
            .iter()
            .filter_map(|decl| parse_declaration_to_contract(decl, &kit_label))
            .collect::<Vec<_>>();

        // 7. Extract callEdges array (may be absent for some kits, e.g. zig).
        let edges_json = extract_array_field(result, "callEdges");
        let call_edges = edges_json
            .iter()
            .filter_map(parse_call_edge)
            .collect::<Vec<_>>();

        Ok((contracts, call_edges))
    })
    .await
    .map_err(|e| LiftError::LifterUnavailable(format!("spawn_blocking: {e}")))?
}

/// Extract a JSON array from a field in a result object.
///
/// Handles the case where the field is absent (returns empty vec) or where the
/// field is a JSON-encoded string (a shape used by some kit lifters): in that
/// case the string is re-parsed as JSON.
fn extract_array_field<'a>(result: &'a Json, field: &str) -> Vec<Json> {
    match result.get(field) {
        None => vec![],
        Some(Json::Array(arr)) => arr.clone(),
        Some(Json::String(s)) => {
            // Some kit lifters (e.g. python) encode the array as a JSON string.
            // Re-parse it.
            match serde_json::from_str::<Json>(s) {
                Ok(Json::Array(arr)) => arr,
                _ => vec![],
            }
        }
        _ => vec![],
    }
}

/// Parse a single IR declaration JSON object into a `LinkerContract`.
///
/// Only `kind: "contract"` declarations are mapped; bridges and call-edges
/// in the declarations array are skipped.
///
/// CID is computed as BLAKE3-512(JCS({name, outBinding?, pre?, post?, inv?})).
fn parse_declaration_to_contract(decl: &Json, kit_label: &str) -> Option<LinkerContract> {
    if decl.get("kind").and_then(|k| k.as_str()) != Some("contract") {
        return None;
    }
    let name = decl.get("name").and_then(|n| n.as_str())?.to_string();
    if name.is_empty() {
        return None;
    }

    let pre_json = decl.get("pre").cloned();
    let post_json = decl.get("post").cloned();
    let inv_json = decl.get("inv").cloned();
    let out_binding = decl
        .get("outBinding")
        .and_then(|v| v.as_str())
        .unwrap_or("out")
        .to_string();

    // Compute a stable content CID: BLAKE3-512(JCS({name, outBinding, pre?, post?, inv?})).
    let contract_cid = compute_contract_cid_from_json(
        &name,
        &out_binding,
        pre_json.as_ref(),
        post_json.as_ref(),
        inv_json.as_ref(),
    );

    Some(LinkerContract {
        name,
        kit: kit_label.to_string(),
        contract_cid,
        pre_json,
        post_json,
    })
}

/// Compute a contract content CID from declaration fields.
///
/// Algorithm: BLAKE3-512(JCS({name, outBinding, pre?, post?, inv?}))
/// Matches the rust lifter's `contract_cid()` formula so that cross-kit
/// contracts with identical logical content produce identical CIDs.
fn compute_contract_cid_from_json(
    name: &str,
    out_binding: &str,
    pre: Option<&Json>,
    post: Option<&Json>,
    inv: Option<&Json>,
) -> String {
    use sugar_canonicalizer::{encode_jcs, Value};

    // Build the canonical object with required + optional fields.
    let mut kvs: Vec<(String, std::sync::Arc<Value>)> = Vec::new();
    kvs.push(("name".into(), Value::string(name.to_string())));
    kvs.push(("outBinding".into(), Value::string(out_binding.to_string())));
    if let Some(p) = pre {
        if let Some(v) = json_to_canon_value(p) {
            kvs.push(("pre".into(), v));
        }
    }
    if let Some(p) = post {
        if let Some(v) = json_to_canon_value(p) {
            kvs.push(("post".into(), v));
        }
    }
    if let Some(i) = inv {
        if let Some(v) = json_to_canon_value(i) {
            kvs.push(("inv".into(), v));
        }
    }
    let obj = std::sync::Arc::new(Value::Object(kvs));
    let jcs = encode_jcs(&obj);
    blake3_512_of(jcs.as_bytes())
}

/// Parse a single call-edge JSON object from a kit lifter's response.
///
/// JSON field names (camelCase) per the IR spec:
///   `sourceContractCid`, `targetContractCid`, `targetSymbol`,
///   `callSiteLocus`, `evidenceTerm`
fn parse_call_edge(edge: &Json) -> Option<LinkerCallEdge> {
    let source_cid = edge
        .get("sourceContractCid")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if source_cid.is_empty() {
        return None;
    }

    let target_cid = edge
        .get("targetContractCid")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let target_symbol = edge
        .get("targetSymbol")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let locus = edge.get("callSiteLocus").cloned().unwrap_or(Json::Null);
    let evidence = edge.get("evidenceTerm").cloned().unwrap_or(Json::Null);

    Some(LinkerCallEdge {
        source_contract_cid: source_cid,
        target_contract_cid: target_cid,
        target_symbol,
        call_site_locus_json: locus,
        evidence_term_json: evidence,
    })
}

/// Convert a `serde_json::Value` to a `sugar_canonicalizer::Value`.
///
/// Used when computing content CIDs from parsed declaration JSON.
fn json_to_canon_value(v: &Json) -> Option<std::sync::Arc<sugar_canonicalizer::Value>> {
    use sugar_canonicalizer::Value;
    let cv = match v {
        Json::Null => Value::Null,
        Json::Bool(b) => Value::Bool(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::Integer(i)
            } else {
                Value::String(n.to_string())
            }
        }
        Json::String(s) => Value::String(s.clone()),
        Json::Array(arr) => {
            let items: Vec<std::sync::Arc<Value>> =
                arr.iter().filter_map(json_to_canon_value).collect();
            Value::Array(items)
        }
        Json::Object(map) => {
            let kvs: Vec<(String, std::sync::Arc<Value>)> = map
                .iter()
                .filter_map(|(k, v)| json_to_canon_value(v).map(|cv| (k.clone(), cv)))
                .collect();
            Value::Object(kvs)
        }
    };
    Some(std::sync::Arc::new(cv))
}

// -------------------------------------------------------------------
// Rust in-process lifter
// -------------------------------------------------------------------

/// Lift a single Rust source file.
///
/// Writes the source to a fresh temp directory so `sugar_lift::lift_path`
/// can walk it. Returns `(LinkerContract[], LinkerCallEdge[])`.
async fn lift_rust_source(
    file: &str,
    source: &str,
) -> Result<(Vec<LinkerContract>, Vec<LinkerCallEdge>), LiftError> {
    use sugar_linker::{LinkerCallEdge as LinkerEdge, LinkerContract};

    // Write source to a temp dir (blocking I/O, run in spawn_blocking).
    let source_owned = source.to_string();
    let file_name = PathBuf::from(file)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "lifted.rs".to_string());

    let result = tokio::task::spawn_blocking(move || {
        let tmp_dir = std::env::temp_dir().join(format!(
            "sugar-linkerd-lift-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.subsec_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(&tmp_dir)
            .map_err(|e| LiftError::LifterUnavailable(format!("create temp dir: {e}")))?;

        let tmp_file = tmp_dir.join(&file_name);
        std::fs::write(&tmp_file, &source_owned)
            .map_err(|e| LiftError::LifterUnavailable(format!("write temp file: {e}")))?;

        let report = sugar_lift::lift_path(&tmp_dir);

        // Convert sugar_lift::ContractDecl -> LinkerContract.
        let mut contracts: Vec<LinkerContract> = Vec::new();
        for decl in &report.decls {
            use sugar_claim_envelope::{
                contract_cid as compute_contract_cid, Authoring, MintContractArgs,
            };
            use sugar_ir_symbolic::serialize::formula_to_value;

            let pre_v = decl.pre.as_deref().map(formula_to_value);
            let post_v = decl.post.as_deref().map(formula_to_value);
            let inv_v = decl.inv.as_deref().map(formula_to_value);

            let args = MintContractArgs {
                evidence_term: None,
                formals: Vec::new(),
                emit_empty_formals: false,
                formal_sorts: Vec::new(),
                library: None,
                body_discharge_eligible: true,
                body_discharge_refusal_reason: None,
                panic_loci: Vec::new(),
                class_shapes: Vec::new(),
                source_warrants: Vec::new(),
                contract_name: decl.name.clone(),
                pre: pre_v.clone(),
                post: post_v.clone(),
                inv: inv_v.clone(),
                out_binding: decl.out_binding.clone(),
                produced_by: "sugar-linkerd@0.1.0".into(),
                produced_at: "2026-05-04T00:00:00.000Z".into(),
                input_cids: vec![],
                authoring: Authoring::Lift {
                    lifter: "sugar-lift".into(),
                    evidence: format!("lifted from `{}` annotations", decl.name),
                    source_cid: None,
                },
                signer_seed: [0x42; 32],
            };
            let cid = compute_contract_cid(&args);

            let pre_json = pre_v.map(|v| value_arc_to_json(&v));
            let post_json = post_v.map(|v| value_arc_to_json(&v));

            contracts.push(LinkerContract {
                name: decl.name.clone(),
                kit: "rust-kit".into(),
                contract_cid: cid,
                pre_json,
                post_json,
            });
        }

        // Convert call-edge mementos -> LinkerEdge.
        // Build name->cid index from this file's contracts for same-file resolution.
        let name_to_cid: std::collections::BTreeMap<String, String> = contracts
            .iter()
            .map(|c| (c.name.clone(), c.contract_cid.clone()))
            .collect();

        let mut call_edges: Vec<LinkerEdge> = Vec::new();
        for edge in &report.call_edges {
            let target_cid = name_to_cid.get(&edge.target_symbol).cloned();
            call_edges.push(LinkerEdge {
                source_contract_cid: edge.source_contract_cid.clone(),
                target_contract_cid: target_cid,
                target_symbol: edge.target_symbol.clone(),
                call_site_locus_json: serde_json::json!({
                    "file": file_name,
                    "line": edge.call_site_locus.line,
                    "column": edge.call_site_locus.col,
                }),
                evidence_term_json: serde_json::json!({
                    "kind": "Atomic",
                    "name": "call-site-obligation",
                    "args": [],
                }),
            });
        }

        // Clean up temp dir (best effort).
        let _ = std::fs::remove_dir_all(&tmp_dir);

        Ok((contracts, call_edges))
    })
    .await;

    match result {
        Ok(inner) => inner,
        Err(join_err) => Err(LiftError::LifterUnavailable(format!(
            "spawn_blocking error: {join_err}"
        ))),
    }
}

fn value_arc_to_json(v: &std::sync::Arc<sugar_canonicalizer::Value>) -> Json {
    value_to_json(v)
}

fn value_to_json(v: &sugar_canonicalizer::Value) -> Json {
    use sugar_canonicalizer::Value;
    match v {
        Value::Null => Json::Null,
        Value::Bool(b) => Json::Bool(*b),
        Value::Integer(i) => Json::Number((*i).into()),
        Value::String(s) => Json::String(s.clone()),
        Value::Array(items) => Json::Array(items.iter().map(|i| value_to_json(i)).collect()),
        Value::Object(kvs) => {
            let mut map = serde_json::Map::new();
            for (k, val) in kvs {
                map.insert(k.clone(), value_to_json(val));
            }
            Json::Object(map)
        }
    }
}
