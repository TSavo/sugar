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
// of the invariant itself. The manifest-backed compiler emits
// `assert (not goal); check-sat`, so this pass asks it to compile
// `goal = not(inv)`, yielding `assert inv; check-sat`.
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

use crate::solvers::{run_plan_with_compilers, SolverHandle, SolverInvocation, SolverPlan};
use crate::types::{
    memento_body, memento_body_field, memento_kind, MementoPool, ObligationVerdict,
};
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;

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
    pub verification: Option<Json>,
}

const CONSISTENT_REASON: &str = "test assertions mutually consistent about callsite";
const CONTRADICTORY_REASON: &str = "test assertions contradictory about callsite";

/// Does this contract carry asserted axioms that must be checked for
/// satisfiability against the local universe? We approximate the boundary
/// structurally: the pass fires for contracts that carry an `inv` and NO
/// `pre`. A `post` is allowed and is conjoined with the asserted `inv` as the
/// lifted universe relation. Pre-bearing contracts remain the call-site path's
/// job because their `pre` is an obligation, not an established fact.
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
pub(crate) fn is_consistency_candidate(body: &Json) -> bool {
    let has_inv = body.get("inv").map(|v| v.is_object()).unwrap_or(false);
    let has_pre = body.get("pre").map(|v| v.is_object()).unwrap_or(false);
    if !(has_inv && !has_pre) {
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

fn axiom_context_formula(body: &Json) -> Json {
    let inv = body.get("inv").cloned().unwrap_or(Json::Null);
    match body.get("post").filter(|post| post.is_object()).cloned() {
        Some(post) => json!({ "kind": "and", "operands": [inv, post] }),
        None => inv,
    }
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

fn structural_contradiction_reason(inv: &Json) -> Option<String> {
    let mut equalities: std::collections::BTreeMap<String, (String, String, String)> =
        std::collections::BTreeMap::new();
    collect_ground_equalities(inv, &mut equalities)
}

fn collect_ground_equalities(
    node: &Json,
    equalities: &mut std::collections::BTreeMap<String, (String, String, String)>,
) -> Option<String> {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => None,
        Some("and") => {
            for child in node.get("operands").and_then(|v| v.as_array())? {
                if let Some(reason) = collect_ground_equalities(child, equalities) {
                    return Some(reason);
                }
            }
            None
        }
        Some("implies") => {
            let operands = node.get("operands").and_then(|v| v.as_array())?;
            if operands.len() != 2 || !eval_ground_bool(&operands[0])? {
                return None;
            }
            collect_ground_equalities(&operands[1], equalities)
        }
        Some("atomic") if node.get("name").and_then(|v| v.as_str()) == Some("=") => {
            let (term, value) = ground_term_const_equality(node)?;
            record_ground_equality(term, value, equalities)
        }
        _ => None,
    }
}

fn record_ground_equality(
    term: &Json,
    value: &Json,
    equalities: &mut std::collections::BTreeMap<String, (String, String, String)>,
) -> Option<String> {
    let term_key = libsugar::canonical::json_jcs(term).ok()?;
    let value_key = libsugar::canonical::json_jcs(value).ok()?;
    let term_display = compact_json(term);
    let value_display = compact_json(value);
    if let Some((existing_key, existing_display, _)) = equalities.get(&term_key) {
        if existing_key != &value_key {
            return Some(format!(
                "{term_display} equals both {existing_display} and {value_display}"
            ));
        }
        return None;
    }
    equalities.insert(term_key, (value_key, value_display, term_display));
    None
}

fn ground_term_const_equality(eq: &Json) -> Option<(&Json, &Json)> {
    let args = eq.get("args").and_then(|v| v.as_array())?;
    if args.len() != 2 {
        return None;
    }
    match (is_ground_non_const_term(&args[0]), is_const_value(&args[1])) {
        (true, true) => Some((&args[0], &args[1])),
        _ if is_const_value(&args[0]) && is_ground_non_const_term(&args[1]) => {
            Some((&args[1], &args[0]))
        }
        _ => None,
    }
}

fn is_ground_non_const_term(node: &Json) -> bool {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("const") | Some("var") | Some("forall") | Some("exists") => false,
        Some("ctor") => node
            .get("args")
            .and_then(|v| v.as_array())
            .is_some_and(|args| args.iter().all(is_ground_term)),
        _ => false,
    }
}

fn is_ground_term(node: &Json) -> bool {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("const") => true,
        Some("ctor") => node
            .get("args")
            .and_then(|v| v.as_array())
            .is_some_and(|args| args.iter().all(is_ground_term)),
        _ => false,
    }
}

fn is_const_value(node: &Json) -> bool {
    node.get("kind").and_then(|k| k.as_str()) == Some("const")
}

fn eval_ground_bool(node: &Json) -> Option<bool> {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("and") => {
            for child in node.get("operands").and_then(|v| v.as_array())? {
                if !eval_ground_bool(child)? {
                    return Some(false);
                }
            }
            Some(true)
        }
        Some("or") => {
            for child in node.get("operands").and_then(|v| v.as_array())? {
                if eval_ground_bool(child)? {
                    return Some(true);
                }
            }
            Some(false)
        }
        Some("not") => {
            let operands = node.get("operands").and_then(|v| v.as_array())?;
            if operands.len() == 1 {
                eval_ground_bool(&operands[0]).map(|value| !value)
            } else {
                None
            }
        }
        Some("atomic") => eval_ground_atomic_bool(node),
        _ => None,
    }
}

fn eval_ground_atomic_bool(node: &Json) -> Option<bool> {
    let name = node.get("name").and_then(|v| v.as_str())?;
    let args = node.get("args").and_then(|v| v.as_array())?;
    if args.len() != 2 {
        return None;
    }
    let left = int_const_value(&args[0])?;
    let right = int_const_value(&args[1])?;
    match name {
        "<" => Some(left < right),
        ">" => Some(left > right),
        "\u{2264}" | "<=" => Some(left <= right),
        "\u{2265}" | ">=" => Some(left >= right),
        "=" => Some(left == right),
        "\u{2260}" | "!=" => Some(left != right),
        _ => None,
    }
}

fn int_const_value(node: &Json) -> Option<i64> {
    if node.get("kind").and_then(|k| k.as_str()) != Some("const") {
        return None;
    }
    if node
        .get("sort")
        .and_then(|s| s.get("kind"))
        .and_then(|v| v.as_str())
        != Some("primitive")
        || node
            .get("sort")
            .and_then(|s| s.get("name"))
            .and_then(|v| v.as_str())
            != Some("Int")
    {
        return None;
    }
    node.get("value").and_then(|v| v.as_i64())
}

fn compact_json(value: &Json) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "<json>".to_string())
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
        reason: reason.clone(),
        witnessed: false,
        verification: Some(json!({
            "kind": "witness",
            "witnessed": false,
            "verdict": ObligationVerdict::Undecidable.as_str(),
            "reason": reason,
        })),
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
            let reason = format!("witness REFUSED by rust package recompute: {e}");
            return Some(ConsistencyResult {
                contract_cid,
                property_name,
                verdict: ObligationVerdict::Unsatisfied,
                reason: reason.clone(),
                witnessed: false,
                verification: Some(json!({
                    "kind": "witness",
                    "witnessed": false,
                    "verdict": ObligationVerdict::Unsatisfied.as_str(),
                    "reason": reason,
                })),
            });
        }
    };
    Some(if outcome.failed == 0 {
        let reason = format!(
            "witness package verified by rust via {}; all {} outcomes passed",
            outcome.resolved_by, outcome.count
        );
        ConsistencyResult {
            contract_cid,
            property_name,
            verdict: ObligationVerdict::Discharged,
            reason: reason.clone(),
            witnessed: true,
            verification: Some(json!({
                "kind": "witness",
                "witnessed": true,
                "verdict": ObligationVerdict::Discharged.as_str(),
                "resolvedBy": outcome.resolved_by,
                "outcomes": outcome.count,
                "failed": outcome.failed,
                "reason": reason,
            })),
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
        let reason = format!(
            "witness REFUSED by rust package body: bundle reproduced via {}; \
             {}/{} outcomes failed: {}{}",
            outcome.resolved_by,
            outcome.failed,
            outcome.count,
            shown.join(", "),
            more
        );
        ConsistencyResult {
            contract_cid,
            property_name,
            verdict: ObligationVerdict::Unsatisfied,
            reason: reason.clone(),
            witnessed: false,
            verification: Some(json!({
                "kind": "witness",
                "witnessed": false,
                "verdict": ObligationVerdict::Unsatisfied.as_str(),
                "resolvedBy": outcome.resolved_by,
                "outcomes": outcome.count,
                "failed": outcome.failed,
                "failedTests": shown,
                "reason": reason,
            })),
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
    let mut found = witness_resolvers_from_env();
    if let Ok(entries) = std::fs::read_dir(&lift_dir) {
        for entry in entries.flatten() {
            let manifest = entry.path().join("manifest.toml");
            if let Some(resolver) = parse_witness_resolver(&manifest, project_root) {
                found.push(resolver);
            }
        }
    }
    found
}

fn witness_resolvers_from_env() -> Vec<WitnessResolver> {
    let Ok(raw) = std::env::var("SUGAR_WITNESS_RESOLVERS") else {
        return Vec::new();
    };
    let Ok(value): Result<Json, _> = serde_json::from_str(&raw) else {
        warn!("SUGAR_WITNESS_RESOLVERS was not valid JSON; ignoring configured witness resolvers");
        return Vec::new();
    };
    let Some(items) = value.as_array() else {
        warn!("SUGAR_WITNESS_RESOLVERS was not an array; ignoring configured witness resolvers");
        return Vec::new();
    };
    items
        .iter()
        .filter_map(|item| {
            let argv = item
                .get("argv")
                .and_then(|v| v.as_array())
                .map(|values| {
                    values
                        .iter()
                        .filter_map(|value| value.as_str().map(str::to_string))
                        .filter(|value| !value.is_empty())
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            if argv.is_empty() {
                return None;
            }
            let working_dir = item
                .get("working_dir")
                .or_else(|| item.get("workingDir"))
                .and_then(|v| v.as_str())
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."));
            let method = item
                .get("method")
                .and_then(|v| v.as_str())
                .unwrap_or("sugar.plugin.resolve_witness")
                .to_string();
            Some(WitnessResolver {
                argv,
                working_dir,
                method,
            })
        })
        .collect()
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

fn canonicalize_formula_json(inv: &Json) -> Json {
    let Ok(formula) = serde_json::from_value::<sugar_ir_types::IrFormula>(inv.clone()) else {
        return inv.clone();
    };
    serde_json::to_value(sugar_ir_types::canonicalize_formula(&formula))
        .unwrap_or_else(|_| inv.clone())
}

fn linked_posts_to_json(linked_posts: &[LinkedPostInstance]) -> Json {
    Json::Array(
        linked_posts
            .iter()
            .map(|p| {
                json!({
                    "sourceSymbol": &p.source_symbol,
                    "targetContractCid": &p.target_cid,
                    "targetProofCid": &p.target_proof_cid,
                    "formals": &p.formals,
                    "outBinding": &p.out_binding,
                    "call": &p.call,
                    "vendorPost": &p.vendor_post,
                    "instantiatedPost": &p.instantiated_post,
                })
            })
            .collect(),
    )
}

fn solver_invocations_to_json(invs: &[SolverInvocation]) -> Json {
    Json::Array(
        invs.iter()
            .map(|inv| {
                let stdout_first_line = inv
                    .result
                    .solver_stdout
                    .lines()
                    .map(str::trim)
                    .find(|line| !line.is_empty())
                    .unwrap_or("");
                let mut value = json!({
                    "solver": &inv.result.solver_name,
                    "version": &inv.result.solver_version,
                    "compiler": &inv.compiler,
                    "authoritative": inv.authoritative,
                    "verdict": inv.result.verdict.as_str(),
                    "timedOut": inv.result.timed_out,
                    "error": &inv.result.error,
                    "stdoutFirstLine": stdout_first_line,
                });
                if let Some(artifact_cid) = &inv.identity.artifact_cid {
                    value["solverArtifactCid"] = json!(artifact_cid);
                }
                if let Some(invocation_cid) = &inv.identity.invocation_cid {
                    value["solverInvocationCid"] = json!(invocation_cid);
                }
                if let Some(vendor_memento_cid) = &inv.identity.vendor_memento_cid {
                    value["solverVendorMementoCid"] = json!(vendor_memento_cid);
                }
                if let Some(vendor_memento) = &inv.identity.vendor_memento {
                    value["solverVendorMemento"] = vendor_memento.clone();
                }
                value
            })
            .collect(),
    )
}

fn consistency_verification_detail(
    property_name: &str,
    checked_formula: &Json,
    linked_posts: &[LinkedPostInstance],
    raw_verdict: Option<ObligationVerdict>,
    final_verdict: ObligationVerdict,
    solver_reason: Option<&str>,
    invs: &[SolverInvocation],
) -> Json {
    json!({
        "kind": "consistency",
        "property": property_name,
        "checkedFormula": checked_formula,
        "linkedPosts": linked_posts_to_json(linked_posts),
        "rawSolverVerdict": raw_verdict.map(|v| v.as_str()),
        "finalVerdict": final_verdict.as_str(),
        "solverReason": solver_reason,
        "solverInvocations": solver_invocations_to_json(invs),
    })
}

/// Run the raw-satisfiability consistency check on a single `inv` and label it.
/// Shared by the per-contract path and the cross-proof conjoined path.
fn check_inv_consistency(
    cid: String,
    property_name: &str,
    inv: Json,
    linked_posts: Vec<LinkedPostInstance>,
    plan: &SolverPlan,
    registry: &HashMap<String, SolverHandle>,
    compilers: &CompilerRegistry,
) -> ConsistencyResult {
    let t_local = std::time::Instant::now();
    let inv = with_local_forall_instances(canonicalize_formula_json(&inv), property_name);
    let local_inst_us = t_local.elapsed().as_micros();
    if let Some(reason) = structural_contradiction_reason(&inv) {
        let verdict = ObligationVerdict::Unsatisfied;
        return ConsistencyResult {
            contract_cid: cid,
            property_name: property_name.to_string(),
            verdict,
            reason: format!("{CONTRADICTORY_REASON} `{property_name}` [structural: {reason}]"),
            witnessed: false,
            verification: Some(consistency_verification_detail(
                property_name,
                &inv,
                &linked_posts,
                None,
                verdict,
                Some(&format!("structural: {reason}")),
                &[],
            )),
        };
    }
    let raw_sat_goal = json!({ "kind": "not", "operands": [inv.clone()] });
    let t_solve = std::time::Instant::now();
    let (raw, raw_reason, invs) = run_plan_with_compilers(plan, registry, compilers, &raw_sat_goal);
    let solve_us = t_solve.elapsed().as_micros();
    // Per-obligation phase split (timestamped): local-forall instantiation vs the
    // compile+solve round. Pairs with the "ambient instantiation hotspot" line
    // (same `property`) for a full instantiate-vs-solve breakdown. Non-trivial only.
    if local_inst_us + solve_us >= 2000 {
        info!(
            property = property_name,
            local_inst_us,
            solve_us,
            "verifier/timing: obligation phases (local-instantiate vs compile+solve)"
        );
    }
    let (verdict, label) = consistency_verdict(raw);
    let reason = format!("{label} `{property_name}` [{raw_reason}]");
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
        verification: Some(consistency_verification_detail(
            property_name,
            &inv,
            &linked_posts,
            Some(raw),
            verdict,
            Some(&raw_reason),
            &invs,
        )),
    }
}

/// Collect the universal-quantifier sub-formulas of an invariant. A lifted loop
/// is emitted as a `forall`, but the lifter conjoins a contract's atoms, so the
/// `inv` reaching here is typically `and([forall, ...])` rather than a bare
/// `forall`. We pull the `forall` conjuncts out (top-level, or under nested
/// conjunctions) as instantiation templates for point-claims. We deliberately
/// do NOT descend into the `and`'s non-forall operands -- asserting a contract's
/// point-claims into unrelated obligations would be unsound.
///
/// CLOSEDNESS GATE. The pool's shared vocabulary is CALLSITES (`call:*` ctors,
/// the `#euf#` names) -- that is what every lifter elides to, and it is the only
/// vocabulary with pool-wide meaning. A universal earns cross-obligation force
/// only through a CLOSED SPECIALIZED INSTANCE. A forall still carrying a FREE
/// variable after specialization (an un-elided test-local, e.g. a symbolic range
/// bound `n`) is a fact about THAT TEST's locals, not about a callsite: two
/// tests' unrelated locals can share a spelling, and conjoining the open formula
/// would couple them through name capture. Open templates may be collected, but
/// their open instances stay home.
fn collect_ambient_foralls(inv: &Json, out: &mut Vec<Json>) {
    let mut consider = |op: &Json| {
        if op.get("kind").and_then(|k| k.as_str()) != Some("forall") {
            return;
        }
        if !formula_is_closed(op, &mut Vec::new()) {
            debug!(
                "verifier/ambient: open universal template collected; only closed instances may travel"
            );
        }
        out.push(op.clone());
    };
    match inv.get("kind").and_then(|k| k.as_str()) {
        Some("forall") => consider(inv),
        Some("and") => {
            if let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    collect_ambient_foralls(op, out);
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

/// Derive quantifier-free instances of ambient universals for the concrete
/// callsite terms already present in this obligation. Z3 usually instantiates
/// `forall x. ... call:g(x) ...` against `call:g(2)` on its own, but that is a
/// heuristic. The verifier owns the pool vocabulary, so make the obvious
/// instantiation explicit before asking the solver.
fn instantiate_ambient_foralls_for_inv(
    inv: &Json,
    property_name: &str,
    ambient: &[Json],
) -> Vec<Json> {
    if ambient.is_empty() {
        return Vec::new();
    }
    // Discharge profiling (timestamped, real hotspot visibility -- no caps).
    let t_all = std::time::Instant::now();
    AMBIENT_SUBST_US.with(|c| c.set(0));
    AMBIENT_JCS_US.with(|c| c.set(0));
    let mut ground_terms_total = 0usize;
    let mut callsite_pairs = 0usize;

    let mut instances = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for forall in ambient {
        let Some(var_name) = forall.get("name").and_then(|v| v.as_str()) else {
            continue;
        };
        let Some(body) = forall.get("body") else {
            continue;
        };
        if let Some(sort) = forall.get("sort") {
            let mut ground_terms = Vec::new();
            collect_unquantified_ground_terms(inv, sort, &mut ground_terms);
            collect_property_name_ground_terms(property_name, sort, &mut ground_terms);
            ground_terms_total += ground_terms.len();
            for term in &ground_terms {
                push_ambient_instance(body, var_name, term, &mut instances, &mut seen);
            }
        }

        let mut callsites = Vec::new();
        collect_unquantified_ctor_terms(inv, &mut callsites);
        let mut patterns = Vec::new();
        collect_forall_call_patterns(body, var_name, &mut patterns);
        callsite_pairs += patterns.len().saturating_mul(callsites.len());
        for pattern in &patterns {
            for callsite in &callsites {
                let Some(replacement) = match_forall_call_pattern(pattern, callsite, var_name)
                else {
                    continue;
                };
                push_ambient_instance(body, var_name, &replacement, &mut instances, &mut seen);
            }
        }
    }

    let total_us = t_all.elapsed().as_micros();
    let subst_us = AMBIENT_SUBST_US.with(|c| c.get());
    let jcs_us = AMBIENT_JCS_US.with(|c| c.get());
    // Log only non-trivial calls (>=2ms) so the slow obligations stand out in the
    // trace instead of drowning under microsecond ones. Each line is timestamped
    // by the tracing subscriber; `property` ties it to the obligation.
    if total_us >= 2000 {
        info!(
            property = property_name,
            ambient = ambient.len(),
            ground_terms = ground_terms_total,
            callsite_pairs,
            instances = instances.len(),
            subst_us,
            jcs_us,
            total_us,
            "verifier/timing: ambient instantiation hotspot"
        );
    }
    instances
}

fn collect_property_name_ground_terms(property_name: &str, sort: &Json, out: &mut Vec<Json>) {
    if !sort_is_primitive(sort, "Int") {
        return;
    }
    let mut offset = 0;
    while let Some(rel) = property_name[offset..].find("i:") {
        let start = offset + rel + 2;
        let mut end = start;
        let bytes = property_name.as_bytes();
        if end < bytes.len() && bytes[end] == b'-' {
            end += 1;
        }
        while end < bytes.len() && bytes[end].is_ascii_digit() {
            end += 1;
        }
        if end > start && property_name[start..end].parse::<i64>().is_ok() {
            let value = property_name[start..end].parse::<i64>().unwrap();
            out.push(serde_json::json!({
                "kind": "const",
                "value": value,
                "sort": {"kind": "primitive", "name": "Int"}
            }));
        }
        offset = end.max(start);
    }
}

fn sort_is_primitive(sort: &Json, name: &str) -> bool {
    sort.get("kind").and_then(|v| v.as_str()) == Some("primitive")
        && sort.get("name").and_then(|v| v.as_str()) == Some(name)
}

// Discharge profiling (timestamped): per-`instantiate_ambient_foralls_for_inv`
// accumulators, split so we can see whether instantiation cost is substitution
// vs JCS canonicalization. Reset + read by that function; logged per obligation.
thread_local! {
    static AMBIENT_SUBST_US: std::cell::Cell<u128> = const { std::cell::Cell::new(0) };
    static AMBIENT_JCS_US: std::cell::Cell<u128> = const { std::cell::Cell::new(0) };
}

fn push_ambient_instance(
    body: &Json,
    var_name: &str,
    replacement: &Json,
    instances: &mut Vec<Json>,
    seen: &mut std::collections::BTreeSet<String>,
) {
    let t_subst = std::time::Instant::now();
    let instance = crate::instantiate::substitute_formula_pub(body, var_name, replacement);
    AMBIENT_SUBST_US.with(|c| c.set(c.get() + t_subst.elapsed().as_micros()));
    if !formula_is_closed(&instance, &mut Vec::new()) {
        return;
    }
    let t_jcs = std::time::Instant::now();
    let key = libsugar::canonical::json_jcs(&instance)
        .unwrap_or_else(|_| serde_json::to_string(&instance).unwrap_or_default());
    AMBIENT_JCS_US.with(|c| c.set(c.get() + t_jcs.elapsed().as_micros()));
    if seen.insert(key) {
        instances.push(instance);
    }
}

fn collect_unquantified_ground_terms(node: &Json, sort: &Json, out: &mut Vec<Json>) {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => return,
        Some("const") if term_matches_sort(node, sort) => out.push(node.clone()),
        _ => {}
    }
    for key in ["operands", "args"] {
        if let Some(arr) = node.get(key).and_then(|v| v.as_array()) {
            for child in arr {
                collect_unquantified_ground_terms(child, sort, out);
            }
        }
    }
    if let Some(body) = node.get("body") {
        collect_unquantified_ground_terms(body, sort, out);
    }
}

fn term_matches_sort(term: &Json, sort: &Json) -> bool {
    term.get("sort").is_some_and(|term_sort| term_sort == sort)
}

fn collect_unquantified_ctor_terms(node: &Json, out: &mut Vec<Json>) {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => return,
        Some("ctor") => out.push(node.clone()),
        _ => {}
    }
    for key in ["operands", "args"] {
        if let Some(arr) = node.get(key).and_then(|v| v.as_array()) {
            for child in arr {
                collect_unquantified_ctor_terms(child, out);
            }
        }
    }
    if let Some(body) = node.get("body") {
        collect_unquantified_ctor_terms(body, out);
    }
}

fn collect_forall_call_patterns(node: &Json, var_name: &str, out: &mut Vec<Json>) {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => return,
        Some("ctor") if ctor_has_direct_bound_arg(node, var_name) => out.push(node.clone()),
        _ => {}
    }
    for key in ["operands", "args"] {
        if let Some(arr) = node.get(key).and_then(|v| v.as_array()) {
            for child in arr {
                collect_forall_call_patterns(child, var_name, out);
            }
        }
    }
    if let Some(body) = node.get("body") {
        collect_forall_call_patterns(body, var_name, out);
    }
}

fn ctor_has_direct_bound_arg(node: &Json, var_name: &str) -> bool {
    node.get("args")
        .and_then(|v| v.as_array())
        .is_some_and(|args| args.iter().any(|arg| is_var_named(arg, var_name)))
}

fn match_forall_call_pattern(pattern: &Json, callsite: &Json, var_name: &str) -> Option<Json> {
    if pattern.get("kind").and_then(|v| v.as_str()) != Some("ctor")
        || callsite.get("kind").and_then(|v| v.as_str()) != Some("ctor")
        || pattern.get("name").and_then(|v| v.as_str())
            != callsite.get("name").and_then(|v| v.as_str())
    {
        return None;
    }
    let pattern_args = pattern.get("args").and_then(|v| v.as_array())?;
    let callsite_args = callsite.get("args").and_then(|v| v.as_array())?;
    if pattern_args.len() != callsite_args.len() {
        return None;
    }

    let mut replacement: Option<Json> = None;
    for (pattern_arg, callsite_arg) in pattern_args.iter().zip(callsite_args.iter()) {
        if is_var_named(pattern_arg, var_name) {
            if replacement
                .as_ref()
                .is_some_and(|seen| seen != callsite_arg)
            {
                return None;
            }
            replacement = Some(callsite_arg.clone());
        } else if term_contains_var(pattern_arg, var_name) || pattern_arg != callsite_arg {
            return None;
        }
    }
    replacement
}

fn is_var_named(node: &Json, var_name: &str) -> bool {
    node.get("kind").and_then(|v| v.as_str()) == Some("var")
        && node.get("name").and_then(|v| v.as_str()) == Some(var_name)
}

fn term_contains_var(node: &Json, var_name: &str) -> bool {
    if is_var_named(node, var_name) {
        return true;
    }
    for key in ["operands", "args"] {
        if let Some(arr) = node.get(key).and_then(|v| v.as_array()) {
            if arr.iter().any(|child| term_contains_var(child, var_name)) {
                return true;
            }
        }
    }
    node.get("body")
        .is_some_and(|body| term_contains_var(body, var_name))
}

/// Conjoin closed instances of ambient universal invariants into an obligation's
/// inv. The raw forall templates are not copied into every obligation; only
/// concrete, closed instances travel across contracts.
fn with_ambient_foralls(inv: Json, property_name: &str, ambient: &[Json]) -> Json {
    if ambient.is_empty() {
        return inv;
    }
    // Callsite-keyed (`#euf#`) obligations: the closed universals travel as
    // `forall` QUANTIFIERS (`closed_templates`); the compilers lower them to the
    // backend's native quantifier (z3 `(forall)`, coq `forall`, lean `∀`) and the
    // solver instantiates via MBQI/e-matching. We deliberately do NOT also
    // materialize ground instances: profiling showed that path is combinatorial
    // (up to 57K ground terms x 600K callsite-pair attempts -> 142s for ONE
    // obligation, dominated by json_jcs dedup) to emit ~825 instances the
    // quantifier already covers -- and covers MORE completely (all instantiations,
    // not a finite materialized subset). Complete soundness, in milliseconds.
    //
    // Bare-name-keyed obligations must NOT copy in the raw forall (two unrelated
    // tests can share a spelling -> cross-test name capture; see
    // `collect_ambient_foralls`), so there -- and only there -- we still travel
    // concrete CLOSED ground instances, which carry no free names.
    let callsite_keyed = property_name.contains("#euf#");
    let closed_templates: Vec<Json> = if callsite_keyed {
        ambient
            .iter()
            .filter(|forall| formula_is_closed(forall, &mut Vec::new()))
            .cloned()
            .collect()
    } else {
        Vec::new()
    };
    let instances: Vec<Json> = if callsite_keyed {
        Vec::new()
    } else {
        instantiate_ambient_foralls_for_inv(&inv, property_name, ambient)
    };
    debug!(
        property = property_name,
        ambient = ambient.len(),
        closed_templates = closed_templates.len(),
        instances = instances.len(),
        "verifier/ambient: conjoining universals into obligation"
    );
    if instances.is_empty() && closed_templates.is_empty() {
        return inv;
    }
    let mut operands = Vec::with_capacity(closed_templates.len() + instances.len() + 1);
    operands.push(inv);
    operands.extend(closed_templates);
    operands.extend(instances);
    serde_json::json!({ "kind": "and", "operands": operands })
}

#[derive(Debug, Clone)]
struct AmbientPost {
    source_symbol: String,
    target_cid: String,
    target_proof_cid: Option<String>,
    formals: Vec<String>,
    out_binding: String,
    post: Json,
}

#[derive(Debug, Clone)]
struct LinkedPostInstance {
    source_symbol: String,
    target_cid: String,
    target_proof_cid: Option<String>,
    formals: Vec<String>,
    out_binding: String,
    call: Json,
    vendor_post: Json,
    instantiated_post: Json,
}

fn collect_ambient_posts(pool: &MementoPool) -> Vec<AmbientPost> {
    let mut posts = Vec::new();
    for (indexed_symbol, bridge_env) in &pool.bridges_by_symbol {
        let source_symbol = memento_body_field(bridge_env, "sourceSymbol")
            .and_then(|v| v.as_str())
            .unwrap_or(indexed_symbol)
            .to_string();
        if source_symbol.is_empty() {
            continue;
        }
        let Some(target_cid) =
            memento_body_field(bridge_env, "targetContractCid").and_then(|v| v.as_str())
        else {
            continue;
        };
        let Some(contract_env) = pool.mementos.get(target_cid) else {
            continue;
        };
        if memento_kind(contract_env) != Some("contract") {
            continue;
        }
        let Some(body) = memento_body(contract_env) else {
            continue;
        };
        let Some(post) = body
            .get("post")
            .or_else(|| body.get("postcondition"))
            .filter(|v| v.is_object())
            .cloned()
        else {
            continue;
        };
        let Some(formals_arr) = body.get("formals").and_then(|v| v.as_array()) else {
            continue;
        };
        let Some(formals) = formals_arr
            .iter()
            .map(|v| v.as_str().map(str::to_string))
            .collect::<Option<Vec<_>>>()
        else {
            continue;
        };
        let out_binding = body
            .get("outBinding")
            .or_else(|| body.get("out_binding"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("out")
            .to_string();
        let target_proof_cid = memento_body_field(bridge_env, "targetProofCid")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| {
                pool.bridge_self_bundle_by_symbol
                    .get(&source_symbol)
                    .cloned()
            });
        posts.push(AmbientPost {
            source_symbol,
            target_cid: target_cid.to_string(),
            target_proof_cid,
            formals,
            out_binding,
            post,
        });
    }
    posts
}

pub(crate) fn linked_post_instance_count(pool: &MementoPool, body: &Json) -> usize {
    if !is_consistency_candidate(body) {
        return 0;
    }
    let inv = canonicalize_formula_json(&axiom_context_formula(body));
    let ambient_posts = collect_ambient_posts(pool);
    instantiate_ambient_posts_for_inv(&inv, &ambient_posts).len()
}

fn instantiate_ambient_posts_for_inv(inv: &Json, ambient: &[AmbientPost]) -> Vec<Json> {
    linked_ambient_post_instances_for_inv(inv, ambient)
        .into_iter()
        .map(|p| p.instantiated_post)
        .collect()
}

fn linked_ambient_post_instances_for_inv(
    inv: &Json,
    ambient: &[AmbientPost],
) -> Vec<LinkedPostInstance> {
    if ambient.is_empty() {
        return Vec::new();
    }
    let mut callsites = Vec::new();
    collect_unquantified_ctor_terms(inv, &mut callsites);
    if callsites.is_empty() {
        return Vec::new();
    }

    let mut instances = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for callsite in &callsites {
        let Some(name) = callsite.get("name").and_then(|v| v.as_str()) else {
            continue;
        };
        let Some(args) = callsite.get("args").and_then(|v| v.as_array()) else {
            continue;
        };
        for post in ambient
            .iter()
            .filter(|post| post.source_symbol == name && post.formals.len() == args.len())
        {
            let mut instance = post.post.clone();
            for (formal, actual) in post.formals.iter().zip(args.iter()) {
                instance = crate::instantiate::substitute_formula_pub(&instance, formal, actual);
            }
            instance =
                crate::instantiate::substitute_formula_pub(&instance, &post.out_binding, callsite);
            if !formula_is_closed(&instance, &mut Vec::new()) {
                debug!(
                    source_symbol = %post.source_symbol,
                    target_cid = %post.target_cid,
                    "verifier/linker: skipped open specialized post"
                );
                continue;
            }
            let key = libsugar::canonical::json_jcs(&instance)
                .unwrap_or_else(|_| serde_json::to_string(&instance).unwrap_or_default());
            if seen.insert(key) {
                instances.push(LinkedPostInstance {
                    source_symbol: post.source_symbol.clone(),
                    target_cid: post.target_cid.clone(),
                    target_proof_cid: post.target_proof_cid.clone(),
                    formals: post.formals.clone(),
                    out_binding: post.out_binding.clone(),
                    call: callsite.clone(),
                    vendor_post: post.post.clone(),
                    instantiated_post: canonicalize_formula_json(&instance),
                });
            }
        }
    }
    instances
}

fn with_ambient_posts_with_instances(
    inv: Json,
    ambient: &[AmbientPost],
) -> (Json, Vec<LinkedPostInstance>) {
    if ambient.is_empty() {
        return (inv, Vec::new());
    }
    let instances = linked_ambient_post_instances_for_inv(&inv, ambient);
    debug!(
        ambient_posts = ambient.len(),
        instances = instances.len(),
        "verifier/linker: conjoining specialized contract posts into obligation"
    );
    if instances.is_empty() {
        return (inv, Vec::new());
    }
    let mut operands = Vec::with_capacity(instances.len() + 1);
    operands.push(inv);
    operands.extend(instances.iter().map(|p| p.instantiated_post.clone()));
    (
        serde_json::json!({ "kind": "and", "operands": operands }),
        instances,
    )
}

fn with_local_forall_instances(inv: Json, property_name: &str) -> Json {
    let mut foralls = Vec::new();
    collect_ambient_foralls(&inv, &mut foralls);
    if foralls.is_empty() {
        return inv;
    }
    let instances = instantiate_ambient_foralls_for_inv(&inv, property_name, &foralls);
    if instances.is_empty() {
        return inv;
    }
    let mut operands = Vec::with_capacity(instances.len() + 1);
    operands.push(inv);
    operands.extend(instances);
    serde_json::json!({ "kind": "and", "operands": operands })
}

pub fn verify_consistency(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<String, SolverHandle>,
    compilers: &CompilerRegistry,
) -> Vec<ConsistencyResult> {
    let candidates: Vec<(&String, &Json)> = pool
        .mementos
        .iter()
        .filter(|(_, env)| memento_kind(env) == Some("contract"))
        .filter_map(|(cid, env)| memento_body(env).map(|b| (cid, b)))
        .filter(|(_, body)| is_consistency_candidate(body))
        .collect();

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
            let inv = canonicalize_formula_json(inv);
            let before = ambient_foralls.len();
            collect_ambient_foralls(&inv, &mut ambient_foralls);
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
    let ambient_posts = collect_ambient_posts(pool);
    info!(
        candidates = candidates.len(),
        ambient_posts = ambient_posts.len(),
        "verifier/linker: contract posts will be specialized into matching obligations"
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

    let results: Vec<ConsistencyResult> = groups
        .par_iter()
        .flat_map(|(property_name, members)| {
            let mut out: Vec<ConsistencyResult> = Vec::new();

            // WITNESS members are settled from the rust-recomputed package body,
            // PER MEMBER. They are NEVER folded into the symbolic conjunction
            // AND never short-circuit the group: a witness member must not mask
            // a contradictory inv group.
            let mut inv_cids: Vec<&String> = Vec::new();
            let mut inv_bodies: Vec<&Json> = Vec::new();
            for (m_cid, body) in members {
                if is_witness_member(body) {
                    if let Some(res) =
                        try_witness_discharge(body, (*m_cid).clone(), property_name.clone())
                    {
                        out.push(res);
                        continue;
                    }
                }
                inv_bodies.push(body);
                inv_cids.push(m_cid);
            }
            if inv_bodies.is_empty() {
                return out;
            }

            // CROSS-PROOF CONJOIN only for CALLSITE-KEYED names (`#euf#`). That key
            // is `(callee, args)`, so same name == same call == sound to conjoin a
            // consumer's assertion with an imported vendor contract -> `and(==5,==6)`
            // -> unsat -> refused. A bare test/location name does NOT guarantee the
            // same subject, so those stay PER-CONTRACT (conjoining them could falsely
            // refuse two unrelated tests that happen to share a function name).
            let callsite_keyed = property_name.contains("#euf#");
            if callsite_keyed && inv_bodies.len() > 1 {
                let invs: Vec<Json> = inv_bodies
                    .iter()
                    .map(|b| canonicalize_formula_json(&axiom_context_formula(b)))
                    .collect();
                let inv = serde_json::json!({ "kind": "and", "operands": invs });
                let (inv, linked_posts) = with_ambient_posts_with_instances(inv, &ambient_posts);
                out.push(check_inv_consistency(
                    inv_cids[0].clone(),
                    property_name,
                    with_ambient_foralls(inv, property_name, &ambient_foralls),
                    linked_posts,
                    plan,
                    registry,
                    compilers,
                ));
            } else {
                for (cid, body) in inv_cids.iter().zip(inv_bodies.iter()) {
                    let inv = canonicalize_formula_json(&axiom_context_formula(body));
                    let (inv, linked_posts) =
                        with_ambient_posts_with_instances(inv, &ambient_posts);
                    out.push(check_inv_consistency(
                        (*cid).clone(),
                        property_name,
                        with_ambient_foralls(inv, property_name, &ambient_foralls),
                        linked_posts,
                        plan,
                        registry,
                        compilers,
                    ));
                }
            }
            out
        })
        .collect();

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
    use crate::solvers::{registry, StubSolver};
    use serde_json::json;
    use std::sync::{Arc, Mutex, OnceLock};

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

    fn test_compilers() -> CompilerRegistry {
        let mut compilers = CompilerRegistry::new();
        compilers.register(Arc::new(sugar_ir_compiler_smt_lib::SmtLibCompiler::new()));
        compilers
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
    fn implies(a: Json, b: Json) -> Json {
        json!({"kind":"implies","operands":[a,b]})
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

    #[test]
    fn witness_resolvers_can_be_supplied_by_env_registry() {
        let _env = witness_env_lock();
        let cwd = std::env::current_dir().unwrap();
        let encoded = json!([{
            "argv": ["/bin/echo"],
            "working_dir": cwd.display().to_string(),
            "method": "sugar.plugin.resolve_witness",
        }])
        .to_string();
        std::env::set_var("SUGAR_WITNESS_RESOLVERS", encoded);

        let resolvers = witness_resolvers_from_env();
        assert_eq!(resolvers.len(), 1);
        assert_eq!(resolvers[0].argv, vec!["/bin/echo".to_string()]);
        assert_eq!(resolvers[0].working_dir, cwd);
        assert_eq!(resolvers[0].method, "sugar.plugin.resolve_witness");

        std::env::remove_var("SUGAR_WITNESS_RESOLVERS");
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "consistent conjunction must stay proven (no false refusal): {res:?}"
        );

        // a LONE contract is untouched -> PROVEN
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:solo", name, eqf(var("r"), int(5)));
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
        assert_eq!(res.len(), 1);
        assert_eq!(res[0].verdict, ObligationVerdict::Discharged);
    }

    /// CONGRUENCE TEETH on a PURE nullary callsite (the cardinal-sin guard).
    ///
    /// This is the exact FOL shape the rust/tokio/polars consistency showcases
    /// lift for their `bad` fixtures: a PURE deterministic call `make_value()`
    /// (no args, no effect) asserted equal to two distinct integer literals in
    /// the SAME conjoined contract. By EUF congruence both `call:make_value()`
    /// occurrences are the SAME ground term, so `f()==6 ∧ f()==7` is UNSAT and
    /// the consistency row MUST refuse. A regression here would fake-discharge a
    /// contradiction -- the cardinal sin. (Root-caused 2026-06-15: the verifier
    /// teeth were INTACT; the regression was a showcase harness row-selection
    /// bug after PR #2138 began emitting a separate `rust-source::<fn>` row.)
    ///
    /// POSITIVE: the pure contradiction refuses.
    #[test]
    fn pure_nullary_callsite_literal_contradiction_refuses() {
        let (plan, reg) = z3_plan_and_registry();
        let call = json!({"kind":"ctor","name":"call:make_value","args":[]});
        let inv = json!({"kind":"and","operands":[
            eqf(call.clone(), int(6)),
            eqf(call.clone(), int(7)),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:pure-contradiction",
            "make_value#euf#c:callresult_make_value_a0()::assertion",
            inv,
        );
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
        assert_eq!(res.len(), 1, "one conjoined obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "PURE f()==6 ∧ f()==7 is UNSAT by congruence -> MUST refuse (cardinal-sin guard): {res:?}"
        );
    }

    /// DISCRIMINATION: a `.await` over a pure callsite is lifted as a STRUCTURAL
    /// deterministic term (`await(call:async_value())`). The tokio showcase
    /// header documents this: `.await` is a structural await term inside the
    /// consistency obligation, so two awaited reads of the SAME callsite are the
    /// SAME ground term and contradictory literals about it still refuse. (The
    /// intended fork model vindicates a contradiction ONLY when the impurity is
    /// modeled by DISTINCT terms at distinct program points -- see the next
    /// test. A structurally-identical await term carries the teeth.)
    #[test]
    fn structural_await_callsite_literal_contradiction_refuses() {
        let (plan, reg) = z3_plan_and_registry();
        let awaited = json!({"kind":"ctor","name":"await","args":[
            {"kind":"ctor","name":"call:async_value","args":[]}
        ]});
        let inv = json!({"kind":"and","operands":[
            eqf(awaited.clone(), int(6)),
            eqf(awaited.clone(), int(7)),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:await-contradiction",
            "tokio_await_scalar_contradiction",
            inv,
        );
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
        assert_eq!(res.len(), 1, "one conjoined obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "await(f())==6 ∧ await(f())==7 over the SAME structural await term refuses: {res:?}"
        );
    }

    /// DISCRIMINATION (the fork boundary -- no false refusal): two DISTINCT
    /// uninterpreted callsites with NO shared term and NO literal congruence
    /// (`f()==6 ∧ g()==7`) are always-SAT -- there is no UNSAT to invert -- so
    /// the consistency row DISCHARGES. This is the "impure read at distinct
    /// program points = distinct terms = consistent" leg of the fork model: the
    /// teeth fire ONLY when the two facts share the same ground term. Guards
    /// against an over-eager refusal that would convict a legitimate trajectory.
    #[test]
    fn distinct_callsites_no_shared_term_discharges() {
        let (plan, reg) = z3_plan_and_registry();
        let f = json!({"kind":"ctor","name":"call:f","args":[]});
        let g = json!({"kind":"ctor","name":"call:g","args":[]});
        let inv = json!({"kind":"and","operands":[
            eqf(f, int(6)),
            eqf(g, int(7)),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:distinct-callsites",
            "two_distinct_calls#euf#c:callresult_x::assertion",
            inv,
        );
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
        assert_eq!(res.len(), 1, "one obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "distinct callsites f()==6 ∧ g()==7 share no term -> SAT -> discharge (no false refusal): {res:?}"
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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

    #[test]
    fn vendor_function_post_is_linked_into_fresh_consumer_assertions() {
        let (plan, reg) = z3_plan_and_registry();
        let vendor_cid = "blake3-512:vendor-enc-contract";
        let source_symbol = "call:enc";
        let call_enc = |arg: Json| json!({"kind":"ctor","name":source_symbol,"args":[arg]});
        let post = implies(
            eqf(var("input"), string_const("def")),
            eqf(var("out"), string_const("ghi")),
        );

        let mut pool = MementoPool::default();
        pool.mementos.insert(
            vendor_cid.to_string(),
            json!({
                "evidence": {
                    "kind": "contract",
                    "body": {
                        "contractName": "rust-source::enc",
                        "formals": ["input"],
                        "outBinding": "out",
                        "post": post
                    }
                }
            }),
        );
        let bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": source_symbol,
                    "targetContractCid": vendor_cid,
                    "targetProofCid": "blake3-512:vendor-proof"
                }
            }
        });
        pool.bridges_by_symbol
            .insert(source_symbol.to_string(), bridge);

        insert_contract(
            &mut pool,
            "blake3-512:good-consumer-assertion",
            "src/lib.rs::tests::fresh_vendor_fol_good::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion",
            eqf(call_enc(string_const("def")), string_const("ghi")),
        );
        insert_contract(
            &mut pool,
            "blake3-512:bad-consumer-assertion",
            "src/lib.rs::tests::fresh_vendor_fol_bad::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion",
            eqf(call_enc(string_const("def")), string_const("zzz")),
        );

        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
        assert_eq!(res.len(), 2, "two fresh consumer assertions: {res:?}");
        let good = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:good-consumer-assertion")
            .expect("good consumer assertion row present");
        assert_eq!(
            good.verdict,
            ObligationVerdict::Discharged,
            "vendor post enc(\"def\") = \"ghi\" must agree with the fresh good assertion: {res:?}"
        );
        let good_verification = good
            .verification
            .as_ref()
            .expect("good row carries verification detail");
        assert_eq!(good_verification["kind"], "consistency");
        assert_eq!(
            good_verification["linkedPosts"][0]["sourceSymbol"],
            source_symbol
        );
        assert_eq!(
            good_verification["linkedPosts"][0]["targetContractCid"],
            vendor_cid
        );
        assert_eq!(
            good_verification["linkedPosts"][0]["targetProofCid"],
            "blake3-512:vendor-proof"
        );
        assert_eq!(
            good_verification["solverInvocations"][0]["compiler"],
            "smt-lib-v2.6"
        );
        assert_eq!(good_verification["rawSolverVerdict"], "unsatisfied");
        assert_eq!(good_verification["finalVerdict"], "discharged");
        let bad = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:bad-consumer-assertion")
            .expect("bad consumer assertion row present");
        assert_eq!(
            bad.verdict,
            ObligationVerdict::Unsatisfied,
            "vendor post enc(\"def\") = \"ghi\" must refute the fresh bad assertion: {res:?}"
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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

    // --- forall-rewrite regression: callsite-keyed obligations travel the
    // universal AS A QUANTIFIER, never a materialized ground flood ---
    // Profiling showed the old ground materialization was combinatorial (up to
    // 57K ground terms x 600K callsite pairs -> 142s for ONE #euf# obligation,
    // dominated by json_jcs) to emit instances the conjoined `forall` already
    // covers. These tests pin the mechanism: #euf# -> quantifier (no instances),
    // bare-name -> closed instances (raw forall would capture across tests). The
    // end-to-end SOUNDNESS (z3 e-matches the quantifier to refute) is pinned by
    // `ambient_forall_refutes_separate_point_claim_memento` above.

    #[test]
    fn euf_obligation_travels_forall_quantifier_not_materialized_instances() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        // ambient universal over a callsite: forall x. g(x) == 1
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": eqf(callg(var("x")), int(1)),
        });
        // a #euf# obligation that MENTIONS the callsite g(2); the OLD code would
        // Path-B-match this and materialize the ground instance g(2)==1.
        let inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});
        let out = with_ambient_foralls(inv, "g#euf#c:callresult_g_a1(i:2)::assertion", &[forall]);
        let operands = out
            .get("operands")
            .and_then(|v| v.as_array())
            .expect("conjoined `and` node");
        // The universal travels AS A QUANTIFIER.
        assert!(
            operands
                .iter()
                .any(|op| op.get("kind").and_then(|k| k.as_str()) == Some("forall")),
            "ambient universal must be conjoined as a forall quantifier: {out}"
        );
        // ...and is NOT materialized. (RED on the pre-rewrite code, which emitted
        // exactly this ground instance for #euf# obligations too.)
        let materialized = eqf(callg(int(2)), int(1));
        assert!(
            !operands.iter().any(|op| *op == materialized),
            "rewrite must NOT materialize ground instances for #euf# obligations: {out}"
        );
    }

    #[test]
    fn bare_name_obligation_still_materializes_closed_instance_not_raw_forall() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": eqf(callg(var("x")), int(1)),
        });
        let inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});
        // BARE name (no #euf#): two unrelated tests can share this spelling, so the
        // raw forall must NOT be copied in (name capture). The closed ground
        // instance g(2)==1 -- which carries no free names -- travels instead.
        let out = with_ambient_foralls(inv, "src/lib.rs::tests::some_bare_test", &[forall]);
        let operands = out
            .get("operands")
            .and_then(|v| v.as_array())
            .expect("conjoined `and` node");
        assert!(
            operands.iter().any(|op| *op == eqf(callg(int(2)), int(1))),
            "bare-name obligation must travel the closed ground instance: {out}"
        );
        assert!(
            !operands
                .iter()
                .any(|op| op.get("kind").and_then(|k| k.as_str()) == Some("forall")),
            "bare-name obligation must NOT copy in the raw forall (capture safety): {out}"
        );
    }

    #[test]
    fn ambient_forall_is_specialized_at_concrete_callsite() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("x")]}),
            json!({"kind":"atomic","name":"<","args":[var("x"), int(3)]}),
        ]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[
                guard,
                eqf(callg(var("x")), int(1))
            ]}),
        });
        let point_inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});

        let instances = instantiate_ambient_foralls_for_inv(
            &point_inv,
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            &[forall],
        );

        assert_eq!(instances.len(), 1, "one call:g(2) instance: {instances:?}");
        assert_eq!(
            instances[0],
            json!({"kind":"implies","operands":[
                {"kind":"and","operands":[
                    {"kind":"atomic","name":"\u{2264}","args":[int(0), int(2)]},
                    {"kind":"atomic","name":"<","args":[int(2), int(3)]}
                ]},
                eqf(callg(int(2)), int(1))
            ]})
        );
    }

    #[test]
    fn ambient_forall_is_specialized_from_ground_constant() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let callh = |arg: Json| json!({"kind":"ctor","name":"call:h","args":[arg]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": eqf(callg(var("x")), int(1)),
        });
        let point_inv = json!({"kind":"and","operands":[eqf(callh(int(2)), int(2))]});

        let instances = instantiate_ambient_foralls_for_inv(
            &point_inv,
            "h#euf#c:callresult_h_a1(i:2)::assertion",
            &[forall],
        );

        assert_eq!(instances, vec![eqf(callg(int(2)), int(1))]);
    }

    #[test]
    fn ambient_forall_is_specialized_from_callsite_name_constant() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": eqf(callg(var("x")), int(1)),
        });
        let point_inv = json!({"kind":"and","operands":[]});

        let instances = instantiate_ambient_foralls_for_inv(
            &point_inv,
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            &[forall],
        );

        assert_eq!(instances, vec![eqf(callg(int(2)), int(1))]);
    }

    #[test]
    fn ambient_forall_ground_contradiction_short_circuits_solver() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("x")]}),
            json!({"kind":"atomic","name":"<","args":[var("x"), int(3)]}),
        ]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[
                guard,
                eqf(callg(var("x")), int(1))
            ]}),
        });
        let loop_inv = json!({"kind":"and","operands":[forall]});
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

        let plan = SolverPlan::Single("z3".into());
        let mut registry = HashMap::new();
        registry.insert(
            "z3".into(),
            Arc::new(StubSolver::new("z3", ObligationVerdict::Unsatisfied)) as SolverHandle,
        );
        let res = verify_consistency(&pool, &plan, &registry, &test_compilers());
        let point = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:point")
            .expect("point row present");

        assert_eq!(
            point.verdict,
            ObligationVerdict::Unsatisfied,
            "ground contradiction must refute before the stub solver can discharge: {res:?}"
        );
        assert!(
            point.reason.contains("structural:"),
            "reason must prove the pre-SMT path fired: {}",
            point.reason
        );
    }

    #[test]
    fn closed_forall_conjoined_with_point_claim_specializes_before_solver() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("$b0")]}),
            json!({"kind":"atomic","name":"<","args":[var("$b0"), int(3)]}),
        ]});
        let forall = json!({
            "kind":"forall","name":"$b0",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[
                guard,
                eqf(callg(var("$b0")), int(1))
            ]}),
        });
        let inv = json!({"kind":"and","operands":[
            eqf(callg(int(2)), int(2)),
            forall
        ]});

        let plan = SolverPlan::Single("z3".into());
        let mut registry = HashMap::new();
        registry.insert(
            "z3".into(),
            Arc::new(StubSolver::new("z3", ObligationVerdict::Unsatisfied)) as SolverHandle,
        );
        let res = check_inv_consistency(
            "blake3-512:point".into(),
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            inv,
            Vec::new(),
            &plan,
            &registry,
            &test_compilers(),
        );

        assert_eq!(res.verdict, ObligationVerdict::Unsatisfied, "{res:?}");
        assert!(
            res.reason.contains("structural:"),
            "closed forall instance must be reduced before the solver: {}",
            res.reason
        );
    }

    #[test]
    fn ambient_forall_is_collected_through_nested_conjunction() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": eqf(callg(var("x")), int(1)),
        });
        let nested_loop_inv = json!({"kind":"and","operands":[
            {"kind":"and","operands":[forall]}
        ]});
        let point_inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:loop",
            "src/lib.rs::tests::t::loop::x",
            nested_loop_inv,
        );
        insert_contract(
            &mut pool,
            "blake3-512:point",
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            point_inv,
        );
        let reg = HashMap::new();
        let res = verify_consistency(
            &pool,
            &SolverPlan::Single("unused".into()),
            &reg,
            &test_compilers(),
        );
        let point = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:point")
            .expect("point-claim row present");
        assert_eq!(point.verdict, ObligationVerdict::Unsatisfied, "{res:?}");
    }

    #[test]
    fn ambient_forall_canonicalizes_mixed_alpha_binder_before_travel() {
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let guard = json!({"kind":"and","operands":[
            json!({"kind":"atomic","name":"\u{2264}","args":[int(0), var("$b0")]}),
            json!({"kind":"atomic","name":"<","args":[var("$b0"), int(3)]}),
        ]});
        let mixed_alpha_forall = json!({
            "kind":"forall","name":"x",
            "sort":{"kind":"primitive","name":"Int"},
            "body": json!({"kind":"implies","operands":[
                guard,
                eqf(callg(var("$b0")), int(1))
            ]}),
        });
        let loop_inv = json!({"kind":"and","operands":[mixed_alpha_forall]});
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
        let reg = HashMap::new();
        let res = verify_consistency(
            &pool,
            &SolverPlan::Single("unused".into()),
            &reg,
            &test_compilers(),
        );
        let point = res
            .iter()
            .find(|r| r.contract_cid == "blake3-512:point")
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Unsatisfied,
            "ambient collection must use the same alpha-normal form as mint: {res:?}"
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let res = verify_consistency(&pool, &plan, &reg, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
        assert!(
            results.is_empty(),
            "pre-bearing contract must not be a consistency candidate"
        );
    }

    #[test]
    fn inv_is_conjoined_with_post_universe_as_axiom_context() {
        // `inv` is the asserted fact; `post` is the lifted universe relation.
        // The consistency/conjoiner pass must check their conjunction so a
        // proof cannot carry an assertion fact that contradicts its own
        // universe contract.
        let mut pool = MementoPool::default();
        let env = json!({
            "envelope": {
                "header": {
                    "kind": "contract",
                    "contractName": "rust-source::contradictory_universe",
                    "inv": eqf(var("out"), int(5)),
                    "post": eqf(var("out"), int(6)),
                }
            }
        });
        pool.insert("blake3-512:inv-post".into(), env);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());

        assert_eq!(
            results.len(),
            1,
            "inv/post contract must be checked: {results:?}"
        );
        assert_eq!(results[0].verdict, ObligationVerdict::Unsatisfied);
        assert!(
            results[0].reason.contains("contradictory"),
            "inv/post contradiction must be surfaced: {results:?}"
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers());
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].verdict, ObligationVerdict::Unsatisfied);
    }
}
