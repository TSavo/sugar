// SPDX-License-Identifier: MIT OR Apache-2.0
//
// daemon_client.rs: integration tests for sugar-lsp-rust daemon-client mode.
//
// Test 1: spawn daemon, run lsp-rust with --daemon-socket, assert parse response
//         has result.diagnostics (shape test, empty is fine for no-violation source).
// Test 2: existing round_trip tests on result.declarations still pass in default mode.
//         (Covered by round_trip.rs: verified by running the full suite.)
// Test 3: byte-determinism: two parse calls with byte-identical source produce
//         byte-identical daemon parseFile output.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn daemon_bin() -> PathBuf {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    // lsp-rust is at implementations/rust/sugar-lsp-rust/
    // workspace root is implementations/rust/
    let workspace = PathBuf::from(manifest_dir).parent().unwrap().to_path_buf();
    let release = workspace
        .join("target")
        .join("release")
        .join("sugar-linkerd");
    let debug = workspace.join("target").join("debug").join("sugar-linkerd");
    if release.exists() {
        release
    } else {
        debug
    }
}

fn lsp_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp-rust"))
}

fn unique_sock(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "sugar-lsp-rust-test-{}-{}.sock",
        label,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos())
            .unwrap_or(0)
    ))
}

fn unique_snap(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "sugar-lsp-rust-snap-{}-{}.bin",
        label,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos())
            .unwrap_or(0)
    ))
}

fn spawn_daemon(sock: &PathBuf, snap: &PathBuf, idle_ms: u64) -> Child {
    let bin = daemon_bin();
    assert!(
        bin.exists(),
        "sugar-linkerd binary not found at {}; run `cargo build -p sugar-linkerd` first",
        bin.display()
    );
    Command::new(&bin)
        .arg("--socket")
        .arg(sock)
        .arg("--snapshot")
        .arg(snap)
        .arg("--idle-timeout-ms")
        .arg(idle_ms.to_string())
        .arg("--project-cid")
        .arg("lsp-rust-test")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn sugar-linkerd")
}

fn wait_for_socket(sock: &PathBuf, timeout: Duration) -> bool {
    let start = Instant::now();
    loop {
        if UnixStream::connect(sock).is_ok() {
            return true;
        }
        if start.elapsed() >= timeout {
            return false;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn shutdown_daemon(sock: &PathBuf) {
    if let Ok(mut stream) = UnixStream::connect(sock) {
        let req = serde_json::to_string(
            &json!({"jsonrpc":"2.0","id":999,"method":"shutdown","params":{}}),
        )
        .unwrap();
        let _ = writeln!(stream, "{req}");
        let _ = stream.flush();
        // Give it a moment to shut down.
        std::thread::sleep(Duration::from_millis(200));
    }
}

// Spawn lsp-rust in daemon-client mode and return (child, stdin, stdout).
struct LspPlugin {
    child: Child,
    stdin: std::process::ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
}

impl LspPlugin {
    fn spawn_daemon_client(socket_path: &PathBuf) -> Self {
        let mut child = Command::new(lsp_bin())
            .arg("--daemon-socket")
            .arg(socket_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn sugar-lsp-rust --daemon-socket");
        let stdin = child.stdin.take().expect("lsp stdin");
        let stdout = BufReader::new(child.stdout.take().expect("lsp stdout"));
        Self {
            child,
            stdin,
            stdout,
        }
    }

    fn exchange(&mut self, payload: &Value) -> Value {
        let line = serde_json::to_string(payload).unwrap();
        writeln!(self.stdin, "{line}").expect("write to lsp stdin");
        self.stdin.flush().expect("flush lsp stdin");
        let mut buf = String::new();
        let n = self.stdout.read_line(&mut buf).expect("read lsp stdout");
        assert!(n > 0, "lsp plugin closed stdout without responding");
        serde_json::from_str(buf.trim()).expect("decode lsp response as JSON")
    }

    fn shutdown(mut self) {
        let _ = self.exchange(&json!({"jsonrpc":"2.0","id":99,"method":"shutdown"}));
        let _ = self.child.wait();
    }
}

// ---------------------------------------------------------------------------
// Test 1: daemon-client mode returns result.diagnostics
// ---------------------------------------------------------------------------

#[test]
fn daemon_client_parse_returns_diagnostics_shape() {
    let sock = unique_sock("dc1");
    let snap = unique_snap("dc1");

    let mut daemon = spawn_daemon(&sock, &snap, 60_000);
    assert!(
        wait_for_socket(&sock, Duration::from_secs(10)),
        "daemon did not bind socket at {} within 10s",
        sock.display()
    );

    let mut plugin = LspPlugin::spawn_daemon_client(&sock);

    // initialize
    let init_resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }));
    assert_eq!(init_resp["result"]["name"], "sugar-lsp-rust");

    // parse a simple Rust source (no contract violations expected)
    let source = r#"
#[test]
fn value_is_non_negative() {
    let x: i64 = 42;
    assert!(x >= 0);
}
"#;

    let resp = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "parse",
        "params": {
            "path": "/tmp/simple.rs",
            "source": source
        }
    }));

    assert_eq!(resp["jsonrpc"], "2.0");
    assert_eq!(resp["id"], 2);

    // Must have result, not error.
    let result = resp
        .get("result")
        .unwrap_or_else(|| panic!("daemon-client parse returned error instead of result: {resp}"));

    // result.diagnostics must be an array.
    assert!(
        result
            .get("diagnostics")
            .and_then(|d| d.as_array())
            .is_some(),
        "result.diagnostics must be an array in daemon-client mode; got: {result}"
    );

    // In daemon-client mode there must NOT be a `declarations` key: that's
    // the default-mode shape.
    assert!(
        result.get("declarations").is_none(),
        "daemon-client mode must not return 'declarations'; got: {result}"
    );

    plugin.shutdown();
    shutdown_daemon(&sock);
    let _ = daemon.wait();
}

// ---------------------------------------------------------------------------
// Test 2: byte-determinism: same source => same diagnostics from daemon
// ---------------------------------------------------------------------------

#[test]
fn daemon_client_parse_is_byte_deterministic() {
    let sock = unique_sock("dc2");
    let snap = unique_snap("dc2");

    let mut daemon = spawn_daemon(&sock, &snap, 60_000);
    assert!(
        wait_for_socket(&sock, Duration::from_secs(10)),
        "daemon did not bind socket in byte-det test"
    );

    let mut plugin = LspPlugin::spawn_daemon_client(&sock);

    let _ = plugin.exchange(&json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}));

    let source = r#"fn add(a: i64, b: i64) -> i64 { a + b }"#;
    let path = "/tmp/det.rs";

    let resp1 = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "parse",
        "params": { "path": path, "source": source }
    }));

    let resp2 = plugin.exchange(&json!({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "parse",
        "params": { "path": path, "source": source }
    }));

    let diags1 = resp1["result"]["diagnostics"]
        .as_array()
        .unwrap_or_else(|| panic!("resp1 missing diagnostics array: {resp1}"));
    let diags2 = resp2["result"]["diagnostics"]
        .as_array()
        .unwrap_or_else(|| panic!("resp2 missing diagnostics array: {resp2}"));

    // Spec R5 idempotency: byte-identical inputs => byte-identical diagnostics.
    assert_eq!(
        diags1, diags2,
        "daemon-client parse is not idempotent: first run != second run"
    );

    plugin.shutdown();
    shutdown_daemon(&sock);
    let _ = daemon.wait();
}
