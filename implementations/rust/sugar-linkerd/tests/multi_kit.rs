// SPDX-License-Identifier: Apache-2.0
//
// multi_kit.rs: tests for polyglot kit dispatch in the linkerd daemon.
//
// Test 1: parseFile(kit="go", ...) invokes the go lifter and returns a
//         LinkerOutput with non-empty contracts when sugar-lsp-go is on PATH.
//         Skipped if sugar-lsp-go is not installed (clearly marked).
//
// Test 2: parseFile(kit="unknown-kit", ...) returns an UnknownKit (-33001) error.
//
// Test 3: kit dispatch is content-deterministic: same source => same linkBundleCid.
//
// Test 4: parseFile(kit="java", ...) dispatches to the java lifter and returns
//         a result with declarations and callEdges arrays when sugar-lsp-java
//         is on PATH. Skipped if sugar-lsp-java is not installed.
//
// Test 5: parseFile(kit="cpp", ...) dispatches to the cpp lifter.
//         Skipped if sugar-lsp-cpp is not installed.
//
// Test 6: parseFile(kit="swift", ...) dispatches to the swift lifter.
//         Skipped if sugar-lsp-swift is not installed.
//
// Test 7: parseFile(kit="c", ...) dispatches to the c lifter.
//         Skipped if sugar-lsp-c is not installed.
//
// Test 8: parseFile(kit="zig", ...) dispatches to the zig lifter.
//         Skipped if sugar-lsp-zig is not installed.
//
// Test 9: parseFile(kit="python", ...) dispatches to the python lifter.
//          Uses a fixture binary on PATH so the test is not coupled to the
//          developer machine's Python package installation state.
//
// Test 10: parseFile(kit="php", ...) dispatches to the php lifter and returns
//          a result with a diagnostics array when sugar-lsp-php is on PATH.
//
// Test 11: parseFile(kit="scala", ...) is registered in linkerd dispatch.
//          If sugar-lsp-scala is absent, it must return LifterUnavailable,
//          not UnknownKit.
//
// These tests communicate with the daemon over its Unix socket.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

fn daemon_bin() -> PathBuf {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let workspace = PathBuf::from(manifest_dir).parent().unwrap().to_path_buf();
    // CI builds with --release; local cargo test uses debug. Try release first.
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

fn unique_sock_path(prefix: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "sugar-linkerd-mk-{}-{}.sock",
        prefix,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos())
            .unwrap_or(0)
    ))
}

fn spawn_daemon(sock: &PathBuf) -> Child {
    let snap = std::env::temp_dir().join(format!(
        "mk-snap-{}.bin",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos())
            .unwrap_or(0)
    ));
    Command::new(daemon_bin())
        .arg("--socket")
        .arg(sock)
        .arg("--snapshot")
        .arg(snap)
        .arg("--idle-timeout-ms")
        .arg("30000")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn daemon")
}

fn wait_for_socket(sock: &PathBuf, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if sock.exists() && UnixStream::connect(sock).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    false
}

fn send_recv(sock: &PathBuf, req: &serde_json::Value) -> serde_json::Value {
    let mut stream = UnixStream::connect(sock).expect("connect");
    stream.set_read_timeout(Some(Duration::from_secs(10))).ok();
    let line = serde_json::to_string(req).unwrap() + "\n";
    stream.write_all(line.as_bytes()).expect("write");
    let mut reader = BufReader::new(stream);
    let mut response_line = String::new();
    reader.read_line(&mut response_line).expect("read");
    serde_json::from_str(response_line.trim()).expect("parse JSON")
}

fn shutdown(sock: &PathBuf) {
    let req = serde_json::json!({
        "jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": {}
    });
    let _ = send_recv(sock, &req);
}

/// Check if a binary is available on PATH.
fn binary_on_path(name: &str) -> bool {
    binary_path(name).is_some()
}

fn binary_path(name: &str) -> Option<PathBuf> {
    if let Ok(path_var) = std::env::var("PATH") {
        for dir in path_var.split(':') {
            let candidate = PathBuf::from(dir).join(name);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

fn rpc_binary_accepts_initialize(name: &str, args: &[&str]) -> Result<PathBuf, String> {
    let path = binary_path(name).ok_or_else(|| format!("{name} not on PATH"))?;

    let mut child = Command::new(&path)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("spawn {}: {e}", path.display()))?;

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| format!("{} did not expose stdin", path.display()))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| format!("{} did not expose stdout", path.display()))?;

    let init_req = serde_json::json!({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    });
    let init_line = serde_json::to_string(&init_req).unwrap() + "\n";
    if let Err(e) = stdin.write_all(init_line.as_bytes()) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!("write initialize to {}: {e}", path.display()));
    }

    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        let read = reader.read_line(&mut line);
        let _ = tx.send((read, line));
    });

    let (read, line) = match rx.recv_timeout(Duration::from_secs(3)) {
        Ok(result) => result,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("{} did not answer initialize", path.display()));
        }
    };

    match read {
        Ok(0) => {
            let _ = child.wait();
            return Err(format!(
                "{} exited before initialize response",
                path.display()
            ));
        }
        Ok(_) => {}
        Err(e) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("read initialize from {}: {e}", path.display()));
        }
    }

    if !line.contains("\"result\"") {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
            "{} returned unexpected initialize response: {}",
            path.display(),
            line.trim()
        ));
    }

    let shutdown_req = serde_json::json!({
        "jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}
    });
    let shutdown_line = serde_json::to_string(&shutdown_req).unwrap() + "\n";
    let _ = stdin.write_all(shutdown_line.as_bytes());
    drop(stdin);
    let _ = child.wait();

    Ok(path)
}

fn install_fixture_python_lsp() -> PathBuf {
    let bin_dir = std::env::temp_dir().join(format!(
        "sugar-linkerd-python-bin-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos())
            .unwrap_or(0)
    ));
    std::fs::create_dir_all(&bin_dir).expect("create python fixture bin dir");
    let binary = bin_dir.join("sugar-lsp-python");
    std::fs::write(
        &binary,
        r#"#!/usr/bin/env python3
import json
import sys

for line in sys.stdin:
    if not line.strip():
        continue
    request = json.loads(line)
    method = request.get("method")
    msg_id = request.get("id")
    if method == "initialize":
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "name": "sugar-lsp-python",
                "version": "fixture",
                "capabilities": ["parse"],
            },
        }
    elif method == "parse":
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "declarations": [],
                "callEdges": [],
                "warnings": [],
            },
        }
    elif method == "shutdown":
        response = {"jsonrpc": "2.0", "id": msg_id, "result": None}
        print(json.dumps(response, separators=(",", ":")), flush=True)
        break
    else:
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }
    print(json.dumps(response, separators=(",", ":")), flush=True)
"#,
    )
    .expect("write python fixture lsp");
    let mut perms = std::fs::metadata(&binary)
        .expect("stat python fixture lsp")
        .permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(&binary, perms).expect("chmod python fixture lsp");

    let current_path = std::env::var("PATH").unwrap_or_default();
    let new_path = if current_path.is_empty() {
        bin_dir.display().to_string()
    } else {
        format!("{}:{}", bin_dir.display(), current_path)
    };
    std::env::set_var("PATH", new_path);
    bin_dir
}

// -------------------------------------------------------------------
// Test 1: go kit dispatch returns diagnostics when sugar-lsp-go is on PATH.
// -------------------------------------------------------------------

/// Test 1: parseFile with kit="go" dispatches to the go lifter.
///
/// Skipped if `sugar-lsp-go` is not on PATH. The skip is printed to stdout
/// so CI can see why the test was skipped, not silently ignored.
///
/// When sugar-lsp-go is available, sends a tiny go source with a
/// `//sugar:contract` annotation and asserts:
///   - The response has a `result.diagnostics` array (may be empty or non-empty).
///   - No JSON-RPC error is returned.
#[test]
fn test1_go_kit_dispatch() {
    if !binary_on_path("sugar-lsp-go") {
        println!(
            "SKIP test1_go_kit_dispatch: sugar-lsp-go not on PATH. \
             Install via: cd implementations/go && go install ./cmd/sugar-lsp-go"
        );
        return;
    }

    let sock = unique_sock_path("t1");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let go_source = r#"package main

//sugar:contract
func Add(a, b int) int {
    return a + b
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "go",
            "file": "/tmp/test_add.go",
            "source": go_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "go kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "go kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 2: unknown kit returns UnknownKit error (-33001).
// -------------------------------------------------------------------

/// Test 2: parseFile with kit="unknown-kit" returns error code -33001.
#[test]
fn test2_unknown_kit_returns_error() {
    let sock = unique_sock_path("t2");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "unknown-kit",
            "file": "/tmp/test.xyz",
            "source": "// nothing"
        }
    });

    let resp = send_recv(&sock, &req);

    let error = resp
        .get("error")
        .expect("expected error field for unknown kit");
    let code = error
        .get("code")
        .and_then(|c| c.as_i64())
        .expect("expected error.code");
    assert_eq!(
        code, -33001,
        "unknown-kit must return error code -33001 (KitNotInManifest), got {}",
        code
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 3: content-determinism across kit dispatch.
// -------------------------------------------------------------------

/// Test 3: Same source + same kit => byte-identical linkBundleCid.
///
/// Uses the rust kit (always available) to verify dispatch determinism
/// without requiring any external binary.
#[test]
fn test3_kit_dispatch_content_deterministic() {
    let sock = unique_sock_path("t3");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let rust_source = r#"
/// #[ensures(result >= 0)]
pub fn abs_value(x: i64) -> i64 {
    if x < 0 { -x } else { x }
}
"#;

    let parse_req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "rust",
            "file": "/tmp/test_deterministic.rs",
            "source": rust_source
        }
    });

    // First parse.
    let _ = send_recv(&sock, &parse_req);
    let status_req = serde_json::json!({
        "jsonrpc": "2.0", "id": 2, "method": "projectStatus", "params": {}
    });
    let status1 = send_recv(&sock, &status_req);
    let cid1 = status1["result"]["linkBundleCid"]
        .as_str()
        .unwrap_or("")
        .to_string();

    // Flush and re-parse with identical source.
    let flush_req = serde_json::json!({
        "jsonrpc": "2.0", "id": 3, "method": "flushCache", "params": {}
    });
    let _ = send_recv(&sock, &flush_req);
    let _ = send_recv(&sock, &parse_req);
    let status2 = send_recv(&sock, &status_req);
    let cid2 = status2["result"]["linkBundleCid"]
        .as_str()
        .unwrap_or("")
        .to_string();

    assert!(
        !cid1.is_empty(),
        "linkBundleCid should be non-empty after parse"
    );
    assert_eq!(
        cid1, cid2,
        "same source must produce byte-identical linkBundleCid across two parse runs"
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 4: java kit dispatch returns diagnostics when sugar-lsp-java is on PATH.
// -------------------------------------------------------------------

/// Test 4: parseFile with kit="java" dispatches to the java lifter.
///
/// Skipped if `sugar-lsp-java` is not on PATH. The skip is printed to stdout
/// so CI can see why the test was skipped, not silently ignored.
///
/// Install via:
///   cd implementations/java/sugar-lift-java-core && \
///   mvn package -q && \
///   cp target/appassembler/bin/sugar-lsp-java ~/.local/bin/
///
/// When sugar-lsp-java is available, sends a tiny Java source and asserts:
///   - The response has a `result.diagnostics` array.
///   - `result.diagnostics` is an array (shape contract).
///   - No JSON-RPC error is returned.
#[test]
fn test4_java_kit_dispatch() {
    match rpc_binary_accepts_initialize("sugar-lsp-java", &["--rpc"]) {
        Ok(_) => {}
        Err(reason) => {
            println!(
                "SKIP test4_java_kit_dispatch: sugar-lsp-java is not usable ({reason}). \
                 Install via: cd implementations/java/sugar-lift-java-core && \
                 mvn package -q && cp target/appassembler/bin/sugar-lsp-java ~/.local/bin/"
            );
            return;
        }
    }

    let sock = unique_sock_path("t4");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let java_source = r#"package com.example;

public class Calculator {
    /** @sugar.contract post="result >= 0" */
    public int abs(int x) {
        return x < 0 ? -x : x;
    }
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "java",
            "file": "/tmp/test_Calculator.java",
            "source": java_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "java kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "java kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 6: cpp kit dispatch returns diagnostics when sugar-lsp-cpp is on PATH.
// -------------------------------------------------------------------

/// Test 6: parseFile with kit="cpp" dispatches to the cpp lifter.
///
/// Skipped if `sugar-lsp-cpp` is not on PATH. The skip is printed to stdout
/// so CI can see why the test was skipped, not silently ignored.
///
/// Install via:
///   cd implementations/cpp/sugar-lsp-cpp && \
///   g++ -std=c++17 -O2 -o sugar-lsp-cpp main.cpp && \
///   cp sugar-lsp-cpp ~/.local/bin/
///
/// When sugar-lsp-cpp is available, sends a tiny C++ source and asserts:
///   - The response has a `result.diagnostics` array.
///   - No JSON-RPC error is returned.
#[test]
fn test6_cpp_kit_dispatch() {
    if !binary_on_path("sugar-lsp-cpp") {
        println!(
            "SKIP test6_cpp_kit_dispatch: sugar-lsp-cpp not on PATH. \
             Install via: cd implementations/cpp/sugar-lsp-cpp && \
             g++ -std=c++17 -O2 -o sugar-lsp-cpp main.cpp && \
             cp sugar-lsp-cpp ~/.local/bin/"
        );
        return;
    }

    let sock = unique_sock_path("t6");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let cpp_source = r#"
// sugar:contract post="result >= 0"
int abs_value(int x) {
    return x < 0 ? -x : x;
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "cpp",
            "file": "/tmp/test_abs.cpp",
            "source": cpp_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "cpp kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "cpp kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 7: swift kit dispatch returns diagnostics when sugar-lsp-swift is on PATH.
// -------------------------------------------------------------------

/// Test 7: parseFile with kit="swift" dispatches to the swift lifter.
///
/// Skipped if `sugar-lsp-swift` is not on PATH. The skip is printed to stdout
/// so CI can see why the test was skipped, not silently ignored.
///
/// Install via:
///   cd implementations/swift && swift build -c release && \
///   cp .build/release/sugar-lsp-swift ~/.local/bin/
///
/// When sugar-lsp-swift is available, sends a tiny Swift source and asserts:
///   - The response has a `result.diagnostics` array.
///   - No JSON-RPC error is returned.
#[test]
fn test7_swift_kit_dispatch() {
    if !binary_on_path("sugar-lsp-swift") {
        println!(
            "SKIP test7_swift_kit_dispatch: sugar-lsp-swift not on PATH. \
             Install via: cd implementations/swift && swift build -c release && \
             cp .build/release/sugar-lsp-swift ~/.local/bin/"
        );
        return;
    }

    let sock = unique_sock_path("t7");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let swift_source = r#"
/// @sugar:contract post="result >= 0"
func absValue(_ x: Int) -> Int {
    return x < 0 ? -x : x
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "swift",
            "file": "/tmp/test_abs.swift",
            "source": swift_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "swift kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "swift kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 8: c kit dispatch returns diagnostics when sugar-lsp-c is on PATH.
// -------------------------------------------------------------------

/// Test 8: parseFile with kit="c" dispatches to the c lifter.
///
/// Skipped if `sugar-lsp-c` is not on PATH. The skip is printed to stdout
/// so CI can see why the test was skipped, not silently ignored.
///
/// Install via:
///   cd implementations/c/sugar-lsp-c && \
///   cc -std=c11 -Wall -o sugar-lsp-c main.c && \
///   cp sugar-lsp-c ~/.local/bin/
///
/// When sugar-lsp-c is available, sends a tiny C source and asserts:
///   - The response has a `result.diagnostics` array.
///   - No JSON-RPC error is returned.
#[test]
fn test8_c_kit_dispatch() {
    if !binary_on_path("sugar-lsp-c") {
        println!(
            "SKIP test8_c_kit_dispatch: sugar-lsp-c not on PATH. \
             Install via: cd implementations/c/sugar-lsp-c && \
             cc -std=c11 -Wall -o sugar-lsp-c main.c && \
             cp sugar-lsp-c ~/.local/bin/"
        );
        return;
    }

    let sock = unique_sock_path("t8");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let c_source = r#"
/* sugar:contract post="result >= 0" */
int abs_value(int x) {
    return x < 0 ? -x : x;
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "c",
            "file": "/tmp/test_abs.c",
            "source": c_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "c kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "c kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 9: zig kit dispatch returns diagnostics when sugar-lsp-zig is on PATH.
// -------------------------------------------------------------------

/// Test 9: parseFile with kit="zig" dispatches to the zig lifter.
///
/// Skipped if `sugar-lsp-zig` is not on PATH. The skip is printed to stdout
/// so CI can see why the test was skipped, not silently ignored.
///
/// Install via:
///   cd implementations/zig/sugar-lsp-zig && \
///   zig build -Doptimize=ReleaseSafe && \
///   cp zig-out/bin/sugar-lsp-zig ~/.local/bin/
///
/// When sugar-lsp-zig is available, sends a tiny Zig source and asserts:
///   - The response has a `result.diagnostics` array.
///   - No JSON-RPC error is returned.
#[test]
fn test9_zig_kit_dispatch() {
    if !binary_on_path("sugar-lsp-zig") {
        println!(
            "SKIP test9_zig_kit_dispatch: sugar-lsp-zig not on PATH. \
             Install via: cd implementations/zig/sugar-lsp-zig && \
             zig build -Doptimize=ReleaseSafe && \
             cp zig-out/bin/sugar-lsp-zig ~/.local/bin/"
        );
        return;
    }

    let sock = unique_sock_path("t9");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let zig_source = r#"
//sugar:contract post="result >= 0"
fn absValue(x: i64) i64 {
    return if (x < 0) -x else x;
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "zig",
            "file": "/tmp/test_abs.zig",
            "source": zig_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "zig kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "zig kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}

// -------------------------------------------------------------------
// Test 10: python kit dispatch returns diagnostics when sugar-lsp-python is on PATH.
// -------------------------------------------------------------------

/// Test 10: parseFile with kit="python" dispatches to the Python lifter.
///
/// Unlike the other optional kit-dispatch tests, this test installs a tiny
/// fixture `sugar-lsp-python` binary on PATH. The regression it pins is
/// linkerd's dispatch arm: Python must be routed like any other per-language
/// kit, not rejected inside Rust as unavailable.
#[test]
fn test10_python_kit_dispatch() {
    let fixture_bin_dir = install_fixture_python_lsp();

    let sock = unique_sock_path("t10");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let python_source = r#"
def test_positive():
    assert 1 > 0
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "python",
            "file": "/tmp/test_positive.py",
            "source": python_source
        }
    });

    let resp = send_recv(&sock, &req);

    assert!(
        resp.get("error").is_none(),
        "python kit parseFile returned unexpected error: {:?}",
        resp
    );
    assert!(
        resp["result"]["diagnostics"].is_array(),
        "python kit parseFile result must have diagnostics array: {:?}",
        resp
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
    std::fs::remove_dir_all(fixture_bin_dir).ok();
}

// -------------------------------------------------------------------
// Test 12: scala kit dispatch is registered.
// -------------------------------------------------------------------

/// Test 12: parseFile with kit="scala" must route to the Scala LSP lifter.
///
/// This does not require sugar-lsp-scala to be installed. In environments
/// without the binary, the correct behavior is LifterUnavailable (-33002) with
/// an install hint. UnknownKit (-33001) means linkerd cannot route Scala at all.
#[test]
fn test12_scala_kit_dispatch_registered() {
    let sock = unique_sock_path("t12");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let scala_source = r#"
def addOne(x: Int): Int = x + 1
def callAddOne(x: Int): Int = addOne(x)
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "scala",
            "file": "/tmp/Calls.scala",
            "source": scala_source
        }
    });

    let resp = send_recv(&sock, &req);

    if let Some(error) = resp.get("error") {
        let code = error.get("code").and_then(|c| c.as_i64()).unwrap_or(0);
        let message = error.get("message").and_then(|m| m.as_str()).unwrap_or("");
        assert_eq!(
            code, -33002,
            "scala kit must be registered; got wrong error: {:?}",
            resp
        );
        assert!(
            message.contains("sugar-lsp-scala"),
            "scala LifterUnavailable message should name the expected binary: {message}"
        );
    } else {
        assert!(
            resp["result"]["diagnostics"].is_array(),
            "scala kit parseFile result must have diagnostics array: {:?}",
            resp
        );
    }

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}
