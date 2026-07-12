// SPDX-License-Identifier: MIT OR Apache-2.0
//
// real_python_kit_prove.rs: PyCon demo path acceptance for the in-process LSP.
//
// THE TERMINUS composition that `in_process_prove.rs` deliberately does NOT
// claim (see its HONESTY NOTE): real pandas source -> real python lift-rpc
// (`python -m sugar_lift_py_tests.lift_rpc --rpc`) -> sugar-lsp overlay mint
// -> real consistency solve -> red squiggle (UNSAT) for the lying twin, clear
// for the truthful twin.
//
// Discrimination is the pandas-showcase consistency seat (same shape as
// `examples/pandas-showcase/test_pandas_sum{,_bad}.py`):
//   lying:     assert total == 6 ∧ assert total == 7  -> unsatisfied / UNSAT
//   truthful:  assert total == 6                       -> refused (not red)
//
// NO shell mock lifter. NO canned IR. The lift process is the same kit the
// witness corpus / pandas DoD scoreboard spawn. The component planner shell
// (if staged) only claims surface `python`; it never answers `lift`.

use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

fn lsp_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp"))
}

/// Repo root: sugar-lsp Cargo.toml is at `implementations/rust/sugar-lsp/`.
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .expect("resolve sugar repo root from CARGO_MANIFEST_DIR")
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
    // Prefer the battleaxe / bcargo provisioned interpreter when present
    // (`bin/brun` exports `PYTHON` to the remote kit venv).
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
                // Prefer an absolute path so the staged wrapper survives cwd changes.
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

/// Gate mode: skip must be red. Armed by:
/// - `SUGAR_REAL_KIT_LSP_REQUIRED=1` (battleaxe Makefile gate / explicit), or
/// - `CI=true` (self-hosted acid CI — a silent skip is not a pass).
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

/// Real kit reachable: `import sugar_lift_py_tests.lift_rpc` and `import pandas`.
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
            "real kit import failed (need pandas + sugar_lift_py_tests on PYTHONPATH)\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&probe.stdout),
            String::from_utf8_lossy(&probe.stderr),
        ));
    }
    Ok(())
}

fn unique_dir(label: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!(
        "sugar-lsp-real-py-kit-{}-{}-{}",
        label,
        std::process::id(),
        stamp
    ));
    fs::create_dir_all(&p).expect("mkdir fixture dir");
    p
}

// ---------------------------------------------------------------------------
// Real python lift-rpc staging (mirror of witness_harness._stage_cli_project,
// minus the capture wrapper — mint talks to the kit directly).
// ---------------------------------------------------------------------------

/// Stage a project whose `.sugar/lift/python` command is the REAL kit:
/// `python -m sugar_lift_py_tests.lift_rpc --rpc`. Never a mock-lifter.sh.
fn stage_real_python_kit_project(label: &str, initial_source: &str) -> PathBuf {
    let project = unique_dir(label);
    let py = python3().expect("python3 required for real-kit fixture");
    let kit_src = python_kit_src();

    fs::write(project.join("test_pandas_sum.py"), initial_source).expect("write source");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift/python")).expect("mkdir lift/python");
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
    .expect("write config.toml");

    // Absolute-path wrapper so the overlay mint (which copies .sugar/lift
    // into a temp overlay) still invokes the same real kit process.
    let wrapper = sugar.join("lift/python/run-lift-rpc.sh");
    let wrapper_body = format!(
        "#!/bin/sh\nexport PYTHONPATH={kit}${{PYTHONPATH:+:$PYTHONPATH}}\nexec {py} -m sugar_lift_py_tests.lift_rpc --rpc\n",
        kit = shell_single_quote(&kit_src.display().to_string()),
        py = shell_single_quote(&py.display().to_string()),
    );
    fs::write(&wrapper, wrapper_body).expect("write run-lift-rpc.sh");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&wrapper).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&wrapper, perms).expect("chmod run-lift-rpc.sh");
    }

    fs::write(
        sugar.join("lift/python/manifest.toml"),
        format!(
            "name = \"python\"\ncommand = [{}]\nworking_dir = \".\"\n",
            toml_string(&wrapper.display().to_string())
        ),
    )
    .expect("write lift manifest");

    // Component planner only claims surface `python` (same as witness_harness).
    // It does NOT answer `lift` — that is the real kit above.
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
    .expect("write component planner");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&component_script).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&component_script, perms).expect("chmod component.sh");
    }
    fs::write(
        sugar.join("components/python-lift/manifest.toml"),
        format!(
            "name = \"python-lift-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&component_script.display().to_string())
        ),
    )
    .expect("write component manifest");

    project
}

fn shell_single_quote(s: &str) -> String {
    // POSIX single-quote: wrap and escape embedded ' as '\''
    format!("'{}'", s.replace('\'', "'\\''"))
}

fn toml_string(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

/// Lying twin: real DataFrame + real Series.sum + contradictory asserts.
/// Same structural claim as `examples/pandas-showcase/test_pandas_sum_bad.py`.
const LYING_TWIN: &str = r#"import pandas as pd


def test_column_sum_contradiction():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6
    assert total == 7
"#;

/// Truthful twin: real DataFrame + real Series.sum + single true assert.
/// Same structural claim as `examples/pandas-showcase/test_pandas_sum.py`.
const TRUTHFUL_TWIN: &str = r#"import pandas as pd


def test_column_sum_is_six():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6
"#;

// ---------------------------------------------------------------------------
// LSP process wrapper (Content-Length framed JSON-RPC) — same shape as
// in_process_prove.rs, duplicated so the mock file stays untouched.
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
        // Hermetic: do not inherit ambient SUGAR_COMPONENT_PATH into the LSP
        // process (component discovery would leave the staged project).
        cmd.env_remove("SUGAR_COMPONENT_PATH");
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
        "sugar-lsp-real-py-kit-missing-config-{label}-{}.toml",
        std::process::id()
    ))
}

fn diag_messages(params: &Value) -> Vec<String> {
    params
        .get("diagnostics")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|d| {
            d.get("message")
                .and_then(|m| m.as_str())
                .map(|s| s.to_string())
        })
        .collect()
}

/// Resolve the real kit or skip (soft) / fail (gate).
///
/// Always emits an observable receipt line:
///   `real-kit LSP: RAN`     — kit present; test body will execute
///   `real-kit LSP: SKIPPED: <reason>` — kit/z3 missing
///
/// When `real_kit_required()` (battleaxe gate / CI), SKIPPED is a hard red,
/// never a silent green.
fn require_real_kit_or_skip() -> Option<PathBuf> {
    let outcome: Result<PathBuf, String> = (|| {
        if !z3_available() {
            return Err("z3 not on PATH; real-kit LSP prove needs z3 discharge".into());
        }
        let py = python3().ok_or_else(|| "python3 not on PATH".to_string())?;
        real_python_kit_available(&py)?;
        Ok(py)
    })();

    match outcome {
        Ok(py) => {
            eprintln!("real-kit LSP: RAN");
            Some(py)
        }
        Err(reason) => {
            eprintln!("real-kit LSP: SKIPPED: {reason}");
            if real_kit_required() {
                panic!(
                    "real-kit LSP: SKIPPED on a gate that requires RUN \
                     (SUGAR_REAL_KIT_LSP_REQUIRED=1 or CI=true); \
                     silent skip is not a pass: {reason}"
                );
            }
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Test 1: didOpen the lying twin -> real UNSAT diagnostic from real kit lift.
// ---------------------------------------------------------------------------

#[test]
fn real_python_kit_did_open_lying_twin_reports_unsat() {
    let Some(_py) = require_real_kit_or_skip() else {
        return;
    };

    let project = stage_real_python_kit_project("open-lie", LYING_TWIN);
    let root_uri = format!("file://{}", project.display());
    let file_uri = format!("file://{}/test_pandas_sum.py", project.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("open-lie"));
    let init_resp = lsp.initialize(&root_uri);
    assert!(
        init_resp.get("result").is_some(),
        "initialize failed: {init_resp}"
    );
    lsp.initialized();

    lsp.notify(
        "textDocument/didOpen",
        json!({
            "textDocument": {
                "uri": file_uri,
                "languageId": "python",
                "version": 1,
                "text": LYING_TWIN,
            }
        }),
    );

    // Real kit mint + solve is heavier than the mock path; allow headroom.
    let params = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(120))
        .unwrap_or_else(|| {
            panic!("no publishDiagnostics for lying twin within 120s (real kit lift + solve)")
        });

    let messages = diag_messages(&params);
    eprintln!(
        "RECEIPT real-kit lying twin diagnostics (n={}): {:?}",
        messages.len(),
        messages
    );
    assert!(
        !messages.is_empty(),
        "lying twin must publish at least one red diagnostic from real-kit UNSAT; got {params}"
    );
    let joined = messages.join("\n---\n");
    assert!(
        joined.contains("UNSAT")
            || joined.to_ascii_lowercase().contains("unsatisfied")
            || joined.contains("contradictory"),
        "lying twin diagnostic must report real UNSAT / contradiction; messages:\n{joined}"
    );
    // Real pandas Series.sum coordinate must appear in the discrimination
    // (proves this is not a canned mock fact about demo.check).
    assert!(
        joined.contains("sum") || joined.contains("pandas") || joined.contains("DataFrame"),
        "lying twin diagnostic must mention the real sum/pandas claim; messages:\n{joined}"
    );
    eprintln!("real-kit LSP: RECEIPT lying twin -> UNSAT (ok)");

    lsp.kill();
    fs::remove_dir_all(&project).ok();
}

// ---------------------------------------------------------------------------
// Test 2: didOpen lying -> didChange truthful -> diagnostics clear.
// ---------------------------------------------------------------------------

#[test]
fn real_python_kit_did_change_to_truthful_twin_clears_diagnostics() {
    let Some(_py) = require_real_kit_or_skip() else {
        return;
    };

    let project = stage_real_python_kit_project("change-truth", LYING_TWIN);
    let root_uri = format!("file://{}", project.display());
    let file_uri = format!("file://{}/test_pandas_sum.py", project.display());

    let mut lsp = LspServer::spawn_in_process(&missing_config_path("change-truth"));
    let init_resp = lsp.initialize(&root_uri);
    assert!(
        init_resp.get("result").is_some(),
        "initialize failed: {init_resp}"
    );
    lsp.initialized();

    lsp.notify(
        "textDocument/didOpen",
        json!({
            "textDocument": {
                "uri": file_uri,
                "languageId": "python",
                "version": 1,
                "text": LYING_TWIN,
            }
        }),
    );
    let opened = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(120))
        .unwrap_or_else(|| panic!("no publishDiagnostics after didOpen (lying twin)"));
    let opened_msgs = diag_messages(&opened);
    eprintln!(
        "RECEIPT real-kit didOpen lying diagnostics (n={}): {:?}",
        opened_msgs.len(),
        opened_msgs
    );
    assert!(
        !opened_msgs.is_empty(),
        "lying twin must open red before we test clear-on-truth: {opened}"
    );
    let opened_joined = opened_msgs.join("\n");
    assert!(
        opened_joined.contains("UNSAT")
            || opened_joined.to_ascii_lowercase().contains("unsatisfied")
            || opened_joined.contains("contradictory"),
        "lying twin must be real UNSAT before clear step; messages:\n{opened_joined}"
    );

    // didChange to the truthful twin: real kit re-lifts the buffer and the
    // consistency seat no longer has the dual-assert contradiction.
    lsp.notify(
        "textDocument/didChange",
        json!({
            "textDocument": {"uri": file_uri, "version": 2},
            "contentChanges": [{"text": TRUTHFUL_TWIN}]
        }),
    );

    // Debounce is 250ms; real mint+solve can take many seconds.
    let changed = lsp
        .wait_for_publish_diagnostics(&file_uri, Duration::from_secs(120))
        .unwrap_or_else(|| panic!("no publishDiagnostics after didChange (truthful twin)"));
    let changed_msgs = diag_messages(&changed);
    eprintln!(
        "RECEIPT real-kit didChange truthful diagnostics (n={}): {:?}",
        changed_msgs.len(),
        changed_msgs
    );
    assert!(
        changed_msgs.is_empty(),
        "truthful twin must clear the contradiction diagnostic; still red: {changed_msgs:?}"
    );
    eprintln!("real-kit LSP: RECEIPT truthful twin -> clear (ok)");

    lsp.kill();
    fs::remove_dir_all(&project).ok();
}
