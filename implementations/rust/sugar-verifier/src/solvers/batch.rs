// SPDX-License-Identifier: Apache-2.0
//
// Chunked batched z3. Spawning a fresh z3 per obligation costs ~50ms alone and
// ~270ms under 16-way parallel contention — which strangles a tight timeout into
// false-Undecidable for trivial (pinned, microsecond) checks. A pinned check is
// the work of microseconds; the spawn is the whole cost. So amortize it: run
// MANY obligations through ONE z3 process.
//
// Each obligation is isolated with `(reset)` and bounded with z3's own
// per-query `(set-option :timeout <ms>)` — so one open/unpinned query returns
// `unknown` (-> Undecidable) without hanging the chunk or killing the session.
// A unique `(echo "<marker>")` after each obligation's `(check-sat)` delimits
// its output, so we parse one verdict per obligation from the single stdout.

use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::types::ObligationVerdict;

/// One obligation's batched outcome: the consistency-raw verdict (z3's view —
/// `sat`/`unsat`/`unknown`) plus the stdout fragment for unknown-constant
/// refusal detection (mirrors the per-spawn subprocess path).
#[derive(Debug, Clone)]
pub struct BatchOutcome {
    pub raw: ObligationVerdict,
    pub fragment: String,
}

fn marker(i: usize) -> String {
    format!("@@SUGAR_OB_{i}@@")
}

/// Run `scripts` through z3 in chunks of `chunk_size`, each query bounded by
/// `timeout_ms`. Returns one outcome per script, in order. A chunk that fails to
/// spawn or whose process dies yields Undecidable for its members (never a false
/// pass). `z3_binary` is the z3 executable (PATH name or absolute path).
pub fn batch_solve(
    scripts: &[String],
    z3_binary: &str,
    timeout_ms: u64,
    chunk_size: usize,
) -> Vec<BatchOutcome> {
    if scripts.is_empty() {
        return Vec::new();
    }
    let chunk_size = chunk_size.max(1);
    // Parallelize across chunks: one z3 process per chunk, num-cores chunks at a
    // time. Spawn count drops from scripts.len() to scripts.len()/chunk_size.
    use rayon::prelude::*;
    scripts
        .par_chunks(chunk_size)
        .flat_map(|chunk| solve_chunk(chunk, z3_binary, timeout_ms))
        .collect()
}

fn undecidable(reason: &str) -> BatchOutcome {
    BatchOutcome {
        raw: ObligationVerdict::Undecidable,
        fragment: reason.to_string(),
    }
}

fn solve_chunk(chunk: &[String], z3_binary: &str, timeout_ms: u64) -> Vec<BatchOutcome> {
    // Build one script: per obligation, reset state, set the per-query timeout,
    // feed the obligation (which carries its own check-sat), force a check-sat
    // (harmless if duplicated — same state, same verdict), then echo the marker.
    let mut script = String::new();
    for (i, ob) in chunk.iter().enumerate() {
        script.push_str("(reset)\n");
        script.push_str(&format!("(set-option :timeout {timeout_ms})\n"));
        script.push_str(ob);
        if !ob.ends_with('\n') {
            script.push('\n');
        }
        script.push_str("(check-sat)\n");
        script.push_str(&format!("(echo \"{}\")\n", marker(i)));
    }

    let mut cmd = Command::new(z3_binary);
    cmd.arg("-smt2").arg("-in");
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            return (0..chunk.len())
                .map(|_| undecidable(&format!("batch: spawn {z3_binary}: {e}")))
                .collect();
        }
    };
    if let Some(mut stdin) = child.stdin.take() {
        if stdin.write_all(script.as_bytes()).is_err() {
            let _ = child.kill();
            return (0..chunk.len())
                .map(|_| undecidable("batch: write stdin"))
                .collect();
        }
    }

    // Backstop wall timeout for the whole chunk: each query is bounded by z3's
    // :timeout, so the chunk is bounded by len * timeout; add generous margin.
    let wall = Duration::from_millis(timeout_ms.saturating_mul(chunk.len() as u64) + 5_000);
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if started.elapsed() >= wall {
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(_) => break,
        }
    }
    let output = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => {
            return (0..chunk.len())
                .map(|_| undecidable(&format!("batch: wait {z3_binary}: {e}")))
                .collect();
        }
    };
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    parse_chunk(&stdout, chunk.len())
}

/// Split the chunk stdout on the per-obligation markers and read one verdict per
/// obligation. The verdict is the LAST `sat`/`unsat`/`unknown` line before the
/// marker (robust to a duplicated check-sat). An `unknown constant` error in a
/// segment is preserved in the fragment so the caller can REFUSE (no discharger)
/// rather than mislabel. Missing markers (truncated output / killed chunk) ->
/// Undecidable for the unseen tail.
fn parse_chunk(stdout: &str, n: usize) -> Vec<BatchOutcome> {
    let mut out: Vec<BatchOutcome> = Vec::with_capacity(n);
    let mut segment = String::new();
    let mut idx = 0usize;
    for line in stdout.lines() {
        let line = line.trim_end_matches('\r');
        if line == marker(idx) {
            out.push(verdict_from_segment(&segment));
            segment.clear();
            idx += 1;
            if idx >= n {
                break;
            }
        } else {
            segment.push_str(line);
            segment.push('\n');
        }
    }
    while out.len() < n {
        out.push(undecidable("batch: missing marker (truncated/killed chunk)"));
    }
    out
}

fn verdict_from_segment(segment: &str) -> BatchOutcome {
    // Unknown-constant => unsupported lowering => the caller REFUSES by name.
    if segment.contains("unknown constant") {
        return BatchOutcome {
            raw: ObligationVerdict::Refused,
            fragment: segment.to_string(),
        };
    }
    let mut verdict: Option<ObligationVerdict> = None;
    for line in segment.lines() {
        match line.trim() {
            "unsat" => verdict = Some(ObligationVerdict::Discharged),
            "sat" => verdict = Some(ObligationVerdict::Unsatisfied),
            "unknown" => verdict = Some(ObligationVerdict::Undecidable),
            _ => {}
        }
    }
    match verdict {
        Some(v) => BatchOutcome {
            raw: v,
            fragment: segment.to_string(),
        },
        None => undecidable("batch: no verdict in segment"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn z3_present() -> bool {
        Command::new("z3").arg("--version").output().is_ok()
    }

    #[test]
    fn batched_verdicts_match_per_query_truth() {
        if !z3_present() {
            eprintln!("z3 absent: skipping batch correctness test");
            return;
        }
        // Three obligations in ONE z3 process: SAT (consistent), UNSAT
        // (contradictory), and an unknown-constant lowering (refuse).
        let sat = "(declare-const out Int)\n(assert (= out (* 3 2)))\n(assert (= out 6))\n";
        let unsat = "(declare-const out Int)\n(assert (= out 6))\n(assert (= out 7))\n";
        let refuse = "(assert (= (mystery_fn 1) 2))\n";
        let r = batch_solve(
            &[sat.to_string(), unsat.to_string(), refuse.to_string()],
            "z3",
            1000,
            64,
        );
        assert_eq!(r.len(), 3);
        // raw z3: sat -> Unsatisfied (consistency layer inverts later); unsat ->
        // Discharged; unknown constant -> Refused.
        assert_eq!(r[0].raw, ObligationVerdict::Unsatisfied, "frag: {}", r[0].fragment);
        assert_eq!(r[1].raw, ObligationVerdict::Discharged, "frag: {}", r[1].fragment);
        assert_eq!(r[2].raw, ObligationVerdict::Refused, "frag: {}", r[2].fragment);
    }

    #[test]
    fn empty_input_is_empty_output() {
        assert!(batch_solve(&[], "z3", 250, 64).is_empty());
    }

    #[test]
    fn reset_isolates_redeclared_symbols_across_obligations() {
        if !z3_present() {
            return;
        }
        // Both obligations declare `out` — without (reset) the second redeclare
        // would error. Batched with (reset) between them, both resolve cleanly.
        let a = "(declare-const out Int)\n(assert (= out 1))\n";
        let b = "(declare-const out Int)\n(assert (= out 2))\n";
        let r = batch_solve(&[a.to_string(), b.to_string()], "z3", 1000, 64);
        assert_eq!(r[0].raw, ObligationVerdict::Unsatisfied);
        assert_eq!(r[1].raw, ObligationVerdict::Unsatisfied);
    }
}
