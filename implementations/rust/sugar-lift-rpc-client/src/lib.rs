// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-lift-rpc-client
//
// THE SEVER (shared transport): the rust `#[requires]`/`#[ensures]`
// contract lifter (`sugar-lift-contracts`) is a real RPC kit
// (`contracts_rpc` bin). The substrate's IN-PROCESS callers
// (`sugar-lift`, `sugar-build`, `sugar-lsp-rust`) USED to
// statically link `sugar_lift_contracts::lift_file`. They now reach
// the lifter THROUGH this crate, which:
//
//   1. RESOLVES the `contracts_rpc` binary path (one resolver, shared by
//      all callers so the determinism-critical resolution can never drift
//      between them).
//   2. SPAWNS it and drives the NDJSON `initialize` / `lift` / `shutdown`
//      protocol (the same protocol the CLI's `cmd_mint` drives).
//   3. Returns the RAW `ir-document` JSON `Value`.
//
// It is a TRUE LEAF: serde_json + std only. It does NOT depend on
// `sugar-ir-symbolic`, so callers that want typed `ContractDecl`s parse
// the returned `ir` array themselves (via `parse_document`), and callers
// that only need the JSON (lsp-rust) forward it directly. It does NOT
// depend on `libsugar`, so the leaf build/lsp crates stay free of the
// proof/crypto stack their own comments warn against.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::{json, Value};
use sugar_proof_envelope::{compute_formula_cid, MementoCid};

/// Process-window cache for RPC questions. There is deliberately no clear or
/// eviction method. Dropping the owning RPC client is the only invalidation
/// operation, so a consistency window can never be half-invalidated.
#[derive(Debug, Default, Clone)]
pub struct QuestionCache {
    answers: BTreeMap<MementoCid, Value>,
    hits: usize,
    misses: usize,
}

impl QuestionCache {
    pub fn ask<E>(
        &mut self,
        question: &Value,
        wire: impl FnOnce() -> Result<Value, E>,
    ) -> Result<Value, E> {
        let identity = json!({
            "workspace_root": question.get("workspace_root").cloned().unwrap_or(Value::Null),
            "level": question.get("level").cloned().unwrap_or(Value::Null),
            "at": question.get("at").cloned().unwrap_or(Value::Null),
            "seek": question.get("seek").cloned().unwrap_or(Value::Bool(false)),
            "options": question.get("options").cloned().unwrap_or_else(|| json!({})),
        });
        let question_cid = MementoCid::try_parse(compute_formula_cid(&identity))
            .expect("canonical question hash is a valid memento CID");
        if let Some(answer) = self.answers.get(&question_cid) {
            self.hits += 1;
            tracing::info!(
                target: "sugar::rpc_cache",
                event = "rpc_question_cache_hit",
                question_cid = %question_cid,
                hits = self.hits,
                misses = self.misses,
            );
            return Ok(answer.clone());
        }
        self.misses += 1;
        tracing::info!(
            target: "sugar::rpc_cache",
            event = "rpc_question_cache_miss",
            question_cid = %question_cid,
            hits = self.hits,
            misses = self.misses,
        );
        let answer = wire()?;
        self.answers.entry(question_cid).or_insert(answer.clone());
        Ok(answer)
    }

    pub fn hits(&self) -> usize {
        self.hits
    }

    pub fn misses(&self) -> usize {
        self.misses
    }
}

/// Environment override for the `contracts_rpc` binary path. When set,
/// it wins over the `current_exe`-relative search. Mirrors the
/// absolute-path injection the witness manifests already use (run.sh
/// substitutes the built binary's path).
pub const CONTRACTS_RPC_ENV: &str = "SUGAR_CONTRACTS_RPC";

/// Override for the `cargo run` fallback's `--target-dir`. When unset, a
/// fixed subdir of the system temp dir is used (see [`cargo_run_kit`]).
pub const CONTRACTS_RPC_TARGET_DIR_ENV: &str = "SUGAR_CONTRACTS_RPC_TARGET_DIR";

/// Fixed temp subdir for the `cargo run` fallback's separate target dir.
/// Stable across calls so the kit is built once, not per `lift_pass` file.
const CONTRACTS_RPC_FALLBACK_TARGET_SUBDIR: &str = "sugar-contracts-rpc-fallback-target";

/// The `contracts_rpc` binary name (cargo target name).
const CONTRACTS_RPC_BIN: &str = "contracts_rpc";

/// A resolved way to RUN the `contracts_rpc` kit. Either a prebuilt runnable
/// binary, or the portable `cargo run` invocation that builds-and-runs it.
///
/// The cargo-run form exists for the CI condition that `cargo test` (with no
/// prior `cargo build`) produces the TEST HARNESS
/// (`target/<profile>/deps/contracts_rpc-<hash>`) but NOT the runnable bin
/// (`target/<profile>/contracts_rpc`). When the built bin is absent at every
/// resolved path, `cargo run` always has a way to produce and run the kit.
#[derive(Debug, Clone)]
pub enum ResolvedKit {
    /// A prebuilt runnable binary (production: the showcase's `sugar`
    /// binary has `contracts_rpc` as a sibling). Fast path, no rebuild.
    Bin(PathBuf),
    /// `cargo run --quiet --manifest-path <root>/Cargo.toml -p
    /// sugar-lift-contracts --bin contracts_rpc --`. Same code as the
    /// built bin, so output (and therefore CIDs) is byte-identical.
    CargoRun { argv: Vec<String> },
}

impl ResolvedKit {
    /// The program + args to spawn (the `--rpc`-style trailing `--` is
    /// already included for the cargo-run form; the bin needs no args).
    fn command(&self) -> (String, Vec<String>) {
        match self {
            Self::Bin(p) => (p.display().to_string(), Vec::new()),
            Self::CargoRun { argv } => (argv[0].clone(), argv[1..].to_vec()),
        }
    }
}

#[derive(Debug)]
pub enum RpcClientError {
    BinNotFound(String),
    Spawn(String),
    Io(String),
    Protocol(String),
}

impl std::fmt::Display for RpcClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BinNotFound(m) => write!(f, "contracts_rpc binary not found: {m}"),
            Self::Spawn(m) => write!(f, "spawn contracts_rpc: {m}"),
            Self::Io(m) => write!(f, "contracts_rpc io: {m}"),
            Self::Protocol(m) => write!(f, "contracts_rpc protocol: {m}"),
        }
    }
}

impl std::error::Error for RpcClientError {}

/// Resolve a runnable path to the `contracts_rpc` binary, if one exists.
///
/// Resolution order:
///   1. `SUGAR_CONTRACTS_RPC` env var (explicit absolute path override).
///   2. A sibling of the current executable (`<exe_dir>/contracts_rpc`).
///   3. The parent of the current exe dir when that dir is `deps/` — under
///      `cargo test`, integration/unit test binaries run from
///      `target/<profile>/deps/`, but the runnable `contracts_rpc` is built
///      into `target/<profile>/`. So we also try `<exe_dir>/../contracts_rpc`.
///
/// Returns `None` when no runnable bin exists at any of those paths (the
/// `cargo test`-without-`cargo build` condition); the caller then falls back
/// to [`cargo_run_kit`]. The env-var form, when SET but pointing at a missing
/// path, is a hard error — an explicit override that doesn't resolve is a
/// misconfiguration, not a reason to silently rebuild.
pub fn resolve_bin() -> Result<Option<PathBuf>, RpcClientError> {
    if let Some(p) = std::env::var_os(CONTRACTS_RPC_ENV) {
        let p = PathBuf::from(p);
        if p.exists() {
            return Ok(Some(p));
        }
        return Err(RpcClientError::BinNotFound(format!(
            "{CONTRACTS_RPC_ENV}={} does not exist",
            p.display()
        )));
    }

    let exe = std::env::current_exe()
        .map_err(|e| RpcClientError::BinNotFound(format!("current_exe: {e}")))?;
    let Some(exe_dir) = exe.parent() else {
        return Ok(None);
    };

    // 2: sibling of current exe.
    let sibling = exe_dir.join(CONTRACTS_RPC_BIN);
    if sibling.exists() {
        return Ok(Some(sibling));
    }

    // 3: climb out of `deps/` (cargo-test layout).
    if exe_dir.file_name().and_then(|n| n.to_str()) == Some("deps") {
        if let Some(up) = exe_dir.parent() {
            let candidate = up.join(CONTRACTS_RPC_BIN);
            if candidate.exists() {
                return Ok(Some(candidate));
            }
        }
    }

    Ok(None)
}

/// Locate the rust workspace root: the directory holding the `Cargo.toml`
/// that declares `sugar-lift-contracts`. Used to build the `cargo run`
/// fallback's `--manifest-path`.
///
/// Strategy:
///   1. `current_exe()` is `…/target/<profile>/[deps/]<bin>`; climb to the
///      first ancestor named `target` and take its parent (the workspace
///      root). This is exact under any cargo layout (test, run, build).
///   2. Fall back to `CARGO_MANIFEST_DIR` if cargo set it (it does inside
///      `cargo test`/`cargo run` for the crate under test, but NOT for a
///      spawned bin — kept as a belt-and-suspenders second source).
fn workspace_root() -> Option<PathBuf> {
    if let Ok(exe) = std::env::current_exe() {
        // …/target/<profile>/deps/<bin>  OR  …/target/<profile>/<bin>
        // Climb to the `target` dir, then take its parent.
        let mut cur = exe.as_path();
        while let Some(parent) = cur.parent() {
            if parent.file_name().and_then(|n| n.to_str()) == Some("target") {
                if let Some(root) = parent.parent() {
                    if root.join("Cargo.toml").exists() {
                        return Some(root.to_path_buf());
                    }
                }
            }
            cur = parent;
        }
    }
    if let Some(dir) = std::env::var_os("CARGO_MANIFEST_DIR") {
        // CARGO_MANIFEST_DIR points at sugar-lift-rpc-client; its parent
        // is the workspace root (all member crates are siblings under it).
        let dir = PathBuf::from(dir);
        if let Some(root) = dir.parent() {
            if root.join("Cargo.toml").exists() {
                return Some(root.to_path_buf());
            }
        }
    }
    None
}

/// Build the portable `cargo run` invocation that builds-and-runs the kit.
/// Same code as the prebuilt bin, so its output (and CIDs) are byte-identical.
///
/// CRITICAL — SEPARATE TARGET DIR (deadlock avoidance): this fallback fires
/// precisely under `cargo test` with no prior `cargo build`, i.e. while an
/// OUTER cargo holds the build lock on the workspace `target/`. A nested
/// `cargo run` against that SAME target dir blocks forever on that lock (an
/// empirically reproduced deadlock; the same reason trybuild/escargot route
/// nested cargo to a separate target). So we point the nested build at a
/// FIXED, STABLE dir OUTSIDE the workspace target. Fixed (not per-call temp)
/// because `lift_pass` invokes this PER FILE: a stable dir means the first
/// call builds and the rest are up-to-date checks. Overridable via
/// `SUGAR_CONTRACTS_RPC_TARGET_DIR`.
fn cargo_run_kit() -> Result<ResolvedKit, RpcClientError> {
    let root = workspace_root().ok_or_else(|| {
        RpcClientError::BinNotFound(format!(
            "no runnable `{CONTRACTS_RPC_BIN}` found and could not locate the rust \
             workspace root for the `cargo run` fallback (set {CONTRACTS_RPC_ENV})"
        ))
    })?;
    let manifest = root.join("Cargo.toml");
    let cargo = std::env::var_os("CARGO")
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "cargo".to_string());
    let target_dir = std::env::var_os(CONTRACTS_RPC_TARGET_DIR_ENV)
        .map(PathBuf::from)
        .unwrap_or_else(|| std::env::temp_dir().join(CONTRACTS_RPC_FALLBACK_TARGET_SUBDIR));
    Ok(ResolvedKit::CargoRun {
        argv: vec![
            cargo,
            "run".into(),
            "--quiet".into(),
            "--manifest-path".into(),
            manifest.display().to_string(),
            "--target-dir".into(),
            target_dir.display().to_string(),
            "-p".into(),
            "sugar-lift-contracts".into(),
            "--bin".into(),
            CONTRACTS_RPC_BIN.into(),
            "--".into(),
        ],
    })
}

/// Resolve a runnable kit: a prebuilt bin if one exists, else the `cargo run`
/// fallback. `invoke_lift` ALWAYS has a way to run the kit through this.
pub fn resolve_kit() -> Result<ResolvedKit, RpcClientError> {
    match resolve_bin()? {
        Some(bin) => Ok(ResolvedKit::Bin(bin)),
        None => cargo_run_kit(),
    }
}

/// Drive the `contracts_rpc` lift kit over NDJSON and return the raw
/// `ir-document` JSON `Value` (the `result` of the `lift` call).
///
/// `workspace_root` is the directory the kit walks/reads relative to.
/// `source_paths` are relative paths within it; pass an empty slice to
/// have the kit walk the whole workspace (mirrors the pre-sever
/// `lift_path` whole-workspace walk).
///
/// The returned `Value` is the lift result envelope:
///   { "kind": "ir-document", "ir": [ <contract>, ... ], "diagnostics": [...], ... }
pub fn invoke_lift(
    workspace_root: &std::path::Path,
    source_paths: &[String],
) -> Result<Value, RpcClientError> {
    let kit = resolve_kit()?;
    invoke_lift_with_kit(&kit, workspace_root, source_paths)
}

/// Same as [`invoke_lift`] but with an explicit prebuilt binary path (used by
/// tests and when the caller has already resolved the bin once).
pub fn invoke_lift_with_bin(
    bin: &std::path::Path,
    workspace_root: &std::path::Path,
    source_paths: &[String],
) -> Result<Value, RpcClientError> {
    invoke_lift_with_kit(
        &ResolvedKit::Bin(bin.to_path_buf()),
        workspace_root,
        source_paths,
    )
}

/// Drive a resolved kit (prebuilt bin OR `cargo run`) over NDJSON.
///
/// The kit's stdout carries ONLY the NDJSON protocol. For the `cargo run`
/// form, `--quiet` suppresses cargo's "Compiling…/Finished" lines and all
/// build output goes to stderr (inherited), so it never corrupts the stdout
/// JSON stream.
pub fn invoke_lift_with_kit(
    kit: &ResolvedKit,
    workspace_root: &std::path::Path,
    source_paths: &[String],
) -> Result<Value, RpcClientError> {
    let (program, args) = kit.command();
    let mut child = Command::new(&program)
        .args(&args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| RpcClientError::Spawn(format!("{program}: {e}")))?;

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| RpcClientError::Io("stdin unavailable".into()))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| RpcClientError::Io("stdout unavailable".into()))?;
    let mut reader = BufReader::new(stdout);

    let workspace_root_str = workspace_root.display().to_string();

    // 1: initialize
    let init = json!({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": { "workspace_root": workspace_root_str }
    });
    write_line(&mut stdin, &init)?;
    let _ = read_response(&mut reader, 1)?;

    // 2: lift
    let lift = json!({
        "jsonrpc": "2.0", "id": 2, "method": "lift",
        "params": {
            "workspace_root": workspace_root_str,
            "source_paths": source_paths,
        }
    });
    write_line(&mut stdin, &lift)?;
    let lift_resp = read_response(&mut reader, 2)?;

    // 3: shutdown
    let shutdown = json!({"jsonrpc": "2.0", "id": 3, "method": "shutdown"});
    let _ = write_line(&mut stdin, &shutdown);
    drop(stdin);

    let status = child
        .wait()
        .map_err(|e| RpcClientError::Io(format!("wait: {e}")))?;
    if !status.success() {
        return Err(RpcClientError::Protocol(format!(
            "contracts_rpc exited {status}"
        )));
    }

    lift_resp
        .get("result")
        .cloned()
        .ok_or_else(|| RpcClientError::Protocol("lift response missing `result`".into()))
}

fn write_line(stdin: &mut std::process::ChildStdin, v: &Value) -> Result<(), RpcClientError> {
    let s = serde_json::to_string(v).map_err(|e| RpcClientError::Io(e.to_string()))?;
    stdin
        .write_all(s.as_bytes())
        .and_then(|()| stdin.write_all(b"\n"))
        .and_then(|()| stdin.flush())
        .map_err(|e| RpcClientError::Io(e.to_string()))
}

/// Read NDJSON response lines until one matches `expect_id`. Skips blank
/// lines. Errors if the stream ends first.
fn read_response<R: BufRead>(reader: &mut R, expect_id: i64) -> Result<Value, RpcClientError> {
    loop {
        let mut line = String::new();
        let n = reader
            .read_line(&mut line)
            .map_err(|e| RpcClientError::Io(e.to_string()))?;
        if n == 0 {
            return Err(RpcClientError::Protocol(format!(
                "stream ended before response id={expect_id}"
            )));
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let v: Value = serde_json::from_str(trimmed)
            .map_err(|e| RpcClientError::Protocol(format!("bad json line: {e}")))?;
        if v.get("id").and_then(Value::as_i64) == Some(expect_id) {
            if let Some(err) = v.get("error") {
                return Err(RpcClientError::Protocol(format!("rpc error: {err}")));
            }
            return Ok(v);
        }
        // Different id (or notification): keep reading.
    }
}

#[cfg(test)]
mod tests {
    use super::QuestionCache;
    use serde_json::json;

    #[test]
    fn canonical_question_cache_crosses_wire_once_per_distinct_question() {
        let subscriber = tracing_subscriber::fmt()
            .with_test_writer()
            .with_max_level(tracing::Level::INFO)
            .finish();
        let _subscriber = tracing::subscriber::set_default(subscriber);
        let mut cache = QuestionCache::default();
        let facts = json!({
            "level": "facts",
            "at": {"source_cid": "blake3-512:abc", "file": "sample.py"},
            "seek": true,
            "options": {"auditFrontier": true}
        });
        let assertions = json!({
            "level": "assertions",
            "at": {"source_cid": "blake3-512:abc", "file": "sample.py"},
            "seek": true,
            "options": {"auditFrontier": true}
        });
        let mut wire_calls = 0;

        for _ in 0..4 {
            let answer = cache
                .ask(&facts, || {
                    wire_calls += 1;
                    Ok::<_, ()>(json!({"nodes": ["fact"]}))
                })
                .unwrap();
            assert_eq!(answer, json!({"nodes": ["fact"]}));
        }
        let answer = cache
            .ask(&assertions, || {
                wire_calls += 1;
                Ok::<_, ()>(json!({"nodes": ["assertion"]}))
            })
            .unwrap();

        assert_eq!(answer, json!({"nodes": ["assertion"]}));
        assert_eq!(wire_calls, 2, "N repeated facts asks must cross once");
        assert_eq!(cache.hits(), 3);
        assert_eq!(cache.misses(), 2);
    }

    #[test]
    fn canonical_question_identity_ignores_json_object_key_order() {
        let mut cache = QuestionCache::default();
        let first = json!({"level":"facts", "seek":true, "at":{"file":"x.py"}});
        let reordered: serde_json::Value =
            serde_json::from_str(r#"{"at":{"file":"x.py"},"seek":true,"level":"facts"}"#).unwrap();
        let mut wire_calls = 0;

        cache
            .ask(&first, || {
                wire_calls += 1;
                Ok::<_, ()>(json!({"nodes": []}))
            })
            .unwrap();
        cache
            .ask(&reordered, || {
                wire_calls += 1;
                Ok::<_, ()>(json!({"nodes": ["wrong"]}))
            })
            .unwrap();

        assert_eq!(wire_calls, 1);
        assert_eq!(cache.hits(), 1);
    }

    #[test]
    fn implication_cache_dedupes_same_question_but_keeps_distinct_callsites() {
        let mut cache = QuestionCache::default();
        let question = |line| {
            json!({
                "workspace_root": "/workspace",
                "level": "implications",
                "at": {
                    "source_cid": format!("blake3-512:callsite-{line}"),
                    "file": "calls.py",
                    "span": {"start_line": line, "start_col": 8}
                },
                "seek": true,
                "options": {"auditFrontier": false}
            })
        };
        let first = question(4);
        let second = question(9);
        let mut wire_calls = 0;

        for demand in [&first, &first, &second, &second] {
            cache
                .ask(demand, || {
                    wire_calls += 1;
                    Ok::<_, ()>(json!({"nodes": []}))
                })
                .unwrap();
        }

        assert_eq!(
            wire_calls, 2,
            "one wire call per call-site question identity"
        );
        assert_eq!(cache.hits(), 2);
        assert_eq!(cache.misses(), 2);
    }

    #[test]
    fn canonical_question_identity_discriminates_workspace_root() {
        let mut cache = QuestionCache::default();
        let first_root = json!({
            "workspace_root": "/workspace/first",
            "level": "source_files",
            "at": null,
            "seek": false,
            "options": {"auditFrontier": true}
        });
        let second_root = json!({
            "workspace_root": "/workspace/second",
            "level": "source_files",
            "at": null,
            "seek": false,
            "options": {"auditFrontier": true}
        });
        let mut wire_calls = 0;

        let first = cache
            .ask(&first_root, || {
                wire_calls += 1;
                Ok::<_, ()>(json!({"nodes": ["first.py"]}))
            })
            .unwrap();
        let second = cache
            .ask(&second_root, || {
                wire_calls += 1;
                Ok::<_, ()>(json!({"nodes": ["second.py"]}))
            })
            .unwrap();
        let first_again = cache
            .ask(&first_root, || {
                wire_calls += 1;
                Ok::<_, ()>(json!({"nodes": ["wrong.py"]}))
            })
            .unwrap();

        assert_eq!(first, json!({"nodes": ["first.py"]}));
        assert_eq!(second, json!({"nodes": ["second.py"]}));
        assert_eq!(first_again, first);
        assert_eq!(wire_calls, 2);
        assert_eq!(cache.hits(), 1);
        assert_eq!(cache.misses(), 2);
    }
}
