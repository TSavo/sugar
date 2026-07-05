// SPDX-License-Identifier: MIT OR Apache-2.0
//
// daemon_client.rs: thin client for the sugar-linkerd daemon.
//
// Implements `connect_or_spawn` (connect to an existing daemon or spawn one)
// and `send_parse_file` (forward a `parseFile` JSON-RPC and return diagnostics).
//
// This module uses only `std`: no tokio, no async. The parent binary speaks
// synchronous NDJSON on stdin/stdout; there is no need for an async runtime here.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value as Json;

/// Connect to the daemon at `socket_path`, spawning it first if it isn't running.
///
/// Spawn args follow the daemon's CLI:
///   `sugar-linkerd --socket <path> --project-cid <cid>
///                     --idle-timeout-ms 300000 --snapshot <snap>`
///
/// The snapshot path is derived as `<socket_path>.snap` for simplicity; the
/// daemon CLI accepts any path, and determinism only requires that the same
/// socket path implies the same snapshot path (which this achieves).
///
/// Returns a connected `UnixStream` or an `io::Error`.
pub fn connect_or_spawn(socket_path: &Path, project_cid: &str) -> std::io::Result<UnixStream> {
    // Fast path: daemon already running.
    if let Ok(stream) = UnixStream::connect(socket_path) {
        return Ok(stream);
    }

    // Derive a snapshot path alongside the socket.
    let snap_path = {
        let mut p = socket_path.to_path_buf();
        let file_name = p
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "linkerd".to_string());
        p.set_file_name(format!("{file_name}.snap"));
        p
    };

    // Spawn the daemon. Detach stdio so it doesn't inherit the LSP plugin's
    // stdin/stdout (the plugin reads from its own stdin in the main loop).
    let _child = Command::new("sugar-linkerd")
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
    // We intentionally don't join the child: it's a long-running daemon.

    // Poll for the socket to appear (max 5 s, 50 ms intervals).
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

/// Send a `parseFile` JSON-RPC to the daemon over `stream` and return the
/// `diagnostics` array from the response, or an error.
///
/// Request shape (spec R5):
/// ```json
/// { "jsonrpc":"2.0","id":1,"method":"parseFile",
///   "params":{"kitId":"rust","file":"<path>","source":"<src>"} }
/// ```
///
/// Response shape:
/// ```json
/// { "jsonrpc":"2.0","id":1,"result":{"diagnostics":[...]} }
/// ```
///
/// `kit_id` MUST be one of the KitIds from spec §1 (e.g. `"rust"`).
pub fn send_parse_file(
    stream: &mut UnixStream,
    kit_id: &str,
    file: &str,
    source: &str,
    request_id: u64,
) -> std::io::Result<Vec<Json>> {
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

    let resp: Json = serde_json::from_str(resp_line.trim()).map_err(|e| {
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
