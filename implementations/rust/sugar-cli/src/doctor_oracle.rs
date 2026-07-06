// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Language-specific oracle host probing for doctor.
//
// The doctor consumes this through OracleHostAdapter, so its policy remains
// substrate-level: requested, locatable, ready, engaged, converged.

use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct OracleHostEnv {
    pub requested: bool,
}

#[derive(Debug, Clone)]
pub struct OracleHostObservation {
    pub host: String,
    pub locatability: OracleHostLocatability,
    pub readiness: OracleHostReadiness,
    pub engagement: OracleHostEngagement,
    pub convergence: OracleResolutionConvergence,
}

impl OracleHostObservation {
    pub fn not_requested() -> Self {
        Self {
            host: "none".to_string(),
            locatability: OracleHostLocatability::NotRequested,
            readiness: OracleHostReadiness::NotRequested,
            engagement: OracleHostEngagement::NotRequested,
            convergence: OracleResolutionConvergence::NotRequested,
        }
    }
}

#[derive(Debug, Clone)]
pub enum OracleHostLocatability {
    NotRequested,
    Found {
        host_binary: String,
        rust_analyzer_binary: Option<String>,
        discovery: String,
    },
    Missing {
        missing: Vec<String>,
        detail: String,
    },
}

#[derive(Debug, Clone)]
pub enum OracleHostReadiness {
    NotRequested,
    Ready { detail: String },
    Degraded { detail: String },
    NotReady { detail: String },
}

#[derive(Debug, Clone)]
pub enum OracleHostEngagement {
    NotRequested,
    Engaged { detail: String },
    Unknown { detail: String },
}

#[derive(Debug, Clone)]
pub enum OracleResolutionConvergence {
    NotRequested,
    Deferred { detail: String },
    Converged { detail: String },
}

pub trait OracleHostAdapter {
    fn observe(&self, env: &OracleHostEnv) -> OracleHostObservation;
}

#[derive(Debug, Default, Clone, Copy)]
pub struct RustAnalyzerOracleAdapter;

impl OracleHostAdapter for RustAnalyzerOracleAdapter {
    fn observe(&self, env: &OracleHostEnv) -> OracleHostObservation {
        if !env.requested {
            return OracleHostObservation::not_requested();
        }

        let rust_analyzer = locate_rust_analyzer();
        let linkerd = locate_linkerd();
        let mut missing = Vec::new();
        if rust_analyzer.path.is_none() {
            missing.push("rust-analyzer".to_string());
        }
        if linkerd.path.is_none() {
            missing.push("sugar-linkerd".to_string());
        }

        if !missing.is_empty() {
            return OracleHostObservation {
                host: "rust-analyzer".to_string(),
                locatability: OracleHostLocatability::Missing {
                    detail: format!(
                        "missing oracle host prerequisite(s): {}",
                        missing.join(", ")
                    ),
                    missing,
                },
                readiness: OracleHostReadiness::NotReady {
                    detail: "oracle host is not locatable".to_string(),
                },
                engagement: OracleHostEngagement::Unknown {
                    detail: "engagement is observed at self-check time".to_string(),
                },
                convergence: OracleResolutionConvergence::Deferred {
                    detail: "oracle readiness cannot be established until the host is locatable"
                        .to_string(),
                },
            };
        }

        let linkerd_path = linkerd.path.expect("linkerd path checked above");
        let readiness = probe_linkerd_readiness(&linkerd_path);
        let convergence = match &readiness {
            OracleHostReadiness::Ready { .. } | OracleHostReadiness::Degraded { .. } => {
                OracleResolutionConvergence::Converged {
                    detail:
                        "resolution readiness is gated by linkerd rustAnalyzerReady; convergence harness removed"
                            .to_string(),
                }
            }
            OracleHostReadiness::NotRequested | OracleHostReadiness::NotReady { .. } => {
                OracleResolutionConvergence::Deferred {
                    detail: "resolution readiness was not reached".to_string(),
                }
            }
        };
        OracleHostObservation {
            host: "rust-analyzer".to_string(),
            locatability: OracleHostLocatability::Found {
                host_binary: linkerd_path.display().to_string(),
                rust_analyzer_binary: rust_analyzer.path.map(|p| p.display().to_string()),
                discovery: linkerd.discovery,
            },
            readiness,
            engagement: OracleHostEngagement::Unknown {
                detail: "oracle engagement is observed at self-check time".to_string(),
            },
            convergence,
        }
    }
}

#[derive(Debug)]
struct LocatedBinary {
    path: Option<PathBuf>,
    discovery: String,
}

fn locate_rust_analyzer() -> LocatedBinary {
    if let Some(path) = env_binary("SUGAR_RUST_ANALYZER") {
        return LocatedBinary {
            path: Some(path),
            discovery: "env".to_string(),
        };
    }
    if let Ok(out) = std::process::Command::new("rustup")
        .args(["which", "rust-analyzer"])
        .output()
    {
        if out.status.success() {
            let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !path.is_empty() {
                let pb = PathBuf::from(&path);
                if pb.is_file() {
                    return LocatedBinary {
                        path: Some(pb),
                        discovery: "rustup".to_string(),
                    };
                }
            }
        }
    }
    match which_binary("rust-analyzer") {
        Some(path) => LocatedBinary {
            path: Some(path),
            discovery: "path".to_string(),
        },
        None => LocatedBinary {
            path: None,
            discovery: "missing".to_string(),
        },
    }
}

fn locate_linkerd() -> LocatedBinary {
    if let Some(path) = env_binary("SUGAR_LINKERD_BIN") {
        return LocatedBinary {
            path: Some(path),
            discovery: "env".to_string(),
        };
    }
    match which_binary("sugar-linkerd") {
        Some(path) => LocatedBinary {
            path: Some(path),
            discovery: "path".to_string(),
        },
        None => LocatedBinary {
            path: None,
            discovery: "missing".to_string(),
        },
    }
}

fn env_binary(key: &str) -> Option<PathBuf> {
    let value = std::env::var(key).ok()?;
    if value.is_empty() {
        return None;
    }
    let path = PathBuf::from(value);
    if path.is_file() && is_executable(&path) {
        Some(path)
    } else {
        None
    }
}

fn which_binary(name: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        let candidate = dir.join(name);
        if candidate.is_file() && is_executable(&candidate) {
            return Some(candidate);
        }
    }
    None
}

fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        return path
            .metadata()
            .map(|m| m.permissions().mode() & 0o111 != 0)
            .unwrap_or(false);
    }
    #[cfg(not(unix))]
    {
        path.is_file()
    }
}

fn probe_linkerd_readiness(binary: &Path) -> OracleHostReadiness {
    #[cfg(unix)]
    {
        match probe_linkerd_rust_analyzer_ready(binary) {
            Ok(detail) => OracleHostReadiness::Ready { detail },
            Err(error) => OracleHostReadiness::NotReady {
                detail: format!("sugar-linkerd did not report rust-analyzer ready: {error}"),
            },
        }
    }
    #[cfg(not(unix))]
    {
        let _ = binary;
        OracleHostReadiness::Degraded {
            detail: "sugar-linkerd readiness probing uses Unix sockets on this platform"
                .to_string(),
        }
    }
}

#[cfg(unix)]
fn probe_linkerd_rust_analyzer_ready(binary: &Path) -> Result<String, String> {
    use serde_json::json;
    use std::os::unix::net::UnixStream;
    use std::process::{Command, Stdio};
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| format!("system time: {e}"))?
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("sugar-doctor-oracle-{stamp}"));
    std::fs::create_dir_all(&dir).map_err(|e| format!("create temp dir: {e}"))?;
    let socket = dir.join("linkerd.sock");
    let snapshot = dir.join("snapshot.bin");
    let workspace_root =
        std::env::current_dir().map_err(|e| format!("resolve current workspace: {e}"))?;
    let ready_timeout_ms = oracle_ready_timeout_ms();

    let mut child = Command::new(binary)
        .arg("--socket")
        .arg(&socket)
        .arg("--project-cid")
        .arg(format!("doctor-{stamp}"))
        .arg("--idle-timeout-ms")
        .arg("1000")
        .arg("--snapshot")
        .arg(&snapshot)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("spawn {}: {e}", binary.display()))?;

    let deadline = Instant::now() + Duration::from_secs(5);
    let mut stream = loop {
        match UnixStream::connect(&socket) {
            Ok(stream) => break stream,
            Err(error) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    let _ = std::fs::remove_dir_all(&dir);
                    return Err(format!("socket did not become ready: {error}"));
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        }
    };
    stream
        .set_read_timeout(Some(Duration::from_millis(ready_timeout_ms + 5_000)))
        .map_err(|e| format!("set readiness read timeout: {e}"))?;

    let status = send_rpc(
        &mut stream,
        &json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "rustAnalyzerReady",
            "params": {
                "workspaceRoot": workspace_root,
                "timeoutMs": ready_timeout_ms,
            }
        }),
    )
    .and_then(|resp| {
        let Some(result) = resp.get("result") else {
            return Err(format!(
                "rustAnalyzerReady returned non-result response: {resp}"
            ));
        };
        let ready = result
            .get("ready")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let phase = result
            .get("phase")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let detail = result
            .get("detail")
            .and_then(|v| v.as_str())
            .unwrap_or("no detail");
        if ready {
            Ok(format!(
                "sugar-linkerd spawned and reported rust-analyzer ready ({phase}: {detail})"
            ))
        } else {
            Err(format!("phase={phase}; {detail}"))
        }
    });
    let detail = match status {
        Ok(detail) => detail,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = std::fs::remove_dir_all(&dir);
            return Err(error);
        }
    };

    let _ = send_rpc(
        &mut stream,
        &json!({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}}),
    );
    let _ = child.wait();
    let _ = std::fs::remove_dir_all(&dir);
    Ok(detail)
}

fn oracle_ready_timeout_ms() -> u64 {
    std::env::var("SUGAR_ORACLE_READY_TIMEOUT_MS")
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .filter(|v| *v > 0)
        .unwrap_or(300_000)
}

#[cfg(unix)]
fn send_rpc(
    stream: &mut std::os::unix::net::UnixStream,
    request: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    use std::io::{BufRead, Write};

    let line = serde_json::to_string(request).map_err(|e| format!("encode request: {e}"))?;
    writeln!(stream, "{line}").map_err(|e| format!("write request: {e}"))?;
    stream.flush().map_err(|e| format!("flush request: {e}"))?;

    let mut reader = std::io::BufReader::new(
        stream
            .try_clone()
            .map_err(|e| format!("clone stream: {e}"))?,
    );
    let mut response = String::new();
    let read = reader
        .read_line(&mut response)
        .map_err(|e| format!("read response: {e}"))?;
    if read == 0 {
        return Err("daemon closed connection without response".to_string());
    }
    serde_json::from_str(response.trim()).map_err(|e| format!("decode response: {e}"))
}
