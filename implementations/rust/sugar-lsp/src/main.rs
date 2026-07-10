// Sugar Language Server Protocol implementation.
//
// A language-agnostic LSP coordinator. Reads `.sugar/config.toml` to discover
// language plugins, routes each source file to the configured RPC plugin, and
// delegates verification to a configurable JSON-RPC backend.
//
// ## Modes of operation
//
// ### Per-plugin subprocess mode (default)
//
// Each language is handled by a per-kit plugin binary that speaks the
// `sugar-lsp-plugin/1` NDJSON protocol (initialize/parse/shutdown).
// The plugin returns `{annotations: [...]}` for each file.  Diagnostics
// come from the local `JsonRpcBackend` (e.g., `sugar verify`).
//
// Usage: sugar-lsp [--config <path>]
//
// To add a new language, create a binary that speaks `sugar-lsp-plugin/1`:
//   1. Receives `initialize` -> responds with name/version
//   2. Receives `parse` with {uri, text} -> responds with {annotations: [...]}
//   3. Receives `shutdown` -> exits
//
// Then add to `.sugar/config.toml`:
//   [[language]]
//   name = "mylang"
//   extensions = [".mylang"]
//   plugin = "sugar-lsp-mylang"
//
// ### In-process engine mode (opt-in, `--in-process`) -- THE TERMINUS, now the
// ### real editor path (the daemon this once routed through, `sugar-linkerd`,
// ### is retired; see #3844 which flipped the VS Code extension to this mode
// ### and the daemon-3-delete cut which removed the daemon crate entirely)
//
// `sugar-lsp --in-process` proves buffers IN-PROCESS by linking the engine
// directly (`prove_engine.rs`): no daemon RPC, no subprocess solver. On
// `initialize` the resident `ProveContext` (vendor-only base pool + solver
// plan/registry + IR-compiler registry + consistency index) is built once
// from the workspace root's `.sugar/imports`. On `didOpen`/`didSave` (and
// `didChange`, debounced 250ms), the edited buffer is staged into a
// SOURCE-OVERLAY and FEED via enumerate→fold
// (`sugar_compiler::feed_from_tree` / `pool_from_graph_with_speaker` — same
// composition as CLI `prove_from_kit`), then solved against the resident
// base index via THE ONE DOOR
// (`sugar_verifier::consistency::verify_consistency_scoped_with_base_index`
// — #3809 one feed + one solve; no parallel mint-as-feed).
// Non-discharged consistency rows become `publishDiagnostics` entries whose
// message is the three-fact block (vendor fact / vendor universe / your
// fact / conjoined / the fix), rendered by `fol_format.rs` (a port of
// `editors/vscode-sugar/src/proveClient.ts`'s `formatDetail`/`prettyFol`).
// Hover repeats the same block; `codeAction` offers the vendor-proven-value
// Quick Fix (port of `extension.ts`'s `provenValueOf`/`SugarProveFixProvider`).
//
// This mode is mutually exclusive with per-plugin subprocess mode (opted
// into by flag; the VS Code extension runs this mode via a
// `LanguageClient` speaking stdio, per #3844).
//
// Usage: sugar-lsp --in-process [--config <path>]

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use tokio::sync::Mutex;
use tower_lsp::jsonrpc::Result;
use tower_lsp::lsp_types::*;
use tower_lsp::{Client, LanguageServer, LspService, Server};

mod backend;
mod config;
mod fol_format;
mod parser;
mod plugin;
mod prove_diagnostics;

use sugar_lsp::prove_engine;

use backend::JsonRpcBackend;
use config::LspConfig;
use parser::{Annotation, AnnotationKind, SourceAnnotations};
use plugin::LanguagePlugin;

/// Per-language plugin handle.
#[derive(Debug)]
enum LanguageHandle {
    External(Arc<std::sync::Mutex<LanguagePlugin>>),
}

struct SugarLanguageServer {
    client: Client,
    /// The JSON-RPC verification backend. `Some` in per-plugin mode; `None`
    /// in in-process mode (the resident `ProveContext` handles analysis; the
    /// backend is not needed and is not spawned).
    backend: Option<Arc<Mutex<JsonRpcBackend>>>,
    config: LspConfig,
    documents: Arc<Mutex<HashMap<Url, SourceAnnotations>>>,
    plugins: Arc<Mutex<HashMap<String, LanguageHandle>>>,
    /// THE TERMINUS: `--in-process` mode active. Mutually exclusive with
    /// per-plugin routing (see `update_document`'s dispatch).
    in_process: bool,
    /// THE `proofs` MAP (`.proofs: Map<Cid, ProofGraph>` in the re-plumb
    /// spec): the vendor-only base pool parsed from `.sugar/imports`, built
    /// once at `initialize` and refreshed whole-map when the `.proof` file
    /// watcher (`did_change_watched_files`, or the drift check every solve
    /// already runs) sees a manifest change. `ProveContext` bundles the
    /// parsed pool with the derived `ConsistencyIndex`/solver plan so a
    /// refresh recomputes both together (see `get_or_refresh_prove_ctx`).
    /// `None` until `initialize` runs (or if the workspace root has no
    /// resolvable project).
    prove_ctx: Arc<Mutex<Option<Arc<prove_engine::ProveContext>>>>,
    /// THE `lifted` MAP (`.lifted: Map<File, ProofGraph>` in the re-plumb
    /// spec): last-known raw buffer text per open uri, refreshed per-entry
    /// on `didOpen`/`didChange`/`didSave`. Feeds `solve_buffer`'s per-file
    /// mint. Also serves `code_action`'s `==` line lookup, and is the
    /// fallback when `didSave` omits the body.
    lifted: Arc<Mutex<HashMap<Url, String>>>,
    /// Per-uri stash of the last solve's row diagnostics, so `hover` and
    /// `code_action` can serve the SAME three-fact message / proven-value
    /// Quick Fix that `publish_diagnostics` just painted, without re-solving.
    prove_diagnostics: Arc<Mutex<HashMap<Url, Vec<prove_diagnostics::RowDiag>>>>,
    /// Monotonic per-uri edit counter for the `didChange` 250ms debounce: a
    /// spawned debounce task solves only if its captured generation is still
    /// the latest when the sleep completes, so a burst of keystrokes solves
    /// once, not once per keystroke.
    change_generation: Arc<Mutex<HashMap<Url, u64>>>,
    /// Mirror of the last `publishDiagnostics` payload sent per uri, across
    /// both modes (per-plugin, in-process). Exists so
    /// `textDocument/diagnostic` (the LSP 3.17 pull counterpart to push
    /// `publishDiagnostics`) has something honest to answer with instead of
    /// falling through to tower-lsp's default `Err(method_not_found())`: this
    /// server declares `diagnosticProvider` in `initialize`, and standard
    /// clients that support pull diagnostics (e.g. Neovim 0.10+) will call
    /// `textDocument/diagnostic` whenever that capability is present, so an
    /// unimplemented handler surfaces as `-32601: Method not found` in the
    /// client's log the moment such a client attaches.
    last_diagnostics: Arc<Mutex<HashMap<Url, Vec<Diagnostic>>>>,
}

/// Push `diagnostics` to the client via `publishDiagnostics` and mirror the
/// same payload into `cache` so a subsequent `textDocument/diagnostic` pull
/// for `uri` can answer from the last known state instead of erroring.
async fn publish_and_cache(
    client: &Client,
    cache: &Arc<Mutex<HashMap<Url, Vec<Diagnostic>>>>,
    uri: Url,
    diagnostics: Vec<Diagnostic>,
) {
    cache.lock().await.insert(uri.clone(), diagnostics.clone());
    client.publish_diagnostics(uri, diagnostics, None).await;
}

#[tower_lsp::async_trait]
impl LanguageServer for SugarLanguageServer {
    async fn initialize(&self, params: InitializeParams) -> Result<InitializeResult> {
        // Determine project root from workspace folders or root_uri
        let root = params
            .root_uri
            .as_ref()
            .map(|u| PathBuf::from(u.path()))
            .or_else(|| {
                params
                    .workspace_folders
                    .as_ref()
                    .and_then(|folders| folders.first().map(|f| PathBuf::from(f.uri.path())))
            })
            .unwrap_or_else(|| PathBuf::from("."));

        if self.in_process {
            // THE TERMINUS: build the resident `ProveContext` once, in-process
            // (loads `.sugar/imports`, builds plan/registry/compilers, indexes
            // the consistency candidates). Warm because the LSP process lives.
            let build_root = root.clone();
            let ctx = tokio::task::spawn_blocking(move || {
                prove_engine::build_prove_context_for(&build_root)
            })
            .await;
            match ctx {
                Ok(ctx) => {
                    let mut slot = self.prove_ctx.lock().await;
                    *slot = Some(Arc::new(ctx));
                }
                Err(e) => {
                    self.client
                        .log_message(
                            MessageType::ERROR,
                            format!("in-process ProveContext build panicked: {e}"),
                        )
                        .await;
                }
            }
        } else {
            // Initialize plugins from config (per-plugin subprocess mode only;
            // in-process mode routes elsewhere).
            self.init_plugins(&root).await;
        }

        Ok(InitializeResult {
            capabilities: ServerCapabilities {
                text_document_sync: Some(TextDocumentSyncCapability::Options(
                    TextDocumentSyncOptions {
                        open_close: Some(true),
                        change: Some(TextDocumentSyncKind::FULL),
                        save: Some(TextDocumentSyncSaveOptions::SaveOptions(SaveOptions {
                            include_text: Some(true),
                        })),
                        ..TextDocumentSyncOptions::default()
                    },
                )),
                hover_provider: Some(HoverProviderCapability::Simple(true)),
                diagnostic_provider: Some(DiagnosticServerCapabilities::Options(
                    DiagnosticOptions {
                        identifier: Some("sugar".to_string()),
                        inter_file_dependencies: true,
                        workspace_diagnostics: false,
                        work_done_progress_options: WorkDoneProgressOptions::default(),
                    },
                )),
                code_lens_provider: Some(CodeLensOptions {
                    resolve_provider: Some(false),
                }),
                code_action_provider: Some(CodeActionProviderCapability::Simple(true)),
                ..ServerCapabilities::default()
            },
            ..InitializeResult::default()
        })
    }

    async fn initialized(&self, _: InitializedParams) {
        self.client
            .log_message(MessageType::INFO, "Sugar LSP server initialized")
            .await;

        // THE `proofs` MAP's watcher: dynamically register interest in
        // `.proof` files so a real client forwards `did_change_watched_files`
        // whenever `.sugar/imports` gains/loses/updates a vendor proof.
        // Registration failure (a client without watcher support) is not
        // fatal -- the per-solve drift check in `get_or_refresh_prove_ctx`
        // still catches the same drift on the next buffer edit; this
        // registration only makes the refresh happen WITHOUT waiting for one.
        if self.in_process {
            let registration = Registration {
                id: "sugar-lsp-proof-watcher".to_string(),
                method: "workspace/didChangeWatchedFiles".to_string(),
                register_options: Some(
                    serde_json::to_value(DidChangeWatchedFilesRegistrationOptions {
                        watchers: vec![FileSystemWatcher {
                            glob_pattern: GlobPattern::String("**/*.proof".to_string()),
                            kind: None,
                        }],
                    })
                    .unwrap(),
                ),
            };
            if let Err(e) = self.client.register_capability(vec![registration]).await {
                self.client
                    .log_message(
                        MessageType::WARNING,
                        format!("proof-watcher registration failed (client may lack support): {e}"),
                    )
                    .await;
            }
        }
    }

    async fn shutdown(&self) -> Result<()> {
        // Shut down all external plugins
        let mut plugins = self.plugins.lock().await;
        for (_name, LanguageHandle::External(plugin)) in plugins.drain() {
            let _ = tokio::task::spawn_blocking(move || {
                if let Ok(mut p) = plugin.lock() {
                    let _ = p.shutdown();
                }
            });
        }
        Ok(())
    }

    async fn did_open(&self, params: DidOpenTextDocumentParams) {
        let uri = params.text_document.uri;
        let text = params.text_document.text;
        let lang_id = params.text_document.language_id;
        if self.in_process {
            self.in_process_open_or_save(uri, text).await;
            return;
        }
        self.update_document(uri, text, lang_id).await;
    }

    async fn did_change(&self, params: DidChangeTextDocumentParams) {
        let uri = params.text_document.uri;
        if self.in_process {
            // Full sync: take the last content change.
            if let Some(change) = params.content_changes.last() {
                self.in_process_debounced_change(uri, change.text.clone())
                    .await;
            }
            return;
        }
        let lang_id = self
            .documents
            .lock()
            .await
            .get(&uri)
            .map(|_| String::new())
            .unwrap_or_default();
        // Full sync: take the last content change
        if let Some(change) = params.content_changes.last() {
            self.update_document(uri, change.text.clone(), lang_id)
                .await;
        }
    }

    async fn did_save(&self, params: DidSaveTextDocumentParams) {
        if !self.in_process {
            return;
        }
        let uri = params.text_document.uri;
        let text = match params.text {
            Some(t) => t,
            // The client may omit the body on save; fall back to the last
            // buffer content we cached from didOpen/didChange.
            None => match self.lifted.lock().await.get(&uri).cloned() {
                Some(t) => t,
                None => return,
            },
        };
        self.in_process_open_or_save(uri, text).await;
    }

    /// The proof-watcher event: the `proofs` map's own entry point (a
    /// `.proof` landing/changing under `.sugar/imports`), symmetric with
    /// `did_change`'s `lifted` map entry point. Neither event kind gets a
    /// private code path: both end at `get_or_refresh_prove_ctx` (refresh
    /// `proofs`) followed by `in_process_solve_and_publish` (fold everything,
    /// discharge, publish) -- the IDENTICAL call `did_open`/`did_save`/
    /// `did_change` make. A `.proof` change cannot alter any open buffer's
    /// text, so this refreshes `proofs` once and re-folds for every
    /// currently-open uri in `lifted`, each against its own last-known text.
    async fn did_change_watched_files(&self, _params: DidChangeWatchedFilesParams) {
        if !self.in_process {
            return;
        }
        let open: Vec<(Url, String)> = self
            .lifted
            .lock()
            .await
            .iter()
            .map(|(u, t)| (u.clone(), t.clone()))
            .collect();
        for (uri, text) in open {
            self.in_process_open_or_save(uri, text).await;
        }
    }

    async fn did_close(&self, params: DidCloseTextDocumentParams) {
        let uri = params.text_document.uri;
        {
            let mut docs = self.documents.lock().await;
            docs.remove(&uri);
        }
        if self.in_process {
            self.lifted.lock().await.remove(&uri);
            self.prove_diagnostics.lock().await.remove(&uri);
            self.change_generation.lock().await.remove(&uri);
        }
        self.last_diagnostics.lock().await.remove(&uri);
        // Clear any published diagnostics for this file so the editor pane
        // goes clean.  This applies to per-plugin and in-process mode alike.
        self.client.publish_diagnostics(uri, vec![], None).await;
    }

    /// The LSP 3.17 pull counterpart to push `publishDiagnostics`. Answers
    /// from `last_diagnostics`, the mirror populated by every
    /// `publish_and_cache` call site across both modes. An empty vec is
    /// an honest "nothing known yet for this uri" (e.g. queried before the
    /// first solve/parse completes), not a stub.
    async fn diagnostic(
        &self,
        params: DocumentDiagnosticParams,
    ) -> Result<DocumentDiagnosticReportResult> {
        let uri = params.text_document.uri;
        let items = self
            .last_diagnostics
            .lock()
            .await
            .get(&uri)
            .cloned()
            .unwrap_or_default();
        Ok(DocumentDiagnosticReportResult::Report(
            DocumentDiagnosticReport::Full(RelatedFullDocumentDiagnosticReport {
                related_documents: None,
                full_document_diagnostic_report: FullDocumentDiagnosticReport {
                    result_id: None,
                    items,
                },
            }),
        ))
    }

    async fn hover(&self, params: HoverParams) -> Result<Option<Hover>> {
        let uri = params.text_document_position_params.text_document.uri;
        let position = params.text_document_position_params.position;

        if self.in_process {
            let diags = self.prove_diagnostics.lock().await;
            if let Some(rows) = diags.get(&uri) {
                for row in rows {
                    if is_in_range(position, row.range) {
                        return Ok(Some(Hover {
                            contents: HoverContents::Markup(MarkupContent {
                                kind: MarkupKind::Markdown,
                                value: format!("```\n{}\n```", row.message),
                            }),
                            range: Some(row.range),
                        }));
                    }
                }
            }
            return Ok(None);
        }

        let docs = self.documents.lock().await;
        let annotations = match docs.get(&uri) {
            Some(a) => a,
            None => return Ok(None),
        };

        for ann in &annotations.annotations {
            if is_in_range(position, ann.range) {
                return Ok(Some(Hover {
                    contents: HoverContents::Markup(MarkupContent {
                        kind: MarkupKind::Markdown,
                        value: format_hover(ann),
                    }),
                    range: Some(ann.range),
                }));
            }
        }

        Ok(None)
    }

    async fn code_lens(&self, params: CodeLensParams) -> Result<Option<Vec<CodeLens>>> {
        let uri = params.text_document.uri;
        let docs = self.documents.lock().await;
        let annotations = match docs.get(&uri) {
            Some(a) => a,
            None => return Ok(None),
        };

        let mut lenses = Vec::new();
        for ann in &annotations.annotations {
            if let Some(cid) = &ann.target_cid {
                lenses.push(CodeLens {
                    range: ann.range,
                    command: Some(Command {
                        title: format!("🔍 Verify: {}", cid),
                        command: "sugar.verify".to_string(),
                        arguments: Some(vec![
                            serde_json::json!(ann.function_name),
                            serde_json::json!(cid),
                        ]),
                    }),
                    data: None,
                });
            }
        }

        Ok(Some(lenses))
    }

    async fn code_action(&self, params: CodeActionParams) -> Result<Option<CodeActionResponse>> {
        let uri = params.text_document.uri;
        let range = params.range;

        if self.in_process {
            let mut actions = Vec::new();
            let diags = self.prove_diagnostics.lock().await;
            if let Some(rows) = diags.get(&uri) {
                let raw = self.lifted.lock().await;
                if let Some(text) = raw.get(&uri) {
                    for row in rows {
                        if !overlaps_range(range, row.range) {
                            continue;
                        }
                        let Some(proven) = &row.proven_value else {
                            continue;
                        };
                        let Some(line_text) = text.lines().nth(row.range.start.line as usize)
                        else {
                            continue;
                        };
                        // Replace everything after `==` (the asserted RHS) with
                        // the proven value. Byte-index `find` is safe here: `==`
                        // is ASCII, so the split point is a valid UTF-8 boundary
                        // regardless of what precedes/follows it.
                        let Some(eq) = line_text.find("==") else {
                            continue;
                        };
                        let rhs_start_col = line_text[..eq + 2].chars().count() as u32;
                        let rhs_end_col = line_text.chars().count() as u32;
                        let mut changes = HashMap::new();
                        changes.insert(
                            uri.clone(),
                            vec![TextEdit {
                                range: Range {
                                    start: Position {
                                        line: row.range.start.line,
                                        character: rhs_start_col,
                                    },
                                    end: Position {
                                        line: row.range.start.line,
                                        character: rhs_end_col,
                                    },
                                },
                                new_text: format!(" {proven}"),
                            }],
                        );
                        actions.push(CodeActionOrCommand::CodeAction(CodeAction {
                            title: format!("Replace with proven value: {proven}"),
                            kind: Some(CodeActionKind::QUICKFIX),
                            is_preferred: Some(true),
                            edit: Some(WorkspaceEdit {
                                changes: Some(changes),
                                ..WorkspaceEdit::default()
                            }),
                            ..CodeAction::default()
                        }));
                    }
                }
            }
            return Ok(Some(actions));
        }

        let docs = self.documents.lock().await;
        let annotations = match docs.get(&uri) {
            Some(a) => a,
            None => return Ok(None),
        };

        let mut actions = Vec::new();
        for ann in &annotations.annotations {
            if overlaps_range(range, ann.range) {
                if let Some(cid) = &ann.target_cid {
                    actions.push(CodeActionOrCommand::CodeAction(CodeAction {
                        title: format!("Re-verify against {}", cid),
                        kind: Some(CodeActionKind::QUICKFIX),
                        diagnostics: None,
                        edit: None,
                        command: Some(Command {
                            title: "Re-verify".to_string(),
                            command: "sugar.reverify".to_string(),
                            arguments: Some(vec![
                                serde_json::json!(ann.function_name),
                                serde_json::json!(cid),
                            ]),
                        }),
                        is_preferred: Some(false),
                        ..CodeAction::default()
                    }));
                }
            }
        }

        Ok(Some(actions))
    }
}

impl SugarLanguageServer {
    /// `didOpen` / `didSave`: solve immediately, no debounce.
    async fn in_process_open_or_save(&self, uri: Url, text: String) {
        in_process_solve_and_publish(
            &self.client,
            &self.prove_ctx,
            &self.lifted,
            &self.prove_diagnostics,
            &self.last_diagnostics,
            uri,
            text,
        )
        .await;
    }

    /// `didChange`: cache the buffer immediately (so a save/hover mid-debounce
    /// sees the latest text), then solve after a 250ms debounce window --
    /// only if no NEWER change has landed for this `uri` while we slept.
    async fn in_process_debounced_change(&self, uri: Url, text: String) {
        self.lifted
            .lock()
            .await
            .insert(uri.clone(), text.clone());

        let generation = {
            let mut gens = self.change_generation.lock().await;
            let next = gens.get(&uri).copied().unwrap_or(0) + 1;
            gens.insert(uri.clone(), next);
            next
        };

        let client = self.client.clone();
        let prove_ctx = self.prove_ctx.clone();
        let lifted = self.lifted.clone();
        let prove_diagnostics = self.prove_diagnostics.clone();
        let change_generation = self.change_generation.clone();
        let last_diagnostics = self.last_diagnostics.clone();
        let uri_for_task = uri.clone();

        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
            let still_latest = change_generation.lock().await.get(&uri_for_task).copied()
                == Some(generation);
            if !still_latest {
                // A newer edit landed during the debounce window; that task
                // (or a didSave) will solve instead.
                return;
            }
            in_process_solve_and_publish(
                &client,
                &prove_ctx,
                &lifted,
                &prove_diagnostics,
                &last_diagnostics,
                uri_for_task,
                text,
            )
            .await;
        });
    }

    async fn init_plugins(&self, project_root: &std::path::Path) {
        let mut plugins = self.plugins.lock().await;
        for lang in &self.config.language {
            if let Some(plugin_name) = &lang.plugin {
                match plugin::load_plugin(project_root, lang) {
                    Ok(p) => {
                        plugins.insert(
                            lang.name.clone(),
                            LanguageHandle::External(Arc::new(std::sync::Mutex::new(p))),
                        );
                    }
                    Err(e) => {
                        self.client
                            .log_message(
                                MessageType::WARNING,
                                format!("Failed to load language plugin `{}`: {}", plugin_name, e),
                            )
                            .await;
                    }
                }
            } else {
                self.client
                    .log_message(
                        MessageType::WARNING,
                        format!(
                            "Language `{}` has no LSP plugin configured; skipping",
                            lang.name
                        ),
                    )
                    .await;
            }
        }
    }

    async fn update_document(&self, uri: Url, text: String, _lang_id: String) {
        // --- Per-plugin subprocess mode (default) ---

        // Determine language from file extension
        let path = PathBuf::from(uri.path());
        let lang_config = self.config.for_path(&path);

        let annotations = match lang_config {
            Some(cfg) => {
                let plugins = self.plugins.lock().await;
                match plugins.get(&cfg.name) {
                    Some(LanguageHandle::External(plugin)) => {
                        let plugin = plugin.clone();
                        let uri_str = uri.to_string();
                        // Run blocking plugin call in spawn_blocking
                        match tokio::task::spawn_blocking(move || {
                            let mut p = plugin.lock().unwrap();
                            p.parse(&uri_str, &text)
                        })
                        .await
                        {
                            Ok(Ok(anns)) => anns,
                            Ok(Err(e)) => {
                                self.client
                                    .log_message(
                                        MessageType::ERROR,
                                        format!("Plugin parse error: {}", e),
                                    )
                                    .await;
                                SourceAnnotations {
                                    annotations: Vec::new(),
                                }
                            }
                            Err(e) => {
                                self.client
                                    .log_message(
                                        MessageType::ERROR,
                                        format!("Plugin task panicked: {}", e),
                                    )
                                    .await;
                                SourceAnnotations {
                                    annotations: Vec::new(),
                                }
                            }
                        }
                    }
                    None => {
                        self.client
                            .log_message(
                                MessageType::WARNING,
                                format!("No plugin loaded for language `{}`", cfg.name),
                            )
                            .await;
                        SourceAnnotations {
                            annotations: Vec::new(),
                        }
                    }
                }
            }
            None => SourceAnnotations {
                annotations: Vec::new(),
            },
        };

        // Store parsed annotations
        {
            let mut docs = self.documents.lock().await;
            docs.insert(uri.clone(), annotations.clone());
        }

        // Queue verification for annotations with target CIDs (per-plugin mode only).
        if let Some(backend) = &self.backend {
            for ann in &annotations.annotations {
                if let Some(cid) = &ann.target_cid {
                    let backend = backend.clone();
                    let client = self.client.clone();
                    let last_diagnostics = self.last_diagnostics.clone();
                    let uri_clone = uri.clone();
                    let function_name = ann.function_name.clone();
                    let cid = cid.clone();
                    let range = ann.range;

                    tokio::spawn(async move {
                        let mut backend = backend.lock().await;
                        match backend.verify(&function_name, &cid).await {
                            Ok(result) => {
                                let diagnostics = build_diagnostics(&result, range);
                                publish_and_cache(&client, &last_diagnostics, uri_clone, diagnostics)
                                    .await;
                            }
                            Err(e) => {
                                client
                                    .log_message(
                                        MessageType::ERROR,
                                        format!("Verification failed: {}", e),
                                    )
                                    .await;
                            }
                        }
                    });
                }
            }
        }
    }
}

fn is_in_range(position: Position, range: Range) -> bool {
    (position.line > range.start.line
        || (position.line == range.start.line && position.character >= range.start.character))
        && (position.line < range.end.line
            || (position.line == range.end.line && position.character <= range.end.character))
}

fn overlaps_range(a: Range, b: Range) -> bool {
    a.start.line <= b.end.line && a.end.line >= b.start.line
}

/// Return the resident `ProveContext`, rebuilding it in place first if
/// `.sugar/imports` has drifted since the last (re)build. `None` means
/// `initialize` never built one (no workspace root, or the build panicked).
/// A rebuild failure keeps serving the stale-but-present context rather
/// than regressing a working session.
async fn get_or_refresh_prove_ctx(
    prove_ctx: &Arc<Mutex<Option<Arc<prove_engine::ProveContext>>>>,
) -> Option<Arc<prove_engine::ProveContext>> {
    let mut guard = prove_ctx.lock().await;
    let current = guard.clone()?;
    let imports_root = current.project_root.join(".sugar").join("imports");
    let current_manifest = prove_engine::scan_proof_manifest(&imports_root);
    if current_manifest == current.proof_manifest {
        return Some(current);
    }
    let project_root = current.project_root.clone();
    let rebuilt =
        tokio::task::spawn_blocking(move || prove_engine::build_prove_context_for(&project_root))
            .await;
    match rebuilt {
        Ok(ctx) => {
            let arc = Arc::new(ctx);
            *guard = Some(arc.clone());
            Some(arc)
        }
        Err(_) => Some(current),
    }
}

/// THE TERMINUS: solve one buffer in-process against the resident base index
/// and publish diagnostics. Caches the raw buffer text (for `code_action`'s
/// line lookup) and the rendered `RowDiag`s (for `hover`) keyed by `uri`.
/// A free function (rather than a `&self` method) so it can be called both
/// synchronously (`didOpen`/`didSave`) and from a spawned debounce task
/// (`didChange`) without fighting the borrow checker over `&self`'s lifetime.
async fn in_process_solve_and_publish(
    client: &Client,
    prove_ctx: &Arc<Mutex<Option<Arc<prove_engine::ProveContext>>>>,
    lifted: &Arc<Mutex<HashMap<Url, String>>>,
    prove_diagnostics: &Arc<Mutex<HashMap<Url, Vec<prove_diagnostics::RowDiag>>>>,
    last_diagnostics: &Arc<Mutex<HashMap<Url, Vec<Diagnostic>>>>,
    uri: Url,
    text: String,
) {
    lifted.lock().await.insert(uri.clone(), text.clone());

    let Some(ctx) = get_or_refresh_prove_ctx(prove_ctx).await else {
        client
            .log_message(
                MessageType::WARNING,
                "in-process mode: no resident ProveContext (initialize never built one)",
            )
            .await;
        publish_and_cache(client, last_diagnostics, uri, vec![]).await;
        return;
    };

    let file = PathBuf::from(uri.path());
    let file_for_solve = file.clone();
    let outcome = tokio::task::spawn_blocking(move || {
        prove_engine::solve_buffer(&ctx, &file_for_solve, &text)
    })
    .await;

    let outcome = match outcome {
        Ok(o) => o,
        Err(e) => {
            client
                .log_message(MessageType::ERROR, format!("in-process solve panicked: {e}"))
                .await;
            return;
        }
    };

    if let Some(reason) = &outcome.degraded_reason {
        client
            .log_message(
                MessageType::INFO,
                format!("in-process solve degraded: {reason}"),
            )
            .await;
    }
    for line in &outcome.auto_logs {
        client
            .log_message(MessageType::INFO, format!("#4007 {line}"))
            .await;
    }

    let project_root = prove_ctx
        .lock()
        .await
        .as_ref()
        .map(|c| c.project_root.clone())
        .unwrap_or_else(|| PathBuf::from("."));
    let row_diags = prove_diagnostics::build_row_diags(&outcome.rows, &file, &project_root);

    let diagnostics: Vec<Diagnostic> = row_diags
        .iter()
        .map(|rd| Diagnostic {
            range: rd.range,
            severity: Some(DiagnosticSeverity::ERROR),
            code: Some(NumberOrString::String("sugar.prove.unsatisfied".to_string())),
            source: Some("sugar-prove".to_string()),
            message: rd.message.clone(),
            ..Diagnostic::default()
        })
        .collect();

    prove_diagnostics.lock().await.insert(uri.clone(), row_diags);
    publish_and_cache(client, last_diagnostics, uri, diagnostics).await;
}

fn format_hover(ann: &Annotation) -> String {
    match &ann.kind {
        AnnotationKind::Implement { target_cid } => {
            format!(
                "## Sugar Contract\n\n**Function:** `{}`\n**Kind:** implement\n**Target CID:** `{}`\n\nThis function is bound to the contract at the given CID. The framework will verify that the function body satisfies the contract's postcondition.",
                ann.function_name, target_cid
            )
        }
        AnnotationKind::Contract => {
            format!(
                "## Sugar Contract\n\n**Function:** `{}`\n**Kind:** contract\n\nThis function declares its own contract with native `#[requires]` / `#[ensures]` annotations.",
                ann.function_name
            )
        }
        AnnotationKind::Verify => {
            format!(
                "## Sugar Verify\n\n**Function:** `{}`\n**Kind:** verify\n\nThis function is marked for verification against its contract.",
                ann.function_name
            )
        }
    }
}

fn build_diagnostics(result: &backend::VerifyResult, range: Range) -> Vec<Diagnostic> {
    match result.status.as_str() {
        "verified" => vec![Diagnostic {
            range,
            severity: Some(DiagnosticSeverity::HINT),
            code: Some(NumberOrString::String("sugar.verified".to_string())),
            source: Some("sugar".to_string()),
            message: format!(
                "✅ Bridge verified: {} domain transfers",
                result.transfers.len()
            ),
            related_information: None,
            code_description: None,
            data: None,
            tags: None,
        }],
        "violation" => vec![Diagnostic {
            range,
            severity: Some(DiagnosticSeverity::ERROR),
            code: Some(NumberOrString::String("sugar.violation".to_string())),
            source: Some("sugar".to_string()),
            message: format!(
                "❌ Contract violation: {}",
                result.error.as_deref().unwrap_or("unknown")
            ),
            related_information: None,
            code_description: None,
            data: None,
            tags: None,
        }],
        _ => vec![Diagnostic {
            range,
            severity: Some(DiagnosticSeverity::WARNING),
            code: Some(NumberOrString::String("sugar.unknown".to_string())),
            source: Some("sugar".to_string()),
            message: format!("⚠️ Unknown verification status: {}", result.status),
            related_information: None,
            code_description: None,
            data: None,
            tags: None,
        }],
    }
}

#[tokio::main]
async fn main() {
    let mut config_path = ".sugar/config.toml".to_string();
    // THE TERMINUS: `--in-process` opts into proving buffers in-process
    // (see the module doc comment). Per-plugin subprocess mode is skipped
    // entirely when active.
    let mut in_process = false;

    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--config" => {
                if let Some(path) = args.next() {
                    config_path = path;
                }
            }
            "--in-process" => {
                in_process = true;
            }
            _ => {}
        }
    }

    // Read config
    let config = config::load_config(&config_path).unwrap_or_default();

    let backend_path = config.server.backend.clone();

    // Spawn backend in per-plugin mode.  In-process mode handles analysis
    // itself, so no backend binary is spawned.
    let backend: Option<Arc<Mutex<JsonRpcBackend>>> = if in_process {
        eprintln!("sugar-lsp: in-process engine mode active (no backend subprocess)");
        None
    } else {
        match JsonRpcBackend::spawn(&backend_path, &config.server.backend_args).await {
            Ok(b) => Some(Arc::new(Mutex::new(b))),
            Err(e) => {
                eprintln!("Failed to spawn backend '{}': {}", backend_path, e);
                std::process::exit(1);
            }
        }
    };

    // Start LSP
    let (stdin, stdout) = (tokio::io::stdin(), tokio::io::stdout());
    let (service, socket) = LspService::new(|client| SugarLanguageServer {
        client,
        backend,
        config,
        documents: Arc::new(Mutex::new(HashMap::new())),
        plugins: Arc::new(Mutex::new(HashMap::new())),
        // project_root removed (unused)
        in_process,
        prove_ctx: Arc::new(Mutex::new(None)),
        lifted: Arc::new(Mutex::new(HashMap::new())),
        prove_diagnostics: Arc::new(Mutex::new(HashMap::new())),
        change_generation: Arc::new(Mutex::new(HashMap::new())),
        last_diagnostics: Arc::new(Mutex::new(HashMap::new())),
    });

    Server::new(stdin, stdout, socket).serve(service).await;
}
