// SPDX-License-Identifier: MIT OR Apache-2.0
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
//   timeout        (host/budget exhaustion)     -> SolverTimeout, reported LOUD
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

use crate::effects::{VerifyEffect, WitnessDischargeGround};
use crate::solvers::{
    run_plan_with_compilers, SolverHandle, SolverInvocation, SolverPlan, SolverSeat,
};
use crate::types::{MementoCid, MementoPool, ObligationVerdict, SourceLocus, StoredMember};
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_ir_compiler::CompilerInput;

/// Outcome of a single contract's consistency check.
#[derive(Debug, Clone)]
pub struct ConsistencyResult {
    pub contract_cid: String,
    pub property_name: String,
    /// `Discharged` => PROVEN-consistent; `Unsatisfied` => REFUSED-contradictory;
    /// `Undecidable` => encoding STOP (must be surfaced, never silently passed).
    pub verdict: ObligationVerdict,
    pub reason: String,
    pub effect: Option<VerifyEffect>,
    /// True when the verdict came from an EXECUTION WITNESS discharged by
    /// recompute (k(I)=t), NOT from a symbolic solver. Kept distinct so the
    /// report never reads witnessed-by-execution as proven-by-solver.
    pub witnessed: bool,
    pub verification: Option<Json>,
    /// The source locus (file/line/column) of the assertion this result is
    /// about, recovered from the contract memento's own `file`+`span`. Stamped
    /// by `verify_consistency` and threaded to the report row so an
    /// `unsatisfied` verdict can anchor an IDE diagnostic at the exact
    /// assertion instead of dropping the source. `None` when the contract
    /// memento carries no readable locus (fail-open: no false anchor).
    pub locus: Option<SourceLocus>,
}

/// Recover the assertion's source locus from a contract memento body. The
/// python literal-call lifter emits a top-level `file` plus a `span` object
/// (`start_line`/`start_col`); we read those directly rather than re-deriving
/// anything. Returns `None` if no usable `file`+line is present.
fn locus_from_body(body: &Json) -> Option<SourceLocus> {
    let file = body.get("file").and_then(|v| v.as_str())?.to_string();
    if file.is_empty() {
        return None;
    }
    let span = body.get("span");
    let line = span
        .and_then(|s| s.get("start_line"))
        .or_else(|| body.get("line"))
        .and_then(|v| v.as_u64())? as usize;
    let column = span
        .and_then(|s| s.get("start_col"))
        .and_then(|v| v.as_u64())
        .map(|c| c as usize);
    Some(SourceLocus { file, line, column })
}

const CONSISTENT_REASON: &str = "test assertions mutually consistent about callsite";
const CONTRADICTORY_REASON: &str = "test assertions contradictory about callsite";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum VacuityRefusalKind {
    NoSiblingToContradict,
    MissingIndependentKindWitness,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum ProofIrProvenanceKind {
    Stated,
    Derived,
}

impl ProofIrProvenanceKind {
    fn label(self) -> &'static str {
        match self {
            ProofIrProvenanceKind::Stated => "Stated",
            ProofIrProvenanceKind::Derived => "Derived",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct AmbientFactWitnessKey {
    semantic_cid: String,
    provenance_kind: ProofIrProvenanceKind,
}

#[derive(Debug, Clone)]
struct ConsistencyCandidate {
    cid: String,
    body: Json,
    provenance_kind: ProofIrProvenanceKind,
    /// #3807/#3812: was this candidate's own member CID SPOKEN BY A VENDOR
    /// (attributed to a `SpeakerRole::Vendor` speaker -- a staged `.proof`
    /// under `.sugar/imports/` or a vendor-role `speak_*` utterance)? Read
    /// once at candidate-construction time via `pool.is_vendor_member` so
    /// the group solve below never has to touch the pool again to answer
    /// "whose fact is this" -- the CONSTRUCTED label, not an inference.
    spoken_by_vendor: bool,
}

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

fn contract_property_name(body: &Json) -> &str {
    body.get("name")
        .and_then(|v| v.as_str())
        .or_else(|| body.get("contractName").and_then(|v| v.as_str()))
        .unwrap_or("<unnamed>")
}

fn contract_provenance_kind(
    member: &StoredMember,
    body: &Json,
) -> Result<ProofIrProvenanceKind, String> {
    if let Some(provenance) = member
        .field("proofirProvenance")
        .or_else(|| body.get("proofirProvenance"))
    {
        return proofir_provenance_kind(provenance);
    }
    if let Some(warrants) = member
        .field("sourceWarrants")
        .or_else(|| body.get("sourceWarrants"))
        .or_else(|| body.get("source_warrants"))
    {
        return source_warrants_provenance_kind(warrants);
    }
    Err(
        "contract memento lacks required proofirProvenance/sourceWarrants provenance KIND"
            .to_string(),
    )
}

fn proofir_provenance_kind(provenance: &Json) -> Result<ProofIrProvenanceKind, String> {
    let Some(warrants) = provenance.get("warrants").and_then(|v| v.as_array()) else {
        return Err("proofirProvenance missing warrants array".to_string());
    };
    let mut saw_stated = false;
    let mut saw_derived = false;
    for warrant in warrants {
        match warrant.get("kind").and_then(|v| v.as_str()) {
            Some("Stated") => saw_stated = true,
            Some("Derived") => saw_derived = true,
            Some(other) => {
                return Err(format!(
                    "proofirProvenance carries unknown warrant kind `{other}`"
                ))
            }
            None => return Err("proofirProvenance warrant missing kind".to_string()),
        }
    }
    if saw_derived {
        Ok(ProofIrProvenanceKind::Derived)
    } else if saw_stated {
        Ok(ProofIrProvenanceKind::Stated)
    } else {
        Err("proofirProvenance warrants array is empty".to_string())
    }
}

fn source_warrants_provenance_kind(warrants: &Json) -> Result<ProofIrProvenanceKind, String> {
    let Some(warrants) = warrants.as_array() else {
        return Err("sourceWarrants must be an array to derive provenance KIND".to_string());
    };
    let mut saw_stated = false;
    let mut saw_derived = false;
    for warrant in warrants {
        match warrant.get("kind").and_then(|v| v.as_str()) {
            Some("source-memento") => saw_stated = true,
            Some("proofir-provenance") => match proofir_provenance_kind(warrant)? {
                ProofIrProvenanceKind::Stated => saw_stated = true,
                ProofIrProvenanceKind::Derived => saw_derived = true,
            },
            Some(other) => {
                return Err(format!(
                    "sourceWarrants carries unknown provenance memento kind `{other}`"
                ))
            }
            None => return Err("sourceWarrants entry missing kind".to_string()),
        }
    }
    if saw_derived {
        Ok(ProofIrProvenanceKind::Derived)
    } else if saw_stated {
        Ok(ProofIrProvenanceKind::Stated)
    } else {
        Err("sourceWarrants array is empty".to_string())
    }
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
fn consistency_verdict(
    raw: ObligationVerdict,
    property_name: &str,
    raw_reason: &str,
) -> (ObligationVerdict, String, Option<VerifyEffect>) {
    match raw {
        // raw `sat`  -> solver said Unsatisfied -> the inv IS satisfiable -> consistent
        ObligationVerdict::Unsatisfied => (
            ObligationVerdict::Discharged,
            format!("{CONSISTENT_REASON} `{property_name}` [{raw_reason}]"),
            None,
        ),
        // raw `unsat` -> solver said Discharged -> the inv is contradictory -> refuse
        ObligationVerdict::Discharged => (
            ObligationVerdict::Unsatisfied,
            format!("{CONTRADICTORY_REASON} `{property_name}` [{raw_reason}]"),
            None,
        ),
        // An honest refusal passes through as a typed effect, never overwritten
        // with the generic encoding-STOP message.
        ObligationVerdict::Refused => {
            let effect = VerifyEffect::ConsistencyNoSoundDischarger {
                property_name: property_name.to_string(),
                solver_reason: raw_reason.to_string(),
            };
            let boundary = effect.to_legacy_boundary();
            (boundary.verdict, boundary.reason, Some(effect))
        }
        // Host/budget timeout is not formula undecidability. Keep it as its own
        // typed outcome so load can never be mistaken for a solver claim.
        ObligationVerdict::SolverTimeout => {
            let effect = VerifyEffect::SolverTimeout {
                property_name: property_name.to_string(),
                solver_reason: raw_reason.to_string(),
            };
            let boundary = effect.to_legacy_boundary();
            (boundary.verdict, boundary.reason, Some(effect))
        }
        // unknown / error -> encoding STOP, surfaced loud
        other => (
            other,
            format!(
                "consistency check undecidable (encoding STOP) `{property_name}` [{raw_reason}]"
            ),
            None,
        ),
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
    // Federate platform-width primitive sorts BEFORE keying: width is a range
    // REFINEMENT, not a sort distinction, so `0:i128` and `0:u128` are the SAME
    // value. Without this they JCS-hash differently and a callsite asserted equal
    // to both is FALSELY reported contradictory -- a fake refutation (the mirror
    // of a fake discharge). The solver path already federates via
    // sort_translate; this closes the same leak in the structural pre-check.
    // Only the KEY federates; the display keeps the original width for audit.
    let term_key = libsugar::canonical::json_jcs(&federate_primitive_sorts(term)).ok()?;
    let value_key = libsugar::canonical::json_jcs(&federate_primitive_sorts(value)).ok()?;
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

/// Canonical IR sort for a Rust primitive width name, or `None` if the name is
/// not a width-refined primitive. Mirrors `sugar-walk::sort_translate`'s
/// `primitive_sort_name` (canonicalization-grammar.md §5): integer widths
/// (`i8`..`i128`/`isize`, `u8`..`u128`/`usize`) federate to `Int`; float widths
/// (`f32`/`f64`) to `Real`. Width is a range refinement sidecar to the contract,
/// never a sort identity.
fn canonical_primitive_sort(name: &str) -> Option<&'static str> {
    match name {
        "u8" | "u16" | "u32" | "u64" | "u128" | "usize" | "i8" | "i16" | "i32" | "i64" | "i128"
        | "isize" => Some("Int"),
        "f32" | "f64" => Some("Real"),
        _ => None,
    }
}

/// Recursively rewrite any `{"kind":"primitive","name":<width>}` node to its
/// canonical sort, so width-only differences (`0:i128` vs `0:u128`) collapse.
/// Pure value-preserving normalization of the SORT only; the `value` field is
/// untouched, so distinct values (`0` vs `1`) remain distinct -- this removes
/// false contradictions without hiding real ones.
fn federate_primitive_sorts(node: &Json) -> Json {
    match node {
        Json::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                out.insert(k.clone(), federate_primitive_sorts(v));
            }
            if out.get("kind").and_then(|k| k.as_str()) == Some("primitive") {
                if let Some(canon) = out
                    .get("name")
                    .and_then(|n| n.as_str())
                    .and_then(canonical_primitive_sort)
                {
                    out.insert("name".to_string(), Json::String(canon.to_string()));
                }
            }
            Json::Object(out)
        }
        Json::Array(arr) => Json::Array(arr.iter().map(federate_primitive_sorts).collect()),
        other => other.clone(),
    }
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
        effect: None,
        witnessed: false,
        locus: None,
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
            let effect = VerifyEffect::UnwitnessedDischarge {
                contract_cid: contract_cid.clone(),
                property_name: property_name.clone(),
                ground: WitnessDischargeGround::PackageRecompute { error: e },
            };
            let boundary = effect.to_legacy_boundary();
            return Some(ConsistencyResult {
                contract_cid,
                property_name,
                verdict: boundary.verdict,
                reason: boundary.reason,
                effect: Some(effect),
                witnessed: false,
                locus: None,
                verification: boundary.verification,
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
            effect: None,
            witnessed: true,
            locus: None,
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
        let effect = VerifyEffect::UnwitnessedDischarge {
            contract_cid: contract_cid.clone(),
            property_name: property_name.clone(),
            ground: WitnessDischargeGround::PackageBody {
                resolved_by: outcome.resolved_by,
                failed: outcome.failed,
                count: outcome.count,
                failed_tests: shown,
                omitted: outcome.failed_tests.len().saturating_sub(6),
            },
        };
        let boundary = effect.to_legacy_boundary();
        ConsistencyResult {
            contract_cid,
            property_name,
            verdict: boundary.verdict,
            reason: boundary.reason,
            effect: Some(effect),
            witnessed: false,
            locus: None,
            verification: boundary.verification,
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
        return Err(VerifyEffect::WitnessOracleResolution {
            resolver: resolver.argv.first().cloned(),
            message: msg.to_string(),
        }
        .to_string());
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

/// Discharge strategy: ONE LEVEL ABOVE `Solver`. Every obligation is settled by
/// exactly one of these arms, and both converge on the same
/// `ConsistencyResult`/`ObligationVerdict` codomain. This sum type answers the
/// fuzzy "is this a solver or a witness?" question ONCE, at intake, so the two
/// discharge kinds sit behind a single `Obligation -> verdict` interface.
///
/// Neither arm changes WHAT it computes:
/// * [`DischargeStrategy::ProvedBySolver`] defers, unchanged, to the symbolic
///   `Solver`/`SolverPlan` group-solve path.
/// * [`DischargeStrategy::WitnessedByExecution`] delegates, unchanged, to
///   [`try_witness_discharge`] (re-check the pinned execution-witness package).
///
/// The proved-by-solver vs witnessed-by-execution provenance distinction is NOT
/// re-invented here: it is already carried on the produced `ConsistencyResult`
/// (`witnessed: bool` + `verification.kind == "witness"`) and surfaced on the
/// report row as `dischargeMethod`/`bodyDischargeTier`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DischargeStrategy {
    /// Settle symbolically via the existing `Solver` path (group conjunction).
    ProvedBySolver,
    /// Settle by re-checking the pinned execution-witness package.
    WitnessedByExecution,
}

impl DischargeStrategy {
    /// Answer "solver or witness?" ONCE, from the obligation body. Custom
    /// execution-witness contracts take [`DischargeStrategy::WitnessedByExecution`];
    /// everything else is [`DischargeStrategy::ProvedBySolver`].
    fn classify(body: &Json) -> Self {
        if is_witness_member(body) {
            DischargeStrategy::WitnessedByExecution
        } else {
            DischargeStrategy::ProvedBySolver
        }
    }

    /// Discharge the obligation through the selected strategy's execution arm.
    /// For [`DischargeStrategy::WitnessedByExecution`] this calls
    /// [`try_witness_discharge`] UNCHANGED (it may itself return `None` when
    /// there is no settleable custom witness, in which case the caller falls
    /// through to symbolic solving). For [`DischargeStrategy::ProvedBySolver`]
    /// there is nothing to settle here: `None` signals "hand to the solver
    /// path", which is the existing behavior.
    fn discharge(
        self,
        body: &Json,
        contract_cid: String,
        property_name: String,
    ) -> Option<ConsistencyResult> {
        match self {
            DischargeStrategy::WitnessedByExecution => {
                try_witness_discharge(body, contract_cid, property_name)
            }
            DischargeStrategy::ProvedBySolver => None,
        }
    }
}

fn witness_provenance_kind_error(
    body: &Json,
    provenance_kind: ProofIrProvenanceKind,
) -> Option<String> {
    if !is_witness_member(body) || provenance_kind == ProofIrProvenanceKind::Derived {
        return None;
    }
    Some(format!(
        "custom execution-witness contract carries wrong provenance KIND; \
         owner=sugar-verifier/consistency custom-witness recompute; \
         shape=proofirProvenance.warrants[].kind={}; \
         replacement=proofirProvenance.warrants[].kind=Derived",
        provenance_kind.label()
    ))
}

fn is_panic_callsite_member(body: &Json) -> bool {
    contract_property_name(body).contains("#panic_callsite#")
}

fn panic_callsite_provenance_kind_error(
    body: &Json,
    provenance_kind: ProofIrProvenanceKind,
) -> Option<String> {
    if !is_panic_callsite_member(body) || provenance_kind == ProofIrProvenanceKind::Derived {
        return None;
    }
    Some(format!(
        "panic-callsite contract carries wrong provenance KIND; \
         owner=sugar-verifier/consistency panic-callsite ambient replay; \
         shape=proofirProvenance.warrants[].kind={}; \
         replacement=proofirProvenance.warrants[].kind=Derived",
        provenance_kind.label()
    ))
}

fn provenance_kind_refusal(cid: String, body: &Json, reason: String) -> ConsistencyResult {
    let property_name = contract_property_name(body).to_string();
    let effect = VerifyEffect::MissingProvenanceKind {
        contract_cid: cid.clone(),
        property_name: property_name.clone(),
        detail: reason,
    };
    let boundary = effect.to_legacy_boundary();
    ConsistencyResult {
        contract_cid: cid,
        property_name,
        verdict: boundary.verdict,
        reason: boundary.reason,
        effect: Some(effect),
        witnessed: false,
        locus: None,
        verification: boundary.verification,
    }
}

fn canonicalize_formula_json(inv: &Json) -> Json {
    let Ok(formula) = serde_json::from_value::<sugar_ir_types::IrFormula>(inv.clone()) else {
        return inv.clone();
    };
    serde_json::to_value(sugar_ir_types::canonicalize_formula(&formula))
        .unwrap_or_else(|_| inv.clone())
}

fn formula_semantic_cid(formula: &Json) -> String {
    let canonical = canonicalize_formula_json(formula);
    let bytes = libsugar::canonical::json_jcs(&canonical)
        .unwrap_or_else(|_| serde_json::to_string(&canonical).unwrap_or_default());
    blake3_512_of(bytes.as_bytes())
}

fn top_level_conjuncts(formula: Json) -> Vec<Json> {
    if formula.get("kind").and_then(|k| k.as_str()) == Some("and") {
        if let Some(operands) = formula.get("operands").and_then(|v| v.as_array()) {
            return operands.clone();
        }
    }
    vec![formula]
}

fn conjoin_distinct_provenance_witnesses(invs: Vec<(Json, ProofIrProvenanceKind)>) -> (Json, bool) {
    let mut seen = std::collections::BTreeSet::new();
    let mut operands = Vec::new();
    let mut collapsed_same_kind_duplicate = false;
    for (inv, provenance_kind) in invs {
        for conjunct in top_level_conjuncts(inv) {
            let key = AmbientFactWitnessKey {
                semantic_cid: formula_semantic_cid(&conjunct),
                provenance_kind,
            };
            if seen.insert(key) {
                operands.push(conjunct);
            } else {
                collapsed_same_kind_duplicate = true;
            }
        }
    }
    (
        serde_json::json!({ "kind": "and", "operands": operands }),
        collapsed_same_kind_duplicate,
    )
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
                let mut exit = json!({
                    "kind": inv.result.exit.kind.as_str(),
                    "timedOut": inv.result.timed_out,
                });
                if let Some(code) = inv.result.exit.code {
                    exit["code"] = json!(code);
                }
                if let Some(diagnostic) = &inv.result.evidence.diagnostic {
                    exit["diagnosticCid"] = json!(&diagnostic.cid);
                    exit["diagnosticBytes"] = json!(diagnostic.byte_len);
                }
                if let Some(frontend_error) = &inv.result.exit.frontend_error {
                    exit["frontendError"] = serde_json::to_value(frontend_error)
                        .expect("FrontendErrorPayload serializes");
                }
                let mut value = json!({
                    "solver": &inv.result.solver_name,
                    "version": &inv.result.solver_version,
                    "compiler": &inv.compiler,
                    "authoritative": inv.authoritative,
                    "verdict": inv.result.verdict.as_str(),
                    "exit": exit,
                });
                if let Some(stdout) = &inv.result.evidence.stdout {
                    value["stdoutCid"] = json!(&stdout.cid);
                    value["stdoutBytes"] = json!(stdout.byte_len);
                }
                if let Some(stderr) = &inv.result.evidence.stderr {
                    value["stderrCid"] = json!(&stderr.cid);
                    value["stderrBytes"] = json!(stderr.byte_len);
                }
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

/// Stamp the two pool-resolved ProofIR facts onto a consistency result's
/// verification detail so the CLI report can render them to human-readable FOL
/// (the `sugar lift --report --visual` rendering) for the IDE squiggle:
///   - `clientFactIr`: the consumer's OWN asserted fact (pre-vendor-conjoin) --
///     the YOUR-FACT half of the flip.
///   - `vendorFactIr`: the vendor's own sworn ground vectors that were conjoined
///     from the staged .proof -- the VENDOR-FACT half.
/// The VENDOR-UNIVERSE half is already inline as `linkedPosts[].vendorPost`.
/// These are small single-equality formulas (NOT the ~MB conjoined universe,
/// which stays externalized by CID), so inlining them is memory-safe.
/// Fail-open: a result with no verification object is left untouched.
/// Union two ProofIR fact lists, de-duplicating by canonical JCS so a vector
/// captured by both the ambient-conjoin path and the sworn-vector scan appears
/// once.
fn union_facts(mut a: Vec<Json>, b: Vec<Json>) -> Vec<Json> {
    let mut seen: std::collections::BTreeSet<String> = a
        .iter()
        .filter_map(|f| libsugar::canonical::json_jcs(f).ok())
        .collect();
    for f in b {
        let key = libsugar::canonical::json_jcs(&f).unwrap_or_default();
        if seen.insert(key) {
            a.push(f);
        }
    }
    a
}

fn attach_conjoined_facts(
    result: &mut ConsistencyResult,
    client_fact: &Json,
    vendor_facts: &[Json],
) {
    let Some(Json::Object(v)) = result.verification.as_mut() else {
        return;
    };
    v.insert("clientFactIr".to_string(), client_fact.clone());
    if !vendor_facts.is_empty() {
        v.insert(
            "vendorFactIr".to_string(),
            Json::Array(vendor_facts.to_vec()),
        );
    }
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
    // The checked formula is the conjoined universe -- on a real stdlib run that
    // is ~MB per obligation, and the report accumulates one verification detail
    // per obligation (10k+), so holding it INLINE OOMs (~43GB observed). Pin it
    // BY CID instead: content-addressed, recomputable from the pinned proof
    // inputs -- the same externalize-by-CID move as witness bodies, one level
    // down. The verdict NEVER reads this field (it is computed by solving
    // `not(inv)`); it is audit-only. So addressing it by reference loses no
    // soundness and no refutation power -- it is a correctness-neutral memory fix.
    let checked_formula_cid = libsugar::canonical::json_jcs(checked_formula)
        .map(|jcs| blake3_512_of(jcs.as_bytes()))
        .unwrap_or_else(|_| "blake3-512:uncanonicalizable-checked-formula".to_string());
    json!({
        "kind": "consistency",
        "property": property_name,
        "checkedFormulaCid": checked_formula_cid,
        "linkedPosts": linked_posts_to_json(linked_posts),
        "rawSolverVerdict": raw_verdict.map(|v| v.as_str()),
        "finalVerdict": final_verdict.as_str(),
        "solverReason": solver_reason,
        "solverInvocations": solver_invocations_to_json(invs),
    })
}

/// Count the number of independent top-level atomic constraints in `inv`.
/// An `and([a, b, ...])` contributes its operand count; any other shape
/// (bare atomic, forall, implies, ctor equality, etc.) contributes 1.
/// Used to gate the consistency-SAT check: a lone constraint with no sibling
/// is trivially satisfiable (any uninterpreted callsite satisfies it) and must
/// NOT count as a substantive discharge — there is nothing to contradict it.
fn count_top_level_constraints(inv: &Json) -> usize {
    if inv.get("kind").and_then(|k| k.as_str()) == Some("and") {
        inv.get("operands")
            .and_then(|v| v.as_array())
            .map(|a| a.len())
            .unwrap_or(1)
    } else {
        1
    }
}

/// Does a LONE fact carry a COVERING DOMAIN UNIVERSE that genuinely decides it?
///
/// The vacuity guard (`count_top_level_constraints < 2`) refuses lone facts
/// because a bare opaque equality `=(call:foo(x), 99)` is trivially SAT — the
/// callsite ctor is uninterpreted, so any model assigns it 99 and the "discharge"
/// is not entailed. That reasoning holds ONLY for the degenerate `=` universe over
/// an uninterpreted term. A lone fact stated against a REAL theory universe is a
/// different animal: `str.in-regex(subject, R)` is regex-as-language membership,
/// and z3's string/regex sort GENUINELY decides it — SAT iff `subject` is in the
/// language of `R`, UNSAT otherwise. So a lone membership over a PINNED GROUND
/// subject is a substantive verdict, not a vacuous one, and must reach the solver.
///
/// SOUNDNESS RAIL. The subject must be pinned: a closed ground term with NO
/// uninterpreted `call:` ctor. An UNPINNED subject (a free var or an opaque
/// callresult) is trivially SAT again — the solver would pick some member string
/// and falsely discharge — so it stays vacuous and refused. This is the same line
/// the `=` case draws: interpreted+ground universe decides; uninterpreted operand
/// does not.
fn lone_fact_has_covering_universe(inv: &Json) -> bool {
    // Unwrap a single-operand `and([...])` (the lifter conjoins a contract's atoms,
    // so a one-atom contract arrives as `and([atom])`). A 0- or >=2-operand `and`
    // is handled by the ordinary constraint-count path, not here.
    let node = match inv.get("kind").and_then(|k| k.as_str()) {
        Some("and") => match inv.get("operands").and_then(|v| v.as_array()) {
            Some(operands) if operands.len() == 1 => &operands[0],
            _ => return false,
        },
        _ => inv,
    };
    is_ground_regex_membership(node)
}

/// A `str.in-regex(subject, R)` membership atom whose SUBJECT is a pinned ground
/// term (closed, no uninterpreted `call:` ctor) and whose PATTERN is a String
/// const literal (the vendor's walked regex, the emitter's required shape). This
/// is the regex-as-language covering universe: z3 decides membership outright.
fn is_ground_regex_membership(node: &Json) -> bool {
    if node.get("kind").and_then(|k| k.as_str()) != Some("atomic") {
        return false;
    }
    if node.get("name").and_then(|v| v.as_str()) != Some("str.in-regex") {
        return false;
    }
    let Some(args) = node.get("args").and_then(|v| v.as_array()) else {
        return false;
    };
    if args.len() != 2 {
        return false;
    }
    let subject = &args[0];
    let pattern = &args[1];
    let subject_pinned =
        formula_is_closed(subject, &mut Vec::new()) && !term_has_opaque_call(subject);
    let pattern_is_const_literal = pattern.get("kind").and_then(|k| k.as_str()) == Some("const");
    subject_pinned && pattern_is_const_literal
}

/// True if any `call:*` ctor appears anywhere in `term`. Such a ctor is an
/// uninterpreted callresult; a fact whose operand contains one is not pinned to a
/// concrete value and cannot be a substantive lone-fact discharge.
fn term_has_opaque_call(term: &Json) -> bool {
    if is_callsite_ctor_term(term) {
        return true;
    }
    for key in ["args", "operands"] {
        if let Some(arr) = term.get(key).and_then(|v| v.as_array()) {
            if arr.iter().any(term_has_opaque_call) {
                return true;
            }
        }
    }
    if let Some(body) = term.get("body") {
        if term_has_opaque_call(body) {
            return true;
        }
    }
    false
}

/// Run the raw-satisfiability consistency check on a single `inv` and label it.
/// Shared by the per-contract path and the cross-proof conjoined path.
fn check_inv_consistency(
    cid: String,
    property_name: &str,
    inv: Json,
    linked_posts: Vec<LinkedPostInstance>,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> ConsistencyResult {
    check_inv_consistency_with_vacuity_reason(
        cid,
        property_name,
        inv,
        linked_posts,
        plan,
        registry,
        compilers,
        VacuityRefusalKind::NoSiblingToContradict,
    )
}

fn check_inv_consistency_with_vacuity_reason(
    cid: String,
    property_name: &str,
    inv: Json,
    linked_posts: Vec<LinkedPostInstance>,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    vacuity_kind: VacuityRefusalKind,
) -> ConsistencyResult {
    let t_local = std::time::Instant::now();
    let inv = with_local_forall_instances(canonicalize_formula_json(&inv), property_name);
    let local_inst_us = t_local.elapsed().as_micros();
    // VACUITY GUARD. A lone constraint (count < 2) has no sibling to contradict.
    // Any uninterpreted callsite trivially satisfies it under bare SAT, giving a
    // Discharged verdict that is NOT entailed — there is no universe forcing the
    // value. Refuse early so a lone opaque equality like `=(call:foo(x), 99)` is
    // never counted as a substantive discharge. Conjunctions (count >= 2) proceed:
    // two constraints CAN contradict each other, making SAT genuinely informative.
    //
    // COVERING-UNIVERSE EXCEPTION. The count<2 test counts JOIN PARTNERS (siblings),
    // but a lone fact can still be genuinely decided by its RIGHT-HAND SORT'S
    // UNIVERSE when that universe is a real theory rather than the degenerate `=`
    // over an uninterpreted term. `str.in-regex(subject, R)` with a pinned ground
    // subject is regex-as-language membership: z3 returns real SAT/UNSAT, so it is a
    // substantive verdict and must reach the solver. Vacuous is therefore: alone in
    // the bucket AND no covering universe — not merely count<2.
    let constraint_count = count_top_level_constraints(&inv);
    if constraint_count < 2 && !lone_fact_has_covering_universe(&inv) {
        let effect = match vacuity_kind {
            VacuityRefusalKind::NoSiblingToContradict => VerifyEffect::NoSiblingToContradict {
                contract_cid: cid.clone(),
                property_name: property_name.to_string(),
                constraint_count,
            },
            VacuityRefusalKind::MissingIndependentKindWitness => {
                VerifyEffect::MissingIndependentKindWitness {
                    contract_cid: cid.clone(),
                    property_name: property_name.to_string(),
                }
            }
        };
        let boundary = effect.to_legacy_boundary();
        let solver_reason = effect.legacy_solver_reason();
        return ConsistencyResult {
            contract_cid: cid,
            property_name: property_name.to_string(),
            verdict: boundary.verdict,
            reason: boundary.reason,
            effect: Some(effect),
            witnessed: false,
            locus: None,
            verification: Some(consistency_verification_detail(
                property_name,
                &inv,
                &linked_posts,
                None,
                boundary.verdict,
                solver_reason,
                &[],
            )),
        };
    }
    if let Some(reason) = structural_contradiction_reason(&inv) {
        let verdict = ObligationVerdict::Unsatisfied;
        return ConsistencyResult {
            contract_cid: cid,
            property_name: property_name.to_string(),
            verdict,
            reason: format!("{CONTRADICTORY_REASON} `{property_name}` [structural: {reason}]"),
            effect: None,
            witnessed: false,
            locus: None,
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
    let (raw, raw_reason, invs) = match CompilerInput::decode_json(raw_sat_goal.clone()) {
        Ok(input) => run_plan_with_compilers(plan, registry, compilers, &input),
        Err(error) => (
            ObligationVerdict::Undecidable,
            format!("frontend decode: {}", error.payload),
            Vec::new(),
        ),
    };
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
    let (verdict, reason, effect) = consistency_verdict(raw, property_name, &raw_reason);
    if matches!(
        verdict,
        ObligationVerdict::Undecidable | ObligationVerdict::SolverTimeout
    ) {
        warn!(
            contract = %property_name,
            cid = %cid,
            raw = ?raw,
            "consistency: undecided solver outcome -- encoding STOP, NOT a pass"
        );
    }
    ConsistencyResult {
        contract_cid: cid,
        property_name: property_name.to_string(),
        verdict,
        reason,
        effect,
        witnessed: false,
        locus: None,
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

#[derive(Debug, Clone)]
struct AmbientGroundCallsiteFact {
    source_cid: String,
    scope: Option<String>,
    term_key: String,
    witness_key: AmbientFactWitnessKey,
    fact: Json,
}

/// Collect closed ground facts about concrete callsite terms. A literal-domain
/// loop replay may emit `call:g(3) == 1` rather than a universal. That fact is
/// still in the pool's shared callsite vocabulary and must constrain sibling
/// `#euf#` obligations about the same concrete call. We collect only ground
/// equalities whose subject is a `call:*` ctor; local variables and non-call
/// helper ctors never travel. Unlike closed universals, these are finite replay
/// facts from one assertion context, so they are scoped to that context and do
/// not pool across independent consumers that happen to name the same callsite.
fn collect_ambient_ground_callsite_facts(
    inv: &Json,
    source_cid: &str,
    scope: &Option<String>,
    provenance_kind: ProofIrProvenanceKind,
    out: &mut Vec<AmbientGroundCallsiteFact>,
) {
    match inv.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => {}
        Some("and") => {
            if let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    collect_ambient_ground_callsite_facts(
                        op,
                        source_cid,
                        scope,
                        provenance_kind,
                        out,
                    );
                }
            }
        }
        Some("implies") => {
            let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) else {
                return;
            };
            if ops.len() == 2 && eval_ground_bool(&ops[0]) == Some(true) {
                collect_ambient_ground_callsite_facts(
                    &ops[1],
                    source_cid,
                    scope,
                    provenance_kind,
                    out,
                );
            }
        }
        Some("atomic") if inv.get("name").and_then(|v| v.as_str()) == Some("=") => {
            let Some((term, _value)) = ground_term_const_equality(inv) else {
                return;
            };
            let Some(term_key) = ground_callsite_term_key(term) else {
                return;
            };
            out.push(AmbientGroundCallsiteFact {
                source_cid: source_cid.to_string(),
                scope: scope.clone(),
                term_key,
                witness_key: AmbientFactWitnessKey {
                    semantic_cid: formula_semantic_cid(inv),
                    provenance_kind,
                },
                fact: inv.clone(),
            });
        }
        _ => {}
    }
}

fn ground_callsite_witness_keys(
    inv: &Json,
    scope: &Option<String>,
    provenance_kind: ProofIrProvenanceKind,
) -> std::collections::BTreeSet<AmbientFactWitnessKey> {
    let mut facts = Vec::new();
    collect_ambient_ground_callsite_facts(
        inv,
        "<current-obligation>",
        scope,
        provenance_kind,
        &mut facts,
    );
    facts.into_iter().map(|fact| fact.witness_key).collect()
}

fn is_ground_callsite_fact_formula(formula: &Json) -> bool {
    if formula.get("kind").and_then(|k| k.as_str()) != Some("atomic")
        || formula.get("name").and_then(|v| v.as_str()) != Some("=")
    {
        return false;
    }
    let Some((term, _value)) = ground_term_const_equality(formula) else {
        return false;
    };
    ground_callsite_term_key(term).is_some()
}

fn is_derived_ground_callsite_support(
    property_name: &str,
    candidate: &ConsistencyCandidate,
    inv: &Json,
) -> bool {
    if candidate.provenance_kind != ProofIrProvenanceKind::Derived
        || !property_name.contains("#euf#")
    {
        return false;
    }
    let conjuncts = top_level_conjuncts(inv.clone());
    !conjuncts.is_empty() && conjuncts.iter().all(is_ground_callsite_fact_formula)
}

fn suppress_standalone_support_vacuity(
    property_name: &str,
    candidate: &ConsistencyCandidate,
    original_inv: &Json,
    result: &ConsistencyResult,
) -> bool {
    result.verdict == ObligationVerdict::Refused
        && matches!(
            &result.effect,
            Some(VerifyEffect::NoSiblingToContradict { .. })
        )
        && is_derived_ground_callsite_support(property_name, candidate, original_inv)
}

fn is_callsite_ctor_term(term: &Json) -> bool {
    term.get("kind").and_then(|k| k.as_str()) == Some("ctor")
        && term
            .get("name")
            .and_then(|n| n.as_str())
            .is_some_and(|name| name.starts_with("call:"))
}

/// The ctor NAME (`call:encodeBase64`) of a ground callsite equality's subject,
/// used to pair a consumer's fact with the vendor's own sworn vectors about the
/// SAME callee (a different argument, e.g. the vendor's `encodeBase64("abc")`).
fn ground_fact_subject_name(fact: &Json) -> Option<String> {
    let args = fact.get("args").and_then(|v| v.as_array())?;
    let subject = args.first()?;
    subject
        .get("name")
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

/// Collect the vendor's OWN sworn ground vectors (e.g.
/// `encodeBase64("abc") == "YWJj"`) that share the consumer obligation's callee
/// but were sworn by a DIFFERENT memento (the staged .proof). These are the
/// VENDOR-FACT half of the three-part IDE FOL. Display-only: they are surfaced
/// on the report row, never conjoined into the solved obligation, so they carry
/// no soundness weight on the verdict. Excludes the obligation's own source cids
/// (a row is not its own vendor) and honors ambient scope.
fn collect_vendor_sworn_facts(
    client_fact: &Json,
    ambient: &[AmbientGroundCallsiteFact],
    excluded_source_cids: &[String],
) -> Vec<Json> {
    let mut client_callees: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut client_facts = Vec::new();
    collect_ambient_ground_callsite_facts(
        client_fact,
        "<client>",
        &None,
        ProofIrProvenanceKind::Stated,
        &mut client_facts,
    );
    for f in &client_facts {
        if let Some(name) = ground_fact_subject_name(&f.fact) {
            client_callees.insert(name);
        }
    }
    if client_callees.is_empty() {
        return Vec::new();
    }
    let client_term_keys: std::collections::BTreeSet<&str> =
        client_facts.iter().map(|f| f.term_key.as_str()).collect();

    let mut seen = std::collections::BTreeSet::new();
    let mut out = Vec::new();
    for fact in ambient {
        if excluded_source_cids.iter().any(|c| c == &fact.source_cid) {
            continue;
        }
        // NOTE: no `scope` filter here (unlike the solver-conjoin path). This
        // surfacing is DISPLAY-ONLY -- the vendor's vector is never conjoined
        // into the solved obligation -- so it carries no soundness weight, and
        // the federation's whole point is that a vendor vector sworn in ITS OWN
        // scope is exactly what should appear next to the consumer's fact.
        // Same callee as the consumer's fact, but a DIFFERENT sworn callsite
        // (its own distinct argument vector), so we surface the vendor's proof
        // vector rather than echoing the consumer's own claim.
        if client_term_keys.contains(fact.term_key.as_str()) {
            continue;
        }
        let Some(name) = ground_fact_subject_name(&fact.fact) else {
            continue;
        };
        if !client_callees.contains(&name) {
            continue;
        }
        if seen.insert(fact.term_key.clone()) {
            out.push(fact.fact.clone());
        }
    }
    out
}

fn ground_callsite_term_key(term: &Json) -> Option<String> {
    if !is_callsite_ctor_term(term) {
        return None;
    }
    libsugar::canonical::json_jcs(&federate_primitive_sorts(term)).ok()
}

fn ambient_ground_callsite_scope(property_name: &str) -> Option<String> {
    if let Some((prefix, _)) = property_name.split_once("#euf#") {
        return Some(
            prefix
                .rsplit_once("::")
                .map(|(scope, _callee)| scope.to_string())
                .unwrap_or_else(|| prefix.to_string()),
        );
    }
    None
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
    // CALLSITE-BOUNDED materialization (no ground-const flood). We specialize each
    // universal ONLY at the concrete CALLSITES present in the obligation -- never
    // against every ground const of the sort. The former ground-const path was an
    // unbounded literal flood (profiled: 18K-57K ground terms -> 142-517s for ONE
    // obligation, dominated by json_jcs dedup) and redundant: the universal is
    // also conjoined as a `forall` QUANTIFIER, so z3 decides arbitrary points via
    // MBQI/e-matching -- that is what lets the universe decide inputs no assertion
    // ever named. The callsite instances we keep are NOT for z3's benefit; they
    // give the SOLVER-INDEPENDENT ground-contradiction check its teeth: a point
    // claim `g(2)==2` is refused even by a stubbed/lying/missing solver because the
    // universal specialized at the callsite g(2) (-> g(2)==1) contradicts it
    // structurally. Callsites are the pool's shared vocabulary (EUF: a pure g(2)
    // has one value); arbitrary literals are not. Bounded by the obligation's own
    // callsites, this stays cheap even for u128 isqrt loops and 540-element arrays.
    let t_all = std::time::Instant::now();
    AMBIENT_SUBST_US.with(|c| c.set(0));
    AMBIENT_JCS_US.with(|c| c.set(0));

    // Callsites depend only on the obligation, not the universal -- collect once.
    let mut callsites = Vec::new();
    collect_unquantified_ctor_terms(inv, &mut callsites);
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
        // (a) Specialize at the obligation's OWN subject argument(s), named in its
        // `#euf#` property name (`...(i:N)...`). Bounded by the name (a callsite's
        // arity), relevant (the point the obligation is about). This -- unlike the
        // dropped inv-wide `collect_unquantified_ground_terms` -- never walks the
        // inv's array literals / loop ranges (the 142s/517s flood source).
        if let Some(sort) = forall.get("sort") {
            let mut name_terms = Vec::new();
            collect_property_name_ground_terms(property_name, sort, &mut name_terms);
            for term in &name_terms {
                push_ambient_instance(body, var_name, term, &mut instances, &mut seen);
            }
        }
        // (b) Specialize at the obligation's concrete callsites (pattern match).
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
    // Surface only non-trivial calls (>=2ms); timestamped by the subscriber.
    if total_us >= 2000 {
        info!(
            property = property_name,
            ambient = ambient.len(),
            callsite_pairs,
            instances = instances.len(),
            subst_us,
            jcs_us,
            total_us,
            "verifier/timing: ambient instantiation (callsite-bounded)"
        );
    }
    instances
}

// Extract the Int constants named in an obligation's `#euf#` property name
// (`...(i:N)...`) -- the obligation's own subject argument(s). Bounded by the name
// (a callsite's arity), so it never walks the inv's array literals / loop ranges
// the way an inv-wide ground-term scan would. Used for callsite-relevant ambient
// specialization in `instantiate_ambient_foralls_for_inv`.
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

/// Conjoin closed ground callsite facts into matching callsite-keyed obligations.
/// This is the finite-replay twin of `with_ambient_foralls`: a replayed literal
/// loop has already named the concrete calls (`call:g(0)`, `call:g(1)`, ...), so
/// only facts whose subject exactly appears in the current obligation are
/// relevant. Bare names still receive nothing, and callsite-keyed obligations
/// receive only facts from the same source/test scope; two independent consumers
/// can share a structural `call:*` term without pooling their asserted values.
fn with_ambient_ground_callsite_facts(
    inv: Json,
    property_name: &str,
    ambient: &[AmbientGroundCallsiteFact],
    excluded_source_cids: &[String],
    current_ground_witnesses: &std::collections::BTreeSet<AmbientFactWitnessKey>,
) -> (Json, bool, Vec<Json>) {
    if ambient.is_empty() || !property_name.contains("#euf#") {
        return (inv, false, Vec::new());
    }

    let mut callsites = Vec::new();
    collect_unquantified_ctor_terms(&inv, &mut callsites);
    let wanted: std::collections::BTreeSet<String> = callsites
        .iter()
        .filter_map(ground_callsite_term_key)
        .collect();
    if wanted.is_empty() {
        return (inv, false, Vec::new());
    }
    let obligation_scope = ambient_ground_callsite_scope(property_name);

    let mut seen = std::collections::BTreeSet::new();
    let mut facts = Vec::new();
    let mut skipped_same_kind_duplicate = false;
    for fact in ambient {
        // A stated row is not independent testimony for itself. The ambient
        // replay path may only add facts sourced from other mementos.
        if excluded_source_cids
            .iter()
            .any(|source_cid| source_cid == &fact.source_cid)
        {
            continue;
        }
        if fact
            .scope
            .as_ref()
            .is_some_and(|scope| Some(scope) != obligation_scope.as_ref())
        {
            continue;
        }
        if !wanted.contains(&fact.term_key) {
            continue;
        }
        if current_ground_witnesses.contains(&fact.witness_key) {
            skipped_same_kind_duplicate = true;
            continue;
        }
        if seen.insert(fact.witness_key.clone()) {
            facts.push(fact.fact.clone());
        }
    }
    if facts.is_empty() {
        return (inv, skipped_same_kind_duplicate, Vec::new());
    }

    // The conjoined `facts` ARE the vendor's own sworn ground vectors (e.g.
    // `encodeBase64("abc") == "YWJj"`) imported from the staged .proof; return
    // them so the report can render the VENDOR FACT half of the three-part FOL.
    let vendor_facts = facts.clone();
    let mut operands = Vec::with_capacity(facts.len() + 1);
    operands.push(inv);
    operands.extend(facts);
    (
        serde_json::json!({ "kind": "and", "operands": operands }),
        skipped_same_kind_duplicate,
        vendor_facts,
    )
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
    for (_bridge_cid, bridge_env) in pool.bridge_members() {
        let Some(source_symbol) = bridge_env
            .field("sourceSymbol")
            .and_then(|v| v.as_str())
            .map(str::to_string)
        else {
            continue;
        };
        if source_symbol.is_empty() {
            continue;
        }
        let Some(target_cid) = bridge_env
            .field("targetContractCid")
            .and_then(|v| v.as_str())
            .and_then(|raw| MementoCid::try_parse(raw.to_string()).ok())
        else {
            continue;
        };
        let Some(body) = pool.contract_body_by_cid(&target_cid) else {
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
        let target_proof_cid = bridge_env
            .field("targetProofCid")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| {
                pool.bridge_self_bundle_by_symbol
                    .get(&source_symbol)
                    .cloned()
                    .map(|cid| cid.to_string())
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
        for post in ambient.iter().filter(|post| {
            let bare = name
                .strip_prefix("call:")
                .or_else(|| name.strip_prefix("method:"))
                .unwrap_or(name);
            (post.source_symbol == name || post.source_symbol == bare)
                && post.formals.len() == args.len()
        }) {
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
    // CALLSITE-BOUNDED materialization. `instantiate_ambient_foralls_for_inv` now
    // specializes each universal only at the obligation's concrete CALLSITES (no
    // ground-const flood -- see its doc), so this stays bounded even for wide
    // ranges (u128 isqrt loops). It is NOT redundant with the conjoined `forall`
    // quantifier: the quantifier lets z3 decide un-named points via MBQI, while
    // these callsite instances give the SOLVER-INDEPENDENT ground-contradiction
    // check its teeth -- a point claim contradicting the universal at a named
    // callsite is refused even by a stubbed/lying/missing solver.
    let instances = instantiate_ambient_foralls_for_inv(&inv, property_name, &foralls);
    if instances.is_empty() {
        return inv;
    }
    let mut operands = Vec::with_capacity(instances.len() + 1);
    operands.push(inv);
    operands.extend(instances);
    serde_json::json!({ "kind": "and", "operands": operands })
}

/// Walk every contract member in `pool`, apply the consistency-candidate
/// filter (`is_consistency_candidate`) and the provenance-KIND gate, and
/// return the surviving candidates plus any provenance refusals. This is the
/// FIRST loop of `verify_consistency`, factored out (pure relocation, no
/// behavior change) so the seal-time manifest builder
/// (`build_manifest_from_pool`) can run the identical filter scoped to one
/// proof's own pool instead of re-scanning a whole-pool verify pass -- the
/// "pure relocation of the existing scan/grouping code from every-prove to
/// once-per-seal" the join-manifest design calls for.
fn collect_consistency_candidates(
    pool: &MementoPool,
) -> (Vec<ConsistencyCandidate>, Vec<ConsistencyResult>) {
    let mut candidates: Vec<ConsistencyCandidate> = Vec::new();
    let mut provenance_refusals: Vec<ConsistencyResult> = Vec::new();
    for (cid, member) in pool.contract_members() {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        if !is_consistency_candidate(&body) {
            continue;
        }
        match contract_provenance_kind(member, &body) {
            Ok(provenance_kind) => {
                if let Some(reason) = witness_provenance_kind_error(&body, provenance_kind)
                    .or_else(|| panic_callsite_provenance_kind_error(&body, provenance_kind))
                {
                    warn!(
                        cid = %cid,
                        contract = contract_property_name(&body),
                        provenance_kind = provenance_kind.label(),
                        reason = %reason,
                        "verifier/ambient: contract carries wrong provenance KIND; refusing rather than defaulting"
                    );
                    provenance_refusals.push(provenance_kind_refusal(
                        cid.to_string(),
                        &body,
                        reason,
                    ));
                } else {
                    let spoken_by_vendor = pool.is_vendor_member(&cid.to_string());
                    candidates.push(ConsistencyCandidate {
                        cid: cid.to_string(),
                        body,
                        provenance_kind,
                        spoken_by_vendor,
                    });
                }
            }
            Err(reason) => {
                warn!(
                    cid = %cid,
                    contract = contract_property_name(&body),
                    reason = %reason,
                    "verifier/ambient: contract lacks required provenance KIND; refusing rather than defaulting"
                );
                provenance_refusals.push(provenance_kind_refusal(cid.to_string(), &body, reason));
            }
        }
    }
    (candidates, provenance_refusals)
}

/// SEAL-TIME MANIFEST BUILDER (join-manifest design, lane 1). Runs the exact
/// same candidate filter `verify_consistency` uses
/// (`collect_consistency_candidates`), the exact same `#euf#`-name grouping
/// criterion (`property_name.contains("#euf#")`), and the exact same ambient
/// collectors (`collect_ambient_foralls`, `collect_ambient_ground_callsite_facts`),
/// scoped to ONE proof's own pool -- `pool` here is expected to be loaded
/// from just-minted bytes (this proof alone), not the whole project pool.
/// `contributor_bundle` is this proof's own identity, recorded per group so a
/// LATER cross-proof reader (out of this lane's scope; see design items 3-4)
/// can detect a stale reference after a re-mint.
pub fn build_manifest_from_pool(
    pool: &MementoPool,
    contributor_bundle: &str,
) -> sugar_proof_envelope::manifest::Manifest {
    let (candidates, _provenance_refusals) = collect_consistency_candidates(pool);

    let mut manifest = sugar_proof_envelope::manifest::Manifest::new();

    for candidate in &candidates {
        let name = contract_property_name(&candidate.body).to_string();
        if !name.contains("#euf#") {
            continue;
        }
        let group = manifest.groups.entry(name).or_default();
        group.member_cids.insert(candidate.cid.clone());
        // First writer sets the contributor bundle; every candidate in this
        // pool comes from the same just-minted proof, so this is invariant
        // across a group's members.
        if group.contributor_bundle.is_empty() {
            group.contributor_bundle = contributor_bundle.to_string();
        }
    }

    for candidate in &candidates {
        if is_witness_member(&candidate.body) {
            continue;
        }
        let Some(inv) = candidate.body.get("inv") else {
            continue;
        };
        let inv = canonicalize_formula_json(inv);

        let mut foralls: Vec<Json> = Vec::new();
        collect_ambient_foralls(&inv, &mut foralls);
        if !foralls.is_empty() {
            manifest
                .ambient
                .closed_forall_cids
                .insert(candidate.cid.clone());
        }

        let contract_name = contract_property_name(&candidate.body);
        let ground_scope = ambient_ground_callsite_scope(contract_name);
        let mut facts: Vec<AmbientGroundCallsiteFact> = Vec::new();
        collect_ambient_ground_callsite_facts(
            &inv,
            &candidate.cid,
            &ground_scope,
            candidate.provenance_kind,
            &mut facts,
        );
        if !facts.is_empty() {
            manifest
                .ambient
                .ground_callsite_fact_cids
                .insert(candidate.cid.clone());
        }
    }

    manifest
}

/// Unscoped consistency over a whole pool: build the pool's
/// [`ConsistencyIndex`] and drive the single solve door
/// [`verify_consistency_from_indexes`] with no overlay and no scope. This is a
/// thin convenience over the door for callers that hold a pool directly (the
/// referee wrapper and the in-module tests); production `prove` and the daemon
/// call the door themselves.
pub fn verify_consistency(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
) -> Vec<ConsistencyResult> {
    let index = build_consistency_index(pool);
    verify_consistency_from_indexes(&index, None, plan, registry, compilers, project_root, None)
}

/// Pool-derived consistency inputs, computed once per pool and reusable
/// across solve calls (#3774 daemonSolve trim). Every field is a pure
/// projection of `pool` -- field for field, the same construction
/// `verify_consistency` performs inline before driving the solve door (the
/// stages MOVED into `build_consistency_index_filtered`; they were not
/// reimplemented). The daemon caches the resident base (vendor) pool's index
/// in its ProveContext and, per request, builds only the tiny scratch-proof
/// overlay's index, merging the two in
/// `verify_consistency_scoped_with_base_index` -- so the per-save cost is
/// O(overlay members), not O(pool re-scan + pool clone).
pub struct ConsistencyIndex {
    candidates: Vec<ConsistencyCandidate>,
    provenance_refusals: Vec<ConsistencyResult>,
    ambient_foralls: Vec<Json>,
    ambient_ground_callsite_facts: Vec<AmbientGroundCallsiteFact>,
    ambient_posts: Vec<AmbientPost>,
    /// Raw (contract/property name, locus) pairs in pool iteration order.
    /// The project-local preference merge (consumer file beats vendor file
    /// for the squiggle anchor) happens at solve time in
    /// `verify_consistency_from_indexes` because it needs `project_root`.
    locus_entries: Vec<(String, SourceLocus)>,
}

impl ConsistencyIndex {
    /// Number of consistency candidates the pool contributed. Exposed for
    /// caller-side telemetry only; the solve path never re-derives from it.
    pub fn candidate_count(&self) -> usize {
        self.candidates.len()
    }
}

/// Build the pool's [`ConsistencyIndex`]. This is stage 1 of
/// `verify_consistency` factored out verbatim; callers that hold a stable
/// pool (the daemon's resident vendor pool) build this once and pass it to
/// `verify_consistency_scoped_with_base_index` per request.
pub fn build_consistency_index(pool: &MementoPool) -> ConsistencyIndex {
    build_consistency_index_filtered(pool, None)
}

/// Same construction as [`build_consistency_index`], but candidates and
/// provenance refusals whose CID appears in `skip_cids` are dropped BEFORE
/// ambient collection. Used for the overlay index in the merged (cached)
/// path: when the same member CID exists in both the base pool and the
/// overlay scratch proof, the merged-pool semantics are "one member" (the
/// pool dedupes by CID on load), so the overlay index must not contribute a
/// second copy -- a duplicate would flip an identical-assertion group from
/// PROVEN to a same-kind-duplicate vacuity refusal the merged-pool run never
/// raises.
fn build_consistency_index_filtered(
    pool: &MementoPool,
    skip_cids: Option<&std::collections::HashSet<String>>,
) -> ConsistencyIndex {
    let (candidates, provenance_refusals) = collect_consistency_candidates(pool);
    let (candidates, provenance_refusals): (Vec<ConsistencyCandidate>, Vec<ConsistencyResult>) =
        match skip_cids {
            None => (candidates, provenance_refusals),
            Some(skip) => (
                candidates
                    .into_iter()
                    .filter(|c| !skip.contains(&c.cid))
                    .collect(),
                provenance_refusals
                    .into_iter()
                    .filter(|r| !skip.contains(&r.contract_cid))
                    .collect(),
            ),
        };

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
    let mut ambient_ground_callsite_facts: Vec<AmbientGroundCallsiteFact> = Vec::new();
    for candidate in &candidates {
        let cid = &candidate.cid;
        let body = &candidate.body;
        if is_witness_member(body) {
            continue;
        }
        let contract_name = contract_property_name(body);
        if let Some(inv) = body.get("inv") {
            let inv = canonicalize_formula_json(inv);
            let before = ambient_foralls.len();
            collect_ambient_foralls(&inv, &mut ambient_foralls);
            let found = ambient_foralls.len() - before;
            let ground_scope = ambient_ground_callsite_scope(contract_name);
            collect_ambient_ground_callsite_facts(
                &inv,
                cid,
                &ground_scope,
                candidate.provenance_kind,
                &mut ambient_ground_callsite_facts,
            );
            if found > 0 {
                debug!(
                    cid = cid.as_str(),
                    contract = contract_name,
                    provenance_kind = candidate.provenance_kind.label(),
                    foralls = found,
                    inv_kind = inv.get("kind").and_then(|k| k.as_str()).unwrap_or("?"),
                    "verifier/ambient: collected universal(s) from contract inv"
                );
            }
        }
    }
    let ambient_posts = collect_ambient_posts(pool);

    // Pool-wide assertion-locus entries, keyed by contract/property name. The
    // callsite-keyed consistency candidate is a coalesced claim whose OWN body
    // carries no `file`/`span`; the assertion's source locus lives on the
    // sibling SOURCE-MEMENTO member the lifter emitted for that same assertion
    // (its `contractName` == the property name). We read `file`+`span` straight
    // off that member -- no re-derivation -- so an `unsatisfied` verdict can be
    // anchored back to the exact `assert` line/column in the editor.
    // #3802 root cause: locus carriers differ per lifter. The python lifter
    // emits `source-memento` members; the RUST lifter emits
    // `assertion-surface-memento` members carrying the same
    // contractName+file+line payload. Reading only source mementos left the
    // rust overlay's locus map EMPTY, so the editor-scope filter dropped
    // every rust consumer group -- the daemon then answered 0 rows with
    // degraded=false (the false green). Scan BOTH kinds; `locus_from_body`
    // applies the identical field contract to each.
    let mut locus_entries: Vec<(String, SourceLocus)> = Vec::new();
    for (_cid, member) in pool.source_memento_members().chain(
        pool.members_by_kind(sugar_proof_envelope::MemberKind::AssertionSurfaceMemento),
    ) {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        if let Some(l) = locus_from_body(&body) {
            locus_entries.push((contract_property_name(&body).to_string(), l));
        }
    }

    ConsistencyIndex {
        candidates,
        provenance_refusals,
        ambient_foralls,
        ambient_ground_callsite_facts,
        ambient_posts,
        locus_entries,
    }
}

/// CACHED-BASE editor path (#3774 daemonSolve trim): identical semantics to
/// loading `overlay_pool`'s members onto the base pool and running the solve
/// door with `Some(scope)` over the merged pool -- adjudicated by the
/// differential test `cached_index_path_matches_merged_pool_scoped_run`
/// (sugar-linkerd/tests/prove_consistency.rs) -- but the base pool's
/// candidates/ambients/locus come from the prebuilt `base` index instead of
/// an O(pool) re-scan, and the base pool itself is never cloned. Per-request
/// work: index the (tiny) overlay pool, dedupe by CID against the base,
/// merge, group, solve the in-scope groups.
pub fn verify_consistency_scoped_with_base_index(
    base: &ConsistencyIndex,
    overlay_pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    scope: &Path,
) -> Vec<ConsistencyResult> {
    let skip: std::collections::HashSet<String> = base
        .candidates
        .iter()
        .map(|c| c.cid.clone())
        .chain(
            base.provenance_refusals
                .iter()
                .map(|r| r.contract_cid.clone()),
        )
        .collect();
    let overlay = build_consistency_index_filtered(overlay_pool, Some(&skip));
    verify_consistency_from_indexes(
        base,
        Some(&overlay),
        plan,
        registry,
        compilers,
        project_root,
        Some(scope),
    )
}

/// THE consistency solve door. Grouping, scoping, and the per-group solve,
/// over the merged (base + optional overlay) index. Every consistency verdict
/// -- production `prove` (via `verify_consistency`), the editor daemon (via
/// `verify_consistency_scoped_with_base_index`), and the tests -- flows through
/// this one function; `overlay` supplies the daemon's per-request scratch
/// index (or `None` for a whole-pool run) and `scope` restricts which groups
/// are solved (or `None` for the full CLI pass).
#[allow(clippy::too_many_arguments)]
pub fn verify_consistency_from_indexes(
    base: &ConsistencyIndex,
    overlay: Option<&ConsistencyIndex>,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    scope: Option<&Path>,
) -> Vec<ConsistencyResult> {
    let candidates: Vec<&ConsistencyCandidate> = base
        .candidates
        .iter()
        .chain(overlay.iter().flat_map(|o| o.candidates.iter()))
        .collect();
    let provenance_refusals: Vec<ConsistencyResult> = base
        .provenance_refusals
        .iter()
        .cloned()
        .chain(
            overlay
                .iter()
                .flat_map(|o| o.provenance_refusals.iter().cloned()),
        )
        .collect();
    let ambient_foralls: Vec<Json> = base
        .ambient_foralls
        .iter()
        .cloned()
        .chain(overlay.iter().flat_map(|o| o.ambient_foralls.iter().cloned()))
        .collect();
    let ambient_ground_callsite_facts: Vec<AmbientGroundCallsiteFact> = base
        .ambient_ground_callsite_facts
        .iter()
        .cloned()
        .chain(
            overlay
                .iter()
                .flat_map(|o| o.ambient_ground_callsite_facts.iter().cloned()),
        )
        .collect();
    // Ambient posts merge with (source_symbol, target_cid) dedupe: the
    // merged-pool run sees one bridge member per CID, so an overlay proof
    // re-declaring a base bridge must not conjoin the same post twice.
    let mut ambient_posts: Vec<AmbientPost> = base.ambient_posts.clone();
    if let Some(o) = overlay {
        let seen: std::collections::HashSet<(String, String)> = ambient_posts
            .iter()
            .map(|p| (p.source_symbol.clone(), p.target_cid.clone()))
            .collect();
        for p in &o.ambient_posts {
            if !seen.contains(&(p.source_symbol.clone(), p.target_cid.clone())) {
                ambient_posts.push(p.clone());
            }
        }
    }

    info!(
        candidates = candidates.len(),
        ambient_foralls = ambient_foralls.len(),
        ambient_ground_callsite_facts = ambient_ground_callsite_facts.len(),
        "verifier/ambient: universals will be conjoined into every obligation"
    );
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
    let mut by_name: std::collections::BTreeMap<String, Vec<&ConsistencyCandidate>> =
        std::collections::BTreeMap::new();
    for candidate in &candidates {
        let name = contract_property_name(&candidate.body).to_string();
        by_name.entry(name).or_default().push(*candidate);
    }

    // Locus map with PROJECT-LOCAL PREFERENCE. When two source mementos share
    // a contractName (a consumer asserting the EXACT sworn fact -> case-1
    // congruence, e.g. `len(pd.DataFrame()) == 1` contradicting pandas' sworn
    // `== 0`), the consumer's assertion and the vendor's sworn assertion
    // collide on the same euf coordinate. First-write-wins would anchor the
    // squiggle at the VENDOR's source file (pandas' internal
    // `tests/frame/test_constructors.py`) instead of the user's line.
    // Overwrite only when the NEW locus's file EXISTS under project_root on
    // disk and the CURRENT one does not -- the consumer's `test_consumer.py`
    // lives under the project; the vendor's path does not. Fail-open: if
    // neither or both exist, keep first-write (no worse than before).
    let mut locus_by_name: HashMap<String, SourceLocus> = HashMap::new();
    for (name, l) in base
        .locus_entries
        .iter()
        .chain(overlay.iter().flat_map(|o| o.locus_entries.iter()))
    {
        match locus_by_name.entry(name.clone()) {
            std::collections::hash_map::Entry::Vacant(e) => {
                e.insert(l.clone());
            }
            std::collections::hash_map::Entry::Occupied(mut e) => {
                let new_local = project_root.join(&l.file).exists();
                let cur_local = project_root.join(&e.get().file).exists();
                if new_local && !cur_local {
                    e.insert(l.clone());
                }
            }
        }
    }

    // EDITOR SCOPE (the daemon's `Some(scope)` door call): keep only groups whose
    // anchor locus resolves inside `scope` ON DISK. Whole groups are kept or
    // dropped -- never individual members -- so a kept group's conjunct set
    // (vendor sworn facts included) is identical to the unscoped run's, and
    // its solved row is therefore identical too. Ambient sets stay pool-wide.
    // Members are CLONED only for KEPT groups (post-filter), never for the
    // vendor-internal thousands the editor never paints.
    let groups: Vec<(String, Vec<ConsistencyCandidate>)> = by_name
        .into_iter()
        .filter(|(property_name, members)| match scope {
            None => true,
            Some(scope_root) => {
                let anchored_in_scope = |name: &str| {
                    locus_by_name
                        .get(name)
                        .map(|l| scope_root.join(&l.file).exists())
                        .unwrap_or(false)
                };
                anchored_in_scope(property_name)
                    || members
                        .iter()
                        .any(|m| anchored_in_scope(contract_property_name(&m.body).as_ref()))
            }
        })
        .map(|(name, members)| (name, members.into_iter().cloned().collect()))
        .collect();

    let mut results: Vec<ConsistencyResult> = groups
        .par_iter()
        .flat_map(|(property_name, members)| {
            process_consistency_group(
                property_name,
                members,
                &ambient_posts,
                &ambient_ground_callsite_facts,
                &ambient_foralls,
                &locus_by_name,
                plan,
                registry,
                compilers,
            )
        })
        .collect();
    results.extend(provenance_refusals);

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

/// PER-GROUP SOLVE, factored out of the solve door (pure relocation, no
/// behavior change) so grouping/scoping in `verify_consistency_from_indexes`
/// drives the conjoin/vacuity classification one `#euf#` group at a time.
/// `property_name`/`members` name one `#euf#` (or plain) callsite group;
/// `ambient_posts`/`ambient_ground_callsite_facts`/`ambient_foralls` are the
/// pool-wide background facts asserted into every obligation.
#[allow(clippy::too_many_arguments)]
fn process_consistency_group(
    property_name: &str,
    members: &[ConsistencyCandidate],
    ambient_posts: &[AmbientPost],
    ambient_ground_callsite_facts: &[AmbientGroundCallsiteFact],
    ambient_foralls: &[Json],
    locus_by_name: &HashMap<String, SourceLocus>,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> Vec<ConsistencyResult> {
    let property_name = &property_name.to_string();
    {
            let mut out: Vec<ConsistencyResult> = Vec::new();

            // WITNESS members are settled from the rust-recomputed package body,
            // PER MEMBER. They are NEVER folded into the symbolic conjunction
            // AND never short-circuit the group: a witness member must not mask
            // a contradictory inv group.
            let mut inv_cids: Vec<String> = Vec::new();
            let mut inv_candidates: Vec<ConsistencyCandidate> = Vec::new();
            for candidate in members {
                let body = &candidate.body;
                // Answer "solver or witness?" ONCE via the discharge-strategy sum
                // type, then dispatch. The WitnessedByExecution arm wraps
                // `try_witness_discharge` unchanged; ProvedBySolver falls through
                // to the symbolic group-solve path below (byte-identical control
                // flow to the prior `if is_witness_member { try_witness_discharge }`).
                let strategy = DischargeStrategy::classify(body);
                if let Some(res) =
                    strategy.discharge(body, candidate.cid.clone(), property_name.clone())
                {
                    out.push(res);
                    continue;
                }
                inv_cids.push(candidate.cid.clone());
                inv_candidates.push(candidate.clone());
            }
            if inv_candidates.is_empty() {
                return out;
            }

            // CROSS-PROOF CONJOIN only for CALLSITE-KEYED names (`#euf#`). That key
            // is `(callee, args)`, so same name == same call == sound to conjoin a
            // consumer's assertion with an imported vendor contract -> `and(==5,==6)`
            // -> unsat -> refused. A bare test/location name does NOT guarantee the
            // same subject, so those stay PER-CONTRACT (conjoining them could falsely
            // refuse two unrelated tests that happen to share a function name).
            let callsite_keyed = property_name.contains("#euf#");
            if callsite_keyed && inv_candidates.len() > 1 {
                let invs: Vec<(Json, ProofIrProvenanceKind)> = inv_candidates
                    .iter()
                    .map(|candidate| {
                        (
                            canonicalize_formula_json(&axiom_context_formula(&candidate.body)),
                            candidate.provenance_kind,
                        )
                    })
                    .collect();
                let (inv, collapsed_same_kind_duplicate) =
                    conjoin_distinct_provenance_witnesses(invs);
                // #3807/#3812: the group's SOLVER INPUT (`inv`, above) stays
                // the full conjunction of every candidate -- consumer-spoken
                // AND vendor-spoken -- byte-identical to before this change.
                // What changes is what gets LABELED "your fact" for the
                // report/IDE row: partition the group's candidates by their
                // CONSTRUCTED speaker attribution
                // (`ConsistencyCandidate::spoken_by_vendor`, stamped at
                // intake from which speaker each member's bytes actually
                // came from) instead of treating the whole conjoined group
                // as the client's own fact. `clientFactIr` is the
                // conjunction of the CONSUMER-spoken candidates ONLY (a
                // single candidate needs no `and` wrapper); `vendorFactIr`
                // gathers the VENDOR-spoken candidates' equalities alongside
                // the imported ambient sworn facts. A group with no
                // consumer-spoken candidate at all (vendor-internal, e.g.
                // two staged vendor mementos sharing an `#euf#` name)
                // attaches nothing new, matching pre-#3774 behavior.
                let (own_candidates, vendor_candidates): (Vec<_>, Vec<_>) =
                    inv_candidates.iter().partition(|c| !c.spoken_by_vendor);
                // ONE construction (#3813 review): the client fact is built
                // by the SAME conjoin/flatten/dedup helper that builds the
                // solver input, restricted to the consumer-spoken
                // candidates. For an all-consumer group this is
                // byte-identical to the pre-partition `clientFactIr` (the
                // whole group's flattened, provenance-deduped conjunction);
                // for a mixed group it is that same construction minus the
                // vendor's conjuncts.
                let client_fact_partitioned: Option<Json> = if own_candidates.is_empty() {
                    None
                } else {
                    let own_invs: Vec<(Json, ProofIrProvenanceKind)> = own_candidates
                        .iter()
                        .map(|candidate| {
                            (
                                canonicalize_formula_json(&axiom_context_formula(&candidate.body)),
                                candidate.provenance_kind,
                            )
                        })
                        .collect();
                    let (client_fact, _) = conjoin_distinct_provenance_witnesses(own_invs);
                    Some(client_fact)
                };
                let vendor_spoken_equalities: Vec<Json> = vendor_candidates
                    .iter()
                    .map(|c| canonicalize_formula_json(&axiom_context_formula(&c.body)))
                    .collect();
                let current_ground_witnesses: std::collections::BTreeSet<_> = inv_candidates
                    .iter()
                    .flat_map(|candidate| {
                        let scope = ambient_ground_callsite_scope(property_name);
                        let inv =
                            canonicalize_formula_json(&axiom_context_formula(&candidate.body));
                        ground_callsite_witness_keys(&inv, &scope, candidate.provenance_kind)
                            .into_iter()
                    })
                    .collect();
                let (inv, linked_posts) = with_ambient_posts_with_instances(inv, &ambient_posts);
                let (inv, skipped_same_kind_duplicate, vendor_facts) =
                    with_ambient_ground_callsite_facts(
                        inv,
                        property_name,
                        &ambient_ground_callsite_facts,
                        &inv_cids,
                        &current_ground_witnesses,
                    );
                let inv = with_ambient_foralls(inv, property_name, &ambient_foralls);
                let mut result = if collapsed_same_kind_duplicate || skipped_same_kind_duplicate {
                    check_inv_consistency_with_vacuity_reason(
                        inv_cids[0].clone(),
                        property_name,
                        inv,
                        linked_posts,
                        plan,
                        registry,
                        compilers,
                        VacuityRefusalKind::MissingIndependentKindWitness,
                    )
                } else {
                    check_inv_consistency(
                        inv_cids[0].clone(),
                        property_name,
                        inv,
                        linked_posts,
                        plan,
                        registry,
                        compilers,
                    )
                };
                if let Some(client_fact_own) = &client_fact_partitioned {
                    let sworn = collect_vendor_sworn_facts(
                        client_fact_own,
                        &ambient_ground_callsite_facts,
                        &inv_cids,
                    );
                    attach_conjoined_facts(
                        &mut result,
                        client_fact_own,
                        &union_facts(union_facts(vendor_facts, vendor_spoken_equalities), sworn),
                    );
                }
                out.push(result);
            } else {
                for candidate in &inv_candidates {
                    let original_inv =
                        canonicalize_formula_json(&axiom_context_formula(&candidate.body));
                    let scope = ambient_ground_callsite_scope(property_name);
                    let current_ground_witnesses = ground_callsite_witness_keys(
                        &original_inv,
                        &scope,
                        candidate.provenance_kind,
                    );
                    let (inv, linked_posts) =
                        with_ambient_posts_with_instances(original_inv.clone(), &ambient_posts);
                    let (inv, skipped_same_kind_duplicate, vendor_facts) =
                        with_ambient_ground_callsite_facts(
                            inv,
                            property_name,
                            &ambient_ground_callsite_facts,
                            std::slice::from_ref(&candidate.cid),
                            &current_ground_witnesses,
                        );
                    let inv = with_ambient_foralls(inv, property_name, &ambient_foralls);
                    let mut result = if skipped_same_kind_duplicate {
                        check_inv_consistency_with_vacuity_reason(
                            candidate.cid.clone(),
                            property_name,
                            inv,
                            linked_posts,
                            plan,
                            registry,
                            compilers,
                            VacuityRefusalKind::MissingIndependentKindWitness,
                        )
                    } else {
                        check_inv_consistency(
                            candidate.cid.clone(),
                            property_name,
                            inv,
                            linked_posts,
                            plan,
                            registry,
                            compilers,
                        )
                    };
                    // #3807/#3812: this branch processes ONE candidate at a
                    // time (no cross-proof conjoin), so `original_inv` is
                    // already that candidate's own formula with nothing else
                    // folded in. It is the client's own fact ONLY when the
                    // candidate was spoken by the consumer; a lone
                    // VENDOR-spoken candidate (a vendor-internal contract
                    // that never joined an `#euf#` group) must attach
                    // nothing new rather than mislabel a vendor fact as the
                    // client's.
                    if !candidate.spoken_by_vendor {
                        let sworn = collect_vendor_sworn_facts(
                            &original_inv,
                            &ambient_ground_callsite_facts,
                            std::slice::from_ref(&candidate.cid),
                        );
                        attach_conjoined_facts(
                            &mut result,
                            &original_inv,
                            &union_facts(vendor_facts, sworn),
                        );
                    }
                    if !suppress_standalone_support_vacuity(
                        property_name,
                        candidate,
                        &original_inv,
                        &result,
                    ) {
                        out.push(result);
                    }
                }
            }
            // Stamp the group's source locus onto every result so an
            // `unsatisfied` verdict says WHERE. All members of a group share
            // one property_name (one call site / one assertion), so the first
            // member with a readable `file`+`span` is the right anchor. Only
            // fills a locus we do not already have (fail-open, never overwrite).
            let group_locus = members
                .iter()
                .find_map(|c| locus_from_body(&c.body))
                .or_else(|| locus_by_name.get(property_name).cloned());
            if group_locus.is_some() {
                for r in out.iter_mut() {
                    if r.locus.is_none() {
                        r.locus = group_locus.clone();
                    }
                }
            }
            out
    }
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

    fn test_cid(label: &str) -> MementoCid {
        MementoCid::try_parse(label.to_string()).unwrap_or_else(|_| {
            MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(label.as_bytes()))
                .expect("test CID must parse")
        })
    }

    fn test_cid_string(label: &str) -> String {
        test_cid(label).to_string()
    }

    fn pool_with_contract(name: &str, inv: Json) -> MementoPool {
        let mut pool = MementoPool::default();
        let cid = test_cid(&format!("contract:{name}"));
        // v1.2 layered shape: accessors branch on presence of `envelope`.
        let env = json!({
            "envelope": {
                "header": {
                    "kind": "contract",
                    "contractName": name,
                    "inv": inv,
                    "proofirProvenance": proofir_provenance("Stated"),
                }
            }
        });
        pool.insert_unanchored_for_tests(cid, env);
        pool
    }

    fn z3_plan_and_registry() -> (SolverPlan, HashMap<SolverSeat, SolverHandle>) {
        let registry = registry::build_default_z3("z3");
        (SolverPlan::Single(SolverSeat::Z3), registry)
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
    fn proofir_provenance(kind: &str) -> Json {
        let warrant = match kind {
            "Stated" => json!({
                "kind": "Stated",
                "locus": {"path": "tests/consistency.rs", "line": 1, "column": 0}
            }),
            "Derived" => json!({
                "kind": "Derived",
                "floorChain": ["tests/consistency-floor"]
            }),
            other => panic!("unknown test proofir provenance kind {other}"),
        };
        json!({
            "kind": "proofir-provenance",
            "nodeClass": "EqualityFact",
            "constructionSite": {"path": "tests/consistency.rs", "line": 1, "column": 0},
            "warrants": [warrant]
        })
    }

    fn insert_contract_with_provenance(
        pool: &mut MementoPool,
        cid: &str,
        name: &str,
        inv: Json,
        provenance_kind: &str,
    ) {
        let env = json!({
            "envelope": {
                "header": {
                    "kind": "contract",
                    "contractName": name,
                    "inv": inv,
                    "proofirProvenance": proofir_provenance(provenance_kind)
                }
            }
        });
        pool.insert_unanchored_for_tests(test_cid(cid), env);
    }

    fn insert_contract(pool: &mut MementoPool, cid: &str, name: &str, inv: Json) {
        insert_contract_with_provenance(pool, cid, name, inv, "Stated");
    }

    fn insert_derived_contract(pool: &mut MementoPool, cid: &str, name: &str, inv: Json) {
        insert_contract_with_provenance(pool, cid, name, inv, "Derived");
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

    fn package_contract_with_provenance(
        tool: &str,
        package_cid: &str,
        count: usize,
        passed: usize,
        provenance_kind: &str,
    ) -> Json {
        let mut body = package_contract(tool, package_cid, count, passed);
        body.as_object_mut()
            .expect("package contract body is an object")
            .insert(
                "proofirProvenance".to_string(),
                proofir_provenance(provenance_kind),
            );
        body
    }

    fn insert_package_contract_with_provenance(pool: &mut MementoPool, cid: &str, body: Json) {
        let env = json!({
            "envelope": {
                "header": body
            }
        });
        pool.insert_unanchored_for_tests(test_cid(cid), env);
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "consistent conjunction must stay proven (no false refusal): {res:?}"
        );

        // a LONE contract has no sibling to contradict -> REFUSED (vacuous)
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:solo", name, eqf(var("r"), int(5)));
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "lone constraint has no sibling to contradict — must be Refused (vacuous), not Discharged: {res:?}"
        );
    }

    /// #3812 ATTRIBUTION LABELS on the cross-proof contradiction: the row's
    /// `clientFactIr` must be EXACTLY the CONSUMER-spoken conjunct and
    /// `vendorFactIr` must carry the VENDOR-spoken conjunct, read from the
    /// pool's Speaker attribution -- and FLIPPING the attribution flips the
    /// labels while the verdict stays REFUSED, because attribution never
    /// touches the solver input. This is the pandas-demo row shape ("Your
    /// fact = 6 / Vendor fact = 5") as a constructed fact, with the
    /// discrimination arm (flip) that a positional heuristic would fail.
    #[test]
    fn attribution_constructs_fact_labels_and_flipping_attribution_flips_them() {
        use crate::types::SpeakerRole;
        let (plan, reg) = z3_plan_and_registry();
        let name = "numpy.add#euf#callresult_numpy_add_a2(2,3)::assertion";

        let solve_with = |consumer_speaks_6: bool| -> ConsistencyResult {
            let mut pool = MementoPool::default();
            insert_contract(&mut pool, "speaker-c6", name, eqf(var("r"), int(6)));
            insert_contract(&mut pool, "speaker-v5", name, eqf(var("r"), int(5)));
            let (consumer_cid, vendor_cid) = if consumer_speaks_6 {
                ("speaker-c6", "speaker-v5")
            } else {
                ("speaker-v5", "speaker-c6")
            };
            pool.attribute_member_for_tests(
                &test_cid_string(consumer_cid),
                SpeakerRole::Consumer,
                "me",
            );
            pool.attribute_member_for_tests(
                &test_cid_string(vendor_cid),
                SpeakerRole::Vendor,
                "the-vendor",
            );
            let mut res = verify_consistency(
                &pool,
                &plan,
                &reg,
                &test_compilers(),
                std::path::Path::new("."),
            );
            assert_eq!(res.len(), 1, "one conjoined group: {res:?}");
            res.remove(0)
        };

        let labels = |r: &ConsistencyResult| -> (String, String) {
            let v = r.verification.as_ref().expect("verification detail");
            let client = v.get("clientFactIr").expect("client fact label").to_string();
            let vendor = v
                .get("vendorFactIr")
                .expect("vendor fact label")
                .to_string();
            (client, vendor)
        };

        // Consumer speaks ==6, vendor speaks ==5.
        let normal = solve_with(true);
        assert_eq!(normal.verdict, ObligationVerdict::Unsatisfied);
        let (client, vendor) = labels(&normal);
        assert!(
            client.contains("\"value\":6") && !client.contains("\"value\":5"),
            "clientFactIr must be the consumer's ==6 conjunct ONLY: {client}"
        );
        assert!(
            vendor.contains("\"value\":5") && !vendor.contains("\"value\":6"),
            "vendorFactIr must carry the vendor's ==5 conjunct: {vendor}"
        );

        // FLIP the speakers over the SAME two contracts: labels flip,
        // verdict does not.
        let flipped = solve_with(false);
        assert_eq!(
            flipped.verdict,
            ObligationVerdict::Unsatisfied,
            "attribution must never change the verdict (solver input is byte-identical)"
        );
        let (client, vendor) = labels(&flipped);
        assert!(
            client.contains("\"value\":5") && !client.contains("\"value\":6"),
            "flipped clientFactIr must be the (now consumer-spoken) ==5 conjunct: {client}"
        );
        assert!(
            vendor.contains("\"value\":6") && !vendor.contains("\"value\":5"),
            "flipped vendorFactIr must carry the (now vendor-spoken) ==6 conjunct: {vendor}"
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one conjoined obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "await(f())==6 ∧ await(f())==7 over the SAME structural await term refuses: {res:?}"
        );
    }

    /// REGRESSION (int-width fake refutation): a callsite asserted equal to the
    /// SAME value under two integer WIDTHS (`f()==0:i128 ∧ f()==0:u128`) is NOT a
    /// contradiction -- width is a range refinement, not a sort. Before the fix
    /// the structural detector JCS-hashed the width-specific `sort.name`, so the
    /// two values keyed differently and it falsely refused. Observed live on the
    /// stdlib coretests corpus (30/32 structural unsatisfieds were this).
    #[test]
    fn integer_width_difference_is_not_a_contradiction() {
        let (plan, reg) = z3_plan_and_registry();
        let f = json!({"kind":"ctor","name":"call:f","args":[]});
        let zero_i128 = json!({"kind":"const","value":0,"sort":{"kind":"primitive","name":"i128"}});
        let zero_u128 = json!({"kind":"const","value":0,"sort":{"kind":"primitive","name":"u128"}});
        let inv = json!({"kind":"and","operands":[
            eqf(f.clone(), zero_i128),
            eqf(f.clone(), zero_u128),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:int-width-refine",
            "width_refine#euf#c:callresult_x::assertion",
            inv,
        );
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one conjoined obligation: {res:?}");
        assert_ne!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "0:i128 and 0:u128 are the SAME value -- width is a refinement, not a \
             contradiction: {res:?}"
        );
    }

    /// DISCRIMINATION: same callsite, DIFFERENT values across widths
    /// (`f()==0:i128 ∧ f()==1:u8`) IS a real contradiction -- federating the
    /// SORT must never federate the VALUE.
    #[test]
    fn distinct_values_across_widths_still_refuses() {
        let (plan, reg) = z3_plan_and_registry();
        let f = json!({"kind":"ctor","name":"call:f","args":[]});
        let zero_i128 = json!({"kind":"const","value":0,"sort":{"kind":"primitive","name":"i128"}});
        let one_u8 = json!({"kind":"const","value":1,"sort":{"kind":"primitive","name":"u8"}});
        let inv = json!({"kind":"and","operands":[
            eqf(f.clone(), zero_i128),
            eqf(f.clone(), one_u8),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:int-width-value",
            "width_value#euf#c:callresult_x::assertion",
            inv,
        );
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one conjoined obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "0 and 1 differ in VALUE -- a real contradiction even across widths: {res:?}"
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let vendor_cid = test_cid_string("vendor-enc-contract");
        // Production bridges store the BARE symbol name (no "call:" prefix).
        // The callsite ctor uses the prefixed form "call:enc".
        // This test exercises the production shape so the linker's strip logic is exercised.
        let bridge_source_symbol = "enc"; // bare — what real bridges emit
        let callsite_ctor_name = "call:enc"; // prefixed — what callsites emit
        let call_enc = |arg: Json| json!({"kind":"ctor","name":callsite_ctor_name,"args":[arg]});
        let post = implies(
            eqf(var("input"), string_const("def")),
            eqf(var("out"), string_const("ghi")),
        );

        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            test_cid(&vendor_cid),
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
                    "sourceSymbol": bridge_source_symbol,
                    "targetContractCid": vendor_cid.clone(),
                    "targetProofCid": "blake3-512:vendor-proof"
                }
            }
        });
        pool.insert_bridge_by_symbol(bridge_source_symbol, test_cid("vendor-bridge"), bridge);

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

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 2, "two fresh consumer assertions: {res:?}");
        let good = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:good-consumer-assertion"))
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
            bridge_source_symbol
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
            .find(|r| r.contract_cid == test_cid_string("blake3-512:bad-consumer-assertion"))
            .expect("bad consumer assertion row present");
        assert_eq!(
            bad.verdict,
            ObligationVerdict::Unsatisfied,
            "vendor post enc(\"def\") = \"ghi\" must refute the fresh bad assertion: {res:?}"
        );
    }

    #[test]
    fn stale_same_symbol_bridge_does_not_hide_body_post_bridge() {
        let (plan, reg) = z3_plan_and_registry();
        let vendor_cid = test_cid_string("vendor-enc-contract");
        let stale_target_cid = test_cid_string("stale-callsite-target");
        let bridge_source_symbol = "enc";
        let call_enc = |arg: Json| json!({"kind":"ctor","name":"call:enc","args":[arg]});
        let post = implies(
            eqf(var("input"), string_const("def")),
            eqf(var("out"), string_const("ghi")),
        );

        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            test_cid(&vendor_cid),
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
        let good_bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": bridge_source_symbol,
                    "targetContractCid": vendor_cid.clone(),
                    "targetProofCid": "blake3-512:vendor-proof"
                }
            }
        });
        let stale_bridge = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": bridge_source_symbol,
                    "targetContractCid": stale_target_cid,
                    "callsite": {
                        "file": "src/lib.rs",
                        "start_line": 12,
                        "panicSite": false
                    }
                }
            }
        });
        pool.insert_unanchored_for_tests(test_cid("good-body-bridge"), good_bridge);
        pool.insert_unanchored_for_tests(test_cid("stale-callsite-bridge"), stale_bridge);
        // Model the production failure: the lossy per-symbol bridge slot can
        // point at a same-symbol callsite bridge whose target is not a loaded
        // post-bearing contract. Ambient consistency corroboration must still
        // see the valid body bridge member rather than treating the assertion
        // as lone testimony.
        pool.bridges_by_symbol.insert(
            bridge_source_symbol.to_string(),
            test_cid("stale-callsite-bridge"),
        );

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

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 2, "two consumer assertions: {res:?}");
        let good = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:good-consumer-assertion"))
            .expect("good consumer assertion row present");
        assert_eq!(
            good.verdict,
            ObligationVerdict::Discharged,
            "valid body bridge must supply the independent sibling even when the per-symbol slot points at a stale callsite bridge: {res:?}"
        );
        let bad = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:bad-consumer-assertion"))
            .expect("bad consumer assertion row present");
        assert_eq!(
            bad.verdict,
            ObligationVerdict::Unsatisfied,
            "valid body bridge must still refute a lying same-callsite assertion: {res:?}"
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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

    fn str_const(v: &str) -> Json {
        json!({"kind":"const","sort":{"kind":"primitive","name":"String"},"value":v})
    }
    fn str_in_regex(subject: Json, pattern: &str) -> Json {
        json!({"kind":"atomic","name":"str.in-regex","args":[subject, str_const(pattern)]})
    }

    /// COVERING UNIVERSE — regex-as-language. A LONE `str.in-regex(subject, R)` over
    /// a PINNED GROUND subject is NOT vacuous: z3's string/regex sort decides
    /// membership. A matching literal subject -> str.in_re SAT -> DISCHARGED. Before
    /// the covering-universe exception this lone fact tripped the count<2 vacuity
    /// guard and was falsely Refused; the regex-membership showcase good suite is
    /// built on this discharge.
    #[test]
    fn lone_ground_regex_membership_matching_subject_discharges() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "is_match#euf#callresult_is_match_a1(s:1)::assertion";
        let inv = str_in_regex(str_const("alice_01"), "^[a-z][a-z0-9_]{2,15}$");
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:regexgood", name, inv);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one membership row: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "a matching literal subject is a MEMBER of the walked language -> discharged: {res:?}"
        );
    }

    /// THE TEETH (bad twin, same universe). A LONE `str.in-regex` over a NON-matching
    /// pinned subject -> str.in_re UNSAT -> the membership is REFUTED (Unsatisfied),
    /// by the regular language itself, not a within-test contradiction. Same atom
    /// shape as the good twin, subject the regex rejects, z3 flips the verdict.
    #[test]
    fn lone_ground_regex_membership_nonmatching_subject_is_refuted() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "is_match#euf#callresult_is_match_a1(s:1)::assertion";
        // "Alice!": uppercase lead AND '!' body char, both outside the class.
        let inv = str_in_regex(str_const("Alice!"), "^[a-z][a-z0-9_]{2,15}$");
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:regexbad", name, inv);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one membership row: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "a non-matching subject is REFUTED by z3 str.in_re UNSAT -> the teeth: {res:?}"
        );
    }

    /// SOUNDNESS RAIL. The covering-universe exception fires ONLY for a PINNED
    /// ground subject. A membership over an UNPINNED subject (an uninterpreted
    /// `call:` callresult) is trivially SAT — z3 picks some member string — so it
    /// must STAY vacuous and Refused, never a false discharge. This keeps the
    /// pre-vacuity-fix false-Discharged bug impossible on the membership path.
    #[test]
    fn lone_regex_membership_unpinned_subject_stays_vacuous_refused() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "is_match#euf#callresult_is_match_a1(s:1)::assertion";
        let opaque_subject = json!({"kind":"ctor","name":"call:subject","args":[]});
        let inv = str_in_regex(opaque_subject, "^[a-z][a-z0-9_]{2,15}$");
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:regexopaque", name, inv);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one membership row: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "an unpinned (uninterpreted callresult) subject is trivially SAT -> must stay vacuous/Refused, not falsely Discharged: {res:?}"
        );
        assert!(
            res[0].reason.contains("single constraint has no sibling"),
            "vacuity reason must surface (read-compat pin preserved): {}",
            res[0].reason
        );
    }

    /// MIXED-OPERATOR SAME-TERM, number sort universe. Two facts about the SAME
    /// left-operand call term but DIFFERENT operators must JOIN and let the number
    /// sort decide. `enc(5) < 10 ∧ enc(5) > 20` has no Int model -> UNSAT -> REFUSED.
    /// The operator is not part of the bucket key; a (term, operator) bucket would
    /// throw this verdict away. This joins through the existing callsite-keyed
    /// conjoin path (same `#euf#` name -> one obligation -> number sort in the pot).
    #[test]
    fn mixed_operator_same_term_lt_and_gt_is_unsat() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "enc#euf#callresult_enc_a1(i:1)::assertion";
        let enc5 = || json!({"kind":"ctor","name":"call:enc","args":[int(5)]});
        let lt10 = json!({"kind":"atomic","name":"<","args":[enc5(), int(10)]});
        let gt20 = json!({"kind":"atomic","name":">","args":[enc5(), int(20)]});
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:enclt", name, lt10);
        insert_contract(&mut pool, "blake3-512:encgt", name, gt20);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            1,
            "same-named facts conjoin to one obligation: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "enc(5)<10 AND enc(5)>20 is UNSAT through the number sort universe: {res:?}"
        );
    }

    /// MIXED-OPERATOR SAME-TERM, satisfiable twin. `enc(5) < 10 ∧ enc(5) < 15` HAS
    /// an Int model -> SAT -> DISCHARGED, through the same number sort universe. The
    /// good/bad pair proves the join genuinely decides (both directions flip through
    /// the same key/universe structure), not a structural "a universe is nearby".
    #[test]
    fn mixed_operator_same_term_lt_and_lt_is_sat() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "enc#euf#callresult_enc_a1(i:1)::assertion";
        let enc5 = || json!({"kind":"ctor","name":"call:enc","args":[int(5)]});
        let lt10 = json!({"kind":"atomic","name":"<","args":[enc5(), int(10)]});
        let lt15 = json!({"kind":"atomic","name":"<","args":[enc5(), int(15)]});
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:enclt10", name, lt10);
        insert_contract(&mut pool, "blake3-512:enclt15", name, lt15);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            1,
            "same-named facts conjoin to one obligation: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "enc(5)<10 AND enc(5)<15 is SAT through the number sort universe: {res:?}"
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

        // The universal alone has no sibling to contradict -> REFUSED (vacuous).
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:fa", name, forall.clone());
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1);
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "lone universal has no sibling to contradict — must be Refused (vacuous), not Discharged: {res:?}"
        );

        // Conjoined with f(2)==2 (an in-range contradiction): REFUTED.
        let contradiction = json!({"kind":"and","operands":[
            forall.clone(),
            eqf(callf(int(2)), int(2)),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:fc", name, contradiction);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 2, "two separate obligations: {res:?}");
        // Pin WHICH row refutes: the point-claim must be the Unsatisfied one and
        // the loop universal itself must stay internally consistent. An any()
        // over both rows would stay green if a regression flipped the wrong row.
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:point"))
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Unsatisfied,
            "the ambient universal must refute the separate point-claim memento: {res:?}"
        );
        let loop_row = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:loop"))
            .expect("loop row present");
        assert_eq!(
            loop_row.verdict,
            ObligationVerdict::Refused,
            "lone loop universal has no sibling to contradict — must be Refused (vacuous), not Discharged: {res:?}"
        );
    }

    /// LITERAL-REPLAY TWIN. A finite literal loop may replay to concrete callsite
    /// facts rather than a quantifier: `call:g(0)==1`, `call:g(1)==1`, ... . Those
    /// facts are still closed pool vocabulary and must constrain a separate `#euf#`
    /// point claim about the same concrete call.
    #[test]
    fn ambient_ground_callsite_fact_refutes_separate_point_claim_memento() {
        let (plan, reg) = z3_plan_and_registry();
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});
        let loop_inv = json!({"kind":"and","operands":[
            eqf(callg(int(0)), int(1)),
            eqf(callg(int(1)), int(1)),
            eqf(callg(int(2)), int(1)),
        ]});
        let point_inv = json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]});

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:loop-ground",
            "src/lib.rs::tests::t::loop::x",
            loop_inv,
        );
        insert_contract(
            &mut pool,
            "blake3-512:point-ground",
            "src/lib.rs::tests::t::g#euf#c:callresult_g_a1(i:2)::assertion",
            point_inv,
        );
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 2, "two separate obligations: {res:?}");
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:point-ground"))
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Unsatisfied,
            "the replayed ground callsite fact must refute the point claim: {res:?}"
        );
        let loop_row = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:loop-ground"))
            .expect("loop row present");
        assert_eq!(
            loop_row.verdict,
            ObligationVerdict::Discharged,
            "the replayed loop facts alone are consistent: {res:?}"
        );
    }

    #[test]
    fn ambient_ground_callsite_fact_does_not_self_witness_stated_only_claim() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});
        let stated_inv = json!({"kind":"and","operands":[eqf(calla, int(10))]});

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:stated-only-callsite",
            "src/lib.rs::tests::test_a::A#euf#c:call:A()::assertion",
            stated_inv,
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one stated-only obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "a stated-only callsite equality must not discharge by feeding itself \
             back as ambient testimony: {res:?}"
        );
        assert!(
            res[0].reason.contains("single constraint"),
            "refusal must stay loud and name the missing independent witness: {}",
            res[0].reason
        );
    }

    #[test]
    fn duplicate_minted_stated_ground_callsite_fact_does_not_mutually_corroborate() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});
        let stated_inv = json!({"kind":"and","operands":[eqf(calla, int(10))]});
        let name = "src/lib.rs::tests::test_a::A#euf#c:call:A()::assertion";

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:stated-lie-copy-a",
            name,
            stated_inv.clone(),
        );
        insert_contract(&mut pool, "blake3-512:stated-lie-copy-b", name, stated_inv);

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            1,
            "duplicate same-name stated rows coalesce: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "duplicate stated mementos are still one stated warrant, not an \
             independent-kind witness: {res:?}"
        );
        assert!(
            res[0].reason.contains("independent-KIND"),
            "refusal must name the missing independent-KIND witness: {}",
            res[0].reason
        );
    }

    #[test]
    fn same_stated_ground_callsite_fact_under_distinct_names_does_not_replay_as_independent_kind() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});
        let stated_inv = json!({"kind":"and","operands":[eqf(calla, int(10))]});

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:ambient-stated-copy-a",
            "src/lib.rs::tests::test_a::A#euf#c:call:A()::assertion",
            stated_inv.clone(),
        );
        insert_contract(
            &mut pool,
            "blake3-512:ambient-stated-copy-b",
            "src/lib.rs::tests::test_a::B#euf#c:call:A()::assertion",
            stated_inv,
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 2, "distinct names stay distinct rows: {res:?}");
        for row in &res {
            assert_eq!(
                row.verdict,
                ObligationVerdict::Refused,
                "same-kind ambient replay must not corroborate row {row:?}"
            );
            assert!(
                row.reason.contains("independent-KIND"),
                "ambient same-kind refusal must name the missing witness kind: {}",
                row.reason
            );
        }
    }

    #[test]
    fn different_stated_ground_callsite_facts_still_refute() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});
        let name = "src/lib.rs::tests::test_a::A#euf#c:call:A()::assertion";

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:stated-a-is-ten",
            name,
            json!({"kind":"and","operands":[eqf(calla.clone(), int(10))]}),
        );
        insert_contract(
            &mut pool,
            "blake3-512:stated-a-is-eleven",
            name,
            json!({"kind":"and","operands":[eqf(calla, int(11))]}),
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            1,
            "different stated values collapse to one contradiction row: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "kind filtering must not hide genuine same-callsite contradictions: {res:?}"
        );
        assert!(
            res[0].reason.contains("contradictory"),
            "reason must still name contradiction, got: {}",
            res[0].reason
        );
    }

    #[test]
    fn ambient_ground_callsite_fact_from_independent_memento_witnesses_truthful_claim() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});

        let mut pool = MementoPool::default();
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-callsite",
            "src/lib.rs::tests::test_a::derived#euf#c:call:A()::replay",
            json!({"kind":"and","operands":[eqf(calla.clone(), int(10))]}),
        );
        insert_contract(
            &mut pool,
            "blake3-512:stated-callsite",
            "src/lib.rs::tests::test_a::A#euf#c:call:A()::assertion",
            json!({"kind":"and","operands":[eqf(calla, int(10))]}),
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            2,
            "two independently sourced obligations: {res:?}"
        );
        let stated = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:stated-callsite"))
            .expect("stated row present");
        assert_eq!(
            stated.verdict,
            ObligationVerdict::Discharged,
            "matching independent ground callsite testimony still witnesses the \
             stated equality: {res:?}"
        );
    }

    #[test]
    fn conflicting_derived_ground_callsite_support_stays_loud() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});
        let name = "A#euf#c:call:A()::assertion";

        let mut pool = MementoPool::default();
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-a-is-ten",
            name,
            json!({"kind":"and","operands":[eqf(calla.clone(), int(10))]}),
        );
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-a-is-eleven",
            name,
            json!({"kind":"and","operands":[eqf(calla, int(11))]}),
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            1,
            "same-name derived support facts still group as one semantic obligation: {res:?}"
        );
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "derived support contradictions remain a loud refutation, not a skipped \
             support row: {res:?}"
        );
    }

    #[test]
    fn derived_ground_callsite_support_does_not_create_standalone_vacuity_row() {
        let (plan, reg) = z3_plan_and_registry();
        let calla = json!({"kind":"ctor","name":"call:A","args":[]});
        let call_len = json!({"kind":"ctor","name":"call:Box.__len__","args":[
            {"kind":"ctor","name":"py.object.identity","args":[
                {"kind":"const","sort":{"kind":"primitive","name":"String"},"value":"Box"},
                {"kind":"const","sort":{"kind":"primitive","name":"String"},"value":"test.py:6:28"},
            ]}
        ]});

        let mut pool = MementoPool::default();
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-len-support",
            "Box.__len__#euf#c:call:Box.__len__(c:py.object.identity(s:'Box',s:'test.py:6:28'))::assertion",
            json!({"kind":"and","operands":[eqf(call_len, int(1))]}),
        );
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-a-claim",
            "A#euf#c:call:A()::assertion",
            json!({"kind":"and","operands":[eqf(calla.clone(), int(20))]}),
        );
        insert_contract(
            &mut pool,
            "blake3-512:stated-a-claim",
            "A#euf#c:call:A()::assertion",
            json!({"kind":"and","operands":[eqf(calla, int(20))]}),
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(
            res.len(),
            1,
            "Derived-only ground callsite support must feed ambient testimony, not \
             become a standalone vacuity verdict row: {res:?}"
        );
        assert_eq!(res[0].property_name, "A#euf#c:call:A()::assertion");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "the split Stated+Derived semantic fact group should discharge as one \
             obligation: {res:?}"
        );
    }

    #[test]
    fn ambient_ground_callsite_facts_do_not_cross_consumer_scopes() {
        let (plan, reg) = z3_plan_and_registry();
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});

        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:consumer-a-point",
            "src/lib.rs::tests::consumer_a::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(1))]}),
        );
        insert_contract(
            &mut pool,
            "blake3-512:consumer-b-point",
            "src/lib.rs::tests::consumer_b::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]}),
        );
        insert_contract(
            &mut pool,
            "blake3-512:consumer-c-point",
            "src/lib.rs::tests::consumer_c::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]}),
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 3, "three separate obligations: {res:?}");
        let consumer_a = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:consumer-a-point"))
            .expect("consumer A point row present");
        assert_eq!(
            consumer_a.verdict,
            ObligationVerdict::Refused,
            "consumer A's point assertion must not pool into other consumer scopes \
             OR discharge by self-witnessing: {res:?}"
        );
        let consumer_b = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:consumer-b-point"))
            .expect("consumer B point row present");
        assert_eq!(
            consumer_b.verdict,
            ObligationVerdict::Refused,
            "consumer B must not see consumer A's different value for the same structural \
             callsite, and with no independent same-scope witness remains refused: {res:?}"
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

        let plan = SolverPlan::Single(SolverSeat::Z3);
        let mut registry = HashMap::new();
        registry.insert(
            SolverSeat::Z3,
            Arc::new(StubSolver::new("z3", ObligationVerdict::Unsatisfied)) as SolverHandle,
        );
        let res = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:point"))
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

        let plan = SolverPlan::Single(SolverSeat::Z3);
        let mut registry = HashMap::new();
        registry.insert(
            SolverSeat::Z3,
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
            &SolverPlan::Single(SolverSeat::Bitwuzla),
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:point"))
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
            &SolverPlan::Single(SolverSeat::Bitwuzla),
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:point"))
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
    /// open universal stays home; the separate in-range-looking point-claim has
    /// no independent witness and stays Refused.
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 2, "two separate obligations: {res:?}");
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:openpoint"))
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Refused,
            "an OPEN universal must not refute anything ambiently or become a \
             self-witnessed discharge: {res:?}"
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
        pool.insert_unanchored_for_tests(test_cid("witnessloop"), witness_member);
        insert_contract(
            &mut pool,
            "blake3-512:wpoint",
            "g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]}),
        );
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let point = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:wpoint"))
            .expect("point-claim row present");
        assert_eq!(
            point.verdict,
            ObligationVerdict::Refused,
            "a witness member's forall must not leak into symbolic checks, and the \
             standalone point claim must not self-witness: {res:?}"
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
        pool.insert_unanchored_for_tests(test_cid("witnessmember"), witness);
        insert_contract(&mut pool, "blake3-512:c5", name, eqf(var("r"), int(5)));
        insert_contract(&mut pool, "blake3-512:c6", name, eqf(var("r"), int(6)));
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        // per-contract: each is a lone constraint (vacuous) -> both Refused, none Discharged.
        // The key guarantee: bare names are NOT conjoined — the two rows stay separate and
        // do NOT combine into one obligation that could falsely refuse.
        assert_eq!(
            res.len(),
            2,
            "bare names must NOT collapse into one obligation: {res:?}"
        );
        assert!(
            res.iter()
                .all(|r| r.verdict == ObligationVerdict::Refused),
            "independent same-test-name lone contracts must be Refused (vacuous), not conjoined or Discharged: {res:?}"
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

    #[test]
    fn stated_provenance_cannot_discharge_custom_execution_witness_package() {
        let _env = witness_env_lock();
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("stated-witness-package-kind");
        write_resolver_manifest(&project, package_bytes);
        std::env::set_var("SUGAR_WITNESS_PROJECT_DIR", &project);

        let body = package_contract_with_provenance("cargo-test", &package_cid, 1, 1, "Stated");
        let mut pool = MementoPool::default();
        insert_package_contract_with_provenance(
            &mut pool,
            "blake3-512:stated-witness-package",
            body,
        );
        let (plan, reg) = z3_plan_and_registry();
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );

        assert_eq!(res.len(), 1, "one witness-package obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "Stated provenance is the wrong kind for recomputed execution testimony: {res:?}"
        );
        assert!(
            res[0].reason.contains("execution-witness")
                && res[0].reason.contains("Derived")
                && res[0].reason.contains("Stated"),
            "wrong-kind refusal must name the crime and replacement: {}",
            res[0].reason
        );
        assert!(
            !res[0].witnessed,
            "wrong-kind witness package must refuse before recompute can witness it"
        );

        std::env::remove_var("SUGAR_WITNESS_PROJECT_DIR");
        let _ = std::fs::remove_dir_all(&project);
    }

    #[test]
    fn stated_provenance_cannot_discharge_panic_callsite_testimony() {
        let mut pool = MementoPool::default();
        insert_contract_with_provenance(
            &mut pool,
            "panic-callsite-stated-kind",
            "tests::f#panic_callsite#euf#c:callresult_f_panic_callsite_a1(i:1)::assertion",
            ne(var("panic"), none()),
            "Stated",
        );
        let (plan, reg) = z3_plan_and_registry();
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );

        assert_eq!(res.len(), 1, "one panic-callsite obligation: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "Stated provenance is the wrong kind for derived panic-callsite testimony: {res:?}"
        );
        assert!(
            res[0].reason.contains("panic-callsite")
                && res[0].reason.contains("Derived")
                && res[0].reason.contains("Stated"),
            "wrong-kind refusal must name the crime and replacement: {}",
            res[0].reason
        );
        assert!(
            !res[0].witnessed,
            "wrong-kind panic-callsite testimony must refuse before ambient replay"
        );
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
        // assert x is not None  (single satisfiable fact) -> ≠(x, None) -> lone constraint
        // Under the vacuity guard a lone constraint is Refused (no sibling to contradict).
        let inv = ne(var("x"), none());
        let pool = pool_with_contract("test_consistent", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Refused,
            "lone constraint has no sibling — must be Refused (vacuous); reason: {}",
            results[0].reason
        );
        assert!(
            results[0]
                .reason
                .contains("single constraint has no sibling"),
            "vacuous-refused reason must cite the single-constraint guard, got: {}",
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        pool.insert_unanchored_for_tests(test_cid("bridge"), env);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
                    "proofirProvenance": proofir_provenance("Stated"),
                }
            }
        });
        pool.insert_unanchored_for_tests(test_cid("inv-post"), env);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));

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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
        assert!(
            results.is_empty(),
            "::facts::N setup-binding contract must not be a consistency candidate; got: {:?}",
            results.iter().map(|r| &r.property_name).collect::<Vec<_>>()
        );
    }

    #[test]
    fn assertion_contract_remains_a_consistency_candidate() {
        // The `::assertion` contract carries the asserted property and MUST
        // still be checked (not filtered out). Guards against an over-broad
        // `::facts` filter (substring match would wrongly catch
        // `::facts-implies-assertion`). A lone constraint has no sibling to
        // contradict and is Refused (vacuous) — the check is "is it a
        // candidate?" (len==1), not what verdict it gets.
        let inv = ne(var("y"), none());
        let pool = pool_with_contract("make_value@t.py:6:8::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
        assert_eq!(
            results.len(),
            1,
            "::assertion contract must remain a consistency candidate"
        );
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Refused,
            "lone constraint has no sibling — Refused (vacuous); was Discharged pre-vacuity-fix"
        );
    }

    #[test]
    fn bare_var_pattern3_contract_remains_a_consistency_candidate() {
        // A whole-test Pattern-3 contract is named by the test (no `::facts`
        // suffix) and must remain a candidate.
        let inv = ne(var("x"), none());
        let pool = pool_with_contract("test_x_consistent", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        // POSITIVE: `assert r == '{"a":1}'` — a single string-equality assertion.
        // Before vacuity fix: UNDECIDABLE (parse error pre-string fix) then
        // PROVEN-consistent (raw sat from z3 post-string fix).
        // After vacuity fix: REFUSED (lone constraint, no sibling to contradict).
        // The key guarantee: NOT UNDECIDABLE (encoding STOP). Refused is honest;
        // Discharged without a universe was a falsePass.
        let inv = eqf(var("r"), string_const(r#"{"a":1}"#));
        let pool = pool_with_contract("encode_jcs::assertion", inv);
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
        assert_eq!(results.len(), 1, "exactly one candidate");
        assert_eq!(
            results[0].verdict,
            ObligationVerdict::Refused,
            "single string-equality lone constraint must be Refused (vacuous — no sibling); \
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
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
        let results = verify_consistency(&pool, &plan, &registry, &test_compilers(), std::path::Path::new("."));
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].verdict, ObligationVerdict::Unsatisfied);
    }
}
