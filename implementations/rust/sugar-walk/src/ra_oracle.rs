//! Tier 2b native semantic oracle (spec 2026-05-30-callee-resolution-tiers, §2.T2b).
//!
//! The syntactic tiers (T1 path/import resolution, T2a local type-flow) resolve
//! a method call's receiver-defining crate only when it is locally determinable.
//! When they refuse (`callee_crate == None` on a method call), this oracle asks
//! the language's own semantic analyzer, rust-analyzer, "what does this method
//! resolve to, and in which crate is the receiver type defined" via the LSP
//! `textDocument/definition` request, then maps the resolved definition's file
//! path to a defining crate.
//!
//! Soundness (§1.R2, supra omnia rectum): the oracle returns a crate ONLY when
//! the answer is definitive: a single definition location whose path maps to a
//! known crate (sysroot core/alloc/std, collapsed to "std"; or a cargo-registry
//! crate). Ambiguity (more than one distinct crate), an unmappable path (a
//! workspace-local file, a path outside the known roots), a null result, or an
//! unavailable analyzer all yield `None` (refuse). The oracle never guesses a
//! bridge; an unresolved call stays a lift-gap.
//!
//! Availability: the oracle is opt-in behind the `SUGAR_RESOLVE_ORACLE`
//! environment variable (`= "rust-analyzer"`). When unset, or when the
//! rust-analyzer binary cannot be located/spawned, `RaOracle::start` returns
//! `None` and every resolution refuses, so the fast path and CI are unaffected
//! by a missing analyzer. This degradation is deterministic: oracle-off and
//! oracle-on-but-absent both reduce to the same Tier-2a behavior.

use std::collections::HashMap;
use std::io::{BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::Receiver;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tracing::{debug, info, trace, warn};

/// A position to resolve: 0-based LSP line and 0-based character of the method
/// identifier, in the given absolute file path.
#[derive(Debug, Clone)]
pub struct ResolveQuery {
    pub abs_path: PathBuf,
    pub lsp_line: u32,
    pub lsp_col: u32,
}

/// A resolved method call: the receiver-defining crate (always present when
/// resolution succeeds) plus the defining TYPE stem (best-effort; the
/// receiver-type discriminator panic-freedom uses to pick the disambiguated
/// rust-std shim partial). `type_stem == None` means the crate is known but the
/// type could not be disambiguated (ambiguous or unmappable stem), so the caller
/// keeps the crate-only resolution and refuses to disambiguate, never guesses.
#[derive(Debug, Clone)]
pub struct TypedResolution {
    pub krate: String,
    pub type_stem: Option<String>,
    pub definition_files: Vec<PathBuf>,
}

/// The oracle handle: a live rust-analyzer LSP subprocess plus the bookkeeping
/// to send requests and correlate responses. Dropped (and the child killed) at
/// the end of one `lift_implications` run.
pub struct RaOracle {
    child: Child,
    stdin: ChildStdin,
    /// Messages from rust-analyzer, framed and JSON-parsed by a background
    /// reader thread. A channel (rather than a blocking `BufReader`) is what
    /// gives us `recv_timeout`, which we need both to bound a response wait and,
    /// crucially, to detect QUIESCENCE: rust-analyzer answers `definition` from
    /// whatever index state it has reached, so a query issued mid-load returns a
    /// DIFFERENT (partial) answer than the same query after the workspace fully
    /// settles. Determinism therefore requires waiting until the server stops
    /// emitting progress, not merely until some early phase reports `end`.
    rx: Receiver<Value>,
    reader_handle: Option<JoinHandle<()>>,
    root: PathBuf,
    next_id: i64,
    /// Files this session has opened in rust-analyzer, mapped to the
    /// `(content_hash, lsp_version)` they were last synced at. A RESIDENT
    /// session outlives edits to the workspace, so didOpen-once is unsound: if
    /// a file changes on disk between mints, RA would keep answering against the
    /// STALE text it first opened, and that wrong answer could be cached under
    /// the file's NEW content hash (a wrong edge on edit). Tracking the synced
    /// content hash lets `ensure_open` send a `textDocument/didChange` with the
    /// fresh text and a bumped version whenever the on-disk bytes differ, so RA
    /// always resolves against the current source. (The old per-mint cold-spawn
    /// path was immune because every mint got a brand-new RA process.)
    opened: std::collections::HashMap<PathBuf, (u64, i64)>,
}

/// How long to wait for rust-analyzer to finish loading the workspace before
/// issuing resolution queries. The cold load runs cargo/rustc over the project,
/// which can take minutes on a large workspace; this is generous on purpose.
const INDEX_WAIT: Duration = Duration::from_secs(300);
/// How long to wait for a single `textDocument/definition` response.
const DEFINITION_WAIT: Duration = Duration::from_secs(30);
/// LSP `ContentModified` error code. rust-analyzer returns this for a request
/// it cannot answer yet because its analysis state changed underneath the
/// request (i.e. it is still loading/indexing). It is the server's explicit
/// "not ready, retry" signal, which we use INSTEAD of any wall-clock wait.
const CONTENT_MODIFIED: i64 = -32801;
/// How many times to re-ask a `ContentModified`-answered query before giving up
/// and refusing. With the backoff below this spans up to a couple of minutes of
/// genuine cold-load churn, while a warm server pays zero retries.
const NOT_READY_RETRIES: usize = 40;

impl RaOracle {
    /// Start the oracle for `workspace_root`, or return `None` to refuse.
    ///
    /// Returns `None` (and the caller falls back to Tier-2a refusal) when:
    ///   - `SUGAR_RESOLVE_ORACLE` is not exactly `"rust-analyzer"`; or
    ///   - the rust-analyzer binary cannot be located or spawned.
    pub fn start(workspace_root: &Path) -> Option<RaOracle> {
        let switch = std::env::var("SUGAR_RESOLVE_ORACLE").unwrap_or_default();
        if switch != "rust-analyzer" {
            debug!(
                SUGAR_RESOLVE_ORACLE = %switch,
                "oracle disabled: SUGAR_RESOLVE_ORACLE != \"rust-analyzer\""
            );
            return None;
        }
        let bin = match locate_rust_analyzer() {
            Some(b) => {
                info!(binary = %b.display(), "oracle: rust-analyzer binary located");
                b
            }
            None => {
                warn!("oracle unavailable: rust-analyzer binary not found (PATH, rustup, SUGAR_RUST_ANALYZER)");
                return None;
            }
        };
        debug!(
            workspace = %workspace_root.display(),
            binary = %bin.display(),
            "oracle: spawning rust-analyzer LSP subprocess"
        );
        // rust-analyzer shells out `cargo metadata` to load the dependency graph.
        // If the ambient `cargo` it resolves to is OLDER than the rust-analyzer
        // binary, that call fails on a flag RA's vintage emits (e.g.
        // `--lockfile-path`), RA silently resolves NOTHING, yet still reports
        // `quiescent=true, health=warning`. That is a silent zero-resolution: a
        // K=0 census that looks honest but is a broken oracle. When RA was located
        // under a rustup toolchain, pin `CARGO`/`RUSTUP_TOOLCHAIN` to that SAME
        // toolchain so RA's `cargo metadata` matches its own vintage. Only set
        // what the caller has not set, so an explicit override always wins.
        let toolchain_env = rustup_toolchain_env_for(&bin);
        let mut cmd = Command::new(&bin);
        cmd.current_dir(workspace_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        for (k, v) in &toolchain_env {
            if std::env::var_os(k).is_none() {
                info!(key = %k, value = %v, "oracle: pinning RA toolchain env (matches the RA binary)");
                cmd.env(k, v);
            }
        }
        let mut child = cmd.spawn().ok()?;
        let stdin = child.stdin.take()?;
        let stdout = child.stdout.take()?;
        let (tx, rx) = std::sync::mpsc::channel::<Value>();
        // Background reader: frame and parse every LSP message off stdout into
        // the channel. It exits when stdout closes (the channel send then errors
        // on a dropped receiver, which also unblocks it).
        let reader_handle = std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            while let Some(msg) = read_framed_message(&mut reader) {
                if tx.send(msg).is_err() {
                    break;
                }
            }
        });
        let mut oracle = RaOracle {
            child,
            stdin,
            rx,
            reader_handle: Some(reader_handle),
            root: workspace_root.to_path_buf(),
            next_id: 0,
            opened: std::collections::HashMap::new(),
        };
        debug!("oracle: sending LSP initialize handshake");
        let quiesced = match oracle.initialize() {
            Some(q) => q,
            None => {
                warn!("oracle: LSP initialize handshake failed; refusing all queries");
                let _ = oracle.child.kill();
                return None;
            }
        };
        if quiesced {
            info!(
                workspace = %workspace_root.display(),
                "oracle: rust-analyzer ready (workspace indexed and quiescent)"
            );
        } else {
            warn!(
                workspace = %workspace_root.display(),
                index_wait_s = INDEX_WAIT.as_secs(),
                "oracle: rust-analyzer NOT quiescent after the index wait; refusing rather than \
                 minting against a partially-indexed analyzer"
            );
            let _ = oracle.child.kill();
            return None;
        }
        Some(oracle)
    }

    /// Run the LSP handshake and wait out the initial index. Returns `true` iff
    /// rust-analyzer reached quiescence (vs. proceeding best-effort on timeout).
    fn initialize(&mut self) -> Option<bool> {
        let root_uri = path_to_uri(&self.root);
        debug!(root = %self.root.display(), "oracle: step 1/4 sending LSP initialize request");
        let id = self.send_request(
            "initialize",
            json!({
                "processId": std::process::id(),
                "rootUri": root_uri,
                "capabilities": {
                    "textDocument": {
                        "definition": { "linkSupport": true },
                        // Ask for markdown hover so the receiver type renders as a
                        // fenced ```rust``` block we can parse the type head from.
                        "hover": { "contentFormat": ["markdown", "plaintext"] }
                    },
                    "window": { "workDoneProgress": true },
                    // Ask rust-analyzer to emit `experimental/serverStatus`
                    // notifications. They carry `quiescent: true` once the
                    // workspace is loaded AND indexed, which is the one
                    // authoritative readiness signal (see wait_until_quiescent).
                    "experimental": { "serverStatusNotification": true }
                },
                "workspaceFolders": [ { "uri": root_uri, "name": "sugar-target" } ],
            }),
        )?;
        // Drain until the initialize response arrives.
        self.wait_for_response(id, INDEX_WAIT)?;
        debug!("oracle: step 2/4 initialize response received");
        self.send_notification("initialized", json!({}));
        debug!(
            "oracle: step 3/4 sent 'initialized'; awaiting workspace load + index \
             (rust-analyzer progress streams below)"
        );
        // Wait ONCE for the workspace to settle before issuing any query. While
        // rust-analyzer is still loading the sysroot / a dependency it answers
        // `definition` with a REAL null (no definition yet), not ContentModified,
        // so the per-query retry below cannot recover it: the call would refuse
        // permanently. Blocking here on the server's own quiescence signal fixes
        // that, and is still event-driven (a warm server reports quiescent
        // immediately, paying nothing). The per-query ContentModified retry
        // stays as a secondary guard for re-analysis churn mid-batch.
        let quiesced = self.wait_until_quiescent(INDEX_WAIT);
        debug!(quiesced, "oracle: step 4/4 readiness wait complete");
        Some(quiesced)
    }

    /// Block until rust-analyzer reports it is quiescent (workspace loaded and
    /// indexed) or `timeout` elapses. Returns `true` iff quiescence was reached.
    ///
    /// RA emits `experimental/serverStatus` (enabled by the client capability)
    /// with `quiescent: true` once analysis settles. A query issued mid-load
    /// gets a partial/null answer the retry path cannot recover, so we wait for
    /// that one authoritative signal before batching.
    ///
    /// Every step is surfaced so the caller can SEE the index progress rather
    /// than stare at a silent multi-minute wait: RA's `$/progress`
    /// (workDoneProgress) stream is logged (begin/end + percentage at INFO/DEBUG),
    /// `serverStatus` health transitions at INFO, and a 10s heartbeat with
    /// elapsed time fires even when RA goes quiet mid-index. The return value is
    /// honest: `false` means we are about to query an unindexed server and
    /// resolution will be incomplete (the case the resident daemon exists to fix).
    fn wait_until_quiescent(&mut self, timeout: Duration) -> bool {
        let start = Instant::now();
        let deadline = start + timeout;
        let mut last_heartbeat = start;
        info!(
            timeout_s = timeout.as_secs(),
            "oracle: awaiting rust-analyzer workspace index (progress below)"
        );
        loop {
            let Some(remaining) = deadline.checked_duration_since(Instant::now()) else {
                warn!(
                    elapsed_s = start.elapsed().as_secs(),
                    timeout_s = timeout.as_secs(),
                    "oracle: rust-analyzer did NOT reach quiescence before timeout; \
                     proceeding against a partially-indexed server (resolution will be incomplete)"
                );
                return false;
            };
            // Cap the wait so the heartbeat fires even when RA is silent mid-index.
            let recv_window = remaining.min(Duration::from_secs(5));
            match self.rx.recv_timeout(recv_window) {
                Ok(msg) => {
                    // Keep RA's load unblocked (workDoneProgress/create etc.).
                    self.respond_if_server_request(&msg);
                    let method = msg.get("method").and_then(|m| m.as_str()).unwrap_or("");
                    match method {
                        "$/progress" => {
                            let token = msg
                                .pointer("/params/token")
                                .map(|v| {
                                    v.as_str()
                                        .map(str::to_string)
                                        .unwrap_or_else(|| v.to_string())
                                })
                                .unwrap_or_default();
                            let kind = msg
                                .pointer("/params/value/kind")
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            let pmsg = msg
                                .pointer("/params/value/message")
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            let title = msg
                                .pointer("/params/value/title")
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            let pct = msg
                                .pointer("/params/value/percentage")
                                .and_then(|v| v.as_u64());
                            let detail = if title.is_empty() { pmsg } else { title };
                            match kind {
                                "begin" => info!(
                                    elapsed_s = start.elapsed().as_secs(),
                                    "RA index begin: {} {}", token, detail
                                ),
                                "end" => info!(
                                    elapsed_s = start.elapsed().as_secs(),
                                    "RA index done:  {} {}", token, pmsg
                                ),
                                _ => match pct {
                                    Some(p) => debug!(
                                        elapsed_s = start.elapsed().as_secs(),
                                        "RA index:       {} {}% {}", token, p, pmsg
                                    ),
                                    None => debug!("RA index:       {} {}", token, pmsg),
                                },
                            }
                        }
                        "experimental/serverStatus" => {
                            let quiescent = msg
                                .pointer("/params/quiescent")
                                .and_then(|v| v.as_bool())
                                .unwrap_or(false);
                            let health = msg
                                .pointer("/params/health")
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            let smsg = msg
                                .pointer("/params/message")
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            info!(
                                quiescent,
                                health = %health,
                                elapsed_s = start.elapsed().as_secs(),
                                "RA serverStatus{}",
                                if smsg.is_empty() { String::new() } else { format!(": {smsg}") }
                            );
                            if quiescent {
                                info!(
                                    elapsed_s = start.elapsed().as_secs(),
                                    "oracle: rust-analyzer quiescent — workspace indexed, ready to resolve"
                                );
                                return true;
                            }
                        }
                        other => {
                            trace!(
                                method = other,
                                "oracle: inbound message (not progress/status)"
                            );
                        }
                    }
                }
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                    if last_heartbeat.elapsed() >= Duration::from_secs(10) {
                        info!(
                            elapsed_s = start.elapsed().as_secs(),
                            timeout_s = timeout.as_secs(),
                            "oracle: still indexing... (rust-analyzer quiet; waiting for quiescence)"
                        );
                        last_heartbeat = Instant::now();
                    }
                }
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                    warn!(
                        elapsed_s = start.elapsed().as_secs(),
                        "oracle: rust-analyzer stdout closed during indexing (process died?)"
                    );
                    return false;
                }
            }
        }
    }

    /// Ensure rust-analyzer has the CURRENT on-disk content of `abs_path` open.
    ///
    /// First sight of the file: `textDocument/didOpen` at version 1. A later
    /// call after the file changed on disk: `textDocument/didChange` (full
    /// replace) at a bumped version, so a RESIDENT session never answers against
    /// stale text. Unchanged content is a no-op. The content hash is the cheap
    /// discriminator; on a change we resync before any query so the resolution
    /// (and anything cached from it) reflects the new source.
    fn ensure_open(&mut self, abs_path: &Path) -> Option<()> {
        let text = std::fs::read_to_string(abs_path).ok()?;
        let hash = content_hash(text.as_bytes());
        let uri = path_to_uri(abs_path);

        match self.opened.get(abs_path).copied() {
            Some((prev_hash, _)) if prev_hash == hash => {
                // Already open with identical content: nothing to sync.
                Some(())
            }
            Some((_, prev_version)) => {
                // Open but content changed on disk: resync via didChange (full
                // document replace) at a bumped version.
                let version = prev_version + 1;
                self.send_notification(
                    "textDocument/didChange",
                    json!({
                        "textDocument": { "uri": uri, "version": version },
                        "contentChanges": [ { "text": text } ],
                    }),
                );
                self.opened.insert(abs_path.to_path_buf(), (hash, version));
                Some(())
            }
            None => {
                // First sight: didOpen at version 1.
                self.send_notification(
                    "textDocument/didOpen",
                    json!({
                        "textDocument": {
                            "uri": uri,
                            "languageId": "rust",
                            "version": 1,
                            "text": text,
                        }
                    }),
                );
                self.opened.insert(abs_path.to_path_buf(), (hash, 1));
                Some(())
            }
        }
    }

    /// Resolve one query to a definitive crate, or `None` (refuse).
    ///
    /// Readiness is EVENT-DRIVEN, not timer-driven. While rust-analyzer is still
    /// loading/indexing it answers `textDocument/definition` with the LSP
    /// `ContentModified` error (-32801) meaning "ask again, my state changed
    /// under you"; a settled server returns a definition (or a real null). We
    /// retry only on that explicit not-ready signal, with a short backoff, up to
    /// a bounded number of times. This is what makes the answer reproducible
    /// across a cold and a warm run WITHOUT paying any fixed wall-clock wait:
    /// when the index is already warm the first reply is the answer, and when it
    /// is cold we retry exactly as long as the server says it is still moving.
    /// A definition / a real null is taken as final; ambiguity and unmappable
    /// paths are refusals (never retried).
    ///
    /// Returns `None` on any refusal. Call `resolve_crate_classified` for the
    /// reason breakdown (used by `resolve_batch` for the N/M/K summary).
    pub fn resolve_crate(&mut self, q: &ResolveQuery) -> Option<String> {
        self.resolve_crate_classified(q).ok().flatten()
    }

    /// Like `resolve_crate` but distinguishes the refusal reason so callers
    /// can produce the N/M/K summary (resolved/total/not-ready).
    ///   Ok(Some(crate))  -> resolved
    ///   Ok(None)         -> refused: null definition, unmappable, or ambiguous
    ///   Err(())          -> refused: ContentModified budget exhausted (RA not ready)
    pub fn resolve_crate_classified(&mut self, q: &ResolveQuery) -> Result<Option<String>, ()> {
        let result = match self.definition_result(q)? {
            Some(r) => r,
            None => return Ok(None),
        };
        let resolved = crate_from_definition_result(&result);
        match &resolved {
            Some(krate) => debug!(
                file = %q.abs_path.display(),
                line = q.lsp_line, col = q.lsp_col, resolved_crate = %krate,
                "oracle: resolved method call to crate"
            ),
            None => trace!(
                file = %q.abs_path.display(),
                line = q.lsp_line, col = q.lsp_col,
                "oracle: refused (null result, unmappable path, or ambiguous crates)"
            ),
        }
        Ok(resolved)
    }

    /// Resolve one query to BOTH the defining crate AND the defining type stem,
    /// from a single `textDocument/definition` request. The type stem is the
    /// receiver-type discriminator panic-freedom needs (Option vs Result vs
    /// slice/vec); it disambiguates which rust-std shim partial a call must
    /// discharge against. Classification mirrors `resolve_crate_classified`:
    ///   Ok(Some(TypedResolution)) -> crate resolved (stem may still be None if
    ///                                the stem was ambiguous/unmappable but the
    ///                                crate was definite; the caller then keeps
    ///                                the crate but cannot disambiguate the type)
    ///   Ok(None)                  -> deterministic refuse (null/unmappable/ambiguous)
    ///   Err(())                   -> not-ready (ContentModified budget exhausted)
    pub fn resolve_typed_classified(
        &mut self,
        q: &ResolveQuery,
    ) -> Result<Option<TypedResolution>, ()> {
        let result = match self.definition_result(q)? {
            Some(r) => r,
            None => return Ok(None),
        };
        let Some(krate) = crate_from_definition_result(&result) else {
            return Ok(None);
        };
        // The type stem is BEST-EFFORT on top of a definite crate: an ambiguous
        // or unmappable stem leaves `type_stem = None` (the caller keeps the
        // crate but cannot reach a disambiguated partial), never a wrong stem.
        //
        // PREFER hover for the panic-leaf type stem. `textDocument/hover` at the
        // method-ident position renders the RECEIVER's own type as text: its first
        // ```rust``` block is the receiver-type path (e.g. `core::result::Result`,
        // `core::option::Option`). That gives the receiver TYPE HEAD directly, with
        // no def-jump-to-a-file heuristic, so it disambiguates the panic partial
        // even when the definition lands at a workspace-local position (where the
        // def-file-stem path yields nothing). The definition file-stem
        // (`type_stem_from_definition_result`) stays as the FALLBACK for the cases
        // hover refuses, so this is strictly additive: a hover that is empty,
        // ambiguous, or a signature/binding block (not a bare type path) refuses,
        // and the caller drops to the def-stem, then to None. An unresolved stem
        // stays unresolved; we never guess. (The crate still comes from
        // `definition`; hover only refines the type stem.)
        let hover_stem = self.hover_type_stem(q);
        let type_stem = hover_stem
            .clone()
            .or_else(|| type_stem_from_definition_result(&result));
        let definition_files = definition_files_from_definition_result(&result);
        debug!(
            file = %q.abs_path.display(),
            line = q.lsp_line, col = q.lsp_col,
            resolved_crate = %krate,
            hover_stem = ?hover_stem,
            type_stem = ?type_stem,
            stem_source = if hover_stem.is_some() { "hover" } else { "definition-file-stem" },
            definition_files = definition_files.len(),
            "oracle: resolved method call to crate + type stem"
        );
        Ok(Some(TypedResolution {
            krate,
            type_stem,
            definition_files,
        }))
    }

    /// Ask `textDocument/hover` at the method-ident position for the RECEIVER's
    /// type stem (`result`/`option`/`slice`/`str`/...), or `None` (refuse).
    ///
    /// rust-analyzer's hover at a method-call ident renders the receiver type as
    /// the FIRST fenced ```rust``` block of the markdown (a bare type path such as
    /// `core::result::Result` or `core::option::Option`); the method signature and
    /// docs follow in later blocks. `type_stem_from_hover_markdown` extracts the
    /// head of that first block (last `::` segment, generics stripped, lowercased).
    ///
    /// Soundness: this is BEST-EFFORT and never blocks the crate resolution. Hover
    /// is a refinement layered on top of the already-settled definition result, so
    /// a not-ready (ContentModified) hover, a transport failure, an empty/ambiguous
    /// markdown, or a block that is a signature/binding rather than a bare type
    /// path all yield `None` (refuse) and the caller falls back to the definition
    /// file-stem. We never guess a stem from an ambiguous hover.
    fn hover_type_stem(&mut self, q: &ResolveQuery) -> Option<String> {
        if self.ensure_open(&q.abs_path).is_none() {
            return None;
        }
        let uri = path_to_uri(&q.abs_path);
        // Hover refines an already-resolved crate, so it does NOT carry the
        // ContentModified retry budget the crate path does: if RA answers "not
        // ready" we simply refuse the stem (the def-stem fallback or `None`
        // remains). A single ContentModified retry catches a transient churn
        // without spinning.
        for attempt in 0..=1 {
            let id = self.send_request(
                "textDocument/hover",
                json!({
                    "textDocument": { "uri": uri },
                    "position": { "line": q.lsp_line, "character": q.lsp_col },
                }),
            )?;
            let resp = self.wait_for_response(id, DEFINITION_WAIT)?;
            let is_content_modified = resp
                .get("error")
                .and_then(|e| e.get("code"))
                .and_then(|c| c.as_i64())
                == Some(CONTENT_MODIFIED);
            if is_content_modified {
                if attempt < 1 {
                    std::thread::sleep(not_ready_backoff(attempt));
                    continue;
                }
                return None;
            }
            let result = resp.get("result")?;
            let markdown = hover_markdown(result)?;
            return type_stem_from_hover_markdown(&markdown);
        }
        None
    }

    /// Diagnostic: return the RAW `textDocument/hover` markdown at `q`, before any
    /// stem parsing. Used by the `hover_probe` bin to SEE what live rust-analyzer
    /// renders at a method-ident position (the input `type_stem_from_hover_markdown`
    /// is assumed to receive), rather than trusting synthetic unit-test markdown.
    /// Not on the resolution hot path; `hover_type_stem` is the production caller.
    pub fn hover_markdown_raw(&mut self, q: &ResolveQuery) -> Option<String> {
        self.ensure_open(&q.abs_path)?;
        let uri = path_to_uri(&q.abs_path);
        let id = self.send_request(
            "textDocument/hover",
            json!({
                "textDocument": { "uri": uri },
                "position": { "line": q.lsp_line, "character": q.lsp_col },
            }),
        )?;
        let resp = self.wait_for_response(id, DEFINITION_WAIT)?;
        let result = resp.get("result")?;
        hover_markdown(result)
    }

    /// Resolve a method call's receiver/param mutability via its hover signature:
    /// `Mutating` (`&mut self` / `&mut` param -> refuse "mutation through &mut"),
    /// `RefClean` (no receiver/param mutation), or `Unknown` (hover unavailable or
    /// no parseable `fn`). The source-audit datum that turns a side-effect-
    /// undetermined method call into a verdict.
    pub fn resolve_signature_effect(&mut self, q: &ResolveQuery) -> SignatureEffect {
        match self.hover_markdown_raw(q) {
            Some(md) => signature_effect_from_hover(&md),
            None => SignatureEffect::Unknown,
        }
    }

    /// Send the `textDocument/definition` request for `q`, honouring the
    /// ContentModified not-ready retry/backoff, and return the raw `result`
    /// value:
    ///   Ok(Some(result)) -> a settled definition result (may be null/empty)
    ///   Ok(None)         -> the request could not even be issued (transport)
    ///   Err(())          -> not-ready: ContentModified budget exhausted
    /// Shared by `resolve_crate_classified` and `resolve_typed_classified` so the
    /// crate and the type stem come from ONE round-trip, never two.
    fn definition_result(&mut self, q: &ResolveQuery) -> Result<Option<Value>, ()> {
        trace!(
            file = %q.abs_path.display(),
            line = q.lsp_line,
            col = q.lsp_col,
            "oracle: resolving method call position via textDocument/definition"
        );
        if self.ensure_open(&q.abs_path).is_none() {
            return Ok(None);
        }
        let uri = path_to_uri(&q.abs_path);
        for attempt in 0..=NOT_READY_RETRIES {
            let Some(id) = self.send_request(
                "textDocument/definition",
                json!({
                    "textDocument": { "uri": uri },
                    "position": { "line": q.lsp_line, "character": q.lsp_col },
                }),
            ) else {
                return Ok(None);
            };
            let Some(resp) = self.wait_for_response(id, DEFINITION_WAIT) else {
                return Ok(None);
            };
            let is_content_modified = resp
                .get("error")
                .and_then(|e| e.get("code"))
                .and_then(|c| c.as_i64())
                == Some(CONTENT_MODIFIED);
            if is_content_modified {
                if attempt < NOT_READY_RETRIES {
                    debug!(
                        file = %q.abs_path.display(),
                        line = q.lsp_line, col = q.lsp_col, attempt = attempt,
                        retries_remaining = NOT_READY_RETRIES - attempt,
                        "oracle: RA not ready (ContentModified), backing off and retrying"
                    );
                    std::thread::sleep(not_ready_backoff(attempt));
                    continue;
                }
                warn!(
                    file = %q.abs_path.display(),
                    line = q.lsp_line, col = q.lsp_col, attempts = attempt + 1,
                    "oracle: refused after exhausting ContentModified retry budget"
                );
                return Err(());
            }
            return Ok(Some(resp.get("result").cloned().unwrap_or(Value::Null)));
        }
        Ok(None)
    }

    fn send_request(&mut self, method: &str, params: Value) -> Option<i64> {
        self.next_id += 1;
        let id = self.next_id;
        trace!(method = method, id = id, "oracle: sending LSP request");
        let msg = json!({ "jsonrpc": "2.0", "id": id, "method": method, "params": params });
        self.write_message(&msg)?;
        Some(id)
    }

    fn send_notification(&mut self, method: &str, params: Value) {
        trace!(method = method, "oracle: sending LSP notification");
        let msg = json!({ "jsonrpc": "2.0", "method": method, "params": params });
        let _ = self.write_message(&msg);
    }

    /// If `msg` is a server-to-client REQUEST (has both `method` and `id`),
    /// answer it so rust-analyzer is not left waiting on us. An LSP server can
    /// block its own workspace-load progress on requests like
    /// `window/workDoneProgress/create` and `workspace/diagnostic/refresh`; a
    /// client that drops them on the floor (as the original drain loop did) can
    /// stall RA indefinitely on a large workspace. Returns true if it answered.
    ///
    /// `result: null` is the correct reply for the void-returning requests RA
    /// sends during load (workDoneProgress/create, diagnostic/refresh,
    /// registerCapability). `workspace/configuration` expects an array; we hand
    /// back one null per requested item so RA falls back to its defaults rather
    /// than erroring.
    fn respond_if_server_request(&mut self, msg: &Value) -> bool {
        let (Some(method), Some(id)) = (msg.get("method").and_then(|m| m.as_str()), msg.get("id"))
        else {
            return false;
        };
        let result = if method == "workspace/configuration" {
            let n = msg
                .pointer("/params/items")
                .and_then(|v| v.as_array())
                .map(|a| a.len())
                .unwrap_or(1);
            Value::Array(vec![Value::Null; n.max(1)])
        } else {
            Value::Null
        };
        trace!(
            method = method,
            "oracle: answering RA server->client request"
        );
        let reply = json!({ "jsonrpc": "2.0", "id": id.clone(), "result": result });
        let _ = self.write_message(&reply);
        true
    }

    fn write_message(&mut self, msg: &Value) -> Option<()> {
        let body = serde_json::to_vec(msg).ok()?;
        write!(self.stdin, "Content-Length: {}\r\n\r\n", body.len()).ok()?;
        self.stdin.write_all(&body).ok()?;
        self.stdin.flush().ok()?;
        Some(())
    }

    /// Pump messages until one with `id == want` carrying `result`/`error`, or
    /// until the deadline. Server-to-client requests/notifications are ignored.
    fn wait_for_response(&mut self, want: i64, timeout: Duration) -> Option<Value> {
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.checked_duration_since(Instant::now())?;
            match self.rx.recv_timeout(remaining) {
                Ok(msg) => {
                    // Keep RA unblocked while we wait for our own response.
                    self.respond_if_server_request(&msg);
                    if msg.get("id").and_then(|v| v.as_i64()) == Some(want)
                        && (msg.get("result").is_some() || msg.get("error").is_some())
                    {
                        return Some(msg);
                    }
                }
                Err(_) => return None,
            }
        }
    }
}

/// Backoff between `ContentModified` retries: ramp from 250ms to a 3s cap so
/// early churn re-asks quickly and a long cold load does not spin. With
/// `NOT_READY_RETRIES` this covers a couple of minutes of genuine indexing.
fn not_ready_backoff(attempt: usize) -> Duration {
    let ms = (250u64 * (attempt as u64 + 1)).min(3000);
    Duration::from_millis(ms)
}

/// Read one LSP message (framed by Content-Length) from a blocking reader.
/// Returns `None` on EOF or a malformed frame. Runs on the background reader
/// thread.
fn read_framed_message<R: Read>(reader: &mut BufReader<R>) -> Option<Value> {
    let mut header = Vec::new();
    let mut byte = [0u8; 1];
    loop {
        if reader.read(&mut byte).ok()? == 0 {
            return None;
        }
        header.push(byte[0]);
        if header.ends_with(b"\r\n\r\n") {
            break;
        }
        if header.len() > 1 << 16 {
            return None;
        }
    }
    let header_str = String::from_utf8_lossy(&header);
    let mut len = 0usize;
    for line in header_str.split("\r\n") {
        if let Some(rest) = line.to_ascii_lowercase().strip_prefix("content-length:") {
            len = rest.trim().parse().ok()?;
        }
    }
    if len == 0 {
        return None;
    }
    let mut body = vec![0u8; len];
    reader.read_exact(&mut body).ok()?;
    serde_json::from_slice(&body).ok()
}

impl Drop for RaOracle {
    fn drop(&mut self) {
        // Best-effort graceful shutdown, then kill. Killing the child closes
        // stdout, which ends the reader thread's loop; join it so no detached
        // thread outlives the oracle.
        let _ = self.send_request("shutdown", json!(null));
        self.send_notification("exit", json!(null));
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(handle) = self.reader_handle.take() {
            let _ = handle.join();
        }
    }
}

/// Locate the rust-analyzer binary: prefer the explicit override, then PATH,
/// then `rustup which`. Returns `None` when none is runnable.
fn locate_rust_analyzer() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("SUGAR_RUST_ANALYZER") {
        if !p.is_empty() {
            return Some(PathBuf::from(p));
        }
    }
    // `rustup which rust-analyzer` gives the toolchain-resolved path even when
    // the bare `rust-analyzer` proxy is not on PATH.
    if let Ok(out) = Command::new("rustup")
        .args(["which", "rust-analyzer"])
        .output()
    {
        if out.status.success() {
            let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !path.is_empty() && Path::new(&path).exists() {
                return Some(PathBuf::from(path));
            }
        }
    }
    // Fall back to the bare name and let spawn resolve it via PATH.
    if Command::new("rust-analyzer")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
    {
        return Some(PathBuf::from("rust-analyzer"));
    }
    None
}

/// Derive the `CARGO` / `RUSTUP_TOOLCHAIN` env that pins rust-analyzer's
/// `cargo metadata` shell-out to the SAME rustup toolchain the RA binary lives
/// in. Returns an empty vec when `bin` is not under a rustup toolchain layout
/// (a bare `rust-analyzer` on PATH, or a non-rustup install) -- in that case we
/// leave the ambient env alone and rely on health-signal surfacing if it breaks.
///
/// A rustup RA binary is at `<...>/toolchains/<tc>/bin/rust-analyzer`; the
/// matching cargo is the sibling `<...>/toolchains/<tc>/bin/cargo`.
fn rustup_toolchain_env_for(bin: &Path) -> Vec<(String, String)> {
    // bin/ dir, then the toolchain dir, then its parent (must be `toolchains`).
    let bin_dir = match bin.parent() {
        Some(d) => d,
        None => return Vec::new(),
    };
    let tc_dir = match bin_dir.parent() {
        Some(d) => d,
        None => return Vec::new(),
    };
    let is_rustup_layout = tc_dir
        .parent()
        .and_then(|p| p.file_name())
        .map(|n| n == "toolchains")
        .unwrap_or(false);
    if !is_rustup_layout {
        return Vec::new();
    }
    let tc_name = match tc_dir.file_name().and_then(|n| n.to_str()) {
        Some(n) => n.to_string(),
        None => return Vec::new(),
    };
    let mut out = Vec::new();
    let cargo = bin_dir.join("cargo");
    if cargo.is_file() {
        if let Some(c) = cargo.to_str() {
            out.push(("CARGO".to_string(), c.to_string()));
        }
    }
    out.push(("RUSTUP_TOOLCHAIN".to_string(), tc_name));
    out
}

/// Map a `textDocument/definition` result to a single defining crate, or
/// `None` (refuse). Accepts `Location`, `Location[]`, or `LocationLink[]`.
/// Refuses on: empty result, any location whose path is unmappable, or more
/// than one distinct normalized crate across the locations.
fn crate_from_definition_result(result: &Value) -> Option<String> {
    let locations: Vec<&Value> = match result {
        Value::Array(a) => a.iter().collect(),
        Value::Object(_) => vec![result],
        _ => return None,
    };
    if locations.is_empty() {
        return None;
    }
    let mut crates = std::collections::BTreeSet::new();
    for loc in locations {
        let uri = loc
            .get("uri")
            .or_else(|| loc.get("targetUri"))
            .and_then(|v| v.as_str())?;
        // Every location must map to a known crate; an unmappable one is a
        // refuse, not a "skip and trust the rest". Soundness over coverage.
        let krate = crate_from_uri(uri)?;
        crates.insert(normalize_crate(&krate));
    }
    if crates.len() == 1 {
        crates.into_iter().next()
    } else {
        // Ambiguous dispatch across distinct crates: refuse.
        None
    }
}

/// Map a `textDocument/definition` result to the defining TYPE stem (the source
/// file's stem at the definition site), or `None` (refuse). This is the cheap
/// receiver-type discriminator for panic-freedom: `Option::unwrap` is defined in
/// `core/src/option.rs` (stem `option`), `Result::unwrap` in `result.rs` (stem
/// `result`), `[T]::get`/`Vec::get` in `slice/mod.rs` / `vec/mod.rs`. The stem
/// alone separates the std panic partials (Option vs Result vs slice/vec) with
/// no `textDocument/hover` round-trip. Refuses (None) on empty, ambiguity across
/// distinct stems, or any unmappable location, mirroring the crate extractor.
fn type_stem_from_definition_result(result: &Value) -> Option<String> {
    let locations: Vec<&Value> = match result {
        Value::Array(a) => a.iter().collect(),
        Value::Object(_) => vec![result],
        _ => return None,
    };
    if locations.is_empty() {
        return None;
    }
    let mut stems = std::collections::BTreeSet::new();
    for loc in locations {
        let uri = loc
            .get("uri")
            .or_else(|| loc.get("targetUri"))
            .and_then(|v| v.as_str())?;
        let stem = type_stem_from_uri(uri)?;
        stems.insert(stem);
    }
    if stems.len() == 1 {
        stems.into_iter().next()
    } else {
        // Ambiguous defining type across locations: refuse (no disambiguation).
        None
    }
}

/// Extract every file URI named by a settled definition result. These files are
/// the immediate semantic evidence for #1706's per-position cache deps. When no
/// readable file deps can be built from them, linkerd falls back to the coarse
/// workspace context instead of serving an unverifiable hit.
fn definition_files_from_definition_result(result: &Value) -> Vec<PathBuf> {
    let locations: Vec<&Value> = match result {
        Value::Array(a) => a.iter().collect(),
        Value::Object(_) => vec![result],
        _ => return Vec::new(),
    };
    let mut files = std::collections::BTreeSet::new();
    for loc in locations {
        let Some(uri) = loc
            .get("uri")
            .or_else(|| loc.get("targetUri"))
            .and_then(|v| v.as_str())
        else {
            continue;
        };
        if let Some(path) = file_path_from_uri(uri) {
            files.insert(path);
        }
    }
    files.into_iter().collect()
}

fn file_path_from_uri(uri: &str) -> Option<PathBuf> {
    uri.strip_prefix("file://").map(PathBuf::from)
}

/// The defining type stem from a definition-target URI: the source file stem,
/// with the parent dir folded in for module files named `mod.rs` (so
/// `slice/mod.rs` -> `slice`, not the useless `mod`). `None` for an unmappable
/// path. The stem is a kit-internal disambiguation HANDLE, paired with the leaf
/// to select the rust-std shim's disambiguated partial (e.g. `(option, unwrap)`
/// -> `option_unwrap`); the substrate never sees it.
pub fn type_stem_from_uri(uri: &str) -> Option<String> {
    let path = uri.strip_prefix("file://").unwrap_or(uri);
    let file = path.rsplit('/').next()?;
    let stem = file.strip_suffix(".rs").unwrap_or(file);
    if stem == "mod" || stem.is_empty() {
        // A module root (`.../slice/mod.rs`): use the enclosing directory name.
        let without_file = &path[..path.len() - file.len()];
        let dir = without_file.trim_end_matches('/').rsplit('/').next()?;
        if dir.is_empty() {
            return None;
        }
        return Some(dir.to_string());
    }
    Some(stem.to_string())
}

/// Extract the markdown text from a `textDocument/hover` result value. rust-
/// analyzer returns `{ "contents": { "kind": "markdown"|"plaintext", "value":
/// <str> } }`; older shapes (`MarkedString` as a bare string, or an array) are
/// tolerated. `None` when there is no string value (null hover / unexpected
/// shape).
fn hover_markdown(result: &Value) -> Option<String> {
    let contents = result.get("contents")?;
    match contents {
        // MarkupContent { kind, value }.
        Value::Object(o) => o.get("value").and_then(|v| v.as_str()).map(str::to_string),
        // MarkedString as a bare string.
        Value::String(s) => Some(s.clone()),
        // MarkedString[]: concatenate any string/`value` members in order.
        Value::Array(a) => {
            let mut parts: Vec<String> = Vec::new();
            for item in a {
                match item {
                    Value::String(s) => parts.push(s.clone()),
                    Value::Object(o) => {
                        if let Some(v) = o.get("value").and_then(|v| v.as_str()) {
                            parts.push(v.to_string());
                        }
                    }
                    _ => {}
                }
            }
            if parts.is_empty() {
                None
            } else {
                Some(parts.join("\n"))
            }
        }
        _ => None,
    }
}

/// Parse the RECEIVER TYPE STEM from a `textDocument/hover` markdown body, or
/// `None` (refuse). This is the hover path of the panic-leaf type discriminator:
/// hover at a method-call ident renders the receiver type as the FIRST fenced
/// ```rust``` block (a bare type path, e.g. `core::result::Result`); the method
/// signature and docs follow in later blocks.
///
/// Extraction: take the first ```rust``` fenced block; its first non-empty line
/// is the receiver type. Strip a leading `&`/`&mut `/`*` (a borrowed receiver is
/// the value's identity for partial selection), drop everything from the first
/// `<` (the generic args), take the last `::`-separated path segment, and
/// lowercase it to the stem (`Result` -> `result`, `Option` -> `option`,
/// `Vec` -> `vec`, `str` -> `str`).
///
/// REFUSE (`None`) when:
///   - there is no ```rust``` block, or it is empty;
///   - the first line is a SIGNATURE or BINDING, not a bare type path: it begins
///     with a Rust keyword (`impl`/`fn`/`pub`/`let`/`const`/`static`/`use`/
///     `extern`/`struct`/`enum`/`trait`/`type`/`mod`/`where`) or contains a `(`
///     (a function signature). A hover that only renders the method signature
///     (not the receiver type) would otherwise yield a wrong head. (At the
///     method-ident position RA renders the receiver type first, so this is the
///     defensive floor, not the common path.)
///   - the resulting head is empty.
/// The head is NOT itself constrained to a known panic type here: the
/// `(type_stem, leaf)` mapping downstream is the gate that refuses an
/// out-of-set head. This keeps the parser a pure, total text function.
pub fn type_stem_from_hover_markdown(markdown: &str) -> Option<String> {
    // Find the first fenced ```rust ... ``` block.
    let block = first_rust_fenced_block(markdown)?;
    let first_line = block.lines().map(str::trim).find(|l| !l.is_empty())?;

    // Reject signature / binding blocks: only a bare type path is a receiver
    // type. A leading keyword or a `(` (function signature) means this block is
    // not the receiver type.
    const REJECT_PREFIXES: &[&str] = &[
        "impl ", "impl<", "fn ", "pub ", "let ", "const ", "static ", "use ", "extern ", "struct ",
        "enum ", "trait ", "type ", "mod ", "where ",
    ];
    if REJECT_PREFIXES.iter().any(|p| first_line.starts_with(p)) {
        return None;
    }
    if first_line.contains('(') {
        return None;
    }

    // Strip a borrow prefix (`&`, `&mut `, `*`): the partial selection is on the
    // pointee type's stem.
    let mut ty = first_line.trim();
    loop {
        let trimmed = ty
            .strip_prefix("&mut ")
            .or_else(|| ty.strip_prefix('&'))
            .or_else(|| ty.strip_prefix('*'))
            .map(str::trim_start);
        match trimmed {
            Some(t) => ty = t,
            None => break,
        }
    }

    // Drop generic args (everything from the first `<`).
    let ty = match ty.find('<') {
        Some(i) => &ty[..i],
        None => ty,
    };
    let ty = ty.trim();
    if ty.is_empty() {
        return None;
    }

    // Take the last `::`-separated path segment and lowercase it.
    let head = ty.rsplit("::").next()?.trim();
    if head.is_empty() || head.contains(char::is_whitespace) {
        return None;
    }
    Some(head.to_ascii_lowercase())
}

/// Return the body of the first fenced ```rust``` (or bare ```` ``` ````) block
/// in `markdown`, or `None`. We accept an explicit `rust` language tag and also
/// a bare fence (some hovers omit the tag); a fence tagged with another language
/// (e.g. ```json``` in docs) is skipped in favour of the first `rust`/untagged
/// one. The first such block at a method-ident hover is the receiver type.
fn first_rust_fenced_block(markdown: &str) -> Option<String> {
    let mut lines = markdown.lines().peekable();
    while let Some(line) = lines.next() {
        let trimmed = line.trim_start();
        if let Some(rest) = trimmed.strip_prefix("```") {
            let tag = rest.trim();
            let is_rust_or_bare = tag.is_empty() || tag.eq_ignore_ascii_case("rust");
            // Collect the block body up to the closing fence regardless, so we
            // can skip non-rust blocks correctly.
            let mut body: Vec<&str> = Vec::new();
            for inner in lines.by_ref() {
                if inner.trim_start().starts_with("```") {
                    break;
                }
                body.push(inner);
            }
            if is_rust_or_bare {
                return Some(body.join("\n"));
            }
            // Otherwise keep scanning for the next fence.
        }
    }
    None
}

/// The side-effect signal a resolved method's hover SIGNATURE carries: whether
/// it can mutate caller-observable state through its receiver or a `&mut`
/// parameter. This is the oracle datum the source-audit needs to turn a
/// side-effect-UNDETERMINED method call into a verdict:
///   - `Mutating`  -> `&mut self` or a `&mut`-typed parameter is present. The
///                    provable "mutation through &mut" effect -> REFUSE.
///   - `RefClean`  -> only `&self` / by-value `self` / shared-ref / value params.
///                    No receiver/param mutation -> consistent with the EUF value
///                    warrant. (The body could still do IO/panic, which a
///                    signature does not reveal -- so this CONFIRMS the warrant is
///                    not a `&mut` false-pass, it does not by itself prove total
///                    purity.)
///   - `Unknown`   -> no `fn` signature could be parsed from the hover.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignatureEffect {
    Mutating,
    RefClean,
    Unknown,
}

/// Parse the receiver/param mutability of a method from its rust-analyzer hover
/// markdown (the same hover the oracle already fetches). `&mut self` or any
/// `&mut`-typed parameter in the FIRST balanced `(...)` group of the `fn`
/// signature => `Mutating`; otherwise `RefClean`; no parseable signature =>
/// `Unknown`. The return type (after the matched `)`) is excluded, so a `&self`
/// method returning `&mut T` / `*mut T` is correctly `RefClean` (it hands out a
/// mutable view but does not itself mutate the receiver).
pub fn signature_effect_from_hover(markdown: &str) -> SignatureEffect {
    // RA's method hover has MULTIPLE ```rust blocks: the receiver TYPE block
    // (`core::option::Option`, no `fn`) then the impl/signature block
    // (`impl<T> Option<T>\npub const fn unwrap(self) -> T`). Scan every fenced
    // block for the one carrying the `fn` signature.
    for block in rust_fenced_blocks(markdown) {
        let joined: String = block.lines().map(str::trim).collect::<Vec<_>>().join(" ");
        let Some(fnpos) = joined.find("fn ") else {
            continue;
        };
        let Some(params) = first_balanced_parens(&joined[fnpos..]) else {
            continue;
        };
        return if params.contains("&mut ") {
            SignatureEffect::Mutating
        } else {
            SignatureEffect::RefClean
        };
    }
    SignatureEffect::Unknown
}

/// Every ```rust (or bare ```) fenced block body in `markdown`, in order.
fn rust_fenced_blocks(markdown: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut lines = markdown.lines();
    while let Some(line) = lines.next() {
        if let Some(rest) = line.trim_start().strip_prefix("```") {
            let tag = rest.trim();
            let is_rust_or_bare = tag.is_empty() || tag.eq_ignore_ascii_case("rust");
            let mut body: Vec<&str> = Vec::new();
            for inner in lines.by_ref() {
                if inner.trim_start().starts_with("```") {
                    break;
                }
                body.push(inner);
            }
            if is_rust_or_bare {
                out.push(body.join("\n"));
            }
        }
    }
    out
}

/// The content between the first `(` and its matching `)` in `s` (depth-balanced,
/// so nested parens in param types are handled), or None if unbalanced/absent.
fn first_balanced_parens(s: &str) -> Option<&str> {
    let start = s.find('(')?;
    let mut depth = 0usize;
    for (i, c) in s[start..].char_indices() {
        match c {
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    return Some(&s[start + 1..start + i]);
                }
            }
            _ => {}
        }
    }
    None
}

/// Map a definition-target file URI to its defining crate name, or `None` when
/// the path is outside the known roots (sysroot / cargo registry). A
/// workspace-local path is intentionally `None`: Tier 2a already resolves the
/// locally-determinable receivers, and Tier 2b must not invent a workspace-crate
/// key it cannot be sure of.
pub fn crate_from_uri(uri: &str) -> Option<String> {
    let path = uri.strip_prefix("file://").unwrap_or(uri);
    // sysroot rust-src: .../library/{core,alloc,std,...}/...
    if let Some(name) = segment_after(path, "/library/") {
        return Some(name);
    }
    // cargo registry: .../registry/src/<host>/<crate>-<version>/...
    if let Some(idx) = path.find("/registry/src/") {
        let rest = &path[idx + "/registry/src/".len()..];
        // skip the <host> segment
        let mut parts = rest.splitn(2, '/');
        let _host = parts.next();
        if let Some(after_host) = parts.next() {
            if let Some(pkg) = after_host.split('/').next() {
                // pkg is `<crate>-<version>`; strip the trailing `-<semver>`.
                if let Some(name) = strip_version_suffix(pkg) {
                    return Some(name);
                }
            }
        }
    }
    // git checkouts and path/workspace deps are not resolved here: refuse.
    None
}

/// Return the first path segment immediately after `marker`.
fn segment_after(path: &str, marker: &str) -> Option<String> {
    let idx = path.find(marker)?;
    let rest = &path[idx + marker.len()..];
    rest.split('/').next().map(|s| s.to_string())
}

/// `serde_json-1.0.117` -> `serde_json`; `base64-0.22.1` -> `base64`. Strips the
/// last `-<digit...>` component that begins a semver.
fn strip_version_suffix(pkg: &str) -> Option<String> {
    let idx = pkg.rfind('-')?;
    let (name, ver) = pkg.split_at(idx);
    // ver starts with '-'; the next char must be a digit for this to be a
    // version suffix.
    if ver.len() >= 2 && ver.as_bytes()[1].is_ascii_digit() && !name.is_empty() {
        Some(name.to_string())
    } else {
        Some(pkg.to_string())
    }
}

/// Collapse the standard-library facade crates to the single `std` label the
/// rust-std shim publishes its contracts under. `String::to_string` resolves to
/// `alloc`, `Option::unwrap` to `core`; both are re-exported through `std`, so
/// the collapse is sound. Any other crate name passes through unchanged.
pub fn normalize_crate(krate: &str) -> String {
    match krate {
        "core" | "alloc" | "std" | "proc_macro" => "std".to_string(),
        other => other.replace('-', "_"),
    }
}

/// Cheap content hash for in-session change detection (didOpen vs didChange).
/// Not content-addressing: it only needs to be stable within one process run to
/// notice that a file's on-disk bytes differ from what RA currently has open.
fn content_hash(bytes: &[u8]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    bytes.hash(&mut h);
    h.finish()
}

/// Build the file:// URI for an absolute path (LSP wants forward-slash URIs).
fn path_to_uri(path: &Path) -> String {
    let s = path.to_string_lossy();
    format!("file://{}", s)
}

/// Resolve a batch of queries grouped by file, reusing one warm oracle session.
/// Returns a map from (file, lsp_line, lsp_col) to the resolved crate. Queries
/// that refuse are simply absent from the map.
pub fn resolve_batch(
    workspace_root: &Path,
    queries: &[ResolveQuery],
) -> HashMap<(PathBuf, u32, u32), String> {
    let mut out = HashMap::new();
    if queries.is_empty() {
        return out;
    }
    let total = queries.len();
    info!(
        total_queries = total,
        workspace = %workspace_root.display(),
        "oracle: starting batch resolution"
    );
    let Some(mut oracle) = RaOracle::start(workspace_root) else {
        // start() returns None for two very different reasons. Report them
        // differently: opt-in-off is the DEFAULT and must stay quiet (a
        // default-disabled feature crying WARN on every mint is noise that
        // hides real problems); a missing/broken analyzer when the operator
        // *did* opt in is a genuine environmental fault worth a WARN. start()
        // already logs the specific cause (debug "oracle disabled" / warn
        // "binary not found"); here we classify the batch-level consequence.
        let opted_in = std::env::var("SUGAR_RESOLVE_ORACLE").unwrap_or_default() == "rust-analyzer";
        if opted_in {
            warn!(
                total_queries = total,
                "oracle: opted in but analyzer unavailable (binary missing or handshake failed); \
                 all {} method calls left to the syntactic tiers",
                total
            );
        } else {
            debug!(
                total_queries = total,
                "oracle: off (SUGAR_RESOLVE_ORACLE != rust-analyzer); \
                 {} method calls left to the syntactic tiers (Tier 1/2a)",
                total
            );
        }
        return out;
    };
    let mut not_ready_count = 0usize;
    let mut other_refused_count = 0usize;
    for q in queries {
        match oracle.resolve_crate_classified(q) {
            Ok(Some(krate)) => {
                out.insert((q.abs_path.clone(), q.lsp_line, q.lsp_col), krate);
            }
            Ok(None) => {
                other_refused_count += 1;
            }
            Err(()) => {
                not_ready_count += 1;
            }
        }
    }
    let resolved = out.len();
    let refused_count = not_ready_count + other_refused_count;
    info!(
        resolved = resolved,
        total = total,
        refused = refused_count,
        not_ready = not_ready_count,
        other_refused = other_refused_count,
        "oracle: batch complete: resolved {}/{} method calls ({} not-ready/churn, {} refused: no definite crate)",
        resolved,
        total,
        not_ready_count,
        other_refused_count
    );
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn crate_from_uri_maps_sysroot_library_to_crate() {
        let u = "file:///Users/x/.rustup/toolchains/stable/lib/rustlib/src/rust/library/alloc/src/string.rs";
        assert_eq!(crate_from_uri(u).as_deref(), Some("alloc"));
        let u2 = "file:///opt/rust/library/core/src/option.rs";
        assert_eq!(crate_from_uri(u2).as_deref(), Some("core"));
    }

    #[test]
    fn type_stem_distinguishes_option_result_slice() {
        // Option::unwrap and Result::unwrap differ ONLY by their defining file
        // stem; this is the disambiguator panic-freedom rides on.
        assert_eq!(
            type_stem_from_uri("file:///opt/rust/library/core/src/option.rs").as_deref(),
            Some("option")
        );
        assert_eq!(
            type_stem_from_uri("file:///opt/rust/library/core/src/result.rs").as_deref(),
            Some("result")
        );
        // A module root (`slice/mod.rs`) folds to the directory name, not `mod`.
        assert_eq!(
            type_stem_from_uri("file:///opt/rust/library/core/src/slice/mod.rs").as_deref(),
            Some("slice")
        );
        assert_eq!(
            type_stem_from_uri("file:///opt/rust/library/alloc/src/vec/mod.rs").as_deref(),
            Some("vec")
        );
    }

    #[test]
    fn type_stem_from_definition_result_single_and_ambiguous() {
        let single = json!([{ "uri": "file:///opt/rust/library/core/src/option.rs", "range": {} }]);
        assert_eq!(
            type_stem_from_definition_result(&single).as_deref(),
            Some("option")
        );
        // Two distinct stems -> refuse (no disambiguation).
        let ambiguous = json!([
            { "uri": "file:///opt/rust/library/core/src/option.rs", "range": {} },
            { "uri": "file:///opt/rust/library/core/src/result.rs", "range": {} }
        ]);
        assert_eq!(type_stem_from_definition_result(&ambiguous), None);
        // Empty / null -> refuse.
        assert_eq!(type_stem_from_definition_result(&json!([])), None);
        // LocationLink targetUri is read.
        let link = json!([{ "targetUri": "file:///opt/rust/library/core/src/result.rs", "targetRange": {} }]);
        assert_eq!(
            type_stem_from_definition_result(&link).as_deref(),
            Some("result")
        );
    }

    #[test]
    fn definition_files_from_definition_result_reads_location_and_locationlink() {
        let result = json!([
            { "uri": "file:///opt/rust/library/core/src/option.rs", "range": {} },
            { "targetUri": "file:///opt/rust/library/core/src/result.rs", "targetRange": {} }
        ]);
        let files = definition_files_from_definition_result(&result);
        assert_eq!(files.len(), 2);
        assert!(files
            .iter()
            .any(|path| path.ends_with("library/core/src/option.rs")));
        assert!(files
            .iter()
            .any(|path| path.ends_with("library/core/src/result.rs")));
    }

    // ---- hover type-head parser (the hover panic-leaf disambiguator) ----

    /// Build a method-ident hover markdown the way rust-analyzer renders it: the
    /// receiver type as the FIRST ```rust``` block, then the method signature.
    fn hover_md(receiver_type_block: &str, signature_block: &str) -> String {
        format!(
            "\n```rust\n{receiver_type_block}\n```\n\n```rust\n{signature_block}\n```\n\n---\n\ndocs..."
        )
    }

    #[test]
    fn signature_effect_classifies_receiver_and_param_mutability() {
        use super::{signature_effect_from_hover, SignatureEffect::*};
        let md = |sig: &str| format!("```rust\n{sig}\n```");
        // &mut self / &mut param -> Mutating (the "mutation through &mut" effect).
        for sig in [
            "pub fn push(&mut self, value: T)",
            "fn write_u64(&mut self, i: u64)",
            "pub fn swap(&mut self, a: usize, b: usize)",
            "fn replace(&mut self, src: T) -> T",
            "pub fn read(self, buf: &mut [u8]) -> usize",
        ] {
            assert_eq!(signature_effect_from_hover(&md(sig)), Mutating, "{sig}");
        }
        // &self / by-value self / shared-ref / value params -> RefClean. A &self
        // method returning &mut T is RefClean (it does not mutate the receiver).
        for sig in [
            "pub fn len(&self) -> usize",
            "pub const fn unwrap(self) -> T",
            "pub fn clone(&self) -> Self",
            "pub fn get(&self, i: usize) -> Option<&T>",
            "pub fn as_mut_ptr(&self) -> *mut T",
            "pub fn from_raw_parts(ptr: *const T, len: usize) -> Self",
        ] {
            assert_eq!(signature_effect_from_hover(&md(sig)), RefClean, "{sig}");
        }
        // No fn signature (bare receiver-type block) -> Unknown.
        assert_eq!(
            signature_effect_from_hover("```rust\nVec<u8>\n```"),
            Unknown
        );
        assert_eq!(signature_effect_from_hover("not markdown"), Unknown);

        // REAL rust-analyzer hover shape: a receiver-TYPE block FIRST (no fn),
        // then the impl/signature block. The parser must scan past the first
        // block to the fn signature (captured live: Option::unwrap, Vec::push).
        let unwrap_md = "```rust\ncore::option::Option\n```\n\n```rust\nimpl<T> Option<T>\npub const fn unwrap(self) -> T\n```\n\n---\n`T` = `i32`";
        assert_eq!(signature_effect_from_hover(unwrap_md), RefClean);
        let push_md = "```rust\nalloc::vec::Vec\n```\n\n```rust\nimpl<T, A> Vec<T, A>\npub fn push(&mut self, value: T)\n```";
        assert_eq!(signature_effect_from_hover(push_md), Mutating);
    }

    #[test]
    fn hover_type_head_parses_result_option_vec_str() {
        // The receiver-type block RA emits at a method-ident hover (captured from
        // a real session): a bare fully-qualified type path.
        assert_eq!(
            type_stem_from_hover_markdown(&hover_md(
                "core::result::Result",
                "impl<T, E> Result<T, E>\npub fn unwrap(self) -> T"
            ))
            .as_deref(),
            Some("result")
        );
        assert_eq!(
            type_stem_from_hover_markdown(&hover_md(
                "core::option::Option",
                "impl<T> Option<T>\npub const fn unwrap(self) -> T"
            ))
            .as_deref(),
            Some("option")
        );
        // `Vec<T>` head -> `vec` (generics stripped). A non-std-path bare type is
        // still parsed to its head; the downstream (type, leaf) map is the gate.
        assert_eq!(
            type_stem_from_hover_markdown("```rust\nVec<u32>\n```").as_deref(),
            Some("vec")
        );
        // `core::str` (no generic args) -> `str`.
        assert_eq!(
            type_stem_from_hover_markdown("```rust\ncore::str\n```").as_deref(),
            Some("str")
        );
        // A borrowed receiver `&str` -> the pointee stem `str`.
        assert_eq!(
            type_stem_from_hover_markdown("```rust\n&str\n```").as_deref(),
            Some("str")
        );
        assert_eq!(
            type_stem_from_hover_markdown("```rust\n&mut Vec<u8>\n```").as_deref(),
            Some("vec")
        );
    }

    #[test]
    fn hover_type_head_refuses_signature_binding_and_empty() {
        // A SIGNATURE-only block (no leading receiver-type block): refuse, never
        // mis-read a fn signature as the receiver type.
        assert_eq!(
            type_stem_from_hover_markdown(
                "```rust\npub fn unwrap(self) -> T\nwhere\n    E: fmt::Debug,\n```"
            ),
            None
        );
        // An `impl` header is a signature block, not a bare type: refuse.
        assert_eq!(
            type_stem_from_hover_markdown("```rust\nimpl<T, E> Result<T, E>\n```"),
            None
        );
        // A `let` binding render (hover at the receiver expression, not the
        // method): refuse — not a bare type path.
        assert_eq!(
            type_stem_from_hover_markdown("```rust\nlet opt: Option<u32>\n```"),
            None
        );
        // No ```rust``` block at all (e.g. an `extern crate serde_json` doc hover
        // that opens with prose): refuse.
        assert_eq!(
            type_stem_from_hover_markdown("# Serde JSON\n\nsome prose, no code fence"),
            None
        );
        // Empty markdown -> refuse.
        assert_eq!(type_stem_from_hover_markdown(""), None);
        // An empty ```rust``` block -> refuse.
        assert_eq!(type_stem_from_hover_markdown("```rust\n\n```"), None);
    }

    #[test]
    fn hover_type_head_skips_non_rust_fence_then_reads_rust() {
        // A leading ```json``` fence (serde docs) must be SKIPPED; the first
        // ```rust``` block is the receiver type.
        let md = "```json\n{ \"k\": 1 }\n```\n\n```rust\ncore::result::Result\n```";
        assert_eq!(type_stem_from_hover_markdown(md).as_deref(), Some("result"));
    }

    #[test]
    fn hover_markdown_extracts_value_from_shapes() {
        // MarkupContent { kind, value }.
        let mc = json!({ "contents": { "kind": "markdown", "value": "```rust\ncore::option::Option\n```" } });
        assert_eq!(
            hover_markdown(&mc)
                .and_then(|m| type_stem_from_hover_markdown(&m))
                .as_deref(),
            Some("option")
        );
        // Bare MarkedString.
        let bare = json!({ "contents": "```rust\nString\n```" });
        assert_eq!(
            hover_markdown(&bare)
                .and_then(|m| type_stem_from_hover_markdown(&m))
                .as_deref(),
            Some("string")
        );
        // Null hover -> no markdown.
        assert_eq!(hover_markdown(&json!({ "contents": Value::Null })), None);
        assert_eq!(hover_markdown(&json!({})), None);
    }

    #[test]
    fn crate_from_uri_maps_registry_crate() {
        let u = "file:///home/u/.cargo/registry/src/index.crates.io-6f17d22bba15001f/serde_json-1.0.117/src/lib.rs";
        assert_eq!(crate_from_uri(u).as_deref(), Some("serde_json"));
        let u2 = "file:///home/u/.cargo/registry/src/github.com-1ecc6299db9ec823/base64-0.22.1/src/lib.rs";
        assert_eq!(crate_from_uri(u2).as_deref(), Some("base64"));
    }

    #[test]
    fn crate_from_uri_refuses_workspace_local() {
        let u = "file:///Users/x/sugar/implementations/rust/sugar-cli/src/main.rs";
        assert_eq!(crate_from_uri(u), None);
    }

    #[test]
    fn normalize_collapses_std_facade() {
        assert_eq!(normalize_crate("core"), "std");
        assert_eq!(normalize_crate("alloc"), "std");
        assert_eq!(normalize_crate("std"), "std");
        assert_eq!(normalize_crate("serde_json"), "serde_json");
        assert_eq!(normalize_crate("my-dep"), "my_dep");
    }

    #[test]
    fn definition_result_refuses_on_empty() {
        assert_eq!(crate_from_definition_result(&json!([])), None);
        assert_eq!(crate_from_definition_result(&json!(null)), None);
    }

    #[test]
    fn definition_result_resolves_single_location() {
        let r = json!([{
            "uri": "file:///opt/rust/library/alloc/src/string.rs",
            "range": {}
        }]);
        assert_eq!(crate_from_definition_result(&r).as_deref(), Some("std"));
    }

    #[test]
    fn definition_result_refuses_ambiguous_crates() {
        let r = json!([
            { "uri": "file:///x/registry/src/h/foo-1.0.0/src/lib.rs", "range": {} },
            { "uri": "file:///x/registry/src/h/bar-2.0.0/src/lib.rs", "range": {} }
        ]);
        assert_eq!(crate_from_definition_result(&r), None);
    }

    #[test]
    fn definition_result_refuses_when_one_location_unmappable() {
        // One known crate, one workspace-local: must refuse, not trust the known.
        let r = json!([
            { "uri": "file:///opt/rust/library/core/src/option.rs", "range": {} },
            { "uri": "file:///ws/sugar/src/main.rs", "range": {} }
        ]);
        assert_eq!(crate_from_definition_result(&r), None);
    }

    #[test]
    fn locationlink_targeturi_is_read() {
        let r = json!([{
            "targetUri": "file:///opt/rust/library/alloc/src/vec/mod.rs",
            "targetRange": {},
            "targetSelectionRange": {}
        }]);
        assert_eq!(crate_from_definition_result(&r).as_deref(), Some("std"));
    }
}
