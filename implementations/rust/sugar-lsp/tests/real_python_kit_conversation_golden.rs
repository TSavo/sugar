// SPDX-License-Identifier: MIT OR Apache-2.0
//
// real_python_kit_conversation_golden.rs: recomputable-artifact form of the
// PyCon demo conversation (epic #3809: "golden NDJSON conversation in the
// conformance corpus").
//
// Captures / replays the pure field-mapping LSP conversation driven by the
// REAL python/pandas kit (never the mock):
//
//   initialize → didOpen(lying) → publishDiagnostics(UNSAT)
//             → didChange(truth) → publishDiagnostics(clear)
//
// Golden: conformance/lsp/real_python_pandas_sum_conversation.ndjson
// DoD: live real-kit capture (normalized) is BYTE-IDENTICAL to the golden.
//
// Update (real RAN only):
//   SUGAR_LSP_GOLDEN_UPDATE=1 SUGAR_REAL_KIT_LSP_REQUIRED=1 \
//     cargo test -p sugar-lsp --test real_python_kit_conversation_golden \
//       real_python_kit_conversation_is_byte_identical_to_golden_ndjson \
//       -- --ignored --exact --nocapture

use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};

// ---------------------------------------------------------------------------
// Fixture constants (identical twins to real_python_kit_prove.rs)
// ---------------------------------------------------------------------------

const LYING_TWIN: &str = r#"import pandas as pd


def test_column_sum_contradiction():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6
    assert total == 7
"#;

const TRUTHFUL_TWIN: &str = r#"import pandas as pd


def test_column_sum_is_six():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6
"#;

const PROJECT_PLACEHOLDER: &str = "__PROJECT__";
const SOURCE_FILE: &str = "test_pandas_sum.py";

fn golden_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../conformance/lsp/real_python_pandas_sum_conversation.ndjson")
        .canonicalize()
        .unwrap_or_else(|_| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../conformance/lsp/real_python_pandas_sum_conversation.ndjson")
        })
}

fn lsp_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp"))
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .expect("resolve sugar repo root")
}

fn python_kit_src() -> PathBuf {
    repo_root().join("implementations/python/sugar-lift-py-tests/src")
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn python3() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(py) = std::env::var("PYTHON") {
        if !py.is_empty() {
            candidates.push(PathBuf::from(py));
        }
    }
    candidates.push(PathBuf::from("python3"));
    candidates.push(PathBuf::from("python"));
    for candidate in candidates {
        if let Ok(out) = Command::new(&candidate).arg("--version").output() {
            if out.status.success() {
                if candidate.is_absolute() {
                    return Some(candidate);
                }
                let name = candidate.to_string_lossy().to_string();
                if let Ok(which) = Command::new("which").arg(&name).output() {
                    if which.status.success() {
                        let p = String::from_utf8_lossy(&which.stdout).trim().to_string();
                        if !p.is_empty() {
                            return Some(PathBuf::from(p));
                        }
                    }
                }
                return Some(candidate);
            }
        }
    }
    None
}

fn real_kit_required() -> bool {
    fn truthy(v: &str) -> bool {
        matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    }
    std::env::var("SUGAR_REAL_KIT_LSP_REQUIRED")
        .map(|v| truthy(&v))
        .unwrap_or(false)
        || std::env::var("CI").map(|v| truthy(&v)).unwrap_or(false)
}

fn real_python_kit_available(py: &Path) -> Result<(), String> {
    let kit_src = python_kit_src();
    if !kit_src.join("sugar_lift_py_tests/lift_rpc.py").is_file() {
        return Err(format!(
            "python kit source missing at {}",
            kit_src.display()
        ));
    }
    let probe = Command::new(py)
        .env("PYTHONPATH", &kit_src)
        .args([
            "-c",
            "import pandas; import sugar_lift_py_tests.lift_rpc; print('ok')",
        ])
        .output()
        .map_err(|e| format!("failed to spawn {py:?}: {e}"))?;
    if !probe.status.success() {
        return Err(format!(
            "real kit import failed\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&probe.stdout),
            String::from_utf8_lossy(&probe.stderr),
        ));
    }
    Ok(())
}

fn require_real_kit_or_skip() -> Option<PathBuf> {
    let outcome: Result<PathBuf, String> = (|| {
        if !z3_available() {
            return Err("z3 not on PATH".into());
        }
        let py = python3().ok_or_else(|| "python3 not on PATH".to_string())?;
        real_python_kit_available(&py)?;
        Ok(py)
    })();
    match outcome {
        Ok(py) => {
            eprintln!("real-kit LSP: RAN (conversation golden)");
            Some(py)
        }
        Err(reason) => {
            eprintln!("real-kit LSP: SKIPPED: {reason}");
            if real_kit_required() {
                panic!(
                    "real-kit LSP: SKIPPED on a gate that requires RUN; \
                     golden capture/replay must not skip: {reason}"
                );
            }
            None
        }
    }
}

fn unique_dir(label: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!(
        "sugar-lsp-golden-conv-{}-{}-{}",
        label,
        std::process::id(),
        stamp
    ));
    fs::create_dir_all(&p).expect("mkdir fixture");
    p
}

fn shell_single_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

fn toml_string(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

fn stage_real_python_kit_project(label: &str, initial_source: &str) -> PathBuf {
    let project = unique_dir(label);
    let py = python3().expect("python3");
    let kit_src = python_kit_src();
    fs::write(project.join(SOURCE_FILE), initial_source).expect("write source");
    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift/python")).expect("mkdir lift");
    fs::create_dir_all(sugar.join("components/python-lift")).expect("mkdir components");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"

[solvers]
default = "z3"
[solvers.dispatch]
linear_arithmetic = "z3"
default = "z3"
[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 10
"#,
    )
    .expect("config");
    let wrapper = sugar.join("lift/python/run-lift-rpc.sh");
    fs::write(
        &wrapper,
        format!(
            "#!/bin/sh\nexport PYTHONPATH={kit}${{PYTHONPATH:+:$PYTHONPATH}}\nexec {py} -m sugar_lift_py_tests.lift_rpc --rpc\n",
            kit = shell_single_quote(&kit_src.display().to_string()),
            py = shell_single_quote(&py.display().to_string()),
        ),
    )
    .expect("wrapper");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&wrapper).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&wrapper, perms).unwrap();
    }
    fs::write(
        sugar.join("lift/python/manifest.toml"),
        format!(
            "name = \"python\"\ncommand = [{}]\nworking_dir = \".\"\n",
            toml_string(&wrapper.display().to_string())
        ),
    )
    .expect("lift manifest");
    let component_script = sugar.join("components/python-lift/component.sh");
    fs::write(
        &component_script,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"python-lift-component","protocol_version":"sugar-component/1","capabilities":{}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"decision":"claim","plugins":[{"name":"python-lift","kind":"lift","surface":"python"}],"diagnostics":[{"level":"info","message":"python lift component planned"}]}}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
    )
    .expect("component script");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&component_script).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&component_script, perms).unwrap();
    }
    fs::write(
        sugar.join("components/python-lift/manifest.toml"),
        format!(
            "name = \"python-lift-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&component_script.display().to_string())
        ),
    )
    .expect("component manifest");
    project
}

// ---------------------------------------------------------------------------
// Explicit normalizer (see conformance/lsp/README.md)
// ---------------------------------------------------------------------------

/// Recursive Unicode-code-point key sort (JCS-like) for byte-stable encode.
fn sort_keys(v: &Value) -> Value {
    match v {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let mut out = Map::new();
            for k in keys {
                out.insert(k.clone(), sort_keys(&map[k]));
            }
            Value::Object(out)
        }
        Value::Array(items) => Value::Array(items.iter().map(sort_keys).collect()),
        other => other.clone(),
    }
}

/// Apply the loud normalizations from conformance/lsp/README.md.
fn normalize_message(msg: &Value, project: &Path) -> Value {
    let project_abs = project
        .canonicalize()
        .unwrap_or_else(|_| project.to_path_buf());
    let project_str = project_abs.to_string_lossy().to_string();
    // file:// URI forms for absolute paths (Unix: file:///tmp/...).
    let project_uri = format!("file://{project_str}");
    let project_uri_slash = format!("file://{}", project_str.trim_start_matches('/'));

    let mut text = serde_json::to_string(msg).expect("serialize msg for path rewrite");
    // Longest-first replacements so nested paths collapse cleanly.
    text = text.replace(&project_uri, &format!("file://{PROJECT_PLACEHOLDER}"));
    text = text.replace(&project_uri_slash, &format!("file://{PROJECT_PLACEHOLDER}"));
    text = text.replace(&project_str, PROJECT_PLACEHOLDER);
    // Windows-style backslash paths if any slipped in.
    let project_bs = project_str.replace('/', "\\");
    if project_bs != project_str {
        text = text.replace(&project_bs, PROJECT_PLACEHOLDER);
    }

    let mut v: Value = serde_json::from_str(&text).expect("reparse after path rewrite");

    // processId → null (explicit normalization #3)
    if let Some(params) = v.get_mut("params").and_then(|p| p.as_object_mut()) {
        if params.contains_key("processId") {
            params.insert("processId".into(), Value::Null);
        }
    }

    sort_keys(&v)
}

fn encode_line(role: &str, message: &Value) -> String {
    let envelope = json!({
        "message": message,
        "role": role,
    });
    serde_json::to_string(&sort_keys(&envelope)).expect("encode ndjson line")
}

fn conversation_to_ndjson(lines: &[(String, Value)]) -> String {
    let mut out = String::new();
    for (role, msg) in lines {
        out.push_str(&encode_line(role, msg));
        out.push('\n');
    }
    out
}

// ---------------------------------------------------------------------------
// LSP harness with capture
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
        cmd.env_remove("SUGAR_COMPONENT_PATH");
        let mut child = cmd.spawn().expect("spawn sugar-lsp");
        Self {
            stdin: child.stdin.take().expect("stdin"),
            stdout: BufReader::new(child.stdout.take().expect("stdout")),
            child,
            next_id: 1,
        }
    }

    fn send_raw(&mut self, msg: &Value) {
        let body = serde_json::to_string(msg).unwrap();
        let header = format!("Content-Length: {}\r\n\r\n", body.len());
        self.stdin.write_all(header.as_bytes()).unwrap();
        self.stdin.write_all(body.as_bytes()).unwrap();
        self.stdin.flush().unwrap();
    }

    fn recv_raw(&mut self) -> Value {
        let mut content_length: usize = 0;
        loop {
            let mut line = String::new();
            self.stdout.read_line(&mut line).expect("header");
            let trimmed = line.trim();
            if trimmed.is_empty() {
                break;
            }
            if let Some(rest) = trimmed.strip_prefix("Content-Length:") {
                content_length = rest.trim().parse().expect("Content-Length");
            }
        }
        assert!(content_length > 0);
        let mut body = vec![0u8; content_length];
        self.stdout.read_exact(&mut body).expect("body");
        serde_json::from_slice(&body).expect("json")
    }

    fn notify(&mut self, method: &str, params: Value) {
        self.send_raw(&json!({"jsonrpc": "2.0", "method": method, "params": params}));
    }

    fn wait_for_publish_diagnostics(&mut self, uri: &str, timeout: Duration) -> Value {
        let deadline = Instant::now() + timeout;
        loop {
            if Instant::now() >= deadline {
                panic!("no publishDiagnostics for {uri} within {timeout:?}");
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
            let msg = self.recv_raw();
            if msg.get("method").and_then(|m| m.as_str()) == Some("textDocument/publishDiagnostics")
            {
                let params = msg.get("params").cloned().unwrap_or(Value::Null);
                if params.get("uri").and_then(|v| v.as_str()) == Some(uri) {
                    return msg;
                }
            }
        }
    }

    fn kill(mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Drive the real-kit conversation and return normalized field-mapping turns.
fn capture_real_kit_conversation() -> String {
    let project = stage_real_python_kit_project("golden-conv", LYING_TWIN);
    let root_uri = format!("file://{}", project.display());
    let file_uri = format!("file://{}/{}", project.display(), SOURCE_FILE);

    let missing = std::env::temp_dir().join(format!(
        "sugar-lsp-golden-missing-config-{}.toml",
        std::process::id()
    ));

    let mut lsp = LspServer::spawn_in_process(&missing);
    let mut turns: Vec<(String, Value)> = Vec::new();

    // 1. client initialize
    let init_req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "processId": null,
            "capabilities": {},
            "rootUri": root_uri,
        }
    });
    // Force next_id alignment: request() uses next_id starting at 1.
    lsp.next_id = 1;
    turns.push(("client".into(), normalize_message(&init_req, &project)));
    // Send via request path (records response)
    let init_resp = {
        let id = lsp.next_id;
        lsp.next_id += 1;
        lsp.send_raw(&init_req);
        loop {
            let msg = lsp.recv_raw();
            if msg.get("id") == Some(&Value::Number(id.into())) {
                break msg;
            }
        }
    };
    assert!(
        init_resp.get("result").is_some(),
        "initialize failed: {init_resp}"
    );
    // 2. server initialize response
    turns.push(("server".into(), normalize_message(&init_resp, &project)));

    // 3. client initialized
    let initialized = json!({"jsonrpc": "2.0", "method": "initialized", "params": {}});
    turns.push(("client".into(), normalize_message(&initialized, &project)));
    lsp.notify("initialized", json!({}));

    // Drain optional registerCapability without recording (filter).
    // Brief non-blocking poll: not required for the DoD.

    // 4. client didOpen (lying)
    let did_open = json!({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": file_uri,
                "languageId": "python",
                "version": 1,
                "text": LYING_TWIN,
            }
        }
    });
    turns.push(("client".into(), normalize_message(&did_open, &project)));
    lsp.notify(
        "textDocument/didOpen",
        did_open.get("params").cloned().unwrap(),
    );

    // 5. server publishDiagnostics (UNSAT)
    let diags_bad = lsp.wait_for_publish_diagnostics(&file_uri, Duration::from_secs(120));
    let diags_bad_norm = normalize_message(&diags_bad, &project);
    let bad_msgs = diags_bad_norm
        .pointer("/params/diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert!(
        !bad_msgs.is_empty(),
        "lying twin must produce diagnostics: {diags_bad_norm}"
    );
    let bad_text = serde_json::to_string(&bad_msgs).unwrap();
    assert!(
        bad_text.contains("UNSAT")
            || bad_text.to_ascii_lowercase().contains("unsatisfied")
            || bad_text.contains("contradictory"),
        "lying twin must be real UNSAT: {bad_text}"
    );
    turns.push(("server".into(), diags_bad_norm));
    eprintln!(
        "RECEIPT golden capture: lying twin -> UNSAT (n={})",
        bad_msgs.len()
    );

    // 6. client didChange (truthful)
    let did_change = json!({
        "jsonrpc": "2.0",
        "method": "textDocument/didChange",
        "params": {
            "textDocument": {"uri": file_uri, "version": 2},
            "contentChanges": [{"text": TRUTHFUL_TWIN}]
        }
    });
    turns.push(("client".into(), normalize_message(&did_change, &project)));
    lsp.notify(
        "textDocument/didChange",
        did_change.get("params").cloned().unwrap(),
    );

    // 7. server publishDiagnostics (clear)
    let diags_good = lsp.wait_for_publish_diagnostics(&file_uri, Duration::from_secs(120));
    let diags_good_norm = normalize_message(&diags_good, &project);
    let good_msgs = diags_good_norm
        .pointer("/params/diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    assert!(
        good_msgs.is_empty(),
        "truthful twin must clear diagnostics: {diags_good_norm}"
    );
    turns.push(("server".into(), diags_good_norm));
    eprintln!("RECEIPT golden capture: truthful twin -> clear");

    lsp.kill();
    fs::remove_dir_all(&project).ok();
    let _ = fs::remove_file(&missing);

    conversation_to_ndjson(&turns)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/// #3928 gap-1 always-on pin: the checked-in golden NDJSON must freeze the
/// pure field-mapping sequence without requiring a real-kit RAN.
///
/// Byte-identical live replay remains the battleaxe instrument below
/// (`#[ignore]` + `make test-3809-dod-scoreboard`). This test is the local
/// ratchet: deleting/corrupting the golden cannot go silent.
#[test]
fn golden_ndjson_freezes_field_mapping_sequence() {
    let path = golden_path();
    let text = fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "R(gap1 golden_ndjson)>0: missing golden at {} ({e})\n\
             replacement: capture with SUGAR_LSP_GOLDEN_UPDATE=1 + real kit RAN\n\
             see conformance/lsp/README.md",
            path.display()
        );
    });

    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    assert_eq!(
        lines.len(),
        7,
        "R(gap1 golden_ndjson)>0: expected 7 field-mapping turns, got {}\n\
         sequence: initialize → init-result → initialized → didOpen(lie) → \
         publishDiagnostics(UNSAT) → didChange(truth) → publishDiagnostics([])\n\
         path: {}",
        lines.len(),
        path.display()
    );

    let mut roles: Vec<String> = Vec::new();
    let mut methods: Vec<Option<String>> = Vec::new();
    let mut has_init_result = false;
    for (i, line) in lines.iter().enumerate() {
        let v: Value = serde_json::from_str(line).unwrap_or_else(|e| {
            panic!("golden line {} not JSON: {e}\n  {line}", i + 1);
        });
        // Keys must be sorted recursively at the top level (byte-stable encode).
        if let Some(obj) = v.as_object() {
            let keys: Vec<&String> = obj.keys().collect();
            let mut sorted = keys.clone();
            sorted.sort();
            assert_eq!(
                keys,
                sorted,
                "golden line {} top-level keys not Unicode-sorted: {keys:?}",
                i + 1
            );
        }
        let role = v
            .get("role")
            .and_then(|r| r.as_str())
            .unwrap_or_else(|| panic!("line {} missing role", i + 1));
        roles.push(role.to_string());
        let msg = v
            .get("message")
            .unwrap_or_else(|| panic!("line {} missing message", i + 1));
        methods.push(
            msg.get("method")
                .and_then(|m| m.as_str())
                .map(|s| s.to_string()),
        );
        if i == 1 {
            assert!(
                msg.get("result").is_some(),
                "line 2 must be server initialize result"
            );
            has_init_result = true;
        }
    }
    assert!(has_init_result);

    assert_eq!(
        roles,
        ["client", "server", "client", "client", "server", "client", "server"],
        "role sequence drift in golden"
    );
    assert_eq!(methods[0].as_deref(), Some("initialize"));
    assert!(methods[1].is_none(), "init result has no method");
    assert_eq!(methods[2].as_deref(), Some("initialized"));
    assert_eq!(methods[3].as_deref(), Some("textDocument/didOpen"));
    assert_eq!(
        methods[4].as_deref(),
        Some("textDocument/publishDiagnostics")
    );
    assert_eq!(methods[5].as_deref(), Some("textDocument/didChange"));
    assert_eq!(
        methods[6].as_deref(),
        Some("textDocument/publishDiagnostics")
    );

    // Lying twin source frozen; real UNSAT discrimination frozen; clear frozen.
    assert!(
        text.contains("assert total == 6") && text.contains("assert total == 7"),
        "golden must freeze lying dual-assert twin"
    );
    assert!(
        text.contains("UNSAT") || text.to_ascii_lowercase().contains("unsatisfied"),
        "golden must freeze real UNSAT diagnostic"
    );
    assert!(
        text.contains("pandas") || text.contains("DataFrame") || text.contains("sum"),
        "golden must freeze real pandas/sum claim (not mock demo.check)"
    );
    // Clear diagnostics = empty array on the second publishDiagnostics.
    let clear_line = lines[6];
    assert!(
        clear_line.contains(r#""diagnostics":[]"#) || clear_line.contains(r#""diagnostics": []"#),
        "final publishDiagnostics must clear (empty diagnostics): {clear_line}"
    );
    // Placeholder normalizations (no live /tmp paths).
    assert!(
        text.contains(PROJECT_PLACEHOLDER),
        "golden must use {PROJECT_PLACEHOLDER} path placeholder"
    );
    assert!(
        !text.contains("/tmp/"),
        "golden must not leak live /tmp project paths"
    );

    eprintln!(
        "RECEIPT #3928 gap1 pin: golden field-mapping sequence ok ({} bytes, 7 turns)",
        text.len()
    );
}

/// #3928 gap-2 always-on pin: real-kit prove instrument is enrolled (module
/// present) and names the real python lift path — mock-only acceptance is
/// not allowed to silently replace the PyCon face.
#[test]
fn real_python_kit_prove_instrument_is_enrolled() {
    let prove_src =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/real_python_kit_prove.rs");
    let text = fs::read_to_string(&prove_src).unwrap_or_else(|e| {
        panic!(
            "R(gap2 real_kit)>0: missing {p} ({e})\n\
             replacement: restore real_python_kit_prove.rs (real lift_rpc, not mock)",
            p = prove_src.display()
        );
    });
    for needle in [
        "sugar_lift_py_tests.lift_rpc",
        "SUGAR_REAL_KIT_LSP_REQUIRED",
        "real-kit LSP: RAN",
        "LYING_TWIN",
        "TRUTHFUL_TWIN",
        "UNSAT",
    ] {
        assert!(
            text.contains(needle),
            "R(gap2 real_kit)>0: real_python_kit_prove.rs missing enrollment marker {needle:?}\n\
             replacement: keep real kit face; mock stays in in_process_prove only"
        );
    }
    eprintln!("RECEIPT #3928 gap2 pin: real_python_kit_prove instrument enrolled");
}

/// #3928 gap-3 always-on pin: LSP buffer re-solve discharges through the
/// resident-base one door. `warm_solve` was deleted (#3981); warmth is
/// derived (resident base index + pre-fed overlay), not a second function.
/// Identity: LSP door = `verify_consistency_scoped_with_base_index`;
/// Runner door = `solve_project_with_pool`. Both are pool-resident discharge.
#[test]
fn lsp_solve_buffer_uses_resident_base_one_door() {
    let src_path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/prove_engine.rs");
    let text = fs::read_to_string(&src_path).expect("read prove_engine.rs");

    assert!(
        text.contains("verify_consistency_scoped_with_base_index"),
        "R(gap3 warm_face)>0: solve_buffer must call the resident-base one door\n\
         replacement: discharge via sugar_verifier::consistency::verify_consistency_scoped_with_base_index\n\
         (warmth = resident base index; do not reintroduce a parallel cold load_pool path)"
    );
    // Count call sites in the solve_buffer body region: the function name must
    // appear as an actual call, not only in docs.
    let call_needle = "sugar_verifier::consistency::verify_consistency_scoped_with_base_index(";
    assert!(
        text.contains(call_needle),
        "R(gap3 warm_face)>0: missing call {call_needle}\n\
         prove_engine must route buffer re-solve through the one resident-base door"
    );
    // Parallel mint-as-feed is the illegal dual path (#4030 closed it).
    // Call-site only: docs may name the banned symbol as the thing not to do.
    assert!(
        !text.contains("mint_project_scratch_proof("),
        "R(gap3 warm_face)>0: mint-as-feed call reappeared in prove_engine\n\
         replacement: keep enumerate→fold→resident-base door only; mint is seal/publish"
    );
    // Must not reintroduce the deleted dual warm_solve symbol as a second door.
    assert!(
        !text.contains("warm_solve("),
        "R(gap3 warm_face)>0: warm_solve( call reintroduced — one door was the point of #3981\n\
         warmth is derived residency, not a second function name"
    );
    eprintln!(
        "RECEIPT #3928 gap3 pin: solve_buffer → verify_consistency_scoped_with_base_index (one door)"
    );
}

#[test]
#[ignore = "explicit real-Pandas battleaxe instrument: run make test-3809-dod-scoreboard"]
fn real_python_kit_conversation_is_byte_identical_to_golden_ndjson() {
    let Some(_py) = require_real_kit_or_skip() else {
        return;
    };

    let live = capture_real_kit_conversation();
    let path = golden_path();

    if matches!(
        std::env::var("SUGAR_LSP_GOLDEN_UPDATE").as_deref(),
        Ok("1") | Ok("true") | Ok("yes")
    ) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("mkdir golden dir");
        }
        fs::write(&path, &live).expect("write golden");
        eprintln!(
            "UPDATED golden at {} ({} bytes)\n{}",
            path.display(),
            live.len(),
            live
        );
        // Fall through to assert against what we just wrote (self-check).
    }

    let golden = fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "missing golden at {} ({e}); capture with SUGAR_LSP_GOLDEN_UPDATE=1 \
             from a real-kit RAN (battleaxe / SUGAR_REAL_KIT_LSP_REQUIRED=1)",
            path.display()
        );
    });

    if live != golden {
        // Loud byte-diff: length + first differing line.
        let live_lines: Vec<&str> = live.lines().collect();
        let gold_lines: Vec<&str> = golden.lines().collect();
        let mut detail = format!(
            "BYTE MISMATCH real-kit conversation vs golden\n  golden: {}\n  live_bytes={} golden_bytes={}\n  live_lines={} golden_lines={}\n",
            path.display(),
            live.len(),
            golden.len(),
            live_lines.len(),
            gold_lines.len()
        );
        let n = live_lines.len().max(gold_lines.len());
        for i in 0..n {
            let a = live_lines.get(i).copied().unwrap_or("<missing>");
            let b = gold_lines.get(i).copied().unwrap_or("<missing>");
            if a != b {
                detail.push_str(&format!(
                    "  first diff at line {}:\n    live  : {}\n    golden: {}\n",
                    i + 1,
                    a,
                    b
                ));
                break;
            }
        }
        // Also dump publishDiagnostics turns for human receipt.
        for (i, line) in live_lines.iter().enumerate() {
            if line.contains("publishDiagnostics") {
                detail.push_str(&format!("  live publishDiagnostics L{}: {}\n", i + 1, line));
            }
        }
        panic!("{detail}");
    }

    // Extra teeth: golden must contain the real discrimination shape.
    assert!(
        golden.contains("UNSAT") || golden.contains("unsatisfied"),
        "golden must freeze real UNSAT"
    );
    assert!(
        golden.contains("pandas") || golden.contains("DataFrame") || golden.contains("sum"),
        "golden must freeze real pandas/sum claim"
    );
    assert!(
        golden.matches("publishDiagnostics").count() >= 2,
        "golden must include both UNSAT and clear publishDiagnostics"
    );
    eprintln!(
        "RECEIPT byte-identical: live real-kit conversation matches golden ({} bytes, {} lines)",
        live.len(),
        live.lines().count()
    );
    eprintln!("real-kit LSP: RECEIPT conversation golden BYTE-IDENTICAL (ok)");
}
