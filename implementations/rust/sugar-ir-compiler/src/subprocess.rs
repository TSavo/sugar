// SPDX-License-Identifier: Apache-2.0
//
// JSON-RPC over stdio subprocess client. Wraps a binary that speaks
// the protocol defined in protocol/specs/2026-04-30-ir-compiler-protocol.md
// behind the same IrCompiler trait used for in-process Rust impls.
//
// Framing: line-delimited JSON. One request per stdin line, one
// response per stdout line. stderr is the plugin's logging channel
// and is intentionally not consumed here.

use std::io::{Read, Write};
#[cfg(unix)]
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde_json::{json, Value as Json};
use tracing::{debug, info, warn};

use crate::{Capabilities, CompileError, CompiledFormula, IrCompiler, PROTOCOL_VERSION};

/// JSON-RPC subprocess wrapper. The child is spawned on construction,
/// the handshake is performed once, capabilities are cached. Subsequent
/// `compile` calls reuse the long-lived process.
pub struct JsonRpcCompiler {
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    cached_caps: Capabilities,
    rpc_timeout: Option<Duration>,
    inner: Mutex<ChildIo>,
    next_id: Mutex<u64>,
}

struct ChildIo {
    child: Child,
    stdin: ChildStdin,
    stdout: ChildStdout,
}

impl JsonRpcCompiler {
    /// Spawn the subprocess and perform the handshake. Returns an
    /// error if the binary cannot be launched or rejects the protocol
    /// version.
    pub fn spawn(binary: impl AsRef<Path>) -> Result<Self, CompileError> {
        let command = vec![binary.as_ref().to_string_lossy().to_string()];
        Self::spawn_command(&command, None)
    }

    /// Spawn a subprocess command and perform the protocol handshake.
    /// `command[0]` is the binary; remaining entries are argv.
    pub fn spawn_command(
        command: &[String],
        working_dir: Option<&Path>,
    ) -> Result<Self, CompileError> {
        let (program, args) = command
            .split_first()
            .ok_or_else(|| CompileError::Transport("compiler command is empty".into()))?;
        let rendered = render_command(command);
        let rpc_timeout = default_rpc_timeout();
        info!(
            command = %rendered,
            working_dir = working_dir.map(|p| p.display().to_string()).as_deref().unwrap_or("<inherit>"),
            timeout_ms = rpc_timeout.map(|d| d.as_millis() as u64),
            "ir compiler rpc: spawning subprocess"
        );
        let mut cmd = Command::new(program);
        cmd.args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        if let Some(dir) = working_dir {
            cmd.current_dir(dir);
        }
        let mut child = cmd.spawn().map_err(|e| match working_dir {
            Some(dir) => {
                CompileError::Transport(format!("spawn {rendered} in {}: {e}", dir.display()))
            }
            None => CompileError::Transport(format!("spawn {rendered}: {e}")),
        })?;
        debug!(
            command = %rendered,
            pid = child.id(),
            "ir compiler rpc: subprocess spawned"
        );
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| CompileError::Transport("child stdin missing".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| CompileError::Transport("child stdout missing".into()))?;

        let mut io = ChildIo {
            child,
            stdin,
            stdout,
        };

        let caps = handshake(&mut io, rpc_timeout)?;
        info!(
            command = %rendered,
            pid = io.child.id(),
            compiler = %caps.name,
            version = %caps.version,
            dialects = ?caps.dialects,
            "ir compiler rpc: handshake complete"
        );

        Ok(Self {
            command: command.to_vec(),
            working_dir: working_dir.map(Path::to_path_buf),
            cached_caps: caps,
            rpc_timeout,
            inner: Mutex::new(io),
            next_id: Mutex::new(2),
        })
    }

    /// Path to the binary backing this compiler.
    pub fn binary_path(&self) -> &Path {
        Path::new(self.command.first().map(String::as_str).unwrap_or_default())
    }

    pub fn command(&self) -> &[String] {
        &self.command
    }

    pub fn working_dir(&self) -> Option<&Path> {
        self.working_dir.as_deref()
    }
}

/// Lazily-spawned JSON-RPC compiler declared by a manifest. Capabilities come
/// from the manifest so registering the compiler does not start optional
/// binaries; the child is spawned only when a solver actually needs that
/// dialect.
pub struct LazyJsonRpcCompiler {
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    manifest_caps: Capabilities,
    inner: Mutex<Option<JsonRpcCompiler>>,
}

impl LazyJsonRpcCompiler {
    pub fn new(
        command: Vec<String>,
        working_dir: Option<PathBuf>,
        manifest_caps: Capabilities,
    ) -> Self {
        Self {
            command,
            working_dir,
            manifest_caps,
            inner: Mutex::new(None),
        }
    }
}

impl IrCompiler for LazyJsonRpcCompiler {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError> {
        let mut inner = self.inner.lock().unwrap();
        if inner.is_none() {
            debug!(
                command = %render_command(&self.command),
                working_dir = self
                    .working_dir
                    .as_ref()
                    .map(|p| p.display().to_string())
                    .as_deref()
                    .unwrap_or("<inherit>"),
                dialect,
                "ir compiler rpc: lazy spawn"
            );
            *inner = Some(JsonRpcCompiler::spawn_command(
                &self.command,
                self.working_dir.as_deref(),
            )?);
        }
        let result = inner
            .as_ref()
            .ok_or_else(|| CompileError::Transport("compiler spawn failed".into()))?
            .compile(ir, dialect);
        if matches!(result, Err(CompileError::Transport(_))) {
            warn!(
                command = %render_command(&self.command),
                dialect,
                "ir compiler rpc: dropping subprocess after transport failure"
            );
            *inner = None;
        }
        result
    }

    fn capabilities(&self) -> Capabilities {
        self.manifest_caps.clone()
    }
}

impl IrCompiler for JsonRpcCompiler {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError> {
        let id = {
            let mut g = self.next_id.lock().unwrap();
            let v = *g;
            *g += 1;
            v
        };
        let req = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": "sugar.ir.compile",
            "params": {
                "ir_json": ir,
                "target_dialect": dialect,
            }
        });
        let mut io = self.inner.lock().unwrap();
        info!(
            command = %render_command(&self.command),
            pid = io.child.id(),
            request_id = id,
            dialect,
            ir_bytes = ir.to_string().len(),
            "ir compiler rpc: compile request"
        );
        let resp = exchange(&mut io, &req, "sugar.ir.compile", self.rpc_timeout)?;
        if let Some(err) = resp.get("error") {
            warn!(
                command = %render_command(&self.command),
                pid = io.child.id(),
                request_id = id,
                dialect,
                error = %err,
                "ir compiler rpc: compile error response"
            );
            return Err(rpc_error_to_compile_error(err));
        }
        let result = resp
            .get("result")
            .ok_or_else(|| CompileError::Transport("no result in compile response".into()))?;
        let compiled = serde_json::from_value::<CompiledFormula>(result.clone())
            .map_err(|e| CompileError::Transport(format!("compile result decode: {e}")))?;
        info!(
            command = %render_command(&self.command),
            pid = io.child.id(),
            request_id = id,
            dialect,
            free_vars = compiled.free_vars.len(),
            opacities = compiled.opacity_manifest.opacities.len(),
            output_bytes = compiled.script().len(),
            "ir compiler rpc: compile response"
        );
        Ok(compiled)
    }

    fn capabilities(&self) -> Capabilities {
        self.cached_caps.clone()
    }
}

fn handshake(io: &mut ChildIo, timeout: Option<Duration>) -> Result<Capabilities, CompileError> {
    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.ir.handshake",
        "params": {
            "sugar_version": env!("CARGO_PKG_VERSION"),
            "protocol_version": PROTOCOL_VERSION,
        }
    });
    debug!(
        pid = io.child.id(),
        timeout_ms = timeout.map(|d| d.as_millis() as u64),
        "ir compiler rpc: handshake request"
    );
    let resp = exchange(io, &req, "sugar.ir.handshake", timeout)?;
    if let Some(err) = resp.get("error") {
        return Err(rpc_error_to_compile_error(err));
    }
    let result = resp
        .get("result")
        .ok_or_else(|| CompileError::Transport("no result in handshake".into()))?;
    let caps: Capabilities = serde_json::from_value(result.clone())
        .map_err(|e| CompileError::Transport(format!("handshake decode: {e}")))?;
    if caps.protocol_version != PROTOCOL_VERSION {
        return Err(CompileError::Transport(format!(
            "protocol version mismatch: plugin reports {}, expected {}",
            caps.protocol_version, PROTOCOL_VERSION
        )));
    }
    Ok(caps)
}

fn exchange(
    io: &mut ChildIo,
    req: &Json,
    method: &str,
    timeout: Option<Duration>,
) -> Result<Json, CompileError> {
    let line =
        serde_json::to_string(req).map_err(|e| CompileError::Transport(format!("encode: {e}")))?;
    writeln!(io.stdin, "{line}").map_err(|e| CompileError::Transport(format!("write: {e}")))?;
    io.stdin
        .flush()
        .map_err(|e| CompileError::Transport(format!("flush: {e}")))?;

    let buf = read_response_line(io, method, timeout)?;
    serde_json::from_str(&buf).map_err(|e| CompileError::Transport(format!("decode: {e}")))
}

fn read_response_line(
    io: &mut ChildIo,
    method: &str,
    timeout: Option<Duration>,
) -> Result<String, CompileError> {
    let started = Instant::now();
    let mut buf = Vec::new();
    loop {
        let remaining = timeout.and_then(|timeout| timeout.checked_sub(started.elapsed()));
        if timeout.is_some() && remaining.is_none() {
            kill_child_after_timeout(io, method, timeout.unwrap());
            return Err(CompileError::Transport(format!(
                "{method} timed out after {}ms",
                timeout.unwrap().as_millis()
            )));
        }
        if let Err(err) = wait_for_stdout(&io.stdout, remaining, method) {
            if matches!(&err, CompileError::Transport(msg) if msg.contains("timed out")) {
                kill_child_after_timeout(io, method, timeout.unwrap_or_default());
            }
            return Err(err);
        }
        let mut byte = [0u8; 1];
        match io.stdout.read(&mut byte) {
            Ok(0) if buf.is_empty() => {
                return Err(CompileError::Transport("plugin closed stdout".into()));
            }
            Ok(0) => {
                return Err(CompileError::Transport(
                    "plugin closed stdout before newline".into(),
                ));
            }
            Ok(_) => {
                buf.push(byte[0]);
                if byte[0] == b'\n' {
                    return String::from_utf8(buf)
                        .map_err(|e| CompileError::Transport(format!("utf8 decode: {e}")));
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(CompileError::Transport(format!("read: {e}"))),
        }
    }
}

#[cfg(unix)]
fn wait_for_stdout(
    stdout: &ChildStdout,
    remaining: Option<Duration>,
    method: &str,
) -> Result<(), CompileError> {
    loop {
        let timeout_ms = remaining.map(duration_to_poll_timeout_ms).unwrap_or(-1);
        let mut fd = libc::pollfd {
            fd: stdout.as_raw_fd(),
            events: libc::POLLIN | libc::POLLHUP | libc::POLLERR,
            revents: 0,
        };
        let rc = unsafe { libc::poll(&mut fd, 1, timeout_ms) };
        if rc == 0 {
            return Err(CompileError::Transport(format!(
                "{method} timed out waiting for compiler stdout"
            )));
        }
        if rc < 0 {
            let err = std::io::Error::last_os_error();
            if err.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(CompileError::Transport(format!("poll stdout: {err}")));
        }
        return Ok(());
    }
}

#[cfg(not(unix))]
fn wait_for_stdout(
    _stdout: &ChildStdout,
    _remaining: Option<Duration>,
    _method: &str,
) -> Result<(), CompileError> {
    Ok(())
}

fn duration_to_poll_timeout_ms(duration: Duration) -> i32 {
    let ms = duration.as_millis();
    if ms == 0 && duration.is_zero() {
        0
    } else if ms == 0 {
        1
    } else if ms > i32::MAX as u128 {
        i32::MAX
    } else {
        ms as i32
    }
}

fn kill_child_after_timeout(io: &mut ChildIo, method: &str, timeout: Duration) {
    warn!(
        pid = io.child.id(),
        method,
        timeout_ms = timeout.as_millis() as u64,
        "ir compiler rpc: killing subprocess after timeout"
    );
    let _ = io.child.kill();
    let _ = io.child.wait();
}

fn default_rpc_timeout() -> Option<Duration> {
    if let Ok(v) = std::env::var("SUGAR_IR_COMPILER_TIMEOUT_MS") {
        return match v.trim().parse::<u64>() {
            Ok(0) => None,
            Ok(n) => Some(Duration::from_millis(n)),
            Err(_) => Some(Duration::from_secs(30)),
        };
    }
    match std::env::var("SUGAR_IR_COMPILER_TIMEOUT_SECS") {
        Ok(v) => match v.trim().parse::<u64>() {
            Ok(0) => None,
            Ok(n) => Some(Duration::from_secs(n)),
            Err(_) => Some(Duration::from_secs(30)),
        },
        Err(_) => Some(Duration::from_secs(30)),
    }
}

fn rpc_error_to_compile_error(err: &Json) -> CompileError {
    let code = err.get("code").and_then(|v| v.as_i64()).unwrap_or(0);
    let msg = err
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("(no message)")
        .to_string();
    let data = err
        .get("data")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    match code {
        2000 => CompileError::UnsupportedDialect(data.unwrap_or(msg)),
        2001 => CompileError::UnsupportedSort(data.unwrap_or(msg)),
        2002 => CompileError::UnsupportedPredicate(data.unwrap_or(msg)),
        2003 => CompileError::MalformedIr(data.unwrap_or(msg)),
        2004 => CompileError::Internal(data.unwrap_or(msg)),
        _ => CompileError::Transport(format!("rpc error {code}: {msg}")),
    }
}

fn render_command(command: &[String]) -> String {
    command.join(" ")
}
