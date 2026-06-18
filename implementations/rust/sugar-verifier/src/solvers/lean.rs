// SPDX-License-Identifier: Apache-2.0
//
// Lean subprocess solver. Invokes `lake env lean` on a generated file.

use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

use serde_json::{json, Value as Json};
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_compiler::IrCompiler;
use sugar_ir_compiler_lean::{LeanCompiler, DIALECT, THEOREM_NAME};

use crate::solvers::{SolveResult, Solver, SolverIdentity};
use crate::types::ObligationVerdict;

#[derive(Debug)]
pub struct LeanSubprocessSolver {
    name: String,
    version: String,
    binary: String,
    timeout: Option<Duration>,
    lake_project: Option<PathBuf>,
    lean_toolchain: Option<String>,
    identity: SolverIdentity,
}

impl LeanSubprocessSolver {
    pub fn new(
        name: impl Into<String>,
        binary: impl Into<String>,
        version: impl Into<String>,
        timeout: Option<Duration>,
        lake_project: Option<String>,
        lean_toolchain: Option<String>,
    ) -> Self {
        Self {
            name: name.into(),
            version: version.into(),
            binary: binary.into(),
            timeout,
            lake_project: lake_project.map(PathBuf::from),
            lean_toolchain,
            identity: SolverIdentity::default(),
        }
    }

    pub fn with_identity(mut self, identity: SolverIdentity) -> Self {
        self.identity = identity;
        self
    }

    pub fn lean_file_cid(source: &str) -> String {
        blake3_512_of(source.as_bytes())
    }

    pub fn uses_sorry_or_sorry_ax(source: &str, output: &str) -> bool {
        source.contains("sorry")
            || output.contains("sorryAx")
            || output.to_ascii_lowercase().contains("sorry")
    }

    pub fn parse_axiom_set(output: &str, theorem_name: &str) -> Vec<String> {
        if output.contains("does not depend on any axioms") {
            return vec![];
        }
        let relevant = output
            .lines()
            .find(|line| line.contains(theorem_name) && line.contains('['))
            .unwrap_or(output);
        if let (Some(start), Some(end)) = (relevant.find('['), relevant.rfind(']')) {
            return relevant[start + 1..end]
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(ToOwned::to_owned)
                .collect();
        }
        output
            .lines()
            .map(str::trim)
            .filter(|line| {
                !line.is_empty()
                    && !line.contains(theorem_name)
                    && !line.starts_with("info:")
                    && !line.starts_with("warning:")
            })
            .map(ToOwned::to_owned)
            .collect()
    }

    pub fn mathlib_commit_from_project(project: &Path) -> Option<String> {
        let manifest_path = project.join("lake-manifest.json");
        let body = std::fs::read_to_string(manifest_path).ok()?;
        let value: Json = serde_json::from_str(&body).ok()?;
        find_mathlib_rev(&value)
    }

    fn project_dir(&self, tmp_dir: &Path) -> PathBuf {
        match &self.lake_project {
            Some(path) if path.is_file() => path
                .parent()
                .map(Path::to_path_buf)
                .unwrap_or_else(|| tmp_dir.to_path_buf()),
            Some(path) => path.clone(),
            None => tmp_dir.to_path_buf(),
        }
    }

    fn lean_version(&self, cwd: &Path) -> String {
        let mut cmd = Command::new("lean");
        if let Some(toolchain) = &self.lean_toolchain {
            cmd.arg(format!("+{toolchain}"));
        }
        cmd.arg("--version");
        cmd.current_dir(cwd);
        match cmd.output() {
            Ok(output) if output.status.success() => {
                String::from_utf8_lossy(&output.stdout).trim().to_string()
            }
            Ok(output) => String::from_utf8_lossy(&output.stderr).trim().to_string(),
            Err(error) => format!("lean --version unavailable: {error}"),
        }
    }

    fn wait_for_child(
        &self,
        mut child: std::process::Child,
        started: Instant,
    ) -> Result<(Output, bool), String> {
        if let Some(timeout) = self.timeout {
            let deadline = started + timeout;
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        return child
                            .wait_with_output()
                            .map(|output| (output, false))
                            .map_err(|error| format!("lean: wait error: {error}"));
                    }
                    Ok(None) => {
                        if Instant::now() >= deadline {
                            let _ = child.kill();
                            let _ = child.wait();
                            return Err(format!(
                                "lean: timeout after {}s",
                                timeout.as_secs().max(1)
                            ));
                        }
                        std::thread::sleep(Duration::from_millis(20));
                    }
                    Err(error) => return Err(format!("lean: wait error: {error}")),
                }
            }
        }
        child
            .wait_with_output()
            .map(|output| (output, false))
            .map_err(|error| format!("lean: wait error: {error}"))
    }
}

impl Solver for LeanSubprocessSolver {
    fn name(&self) -> &str {
        &self.name
    }

    fn version(&self) -> &str {
        &self.version
    }

    fn ir_compiler(&self) -> &str {
        DIALECT
    }

    fn identity(&self) -> SolverIdentity {
        self.identity.clone()
    }

    fn solve(&self, smt: &str) -> SolveResult {
        let started = Instant::now();
        let ir: Json = match serde_json::from_str(smt) {
            Ok(value) => value,
            Err(error) => {
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("lean: failed to parse IR-JSON: {error}"),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: false,
                };
            }
        };

        let compiler = LeanCompiler::new();
        let compiled = match compiler.compile(&ir, DIALECT) {
            Ok(compiled) => compiled,
            Err(error) => {
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("lean: compilation error: {error}"),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: false,
                };
            }
        };

        let tmp_dir = std::env::temp_dir().join(format!(
            "sugar-lean-{}-{}",
            std::process::id(),
            started.elapsed().as_nanos()
        ));
        if let Err(error) = std::fs::create_dir_all(&tmp_dir) {
            return SolveResult {
                verdict: ObligationVerdict::Undecidable,
                solver_name: self.name.clone(),
                solver_version: self.version.clone(),
                error: format!("lean: failed to create temp dir: {error}"),
                solver_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
            };
        }

        let lean_file = tmp_dir.join("proof.lean");
        let source = format!("{}{}", compiled.preamble, compiled.body);
        let file_cid = Self::lean_file_cid(&source);
        if let Err(error) = std::fs::write(&lean_file, &source) {
            let _ = std::fs::remove_dir_all(&tmp_dir);
            return SolveResult {
                verdict: ObligationVerdict::Undecidable,
                solver_name: self.name.clone(),
                solver_version: self.version.clone(),
                error: format!("lean: failed to write .lean file: {error}"),
                solver_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
            };
        }

        let project_dir = self.project_dir(&tmp_dir);

        // Degrade gracefully when the configured lake project is not
        // provisioned. `lake env lean` runs with `current_dir(project_dir)`;
        // if that directory is absent the spawn fails with a bare ENOENT that
        // misleadingly reads "spawn lake: No such file or directory". Detect
        // it here and return a clear, actionable Undecidable instead: the lean
        // seat is wired but its mathlib project has not been built. This keeps
        // first-wins working (the seat lights up the moment the project exists)
        // without crashing or emitting a confusing error.
        if !project_dir.exists() {
            let _ = std::fs::remove_dir_all(&tmp_dir);
            return SolveResult {
                verdict: ObligationVerdict::Undecidable,
                solver_name: self.name.clone(),
                solver_version: self.version.clone(),
                error: format!(
                    "lean: lake project {} is not provisioned (run `lake exe cache get` there, or unset lake_project to run lean standalone)",
                    project_dir.display()
                ),
                solver_stdout: String::new(),
                wall_clock: started.elapsed(),
                timed_out: false,
            };
        }

        let lean_version = self.lean_version(&project_dir);
        let mathlib_commit = Self::mathlib_commit_from_project(&project_dir);

        let mut cmd = Command::new(&self.binary);
        if let Some(toolchain) = &self.lean_toolchain {
            cmd.arg(format!("+{toolchain}"));
        }
        cmd.arg("env").arg("lean").arg(&lean_file);
        cmd.current_dir(&project_dir);
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let child = match cmd.spawn() {
            Ok(child) => child,
            Err(error) => {
                let _ = std::fs::remove_dir_all(&tmp_dir);
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error: format!("lean: spawn {}: {error}", self.binary),
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: false,
                };
            }
        };

        let (output, timed_out) = match self.wait_for_child(child, started) {
            Ok(result) => result,
            Err(error) => {
                let _ = std::fs::remove_dir_all(&tmp_dir);
                return SolveResult {
                    verdict: ObligationVerdict::Undecidable,
                    solver_name: self.name.clone(),
                    solver_version: self.version.clone(),
                    error,
                    solver_stdout: String::new(),
                    wall_clock: started.elapsed(),
                    timed_out: true,
                };
            }
        };
        let _ = std::fs::remove_dir_all(&tmp_dir);

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let combined = format!("{stdout}{stderr}");
        let axioms = Self::parse_axiom_set(&combined, THEOREM_NAME);
        let uses_sorry = Self::uses_sorry_or_sorry_ax(&source, &combined);
        let has_error = combined.contains("error:");
        let discharged = output.status.success() && !uses_sorry && !has_error;
        let verdict = if discharged {
            ObligationVerdict::Discharged
        } else {
            ObligationVerdict::Undecidable
        };

        let receipt = json!({
            "kind": "lean-discharge-receipt",
            "leanVersion": lean_version,
            "mathlibCommit": mathlib_commit,
            "emittedFileCid": file_cid,
            "axioms": axioms,
            "leanStdout": stdout,
            "leanStderr": stderr,
        });
        let solver_stdout = serde_json::to_string_pretty(&receipt)
            .unwrap_or_else(|error| format!("{{\"receiptError\":\"{error}\"}}"));

        SolveResult {
            verdict,
            solver_name: self.name.clone(),
            solver_version: self.version.clone(),
            error: if discharged {
                String::new()
            } else if uses_sorry {
                "lean: proof uses sorry or sorryAx".to_string()
            } else if has_error {
                "lean: output contains errors".to_string()
            } else {
                format!("lake env lean exited with code {:?}", output.status.code())
            },
            solver_stdout,
            wall_clock: started.elapsed(),
            timed_out,
        }
    }
}

fn find_mathlib_rev(value: &Json) -> Option<String> {
    match value {
        Json::Object(map) => {
            let package_name = map
                .get("name")
                .or_else(|| map.get("url"))
                .and_then(Json::as_str)
                .unwrap_or_default()
                .to_ascii_lowercase();
            if package_name.contains("mathlib") {
                if let Some(rev) = map
                    .get("rev")
                    .or_else(|| map.get("gitRev"))
                    .or_else(|| map.get("commit"))
                    .and_then(Json::as_str)
                {
                    return Some(rev.to_string());
                }
            }
            map.values().find_map(find_mathlib_rev)
        }
        Json::Array(items) => items.iter().find_map(find_mathlib_rev),
        _ => None,
    }
}
