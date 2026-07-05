// SPDX-License-Identifier: MIT OR Apache-2.0
//
// concurrent_subprocess_kits.rs - regression test for issue #421:
// concurrent subprocess kit lifters under load (spawn_blocking integration).
//
// Background: PR #420 wrapped subprocess-based kit lifter blocking I/O in
// tokio::task::spawn_blocking to prevent executor stall under concurrent load.
// This test verifies that regression by submitting N concurrent parseFile requests
// all targeting subprocess kits and asserting they complete in parallel (wall-clock
// time roughly max(per_request_time), not sum(per_request_times)).
//
// Test design:
// 1. Spawn the linkerd daemon.
// 2. Fire N concurrent parseFile requests targeting the same subprocess kit
//    (all to the go kit, which is the most commonly available).
// 3. Measure wall-clock time for all N to complete.
// 4. Assert time is sublinear in N (indicating parallelism).
// 5. Assert no response carries LifterUnavailable (-33002) or JoinError.
//
// If spawn_blocking is removed or bypassed, requests will serialize,
// and the wall-clock time will scale linearly with N.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

fn daemon_bin() -> PathBuf {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
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

fn unique_sock_path(prefix: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "sugar-linkerd-conc-{}-{}.sock",
        prefix,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos())
            .unwrap_or(0)
    ))
}

fn spawn_daemon(sock: &PathBuf) -> Child {
    let snap = std::env::temp_dir().join(format!(
        "conc-snap-{}.bin",
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
    stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
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

fn binary_on_path(name: &str) -> bool {
    if let Ok(path_var) = std::env::var("PATH") {
        for dir in path_var.split(':') {
            let candidate = PathBuf::from(dir).join(name);
            if candidate.is_file() {
                return true;
            }
        }
    }
    false
}

// Concurrent subprocess kit lifters regression test.
//
// Fires N concurrent parseFile requests to the go kit and verifies all
// complete in parallel (wall-clock time sublinear in N).
//
// This test is skipped if sugar-lsp-go is not on PATH.
#[test]
fn test_concurrent_subprocess_kit_lifters() {
    if !binary_on_path("sugar-lsp-go") {
        println!(
            "SKIP test_concurrent_subprocess_kit_lifters: sugar-lsp-go not on PATH. \
             Install via: cd implementations/go && go install ./cmd/sugar-lsp-go"
        );
        return;
    }

    let sock = unique_sock_path("t-conc");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    // Simple go source that takes a bit of time to process (ensures subprocess
    // overhead is not negligible and parallelism is detectable).
    let go_source = r#"package main

//sugar:contract
func FibRecursive(n int) int {
    if n <= 1 { return n }
    return FibRecursive(n-1) + FibRecursive(n-2)
}

//sugar:contract post="result >= 0"
func Add(a, b int) int {
    return a + b
}

//sugar:contract post="result <= 0"
func Negate(x int) int {
    return -x
}
"#;

    const NUM_CONCURRENT_REQUESTS: usize = 5;

    let sock = Arc::new(sock);
    let mut handles = vec![];
    let results = Arc::new(Mutex::new(vec![]));

    let start = Instant::now();

    // Spawn N threads, each sending a concurrent parseFile request.
    for i in 0..NUM_CONCURRENT_REQUESTS {
        let sock_clone = Arc::clone(&sock);
        let results_clone = Arc::clone(&results);
        let source_clone = go_source.to_string();

        let handle = std::thread::spawn(move || {
            let req = serde_json::json!({
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "parseFile",
                "params": {
                    "kitId": "go",
                    "file": format!("/tmp/test_conc_{}.go", i),
                    "source": source_clone
                }
            });

            let resp = send_recv(&sock_clone, &req);

            // Check for errors.
            if let Some(err) = resp.get("error") {
                let code = err.get("code").and_then(|c| c.as_i64()).unwrap_or(-1);
                let message = err
                    .get("message")
                    .and_then(|m| m.as_str())
                    .unwrap_or("unknown");
                eprintln!("Request {} returned error code {}: {}", i, code, message);
                results_clone.lock().unwrap().push((i, false, code));
                return;
            }

            // Check for success.
            if !resp
                .get("result")
                .and_then(|r| r.get("diagnostics"))
                .is_some()
            {
                eprintln!(
                    "Request {} response missing result.diagnostics: {:?}",
                    i, resp
                );
                results_clone.lock().unwrap().push((i, false, -999));
                return;
            }

            results_clone.lock().unwrap().push((i, true, 0));
        });

        handles.push(handle);
    }

    // Wait for all threads to complete.
    for handle in handles {
        handle.join().expect("thread join failed");
    }

    let elapsed = start.elapsed();

    // Verify all requests succeeded.
    let res_vec = results.lock().unwrap();
    for (idx, success, code) in res_vec.iter() {
        assert!(success, "Request {} failed with code {}", idx, code);
    }

    // Check for parallelism: if requests ran serially, elapsed would be
    // roughly NUM_CONCURRENT_REQUESTS * per_request_time.
    // If parallel, elapsed ~= per_request_time.
    //
    // We use a conservative check: elapsed should be < 2 * per_single_request_time.
    // A single request to the go kit typically takes 200-500ms; allowing 2x gives
    // plenty of slack for system variance.
    //
    // If spawn_blocking is removed (regression), requests serialize, and elapsed
    // will be ~NUM_CONCURRENT_REQUESTS * 300ms = 1500ms, which fails this check.
    //
    // Heuristic: if all N requests ran sequentially, total would be > 1s (5 requests * 200ms).
    // If they ran in parallel, total should be < 1s. We allow 2s as a generous bound.
    let parallelism_threshold = Duration::from_millis(800);

    println!(
        "Concurrent requests completed in {:.2}s (threshold for parallelism: {:.2}s)",
        elapsed.as_secs_f64(),
        parallelism_threshold.as_secs_f64()
    );

    assert!(
        elapsed < parallelism_threshold,
        "Concurrent {} requests took {:.2}s, expected < {:.2}s. \
         This suggests requests ran serially, not in parallel. \
         Likely cause: spawn_blocking wrapper removed or bypassed.",
        NUM_CONCURRENT_REQUESTS,
        elapsed.as_secs_f64(),
        parallelism_threshold.as_secs_f64()
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&**sock).ok();
}

// Simpler variant: measure per-request latency to understand baseline.
// This test is skipped if sugar-lsp-go is not on PATH.
#[test]
fn test_single_subprocess_kit_baseline() {
    if !binary_on_path("sugar-lsp-go") {
        println!("SKIP test_single_subprocess_kit_baseline: sugar-lsp-go not on PATH");
        return;
    }

    let sock = unique_sock_path("t-baseline");
    let _ = std::fs::remove_file(&sock);

    let mut child = spawn_daemon(&sock);

    assert!(
        wait_for_socket(&sock, Duration::from_secs(5)),
        "daemon socket did not appear"
    );

    let go_source = r#"package main

//sugar:contract
func Baseline(x int) int {
    return x + 1
}
"#;

    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "parseFile",
        "params": {
            "kitId": "go",
            "file": "/tmp/test_baseline.go",
            "source": go_source
        }
    });

    let start = Instant::now();
    let resp = send_recv(&sock, &req);
    let elapsed = start.elapsed();

    assert!(
        resp.get("error").is_none(),
        "baseline request returned error: {:?}",
        resp
    );
    assert!(
        resp.get("result")
            .and_then(|r| r.get("diagnostics"))
            .is_some(),
        "baseline request response missing result.diagnostics: {:?}",
        resp
    );

    println!(
        "Single subprocess kit (go) request latency: {:.2}s",
        elapsed.as_secs_f64()
    );

    shutdown(&sock);
    child.wait().ok();
    std::fs::remove_file(&sock).ok();
}
