// SPDX-License-Identifier: Apache-2.0
//
// Receipt 1: test-assertion consistency pass.
//
// A test that asserts several facts about the SAME term (e.g. a bare
// variable `x`) lifts, after same-name coalescing in sugar-lift, to a
// single contract whose `inv` is the CONJUNCTION of those facts. When the
// conjuncts are mutually satisfiable the test's assertions are mutually
// CONSISTENT; when they contradict (`assert x is None` AND
// `assert x is not None` -> `=(x,None) ∧ ≠(x,None)`) the conjunction is
// UNSATISFIABLE.
//
// `enumerate_callsites` only produces obligations for `inv` ctor terms that
// match a known bridge sourceSymbol. An `inv` over a bare free var and a
// `None` constructor has no bridge ctor, so it produces ZERO call sites and
// the contradiction dies silently. This pass is where that conjoined `inv`
// is actually checked.
//
// SOLVER POLARITY. The shared SMT path (`smt_emitter::emit`) renders the
// NEGATED-VALIDITY form (`assert (not goal); check-sat`), so the z3 kit maps
// `unsat -> Discharged`. This pass needs the OPPOSITE: the RAW satisfiability
// of the invariant itself (`assert <inv>; check-sat`, via `emit_asserted`).
// So we INVERT the solver verdict:
//   raw z3 `sat`   (solver reports Unsatisfied) -> PROVEN-consistent
//   raw z3 `unsat` (solver reports Discharged)  -> REFUSED-contradictory
//   anything else  (Undecidable / unknown)      -> Undecidable, reported LOUD
//
// CLAIM. A PROVEN row here claims EXACTLY "test assertions mutually
// consistent about callsite X" -- NOT that the production code is correct
// and NOT that any postcondition is satisfied. Code-correctness is a
// separate obligation (production-bridge / self-post discharge).
//
// LITERAL-VALUE MODEL (Python `==` semantics; see
// `sugar_ir_compiler_smt_lib::literal_encoding`). The consistency verdict
// for literal-bearing assertions reflects Python equality EXACTLY in these
// dimensions:
//   - Distinct string literals are unequal:        `"a" != "b"`.
//   - A string literal is not any number:          `"5" != 5`.
//   - A string literal is not None:                `"x" != None`.
//   - None is not any number and not any string:   `None != 5`, `None != "x"`.
//   - bool IS int (bool encodes to its int value): `True == 1`, `False == 0`,
//     so `r == True; r == 1` stays CONSISTENT (NOT over-refused).
// RESIDUAL (not modeled): `float == int` cross-type equality. Python
// `5.0 == 5` is true, but a non-integer float literal is NOT folded into the
// integer distinctness set (asserting `5.0 != 5` would be Python-false and
// `(distinct strlit 5.0)` ill-sorted), so a `r == 5.0; r == 5`-style pairing
// is left unconstrained rather than risk a false refusal. Retirement: a
// float<->int sort-morphism / Real-theory encoding.
//
// DOCUMENTED LIMITATION. Contradictions are caught only when the facts share
// the SAME lifted term (same bare var / same syntactic callsite). Two tests
// asserting opposite things about the same INPUT at DIFFERENT source
// locations lift to DISTINCT free vars and do NOT contradict here; catching
// those requires the argument-carrying (uninterpreted-function / EUF) lifter
// change, which is queued as the next capability and deliberately not built
// here.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use rayon::prelude::*;
use serde_json::{json, Value as Json};
use tracing::{debug, info, warn};

use crate::solvers::{run_plan, SolverHandle, SolverPlan};
use crate::types::{memento_body, memento_kind, MementoPool, ObligationVerdict};
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_compiler_smt_lib::emit_asserted;

use std::sync::atomic::{AtomicUsize, Ordering};

/// Running count of consistency obligations solved this process — drives the
/// per-obligation progress log so a `verify` run is never silent about what it
/// is doing or where it is slow.
static OBLIGATIONS_CHECKED: AtomicUsize = AtomicUsize::new(0);

/// Outcome of a single contract's consistency check.
#[derive(Debug, Clone)]
pub struct ConsistencyResult {
    pub contract_cid: String,
    pub property_name: String,
    /// `Discharged` => PROVEN-consistent; `Unsatisfied` => REFUSED-contradictory;
    /// `Undecidable` => encoding STOP (must be surfaced, never silently passed).
    pub verdict: ObligationVerdict,
    pub reason: String,
    /// True when the verdict came from an EXECUTION WITNESS discharged by
    /// recompute (k(I)=t), NOT from a symbolic solver. Kept distinct so the
    /// report never reads witnessed-by-execution as proven-by-solver.
    pub witnessed: bool,
}

const CONSISTENT_REASON: &str = "test assertions mutually consistent about callsite";
const CONTRADICTORY_REASON: &str = "test assertions contradictory about callsite";

/// Does this contract have an `inv` that produces no enumerable bridge
/// callsite? We approximate "no bridge callsite" structurally: the pass only
/// fires for contracts that carry an `inv` and NO `pre`/`post` (the lifted
/// shape of a coalesced test-assertion fact set). Bridge-bearing contracts
/// carry pre/post and are handled by the call-site path.
///
/// SETUP-BINDING EXCLUSION. The Pattern-5 (call-binding) lifter emits, per
/// call site, a `::facts` contract carrying the SETUP BINDING (e.g.
/// `y = make_value(x)` -> `=(y, make_value(x))`) alongside the asserted-
/// property `::assertion` contract. A `::facts` binding is SAT by
/// construction (it is just a definition, not a claim); reporting it as
/// "test assertions mutually consistent" is vacuous and mislabeled. Only
/// asserted-property contracts belong in the consistency report:
///   - whole-test Pattern-3 contracts (named by the test, no `::facts` suffix)
///   - `::assertion` contracts (Pattern-5 conjoined asserted properties)
///   - loop/parametrize assertion contracts (no `::facts` suffix)
/// So `::facts` and `::facts::N` setup-binding contracts are excluded by name.
fn is_consistency_candidate(body: &Json) -> bool {
    let has_inv = body.get("inv").map(|v| v.is_object()).unwrap_or(false);
    let has_pre = body.get("pre").map(|v| v.is_object()).unwrap_or(false);
    let has_post = body.get("post").map(|v| v.is_object()).unwrap_or(false);
    if !(has_inv && !has_pre && !has_post) {
        return false;
    }
    let name = body
        .get("name")
        .and_then(|v| v.as_str())
        .or_else(|| body.get("contractName").and_then(|v| v.as_str()))
        .unwrap_or("");
    !is_setup_binding_name(name)
}

/// A `::facts` / `::facts::N` contract is a setup binding, not an asserted
/// property. Matches the trailing segment exactly so it does not catch the
/// asserted-property `::assertion` name or any other suffix. (The
/// `::facts-implies-assertion` form is an implication DECL, not a contract,
/// so it never reaches this pass; the guard is nonetheless precise.)
fn is_setup_binding_name(name: &str) -> bool {
    // Strip an optional trailing `::N` duplicate-disambiguation suffix, then
    // require the remaining segment to end in exactly `::facts`.
    let stem = match name.rsplit_once("::") {
        Some((head, tail)) if tail.chars().all(|c| c.is_ascii_digit()) && !tail.is_empty() => head,
        _ => name,
    };
    stem.ends_with("::facts")
}

/// Invert a raw-satisfiability solver verdict into a consistency verdict.
/// See the SOLVER POLARITY note at the top of the module.
fn consistency_verdict(raw: ObligationVerdict) -> (ObligationVerdict, &'static str) {
    match raw {
        // raw `sat`  -> solver said Unsatisfied -> the inv IS satisfiable -> consistent
        ObligationVerdict::Unsatisfied => (ObligationVerdict::Discharged, CONSISTENT_REASON),
        // raw `unsat` -> solver said Discharged -> the inv is contradictory -> refuse
        ObligationVerdict::Discharged => (ObligationVerdict::Unsatisfied, CONTRADICTORY_REASON),
        // An honest refusal (no sound discharger) passes through as a refusal --
        // it carries its own named reason from the solver layer, never overwritten
        // with the generic encoding-STOP message.
        ObligationVerdict::Refused => (ObligationVerdict::Refused, "refused: no sound discharger"),
        // unknown / error -> encoding STOP, surfaced loud
        other => (other, "consistency check undecidable (encoding STOP)"),
    }
}

#[derive(Debug, Clone)]
struct WitnessResolver {
    argv: Vec<String>,
    working_dir: PathBuf,
    method: String,
}

#[derive(Debug, Clone)]
struct WitnessPackageClaim {
    package_cid: String,
    witness_kind: String,
    test_files: Vec<String>,
    code_files: Vec<String>,
    expected_count: usize,
    expected_passed: usize,
}

#[derive(Debug, Clone)]
struct WitnessPackageOutcome {
    resolved_by: String,
    count: usize,
    failed: usize,
    failed_tests: Vec<String>,
}

/// Settle a contract carrying a `custom` execution-witness EvidenceTerm from
/// authenticated package bytes, not from the kit's verdict string. The kit is
/// allowed to RESOLVE bytes over RPC. Rust recomputes the package CID, parses the
/// committed per-test `outcome` facts, and derives Discharged or Unsatisfied
/// from those facts. Returns None when there is no custom witness (caller falls
/// through to symbolic solving). FAIL-CLOSED: missing config / malformed schema /
/// unparseable bytes is Undecidable or Unsatisfied, never Discharged.
fn try_witness_discharge(
    body: &Json,
    contract_cid: String,
    property_name: String,
) -> Option<ConsistencyResult> {
    let evidence = body.get("evidence")?;
    if evidence.get("proofType").and_then(|v| v.as_str()) != Some("custom") {
        return None;
    }
    let undecidable = |reason: String| ConsistencyResult {
        contract_cid: contract_cid.clone(),
        property_name: property_name.clone(),
        verdict: ObligationVerdict::Undecidable,
        reason,
        witnessed: false,
    };
    let tool = evidence
        .get("certificate")
        .and_then(|c| c.get("tool"))
        .and_then(|t| t.as_str())
        .unwrap_or("");
    let project = match std::env::var("SUGAR_WITNESS_PROJECT_DIR") {
        Ok(p) if !p.trim().is_empty() => p,
        _ => {
            return Some(undecidable(
                "custom witness present but SUGAR_WITNESS_PROJECT_DIR unset (fail-closed)".into(),
            ))
        }
    };

    let claim = match witness_package_claim(evidence, tool) {
        Ok(c) => c,
        Err(e) => return Some(undecidable(e)),
    };
    let resolvers = find_witness_resolvers(Path::new(&project));
    if resolvers.is_empty() {
        return Some(undecidable(
            "custom witness package present but no resolve_witness_command configured \
             (fail-closed)"
                .to_string(),
        ));
    }
    let outcome = match resolve_witness_package(&resolvers, Path::new(&project), &claim) {
        Ok(o) => o,
        Err(e) => {
            return Some(ConsistencyResult {
                contract_cid,
                property_name,
                verdict: ObligationVerdict::Unsatisfied,
                reason: format!("witness REFUSED by rust package recompute: {e}"),
                witnessed: false,
            })
        }
    };
    Some(if outcome.failed == 0 {
        ConsistencyResult {
            contract_cid,
            property_name,
            verdict: ObligationVerdict::Discharged,
            reason: format!(
                "witness package verified by rust via {}; all {} outcomes passed",
                outcome.resolved_by, outcome.count
            ),
            witnessed: true,
        }
    } else {
        let shown = outcome
            .failed_tests
            .iter()
            .take(6)
            .cloned()
            .collect::<Vec<_>>();
        let more = if outcome.failed_tests.len() > shown.len() {
            format!(" (+{} more)", outcome.failed_tests.len() - shown.len())
        } else {
            String::new()
        };
        ConsistencyResult {
            contract_cid,
            property_name,
            verdict: ObligationVerdict::Unsatisfied,
            reason: format!(
                "witness REFUSED by rust package body: bundle reproduced via {}; \
                 {}/{} outcomes failed: {}{}",
                outcome.resolved_by,
                outcome.failed,
                outcome.count,
                shown.join(", "),
                more
            ),
            witnessed: false,
        }
    })
}

fn witness_package_claim(evidence: &Json, tool: &str) -> Result<WitnessPackageClaim, String> {
    let proof_data = evidence
        .get("certificate")
        .and_then(|c| c.get("proofData"))
        .and_then(|v| v.as_str())
        .ok_or("custom witness evidence missing certificate.proofData (fail-closed)")?;
    let data: Json = serde_json::from_str(proof_data)
        .map_err(|e| format!("custom witness proofData unparseable: {e}"))?;
    if data.get("kind").and_then(|v| v.as_str()) != Some("witness-package") {
        return Err(
            "custom witness proofData is not a witness-package committed-outcome schema \
             (fail-closed)"
                .to_string(),
        );
    }
    let package_cid = data
        .get("packageCid")
        .and_then(|v| v.as_str())
        .ok_or("witness-package proofData missing packageCid")?
        .to_string();
    let expected_count =
        data.get("count")
            .and_then(|v| v.as_u64())
            .ok_or("witness-package proofData missing numeric count")? as usize;
    let expected_passed =
        data.get("passed")
            .and_then(|v| v.as_u64())
            .ok_or("witness-package proofData missing numeric passed")? as usize;
    let witness_kind = match tool {
        "pytest" => "pytest-witness-package",
        "cargo-test" => "cargo-test-witness-package",
        "junit" => "junit-test-witness-package",
        "testng" => "testng-test-witness-package",
        other => {
            return Err(format!(
                "custom witness tool {other:?} has no rust-side package outcome mapping \
                 (fail-closed)"
            ))
        }
    }
    .to_string();
    Ok(WitnessPackageClaim {
        package_cid,
        witness_kind,
        test_files: json_str_list(&data, "testFiles"),
        code_files: json_str_list(&data, "codeFiles"),
        expected_count,
        expected_passed,
    })
}

fn json_str_list(data: &Json, key: &str) -> Vec<String> {
    data.get(key)
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

fn find_witness_resolvers(project_root: &Path) -> Vec<WitnessResolver> {
    let lift_dir = project_root.join(".sugar").join("lift");
    let mut found = Vec::new();
    let Ok(entries) = std::fs::read_dir(&lift_dir) else {
        return found;
    };
    for entry in entries.flatten() {
        let manifest = entry.path().join("manifest.toml");
        if let Some(resolver) = parse_witness_resolver(&manifest, project_root) {
            found.push(resolver);
        }
    }
    found
}

fn parse_witness_resolver(manifest: &Path, project_root: &Path) -> Option<WitnessResolver> {
    let text = std::fs::read_to_string(manifest).ok()?;
    let value: toml::Value = toml::from_str(&text).ok()?;
    let argv: Vec<String> = value
        .get("resolve_witness_command")?
        .as_array()?
        .iter()
        .filter_map(|v| v.as_str().map(|s| s.to_string()))
        .collect();
    if argv.is_empty() {
        return None;
    }
    let working_dir = value
        .get("working_dir")
        .and_then(|v| v.as_str())
        .map(PathBuf::from)
        .map(|p| {
            if p.is_absolute() {
                p
            } else {
                project_root.join(p)
            }
        })
        .unwrap_or_else(|| project_root.to_path_buf());
    let method = value
        .get("resolve_witness_method")
        .and_then(|v| v.as_str())
        .unwrap_or("sugar.plugin.resolve_witness")
        .to_string();
    Some(WitnessResolver {
        argv,
        working_dir,
        method,
    })
}

fn resolve_witness_package(
    resolvers: &[WitnessResolver],
    project_root: &Path,
    claim: &WitnessPackageClaim,
) -> Result<WitnessPackageOutcome, String> {
    let mut mismatches = Vec::new();
    let mut errors = Vec::new();
    let memento = json!({
        "kind": "witness-memento",
        "witness_cid": claim.package_cid,
        "witness_kind": claim.witness_kind,
        "test_files": claim.test_files,
        "code_files": claim.code_files,
        "count": claim.expected_count,
        "passed": claim.expected_passed,
    });
    for resolver in resolvers {
        match resolve_witness_body(resolver, project_root, &memento) {
            Ok((resolved_by, bytes)) => match package_outcome(&bytes, &resolved_by, claim) {
                Ok(outcome) => return Ok(outcome),
                Err(e) => mismatches.push(e),
            },
            Err(e) => errors.push(e),
        }
    }
    if !mismatches.is_empty() {
        Err(mismatches.join("; "))
    } else {
        Err(format!(
            "could not resolve witness package body: {}",
            errors.join("; ")
        ))
    }
}

fn resolve_witness_body(
    resolver: &WitnessResolver,
    project_root: &Path,
    memento: &Json,
) -> Result<(String, Vec<u8>), String> {
    if resolver.argv.is_empty() {
        return Err("empty resolver argv".to_string());
    }
    let abs_root = std::fs::canonicalize(project_root)
        .unwrap_or_else(|_| project_root.to_path_buf())
        .display()
        .to_string();
    let package_dir = project_root.join(".sugar").join("witnesses");
    let mut params = json!({
        "memento": memento,
        "workspace_root": abs_root,
    });
    if package_dir.exists() {
        params["package_dir"] = json!(package_dir.display().to_string());
    }
    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": resolver.method,
        "params": params,
    });

    let mut cmd = Command::new(&resolver.argv[0]);
    cmd.args(&resolver.argv[1..]);
    cmd.arg("--rpc");
    cmd.current_dir(&resolver.working_dir);
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::null());
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("spawn resolver {}: {e}", resolver.argv[0]))?;
    {
        let mut stdin = child.stdin.take().ok_or("resolver stdin unavailable")?;
        let line = serde_json::to_string(&req).map_err(|e| e.to_string())?;
        stdin
            .write_all(line.as_bytes())
            .and_then(|_| stdin.write_all(b"\n"))
            .map_err(|e| format!("write resolver stdin: {e}"))?;
    }

    let stdout = child.stdout.take().ok_or("resolver stdout unavailable")?;
    let (tx, rx) = std::sync::mpsc::channel::<Option<Json>>();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut last_reply: Option<Json> = None;
        for line in reader.lines().map_while(Result::ok) {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str::<Json>(trimmed) {
                if v.get("result").is_some() || v.get("error").is_some() {
                    last_reply = Some(v);
                }
            }
        }
        let _ = tx.send(last_reply);
    });
    const RESOLVER_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(120);
    let reply = match rx.recv_timeout(RESOLVER_TIMEOUT) {
        Ok(r) => r,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "resolver `{}` timed out after {}s",
                resolver.argv[0],
                RESOLVER_TIMEOUT.as_secs()
            ));
        }
    };
    let _ = child.wait();
    let reply = reply.ok_or("resolver produced no JSON-RPC reply")?;
    if let Some(err) = reply.get("error") {
        let msg = err
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        return Err(format!("oracle refused resolution: {msg}"));
    }
    let result = reply.get("result").ok_or("reply missing result")?;
    let body_b64 = result
        .get("body_b64")
        .and_then(|v| v.as_str())
        .ok_or("resolve_witness result missing body_b64")?;
    let resolved_by = result
        .get("resolved_by")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();
    let bytes = B64
        .decode(body_b64)
        .map_err(|e| format!("decode body_b64: {e}"))?;
    Ok((resolved_by, bytes))
}

fn package_outcome(
    bytes: &[u8],
    resolved_by: &str,
    claim: &WitnessPackageClaim,
) -> Result<WitnessPackageOutcome, String> {
    let computed = blake3_512_of(bytes);
    if computed != claim.package_cid {
        return Err(format!(
            "package content computes to {computed}, not pinned {}",
            claim.package_cid
        ));
    }
    let mut count = 0usize;
    let mut passed = 0usize;
    let mut failed_tests = Vec::new();
    for (idx, raw) in bytes.split(|b| *b == b'\n').enumerate() {
        let raw = raw.strip_suffix(b"\r").unwrap_or(raw);
        if raw.is_empty() {
            continue;
        }
        let line: Json = serde_json::from_slice(raw)
            .map_err(|e| format!("package line {} is not JSON: {e}", idx + 1))?;
        count += 1;
        match line.get("outcome").and_then(|v| v.as_str()) {
            Some("passed") => passed += 1,
            Some(other) => failed_tests.push(
                line.get("test")
                    .or_else(|| line.get("test_id"))
                    .and_then(|v| v.as_str())
                    .unwrap_or(other)
                    .to_string(),
            ),
            None => {
                return Err(format!(
                    "package line {} missing committed outcome field",
                    idx + 1
                ))
            }
        }
    }
    if count != claim.expected_count || passed != claim.expected_passed {
        return Err(format!(
            "package body count/passed mismatch: proofData committed count={} passed={}, \
             body has count={count} passed={passed}",
            claim.expected_count, claim.expected_passed
        ));
    }
    Ok(WitnessPackageOutcome {
        resolved_by: resolved_by.to_string(),
        count,
        failed: count.saturating_sub(passed),
        failed_tests,
    })
}

/// Run the consistency pass over every candidate contract in the pool.
/// True iff this contract carries a `custom` execution-witness EvidenceTerm, so
/// it is settled BY RECOMPUTE (`try_witness_discharge`) rather than symbolic SAT.
fn is_witness_member(body: &Json) -> bool {
    body.get("evidence")
        .and_then(|e| e.get("proofType"))
        .and_then(|v| v.as_str())
        == Some("custom")
}

/// Run the raw-satisfiability consistency check on a single `inv` and label it.
/// Shared by the per-contract path and the cross-proof conjoined path.
fn check_inv_consistency(
    cid: String,
    property_name: &str,
    inv: Json,
    plan: &SolverPlan,
    registry: &HashMap<String, SolverHandle>,
    pool: &MementoPool,
) -> ConsistencyResult {
    let smt = match emit_asserted(&inv) {
        Ok(s) => s,
        Err(e) => {
            return ConsistencyResult {
                contract_cid: cid,
                property_name: property_name.to_string(),
                verdict: ObligationVerdict::Undecidable,
                reason: format!("consistency smt-emit (encoding STOP): {e}"),
                witnessed: false,
            };
        }
    };
    let solve_started = std::time::Instant::now();
    let (raw, raw_reason, _invs) = run_plan(plan, registry, &smt, Some(&inv));
    let ms = solve_started.elapsed().as_millis();
    // Per-obligation progress on stderr. A PINNED obligation is a closed ground
    // check (microseconds); >=250ms is the signal of an unpinned/open lowering —
    // always surfaced. Set SUGAR_VERIFY_PROGRESS=1 to log every obligation.
    let n = OBLIGATIONS_CHECKED.fetch_add(1, Ordering::Relaxed) + 1;
    if ms >= 250 {
        eprintln!("[verify #{n}] SLOW {ms}ms  {property_name}  (unpinned/open?)");
    } else if std::env::var_os("SUGAR_VERIFY_PROGRESS").is_some() {
        eprintln!("[verify #{n}] {ms}ms  {property_name}");
    } else if n % 200 == 0 {
        eprintln!("[verify] {n} obligations checked…");
    }
    let (mut verdict, label) = consistency_verdict(raw);
    let mut reason = format!("{label} `{property_name}` [{raw_reason}]");
    // THE VENDOR FIXED `t`. An `unsat` on conflicting pins of a non-ground compound
    // is a fork-around-`t`: vindicated to Discharged when the callee is proven
    // impure (v2 dig), convicted when proven pure, refused while purity is unproven.
    if verdict == ObligationVerdict::Unsatisfied {
        if let Some((nv, nr)) = vindicate_or_refuse(&inv, property_name, pool) {
            verdict = nv;
            reason = nr;
        }
    }
    if verdict == ObligationVerdict::Undecidable {
        warn!(
            contract = %property_name,
            cid = %cid,
            raw = ?raw,
            "consistency: UNDECIDABLE/ill-sorted -- encoding STOP, NOT a pass"
        );
    }
    ConsistencyResult {
        contract_cid: cid,
        property_name: property_name.to_string(),
        verdict,
        reason,
        witnessed: false,
    }
}

/// Collect the universal-quantifier sub-formulas of an invariant. A lifted loop
/// is emitted as a `forall`, but the lifter conjoins a contract's atoms, so the
/// `inv` reaching here is typically `and([forall, ...])` rather than a bare
/// `forall`. We pull the `forall` conjuncts out (top-level, or directly under a
/// top-level `and`) so each can be asserted ambiently against point-claims. We
/// deliberately do NOT descend into the `and`'s non-forall operands -- asserting
/// a contract's point-claims into unrelated obligations would be unsound.
///
/// CLOSEDNESS GATE. The pool's shared vocabulary is CALLSITES (`call:*` ctors,
/// the `#euf#` names) -- that is what every lifter elides to, and it is the only
/// vocabulary with pool-wide meaning. A universal earns ambient status because
/// it quantifies over a callsite, instantiable at any point-claim. A forall
/// still carrying a FREE variable (an un-elided test-local, e.g. a symbolic
/// range bound `n`) is a fact about THAT TEST's locals, not about a callsite:
/// two tests' unrelated locals can share a spelling, and conjoining the open
/// formula would couple them through name capture. Open universals stay home
/// (their own obligation still checks them); only closed ones travel.
fn collect_ambient_foralls(inv: &Json, out: &mut Vec<Json>) {
    let mut consider = |op: &Json| {
        if op.get("kind").and_then(|k| k.as_str()) != Some("forall") {
            return;
        }
        if formula_is_closed(op, &mut Vec::new()) {
            out.push(op.clone());
        } else {
            debug!(
                "verifier/ambient: open universal (free test-local variable) excluded from ambient set"
            );
        }
    };
    match inv.get("kind").and_then(|k| k.as_str()) {
        Some("forall") => consider(inv),
        Some("and") => {
            if let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    consider(op);
                }
            }
        }
        _ => {}
    }
}

/// True if every `var` occurrence in the formula/term tree is bound by an
/// enclosing quantifier. Walks `operands`/`args`/`body` recursively; `forall`
/// and `exists` extend the bound set for their body. Any binder shape we do
/// not understand (e.g. `lambda`) fails CLOSED -- excluding a universal from
/// the ambient set only loses refutation power, never soundness, so unknown
/// structure is treated as not-closed.
fn formula_is_closed(node: &Json, bound: &mut Vec<String>) -> bool {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("var") => {
            let name = node.get("name").and_then(|v| v.as_str()).unwrap_or("");
            bound.iter().any(|b| b == name)
        }
        Some("const") => true,
        Some("forall") | Some("exists") => {
            let Some(name) = node.get("name").and_then(|v| v.as_str()) else {
                return false;
            };
            bound.push(name.to_string());
            let ok = node
                .get("body")
                .map(|b| formula_is_closed(b, bound))
                .unwrap_or(false);
            bound.pop();
            ok
        }
        Some("lambda") => false,
        _ => {
            let mut ok = true;
            for key in ["operands", "args"] {
                if let Some(arr) = node.get(key).and_then(|v| v.as_array()) {
                    for child in arr {
                        ok = ok && formula_is_closed(child, bound);
                    }
                }
            }
            if let Some(b) = node.get("body") {
                ok = ok && formula_is_closed(b, bound);
            }
            ok
        }
    }
}

/// Conjoin the ambient universal invariants into an obligation's inv so the
/// solver can instantiate them against this obligation's point-claims. Empty
/// ambient set leaves the inv untouched.
/// Collect the uninterpreted-function (`ctor`) symbols a formula references —
/// its solver vocabulary. Two formulas are independent (disjoint-signature, so
/// sound to separate) iff they share no such symbol.
/// Structural / arithmetic plumbing ctors (`ref`, `deref`, `+`/`-`/`*`, bitwise,
/// range constructors) appear ubiquitously and are NOT meaningful uninterpreted
/// predicates to quantify over: the arithmetic ones are z3 builtins, and
/// `ref`/`deref`/`range` are wrappers applied to unrelated arguments. A universal
/// that shares ONLY such a symbol with an obligation does not constrain it
/// (`ref(Big::from_small 1)` never aliases `ref(1)`), so counting them as
/// relevance vocabulary spuriously drags unrelated lifted-loop universals
/// (bignum/ascii) into a trivial obligation through a common `ref`, turning
/// `align_of_val(ref 1) == 2` (SAT) into a quantifier-laden `unknown`. Excluding
/// them only makes relevance STRICTER (fewer foralls conjoined) -- sound, since a
/// dropped disjoint-signature universal is a conservative extension.
fn is_structural_hub_symbol(name: &str) -> bool {
    matches!(
        name,
        "ref" | "deref"
            | "+"
            | "-"
            | "*"
            | "int-div"
            | "int-rem"
            | "bit-and"
            | "bit-or"
            | "bit-xor"
            | "shift-left"
            | "shift-right"
            | "bit-not"
            | "range"
            | "range_incl"
    )
}

fn collect_ctor_symbols(j: &Json, out: &mut std::collections::BTreeSet<String>) {
    match j {
        Json::Object(m) => {
            if m.get("kind").and_then(|k| k.as_str()) == Some("ctor") {
                if let Some(n) = m.get("name").and_then(|n| n.as_str()) {
                    if !is_structural_hub_symbol(n) {
                        out.insert(n.to_string());
                    }
                }
            }
            for v in m.values() {
                collect_ctor_symbols(v, out);
            }
        }
        Json::Array(a) => {
            for v in a {
                collect_ctor_symbols(v, out);
            }
        }
        _ => {}
    }
}

/// A term is GROUND iff built entirely from constants (no variable) -- its value
/// is fixed by literals alone, so it is `t`-independent and pure-evaluable.
fn term_is_ground(t: &Json) -> bool {
    match t.get("kind").and_then(|k| k.as_str()) {
        Some("const") => true,
        Some("var") => false,
        Some("ctor") => t
            .get("args")
            .and_then(|a| a.as_array())
            .map(|a| a.iter().all(term_is_ground))
            .unwrap_or(true),
        _ => false,
    }
}

fn json_is_const(t: &Json) -> bool {
    t.get("kind").and_then(|k| k.as_str()) == Some("const")
}

/// A NON-GROUND COMPOUND: a constructor application (a call/method/field/deref/
/// projection) carrying at least one variable -- so its value MAY depend on
/// hidden state (`t`) the lift cannot see (interior mutability, a mutated binding,
/// a pointer write). Whether it is actually pure is a body-walk question we cannot
/// answer without the callee body.
fn is_nonground_compound(t: &Json) -> bool {
    t.get("kind").and_then(|k| k.as_str()) == Some("ctor") && !term_is_ground(t)
}

/// The kind of unwarranted conflict an `unsat` invariant exhibits.
enum ConflictKind {
    /// A non-ground compound (call/method/field/deref) pinned to differing values,
    /// or forced `X != X` -- a fork around `t`. The carried term is the offending
    /// call, for the body dig (v2) to classify: IMPURE -> legitimate trajectory
    /// (vindicate Discharged); PURE -> real contradiction (Unsatisfied).
    Trajectory(Json),
    /// A lift artifact unrelated to purity: value-equality conflated with
    /// reference-identity (`eq` and `ne` on one pair), or a partial order lowered
    /// onto a total encoding (asserted incomparability). Always refused.
    Relational(String),
}

// v2, the dig: the wp-based purity classifier. `callee_purity` reduces a callee's
// body via wp and returns Pure / Impure / Unknown, conservatively (Unknown on any
// ambiguity -- no body, wp refused, non-trivial `pre`, or an unexplained free var).
// Impure is reached only via an explicit lifter-injected `__state::`/`__hidden::`
// symbol; absent that, a stateful read with no body contract stays Unknown ->
// Refused. See `crate::callee_purity`.
use crate::callee_purity::{callee_purity, Purity};

/// v2 vindication. Given an `unsat` invariant that is an unwarranted conflict,
/// decide the final verdict: a fork-around-`t` trajectory is vindicated to
/// Discharged when its callee is PROVEN impure, convicted (Unsatisfied) when
/// PROVEN pure, and refused while purity is Unknown. Relational artifacts are
/// always refused. Returns None when the inv is not an unwarranted conflict, so
/// the caller keeps the raw verdict.
fn vindicate_or_refuse(
    inv: &Json,
    property_name: &str,
    pool: &MementoPool,
) -> Option<(ObligationVerdict, String)> {
    let kind = unwarranted_compound_conflict(inv)?;
    Some(match kind {
        ConflictKind::Trajectory(call) => match callee_purity(&call, pool) {
            Purity::Impure => (
                // SOUND LIMIT: knowing the callee is impure is NOT enough to discharge
                // at the verdict layer. The lifted inv does not carry the program-point
                // `t`, so `=(load(A),0) ∧ =(load(A),5)` is the SAME term whether it came
                // from two re-evaluations (different `t`, a legit trajectory) or from ONE
                // value bound once and pinned twice (same `t`, a real contradiction -- a
                // broken test). Discharging would falsePass the latter. So we still
                // REFUSE; true vindication needs lift-side `t`-tagging of impure-call
                // evaluations (re-evaluations become distinct terms -> discharge
                // naturally; a same-`t` double-pin stays a bare-var contradiction).
                ObligationVerdict::Refused,
                format!(
                    "refused: callee proven IMPURE, but the lift does not distinguish a \
                     re-evaluation (legit `t`-trajectory) from a single read pinned twice \
                     (real contradiction); not discharged without program-point `t` -- \
                     `{property_name}`"
                ),
            ),
            Purity::Pure => (
                ObligationVerdict::Unsatisfied,
                format!(
                    "CONVICTED: callee proven PURE (cannot fork around `t`); the conflicting \
                     pins are a real contradiction -- `{property_name}`"
                ),
            ),
            Purity::Unknown => (
                ObligationVerdict::Refused,
                format!(
                    "refused: conflicting pins on a non-ground call whose purity is unproven \
                     (no callee body); a real contradiction vs. a `t`-dependent trajectory \
                     cannot be distinguished -- not accused -- `{property_name}`"
                ),
            ),
        },
        ConflictKind::Relational(t) => (
            ObligationVerdict::Refused,
            format!(
                "refused: `{t}` -- value-equality vs reference-identity conflated, or a partial \
                 order on a total encoding; lift artifact, not a warranted contradiction -- \
                 `{property_name}`"
            ),
        ),
    })
}

/// THE VENDOR FIXED `t`. Each assertion is pinned at a concrete program point.
/// If an UNSAT invariant's contradiction rests on two or more pins (`=(T, c)`) of
/// the SAME non-ground compound `T` set to DIFFERENT constants, the
/// "contradiction" cannot be distinguished -- without the callee body -- from a
/// benign trajectory of an impure / `t`-dependent `T` (`get(i)==0`, then
/// `get(i)==4` after a mutation; the drop-counter even mutates via the drop
/// side-effects of OTHER bindings, with no syntactic reference to `i`). A PURE `T`
/// cannot fork around `t`, so for a pure `T` this WOULD be a real contradiction --
/// but proving purity is the dig (v2). Until then we must NOT accuse: return the
/// term so the caller REFUSES (not "contradictory", not "consistent").
///
/// Warranted contradictions are NOT reported here and stay `Unsatisfied`:
///   * pins on a BARE VAR -- a value bound once, so same `t` (`x==1 ∧ x==2`);
///   * pins on a GROUND call -- `t`-independent, pure-evaluable
///     (`numpy.add(2,3)==5` vs `==6`; `g(7)<10 ∧ g(7)<5`).
/// A same-`T` group with two distinct constants is independently UNSAT, so its
/// mere presence means the unsat cannot be cleanly accused.
fn unwarranted_compound_conflict(inv: &Json) -> Option<ConflictKind> {
    use std::collections::{BTreeMap, BTreeSet};

    // Canonical unordered pair key for two operand terms.
    fn upair(a: &Json, b: &Json) -> (String, String) {
        let x = serde_json::to_string(a).unwrap_or_default();
        let y = serde_json::to_string(b).unwrap_or_default();
        if x <= y {
            (x, y)
        } else {
            (y, x)
        }
    }
    // ≤-family vs ≥-family of a NON-STRICT comparison (strict `<`/`>` do not
    // witness incomparability: `not(a<b) ∧ not(a>b)` just means `a==b`).
    fn nonstrict_dir(name: &str) -> Option<&'static str> {
        match name {
            "lte" | "le" | "<=" | "\u{2264}" => Some("le"),
            "gte" | "ge" | ">=" | "\u{2265}" => Some("ge"),
            _ => None,
        }
    }
    fn is_eq(name: &str) -> bool {
        matches!(name, "=" | "eq")
    }
    fn is_ne(name: &str) -> bool {
        matches!(name, "ne" | "neq" | "distinct" | "\u{2260}")
    }

    #[derive(Default)]
    struct Acc {
        // (a) =(T,c) pins on a non-ground compound T -> set of distinct consts.
        pins: BTreeMap<String, BTreeSet<String>>,
        // (b) a non-ground compound forced `X != X` (self-distinct).
        self_ne: BTreeSet<String>,
        // (c) unordered pairs (>=1 non-ground compound) seen under `=` and `ne`.
        eq_pairs: BTreeSet<(String, String)>,
        ne_pairs: BTreeSet<(String, String)>,
        // (d) per pair, the set of NEGATED non-strict directions {le, ge}.
        neg_cmp: BTreeMap<(String, String), BTreeSet<&'static str>>,
        // serialized non-ground-compound term -> its Json, so a Trajectory
        // conflict can hand the offending call to the purity probe (v2).
        terms: BTreeMap<String, Json>,
    }

    // `negated` tracks whether we are under an odd number of `not`s.
    fn collect(inv: &Json, acc: &mut Acc, negated: bool) {
        match inv.get("kind").and_then(|k| k.as_str()) {
            Some("and") | Some("or") => {
                if let Some(ops) = inv.get("operands").and_then(|o| o.as_array()) {
                    for op in ops {
                        collect(op, acc, negated);
                    }
                }
            }
            Some("not") => {
                if let Some(ops) = inv.get("operands").and_then(|o| o.as_array()) {
                    for op in ops {
                        collect(op, acc, !negated);
                    }
                } else if let Some(op) = inv.get("operand") {
                    collect(op, acc, !negated);
                }
            }
            Some("atomic") => {
                let name = inv.get("name").and_then(|n| n.as_str()).unwrap_or("");
                let Some(args) = inv.get("args").and_then(|a| a.as_array()) else {
                    return;
                };
                if args.len() != 2 {
                    return;
                }
                let (a, b) = (&args[0], &args[1]);
                if !negated && is_eq(name) {
                    // (a) fork-around-`t` in equality form.
                    let pin = if is_nonground_compound(a) && json_is_const(b) {
                        Some((a, b))
                    } else if is_nonground_compound(b) && json_is_const(a) {
                        Some((b, a))
                    } else {
                        None
                    };
                    if let Some((term, c)) = pin {
                        let key = serde_json::to_string(term).unwrap_or_default();
                        acc.terms.entry(key.clone()).or_insert_with(|| term.clone());
                        acc.pins
                            .entry(key)
                            .or_default()
                            .insert(serde_json::to_string(c).unwrap_or_default());
                    }
                    if is_nonground_compound(a) || is_nonground_compound(b) {
                        acc.eq_pairs.insert(upair(a, b));
                    }
                }
                if !negated && is_ne(name) {
                    // (b) `X != X` on a non-ground compound (re-evaluated stateful
                    // call), and (c) record the inequality pair.
                    if is_nonground_compound(a)
                        && serde_json::to_string(a).ok() == serde_json::to_string(b).ok()
                    {
                        let key = serde_json::to_string(a).unwrap_or_default();
                        acc.terms.entry(key.clone()).or_insert_with(|| a.clone());
                        acc.self_ne.insert(key);
                    }
                    if is_nonground_compound(a) || is_nonground_compound(b) {
                        acc.ne_pairs.insert(upair(a, b));
                    }
                }
                if negated {
                    // (d) a NEGATED non-strict comparison witnesses one direction
                    // of an asserted incomparability.
                    if let Some(dir) = nonstrict_dir(name) {
                        acc.neg_cmp.entry(upair(a, b)).or_default().insert(dir);
                    }
                }
            }
            _ => {}
        }
    }

    let mut acc = Acc::default();
    collect(inv, &mut acc, false);

    // (a)/(b) fork-around-`t`: a non-ground compound pinned to >=2 distinct values,
    // or forced `X != X`. Eligible for purity vindication -- carry the offending
    // call so the dig can classify it.
    let traj_key = acc
        .pins
        .iter()
        .find(|(_, consts)| consts.len() >= 2)
        .map(|(k, _)| k.clone())
        .or_else(|| acc.self_ne.iter().next().cloned());
    if let Some(k) = traj_key {
        let term = acc.terms.get(&k).cloned().unwrap_or(Json::Null);
        return Some(ConflictKind::Trajectory(term));
    }
    // (c) RELATION CONFLATION: the SAME pair asserted both equal AND unequal,
    // with a non-ground compound operand. The lift merged value-equality and
    // reference-identity (`assert_eq!(a,&*b)` + `ptr::eq`) onto one `=`/`ne`; we
    // cannot warrant they are the same relation -> refuse, do not accuse.
    if let Some((x, _)) = acc.eq_pairs.intersection(&acc.ne_pairs).next() {
        return Some(ConflictKind::Relational(format!("eq∧ne:{x}")));
    }
    // (d) INCOMPARABILITY on a TOTAL encoding: a pair asserted neither `<=` nor
    // `>=`. For a total order `a<=b ∨ b<=a` always holds, so this is unsat only
    // because a PARTIAL order (PartialOrd / NaN / float) was lowered onto z3's
    // total `<=`. The encoding is wrong, not the vendor -> refuse.
    if let Some((pair, _)) = acc
        .neg_cmp
        .iter()
        .find(|(_, dirs)| dirs.contains("le") && dirs.contains("ge"))
    {
        return Some(ConflictKind::Relational(format!("incomparable:{}", pair.0)));
    }
    None
}

/// Conjoin ONLY the ambient universals RELEVANT to this obligation. An ambient
/// `forall` is conjoined iff its vocabulary intersects the obligation's (or that
/// of an already-included forall — relevance closure, so transitively-linked
/// universals are kept). A universal over disjoint vocabulary is a conservative
/// extension: it cannot change this obligation's SAT/UNSAT, so dropping it is
/// sound — and it removes the quantifier-instantiation cost that turned a
/// microsecond EUF check (e.g. `cmp::max_by`) into a >250ms `unknown` by dragging
/// 7 unrelated lifted-loop universals (bignum/ascii/case-folding) into it.
fn with_ambient_foralls(inv: Json, property_name: &str, ambient: &[Json]) -> Json {
    if ambient.is_empty() {
        return inv;
    }
    let mut relevant: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    collect_ctor_symbols(&inv, &mut relevant);
    let forall_syms: Vec<std::collections::BTreeSet<String>> = ambient
        .iter()
        .map(|f| {
            let mut s = std::collections::BTreeSet::new();
            collect_ctor_symbols(f, &mut s);
            s
        })
        .collect();
    let mut included = vec![false; ambient.len()];
    loop {
        let mut changed = false;
        for i in 0..ambient.len() {
            if included[i] {
                continue;
            }
            if forall_syms[i].iter().any(|s| relevant.contains(s)) {
                included[i] = true;
                relevant.extend(forall_syms[i].iter().cloned());
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    let chosen: Vec<Json> = ambient
        .iter()
        .enumerate()
        .filter(|(i, _)| included[*i])
        .map(|(_, f)| f.clone())
        .collect();
    if chosen.is_empty() {
        return inv;
    }
    debug!(
        property = property_name,
        ambient_relevant = chosen.len(),
        ambient_total = ambient.len(),
        "verifier/ambient: conjoining RELEVANT universals (disjoint-vocabulary ones dropped, sound)"
    );
    let mut operands = Vec::with_capacity(chosen.len() + 1);
    operands.push(inv);
    operands.extend(chosen);
    serde_json::json!({ "kind": "and", "operands": operands })
}

/// A consistency obligation to solve: the contract CID, the callsite-keyed
/// property name, and the (ambient-conjoined) invariant.
struct Obligation {
    cid: String,
    property_name: String,
    inv: Json,
}

/// Batch the z3 solve unless the plan is non-z3 or it is explicitly disabled.
/// Only the plain `z3` single-solver plan (the common consistency case) is
/// batched; coq/maude/portfolio plans keep the per-obligation `run_plan` path.
fn should_batch(plan: &SolverPlan) -> bool {
    if std::env::var("SUGAR_VERIFY_BATCH").as_deref() == Ok("0") {
        return false;
    }
    matches!(plan, SolverPlan::Single(n) if n == "z3")
}

/// Per-query solver timeout in ms (SUGAR_SOLVER_TIMEOUT_MS, then _SECS, else
/// 250ms — a pinned check is microseconds, so 250ms is generous headroom).
fn solver_timeout_ms() -> u64 {
    if let Ok(v) = std::env::var("SUGAR_SOLVER_TIMEOUT_MS") {
        if let Ok(n) = v.trim().parse::<u64>() {
            return n;
        }
    }
    if let Ok(v) = std::env::var("SUGAR_SOLVER_TIMEOUT_SECS") {
        if let Ok(n) = v.trim().parse::<u64>() {
            return n.saturating_mul(1000);
        }
    }
    250
}

fn unknown_symbol_frag(fragment: &str) -> Option<String> {
    const MARK: &str = "unknown constant ";
    let start = fragment.find(MARK)? + MARK.len();
    let sym: String = fragment[start..]
        .chars()
        .take_while(|c| !c.is_whitespace() && *c != '(' && *c != ')')
        .collect();
    (!sym.is_empty()).then_some(sym)
}

/// Solve all obligations by batching them through few z3 processes (PHASE 2 for
/// the z3 plan). emit_asserted each; compilation failures are Undecidable
/// (encoding STOP) and excluded from the batch. Verdicts map exactly as the
/// per-spawn path: raw `sat`->consistent, raw `unsat`->contradictory, unknown
/// constant->Refused (no discharger), timeout/unknown->Undecidable.
fn solve_obligations_batched(
    obligations: &[Obligation],
    pool: &MementoPool,
) -> Vec<ConsistencyResult> {
    let mut results: Vec<Option<ConsistencyResult>> = (0..obligations.len()).map(|_| None).collect();
    let mut scripts: Vec<String> = Vec::new();
    let mut script_idx: Vec<usize> = Vec::new();
    let dump_needle = std::env::var("SUGAR_DUMP_SMT").ok();
    for (i, o) in obligations.iter().enumerate() {
        match emit_asserted(&o.inv) {
            Ok(s) => {
                if let Some(needle) = &dump_needle {
                    if o.property_name.contains(needle.as_str()) {
                        let path = format!("/tmp/sugar_smt_dump_{i}.smt2");
                        let _ = std::fs::write(&path, &s);
                        eprintln!(
                            "[verify] dumped SMT for {} -> {} ({} bytes, {} forall)",
                            o.property_name,
                            path,
                            s.len(),
                            s.matches("forall").count()
                        );
                    }
                }
                scripts.push(s);
                script_idx.push(i);
            }
            Err(e) => {
                results[i] = Some(ConsistencyResult {
                    contract_cid: o.cid.clone(),
                    property_name: o.property_name.clone(),
                    verdict: ObligationVerdict::Undecidable,
                    reason: format!("consistency smt-emit (encoding STOP): {e}"),
                    witnessed: false,
                });
            }
        }
    }
    let timeout_ms = solver_timeout_ms();
    eprintln!(
        "[verify] batched z3: {} obligation(s), {}ms/query cap (pinned=µs; cap bounds the unpinned)",
        scripts.len(),
        timeout_ms
    );
    let outcomes = crate::solvers::batch::batch_solve(&scripts, "z3", timeout_ms, 100);
    let mut undecidable = 0usize;
    for (k, &i) in script_idx.iter().enumerate() {
        let o = &obligations[i];
        let outcome = &outcomes[k];
        let (verdict, reason) = if outcome.raw == ObligationVerdict::Refused {
            let sym = unknown_symbol_frag(&outcome.fragment).unwrap_or_default();
            (
                ObligationVerdict::Refused,
                format!(
                    "no discharger for `{sym}`: solver cannot interpret (unknown constant); \
                     refused, not guessed"
                ),
            )
        } else {
            let (mut v, label) = consistency_verdict(outcome.raw);
            let mut r = format!("{label} `{}` [batched z3]", o.property_name);
            // THE VENDOR FIXED `t`: an `unsat` on conflicting pins of a non-ground
            // compound is a fork-around-`t`, indistinguishable from a real
            // contradiction without the callee body (v2). Refuse, do not accuse.
            if v == ObligationVerdict::Unsatisfied {
                if let Some((nv, nr)) = vindicate_or_refuse(&o.inv, &o.property_name, pool) {
                    v = nv;
                    r = nr;
                }
            }
            (v, r)
        };
        if verdict == ObligationVerdict::Undecidable {
            undecidable += 1;
        }
        results[i] = Some(ConsistencyResult {
            contract_cid: o.cid.clone(),
            property_name: o.property_name.clone(),
            verdict,
            reason,
            witnessed: false,
        });
    }
    eprintln!(
        "[verify] batched z3: done; {} undecidable (unpinned/open -> the worklist)",
        undecidable
    );
    results.into_iter().map(|r| r.expect("every obligation assigned a result")).collect()
}

pub fn verify_consistency(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<String, SolverHandle>,
) -> Vec<ConsistencyResult> {
    OBLIGATIONS_CHECKED.store(0, Ordering::Relaxed);
    let candidates: Vec<(&String, &Json)> = pool
        .mementos
        .iter()
        .filter(|(_, env)| memento_kind(env) == Some("contract"))
        .filter_map(|(cid, env)| memento_body(env).map(|b| (cid, b)))
        .filter(|(_, body)| is_consistency_candidate(body))
        .collect();
    eprintln!(
        "[verify] consistency: {} candidate obligation(s); solver timeout caps unpinned queries",
        candidates.len()
    );

    // AMBIENT UNIVERSALS: a forall invariant (a lifted bounded loop, memento
    // `<test>::loop::<var>`, from any language's lifter) constrains every claim
    // about the callsites it quantifies. Assert each CLOSED, NON-WITNESS forall
    // as background in every obligation so the solver instantiates it against
    // point-claims -- `forall x. g(x)==1` refutes a sibling `g(2)==2`. This is
    // the cross-proof conjoin extended to quantified contracts, sound by the
    // same EUF purity (a pure `g(2)` has one value pool-wide): callsites are
    // the pool's shared vocabulary, so a closed universal over them is a
    // pool-wide fact, while an OPEN one (free test-local variable) is not (see
    // `collect_ambient_foralls`). WITNESS members are settled by recompute, per
    // member, and are never folded into the symbolic conjunction -- so their
    // invs are likewise never ambient-collected. Answered ONCE here, in the
    // shared engine, not per-lifter.
    let mut ambient_foralls: Vec<Json> = Vec::new();
    for (cid, body) in &candidates {
        if is_witness_member(body) {
            continue;
        }
        if let Some(inv) = body.get("inv") {
            let before = ambient_foralls.len();
            collect_ambient_foralls(inv, &mut ambient_foralls);
            let found = ambient_foralls.len() - before;
            if found > 0 {
                debug!(
                    cid = cid.as_str(),
                    contract = body
                        .get("name")
                        .and_then(|v| v.as_str())
                        .or_else(|| body.get("contractName").and_then(|v| v.as_str()))
                        .unwrap_or("<unnamed>"),
                    foralls = found,
                    inv_kind = inv.get("kind").and_then(|k| k.as_str()).unwrap_or("?"),
                    "verifier/ambient: collected universal(s) from contract inv"
                );
            }
        }
    }
    info!(
        candidates = candidates.len(),
        ambient_foralls = ambient_foralls.len(),
        "verifier/ambient: universals will be conjoined into every obligation"
    );
    eprintln!(
        "[verify] ambient foralls conjoined into EVERY obligation: {} (quantifiers = z3 instantiation, not µs eval)",
        ambient_foralls.len()
    );

    // CROSS-PROOF CONJOIN: group same-named contracts and conjoin their `inv`s
    // before the SAT check -- the cross-proof twin of mint's same-name coalesce
    // (cmd_mint.rs `ir_coalesced` / CoalesceEntry::InvOnly). When a consumer
    // asserts `np.add(2,3)==6` and an IMPORTED numpy proof asserts
    // `np.add(2,3)==5`, both land on `numpy.add#euf#...::assertion`; conjoining
    // gives `and(==5, ==6)` -> raw unsat -> CONTRADICTORY -> refused. Identical
    // assertions dedupe by CID (one member) and stay PROVEN. The contract NAME is
    // the content-keyed callsite, so same name == same callsite == sound to
    // conjoin -- the same invariant mint relies on.
    let mut by_name: std::collections::BTreeMap<String, Vec<(&String, &Json)>> =
        std::collections::BTreeMap::new();
    for (cid, body) in &candidates {
        let name = body
            .get("name")
            .and_then(|v| v.as_str())
            .or_else(|| body.get("contractName").and_then(|v| v.as_str()))
            .unwrap_or("<unnamed>")
            .to_string();
        by_name.entry(name).or_default().push((*cid, *body));
    }
    let groups: Vec<(String, Vec<(&String, &Json)>)> = by_name.into_iter().collect();

    // PHASE 1 (parallel, cheap, NO solving): settle witnesses and BUILD the
    // solver obligations. Collecting them all first lets PHASE 2 batch them into
    // a few z3 processes — a fresh z3 per obligation costs ~50ms alone and
    // ~270ms under contention, dwarfing the microsecond solve of a pinned check.
    let built: Vec<(Vec<ConsistencyResult>, Vec<Obligation>)> = groups
        .par_iter()
        .map(|(property_name, members)| {
            let mut wits: Vec<ConsistencyResult> = Vec::new();
            let mut obls: Vec<Obligation> = Vec::new();
            let mut inv_cids: Vec<&String> = Vec::new();
            let mut inv_bodies: Vec<&Json> = Vec::new();
            for (m_cid, body) in members {
                if is_witness_member(body) {
                    if let Some(res) =
                        try_witness_discharge(body, (*m_cid).clone(), property_name.clone())
                    {
                        wits.push(res);
                        continue;
                    }
                }
                inv_bodies.push(body);
                inv_cids.push(m_cid);
            }
            if inv_bodies.is_empty() {
                return (wits, obls);
            }
            // CROSS-PROOF CONJOIN only for CALLSITE-KEYED names (`#euf#`), as before.
            let callsite_keyed = property_name.contains("#euf#");
            if callsite_keyed && inv_bodies.len() > 1 {
                let invs: Vec<Json> = inv_bodies
                    .iter()
                    .map(|b| b.get("inv").cloned().unwrap_or(Json::Null))
                    .collect();
                let inv = serde_json::json!({ "kind": "and", "operands": invs });
                obls.push(Obligation {
                    cid: inv_cids[0].clone(),
                    property_name: property_name.clone(),
                    inv: with_ambient_foralls(inv, property_name, &ambient_foralls),
                });
            } else {
                for (cid, body) in inv_cids.iter().zip(inv_bodies.iter()) {
                    let inv = body.get("inv").cloned().unwrap_or(Json::Null);
                    obls.push(Obligation {
                        cid: (*cid).clone(),
                        property_name: property_name.clone(),
                        inv: with_ambient_foralls(inv, property_name, &ambient_foralls),
                    });
                }
            }
            (wits, obls)
        })
        .collect();

    let mut results: Vec<ConsistencyResult> = Vec::new();
    let mut obligations: Vec<Obligation> = Vec::new();
    for (wits, obls) in built {
        results.extend(wits);
        obligations.extend(obls);
    }

    // PHASE 2: solve. Batch through few z3 processes when the plan is plain z3
    // (the common case); otherwise the general per-obligation plan path.
    if should_batch(plan) {
        results.extend(solve_obligations_batched(&obligations, pool));
    } else {
        let solved: Vec<ConsistencyResult> = obligations
            .par_iter()
            .map(|o| {
                check_inv_consistency(o.cid.clone(), &o.property_name, o.inv.clone(), plan, registry, pool)
            })
            .collect();
        results.extend(solved);
    }

    info!(
        candidates = candidates.len(),
        consistent = results
            .iter()
            .filter(|r| r.verdict == ObligationVerdict::Discharged)
            .count(),
        contradictory = results
            .iter()
            .filter(|r| r.verdict == ObligationVerdict::Unsatisfied)
            .count(),
        undecidable = results
            .iter()
            .filter(|r| r.verdict == ObligationVerdict::Undecidable)
            .count(),
        witnessed = results.iter().filter(|r| r.witnessed).count(),
        "verifier: test-assertion consistency pass complete"
    );

    results
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::solvers::registry;
    use serde_json::json;
    use std::sync::{Mutex, OnceLock};

    static WITNESS_ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

    fn witness_env_lock() -> std::sync::MutexGuard<'static, ()> {
        WITNESS_ENV_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap()
    }

    fn pool_with_contract(name: &str, inv: Json) -> MementoPool {
        let mut pool = MementoPool::default();
        let cid = format!("blake3-512:{name}");
        // v1.2 layered shape: accessors branch on presence of `envelope`.
        let env = json!({
            "envelope": {
                "header": {
                    "kind": "contract",
                    "contractName": name,
                    "inv": inv,
                }
            }
        });
        pool.insert(cid.clone(), env);
        pool
    }

    fn z3_plan_and_registry() -> (SolverPlan, HashMap<String, SolverHandle>) {
        let registry = registry::build_default_z3("z3");
        (SolverPlan::Single("z3".into()), registry)
    }

    fn ne(a: Json, b: Json) -> Json {
        json!({"kind":"atomic","name":"≠","args":[a,b]})
    }
    fn eqf(a: Json, b: Json) -> Json {
        json!({"kind":"atomic","name":"=","args":[a,b]})
    }
    fn var(n: &str) -> Json {
        json!({"kind":"var","name":n})
    }
    fn none() -> Json {
        json!({"kind":"ctor","name":"None","args":[]})
    }
    fn int(n: i64) -> Json {
        json!({"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":n})
    }
    fn gt(a: Json, b: Json) -> Json {
        json!({"kind":"atomic","name":">","args":[a,b]})
    }
    fn insert_contract(pool: &mut MementoPool, cid: &str, name: &str, inv: Json) {
        let env = json!({
            "envelope": { "header": { "kind": "contract", "contractName": name, "inv": inv } }
        });
        pool.insert(cid.to_string(), env);
    }

    fn unique_temp_dir(label: &str) -> std::path::PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "sugar-verifier-{label}-{}-{nanos}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn set_executable(path: &std::path::Path) {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
    }

    fn package_contract(tool: &str, package_cid: &str, count: usize, passed: usize) -> Json {
        let proof_data = json!({
            "kind": "witness-package",
            "packageCid": package_cid,
            "testFiles": ["tests/failing.rs"],
            "codeFiles": ["src/lib.rs"],
            "count": count,
            "passed": passed,
        })
        .to_string();
        json!({
            "kind": "contract",
            "contractName": format!("{tool}:witness-package"),
            "inv": {"kind":"atomic","name":"witnessed","args":[]},
            "evidence": {"kind":"evidence","proofType":"custom",
                         "certificate":{"tool":tool,"proofData":proof_data}},
        })
    }

    fn write_resolver_manifest(project: &std::path::Path, package_bytes: &[u8]) {
        let manifest_dir = project.join(".sugar").join("lift").join("fake-witness");
        std::fs::create_dir_all(&manifest_dir).unwrap();
        let script = manifest_dir.join("resolve.sh");
        let reply = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "resolved_by": "package",
                "body_b64": B64.encode(package_bytes),
            }
        })
        .to_string();
        std::fs::write(
            &script,
            format!("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' '{}'\n", reply),
        )
        .unwrap();
        set_executable(&script);
        let manifest = format!(
            "name = \"fake-witness\"\n\
             working_dir = \".\"\n\
             resolve_witness_command = [\"{}\"]\n\
             resolve_witness_method = \"sugar.plugin.resolve_witness\"\n",
            script.display()
        );
        std::fs::write(manifest_dir.join("manifest.toml"), manifest).unwrap();
    }

    fn write_discharge_stdout(project: &std::path::Path, verdict: &str) -> std::path::PathBuf {
        let script = project.join("lie-discharge.sh");
        std::fs::write(
            &script,
            format!(
                "#!/bin/sh\necho '{{\"verdict\":\"{verdict}\",\"reason\":\"lying oracle\"}}'\n"
            ),
        )
        .unwrap();
        set_executable(&script);
        script
    }

    fn tool_env_key(tool: &str) -> String {
        format!(
            "SUGAR_WITNESS_DISCHARGE_{}",
            tool.to_uppercase()
                .replace(|c: char| !c.is_ascii_alphanumeric(), "_")
        )
    }

    /// CROSS-PROOF CONJOIN: two contracts sharing a callsite name -- a consumer's
    /// assertion and an IMPORTED vendor contract about the same call -- are
    /// CONJOINED before the SAT check, not kept-one-dropped-one. This is what
    /// makes a numpy USER who asserts `np.add(2,3)==6` get REFUSED against an
    /// inherited numpy `==5`. Discrimination guards the false-refusal boundary:
    /// a CONSISTENT conjunction stays PROVEN, and a lone contract is untouched.
    #[test]
    fn cross_proof_same_named_contracts_are_conjoined() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "numpy.add#euf#callresult_numpy_add_a2(2,3)::assertion";

        // consumer ==6 + imported numpy ==5 (distinct CIDs) -> and(==5,==6) -> REFUSED
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:consumer6",
            name,
            eqf(var("r"), int(6)),
        );
        insert_contract(&mut pool, "blake3-512:numpy5", name, eqf(var("r"), int(5)));
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(
            res.len(),
            1,
            "same-named contracts collapse to one obligation: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "cross-proof contradiction must be refused: {res:?}"
        );

        // consumer ==5 + numpy r>0 (distinct CIDs, CONSISTENT) -> and -> PROVEN
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:a", name, eqf(var("r"), int(5)));
        insert_contract(&mut pool, "blake3-512:b", name, gt(var("r"), int(0)));
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "consistent conjunction must stay proven (no false refusal): {res:?}"
        );

        // a LONE contract is untouched -> PROVEN
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:solo", name, eqf(var("r"), int(5)));
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(res[0].verdict, ObligationVerdict::Discharged);
    }

    /// THE FORK-AROUND-`t` GUARD (the lemma, as teeth). A test pins the SAME
    /// non-ground compound `get(i)` to two values -- a `t`-dependent trajectory
    /// (an interior-mutable read), NOT a contradiction. Without the callee body we
    /// cannot prove `get` pure, so we REFUSE rather than accuse. A GROUND call
    /// (`add(2,3)`) and a BARE VAR (`x`) are warranted, so their conflicts stay
    /// `Unsatisfied` -- the discrimination that keeps the numpy/holster findings
    /// real. An identical repeated observation is the fixedpoint holding: no fork,
    /// consistent.
    #[test]
    fn nonground_compound_conflict_is_refused_not_accused() {
        let (plan, reg) = z3_plan_and_registry();
        let get_i = || json!({"kind":"ctor","name":"method:get","args":[var("i")]});
        let andf = |ops: Vec<Json>| json!({"kind":"and","operands":ops});

        // (1) impure/unknown fork: get(i)==0 ∧ get(i)==4 -> REFUSED (not accused)
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:traj",
            "method:get#euf#c:callresult_method_get_a1(v:t::i)::assertion",
            andf(vec![eqf(get_i(), int(0)), eqf(get_i(), int(4))]),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "a fork-around-t on a non-ground compound must be refused, not accused: {res:?}"
        );

        // (2) pure GROUND call fork: add(2,3)==5 ∧ add(2,3)==6 -> still UNSATISFIED
        let add23 = || json!({"kind":"ctor","name":"call:add","args":[int(2), int(3)]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:ground",
            "add#euf#c:callresult_add_a2(i:2,i:3)::assertion",
            andf(vec![eqf(add23(), int(5)), eqf(add23(), int(6))]),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "a ground-arg (t-independent, pure) call conflict is a real contradiction: {res:?}"
        );

        // (3) BARE VAR same-t: x==1 ∧ x==2 -> UNSATISFIED (single binding, same t)
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:bare",
            "x#euf#c:callresult_x_a0()::assertion",
            andf(vec![eqf(var("x"), int(1)), eqf(var("x"), int(2))]),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "a bare-var (same-t, value bound once) conflict is a real contradiction: {res:?}"
        );

        // (5) self-distinct (fork-around-t in inequality form): ne(nth(it),nth(it))
        //     -- a re-evaluated stateful call forced unequal to itself. REFUSED.
        let nth_it = || json!({"kind":"ctor","name":"method:nth","args":[var("it"), int(0)]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:selfne",
            "method:nth#euf#c:callresult_method_nth_a2(v:t::it,i:0)::assertion",
            json!({"kind":"atomic","name":"ne","args":[nth_it(), nth_it()]}),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "ne(X,X) on a non-ground compound (stateful re-evaluation) must be refused: {res:?}"
        );

        // (4) idempotent repeat (the fixedpoint holds, no fork): get(i)==4 ∧ ==4
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:idem",
            "method:get#euf#c:callresult_method_get_a1(v:t::j)::assertion",
            andf(vec![eqf(get_i(), int(4)), eqf(get_i(), int(4))]),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "identical repeated observation is consistent (fixedpoint holds), not refused: {res:?}"
        );

        // (6) RELATION CONFLATION (C): a == ref(deref b) ∧ a != ref(deref b).
        //     value-equality and pointer-identity merged onto one =/ne over a
        //     non-ground compound -> cannot warrant they are one relation -> REFUSED.
        let refderef_b =
            || json!({"kind":"ctor","name":"ref","args":[{"kind":"ctor","name":"deref","args":[var("b")]}]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:clone",
            "method:clone_to_uninit#euf#c:callresult_x_a0()::assertion",
            json!({"kind":"and","operands":[
                {"kind":"atomic","name":"=","args":[var("a"), refderef_b()]},
                {"kind":"atomic","name":"ne","args":[var("a"), refderef_b()]}
            ]}),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "eq∧ne on the same non-ground-compound pair (relation conflation) must be refused: {res:?}"
        );

        // (7) INCOMPARABILITY (D): not(x<=y) ∧ not(x>=y). On z3's TOTAL Int order
        //     this is unsat, but it is only assertable for a PARTIAL order
        //     (PartialOrd/NaN) lowered onto the wrong encoding -> REFUSED.
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:partialord",
            "tuple_cmp#euf#c:callresult_cmp_a2(v:t::x,v:t::y)::assertion",
            json!({"kind":"and","operands":[
                {"kind":"not","operands":[{"kind":"atomic","name":"lte","args":[var("x"), var("y")]}]},
                {"kind":"not","operands":[{"kind":"atomic","name":"gte","args":[var("x"), var("y")]}]}
            ]}),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "asserted incomparability (partial order on a total encoding) must be refused: {res:?}"
        );
    }

    /// THE HOLSTER DEMO. A vendor swears `result < X`; a consumer swears
    /// `result < Y` about THE SAME CALLSITE. To Sugar these are not two
    /// contracts that happen to be related -- they are ONE contract, because a
    /// contract's identity is the `#euf#` callsite CID, not the predicate. Two
    /// separate `.proof`s (distinct memento CIDs) carrying different bounds on
    /// `g(7)` collapse to a single obligation and are conjoined. Compatible
    /// bounds stay PROVEN; opposite bounds REFUTE -- the same contract, judged
    /// once. Prints the verdicts so the mechanism is visible, not just asserted.
    #[test]
    fn vendor_lt_x_and_consumer_lt_y_are_the_same_contract() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "g#euf#c:callresult_g_a1(i:7)::assertion";
        let lt = |a: Json, b: Json| json!({"kind":"atomic","name":"<","args":[a, b]});
        let callg = json!({"kind":"ctor","name":"call:g","args":[int(7)]});

        // VENDOR proof: g(7) < 10.  CONSUMER proof: g(7) < 5.  Distinct CIDs,
        // SAME callsite name -> one obligation -> and(<10, <5) -> SAT (e.g. 4)
        // -> the two bounds are the same contract and they agree.
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:vendor10",
            name,
            lt(callg.clone(), int(10)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:consumer5",
            name,
            lt(callg.clone(), int(5)),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(
            res.len(),
            1,
            "vendor<10 and consumer<5 are ONE contract: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "compatible bounds on the same callsite stay proven: {res:?}"
        );
        println!(
            "[holster] vendor `g(7) < 10` + consumer `g(7) < 5`  (2 proofs, 1 contract by #euf# CID)  -> {:?}",
            res[0].verdict
        );

        // CONSUMER now swears g(7) < 5 while the VENDOR swears g(7) > 10. Same
        // callsite -> same contract -> and(<5, >10) -> UNSAT -> REFUSED. The
        // consumer's bound contradicts the vendor's, and Sugar names the clash
        // because it never thought of them as two separate things.
        let gtp = |a: Json, b: Json| json!({"kind":"atomic","name":">","args":[a, b]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:vendorGt10",
            name,
            gtp(callg.clone(), int(10)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:consumerLt5",
            name,
            lt(callg.clone(), int(5)),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1, "still ONE contract: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "opposite bounds on the same callsite must refute: {res:?}"
        );
        println!(
            "[holster] vendor `g(7) > 10` + consumer `g(7) < 5`  (2 proofs, 1 contract by #euf# CID)  -> {:?}",
            res[0].verdict
        );
    }

    /// H1 [B7]: MIXED-SORT CONJUNCTION is a NAMED Undecidable, not a parse error.
    /// Two same-named contracts equate the same `call:f` ctor to a String literal
    /// (String-theory regime: String return sort) and to an Int literal (legacy
    /// regime: Int return sort). One declare-fun cannot carry both return sorts;
    /// before the fix the conjoined emit produced an ill-sorted script -> z3
    /// parse error -> an OPAQUE undecidable. Now the emitter refuses by name and
    /// the verifier surfaces the reason in the ConsistencyResult.
    #[test]
    fn mixed_sort_conjunction_is_named_undecidable() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "f#euf#callresult_f_a1(i:1)::assertion";
        let callf = json!({"kind":"ctor","name":"call:f","args":[int(1)]});

        // A GENUINE mixed-sort: a chars-in-set UNIVERSE string-taints call:f to
        // the String return sort, while a sibling Int equality forces Int. One
        // declare-fun cannot carry both -> named Undecidable. (Since the
        // string-contagion fix, a BARE `call:f == "abc"` with no universe is
        // NOT mixed-sort -- the untainted ctor stays opaque-Int and the
        // String-vs-Int conflict refutes cleanly as Unsatisfied instead.)
        let universe = json!({"kind":"atomic","name":"str.chars-in-set","args":[
            callf.clone(),
            {"kind":"const","sort":{"kind":"primitive","name":"String"},"value":"abc"}]});

        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:strrow", name, universe);
        insert_contract(&mut pool, "blake3-512:introw", name, eqf(callf, int(7)));
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(
            res.len(),
            1,
            "same-named contracts collapse to one obligation: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Undecidable,
            "mixed-sort conjunction must be a LOUD Undecidable: {res:?}"
        );
        assert!(
            res[0].reason.contains("mixed-sort conjunction on call:f"),
            "reason must name the conflict and the ctor: {}",
            res[0].reason
        );
        assert!(
            res[0].reason.contains("String vs Int"),
            "reason must name both regimes: {}",
            res[0].reason
        );
    }

    /// A bounded loop lifts to a guarded universal `forall x. (0<=x<3 => f(x)==1)`.
    /// The verifier must REFUTE a claim that contradicts it at an in-range point:
    /// conjoined with `f(2)==2`, z3 instantiates x=2 and the conjunction is UNSAT.
    /// This is the loops-to-forall mechanism proven end to end, in z3 -- not the
    /// lifter's word, the solver's verdict.
    #[test]
    fn bounded_forall_refutes_contradicting_claim_in_range() {
        let (plan, reg) = z3_plan_and_registry();
        let xvar = || var("x");
        let callf = |arg: Json| json!({"kind":"ctor","name":"call:f","args":[arg]});
        // forall x:Int. ( 0<=x<3 => f(x)==1 )
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), xvar()]}),
            json!({"kind":"atomic","name":"<","args":[xvar(), int(3)]}),
        ]});
        let body = eqf(callf(xvar()), int(1));
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[guard, body]}),
        });
        let name = "loop.rs::t::assertion";

        // The universal alone is consistent (PROVEN).
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:fa", name, forall.clone());
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "bounded universal alone must be consistent: {res:?}"
        );

        // Conjoined with f(2)==2 (an in-range contradiction): REFUTED.
        let contradiction = json!({"kind":"and","operands":[
            forall.clone(),
            eqf(callf(int(2)), int(2)),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:fc", name, contradiction);
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "z3 must instantiate x=2 and refute f(2)==1 and f(2)==2: {res:?}"
        );
    }

    /// THE REAL-PIPELINE SHAPE. The lifter emits the loop universal and the
    /// point-claim as SEPARATE mementos with DIFFERENT names (`...::loop::x` vs
    /// `g#euf#...::assertion`), and wraps each inv in `and([...])`. The earlier
    /// hand-conjoined test masked the bug where the ambient pass only matched a
    /// bare top-level `forall` (never `and([forall])`) and so never refuted. This
    /// reproduces the forall-loop-showcase bad twin in-process: two mementos, the
    /// universal must refute the in-range point-claim via the ambient rule alone.
    #[test]
    fn ambient_forall_refutes_separate_point_claim_memento() {
        let (plan, reg) = z3_plan_and_registry();
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        // forall x. (0<=x<3 => g(x)==1), wrapped in `and([forall])` exactly as the
        // lifter emits it.
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("x")]}),
            json!({"kind":"atomic","name":"<","args":[var("x"), int(3)]}),
        ]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[guard, eqf(callg(var("x")), int(1))]}),
        });
        let loop_inv = json!({"kind":"and","operands":[forall]});
        // The in-range point-claim g(2)==2, a DIFFERENT name, also `and`-wrapped.
        let point_inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:loop",
            "src/lib.rs::tests::t::loop::x",
            loop_inv,
        );
        insert_contract(
            &mut pool,
            "blake3-512:point",
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            point_inv,
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 2, "two separate obligations: {res:?}");
        // Pin WHICH row refutes: the point-claim must be the Unsatisfied one and
        // the loop universal itself must stay internally consistent. An any()
        // over both rows would stay green if a regression flipped the wrong row.
        let point = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:point")
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Unsatisfied,
            "the ambient universal must refute the separate point-claim memento: {res:?}"
        );
        let loop_row = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:loop")
            .expect("loop row present");
        assert_eq!(
            loop_row.verdict,
            ObligationVerdict::Discharged,
            "the loop universal alone is consistent: {res:?}"
        );
    }

    /// CLOSEDNESS DISCRIMINATION. A forall whose range bound is a FREE variable
    /// (an un-elided test-local `n`) is a fact about that test's locals, not
    /// about a callsite, and must NOT travel ambiently: two tests' unrelated
    /// locals can share a spelling and would couple through name capture. The
    /// open universal stays home; the separate in-range-looking point-claim
    /// stays Discharged.
    #[test]
    fn open_forall_is_not_ambient() {
        let (plan, reg) = z3_plan_and_registry();
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        // forall x. (0<=x<n => g(x)==1) -- `n` is FREE (test-local bound).
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("x")]}),
            json!({"kind":"atomic","name":"<","args":[var("x"), var("n")]}),
        ]});
        let open_forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[guard, eqf(callg(var("x")), int(1))]}),
        });
        let loop_inv = json!({"kind":"and","operands":[open_forall]});
        let point_inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:openloop",
            "src/lib.rs::tests::t::loop::x",
            loop_inv,
        );
        insert_contract(
            &mut pool,
            "blake3-512:openpoint",
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            point_inv,
        );
        let res = verify_consistency(&pool, &plan, &reg);
        assert_eq!(res.len(), 2, "two separate obligations: {res:?}");
        let point = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:openpoint")
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Discharged,
            "an OPEN universal must not refute anything ambiently: {res:?}"
        );
    }

    /// WITNESS DISCRIMINATION. A witness member is settled by recompute, per
    /// member; its inv is never folded into the symbolic conjunction, so a
    /// closed forall riding in a witness member must NOT be ambient-collected
    /// against the symbolic point-claims.
    #[test]
    fn witness_member_forall_is_not_ambient() {
        let _env = witness_env_lock();
        std::env::remove_var("SUGAR_WITNESS_PROJECT_DIR");
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE");
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE_PYTEST");
        let (plan, reg) = z3_plan_and_registry();
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("x")]}),
            json!({"kind":"atomic","name":"<","args":[var("x"), int(3)]}),
        ]});
        let closed_forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[guard, eqf(callg(var("x")), int(1))]}),
        });
        let witness_member = json!({"envelope":{"header":{
            "kind":"contract","contractName":"src/lib.rs::tests::t::loop::x",
            "inv": json!({"kind":"and","operands":[closed_forall]}),
            "evidence":{"proofType":"custom","certificate":
                {"tool":"pytest","version":"x","formulaHash":"x","proofData":"{}"}}}}});
        let mut pool = MementoPool::default();
        pool.insert("blake3-512:witnessloop".to_string(), witness_member);
        insert_contract(
            &mut pool,
            "blake3-512:wpoint",
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]}),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        let point = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:wpoint")
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Discharged,
            "a witness member's forall must not leak into symbolic checks: {res:?}"
        );
    }

    /// A WITNESS member in a same-callsite group must NOT short-circuit the group
    /// and mask a contradictory inv conjunction. Witnesses settle per-member; the
    /// `and(==5,==6)` must still surface as Unsatisfied. (Review: CodeRabbit
    /// Critical / Codex P1 on the first-witnessed-member return.)
    #[test]
    fn witness_member_does_not_mask_a_contradictory_group() {
        let _env = witness_env_lock();
        std::env::remove_var("SUGAR_WITNESS_PROJECT_DIR");
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE");
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE_PYTEST");
        let (plan, reg) = z3_plan_and_registry();
        let name = "numpy.add#euf#c:callresult_numpy_add_a2(i:2,i:3)::assertion";
        let mut pool = MementoPool::default();
        // a custom-witness member sharing the callsite name (no project resolver
        // configured -> Undecidable, fail-closed; the point is it must not swallow
        // the group's contradiction).
        let witness = json!({"envelope":{"header":{
            "kind":"contract","contractName":name,"inv": eqf(var("r"), int(5)),
            "evidence":{"proofType":"custom","certificate":
                {"tool":"pytest","version":"x","formulaHash":"x","proofData":"{}"}}}}});
        pool.insert("blake3-512:witnessmember".to_string(), witness);
        insert_contract(&mut pool, "blake3-512:c5", name, eqf(var("r"), int(5)));
        insert_contract(&mut pool, "blake3-512:c6", name, eqf(var("r"), int(6)));
        let res = verify_consistency(&pool, &plan, &reg);
        assert!(
            res.iter()
                .any(|r| r.verdict == ObligationVerdict::Unsatisfied),
            "the contradiction must surface despite a witness member: {res:?}"
        );
    }

    /// Same callee NAME but DIFFERENT (non-callsite-keyed) test names must NOT be
    /// conjoined: two unrelated tests that share a function name stay independent,
    /// no false refusal. Only `#euf#` callsite keys conjoin across proofs.
    #[test]
    fn bare_test_names_are_not_conjoined() {
        let (plan, reg) = z3_plan_and_registry();
        let mut pool = MementoPool::default();
        // Two same-named, contradictory-looking contracts under a BARE test name.
        // They are about independent subjects; conjoining would falsely refuse.
        insert_contract(
            &mut pool,
            "blake3-512:t1",
            "test_add",
            eqf(var("r"), int(5)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:t2",
            "test_add",
            eqf(var("r"), int(6)),
        );
        let res = verify_consistency(&pool, &plan, &reg);
        // per-contract: each is internally satisfiable -> both Discharged, none refused.
        assert_eq!(
            res.len(),
            2,
            "bare names must NOT collapse into one obligation: {res:?}"
        );
        assert!(
            res.iter()
                .all(|r| r.verdict == ObligationVerdict::Discharged),
            "independent same-test-name contracts must not be conjoined: {res:?}"
        );
    }

    /// A lying discharge command cannot turn a failed witness package into a
    /// discharge. The row verdict must be derived from the resolved package
    /// bytes, whose CID is recomputed rust-side and whose per-test bodies commit
    /// their real `outcome`.
    #[test]
    fn lying_discharge_cannot_pass_failed_package_for_any_witness_kind() {
        let _env = witness_env_lock();
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"good\"}\n{\"outcome\":\"failed\",\"test\":\"bad\"}\n";
        let package_cid = blake3_512_of(package_bytes);

        for tool in ["pytest", "cargo-test", "junit", "testng"] {
            let project = unique_temp_dir(tool);
            write_resolver_manifest(&project, package_bytes);
            let lie = write_discharge_stdout(&project, "DISCHARGED");
            let env_key = tool_env_key(tool);
            std::env::set_var("SUGAR_WITNESS_PROJECT_DIR", &project);
            std::env::remove_var("SUGAR_WITNESS_DISCHARGE");
            std::env::set_var(&env_key, &lie);

            let body = package_contract(tool, &package_cid, 2, 1);
            let result =
                try_witness_discharge(&body, "blake3-512:cid".into(), "test_x".into()).unwrap();
            assert_eq!(
                result.verdict,
                ObligationVerdict::Unsatisfied,
                "tool={tool} must refuse the failed package despite a DISCHARGED stdout lie: {result:?}"
            );
            assert!(
                !result.witnessed,
                "failed package is not a witness discharge"
            );

            std::env::remove_var(&env_key);
            let _ = std::fs::remove_dir_all(&project);
        }

        std::env::remove_var("SUGAR_WITNESS_PROJECT_DIR");
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE");
    }

    #[test]
    fn all_passed_package_discharges_from_body_not_stdout() {
        let _env = witness_env_lock();
        let package_bytes =
            b"{\"outcome\":\"passed\",\"test\":\"one\"}\n{\"outcome\":\"passed\",\"test\":\"two\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("all-passed-package");
        write_resolver_manifest(&project, package_bytes);
        let lie = write_discharge_stdout(&project, "REFUSED");
        std::env::set_var("SUGAR_WITNESS_PROJECT_DIR", &project);
        std::env::set_var("SUGAR_WITNESS_DISCHARGE_PYTEST", &lie);

        let body = package_contract("pytest", &package_cid, 2, 2);
        let result =
            try_witness_discharge(&body, "blake3-512:cid".into(), "test_x".into()).unwrap();
        assert_eq!(result.verdict, ObligationVerdict::Discharged);
        assert!(
            result.reason.contains("all 2 outcomes passed"),
            "reason must cite rust-side package outcome: {result:?}"
        );
        assert!(result.witnessed);

        std::env::remove_var("SUGAR_WITNESS_PROJECT_DIR");
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE_PYTEST");
        let _ = std::fs::remove_dir_all(&project);
    }

    /// A contract WITHOUT a custom witness is untouched by the arm (falls through
    /// to the normal SAT path).
    #[test]
    fn non_witness_contract_ignores_the_arm() {
        let body = json!({"kind":"contract","contractName":"t","inv": ne(var("x"), none())});
        assert!(try_witness_discharge(&body, "c".into(), "t".into()).is_none());
    }

    #[test]
    fn consistent_assertions_prove_consistent() {
        // assert x is not None  (single satisfiable fact) -> ≠(x, None) -> SAT
        let inv = ne(var("x"), none());
        let pool = pool_with_contract("test_consistent", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Discharged,
            "consistent inv must be PROVEN-consistent; reason: {}",
            results[0].reason
        );
        assert!(
            results[0].reason.contains("mutually consistent"),
            "claim must be labeled consistency, got: {}",
            results[0].reason
        );
    }

    #[test]
    fn contradictory_assertions_are_refused() {
        // assert x is None AND assert x is not None
        //   -> and(=(x,None), ≠(x,None)) -> UNSAT
        let inv = json!({"kind":"and","operands":[
            eqf(var("x"), none()),
            ne(var("x"), none()),
        ]});
        let pool = pool_with_contract("test_contradictory", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Unsatisfied,
            "contradictory inv must be REFUSED; reason: {}",
            results[0].reason
        );
        assert!(
            results[0].reason.contains("contradictory"),
            "claim must be labeled contradiction, got: {}",
            results[0].reason
        );
    }

    #[test]
    fn pre_post_bearing_contract_is_not_a_consistency_candidate() {
        // A bridge-bearing contract (carries pre/post) must NOT be picked up
        // by this pass; it is the call-site path's job.
        let mut pool = MementoPool::default();
        let env = json!({
            "envelope": {
                "header": {
                    "kind": "contract",
                    "contractName": "bridge_contract",
                    "pre": ne(var("x"), none()),
                    "inv": ne(var("x"), none()),
                }
            }
        });
        pool.insert("blake3-512:bridge".into(), env);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert!(
            results.is_empty(),
            "pre-bearing contract must not be a consistency candidate"
        );
    }

    #[test]
    fn facts_setup_binding_contract_is_not_a_consistency_candidate() {
        // A `::facts` contract carries the call-site SETUP BINDING
        // (e.g. `y = make_value(x)` -> `=(y, make_value(x))`), not an
        // asserted property. It is SAT by construction and reporting it
        // as "test assertions mutually consistent" is vacuous and
        // mislabeled. It must NOT appear in the consistency report.
        let facts_inv = eqf(var("y"), none());
        let pool = pool_with_contract("make_value@t.py:6:8::facts", facts_inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert!(
            results.is_empty(),
            "::facts setup-binding contract must not be a consistency candidate; got: {:?}",
            results.iter().map(|r| &r.property_name).collect::<Vec<_>>()
        );
    }

    #[test]
    fn facts_indexed_setup_binding_contract_is_not_a_consistency_candidate() {
        // The duplicate-disambiguated `::facts::N` setup-binding form is
        // likewise excluded.
        let facts_inv = eqf(var("y"), none());
        let pool = pool_with_contract("make_value@t.py:6:8::facts::1", facts_inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert!(
            results.is_empty(),
            "::facts::N setup-binding contract must not be a consistency candidate; got: {:?}",
            results.iter().map(|r| &r.property_name).collect::<Vec<_>>()
        );
    }

    #[test]
    fn assertion_contract_remains_a_consistency_candidate() {
        // The `::assertion` contract carries the asserted property and MUST
        // still be checked. Guards against an over-broad `::facts` filter
        // (substring match would wrongly catch `::facts-implies-assertion`,
        // but that is an implication decl, not a contract; the asserted
        // property contract ends in `::assertion`).
        let inv = ne(var("y"), none());
        let pool = pool_with_contract("make_value@t.py:6:8::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(
            results.len(),
            1,
            "::assertion contract must remain a consistency candidate"
        );
        assert_eq!(results[0].verdict, ObligationVerdict::Discharged);
    }

    #[test]
    fn bare_var_pattern3_contract_remains_a_consistency_candidate() {
        // A whole-test Pattern-3 contract is named by the test (no `::facts`
        // suffix) and must remain a candidate.
        let inv = ne(var("x"), none());
        let pool = pool_with_contract("test_x_consistent", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(
            results.len(),
            1,
            "bare-var Pattern-3 contract must remain a consistency candidate"
        );
    }

    // ── String-equality consistency tests ─────────────────────────────────
    // These are the census contracts that were UNDECIDABLE before the fix.
    // Shape: `assert r == '{"a":1}'` lifts to `=(r, string_const)` in `inv`.

    fn string_const(s: &str) -> Json {
        json!({"kind":"const","value":s,"sort":{"kind":"primitive","name":"String"}})
    }

    #[test]
    fn single_string_equality_asserted_is_consistent() {
        // POSITIVE: `assert r == '{"a":1}'` — a single string-equality assertion
        // is satisfiable (consistent). Before the fix: UNDECIDABLE (parse error).
        // After fix: PROVEN-consistent (raw sat from z3).
        let inv = eqf(var("r"), string_const(r#"{"a":1}"#));
        let pool = pool_with_contract("encode_jcs::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Discharged,
            "single string-equality inv must be PROVEN-consistent (not UNDECIDABLE); \
             reason: {}",
            results[0].reason
        );
        assert!(
            !results[0].reason.contains("UNDECIDABLE")
                && !results[0].reason.contains("encoding STOP"),
            "single string-equality must not be UNDECIDABLE; got: {}",
            results[0].reason
        );
    }

    #[test]
    fn two_distinct_string_literals_same_var_consistency_refused() {
        // DISCRIMINATION: `assert r == "a"; assert r == "b"` with distinct literals.
        // Conjoined inv: `=(r,"a") ∧ =(r,"b")` — same var, two different string
        // constants — is UNSAT (refused as contradictory).
        // Before fix: UNDECIDABLE (parse error / ill-sorted).
        // After fix: REFUSED-contradictory (raw unsat from z3).
        let inv = json!({"kind":"and","operands":[
            eqf(var("r"), string_const("a")),
            eqf(var("r"), string_const("b")),
        ]});
        let pool = pool_with_contract("encode_jcs_two_literals::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Unsatisfied,
            "two-distinct-literal inv must be REFUSED (not UNDECIDABLE); reason: {}",
            results[0].reason
        );
        assert!(
            results[0].reason.contains("contradictory"),
            "must be labeled contradictory, got: {}",
            results[0].reason
        );
    }

    #[test]
    fn weird_char_string_literal_consistency_proven() {
        // STRUCTURAL: brace/backslash/unicode in the literal — must parse cleanly.
        // Before fix: UNDECIDABLE (z3 parse error on the raw literal text).
        // After fix: real sat/unsat verdict.
        let inv = eqf(var("r"), string_const(r#"{"a":"x"}"#));
        let pool = pool_with_contract("encode_jcs_brace::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_ne!(
            results[0].verdict,
            ObligationVerdict::Undecidable,
            "brace-containing string-literal inv must NOT be UNDECIDABLE; got: {}",
            results[0].reason
        );
    }

    // ── Cross-type literal distinctness (Python `==` semantics) ───────────
    // Permanent regression suite. The PROVEN/REFUSED verdict must match
    // Python's `==`: str/None disjoint from numbers and each other; bool IS
    // int (True==1, False==0). The `bool_true ... consistent` test is the
    // guard against over-distinctness and never leaves the suite.

    fn int_const(n: i64) -> Json {
        json!({"kind":"const","value":n,"sort":{"kind":"primitive","name":"Int"}})
    }
    fn bool_const(b: bool) -> Json {
        json!({"kind":"const","value":b,"sort":{"kind":"primitive","name":"Bool"}})
    }

    #[test]
    fn str_literal_vs_int_literal_is_refused() {
        // `assert r == "5"; assert r == 5` -> `=(r,"5") ∧ =(r,5)`.
        // Python `"5" != 5` -> contradictory -> REFUSED. (Was a falsePass:
        // both collapsed into Int with no distinctness -> sat -> "consistent".)
        let inv = json!({"kind":"and","operands":[
            eqf(var("r"), string_const("5")),
            eqf(var("r"), int_const(5)),
        ]});
        let pool = pool_with_contract("cross_str_int::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1);
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Unsatisfied,
            "`r==\"5\" ∧ r==5` must be REFUSED (Python str≠int); reason: {}",
            results[0].reason
        );
    }

    #[test]
    fn none_vs_int_literal_is_refused() {
        // `assert r is None; assert r == 5`. Python `None != 5` -> REFUSED.
        let inv = json!({"kind":"and","operands":[
            eqf(var("r"), none()),
            eqf(var("r"), int_const(5)),
        ]});
        let pool = pool_with_contract("cross_none_int::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1);
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Unsatisfied,
            "`r is None ∧ r==5` must be REFUSED (Python None≠int); reason: {}",
            results[0].reason
        );
    }

    #[test]
    fn none_vs_bool_false_is_refused() {
        // `assert r is None; assert r == False`. Python `None != False`
        // (False==0, None != 0) -> REFUSED. Discriminating test for the
        // "bool joins the concrete-int distinctness target set" wiring.
        let inv = json!({"kind":"and","operands":[
            eqf(var("r"), none()),
            eqf(var("r"), bool_const(false)),
        ]});
        let pool = pool_with_contract("cross_none_false::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1);
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Unsatisfied,
            "`r is None ∧ r==False` must be REFUSED (Python None≠False); reason: {}",
            results[0].reason
        );
    }

    #[test]
    fn bool_true_consistent_with_int_one_is_proven() {
        // OVER-DISTINCTNESS GUARD (permanent). `assert r == True; assert r == 1`.
        // Python `True == 1` -> CONSISTENT -> PROVEN. A REFUSED here would mean
        // bool was wrongly asserted distinct from int. This test never leaves
        // the suite.
        let inv = json!({"kind":"and","operands":[
            eqf(var("r"), bool_const(true)),
            eqf(var("r"), int_const(1)),
        ]});
        let pool = pool_with_contract("cross_true_one::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1);
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Discharged,
            "`r==True ∧ r==1` must be PROVEN-consistent (Python True==1); reason: {}",
            results[0].reason
        );
    }

    #[test]
    fn same_type_string_contradiction_still_refused() {
        // Regression guard: same-type two-literal contradiction unchanged.
        let inv = json!({"kind":"and","operands":[
            eqf(var("r"), string_const("a")),
            eqf(var("r"), string_const("b")),
        ]});
        let pool = pool_with_contract("same_str::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].verdict, ObligationVerdict::Unsatisfied);
    }
}
