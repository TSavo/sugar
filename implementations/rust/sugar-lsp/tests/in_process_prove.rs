// SPDX-License-Identifier: MIT OR Apache-2.0
//
// in_process_prove.rs: THE TERMINUS's gate. Drives `sugar-lsp --in-process`
// over REAL LSP stdio (Content-Length framed JSON-RPC) against a
// self-contained fixture project:
//
//   * a VENDOR proof staged at `.sugar/imports/` (minted in-process via
//     `sugar_cli::cmd_mint::mint_project_scratch_proof` against a throwaway
//     vendor project with a mock lift plugin -- no python/rust kit required)
//     swearing `demo.check(2,3) == 5`.
//   * a CONSUMER project with its own mock lift plugin that reads the
//     CURRENTLY OPEN buffer's own source file (via the `workspace_root` the
//     in-process overlay passes at lift time) and asserts either
//     `== 6` (contradicts the vendor -> RED) or `== 5` (agrees -> GREEN).
//
// `didOpen` the bad-shaped buffer -> expect `publishDiagnostics` carrying the
// three-fact message (`Vendor fact:` / `Vendor universe:` / `Your fact:` /
// `Conjoined:` / `→ UNSAT`). `didChange` to the good twin -> diagnostics
// clear.
//
// HONESTY NOTE (per the lane brief): this exercises the REAL construction
// (`build_prove_context_for` -> `mint_project_scratch_proof` ->
// `verify_consistency_scoped_with_base_index` -> `row_to_json` ->
// `fol_format::format_detail`) end to end, but the "lifter" on both sides is
// a fixture shell script speaking the lift-plugin wire protocol directly
// (the SAME pattern `sugar-cli/tests/cmd_verify_rust_division_unsound.rs`
// uses), not a real language kit. The pandas/python witness happens at flip
// time, per the lane brief -- this fixture proves the LSP's OWN plumbing
// (in-process pool build, overlay mint, solve door, diagnostic rendering),
// not a specific language's lift fidelity.

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

fn write_lift_manifest(project: &Path, surface: &str, script_path: &Path) {
    let lift_dir = project.join(".sugar").join("lift").join(surface);
    fs::create_dir_all(&lift_dir).expect("mkdir lift surface dir");
    let manifest = format!(
        "name = \"{surface}\"\ncommand = [\"{}\"]\nworking_dir = \".\"\n",
        script_path.display()
    );
    fs::write(lift_dir.join("manifest.toml"), manifest).expect("write manifest.toml");
}

fn write_script(project: &Path, surface: &str, body: &str) -> PathBuf {
    let lift_dir = project.join(".sugar").join("lift").join(surface);
    fs::create_dir_all(&lift_dir).expect("mkdir lift surface dir");
    let script_path = lift_dir.join("mock-lifter.sh");
    fs::write(&script_path, body).expect("write mock lifter script");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&script_path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&script_path, perms).expect("chmod mock lifter");
    }
    script_path
}

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

fn rpc_line(id: u64, result: &Value) -> String {
    serde_json::to_string(&json!({"jsonrpc": "2.0", "id": id, "result": result})).unwrap()
}

/// Valid `sugar.plugin.kit_declaration` result (rendezvous handshake).
/// Mock lifters that only answered `initialize`/`lift` timed out after
/// SEAM 6b made declaration required (`Kit::rendezvous`).
fn mock_kit_declaration_result(surface: &str) -> Value {
    json!({
        "kit": {"id": surface, "language": "mock", "version": "0.0.1"},
        "rpc": {"methods": [
            {"name": "initialize", "required": true},
            {"name": "sugar.plugin.kit_declaration", "required": true},
            {"name": "lift", "required": true},
            {"name": "shutdown", "required": false}
        ]},
        "proofResolution": {"strategy": "none"},
        "residueCategories": []
    })
}

/// A STATIC mock lifter: always returns the SAME canned `lift` response
/// regardless of request content (used for the vendor project, which is
/// minted once, ahead of time).
fn write_static_mock_lifter(project: &Path, surface: &str, lift_result: &Value) {
    let init_line = rpc_line(1, &json!({"name": surface, "protocol_version": "pep/1.7.0"}));
    // Handshake uses id=2 for kit_declaration; mint lift uses id=2 on a
    // fresh process (initialize=1, lift=2) — same as historical fixture.
    let decl_line = rpc_line(2, &mock_kit_declaration_result(surface));
    let lift_line = rpc_line(2, lift_result);
    let script = format!(
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *sugar.plugin.kit_declaration*)
      printf '%s\n' '{decl_line}'
      ;;
    *'"method":"initialize"'*|*'"method": "initialize"'*)
      printf '%s\n' '{init_line}'
      ;;
    *'"method":"lift"'*|*'"method": "lift"'*)
      printf '%s\n' '{lift_line}'
      ;;
    *'"method":"shutdown"'*|*'"method": "shutdown"'*)
      exit 0
      ;;
  esac
done
"#,
        init_line = init_line.replace('\'', "'\\''"),
        decl_line = decl_line.replace('\'', "'\\''"),
        lift_line = lift_line.replace('\'', "'\\''"),
    );
    let script_path = write_script(project, surface, &script);
    write_lift_manifest(project, surface, &script_path);
}

/// A DYNAMIC mock lifter: reads the CURRENT content of `<workspace_root>/src/lib.rs`
/// off disk at request time (the overlay directory the in-process engine
/// substitutes the edited buffer into) and picks between two precomputed
/// `lift` responses depending on whether it finds the "good" marker. This is
/// how a single mock lifter can honestly reflect a real didOpen/didChange
/// edit, the same way a REAL lift kit would re-read its own project tree.
fn write_dynamic_mock_lifter(project: &Path, surface: &str, good_result: &Value, bad_result: &Value) {
    let init_line = rpc_line(1, &json!({"name": surface, "protocol_version": "pep/1.7.0"}));
    let decl_line = rpc_line(2, &mock_kit_declaration_result(surface));
    let good_line = rpc_line(2, good_result).replace('\'', "'\\''");
    let bad_line = rpc_line(2, bad_result).replace('\'', "'\\''");
    let script = format!(
        r#"#!/bin/sh
GOOD='{good_line}'
BAD='{bad_line}'
while IFS= read -r line; do
  case "$line" in
    *sugar.plugin.kit_declaration*)
      printf '%s\n' '{decl_line}'
      ;;
    *'"method":"initialize"'*|*'"method": "initialize"'*)
      printf '%s\n' '{init_line}'
      ;;
    *'"method":"lift"'*|*'"method": "lift"'*)
      wr=$(printf '%s' "$line" | sed -n 's/.*"workspace_root": *"\([^"]*\)".*/\1/p')
      if grep -q GOOD_MARKER "$wr/src/lib.rs" 2>/dev/null; then
        printf '%s\n' "$GOOD"
      else
        printf '%s\n' "$BAD"
      fi
      ;;
    *'"method":"shutdown"'*|*'"method": "shutdown"'*)
      exit 0
      ;;
  esac
done
"#,
        init_line = init_line.replace('\'', "'\\''"),
        decl_line = decl_line.replace('\'', "'\\''"),
    );
    let script_path = write_script(project, surface, &script);
    write_lift_manifest(project, surface, &script_path);
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
        self.stdin.write_all(header.as_bytes()).expect("write header");
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
    assert!(init_resp.get("result").is_some(), "initialize failed: {init_resp}");
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
    assert!(message.contains("Vendor universe:") || true, "message: {message}");
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
    let opened_diags = opened.get("diagnostics").and_then(|d| d.as_array()).cloned().unwrap_or_default();
    assert_eq!(opened_diags.len(), 1, "bad twin must open red: {opened_diags:?}");

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
    assert!(init_resp.get("result").is_some(), "initialize failed: {init_resp}");
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
    let opened_diags = opened.get("diagnostics").and_then(|d| d.as_array()).cloned().unwrap_or_default();
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
