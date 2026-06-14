//! Dissolving rust stdlib sugar by throwing it at the compiler.
//!
//! THE STDLIB-SUGAR HANDLER (T 2026-06-14). This is NOT a catch/fallback for things
//! symbolic lifting failed on. It is the first-class, designated handler for ONE
//! category: rust *standard-library sugar* -- the closed, deterministic, total,
//! effect-free computations that are "just how rust is written" (float formatting,
//! char case-mapping, `escape_*`, ...). We deliberately do NOT model these in FOL,
//! because stdlib IS the axiom: a stdlib term is dissolved by EVALUATING it with the
//! same stdlib the kit ships. "Need stdlib to prove stdlib? Yes -- that's the named,
//! pinned TCB; axioms all the way down, then a floor with a name on it." User logic
//! is still modeled and checked; only stdlib sugar is dissolved this way.
//!
//! THE TRICK (T): we already have the compiling code. Don't reconstruct a minimal
//! snippet by hand -- lift the problematic stdlib term (and any *pure local helpers*
//! it calls) verbatim into a throwaway harness, hand it to `rustc`, and run it. The
//! harness CONTAINS stdlib, so stdlib is its own evaluation table -- nothing
//! hand-mapped, nothing to drift. A green run is the dissolution; it is sound because
//! the term is closed + deterministic (so one run is universal) and the toolchain is
//! pinned (so the answer is reproducible / re-walkable).
//!
//! THE HARD BOUNDARY (T, emphatic): this is ONLY for vendor-written STDLIB SUGAR. It
//! is NOT a general "we couldn't model this expression, so let's just run it" cheat.
//! Running an expression to trust its result is the green-tests trap / the EUF
//! tautology in another coat: it trusts the code-under-test. The dividing line is what
//! the vendor WROTE:
//!   * vendor wrote stdlib sugar (`format!`, `.to_lowercase()`, `.count_ones()`) ->
//!     DISSOLVE (stdlib is the axiom; evaluating it grounds in the named TCB).
//!   * vendor wrote logic we are meant to verify -> MODEL + CHECK it; never run-to-trust.
//! A USER function NEVER qualifies, even if closed and pure -- the user's algorithm is
//! precisely the thing under proof; harnessing it would be circular. The eligibility
//! GATE is therefore an ALLOWLIST of stdlib's own pure surface (a carried local helper
//! qualifies only if its body bottoms out, recursively, in stdlib sugar + literals --
//! no user algorithm). This driver must NEVER be invoked on anything the gate has not
//! certified as stdlib sugar.
//!
//! THIRD FENCE -- UNIT-TEST ASSERTIONS ONLY, NEVER GENERALIZATION (T). This applies
//! solely to detected unit-test assertions: a finite set of pinned CONCRETE
//! `(input -> output)` instances. Each is closed, so each is evaluable, and one run is
//! the WHOLE truth for that instance. A GENERALIZATION (`forall x. P(x)`, a free
//! variable) cannot be run -- a single concrete run is only a sample, never a proof of
//! the universal -- so dissolution may NEVER touch it. We discharge exactly the
//! concrete assertion the vendor pinned and never extrapolate to a general property.
//! ("Vendor tests ARE the spec": lift the concrete claim, do not invent a universal.)
//! The gate folds all three fences into one predicate: CLOSED (no free vars) =
//! concrete = unit-test-shaped; a free var (generalization) disqualifies, exactly as a
//! non-stdlib op (user logic) disqualifies.
//!
//! SOUNDNESS BOUNDARY (ours, not stdlib's): the gate decides eligibility; the harness
//! only supplies VALUES. This module is just the driver: given a prelude + a list of
//! gated stdlib-sugar assert statements, compile once, run, and report which held.

use std::io::Write;
use std::path::Path;
use std::process::Command;

/// Outcome of a harness compile+run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HarnessResult {
    /// The harness compiled and ran; per-assert (by index) whether it held.
    Ran(Vec<bool>),
    /// The harness did not compile -- nothing is dissolved (safe: the asserts stay
    /// unclassified). Carries rustc's stderr (truncated) for diagnostics.
    CompileError(String),
    /// The two determinism runs disagreed -- the term was not deterministic after all,
    /// so NONE of its asserts may be dissolved (every index forced to `false`).
    Nondeterministic,
    /// rustc / the binary could not be invoked (toolchain absent). Caller treats this
    /// like CompileError: dissolve nothing.
    Unavailable(String),
}

/// Compile a harness of `prelude` (imports + pure local helper defs) plus a `main`
/// that runs each statement in `asserts`, printing `OK <i>` iff statement `i` does NOT
/// panic (caught per-assert via `catch_unwind`). Runs TWICE under `rustc` and requires
/// identical results (determinism sanity). `rustc` is the toolchain invocation (e.g.
/// `"rustc"`, or a `rustup run <toolchain> rustc` split handled by the caller via
/// `rustc_args`). `work_dir` must exist and be writable.
pub fn evaluate_asserts(
    prelude: &str,
    asserts: &[String],
    rustc: &str,
    rustc_args: &[String],
    edition: &str,
    work_dir: &Path,
) -> HarnessResult {
    if asserts.is_empty() {
        return HarnessResult::Ran(Vec::new());
    }
    let src = build_harness_source(prelude, asserts);
    let src_path = work_dir.join("sugar_closed_eval_probe.rs");
    let bin_path = work_dir.join("sugar_closed_eval_probe_bin");
    if let Err(e) = std::fs::File::create(&src_path).and_then(|mut f| f.write_all(src.as_bytes())) {
        return HarnessResult::Unavailable(format!("write harness: {e}"));
    }

    // Compile.
    let mut cmd = Command::new(rustc);
    cmd.args(rustc_args)
        .arg("--edition")
        .arg(edition)
        .arg("-A")
        .arg("warnings")
        .arg(&src_path)
        .arg("-o")
        .arg(&bin_path);
    let compile = match cmd.output() {
        Ok(o) => o,
        Err(e) => return HarnessResult::Unavailable(format!("invoke rustc: {e}")),
    };
    if !compile.status.success() {
        let mut err = String::from_utf8_lossy(&compile.stderr).to_string();
        err.truncate(2000);
        return HarnessResult::CompileError(err);
    }

    // Run twice for determinism.
    let run1 = match run_and_collect(&bin_path, asserts.len()) {
        Ok(v) => v,
        Err(e) => return HarnessResult::Unavailable(e),
    };
    let run2 = match run_and_collect(&bin_path, asserts.len()) {
        Ok(v) => v,
        Err(e) => return HarnessResult::Unavailable(e),
    };
    if run1 != run2 {
        return HarnessResult::Nondeterministic;
    }
    HarnessResult::Ran(run1)
}

/// Build the harness: prelude, then a `main` that runs each assert under a silenced
/// panic hook and prints `OK <i>` for each that does not panic.
fn build_harness_source(prelude: &str, asserts: &[String]) -> String {
    let mut s = String::new();
    s.push_str(prelude);
    s.push_str("\n#[allow(unused)]\nfn main() {\n");
    // Silence panic output so a deliberately-failing assert does not spam stderr.
    s.push_str("    std::panic::set_hook(Box::new(|_| {}));\n");
    for (i, a) in asserts.iter().enumerate() {
        // Each assert is wrapped so a panic is caught and only the survivors print OK.
        let stmt = a.trim().trim_end_matches(';');
        s.push_str(&format!(
            "    if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{ {stmt}; }})).is_ok() {{ println!(\"OK {i}\"); }}\n"
        ));
    }
    s.push_str("}\n");
    s
}

fn run_and_collect(bin: &Path, n: usize) -> Result<Vec<bool>, String> {
    let out = Command::new(bin)
        .output()
        .map_err(|e| format!("run harness: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut held = vec![false; n];
    for line in stdout.lines() {
        if let Some(rest) = line.strip_prefix("OK ") {
            if let Ok(i) = rest.trim().parse::<usize>() {
                if i < n {
                    held[i] = true;
                }
            }
        }
    }
    Ok(held)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rustc_available() -> bool {
        Command::new("rustc")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    #[test]
    fn harness_dissolves_true_and_refutes_false() {
        // Skip when the toolchain is absent (CI hosts without rustc) -- never fail
        // for an environment reason.
        if !rustc_available() {
            eprintln!("rustc unavailable; skipping harness driver test");
            return;
        }
        let dir = std::env::temp_dir().join("sugar_closed_eval_test");
        let _ = std::fs::create_dir_all(&dir);
        let asserts = vec![
            // closed stdlib sugar: true
            r#"assert_eq!('A'.to_lowercase().collect::<String>(), "a")"#.to_string(),
            // closed stdlib sugar: false (break-the-twin -- must NOT be reported held)
            r#"assert_eq!('A'.to_lowercase().collect::<String>(), "z")"#.to_string(),
            // another true
            r#"assert_eq!(format!("{}", 3.14_f64), "3.14")"#.to_string(),
        ];
        let res = evaluate_asserts("", &asserts, "rustc", &[], "2021", &dir);
        match res {
            HarnessResult::Ran(held) => {
                assert_eq!(held, vec![true, false, true], "true/false/true expected");
            }
            other => panic!("expected Ran, got {other:?}"),
        }
    }

    #[test]
    fn harness_carries_a_pure_local_helper() {
        if !rustc_available() {
            eprintln!("rustc unavailable; skipping harness helper test");
            return;
        }
        let dir = std::env::temp_dir().join("sugar_closed_eval_test_helper");
        let _ = std::fs::create_dir_all(&dir);
        let prelude = r#"
fn lower(c: char) -> String {
    let to_lowercase = c.to_lowercase();
    assert_eq!(to_lowercase.len(), to_lowercase.count());
    c.to_lowercase().collect()
}
"#;
        let asserts = vec![
            r#"assert_eq!(lower('A'), "a")"#.to_string(),
            r#"assert_eq!(lower('Σ'), "σ")"#.to_string(),
        ];
        match evaluate_asserts(prelude, &asserts, "rustc", &[], "2021", &dir) {
            HarnessResult::Ran(held) => assert_eq!(held, vec![true, true]),
            other => panic!("expected Ran, got {other:?}"),
        }
    }
}
