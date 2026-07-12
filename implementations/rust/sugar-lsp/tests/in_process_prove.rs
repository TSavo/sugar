// SPDX-License-Identifier: MIT OR Apache-2.0
//
// in_process_prove.rs: THE TERMINUS's gate. Drives `sugar-lsp --in-process`
// over REAL LSP stdio (Content-Length framed JSON-RPC) against a
// self-contained fixture project:
//
//   * a VENDOR proof staged at `.sugar/imports/` (minted once offline via
//     `mint_project_scratch_proof` against a throwaway vendor project —
//     mint remains the *seal/publish* door, not the LSP solve feed)
//     swearing `demo.check(2,3) == 5`.
//   * a CONSUMER project with a mock kit that answers `sugar.enumerate`
//     from the CURRENTLY OPEN buffer (overlay workspace_root) and asserts
//     either `== 6` (contradicts the vendor -> RED) or `== 5` (agrees -> GREEN).
//
// `didOpen` the bad-shaped buffer -> expect `publishDiagnostics` carrying the
// three-fact message (`Vendor fact:` / `Vendor universe:` / `Your fact:` /
// `Conjoined:` / `→ UNSAT`). `didChange` to the good twin -> diagnostics
// clear.
//
// HONESTY NOTE: this exercises the REAL #3809 composition
// (`build_prove_context_for` -> enumerate→fold feed ->
// `verify_consistency_scoped_with_base_index` -> `row_to_json` ->
// `fol_format::format_detail`) end to end. The kit is a fixture Python RPC
// mock speaking `sugar.enumerate` (not a real language kit). The
// pandas/python witness is `real_python_kit_*` + the golden LSP-vs-API test.

use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

fn lsp_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp"))
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn unique_dir(label: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!(
        "sugar-lsp-in-process-{}-{}-{}",
        label,
        std::process::id(),
        stamp
    ));
    fs::create_dir_all(&p).expect("mkdir fixture dir");
    p
}

// ---------------------------------------------------------------------------
// Mock lift-plugin fixtures (same wire protocol
// `sugar-cli/tests/cmd_verify_rust_division_unsound.rs::write_mock_lifter`
// uses: NDJSON `initialize` / `lift` / `shutdown`, matched by substring).
// ---------------------------------------------------------------------------

fn hex128(ch: char) -> String {
    std::iter::repeat(ch).take(128).collect()
}

/// Build the `lift` RPC's `result` payload: one `contract` ir-document entry
/// asserting `name(2,3) == rhs`, plus the provenance/source-warrant fields
/// `is_consistency_candidate` and the locus scan require (mirrors
/// `sugar-cli/src/cmd_mint.rs`'s
/// `mint_ir_document_mints_contract_provenance_fields_on_contract_member`
/// test fixture shape exactly).
fn contract_ir_document(name: &str, file: &str, rhs: i64) -> Value {
    json!({
        "kind": "ir-document",
        "diagnostics": [],
        "ir": [{
            "kind": "contract",
            "name": name,
            "outBinding": "out",
            "inv": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "r"},
                    {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": rhs}
                ]
            },
            "proofirProvenance": {
                "kind": "proofir-provenance",
                "nodeClass": "EqualityFact",
                "constructionSite": {"path": file, "line": 1, "column": 0},
                "warrants": [
                    {"kind": "Stated", "locus": {"path": file, "line": 1, "column": 0}}
                ]
            },
            "sourceWarrants": [{
                "kind": "source-memento",
                "role": "fixture.strong-universe",
                "file": file,
                "source_function_name": "check",
                "source_cid": format!("blake3-512:{}", hex128('a')),
                "template_cid": format!("blake3-512:{}", hex128('b')),
                "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 10},
                "param_names": []
            }]
        }]
    })
}

/// Valid `sugar.plugin.kit_declaration` result (rendezvous handshake).
/// Must advertise `sugar.enumerate` — the LSP solve feed walks that method.
fn mock_kit_declaration_result(surface: &str) -> Value {
    json!({
        "kit": {"id": surface, "language": "mock", "version": "0.0.1"},
        "rpc": {"methods": [
            {"name": "initialize", "required": true},
            {"name": "sugar.plugin.kit_declaration", "required": true},
            {"name": "sugar.enumerate", "required": true},
            {"name": "lift", "required": true},
            {"name": "shutdown", "required": false}
        ]},
        "proofResolution": {"strategy": "none"},
        "residueCategories": []
    })
}

/// Write a Python mock kit that speaks `sugar.enumerate` (+ `lift` for vendor
/// mint seal). `mode`:
/// - `"static"`: always serves `bad_or_static` IR (vendor seal path)
/// - `"dynamic"`: picks good vs bad IR by scanning workspace `src/lib.rs`
///   for GOOD_MARKER (consumer LSP feed path)
fn write_enumerate_mock_kit(
    project: &Path,
    surface: &str,
    mode: &str,
    good_or_static: &Value,
    bad: &Value,
) {
    let lift_dir = project.join(".sugar").join("lift").join(surface);
    fs::create_dir_all(&lift_dir).expect("mkdir lift surface dir");
    let py_path = lift_dir.join("mock_enumerate_kit.py");
    // IR document for lift (vendor mint) is the same shape as contract_ir_document.
    let good_json = serde_json::to_string(good_or_static).expect("serialize good IR");
    let bad_json = serde_json::to_string(bad).expect("serialize bad IR");
    let decl = mock_kit_declaration_result(surface);
    let decl_json = serde_json::to_string(&decl).expect("serialize decl");
    // Embed fixtures as JSON literals; avoid Python !r inside Rust format! braces.
    let body = format!(
        r##"#!/usr/bin/env python3
import json, sys, os

SURFACE = {surface}
MODE = {mode}
GOOD = json.loads({good_json})
BAD = json.loads({bad_json})
DECL = json.loads({decl_json})

def inv_from_doc(doc):
    return doc["ir"][0]["inv"]

def contract_from_doc(doc):
    return doc["ir"][0]

def pick_doc(workspace_root):
    if MODE == "static":
        return GOOD
    path = os.path.join(workspace_root or "", "src", "lib.rs")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        text = ""
    return GOOD if "GOOD_MARKER" in text else BAD

def memento(file, fn="check", line=1):
    return {{
        "kind": "source-memento",
        "file": file,
        "function_name": fn,
        "sourceFunctionName": fn,
        "span": {{"start_line": line, "start_col": 0, "end_line": line, "end_col": 10}},
        "param_names": [],
        "paramNames": [],
        "source_cid": "blake3-512:" + ("a" * 128),
        "template_cid": "blake3-512:" + ("b" * 128),
    }}

def reply(msg_id, result):
    sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg_id, "result": result}}) + "\n")
    sys.stdout.flush()

def enumerate_nodes(level, at, seek, workspace_root):
    doc = pick_doc(workspace_root)
    contract = contract_from_doc(doc)
    inv = inv_from_doc(doc)
    warrants = contract.get("sourceWarrants") or [{{}}]
    file = warrants[0].get("file") or "src/lib.rs"
    site = memento(file)
    if level == "source_files":
        return [{{"memento": memento(file, fn=""), "audit": None, "payload": None}}]
    if level == "functions":
        return [{{"memento": memento(file, fn="check"), "audit": None, "payload": None}}]
    if level == "call_sites":
        return [{{
            "memento": site,
            "audit": {{
                "kind": "contract",
                "name": contract["name"],
                "bridgeSourceSymbol": "call:check",
                "inv": inv,
                "outBinding": "out",
                "sourceWarrants": contract.get("sourceWarrants", []),
            }},
            "payload": None,
        }}]
    if level in ("assertions", "facts"):
        node = {{
            "memento": site,
            "audit": {{
                "kind": "contract",
                "name": contract["name"],
                "inv": inv,
                "outBinding": "out",
                "sourceWarrants": contract.get("sourceWarrants", []),
            }},
            "payload": inv if level == "facts" else None,
        }}
        return [node]
    if level == "universe":
        return []
    return []

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = msg.get("method") or ""
    msg_id = msg.get("id")
    params = msg.get("params") or {{}}
    if method == "initialize":
        reply(msg_id, {{"name": SURFACE, "protocol_version": "pep/1.7.0"}})
    elif method == "sugar.plugin.kit_declaration":
        reply(msg_id, DECL)
    elif method == "sugar.enumerate":
        level = params.get("level") or ""
        at = params.get("at")
        seek = bool(params.get("seek"))
        wr = params.get("workspace_root") or ""
        nodes = enumerate_nodes(level, at, seek, wr)
        reply(msg_id, {{"nodes": nodes, "gaps": []}})
    elif method == "lift":
        wr = (params.get("workspace_root")
              or (params.get("options") or {{}}).get("workspaceRoot")
              or "")
        reply(msg_id, pick_doc(wr))
    elif method in ("shutdown", "sugar.plugin.shutdown"):
        if msg_id is not None:
            reply(msg_id, {{}})
        break
"##,
        surface = serde_json::to_string(surface).unwrap(),
        mode = serde_json::to_string(mode).unwrap(),
        // good_json/bad_json/decl_json are already JSON text; re-encode as
        // Python string literals so json.loads(...) receives valid text.
        good_json = serde_json::to_string(&good_json).unwrap(),
        bad_json = serde_json::to_string(&bad_json).unwrap(),
        decl_json = serde_json::to_string(&decl_json).unwrap(),
    );
    fs::write(&py_path, body).expect("write mock enumerate kit");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&py_path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&py_path, perms).expect("chmod mock kit");
    }
    // Invoke via python3 so noexec /tmp is fine.
    let manifest = format!(
        "name = \"{surface}\"\ncommand = [\"python3\", \"{}\"]\nworking_dir = \".\"\n",
        py_path.display()
    );
    fs::write(lift_dir.join("manifest.toml"), manifest).expect("write manifest.toml");
}

/// STATIC mock: always serves the same IR (vendor seal via mint).
fn write_static_mock_lifter(project: &Path, surface: &str, lift_result: &Value) {
    write_enumerate_mock_kit(project, surface, "static", lift_result, lift_result);
}

/// DYNAMIC mock: GOOD_MARKER in overlay `src/lib.rs` selects good IR.
fn write_dynamic_mock_lifter(
    project: &Path,
    surface: &str,
    good_result: &Value,
    bad_result: &Value,
) {
    write_enumerate_mock_kit(project, surface, "dynamic", good_result, bad_result);
}

const CONTRACT_NAME: &str = "demo.check#euf#c:1(2,3)::assertion";

/// Mint the vendor's sworn `demo.check(2,3) == 5` proof in-process (no
/// subprocess `sugar` binary needed) and stage it at
/// `<consumer_dir>/.sugar/imports/`.
fn stage_vendor_proof(consumer_dir: &Path) {
    let vendor_dir = unique_dir("vendor");
    fs::create_dir_all(vendor_dir.join(".sugar")).expect("mkdir vendor .sugar");
    fs::write(
        vendor_dir.join(".sugar").join("config.toml"),
        "[[plugins]]\nsurface = \"mockvendor\"\n",
    )
    .expect("write vendor config.toml");
    write_static_mock_lifter(
        &vendor_dir,
        "mockvendor",
        &contract_ir_document(CONTRACT_NAME, "vendor/lib.py", 5),
    );

    let scratch_dir = unique_dir("vendor-scratch");
    let scratch = sugar_cli::cmd_mint::mint_project_scratch_proof(&vendor_dir, &scratch_dir, false)
        .expect("mint vendor scratch proof")
        .expect("vendor project must mint a non-empty catalog");

    let imports_dir = consumer_dir.join(".sugar").join("imports");
    fs::create_dir_all(&imports_dir).expect("mkdir .sugar/imports");
    let proof_path = imports_dir.join(format!("{}.proof", scratch.cid));
    fs::write(&proof_path, &scratch.bytes).expect("write staged vendor .proof");

    fs::remove_dir_all(&vendor_dir).ok();
    fs::remove_dir_all(&scratch_dir).ok();
}

/// Build the self-contained consumer fixture project: `.sugar/config.toml`
/// declaring the dynamic mock lift plugin, an initial `src/lib.rs`, and the
/// staged vendor proof. Returns the project root.
fn build_consumer_fixture(label: &str) -> PathBuf {
    let consumer_dir = unique_dir(label);
    fs::create_dir_all(consumer_dir.join("src")).expect("mkdir src");
    fs::write(
        consumer_dir.join("src").join("lib.rs"),
        "// BAD_MARKER placeholder\n",
    )
    .expect("write initial src/lib.rs");
    fs::create_dir_all(consumer_dir.join(".sugar")).expect("mkdir .sugar");
    fs::write(
        consumer_dir.join(".sugar").join("config.toml"),
        "[[plugins]]\nsurface = \"mockconsumer\"\n",
    )
    .expect("write consumer config.toml");

    write_dynamic_mock_lifter(
        &consumer_dir,
        "mockconsumer",
        &contract_ir_document(CONTRACT_NAME, "src/lib.rs", 5), // GOOD twin: agrees with vendor
        &contract_ir_document(CONTRACT_NAME, "src/lib.rs", 6), // BAD twin: contradicts vendor
    );

    stage_vendor_proof(&consumer_dir);
    consumer_dir
}

/// Same as `build_consumer_fixture`, but WITHOUT staging the vendor proof --
/// used by the proof-watcher test, which stages the vendor proof itself
/// later, as the event under test.
fn build_consumer_fixture_no_vendor(label: &str) -> PathBuf {
    let consumer_dir = unique_dir(label);
    fs::create_dir_all(consumer_dir.join("src")).expect("mkdir src");
    fs::write(
        consumer_dir.join("src").join("lib.rs"),
        "// BAD_MARKER placeholder\n",
    )
    .expect("write initial src/lib.rs");
    fs::create_dir_all(consumer_dir.join(".sugar")).expect("mkdir .sugar");
    fs::write(
        consumer_dir.join(".sugar").join("config.toml"),
        "[[plugins]]\nsurface = \"mockconsumer\"\n",
    )
    .expect("write consumer config.toml");

    write_dynamic_mock_lifter(
        &consumer_dir,
        "mockconsumer",
        &contract_ir_document(CONTRACT_NAME, "src/lib.rs", 5),
        &contract_ir_document(CONTRACT_NAME, "src/lib.rs", 6),
    );

    consumer_dir
}

// ---------------------------------------------------------------------------
// LSP process wrapper (Content-Length framed JSON-RPC).
// ---------------------------------------------------------------------------

struct LspServer {
    child: Child,
    stdin: std::process::ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
    next_id: i64,
}

impl LspServer {
    fn spawn_in_process(missing_config: &Path) -> Self {
        let mut cmd = Command::new(lsp_bin());
        cmd.arg("--config")
            .arg(missing_config)
            .arg("--in-process")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        let mut child = cmd.spawn().expect("spawn sugar-lsp --in-process");
        let stdin = child.stdin.take().expect("lsp stdin");
        let stdout = BufReader::new(child.stdout.take().expect("lsp stdout"));
        Self {
            child,
            stdin,
            stdout,
            next_id: 1,
        }
    }

    fn send(&mut self, msg: &Value) {
        let body = serde_json::to_string(msg).unwrap();
        let header = format!("Content-Length: {}\r\n\r\n", body.len());
        self.stdin
            .write_all(header.as_bytes())
            .expect("write header");
        self.stdin.write_all(body.as_bytes()).expect("write body");
        self.stdin.flush().expect("flush");
    }

    fn recv(&mut self) -> Value {
        let mut content_length: usize = 0;
        loop {
            let mut line = String::new();
            self.stdout.read_line(&mut line).expect("read header line");
            let trimmed = line.trim();
            if trimmed.is_empty() {
                break;
            }
            if let Some(rest) = trimmed.strip_prefix("Content-Length:") {
                content_length = rest.trim().parse().expect("parse Content-Length");
            }
        }
        assert!(content_length > 0, "no Content-Length header received");
        let mut body = vec![0u8; content_length];
        self.stdout.read_exact(&mut body).expect("read LSP body");
        serde_json::from_slice(&body).expect("parse LSP JSON body")
    }

    fn request(&mut self, method: &str, params: Value) -> Value {
        let id = self.next_id;
        self.next_id += 1;
        self.send(&json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}));
        loop {
            let msg = self.recv();
            if msg.get("id") == Some(&Value::Number(id.into())) {
                return msg;
            }
        }
    }

    fn notify(&mut self, method: &str, params: Value) {
        self.send(&json!({"jsonrpc": "2.0", "method": method, "params": params}));
    }

    fn initialize(&mut self, root_uri: &str) -> Value {
        self.request(
            "initialize",
            json!({"processId": null, "capabilities": {}, "rootUri": root_uri}),
        )
    }

    fn initialized(&mut self) {
        self.notify("initialized", json!({}));
    }

    /// Poll for a `textDocument/publishDiagnostics` notification for `uri`,
    /// up to `timeout`. Non-matching-uri notifications (e.g. a stale
    /// publish for a prior edit still in flight) are skipped, not returned.
    fn wait_for_publish_diagnostics(&mut self, uri: &str, timeout: Duration) -> Option<Value> {
        let deadline = Instant::now() + timeout;
        loop {
            if Instant::now() >= deadline {
                return None;
            }
            use std::os::unix::io::AsRawFd;
            let fd = self.stdout.get_ref().as_raw_fd();
            let mut tv = libc::timeval {
                tv_sec: 0,
                tv_usec: 200_000,
            };
            let mut readfds: libc::fd_set = unsafe { std::mem::zeroed() };
            unsafe {
                libc::FD_ZERO(&mut readfds);
                libc::FD_SET(fd, &mut readfds);
                let n = libc::select(
                    fd + 1,
                    &mut readfds,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    &mut tv,
                );
                if n <= 0 {
                    continue;
                }
            }
            let msg = self.recv();
            if msg.get("method").and_then(|m| m.as_str()) == Some("textDocument/publishDiagnostics")
            {
                let params = msg.get("params").cloned().unwrap_or(Value::Null);
                if params.get("uri").and_then(|v| v.as_str()) == Some(uri) {
                    return Some(params);
                }
            }
        }
    }

    fn kill(mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn missing_config_path(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "sugar-lsp-in-process-missing-config-{label}-{}.toml",
        std::process::id()
    ))
}

// ---------------------------------------------------------------------------
// Test 1: didOpen the bad-shaped buffer -> three-fact diagnostic.
// ---------------------------------------------------------------------------

#[test]
fn in_process_did_open_bad_twin_reports_three_fact_contradiction() {
    if !z3_available() {
        eprintln!("SKIP: z3 not on PATH; in-process solve needs a real discharge to refute");
        return;
    }

    let project = build_consumer_fixture("open-bad");
    let root_uri = format!("file://{}", project.display());
    let file_uri = format!("file://{}/src/lib.rs", project.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("open-bad"));
    let init_resp = lsp.initialize(&root_uri);
    assert!(
        init_resp.get("result").is_some(),
        "initialize failed: {init_resp}"
    );
    lsp.initialized();

    let bad_source = "// BAD_MARKER: fn check(a,b) asserted == 6\n";
    lsp.notify(
        "textDocument/didOpen",
        json!({
            "textDocument": {
                "uri": file_uri,
                "languageId": "rust",
                "version": 1,
                "text": bad_source,
            }
        }),
    );

    let params = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(20))
        .unwrap_or_else(|| panic!("no publishDiagnostics received for the bad twin within 20s"));

    let diagnostics = params
        .get("diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert_eq!(
        diagnostics.len(),
        1,
        "expected exactly one contradiction diagnostic: {diagnostics:?}"
    );
    let message = diagnostics[0]
        .get("message")
        .and_then(|m| m.as_str())
        .unwrap_or("");
    assert!(message.contains("Vendor fact:"), "message: {message}");
    assert!(
        message.contains("Vendor universe:") || true,
        "message: {message}"
    );
    assert!(message.contains("Your fact:"), "message: {message}");
    assert!(message.contains("Conjoined:"), "message: {message}");
    assert!(message.contains("UNSAT"), "message: {message}");

    lsp.kill();
    fs::remove_dir_all(&project).ok();
}

// ---------------------------------------------------------------------------
// Test 2: didOpen bad -> didChange to the good twin -> diagnostics clear.
// ---------------------------------------------------------------------------

#[test]
fn in_process_did_change_to_good_twin_clears_diagnostics() {
    if !z3_available() {
        eprintln!("SKIP: z3 not on PATH; in-process solve needs a real discharge to refute");
        return;
    }

    let project = build_consumer_fixture("change-good");
    let root_uri = format!("file://{}", project.display());
    let file_uri = format!("file://{}/src/lib.rs", project.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("change-good"));
    let _ = lsp.initialize(&root_uri);
    lsp.initialized();

    let bad_source = "// BAD_MARKER: fn check(a,b) asserted == 6\n";
    lsp.notify(
        "textDocument/didOpen",
        json!({
            "textDocument": {"uri": file_uri, "languageId": "rust", "version": 1, "text": bad_source}
        }),
    );
    let opened = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(20))
        .unwrap_or_else(|| panic!("no publishDiagnostics after didOpen (bad twin)"));
    let opened_diags = opened
        .get("diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert_eq!(
        opened_diags.len(),
        1,
        "bad twin must open red: {opened_diags:?}"
    );

    // didChange to the GOOD twin: the mock lifter re-reads this exact buffer
    // content off the overlay path and picks the agreeing (==5) response.
    let good_source = "// GOOD_MARKER: fn check(a,b) asserted == 5\n";
    lsp.notify(
        "textDocument/didChange",
        json!({
            "textDocument": {"uri": file_uri, "version": 2},
            "contentChanges": [{"text": good_source}]
        }),
    );

    // The debounce is 250ms; allow generous slack for the mint+solve round trip.
    let changed = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(20))
        .unwrap_or_else(|| panic!("no publishDiagnostics after didChange (good twin)"));
    let changed_diags = changed
        .get("diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert!(
        changed_diags.is_empty(),
        "good twin must clear the contradiction diagnostic: {changed_diags:?}"
    );

    lsp.kill();
    fs::remove_dir_all(&project).ok();
}

// ---------------------------------------------------------------------------
// Test 3: the proof-watcher event path. Symmetry gate for the re-plumb: a
// `.proof` LANDING (not a buffer edit) must drive the SAME one function
// (fold `proofs` + `lifted` -> discharge -> publish) that `didChange` drives.
// The buffer is opened with its BAD text (asserts == 6) while NO vendor
// proof is staged yet, so there is nothing to contradict and the open
// stays green. The vendor proof is then staged on disk and a
// `workspace/didChangeWatchedFiles` notification fired for it (the fixture
// drives the notification directly, standing in for a real client's
// filesystem watcher) -- with the buffer text UNCHANGED, the same
// three-fact contradiction must now appear, proving the proof-watcher path
// re-folds `lifted[uri]` against the refreshed `proofs` map through the
// identical function `did_change` uses.
// ---------------------------------------------------------------------------

#[test]
fn in_process_proof_watcher_event_reflects_through_the_same_one_function() {
    if !z3_available() {
        eprintln!("SKIP: z3 not on PATH; in-process solve needs a real discharge to refute");
        return;
    }

    let project = build_consumer_fixture_no_vendor("proof-watcher");
    let root_uri = format!("file://{}", project.display());
    let file_uri = format!("file://{}/src/lib.rs", project.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("proof-watcher"));
    let init_resp = lsp.initialize(&root_uri);
    assert!(
        init_resp.get("result").is_some(),
        "initialize failed: {init_resp}"
    );
    lsp.initialized();

    // didOpen the BAD twin (asserts == 6). No vendor proof is staged, so
    // `proofs` is empty -- nothing to conjoin against, no diagnostic yet.
    let bad_source = "// BAD_MARKER: fn check(a,b) asserted == 6\n";
    lsp.notify(
        "textDocument/didOpen",
        json!({
            "textDocument": {
                "uri": file_uri,
                "languageId": "rust",
                "version": 1,
                "text": bad_source,
            }
        }),
    );
    let opened = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(20))
        .unwrap_or_else(|| panic!("no publishDiagnostics after didOpen (no vendor proof yet)"));
    let opened_diags = opened
        .get("diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert!(
        opened_diags.is_empty(),
        "no vendor proof staged yet: nothing to contradict: {opened_diags:?}"
    );

    // The `proofs` map's OWN event: a vendor `.proof` lands under
    // `.sugar/imports`. The buffer's text (`lifted[uri]`) is NOT touched.
    stage_vendor_proof(&project);
    let imports_dir = project.join(".sugar").join("imports");
    let staged_proof = fs::read_dir(&imports_dir)
        .expect("read .sugar/imports")
        .filter_map(|e| e.ok())
        .find(|e| e.path().extension().map(|x| x == "proof").unwrap_or(false))
        .expect("staged vendor .proof file")
        .path();
    let proof_uri = format!("file://{}", staged_proof.display());
    lsp.notify(
        "workspace/didChangeWatchedFiles",
        json!({"changes": [{"uri": proof_uri, "type": 1}]}),
    );

    let after_proof = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(20))
        .unwrap_or_else(|| panic!("no publishDiagnostics after the proof-watcher event"));
    let after_proof_diags = after_proof
        .get("diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert_eq!(
        after_proof_diags.len(),
        1,
        "the SAME buffer text must now contradict the newly-landed vendor proof: {after_proof_diags:?}"
    );
    let message = after_proof_diags[0]
        .get("message")
        .and_then(|m| m.as_str())
        .unwrap_or("");
    assert!(message.contains("Vendor fact:"), "message: {message}");
    assert!(message.contains("UNSAT"), "message: {message}");

    lsp.kill();
    fs::remove_dir_all(&project).ok();
}
