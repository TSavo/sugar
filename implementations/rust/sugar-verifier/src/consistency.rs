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
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as Json};
use tracing::{debug, info, warn};

use crate::effects::{VerifyEffect, WitnessDischargeGround};
use crate::solvers::{
    run_plan_with_compilers, SolverHandle, SolverInvocation, SolverPlan, SolverSeat,
};
use crate::types::{
    MementoCid, MementoPool, ObligationVerdict, SourceLocus, SpeakerRole, StoredMember,
};
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_ir_compiler::CompilerInput;

/// Strong type for the boolean-connective formula intermediates this module
/// BUILDS as solver goals and conjoined obligations. The operands are opaque IR
/// `Json` leaves (atomics, foralls, ctor terms, ...) that originate in the
/// lifter, not here; this enum only names the connective this module wraps them
/// in. [`IrFormula::to_value`] is the ONLY crossing back into `Json`, and it
/// reproduces the exact `{"kind":<c>,"operands":[..]}` shapes the module
/// previously hand-built with `json!`, so every solver goal, conjoined formula,
/// and report row is byte-identical (CIDs unchanged).
enum IrFormula {
    /// `{"kind":"and","operands":[..]}` -- conjunction of zero or more operands.
    And(Vec<Json>),
    /// `{"kind":"not","operands":[body]}` -- negation (the raw-sat solver goal).
    Not(Json),
}

impl IrFormula {
    /// Lower to the wire `Json` at the solver / report boundary. Byte-identical
    /// to the previously hand-rolled `json!` shapes.
    fn to_value(self) -> Json {
        match self {
            IrFormula::And(operands) => json!({ "kind": "and", "operands": operands }),
            IrFormula::Not(body) => json!({ "kind": "not", "operands": [body] }),
        }
    }

    /// Borrowing READ accessor: the top-level operands of an `and` node, or
    /// `None` when `node` is not a conjunction (any other head, or a malformed
    /// `and` without an operand array). Replaces the paired
    /// `get("kind") == "and"` + `get("operands").as_array()` dig with one typed
    /// read.
    fn and_operands(node: &Json) -> Option<&Vec<Json>> {
        if node.get("kind").and_then(|k| k.as_str()) != Some("and") {
            return None;
        }
        node.get("operands").and_then(|v| v.as_array())
    }
}

/// The boolean connective / quantifier at the head of an IR formula node, for
/// the READ side: classify a node's `kind` ONCE into a typed head instead of
/// re-stringly comparing `get("kind")` against connective spellings. Every
/// non-connective head (atomics, ctor terms, consts, `var`, `primitive`, ...)
/// is `None`, since this module treats those leaves opaquely.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Connective {
    And,
    Implies,
    Not,
    Forall,
    Exists,
}

impl Connective {
    fn of(node: &Json) -> Option<Connective> {
        match node.get("kind").and_then(|k| k.as_str())? {
            "and" => Some(Connective::And),
            "implies" => Some(Connective::Implies),
            "not" => Some(Connective::Not),
            "forall" => Some(Connective::Forall),
            "exists" => Some(Connective::Exists),
            _ => None,
        }
    }
}

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
    pub verification: Option<VerificationDetail>,
    /// The source locus (file/line/column) of the assertion this result is
    /// about, recovered from the contract memento's own `file`+`span`. Stamped
    /// by `verify_consistency` and threaded to the report row so an
    /// `unsatisfied` verdict can anchor an IDE diagnostic at the exact
    /// assertion instead of dropping the source. `None` when the contract
    /// memento carries no readable locus (fail-open: no false anchor).
    pub locus: Option<SourceLocus>,
    /// #4148: ambient vendor posts that matched a callsite but were dropped
    /// during specialization (open after substitution, etc.). Non-empty under
    /// declared deps means the warm path must degrade -- the vendor law never
    /// reached the solve. Empty is the only path to an un-degraded green.
    pub dropped_ambient_posts: Vec<DroppedAmbientPost>,
}

/// Typed replacement for the hand-rolled `verification` JSON on
/// [`ConsistencyResult`]. Serde is internally-tagged on `kind`, so together with
/// declaration-order fields and `skip_serializing_if` this serializes
/// BYTE-IDENTICALLY to the JSON shapes this module (and the effects boundary,
/// [`VerifyEffect::to_legacy_boundary`]) previously built by hand. That
/// byte-identity is load-bearing: the linked-bundle CID is computed over this
/// serialization. Each arm has a per-shape round-trip test
/// (`test_verification_detail_*_round_trip`) that pins the exact wire bytes.
///
/// Variant / `kind` mapping:
///   - [`VerificationDetail::Witness`]       -> `kind = "witness"`
///   - [`VerificationDetail::Solver`]        -> `kind = "consistency"`
///     (the symbolic consistency detail; the two conjoined-fact fields
///     `clientFactIr`/`vendorFactIr` are attached later by
///     [`attach_conjoined_facts`] and are omitted when absent)
///   - [`VerificationDetail::ProvenanceKind`] -> `kind = "consistency-provenance-kind"`
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum VerificationDetail {
    /// Execution-witness recompute detail. `witnessed`/`verdict`/`reason` are
    /// always present; `resolvedBy`/`outcomes`/`failed`/`failedTests` appear only
    /// on the resolved-package shapes (omitted on the undecidable / recompute-error
    /// shape), matching the three hand-rolled witness variants exactly.
    #[serde(rename = "witness")]
    Witness {
        witnessed: bool,
        verdict: String,
        #[serde(
            rename = "resolvedBy",
            default,
            skip_serializing_if = "Option::is_none"
        )]
        resolved_by: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        outcomes: Option<u64>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        failed: Option<u64>,
        #[serde(
            rename = "failedTests",
            default,
            skip_serializing_if = "Option::is_none"
        )]
        failed_tests: Option<Vec<String>>,
        reason: String,
    },
    /// Symbolic-solver consistency detail. `rawSolverVerdict`/`solverReason` are
    /// nullable-but-always-present (serialized as JSON `null` when absent, never
    /// dropped); `clientFactIr`/`vendorFactIr`/`vendorSwornContextIr` are the
    /// appended conjoined facts and ARE dropped when absent.
    ///
    /// `vendorFactIr` carries ONLY facts that actually entered the checked
    /// formula's conjunction (the ambient ground-callsite conjoin and the
    /// cross-proof vendor-spoken candidates) -- it answers "what did the
    /// solver see." `vendorSwornContextIr` carries `collect_vendor_sworn_facts`'s
    /// DISPLAY-ONLY same-callee sworn vectors, which are never conjoined into
    /// the solved obligation and carry no soundness weight; keeping them in a
    /// separate field means a vacuously-Discharged row (no participating vendor
    /// fact) can never be misread as "the vendor fact that resolved this."
    #[serde(rename = "consistency")]
    Solver {
        property: String,
        #[serde(rename = "checkedFormulaCid")]
        checked_formula_cid: String,
        #[serde(rename = "linkedPosts")]
        linked_posts: Json,
        #[serde(rename = "rawSolverVerdict")]
        raw_solver_verdict: Option<String>,
        #[serde(rename = "finalVerdict")]
        final_verdict: String,
        #[serde(rename = "solverReason")]
        solver_reason: Option<String>,
        #[serde(rename = "solverInvocations")]
        solver_invocations: Json,
        #[serde(
            rename = "clientFactIr",
            default,
            skip_serializing_if = "Option::is_none"
        )]
        client_fact_ir: Option<Json>,
        #[serde(
            rename = "vendorFactIr",
            default,
            skip_serializing_if = "Option::is_none"
        )]
        vendor_fact_ir: Option<Json>,
        #[serde(
            rename = "vendorSwornContextIr",
            default,
            skip_serializing_if = "Option::is_none"
        )]
        vendor_sworn_context_ir: Option<Json>,
    },
    /// Provenance-KIND refusal detail (a custom-witness / panic-callsite contract
    /// that carried the wrong `proofirProvenance.warrants[].kind`).
    #[serde(rename = "consistency-provenance-kind")]
    ProvenanceKind {
        property: String,
        #[serde(rename = "finalVerdict")]
        final_verdict: String,
        reason: String,
    },
}

impl VerificationDetail {
    /// Lower to the wire JSON. This is the boundary back to the report stage,
    /// which still threads `Option<Json>`; the serialization is byte-identical to
    /// the shape this type replaced.
    pub fn to_json(&self) -> Json {
        serde_json::to_value(self).expect("VerificationDetail serializes infallibly")
    }
}

/// Lift the effects boundary's legacy JSON verification (still `Option<Json>` at
/// [`VerifyEffect::to_legacy_boundary`]) into the typed detail. The boundary only
/// ever emits the `witness` and `consistency-provenance-kind` shapes, both of
/// which round-trip through this type; a schema drift panics LOUD rather than
/// silently dropping the detail.
fn verification_from_boundary(v: Option<Json>) -> Option<VerificationDetail> {
    v.map(|j| {
        serde_json::from_value(j)
            .expect("effects boundary verification must match the VerificationDetail schema")
    })
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

/// The pieces of a callsite-keyed group key, split ONCE at construction.
#[derive(Debug, Clone, Copy)]
struct EufParts<'a> {
    /// Scope prefix: everything before the FINAL `::` of the pre-`#euf#`
    /// segment. When that segment carries no `::`, the whole segment is the
    /// scope (mirrors the prior `ambient_ground_callsite_scope` unwrap_or).
    scope: &'a str,
    /// Callee segment: the piece after the final `::` of the pre-`#euf#`
    /// prefix (the whole prefix when it carries no `::`).
    callee: &'a str,
    /// Everything AFTER the `#euf#` marker: `<cid>(args)::assertion`. The
    /// content-keyed callsite CID plus its `::`-suffixed obligation role.
    euf_cid: &'a str,
}

/// A parsed view over a consistency GROUP KEY (a `property_name`). The
/// canonical callsite-keyed spelling is
/// `<scope>::<callee>#euf#<cid>(args)::assertion`; a plain (bare) key carries
/// no `#euf#` marker. Historically the bucketing map, the cross-proof conjoin
/// gate, the ambient scope, and the standalone-vacuity guard each re-split this
/// string with ad-hoc `.contains`/`split_once`/`rsplit_once`. `EufCoordinate`
/// performs that split exactly ONCE (at `parse`) and exposes the fields; it
/// BORROWS the source string and `Display`s back the exact same bytes, so the
/// wire/property string stays byte-identical.
#[derive(Debug, Clone, Copy)]
struct EufCoordinate<'a> {
    raw: &'a str,
    /// `Some` iff the key is callsite-keyed (the `#euf#` marker is present).
    parts: Option<EufParts<'a>>,
}

impl<'a> EufCoordinate<'a> {
    /// Split the group key once. `split_once("#euf#")` is `Some` exactly when
    /// the marker is present, so `is_callsite_keyed()` is byte-for-byte the old
    /// `raw.contains("#euf#")`. The prefix is then split on its final `::` into
    /// `(scope, callee)`, falling back to `(prefix, prefix)` when it carries no
    /// separator -- identical to the old `rsplit_once(...).unwrap_or(prefix)`.
    fn parse(raw: &'a str) -> Self {
        let parts = raw.split_once("#euf#").map(|(prefix, suffix)| {
            let (scope, callee) = prefix.rsplit_once("::").unwrap_or((prefix, prefix));
            EufParts {
                scope,
                callee,
                euf_cid: suffix,
            }
        });
        EufCoordinate { raw, parts }
    }

    /// True iff the key carries the `#euf#` callsite marker. This is the gate
    /// for cross-proof conjoin, ambient-forall travel, and ground-fact travel.
    fn is_callsite_keyed(&self) -> bool {
        self.parts.is_some()
    }

    /// The ambient scope of a callsite-keyed key (the scope prefix, or the
    /// whole pre-`#euf#` segment when it has no `::`). `None` for a bare key.
    /// Owned to match the prior `ambient_ground_callsite_scope` return type.
    fn scope(&self) -> Option<String> {
        self.parts.map(|p| p.scope.to_string())
    }

    /// The callee segment of a callsite-keyed key; `None` for a bare key.
    #[allow(dead_code)]
    fn callee(&self) -> Option<&'a str> {
        self.parts.map(|p| p.callee)
    }

    /// The `#euf#` CID-plus-role suffix of a callsite-keyed key; `None` for a
    /// bare key.
    #[allow(dead_code)]
    fn euf_cid(&self) -> Option<&'a str> {
        self.parts.map(|p| p.euf_cid)
    }
}

impl std::fmt::Display for EufCoordinate<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.raw)
    }
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
        Some(post) => IrFormula::And(vec![inv, post]).to_value(),
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

/// Construction-closure module for dual structural equality (#4141).
///
/// `DualGroundEqFace` fields are **private to this submodule**. Even the
/// parent `consistency` module cannot form a struct literal -- private fields
/// are inaccessible outside the defining module. The sole door is
/// [`dual_ground_eq_face::DualGroundEqFace::try_from_atomic`].
///
/// Compile-time proof: any attempt in the parent like
/// `DualGroundEqFace { term: ..., value: ... }` fails with E0451 (private
/// field). Wrong orientation (py.eq as free equality without term+value) is
/// therefore not expressible as a `DualGroundEqFace` value except through the
/// door's checks.
mod dual_ground_eq_face {
    use serde_json::Value as Json;

    /// Ground **term** half of a dual structural face (callsite / data ctor tree).
    /// Field is private to this module -- not constructible from the parent.
    #[derive(Clone, Copy, Debug)]
    struct DualTerm<'a>(&'a Json);

    /// Ground **value** half of a dual structural face (const / data value).
    /// Field is private to this module -- not constructible from the parent.
    #[derive(Clone, Copy, Debug)]
    struct DualValue<'a>(&'a Json);

    /// The **only** type-system door for dual structural equality.
    ///
    /// Carries an oriented pair `term ≃ value`. There is no constructor that takes
    /// a bare atom name or that asserts reflexivity (`x ≃ x`). Construction is
    /// [`DualGroundEqFace::try_from_atomic`] only:
    /// 1. atomic name is IR `=` **or** Python `py.eq` (assert `==`);
    /// 2. [`super::ground_term_const_equality`] orients **term + ground value**.
    ///
    /// # Why this cuts NaN off at the type system
    ///
    /// Python `==` is not SMT `=` (`nan != nan`). Symbolic comparison therefore
    /// emits `py.eq`, not IR `=`. We allow `py.eq` **only** as a dual-face atom
    /// name inside this type -- never as a general rewrite to reflexive `=`.
    /// `DualGroundEqFace` cannot represent `py.eq(x, x)` (does not orient).
    /// Callers that need dual injectivity take `DualGroundEqFace`; they cannot
    /// pass an un-oriented formula without going through `try_from_atomic`.
    ///
    /// Arithmetic operator ctors stay non-values via `is_const_value` (#3924).
    ///
    /// # Construction closure (#4141)
    ///
    /// Fields are private to this submodule. Same-module (parent) code cannot
    /// bypass `try_from_atomic` with a struct literal -- that is a compile
    /// error (E0451), not a runtime check.
    #[derive(Clone, Copy, Debug)]
    pub(super) struct DualGroundEqFace<'a> {
        term: DualTerm<'a>,
        value: DualValue<'a>,
    }

    impl<'a> DualGroundEqFace<'a> {
        /// Sole construction site for dual structural equality faces.
        pub(super) fn try_from_atomic(node: &'a Json) -> Option<Self> {
            if node.get("kind").and_then(|k| k.as_str()) != Some("atomic") {
                return None;
            }
            let name = node.get("name").and_then(|v| v.as_str())?;
            // Dual-face atom names only -- not a public "is equality?" predicate.
            if !matches!(name, "=" | "py.eq") {
                return None;
            }
            let (term, value) = super::ground_term_const_equality(node)?;
            Some(Self {
                term: DualTerm(term),
                value: DualValue(value),
            })
        }

        /// Oriented ground term half (callsite / data ctor tree).
        pub(super) fn term_json(self) -> &'a Json {
            self.term.0
        }

        /// Oriented ground value half (const / data value).
        pub(super) fn value_json(self) -> &'a Json {
            self.value.0
        }
    }
}

use dual_ground_eq_face::DualGroundEqFace;

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
        Some("atomic") => {
            let face = DualGroundEqFace::try_from_atomic(node)?;
            record_ground_equality(face, equalities)
        }
        _ => None,
    }
}

fn record_ground_equality(
    face: DualGroundEqFace<'_>,
    equalities: &mut std::collections::BTreeMap<String, (String, String, String)>,
) -> Option<String> {
    // Federate platform-width primitive sorts BEFORE keying: width is a range
    // REFINEMENT, not a sort distinction, so `0:i128` and `0:u128` are the SAME
    // value. Without this they JCS-hash differently and a callsite asserted equal
    // to both is FALSELY reported contradictory -- a fake refutation (the mirror
    // of a fake discharge). The solver path already federates via
    // sort_translate; this closes the same leak in the structural pre-check.
    // Only the KEY federates; the display keeps the original width for audit.
    let term = face.term_json();
    let value = face.value_json();
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

/// Ground *data value* for structural equality.
///
/// Primitive consts always count. Ground **data** constructor trees
/// (`tuple(0,0)`, `array(…)`, nested data ctors) also count so component-wise
/// injectivity is free via distinct JCS keys: `tuple(0,0) ≠ tuple(1,1)` without
/// SMT ADT theory.
///
/// Operator / language ctors (`+`, `-`, `py.subscript`, …) are **not** values
/// even when fully ground: `call:A(5) == 6` and body dig `call:A(5) == +(5,1)`
/// must NOT structural-refute a truthful binop seed. #3924 widened this
/// predicate past data ctors and falsely refuted truthful arithmetic body digs
/// (corpus `binop_return` truthful→unsat). Callsites (`call:…`, `await`) stay
/// terms, not values — leaving them out keeps `ground_term_const_equality`
/// oriented (term, value).
fn is_const_value(node: &Json) -> bool {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("const") => true,
        Some("ctor") => {
            let name = node.get("name").and_then(|n| n.as_str()).unwrap_or("");
            if !is_ground_data_ctor_name(name) {
                return false;
            }
            node.get("args")
                .and_then(|v| v.as_array())
                .is_some_and(|args| args.iter().all(is_const_value))
        }
        _ => false,
    }
}

/// Data constructors that are structural *values* (not operators / callsites).
///
/// Whitelist is intentional: any non-data ground ctor (`+`, `*`, `py.attr`, …)
/// must fall through to SMT so theory can prove `+(5,1) == 6`.
fn is_ground_data_ctor_name(name: &str) -> bool {
    matches!(
        name,
        "tuple"
            | "array"
            | "None"
            | "python:dict"
            | "python:dict_entry"
            | "python:set"
            | "python:frozenset"
            | "python:bytes"
            | "python:bytearray"
            | "python:list"
            | "python:tuple"
    )
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

/// Kit oracle RPC method: the ONE resolve door for discharge.
///
/// Conceptual `WitnessPool::get(packageCid)` over the wire — kit returns
/// `.witness` bundle bytes (`body_b64`). Rust never trusts a kit verdict
/// string; verify is always [`package_outcome`] (blake3 vs packageCid +
/// committed outcomes). Do not invent a `WitnessPool` struct: the pool face
/// is realized by this RPC + Rust seal.
const ORACLE_RESOLVE_METHOD: &str = "sugar.plugin.resolve_witness";

#[derive(Debug, Clone)]
struct WitnessResolver {
    argv: Vec<String>,
    working_dir: PathBuf,
    method: String,
}

/// Typed witness-discharge context (#3809 witness-as-verb).
///
/// **CID-idempotency (protocol law):** a witness `ObligationVerdict` is a pure
/// function of content-addressed inputs (`packageCid` on the claim + contract
/// identity + resolver body bytes). Two paths that feed the same inputs MUST
/// return byte-identical verdicts; disagreement is a red test, not a
/// "double-entry" hazard.
///
/// **Trust boundary:** resolve = kit oracle RPC ([`ORACLE_RESOLVE_METHOD`]);
/// verify = Rust [`package_outcome`]. Discharge is speak-packageCid-to-oracle
/// → seal outcome. One resolve door only.
///
/// **Step 3:** `SUGAR_WITNESS_PROJECT_DIR` / `SUGAR_WITNESS_RESOLVERS` are
/// retired as a live config channel. This struct is the sole config surface
/// for project_dir + resolvers (CLI fills it via `WitnessDischargeConfig`).
/// Package CID stays on the claim (`evidence.certificate.proofData`).
///
/// Resolvers are **client-fed only** (#3809 PR series, cut #6): faces (CLI
/// `discharge_config`, LSP) load lift manifests and set [`Self::resolvers`].
/// Solve never `read_dir(.sugar/lift)` for discovery.
#[derive(Debug, Clone, Default)]
pub struct WitnessDischargeContext {
    /// Project root for package resolve (typed only; no env fallback).
    pub project_dir: Option<PathBuf>,
    /// Kit resolve plugins (typed only; no env fallback).
    pub resolvers: Vec<WitnessResolverSpec>,
}

/// One kit oracle that answers [`ORACLE_RESOLVE_METHOD`]
/// (`sugar.plugin.resolve_witness`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WitnessResolverSpec {
    pub argv: Vec<String>,
    pub working_dir: PathBuf,
    pub method: String,
}

impl WitnessResolverSpec {
    pub fn new(
        argv: Vec<String>,
        working_dir: impl Into<PathBuf>,
        method: impl Into<String>,
    ) -> Self {
        Self {
            argv,
            working_dir: working_dir.into(),
            method: method.into(),
        }
    }
}

impl WitnessDischargeContext {
    /// Project dir from typed config only (step 3: no env fallback).
    pub fn project_dir_resolved(&self) -> Option<PathBuf> {
        self.project_dir
            .as_ref()
            .filter(|p| !p.as_os_str().is_empty())
            .cloned()
    }

    fn typed_resolvers(&self) -> Vec<WitnessResolver> {
        self.resolvers
            .iter()
            .filter(|r| !r.argv.is_empty())
            .map(|r| WitnessResolver {
                argv: r.argv.clone(),
                working_dir: r.working_dir.clone(),
                method: if r.method.is_empty() {
                    ORACLE_RESOLVE_METHOD.to_string()
                } else {
                    r.method.clone()
                },
            })
            .collect()
    }
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
/// authenticated package bytes, not from the kit's verdict string.
///
/// **One door (step 2):** resolution goes only through the kit oracle RPC
/// ([`ORACLE_RESOLVE_METHOD`] via [`oracle_resolve_body`]); verification is
/// always Rust [`package_outcome`] (blake3 vs packageCid + committed outcomes).
/// Never kit verdict strings. Returns None when there is no custom witness
/// (caller falls through to symbolic solving). FAIL-CLOSED: missing config /
/// malformed schema / unparseable bytes is Undecidable or Unsatisfied, never
/// Discharged.
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
        verification: Some(VerificationDetail::Witness {
            witnessed: false,
            verdict: ObligationVerdict::Undecidable.as_str().to_string(),
            resolved_by: None,
            outcomes: None,
            failed: None,
            failed_tests: None,
            reason,
        }),
        dropped_ambient_posts: Vec::new(),
    };
    let tool = evidence
        .get("certificate")
        .and_then(|c| c.get("tool"))
        .and_then(|t| t.as_str())
        .unwrap_or("");
    // Typed WitnessDischargeContext only (step 3: env config channel retired).
    let project = match active_witness_context().project_dir_resolved() {
        Some(p) => p,
        None => {
            return Some(undecidable(
                "custom witness present but witness project_dir unset \
                 (typed WitnessDischargeContext required; fail-closed)"
                    .into(),
            ))
        }
    };

    let claim = match witness_package_claim(evidence, tool) {
        Ok(c) => c,
        Err(e) => return Some(undecidable(e)),
    };
    let resolvers = find_witness_resolvers();
    if resolvers.is_empty() {
        return Some(undecidable(
            "custom witness package present but no resolve_witness_command configured \
             (fail-closed; client must feed WitnessDischargeContext.resolvers)"
                .to_string(),
        ));
    }
    // ONE resolve door: kit oracle RPC → Rust package_outcome. No side path.
    Some(seal_witness_package_outcome(
        witness_package_via_oracle(&resolvers, &project, &claim),
        contract_cid,
        property_name,
    ))
}

/// Mint a [`ConsistencyResult`] from the oracle+verify outcome (or recompute
/// error). Shared by the discharge arm so arm-path and explicit-oracle-path
/// cannot drift.
fn seal_witness_package_outcome(
    outcome: Result<WitnessPackageOutcome, String>,
    contract_cid: String,
    property_name: String,
) -> ConsistencyResult {
    match outcome {
        Ok(outcome) if outcome.failed == 0 => {
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
                verification: Some(VerificationDetail::Witness {
                    witnessed: true,
                    verdict: ObligationVerdict::Discharged.as_str().to_string(),
                    resolved_by: Some(outcome.resolved_by.clone()),
                    outcomes: Some(outcome.count as u64),
                    failed: Some(outcome.failed as u64),
                    failed_tests: None,
                    reason,
                }),
                dropped_ambient_posts: Vec::new(),
            }
        }
        Ok(outcome) => {
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
                verification: verification_from_boundary(boundary.verification),
                dropped_ambient_posts: Vec::new(),
            }
        }
        Err(e) => {
            let effect = VerifyEffect::UnwitnessedDischarge {
                contract_cid: contract_cid.clone(),
                property_name: property_name.clone(),
                ground: WitnessDischargeGround::PackageRecompute { error: e },
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
                verification: verification_from_boundary(boundary.verification),
                dropped_ambient_posts: Vec::new(),
            }
        }
    }
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

// Thread-local typed discharge context: set for the duration of
// `verify_consistency_from_indexes` so deep call sites (par_iter group
// solve → `try_witness_discharge`) see the same session config without
// threading every arg through private helpers.
thread_local! {
    static ACTIVE_WITNESS_CTX: std::cell::RefCell<WitnessDischargeContext> =
        std::cell::RefCell::new(WitnessDischargeContext {
            project_dir: None,
            resolvers: Vec::new(),
        });
}

struct WitnessCtxGuard {
    prev: WitnessDischargeContext,
}

impl WitnessCtxGuard {
    fn enter(ctx: &WitnessDischargeContext) -> Self {
        let prev =
            ACTIVE_WITNESS_CTX.with(|c| std::mem::replace(&mut *c.borrow_mut(), ctx.clone()));
        Self { prev }
    }
}

impl Drop for WitnessCtxGuard {
    fn drop(&mut self) {
        let prev = std::mem::take(&mut self.prev);
        ACTIVE_WITNESS_CTX.with(|c| *c.borrow_mut() = prev);
    }
}

fn active_witness_context() -> WitnessDischargeContext {
    ACTIVE_WITNESS_CTX.with(|c| c.borrow().clone())
}

/// Scope membership from memento locus metadata only (#3809 cut #5).
/// Never `Path::exists`. Relative loci are in-scope; absolute loci must be
/// under `scope_root` by path prefix.
fn locus_in_scope(scope_root: &Path, file: &str) -> bool {
    let p = Path::new(file);
    if p.is_relative() {
        return true;
    }
    p.starts_with(scope_root)
}

/// Client-fed resolvers only (#3809 cut #6). Never `read_dir(.sugar/lift)`.
fn find_witness_resolvers() -> Vec<WitnessResolver> {
    active_witness_context().typed_resolvers()
}

/// Speak `packageCid` to the kit oracle (resolve bytes) then Rust-verify
/// ([`package_outcome`]). The only discharge resolve+verify composition —
/// no parallel route that seals a verdict from kit strings or raw FS reads.
fn witness_package_via_oracle(
    resolvers: &[WitnessResolver],
    project_root: &Path,
    claim: &WitnessPackageClaim,
) -> Result<WitnessPackageOutcome, String> {
    let mut mismatches = Vec::new();
    let mut errors = Vec::new();
    // packageCid is the pool key (conceptual WitnessPool::get).
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
        match oracle_resolve_body(resolver, project_root, &memento) {
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

/// **ONE resolve door:** spawn the kit oracle and call
/// [`ORACLE_RESOLVE_METHOD`] (`sugar.plugin.resolve_witness`).
///
/// Returns `(resolved_by, body_bytes)` — CONTENT only, never a verdict.
/// Callers must run [`package_outcome`] (blake3 vs packageCid) themselves.
/// Warm FS=0: package file lookup lives inside the kit when `package_dir` is
/// staged; this function does not `read_dir` the project for resolvers.
fn oracle_resolve_body(
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
    // Force the oracle method: discharge resolve is ONE door, not a free-form RPC.
    let method = if resolver.method.is_empty() {
        ORACLE_RESOLVE_METHOD
    } else {
        resolver.method.as_str()
    };
    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
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

/// Rust VERIFY half of the trust boundary: blake3(bytes) vs claim.packageCid,
/// then seal committed per-test `outcome` fields. Never trusts kit verdict
/// strings. Kit only RESOLVES; this is the only path that mints pass/fail counts.
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
        verification: verification_from_boundary(boundary.verification),
        dropped_ambient_posts: Vec::new(),
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
    if let Some(operands) = IrFormula::and_operands(&formula) {
        return operands.clone();
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
        IrFormula::And(operands).to_value(),
        collapsed_same_kind_duplicate,
    )
}

fn linked_posts_to_json(linked_posts: &[LinkedPostInstance]) -> Json {
    Json::Array(
        linked_posts
            .iter()
            .map(|p| {
                json!({
                    "sourceSymbol": &p.binding.source_symbol,
                    "targetContractCid": &p.binding.target_cid,
                    "targetProofCid": &p.binding.target_proof_cid,
                    "formals": &p.binding.formals,
                    "outBinding": &p.binding.out_binding,
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
    vendor_sworn_context: &[Json],
) {
    let Some(VerificationDetail::Solver {
        client_fact_ir,
        vendor_fact_ir,
        vendor_sworn_context_ir,
        ..
    }) = result.verification.as_mut()
    else {
        return;
    };
    *client_fact_ir = Some(client_fact.clone());
    if !vendor_facts.is_empty() {
        *vendor_fact_ir = Some(Json::Array(vendor_facts.to_vec()));
    }
    if !vendor_sworn_context.is_empty() {
        *vendor_sworn_context_ir = Some(Json::Array(vendor_sworn_context.to_vec()));
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
) -> VerificationDetail {
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
    VerificationDetail::Solver {
        property: property_name.to_string(),
        checked_formula_cid,
        linked_posts: linked_posts_to_json(linked_posts),
        raw_solver_verdict: raw_verdict.map(|v| v.as_str().to_string()),
        final_verdict: final_verdict.as_str().to_string(),
        solver_reason: solver_reason.map(|r| r.to_string()),
        solver_invocations: solver_invocations_to_json(invs),
        client_fact_ir: None,
        vendor_fact_ir: None,
        vendor_sworn_context_ir: None,
    }
}

/// Count the number of independent top-level atomic constraints in `inv`.
/// An `and([a, b, ...])` contributes its operand count; any other shape
/// (bare atomic, forall, implies, ctor equality, etc.) contributes 1.
/// Used to gate the consistency-SAT check: a lone constraint with no sibling
/// is trivially satisfiable (any uninterpreted callsite satisfies it) and must
/// NOT count as a substantive discharge — there is nothing to contradict it.
fn count_top_level_constraints(inv: &Json) -> usize {
    IrFormula::and_operands(inv).map(|a| a.len()).unwrap_or(1)
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
            dropped_ambient_posts: Vec::new(),
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
            dropped_ambient_posts: Vec::new(),
        };
    }
    let raw_sat_goal = IrFormula::Not(inv.clone()).to_value();
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
        dropped_ambient_posts: Vec::new(),
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
        if Connective::of(op) != Some(Connective::Forall) {
            return;
        }
        if !formula_is_closed(op, &mut Vec::new()) {
            debug!(
                "verifier/ambient: open universal template collected; only closed instances may travel"
            );
        }
        out.push(op.clone());
    };
    match Connective::of(inv) {
        Some(Connective::Forall) => consider(inv),
        Some(Connective::And) => {
            if let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    collect_ambient_foralls(op, out);
                }
            }
        }
        _ => {}
    }
}

/// Attribution of a collected ground callsite fact within the ambient pool.
///
/// A ground callsite equality either arrived from an IMPORTED pool member (a
/// staged `.proof` / vendor-role utterance, identified by its source memento
/// cid) or was extracted from the CONSUMER's OWN local formula -- its solved
/// obligation, or its own asserted fact -- which carries no pool identity.
/// This retires the `"<client>"` / `"<current-obligation>"` sentinel strings:
/// an own-origin fact has no cid, so it can never be excluded as "its own
/// vendor" and never collides with a real memento cid in the excluded set.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Attribution {
    /// The consumer's own locally-extracted fact -- no imported pool identity.
    OwnOrigin,
    /// An imported pool member, keyed by its source memento cid.
    Imported(String),
}

impl Attribution {
    /// The source memento cid when this fact was imported from the pool; `None`
    /// for a consumer-own fact (which therefore never matches an excluded cid).
    fn source_cid(&self) -> Option<&str> {
        match self {
            Attribution::OwnOrigin => None,
            Attribution::Imported(cid) => Some(cid.as_str()),
        }
    }
}

/// The canonical join key for a ground callsite fact: the JCS canonicalization
/// of a `call:*` ctor term (args included -- `call:len(100)` and `call:len(200)`
/// are distinct keys). A fact about `call:len(200)` never joins a payload whose
/// wanted set is only `call:len(100)` -- exact call-term identity, not callee
/// name (#3884). Scope is a secondary gate only for Stated peer claims (so a
/// good/bad twin pair under different prefixes can still sit in one pool and
/// receive opposite verdicts); Derived testimony travels pool-wide on TermKey
/// alone. The wrapper carries `Eq`/`Ord`/`Hash` and nothing else may be compared
/// against it. `#[serde(transparent)]`: the wire form is the bare string, so no
/// artifact byte changes.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
struct TermKey(String);

impl TermKey {
    fn as_str(&self) -> &str {
        &self.0
    }
}

/// The ambient scope prefix of a callsite-keyed obligation (the segment before
/// the final `::`, or the whole pre-`#euf#` segment). Finite-replay ground facts
/// travel only within a matching scope, so the wrapper carries `Eq`/`Ord` for
/// that guard. `#[serde(transparent)]`: the wire form is the bare string.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
struct Scope(String);

#[derive(Debug, Clone)]
struct AmbientGroundCallsiteFact {
    attribution: Attribution,
    /// Used for Stated peer-claim scope gating; Derived ignores this at join.
    scope: Option<Scope>,
    term_key: TermKey,
    witness_key: AmbientFactWitnessKey,
    fact: Json,
}

/// Collect closed ground facts about concrete callsite terms. A literal-domain
/// loop replay may emit `call:g(3) == 1` rather than a universal. That fact
/// constrains sibling `#euf#` obligations about the SAME concrete call term
/// (`TermKey` = full JCS of the `call:*` ctor, args included -- never the bare
/// callee name). Derived testimony joins pool-wide on that key; Stated peer
/// claims stay same-scope so a good/bad twin pair can coexist (#3884). We collect
/// only ground equalities whose subject is a `call:*` ctor; local variables and
/// non-call helper ctors never travel.
fn collect_ambient_ground_callsite_facts(
    inv: &Json,
    source: &Attribution,
    scope: &Option<Scope>,
    provenance_kind: ProofIrProvenanceKind,
    out: &mut Vec<AmbientGroundCallsiteFact>,
) {
    match inv.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => {}
        Some("and") => {
            if let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    collect_ambient_ground_callsite_facts(op, source, scope, provenance_kind, out);
                }
            }
        }
        Some("implies") => {
            let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) else {
                return;
            };
            if ops.len() == 2 && eval_ground_bool(&ops[0]) == Some(true) {
                collect_ambient_ground_callsite_facts(&ops[1], source, scope, provenance_kind, out);
            }
        }
        Some("atomic") => {
            let Some(face) = DualGroundEqFace::try_from_atomic(inv) else {
                return;
            };
            let Some(term_key) = ground_callsite_term_key(face.term_json()) else {
                return;
            };
            out.push(AmbientGroundCallsiteFact {
                attribution: source.clone(),
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
    scope: &Option<Scope>,
    provenance_kind: ProofIrProvenanceKind,
) -> std::collections::BTreeSet<AmbientFactWitnessKey> {
    let mut facts = Vec::new();
    collect_ambient_ground_callsite_facts(
        inv,
        &Attribution::OwnOrigin,
        scope,
        provenance_kind,
        &mut facts,
    );
    facts.into_iter().map(|fact| fact.witness_key).collect()
}

fn is_ground_callsite_fact_formula(formula: &Json) -> bool {
    let Some(face) = DualGroundEqFace::try_from_atomic(formula) else {
        return false;
    };
    ground_callsite_term_key(face.term_json()).is_some()
}

fn is_derived_ground_callsite_support(
    property_name: &str,
    candidate: &ConsistencyCandidate,
    inv: &Json,
) -> bool {
    if candidate.provenance_kind != ProofIrProvenanceKind::Derived
        || !EufCoordinate::parse(property_name).is_callsite_keyed()
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
        &Attribution::OwnOrigin,
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
        if fact
            .attribution
            .source_cid()
            .is_some_and(|sc| excluded_source_cids.iter().any(|c| c == sc))
        {
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

fn ground_callsite_term_key(term: &Json) -> Option<TermKey> {
    if !is_callsite_ctor_term(term) {
        return None;
    }
    libsugar::canonical::json_jcs(&federate_primitive_sorts(term))
        .ok()
        .map(TermKey)
}

fn ambient_ground_callsite_scope(property_name: &str) -> Option<Scope> {
    EufCoordinate::parse(property_name).scope().map(Scope)
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
    let callsite_keyed = EufCoordinate::parse(property_name).is_callsite_keyed();
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
    IrFormula::And(operands).to_value()
}

/// Conjoin closed ground callsite facts into matching callsite-keyed obligations.
/// This is the finite-replay twin of `with_ambient_foralls`: a replayed literal
/// loop has already named the concrete calls (`call:g(0)`, `call:g(1)`, ...), so
/// only facts whose subject term is byte-identical (exact `TermKey`) to a term
/// that appears in the current obligation are relevant. Bare names still receive
/// nothing. #3884 join rules:
///   1. Exact call-term identity (full ctor with args) -- never callee name.
///   2. Derived testimony travels pool-wide on that key (independent-KIND
///      witness across property prefixes).
///   3. Stated peer claims join only within the same ambient scope, so a
///      good/bad twin pair under different prefixes can keep opposite verdicts.
fn with_ambient_ground_callsite_facts(
    inv: Json,
    property_name: &str,
    ambient: &[AmbientGroundCallsiteFact],
    excluded_source_cids: &[String],
    current_ground_witnesses: &std::collections::BTreeSet<AmbientFactWitnessKey>,
) -> (Json, bool, Vec<Json>) {
    if ambient.is_empty() || !EufCoordinate::parse(property_name).is_callsite_keyed() {
        return (inv, false, Vec::new());
    }

    let mut callsites = Vec::new();
    collect_unquantified_ctor_terms(&inv, &mut callsites);
    let wanted: std::collections::BTreeSet<TermKey> = callsites
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
        if fact.attribution.source_cid().is_some_and(|sc| {
            excluded_source_cids
                .iter()
                .any(|source_cid| source_cid == sc)
        }) {
            continue;
        }
        // Exact call-term identity -- never callee name, never first-writer among
        // different args (wanted is the full TermKey set of this obligation).
        if !wanted.contains(&fact.term_key) {
            continue;
        }
        // Derived travels pool-wide; Stated peers stay same-scope (#3884).
        let is_derived = fact.witness_key.provenance_kind == ProofIrProvenanceKind::Derived;
        if !is_derived
            && fact
                .scope
                .as_ref()
                .is_some_and(|scope| Some(scope) != obligation_scope.as_ref())
        {
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
        IrFormula::And(operands).to_value(),
        skipped_same_kind_duplicate,
        vendor_facts,
    )
}

/// The shared binding head carried by both an [`AmbientPost`] (the vendor post
/// gathered from one bridge) and every [`LinkedPostInstance`] it specializes
/// into. These five fields were duplicated field-for-field across the two
/// structs and always copied together at instantiation; naming the product once
/// makes the copy a single `binding.clone()` and keeps the two shapes from
/// drifting. Purely internal — no field is serialized via derive, so
/// `linked_posts_to_json` still emits the same wire keys.
#[derive(Debug, Clone)]
struct BridgeBinding {
    source_symbol: String,
    target_cid: String,
    target_proof_cid: Option<String>,
    formals: Vec<String>,
    out_binding: String,
}

/// Why an ambient vendor post was not conjoined into the obligation (#4148).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DroppedAmbientPostReason {
    /// Specialization left free variables -- `formula_is_closed` rejected it.
    OpenAfterSpecialization,
    /// Callsite subject was an opaque uninterpreted call (not a usable match).
    OpaqueCallSubject,
    /// Consumer call term failed to decode as a ctor (fell through to atomic).
    CallTermDecodeFailed,
}

/// One ambient vendor post that matched a callsite but did not enter `linkedPosts`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DroppedAmbientPost {
    pub source_symbol: String,
    pub target_cid: String,
    pub reason: DroppedAmbientPostReason,
    /// Compact spelling of the specialized (or attempted) post for diagnostics.
    pub spelling: String,
}

impl DroppedAmbientPostReason {
    pub fn label(&self) -> &'static str {
        match self {
            DroppedAmbientPostReason::OpenAfterSpecialization => "open-after-specialization",
            DroppedAmbientPostReason::OpaqueCallSubject => "opaque-call-subject",
            DroppedAmbientPostReason::CallTermDecodeFailed => "call-term-decode-failed",
        }
    }
}

/// Partition of ambient-post specialization (#4148 type fence).
///
/// Every specialization step returns this shape -- not a silently-filtered
/// `Vec`. Callers that proceed to a green verdict while `dropped` is non-empty
/// must do so explicitly; the warm-overlay law forbids that under declared deps.
#[derive(Debug, Clone, Default)]
struct AmbientPostInstances {
    kept: Vec<LinkedPostInstance>,
    dropped: Vec<DroppedAmbientPost>,
}

#[derive(Debug, Clone)]
struct AmbientPost {
    binding: BridgeBinding,
    post: Json,
}

#[derive(Debug, Clone)]
struct LinkedPostInstance {
    binding: BridgeBinding,
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
            binding: BridgeBinding {
                source_symbol,
                target_cid: target_cid.to_string(),
                target_proof_cid,
                formals,
                out_binding,
            },
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
        .kept
        .into_iter()
        .map(|p| p.instantiated_post)
        .collect()
}

fn linked_ambient_post_instances_for_inv(
    inv: &Json,
    ambient: &[AmbientPost],
) -> AmbientPostInstances {
    if ambient.is_empty() {
        return AmbientPostInstances::default();
    }
    let mut callsites = Vec::new();
    collect_unquantified_ctor_terms(inv, &mut callsites);
    if callsites.is_empty() {
        return AmbientPostInstances::default();
    }

    let mut kept = Vec::new();
    let mut dropped = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for callsite in &callsites {
        let Some(name) = callsite.get("name").and_then(|v| v.as_str()) else {
            // Call term did not decode as a named ctor -- record if ambient
            // posts exist that we intended to apply (subject opaque / decode fail).
            if !ambient.is_empty() {
                dropped.push(DroppedAmbientPost {
                    source_symbol: "<unknown-call>".to_string(),
                    target_cid: String::new(),
                    reason: DroppedAmbientPostReason::CallTermDecodeFailed,
                    spelling: compact_json(callsite),
                });
            }
            continue;
        };
        let Some(args) = callsite.get("args").and_then(|v| v.as_array()) else {
            dropped.push(DroppedAmbientPost {
                source_symbol: name.to_string(),
                target_cid: String::new(),
                reason: DroppedAmbientPostReason::CallTermDecodeFailed,
                spelling: compact_json(callsite),
            });
            continue;
        };
        for post in ambient.iter().filter(|post| {
            let bare = name
                .strip_prefix("call:")
                .or_else(|| name.strip_prefix("method:"))
                .unwrap_or(name);
            (post.binding.source_symbol == name || post.binding.source_symbol == bare)
                && post.binding.formals.len() == args.len()
        }) {
            let mut instance = post.post.clone();
            for (formal, actual) in post.binding.formals.iter().zip(args.iter()) {
                instance = crate::instantiate::substitute_formula_pub(&instance, formal, actual);
            }
            instance = crate::instantiate::substitute_formula_pub(
                &instance,
                &post.binding.out_binding,
                callsite,
            );
            if !formula_is_closed(&instance, &mut Vec::new()) {
                // #4148: LOUD drop -- never silently skip an open specialized post.
                tracing::warn!(
                    source_symbol = %post.binding.source_symbol,
                    target_cid = %post.binding.target_cid,
                    "verifier/linker: dropped open specialized vendor post (not closed after specialization)"
                );
                dropped.push(DroppedAmbientPost {
                    source_symbol: post.binding.source_symbol.clone(),
                    target_cid: post.binding.target_cid.clone(),
                    reason: DroppedAmbientPostReason::OpenAfterSpecialization,
                    spelling: compact_json(&instance),
                });
                continue;
            }
            let key = libsugar::canonical::json_jcs(&instance)
                .unwrap_or_else(|_| serde_json::to_string(&instance).unwrap_or_default());
            if seen.insert(key) {
                kept.push(LinkedPostInstance {
                    binding: post.binding.clone(),
                    call: callsite.clone(),
                    vendor_post: post.post.clone(),
                    instantiated_post: canonicalize_formula_json(&instance),
                });
            }
        }
    }
    AmbientPostInstances { kept, dropped }
}

fn with_ambient_posts_with_instances(
    inv: Json,
    ambient: &[AmbientPost],
) -> (Json, AmbientPostInstances) {
    if ambient.is_empty() {
        return (inv, AmbientPostInstances::default());
    }
    let partition = linked_ambient_post_instances_for_inv(&inv, ambient);
    debug!(
        ambient_posts = ambient.len(),
        kept = partition.kept.len(),
        dropped = partition.dropped.len(),
        "verifier/linker: conjoining specialized contract posts into obligation"
    );
    if partition.kept.is_empty() {
        return (inv, partition);
    }
    let mut operands = Vec::with_capacity(partition.kept.len() + 1);
    operands.push(inv);
    operands.extend(partition.kept.iter().map(|p| p.instantiated_post.clone()));
    (IrFormula::And(operands).to_value(), partition)
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
    IrFormula::And(operands).to_value()
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
        if !EufCoordinate::parse(&name).is_callsite_keyed() {
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
            &Attribution::Imported(candidate.cid.clone()),
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
///
/// Zero project FS (#3809 series). Locus preference is speaker role only;
/// scope is path-prefix only; witness resolvers are client-fed.
///
/// Witness discharge config defaults empty (typed context required for
/// custom-witness package recompute; no env config channel).
pub fn verify_consistency(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
) -> Vec<ConsistencyResult> {
    verify_consistency_with_policy(
        pool,
        plan,
        registry,
        compilers,
        project_root,
        &WitnessDischargeContext::default(),
    )
}

/// Like [`verify_consistency`], with typed [`WitnessDischargeContext`] (SEAM 7).
///
/// One path (#3809): no `pool_only_inputs` flag. Locus = speaker role;
/// scope = path prefix; witnesses = client-fed context only.
pub fn verify_consistency_with_policy(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    witness: &WitnessDischargeContext,
) -> Vec<ConsistencyResult> {
    let index = build_consistency_index(pool);
    verify_consistency_from_indexes(
        &index,
        None,
        plan,
        registry,
        compilers,
        project_root,
        None,
        witness,
    )
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
    /// Raw (contract/property name, locus, optional speaker role) triples in
    /// pool iteration order. The project-local preference merge (consumer
    /// file beats vendor file for the squiggle anchor) happens at solve time
    /// in `verify_consistency_from_indexes` via speaker role only (#3809).
    locus_entries: Vec<(String, SourceLocus, Option<SpeakerRole>)>,
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
                &Attribution::Imported(cid.clone()),
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
    let mut locus_entries: Vec<(String, SourceLocus, Option<SpeakerRole>)> = Vec::new();
    for (cid, member) in pool
        .source_memento_members()
        .chain(pool.members_by_kind(sugar_proof_envelope::MemberKind::AssertionSurfaceMemento))
    {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        if let Some(l) = locus_from_body(&body) {
            let role = pool.member_speaker(cid).map(|s| s.role);
            locus_entries.push((contract_property_name(&body).to_string(), l, role));
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

/// CACHED-BASE solve body: base index + overlay pool, scoped groups.
/// Shared by the public scoped entry and discrimination helpers; policy is
/// explicit so instruments can compare pool-only vs cold-disk faces.
fn verify_consistency_scoped_with_base_index_policy(
    base: &ConsistencyIndex,
    overlay_pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    scope: &Path,
    witness: &WitnessDischargeContext,
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
        witness,
    )
}

/// Scoped consistency over a **resident** base index + overlay pool (#3809).
///
/// One solve door, zero project FS: speaker-role locus preference, path-prefix
/// scope, client-fed witness resolvers. No `pool_only_inputs` flag.
///
/// - **Is:** pure discharge over a resident base index + pre-fed overlay
///   pool + in-memory plan/registry/compilers.
/// - **Is not:** kit fold / mint / source overlay construction (lift face).
///   Full `Runner`/`proof-run` face is
///   `sugar_compiler::orchestrate::solve_project_with_pool`.
pub fn verify_consistency_scoped_with_base_index(
    base: &ConsistencyIndex,
    overlay_pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    scope: &Path,
) -> Vec<ConsistencyResult> {
    verify_consistency_scoped_with_base_index_with_witness(
        base,
        overlay_pool,
        plan,
        registry,
        compilers,
        project_root,
        scope,
        &WitnessDischargeContext::default(),
    )
}

/// Scoped resident-base solve with typed witness discharge context (SEAM 7).
pub fn verify_consistency_scoped_with_base_index_with_witness(
    base: &ConsistencyIndex,
    overlay_pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    scope: &Path,
    witness: &WitnessDischargeContext,
) -> Vec<ConsistencyResult> {
    verify_consistency_scoped_with_base_index_policy(
        base,
        overlay_pool,
        plan,
        registry,
        compilers,
        project_root,
        scope,
        witness,
    )
}

/// THE consistency solve door. Grouping, scoping, and the per-group solve,
/// over the merged (base + optional overlay) index. Every consistency verdict
/// -- production `prove` (via `verify_consistency`), the editor daemon (via
/// `verify_consistency_scoped_with_base_index`), and the tests -- flows through
/// this one function; `overlay` supplies the daemon's per-request scratch
/// index (or `None` for a whole-pool run) and `scope` restricts which groups
/// are solved (or `None` for the full CLI pass).
///
/// Zero project FS (#3809): locus preference = speaker role; scope = path
/// prefix; witnesses = client-fed context. No `pool_only_inputs` flag.
///
/// `witness`: typed discharge context (project_dir + resolvers). Sole config
/// surface for package recompute (step 3 retired the env channel).
#[allow(clippy::too_many_arguments)]
pub fn verify_consistency_from_indexes(
    base: &ConsistencyIndex,
    overlay: Option<&ConsistencyIndex>,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
    scope: Option<&Path>,
    witness: &WitnessDischargeContext,
) -> Vec<ConsistencyResult> {
    // project_root retained on the signature for API stability; never stats
    // for locus/scope (speaker + path-prefix only).
    let _project_root = project_root;
    let _witness_ctx_guard = WitnessCtxGuard::enter(witness);
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
        .chain(
            overlay
                .iter()
                .flat_map(|o| o.ambient_foralls.iter().cloned()),
        )
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
            .map(|p| {
                (
                    p.binding.source_symbol.clone(),
                    p.binding.target_cid.clone(),
                )
            })
            .collect();
        for p in &o.ambient_posts {
            if !seen.contains(&(
                p.binding.source_symbol.clone(),
                p.binding.target_cid.clone(),
            )) {
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
    //
    // Locus preference (#3809 cut #5): pool speaker role only — Consumer beats
    // Vendor. Never Path::exists. Fail-open (first-write-wins) if both/neither
    // are Consumer-stamped.
    let mut locus_by_name: HashMap<String, SourceLocus> = HashMap::new();
    let mut locus_role: HashMap<String, Option<SpeakerRole>> = HashMap::new();
    for (name, l, role) in base
        .locus_entries
        .iter()
        .chain(overlay.iter().flat_map(|o| o.locus_entries.iter()))
    {
        match locus_by_name.entry(name.clone()) {
            std::collections::hash_map::Entry::Vacant(e) => {
                e.insert(l.clone());
                locus_role.insert(name.clone(), *role);
            }
            std::collections::hash_map::Entry::Occupied(mut e) => {
                let new_consumer = matches!(role, Some(SpeakerRole::Consumer));
                let cur_consumer =
                    matches!(locus_role.get(name), Some(Some(SpeakerRole::Consumer)));
                let prefer_new = new_consumer && !cur_consumer;
                if prefer_new {
                    e.insert(l.clone());
                    locus_role.insert(name.clone(), *role);
                }
            }
        }
    }

    // EDITOR SCOPE: keep groups whose anchor locus is in scope by path
    // metadata only (relative or prefix under scope_root) — never Path::exists.
    let groups: Vec<(String, Vec<ConsistencyCandidate>)> = by_name
        .into_iter()
        .filter(|(property_name, members)| match scope {
            None => true,
            Some(scope_root) => {
                let anchored_in_scope = |name: &str| {
                    locus_by_name
                        .get(name)
                        .map(|l| locus_in_scope(scope_root, &l.file))
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
        let callsite_keyed = EufCoordinate::parse(property_name).is_callsite_keyed();
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
            let (inv, collapsed_same_kind_duplicate) = conjoin_distinct_provenance_witnesses(invs);
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
                    let inv = canonicalize_formula_json(&axiom_context_formula(&candidate.body));
                    ground_callsite_witness_keys(&inv, &scope, candidate.provenance_kind)
                        .into_iter()
                })
                .collect();
            let (inv, ambient_partition) = with_ambient_posts_with_instances(inv, &ambient_posts);
            let linked_posts = ambient_partition.kept.clone();
            let dropped_ambient_posts = ambient_partition.dropped.clone();
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
                    &union_facts(vendor_facts, vendor_spoken_equalities),
                    &sworn,
                );
            }
            result.dropped_ambient_posts = dropped_ambient_posts;
            out.push(result);
        } else {
            for candidate in &inv_candidates {
                let original_inv =
                    canonicalize_formula_json(&axiom_context_formula(&candidate.body));
                let scope = ambient_ground_callsite_scope(property_name);
                let current_ground_witnesses =
                    ground_callsite_witness_keys(&original_inv, &scope, candidate.provenance_kind);
                let (inv, ambient_partition) =
                    with_ambient_posts_with_instances(original_inv.clone(), &ambient_posts);
                let linked_posts = ambient_partition.kept.clone();
                let dropped_ambient_posts = ambient_partition.dropped.clone();
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
                    attach_conjoined_facts(&mut result, &original_inv, &vendor_facts, &sworn);
                }
                result.dropped_ambient_posts = dropped_ambient_posts;
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
    use std::sync::Arc;

    // Attribution is the strong type that retired the "<client>" /
    // "<current-obligation>" sentinel strings. The soundness-load-bearing
    // behavior is that a CONSUMER-own fact carries no pool cid, so it never
    // matches an excluded (own-source) cid, whereas an IMPORTED pool member
    // exposes exactly its source cid for the "not its own vendor" exclusion.
    #[test]
    fn attribution_own_origin_has_no_source_cid() {
        assert_eq!(Attribution::OwnOrigin.source_cid(), None);
        let cid = test_cid_string("attr-src");
        assert_eq!(
            Attribution::Imported(cid.clone()).source_cid(),
            Some(cid.as_str())
        );
        // An own-origin fact is never excluded by any real cid set.
        let excluded = [cid.clone()];
        assert!(!Attribution::OwnOrigin
            .source_cid()
            .is_some_and(|sc| excluded.iter().any(|c| c == sc)));
        // An imported fact IS excluded when its source cid is in the set.
        assert!(Attribution::Imported(cid.clone())
            .source_cid()
            .is_some_and(|sc| excluded.iter().any(|c| c == sc)));
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

    /// Byte-identity contract for [`VerificationDetail`]. For each arm, the typed
    /// value must serialize to the EXACT bytes the hand-rolled `json!` shape it
    /// replaced produced (compared as canonical wire strings under
    /// `preserve_order`), and must round-trip back through `from_value`
    /// unchanged. This is the seam's gate: the linked-bundle CID is taken over
    /// these bytes.
    fn assert_wire_identity(detail: &VerificationDetail, legacy: Json) {
        let typed = serde_json::to_value(detail).expect("detail serializes");
        assert_eq!(
            serde_json::to_string(&typed).unwrap(),
            serde_json::to_string(&legacy).unwrap(),
            "typed VerificationDetail must serialize byte-identically to the legacy shape"
        );
        // to_json() is the production lowering used at the report handoff.
        assert_eq!(detail.to_json(), legacy);
        let back: VerificationDetail = serde_json::from_value(legacy)
            .expect("legacy shape deserializes into the typed detail");
        assert_eq!(&back, detail, "round-trip must be lossless");
    }

    #[test]
    fn test_verification_detail_witness_undecidable_round_trip() {
        let detail = VerificationDetail::Witness {
            witnessed: false,
            verdict: ObligationVerdict::Undecidable.as_str().to_string(),
            resolved_by: None,
            outcomes: None,
            failed: None,
            failed_tests: None,
            reason: "custom witness present but witness project_dir unset \
                 (typed WitnessDischargeContext required; fail-closed)"
                .to_string(),
        };
        assert_wire_identity(
            &detail,
            json!({
                "kind": "witness",
                "witnessed": false,
                "verdict": ObligationVerdict::Undecidable.as_str(),
                "reason": "custom witness present but witness project_dir unset \
                 (typed WitnessDischargeContext required; fail-closed)",
            }),
        );
    }

    #[test]
    fn test_verification_detail_witness_resolved_round_trip() {
        let detail = VerificationDetail::Witness {
            witnessed: true,
            verdict: ObligationVerdict::Discharged.as_str().to_string(),
            resolved_by: Some("cargo-test".to_string()),
            outcomes: Some(7),
            failed: Some(0),
            failed_tests: None,
            reason: "witness package verified by rust".to_string(),
        };
        assert_wire_identity(
            &detail,
            json!({
                "kind": "witness",
                "witnessed": true,
                "verdict": ObligationVerdict::Discharged.as_str(),
                "resolvedBy": "cargo-test",
                "outcomes": 7,
                "failed": 0,
                "reason": "witness package verified by rust",
            }),
        );
    }

    #[test]
    fn test_verification_detail_witness_package_body_round_trip() {
        let detail = VerificationDetail::Witness {
            witnessed: false,
            verdict: ObligationVerdict::Unsatisfied.as_str().to_string(),
            resolved_by: Some("cargo-test".to_string()),
            outcomes: Some(9),
            failed: Some(2),
            failed_tests: Some(vec!["t_one".to_string(), "t_two".to_string()]),
            reason: "witness package had failing outcomes".to_string(),
        };
        assert_wire_identity(
            &detail,
            json!({
                "kind": "witness",
                "witnessed": false,
                "verdict": ObligationVerdict::Unsatisfied.as_str(),
                "resolvedBy": "cargo-test",
                "outcomes": 9,
                "failed": 2,
                "failedTests": ["t_one", "t_two"],
                "reason": "witness package had failing outcomes",
            }),
        );
    }

    #[test]
    fn test_verification_detail_solver_bare_round_trip() {
        // rawSolverVerdict / solverReason are nullable-but-present: they serialize
        // as JSON null, never dropped.
        let detail = VerificationDetail::Solver {
            property: "prop".to_string(),
            checked_formula_cid: "blake3-512:cf".to_string(),
            linked_posts: json!([]),
            raw_solver_verdict: None,
            final_verdict: ObligationVerdict::Refused.as_str().to_string(),
            solver_reason: None,
            solver_invocations: json!([]),
            client_fact_ir: None,
            vendor_fact_ir: None,
            vendor_sworn_context_ir: None,
        };
        assert_wire_identity(
            &detail,
            json!({
                "kind": "consistency",
                "property": "prop",
                "checkedFormulaCid": "blake3-512:cf",
                "linkedPosts": [],
                "rawSolverVerdict": null,
                "finalVerdict": ObligationVerdict::Refused.as_str(),
                "solverReason": null,
                "solverInvocations": [],
            }),
        );
    }

    #[test]
    fn test_verification_detail_solver_with_conjoined_facts_round_trip() {
        // The clientFactIr / vendorFactIr / vendorSwornContextIr fields are
        // appended by attach_conjoined_facts AFTER solverInvocations, and are
        // dropped when absent -- exactly the insertion-order the mutate path
        // produced. vendorFactIr is the solve-participating fact set;
        // vendorSwornContextIr is the display-only sworn-context set and MUST
        // stay a distinct field (#3884: conflating the two let a never-conjoined
        // context fact look like the fact that discharged the row).
        let detail = VerificationDetail::Solver {
            property: "prop".to_string(),
            checked_formula_cid: "blake3-512:cf".to_string(),
            linked_posts: json!([{"sourceSymbol": "enc"}]),
            raw_solver_verdict: Some(ObligationVerdict::Unsatisfied.as_str().to_string()),
            final_verdict: ObligationVerdict::Discharged.as_str().to_string(),
            solver_reason: Some("unsat".to_string()),
            solver_invocations: json!([{"compiler": "smt-lib-v2.6"}]),
            client_fact_ir: Some(json!({"value": 6})),
            vendor_fact_ir: Some(json!([{"value": 5}])),
            vendor_sworn_context_ir: Some(json!([{"value": 9}])),
        };
        assert_wire_identity(
            &detail,
            json!({
                "kind": "consistency",
                "property": "prop",
                "checkedFormulaCid": "blake3-512:cf",
                "linkedPosts": [{"sourceSymbol": "enc"}],
                "rawSolverVerdict": ObligationVerdict::Unsatisfied.as_str(),
                "finalVerdict": ObligationVerdict::Discharged.as_str(),
                "solverReason": "unsat",
                "solverInvocations": [{"compiler": "smt-lib-v2.6"}],
                "clientFactIr": {"value": 6},
                "vendorFactIr": [{"value": 5}],
                "vendorSwornContextIr": [{"value": 9}],
            }),
        );
    }

    #[test]
    fn test_verification_detail_provenance_kind_round_trip() {
        let detail = VerificationDetail::ProvenanceKind {
            property: "prop".to_string(),
            final_verdict: ObligationVerdict::Refused.as_str().to_string(),
            reason: "wrong provenance KIND".to_string(),
        };
        assert_wire_identity(
            &detail,
            json!({
                "kind": "consistency-provenance-kind",
                "property": "prop",
                "finalVerdict": ObligationVerdict::Refused.as_str(),
                "reason": "wrong provenance KIND",
            }),
        );
    }

    #[test]
    fn test_attach_conjoined_facts_only_mutates_solver_variant() {
        // A non-Solver detail is left untouched (fail-open), matching the prior
        // "only mutate the consistency Object" behavior.
        let mut witness = ConsistencyResult {
            contract_cid: "c".to_string(),
            property_name: "p".to_string(),
            verdict: ObligationVerdict::Undecidable,
            reason: "r".to_string(),
            effect: None,
            witnessed: false,
            verification: Some(VerificationDetail::Witness {
                witnessed: false,
                verdict: ObligationVerdict::Undecidable.as_str().to_string(),
                resolved_by: None,
                outcomes: None,
                failed: None,
                failed_tests: None,
                reason: "r".to_string(),
            }),
            locus: None,
            dropped_ambient_posts: Vec::new(),
        };
        let before = witness.verification.clone();
        attach_conjoined_facts(
            &mut witness,
            &json!({"value": 6}),
            &[json!({"value": 5})],
            &[json!({"value": 7})],
        );
        assert_eq!(
            witness.verification, before,
            "witness arm is not a facts sink"
        );

        let mut solver = ConsistencyResult {
            contract_cid: "c".to_string(),
            property_name: "p".to_string(),
            verdict: ObligationVerdict::Discharged,
            reason: "r".to_string(),
            effect: None,
            witnessed: false,
            verification: Some(consistency_verification_detail(
                "p",
                &json!({"kind": "and", "operands": []}),
                &[],
                Some(ObligationVerdict::Unsatisfied),
                ObligationVerdict::Discharged,
                Some("unsat"),
                &[],
            )),
            locus: None,
            dropped_ambient_posts: Vec::new(),
        };
        attach_conjoined_facts(
            &mut solver,
            &json!({"value": 6}),
            &[json!({"value": 5})],
            &[json!({"value": 7})],
        );
        let Some(VerificationDetail::Solver {
            client_fact_ir,
            vendor_fact_ir,
            vendor_sworn_context_ir,
            ..
        }) = &solver.verification
        else {
            panic!("solver detail expected");
        };
        assert_eq!(client_fact_ir.as_ref(), Some(&json!({"value": 6})));
        assert_eq!(vendor_fact_ir.as_ref(), Some(&json!([{"value": 5}])));
        assert_eq!(
            vendor_sworn_context_ir.as_ref(),
            Some(&json!([{"value": 7}])),
            "display-only sworn context lands in its OWN field, never mixed \
             into vendorFactIr"
        );
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

    /// LIFT-AND-SHIFT FLOOR: `EufCoordinate` is a strong-typed view over the
    /// group-key string, and its `Display` MUST reproduce the source bytes
    /// verbatim so the wire/property string stays byte-identical. Also pins the
    /// four accessors against the exact prior scattered-parse semantics:
    /// `is_callsite_keyed` == old `contains("#euf#")`; `scope` == old
    /// `ambient_ground_callsite_scope`; `callee`/`euf_cid` complete the split.
    #[test]
    fn euf_coordinate_round_trips_and_matches_prior_parses() {
        // Scoped, callsite-keyed: scope is everything before the final `::`.
        let scoped = "src/lib.rs::tests::t::enc#euf#c:callresult_enc_a1(s:\"def\")::assertion";
        let c = EufCoordinate::parse(scoped);
        assert_eq!(c.to_string(), scoped, "Display must be byte-identical");
        assert!(c.is_callsite_keyed());
        assert_eq!(c.scope().as_deref(), Some("src/lib.rs::tests::t"));
        assert_eq!(c.callee(), Some("enc"));
        assert_eq!(
            c.euf_cid(),
            Some("c:callresult_enc_a1(s:\"def\")::assertion")
        );

        // Unscoped prefix (no `::` before `#euf#`): the WHOLE prefix is the
        // scope AND the callee -- mirrors the old `unwrap_or_else(prefix)`.
        let bare_prefix = "numpy.add#euf#callresult_numpy_add_a2(2,3)::assertion";
        let c = EufCoordinate::parse(bare_prefix);
        assert_eq!(c.to_string(), bare_prefix);
        assert!(c.is_callsite_keyed());
        assert_eq!(c.scope().as_deref(), Some("numpy.add"));
        assert_eq!(c.callee(), Some("numpy.add"));

        // Not callsite-keyed: no `#euf#` marker -> every accessor is None.
        let plain = "src/lib.rs::tests::some_test::assertion";
        let c = EufCoordinate::parse(plain);
        assert_eq!(c.to_string(), plain);
        assert!(!c.is_callsite_keyed());
        assert_eq!(c.scope(), None);
        assert_eq!(c.callee(), None);
        assert_eq!(c.euf_cid(), None);

        // The accessors agree with the exact spellings the old free function
        // and `.contains` produced, across every euf name literal in this file.
        for name in [scoped, bare_prefix, plain] {
            assert_eq!(
                EufCoordinate::parse(name).is_callsite_keyed(),
                name.contains("#euf#"),
            );
            assert_eq!(
                EufCoordinate::parse(name).scope().map(Scope),
                ambient_ground_callsite_scope(name),
            );
        }
    }

    /// STRONG-TYPING SEAM: `TermKey`/`Scope` are `#[serde(transparent)]` newtypes
    /// over the bare join/scope strings, so a value's wire form is byte-identical
    /// to the raw string it wraps and survives a serde round-trip unchanged. This
    /// is the artifact-invariance receipt for the seam: nothing that touches a
    /// serialized memento observes a different shape.
    #[test]
    fn term_key_and_scope_serde_are_transparent_and_round_trip() {
        let tk = TermKey("call:enc(s:\"abc\")".to_string());
        let wire = serde_json::to_string(&tk).unwrap();
        assert_eq!(
            wire,
            serde_json::to_string("call:enc(s:\"abc\")").unwrap(),
            "TermKey wire form must be the bare string (transparent)",
        );
        assert_eq!(serde_json::from_str::<TermKey>(&wire).unwrap(), tk);

        let sc = Scope("src/lib.rs::tests::t".to_string());
        let wire = serde_json::to_string(&sc).unwrap();
        assert_eq!(
            wire,
            serde_json::to_string("src/lib.rs::tests::t").unwrap(),
            "Scope wire form must be the bare string (transparent)",
        );
        assert_eq!(serde_json::from_str::<Scope>(&wire).unwrap(), sc);
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
             resolve_witness_command = [\"{script}\"]\n\
             resolve_witness_method = \"{method}\"\n",
            script = script.display(),
            method = ORACLE_RESOLVE_METHOD,
        );
        std::fs::write(manifest_dir.join("manifest.toml"), manifest).unwrap();
    }

    /// Assert two discharge rows are CID-idempotent (same packageCid → same seal).
    fn assert_verdict_byte_identical(a: &ConsistencyResult, b: &ConsistencyResult, label: &str) {
        assert_eq!(a.verdict, b.verdict, "{label}: verdict");
        assert_eq!(a.witnessed, b.witnessed, "{label}: witnessed");
        assert_eq!(a.reason, b.reason, "{label}: reason");
        assert_eq!(a.contract_cid, b.contract_cid, "{label}: contract_cid");
        assert_eq!(a.property_name, b.property_name, "{label}: property_name");
        // verification detail must also match (resolved_by / outcomes / etc.)
        assert_eq!(
            format!("{:?}", a.verification),
            format!("{:?}", b.verification),
            "{label}: verification detail"
        );
    }

    #[test]
    fn witness_resolvers_can_be_supplied_by_typed_context() {
        let cwd = std::env::current_dir().unwrap();
        let typed = WitnessDischargeContext {
            project_dir: Some(cwd.clone()),
            resolvers: vec![WitnessResolverSpec {
                argv: vec!["/bin/echo".to_string()],
                working_dir: cwd.clone(),
                method: ORACLE_RESOLVE_METHOD.to_string(),
            }],
        };
        let _guard = WitnessCtxGuard::enter(&typed);
        let resolvers = find_witness_resolvers();
        assert_eq!(resolvers.len(), 1);
        assert_eq!(resolvers[0].argv, vec!["/bin/echo".to_string()]);
        assert_eq!(resolvers[0].working_dir, cwd);
        assert_eq!(resolvers[0].method, ORACLE_RESOLVE_METHOD);
    }

    #[test]
    fn witness_resolvers_typed_list_is_sole_config_never_read_dir() {
        let cwd = std::env::current_dir().unwrap();
        // Even with empty typed list, solve must not walk lift manifests.
        let empty = WitnessDischargeContext {
            project_dir: Some(cwd.clone()),
            resolvers: Vec::new(),
        };
        let _guard = WitnessCtxGuard::enter(&empty);
        let resolvers = find_witness_resolvers();
        assert!(
            resolvers.is_empty(),
            "empty client-fed list must stay empty (no lift read_dir)"
        );

        let typed = WitnessDischargeContext {
            project_dir: Some(cwd.clone()),
            resolvers: vec![WitnessResolverSpec {
                argv: vec!["/bin/from-typed".to_string()],
                working_dir: cwd.clone(),
                method: ORACLE_RESOLVE_METHOD.to_string(),
            }],
        };
        drop(_guard);
        let _guard = WitnessCtxGuard::enter(&typed);
        let resolvers = find_witness_resolvers();
        assert_eq!(resolvers.len(), 1, "typed resolvers are the sole config");
        assert_eq!(resolvers[0].argv, vec!["/bin/from-typed".to_string()]);
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

        // Parsed-structure labels, NOT serialized-substring search (#3870):
        // a benign IR shape change must not false-green a wrong attribution.
        let labels = |r: &ConsistencyResult| -> (Json, Json) {
            let v = r
                .verification
                .as_ref()
                .expect("verification detail")
                .to_json();
            let client = v.get("clientFactIr").expect("client fact label").clone();
            let vendor = v.get("vendorFactIr").expect("vendor fact label").clone();
            (client, vendor)
        };
        // The exact conjunct nodes the two contracts swore, as full IR trees.
        // clientFactIr is the CONSTRUCTED conjunction of consumer-spoken
        // members (an `and` node even for one member); vendorFactIr is the
        // vector of vendor-spoken members.
        let says_6 = eqf(var("r"), int(6));
        let says_5 = eqf(var("r"), int(5));
        let and1 = |c: &Json| json!({"kind":"and","operands":[c]});

        // Consumer speaks ==6, vendor speaks ==5.
        let normal = solve_with(true);
        assert_eq!(normal.verdict, ObligationVerdict::Unsatisfied);
        let (client, vendor) = labels(&normal);
        assert_eq!(
            client,
            and1(&says_6),
            "clientFactIr must be EXACTLY the consumer's ==6 conjunction"
        );
        assert_eq!(
            vendor,
            json!([says_5]),
            "vendorFactIr must be EXACTLY the vendor's ==5 conjunct vector"
        );

        // FLIP the speakers over the SAME two contracts: labels flip,
        // verdict does not.
        //
        // BAD-TWIN RECEIPT (run 2026-07-08, then reverted): with the fixture
        // attribution swapped (Consumer<->Vendor roles on the same CIDs),
        // the structural assert_eq! FAILS loudly:
        //   clientFactIr must be EXACTLY the consumer's ==6 conjunction
        //   left:  {"kind":"and","operands":[{..."value":5...}]}
        //   right: {"kind":"and","operands":[{..."value":6...}]}
        // proving the assertion discriminates attribution structurally.
        // Unlike the old `client.contains("\"value\":6")` substring check,
        // a benign IR serialization/shape change (key reordering, wrapper
        // node, escaping) cannot false-green this: only the exact parsed
        // clientFactIr/vendorFactIr nodes satisfy it.
        let flipped = solve_with(false);
        assert_eq!(
            flipped.verdict,
            ObligationVerdict::Unsatisfied,
            "attribution must never change the verdict (solver input is byte-identical)"
        );
        let (client, vendor) = labels(&flipped);
        assert_eq!(
            client,
            and1(&says_5),
            "flipped clientFactIr must be EXACTLY the (now consumer-spoken) ==5 conjunction"
        );
        assert_eq!(
            vendor,
            json!([says_6]),
            "flipped vendorFactIr must be EXACTLY the (now vendor-spoken) ==6 conjunct vector"
        );
    }

    /// TUPLE / DATA-CTOR INJECTIVITY: a callsite equated to two distinct ground
    /// constructor values (`tuple(0,0)` vs `tuple(1,1)`) is a structural
    /// contradiction. Before this, `is_const_value` only accepted primitive
    /// consts, so `df.shape == (0,0) ∧ df.shape == (1,1)` fell through to z3 as
    /// sat (tuple injectivity gap). Component-wise injectivity is free via
    /// distinct JCS keys of the ground ctor trees — no fabricated witness, no
    /// solver ADT theory required.
    #[test]
    fn pure_callsite_tuple_value_contradiction_refuses_structurally() {
        let (plan, reg) = z3_plan_and_registry();
        let shape = json!({"kind":"ctor","name":"call:shape","args":[
            {"kind":"ctor","name":"call:pandas.DataFrame","args":[]}
        ]});
        let tuple = |a: i64, b: i64| {
            json!({"kind":"ctor","name":"tuple","args":[
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":a},
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":b},
            ]})
        };
        let inv = json!({"kind":"and","operands":[
            eqf(shape.clone(), tuple(0, 0)),
            eqf(shape.clone(), tuple(1, 1)),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:tuple-contradiction",
            "shape#euf#c:call:shape(c:call:pandas.DataFrame())::assertion",
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
            "call:shape()==(0,0) ∧ call:shape()==(1,1) MUST refuse structurally: {res:?}"
        );
        assert!(
            res[0].reason.contains("structural:"),
            "must fire pre-SMT structural path (not z3 ADT): {}",
            res[0].reason
        );
        assert!(
            res[0].reason.contains("equals both"),
            "reason should name the dual values: {}",
            res[0].reason
        );
    }

    /// `py.eq` is Python assert equality — same structural dual as IR `=`.
    /// Dual `py.eq(call:A(), 3) ∧ py.eq(call:A(), 4)` must refuse pre-SMT
    /// (CallSiteValue binary dig witnesses / logo dual-assert path).
    #[test]
    fn pure_callsite_py_eq_value_contradiction_refuses_structurally() {
        let (plan, reg) = z3_plan_and_registry();
        let call_a = json!({"kind":"ctor","name":"call:A","args":[]});
        let py_eq = |rhs: i64| {
            json!({"kind":"atomic","name":"py.eq","args":[
                call_a.clone(),
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":rhs},
            ]})
        };
        let inv = json!({"kind":"and","operands":[
            py_eq(3),
            py_eq(4),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:py-eq-contradiction",
            "test_dual::assertion",
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
            "py.eq(call:A(),3) ∧ py.eq(call:A(),4) MUST refuse structurally: {res:?}"
        );
        assert!(
            res[0].reason.contains("structural:"),
            "must fire pre-SMT structural path: {}",
            res[0].reason
        );
        assert!(
            res[0].reason.contains("equals both"),
            "reason should name the dual values: {}",
            res[0].reason
        );
    }

    /// Scope pin: `py.eq` is NOT general reflexivity. `py.eq(x, x)` must not
    /// structural-discharge (NaN watch — Python == is non-reflexive).
    #[test]
    fn py_eq_var_reflexivity_is_not_structural() {
        let inv = json!({"kind":"atomic","name":"py.eq","args":[
            {"kind":"var","name":"x"},
            {"kind":"var","name":"x"},
        ]});
        assert_eq!(
            structural_contradiction_reason(&inv),
            None,
            "py.eq(x,x) must not enter term-const dual orientation"
        );
        let and = json!({"kind":"and","operands":[inv.clone(), inv]});
        assert_eq!(structural_contradiction_reason(&and), None);
    }

    /// Scope pin: single ground py.eq(call:A(), 3) is not a dual contradiction.
    #[test]
    fn single_py_eq_ground_rhs_is_not_structural_contradiction() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[]});
        let inv = json!({"kind":"atomic","name":"py.eq","args":[
            call_a,
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":3},
        ]});
        assert_eq!(
            structural_contradiction_reason(&inv),
            None,
            "one face is not equals-both"
        );
    }

    /// const-const py.eq does not orient (NaN/reflexivity fence).
    #[test]
    fn py_eq_const_const_does_not_orient_structurally() {
        let inv = json!({"kind":"atomic","name":"py.eq","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Real"},"value":null},
            {"kind":"const","sort":{"kind":"primitive","name":"Real"},"value":null},
        ]});
        assert_eq!(
            structural_contradiction_reason(&inv),
            None,
            "const-const py.eq must not structural-orient"
        );
    }

    /// Type fence: only DualGroundEqFace::try_from_atomic orients; bare names
    /// and non-oriented atoms produce None (no free "py.eq is equality" API).
    ///
    /// # Construction closure (#4141)
    ///
    /// `DualGroundEqFace` lives in private submodule `dual_ground_eq_face` with
    /// private fields. Even this parent module cannot write
    /// `DualGroundEqFace { term: ..., value: ... }` -- that is E0451 at compile
    /// time. The wrong construction (py.eq treated as free equality without
    /// ground term+value orientation) is therefore not expressible as a face
    /// value except through `try_from_atomic` (which rejects non-oriented
    /// atoms at the door). Structural proof: DualTerm/DualValue are not
    /// `use`d outside the submodule; only `try_from_atomic` + read accessors
    /// are `pub(super)`.
    #[test]
    fn dual_ground_eq_face_is_sole_construction_door() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[]});
        let oriented = json!({"kind":"atomic","name":"py.eq","args":[
            call_a.clone(),
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":3},
        ]});
        let face = DualGroundEqFace::try_from_atomic(&oriented);
        assert!(face.is_some());
        // Read accessors (not public field projection) are the only way to
        // recover the oriented halves after the door admits a face.
        let face = face.unwrap();
        assert_eq!(face.term_json()["kind"], "ctor");
        assert_eq!(face.value_json()["kind"], "const");

        let ir_eq = json!({"kind":"atomic","name":"=","args":[
            call_a.clone(),
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":3},
        ]});
        assert!(DualGroundEqFace::try_from_atomic(&ir_eq).is_some());

        let reflexive = json!({"kind":"atomic","name":"py.eq","args":[
            {"kind":"var","name":"x"},
            {"kind":"var","name":"x"},
        ]});
        assert!(DualGroundEqFace::try_from_atomic(&reflexive).is_none());

        let other_atom = json!({"kind":"atomic","name":"py.lt","args":[
            call_a,
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":3},
        ]});
        assert!(DualGroundEqFace::try_from_atomic(&other_atom).is_none());
    }

    /// ARITHMETIC OPERATORS ARE NOT STRUCTURAL VALUES: a truthful binop body dig
    /// posts `call:A(5) == +(5,1)` while the assertion posts `call:A(5) == 6`.
    /// Those must NOT structural-refute — SMT (or fold) proves them equal. #3924
    /// treated every ground non-call ctor as a value, so `+(5,1)` vs `6` falsely
    /// refuted the corpus `binop_return` truthful seed (Part of #3809).
    #[test]
    fn pure_callsite_arithmetic_value_does_not_structural_refute_truthful() {
        let (plan, reg) = z3_plan_and_registry();
        let call_a = json!({"kind":"ctor","name":"call:A","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":5}
        ]});
        let plus = json!({"kind":"ctor","name":"+","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":5},
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":1},
        ]});
        let inv = json!({"kind":"and","operands":[
            eqf(call_a.clone(), int(6)),
            eqf(call_a.clone(), plus),
        ]});
        let mut pool = MementoPool::default();
        insert_contract(
            &mut pool,
            "blake3-512:arith-not-structural",
            "A#euf#c:call:A(i:5)::assertion",
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
            "call:A(5)==6 ∧ call:A(5)==+(5,1) must NOT structural-refute a truthful binop: {res:?}"
        );
        assert!(
            !res[0].reason.contains("structural:"),
            "must not fire pre-SMT structural path on arithmetic: {}",
            res[0].reason
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
            .expect("good row carries verification detail")
            .to_json();
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

    /// Stated peer claims under different property prefixes do not pool each
    /// other (a good/bad twin pair must keep opposite verdicts). Derived
    /// testimony about the same exact term does travel across prefixes (#3884).
    #[test]
    fn ambient_ground_callsite_facts_stated_peers_stay_scoped_derived_crosses() {
        let (plan, reg) = z3_plan_and_registry();
        let callg = |arg: Json| json!({"kind":"ctor","name":"call:g","args":[arg]});

        // Pure Stated peers: no cross-prefix join -- each is a lone claim.
        let mut stated_pool = MementoPool::default();
        insert_contract(
            &mut stated_pool,
            "blake3-512:consumer-a-point",
            "src/lib.rs::tests::consumer_a::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(1))]}),
        );
        insert_contract(
            &mut stated_pool,
            "blake3-512:consumer-b-point",
            "src/lib.rs::tests::consumer_b::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(2))]}),
        );
        let stated_res = verify_consistency(
            &stated_pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        for row in &stated_res {
            assert_eq!(
                row.verdict,
                ObligationVerdict::Refused,
                "Stated peers under different prefixes must not pool each other: {stated_res:?}"
            );
        }

        // Derived cross-prefix: independent-KIND witness of g(2)==1 refutes a
        // lying claim under another prefix about the exact same term.
        let mut derived_pool = MementoPool::default();
        insert_derived_contract(
            &mut derived_pool,
            "blake3-512:derived-g2-one",
            "src/lib.rs::tests::derived_scope::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(1))]}),
        );
        insert_contract(
            &mut derived_pool,
            "blake3-512:lying-g2",
            "src/lib.rs::tests::consumer_lie::g#euf#c:callresult_g_a1(i:2)::assertion",
            json!({"kind":"and","operands":[eqf(callg(int(2)), int(99))]}),
        );
        let derived_res = verify_consistency(
            &derived_pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let lying = derived_res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:lying-g2"))
            .expect("lying claim present");
        assert_eq!(
            lying.verdict,
            ObligationVerdict::Unsatisfied,
            "Derived testimony must cross prefixes on exact term identity: {derived_res:?}"
        );
    }

    /// #3884 SOUNDNESS repro (shape 2 / Repro B): consumer assertions over the
    /// SAME ground call term (`call:len(100)`) but DIFFERENT property-name prefixes
    /// (different ambient scopes) join via exact call-term identity. A derived
    /// witness states the true value. Two discrimination pools (EUF dig needs
    /// teeth -- both sides of the pair):
    ///   * truthful twin agrees -> Discharged
    ///   * lying twin asserts a wrong value -> Unsatisfied (contradiction)
    /// Before the fix the scope key blocked pool-wide term-identity join across
    /// prefixes (silent no-join / false green when a domain universe was present).
    ///
    /// NOTE (from the len-bridge fixture era): the earlier draft tried the shared
    /// pool shape and saw both rows `vendor_fact_ir: None` with both Discharged
    /// when a domain universe was present; without a universe both were Refused.
    #[test]
    fn ambient_ground_facts_join_on_exact_term_across_property_prefixes_bad_twin_refutes() {
        let (plan, reg) = z3_plan_and_registry();
        let call_len = |arg: Json| json!({"kind":"ctor","name":"call:len","args":[arg]});
        let derived_inv = json!({"kind":"and","operands":[eqf(call_len(int(100)), int(0))]});
        let derived_name =
            "src/lib.rs::tests::fresh_len_derived::len#euf#c:call:len(i:100)::assertion";

        // --- truthful twin: matching value, different property prefix ---
        let mut good_pool = MementoPool::default();
        insert_derived_contract(
            &mut good_pool,
            "blake3-512:derived-len-100-zero",
            derived_name,
            derived_inv.clone(),
        );
        insert_contract(
            &mut good_pool,
            "blake3-512:good-len-100",
            "src/lib.rs::tests::fresh_len_good::len#euf#c:call:len(i:100)::assertion",
            json!({"kind":"and","operands":[eqf(call_len(int(100)), int(0))]}),
        );
        let good_res = verify_consistency(
            &good_pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let good = good_res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:good-len-100"))
            .expect("truthful twin present");
        assert_eq!(
            good.verdict,
            ObligationVerdict::Discharged,
            "BEFORE/AFTER: truthful twin must Discharge when the cross-prefix \
             exact-term join fires (was Refused under scope isolation): {good_res:?}"
        );

        // --- lying twin: wrong value, different property prefix ---
        let mut bad_pool = MementoPool::default();
        insert_derived_contract(
            &mut bad_pool,
            "blake3-512:derived-len-100-zero-bad",
            derived_name,
            derived_inv,
        );
        insert_contract(
            &mut bad_pool,
            "blake3-512:bad-len-100",
            "src/lib.rs::tests::fresh_len_bad::len#euf#c:call:len(i:100)::assertion",
            json!({"kind":"and","operands":[eqf(call_len(int(100)), int(2))]}),
        );
        let bad_res = verify_consistency(
            &bad_pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let bad = bad_res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:bad-len-100"))
            .expect("lying twin present");
        assert_eq!(
            bad.verdict,
            ObligationVerdict::Unsatisfied,
            "BEFORE/AFTER: lying twin must be Unsatisfied when the cross-prefix \
             exact-term join fires (was Refused / false-green Discharged): {bad_res:?}"
        );

        // vendor_fact_ir carries the participating ambient fact for THIS term.
        let bad_v = bad
            .verification
            .as_ref()
            .expect("bad row carries verification")
            .to_json();
        let vf = bad_v
            .get("vendorFactIr")
            .and_then(|v| v.as_array())
            .expect("lying twin must receive the matching-term ambient fact in vendorFactIr");
        assert!(
            !vf.is_empty(),
            "vendorFactIr must be non-empty for the refuting join: {bad_v:?}"
        );
        let vf_text = serde_json::to_string(vf).unwrap_or_default();
        assert!(
            vf_text.contains(r#""value":0"#) || vf_text.contains("\"value\":0"),
            "refuting fact must be call:len(100)==0, got: {vf_text}"
        );
    }

    /// #3884 SOUNDNESS repro (shape 1 / Repro A): when multiple ground facts for
    /// the same callee name exist with DIFFERENT arguments (`call:len(100)` vs
    /// `call:len(200)`), a contract about one term must NEVER receive the other
    /// term's fact in solve-participating `vendor_fact_ir`. Exact call-term
    /// identity is the join key -- not the callee name `len`, not first-writer.
    #[test]
    fn ambient_ground_facts_never_attach_non_matching_argument_to_vendor_fact_ir() {
        let (plan, reg) = z3_plan_and_registry();
        let call_len = |arg: Json| json!({"kind":"ctor","name":"call:len","args":[arg]});

        let mut pool = MementoPool::default();
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-len-100",
            "src/lib.rs::tests::fresh_len_a::len#euf#c:call:len(i:100)::assertion",
            json!({"kind":"and","operands":[eqf(call_len(int(100)), int(0))]}),
        );
        insert_derived_contract(
            &mut pool,
            "blake3-512:derived-len-200",
            "src/lib.rs::tests::fresh_len_b::len#euf#c:call:len(i:200)::assertion",
            json!({"kind":"and","operands":[eqf(call_len(int(200)), int(5))]}),
        );
        // Consumer about len(100) only -- must not pick up len(200)==5.
        insert_contract(
            &mut pool,
            "blake3-512:consumer-len-100",
            "src/lib.rs::tests::fresh_len_consumer::len#euf#c:call:len(i:100)::assertion",
            json!({"kind":"and","operands":[eqf(call_len(int(100)), int(0))]}),
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let consumer = res
            .iter()
            .find(|r| r.contract_cid == test_cid_string("blake3-512:consumer-len-100"))
            .expect("consumer present");
        assert_eq!(
            consumer.verdict,
            ObligationVerdict::Discharged,
            "matching-arg derived fact must witness the consumer: {res:?}"
        );

        let v = consumer
            .verification
            .as_ref()
            .expect("consumer carries verification")
            .to_json();
        if let Some(vf) = v.get("vendorFactIr").and_then(|x| x.as_array()) {
            let vf_text = serde_json::to_string(vf).unwrap_or_default();
            assert!(
                !vf_text.contains("\"value\":5") && !vf_text.contains(r#""value":5"#),
                "vendorFactIr must not carry call:len(200)==5 for a call:len(100) \
                 consumer (cross-term attachment): {vf_text}"
            );
            // The matching fact's subject term must be call:len with arg 100 only.
            for fact in vf {
                if let Some((term, _val)) = ground_term_const_equality(fact) {
                    if is_callsite_ctor_term(term) {
                        let args = term.get("args").and_then(|a| a.as_array());
                        if let Some(args) = args {
                            assert!(
                                args.iter().any(|a| a.get("value") == Some(&json!(100))),
                                "solve-participating fact must be about call:len(100), \
                                 got: {fact:?}"
                            );
                            assert!(
                                !args.iter().any(|a| a.get("value") == Some(&json!(200))),
                                "solve-participating fact must not be about call:len(200): \
                                 {fact:?}"
                            );
                        }
                    }
                }
            }
        }
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
        let res = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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

    /// Helper: typed discharge context pointing at a project-local fake oracle.
    fn typed_ctx_for_project(project: &std::path::Path) -> WitnessDischargeContext {
        let script = project
            .join(".sugar")
            .join("lift")
            .join("fake-witness")
            .join("resolve.sh");
        WitnessDischargeContext {
            project_dir: Some(project.to_path_buf()),
            resolvers: vec![WitnessResolverSpec {
                argv: vec![script.display().to_string()],
                working_dir: project.to_path_buf(),
                method: ORACLE_RESOLVE_METHOD.to_string(),
            }],
        }
    }

    /// A lying discharge-command stdout cannot turn a failed witness package
    /// into a discharge. The row verdict is derived from package bytes only
    /// (oracle resolve + package_outcome); kit verdict strings are ignored.
    #[test]
    fn lying_discharge_cannot_pass_failed_package_for_any_witness_kind() {
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"good\"}\n{\"outcome\":\"failed\",\"test\":\"bad\"}\n";
        let package_cid = blake3_512_of(package_bytes);

        for tool in ["pytest", "cargo-test", "junit", "testng"] {
            let project = unique_temp_dir(tool);
            write_resolver_manifest(&project, package_bytes);
            // Pollute process env with a DISCHARGED lie: package path must ignore it.
            let lie = write_discharge_stdout(&project, "DISCHARGED");
            let env_key = tool_env_key(tool);
            std::env::set_var(&env_key, &lie);

            let typed = typed_ctx_for_project(&project);
            let _guard = WitnessCtxGuard::enter(&typed);
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

            drop(_guard);
            std::env::remove_var(&env_key);
            let _ = std::fs::remove_dir_all(&project);
        }
    }

    #[test]
    fn all_passed_package_discharges_from_body_not_stdout() {
        let package_bytes =
            b"{\"outcome\":\"passed\",\"test\":\"one\"}\n{\"outcome\":\"passed\",\"test\":\"two\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("all-passed-package");
        write_resolver_manifest(&project, package_bytes);
        let lie = write_discharge_stdout(&project, "REFUSED");
        // Lie on DISCHARGE env must not affect package recompute.
        std::env::set_var("SUGAR_WITNESS_DISCHARGE_PYTEST", &lie);

        let typed = typed_ctx_for_project(&project);
        let _guard = WitnessCtxGuard::enter(&typed);
        let body = package_contract("pytest", &package_cid, 2, 2);
        let result =
            try_witness_discharge(&body, "blake3-512:cid".into(), "test_x".into()).unwrap();
        assert_eq!(result.verdict, ObligationVerdict::Discharged);
        assert!(
            result.reason.contains("all 2 outcomes passed"),
            "reason must cite rust-side package outcome: {result:?}"
        );
        assert!(result.witnessed);

        drop(_guard);
        std::env::remove_var("SUGAR_WITNESS_DISCHARGE_PYTEST");
        let _ = std::fs::remove_dir_all(&project);
    }

    /// #3809 cut #6: empty typed resolvers must NOT discover lift manifests.
    /// Client must feed resolvers; cold read_dir is deleted.
    #[test]
    fn witness_empty_typed_resolvers_does_not_read_dir_lift() {
        let package_bytes =
            b"{\"outcome\":\"passed\",\"test\":\"one\"}\n{\"outcome\":\"passed\",\"test\":\"two\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("step3-no-lift-read-dir");
        write_resolver_manifest(&project, package_bytes);
        let contract_cid = "blake3-512:step3-no-read-dir-contract".to_string();
        let property = "test_x".to_string();
        let body = package_contract("pytest", &package_cid, 2, 2);

        // Manifest exists on disk, but typed list is empty — must fail-closed
        // without reading lift (undecidable: no resolvers configured).
        let empty_ctx = WitnessDischargeContext {
            project_dir: Some(project.clone()),
            resolvers: Vec::new(),
        };
        let _guard = WitnessCtxGuard::enter(&empty_ctx);
        let via_empty =
            try_witness_discharge(&body, contract_cid.clone(), property.clone()).unwrap();
        drop(_guard);

        assert_eq!(
            via_empty.verdict,
            ObligationVerdict::Undecidable,
            "empty client-fed resolvers must not discover lift manifests: {:?}",
            via_empty
        );
        assert!(
            via_empty.reason.contains("no resolve_witness_command")
                || via_empty.reason.contains("fail-closed"),
            "reason must cite missing client-fed resolvers: {}",
            via_empty.reason
        );

        // Same package with client-fed resolvers discharges (control).
        let script = project
            .join(".sugar")
            .join("lift")
            .join("fake-witness")
            .join("resolve.sh");
        let fed = WitnessDischargeContext {
            project_dir: Some(project.clone()),
            resolvers: vec![WitnessResolverSpec {
                argv: vec![script.display().to_string()],
                working_dir: project.clone(),
                method: ORACLE_RESOLVE_METHOD.to_string(),
            }],
        };
        let _guard = WitnessCtxGuard::enter(&fed);
        let via_fed = try_witness_discharge(&body, contract_cid, property).unwrap();
        drop(_guard);
        assert_eq!(
            via_fed.verdict,
            ObligationVerdict::Discharged,
            "client-fed resolvers must discharge: {:?}",
            via_fed
        );

        let _ = std::fs::remove_dir_all(&project);
    }

    /// Step 2 receipt: kit oracle is the ONE resolve door.
    ///
    /// Path A (arm): `try_witness_discharge` — the consistency arm entry.
    /// Path B (oracle door): speak packageCid via `witness_package_via_oracle`
    /// then `seal_witness_package_outcome` — the explicit resolve+verify composition.
    /// Path C (repeat arm): same typed resolvers — byte-identical recompute.
    ///
    /// All three MUST seal byte-identical `ObligationVerdict` for one packageCid.
    /// Two different results = failing test (the whole invariant).
    #[test]
    fn witness_verdict_byte_identical_arm_vs_oracle_door() {
        let package_bytes =
            b"{\"outcome\":\"passed\",\"test\":\"one\"}\n{\"outcome\":\"passed\",\"test\":\"two\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("step2-oracle-door");
        write_resolver_manifest(&project, package_bytes);
        let script = project
            .join(".sugar")
            .join("lift")
            .join("fake-witness")
            .join("resolve.sh");
        let contract_cid = "blake3-512:step2-oracle-door-contract".to_string();
        let property = "test_x".to_string();
        let body = package_contract("pytest", &package_cid, 2, 2);

        let typed = WitnessDischargeContext {
            project_dir: Some(project.clone()),
            resolvers: vec![WitnessResolverSpec {
                argv: vec![script.display().to_string()],
                working_dir: project.clone(),
                method: ORACLE_RESOLVE_METHOD.to_string(),
            }],
        };
        let claim = witness_package_claim(body.get("evidence").expect("evidence"), "pytest")
            .expect("claim");
        let resolvers: Vec<WitnessResolver> = typed
            .resolvers
            .iter()
            .map(|r| WitnessResolver {
                argv: r.argv.clone(),
                working_dir: r.working_dir.clone(),
                method: r.method.clone(),
            })
            .collect();

        // Path A — consistency arm (typed resolvers, no env).
        let _typed_guard = WitnessCtxGuard::enter(&typed);
        let via_arm = try_witness_discharge(&body, contract_cid.clone(), property.clone()).unwrap();
        drop(_typed_guard);

        // Path B — explicit oracle door (resolve via kit RPC + package_outcome seal).
        let via_oracle = seal_witness_package_outcome(
            witness_package_via_oracle(&resolvers, &project, &claim),
            contract_cid.clone(),
            property.clone(),
        );

        // Path C — repeat arm (one path; same typed resolvers).
        let _typed_warm = WitnessCtxGuard::enter(&typed);
        let via_warm =
            try_witness_discharge(&body, contract_cid.clone(), property.clone()).unwrap();
        drop(_typed_warm);

        assert_verdict_byte_identical(&via_arm, &via_oracle, "arm vs oracle door");
        assert_verdict_byte_identical(&via_arm, &via_warm, "arm vs repeat arm");
        assert_eq!(
            via_arm.verdict,
            ObligationVerdict::Discharged,
            "all-passed package must discharge via oracle door"
        );
        assert!(
            via_arm.reason.contains("verified by rust via package"),
            "reason must cite rust-side package_outcome, not kit verdict: {}",
            via_arm.reason
        );
        eprintln!(
            "RECEIPT step2_oracle_door packageCid={} method={} verdict={:?} reason={}",
            package_cid, ORACLE_RESOLVE_METHOD, via_arm.verdict, via_arm.reason
        );

        let _ = std::fs::remove_dir_all(&project);
    }

    #[test]
    fn stated_provenance_cannot_discharge_custom_execution_witness_package() {
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("stated-witness-package-kind");
        write_resolver_manifest(&project, package_bytes);

        let body = package_contract_with_provenance("cargo-test", &package_cid, 1, 1, "Stated");
        let mut pool = MementoPool::default();
        insert_package_contract_with_provenance(
            &mut pool,
            "blake3-512:stated-witness-package",
            body,
        );
        let (plan, reg) = z3_plan_and_registry();
        let typed = typed_ctx_for_project(&project);
        // Provenance-kind refusal happens before recompute; typed config still
        // required so the arm can attempt discharge after kind checks.
        let res = verify_consistency_with_policy(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
            &typed,
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );

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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
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
        let results = verify_consistency(
            &pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].verdict, ObligationVerdict::Unsatisfied);
    }

    /// #3809 instrument: resident-base scoped solve must produce **byte-
    /// identical** wire rows to a second call of the same one-door body on a
    /// speaker-free base+overlay pool. One path, no `pool_only_inputs` flag.
    ///
    /// Layout mirrors the LSP face: resident **base** index (vendor) +
    /// **overlay** pool (consumer) over one euf property with a contradiction.
    #[test]
    fn resident_base_solve_byte_identical_to_cold_disk_face() {
        let z3_ok = std::process::Command::new("z3")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if !z3_ok {
            eprintln!("skip: z3 unavailable");
            return;
        }
        let prop = "demo.check#euf#c:1(2,3)::assertion";
        // Project tree retained for fixture realism; scope uses path-prefix
        // (relative loci) without Path::exists.
        let project = unique_temp_dir("one-solve-gap3-project");
        std::fs::create_dir_all(project.join("src")).unwrap();
        std::fs::write(project.join("src").join("lib.rs"), b"// fixture\n").unwrap();

        let insert_with_file = |pool: &mut MementoPool, cid: &str, inv: Json| {
            let env = json!({
                "envelope": {
                    "header": {
                        "kind": "contract",
                        "contractName": prop,
                        "inv": inv,
                        "file": "src/lib.rs",
                        "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 10},
                        "proofirProvenance": proofir_provenance("Stated")
                    }
                }
            });
            pool.insert_unanchored_for_tests(test_cid(cid), env);
        };

        // Sibling SOURCE-MEMENTO carries file/span for scope + squiggle anchor
        // (scoped door drops groups with no locus_entries — see #3802).
        let insert_source_locus = |pool: &mut MementoPool, cid: &str| {
            let env = json!({
                "envelope": {
                    "header": {
                        "kind": "source-memento",
                        "contractName": prop,
                        "file": "src/lib.rs",
                        "span": {"start_line": 1, "start_col": 0, "end_line": 1, "end_col": 10},
                    }
                }
            });
            pool.insert_unanchored_for_tests(test_cid(cid), env);
        };

        // Base (vendor): check(2,3) == 5
        let mut base_pool = MementoPool::default();
        insert_with_file(
            &mut base_pool,
            "blake3-512:vendor-warm-gap3",
            json!({"kind":"and","operands":[eqf(var("r"), int_const(5))]}),
        );
        insert_source_locus(&mut base_pool, "blake3-512:vendor-src-warm-gap3");
        // Overlay (consumer): check(2,3) == 6  → conjoined UNSAT with vendor
        let mut overlay = MementoPool::default();
        insert_with_file(
            &mut overlay,
            "blake3-512:consumer-warm-gap3",
            json!({"kind":"and","operands":[eqf(var("r"), int_const(6))]}),
        );
        insert_source_locus(&mut overlay, "blake3-512:consumer-src-warm-gap3");

        let (plan, registry) = z3_plan_and_registry();
        let compilers = test_compilers();
        let base_index = build_consistency_index(&base_pool);

        // Same one-door body via policy helper and public resident-base entry.
        let cold = verify_consistency_scoped_with_base_index_policy(
            &base_index,
            &overlay,
            &plan,
            &registry,
            &compilers,
            &project,
            &project,
            &WitnessDischargeContext::default(),
        );
        let warm = verify_consistency_scoped_with_base_index(
            &base_index,
            &overlay,
            &plan,
            &registry,
            &compilers,
            &project,
            &project,
        );

        // project_root as a FILE trap — zero project FS.
        // Relative locus "src/lib.rs" stays in-scope without exists().
        let trap = unique_temp_dir("one-solve-gap3-trap");
        let trap_file = trap.join("project_root_is_a_file");
        std::fs::write(&trap_file, b"resident-base solve must not open children\n").unwrap();
        let warm_trap = verify_consistency_scoped_with_base_index(
            &base_index,
            &overlay,
            &plan,
            &registry,
            &compilers,
            &trap_file,
            &trap_file,
        );

        let wire = |rows: &[ConsistencyResult]| -> Vec<String> {
            let mut blobs: Vec<String> = rows
                .iter()
                .map(|cr| {
                    let mut report = crate::types::Report::default();
                    crate::report::add_consistency_with_verification(
                        &cr.contract_cid,
                        &cr.property_name,
                        cr.verdict,
                        &cr.reason,
                        cr.verification.as_ref().map(|v| v.to_json()),
                        cr.locus.clone(),
                        &mut report,
                    );
                    serde_json::to_string(&crate::report::row_to_json(&report.rows[0]))
                        .expect("row_to_json serialize")
                })
                .collect();
            blobs.sort();
            blobs
        };

        let cold_wire = wire(&cold);
        let warm_wire = wire(&warm);
        let trap_wire = wire(&warm_trap);
        eprintln!(
            "one-solve byte-identity gate:\n\
             \tcold rows={} warm rows={} trap rows={}\n\
             \tcold={cold_wire:?}\n\
             \twarm={warm_wire:?}\n\
             \ttrap={trap_wire:?}",
            cold.len(),
            warm.len(),
            warm_trap.len(),
        );
        assert_eq!(
            warm_wire, cold_wire,
            "resident-base solve must be byte-identical to cold disk face (row_to_json)"
        );
        assert_eq!(
            trap_wire, warm_wire,
            "resident-base solve with file-trap project_root must match (zero project FS)"
        );
        assert!(
            !warm.is_empty(),
            "fixture must produce at least one consistency row"
        );
        assert!(
            warm.iter()
                .any(|r| r.verdict == ObligationVerdict::Unsatisfied),
            "vendor==5 ∧ consumer==6 must be Unsatisfied: {warm:?}"
        );

        let _ = std::fs::remove_dir_all(&project);
        let _ = std::fs::remove_dir_all(&trap);
    }

    // -----------------------------------------------------------------------
    // #4148 / silent-drop ratchets: ambient vendor post specialization must
    // NEVER silently discard a matched post. Partition.dropped is the only
    // lawful place a non-kept post may land; empty-dropped + missing-kept when
    // a match was attempted is a law violation (silent green class).
    // -----------------------------------------------------------------------

    fn ambient_post_encode_base64(post: Json, formals: Vec<String>) -> AmbientPost {
        AmbientPost {
            binding: BridgeBinding {
                source_symbol: "call:encodeBase64".to_string(),
                target_cid: "test-target-cid".to_string(),
                target_proof_cid: None,
                formals,
                out_binding: "out".to_string(),
            },
            post,
        }
    }

    fn consumer_inv_encode_base64(rhs: &str) -> Json {
        json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {
                    "kind": "ctor",
                    "name": "call:encodeBase64",
                    "args": [
                        {
                            "kind": "const",
                            "sort": {"kind": "primitive", "name": "String"},
                            "value": "xyz"
                        }
                    ]
                },
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": rhs
                }
            ]
        })
    }

    #[test]
    fn silent_drop_ratchet_open_post_after_specialization_is_loud() {
        // Post stays open: free var `unbound` is not a formal and is not the out
        // binding. Specialization must LOUD-drop, never silently filter.
        let ambient = vec![ambient_post_encode_base64(
            json!({
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {"kind": "var", "name": "unbound"}
                ]
            }),
            vec!["value".to_string()],
        )];
        let inv = consumer_inv_encode_base64("AAAA");
        let partition = linked_ambient_post_instances_for_inv(&inv, &ambient);
        assert!(
            partition.kept.is_empty(),
            "open specialized post must not enter linkedPosts: {:?}",
            partition.kept
        );
        assert_eq!(
            partition.dropped.len(),
            1,
            "open specialized post must land in dropped (silent filter is illegal): {:?}",
            partition.dropped
        );
        assert_eq!(
            partition.dropped[0].reason,
            DroppedAmbientPostReason::OpenAfterSpecialization
        );
        assert_eq!(
            partition.dropped[0].reason.label(),
            "open-after-specialization"
        );
        assert_eq!(partition.dropped[0].source_symbol, "call:encodeBase64");
    }

    #[test]
    fn silent_drop_ratchet_closed_post_is_kept_not_dropped() {
        let ambient = vec![ambient_post_encode_base64(
            json!({
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "eHl6"
                    }
                ]
            }),
            vec!["value".to_string()],
        )];
        let inv = consumer_inv_encode_base64("eHl6");
        let partition = linked_ambient_post_instances_for_inv(&inv, &ambient);
        assert_eq!(
            partition.kept.len(),
            1,
            "closed specialized post must be kept: {:?}",
            partition
        );
        assert!(
            partition.dropped.is_empty(),
            "closed specialized post must not be dropped: {:?}",
            partition.dropped
        );
    }

    #[test]
    fn silent_drop_ratchet_call_term_missing_args_is_loud_decode_fail() {
        // Ctor collected without an args array: specialization cannot bind
        // formals. Must record CallTermDecodeFailed -- never a silent skip
        // that leaves dropped empty while ambient posts exist for that call.
        let ambient = vec![ambient_post_encode_base64(
            json!({
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "eHl6"
                    }
                ]
            }),
            vec!["value".to_string()],
        )];
        let inv = json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "ctor", "name": "call:encodeBase64"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": "AAAA"
                }
            ]
        });
        let partition = linked_ambient_post_instances_for_inv(&inv, &ambient);
        assert!(
            partition.kept.is_empty(),
            "decode-fail call term must not keep posts: {:?}",
            partition.kept
        );
        assert!(
            !partition.dropped.is_empty(),
            "LAW VIOLATION: missing-args call term with ambient posts must loud-drop, not silent-skip"
        );
        assert!(
            partition
                .dropped
                .iter()
                .any(|d| d.reason == DroppedAmbientPostReason::CallTermDecodeFailed),
            "expected call-term-decode-failed among {:?}",
            partition
                .dropped
                .iter()
                .map(|d| d.reason.label())
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn silent_drop_ratchet_dropped_reason_labels_are_stable() {
        // Wire labels are load-bearing for assess_dropped_ambient_posts reason
        // strings and IDE/logs. Renaming without updating the assess gate is a
        // silent-green class failure mode.
        assert_eq!(
            DroppedAmbientPostReason::OpenAfterSpecialization.label(),
            "open-after-specialization"
        );
        assert_eq!(
            DroppedAmbientPostReason::OpaqueCallSubject.label(),
            "opaque-call-subject"
        );
        assert_eq!(
            DroppedAmbientPostReason::CallTermDecodeFailed.label(),
            "call-term-decode-failed"
        );
    }
}
