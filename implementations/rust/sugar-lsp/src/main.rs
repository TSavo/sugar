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
// ### Daemon-client mode (opt-in)
//
// When a daemon socket path is supplied (via `--daemon-socket <path>` CLI flag
// or `server.daemon_socket` in config.toml), `did_open` / `did_change` events
// are forwarded to `sugar-linkerd` as `parseFile` JSON-RPC calls instead of
// the per-plugin subprocess path.  The daemon owns the cross-kit cache; the LSP
// server is a thin adapter that converts `LinterError` diagnostics returned by
// the daemon to LSP `Diagnostic` objects and publishes them via
// `client.publish_diagnostics`.
//
// Per-plugin mode and daemon-client mode are mutually exclusive per-file. When
// daemon mode is active, the configured language name for the file is sent as
// the daemon `kitId`; the LSP coordinator does not infer language semantics.
//
// Usage: sugar-lsp --daemon-socket /run/user/1000/sugar/linkerd-<cid>.sock
//
// The daemon is the `sugar-linkerd` binary (LSP+linker step 2).  All five
// JSON-RPC methods (parseFile, getDiagnostics, projectStatus, flushCache,
// shutdown) are defined in `protocol/specs/2026-05-04-linker-daemon-protocol.md`.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Command as ProcessCommand, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::sync::Mutex;
use tower_lsp::jsonrpc::Result;
use tower_lsp::lsp_types::*;
use tower_lsp::{Client, LanguageServer, LspService, Server};

mod backend;
mod config;
mod parser;
mod plugin;

use backend::JsonRpcBackend;
use config::LspConfig;
use parser::{Annotation, AnnotationKind, SourceAnnotations};
use plugin::LanguagePlugin;

static NEXT_DAEMON_REQUEST_ID: AtomicU64 = AtomicU64::new(1);

/// Per-language plugin handle.
#[derive(Debug)]
enum LanguageHandle {
    External(Arc<std::sync::Mutex<LanguagePlugin>>),
}

// ---------------------------------------------------------------------------
// Daemon-client mode: wire types
// ---------------------------------------------------------------------------

/// A single diagnostic entry from the daemon's `parseFile` response.
///
/// Wire shape emitted by `sugar-linkerd` methods.rs:
/// ```json
/// {
///   "kind":              "linker-error",
///   "errorKind":         "unresolved-symbol" | "unprovable-obligation" | "implication-unprovable" | "implication-undecidable",
///   "targetSymbol":      "<string>",
///   "sourceContractCid": "<string>",
///   "reason":            "<string>",
///   "file":              "<string | null>",
///   "callSiteLocus":     {"file": "<string>", "line": 1, "column": 0}
/// }
/// ```
#[derive(Debug, serde::Deserialize)]
struct DaemonDiagnostic {
    /// Discriminator for the linker-error category; maps to LSP severity.
    #[serde(rename = "errorKind", default)]
    error_kind: String,
    /// The unresolved or obligation-violating symbol name.
    #[serde(rename = "targetSymbol", default)]
    target_symbol: String,
    /// Human-readable explanation from the linker.
    #[serde(default)]
    reason: String,
    /// Original kit-owned callsite locus. The LSP adapter only translates
    /// source coordinates; it does not interpret host-language syntax.
    #[serde(rename = "callSiteLocus", default)]
    call_site_locus: Option<serde_json::Value>,
}

/// Convert a single daemon `DaemonDiagnostic` into an LSP `Diagnostic`.
fn daemon_diag_to_lsp(d: &DaemonDiagnostic) -> Diagnostic {
    let range = locus_to_lsp_range(d.call_site_locus.as_ref());
    let severity = match d.error_kind.as_str() {
        "implication-unprovable" | "unprovable-obligation" => Some(DiagnosticSeverity::ERROR),
        "unresolved-symbol" | "implication-undecidable" => Some(DiagnosticSeverity::WARNING),
        _ => Some(DiagnosticSeverity::INFORMATION),
    };
    let message = match d.error_kind.as_str() {
        "implication-unprovable" | "unprovable-obligation" => format!(
            "cannot verify {}'s precondition; postcondition at call site does not establish it ({})",
            d.target_symbol, d.reason
        ),
        "implication-undecidable" => format!(
            "cannot prove {}'s precondition from this call site ({})",
            d.target_symbol, d.reason
        ),
        "unresolved-symbol" => format!(
            "cannot resolve {} against any kit in the project ({})",
            d.target_symbol, d.reason
        ),
        _ => d.reason.clone(),
    };
    Diagnostic {
        range,
        severity,
        code: Some(NumberOrString::String(
            diagnostic_code(&d.error_kind).to_string(),
        )),
        source: Some("sugar".to_string()),
        message,
        ..Default::default()
    }
}

fn file_start_range() -> Range {
    Range {
        start: Position {
            line: 0,
            character: 0,
        },
        end: Position {
            line: 0,
            character: 1,
        },
    }
}

fn locus_to_lsp_range(locus: Option<&serde_json::Value>) -> Range {
    let Some(locus) = locus else {
        return file_start_range();
    };

    let Some(line) = json_u32(locus, "line") else {
        return file_start_range();
    };
    let Some(column) = json_u32(locus, "column").or_else(|| json_u32(locus, "col")) else {
        return file_start_range();
    };

    let start_line = line.saturating_sub(1);
    let start = Position {
        line: start_line,
        character: column,
    };

    let end_line = json_u32(locus, "endLine")
        .map(|n| n.saturating_sub(1))
        .unwrap_or(start_line);
    let mut end_character = json_u32(locus, "endColumn")
        .or_else(|| json_u32(locus, "endCol"))
        .unwrap_or(column.saturating_add(1));
    if end_line == start_line && end_character <= column {
        end_character = column.saturating_add(1);
    }

    Range {
        start,
        end: Position {
            line: end_line,
            character: end_character,
        },
    }
}

fn json_u32(value: &serde_json::Value, key: &str) -> Option<u32> {
    value.get(key)?.as_u64().and_then(|n| u32::try_from(n).ok())
}

fn diagnostic_code(error_kind: &str) -> &'static str {
    match error_kind {
        "implication-unprovable" | "unprovable-obligation" => "sugar.lsp.implication_failed",
        "unresolved-symbol" => "sugar.lsp.unresolved_symbol",
        "implication-undecidable" => "sugar.lsp.unprovable_obligation",
        _ => "sugar.lsp.unprovable_obligation",
    }
}

fn kit_id_for_uri(config: &LspConfig, uri: &Url) -> Option<String> {
    let path = PathBuf::from(uri.path());
    config.for_path(&path).map(|lang| lang.name.clone())
}

fn connect_or_spawn_daemon(
    socket_path: &std::path::Path,
    project_cid: &str,
) -> std::io::Result<UnixStream> {
    if let Ok(stream) = UnixStream::connect(socket_path) {
        return Ok(stream);
    }

    let snap_path = {
        let mut p = socket_path.to_path_buf();
        let file_name = p
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "linkerd".to_string());
        p.set_file_name(format!("{file_name}.snap"));
        p
    };

    let _child = ProcessCommand::new("sugar-linkerd")
        .args([
            "--socket",
            &socket_path.to_string_lossy(),
            "--project-cid",
            project_cid,
            "--idle-timeout-ms",
            "300000",
            "--snapshot",
            &snap_path.to_string_lossy(),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| {
            std::io::Error::new(
                std::io::ErrorKind::Other,
                format!("failed to spawn sugar-linkerd: {e}"),
            )
        })?;

    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        std::thread::sleep(Duration::from_millis(50));
        if let Ok(stream) = UnixStream::connect(socket_path) {
            return Ok(stream);
        }
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!(
                    "sugar-linkerd did not bind socket at {} within 5 s",
                    socket_path.display()
                ),
            ));
        }
    }
}

fn send_parse_file_to_daemon(
    stream: &mut UnixStream,
    kit_id: &str,
    file: &str,
    source: &str,
    request_id: u64,
) -> std::io::Result<Vec<serde_json::Value>> {
    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "parseFile",
        "params": {
            "kitId": kit_id,
            "file": file,
            "source": source,
        }
    });

    let line = serde_json::to_string(&req).map_err(|e| {
        std::io::Error::new(std::io::ErrorKind::InvalidData, format!("json encode: {e}"))
    })?;

    writeln!(stream, "{line}")?;
    stream.flush()?;

    let mut buf_reader = BufReader::new(stream.try_clone()?);
    let mut resp_line = String::new();
    let n = buf_reader.read_line(&mut resp_line)?;
    if n == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::UnexpectedEof,
            "daemon closed connection without responding",
        ));
    }

    let resp: serde_json::Value = serde_json::from_str(resp_line.trim()).map_err(|e| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("json decode daemon response: {e}"),
        )
    })?;

    if let Some(err_obj) = resp.get("error") {
        return Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            format!("daemon returned error: {err_obj}"),
        ));
    }

    let diagnostics = resp
        .get("result")
        .and_then(|r| r.get("diagnostics"))
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();

    Ok(diagnostics)
}

#[derive(Debug)]
struct SugarLanguageServer {
    client: Client,
    /// The JSON-RPC verification backend.  `Some` in per-plugin mode; `None`
    /// in daemon-client mode (the daemon handles analysis; the backend is not
    /// needed and is not spawned).
    backend: Option<Arc<Mutex<JsonRpcBackend>>>,
    config: LspConfig,
    documents: Arc<Mutex<HashMap<Url, SourceAnnotations>>>,
    plugins: Arc<Mutex<HashMap<String, LanguageHandle>>>,
    /// Path to the sugar-linkerd Unix domain socket, if daemon-client mode
    /// is active.  `None` means per-plugin subprocess mode (the default).
    daemon_socket: Option<PathBuf>,
    /// Lazy-connected daemon stream, protected by a mutex so multiple async
    /// tasks can share the single persistent connection.  `None` until the
    /// first `did_open` / `did_change` event in daemon mode.
    daemon_stream: Arc<Mutex<Option<std::os::unix::net::UnixStream>>>,
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

        // Initialize plugins from config
        self.init_plugins(&root).await;

        Ok(InitializeResult {
            capabilities: ServerCapabilities {
                text_document_sync: Some(TextDocumentSyncCapability::Kind(
                    TextDocumentSyncKind::FULL,
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
        self.update_document(uri, text, lang_id).await;
    }

    async fn did_change(&self, params: DidChangeTextDocumentParams) {
        let uri = params.text_document.uri;
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

    async fn did_close(&self, params: DidCloseTextDocumentParams) {
        let uri = params.text_document.uri;
        {
            let mut docs = self.documents.lock().await;
            docs.remove(&uri);
        }
        // Clear any published diagnostics for this file so the editor pane
        // goes clean.  This applies to both per-plugin and daemon-client mode.
        self.client.publish_diagnostics(uri, vec![], None).await;
    }

    async fn hover(&self, params: HoverParams) -> Result<Option<Hover>> {
        let uri = params.text_document_position_params.text_document.uri;
        let position = params.text_document_position_params.position;

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
        // --- Daemon-client mode: route through sugar-linkerd ---
        if let Some(sock_path) = &self.daemon_socket {
            match kit_id_for_uri(&self.config, &uri) {
                Some(kit_id) => {
                    self.daemon_routed_parse(uri, text, sock_path.clone(), kit_id)
                        .await;
                }
                None => {
                    self.client
                        .log_message(
                            MessageType::WARNING,
                            format!("No configured LSP language kit for `{}`", uri.path()),
                        )
                        .await;
                    self.client.publish_diagnostics(uri, vec![], None).await;
                }
            }
            return;
        }

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
                    let uri_clone = uri.clone();
                    let function_name = ann.function_name.clone();
                    let cid = cid.clone();
                    let range = ann.range;

                    tokio::spawn(async move {
                        let mut backend = backend.lock().await;
                        match backend.verify(&function_name, &cid).await {
                            Ok(result) => {
                                let diagnostics = build_diagnostics(&result, range);
                                client
                                    .publish_diagnostics(uri_clone, diagnostics, None)
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

    /// Forward an open/change event to the sugar-linkerd daemon via
    /// `parseFile` JSON-RPC, convert the returned diagnostics, and publish
    /// them.  Lazily connects to the daemon socket on first call.
    ///
    /// Uses `tokio::task::spawn_blocking` because the daemon socket protocol
    /// is synchronous std I/O.
    async fn daemon_routed_parse(
        &self,
        uri: Url,
        text: String,
        sock_path: PathBuf,
        kit_id: String,
    ) {
        let daemon_stream = self.daemon_stream.clone();
        let client = self.client.clone();
        let file_path = uri.path().to_string();

        let result = tokio::task::spawn_blocking(move || {
            let mut guard = daemon_stream.blocking_lock();

            // Lazy connect / spawn.
            if guard.is_none() {
                match connect_or_spawn_daemon(&sock_path, "sugar-lsp") {
                    Ok(stream) => {
                        *guard = Some(stream);
                    }
                    Err(e) => {
                        return Err(format!(
                            "daemon-client: failed to connect to {}: {}",
                            sock_path.display(),
                            e
                        ));
                    }
                }
            }

            let stream = guard.as_mut().unwrap();
            let request_id = NEXT_DAEMON_REQUEST_ID.fetch_add(1, Ordering::Relaxed);
            send_parse_file_to_daemon(stream, &kit_id, &file_path, &text, request_id).map_err(|e| {
                // Connection may have dropped; clear so we reconnect next time.
                format!("daemon-client send_parse_file failed: {e}")
            })
        })
        .await;

        match result {
            Ok(Ok(raw_diags)) => {
                // Deserialize daemon JSON -> DaemonDiagnostic -> LSP Diagnostic.
                let diagnostics: Vec<Diagnostic> = raw_diags
                    .iter()
                    .filter_map(|v| serde_json::from_value::<DaemonDiagnostic>(v.clone()).ok())
                    .map(|d| daemon_diag_to_lsp(&d))
                    .collect();

                client.publish_diagnostics(uri, diagnostics, None).await;
            }
            Ok(Err(e)) => {
                // Clear the stale stream so the next call reconnects.
                {
                    let mut guard = self.daemon_stream.lock().await;
                    *guard = None;
                }
                client
                    .log_message(MessageType::WARNING, format!("sugar daemon: {}", e))
                    .await;
                // Publish empty diagnostics to clear any stale markers.
                client.publish_diagnostics(uri, vec![], None).await;
            }
            Err(join_err) => {
                client
                    .log_message(
                        MessageType::ERROR,
                        format!("sugar daemon task panicked: {}", join_err),
                    )
                    .await;
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

#[cfg(test)]
mod tests {
    use super::*;
    use tower_lsp::lsp_types::{DiagnosticSeverity, NumberOrString};

    fn make_diag(error_kind: &str, target_symbol: &str, reason: &str) -> DaemonDiagnostic {
        DaemonDiagnostic {
            error_kind: error_kind.to_string(),
            target_symbol: target_symbol.to_string(),
            reason: reason.to_string(),
            call_site_locus: None,
        }
    }

    fn make_diag_with_locus(
        error_kind: &str,
        target_symbol: &str,
        reason: &str,
        locus: serde_json::Value,
    ) -> DaemonDiagnostic {
        DaemonDiagnostic {
            error_kind: error_kind.to_string(),
            target_symbol: target_symbol.to_string(),
            reason: reason.to_string(),
            call_site_locus: Some(locus),
        }
    }

    #[test]
    fn callsite_locus_maps_to_lsp_range() {
        let d = make_diag_with_locus(
            "implication-unprovable",
            "checkPositive",
            "solver found a counterexample",
            serde_json::json!({
                "file": "/tmp/caller.rs",
                "line": 20,
                "column": 17,
            }),
        );
        let lsp = daemon_diag_to_lsp(&d);

        assert_eq!(lsp.severity, Some(DiagnosticSeverity::ERROR));
        assert_eq!(lsp.range.start.line, 19);
        assert_eq!(lsp.range.start.character, 17);
        assert_eq!(lsp.range.end.line, 19);
        assert_eq!(lsp.range.end.character, 18);
        assert_eq!(
            lsp.code,
            Some(NumberOrString::String(
                "sugar.lsp.implication_failed".to_string()
            ))
        );
    }

    #[test]
    fn unprovable_obligation_maps_to_error() {
        let d = make_diag(
            "unprovable-obligation",
            "MyTrait::verify",
            "postcondition not met",
        );
        let lsp = daemon_diag_to_lsp(&d);

        assert_eq!(lsp.severity, Some(DiagnosticSeverity::ERROR));
        assert_eq!(
            lsp.code,
            Some(NumberOrString::String(
                "sugar.lsp.implication_failed".to_string()
            ))
        );
        assert_eq!(lsp.source, Some("sugar".to_string()));
        assert!(
            lsp.message.contains("cannot verify"),
            "message should contain 'cannot verify', got: {}",
            lsp.message
        );
        assert!(
            lsp.message.contains("MyTrait::verify"),
            "message should contain symbol name, got: {}",
            lsp.message
        );
        assert!(
            lsp.message.contains("postcondition not met"),
            "message should contain reason, got: {}",
            lsp.message
        );
    }

    #[test]
    fn unresolved_symbol_maps_to_warning() {
        let d = make_diag("unresolved-symbol", "other::foo", "not found in any kit");
        let lsp = daemon_diag_to_lsp(&d);

        assert_eq!(lsp.severity, Some(DiagnosticSeverity::WARNING));
        assert_eq!(
            lsp.code,
            Some(NumberOrString::String(
                "sugar.lsp.unresolved_symbol".to_string()
            ))
        );
        assert_eq!(lsp.source, Some("sugar".to_string()));
        assert!(
            lsp.message.contains("cannot resolve"),
            "message should contain 'cannot resolve', got: {}",
            lsp.message
        );
        assert!(
            lsp.message.contains("other::foo"),
            "message should contain symbol name, got: {}",
            lsp.message
        );
    }

    #[test]
    fn unknown_error_kind_maps_to_information() {
        let d = make_diag("some-future-kind", "anything", "some reason");
        let lsp = daemon_diag_to_lsp(&d);

        assert_eq!(lsp.severity, Some(DiagnosticSeverity::INFORMATION));
        assert_eq!(
            lsp.code,
            Some(NumberOrString::String(
                "sugar.lsp.unprovable_obligation".to_string()
            ))
        );
        assert_eq!(lsp.source, Some("sugar".to_string()));
        assert_eq!(lsp.message, "some reason");
    }

    #[test]
    fn range_is_file_start_marker() {
        let d = make_diag("unprovable-obligation", "x", "y");
        let lsp = daemon_diag_to_lsp(&d);
        assert_eq!(lsp.range.start.line, 0);
        assert_eq!(lsp.range.start.character, 0);
        assert_eq!(lsp.range.end.line, 0);
        assert_eq!(lsp.range.end.character, 1);
    }

    #[test]
    fn daemon_kit_id_resolves_from_language_config() {
        let cfg = LspConfig {
            language: vec![config::LanguagePluginConfig {
                name: "go".to_string(),
                extensions: vec![".go".to_string()],
                plugin: None,
                plugin_args: Vec::new(),
            }],
            ..LspConfig::default()
        };

        let uri = Url::parse("file:///tmp/main.go").expect("valid file uri");
        assert_eq!(
            kit_id_for_uri(&cfg, &uri),
            Some("go".to_string()),
            "daemon routing must use configured language names, not a built-in rust default"
        );
    }

    #[test]
    fn daemon_kit_id_has_no_extension_fallback() {
        let cfg = LspConfig::default();
        let uri = Url::parse("file:///tmp/lib.rs").expect("valid file uri");

        assert_eq!(
            kit_id_for_uri(&cfg, &uri),
            None,
            "without config, even .rs has no implicit kit"
        );
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
    // CLI flag `--daemon-socket <path>` overrides config.server.daemon_socket.
    let mut daemon_socket_cli: Option<String> = None;

    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--config" => {
                if let Some(path) = args.next() {
                    config_path = path;
                }
            }
            "--daemon-socket" => {
                if let Some(path) = args.next() {
                    daemon_socket_cli = Some(path);
                }
            }
            _ => {}
        }
    }

    // Read config
    let config = config::load_config(&config_path).unwrap_or_default();

    // Resolve daemon socket: CLI flag wins over config file entry.
    let daemon_socket: Option<PathBuf> = daemon_socket_cli
        .as_deref()
        .or(config.server.daemon_socket.as_deref())
        .map(PathBuf::from);

    let backend_path = config.server.backend.clone();

    // Spawn backend in per-plugin mode.  In daemon-client mode, the daemon
    // handles all analysis so no backend binary is needed.
    let backend: Option<Arc<Mutex<JsonRpcBackend>>> = if daemon_socket.is_some() {
        eprintln!(
            "sugar-lsp: daemon-client mode active (socket: {})",
            daemon_socket.as_ref().unwrap().display()
        );
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
        daemon_socket,
        daemon_stream: Arc::new(Mutex::new(None)),
    });

    Server::new(stdin, stdout, socket).serve(service).await;
}
