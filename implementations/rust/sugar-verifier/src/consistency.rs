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

use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::Arc;

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
    /// Each `global:<name>` input the row's claims read that its contract
    /// states no value for (`bind_own_inputs_with_unstated`): a free
    /// variable of the row, over every value of which the row is decided
    /// (`decide_over_unstated_inputs`).
    unstated_inputs: Vec<String>,
}

/// Does this contract carry asserted axioms that must be checked for
/// satisfiability against the local universe? We approximate the boundary
/// structurally: the pass fires for contracts that carry an `inv` and NO
/// `pre`. A `post` is allowed and is conjoined with the asserted `inv` as the
/// lifted universe relation where the `inv` reads the contract's result
/// (`axiom_context_formula`). Pre-bearing contracts remain the call-site path's
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
    // A class's stated ancestry is a fact its module's proof states, joined
    // into a consumer's obligation (`with_exception_ancestry`), never a claim
    // checked on its own. So is a class's stated namespace, read by the
    // dispatch of a method call (`dispatched_target`, step 8).
    !is_setup_binding_name(name)
        && !name.ends_with(EXCEPTION_ANCESTRY_SUFFIX)
        && !name.ends_with(CLASS_NAMESPACE_SUFFIX)
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

const CRC_VALUE_PIN_SUFFIX: &str = "::crc-value-pin";
const ASSERTION_SUFFIX: &str = "::assertion";

fn has_source_warrant(body: &Json, role: &str, universe_kind: &str) -> bool {
    body.get("sourceWarrants")
        .or_else(|| body.get("source_warrants"))
        .and_then(Json::as_array)
        .is_some_and(|warrants| {
            warrants.iter().any(|warrant| {
                warrant.get("role").and_then(Json::as_str) == Some(role)
                    && warrant.get("universe_kind").and_then(Json::as_str) == Some(universe_kind)
            })
        })
}

fn formula_contains_atomic(node: &Json, atom_name: &str) -> bool {
    if node.get("kind").and_then(Json::as_str) == Some("atomic")
        && node.get("name").and_then(Json::as_str) == Some(atom_name)
    {
        return true;
    }
    ["operands", "args"].iter().any(|field| {
        node.get(field)
            .and_then(Json::as_array)
            .is_some_and(|children| {
                children
                    .iter()
                    .any(|child| formula_contains_atomic(child, atom_name))
            })
    })
}

fn is_warranted_crc_value_pin(candidate: &ConsistencyCandidate) -> bool {
    contract_property_name(&candidate.body).ends_with(CRC_VALUE_PIN_SUFFIX)
        && has_source_warrant(&candidate.body, "java.crc-value-pin", "crc32.eq-walked")
        && candidate
            .body
            .get("inv")
            .is_some_and(|inv| formula_contains_atomic(inv, "crc32.eq-walked"))
}

fn consistency_group_name(candidate: &ConsistencyCandidate) -> String {
    let name = contract_property_name(&candidate.body);
    if is_warranted_crc_value_pin(candidate) {
        if let Some(location) = name.strip_suffix(CRC_VALUE_PIN_SUFFIX) {
            return format!("{location}{ASSERTION_SUFFIX}");
        }
    }
    name.to_string()
}

/// Every consistency group in `pool`, by name, and whether a staged import
/// spoke every candidate in it (step 9). The grouping is the solve's own
/// (`consistency_group_name` over `collect_consistency_candidates`), so a
/// result's `property_name` names its group.
pub(crate) fn groups_spoken_only_by_imports(pool: &MementoPool) -> BTreeMap<String, bool> {
    let (candidates, _provenance_refusals) = collect_consistency_candidates(pool);
    let mut groups: BTreeMap<String, bool> = BTreeMap::new();
    for candidate in &candidates {
        let only_imports = groups
            .entry(consistency_group_name(candidate))
            .or_insert(true);
        *only_imports &= candidate.spoken_by_vendor;
    }
    groups
}

/// Is this consistency result an imported proof's own row (step 9)? Its
/// contract was spoken by a staged import (`MementoPool::is_vendor_member`)
/// and so was every other candidate of its group. A group the project speaks
/// any candidate of is the project's row: a consumer's claim conjoined with
/// an import's stays the consumer's to answer. A provenance refusal is one
/// contract, its own group.
pub(crate) fn result_is_imported(
    pool: &MementoPool,
    groups: &BTreeMap<String, bool>,
    result: &ConsistencyResult,
) -> bool {
    pool.is_vendor_member(&result.contract_cid)
        && groups
            .get(&result.property_name)
            .copied()
            .unwrap_or(true)
}

fn has_crc_value_pin_assertion_pair(
    property_name: &str,
    candidates: &[ConsistencyCandidate],
) -> bool {
    let has_pin = candidates.iter().any(is_warranted_crc_value_pin);
    let has_assertion = candidates.iter().any(|candidate| {
        contract_property_name(&candidate.body) == property_name
            && property_name.ends_with(ASSERTION_SUFFIX)
            && has_source_warrant(&candidate.body, "java.test-fact", "vendor-fixedpoint")
    });
    has_pin && has_assertion
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
    // Custom execution-witness packages (cargo-test / pytest suite packages)
    // are Derived by construction: discharge is package recompute, not source
    // statement. Sealed mementos sometimes carry `evidence` only on the header
    // (body is inv atomCid alone) and historically dropped proofirProvenance —
    // refuse-for-missing then made the whole showcase witness row refuse
    // (A2 expected-discharge-got-refused / rust-witness). Default Derived when
    // the memento is recognizably a custom execution-witness package.
    if is_execution_witness_package(member, body) {
        return Ok(ProofIrProvenanceKind::Derived);
    }
    Err(
        "contract memento lacks required proofirProvenance/sourceWarrants provenance KIND"
            .to_string(),
    )
}

/// True when this contract is a custom execution-witness package (cargo-test /
/// pytest suite package). Evidence may live on the sealed header while the
/// body holds only the inv atom — so header and body both count.
fn is_execution_witness_package(member: &StoredMember, body: &Json) -> bool {
    if is_witness_member(body) {
        return true;
    }
    if member
        .field("evidence")
        .and_then(|e| e.get("proofType"))
        .and_then(|v| v.as_str())
        == Some("custom")
    {
        return true;
    }
    let name = contract_property_name(body);
    name.starts_with("witness-package:")
        || member
            .field("name")
            .and_then(|n| n.as_str())
            .is_some_and(|n| n.starts_with("witness-package:"))
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

/// The formula the consistency pass checks for one contract: its asserted
/// `inv`, and its `post` where the claim reads the contract's result.
///
/// A `post` relates the result binding (`out`) to the formals. A claim that
/// reads the result is checked against it, so a proof cannot carry an
/// assertion fact that contradicts its own universe contract. A claim that
/// does not read the result is not constrained by it, and the post is not
/// conjoined: a function's assertions are its `inv` and its `post` defines
/// its result on the one contract row (#8292), and that definition is neither
/// a claim nor a sibling of one. Conjoined regardless, it made a decided
/// claim (`and([])`, which the vacuity guard admits alone) read as the lone
/// constraint `out = <result>` and be refused, and it gave a lone opaque
/// claim the sibling the vacuity guard asks for, so it came back satisfiable
/// and discharged (#8416).
fn axiom_context_formula(body: &Json) -> Json {
    let inv = body.get("inv").cloned().unwrap_or(Json::Null);
    match body.get("post").filter(|post| post.is_object()).cloned() {
        Some(post) if formula_reads_var(&inv, contract_out_binding(body)) => {
            IrFormula::And(vec![inv, post]).to_value()
        }
        _ => inv,
    }
}

/// The name a contract's `post` binds its result to: `outBinding`, or `out`.
/// The one reader, for the join (`bridge_answer`) and for the contract's own
/// consistency formula (`axiom_context_formula`).
fn contract_out_binding(body: &Json) -> &str {
    body.get("outBinding")
        .or_else(|| body.get("out_binding"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("out")
}

/// True if a `var` named `name` occurs anywhere in the formula/term tree
/// (`operands`/`args`/`body`, the children `formula_is_closed` walks).
fn formula_reads_var(node: &Json, name: &str) -> bool {
    if node.get("kind").and_then(Json::as_str) == Some("var")
        && node.get("name").and_then(Json::as_str) == Some(name)
    {
        return true;
    }
    if node.get("body").is_some_and(|body| formula_reads_var(body, name)) {
        return true;
    }
    ["operands", "args"].iter().any(|field| {
        node.get(field)
            .and_then(Json::as_array)
            .is_some_and(|children| children.iter().any(|child| formula_reads_var(child, name)))
    })
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
///
/// `py.complex` is a value (Python complex literal), not an operator — dual
/// faces `call:A()=py.complex(0,2)` vs `call:A()=py.complex(0,3)` must refuse
/// structurally (#4398). `py.ellipsis` is Python's Ellipsis singleton — dual
/// `call:A()=py.ellipsis` vs `call:A()=None` must refuse (#4387 residue).
/// Arithmetic/`call:abs` stay out: abs is folded by
/// [`fold_ground_applications`], arithmetic remains SMT theory.
fn is_ground_data_ctor_name(name: &str) -> bool {
    matches!(
        name,
        "tuple"
            | "array"
            | "None"
            | "py.complex"
            | "py.ellipsis"
            // Module / type coordinates are structural identities (BuiltinModuleName /
            // BuiltinTypeName floors), not operators — dual faces
            // `call:A()=python:module("pytest")` vs `call:A()=None` must refuse
            // (#4387 builtin_module_name_truthy).
            | "python:module"
            | "python:type"
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

/// Fold grounded primitive applications inside a formula/term so consistency
/// sees concrete values instead of uninterpreted constructors (#4398).
///
/// Today: `call:abs(<Int const>) → |n|`. Arithmetic operators (`+`, `*`, …)
/// intentionally stay uninterpreted here — SMT theory already owns them, and
/// structural dual faces must not treat `+(5,1)` as the value `6` (#3924).
fn fold_ground_applications(node: &Json) -> Json {
    match node {
        Json::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                if k == "args" || k == "operands" {
                    if let Some(arr) = v.as_array() {
                        out.insert(
                            k.clone(),
                            Json::Array(arr.iter().map(fold_ground_applications).collect()),
                        );
                        continue;
                    }
                }
                out.insert(k.clone(), fold_ground_applications(v));
            }
            let folded = Json::Object(out);
            if let Some(reduced) = fold_ground_ctor_once(&folded) {
                return reduced;
            }
            folded
        }
        Json::Array(arr) => Json::Array(arr.iter().map(fold_ground_applications).collect()),
        other => other.clone(),
    }
}

/// One-step fold for a fully-grounded primitive application ctor.
fn fold_ground_ctor_once(node: &Json) -> Option<Json> {
    if node.get("kind").and_then(|k| k.as_str()) != Some("ctor") {
        return None;
    }
    let name = node.get("name").and_then(|n| n.as_str())?;
    let args = node.get("args").and_then(|v| v.as_array())?;
    match name {
        "call:abs" if args.len() == 1 => {
            let n = int_const_value_i128(&args[0])?;
            // Refuse to fold i128::MIN (no signed magnitude); leave uninterpreted.
            let abs_n = n.checked_abs()?;
            Some(int_const_json(abs_n))
        }
        _ => None,
    }
}

fn int_const_json(value: i128) -> Json {
    // Prefer i64 wire when it fits; otherwise emit as number via serde (i128
    // that exceeds i64 still serializes). Witness seeds use ordinary Ints.
    if let Ok(v) = i64::try_from(value) {
        json!({
            "kind": "const",
            "value": v,
            "sort": {"kind": "primitive", "name": "Int"},
        })
    } else {
        json!({
            "kind": "const",
            "value": value,
            "sort": {"kind": "primitive", "name": "Int"},
        })
    }
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

    // Python control-flow guards emit `py.eq` / `py.lt` / `identity` / `py.in`,
    // not bare IR `=` / `<`. Vendor posts specialize those guards at grounded
    // callsites (`py.eq(1,1) => out=7`); without evaluating them, implies arms
    // never open and lying arms stay SAT (#4398).
    if name == "py.in" {
        return eval_ground_py_in(&args[0], &args[1]);
    }
    if name == "identity" {
        return eval_ground_identity(&args[0], &args[1]);
    }

    // Int comparisons: IR and Python predicate names share the same law.
    if let (Some(left), Some(right)) = (
        int_const_value_i128(&args[0]),
        int_const_value_i128(&args[1]),
    ) {
        return match name {
            "<" | "py.lt" => Some(left < right),
            ">" | "py.gt" => Some(left > right),
            "\u{2264}" | "<=" | "py.le" => Some(left <= right),
            "\u{2265}" | ">=" | "py.ge" => Some(left >= right),
            "=" | "py.eq" => Some(left == right),
            "\u{2260}" | "!=" | "py.ne" => Some(left != right),
            _ => None,
        };
    }

    // Ground structural equality for non-int values (None, tuples, complex):
    // only when both sides are closed data values. Never orient free vars.
    if matches!(name, "=" | "py.eq") && is_const_value(&args[0]) && is_const_value(&args[1]) {
        return Some(ground_values_equal(&args[0], &args[1]));
    }
    if matches!(name, "\u{2260}" | "!=" | "py.ne")
        && is_const_value(&args[0])
        && is_const_value(&args[1])
    {
        return Some(!ground_values_equal(&args[0], &args[1]));
    }
    None
}

fn eval_ground_identity(left: &Json, right: &Json) -> Option<bool> {
    // Python `is` / `is not`: only when both sides are ground values. A free
    // var or opaque call leaves the guard unevaluable (honest None).
    if !is_const_value(left) || !is_const_value(right) {
        return None;
    }
    Some(ground_values_equal(left, right))
}

fn eval_ground_py_in(needle: &Json, haystack: &Json) -> Option<bool> {
    if !is_const_value(needle) {
        return None;
    }
    if haystack.get("kind").and_then(|k| k.as_str()) != Some("ctor") {
        return None;
    }
    let name = haystack.get("name").and_then(|n| n.as_str())?;
    if !matches!(name, "tuple" | "array" | "python:tuple" | "python:list") {
        return None;
    }
    let args = haystack.get("args").and_then(|v| v.as_array())?;
    if !args.iter().all(is_const_value) {
        return None;
    }
    Some(args.iter().any(|item| ground_values_equal(needle, item)))
}

fn ground_values_equal(left: &Json, right: &Json) -> bool {
    let left_key = libsugar::canonical::json_jcs(&federate_primitive_sorts(left))
        .unwrap_or_else(|_| compact_json(left));
    let right_key = libsugar::canonical::json_jcs(&federate_primitive_sorts(right))
        .unwrap_or_else(|_| compact_json(right));
    left_key == right_key
}

fn int_const_value_i128(node: &Json) -> Option<i128> {
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
    let value = node.get("value")?;
    if let Some(v) = value.as_i64() {
        return Some(i128::from(v));
    }
    if let Some(v) = value.as_u64() {
        return Some(i128::from(v));
    }
    if let Some(s) = value.as_str() {
        return s.parse::<i128>().ok();
    }
    None
}

fn compact_json(value: &Json) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "<json>".to_string())
}

/// Witness package bodies the proof states, keyed by `witness_cid`.
///
/// Step 9 (owner, 2026-11-13; ruling 4 on #7766): prove reads `.proof` files
/// only and executes nothing. Mint packages each witness body into its
/// `witness-memento` member (`body_b64`); the solve reads it from there. No kit
/// is asked to resolve or re-run a witness, so there is no resolver, no project
/// directory and no RPC on this path. A witness row whose body the proof does
/// not state is undecided by name.
pub type WitnessBodies = BTreeMap<String, Vec<u8>>;

/// The witness bodies a pool's `witness-memento` members state. A member whose
/// `body_b64` does not decode, or does not address to its `witnessCid`, states
/// no body (mint refuses such a member; a hand-made proof gets no say here).
fn witness_bodies_in_pool(pool: &MementoPool) -> WitnessBodies {
    let mut bodies = WitnessBodies::new();
    for (_cid, member) in pool.witness_memento_members() {
        let Some(witness_cid) = member
            .field("witnessCid")
            .or_else(|| member.field("witness_cid"))
            .and_then(Json::as_str)
        else {
            continue;
        };
        let Some(bytes) = member
            .field("body_b64")
            .and_then(Json::as_str)
            .and_then(|text| B64.decode(text).ok())
        else {
            continue;
        };
        if blake3_512_of(&bytes) == witness_cid {
            bodies.insert(witness_cid.to_string(), bytes);
        }
    }
    bodies
}

#[derive(Debug, Clone)]
struct WitnessPackageClaim {
    package_cid: String,
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
/// **Step 9:** the package body comes only from the proof (the
/// `witness-memento` member's `body_b64`, see [`WitnessBodies`]); verification
/// is always Rust [`package_outcome`] (blake3 vs packageCid + committed outcomes).
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
    let claim = match witness_package_claim(evidence, tool) {
        Ok(c) => c,
        Err(e) => return Some(undecidable(e)),
    };
    // Step 9: the body comes from the proof, never from a kit.
    let Some(bytes) = active_witness_bodies().get(&claim.package_cid).cloned() else {
        return Some(undecidable(format!(
            "witness package {} has no body in the proof; prove resolves no witness \
             by reaching back to a kit (step 9), so this row is undecided",
            claim.package_cid
        )));
    };
    Some(seal_witness_package_outcome(
        package_outcome(&bytes, "proof", &claim),
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
        // A package with no outcome witnessed no test: it decides nothing, so it
        // is not a discharge (green means decided, #7848). "All 0 passed" is
        // vacuous; the row is undecided by name.
        Ok(outcome) if outcome.count == 0 => {
            let reason = format!(
                "witness package verified by rust via {} has no outcomes: no test was \
                 witnessed, so the package decides nothing",
                outcome.resolved_by
            );
            ConsistencyResult {
                contract_cid,
                property_name,
                verdict: ObligationVerdict::Undecidable,
                reason: reason.clone(),
                effect: None,
                witnessed: false,
                locus: None,
                verification: Some(VerificationDetail::Witness {
                    witnessed: false,
                    verdict: ObligationVerdict::Undecidable.as_str().to_string(),
                    resolved_by: Some(outcome.resolved_by.clone()),
                    outcomes: Some(0),
                    failed: Some(0),
                    failed_tests: None,
                    reason,
                }),
                dropped_ambient_posts: Vec::new(),
            }
        }
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
    // An execution-witness tool with no package-outcome mapping is refused
    // (fail-closed), as before.
    if !matches!(
        tool,
        "pytest" | "cargo-test" | "junit" | "testng" | "build-witness"
    ) {
        return Err(format!(
            "custom witness tool {tool:?} has no rust-side package outcome mapping \
             (fail-closed)"
        ));
    }
    Ok(WitnessPackageClaim {
        package_cid,
        expected_count,
        expected_passed,
    })
}

// Thread-local witness bodies: set for the duration of
// `verify_consistency_from_index` so deep call sites (par_iter group
// solve → `try_witness_discharge`) read the bodies the proof states without
// threading them through every private helper.
thread_local! {
    static ACTIVE_WITNESS_BODIES: std::cell::RefCell<Arc<WitnessBodies>> =
        std::cell::RefCell::new(Arc::new(WitnessBodies::new()));
}

struct WitnessBodiesGuard {
    prev: Arc<WitnessBodies>,
}

impl WitnessBodiesGuard {
    fn enter(bodies: &Arc<WitnessBodies>) -> Self {
        let prev =
            ACTIVE_WITNESS_BODIES.with(|c| std::mem::replace(&mut *c.borrow_mut(), bodies.clone()));
        Self { prev }
    }
}

impl Drop for WitnessBodiesGuard {
    fn drop(&mut self) {
        let prev = std::mem::replace(&mut self.prev, Arc::new(WitnessBodies::new()));
        ACTIVE_WITNESS_BODIES.with(|c| *c.borrow_mut() = prev);
    }
}

fn active_witness_bodies() -> Arc<WitnessBodies> {
    ACTIVE_WITNESS_BODIES.with(|c| c.borrow().clone())
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
    // Flatten nested `and` so `and([and([a,b,c])])` (loop-unroll / mint wrap
    // shape) yields three sibling constraints, not one. Vacuity and provenance
    // conjoin both count join partners at this level — a double-wrapped
    // conjunction of three ground eqs is not a lone opaque equality (#A2
    // forall-loop / bulk crate refuse).
    if let Some(operands) = IrFormula::and_operands(&formula) {
        let mut out = Vec::with_capacity(operands.len());
        for operand in operands {
            out.extend(top_level_conjuncts(operand.clone()));
        }
        return out;
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
    let portfolio_seats: Vec<&str> = invs
        .iter()
        .map(|inv| inv.result.solver_name.as_str())
        .collect();
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
                    "seatState": inv.seat_state(),
                    "portfolioSeats": &portfolio_seats,
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
/// Nested `and` is flattened (see [`top_level_conjuncts`]):
/// `and([and([a, b, c])])` contributes 3, not 1. Bare non-`and` shapes
/// (atomic, forall, implies, …) contribute 1. Empty conjunction contributes 0.
/// Used to gate the consistency-SAT check: a lone constraint with no sibling
/// is trivially satisfiable (any uninterpreted callsite satisfies it) and must
/// NOT count as a substantive discharge — there is nothing to contradict it.
fn count_top_level_constraints(inv: &Json) -> usize {
    top_level_conjuncts(inv.clone()).len()
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
    // A claim whose only atoms are equalities of two literals of one sort is a
    // closed claim over interpreted values: connectives over the empty
    // conjunction (the IR's truth) and `=(<literal>, <literal>)`. It names no
    // symbol the solver could leave uninterpreted, so the solver's answer is
    // forced and substantive.
    if is_closed_literal_formula(inv) {
        return true;
    }
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
    is_ground_regex_membership(node) || is_ground_string_theory_predicate(node)
}

/// True when `inv` is built from connectives whose every leaf is an operand-less
/// `and`/`or` or a literal equality ([`is_literal_equality`]). Such a claim has
/// no free variable, no binder and no symbol any solver theory reads as
/// uninterpreted, so whether it holds is its satisfiability. A ground atom over
/// an uninterpreted symbol is deliberately not this: `py.eq(6, 7)` is closed,
/// but the SMT encoding leaves `py.eq` uninterpreted and a solver satisfies it,
/// so it still needs a covering universe.
fn is_closed_literal_formula(inv: &Json) -> bool {
    match inv.get("kind").and_then(|k| k.as_str()) {
        Some("and" | "or" | "not" | "implies") => inv
            .get("operands")
            .and_then(|v| v.as_array())
            .is_some_and(|operands| operands.iter().all(is_closed_literal_formula)),
        Some("atomic") => is_literal_equality(inv),
        _ => false,
    }
}

/// `=(a, b)` with `a` and `b` literal constants of one sort. The lifter states
/// a Python `==` of two decided values of one sort this way (a string equality
/// is a fact, never a lift-time fold: `StringValue` has no `equals` override,
/// `resolve_equality_atom` states `=` for a same-sort pair). FOL `=` over two
/// literals of an interpreted sort is decided by the theory itself: two string
/// literals are equal exactly when they are the same string. So
/// `=("YWJj", "YWJj")` is true and `=("YWJj", "AAAA")` is false, with no
/// model to choose.
fn is_literal_equality(node: &Json) -> bool {
    if node.get("name").and_then(|v| v.as_str()) != Some("=") {
        return false;
    }
    let Some([left, right]) = node
        .get("args")
        .and_then(|v| v.as_array())
        .map(Vec::as_slice)
    else {
        return false;
    };
    let is_literal = |term: &Json| term.get("kind").and_then(|k| k.as_str()) == Some("const");
    is_literal(left)
        && is_literal(right)
        && left.get("sort").is_some()
        && left.get("sort") == right.get("sort")
}

/// `inv` with each atom Python decides over literal operands replaced by the
/// IR's truth (`and([])`) or falsity (`or([])`), outside quantifiers.
///
/// Since step 5 (#7757) a root's claims are over its free inputs, and prove
/// binds each `global:<name>` to the value the contract states
/// (`bind_own_inputs`): `assert X == 3` arrives as
/// `python:compare.completes(python:compare("Eq", 3, 3, <key>))` and
/// `py.eq(3, 3)`. The lift decided that claim before step 5; here it is
/// closed over literals, and Python's answer is forced
/// (`decided_python_atom`), so it is stated as that answer: a closed literal
/// formula (`is_closed_literal_formula`) every solver reads alike. An atom
/// over anything else stays as it was.
fn fold_decided_python_atoms(node: &Json) -> Json {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("and" | "or" | "not" | "implies") => {
            let mut out = node.clone();
            if let Some(operands) = node.get("operands").and_then(|v| v.as_array()) {
                let folded = operands.iter().map(fold_decided_python_atoms).collect();
                out["operands"] = Json::Array(folded);
            }
            out
        }
        Some("atomic") => match decided_python_atom(node) {
            Some(true) => json!({"kind": "and", "operands": []}),
            Some(false) => json!({"kind": "or", "operands": []}),
            None => node.clone(),
        },
        _ => node.clone(),
    }
}

/// Python's answer to an atom over literal operands, where the language
/// fixes it: `=` / `py.eq` of two `int` literals or two `str` literals is
/// their equality, and `==` / `!=` between `int` and `str` literals always
/// completes (`python:compare.completes(python:compare("Eq" | "NotEq", a,
/// b, <key>))`: neither type's `__eq__` raises). An ordering (`Lt`, `LtE`,
/// `Gt`, `GtE`) of two `int` literals always completes and one of an `int`
/// and a `str` never does (`TypeError`). `None` for anything else.
fn decided_python_atom(node: &Json) -> Option<bool> {
    let name = node.get("name").and_then(|v| v.as_str())?;
    let args = node.get("args").and_then(|v| v.as_array())?;
    match (name, args.as_slice()) {
        ("=" | "py.eq", [left, right]) => {
            let ints = (int_const_value_i128(left), int_const_value_i128(right));
            if let (Some(a), Some(b)) = ints {
                return Some(a == b);
            }
            if let (Some(a), Some(b)) = (str_const_value(left), str_const_value(right)) {
                return Some(a == b);
            }
            None
        }
        ("python:compare.completes", [operation]) => {
            if operation.get("kind").and_then(|k| k.as_str()) != Some("ctor")
                || operation.get("name").and_then(|n| n.as_str()) != Some("python:compare")
            {
                return None;
            }
            let [operator, left, right, _key] =
                operation.get("args").and_then(|v| v.as_array())?.as_slice()
            else {
                return None;
            };
            let operator = str_const_value(operator)?;
            let literal = |term: &Json| {
                int_const_value_i128(term).is_some() || str_const_value(term).is_some()
            };
            if matches!(operator, "Lt" | "LtE" | "Gt" | "GtE") {
                // An ordering of two ints always completes; an int against
                // a str is Python's TypeError. Two strs are not decided here
                // (the emitter states no str order either).
                let int = |term: &Json| int_const_value_i128(term).is_some();
                let string = |term: &Json| str_const_value(term).is_some();
                return match (int(left), int(right), string(left), string(right)) {
                    (true, true, _, _) => Some(true),
                    (true, _, _, true) | (_, true, true, _) => Some(false),
                    _ => None,
                };
            }
            (matches!(operator, "Eq" | "NotEq") && literal(left) && literal(right)).then_some(true)
        }
        _ => None,
    }
}

/// The value of a `str` literal: a `const` of primitive sort `String`.
fn str_const_value(node: &Json) -> Option<&str> {
    if node.get("kind").and_then(|k| k.as_str()) != Some("const") {
        return None;
    }
    let sort = node.get("sort")?;
    if sort.get("kind").and_then(|v| v.as_str()) != Some("primitive")
        || sort.get("name").and_then(|v| v.as_str()) != Some("String")
    {
        return None;
    }
    node.get("value")?.as_str()
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

/// A binary string-theory predicate (`prefix-of` / `suffix-of` / `contains`) whose
/// BOTH operands are pinned ground terms (closed, no uninterpreted `call:` ctor).
/// The Rust string-predicate lifter emits these atoms for literal receivers
/// (`"abc".starts_with("a")` → `prefix-of("a","abc")`); z3's string sort decides
/// them outright — the same covering-universe law as regex membership, a different
/// string theory atom. Uninterpreted method EUF (`method:starts_with(...)`) is NOT
/// covered here: that remains vacuous without a body universe or a sibling.
fn is_ground_string_theory_predicate(node: &Json) -> bool {
    if node.get("kind").and_then(|k| k.as_str()) != Some("atomic") {
        return false;
    }
    let Some(name) = node.get("name").and_then(|v| v.as_str()) else {
        return false;
    };
    if !matches!(name, "prefix-of" | "suffix-of" | "contains") {
        return false;
    }
    let Some(args) = node.get("args").and_then(|v| v.as_array()) else {
        return false;
    };
    if args.len() != 2 {
        return false;
    }
    args.iter()
        .all(|arg| formula_is_closed(arg, &mut Vec::new()) && !term_has_opaque_call(arg))
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
    // Fold grounded primitive applications (`call:abs(-5)` → `5`) before
    // structural dual / SMT. Without this, vendor posts that return a grounded
    // constructor stay uninterpreted and lying arms SAT (#4398).
    let folded = fold_decided_python_atoms(&fold_ground_applications(&inv));
    let inv = with_local_forall_instances(canonicalize_formula_json(&folded), property_name);
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
    // subject is regex-as-language membership; ground `prefix-of`/`suffix-of`/
    // `contains` are string-theory predicates. In both cases z3 returns real
    // SAT/UNSAT, so the lone fact is a substantive verdict and must reach the
    // solver. Vacuous is therefore: alone in the bucket AND no covering universe
    // — not merely count<2.
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
    // A satisfiable claim is green only when it is satisfiable as Python reads
    // `==`: never on a model that answered a free `py.eq` (#8416).
    let (verdict, reason, effect) = if verdict == ObligationVerdict::Discharged
        && !py_eq_reading_confirms(&inv, plan, registry, compilers)
    {
        (
            ObligationVerdict::Undecidable,
            format!(
                "consistency check undecidable: `{property_name}` is satisfiable only through a `py.eq` over an operand whose builtin type is not stated [{raw_reason}]"
            ),
            None,
        )
    } else {
        (verdict, reason, effect)
    };
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

/// Does `node` hold a `py.eq` atom anywhere?
fn reads_py_eq(node: &Json) -> bool {
    if node.get("kind").and_then(Json::as_str) == Some("atomic") {
        return node.get("name").and_then(Json::as_str) == Some("py.eq");
    }
    node.get("body").is_some_and(reads_py_eq)
        || node
            .get("operands")
            .and_then(Json::as_array)
            .is_some_and(|operands| operands.iter().any(reads_py_eq))
}

/// `node` with each `py.eq` atom read only over `str` / `int` operands
/// (`python:value.builtin`, one atom per operand that is not a literal). At a
/// positive position `py.eq(a, b)` becomes `and(py.eq(a, b), builtin(a),
/// builtin(b))`; at a negative one `implies(and(builtin(a), builtin(b)),
/// py.eq(a, b))`. The result implies `node`, and in each of its models every
/// `py.eq` that decides it reads typed operands, never the free branch.
/// `changed` is set when an atom was rewritten. `None` when a `py.eq` sits
/// under a connective whose polarity is not read here.
fn py_eq_over_builtins(node: &Json, positive: bool, changed: &mut bool) -> Option<Json> {
    let rebuild = |node: &Json,
                   polarities: &dyn Fn(usize) -> bool,
                   changed: &mut bool|
     -> Option<Json> {
        let mut out = node.clone();
        if let Some(operands) = node.get("operands").and_then(Json::as_array) {
            let rewritten = operands
                .iter()
                .enumerate()
                .map(|(index, operand)| py_eq_over_builtins(operand, polarities(index), changed))
                .collect::<Option<Vec<Json>>>()?;
            out["operands"] = Json::Array(rewritten);
        }
        if let Some(body) = node.get("body") {
            out["body"] = py_eq_over_builtins(body, polarities(0), changed)?;
        }
        Some(out)
    };
    match node.get("kind").and_then(Json::as_str) {
        Some("atomic") => {
            if node.get("name").and_then(Json::as_str) != Some("py.eq") {
                return Some(node.clone());
            }
            let builtins: Vec<Json> = node
                .get("args")
                .and_then(Json::as_array)
                .into_iter()
                .flatten()
                .filter(|arg| arg.get("kind").and_then(Json::as_str) != Some("const"))
                .map(|arg| {
                    json!({
                        "kind": "atomic",
                        "name": sugar_ir_compiler_smt_lib::PYTHON_VALUE_BUILTIN,
                        "args": [arg]
                    })
                })
                .collect();
            if builtins.is_empty() {
                return Some(node.clone());
            }
            *changed = true;
            Some(if positive {
                let mut operands = vec![node.clone()];
                operands.extend(builtins);
                json!({"kind": "and", "operands": operands})
            } else {
                json!({"kind": "implies", "operands": [
                    {"kind": "and", "operands": builtins},
                    node.clone()
                ]})
            })
        }
        Some("and") | Some("or") | Some("forall") | Some("exists") => {
            rebuild(node, &|_: usize| positive, changed)
        }
        Some("not") => rebuild(node, &|_: usize| !positive, changed),
        // The antecedent is read negatively, the consequent as the whole.
        Some("implies") => rebuild(node, &|index: usize| (index != 0) == positive, changed),
        _ if reads_py_eq(node) => None,
        _ => Some(node.clone()),
    }
}

/// Is a satisfiable `inv` satisfiable as Python reads `==` (#8416)?
///
/// The claim is decided by satisfiability: `discharged` is "the negation of
/// `inv` is not valid", not "the negation of the claim is refuted". The
/// SMT-LIB backend reads `py.eq` over an operand whose builtin type is not
/// stated as the free application on its last branch, and a model may answer
/// that application either way: sound for a refutation (unsatisfiable under
/// every reading), never for satisfiability. So the claim is confirmed with
/// every `py.eq` read over `str` / `int` operands (`py_eq_over_builtins`),
/// which implies `inv` and never reaches the free branch: satisfiable then is
/// satisfiable as Python reads it. `true` when `inv` reads no `py.eq` over
/// anything but literals; `false` when the confirmation is not satisfiable or
/// a `py.eq` sits where its polarity is not read.
fn py_eq_reading_confirms(
    inv: &Json,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> bool {
    let mut changed = false;
    let Some(strict) = py_eq_over_builtins(inv, true, &mut changed) else {
        return false;
    };
    if !changed {
        return true;
    }
    let goal = IrFormula::Not(strict).to_value();
    match CompilerInput::decode_json(goal) {
        Ok(input) => {
            run_plan_with_compilers(plan, registry, compilers, &input).0
                == ObligationVerdict::Unsatisfied
        }
        Err(_) => false,
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
    /// #3807: speaker provenance rides each ambient conjunct from pool intake.
    /// Vendor-spoken ambient facts alone may surface as `vendorFactIr`;
    /// consumer-spoken peers still CONJOIN for solver soundness but never
    /// masquerade as the vendor half of a report row. Constructed at collect
    /// time from `ConsistencyCandidate::spoken_by_vendor` — not re-inferred.
    spoken_by_vendor: bool,
}

/// Collect closed ground facts about concrete callsite terms. A literal-domain
/// loop replay may emit `call:g(3) == 1` rather than a universal. That fact
/// constrains sibling `#euf#` obligations about the SAME concrete call term
/// (`TermKey` = full JCS of the `call:*` ctor, args included -- never the bare
/// callee name). Derived testimony joins pool-wide on that key; Stated peer
/// claims stay same-scope so a good/bad twin pair can coexist (#3884). We collect
/// only ground equalities whose subject is a `call:*` ctor; local variables and
/// non-call helper ctors never travel.
///
/// `spoken_by_vendor` is the speaker stamp of the candidate this formula was
/// collected from (#3807 provenance rides the conjuncts). Own-origin
/// extractions (current obligation, client-fact scan) pass `false`.
fn collect_ambient_ground_callsite_facts(
    inv: &Json,
    source: &Attribution,
    scope: &Option<Scope>,
    provenance_kind: ProofIrProvenanceKind,
    spoken_by_vendor: bool,
    out: &mut Vec<AmbientGroundCallsiteFact>,
) {
    match inv.get("kind").and_then(|k| k.as_str()) {
        Some("forall") | Some("exists") => {}
        Some("and") => {
            if let Some(ops) = inv.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    collect_ambient_ground_callsite_facts(
                        op,
                        source,
                        scope,
                        provenance_kind,
                        spoken_by_vendor,
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
                    source,
                    scope,
                    provenance_kind,
                    spoken_by_vendor,
                    out,
                );
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
                spoken_by_vendor,
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
        /*spoken_by_vendor=*/ false,
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
        /*spoken_by_vendor=*/ false,
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
        // #3807: display-only vendor vectors must be VENDOR-spoken. A
        // consumer peer about the same callee is not a vendor sworn vector.
        if !fact.spoken_by_vendor {
            continue;
        }
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
    // #3807: solver conjoins every matching ambient fact (soundness), but the
    // VENDOR-FACT label is a projection of speaker provenance only — consumer
    // peers that join by TermKey must not land in `vendorFactIr`.
    let mut vendor_label_facts = Vec::new();
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
            if fact.spoken_by_vendor {
                vendor_label_facts.push(fact.fact.clone());
            }
        }
    }
    if facts.is_empty() {
        return (inv, skipped_same_kind_duplicate, Vec::new());
    }

    let mut operands = Vec::with_capacity(facts.len() + 1);
    operands.push(inv);
    operands.extend(facts);
    (
        IrFormula::And(operands).to_value(),
        skipped_same_kind_duplicate,
        vendor_label_facts,
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
    /// The value the answering contract states for each `global:<name>`
    /// input it decides (`inputValues`, `stated_input_values`): the binder
    /// binds a global the call does not supply to it (step 5).
    stated_inputs: Vec<(String, Json)>,
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
    /// The join's refusals of a contract that answered the call wrongly
    /// (step 9; ruling 2 on #7766). They were the preliminary fold's
    /// `contract_resolution_gap` kinds; prove reads the vendor contract, so
    /// prove refuses. Each one refuses the row it touches by name.
    ///
    /// Two imported bridges state the call's symbol with different targets.
    AmbiguousTarget,
    /// The contract's formals do not match the call's arguments.
    ImportSignatureMismatch,
    /// The bridge targets a member that is not a function contract.
    WrongContractKind,
    /// The bridge pins a provider bundle that does not hold its target.
    WrongProvider,
    /// The bridge's target contract is not in the proofs prove read.
    StaleContractRef,
    /// The join would re-enter a contract it is already instantiating: the
    /// encoding states no recursion, so the call is not answered and stays
    /// owed (never assumed). Not a wrong answer: the row is not decided on
    /// what remains.
    RecursiveContract,
    /// Nothing answers the call or operation at this site: no bridge states
    /// the member's symbol, the answering contract states no post, or the
    /// member has no symbol at all (an owed operation such as `==`). A row
    /// that reads it through a joined contract reads a free value, so it is
    /// not decided on what remains. Not a wrong answer.
    Unanswered,
}

/// One ambient vendor post that matched a callsite but did not enter `linkedPosts`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DroppedAmbientPost {
    pub source_symbol: String,
    pub target_cid: String,
    /// The joined `undecided` member whose answer was dropped; empty when the
    /// claim's call term does not decode to a site, so no member is known.
    /// That member stays owed (`joined_member_cids`).
    pub member_cid: String,
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
            DroppedAmbientPostReason::AmbiguousTarget => "ambiguous-target",
            DroppedAmbientPostReason::ImportSignatureMismatch => "import-signature-mismatch",
            DroppedAmbientPostReason::WrongContractKind => "wrong-contract-kind",
            DroppedAmbientPostReason::WrongProvider => "wrong-provider",
            DroppedAmbientPostReason::StaleContractRef => "stale-or-malformed-contract-ref",
            DroppedAmbientPostReason::RecursiveContract => "recursive-contract",
            DroppedAmbientPostReason::Unanswered => "unanswered",
        }
    }

    /// True for an edge nothing answers (step 9): the member stays owed. The
    /// claim's own read of it is that member's row (`add_undecided_members`);
    /// a read reached through a joined contract leaves the caller's row
    /// undecided (`linked_ambient_post_instances_for_inv`).
    pub fn is_owed(&self) -> bool {
        matches!(
            self,
            DroppedAmbientPostReason::RecursiveContract | DroppedAmbientPostReason::Unanswered
        )
    }

    /// True for the join's refusals: something answered the call, wrongly.
    pub fn is_wrong_answer(&self) -> bool {
        matches!(
            self,
            DroppedAmbientPostReason::AmbiguousTarget
                | DroppedAmbientPostReason::ImportSignatureMismatch
                | DroppedAmbientPostReason::WrongContractKind
                | DroppedAmbientPostReason::WrongProvider
                | DroppedAmbientPostReason::StaleContractRef
        )
    }
}

/// A row whose claim reads a call whose joined answer was dropped is never
/// green on what remains (step 9).
///
/// - A contract answered the call wrongly: the row is refused by name, and
///   the vendor's answer never reaches the solve.
/// - The answer was dropped for any other reason (open after
///   specialization, a call term that does not decode): the call is not
///   answered. The remainder was solved without the post, and a conjunct
///   left out can only turn a contradiction into a satisfiable formula, so a
///   satisfiable (`discharged`) remainder says nothing about the claim: the
///   row is `undecidable`, the drop named. A contradictory remainder stays
///   refuted, since the full conjunction is contradictory too.
fn refuse_dropped_answers(result: &mut ConsistencyResult) {
    let wrong: Vec<String> = result
        .dropped_ambient_posts
        .iter()
        .filter(|d| d.reason.is_wrong_answer())
        .map(|d| format!("{} for {}", d.reason.label(), d.source_symbol))
        .collect();
    if !wrong.is_empty() {
        // A refused row carries its typed effect: the report seat refuses a
        // refused result with none (`VerifyEffectCarrier::from_producer`).
        let effect = VerifyEffect::JoinWrongAnswer {
            property_name: result.property_name.clone(),
            wrong,
        };
        let boundary = effect.to_legacy_boundary();
        result.verdict = boundary.verdict;
        result.reason = boundary.reason;
        result.effect = Some(effect);
        result.verification = None;
        return;
    }
    if result.dropped_ambient_posts.is_empty() || result.verdict != ObligationVerdict::Discharged {
        return;
    }
    let mut dropped: Vec<String> = result
        .dropped_ambient_posts
        .iter()
        .map(|d| {
            if d.reason.is_owed() && !d.member_cid.is_empty() {
                format!(
                    "{} for {} (member {})",
                    d.reason.label(),
                    d.source_symbol,
                    d.member_cid
                )
            } else {
                format!("{} for {}", d.reason.label(), d.source_symbol)
            }
        })
        .collect();
    dropped.dedup();
    result.verdict = ObligationVerdict::Undecidable;
    result.reason = format!(
        "owed: a joined answer was dropped, so the call is unanswered and the row is not decided on what remains ({})",
        dropped.join(", ")
    );
    result.effect = None;
    if let Some(VerificationDetail::Solver { final_verdict, .. }) = result.verification.as_mut() {
        *final_verdict = ObligationVerdict::Undecidable.as_str().to_string();
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
    /// Owed operations a joined post reads (step 9): a completes atom, at the
    /// call's actuals, keyed at a site nothing answers. The row reads it
    /// through the joined contract; unless what the joined posts state decides
    /// the atom, the value is free and the row is not decided on it
    /// (`settle_owed_operations` moves it to `dropped`).
    owed_operations: Vec<(DroppedAmbientPost, Json)>,
    /// Each dispatched method call's member the claim reads itself (step 8),
    /// with whether the read resolved it (`dispatch_answer`).
    dispatched: Vec<(String, bool)>,
}

/// One vendor answer to one unanswered call (step 9): the consumer's
/// `undecided` member (`reason: unanswered`) joined, by its `symbol`, to the
/// imported bridge whose `sourceSymbol` is the same string. `site_cid` is the
/// member's `SourceFragmentCoordinateV1` CID, the first argument of the
/// `python:occurrence` in the `python:call_result` the claim constrains.
#[derive(Debug, Clone)]
struct AmbientPost {
    binding: BridgeBinding,
    post: Json,
    /// The path conditions of the halts the answering contract states (each
    /// panic locus's `guard`, over the contract's formals). The post speaks
    /// of completed arms only; where the call completed
    /// (`PYTHON_CALL_COMPLETES` over its result), each halt's guard is false
    /// under the call's actual. A halt certain on that path refutes every
    /// arm of the claim on which the call completed.
    halt_guards: Vec<Json>,
    /// Every panic locus the answering contract states names its guard
    /// (`contract_guards_every_halt`), so `halt_guards` are all the halts it
    /// can take: the call completes exactly where none of them holds. False
    /// when a locus states no path condition: then nothing says when the call
    /// completes, and only `completes -> not(guard)` is stated.
    every_halt_guarded: bool,
    /// The halts the answering contract states with their raised type:
    /// `(type, guard)` per panic locus whose `argTerm` names the raised
    /// exception's class and that states its guard (`contract_typed_halts`).
    /// What types the exception a call raised (`with_raised_types`).
    typed_halts: Vec<(Json, Json)>,
    /// The joined member's CID.
    member_cid: String,
    site_cid: String,
    /// `Some` when the answer is wrong: the row that reads this call is
    /// refused by name and `post` is never conjoined.
    refusal: Option<DroppedAmbientPostReason>,
    /// `Some` for a dispatched method call's member (step 8): owed as it
    /// stands, answered at a read that binds its receiver's class
    /// (`dispatch_answer`).
    dispatch: Option<Arc<DispatchEdge>>,
    /// How the call's arguments bind the answering contract
    /// (`post_arguments`): as they stand for every post but a dispatched
    /// answer, which binds them by the kind of function it resolved to
    /// (step 8).
    receiver: DispatchReceiver,
}

#[derive(Debug, Clone)]
struct LinkedPostInstance {
    binding: BridgeBinding,
    call: Json,
    vendor_post: Json,
    instantiated_post: Json,
}

/// The ctor a Python call's completed result is: `python:call_result(<call
/// term>, python:occurrence(<site coordinate CID>, <path>…))`.
const PYTHON_CALL_RESULT: &str = "python:call_result";
const PYTHON_OCCURRENCE: &str = "python:occurrence";
/// The one atom a Python call completes under, over its result term:
/// `python:unknown_callee_call.completes(python:call_result(<call term>,
/// <occurrence>))` (the kit's `UnknownCalleeCallV1.faces`). Every arm on
/// which the call completed states it, whether the arm reads the call's
/// value or discards it; an arm on which the call halted states its negation.
const PYTHON_CALL_COMPLETES: &str = "python:unknown_callee_call.completes";

/// One unanswered call member, as the join reads it.
struct UnansweredEdge {
    member_cid: String,
    symbol: String,
    site_cid: String,
}

/// The CID of an `undecided` member's site as a `SourceFragmentCoordinateV1`
/// (the five coordinate keys, without `file`): the same content the lifter
/// spells as the first argument of the call's `python:occurrence`.
fn undecided_site_coordinate_cid(site: &sugar_proof_envelope::UndecidedSite) -> String {
    sugar_canonicalizer::jcs_cid_of_json(&serde_json::json!({
        "sourceCid": site.source_cid.as_str(),
        "startLine": site.start_line,
        "startCol": site.start_col,
        "endLine": site.end_line,
        "endCol": site.end_col,
    }))
}

/// Every `undecided` member with `reason: unanswered` and a `symbol`. A
/// member with no symbol names nothing another proof could answer: it stays
/// owed and the join never reads it.
fn unanswered_edges(pool: &MementoPool) -> Vec<UnansweredEdge> {
    use sugar_proof_envelope::{UndecidedMember, UndecidedReason};
    let mut edges = Vec::new();
    for (cid, member) in pool.undecided_members() {
        let Ok(undecided) = UndecidedMember::from_stored(member) else {
            continue;
        };
        if undecided.reason != UndecidedReason::Unanswered {
            continue;
        }
        let Some(symbol) = undecided.symbol.clone().filter(|s| !s.is_empty()) else {
            continue;
        };
        edges.push(UnansweredEdge {
            member_cid: cid.to_string(),
            symbol,
            site_cid: undecided_site_coordinate_cid(&undecided.site),
        });
    }
    edges
}

/// The halt guards an answering contract states: the `guard` of each of its
/// panic loci (`enumerate_callsites::panic_loci_from_body`, the one reader).
/// A locus that states no guard states no path condition to read here.
fn contract_halt_guards(body: &Json) -> Vec<Json> {
    crate::enumerate_callsites::panic_loci_from_body(body)
        .iter()
        .flat_map(crate::enumerate_callsites::guard_facts_from_locus)
        .collect()
}

/// Whether every panic locus an answering contract states names its guard
/// (true where it states none). A Python contract states one locus per halted
/// arm of its one reduction, each with the arm's guard (#7766: a halt is never
/// dropped), and the arms of one reduction partition its executions; so when
/// every locus states its guard, the halt guards are all the ways the call
/// can halt, and it completes exactly where none holds.
fn contract_guards_every_halt(body: &Json) -> bool {
    crate::enumerate_callsites::panic_loci_from_body(body)
        .iter()
        .all(|locus| !crate::enumerate_callsites::guard_facts_from_locus(locus).is_empty())
}

/// Each halt an answering contract states with its raised type, as `(type,
/// guard)`: a panic locus whose `argTerm` is a ctor (the raised class's
/// coordinate, the Python kit's `tree_enumerate.halt_locus`) and whose
/// `guard` is a formula. A locus that names no type (an undetermined raise)
/// or states no guard types nothing.
fn contract_typed_halts(body: &Json) -> Vec<(Json, Json)> {
    crate::enumerate_callsites::panic_loci_from_body(body)
        .iter()
        .filter_map(|locus| {
            let raised = locus
                .get("argTerm")
                .filter(|term| term.get("kind").and_then(|v| v.as_str()) == Some("ctor"))?;
            let guard = locus.get("guard").filter(|guard| guard.is_object())?;
            Some((raised.clone(), guard.clone()))
        })
        .collect()
}

/// One bridge's answer: the binding, the post, the halt guards, whether
/// every halt states its guard, and the typed halts.
type BridgeAnswer = (BridgeBinding, Json, Vec<Json>, bool, Vec<(Json, Json)>);

/// What one bridge answers for `symbol`: its binding, post and halt guards,
/// or the reason the answer is wrong. `Ok(None)` when the contract states no
/// post: it answers nothing, and the call stays owed.
fn bridge_answer(
    pool: &MementoPool,
    symbol: &str,
    bridge_env: &sugar_proof_envelope::StoredMember,
) -> Result<Option<BridgeAnswer>, (String, DroppedAmbientPostReason)> {
    let raw_target = bridge_env
        .field("targetContractCid")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    let Some(target_cid) = MementoCid::try_parse(raw_target.clone()).ok() else {
        return Err((raw_target, DroppedAmbientPostReason::StaleContractRef));
    };
    let Some(body) = pool.contract_body_by_cid(&target_cid) else {
        return Err((raw_target, DroppedAmbientPostReason::StaleContractRef));
    };
    let target_proof_cid = bridge_env
        .field("targetProofCid")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    if let Some(bundle) = target_proof_cid
        .as_ref()
        .and_then(|raw| MementoCid::try_parse(raw.clone()).ok())
        .and_then(|bundle| pool.bundle_members.get(&bundle))
    {
        if !bundle.contains(&target_cid) {
            return Err((raw_target, DroppedAmbientPostReason::WrongProvider));
        }
    }
    // Its formals as the one binder reads them: a `*args`/`**kwargs`
    // parameter marked (`contract_binder_formals`).
    let Some(formals) = contract_binder_formals(&body) else {
        return Err((raw_target, DroppedAmbientPostReason::WrongContractKind));
    };
    let Some(post) = body
        .get("post")
        .or_else(|| body.get("postcondition"))
        .filter(|v| v.is_object())
        .cloned()
    else {
        return Ok(None);
    };
    let out_binding = contract_out_binding(&body).to_string();
    let target_proof_cid = target_proof_cid.or_else(|| {
        pool.bridge_self_bundle_by_symbol
            .get(symbol)
            .cloned()
            .map(|cid| cid.to_string())
    });
    let halt_guards = contract_halt_guards(&body);
    let every_halt_guarded = contract_guards_every_halt(&body);
    let typed_halts = contract_typed_halts(&body);
    let stated_inputs = stated_input_values(&body);
    Ok(Some((
        BridgeBinding {
            source_symbol: symbol.to_string(),
            target_cid: target_cid.to_string(),
            target_proof_cid,
            formals,
            out_binding,
            stated_inputs,
        },
        post,
        halt_guards,
        every_halt_guarded,
        typed_halts,
    )))
}

/// The inputs a contract takes beside its parameters (step 4, #7757): what
/// its body reads that the caller supplies at the call. Each is a formal of
/// the contract spelled `<kind>:<name>`, and each is supplied by a named
/// argument of the call term, `<ctor>(<name>, <value>)`:
///
/// - `cell:<name>`: a captured cell of a local `def` or a lambda, supplied by
///   `py.closure(<name>, <value>)`;
/// - `global:<name>`: a module global the body reads at the call, supplied by
///   `py.global(<name>, <value>)`;
/// - `default:<param>`: the default the `def` statement bound for
///   `<param>`, supplied by `py.default(<param>, <value>)`; a parameter the
///   call does not pass is bound to it.
///
/// A parameter is any other formal: bound by position, or by
/// `py.kwarg(<name>, <value>)`.
const CONTRACT_INPUTS: [(&str, &str); 3] = [
    ("py.closure", "cell:"),
    ("py.global", "global:"),
    ("py.default", "default:"),
];

/// The named-argument ctor that binds a parameter by name.
const PYTHON_KWARG: &str = "py.kwarg";

/// The named argument that states the class of one of the call's own
/// arguments (step 8, #7757): `py.class(<key>, <class>)`. `<key>` names the
/// argument: its position among the call's positional arguments, spelled in
/// decimal digits, or its keyword. The one binder binds `<class>` to the
/// answering contract's `class:<parameter>` input, `<parameter>` the formal
/// that argument binds. A contract that takes no such input calls no method
/// of that formal: the class is bound to nothing.
const PYTHON_CLASS: &str = "py.class";

/// The formal prefix of a receiver-class input (step 8, #7757): the class of
/// the object a parameter binds, whose namespace a method call on that
/// parameter reads (`dispatched_target`). The function's own proof states no
/// value for it; a caller that knows the class supplies it (`py.class`).
const CLASS_INPUT_PREFIX: &str = "class:";

/// The contract header field naming a function's variadic parameters
/// (#7757): `[{"kind": "positional" | "keyword", "formal": <name>}]`, the
/// `*args` and `**kwargs` of its `def`. Each names one of `formals`.
const VARIADIC_FORMALS_FIELD: &str = "variadicFormals";
/// The mark of a `*args` formal among the formals the one binder reads
/// (`contract_binder_formals`): `*<name>`. No Python identifier starts with
/// `*`, and no contract input does.
const VARIADIC_POSITIONAL_MARK: &str = "*";
/// The mark of a `**kwargs` formal among them: `**<name>`.
const VARIADIC_KEYWORD_MARK: &str = "**";

/// The two variadic parameters a Python signature may take.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Variadic {
    /// `*args`: the tuple of the positional arguments no parameter takes.
    Positional,
    /// `**kwargs`: the dict of the keyword arguments no parameter takes.
    Keyword,
}

/// A binder formal's variadic kind and the name its contract's formulas
/// spell it by; `None` for any other formal.
fn variadic_formal(formal: &str) -> Option<(Variadic, &str)> {
    if let Some(name) = formal.strip_prefix(VARIADIC_KEYWORD_MARK) {
        return Some((Variadic::Keyword, name));
    }
    formal
        .strip_prefix(VARIADIC_POSITIONAL_MARK)
        .map(|name| (Variadic::Positional, name))
}

/// True for a `*args` or `**kwargs` formal of the one binder's reading.
pub(crate) fn is_variadic_formal(formal: &str) -> bool {
    variadic_formal(formal).is_some()
}

/// The name a formal binds in its contract's formulas: a variadic formal's
/// own name, any other formal itself.
fn bound_name(formal: &str) -> &str {
    variadic_formal(formal).map_or(formal, |(_, name)| name)
}

/// A contract's formals as the one binder reads them (#7757): its
/// `formals`, each one its `variadicFormals` names marked `*<name>`
/// (`*args`) or `**<name>` (`**kwargs`). `None` when the contract states no
/// `formals`, or states a variadic entry that is malformed or names no
/// parameter of them.
///
/// Every reader that binds a call to a contract reads its formals through
/// here (the join's `bridge_answer`, the callsite-scoped bridge match), so
/// a `*args` parameter takes the positional arguments no other parameter
/// takes, never one argument by position.
pub(crate) fn contract_binder_formals(body: &Json) -> Option<Vec<String>> {
    let mut formals: Vec<String> = body
        .get("formals")?
        .as_array()?
        .iter()
        .map(|formal| formal.as_str().map(str::to_string))
        .collect::<Option<Vec<_>>>()?;
    let Some(entries) = body.get(VARIADIC_FORMALS_FIELD) else {
        return Some(formals);
    };
    for entry in entries.as_array()? {
        let name = entry.get("formal")?.as_str()?;
        let mark = match entry.get("kind")?.as_str()? {
            "positional" => VARIADIC_POSITIONAL_MARK,
            "keyword" => VARIADIC_KEYWORD_MARK,
            _ => return None,
        };
        let slot = formals
            .iter_mut()
            .find(|formal| formal.as_str() == name && !is_contract_input(formal.as_str()))?;
        *slot = format!("{mark}{name}");
    }
    Some(formals)
}

/// What one argument of a call term spreads (`f(*xs)`, `f(**d)`), read off
/// its term (`python:starred_arg(<xs>)`, `python:double_starred_kwarg(<d>)`):
/// the positional arguments of a `tuple` display, the keyword arguments of a
/// `python:dict` display whose every key is a string constant, or
/// `Undecided` for any other operand (its length or its keys are not
/// stated). `None` for an argument that spreads nothing.
enum Spread {
    Positional(Vec<Json>),
    Keyword(Vec<(String, Json)>),
    Undecided,
}

/// The ctors a spread argument is spelled by in a call term (the kit's
/// `SpreadCallSugar`).
const PYTHON_STARRED_ARG: &str = "python:starred_arg";
const PYTHON_DOUBLE_STARRED_KWARG: &str = "python:double_starred_kwarg";
/// A tuple display's term (the kit's `TupleLiteralValue.to_term`): what a
/// `*args` formal binds.
const PYTHON_TUPLE_DISPLAY: &str = "tuple";
/// A dict display's term and its entries (the kit's
/// `DictLiteralValue.to_term`): what a `**kwargs` formal binds.
const PYTHON_DICT_DISPLAY: &str = "python:dict";
const PYTHON_DICT_ENTRY: &str = "python:dict_entry";

/// A ctor term's name and arguments.
fn ctor_parts(term: &Json) -> Option<(&str, &Vec<Json>)> {
    if term.get("kind")?.as_str()? != "ctor" {
        return None;
    }
    Some((term.get("name")?.as_str()?, term.get("args")?.as_array()?))
}

fn spread_argument(arg: &Json) -> Option<Spread> {
    let (name, parts) = ctor_parts(arg)?;
    if name != PYTHON_STARRED_ARG && name != PYTHON_DOUBLE_STARRED_KWARG {
        return None;
    }
    let operand = match parts.as_slice() {
        [operand] => ctor_parts(operand),
        _ => None,
    };
    let spread = if name == PYTHON_STARRED_ARG {
        match operand {
            Some((PYTHON_TUPLE_DISPLAY, items)) => Some(Spread::Positional(items.clone())),
            _ => None,
        }
    } else {
        match operand {
            Some((PYTHON_DICT_DISPLAY, entries)) => entries
                .iter()
                .map(|entry| {
                    let (name, parts) = ctor_parts(entry)?;
                    match parts.as_slice() {
                        [key, value] if name == PYTHON_DICT_ENTRY => {
                            Some((str_const_value(key)?.to_string(), value.clone()))
                        }
                        _ => None,
                    }
                })
                .collect::<Option<Vec<_>>>()
                .map(Spread::Keyword),
            _ => None,
        }
    };
    Some(spread.unwrap_or(Spread::Undecided))
}

/// Whether a call spreads an operand whose length or keys are not stated
/// (`spread_argument`): the binding of every parameter from it on is not
/// decided, so the call is not bound (undecided by name, never a wrong
/// answer).
pub(crate) fn spreads_undecided(args: &[Json]) -> bool {
    args.iter()
        .any(|arg| matches!(spread_argument(arg), Some(Spread::Undecided)))
}

/// A string constant term.
fn string_const_term(value: &str) -> Json {
    json!({"kind": "const", "value": value, "sort": {"kind": "primitive", "name": "String"}})
}

/// One entry of a dict display: `python:dict_entry(<key>, <value>)`.
fn dict_entry(key: &str, value: &Json) -> Json {
    json!({"kind": "ctor", "name": PYTHON_DICT_ENTRY, "args": [string_const_term(key), value]})
}

/// Supply the variadic formal `name` (`*args` or `**kwargs`, by the name its
/// formulas spell it) with `display`, what it takes (`call_argument_formals`).
/// Where the call supplied it packed (a `py.kwarg` naming it), that value
/// stands, and nothing else may be packed into it (`takes_any`): `None`.
fn supply_variadic(
    name: Option<&str>,
    display: Json,
    takes_any: bool,
    seen: &mut std::collections::BTreeSet<String>,
    supplied: &mut Vec<(String, Json)>,
) -> Option<()> {
    let Some(name) = name else {
        return Some(());
    };
    if seen.contains(name) {
        return (!takes_any).then_some(());
    }
    seen.insert(name.to_string());
    supplied.push((name.to_string(), display));
    Some(())
}

/// True for a contract input (`cell:`, `global:`, `default:`, `class:`),
/// never a parameter.
fn is_contract_input(formal: &str) -> bool {
    formal.starts_with(CLASS_INPUT_PREFIX)
        || CONTRACT_INPUTS
            .iter()
            .any(|(_, prefix)| formal.starts_with(prefix))
}

/// Which argument of a call a `py.class` states the class of: a positional
/// argument by its position, or a keyword argument by its keyword.
#[derive(Debug, Clone, PartialEq, Eq)]
enum ClassKey {
    Position(usize),
    Keyword(String),
}

/// A call's `py.class(<key>, <class>)` read as `(key, class)` (step 8). `None`
/// for any other argument; `Some(Err(()))` for that ctor with a key that is
/// not a string constant or an arity that is not two.
fn class_argument(arg: &Json) -> Option<Result<(ClassKey, Json), ()>> {
    if arg.get("kind").and_then(|v| v.as_str()) != Some("ctor")
        || arg.get("name").and_then(|v| v.as_str()) != Some(PYTHON_CLASS)
    {
        return None;
    }
    let read = arg
        .get("args")
        .and_then(|v| v.as_array())
        .and_then(|parts| match parts.as_slice() {
            [key, class] => {
                let key = key.get("value").and_then(|v| v.as_str())?;
                let key = if !key.is_empty() && key.bytes().all(|b| b.is_ascii_digit()) {
                    ClassKey::Position(key.parse::<usize>().ok()?)
                } else {
                    ClassKey::Keyword(key.to_string())
                };
                Some((key, class.clone()))
            }
            _ => None,
        });
    Some(read.ok_or(()))
}

/// A named argument of a call term: `(ctor, name, value)` for `py.kwarg`,
/// `py.closure`, `py.global` or `py.default` applied to a string name and a
/// value. `None` for a positional argument. `Some(Err(()))` for a named
/// ctor whose name is not a string constant or whose arity is not two.
fn named_argument(arg: &Json) -> Option<Result<(&str, String, Json), ()>> {
    if arg.get("kind").and_then(|v| v.as_str()) != Some("ctor") {
        return None;
    }
    let ctor = arg.get("name").and_then(|v| v.as_str())?;
    if ctor != PYTHON_KWARG && !CONTRACT_INPUTS.iter().any(|(named, _)| *named == ctor) {
        return None;
    }
    let parts = arg.get("args").and_then(|v| v.as_array());
    let named = parts.and_then(|parts| match parts.as_slice() {
        [name, value] => name
            .get("value")
            .and_then(|v| v.as_str())
            .map(|name| (ctor, name.to_string(), value.clone())),
        _ => None,
    });
    Some(named.ok_or(()))
}

/// Each argument of a call, in the call's order, with the formal of the
/// answering contract it supplies (step 4): a positional argument supplies
/// the next parameter, `py.kwarg` a parameter by name, and each contract
/// input's named argument (`py.closure`, `py.global`, `py.default`) that
/// input. The value is what the argument supplies: the positional argument
/// itself, or a named argument's value. `None` when an argument fits no
/// formal (more positional arguments than parameters, a name the contract
/// does not take, a formal supplied twice, a malformed named argument).
///
/// The one reading of a call's arguments against a contract's formals:
/// `bind_call_arguments` binds through it, and every reader that pairs a
/// call's arguments with a contract's formals (the callsite-scoped bridge
/// match, the vendor post's universal reading) reads it, never a positional
/// zip behind a count check.
///
/// A `py.class(<key>, <class>)` (step 8) supplies the `class:<parameter>`
/// input of the parameter the argument it names binds: a position the
/// parameter a positional argument there binds, a keyword that parameter.
/// It names an argument the call passes or it fits nothing; a contract that
/// takes no such input reads no method of that parameter, and the class is
/// supplied to nothing.
///
/// Variadic parameters (#7757), as Python binds them
/// (`contract_binder_formals` marks them):
///
/// - a `*<name>` formal is bound to the tuple display (`tuple(...)`, the term
///   a tuple display is spelled by) of the positional arguments no parameter
///   before it takes, in order; a parameter after it takes no positional
///   argument (it is keyword-only);
/// - a `**<name>` formal is bound to the dict display (`python:dict(
///   python:dict_entry(<key>, <value>)...)`) of the keyword arguments no
///   parameter takes, keyed by their keyword, in order;
/// - a `py.kwarg` naming the variadic formal itself binds it to its value
///   as it stands: a same-file definition's call supplies a packed formal so
///   (`lambda_callable.definition_edge_call`), the tuple or dict its own
///   binding packed. A packed value beside arguments the formal would also
///   take fits nothing;
/// - an argument that spreads a tuple display (`python:starred_arg`) or a
///   dict display of string keys (`python:double_starred_kwarg`) is its
///   elements; one that spreads anything else is not decided
///   (`spreads_undecided`): the call fits nothing here, and the join leaves
///   it unanswered by name. A positional `py.class` key beside a spread fits
///   nothing (the spread moves the positions it counts).
pub(crate) fn call_argument_formals(
    formals: &[String],
    args: &[Json],
) -> Option<Vec<(String, Json)>> {
    let parameters: Vec<&str> = formals
        .iter()
        .map(String::as_str)
        .filter(|formal| !is_contract_input(formal))
        .collect();
    // `*args` and `**kwargs`, by the name the formulas spell them.
    let star = parameters.iter().position(|parameter| {
        matches!(variadic_formal(parameter), Some((Variadic::Positional, _)))
    });
    let star_name = star.map(|index| bound_name(parameters[index]));
    let double_name = parameters.iter().find_map(|parameter| match variadic_formal(parameter) {
        Some((Variadic::Keyword, name)) => Some(name),
        _ => None,
    });
    // The parameters a positional argument binds: each before `*args` (a
    // parameter after it is keyword-only), never a variadic one.
    let by_position: Vec<&str> = parameters[..star.unwrap_or(parameters.len())]
        .iter()
        .copied()
        .filter(|parameter| variadic_formal(parameter).is_none())
        .collect();
    // The parameters a keyword argument binds by its name.
    let by_name: Vec<&str> = parameters
        .iter()
        .copied()
        .filter(|parameter| variadic_formal(parameter).is_none())
        .collect();
    // Each spread argument as the arguments it spreads.
    let mut spread = false;
    let mut expanded: Vec<Json> = Vec::with_capacity(args.len());
    for arg in args {
        match spread_argument(arg) {
            None => expanded.push(arg.clone()),
            Some(Spread::Positional(items)) => {
                spread = true;
                expanded.extend(items);
            }
            Some(Spread::Keyword(entries)) => {
                spread = true;
                expanded.extend(entries.into_iter().map(|(name, value)| {
                    json!({
                        "kind": "ctor",
                        "name": PYTHON_KWARG,
                        "args": [string_const_term(&name), value],
                    })
                }));
            }
            Some(Spread::Undecided) => return None,
        }
    }
    let mut supplied: Vec<(String, Json)> = Vec::with_capacity(expanded.len());
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut classes: Vec<(ClassKey, Json)> = Vec::new();
    let mut positional = 0usize;
    // What `*args` and `**kwargs` take: the arguments no parameter takes.
    let mut packed_positional: Vec<Json> = Vec::new();
    let mut packed_keyword: Vec<(String, Json)> = Vec::new();
    for arg in &expanded {
        match class_argument(arg) {
            Some(Ok(class)) => {
                classes.push(class);
                continue;
            }
            Some(Err(())) => return None,
            None => {}
        }
        let (formal, value) = match named_argument(arg) {
            None => {
                positional += 1;
                match by_position.get(positional - 1) {
                    Some(parameter) => ((*parameter).to_string(), arg.clone()),
                    None if star_name.is_some() => {
                        packed_positional.push(arg.clone());
                        continue;
                    }
                    None => return None,
                }
            }
            Some(Err(())) => return None,
            Some(Ok((ctor, name, value))) if ctor == PYTHON_KWARG => {
                if is_contract_input(&name) {
                    // An input is never bound as a keyword.
                    return None;
                }
                if by_name.contains(&name.as_str()) {
                    (name, value)
                } else if Some(name.as_str()) == star_name || Some(name.as_str()) == double_name {
                    // A packed variadic formal, supplied as it stands.
                    (name, value)
                } else if double_name.is_some() {
                    packed_keyword.push((name, value));
                    continue;
                } else {
                    return None;
                }
            }
            Some(Ok((ctor, name, value))) => {
                let (_, prefix) = CONTRACT_INPUTS.iter().find(|(named, _)| *named == ctor)?;
                let formal = format!("{prefix}{name}");
                if !formals.contains(&formal) {
                    return None;
                }
                (formal, value)
            }
        };
        if !seen.insert(formal.clone()) {
            return None;
        }
        supplied.push((formal, value));
    }
    // `*args`: the tuple display of what it takes; `**kwargs`: the dict
    // display, keyed by keyword.
    let tuple = json!({"kind": "ctor", "name": PYTHON_TUPLE_DISPLAY, "args": packed_positional});
    let takes_positional = !packed_positional.is_empty();
    supply_variadic(star_name, tuple, takes_positional, &mut seen, &mut supplied)?;
    let entries: Vec<Json> = packed_keyword
        .iter()
        .map(|(key, value)| dict_entry(key, value))
        .collect();
    let dict = json!({"kind": "ctor", "name": PYTHON_DICT_DISPLAY, "args": entries});
    let takes_keyword = !packed_keyword.is_empty();
    supply_variadic(double_name, dict, takes_keyword, &mut seen, &mut supplied)?;
    for (key, class) in classes {
        let parameter = match key {
            ClassKey::Position(_) if spread => return None,
            ClassKey::Position(position) if position < positional => {
                match by_position.get(position) {
                    Some(parameter) => (*parameter).to_string(),
                    // An argument `*args` takes: no parameter's class.
                    None => continue,
                }
            }
            ClassKey::Position(_) => return None,
            ClassKey::Keyword(name) if packed_keyword.iter().any(|(key, _)| *key == name) => {
                // An argument `**kwargs` takes: no parameter's class.
                continue;
            }
            ClassKey::Keyword(name) if seen.contains(&name) => name,
            ClassKey::Keyword(_) => return None,
        };
        let formal = format!("{CLASS_INPUT_PREFIX}{parameter}");
        if !formals.contains(&formal) {
            continue;
        }
        if !seen.insert(formal.clone()) {
            return None;
        }
        supplied.push((formal, class));
    }
    Some(supplied)
}

/// The value a contract states for each `global:<name>` input it decides
/// (step 5, #7757): the header's `inputValues`, `[{formal, value}, ...]`.
/// A function reads its own module's globals; called after import, they are
/// the values the module's one run left, and the producer's own proof states
/// them. A global the run leaves undecided is not stated. An entry that is
/// not `{formal: "global:<name>", value: <term>}` states nothing.
pub(crate) fn stated_input_values(body: &Json) -> Vec<(String, Json)> {
    body.get("inputValues")
        .and_then(Json::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(|entry| {
                    let formal = entry.get("formal")?.as_str()?;
                    if !formal.starts_with(GLOBAL_INPUT_PREFIX) {
                        return None;
                    }
                    let value = entry.get("value").filter(|value| value.is_object())?;
                    Some((formal.to_string(), value.clone()))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// The formal prefix of a module global input.
const GLOBAL_INPUT_PREFIX: &str = "global:";

/// Each formal of the answering contract bound to what the call supplies
/// for it (step 4): the call's arguments read against the formals by
/// `call_argument_formals`, a parameter the call does not pass bound to the
/// contract's `default:<param>` input, and a `global:<name>` input the call
/// does not supply bound to the value the contract states for it
/// (`stated`, `stated_input_values`: the module-final value, as the call of a
/// function after import reads it), exactly as an omitted parameter is bound
/// to its default. A call made while the module runs supplies its own
/// `py.global`, which is bound instead. `None` when the call does not fit the
/// contract (an argument that fits no formal, a parameter neither passed nor
/// defaulted): the join refuses it as `import-signature-mismatch`.
///
/// An input neither the call supplies nor the contract states is left
/// unbound: the instance is open and the call stays owed
/// (`OpenAfterSpecialization`), never answered on a value nobody gave.
///
/// The one binder: a call's join binds the callee's post and halt guards
/// through it, and a row's own claims are bound through it with no caller
/// (`bind_own_inputs`).
pub(crate) fn bind_call_arguments(
    formals: &[String],
    stated: &[(String, Json)],
    args: &[Json],
) -> Option<Vec<(String, Json)>> {
    let parameters: Vec<&str> = formals
        .iter()
        .map(String::as_str)
        .filter(|formal| !is_contract_input(formal))
        .collect();
    let mut bound: std::collections::BTreeMap<String, Json> =
        call_argument_formals(formals, args)?.into_iter().collect();
    for (formal, value) in stated {
        if formals.contains(formal) && !bound.contains_key(formal) {
            bound.insert(formal.clone(), value.clone());
        }
    }
    let mut bindings = Vec::with_capacity(formals.len());
    for parameter in &parameters {
        // A variadic formal binds the name its formulas spell it by; the
        // reading always supplies it (the empty display when the call passes
        // nothing it takes).
        let parameter = &bound_name(parameter);
        if let Some(actual) = bound.remove(*parameter) {
            bindings.push(((*parameter).to_string(), actual));
            continue;
        }
        // Not passed: the parameter is the default the `def` statement bound,
        // as the call supplies it; a default the call does not supply stays
        // the free input, so the instance is open.
        let default = format!("default:{parameter}");
        if !formals.contains(&default) {
            return None;
        }
        let actual = bound
            .get(&default)
            .cloned()
            .unwrap_or_else(|| serde_json::json!({"kind": "var", "name": default}));
        bindings.push(((*parameter).to_string(), actual));
    }
    bindings.extend(bound);
    Some(bindings)
}

/// A function's own row bound through the one binder with no caller (step
/// 5, #7757): pytest calls a test function after import, passing nothing, so
/// each parameter stays itself and each `global:<name>` input is bound to the
/// value the contract states for it (`bind_call_arguments` with the
/// parameters as their own arguments). The row's `inv` and `post` are
/// substituted alike, so the claims are read over exactly the instance a
/// caller after import joins. A row with no `formals` or no stated input is
/// returned as it is.
///
/// `Err` names each `global:<name>` the claims still read after the binding:
/// an input the contract does not state (the module's run left it
/// undecided). Its claims are not decided on a value nobody gave.
fn bind_own_inputs(body: &Json) -> Result<Json, Vec<String>> {
    let (instance, unstated) = bind_own_inputs_with_unstated(body);
    if unstated.is_empty() {
        Ok(instance)
    } else {
        Err(unstated)
    }
}

/// The row bound through the one binder (`bind_own_inputs`), with each
/// `global:<name>` input its claims still read after the binding: an input
/// the contract states no value for (the module's run left it undecided).
/// That input stays in the instance as itself, a free variable of the row
/// (the compiler declares it as a free constant, as it declares a
/// parameter); the consistency check decides the row over every value of it
/// (`decide_over_unstated_inputs`).
fn bind_own_inputs_with_unstated(body: &Json) -> (Json, Vec<String>) {
    let Some(formals) = body.get("formals").and_then(Json::as_array).and_then(|formals| {
        formals
            .iter()
            .map(|formal| formal.as_str().map(str::to_string))
            .collect::<Option<Vec<_>>>()
    }) else {
        return (body.clone(), Vec::new());
    };
    let globals: Vec<&String> = formals
        .iter()
        .filter(|formal| formal.starts_with(GLOBAL_INPUT_PREFIX))
        .collect();
    if globals.is_empty() {
        return (body.clone(), Vec::new());
    }
    let stated = stated_input_values(body);
    let parameters: Vec<Json> = formals
        .iter()
        .filter(|formal| !is_contract_input(formal))
        .map(|formal| serde_json::json!({"kind": "var", "name": formal}))
        .collect();
    let mut instance = body.clone();
    if let Some(bindings) = bind_call_arguments(&formals, &stated, &parameters) {
        if let Some(object) = instance.as_object_mut() {
            for slot in ["inv", "post"] {
                if let Some(formula) = object.get(slot).filter(|formula| formula.is_object()) {
                    let bound = substitute_call_bindings(formula, &bindings);
                    object.insert(slot.to_string(), bound);
                }
            }
        }
    }
    let inv = instance.get("inv").cloned().unwrap_or(Json::Null);
    let unbound: Vec<String> = globals
        .into_iter()
        .filter(|formal| formula_reads_var(&inv, formal))
        .cloned()
        .collect();
    (instance, unbound)
}

/// A row whose claims read a module global input its contract states no
/// value for (`bind_own_inputs_with_unstated`), decided over every value of
/// that input (step 9). The consistency check has already solved the row
/// with the input as a free constant:
///
/// - the claim unsatisfiable (`Unsatisfied`): false for every value of the
///   input, refuted, as it stands;
/// - the claim satisfiable (`Discharged`): satisfiable for SOME value only.
///   It is discharged only when its negation is unsatisfiable too
///   (`holds_for_every_value`: the claim holds whatever the input is);
///   otherwise whether it holds depends on a value nobody gave, and the row
///   is undecidable by name -- never sat on a value the solver chose;
/// - anything else (a refusal, an encoding stop, a timeout): as it stands.
fn decide_over_unstated_inputs(
    result: &mut ConsistencyResult,
    unstated: &[String],
    holds_for_every_value: impl FnOnce() -> bool,
) {
    if result.verdict != ObligationVerdict::Discharged {
        return;
    }
    let inputs = unstated.join(", ");
    if holds_for_every_value() {
        result.reason = format!(
            "{} [holds for every value of the module global input(s) {inputs}, whose value the module's run leaves undecided]",
            result.reason
        );
        return;
    }
    result.verdict = ObligationVerdict::Undecidable;
    result.reason = format!(
        "consistency check undecidable: `{}` reads the module global input(s) {inputs} whose value the module's run leaves undecided, and whether it holds depends on that value",
        result.property_name
    );
    result.effect = None;
    if let Some(VerificationDetail::Solver { final_verdict, .. }) = result.verification.as_mut() {
        *final_verdict = ObligationVerdict::Undecidable.as_str().to_string();
    }
}

/// Does the claim of the contract `body` hold for every value of its free
/// inputs: is its negation unsatisfiable, conjoined with the row's own post
/// (where the claim reads the result) and what the contracts joined to its
/// calls state (the one join, `linked_ambient_post_instances_for_inv`, with
/// the raised types and the stated ancestry it reads)? Peer claims (ambient
/// ground facts, ambient universals) are not conjoined: they are claims, not
/// what a joined contract states, and the row's own claims among them would
/// refute its own negation. A dropped join answer, an undecodable goal or any
/// solver answer but `unsat` is `false`: the claim is not shown to hold.
fn claim_holds_for_every_value(
    body: &Json,
    ambient: &[AmbientPost],
    exception_ancestry: &ExceptionAncestry,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> bool {
    let Some(inv) = body.get("inv").filter(|inv| inv.is_object()) else {
        return false;
    };
    let mut operands = vec![IrFormula::Not(inv.clone()).to_value()];
    if let Some(post) = body.get("post").filter(|post| post.is_object()) {
        if formula_reads_var(inv, contract_out_binding(body)) {
            operands.push(post.clone());
        }
    }
    let counter = canonicalize_formula_json(&IrFormula::And(operands).to_value());
    let mut conjuncts = Vec::new();
    if !ambient.is_empty() {
        let partition = linked_ambient_post_instances_for_inv(&counter, ambient);
        if !partition.dropped.is_empty() {
            return false;
        }
        conjuncts.extend(partition.kept.iter().map(|post| post.instantiated_post.clone()));
    }
    let mut operands = Vec::with_capacity(conjuncts.len() + 1);
    operands.push(counter);
    operands.extend(conjuncts);
    let counter = with_raised_types(IrFormula::And(operands).to_value(), ambient);
    let counter = with_exception_ancestry(counter, exception_ancestry);
    let counter = fold_decided_python_atoms(&counter);
    joined_goal_has_verdict(
        IrFormula::Not(counter).to_value(),
        ObligationVerdict::Discharged,
        plan,
        registry,
        compilers,
    )
}

/// `formula` with each formal replaced by its binding at once: every formal
/// is first renamed to a name no term spells, so an actual that reads a
/// variable spelled as another formal is never captured by that formal's
/// binding.
fn substitute_call_bindings(formula: &Json, bindings: &[(String, Json)]) -> Json {
    let placeholder = |index: usize| format!("\u{0}bound-formal:{index}");
    let mut instance = formula.clone();
    for (index, (formal, _)) in bindings.iter().enumerate() {
        instance = crate::instantiate::substitute_formula_pub(
            &instance,
            formal,
            &serde_json::json!({"kind": "var", "name": placeholder(index)}),
        );
    }
    for (index, (_, actual)) in bindings.iter().enumerate() {
        instance = crate::instantiate::substitute_formula_pub(&instance, &placeholder(index), actual);
    }
    instance
}

/// `term` with each bound formal replaced by what it is bound to: the
/// substitution `substitute_call_bindings` makes in a formula, made in a term.
fn substitute_term_bindings(term: &Json, bindings: &[(String, Json)]) -> Json {
    if bindings.is_empty() {
        return term.clone();
    }
    let carrier = json!({"kind": "atomic", "name": "=", "args": [term]});
    substitute_call_bindings(&carrier, bindings)
        .get("args")
        .and_then(|args| args.get(0))
        .cloned()
        .unwrap_or_else(|| term.clone())
}

// ── Dispatch: a method call on an instance whose class is an input (step 8)
//
// Inside a method, the class of the object a parameter binds is an input of
// the method's contract, `class:<parameter>`, as a module global is: the
// method's own proof states no value for it. `self.m(...)` is the method's
// coordinate and an edge whose member names the method alone
// (`python:dispatch:<m>`), carrying `py.class("0", <class>)` for its
// receiver. A caller that knows the class supplies it at the call
// (`py.class`), and the one binder binds the input (`call_argument_formals`).
// Where the read of the call binds the class to a decided instance
// (`python:instance(<class symbol>, <field>...)`), the method its namespace
// selects is looked up on the order the class's own proof states
// (`<class symbol>::namespace`), and its contract answers the call exactly
// as a contract answers an edge by its symbol. Anything not decided leaves
// the call owed: never a guessed target, never a free class.

/// The contract-name suffix of a class's namespace row (the Python kit's
/// `tree_enumerate.CLASS_NAMESPACE_SUFFIX`): `<class symbol>` + this. The row
/// states facts read by the dispatch, never a claim checked on its own.
pub(crate) const CLASS_NAMESPACE_SUFFIX: &str = "::namespace";
/// `python:class_mro(<class>, <entry>...)`: the class's method resolution
/// order, the class itself first; a source class by its symbol, a builtin
/// class as `builtins.<name>`.
const PYTHON_CLASS_MRO: &str = "python:class_mro";
/// `python:class_binds(<class>, <name>, <kind>, <symbol>)`: a name the class's
/// own namespace holds, with the kind of value it holds and, for a function
/// it holds, that function's join symbol.
const PYTHON_CLASS_BINDS: &str = "python:class_binds";
/// `python:class_object(<class>, <class term>)`: the term the class object
/// is spelled by wherever a reduction reads it (the kit's
/// `python:class-definition(<cid>)`), the first actual a `classmethod` read
/// off an instance of the class binds.
const PYTHON_CLASS_OBJECT: &str = "python:class_object";
/// The kinds of namespace value the dispatch joins (the kit's
/// `tree_enumerate._class_namespace_facts`), each with the function's join
/// symbol and bound as Python's descriptor protocol binds it read off an
/// instance (`DispatchReceiver`):
///
/// - a plain function the class body wrote: a method bound to the instance;
const DISPATCH_FUNCTION_KIND: &str = "function";
/// - a function the class holds as a field (`m = lambda self: ...`): a
///   method bound to the instance, as a plain function is;
const DISPATCH_FIELD_KIND: &str = "field";
/// - a `def` under the builtin `staticmethod`: the function, nothing bound;
const DISPATCH_STATIC_KIND: &str = "staticmethod";
/// - a `def` under the builtin `classmethod`: bound to the instance's class;
const DISPATCH_CLASS_KIND: &str = "classmethod";
/// - a `def` under the builtin `property`: its getter, called with the
///   instance where the attribute is read (a data descriptor: it wins over
///   the instance's `__dict__`).
const DISPATCH_PROPERTY_KIND: &str = "property";
/// The mark of a dispatched attribute read after the dispatch prefix:
/// `python:dispatch:.<name>` is the read `obj.<name>`; `python:dispatch:<m>`
/// the call `obj.<m>(...)`. No Python name starts with `.`.
const DISPATCH_READ_MARK: &str = ".";
/// The prefix of a builtin class's entry in an order.
const BUILTIN_CLASS_PREFIX: &str = "builtins.";
/// A decided instance's class, as a caller binds a class input:
/// `python:instance(<class symbol>, <field>...)`, the fields every name its
/// `__dict__` may hold at the call.
const PYTHON_INSTANCE: &str = "python:instance";
/// The symbol prefix of a dispatched method call's `undecided` member:
/// `python:dispatch:<method>`. No join symbol is spelled so.
const DISPATCH_SYMBOL_PREFIX: &str = "python:dispatch:";

/// What one class's namespace row states (step 8, #7757).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct ClassNamespace {
    /// The method resolution order, the class first. Empty when two proofs
    /// state the class differently: then nothing about it is decided.
    mro: Vec<String>,
    /// Each name the class's own namespace holds: the kind of value, and the
    /// join symbol of a function it holds.
    binds: BTreeMap<String, (String, String)>,
    /// The term the class object is spelled by (`python:class_object`):
    /// what a `classmethod` read off an instance of it binds first.
    object: Option<Json>,
}

/// A string constant's value.
fn const_str(term: &Json) -> Option<&str> {
    if term.get("kind")?.as_str()? != "const" {
        return None;
    }
    term.get("value")?.as_str()
}

/// The namespace one contract body states, when it is a namespace row:
/// `(class symbol, namespace)`. Only facts about the class the row names
/// are read. A row that states no order states nothing.
fn class_namespace_of(body: &Json) -> Option<(String, ClassNamespace)> {
    let symbol = contract_property_name(body)
        .strip_suffix(CLASS_NAMESPACE_SUFFIX)?
        .to_string();
    let inv = canonicalize_formula_json(body.get("inv").filter(|v| v.is_object())?);
    let mut namespace = ClassNamespace::default();
    let mut ordered = false;
    for fact in top_level_conjuncts(inv) {
        if fact.get("kind").and_then(|v| v.as_str()) != Some("atomic") {
            continue;
        }
        let Some(args) = fact.get("args").and_then(|v| v.as_array()) else {
            continue;
        };
        if fact.get("name").and_then(|v| v.as_str()) == Some(PYTHON_CLASS_OBJECT) {
            if let [subject, term] = args.as_slice() {
                if const_str(subject) == Some(symbol.as_str()) && term.is_object() {
                    namespace.object = Some(term.clone());
                }
            }
            continue;
        }
        let Some(strings) = args
            .iter()
            .map(|arg| const_str(arg).map(str::to_string))
            .collect::<Option<Vec<String>>>()
        else {
            continue;
        };
        if strings.first() != Some(&symbol) {
            continue;
        }
        match fact.get("name").and_then(|v| v.as_str()) {
            Some(PYTHON_CLASS_MRO) => {
                namespace.mro = strings[1..].to_vec();
                ordered = true;
            }
            Some(PYTHON_CLASS_BINDS) => {
                if let [_, name, kind, target] = strings.as_slice() {
                    namespace
                        .binds
                        .insert(name.clone(), (kind.clone(), target.clone()));
                }
            }
            _ => {}
        }
    }
    (ordered && !namespace.mro.is_empty()).then_some((symbol, namespace))
}

/// Every class namespace the pool's proofs state, own and imported, by class
/// symbol. A class two proofs state differently is kept with no order:
/// nothing about it is decided.
fn collect_class_namespaces(pool: &MementoPool) -> BTreeMap<String, ClassNamespace> {
    let mut namespaces: BTreeMap<String, ClassNamespace> = BTreeMap::new();
    for (_cid, member) in pool.contract_members() {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        let Some((symbol, namespace)) = class_namespace_of(&body) else {
            continue;
        };
        match namespaces.get_mut(&symbol) {
            Some(stated) if *stated != namespace => *stated = ClassNamespace::default(),
            Some(_) => {}
            None => {
                namespaces.insert(symbol, namespace);
            }
        }
    }
    namespaces
}

/// How a dispatched call's arguments bind the function its class's
/// namespace holds (step 8): Python's descriptor protocol for the kind of
/// value it is, read off an instance (`object.__getattribute__`, then
/// `__get__(obj, type(obj))`).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
enum DispatchReceiver {
    /// The call's arguments as they stand: the instance first (a plain
    /// function, a function held as a field), or a property getter's read.
    /// Every post that is no dispatched answer binds this way.
    #[default]
    AsCalled,
    /// A `staticmethod`: the instance is not passed.
    Static,
    /// A `classmethod`: the instance's class (its `python:class_object`
    /// term) is passed in the instance's place.
    Class(Json),
}

/// What a dispatched call or read resolves to (step 8): the join symbol of
/// the function that runs, and how the call's arguments bind it.
#[derive(Debug, Clone, PartialEq, Eq)]
struct DispatchTarget {
    symbol: String,
    receiver: DispatchReceiver,
}

/// The function a call of `method` on an instance runs -- or, `read`, the
/// getter a read of the attribute `method` runs -- the instance's class input
/// bound to `class` (step 8, #7757).
///
/// `class` is read as `python:instance(<class symbol>, <field>...)`, and
/// `method` is looked up as Python's `object.__getattribute__` looks it up:
/// the first class of the order its own proof states that binds it; a data
/// descriptor there (a property) wins over the instance's `__dict__`, any
/// other value is shadowed by a field of that name. The value found binds by
/// its kind (`DispatchReceiver`). `None` -- the call stays owed -- whenever
/// that lookup is not decided by what the proofs state:
///
/// - `class` is not a decided instance (a free input, anything else);
/// - a class of the order has no namespace row (its namespace is not
///   closed, or no proof here states it), or two proofs state it differently;
/// - a class of the order binds `__getattribute__`, or, for a read (a getter
///   that raises `AttributeError` falls to it), `__getattr__`;
/// - a builtin class comes before the class that binds `method` (it may
///   bind it), or a builtin class other than `object` stands in the order;
/// - no class binds `method`, or binds it with no join symbol;
/// - a call: the instance's `__dict__` may hold `method`, or the value is a
///   property (the getter's result is called, which nothing here states) or
///   any kind but a plain function, a function field, a `staticmethod` or a
///   `classmethod`; a `classmethod` of a class no proof states the object of;
/// - a read: the value is anything but a property.
fn dispatched_target(
    namespaces: &BTreeMap<String, ClassNamespace>,
    method: &str,
    read: bool,
    class: &Json,
) -> Option<DispatchTarget> {
    if class.get("kind")?.as_str()? != "ctor" || class.get("name")?.as_str()? != PYTHON_INSTANCE {
        return None;
    }
    let (subject, fields) = class.get("args")?.as_array()?.split_first()?;
    let subject = const_str(subject)?;
    let mut shadowed = false;
    for field in fields {
        if const_str(field)? == method {
            shadowed = true;
        }
    }
    let order = &namespaces.get(subject)?.mro;
    if order.first().map(String::as_str) != Some(subject) {
        return None;
    }
    let mut found: Option<(String, String)> = None;
    for entry in order {
        if let Some(builtin) = entry.strip_prefix(BUILTIN_CLASS_PREFIX) {
            if found.is_none() || builtin != "object" {
                return None;
            }
            continue;
        }
        let namespace = namespaces.get(entry)?;
        if namespace.mro.is_empty()
            || namespace.binds.contains_key("__getattribute__")
            || (read && namespace.binds.contains_key("__getattr__"))
        {
            return None;
        }
        if found.is_none() {
            if let Some((kind, target)) = namespace.binds.get(method) {
                if target.is_empty() {
                    return None;
                }
                found = Some((kind.clone(), target.clone()));
            }
        }
    }
    let (kind, symbol) = found?;
    let receiver = match kind.as_str() {
        DISPATCH_PROPERTY_KIND if read => DispatchReceiver::AsCalled,
        _ if read || shadowed => return None,
        DISPATCH_FUNCTION_KIND | DISPATCH_FIELD_KIND => DispatchReceiver::AsCalled,
        DISPATCH_STATIC_KIND => DispatchReceiver::Static,
        DISPATCH_CLASS_KIND => DispatchReceiver::Class(namespaces.get(subject)?.object.clone()?),
        _ => return None,
    };
    Some(DispatchTarget { symbol, receiver })
}

/// Whether `arg` is a positional argument of a call term: no named argument
/// (`py.kwarg`, a contract input's) and no `py.class`.
fn is_positional_argument(arg: &Json) -> bool {
    class_argument(arg).is_none() && named_argument(arg).is_none()
}

/// A dispatched call's arguments as the function it resolved to takes them
/// (`DispatchReceiver`), for the one binder (step 8). The instance is the
/// call's first positional argument and its class `py.class("0", ...)`:
///
/// - `AsCalled`: as they stand;
/// - `Static`: the instance and its class dropped, every other positional
///   `py.class` key one lower;
/// - `Class(term)`: the instance replaced by the class object `term`, and
///   the instance's class dropped (the class of a class is its metaclass,
///   which nothing here states: a `class:` input of that formal stays free).
///
/// `None` when the call names no instance (no positional argument).
fn dispatched_arguments(receiver: &DispatchReceiver, args: &[Json]) -> Option<Vec<Json>> {
    if *receiver == DispatchReceiver::AsCalled {
        return Some(args.to_vec());
    }
    let instance = args.iter().position(is_positional_argument)?;
    let mut rebound = Vec::with_capacity(args.len());
    for (index, arg) in args.iter().enumerate() {
        if index == instance {
            if let DispatchReceiver::Class(term) = receiver {
                rebound.push(term.clone());
            }
            continue;
        }
        match class_argument(arg) {
            Some(Ok((ClassKey::Position(0), _))) => continue,
            Some(Ok((ClassKey::Position(position), _)))
                if *receiver == DispatchReceiver::Static =>
            {
                let mut shifted = arg.clone();
                let key = shifted
                    .get_mut("args")
                    .and_then(|v| v.as_array_mut())
                    .and_then(|parts| parts.first_mut())
                    .and_then(|key| key.as_object_mut())?;
                key.insert("value".to_string(), json!((position - 1).to_string()));
                rebound.push(shifted);
            }
            _ => rebound.push(arg.clone()),
        }
    }
    Some(rebound)
}

/// The arguments the one binder binds `post`'s contract with at a call
/// whose arguments are `args`: a dispatched answer's as the function it
/// resolved to takes them (`dispatched_arguments`), any other post's as they
/// stand.
fn post_arguments<'a>(
    post: &AmbientPost,
    args: &'a [Json],
) -> Option<std::borrow::Cow<'a, [Json]>> {
    if post.receiver == DispatchReceiver::AsCalled {
        return Some(std::borrow::Cow::Borrowed(args));
    }
    dispatched_arguments(&post.receiver, args).map(std::borrow::Cow::Owned)
}

/// Everything the join reads to resolve a dispatched method call (step 8):
/// the namespaces the proofs state, and what the contract each function
/// they name answers.
#[derive(Debug, Default)]
struct DispatchTable {
    namespaces: BTreeMap<String, ClassNamespace>,
    /// Each function symbol a namespace names, with the answer its bridge
    /// gives: `None` when no bridge, more than one target, a wrong answer, no
    /// post, or a `global:` input (a dispatched call supplies no module
    /// global, and the value the module's run left is not the one standing
    /// where the call may run).
    answers: BTreeMap<String, Option<BridgeAnswer>>,
    /// Each class a namespace row states, with the instance its constructor
    /// contract states it makes (`constructed_instance`): what a caller's
    /// `python:constructed(<class>)` is bound to. `None` where the contract
    /// does not decide it on every completed face, or no single bridge
    /// answers the class's symbol.
    constructed: BTreeMap<String, Option<Json>>,
}

/// The single bridge answer for `symbol` over `pool`: `None` when no bridge
/// states it, bridges state it with more than one target, or the answer is
/// wrong or states no post.
fn single_bridge_answer(pool: &MementoPool, symbol: &str) -> Option<BridgeAnswer> {
    let bridges: Vec<&sugar_proof_envelope::StoredMember> = pool
        .bridge_members()
        .filter(|(_, bridge)| bridge.field("sourceSymbol").and_then(|v| v.as_str()) == Some(symbol))
        .map(|(_, bridge)| bridge)
        .collect();
    let targets: std::collections::BTreeSet<&str> = bridges
        .iter()
        .filter_map(|bridge| bridge.field("targetContractCid").and_then(|v| v.as_str()))
        .collect();
    match bridges.first() {
        Some(first) if targets.len() == 1 => bridge_answer(pool, symbol, first).ok().flatten(),
        _ => None,
    }
}

/// The dispatch table over `pool` (step 8).
fn dispatch_table(pool: &MementoPool) -> DispatchTable {
    let namespaces = collect_class_namespaces(pool);
    // The instance each class's constructor contract states it makes: the
    // class row is the contract a call of the class joins (its bridge
    // answers the class's own symbol).
    let constructed: BTreeMap<String, Option<Json>> = namespaces
        .keys()
        .map(|class| {
            let instance = single_bridge_answer(pool, class).and_then(|(binding, post, ..)| {
                constructed_instance(&post, &binding.out_binding, class)
            });
            (class.clone(), instance)
        })
        .collect();
    let mut answers: BTreeMap<String, Option<BridgeAnswer>> = BTreeMap::new();
    for namespace in namespaces.values() {
        for (kind, symbol) in namespace.binds.values() {
            let dispatched = matches!(
                kind.as_str(),
                DISPATCH_FUNCTION_KIND
                    | DISPATCH_FIELD_KIND
                    | DISPATCH_STATIC_KIND
                    | DISPATCH_CLASS_KIND
                    | DISPATCH_PROPERTY_KIND
            );
            if !dispatched || symbol.is_empty() || answers.contains_key(symbol) {
                continue;
            }
            let answer = single_bridge_answer(pool, symbol).filter(|(binding, _, _, _, _)| {
                !binding
                    .formals
                    .iter()
                    .any(|formal| formal.starts_with(GLOBAL_INPUT_PREFIX))
            });
            answers.insert(symbol.clone(), answer);
        }
    }
    DispatchTable {
        namespaces,
        answers,
        constructed,
    }
}

/// `python:constructed(<class symbol>)` (the kit's
/// `receiver_dispatch.CONSTRUCTED`): the class of a same-file class call's
/// result as its construction left it. Bound to the instance the class's
/// constructor contract states (`constructed_instance`) before a method on
/// it is dispatched (`dispatch_answer`).
const PYTHON_CONSTRUCTED: &str = "python:constructed";
/// `python:type_is(<object>, <class symbol>)`: `type(<object>)` is that
/// class. A class's constructor contract states it of the instance it makes
/// (`python:after(out, "out")`) on every completed face it decides.
const PYTHON_TYPE_IS: &str = "python:type_is";
/// `python:may_hold(<object>, <name>)`: the object's `__dict__` may hold
/// `<name>`, one fact per name, stated beside `python:type_is`.
const PYTHON_MAY_HOLD: &str = "python:may_hold";
/// `python:class_undecided(<object>)`: a completed face of a constructor
/// contract that does not decide the class of the instance it makes, or
/// what its `__dict__` holds.
const PYTHON_CLASS_UNDECIDED: &str = "python:class_undecided";
/// `python:after(<object>, <label>)`: an object as a call left it; a
/// constructor contract names the instance it makes `python:after(out, "out")`.
const PYTHON_AFTER: &str = "python:after";

/// The class symbol a `python:constructed(<class symbol>)` names; `None` for
/// any other term.
fn constructed_class_symbol(class: &Json) -> Option<&str> {
    match ctor_parts(class)? {
        (PYTHON_CONSTRUCTED, args) => match args.as_slice() {
            [symbol] => const_str(symbol),
            _ => None,
        },
        _ => None,
    }
}

/// Whether `term` is `python:after(<out>, "out")`: the instance a
/// constructor contract makes, `out` its out-binding.
fn names_the_constructed_instance(term: &Json, out: &str) -> bool {
    let Some((PYTHON_AFTER, args)) = ctor_parts(term) else {
        return false;
    };
    match args.as_slice() {
        [object, label] => {
            object.get("kind").and_then(|v| v.as_str()) == Some("var")
                && object.get("name").and_then(|v| v.as_str()) == Some(out)
                && const_str(label) == Some("out")
        }
        _ => false,
    }
}

/// The instance a class's constructor contract states it makes (#7757 step
/// 8): `python:instance(<class>, <field>...)`, read off its `post`, where
/// every completed face states `python:type_is(python:after(out, "out"),
/// <class>)` and one `python:may_hold(python:after(out, "out"), <name>)` per
/// name its `__dict__` holds (the kit's `receiver_dispatch.
/// constructed_class_facts`). The fields are every name any completed face
/// states (what the `__dict__` may hold). `None` -- the dispatch over the
/// result stays owed -- where a face states `python:class_undecided`, a face
/// names another class, a name is not a string constant, or nothing states
/// the class.
fn constructed_instance(post: &Json, out: &str, class: &str) -> Option<Json> {
    let mut stated = false;
    let mut fields: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut pending: Vec<&Json> = vec![post];
    while let Some(node) = pending.pop() {
        match node {
            Json::Array(items) => pending.extend(items.iter()),
            Json::Object(map) => {
                let atom = node.get("kind").and_then(|v| v.as_str()) == Some("atomic");
                let name = node.get("name").and_then(|v| v.as_str());
                let args = node.get("args").and_then(|v| v.as_array());
                let about = args
                    .and_then(|args| args.first())
                    .is_some_and(|subject| names_the_constructed_instance(subject, out));
                if atom && about {
                    let operand = args.and_then(|args| args.get(1));
                    match name {
                        Some(PYTHON_CLASS_UNDECIDED) => return None,
                        Some(PYTHON_TYPE_IS) => {
                            if const_str(operand?)? != class {
                                return None;
                            }
                            stated = true;
                        }
                        Some(PYTHON_MAY_HOLD) => {
                            fields.insert(const_str(operand?)?.to_string());
                        }
                        _ => {}
                    }
                    continue;
                }
                pending.extend(map.values());
            }
            _ => {}
        }
    }
    if !stated {
        return None;
    }
    let mut args = vec![string_const_term(class)];
    args.extend(fields.iter().map(|field| string_const_term(field)));
    Some(json!({"kind": "ctor", "name": PYTHON_INSTANCE, "args": args}))
}

/// A dispatched member (step 8): the name it looks up, whether it is a read
/// of that attribute (`python:dispatch:.<name>`) or a call of it
/// (`python:dispatch:<name>`), and the table the join resolves it through.
#[derive(Debug)]
struct DispatchEdge {
    method: String,
    read: bool,
    table: Arc<DispatchTable>,
}

/// The contract that answers a dispatched method call or attribute read at
/// this read (step 8): the class the read binds the receiver's input to (the
/// call's `py.class` for its first positional argument) resolved by
/// `dispatched_target`, and the answer of that function's bridge, bound to
/// the call's arguments as the function's kind takes them
/// (`dispatched_arguments`) by the one binder. `None` -- the call stays owed
/// -- when `post` is no dispatched member, when nothing decides the method,
/// or when the call's arguments do not bind the function's formals (the call
/// was spelled for whatever runs, so a misfit is Python's `TypeError`, which
/// nothing here states).
fn dispatch_answer(post: &AmbientPost, call: &Json) -> Option<AmbientPost> {
    let dispatch = post.dispatch.as_ref()?;
    let args = call.get("args")?.as_array()?;
    let class = args.iter().find_map(|arg| match class_argument(arg) {
        Some(Ok((ClassKey::Position(0), class))) => Some(class),
        _ => None,
    })?;
    // A class call's result: the instance its class's constructor contract
    // states it makes (#7757 step 8), never a class nothing states.
    let constructed = constructed_class_symbol(&class).map(str::to_string);
    let class = match constructed {
        Some(symbol) => dispatch.table.constructed.get(&symbol)?.clone()?,
        None => class,
    };
    let target = dispatched_target(
        &dispatch.table.namespaces,
        &dispatch.method,
        dispatch.read,
        &class,
    )?;
    let (binding, answer, halt_guards, every_halt_guarded, typed_halts) =
        dispatch.table.answers.get(&target.symbol)?.clone()?;
    let rebound = dispatched_arguments(&target.receiver, args)?;
    bind_call_arguments(&binding.formals, &binding.stated_inputs, &rebound)?;
    Some(AmbientPost {
        binding,
        post: answer,
        halt_guards,
        every_halt_guarded,
        typed_halts,
        member_cid: post.member_cid.clone(),
        site_cid: post.site_cid.clone(),
        refusal: None,
        dispatch: None,
        receiver: target.receiver,
    })
}

/// THE JOIN (step 9; row 0a.5). Each unanswered call member's `symbol` is
/// joined to the bridge whose `sourceSymbol` is the same string, over every
/// proof prove read: the project's own `.proof` and the imported ones alike
/// (owner, 2026-11-15, #7757: a same-file call is coordinate + edge, joined
/// at prove exactly like an imported call). Who spoke the bridge is never
/// read here; it decides only where an import's own rows are reported
/// (`report::member_is_imported`). The join is by symbol and site, never by a
/// call term's spelling: the caller's call term is the same whether anything
/// answers it.
///
/// - No bridge states the symbol: the edge is unbound and the member stays
///   owed (nothing here).
/// - Bridges state it with more than one target: refused, `ambiguous-target`.
/// - A bridge's target is missing, of the wrong kind or from the wrong
///   provider: refused by name.
/// - The answering contract is recursive (it reaches itself through calls
///   the join answers): the encoding states no recursion, so the call is not
///   answered and its member stays owed (`recursive_contract_cids`).
///
/// Every edge nothing answers, and every `undecided` member with no symbol
/// (an owed operation), is carried as an owed entry at its site
/// (`DroppedAmbientPostReason::is_owed`): it answers nothing and conjoins
/// nothing, but a row that reads its site through a joined contract is not
/// decided on that free value.
fn collect_ambient_posts(pool: &MementoPool) -> Vec<AmbientPost> {
    let edges = unanswered_edges(pool);
    let mut posts = Vec::new();
    let mut owed = Vec::new();
    let mut table: Option<Arc<DispatchTable>> = None;
    for edge in &edges {
        // A dispatched method call (step 8): no bridge states its symbol.
        // It is owed as it stands; a read that binds its receiver's class
        // resolves it (`dispatch_answer`).
        if let Some(member) = edge.symbol.strip_prefix(DISPATCH_SYMBOL_PREFIX) {
            let table = table.get_or_insert_with(|| Arc::new(dispatch_table(pool)));
            let mut post = owed_post(
                &edge.symbol,
                &edge.member_cid,
                &edge.site_cid,
                DroppedAmbientPostReason::Unanswered,
            );
            let (method, read) = match member.strip_prefix(DISPATCH_READ_MARK) {
                Some(attribute) => (attribute, true),
                None => (member, false),
            };
            post.dispatch = Some(Arc::new(DispatchEdge {
                method: method.to_string(),
                read,
                table: Arc::clone(table),
            }));
            owed.push(post);
            continue;
        }
        let bridges: Vec<&sugar_proof_envelope::StoredMember> = pool
            .bridge_members()
            .filter(|(_, bridge)| {
                bridge.field("sourceSymbol").and_then(|v| v.as_str()) == Some(edge.symbol.as_str())
            })
            .map(|(_, bridge)| bridge)
            .collect();
        let Some(first) = bridges.first() else {
            owed.push(owed_post(
                &edge.symbol,
                &edge.member_cid,
                &edge.site_cid,
                DroppedAmbientPostReason::Unanswered,
            ));
            continue;
        };
        let targets: std::collections::BTreeSet<&str> = bridges
            .iter()
            .filter_map(|bridge| bridge.field("targetContractCid").and_then(|v| v.as_str()))
            .collect();
        let answer = if targets.len() > 1 {
            Err((
                targets.into_iter().collect::<Vec<_>>().join(" | "),
                DroppedAmbientPostReason::AmbiguousTarget,
            ))
        } else {
            bridge_answer(pool, &edge.symbol, first)
        };
        match answer {
            Ok(Some((binding, post, halt_guards, every_halt_guarded, typed_halts))) => {
                posts.push(AmbientPost {
                    binding,
                    post,
                    halt_guards,
                    every_halt_guarded,
                    typed_halts,
                    member_cid: edge.member_cid.clone(),
                    site_cid: edge.site_cid.clone(),
                    refusal: None,
                    dispatch: None,
                    receiver: DispatchReceiver::AsCalled,
                })
            }
            Ok(None) => owed.push(owed_post(
                &edge.symbol,
                &edge.member_cid,
                &edge.site_cid,
                DroppedAmbientPostReason::Unanswered,
            )),
            Err((target_cid, reason)) => posts.push(AmbientPost {
                binding: BridgeBinding {
                    source_symbol: edge.symbol.clone(),
                    target_cid,
                    target_proof_cid: None,
                    formals: Vec::new(),
                    out_binding: String::new(),
                    stated_inputs: Vec::new(),
                },
                post: Json::Null,
                halt_guards: Vec::new(),
                every_halt_guarded: false,
                typed_halts: Vec::new(),
                member_cid: edge.member_cid.clone(),
                site_cid: edge.site_cid.clone(),
                refusal: Some(reason),
                dispatch: None,
                receiver: DispatchReceiver::AsCalled,
            }),
        }
    }
    for (site_cid, (member_cid, subject)) in unanswered_operations(pool) {
        owed.push(owed_post(
            &subject,
            &member_cid,
            &site_cid,
            DroppedAmbientPostReason::Unanswered,
        ));
    }
    let recursive = recursive_contract_cids(&posts);
    let mut joined: Vec<AmbientPost> = posts
        .into_iter()
        .map(|post| {
            let on_cycle =
                post.refusal.is_none() && recursive.contains(post.binding.target_cid.as_str());
            if !on_cycle {
                return post;
            }
            info!(
                symbol = %post.binding.source_symbol,
                target_cid = %post.binding.target_cid,
                member_cid = %post.member_cid,
                "verifier/linker: a recursive contract answers this call; the encoding states no recursion, so the call stays owed"
            );
            owed_post(
                &post.binding.source_symbol,
                &post.member_cid,
                &post.site_cid,
                DroppedAmbientPostReason::RecursiveContract,
            )
        })
        .collect();
    joined.extend(owed);
    joined
}

/// An owed entry at `site_cid`: it answers nothing and conjoins nothing; a
/// row that reads the site through a joined contract is not decided on it.
fn owed_post(
    subject: &str,
    member_cid: &str,
    site_cid: &str,
    reason: DroppedAmbientPostReason,
) -> AmbientPost {
    AmbientPost {
        binding: BridgeBinding {
            source_symbol: subject.to_string(),
            target_cid: String::new(),
            target_proof_cid: None,
            formals: Vec::new(),
            out_binding: String::new(),
            stated_inputs: Vec::new(),
        },
        post: Json::Null,
        halt_guards: Vec::new(),
        every_halt_guarded: false,
        typed_halts: Vec::new(),
        member_cid: member_cid.to_string(),
        site_cid: site_cid.to_string(),
        refusal: Some(reason),
        dispatch: None,
        receiver: DispatchReceiver::AsCalled,
    }
}

// ── A joined callee's halts are the caller's halts at the call (step 9) ────
//
// When an edge joins a contract, the callee's halt sites stay the callee's
// own rows (an import's are the import's state). The CALLER can halt there
// too: in Python, if `f` can raise, `f(x)` raises at the call. So each halt
// of the joined contract, its guard written over the call's actuals, is a
// panic-locus row of the caller located at the call site, alongside the
// callee's own row, never instead of it. A callee's halts include, in turn,
// the halts of the contracts its own reads join. One join: imported and
// same-proof callees alike.

/// The join's answers, by the call site they answer, and where each site is.
pub(crate) struct JoinedHalts {
    answers: BTreeMap<String, Vec<AmbientPost>>,
    /// Each dispatched method call's member by its site (step 8): answered
    /// where the read binds its receiver's class (`dispatch_answer`).
    dispatch: BTreeMap<String, AmbientPost>,
    /// Site CID to the call site's `(file, line)` (the `undecided` member's).
    sites: BTreeMap<String, (String, u64)>,
}

impl JoinedHalts {
    pub(crate) fn of(pool: &MementoPool) -> Self {
        let mut answers: BTreeMap<String, Vec<AmbientPost>> = BTreeMap::new();
        let mut dispatch: BTreeMap<String, AmbientPost> = BTreeMap::new();
        for post in collect_ambient_posts(pool) {
            if post.refusal.is_none() {
                answers.entry(post.site_cid.clone()).or_default().push(post);
            } else if post.dispatch.is_some() {
                dispatch.insert(post.site_cid.clone(), post);
            }
        }
        let mut sites = BTreeMap::new();
        if !answers.is_empty() || !dispatch.is_empty() {
            for (_cid, member) in pool.undecided_members() {
                let Ok(undecided) = sugar_proof_envelope::UndecidedMember::from_stored(member)
                else {
                    continue;
                };
                let site_cid = undecided_site_coordinate_cid(&undecided.site);
                if answers.contains_key(&site_cid) || dispatch.contains_key(&site_cid) {
                    let line = u64::try_from(undecided.site.start_line).unwrap_or_default();
                    sites.insert(site_cid, (undecided.site.file.clone(), line));
                }
            }
        }
        Self {
            answers,
            dispatch,
            sites,
        }
    }

    /// The halts `body` reaches through the calls it reads that the join
    /// answers: one panic locus per halt of each joined contract (and of the
    /// contracts that one's reads join), its guard over `body`'s terms, at
    /// the call site in `body`. The callee's halt site is carried as the
    /// locus's producer (`producerFile`, `producerLine`, `producerSymbol`).
    pub(crate) fn loci_at_calls(&self, pool: &MementoPool, body: &Json) -> Vec<Json> {
        if self.answers.is_empty() && self.dispatch.is_empty() {
            return Vec::new();
        }
        self.loci_through(pool, body, &mut Vec::new(), &[])
    }

    /// `outer` binds `body`'s formals to what the reads that reached it bind
    /// them to: a dispatched call in `body` is resolved at the class its
    /// receiver's input is bound to there (step 8).
    fn loci_through(
        &self,
        pool: &MementoPool,
        body: &Json,
        visiting: &mut Vec<String>,
        outer: &[(String, Json)],
    ) -> Vec<Json> {
        let mut loci = Vec::new();
        let mut reads = Vec::new();
        for slot in ["pre", "post", "inv"] {
            if let Some(formula) = body.get(slot).filter(|f| f.is_object()) {
                for term in call_result_terms(formula) {
                    if !reads.contains(&term) {
                        reads.push(term);
                    }
                }
            }
        }
        for read in &reads {
            let Some((call, site_cid)) = call_result_parts(read) else {
                continue;
            };
            let Some(args) = call.get("args").and_then(|v| v.as_array()) else {
                continue;
            };
            // A dispatched call (step 8) is answered where the class its
            // receiver's input is bound to here decides the method.
            let dispatched: Vec<AmbientPost> = match self.dispatch.get(site_cid) {
                Some(post) if !self.answers.contains_key(site_cid) => {
                    dispatch_answer(post, &substitute_term_bindings(call, outer))
                        .into_iter()
                        .collect()
                }
                _ => Vec::new(),
            };
            let answers: Vec<&AmbientPost> = self
                .answers
                .get(site_cid)
                .map(|posts| posts.iter().collect())
                .unwrap_or_default();
            if answers.is_empty() && dispatched.is_empty() {
                continue;
            }
            let (file, line) = self
                .sites
                .get(site_cid)
                .cloned()
                .unwrap_or_else(|| (String::new(), 0));
            for post in answers.into_iter().chain(dispatched.iter()) {
                // The call's arguments bound to the contract's parameters and
                // inputs by the one binder the join binds the post with
                // (step 4). A call that does not fit is refused at the join
                // (`import-signature-mismatch`), so no halt is stated through
                // it here either. A dispatched answer binds them as the kind
                // of function it resolved to takes them (`post_arguments`).
                let Some(bindings) = post_arguments(post, args).and_then(|args| {
                    bind_call_arguments(&post.binding.formals, &post.binding.stated_inputs, &args)
                }) else {
                    continue;
                };
                // What the callee's formals are bound to as the reads that
                // reached this one bind them: what a dispatched call in the
                // callee reads its receiver's class at.
                let reached: Vec<(String, Json)> = bindings
                    .iter()
                    .map(|(formal, value)| (formal.clone(), substitute_term_bindings(value, outer)))
                    .collect();
                for locus in self.callee_loci(pool, &post.binding.target_cid, visiting, &reached) {
                    loci.push(halt_at_call(
                        &locus,
                        &bindings,
                        &file,
                        line,
                        &post.binding.source_symbol,
                    ));
                }
            }
        }
        loci
    }

    /// Every halt of the contract `target_cid`, its guards over its formals:
    /// its own panic loci, and the halts its reads reach through the join. A
    /// contract already being followed contributes its own loci only.
    fn callee_loci(
        &self,
        pool: &MementoPool,
        target_cid: &str,
        visiting: &mut Vec<String>,
        reached: &[(String, Json)],
    ) -> Vec<Json> {
        let Some(body) = MementoCid::try_parse(target_cid.to_string())
            .ok()
            .and_then(|cid| pool.contract_body_by_cid(&cid))
        else {
            return Vec::new();
        };
        let mut loci = crate::enumerate_callsites::panic_loci_from_body(&body);
        if visiting.iter().any(|seen| seen == target_cid) {
            return loci;
        }
        visiting.push(target_cid.to_string());
        loci.extend(self.loci_through(pool, &body, visiting, reached));
        visiting.pop();
        loci
    }
}

/// A callee's halt locus as the caller's: its guard with the callee's formals
/// replaced by what the call binds them to (`bind_call_arguments`, the
/// binder the post is joined with), located at the call site; the callee's
/// own site is kept as the producer. An input the call does not supply stays
/// free in the guard, so the halt is never ruled out on a value the caller
/// did not give.
fn halt_at_call(
    locus: &Json,
    bindings: &[(String, Json)],
    file: &str,
    line: u64,
    symbol: &str,
) -> Json {
    let mut at_call = locus.as_object().cloned().unwrap_or_default();
    if let Some(guard) = locus.get("guard").filter(|g| g.is_object()) {
        let guard = substitute_call_bindings(guard, bindings);
        at_call.insert("guard".to_string(), fold_ground_applications(&guard));
    }
    let producer_file = locus
        .get("producerFile")
        .or_else(|| locus.get("file"))
        .cloned()
        .unwrap_or(Json::Null);
    let producer_line = locus
        .get("producerLine")
        .or_else(|| locus.get("line"))
        .cloned()
        .unwrap_or(Json::Null);
    let producer_symbol = locus
        .get("producerSymbol")
        .cloned()
        .unwrap_or_else(|| Json::String(symbol.to_string()));
    at_call.insert("producerFile".to_string(), producer_file);
    at_call.insert("producerLine".to_string(), producer_line);
    at_call.insert("producerSymbol".to_string(), producer_symbol);
    at_call.insert("file".to_string(), Json::String(file.to_string()));
    at_call.insert("line".to_string(), Json::from(line));
    at_call.remove("start_line");
    at_call.remove("col");
    Json::Object(at_call)
}

/// Every `python:call_result` term a formula states outside a quantifier.
fn call_result_terms(formula: &Json) -> Vec<Json> {
    let mut terms = Vec::new();
    collect_unquantified_ctor_terms(formula, &mut terms);
    terms.retain(is_call_result_term);
    terms
}

fn is_call_result_term(term: &Json) -> bool {
    term.get("name").and_then(|v| v.as_str()) == Some(PYTHON_CALL_RESULT)
}

/// The answering contracts that reach themselves through the join (step 9):
/// a contract whose post or halt guards read a call (`python:call_result` at
/// an edge's site) that the join answers with a contract that reaches the
/// first one again, itself included. These are the reads the joined post
/// instances follow (`linked_ambient_post_instances_for_inv`), so a contract
/// not in this set is never re-entered by the join.
fn recursive_contract_cids(posts: &[AmbientPost]) -> std::collections::BTreeSet<String> {
    use std::collections::BTreeSet;
    let answered: Vec<&AmbientPost> = posts.iter().filter(|p| p.refusal.is_none()).collect();
    let mut targets_by_site: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
    for post in &answered {
        targets_by_site
            .entry(post.site_cid.as_str())
            .or_default()
            .push(post.binding.target_cid.as_str());
    }
    let mut successors: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for post in &answered {
        let target = post.binding.target_cid.as_str();
        if successors.contains_key(target) {
            continue;
        }
        let mut reads = call_result_terms(&post.post);
        for guard in &post.halt_guards {
            reads.extend(call_result_terms(guard));
        }
        let mut next: BTreeSet<&str> = BTreeSet::new();
        for read in &reads {
            if let Some((_call, site)) = call_result_parts(read) {
                if let Some(site_targets) = targets_by_site.get(site) {
                    next.extend(site_targets.iter().copied());
                }
            }
        }
        successors.insert(target, next);
    }
    let mut recursive = BTreeSet::new();
    for (&start, first) in &successors {
        let mut stack: Vec<&str> = first.iter().copied().collect();
        let mut seen: BTreeSet<&str> = BTreeSet::new();
        while let Some(node) = stack.pop() {
            if node == start {
                recursive.insert(start.to_string());
                break;
            }
            if !seen.insert(node) {
                continue;
            }
            if let Some(next) = successors.get(node) {
                stack.extend(next.iter().copied());
            }
        }
    }
    recursive
}

/// The `undecided` members the join answers: a vendor contract states a post
/// for the call, rightly, and every claim that reads the call conjoins it.
/// They are no longer owed; their call's row carries the verdict. A member
/// answered wrongly stays owed, and its row is refused. A member whose post a
/// claim dropped (open after specialization, a call term that does not
/// decode) is not answered either: it stays owed, and that claim's row is
/// not decided on what remains (`refuse_dropped_answers`).
///
/// A dispatched method call's member (step 8) is answered where claims read
/// it themselves and every such read binds its receiver's class to one that
/// decides the method (`dispatch_answer`). A member read only through a
/// joined contract (`self.m()` in a method another call joins) stays owed:
/// the method's own proof states no class for it.
pub(crate) fn joined_member_cids(pool: &MementoPool) -> std::collections::BTreeSet<String> {
    let ambient = collect_ambient_posts(pool);
    if ambient.is_empty() {
        return std::collections::BTreeSet::new();
    }
    let mut dropped: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut resolved: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut unresolved: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    for (_cid, member) in pool.contract_members() {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        if !is_consistency_candidate(&body) {
            continue;
        }
        // The claims as the row's own call binds them (step 5), as
        // `members_answered_at_prove` and the consistency candidates read
        // them: a call whose actual is the row's own `global:<name>` input
        // (`f(LIMIT)`, or the `py.global` a call of a function reading it
        // supplies) is joined at the value the contract states, not dropped
        // as an instance over a free input. A row whose claims read an input
        // nothing states keeps its claims as they stand.
        let bound = bind_own_inputs(&body).unwrap_or_else(|_| body.clone());
        let claim = canonicalize_formula_json(&axiom_context_formula(&bound));
        let partition = linked_ambient_post_instances_for_inv(&claim, &ambient);
        dropped.extend(
            partition
                .dropped
                .into_iter()
                .map(|post| post.member_cid)
                .filter(|cid| !cid.is_empty()),
        );
        for (member_cid, answered) in partition.dispatched {
            if answered {
                resolved.insert(member_cid);
            } else {
                unresolved.insert(member_cid);
            }
        }
    }
    let mut joined: std::collections::BTreeSet<String> = ambient
        .into_iter()
        .filter(|post| post.refusal.is_none() && !dropped.contains(&post.member_cid))
        .map(|post| post.member_cid)
        .collect();
    joined.extend(
        resolved
            .into_iter()
            .filter(|cid| !unresolved.contains(cid) && !dropped.contains(cid)),
    );
    joined
}

// ── An operation with no symbol, answered at prove (step 9; #7766) ─────────
//
// An `undecided` member with no symbol is an operation the lifter left
// two-faced at its site: an `==` on a call's result, whose dispatch is not
// decided at lift because the result's type is not known there. It completes
// only under its own `python:<p>.completes(python:<p>(…, <site key>))` atom.
// No contract answers it by name. Prove answers it only where the contracts
// the join binds decide the operation itself: under what the joined posts
// state, alone, the solver proves the atom (the operation completes) or its
// negation (it raises). The joined post is what pins the operand's type and
// value, so the member is answered by the joined contract, exactly as a call
// member is answered by the contract its symbol joins. Where the join leaves
// the operand undecided, nothing is proved and the member stays owed.

/// The site an operation's completes atom is keyed on: an atomic
/// `<p>.completes(<p>(…, <key>))` whose key (the protocol term's last
/// argument, the kit's `occurrence_key`) is the site's coordinate CID, alone
/// or followed by `@<occurrence path>`. `None` when the atom is not that
/// shape.
fn completes_atom_site(atom: &Json) -> Option<&str> {
    let protocol = atom.get("name")?.as_str()?.strip_suffix(".completes")?;
    let [operation] = atom.get("args")?.as_array()?.as_slice() else {
        return None;
    };
    if operation.get("kind")?.as_str()? != "ctor" || operation.get("name")?.as_str()? != protocol {
        return None;
    }
    let key = operation.get("args")?.as_array()?.last()?.get("value")?.as_str()?;
    Some(key.split_once('@').map_or(key, |(site, _path)| site))
}

/// Every completes atom a claim states outside a quantifier, with its site.
fn collect_completes_atoms<'a>(node: &'a Json, out: &mut Vec<(&'a str, &'a Json)>) {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("atomic") => {
            if let Some(site) = completes_atom_site(node) {
                out.push((site, node));
            }
        }
        // A quantified body speaks of its bound instances, never of this
        // site's one evaluation.
        Some("forall") | Some("exists") => {}
        _ => {
            if let Some(operands) = node.get("operands").and_then(|v| v.as_array()) {
                for operand in operands {
                    collect_completes_atoms(operand, out);
                }
            }
        }
    }
}

/// Every `undecided` member with `reason: unanswered` and no symbol, by the
/// coordinate CID of its site: site CID to the member CID and the site's
/// `file:line` (what the member is named by, having no symbol).
fn unanswered_operations(pool: &MementoPool) -> BTreeMap<String, (String, String)> {
    use sugar_proof_envelope::{UndecidedMember, UndecidedReason};
    let mut operations = BTreeMap::new();
    for (cid, member) in pool.undecided_members() {
        let Ok(undecided) = UndecidedMember::from_stored(member) else {
            continue;
        };
        if undecided.reason != UndecidedReason::Unanswered {
            continue;
        }
        if undecided.symbol.as_deref().is_some_and(|s| !s.is_empty()) {
            continue;
        }
        operations.insert(
            undecided_site_coordinate_cid(&undecided.site),
            (
                cid.to_string(),
                format!("{}:{}", undecided.site.file, undecided.site.start_line),
            ),
        );
    }
    operations
}

/// Does the solver answer `goal` with `verdict`? The plan proves a goal by
/// refuting its negation: `Discharged` is "valid", `Unsatisfied` is "its
/// negation is satisfiable". Anything else (unknown, timeout, an encoding
/// stop) answers nothing.
fn joined_goal_has_verdict(
    goal: Json,
    verdict: ObligationVerdict,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> bool {
    let goal = canonicalize_formula_json(&fold_ground_applications(&goal));
    match CompilerInput::decode_json(goal) {
        Ok(input) => run_plan_with_compilers(plan, registry, compilers, &input).0 == verdict,
        Err(_) => false,
    }
}

/// What the contracts joined to `claim`'s calls state, alone: the
/// conjunction of the kept linked post instances, with the symbols they
/// answer. `None` when nothing joined, when a joined answer was dropped or
/// refused, or when the conjunction is not satisfiable (the call certainly
/// halts, so no operation after it is reached and none is decided by it).
fn joined_context(
    claim: &Json,
    ambient: &[AmbientPost],
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> Option<(Json, Vec<String>)> {
    let partition = linked_ambient_post_instances_for_inv(claim, ambient);
    if partition.kept.is_empty() || !partition.dropped.is_empty() {
        return None;
    }
    let mut symbols: Vec<String> = partition
        .kept
        .iter()
        .map(|post| post.binding.source_symbol.clone())
        .collect();
    symbols.sort();
    symbols.dedup();
    let context = IrFormula::And(
        partition
            .kept
            .iter()
            .map(|post| post.instantiated_post.clone())
            .collect(),
    )
    .to_value();
    let satisfiable = joined_goal_has_verdict(
        IrFormula::Not(context.clone()).to_value(),
        ObligationVerdict::Unsatisfied,
        plan,
        registry,
        compilers,
    );
    satisfiable.then_some((context, symbols))
}

/// Does `context` decide `atom`: does it prove the atom, or its negation?
fn joined_context_decides(
    context: &Json,
    atom: &Json,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> bool {
    // `context` entails a face exactly when `context` with the other face is
    // unsatisfiable: `not(context and counter)` is valid.
    let excludes = |counter: Json| -> bool {
        let goal =
            IrFormula::Not(IrFormula::And(vec![context.clone(), counter]).to_value()).to_value();
        joined_goal_has_verdict(goal, ObligationVerdict::Discharged, plan, registry, compilers)
    };
    // The atom is proved (its negation is excluded), or refuted.
    excludes(IrFormula::Not(atom.clone()).to_value()) || excludes(atom.clone())
}

/// The `undecided` members with no symbol that prove answers (step 9): member
/// CID to the reason, which names the joined contracts and the atoms they
/// decide.
///
/// A member is answered when a claim states its operation's completes atoms
/// (keyed at the member's site) and, in every claim that states them, what
/// the joined contracts state decides each one. A claim nothing joins, a
/// joined post that leaves the operand's type open, or a wrong or dropped
/// answer decides nothing: the member stays owed.
pub fn members_answered_at_prove(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> BTreeMap<String, String> {
    let mut answered: BTreeMap<String, String> = BTreeMap::new();
    let operations = unanswered_operations(pool);
    if operations.is_empty() {
        return answered;
    }
    let ambient = collect_ambient_posts(pool);
    let mut owed: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    for (_cid, member) in pool.contract_members() {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        if !is_consistency_candidate(&body) {
            continue;
        }
        // The claims as the row's own call binds them (step 5): each module
        // global input at the value the contract states for it, through the
        // one binder (`bind_own_inputs`). A claim reading an input nothing
        // states decides nothing.
        let Ok(bound) = bind_own_inputs(&body) else {
            continue;
        };
        let binds_own_inputs = bound != body;
        let claim = canonicalize_formula_json(&axiom_context_formula(&bound));
        let mut stated = Vec::new();
        collect_completes_atoms(&claim, &mut stated);
        let mut reads: BTreeMap<String, Vec<&Json>> = BTreeMap::new();
        for (site, atom) in stated {
            if let Some((member_cid, _subject)) = operations.get(site) {
                let atoms = reads.entry(member_cid.clone()).or_default();
                if !atoms.contains(&atom) {
                    atoms.push(atom);
                }
            }
        }
        if reads.is_empty() {
            continue;
        }
        // What the joined contracts state; where nothing is joined and the
        // row's own inputs were bound, the bound operation alone (an atom
        // over the stated values is proved or refuted by itself, or nothing
        // is answered).
        let context = joined_context(&claim, &ambient, plan, registry, compilers).or_else(|| {
            binds_own_inputs.then(|| {
                (
                    IrFormula::And(Vec::new()).to_value(),
                    vec!["the row's own stated inputs".to_string()],
                )
            })
        });
        for (member_cid, atoms) in reads {
            let reason = match &context {
                Some((joined, symbols))
                    if atoms.iter().copied().all(|atom| {
                        joined_context_decides(joined, atom, plan, registry, compilers)
                    }) =>
                {
                    let mut names: Vec<&str> = atoms
                        .iter()
                        .copied()
                        .filter_map(|atom| atom.get("name").and_then(|v| v.as_str()))
                        .collect();
                    names.sort_unstable();
                    names.dedup();
                    Some(format!(
                        "the joined contract ({}) decides {} at this site",
                        symbols.join(", "),
                        names.join(", ")
                    ))
                }
                _ => None,
            };
            match reason {
                Some(reason) if !owed.contains(&member_cid) => {
                    answered.entry(member_cid).or_insert(reason);
                }
                _ => {
                    answered.remove(&member_cid);
                    owed.insert(member_cid);
                }
            }
        }
    }
    info!(
        operations = operations.len(),
        answered = answered.len(),
        "verifier/linker: undecided operations answered by the joined contracts"
    );
    answered
}

/// `python:call_result(<call>, python:occurrence(<site CID>, …))` read as
/// `(<call>, <site CID>)`. `None` when the term is not that shape.
fn call_result_parts(term: &Json) -> Option<(&Json, &str)> {
    let args = term.get("args")?.as_array()?;
    let [call, occurrence] = args.as_slice() else {
        return None;
    };
    if occurrence.get("kind")?.as_str()? != "ctor"
        || occurrence.get("name")?.as_str()? != PYTHON_OCCURRENCE
    {
        return None;
    }
    let site = occurrence.get("args")?.as_array()?.first()?.get("value")?.as_str()?;
    Some((call, site))
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
    // Owed entries answer nothing: they matter only to a read reached through
    // a contract something answers.
    let is_owed = |post: &AmbientPost| post.refusal.as_ref().is_some_and(|r| r.is_owed());
    // A dispatched member is owed as it stands and answered where a read
    // binds its receiver's class (step 8).
    if ambient
        .iter()
        .all(|post| is_owed(post) && post.dispatch.is_none())
    {
        return AmbientPostInstances::default();
    }
    let mut callsites = Vec::new();
    collect_unquantified_ctor_terms(inv, &mut callsites);
    if callsites.is_empty() {
        return AmbientPostInstances::default();
    }

    let mut kept = Vec::new();
    let mut dropped = Vec::new();
    let mut owed_operations: Vec<(DroppedAmbientPost, Json)> = Vec::new();
    let mut dispatched_members: Vec<(String, bool)> = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    // The join reads only the term the claim constrains: the call's
    // completed result at its occurrence. The vendor's `out` IS that term.
    //
    // One join over every contract (step 9): a joined post reads calls of its
    // own (a same-file helper, or another import), and the claim reads them
    // through it, so each is joined in turn wherever it has an answer. The
    // claim's own reads are taken as they stand; a read a joined instance
    // adds is taken once. Each read carries the contracts it was reached
    // through, so the join never re-enters one (`RecursiveContract`).
    let term_key = |term: &Json| {
        libsugar::canonical::json_jcs(term)
            .unwrap_or_else(|_| serde_json::to_string(term).unwrap_or_default())
    };
    let mut pending: std::collections::VecDeque<(Json, Vec<String>)> = callsites
        .into_iter()
        .filter(is_call_result_term)
        .map(|term| (term, Vec::new()))
        .collect();
    let mut read: std::collections::BTreeSet<String> =
        pending.iter().map(|(term, _)| term_key(term)).collect();
    while let Some((result_term, through)) = pending.pop_front() {
        let result_term = &result_term;
        let Some((call, site_cid)) = call_result_parts(result_term) else {
            dropped.push(DroppedAmbientPost {
                source_symbol: "<unknown-call>".to_string(),
                target_cid: String::new(),
                member_cid: String::new(),
                reason: DroppedAmbientPostReason::CallTermDecodeFailed,
                spelling: compact_json(result_term),
            });
            continue;
        };
        // What answers this site: a contract (rightly or wrongly), or, when
        // nothing does, the owed entries. The claim's own read of an owed
        // site is that member's row; a read reached through a joined
        // contract leaves the claim reading a free value, so it is dropped
        // and the row is not decided on what remains (step 9).
        let at_site: Vec<&AmbientPost> = ambient
            .iter()
            .filter(|post| post.site_cid == site_cid)
            .collect();
        let stated: Vec<&AmbientPost> =
            at_site.iter().copied().filter(|p| !is_owed(*p)).collect();
        // A dispatched method call (step 8): the class this read binds its
        // receiver's input to decides which contract answers it, if any.
        let dispatched: Vec<AmbientPost> = if stated.is_empty() {
            at_site
                .iter()
                .filter_map(|post| dispatch_answer(post, call))
                .collect()
        } else {
            Vec::new()
        };
        if through.is_empty() {
            for post in at_site.iter().filter(|post| post.dispatch.is_some()) {
                dispatched_members.push((post.member_cid.clone(), !dispatched.is_empty()));
            }
        }
        let answering: Vec<&AmbientPost> = stated.into_iter().chain(dispatched.iter()).collect();
        if answering.is_empty() {
            // A site with no member at all is not a call another proof
            // answers: a body the lift reduced states its result in the same
            // post (`derived_equality_residue`), so nothing is owed there.
            if !through.is_empty() {
                for post in at_site {
                    dropped.push(DroppedAmbientPost {
                        source_symbol: post.binding.source_symbol.clone(),
                        target_cid: post.binding.target_cid.clone(),
                        member_cid: post.member_cid.clone(),
                        reason: post
                            .refusal
                            .clone()
                            .unwrap_or(DroppedAmbientPostReason::Unanswered),
                        spelling: compact_json(result_term),
                    });
                }
            }
            continue;
        }
        for post in answering {
            if let Some(reason) = &post.refusal {
                dropped.push(DroppedAmbientPost {
                    source_symbol: post.binding.source_symbol.clone(),
                    target_cid: post.binding.target_cid.clone(),
                    member_cid: post.member_cid.clone(),
                    reason: reason.clone(),
                    spelling: compact_json(result_term),
                });
                continue;
            }
            if through.contains(&post.binding.target_cid) {
                dropped.push(DroppedAmbientPost {
                    source_symbol: post.binding.source_symbol.clone(),
                    target_cid: post.binding.target_cid.clone(),
                    member_cid: post.member_cid.clone(),
                    reason: DroppedAmbientPostReason::RecursiveContract,
                    spelling: compact_json(result_term),
                });
                continue;
            }
            let Some(args) = call.get("args").and_then(|v| v.as_array()) else {
                dropped.push(DroppedAmbientPost {
                    source_symbol: post.binding.source_symbol.clone(),
                    target_cid: post.binding.target_cid.clone(),
                    member_cid: post.member_cid.clone(),
                    reason: DroppedAmbientPostReason::CallTermDecodeFailed,
                    spelling: compact_json(call),
                });
                continue;
            };
            // Positional and named arguments bound to the contract's
            // parameters and inputs (step 4): one binder for every call. A
            // dispatched answer binds them as the kind of function it
            // resolved to takes them (`post_arguments`, step 8).
            let Some(bindings) = post_arguments(post, args).and_then(|args| {
                bind_call_arguments(&post.binding.formals, &post.binding.stated_inputs, &args)
            }) else {
                dropped.push(DroppedAmbientPost {
                    source_symbol: post.binding.source_symbol.clone(),
                    target_cid: post.binding.target_cid.clone(),
                    member_cid: post.member_cid.clone(),
                    // A call that spreads an operand whose length or keys
                    // are not stated binds nothing decided: not answered,
                    // by name, never a wrong answer. Any other misfit is
                    // the contract answering the call wrongly.
                    reason: if spreads_undecided(args) {
                        DroppedAmbientPostReason::OpenAfterSpecialization
                    } else {
                        DroppedAmbientPostReason::ImportSignatureMismatch
                    },
                    spelling: compact_json(call),
                });
                continue;
            };
            // Where the call completes, every halt the contract states is
            // off its path: `completes(<result>) -> not(guard)` under the
            // call's actual (step 9). The completion is the lifter's one
            // completion atom over the call's result term
            // (`PYTHON_CALL_COMPLETES`), the same for a call whose value the
            // claim reads and one whose value is discarded (#7757 step 5).
            // A halt certain on the path refutes every arm on which the call
            // completed; an arm on which it halted (a handler that caught
            // the raise) is not ruled out by it; one the actual rules out
            // conjoins `true`. `out` stands for the result term here and is
            // replaced with it below, after the formals are bound, so no
            // caller term is ever rewritten by the callee's bindings.
            //
            // The converse, the completion fact: where every halt the
            // contract states names its guard (`every_halt_guarded`), those
            // are all the ways the call can halt (one locus per halted arm,
            // the arms of one reduction partition its executions), so where
            // none holds the call completes: `not(guard)... -> completes`,
            // and with no halt stated it always completes. Together:
            // `completes(<result>) <-> and(not(guard))`, for a joined call
            // only (an owed or refused call never reaches here and keeps both
            // faces). Without it a joined callee that cannot halt on these
            // actuals left the caller a satisfiable halt face, and a lie on
            // that call's handler path read sat.
            let completes = json!({
                "kind": "atomic",
                "name": PYTHON_CALL_COMPLETES,
                "args": [{"kind": "var", "name": post.binding.out_binding}],
            });
            let off_path = IrFormula::And(
                post.halt_guards
                    .iter()
                    .map(|guard| IrFormula::Not(guard.clone()).to_value())
                    .collect(),
            )
            .to_value();
            let mut instance = if post.every_halt_guarded && post.halt_guards.is_empty() {
                IrFormula::And(vec![post.post.clone(), completes]).to_value()
            } else if post.every_halt_guarded {
                IrFormula::And(vec![
                    post.post.clone(),
                    json!({"kind": "implies", "operands": [completes.clone(), off_path.clone()]}),
                    json!({"kind": "implies", "operands": [off_path, completes]}),
                ])
                .to_value()
            } else if post.halt_guards.is_empty() {
                post.post.clone()
            } else {
                IrFormula::And(vec![
                    post.post.clone(),
                    json!({"kind": "implies", "operands": [completes, off_path]}),
                ])
                .to_value()
            };
            instance = substitute_call_bindings(&instance, &bindings);
            instance = crate::instantiate::substitute_formula_pub(
                &instance,
                &post.binding.out_binding,
                result_term,
            );
            // Fold grounded primitives after specialization so linked posts
            // and structural dual faces see concrete values (#4398).
            instance = fold_ground_applications(&instance);
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
                    member_cid: post.member_cid.clone(),
                    reason: DroppedAmbientPostReason::OpenAfterSpecialization,
                    spelling: compact_json(&instance),
                });
                continue;
            }
            let key = libsugar::canonical::json_jcs(&instance)
                .unwrap_or_else(|_| serde_json::to_string(&instance).unwrap_or_default());
            if seen.insert(key) {
                // The joined contract's own reads, at the call's actual: the
                // claim reads them through this instance. The read at this
                // site is the one just answered (`out` stands for it).
                for nested in call_result_terms(&instance) {
                    let nested_site = call_result_parts(&nested).map(|(_, site)| site);
                    if nested_site == Some(site_cid) {
                        continue;
                    }
                    if read.insert(term_key(&nested)) {
                        let mut nested_through = through.clone();
                        nested_through.push(post.binding.target_cid.clone());
                        pending.push_back((nested, nested_through));
                    }
                }
                // The joined contract's owed operations (an `==` nothing
                // answers, keyed at the callee's site): the claim reads them
                // through this instance too. Each is settled against what the
                // joined posts state (`settle_owed_operations`).
                let mut atoms = Vec::new();
                collect_completes_atoms(&instance, &mut atoms);
                for (atom_site, atom) in atoms {
                    let owed_here: Vec<&AmbientPost> = ambient
                        .iter()
                        .filter(|p| p.site_cid == atom_site)
                        .collect();
                    if owed_here.is_empty() || !owed_here.iter().all(|p| is_owed(*p)) {
                        continue;
                    }
                    for owed in owed_here {
                        let entry = DroppedAmbientPost {
                            source_symbol: owed.binding.source_symbol.clone(),
                            target_cid: String::new(),
                            member_cid: owed.member_cid.clone(),
                            reason: owed
                                .refusal
                                .clone()
                                .unwrap_or(DroppedAmbientPostReason::Unanswered),
                            spelling: compact_json(atom),
                        };
                        if !owed_operations
                            .iter()
                            .any(|(seen, seen_atom)| seen == &entry && seen_atom == atom)
                        {
                            owed_operations.push((entry, atom.clone()));
                        }
                    }
                }
                kept.push(LinkedPostInstance {
                    binding: post.binding.clone(),
                    call: result_term.clone(),
                    vendor_post: post.post.clone(),
                    instantiated_post: canonicalize_formula_json(&instance),
                });
            }
        }
    }
    AmbientPostInstances {
        kept,
        dropped,
        owed_operations,
        dispatched: dispatched_members,
    }
}

/// An owed operation a joined post reads is a free value in the row unless
/// what the joined posts state, alone, decides its completes atom (proves it
/// or its negation): then the row reads a decided value. Otherwise it moves
/// to `dropped`, and the row is not decided on what remains
/// (`refuse_dropped_answers`), naming the owed member.
fn settle_owed_operations(
    partition: &mut AmbientPostInstances,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) {
    let owed = std::mem::take(&mut partition.owed_operations);
    if owed.is_empty() {
        return;
    }
    let context = IrFormula::And(
        partition
            .kept
            .iter()
            .map(|post| post.instantiated_post.clone())
            .collect(),
    )
    .to_value();
    for (entry, atom) in owed {
        if !joined_context_decides(&context, &atom, plan, registry, compilers) {
            partition.dropped.push(entry);
        }
    }
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

// ── The raised type of a joined call (step 9; #7757 step 7) ────────────────
//
// A call whose edge names its callee raises, when it halts, the exception
// `python:raised(<call term>, <occurrence>)` (the Python kit's
// `UnknownCalleeCallV1.faces`). A handler around the call tests it with
// `adt.is_python_type(<that exception>, <handler class>)`. The callee's
// contract states each halt it can take with its raised class and its guard
// (a panic locus's `argTerm` and `guard`). The halts of one reduction are
// its halted arms, whose guards are disjoint path conditions, so under halt
// `i`'s guard, bound to the call's actuals, the exception is an instance of
// exactly that class: whether the handler takes it is whether the class is
// the handler's class or a subclass of it. That is the class question
// `adt.is_python_type(<class>, <handler class>)`, true where the two are one
// class; any other pair is the open subclass question the ancestry join
// answers where a proof states the class's ancestry, and leaves open
// otherwise. A halt that names no class (an undetermined raise) states
// nothing, and the handler's test stays open.

/// The ctor naming the exception one evaluation of a call raised.
const PYTHON_RAISED: &str = "python:raised";
/// The open subclass question an `except` retains.
const PYTHON_IS_TYPE_PREDICATE: &str = "adt.is_python_type";

/// Every `adt.is_python_type(python:raised(..), <class>)` atom `node` states
/// outside a quantifier.
fn collect_raised_type_tests<'a>(node: &'a Json, out: &mut Vec<&'a Json>) {
    match node.get("kind").and_then(|k| k.as_str()) {
        Some("atomic") => {
            if node.get("name").and_then(|v| v.as_str()) != Some(PYTHON_IS_TYPE_PREDICATE) {
                return;
            }
            let Some([subject, _class]) = node
                .get("args")
                .and_then(|v| v.as_array())
                .map(Vec::as_slice)
            else {
                return;
            };
            if subject.get("kind").and_then(|v| v.as_str()) == Some("ctor")
                && subject.get("name").and_then(|v| v.as_str()) == Some(PYTHON_RAISED)
                && !out.contains(&node)
            {
                out.push(node);
            }
        }
        Some("forall") | Some("exists") => {}
        _ => {
            if let Some(operands) = node.get("operands").and_then(|v| v.as_array()) {
                for operand in operands {
                    collect_raised_type_tests(operand, out);
                }
            }
        }
    }
}

/// `{"kind":"implies","operands":[a, b]}`.
fn implies_formula(antecedent: Json, consequent: Json) -> Json {
    json!({ "kind": "implies", "operands": [antecedent, consequent] })
}

/// The facts that type each exception a joined call raised in `inv`: for
/// each handler test `adt.is_python_type(python:raised(<call>, <occurrence>),
/// <H>)` whose occurrence's site an answering contract joins (`ambient`),
/// and each halt that contract states with its class `T` and guard `g`
/// (`AmbientPost::typed_halts`), `g[actuals] -> (test <-> is(T, H))`, with
/// `is(T, H)` true where `T` and `H` are one class. The call's actuals are
/// bound to the contract's formals by the one binder
/// (`bind_call_arguments`); a call that does not fit types nothing.
fn raised_type_facts(inv: &Json, ambient: &[AmbientPost]) -> Vec<Json> {
    let mut tests = Vec::new();
    collect_raised_type_tests(inv, &mut tests);
    let mut facts: Vec<Json> = Vec::new();
    for test in tests {
        let Some([raised, handler]) = test
            .get("args")
            .and_then(|v| v.as_array())
            .map(Vec::as_slice)
        else {
            continue;
        };
        let Some((call, site_cid)) = call_result_parts(raised) else {
            continue;
        };
        let Some(args) = call.get("args").and_then(|v| v.as_array()) else {
            continue;
        };
        for post in ambient
            .iter()
            .filter(|post| post.site_cid == site_cid && post.refusal.is_none())
        {
            let Some(bindings) =
                bind_call_arguments(&post.binding.formals, &post.binding.stated_inputs, args)
            else {
                continue;
            };
            for (class, guard) in &post.typed_halts {
                let guard = fold_ground_applications(&substitute_call_bindings(guard, &bindings));
                let fact = if class == handler {
                    implies_formula(guard, (*test).clone())
                } else {
                    let class_test = json!({
                        "kind": "atomic",
                        "name": PYTHON_IS_TYPE_PREDICATE,
                        "args": [class, handler],
                    });
                    implies_formula(
                        guard,
                        IrFormula::And(vec![
                            implies_formula((*test).clone(), class_test.clone()),
                            implies_formula(class_test, (*test).clone()),
                        ])
                        .to_value(),
                    )
                };
                if !facts.contains(&fact) {
                    facts.push(fact);
                }
            }
        }
    }
    facts
}

/// Conjoin `raised_type_facts` with `inv`. Each fact is true of the call
/// whatever path the claim takes (it speaks of the exception that call
/// raised under the halt the callee took), so it is conjoined at the top.
fn with_raised_types(inv: Json, ambient: &[AmbientPost]) -> Json {
    if ambient.is_empty() {
        return inv;
    }
    let facts = raised_type_facts(&inv, ambient);
    if facts.is_empty() {
        return inv;
    }
    debug!(
        facts = facts.len(),
        "verifier/linker: conjoining the raised types of joined calls into obligation"
    );
    let mut operands = Vec::with_capacity(facts.len() + 1);
    operands.push(inv);
    operands.extend(facts);
    IrFormula::And(operands).to_value()
}

// ── The ancestry join (step 9; #7757) ──────────────────────────────────────
//
// A Python consumer's `except Handler` against a raised class it imported
// retains `adt.is_python_type(<class>, <handler>)`: nothing at lift testifies
// to an imported class's bases. The class's defining module states them: its
// proof carries one contract `<class symbol>::exception-ancestry` whose `inv`
// is `adt.is_python_type(<class>, <ancestor>)` for every ancestor its source
// testifies to. The two meet here, by the class's target symbol, and the
// facts are conjoined with the consumer's question, so the solver decides it.

/// The contract-name suffix of a class's ancestry row (the Python kit's
/// `tree_enumerate.EXCEPTION_ANCESTRY_SUFFIX`): `<class symbol>` + this.
pub(crate) const EXCEPTION_ANCESTRY_SUFFIX: &str = "::exception-ancestry";
/// The open subclass question, and the fact that answers it.
const PYTHON_IS_TYPE: &str = "adt.is_python_type";
/// An exception class's coordinate (`exception_type_identity_of_symbol`).
const PYTHON_EXCEPTION_TYPE_IDENTITY: &str = "python:exception_type_identity";

/// Every stated ancestry fact in a pool, keyed by the class's target symbol.
pub(crate) type ExceptionAncestry = BTreeMap<String, Vec<Json>>;

/// `python:exception_type_identity("import", "<q>")` read as its target
/// symbol `python:<q>`. A builtin or source-class coordinate names no symbol
/// another proof states facts for.
fn exception_identity_target_symbol(term: &Json) -> Option<String> {
    if term.get("kind")?.as_str()? != "ctor"
        || term.get("name")?.as_str()? != PYTHON_EXCEPTION_TYPE_IDENTITY
    {
        return None;
    }
    let args = term.get("args")?.as_array()?;
    let [tag, qualified] = args.as_slice() else {
        return None;
    };
    if tag.get("value")?.as_str()? != "import" {
        return None;
    }
    let qualified = qualified.get("value")?.as_str()?;
    if qualified.is_empty() {
        return None;
    }
    Some(format!("python:{qualified}"))
}

/// The class symbol an `adt.is_python_type(<class>, _)` atom asks about.
fn is_type_subject_symbol(formula: &Json) -> Option<String> {
    if formula.get("kind")?.as_str()? != "atomic"
        || formula.get("name")?.as_str()? != PYTHON_IS_TYPE
    {
        return None;
    }
    let args = formula.get("args")?.as_array()?;
    let [subject, _ancestor] = args.as_slice() else {
        return None;
    };
    exception_identity_target_symbol(subject)
}

/// The ancestry one contract body states, when it is an ancestry row:
/// `(class symbol, facts)`. Only facts about the class the row names are
/// read; a conjunct about anything else is not this row's statement.
fn exception_ancestry_of(body: &Json) -> Option<(String, Vec<Json>)> {
    let symbol = contract_property_name(body).strip_suffix(EXCEPTION_ANCESTRY_SUFFIX)?;
    let inv = canonicalize_formula_json(body.get("inv").filter(|v| v.is_object())?);
    let facts: Vec<Json> = top_level_conjuncts(inv)
        .into_iter()
        .filter(|fact| is_type_subject_symbol(fact).as_deref() == Some(symbol))
        .collect();
    (!facts.is_empty()).then(|| (symbol.to_string(), facts))
}

/// Every class ancestry the pool's proofs state.
fn collect_exception_ancestry(pool: &MementoPool) -> ExceptionAncestry {
    let mut ancestry = ExceptionAncestry::new();
    for (_cid, member) in pool.contract_members() {
        let Some(body) = pool
            .contract_body_for_member(member)
            .filter(|v| v.is_object())
        else {
            continue;
        };
        if let Some((symbol, facts)) = exception_ancestry_of(&body) {
            merge_exception_ancestry(&mut ancestry, symbol, facts);
        }
    }
    ancestry
}

fn merge_exception_ancestry(ancestry: &mut ExceptionAncestry, symbol: String, facts: Vec<Json>) {
    let stated = ancestry.entry(symbol).or_default();
    for fact in facts {
        if !stated.contains(&fact) {
            stated.push(fact);
        }
    }
}

fn collect_is_type_subject_symbols(node: &Json, out: &mut std::collections::BTreeSet<String>) {
    if let Some(symbol) = is_type_subject_symbol(node) {
        out.insert(symbol);
        return;
    }
    for key in ["operands", "args"] {
        if let Some(children) = node.get(key).and_then(|v| v.as_array()) {
            for child in children {
                collect_is_type_subject_symbols(child, out);
            }
        }
    }
    if let Some(body) = node.get("body") {
        collect_is_type_subject_symbols(body, out);
    }
}

/// The ancestor symbol an `adt.is_python_type(_, <ancestor>)` fact names,
/// when the ancestor is an import coordinate: another proof may state that
/// class's own ancestry.
fn is_type_ancestor_symbol(fact: &Json) -> Option<String> {
    let args = fact.get("args")?.as_array()?;
    let [_subject, ancestor] = args.as_slice() else {
        return None;
    };
    exception_identity_target_symbol(ancestor)
}

/// The ancestry of `symbol`'s class, closed across the staged proofs: the
/// facts the pool states for `symbol`, and, for each ancestor that is an
/// import coordinate, that ancestor's stated ancestry with `symbol`'s class
/// in its place. `class E(Base)` with `Base` imported states `is(E, Base)`
/// in E's proof; Base's proof states `is(Base, ValueError)`; the subclass
/// relation is transitive, so `is(E, ValueError)` is joined. A re-export is
/// the same edge: the package states `is(<package>.E, <module>.E)`, and the
/// defining module's facts follow. Each proof is read once per closure, so a
/// cycle ends.
fn closed_exception_ancestry(symbol: &str, ancestry: &ExceptionAncestry) -> Vec<Json> {
    let Some(stated) = ancestry.get(symbol) else {
        return Vec::new();
    };
    let mut facts: Vec<Json> = stated.clone();
    let mut read = std::collections::BTreeSet::from([symbol.to_string()]);
    let mut next = 0;
    while next < facts.len() {
        let fact = facts[next].clone();
        next += 1;
        let Some(ancestor) = is_type_ancestor_symbol(&fact) else {
            continue;
        };
        if !read.insert(ancestor.clone()) {
            continue;
        }
        let Some(subject) = fact
            .get("args")
            .and_then(|v| v.as_array())
            .and_then(|args| args.first())
            .cloned()
        else {
            continue;
        };
        for inherited in ancestry.get(&ancestor).into_iter().flatten() {
            let mut derived = inherited.clone();
            let Some(first) = derived
                .get_mut("args")
                .and_then(|v| v.as_array_mut())
                .and_then(|args| args.first_mut())
            else {
                continue;
            };
            *first = subject.clone();
            if !facts.contains(&derived) {
                facts.push(derived);
            }
        }
    }
    facts
}

/// The stated facts that answer `inv`'s open subclass questions: for each
/// `adt.is_python_type(<class>, _)` in `inv` whose class is an import
/// coordinate, the ancestry the pool states for that class's symbol, closed
/// across the staged proofs (`closed_exception_ancestry`). No proof states
/// it: nothing, and the question stays open.
fn exception_ancestry_facts_for_inv(inv: &Json, ancestry: &ExceptionAncestry) -> Vec<Json> {
    if ancestry.is_empty() {
        return Vec::new();
    }
    let mut symbols = std::collections::BTreeSet::new();
    collect_is_type_subject_symbols(inv, &mut symbols);
    let mut facts: Vec<Json> = Vec::new();
    for symbol in &symbols {
        for fact in closed_exception_ancestry(symbol, ancestry) {
            if !facts.contains(&fact) {
                facts.push(fact);
            }
        }
    }
    facts
}

/// THE ANCESTRY JOIN: conjoin the stated facts that answer `inv`'s open
/// subclass questions. Each fact is ground and true of the class the
/// defining module names, so it is conjoined at the top, wherever the
/// question stands inside `inv`.
fn with_exception_ancestry(inv: Json, ancestry: &ExceptionAncestry) -> Json {
    let facts = exception_ancestry_facts_for_inv(&inv, ancestry);
    if facts.is_empty() {
        return inv;
    }
    debug!(
        facts = facts.len(),
        "verifier/linker: conjoining stated exception ancestry into obligation"
    );
    let mut operands = Vec::with_capacity(facts.len() + 1);
    operands.push(inv);
    operands.extend(facts);
    IrFormula::And(operands).to_value()
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
        // The row's own claims are read over its inputs bound as a caller
        // after import binds them (`bind_own_inputs`, the one binder): each
        // module global at the value the contract states for it. An input
        // the contract states no value for stays a free variable of the row,
        // and the row is decided over every value of it
        // (`decide_over_unstated_inputs`), never refused for reading it.
        let (body, unstated_inputs) = bind_own_inputs_with_unstated(&body);
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
                        unstated_inputs,
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
            candidate.spoken_by_vendor,
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

/// THE consistency solve door, over every proof prove loaded (the project's
/// own `.proof` and the staged imports alike, one pool): build the pool's
/// `ConsistencyIndex` and solve it (`verify_consistency_from_index`).
/// Production `prove`, the editor (through the same `prove_rows`) and the
/// tests all come here, so the join (`collect_ambient_posts`) is always over
/// every contract prove has.
///
/// Zero project FS (#3809 series). Locus preference is speaker role only;
/// witness bodies come from the proof (step 9).
pub fn verify_consistency(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
) -> Vec<ConsistencyResult> {
    // project_root retained on the signature for API stability; never stats
    // for locus or scope.
    let _project_root = project_root;
    let index = build_consistency_index(pool);
    verify_consistency_from_index(&index, plan, registry, compilers)
}

/// Pool-derived consistency inputs. Every field is a pure projection of the
/// one pool prove loaded.
struct ConsistencyIndex {
    candidates: Vec<ConsistencyCandidate>,
    provenance_refusals: Vec<ConsistencyResult>,
    ambient_foralls: Vec<Json>,
    ambient_ground_callsite_facts: Vec<AmbientGroundCallsiteFact>,
    ambient_posts: Vec<AmbientPost>,
    /// The class ancestry this pool's proofs state, by class symbol: the
    /// facts the ancestry join conjoins (`with_exception_ancestry`).
    exception_ancestry: ExceptionAncestry,
    /// Raw (contract/property name, locus, optional speaker role) triples in
    /// pool iteration order. The project-local preference merge (consumer
    /// file beats vendor file for the squiggle anchor) happens at solve time
    /// in `verify_consistency_from_index` via speaker role only (#3809).
    locus_entries: Vec<(String, SourceLocus, Option<SpeakerRole>)>,
    /// Witness package bodies this pool's `witness-memento` members state
    /// (step 9: the body a witness row is decided from is in the proof).
    witness_bodies: WitnessBodies,
}

/// Build the pool's [`ConsistencyIndex`]: stage 1 of `verify_consistency`.
fn build_consistency_index(pool: &MementoPool) -> ConsistencyIndex {
    let (candidates, provenance_refusals) = collect_consistency_candidates(pool);

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
                candidate.spoken_by_vendor,
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
    let exception_ancestry = collect_exception_ancestry(pool);

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
        exception_ancestry,
        locus_entries,
        witness_bodies: witness_bodies_in_pool(pool),
    }
}

/// The per-pool solve: grouping and the per-group solve over the one pool's
/// index. Witness bodies are what the pool's `witness-memento` members state
/// (step 9: no kit is asked). Zero project FS (#3809).
fn verify_consistency_from_index(
    index: &ConsistencyIndex,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
) -> Vec<ConsistencyResult> {
    let witness_bodies: Arc<WitnessBodies> = Arc::new(index.witness_bodies.clone());
    let _witness_bodies_guard = WitnessBodiesGuard::enter(&witness_bodies);
    let candidates: Vec<&ConsistencyCandidate> = index.candidates.iter().collect();
    let provenance_refusals: Vec<ConsistencyResult> = index.provenance_refusals.clone();
    let ambient_foralls = &index.ambient_foralls;
    let ambient_ground_callsite_facts = &index.ambient_ground_callsite_facts;
    let ambient_posts = &index.ambient_posts;
    let exception_ancestry = &index.exception_ancestry;

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
        let name = consistency_group_name(candidate);
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
    for (name, l, role) in &index.locus_entries {
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

    let groups: Vec<(String, Vec<ConsistencyCandidate>)> = by_name
        .into_iter()
        .map(|(name, members)| (name, members.into_iter().cloned().collect()))
        .collect();

    let mut results: Vec<ConsistencyResult> = groups
        .par_iter()
        .flat_map(|(property_name, members)| {
            // Rayon workers have distinct thread-local storage.  The guard on
            // the caller thread cannot carry the witness bodies into this
            // closure, so install the same bodies for each group solve.
            let _worker_witness_bodies_guard = WitnessBodiesGuard::enter(&witness_bodies);
            process_consistency_group(
                property_name,
                members,
                ambient_posts,
                exception_ancestry,
                ambient_ground_callsite_facts,
                ambient_foralls,
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
/// behavior change) so grouping in `verify_consistency_from_index`
/// drives the conjoin/vacuity classification one `#euf#` group at a time.
/// `property_name`/`members` name one `#euf#` (or plain) callsite group;
/// `ambient_posts`/`ambient_ground_callsite_facts`/`ambient_foralls` are the
/// pool-wide background facts asserted into every obligation.
#[allow(clippy::too_many_arguments)]
fn process_consistency_group(
    property_name: &str,
    members: &[ConsistencyCandidate],
    ambient_posts: &[AmbientPost],
    exception_ancestry: &ExceptionAncestry,
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

        // CROSS-PROOF CONJOIN for CALLSITE-KEYED names (`#euf#`). That key is
        // `(callee, args)`, so same name == same call == sound to conjoin a
        // consumer's assertion with an imported vendor contract -> `and(==5,==6)`
        // -> unsat -> refused. A bare test/location name does NOT normally
        // guarantee the same subject, so those stay PER-CONTRACT.
        //
        // CRC value pins are the one typed bare-coordinate exception: the Java
        // owner emits a source-warranted `::assertion` and a source-warranted
        // `::crc-value-pin` from the same `locationBase`. The grouping key above
        // projects only that adjudicated pair onto the assertion coordinate;
        // both warrants must be present before this gate permits the conjoin.
        let callsite_keyed = EufCoordinate::parse(property_name).is_callsite_keyed();
        let crc_value_pin_join = has_crc_value_pin_assertion_pair(property_name, &inv_candidates);
        if (callsite_keyed || crc_value_pin_join) && inv_candidates.len() > 1 {
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
            let (inv, mut ambient_partition) =
                with_ambient_posts_with_instances(inv, &ambient_posts);
            settle_owed_operations(&mut ambient_partition, plan, registry, compilers);
            let inv = with_raised_types(inv, ambient_posts);
            let inv = with_exception_ancestry(inv, exception_ancestry);
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
            refuse_dropped_answers(&mut result);
            // The conjunction holds for every value of the members' unstated
            // inputs when each member's claim does.
            let mut unstated: Vec<String> = inv_candidates
                .iter()
                .flat_map(|candidate| candidate.unstated_inputs.iter().cloned())
                .collect();
            unstated.sort();
            unstated.dedup();
            if !unstated.is_empty() {
                decide_over_unstated_inputs(&mut result, &unstated, || {
                    inv_candidates.iter().all(|candidate| {
                        claim_holds_for_every_value(
                            &candidate.body,
                            ambient_posts,
                            exception_ancestry,
                            plan,
                            registry,
                            compilers,
                        )
                    })
                });
            }
            out.push(result);
        } else {
            for candidate in &inv_candidates {
                let original_inv =
                    canonicalize_formula_json(&axiom_context_formula(&candidate.body));
                let scope = ambient_ground_callsite_scope(property_name);
                let current_ground_witnesses =
                    ground_callsite_witness_keys(&original_inv, &scope, candidate.provenance_kind);
                let (inv, mut ambient_partition) =
                    with_ambient_posts_with_instances(original_inv.clone(), &ambient_posts);
                settle_owed_operations(&mut ambient_partition, plan, registry, compilers);
                let inv = with_raised_types(inv, ambient_posts);
                let inv = with_exception_ancestry(inv, exception_ancestry);
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
                refuse_dropped_answers(&mut result);
                if !candidate.unstated_inputs.is_empty() {
                    decide_over_unstated_inputs(&mut result, &candidate.unstated_inputs, || {
                        claim_holds_for_every_value(
                            &candidate.body,
                            ambient_posts,
                            exception_ancestry,
                            plan,
                            registry,
                            compilers,
                        )
                    });
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

    fn insert_source_warranted_contract(
        pool: &mut MementoPool,
        cid: &str,
        name: &str,
        inv: Json,
        role: &str,
        universe_kind: &str,
    ) {
        let env = json!({
            "envelope": {
                "header": {
                    "kind": "contract",
                    "contractName": name,
                    "inv": inv,
                    "sourceWarrants": [{
                        "kind": "source-memento",
                        "role": role,
                        "universe_kind": universe_kind,
                        "file": "CrcValuePinTest.java",
                        "source_cid": test_cid_string(cid),
                        "template_cid": test_cid_string(&format!("{cid}-template")),
                        "span": {
                            "start_line": 1,
                            "start_col": 0,
                            "end_line": 1,
                            "end_col": 1
                        }
                    }]
                }
            }
        });
        pool.insert_unanchored_for_tests(test_cid(cid), env);
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

    #[test]
    fn build_witness_claim_uses_the_rust_package_verification_path() {
        let body = package_contract("build-witness", "blake3-512:build", 1, 1);
        let claim = witness_package_claim(body.get("evidence").expect("evidence"), "build-witness")
            .expect("build-witness is an execution-witness package");

        assert_eq!(claim.package_cid, "blake3-512:build");
        assert_eq!(claim.expected_count, 1);
        assert_eq!(claim.expected_passed, 1);
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

    /// The witness bodies a proof states, for tests that call the arm directly.
    fn bodies_for(package_bytes: &[u8]) -> Arc<WitnessBodies> {
        let mut bodies = WitnessBodies::new();
        bodies.insert(blake3_512_of(package_bytes), package_bytes.to_vec());
        Arc::new(bodies)
    }

    /// A `witness-memento` member carrying its package body, as mint writes it.
    fn insert_witness_memento_with_body(pool: &mut MementoPool, label: &str, package_bytes: &[u8]) {
        let witness_cid = blake3_512_of(package_bytes);
        let env = json!({
            "header": {"kind": "witness-memento", "witnessCid": witness_cid},
            "body": {"kind": "witness-memento", "witness_cid": witness_cid,
                     "body_b64": B64.encode(package_bytes)},
            "schemaVersion": "1",
        });
        pool.insert_unanchored_for_tests(test_cid(label), env);
    }

    /// Step 9: only a member whose body addresses to its `witnessCid` states a
    /// body; anything else states none.
    #[test]
    fn witness_bodies_come_only_from_members_that_address_to_their_cid() {
        let good = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
        let mut pool = MementoPool::default();
        insert_witness_memento_with_body(&mut pool, "witness-good", good);
        let forged_cid = blake3_512_of(b"something else");
        pool.insert_unanchored_for_tests(
            test_cid("witness-forged"),
            json!({
                "header": {"kind": "witness-memento", "witnessCid": forged_cid},
                "body": {"kind": "witness-memento", "body_b64": B64.encode(good)},
                "schemaVersion": "1",
            }),
        );
        let bodies = witness_bodies_in_pool(&pool);
        assert_eq!(bodies.len(), 1, "{bodies:?}");
        assert_eq!(
            bodies.get(&blake3_512_of(good)).map(Vec::as_slice),
            Some(&good[..])
        );
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

    /// Step 9: a consistency row a staged import alone spoke is that proof's
    /// own state (`result_is_imported`). The importer's report carries it in
    /// `imported` with its status and counts none of it. A group the project
    /// speaks any candidate of stays the project's row, counted.
    #[test]
    fn a_consistency_row_only_an_import_spoke_is_the_imports_own_state() {
        use crate::types::SpeakerRole;
        let (plan, reg) = z3_plan_and_registry();
        let mut pool = MementoPool::default();
        // The import's own test: a lone constraint, refused as vacuous.
        insert_contract(
            &mut pool,
            "import-own-test",
            "test_vendor",
            eqf(var("v"), int(1)),
        );
        pool.attribute_member_for_tests(
            &test_cid_string("import-own-test"),
            SpeakerRole::Vendor,
            "the-vendor",
        );
        // A callsite-keyed group both speak: the consumer's claim beside the
        // import's, conjoined into one row.
        let shared = "numpy.add#euf#callresult_numpy_add_a2(2,3)::assertion";
        insert_contract(&mut pool, "shared-consumer", shared, eqf(var("r"), int(6)));
        insert_contract(&mut pool, "shared-vendor", shared, eqf(var("r"), int(5)));
        pool.attribute_member_for_tests(
            &test_cid_string("shared-consumer"),
            SpeakerRole::Consumer,
            "me",
        );
        pool.attribute_member_for_tests(
            &test_cid_string("shared-vendor"),
            SpeakerRole::Vendor,
            "the-vendor",
        );

        let results = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        let groups = groups_spoken_only_by_imports(&pool);
        let own = results
            .iter()
            .find(|r| r.property_name == "test_vendor")
            .expect("the import's own row");
        let mixed = results
            .iter()
            .find(|r| r.property_name == shared)
            .expect("the shared group's row");
        assert!(result_is_imported(&pool, &groups, own), "{own:?}");
        assert!(!result_is_imported(&pool, &groups, mixed), "{mixed:?}");

        let mut report = crate::types::Report::default();
        for result in &results {
            crate::report::add_consistency_result_spoken(
                result,
                result_is_imported(&pool, &groups, result),
                &mut report,
            );
        }
        // The import's row is visible, with its status, as the import's.
        assert_eq!(report.imported.len(), 1, "{:?}", report.imported);
        assert_eq!(report.imported[0].status, own.verdict);
        assert_eq!(
            report.imported[0].callsite.property_name,
            "consistency:test_vendor"
        );
        // The project's rows and counts are the shared group alone.
        assert_eq!(report.rows.len(), 1, "{:?}", report.rows);
        assert_eq!(
            report.rows[0].callsite.property_name,
            format!("consistency:{shared}")
        );
        assert_eq!(report.discharged + report.refused + report.violations, 1);
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

    /// #4398: vendor if-posts specialize `py.eq` guards at grounded callsites.
    /// `py.eq(1,1) => call:A(1)=7` conjoined with stated `call:A(1)=0` must
    /// refuse structurally — previously `eval_ground_atomic_bool` ignored
    /// `py.eq`, so the implies arm never opened and the lie SAT.
    #[test]
    fn grounded_py_eq_guard_opens_implies_for_structural_refute() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":1}
        ]});
        let inv = json!({"kind":"and","operands":[
            {"kind":"atomic","name":"py.eq","args":[
                call_a.clone(),
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":0},
            ]},
            {"kind":"implies","operands":[
                {"kind":"atomic","name":"py.eq","args":[
                    {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":1},
                    {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":1},
                ]},
                {"kind":"atomic","name":"=","args":[
                    call_a.clone(),
                    {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":7},
                ]},
            ]},
        ]});
        let reason = structural_contradiction_reason(&inv)
            .expect("py.eq(1,1) must open implies and dual-refute call:A(1)");
        assert!(
            reason.contains("equals both"),
            "expected dual-value structural reason, got: {reason}"
        );
    }

    /// #4398: `call:abs(-5)` folds to `5` so body dig + lying statement dual-refute.
    #[test]
    fn grounded_call_abs_folds_for_structural_refute() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":-5}
        ]});
        let inv = json!({"kind":"and","operands":[
            {"kind":"atomic","name":"py.eq","args":[
                call_a.clone(),
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":-5},
            ]},
            {"kind":"atomic","name":"=","args":[
                call_a.clone(),
                {"kind":"ctor","name":"call:abs","args":[
                    {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":-5},
                ]},
            ]},
        ]});
        let folded = fold_ground_applications(&inv);
        let reason = structural_contradiction_reason(&folded)
            .expect("folded abs must dual-refute call:A(-5)=5 vs -5");
        assert!(
            reason.contains("equals both"),
            "expected dual-value structural reason, got: {reason}"
        );
    }

    /// #4398: `py.complex` is a data value — dual complex literals refuse.
    #[test]
    fn grounded_py_complex_value_contradiction_refuses_structurally() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":5}
        ]});
        let complex = |im: &str| {
            json!({"kind":"ctor","name":"py.complex","args":[
                {"kind":"const","sort":{"kind":"primitive","name":"Real"},"value":"0.0"},
                {"kind":"const","sort":{"kind":"primitive","name":"Real"},"value":im},
            ]})
        };
        let inv = json!({"kind":"and","operands":[
            {"kind":"atomic","name":"=","args":[call_a.clone(), complex("2.0")]},
            {"kind":"atomic","name":"py.eq","args":[call_a.clone(), complex("3.0")]},
        ]});
        let reason = structural_contradiction_reason(&inv)
            .expect("py.complex(0,2) vs py.complex(0,3) must dual-refute");
        assert!(
            reason.contains("equals both"),
            "expected dual-value structural reason, got: {reason}"
        );
    }

    /// #4387 residual: `py.ellipsis` is a data singleton — dual vs `None` refuses.
    #[test]
    fn grounded_py_ellipsis_value_contradiction_refuses_structurally() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":5}
        ]});
        let ellipsis = json!({"kind":"ctor","name":"py.ellipsis","args":[]});
        let none = json!({"kind":"ctor","name":"None","args":[]});
        let inv = json!({"kind":"and","operands":[
            {"kind":"atomic","name":"=","args":[call_a.clone(), ellipsis]},
            {"kind":"atomic","name":"py.eq","args":[call_a.clone(), none]},
        ]});
        let reason =
            structural_contradiction_reason(&inv).expect("py.ellipsis vs None must dual-refute");
        assert!(
            reason.contains("equals both"),
            "expected dual-value structural reason, got: {reason}"
        );
    }

    /// #4398: `py.in` membership on a ground tuple opens implies arms.
    #[test]
    fn grounded_py_in_guard_opens_implies_for_structural_refute() {
        let call_a = json!({"kind":"ctor","name":"call:A","args":[
            {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":2}
        ]});
        let inv = json!({"kind":"and","operands":[
            {"kind":"atomic","name":"py.eq","args":[
                call_a.clone(),
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":0},
            ]},
            {"kind":"implies","operands":[
                {"kind":"atomic","name":"py.in","args":[
                    {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":2},
                    {"kind":"ctor","name":"tuple","args":[
                        {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":1},
                        {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":2},
                        {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":3},
                    ]},
                ]},
                {"kind":"atomic","name":"=","args":[
                    call_a.clone(),
                    {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":1},
                ]},
            ]},
        ]});
        let reason = structural_contradiction_reason(&inv)
            .expect("py.in(2,tuple(1,2,3)) must open implies and dual-refute");
        assert!(
            reason.contains("equals both"),
            "expected dual-value structural reason, got: {reason}"
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

    #[test]
    fn crc_assertion_and_walked_value_pin_share_one_contradiction() {
        let (plan, reg) = z3_plan_and_registry();
        let location = "getValue@Test.java::CrcTest::wrong:crc";
        let asserted = int(2);
        let call = json!({
            "kind": "ctor",
            "name": "call:getValue",
            "args": [{"kind": "var", "name": "crc"}]
        });
        let walked = serde_json::to_string(&json!({"kind": "const", "value": 1})).unwrap();
        let mut pool = MementoPool::default();
        insert_source_warranted_contract(
            &mut pool,
            "crc-assertion",
            &format!("{location}::assertion"),
            eqf(call, asserted.clone()),
            "java.test-fact",
            "vendor-fixedpoint",
        );
        insert_source_warranted_contract(
            &mut pool,
            "crc-walked-pin",
            &format!("{location}::crc-value-pin"),
            json!({
                "kind": "atomic",
                "name": "crc32.eq-walked",
                "args": [asserted, str_const(&walked)]
            }),
            "java.crc-value-pin",
            "crc32.eq-walked",
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "CRC facts must form one group: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "the walked value 1 contradicts the asserted CRC value 2: {res:?}"
        );
    }

    #[test]
    fn lone_consistent_crc_walked_pin_stays_vacuous_refused() {
        let (plan, reg) = z3_plan_and_registry();
        let walked = serde_json::to_string(&json!({"kind": "const", "value": 1})).unwrap();
        let mut pool = MementoPool::default();
        insert_source_warranted_contract(
            &mut pool,
            "crc-lone-pin",
            "getValue@Test.java::CrcTest::lone:crc::crc-value-pin",
            json!({
                "kind": "atomic",
                "name": "crc32.eq-walked",
                "args": [int(1), str_const(&walked)]
            }),
            "java.crc-value-pin",
            "crc32.eq-walked",
        );

        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one CRC pin yields one row: {res:?}");
        assert_eq!(res[0].verdict, ObligationVerdict::Refused, "{res:?}");
        assert!(
            res[0].reason.contains("single constraint has no sibling"),
            "the refusal must remain explicitly vacuous: {}",
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

    /// COVERING UNIVERSE — string theory. The string-predicate lifter emits
    /// ground `prefix-of`/`suffix-of`/`contains` for literal receivers
    /// (`"abc".starts_with("a")` → `prefix-of("a","abc")`). z3's string sort
    /// decides these atoms; a lone matching ground predicate must DISCHARGE,
    /// not trip the count<2 vacuity refuse (std-core-string-predicates).
    #[test]
    fn lone_ground_prefix_of_matching_subject_discharges() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "method:starts_with#euf#c:callresult_method_starts_with_a2(s:\"abc\",s:\"a\")::assertion";
        let inv = json!({
            "kind": "and",
            "operands": [{
                "kind": "atomic",
                "name": "prefix-of",
                "args": [str_const("a"), str_const("abc")]
            }]
        });
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:prefixgood", name, inv);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one prefix-of row: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Discharged,
            "ground prefix-of(\"a\",\"abc\") is string-theory membership of the prefix relation -> discharged: {res:?}"
        );
    }

    /// THE TEETH: ground `contains` that is false under string theory is Unsatisfied.
    #[test]
    fn lone_ground_contains_nonmatching_is_refuted() {
        let (plan, reg) = z3_plan_and_registry();
        let name =
            "method:contains#euf#c:callresult_method_contains_a2(s:\"abc\",s:\"z\")::assertion";
        let inv = json!({
            "kind": "and",
            "operands": [{
                "kind": "atomic",
                "name": "contains",
                "args": [str_const("abc"), str_const("z")]
            }]
        });
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:containsbad", name, inv);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one contains row: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Unsatisfied,
            "ground contains(\"abc\",\"z\") is REFUTED by string theory: {res:?}"
        );
    }

    /// SOUNDNESS RAIL. Opaque method EUF (uninterpreted callresult) stays vacuous —
    /// covering universe is string-theory atoms, not `method:starts_with` as EUF.
    #[test]
    fn lone_opaque_method_starts_with_euf_stays_vacuous_refused() {
        let (plan, reg) = z3_plan_and_registry();
        let name = "method:starts_with#euf#c:callresult_method_starts_with_a2(s:\"abc\",s:\"a\")::assertion";
        let call = json!({
            "kind": "ctor",
            "name": "method:starts_with",
            "args": [str_const("abc"), str_const("a")]
        });
        let inv = json!({
            "kind": "and",
            "operands": [{
                "kind": "atomic",
                "name": "=",
                "args": [call, {"kind":"const","sort":{"kind":"primitive","name":"Bool"},"value":true}]
            }]
        });
        let mut pool = MementoPool::default();
        insert_contract(&mut pool, "blake3-512:eufopaque", name, inv);
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(res.len(), 1, "one euf row: {res:?}");
        assert_eq!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "opaque method EUF without a body universe must stay vacuous-refused: {res:?}"
        );
        assert!(
            res[0].reason.contains("no covering universe") || res[0].reason.contains("no sibling"),
            "reason must name vacuity, not invent discharge: {}",
            res[0].reason
        );
    }

    /// The federation vendor's own test (`examples/python-base64-federation`):
    /// `assert encodeBase64("abc") == "YWJj"` calls a function in its own
    /// module, the floor follows the body, and the call completes with the
    /// decided string. A string `==` is stated, never folded (`StringValue`
    /// has no `equals`): the row is `=(<decided str>, <claimed str>)`, one
    /// constraint over two literals. The theory decides it: the truthful
    /// vendor discharges and a lying vendor is refuted, never refused as
    /// vacuous.
    #[test]
    fn a_lone_equality_of_two_string_literals_is_decided_not_vacuous() {
        let (plan, reg) = z3_plan_and_registry();
        let row = |claimed: &str| {
            json!({
                "kind": "and",
                "operands": [{
                    "kind": "atomic",
                    "name": "=",
                    "args": [str_const("YWJj"), str_const(claimed)]
                }]
            })
        };
        let verdict = |claimed: &str| {
            let mut pool = MementoPool::default();
            insert_contract(&mut pool, "blake3-512:vendor-own-test", "test_vendor", row(claimed));
            let res = verify_consistency(
                &pool,
                &plan,
                &reg,
                &test_compilers(),
                std::path::Path::new("."),
            );
            assert_eq!(res.len(), 1, "one row for the vendor's test: {res:?}");
            res[0].clone()
        };
        let truthful = verdict("YWJj");
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "encodeBase64(\"abc\") == \"YWJj\" is true: {truthful:?}"
        );
        let lying = verdict("AAAA");
        assert_eq!(
            lying.verdict,
            ObligationVerdict::Unsatisfied,
            "encodeBase64(\"abc\") == \"AAAA\" is false: {lying:?}"
        );
        // An equality with a call operand still names a symbol the solver may
        // interpret freely: it stays vacuous without a joined contract.
        let call = json!({"kind": "ctor", "name": "call:encodeBase64", "args": [str_const("abc")]});
        assert!(!is_literal_equality(&json!({
            "kind": "atomic", "name": "=", "args": [call, str_const("YWJj")]
        })));
        // Two literals of different sorts are not one theory's equality.
        assert!(!is_literal_equality(&json!({
            "kind": "atomic", "name": "=", "args": [str_const("1"), int(1)]
        })));
        // `py.eq` is uninterpreted in the SMT encoding: not a literal equality.
        assert!(!is_literal_equality(&json!({
            "kind": "atomic", "name": "py.eq", "args": [str_const("a"), str_const("a")]
        })));
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
        use crate::types::SpeakerRole;
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
        // #3807: ambient derived testimony that surfaces as vendorFactIr is
        // Vendor-spoken; stamp it so labels are a provenance projection.
        good_pool.attribute_member_for_tests(
            &test_cid_string("blake3-512:derived-len-100-zero"),
            SpeakerRole::Vendor,
            "derived-ambient",
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
        bad_pool.attribute_member_for_tests(
            &test_cid_string("blake3-512:derived-len-100-zero-bad"),
            SpeakerRole::Vendor,
            "derived-ambient",
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
        use crate::types::SpeakerRole;
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
        // #3807: stamp derived ambient as Vendor so any vendorFactIr surface is
        // a provenance projection (labels never invent Vendor from Imported alone).
        pool.attribute_member_for_tests(
            &test_cid_string("blake3-512:derived-len-100"),
            SpeakerRole::Vendor,
            "derived-ambient",
        );
        pool.attribute_member_for_tests(
            &test_cid_string("blake3-512:derived-len-200"),
            SpeakerRole::Vendor,
            "derived-ambient",
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

    /// A lying discharge-command stdout cannot turn a failed witness package
    /// into a discharge. The row verdict is derived from package bytes only
    /// (oracle resolve + package_outcome); kit verdict strings are ignored.
    #[test]
    fn lying_discharge_cannot_pass_failed_package_for_any_witness_kind() {
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"good\"}\n{\"outcome\":\"failed\",\"test\":\"bad\"}\n";
        let package_cid = blake3_512_of(package_bytes);

        for tool in ["pytest", "cargo-test", "junit", "testng"] {
            let project = unique_temp_dir(tool);
            // Pollute process env with a DISCHARGED lie: package path must ignore it.
            let lie = write_discharge_stdout(&project, "DISCHARGED");
            let env_key = tool_env_key(tool);
            std::env::set_var(&env_key, &lie);

            let _guard = WitnessBodiesGuard::enter(&bodies_for(package_bytes));
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

    /// #3754 / serde-json-showcase bad suite: a cargo-test package whose sole
    /// committed outcome is `failed` must stay not-green. package_outcome
    /// seals failed=count-passed from the body; seal_witness_package_outcome
    /// maps failed>0 to Unsatisfied. Never discharge a suite that ran wrong.
    #[test]
    fn cargo_test_all_failed_package_is_unsatisfied_never_discharged() {
        let package_bytes = br#"{"outcome":"failed","test":"tests::test_write_bool_contradiction"}
"#;
        let package_cid = blake3_512_of(package_bytes);
        let _guard = WitnessBodiesGuard::enter(&bodies_for(package_bytes));
        // proofData count=1 passed=0 matches the single failed body line.
        let body = package_contract("cargo-test", &package_cid, 1, 0);
        let result = try_witness_discharge(
            &body,
            "blake3-512:serde-bad".into(),
            "witness-package".into(),
        )
        .expect("custom cargo-test evidence must settle via package path");
        assert_eq!(
            result.verdict,
            ObligationVerdict::Unsatisfied,
            "all-failed cargo-test package must be unsatisfied, not discharged: {result:?}"
        );
        assert!(
            !result.witnessed,
            "a failing cargo-test package is not a witnessed discharge"
        );
        assert!(
            result.reason.contains("1/1 outcomes failed")
                || result.reason.contains("outcomes failed"),
            "reason must cite package-body failure counts (not kit stdout): {result:?}"
        );

        drop(_guard);
    }

    #[test]
    fn all_passed_package_discharges_from_body_not_stdout() {
        let package_bytes =
            b"{\"outcome\":\"passed\",\"test\":\"one\"}\n{\"outcome\":\"passed\",\"test\":\"two\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let project = unique_temp_dir("all-passed-package");
        let lie = write_discharge_stdout(&project, "REFUSED");
        // Lie on DISCHARGE env must not affect the package verdict.
        std::env::set_var("SUGAR_WITNESS_DISCHARGE_PYTEST", &lie);

        let _guard = WitnessBodiesGuard::enter(&bodies_for(package_bytes));
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

    /// #7848: green means decided. A package that witnessed one passing test
    /// discharges; a package with zero outcomes (an empty body, committed as
    /// count=0 passed=0) witnessed nothing and is undecided by name, never
    /// "all 0 outcomes passed".
    #[test]
    fn a_witness_package_with_no_outcomes_is_undecided_not_discharged() {
        for tool in ["pytest", "cargo-test", "junit", "testng", "build-witness"] {
            let one = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
            let one_cid = blake3_512_of(one);
            let _guard = WitnessBodiesGuard::enter(&bodies_for(one));
            let witnessed = try_witness_discharge(
                &package_contract(tool, &one_cid, 1, 1),
                "blake3-512:one-outcome".into(),
                "witness-package".into(),
            )
            .unwrap();
            drop(_guard);
            assert_eq!(
                witnessed.verdict,
                ObligationVerdict::Discharged,
                "tool={tool}: one passed outcome is decided: {witnessed:?}"
            );
            assert!(witnessed.witnessed);

            let empty: &[u8] = b"";
            let empty_cid = blake3_512_of(empty);
            let _guard = WitnessBodiesGuard::enter(&bodies_for(empty));
            let vacuous = try_witness_discharge(
                &package_contract(tool, &empty_cid, 0, 0),
                "blake3-512:no-outcomes".into(),
                "witness-package".into(),
            )
            .unwrap();
            drop(_guard);
            assert_eq!(
                vacuous.verdict,
                ObligationVerdict::Undecidable,
                "tool={tool}: a package with no outcomes decides nothing: {vacuous:?}"
            );
            assert!(!vacuous.witnessed, "tool={tool}: {vacuous:?}");
            assert!(
                vacuous.reason.contains("no outcomes"),
                "tool={tool}: reason must say the package has no outcomes: {}",
                vacuous.reason
            );
        }
    }

    #[test]
    fn witness_bodies_reach_parallel_consistency_workers() {
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
        let package_cid = blake3_512_of(package_bytes);

        let body = package_contract_with_provenance("cargo-test", &package_cid, 1, 1, "Derived");
        let mut pool = MementoPool::default();
        insert_package_contract_with_provenance(
            &mut pool,
            "blake3-512:parallel-witness-context",
            body,
        );
        insert_witness_memento_with_body(&mut pool, "parallel-witness-body", package_bytes);
        let (plan, registry) = z3_plan_and_registry();
        let thread_pool = rayon::ThreadPoolBuilder::new()
            .num_threads(2)
            .build()
            .expect("two-worker pool");

        let results = thread_pool.install(|| {
            verify_consistency(
                &pool,
                &plan,
                &registry,
                &test_compilers(),
                std::path::Path::new("."),
            )
        });

        assert_eq!(results.len(), 1, "one witness-package obligation");
        assert_eq!(results[0].verdict, ObligationVerdict::Discharged);
        assert!(results[0].witnessed);
    }

    /// Step 9: a witness row whose package body the proof does not state is
    /// undecided by name; prove asks no kit for it.
    #[test]
    fn witness_row_without_a_body_in_the_proof_is_undecided_by_name() {
        let package_bytes =
            b"{\"outcome\":\"passed\",\"test\":\"one\"}\n{\"outcome\":\"passed\",\"test\":\"two\"}\n";
        let package_cid = blake3_512_of(package_bytes);
        let contract_cid = "blake3-512:no-body-contract".to_string();
        let property = "test_x".to_string();
        let body = package_contract("pytest", &package_cid, 2, 2);

        let _guard = WitnessBodiesGuard::enter(&Arc::new(WitnessBodies::new()));
        let without = try_witness_discharge(&body, contract_cid.clone(), property.clone()).unwrap();
        drop(_guard);
        assert_eq!(
            without.verdict,
            ObligationVerdict::Undecidable,
            "{without:?}"
        );
        assert!(
            without.reason.contains("has no body in the proof"),
            "reason must say the body is not in the proof: {}",
            without.reason
        );

        let _guard = WitnessBodiesGuard::enter(&bodies_for(package_bytes));
        let with = try_witness_discharge(&body, contract_cid, property).unwrap();
        drop(_guard);
        assert_eq!(with.verdict, ObligationVerdict::Discharged, "{with:?}");
        assert!(
            with.reason.contains("verified by rust via proof"),
            "reason must cite the body read from the proof: {}",
            with.reason
        );
    }

    #[test]
    fn missing_provenance_on_custom_execution_witness_package_defaults_derived() {
        // Sealed cargo-test packages often carry evidence on the header and no
        // proofirProvenance field. That must not refuse as MissingProvenanceKind.
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
        let package_cid = blake3_512_of(package_bytes);

        let body = package_contract("cargo-test", &package_cid, 1, 1);
        assert!(
            body.get("proofirProvenance").is_none(),
            "fixture must omit proofirProvenance to pin the default-Derived path"
        );
        let mut pool = MementoPool::default();
        insert_package_contract_with_provenance(
            &mut pool,
            "blake3-512:missing-witness-package",
            body,
        );
        insert_witness_memento_with_body(&mut pool, "missing-witness-package-body", package_bytes);
        let (plan, reg) = z3_plan_and_registry();
        let res = verify_consistency(
            &pool,
            &plan,
            &reg,
            &test_compilers(),
            std::path::Path::new("."),
        );

        assert_eq!(res.len(), 1, "one witness-package obligation: {res:?}");
        assert_ne!(
            res[0].verdict,
            ObligationVerdict::Refused,
            "missing provenance on a custom execution-witness package must default Derived, not MissingProvenanceKind: {}",
            res[0].reason
        );
        assert!(
            !res[0].reason.contains("lacks required provenance KIND"),
            "must not refuse for missing provenance KIND: {}",
            res[0].reason
        );
    }

    #[test]
    fn stated_provenance_cannot_discharge_custom_execution_witness_package() {
        let package_bytes = b"{\"outcome\":\"passed\",\"test\":\"one\"}\n";
        let package_cid = blake3_512_of(package_bytes);

        let body = package_contract_with_provenance("cargo-test", &package_cid, 1, 1, "Stated");
        let mut pool = MementoPool::default();
        insert_package_contract_with_provenance(
            &mut pool,
            "blake3-512:stated-witness-package",
            body,
        );
        insert_witness_memento_with_body(&mut pool, "stated-witness-package-body", package_bytes);
        let (plan, reg) = z3_plan_and_registry();
        // Provenance-kind refusal happens before the package is read.
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

    /// A lone claim with no atom is not vacuous (#7766). The vacuity guard
    /// exists because a solver can assign an uninterpreted symbol any value; a
    /// propositional constant names no symbol, so satisfiable means true and
    /// unsatisfiable means false. Twin: the constant and its negation.
    ///
    /// The boundary is pinned too: a lone ground atom over an uninterpreted
    /// symbol stays refused. `py.eq` is uninterpreted in the SMT encoding, so
    /// admitting `py.eq(6, 7)` would come back satisfiable and discharge a
    /// false claim. (FOL `=` of two literals of one sort is interpreted:
    /// `a_lone_equality_of_two_string_literals_is_decided_not_vacuous`.)
    #[test]
    fn lone_atom_free_claim_reaches_the_solver_and_a_ground_atom_does_not() {
        let truth = json!({"kind":"and","operands":[]});
        let falsity = json!({"kind":"not","operands":[truth.clone()]});
        let py_eq = |left: i64, right: i64| json!({"kind":"atomic","name":"py.eq","args":[int(left), int(right)]});
        for (name, inv, expected) in [
            ("constant_true", truth, ObligationVerdict::Discharged),
            ("constant_false", falsity, ObligationVerdict::Unsatisfied),
            (
                "ground_atom_truthful",
                py_eq(6, 6),
                ObligationVerdict::Refused,
            ),
            ("ground_atom_lying", py_eq(6, 7), ObligationVerdict::Refused),
        ] {
            let pool = pool_with_contract(name, inv);
            let (plan, registry) = z3_plan_and_registry();
            let results = verify_consistency(
                &pool,
                &plan,
                &registry,
                &test_compilers(),
                std::path::Path::new("."),
            );
            assert_eq!(results.len(), 1, "{name}: exactly one candidate");
            assert_eq!(
                results[0].verdict, expected,
                "{name}: only a claim with no uninterpreted atom passes the vacuity guard alone: {}",
                results[0].reason
            );
        }
    }

    #[test]
    fn nested_and_of_ground_eqs_is_not_vacuous_single_constraint() {
        // Loop-unroll mint shape: and([and([g(0)=1, g(1)=1, g(2)=1])]).
        // Flattening must see three siblings so the vacuity guard does not
        // refuse a multi-point bounded-loop conjunction as a lone fact.
        let g = |n: i64| {
            json!({"kind":"ctor","name":"call:g","args":[
                {"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":n}
            ]})
        };
        let eq1 = json!({"kind":"atomic","name":"=","args":[g(0), int(1)]});
        let eq2 = json!({"kind":"atomic","name":"=","args":[g(1), int(1)]});
        let eq3 = json!({"kind":"atomic","name":"=","args":[g(2), int(1)]});
        let inv = json!({
            "kind":"and",
            "operands":[{
                "kind":"and",
                "operands":[eq1, eq2, eq3]
            }]
        });
        assert_eq!(
            count_top_level_constraints(&inv),
            3,
            "nested and must flatten for vacuity join-partner count"
        );
        let pool = pool_with_contract("loop_unroll", inv);
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
            ObligationVerdict::Refused,
            "three ground eqs under nested and must reach the solver, not vacuity-refuse: {}",
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

    /// A function is one contract: its assertions are its `inv` and its
    /// `post` defines its result (#8292). A claim that does not read the
    /// result is checked as itself; `out = <result>` is neither its conjunct
    /// nor its sibling (#8416). Twin of the test above, where the claim reads
    /// `out` and the post refutes it.
    ///
    /// - a decided claim (`and([])`) is discharged, as it is with no post:
    ///   conjoined, the formula's one constraint was the post and the row was
    ///   refused as vacuous;
    /// - its negation is refuted;
    /// - a lone claim over a free symbol stays refused, as it is with no
    ///   post: conjoined, the post was counted as its sibling, the pair went
    ///   to the solver and came back satisfiable.
    #[test]
    fn a_claim_that_does_not_read_the_result_is_checked_without_the_post() {
        let truth = json!({"kind":"and","operands":[]});
        let falsity = json!({"kind":"not","operands":[truth.clone()]});
        for (name, inv, expected) in [
            ("decided_true", truth, ObligationVerdict::Discharged),
            ("decided_false", falsity, ObligationVerdict::Unsatisfied),
            ("lone_claim", ne(var("x"), none()), ObligationVerdict::Refused),
        ] {
            let mut pool = MementoPool::default();
            let env = json!({
                "envelope": {
                    "header": {
                        "kind": "contract",
                        "contractName": name,
                        "inv": inv,
                        "post": eqf(var("out"), none()),
                        "proofirProvenance": proofir_provenance("Stated"),
                    }
                }
            });
            pool.insert_unanchored_for_tests(test_cid(name), env);
            let (plan, registry) = z3_plan_and_registry();
            let results = verify_consistency(
                &pool,
                &plan,
                &registry,
                &test_compilers(),
                std::path::Path::new("."),
            );
            assert_eq!(results.len(), 1, "{name}: exactly one candidate");
            assert_eq!(
                results[0].verdict, expected,
                "{name}: a result definition is not the claim's sibling: {}",
                results[0].reason
            );
        }
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

    /// #3809 instrument: the one solve door produces **byte-identical** wire
    /// rows whatever `project_root` is, a file trap included (zero project
    /// FS). The vendor's and the consumer's claims are one pool, as prove
    /// loads them, over one euf property with a contradiction.
    #[test]
    fn the_one_solve_door_reads_no_project_fs() {
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

        // Vendor: check(2,3) == 5; consumer: check(2,3) == 6 -> conjoined
        // UNSAT. One pool, as prove loads the project's proof and its imports.
        let mut pool = MementoPool::default();
        insert_with_file(
            &mut pool,
            "blake3-512:vendor-warm-gap3",
            json!({"kind":"and","operands":[eqf(var("r"), int_const(5))]}),
        );
        insert_source_locus(&mut pool, "blake3-512:vendor-src-warm-gap3");
        insert_with_file(
            &mut pool,
            "blake3-512:consumer-warm-gap3",
            json!({"kind":"and","operands":[eqf(var("r"), int_const(6))]}),
        );
        insert_source_locus(&mut pool, "blake3-512:consumer-src-warm-gap3");

        let (plan, registry) = z3_plan_and_registry();
        let compilers = test_compilers();
        let cold = verify_consistency(&pool, &plan, &registry, &compilers, &project);
        let warm = verify_consistency(&pool, &plan, &registry, &compilers, &project);

        // project_root as a FILE trap — zero project FS.
        let trap = unique_temp_dir("one-solve-gap3-trap");
        let trap_file = trap.join("project_root_is_a_file");
        std::fs::write(&trap_file, b"the solve must not open children\n").unwrap();
        let warm_trap = verify_consistency(&pool, &plan, &registry, &compilers, &trap_file);

        let wire = |rows: &[ConsistencyResult]| -> Vec<String> {
            let mut blobs: Vec<String> = rows
                .iter()
                .map(|cr| {
                    let mut report = crate::types::Report::default();
                    crate::report::add_consistency_result(cr, &mut report);
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
            "the one solve door must be byte-identical across calls (row_to_json)"
        );
        assert_eq!(
            trap_wire, warm_wire,
            "the solve with a file-trap project_root must match (zero project FS)"
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

    /// The joined call's site: the `SourceFragmentCoordinateV1` CID the
    /// member's site hashes to, and the first argument of the claim's
    /// `python:occurrence`.
    const JOIN_SITE: &str = "blake3-512:join-site";

    fn joined_post(symbol: &str, site_cid: &str, post: Json, formals: Vec<String>) -> AmbientPost {
        AmbientPost {
            binding: BridgeBinding {
                source_symbol: symbol.to_string(),
                target_cid: "test-target-cid".to_string(),
                target_proof_cid: None,
                formals,
                out_binding: "out".to_string(),
                stated_inputs: Vec::new(),
            },
            post,
            halt_guards: Vec::new(),
            // The one-way join (`completes -> not(guard)`) these fixtures pin;
            // the completion fact's tests set it (`guarded_ident_post`).
            every_halt_guarded: false,
            typed_halts: Vec::new(),
            member_cid: "test-member-cid".to_string(),
            site_cid: site_cid.to_string(),
            refusal: None,
            dispatch: None,
            receiver: DispatchReceiver::AsCalled,
        }
    }

    /// #7757 step 7: a handler's test over the exception a joined call
    /// raised is typed by each halt the callee's contract states, under that
    /// halt's guard bound to the call's actuals; a halt with no class types
    /// nothing; a site nothing answers types nothing.
    #[test]
    fn a_joined_calls_raised_exception_is_typed_by_the_callees_halts() {
        let class = |name: &str| {
            json!({"kind": "ctor", "name": "python:exception_type_identity", "args": [
                {"kind": "const", "value": "builtins", "sort": {"kind": "primitive", "name": "String"}},
                {"kind": "const", "value": name, "sort": {"kind": "primitive", "name": "String"}},
            ]})
        };
        let call = json!({"kind": "ctor", "name": "call:m.boom", "args": [
            {"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}},
        ]});
        let raised = json!({"kind": "ctor", "name": PYTHON_RAISED, "args": [
            call,
            {"kind": "ctor", "name": PYTHON_OCCURRENCE, "args": [
                {"kind": "const", "value": JOIN_SITE, "sort": {"kind": "primitive", "name": "String"}},
            ]},
        ]});
        let test = |handler: Json| {
            json!({"kind": "atomic", "name": PYTHON_IS_TYPE_PREDICATE, "args": [raised.clone(), handler]})
        };
        let guard = json!({"kind": "atomic", "name": "p", "args": [{"kind": "var", "name": "x"}]});
        let mut post = joined_post(
            "python:m.boom",
            JOIN_SITE,
            json!({"kind": "and", "operands": []}),
            vec!["x".to_string()],
        );
        post.typed_halts = vec![(class("ValueError"), guard)];

        // The handler names the raised class: under the halt's guard (its
        // formal bound to the call's actual) the handler takes it.
        let exact = raised_type_facts(&test(class("ValueError")), std::slice::from_ref(&post));
        assert_eq!(exact.len(), 1, "{exact:?}");
        let rendered = exact[0].to_string();
        assert!(rendered.contains("\"implies\""), "{rendered}");
        assert!(!rendered.contains("\"var\""), "the formal is bound: {rendered}");

        // Another handler class: the class question, both ways.
        let other = raised_type_facts(&test(class("Exception")), std::slice::from_ref(&post));
        assert_eq!(other.len(), 1, "{other:?}");
        assert!(other[0].to_string().contains("Exception"));

        // A halt with no class, or a site nothing answers, types nothing.
        let mut untyped = post.clone();
        untyped.typed_halts.clear();
        assert!(raised_type_facts(&test(class("ValueError")), &[untyped]).is_empty());
        let mut elsewhere = post.clone();
        elsewhere.site_cid = "blake3-512:elsewhere".to_string();
        assert!(raised_type_facts(&test(class("ValueError")), &[elsewhere]).is_empty());
    }

    fn ambient_post_encode_base64(post: Json, formals: Vec<String>) -> AmbientPost {
        joined_post("python:b64.encodeBase64", JOIN_SITE, post, formals)
    }

    /// `python:call_result(<call>, python:occurrence(<site>))`: the term a
    /// Python claim constrains for one evaluation of a call.
    fn call_result(call: Json, site_cid: &str) -> Json {
        json!({
            "kind": "ctor",
            "name": PYTHON_CALL_RESULT,
            "args": [
                call,
                {
                    "kind": "ctor",
                    "name": PYTHON_OCCURRENCE,
                    "args": [{
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": site_cid
                    }]
                }
            ]
        })
    }

    fn consumer_inv_encode_base64(rhs: &str) -> Json {
        json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                call_result(
                    json!({
                        "kind": "ctor",
                        "name": "call:encodeBase64",
                        "args": [
                            {
                                "kind": "const",
                                "sort": {"kind": "primitive", "name": "String"},
                                "value": "xyz"
                            }
                        ]
                    }),
                    JOIN_SITE,
                ),
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": rhs
                }
            ]
        })
    }

    // ── The join (step 9): the `ident` twin ─────────────────────────────
    // vendor `idn.py`: `def ident(x): return x`, post `out = x`, bridged as
    // `python:idn.ident`; the consumer's unanswered member names that symbol
    // at the call's site. The vendor's `out` is the consumer's
    // `python:call_result` at that occurrence, never the inner call term.

    fn ident_vendor_post() -> AmbientPost {
        joined_post(
            "python:idn.ident",
            JOIN_SITE,
            eqf(var("out"), var("x")),
            vec!["x".to_string()],
        )
    }

    fn ident_claim(rhs: i64, site_cid: &str) -> Json {
        let call = json!({"kind": "ctor", "name": "call:ident", "args": [int(3)]});
        eqf(call_result(call, site_cid), int(rhs))
    }

    fn prove_joined(inv: Json, ambient: &[AmbientPost]) -> ConsistencyResult {
        let (inv, mut partition) = with_ambient_posts_with_instances(inv, ambient);
        let (plan, registry) = z3_plan_and_registry();
        settle_owed_operations(&mut partition, &plan, &registry, &test_compilers());
        let mut result = check_inv_consistency(
            "ident-claim".to_string(),
            "consistency:test_ident",
            inv,
            partition.kept.clone(),
            &plan,
            &registry,
            &test_compilers(),
        );
        result.dropped_ambient_posts = partition.dropped;
        refuse_dropped_answers(&mut result);
        result
    }

    #[test]
    fn the_join_conjoins_the_vendor_post_onto_the_call_result() {
        let partition =
            linked_ambient_post_instances_for_inv(&ident_claim(3, JOIN_SITE), &[ident_vendor_post()]);
        assert!(partition.dropped.is_empty(), "{:?}", partition.dropped);
        assert_eq!(partition.kept.len(), 1, "{partition:?}");
        let call = json!({"kind": "ctor", "name": "call:ident", "args": [int(3)]});
        assert_eq!(
            partition.kept[0].instantiated_post,
            canonicalize_formula_json(&eqf(call_result(call, JOIN_SITE), int(3))),
            "out := the call_result at the occurrence, x := the actual"
        );
    }

    fn solve_claim(inv: Json) -> ConsistencyResult {
        let (plan, registry) = z3_plan_and_registry();
        check_inv_consistency(
            "py-eq-claim".to_string(),
            "consistency:test_py_eq",
            inv,
            Vec::new(),
            &plan,
            &registry,
            &test_compilers(),
        )
    }

    fn py_eq_atom(left: Json, right: Json) -> Json {
        json!({"kind": "atomic", "name": "py.eq", "args": [left, right]})
    }

    // ── #8416: `py.eq` over a value bound to a literal ──────────────────
    // vendor `def twice(n): return n + n`, joined at `twice(3)` as
    // `completes -> out = 6`: a plain `=` to an int literal. The consumer
    // claims `twice(3) == rhs`. The literal states its own type, so `py.eq`
    // over the value is SMT equality and the lying claim is refuted.

    fn twice_claim(rhs: i64) -> Json {
        let call = json!({"kind": "ctor", "name": "call:twice", "args": [int(3)]});
        let result = call_result(call, JOIN_SITE);
        let completes = json!({
            "kind": "atomic",
            "name": "python:unknown_callee_call.completes",
            "args": [result.clone()]
        });
        json!({"kind": "and", "operands": [
            completes.clone(),
            {"kind": "implies", "operands": [completes, eqf(result.clone(), int(6))]},
            py_eq_atom(result, int(rhs))
        ]})
    }

    #[test]
    fn py_eq_over_a_value_bound_to_a_literal_decides_both_ways() {
        let truthful = solve_claim(twice_claim(6));
        assert_eq!(truthful.verdict, ObligationVerdict::Discharged, "{}", truthful.reason);
        let lying = solve_claim(twice_claim(7));
        assert_eq!(
            lying.verdict,
            ObligationVerdict::Unsatisfied,
            "twice(3) == 7 under `out = 6` is refuted, never satisfied by a free `py.eq`: {}",
            lying.reason
        );
    }

    #[test]
    fn a_free_py_eq_never_discharges_a_claim() {
        // Nothing states `x`'s type. Read as Python reads `==` over a `str`
        // or an `int`, `x == 7 and x != 8` is satisfiable: discharged.
        let x = var("x");
        let truthful = solve_claim(json!({"kind": "and", "operands": [
            py_eq_atom(x.clone(), int(7)),
            {"kind": "not", "operands": [py_eq_atom(x.clone(), int(8))]}
        ]}));
        assert_eq!(truthful.verdict, ObligationVerdict::Discharged, "{}", truthful.reason);
        // `x == 7 and x == 8` is satisfiable only by a model that answers the
        // free `py.eq` application: never discharged, and never refuted
        // either (a value of another type may answer `==` either way).
        let lying = solve_claim(json!({"kind": "and", "operands": [
            py_eq_atom(x.clone(), int(7)),
            py_eq_atom(x, int(8))
        ]}));
        assert_eq!(
            lying.verdict,
            ObligationVerdict::Undecidable,
            "a claim satisfiable only through a free `py.eq` is open: {}",
            lying.reason
        );
        assert!(lying.reason.contains("builtin type is not stated"), "{}", lying.reason);
    }

    #[test]
    fn a_py_eq_is_read_over_builtins_by_its_polarity() {
        let x = var("x");
        let builtin = |operand: Json| {
            json!({
                "kind": "atomic",
                "name": sugar_ir_compiler_smt_lib::PYTHON_VALUE_BUILTIN,
                "args": [operand]
            })
        };
        let atom = py_eq_atom(x.clone(), int(7));
        let negated = json!({"kind": "not", "operands": [atom.clone()]});
        let mut changed = false;
        assert_eq!(
            py_eq_over_builtins(&negated, true, &mut changed),
            Some(json!({"kind": "not", "operands": [
                {"kind": "implies", "operands": [
                    {"kind": "and", "operands": [builtin(x.clone())]},
                    atom.clone()
                ]}
            ]}))
        );
        assert!(changed);
        let quantified = json!({
            "kind": "forall",
            "name": "x",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": atom.clone()
        });
        let mut changed = false;
        assert_eq!(
            py_eq_over_builtins(&quantified, true, &mut changed).map(|q| q["body"].clone()),
            Some(json!({"kind": "and", "operands": [atom, builtin(x)]})),
            "a bound operand is read in its own scope"
        );
        // A literal-only `py.eq` reads no free branch: nothing to confirm.
        let mut changed = false;
        let ground = py_eq_atom(int(6), int(6));
        assert_eq!(py_eq_over_builtins(&ground, true, &mut changed), Some(ground));
        assert!(!changed);
    }

    #[test]
    fn ident_twin_truthful_half_is_sat() {
        let result = prove_joined(ident_claim(3, JOIN_SITE), &[ident_vendor_post()]);
        assert_eq!(
            result.verdict,
            ObligationVerdict::Discharged,
            "ident(3) == 3 under the joined `out = x` is sat: {}",
            result.reason
        );
    }

    #[test]
    fn ident_twin_lying_half_is_unsat() {
        let result = prove_joined(ident_claim(4, JOIN_SITE), &[ident_vendor_post()]);
        assert_eq!(
            result.verdict,
            ObligationVerdict::Unsatisfied,
            "ident(3) == 4 under the joined `out = x` is unsat: {}",
            result.reason
        );
    }

    // ── Step 9: the joined contract's halts under the call's actual ──────
    // vendor `def ident(x): if x == 3: raise ValueError; return x`: post
    // `out = x` over the completed arm, one panic locus guarded `x = 3`.

    fn ident_vendor_post_halting_when(guard: Json) -> AmbientPost {
        let mut post = ident_vendor_post();
        post.halt_guards = vec![guard];
        post
    }

    /// `ident(3)`'s one completion atom, over its result term: what every
    /// arm on which the call completed states (`PYTHON_CALL_COMPLETES`).
    fn ident_completes(site_cid: &str) -> Json {
        let call = json!({"kind": "ctor", "name": "call:ident", "args": [int(3)]});
        json!({
            "kind": "atomic",
            "name": PYTHON_CALL_COMPLETES,
            "args": [call_result(call, site_cid)]
        })
    }

    /// `assert ident(3) == rhs` as the lifter states it: the call completed,
    /// and its result is `rhs`.
    fn completed_ident_claim(rhs: i64, site_cid: &str) -> Json {
        json!({"kind": "and", "operands": [
            ident_completes(site_cid),
            ident_claim(rhs, site_cid)
        ]})
    }

    #[test]
    fn a_halt_certain_on_the_call_path_refutes_the_claim() {
        // ident(3) certainly raises: the result `ident(3) == 3` reads never
        // exists, so the claim is refuted, although `out = x` alone says 3.
        let result = prove_joined(
            completed_ident_claim(3, JOIN_SITE),
            &[ident_vendor_post_halting_when(eqf(var("x"), int(3)))],
        );
        assert_eq!(
            result.verdict,
            ObligationVerdict::Unsatisfied,
            "a raise certain under the actual 3 refutes ident(3) == 3: {}",
            result.reason
        );
    }

    #[test]
    fn an_unconditional_halt_refutes_every_claim_on_the_call() {
        let result = prove_joined(
            completed_ident_claim(3, JOIN_SITE),
            &[ident_vendor_post_halting_when(eqf(int(1), int(1)))],
        );
        assert_eq!(result.verdict, ObligationVerdict::Unsatisfied, "{}", result.reason);
    }

    #[test]
    fn a_halt_certain_on_a_discarded_call_refutes_the_claim() {
        // `ident(3)` as a statement, then `assert True`: the claim reads no
        // value of the call, only that it completed (#7757 step 5). The same
        // completion atom over the same result term joins the same halts.
        let claim = ident_completes(JOIN_SITE);
        let lying = prove_joined(
            claim.clone(),
            &[ident_vendor_post_halting_when(eqf(int(1), int(1)))],
        );
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
        let truthful = prove_joined(claim, &[ident_vendor_post()]);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "{}",
            truthful.reason
        );
    }

    #[test]
    fn a_certain_halt_never_refutes_the_arm_that_caught_it() {
        // `try: a = ident(3) except ValueError: a = 3`, then `assert a == 3`:
        // ident(3) certainly raises and the handler's arm completes. The
        // halt rules out only the arm on which the call completed.
        let caught = json!({"kind": "or", "operands": [
            completed_ident_claim(3, JOIN_SITE),
            {"kind": "not", "operands": [ident_completes(JOIN_SITE)]}
        ]});
        let result = prove_joined(
            caught,
            &[ident_vendor_post_halting_when(eqf(int(1), int(1)))],
        );
        assert_eq!(result.verdict, ObligationVerdict::Discharged, "{}", result.reason);
    }

    // ── Step 9: the completion fact ──────────────────────────────────────
    // A Python contract states every halt of its one reduction with its
    // guard, so a joined call completes exactly where no halt's guard holds:
    // `completes(<result>) <-> and(not(guard))` under the call's actual.

    /// `ident` whose every halt states its guard: `guards` are all of them.
    fn guarded_ident_post(guards: Vec<Json>) -> AmbientPost {
        let mut post = ident_vendor_post();
        post.halt_guards = guards;
        post.every_halt_guarded = true;
        post
    }

    /// `try: ident(3) except: r = 2`, then `assert r == 2`: the handler's arm,
    /// on which the call halted.
    fn handler_arm_claim(site_cid: &str) -> Json {
        json!({"kind": "not", "operands": [ident_completes(site_cid)]})
    }

    #[test]
    fn a_joined_call_whose_callee_states_no_halt_always_completes() {
        // `def ident(x): return x` states no halt: the handler never runs,
        // so a claim on its arm is a lie, and the completed arm is the truth.
        let lying = prove_joined(handler_arm_claim(JOIN_SITE), &[guarded_ident_post(vec![])]);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
        let truthful = prove_joined(
            completed_ident_claim(3, JOIN_SITE),
            &[guarded_ident_post(vec![])],
        );
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "{}",
            truthful.reason
        );
    }

    #[test]
    fn a_joined_call_completes_where_the_actual_rules_out_every_halt() {
        // `def ident(x): if x == 4: raise ValueError; return x` at 3: no
        // halt's guard holds, so the call completes and the handler's arm
        // is refuted.
        let halts_at_4 = || guarded_ident_post(vec![eqf(var("x"), int(4))]);
        let lying = prove_joined(handler_arm_claim(JOIN_SITE), &[halts_at_4()]);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
        let truthful = prove_joined(completed_ident_claim(3, JOIN_SITE), &[halts_at_4()]);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "{}",
            truthful.reason
        );
    }

    #[test]
    fn a_certain_halt_keeps_the_handler_arm_under_the_completion_fact() {
        // The halt at 3 holds: the call halts, the handler's arm is the
        // truth and the completed arm the lie.
        let halts_at_3 = || guarded_ident_post(vec![eqf(var("x"), int(3))]);
        let truthful = prove_joined(handler_arm_claim(JOIN_SITE), &[halts_at_3()]);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "{}",
            truthful.reason
        );
        let lying = prove_joined(completed_ident_claim(3, JOIN_SITE), &[halts_at_3()]);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
    }

    #[test]
    fn a_halt_with_no_guard_states_no_completion() {
        // A locus that states no path condition: nothing says when the call
        // completes, so its halt face stays open.
        let result = prove_joined(handler_arm_claim(JOIN_SITE), &[ident_vendor_post()]);
        assert_eq!(result.verdict, ObligationVerdict::Discharged, "{}", result.reason);
        let locus = |guard: Option<Json>| {
            let mut locus = json!({"callee": "concept:panic-freedom.leaf.runtime-failure-site"});
            if let Some(guard) = guard {
                locus["guard"] = guard;
            }
            locus
        };
        let guarded = locus(Some(eqf(var("x"), int(3))));
        assert!(contract_guards_every_halt(&json!({"formals": ["x"]})));
        assert!(contract_guards_every_halt(
            &json!({"formals": ["x"], "panicLoci": [guarded.clone()]})
        ));
        assert!(!contract_guards_every_halt(
            &json!({"formals": ["x"], "panicLoci": [guarded, locus(None)]})
        ));
    }

    #[test]
    fn a_halt_the_actual_rules_out_leaves_the_claim_to_the_post() {
        // The halt is at x = 4; the call's actual is 3, so it is off the
        // path and the post decides alone.
        let halts_at_4 = ident_vendor_post_halting_when(eqf(var("x"), int(4)));
        let truthful = prove_joined(completed_ident_claim(3, JOIN_SITE), &[halts_at_4.clone()]);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "{}",
            truthful.reason
        );
        let lying = prove_joined(completed_ident_claim(4, JOIN_SITE), &[halts_at_4]);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
    }

    #[test]
    fn the_halt_guard_is_instantiated_at_the_call_actual() {
        let partition = linked_ambient_post_instances_for_inv(
            &completed_ident_claim(3, JOIN_SITE),
            &[ident_vendor_post_halting_when(eqf(var("x"), int(3)))],
        );
        assert!(partition.dropped.is_empty(), "{:?}", partition.dropped);
        assert_eq!(partition.kept.len(), 1, "{partition:?}");
        let call = json!({"kind": "ctor", "name": "call:ident", "args": [int(3)]});
        assert_eq!(
            partition.kept[0].instantiated_post,
            canonicalize_formula_json(&IrFormula::And(vec![
                eqf(call_result(call, JOIN_SITE), int(3)),
                json!({"kind": "implies", "operands": [
                    ident_completes(JOIN_SITE),
                    IrFormula::And(vec![IrFormula::Not(eqf(int(3), int(3))).to_value()])
                        .to_value(),
                ]}),
            ])
            .to_value()),
            "x := the actual in the post and in every halt guard, out := the \
             result in the completion the halts are off the path of"
        );
    }

    #[test]
    fn the_join_reads_each_panic_locus_guard_of_the_answering_contract() {
        let guard = eqf(var("x"), int(3));
        let body = json!({
            "formals": ["x"],
            "post": eqf(var("out"), var("x")),
            "panicLoci": [
                {"callee": "concept:panic-freedom.leaf.runtime-failure-site",
                 "file": "idn.py", "line": 2, "guard": guard.clone()},
                // A locus that states no guard states no path condition.
                {"callee": "concept:panic-freedom.leaf.runtime-failure-site",
                 "file": "idn.py", "line": 3},
            ],
        });
        assert_eq!(contract_halt_guards(&body), vec![guard]);
        assert!(contract_halt_guards(&json!({"formals": ["x"]})).is_empty());
    }

    #[test]
    fn the_join_reads_the_site_never_the_call_spelling() {
        // Same call spelling, another occurrence: nothing joins there.
        let partition = linked_ambient_post_instances_for_inv(
            &ident_claim(4, "blake3-512:another-site"),
            &[ident_vendor_post()],
        );
        assert!(partition.kept.is_empty(), "{partition:?}");
        assert!(partition.dropped.is_empty(), "{partition:?}");
    }

    #[test]
    fn a_wrong_answer_refuses_the_row_by_name() {
        let mut wrong = ident_vendor_post();
        wrong.refusal = Some(DroppedAmbientPostReason::AmbiguousTarget);
        wrong.post = Json::Null;
        let result = prove_joined(ident_claim(3, JOIN_SITE), &[wrong]);
        assert_eq!(result.verdict, ObligationVerdict::Refused, "{}", result.reason);
        assert!(
            result.reason.contains("ambiguous-target for python:idn.ident"),
            "{}",
            result.reason
        );
        // The refusal carries its typed effect, so the report seat
        // (`VerifyEffectCarrier::from_producer`) takes it instead of panicking.
        assert!(
            matches!(&result.effect, Some(VerifyEffect::JoinWrongAnswer { wrong, .. })
                if wrong.iter().any(|w| w.contains("ambiguous-target"))),
            "{:?}",
            result.effect
        );
        let _ = crate::effects::VerifyEffectCarrier::from_producer(
            result.verdict,
            result.effect.as_ref(),
        );

        // Formals that do not match the call's arguments: refused, never skipped.
        let mut arity = ident_vendor_post();
        arity.binding.formals = vec!["x".to_string(), "y".to_string()];
        let result = prove_joined(ident_claim(3, JOIN_SITE), &[arity]);
        assert_eq!(result.verdict, ObligationVerdict::Refused, "{}", result.reason);
        assert!(
            result.reason.contains("import-signature-mismatch"),
            "{}",
            result.reason
        );
    }

    // ── Step 4: a contract's inputs beside its parameters ───────────────
    // A captured cell, a module global and a default are formals of the
    // contract spelled `cell:<name>`, `global:<name>`, `default:<param>`; the
    // call supplies each by a named argument, as it supplies a parameter by
    // position or by `py.kwarg`.

    fn named_arg(ctor: &str, name: &str, value: Json) -> Json {
        json!({"kind": "ctor", "name": ctor, "args": [string_const(name), value]})
    }

    fn formals(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| name.to_string()).collect()
    }

    #[test]
    fn the_binder_binds_parameters_by_position_and_name_and_inputs_by_name() {
        let bound = bind_call_arguments(
            &formals(&["x", "y", "cell:k", "global:G"]),
            &[],
            &[
                int(1),
                named_arg("py.kwarg", "y", int(2)),
                named_arg("py.closure", "k", int(3)),
                named_arg("py.global", "G", int(4)),
            ],
        )
        .expect("the call fits the contract");
        assert_eq!(
            bound,
            vec![
                ("x".to_string(), int(1)),
                ("y".to_string(), int(2)),
                ("cell:k".to_string(), int(3)),
                ("global:G".to_string(), int(4)),
            ]
        );
    }

    #[test]
    fn a_parameter_the_call_omits_is_its_default_input() {
        let contract = formals(&["x", "default:x"]);
        let supplied =
            bind_call_arguments(&contract, &[], &[named_arg("py.default", "x", int(4))]).unwrap();
        assert_eq!(supplied, vec![("x".to_string(), int(4)), ("default:x".to_string(), int(4))]);
        // A default the call does not supply stays the free input: open.
        let unsupplied = bind_call_arguments(&contract, &[], &[]).unwrap();
        assert_eq!(unsupplied, vec![("x".to_string(), var("default:x"))]);
        // No default: a parameter the call omits does not fit.
        assert!(bind_call_arguments(&formals(&["x"]), &[], &[]).is_none());
    }

    #[test]
    fn a_call_that_does_not_fit_the_contract_is_refused() {
        let contract = formals(&["x", "cell:k"]);
        // More positional arguments than parameters.
        assert!(bind_call_arguments(&contract, &[], &[int(1), int(2)]).is_none());
        // A name the contract does not take.
        assert!(
            bind_call_arguments(&contract, &[], &[int(1), named_arg("py.kwarg", "z", int(2))])
                .is_none()
        );
        assert!(
            bind_call_arguments(&contract, &[], &[int(1), named_arg("py.closure", "j", int(2))])
                .is_none()
        );
        // A formal bound twice.
        assert!(
            bind_call_arguments(&contract, &[], &[int(1), named_arg("py.kwarg", "x", int(2))])
                .is_none()
        );
        // An input is never bound as a keyword.
        assert!(bind_call_arguments(
            &contract,
            &[],
            &[int(1), named_arg("py.kwarg", "cell:k", int(2))]
        )
        .is_none());
    }

    // ── Variadic parameters (#7757): `*args` and `**kwargs` ──────────────

    fn tuple_display(items: Vec<Json>) -> Json {
        json!({"kind": "ctor", "name": "tuple", "args": items})
    }

    #[test]
    fn a_contract_s_variadic_formals_are_marked_for_the_binder() {
        let body = json!({
            "formals": ["self", "exc", "kw", "global:G"],
            "variadicFormals": [
                {"kind": "positional", "formal": "exc"},
                {"kind": "keyword", "formal": "kw"},
            ],
        });
        assert_eq!(
            contract_binder_formals(&body).unwrap(),
            formals(&["self", "*exc", "**kw", "global:G"])
        );
        // No variadic: the formals as they stand.
        assert_eq!(
            contract_binder_formals(&json!({"formals": ["x"]})).unwrap(),
            formals(&["x"])
        );
        // A variadic entry naming no parameter is malformed.
        assert!(contract_binder_formals(&json!({
            "formals": ["x"],
            "variadicFormals": [{"kind": "positional", "formal": "y"}],
        }))
        .is_none());
    }

    #[test]
    fn a_star_formal_binds_the_tuple_of_the_positionals_no_parameter_takes() {
        // `def __exit__(self, *exc)`, called as a `with` calls it:
        // `__exit__(m, t, v, tb)`.
        let contract = formals(&["self", "*exc"]);
        let bound =
            bind_call_arguments(&contract, &[], &[var("m"), int(1), int(2), int(3)]).unwrap();
        assert_eq!(
            bound,
            vec![
                ("self".to_string(), var("m")),
                ("exc".to_string(), tuple_display(vec![int(1), int(2), int(3)])),
            ]
        );
        // Nothing left over: the empty tuple.
        let bound = bind_call_arguments(&contract, &[], &[var("m")]).unwrap();
        assert_eq!(bound[1], ("exc".to_string(), tuple_display(vec![])));
        // A parameter after `*args` is keyword-only.
        let contract = formals(&["a", "*rest", "b"]);
        assert!(bind_call_arguments(&contract, &[], &[int(1), int(2), int(3)]).is_none());
        let bound = bind_call_arguments(
            &contract,
            &[],
            &[int(1), int(2), named_arg("py.kwarg", "b", int(3))],
        )
        .unwrap();
        assert_eq!(
            bound,
            vec![
                ("a".to_string(), int(1)),
                ("rest".to_string(), tuple_display(vec![int(2)])),
                ("b".to_string(), int(3)),
            ]
        );
    }

    #[test]
    fn a_double_star_formal_binds_the_dict_of_the_keywords_no_parameter_takes() {
        let contract = formals(&["x", "**kw"]);
        let bound = bind_call_arguments(
            &contract,
            &[],
            &[int(1), named_arg("py.kwarg", "a", int(2))],
        )
        .unwrap();
        assert_eq!(
            bound,
            vec![
                ("x".to_string(), int(1)),
                (
                    "kw".to_string(),
                    json!({"kind": "ctor", "name": "python:dict", "args": [
                        {"kind": "ctor", "name": "python:dict_entry", "args": [
                            string_const("a"), int(2)
                        ]}
                    ]})
                ),
            ]
        );
        // With no `**kwargs`, an unknown keyword still fits nothing.
        assert!(bind_call_arguments(
            &formals(&["x"]),
            &[],
            &[int(1), named_arg("py.kwarg", "a", int(2))]
        )
        .is_none());
    }

    #[test]
    fn a_packed_variadic_stands_and_an_undecided_spread_binds_nothing() {
        let contract = formals(&["*args"]);
        let packed = tuple_display(vec![int(1)]);
        // A same-file definition's call supplies a packed formal by name.
        assert_eq!(
            bind_call_arguments(&contract, &[], &[named_arg("py.kwarg", "args", packed.clone())])
                .unwrap(),
            vec![("args".to_string(), packed.clone())]
        );
        // A packed value beside an argument it would also take fits nothing.
        assert!(bind_call_arguments(
            &contract,
            &[],
            &[int(2), named_arg("py.kwarg", "args", packed.clone())]
        )
        .is_none());
        // `f(*(1,))`: the spread tuple display is its elements.
        let spread = json!({"kind": "ctor", "name": "python:starred_arg", "args": [packed.clone()]});
        assert_eq!(
            bind_call_arguments(&contract, &[], &[spread]).unwrap(),
            vec![("args".to_string(), packed)]
        );
        // `f(*xs)`, `xs` of no stated length: nothing is bound.
        let undecided = json!({"kind": "ctor", "name": "python:starred_arg", "args": [var("xs")]});
        assert!(bind_call_arguments(&formals(&["a"]), &[], &[undecided.clone()]).is_none());
        assert!(spreads_undecided(&[undecided]));
        assert!(!spreads_undecided(&[int(1)]));
    }

    #[test]
    fn an_unsupplied_global_is_the_value_its_contract_states() {
        // `def f(x): return x + G`, `G` a module global the module's run
        // leaves 7: the contract states `global:G` = 7. A call after import
        // supplies no `py.global`, so the binder binds the stated value, as it
        // binds an omitted parameter to its default; a call made while the
        // module runs supplies its own value, which wins.
        let contract = formals(&["x", "global:G"]);
        let stated = vec![("global:G".to_string(), int(7))];
        assert_eq!(
            bind_call_arguments(&contract, &stated, &[int(1)]),
            Some(vec![("x".to_string(), int(1)), ("global:G".to_string(), int(7))])
        );
        assert_eq!(
            bind_call_arguments(&contract, &stated, &[int(1), named_arg("py.global", "G", int(3))]),
            Some(vec![("x".to_string(), int(1)), ("global:G".to_string(), int(3))])
        );
        // Stated nothing (the run left it undecided): unbound, so open.
        assert_eq!(
            bind_call_arguments(&contract, &[], &[int(1)]),
            Some(vec![("x".to_string(), int(1))])
        );
    }

    #[test]
    fn a_row_reads_its_own_claims_at_the_stated_globals() {
        // `X = 3; def test_x(): assert X == 3`: the claim reads the input
        // `global:X`; pytest's call after import passes nothing, so the row is
        // bound through the one binder at the stated module-final value.
        let body = json!({
            "formals": ["global:X"],
            "inputValues": [{"formal": "global:X", "value": int(3)}],
            "inv": eqf(var("global:X"), int(3)),
        });
        let bound = bind_own_inputs(&body).expect("the stated global binds the claim");
        assert_eq!(bound["inv"], eqf(int(3), int(3)));
        // A parameter stays itself.
        let with_parameter = json!({
            "formals": ["p", "global:X"],
            "inputValues": [{"formal": "global:X", "value": int(3)}],
            "inv": eqf(var("p"), var("global:X")),
        });
        assert_eq!(
            bind_own_inputs(&with_parameter).unwrap()["inv"],
            eqf(var("p"), int(3))
        );
        // No stated value: the claim is not decided on the free input.
        let unstated = json!({
            "formals": ["global:X"],
            "inv": eqf(var("global:X"), int(4)),
        });
        assert_eq!(bind_own_inputs(&unstated), Err(vec!["global:X".to_string()]));
        // The candidate keeps it as a free variable of the row.
        let (instance, inputs) = bind_own_inputs_with_unstated(&unstated);
        assert_eq!(instance["inv"], eqf(var("global:X"), int(4)));
        assert_eq!(inputs, vec!["global:X".to_string()]);
    }

    #[test]
    fn a_row_over_an_unstated_input_is_decided_for_every_value_or_open() {
        let solved = |verdict: ObligationVerdict| ConsistencyResult {
            contract_cid: "cid".to_string(),
            property_name: "python:m.test_x".to_string(),
            verdict,
            reason: "solved".to_string(),
            effect: None,
            witnessed: false,
            locus: None,
            verification: None,
            dropped_ambient_posts: Vec::new(),
        };
        let inputs = vec!["global:X".to_string()];
        // Refuted with the input free: false for every value, as it stands.
        let mut refuted = solved(ObligationVerdict::Unsatisfied);
        decide_over_unstated_inputs(&mut refuted, &inputs, || unreachable!());
        assert_eq!(refuted.verdict, ObligationVerdict::Unsatisfied);
        // Satisfiable for some value, and its negation too: open, never sat.
        let mut depends = solved(ObligationVerdict::Discharged);
        decide_over_unstated_inputs(&mut depends, &inputs, || false);
        assert_eq!(depends.verdict, ObligationVerdict::Undecidable);
        assert!(depends.reason.contains("global:X"), "{}", depends.reason);
        // Holds for every value: discharged.
        let mut holds = solved(ObligationVerdict::Discharged);
        decide_over_unstated_inputs(&mut holds, &inputs, || true);
        assert_eq!(holds.verdict, ObligationVerdict::Discharged);
    }

    #[test]
    fn each_argument_names_the_formal_it_supplies_in_call_order() {
        // The binder's one reading of a call's arguments, in the call's own
        // order: what the callsite-scoped bridge match and the vendor post's
        // universal reading pair with formals (never a positional zip).
        let contract = formals(&["x", "y", "global:G"]);
        let supplied = call_argument_formals(
            &contract,
            &[
                named_arg("py.global", "G", int(4)),
                int(1),
                named_arg("py.kwarg", "y", int(2)),
            ],
        )
        .expect("every argument fits a formal");
        assert_eq!(
            supplied,
            vec![
                ("global:G".to_string(), int(4)),
                ("x".to_string(), int(1)),
                ("y".to_string(), int(2)),
            ]
        );
        // A formal supplied twice, or an argument past the parameters, fits
        // nothing.
        assert!(call_argument_formals(&contract, &[int(1), named_arg("py.kwarg", "x", int(2))])
            .is_none());
        assert!(call_argument_formals(&contract, &[int(1), int(2), int(3)]).is_none());
        // Reading the arguments never asks that every parameter is passed:
        // that is the binding's question (`bind_call_arguments`).
        assert_eq!(
            call_argument_formals(&contract, &[int(1)]),
            Some(vec![("x".to_string(), int(1))])
        );
        assert!(bind_call_arguments(&contract, &[], &[int(1)]).is_none());
    }

    /// `python:instance(<class>, <field>...)`: a decided instance's class.
    fn instance(class: &str, fields: &[&str]) -> Json {
        let mut args = vec![string_const(class)];
        args.extend(fields.iter().map(|field| string_const(field)));
        json!({"kind": "ctor", "name": PYTHON_INSTANCE, "args": args})
    }

    /// `python:after(out, "out")`: the instance a constructor contract makes.
    fn made() -> Json {
        json!({"kind": "ctor", "name": PYTHON_AFTER, "args": [var("out"), string_const("out")]})
    }

    fn class_atom(name: &str, operand: Option<&str>) -> Json {
        let mut args = vec![made()];
        args.extend(operand.map(string_const));
        json!({"kind": "atomic", "name": name, "args": args})
    }

    #[test]
    fn a_constructor_contract_states_the_instance_it_makes() {
        // Two completed faces of `Box`'s constructor contract: one leaves
        // `n`, the other `n` and `k`. The `__dict__` may hold either.
        let post = json!({"kind": "and", "operands": [
            {"kind": "implies", "operands": [
                {"kind": "atomic", "name": "g", "args": []},
                {"kind": "and", "operands": [
                    class_atom(PYTHON_TYPE_IS, Some("python:m.Box")),
                    class_atom(PYTHON_MAY_HOLD, Some("n")),
                ]},
            ]},
            {"kind": "implies", "operands": [
                {"kind": "not", "operand": {"kind": "atomic", "name": "g", "args": []}},
                {"kind": "and", "operands": [
                    class_atom(PYTHON_TYPE_IS, Some("python:m.Box")),
                    class_atom(PYTHON_MAY_HOLD, Some("k")),
                    class_atom(PYTHON_MAY_HOLD, Some("n")),
                ]},
            ]},
        ]});
        assert_eq!(
            constructed_instance(&post, "out", "python:m.Box"),
            Some(instance("python:m.Box", &["k", "n"]))
        );
        // A face that does not decide it: nothing is bound.
        let undecided = json!({"kind": "and", "operands": [
            class_atom(PYTHON_TYPE_IS, Some("python:m.Box")),
            class_atom(PYTHON_CLASS_UNDECIDED, None),
        ]});
        assert_eq!(constructed_instance(&undecided, "out", "python:m.Box"), None);
        // Another class, or no class stated: nothing is bound.
        assert_eq!(constructed_instance(&post, "out", "python:m.Other"), None);
        assert_eq!(
            constructed_instance(&class_atom(PYTHON_MAY_HOLD, Some("n")), "out", "python:m.Box"),
            None
        );
    }

    #[test]
    fn a_constructed_class_names_its_symbol() {
        let constructed = json!({"kind": "ctor", "name": PYTHON_CONSTRUCTED, "args": [
            string_const("python:m.Box")
        ]});
        assert_eq!(constructed_class_symbol(&constructed), Some("python:m.Box"));
        assert_eq!(constructed_class_symbol(&instance("python:m.Box", &[])), None);
    }

    #[test]
    fn a_class_argument_supplies_the_class_input_of_the_parameter_it_names() {
        // Step 8: `py.class("0", C)` states the class of the call's first
        // positional argument; the binder binds it to `class:<parameter>`
        // of the parameter that argument binds.
        let contract = formals(&["self", "k", "class:self"]);
        let class = instance("python:m.Box", &[]);
        assert_eq!(
            bind_call_arguments(
                &contract,
                &[],
                &[var("b"), int(4), named_arg("py.class", "0", class.clone())]
            ),
            Some(vec![
                ("self".to_string(), var("b")),
                ("k".to_string(), int(4)),
                ("class:self".to_string(), class.clone()),
            ])
        );
        // By keyword: the parameter the keyword argument binds. This contract
        // calls no method of `k` (no `class:k`), so that class is skipped.
        assert_eq!(
            call_argument_formals(
                &contract,
                &[
                    var("b"),
                    named_arg("py.kwarg", "k", int(4)),
                    named_arg("py.class", "k", class.clone()),
                ]
            ),
            Some(vec![("self".to_string(), var("b")), ("k".to_string(), int(4))])
        );
        // A contract that calls no method of the parameter takes no class
        // input: the class is supplied to nothing.
        assert_eq!(
            bind_call_arguments(
                &formals(&["self", "k"]),
                &[],
                &[var("b"), int(4), named_arg("py.class", "0", class.clone())]
            ),
            Some(vec![("self".to_string(), var("b")), ("k".to_string(), int(4))])
        );
        // A class of an argument the call does not pass fits nothing.
        assert!(call_argument_formals(
            &contract,
            &[var("b"), named_arg("py.class", "1", class)]
        )
        .is_none());
    }

    fn namespace(mro: &[&str], binds: &[(&str, &str, &str)]) -> ClassNamespace {
        ClassNamespace {
            mro: mro.iter().map(|entry| entry.to_string()).collect(),
            binds: binds
                .iter()
                .map(|(name, kind, symbol)| {
                    (name.to_string(), (kind.to_string(), symbol.to_string()))
                })
                .collect(),
            object: None,
        }
    }

    /// The symbol a call of `method` resolves to (`dispatched_target`).
    fn dispatched_symbol(
        namespaces: &BTreeMap<String, ClassNamespace>,
        method: &str,
        class: &Json,
    ) -> Option<String> {
        dispatched_target(namespaces, method, false, class).map(|target| target.symbol)
    }

    fn class_object(cid: &str) -> Json {
        json!({"kind": "ctor", "name": "python:class-definition", "args": [string_const(cid)]})
    }

    #[test]
    fn each_kind_binds_as_its_descriptor_binds_read_off_an_instance() {
        // Step 8: `class C` holds a plain def, a function field, a
        // staticmethod, a classmethod and a property.
        let mut c = namespace(
            &["python:m.C", "builtins.object"],
            &[
                ("get", "function", "python:m.C.get"),
                ("f", "field", "python:m.C.<lambda>@3:8"),
                ("s", "staticmethod", "python:m.C.s"),
                ("k", "classmethod", "python:m.C.k"),
                ("p", "property", "python:m.C.p"),
            ],
        );
        c.object = Some(class_object("cid-c"));
        let mut namespaces = BTreeMap::new();
        namespaces.insert("python:m.C".to_string(), c);
        let obj = instance("python:m.C", &[]);
        let target = |method: &str, read: bool, class: &Json| {
            dispatched_target(&namespaces, method, read, class)
        };
        let to = |symbol: &str, receiver: DispatchReceiver| {
            Some(DispatchTarget {
                symbol: symbol.to_string(),
                receiver,
            })
        };
        assert_eq!(target("get", false, &obj), to("python:m.C.get", DispatchReceiver::AsCalled));
        assert_eq!(
            target("f", false, &obj),
            to("python:m.C.<lambda>@3:8", DispatchReceiver::AsCalled)
        );
        assert_eq!(target("s", false, &obj), to("python:m.C.s", DispatchReceiver::Static));
        assert_eq!(
            target("k", false, &obj),
            to("python:m.C.k", DispatchReceiver::Class(class_object("cid-c")))
        );
        // A property is read, never called: its getter answers the read; a
        // call of what it returns is not stated here.
        assert_eq!(target("p", true, &obj), to("python:m.C.p", DispatchReceiver::AsCalled));
        assert_eq!(target("p", false, &obj), None);
        // A read of anything but a property is no call of a getter.
        assert_eq!(target("get", true, &obj), None);
        // A field shadows a non-data descriptor, never a property.
        let shadowing = instance("python:m.C", &["p", "s"]);
        assert_eq!(target("p", true, &shadowing), to("python:m.C.p", DispatchReceiver::AsCalled));
        assert_eq!(target("s", false, &shadowing), None);
        // A classmethod of a class no proof states the object of.
        namespaces.get_mut("python:m.C").unwrap().object = None;
        assert_eq!(dispatched_target(&namespaces, "k", false, &obj), None);
        // `__getattr__` answers a getter's `AttributeError`: a read is not
        // decided; a call of a method is.
        namespaces
            .get_mut("python:m.C")
            .unwrap()
            .binds
            .insert(
                "__getattr__".to_string(),
                ("function".to_string(), "python:m.C.__getattr__".to_string()),
            );
        assert_eq!(dispatched_target(&namespaces, "p", true, &obj), None);
        assert!(dispatched_target(&namespaces, "s", false, &obj).is_some());
    }

    #[test]
    fn a_dispatched_call_s_arguments_bind_as_its_kind_takes_them() {
        let d = instance("python:m.D", &[]);
        let args = vec![
            var("obj"),
            int(4),
            named_arg("py.class", "0", instance("python:m.C", &[])),
            named_arg("py.class", "1", d.clone()),
            named_arg("py.kwarg", "k", int(5)),
        ];
        assert_eq!(dispatched_arguments(&DispatchReceiver::AsCalled, &args), Some(args.clone()));
        // A staticmethod: no instance, its class dropped, the next argument's
        // class keyed one lower.
        assert_eq!(
            dispatched_arguments(&DispatchReceiver::Static, &args),
            Some(vec![
                int(4),
                named_arg("py.class", "0", d.clone()),
                named_arg("py.kwarg", "k", int(5)),
            ])
        );
        // A classmethod: the class object in the instance's place, the
        // instance's class dropped.
        assert_eq!(
            dispatched_arguments(&DispatchReceiver::Class(class_object("cid-c")), &args),
            Some(vec![
                class_object("cid-c"),
                int(4),
                named_arg("py.class", "1", d),
                named_arg("py.kwarg", "k", int(5)),
            ])
        );
        // The one binder binds the staticmethod's formals from them.
        let rebound = dispatched_arguments(&DispatchReceiver::Static, &args).unwrap();
        assert_eq!(
            bind_call_arguments(&formals(&["n", "k"]), &[], &rebound),
            Some(vec![("n".to_string(), int(4)), ("k".to_string(), int(5))])
        );
    }

    #[test]
    fn a_method_is_dispatched_on_the_order_the_class_states() {
        // `class Base: def get(self)`; `class Child(Base): def run(self)`.
        let mut namespaces = BTreeMap::new();
        namespaces.insert(
            "python:m.Base".to_string(),
            namespace(
                &["python:m.Base", "builtins.object"],
                &[("get", "function", "python:m.Base.get")],
            ),
        );
        namespaces.insert(
            "python:m.Child".to_string(),
            namespace(
                &["python:m.Child", "python:m.Base", "builtins.object"],
                &[("run", "function", "python:m.Child.run")],
            ),
        );
        let child = instance("python:m.Child", &[]);
        assert_eq!(
            dispatched_symbol(&namespaces, "get", &child),
            Some("python:m.Base.get".to_string())
        );
        assert_eq!(
            dispatched_symbol(&namespaces, "run", &child),
            Some("python:m.Child.run".to_string())
        );
        // The instance's `__dict__` may hold the name: not decided.
        assert_eq!(
            dispatched_symbol(&namespaces, "get", &instance("python:m.Child", &["get"])),
            None
        );
        // No class binds it before `object`: not decided (a builtin may).
        assert_eq!(dispatched_symbol(&namespaces, "missing", &child), None);
        // A free class input: not decided.
        assert_eq!(dispatched_symbol(&namespaces, "get", &var("class:self")), None);
        // A class of the order whose namespace no proof states: not decided.
        namespaces.remove("python:m.Base");
        assert_eq!(dispatched_symbol(&namespaces, "run", &child), None);
    }

    #[test]
    fn a_method_bound_to_anything_but_a_written_function_is_not_dispatched() {
        let mut namespaces = BTreeMap::new();
        namespaces.insert(
            "python:m.C".to_string(),
            namespace(
                &["python:m.C", "builtins.object"],
                &[
                    ("prop", "other", ""),
                    ("maybe", "undecided", ""),
                    ("get", "function", "python:m.C.get"),
                ],
            ),
        );
        let c = instance("python:m.C", &[]);
        assert_eq!(dispatched_symbol(&namespaces, "prop", &c), None);
        assert_eq!(dispatched_symbol(&namespaces, "maybe", &c), None);
        assert_eq!(
            dispatched_symbol(&namespaces, "get", &c),
            Some("python:m.C.get".to_string())
        );
        // A class that binds `__getattribute__` decides every read itself.
        namespaces.insert(
            "python:m.C".to_string(),
            namespace(
                &["python:m.C", "builtins.object"],
                &[
                    ("__getattribute__", "function", "python:m.C.__getattribute__"),
                    ("get", "function", "python:m.C.get"),
                ],
            ),
        );
        assert_eq!(dispatched_symbol(&namespaces, "get", &c), None);
    }

    #[test]
    fn a_class_namespace_row_is_read_off_its_facts() {
        let fact = |name: &str, args: &[&str]| {
            json!({
                "kind": "atomic",
                "name": name,
                "args": args.iter().map(|arg| string_const(arg)).collect::<Vec<_>>(),
            })
        };
        let body = json!({
            "name": "python:m.C::namespace",
            "inv": {
                "kind": "and",
                "operands": [
                    fact(PYTHON_CLASS_MRO, &["python:m.C", "python:m.C", "builtins.object"]),
                    fact(PYTHON_CLASS_BINDS, &["python:m.C", "get", "function", "python:m.C.get"]),
                    fact(PYTHON_CLASS_BINDS, &["python:m.Other", "get", "function", "python:m.Other.get"]),
                    json!({
                        "kind": "atomic",
                        "name": PYTHON_CLASS_OBJECT,
                        "args": [string_const("python:m.C"), class_object("cid-c")],
                    }),
                ],
            },
        });
        let (symbol, stated) = class_namespace_of(&body).expect("a namespace row");
        assert_eq!(symbol, "python:m.C");
        let mut expected = namespace(
            &["python:m.C", "builtins.object"],
            &[("get", "function", "python:m.C.get")],
        );
        // The class object is the term the row states, as the row's `inv`
        // reads canonically.
        let object = stated.object.clone().expect("the class object");
        assert_eq!(object.get("name").and_then(|v| v.as_str()), Some("python:class-definition"));
        assert_eq!(
            object
                .get("args")
                .and_then(|v| v.as_array())
                .and_then(|args| args.first())
                .and_then(const_str),
            Some("cid-c")
        );
        expected.object = Some(object);
        assert_eq!(stated, expected);
        // A namespace row is a statement of fact, never a claim to check.
        assert!(!is_consistency_candidate(&body));
    }

    #[test]
    fn a_callee_halt_reaches_the_call_through_the_one_binder() {
        // `def f(x): ...` reading the module global `G` states the contract
        // formals `[x, global:G]`; a call `f(5)` passes one positional
        // argument. Before, the halt locus zipped formals and arguments by
        // position and dropped the halt when their counts differed.
        let contract = formals(&["x", "global:G"]);
        let bindings = bind_call_arguments(&contract, &[], &[int(5)])
            .expect("a positional call fits a contract with an input");
        let locus = json!({
            "file": "producer.py",
            "line": 3,
            "guard": eqf(var("x"), var("global:G")),
        });
        let at_call = halt_at_call(&locus, &bindings, "consumer.py", 9, "python:producer.f");
        // The parameter is the call's actual; the input the call does not
        // supply stays free, so the halt is never ruled out on it.
        assert_eq!(
            at_call["guard"],
            fold_ground_applications(&eqf(int(5), var("global:G")))
        );
        assert_eq!(at_call["file"], json!("consumer.py"));
        assert_eq!(at_call["producerFile"], json!("producer.py"));
    }

    #[test]
    fn the_binder_never_captures_an_actual_spelled_as_another_formal() {
        // `def g(x, y): return x`, called `g(y, 2)` from a contract whose own
        // formal is `y`: `x := y` must not then be rebound by `y := 2`.
        let instance = substitute_call_bindings(
            &eqf(var("out"), var("x")),
            &[("x".to_string(), var("y")), ("y".to_string(), int(2))],
        );
        assert_eq!(instance, eqf(var("out"), var("y")));
    }

    fn cell_reader_post() -> AmbientPost {
        joined_post(
            "python:m.outer.<locals>.g@3:4",
            JOIN_SITE,
            eqf(var("out"), var("cell:k")),
            formals(&["x", "cell:k"]),
        )
    }

    fn cell_reader_claim(rhs: i64, closure: Option<i64>) -> Json {
        let mut args = vec![int(3)];
        if let Some(value) = closure {
            args.push(named_arg("py.closure", "k", int(value)));
        }
        let call = json!({"kind": "ctor", "name": "call:g", "args": args});
        eqf(call_result(call, JOIN_SITE), int(rhs))
    }

    #[test]
    fn a_captured_cell_the_call_supplies_decides_the_claim() {
        let truthful = prove_joined(cell_reader_claim(5, Some(5)), &[cell_reader_post()]);
        assert_eq!(truthful.verdict, ObligationVerdict::Discharged, "{}", truthful.reason);
        let lying = prove_joined(cell_reader_claim(6, Some(5)), &[cell_reader_post()]);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
    }

    #[test]
    fn an_input_the_call_does_not_supply_leaves_the_call_owed() {
        let partition =
            linked_ambient_post_instances_for_inv(&cell_reader_claim(5, None), &[cell_reader_post()]);
        assert!(partition.kept.is_empty(), "{partition:?}");
        assert_eq!(partition.dropped.len(), 1, "{partition:?}");
        assert_eq!(
            partition.dropped[0].reason,
            DroppedAmbientPostReason::OpenAfterSpecialization
        );
        let result = prove_joined(cell_reader_claim(6, None), &[cell_reader_post()]);
        assert_ne!(result.verdict, ObligationVerdict::Discharged, "{}", result.reason);
    }

    // ── Step 9: a dropped answer leaves the call unanswered ─────────────
    // vendor post `out = x and out = unbound`: `unbound` is neither a formal
    // nor the out binding, so the specialized post is open and dropped. The
    // claim `ident(3) == r and ident(3) != 5` alone is satisfiable for every
    // `r`: solved without the post, the lying `r = 4` read discharged.

    fn ident_post_left_open() -> Json {
        IrFormula::And(vec![
            eqf(var("out"), var("x")),
            eqf(var("out"), var("unbound")),
        ])
        .to_value()
    }

    fn ident_claim_with_sibling(rhs: i64, other: i64, site_cid: &str) -> Json {
        let call = json!({"kind": "ctor", "name": "call:ident", "args": [int(3)]});
        IrFormula::And(vec![
            ident_claim(rhs, site_cid),
            IrFormula::Not(eqf(call_result(call, site_cid), int(other))).to_value(),
        ])
        .to_value()
    }

    #[test]
    fn a_dropped_answer_never_discharges_the_row_on_what_remains() {
        let mut open = ident_vendor_post();
        open.post = ident_post_left_open();
        // Truthful and lying alike: the call is unanswered, so neither is
        // decided on the remainder, and the row names the drop.
        for rhs in [3, 4] {
            let claim = ident_claim_with_sibling(rhs, 5, JOIN_SITE);
            let result = prove_joined(claim, &[open.clone()]);
            assert_eq!(
                result.verdict,
                ObligationVerdict::Undecidable,
                "ident(3) == {rhs} with the answer dropped is not decided: {}",
                result.reason
            );
            assert!(
                result
                    .reason
                    .contains("open-after-specialization for python:idn.ident"),
                "{}",
                result.reason
            );
        }
        // A remainder that is already contradictory stays refuted: the full
        // conjunction is contradictory too.
        let contradictory = prove_joined(
            IrFormula::And(vec![
                ident_claim(4, JOIN_SITE),
                ident_claim(5, JOIN_SITE),
            ])
            .to_value(),
            &[open],
        );
        assert_eq!(
            contradictory.verdict,
            ObligationVerdict::Unsatisfied,
            "{}",
            contradictory.reason
        );
        // The same pair with the answer conjoined is decided both ways.
        let claim = ident_claim_with_sibling(3, 5, JOIN_SITE);
        let truthful = prove_joined(claim, &[ident_vendor_post()]);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "{}",
            truthful.reason
        );
        let claim = ident_claim_with_sibling(4, 5, JOIN_SITE);
        let lying = prove_joined(claim, &[ident_vendor_post()]);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
    }

    /// A consumer whose claim reads `ident(3)` at a call member's site, and a
    /// vendor contract answering `python:idn.ident` with `post`. Returns the
    /// pool and the call member's CID.
    fn ident_join_pool(post: Json) -> (MementoPool, String) {
        let site = answered_site(4, 12);
        let site_cid = undecided_site_coordinate_cid(&site);
        let mut pool = MementoPool::default();
        let member = insert_unanswered(&mut pool, Some("python:idn.ident"), site);
        insert_contract(
            &mut pool,
            "blake3-512:ident-consumer",
            "test_ident",
            ident_claim_with_sibling(3, 5, &site_cid),
        );
        let contract_cid = blake3_512_of(b"ident-vendor-contract");
        pool.insert_unanchored_for_tests(
            test_cid(&contract_cid),
            json!({
                "evidence": {
                    "kind": "contract",
                    "body": {
                        "contractName": "ident",
                        "formals": ["x"],
                        "outBinding": "out",
                        "post": post
                    }
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            test_cid(&blake3_512_of(b"ident-vendor-bridge")),
            json!({
                "evidence": {
                    "kind": "bridge",
                    "body": {
                        "sourceSymbol": "python:idn.ident",
                        "targetContractCid": contract_cid
                    }
                }
            }),
        );
        (pool, member)
    }

    #[test]
    fn a_member_whose_joined_answer_was_dropped_stays_owed() {
        let (pool, member) = ident_join_pool(eqf(var("out"), var("x")));
        assert!(
            joined_member_cids(&pool).contains(&member),
            "a conjoined answer answers the call"
        );
        let (pool, member) = ident_join_pool(ident_post_left_open());
        assert!(
            !joined_member_cids(&pool).contains(&member),
            "an answer dropped as open after specialization never answers the call"
        );
    }

    // ── One join over every contract prove has (owner, 2026-11-15, #7757) ──
    // One proof, nothing imported. A same-file call is coordinate + edge: the
    // caller's claim reads `python:call_result(call:<name>(…), <site>)` and
    // an unanswered member at that site names the callee's target symbol; the
    // callee's own contract is bridged under that symbol in the same proof.
    // The join binds it exactly as it binds an imported contract.

    /// A function contract `name(x)` with `post`, bridged as `symbol`, in the
    /// project's own proof (no speaker stamp: the consumer's). Returns its CID.
    fn own_function(pool: &mut MementoPool, name: &str, symbol: &str, post: Json) -> String {
        let contract_cid = blake3_512_of(format!("same-proof-contract-{name}").as_bytes());
        pool.insert_unanchored_for_tests(
            test_cid(&contract_cid),
            json!({
                "evidence": {
                    "kind": "contract",
                    "body": {
                        "contractName": name,
                        "formals": ["x"],
                        "outBinding": "out",
                        "post": post
                    }
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            test_cid(&blake3_512_of(format!("same-proof-bridge-{name}").as_bytes())),
            json!({
                "evidence": {
                    "kind": "bridge",
                    "body": {
                        "sourceSymbol": symbol,
                        "targetContractCid": contract_cid
                    }
                }
            }),
        );
        contract_cid
    }

    /// `<callee>(3) == rhs and <callee>(3) != 5`, read at `site_cid`.
    fn same_proof_claim(callee: &str, rhs: i64, site_cid: &str) -> Json {
        let call = json!({"kind": "ctor", "name": callee, "args": [int(3)]});
        IrFormula::And(vec![
            eqf(call_result(call.clone(), site_cid), int(rhs)),
            IrFormula::Not(eqf(call_result(call, site_cid), int(5))).to_value(),
        ])
        .to_value()
    }

    fn the_one_claim(pool: &MementoPool) -> ConsistencyResult {
        let (plan, registry) = z3_plan_and_registry();
        let results = verify_consistency(
            pool,
            &plan,
            &registry,
            &test_compilers(),
            std::path::Path::new("."),
        );
        assert_eq!(results.len(), 1, "exactly one claim");
        results.into_iter().next().expect("one claim")
    }

    /// `def g(x): return x` and `def test_f(): assert g(3) == rhs`, one file.
    fn f_calls_g_pool(rhs: i64) -> (MementoPool, String) {
        let site = answered_site(4, 12);
        let site_cid = undecided_site_coordinate_cid(&site);
        let mut pool = MementoPool::default();
        let member = insert_unanswered(&mut pool, Some("python:m.g"), site);
        own_function(&mut pool, "g", "python:m.g", eqf(var("out"), var("x")));
        insert_contract(
            &mut pool,
            "blake3-512:same-proof-test-f",
            "test_f",
            same_proof_claim("call:g", rhs, &site_cid),
        );
        (pool, member)
    }

    #[test]
    fn a_same_proof_edge_binds_its_contract_like_an_imported_one() {
        let (pool, member) = f_calls_g_pool(3);
        assert!(
            !pool.is_vendor_member(&member),
            "nothing here is imported: the edge and its contract are one proof's"
        );
        assert!(
            joined_member_cids(&pool).contains(&member),
            "the same-proof contract answers the call, so it is not owed"
        );
        // Python call edges are `undecided` members joined here, never a
        // linker callsite: the link surface states no unresolved edge.
        assert!(
            crate::enumerate_callsites::run(&pool)
                .iter()
                .all(|cs| cs.bridge_target_cid.is_some()),
            "a same-proof edge is never an unresolved link edge"
        );
        let truthful = the_one_claim(&pool);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "g(3) == 3 under g's `out = x`: {}",
            truthful.reason
        );
        let (pool, _) = f_calls_g_pool(4);
        let lying = the_one_claim(&pool);
        assert_eq!(
            lying.verdict,
            ObligationVerdict::Unsatisfied,
            "g(3) == 4 under g's `out = x` is refuted: {}",
            lying.reason
        );
    }

    /// The editor and `sugar prove` are one door over one pool: the
    /// consumer's edge (its own proof) binds the import's bridge (a staged
    /// proof) exactly as a same-proof edge binds, decided both ways. (The
    /// overlay path that joined each index's edges only to its own bridges is
    /// gone; `verify_consistency` is the only consistency door.)
    #[test]
    fn a_consumer_edge_binds_an_imported_bridge_through_the_one_door() {
        use crate::types::SpeakerRole;
        for (rhs, verdict) in [
            (3, ObligationVerdict::Discharged),
            (4, ObligationVerdict::Unsatisfied),
        ] {
            let (mut pool, member) = f_calls_g_pool(rhs);
            let contract_cid = blake3_512_of(b"same-proof-contract-g");
            let bridge_cid = blake3_512_of(b"same-proof-bridge-g");
            for cid in [&contract_cid, &bridge_cid] {
                pool.attribute_member_for_tests(
                    &test_cid_string(cid),
                    SpeakerRole::Vendor,
                    "staged-import",
                );
            }
            pool.attribute_member_for_tests(&member, SpeakerRole::Consumer, "me");
            assert!(pool.is_vendor_member(&test_cid_string(&contract_cid)));
            assert!(
                joined_member_cids(&pool).contains(&member),
                "the import's bridge answers the consumer's edge"
            );
            let result = the_one_claim(&pool);
            assert_eq!(result.verdict, verdict, "g(3) == {rhs}: {}", result.reason);
        }
    }

    /// `def g(x): return x`, `def f(x): return g(x)`, and
    /// `def test_f(): assert f(3) == rhs`, one file: the claim reads `g`
    /// through `f`'s post.
    fn f_through_g_pool(rhs: i64) -> MementoPool {
        let test_site = answered_site(4, 12);
        let test_site_cid = undecided_site_coordinate_cid(&test_site);
        let f_site = answered_site(20, 24);
        let f_site_cid = undecided_site_coordinate_cid(&f_site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:m.f"), test_site);
        insert_unanswered(&mut pool, Some("python:m.g"), f_site);
        own_function(&mut pool, "g", "python:m.g", eqf(var("out"), var("x")));
        let inner = json!({"kind": "ctor", "name": "call:g", "args": [var("x")]});
        own_function(
            &mut pool,
            "f",
            "python:m.f",
            eqf(var("out"), call_result(inner, &f_site_cid)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:same-proof-test-f-through-g",
            "test_f",
            same_proof_claim("call:f", rhs, &test_site_cid),
        );
        pool
    }

    #[test]
    fn a_joined_contracts_own_calls_are_joined_in_turn() {
        let truthful = the_one_claim(&f_through_g_pool(3));
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "f(3) == 3 under f's `out = g(x)` and g's `out = x`: {}",
            truthful.reason
        );
        // Without g's post the claim reads a free `g(3)` and `f(3) == 4`
        // would be satisfiable: the join must reach g through f.
        let lying = the_one_claim(&f_through_g_pool(4));
        assert_eq!(
            lying.verdict,
            ObligationVerdict::Unsatisfied,
            "f(3) == 4 is refuted through f's call of g: {}",
            lying.reason
        );
    }

    /// `def f(x): return f(x)` and `def test_f(): assert f(3) == 3`, one
    /// file: f's edge targets f itself.
    fn recursive_pool() -> (MementoPool, String, String) {
        let test_site = answered_site(4, 12);
        let test_site_cid = undecided_site_coordinate_cid(&test_site);
        let f_site = answered_site(20, 24);
        let f_site_cid = undecided_site_coordinate_cid(&f_site);
        let mut pool = MementoPool::default();
        let test_member = insert_unanswered(&mut pool, Some("python:m.f"), test_site);
        let self_member = insert_unanswered(&mut pool, Some("python:m.f"), f_site);
        let inner = json!({"kind": "ctor", "name": "call:f", "args": [var("x")]});
        own_function(
            &mut pool,
            "f",
            "python:m.f",
            eqf(var("out"), call_result(inner, &f_site_cid)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:same-proof-test-recursive",
            "test_f",
            same_proof_claim("call:f", 3, &test_site_cid),
        );
        (pool, test_member, self_member)
    }

    #[test]
    fn a_recursive_edge_stays_owed() {
        let (pool, test_member, self_member) = recursive_pool();
        assert!(
            collect_ambient_posts(&pool)
                .iter()
                .all(|post| post.refusal == Some(DroppedAmbientPostReason::RecursiveContract)),
            "a recursive contract answers nothing: the encoding states no recursion"
        );
        let joined = joined_member_cids(&pool);
        assert!(!joined.contains(&self_member), "f's call of itself stays owed");
        assert!(
            !joined.contains(&test_member),
            "a call answered only by the recursive contract stays owed"
        );
        let mut report = crate::types::Report::default();
        crate::report::add_undecided_members(&pool, &BTreeMap::new(), &mut report);
        assert_eq!(report.owed, 2, "both calls are owed, never assumed");
        // The solve terminates: nothing re-enters f.
        let _ = the_one_claim(&pool);
    }

    #[test]
    fn the_join_never_re_enters_a_contract_it_is_instantiating() {
        // Two answers at two sites by the one contract `f`, whose post reads
        // its own call: reached through f, f is not instantiated again.
        let inner = json!({"kind": "ctor", "name": "call:f", "args": [var("x")]});
        let f_post = eqf(var("out"), call_result(inner, "blake3-512:f-site"));
        let outer = joined_post("python:m.f", JOIN_SITE, f_post.clone(), vec!["x".into()]);
        let again = joined_post("python:m.f", "blake3-512:f-site", f_post, vec!["x".into()]);
        let call = json!({"kind": "ctor", "name": "call:f", "args": [int(3)]});
        let claim = eqf(call_result(call, JOIN_SITE), int(3));
        let partition = linked_ambient_post_instances_for_inv(&claim, &[outer, again]);
        assert_eq!(partition.kept.len(), 1, "{partition:?}");
        assert!(
            partition
                .dropped
                .iter()
                .any(|d| d.reason == DroppedAmbientPostReason::RecursiveContract),
            "{:?}",
            partition.dropped
        );
        assert!(!DroppedAmbientPostReason::RecursiveContract.is_wrong_answer());
    }

    // ── A row is never green on what a joined contract leaves unanswered ──
    // `def f(x): return g(x)` where nothing answers `g`, and
    // `def test_f(): assert f(3) == rhs`. f's contract is joined, but its post
    // reads `g(3)`, which is free: `f(3) == 4` would be satisfiable. The row
    // is not decided on it, and names g's owed member.

    fn f_reads_unanswered_g_pool(rhs: i64) -> (MementoPool, String) {
        let test_site = answered_site(4, 12);
        let test_site_cid = undecided_site_coordinate_cid(&test_site);
        let f_site = answered_site(20, 24);
        let f_site_cid = undecided_site_coordinate_cid(&f_site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:m.f"), test_site);
        let g_member = insert_unanswered(&mut pool, Some("python:m.g"), f_site);
        let inner = json!({"kind": "ctor", "name": "call:g", "args": [var("x")]});
        own_function(
            &mut pool,
            "f",
            "python:m.f",
            eqf(var("out"), call_result(inner, &f_site_cid)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:transitively-owed-test-f",
            "test_f",
            same_proof_claim("call:f", rhs, &test_site_cid),
        );
        (pool, g_member)
    }

    #[test]
    fn a_call_a_joined_contract_reads_and_nothing_answers_leaves_the_row_owed() {
        for rhs in [3, 4] {
            let (pool, g_member) = f_reads_unanswered_g_pool(rhs);
            let result = the_one_claim(&pool);
            assert_eq!(
                result.verdict,
                ObligationVerdict::Undecidable,
                "f(3) == {rhs} reads g(3) through f, and nothing answers g: {}",
                result.reason
            );
            assert!(
                result.reason.contains("unanswered for python:m.g"),
                "{}",
                result.reason
            );
            assert!(result.reason.contains(&g_member), "{}", result.reason);
            // f's call is still answered by f; g's stays owed.
            let joined = joined_member_cids(&pool);
            assert!(!joined.contains(&g_member));
        }
        assert!(DroppedAmbientPostReason::Unanswered.is_owed());
        assert!(!DroppedAmbientPostReason::Unanswered.is_wrong_answer());
        assert_eq!(DroppedAmbientPostReason::Unanswered.label(), "unanswered");
    }

    #[test]
    fn the_claims_own_unanswered_read_is_its_members_row_not_a_drop() {
        // `assert g(3) == 4` with nothing answering g: the member is the
        // claim proof's own owed row; the claim reads no joined contract.
        let site = answered_site(4, 12);
        let site_cid = undecided_site_coordinate_cid(&site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:m.g"), site);
        insert_contract(
            &mut pool,
            "blake3-512:own-unanswered-read",
            "test_g",
            same_proof_claim("call:g", 4, &site_cid),
        );
        let partition = linked_ambient_post_instances_for_inv(
            &same_proof_claim("call:g", 4, &site_cid),
            &collect_ambient_posts(&pool),
        );
        assert!(
            partition.kept.is_empty() && partition.dropped.is_empty(),
            "{partition:?}"
        );
        let mut report = crate::types::Report::default();
        crate::report::add_undecided_members(&pool, &BTreeMap::new(), &mut report);
        assert_eq!(report.owed, 1, "the unanswered call is owed");
    }

    /// `def f(x): return x.a == 1`-shaped: f's post reads an owed `==` at its
    /// own site (a member with no symbol). Its left operand, `x.a`, is a value
    /// whose builtin type nothing states, so binding `x` to the actual `3`
    /// leaves the comparison open: Python decides `3 == 1` itself (the SMT
    /// backend writes `==` over two `int`s as completing), but not `x.a == 1`.
    /// `decided` states the operation's completes atom in the post itself, so
    /// the joined post decides it.
    fn f_reads_owed_operation_pool(rhs: i64, decided: bool) -> (MementoPool, String) {
        let test_site = answered_site(4, 12);
        let test_site_cid = undecided_site_coordinate_cid(&test_site);
        let compare_site = answered_site(30, 36);
        let compare_key = undecided_site_coordinate_cid(&compare_site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:m.f"), test_site);
        let compare_member = insert_unanswered(&mut pool, None, compare_site);
        let x_a = json!({
            "kind": "ctor",
            "name": "python:attribute",
            "args": [var("x"), str_const("a")]
        });
        let completes = json!({
            "kind": "atomic",
            "name": "python:compare.completes",
            "args": [{
                "kind": "ctor",
                "name": "python:compare",
                "args": [str_const("Eq"), x_a, int(1), str_const(&compare_key)]
            }]
        });
        let guarded = json!({
            "kind": "implies",
            "operands": [completes.clone(), eqf(var("out"), var("x"))]
        });
        let post = if decided {
            json!({"kind": "and", "operands": [completes, guarded]})
        } else {
            guarded
        };
        own_function(&mut pool, "f", "python:m.f", post);
        insert_contract(
            &mut pool,
            "blake3-512:owed-operation-test-f",
            "test_f",
            same_proof_claim("call:f", rhs, &test_site_cid),
        );
        (pool, compare_member)
    }

    #[test]
    fn an_owed_operation_a_joined_post_reads_leaves_the_row_owed() {
        for rhs in [3, 4] {
            let (pool, compare_member) = f_reads_owed_operation_pool(rhs, false);
            let result = the_one_claim(&pool);
            assert_eq!(
                result.verdict,
                ObligationVerdict::Undecidable,
                "f(3) == {rhs} reads f's owed `==`, which nothing decides: {}",
                result.reason
            );
            let reason = &result.reason;
            assert!(reason.contains("unanswered for"), "{reason}");
            assert!(reason.contains(&compare_member), "{reason}");
        }
    }

    #[test]
    fn an_owed_operation_the_joined_posts_decide_does_not_hold_the_row() {
        let truthful = the_one_claim(&f_reads_owed_operation_pool(3, true).0);
        assert_eq!(
            truthful.verdict,
            ObligationVerdict::Discharged,
            "f's post decides its `==` completes: {}",
            truthful.reason
        );
        let lying = the_one_claim(&f_reads_owed_operation_pool(4, true).0);
        assert_eq!(lying.verdict, ObligationVerdict::Unsatisfied, "{}", lying.reason);
    }

    // ── A joined callee's halts are the caller's halts at the call ────────
    // `def f(x): if x == 3: raise ValueError; return x` and
    // `def test_f(): assert f(3) == 3`. f's halt stays f's own row; the call
    // `f(3)` can raise there too, so test_f has a halt row at the call, its
    // guard over the actual.

    const HALT_CALLEE: &str = "concept:panic-freedom.leaf.runtime-failure-site";

    /// `own_function` with one panic locus at `m.py:<line>` guarded `guard`.
    fn own_halting_function(
        pool: &mut MementoPool,
        name: &str,
        symbol: &str,
        post: Json,
        line: u64,
        guard: Json,
    ) -> String {
        let contract_cid = blake3_512_of(format!("halting-contract-{name}").as_bytes());
        pool.insert_unanchored_for_tests(
            test_cid(&contract_cid),
            json!({
                "evidence": {
                    "kind": "contract",
                    "body": {
                        "contractName": name,
                        "formals": ["x"],
                        "outBinding": "out",
                        "post": post,
                        "panicLoci": [{
                            "callee": HALT_CALLEE,
                            "file": "m.py",
                            "line": line,
                            "guard": guard
                        }]
                    }
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            test_cid(&blake3_512_of(format!("halting-bridge-{name}").as_bytes())),
            json!({
                "evidence": {
                    "kind": "bridge",
                    "body": {
                        "sourceSymbol": symbol,
                        "targetContractCid": contract_cid
                    }
                }
            }),
        );
        contract_cid
    }

    fn halt_rows_of<'a>(
        rows: &'a [crate::types::CallSite],
        property: &str,
    ) -> Vec<&'a crate::types::CallSite> {
        rows.iter()
            .filter(|cs| cs.panic_site && cs.property_name == property)
            .collect()
    }

    /// `f` halts when `x == 3`; `test_f` reads `f(actual)`.
    fn caller_of_halting_f(actual: i64) -> (MementoPool, String) {
        let test_site = answered_site(4, 12);
        let test_site_cid = undecided_site_coordinate_cid(&test_site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:m.f"), test_site);
        let f_cid = own_halting_function(
            &mut pool,
            "f",
            "python:m.f",
            eqf(var("out"), var("x")),
            2,
            eqf(var("x"), int(3)),
        );
        let call = json!({"kind": "ctor", "name": "call:f", "args": [int(actual)]});
        insert_contract(
            &mut pool,
            "blake3-512:caller-of-halting-f",
            "test_f",
            eqf(call_result(call, &test_site_cid), int(actual)),
        );
        (pool, f_cid)
    }

    #[test]
    fn a_joined_callees_halt_is_the_callers_halt_at_the_call() {
        let (pool, _) = caller_of_halting_f(3);
        let rows = crate::enumerate_callsites::run(&pool);
        let caller = halt_rows_of(&rows, "test_f");
        assert_eq!(
            caller.len(),
            1,
            "one halt of f, one row of the caller: {rows:?}"
        );
        let row = caller[0];
        assert_eq!(row.bridge_ir_name, HALT_CALLEE);
        // At the call site.
        assert_eq!(row.file.as_deref(), Some("test_consumer.py"));
        assert_eq!(row.line, Some(9));
        assert_eq!(
            row.guard_facts,
            vec![fold_ground_applications(&eqf(int(3), int(3)))],
            "f's guard `x == 3` over the call's actual"
        );
        // f's halt site is carried as the producer.
        assert_eq!(row.producer_file.as_deref(), Some("m.py"));
        assert_eq!(row.producer_line, Some(2));
        assert_eq!(row.producer_symbol.as_deref(), Some("python:m.f"));
        // f's own halt stays f's row, guarded over its formal.
        let callee = halt_rows_of(&rows, "f");
        assert_eq!(callee.len(), 1, "{rows:?}");
        assert_eq!(callee[0].guard_facts, vec![eqf(var("x"), int(3))]);
        // A halt the actual rules out is still a row (never dropped); its
        // guard says the actual rules it out.
        let (pool, _) = caller_of_halting_f(4);
        let rows = crate::enumerate_callsites::run(&pool);
        let caller = halt_rows_of(&rows, "test_f");
        assert_eq!(caller.len(), 1, "{rows:?}");
        assert_eq!(
            caller[0].guard_facts,
            vec![fold_ground_applications(&eqf(int(4), int(3)))]
        );
    }

    #[test]
    fn a_halt_reached_through_a_joined_callees_own_call_is_the_callers_too() {
        // `def g(x): if x == 0: raise; return x`, `def f(x): return g(x)`,
        // `def test_f(): assert f(3) == 3`.
        let test_site = answered_site(4, 12);
        let test_site_cid = undecided_site_coordinate_cid(&test_site);
        let f_site = answered_site(20, 24);
        let f_site_cid = undecided_site_coordinate_cid(&f_site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:m.f"), test_site);
        insert_unanswered(&mut pool, Some("python:m.g"), f_site);
        own_halting_function(
            &mut pool,
            "g",
            "python:m.g",
            eqf(var("out"), var("x")),
            7,
            eqf(var("x"), int(0)),
        );
        let inner = json!({"kind": "ctor", "name": "call:g", "args": [var("x")]});
        own_function(
            &mut pool,
            "f",
            "python:m.f",
            eqf(var("out"), call_result(inner, &f_site_cid)),
        );
        insert_contract(
            &mut pool,
            "blake3-512:caller-through-f",
            "test_f",
            same_proof_claim("call:f", 3, &test_site_cid),
        );
        let rows = crate::enumerate_callsites::run(&pool);
        let in_f = halt_rows_of(&rows, "f");
        // f calls g: g's halt is f's at that call.
        assert_eq!(in_f.len(), 1, "{rows:?}");
        assert_eq!(in_f[0].guard_facts, vec![eqf(var("x"), int(0))]);
        // g's halt reaches test_f through f.
        let in_test = halt_rows_of(&rows, "test_f");
        assert_eq!(in_test.len(), 1, "{rows:?}");
        assert_eq!(
            in_test[0].guard_facts,
            vec![fold_ground_applications(&eqf(int(3), int(0)))]
        );
        assert_eq!(in_test[0].producer_symbol.as_deref(), Some("python:m.g"));
        assert_eq!(in_test[0].producer_line, Some(7));
        // g's own halt stays g's row.
        assert_eq!(halt_rows_of(&rows, "g").len(), 1);
    }

    #[test]
    fn an_imported_callees_halt_is_the_importers_row_at_the_call() {
        use crate::types::SpeakerRole;
        let (mut pool, f_cid) = caller_of_halting_f(3);
        pool.attribute_member_for_tests(
            &test_cid_string(&f_cid),
            SpeakerRole::Vendor,
            "the-vendor",
        );
        let rows = crate::enumerate_callsites::run(&pool);
        let caller = halt_rows_of(&rows, "test_f");
        assert_eq!(caller.len(), 1, "{rows:?}");
        assert!(
            !crate::report::callsite_is_imported(caller[0], &pool),
            "the call is the importer's: its halt there is the importer's row"
        );
        let callee = halt_rows_of(&rows, "f");
        assert_eq!(callee.len(), 1, "{rows:?}");
        assert!(
            crate::report::callsite_is_imported(callee[0], &pool),
            "the callee's own halt stays the import's state"
        );
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
        assert_eq!(partition.dropped[0].source_symbol, "python:b64.encodeBase64");
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
                call_result(json!({"kind": "ctor", "name": "call:encodeBase64"}), JOIN_SITE),
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

    // ── Step 9: an operation with no symbol, answered by the joined contract ──
    // consumer: `assert concat(<actual>) == "abc"`. The call is an unanswered
    // member with the symbol `python:v.concat`; the `==` on its result is a
    // second member, at its own site, with no symbol. The vendor's `concat`
    // states `out = x + "c"`. With a `str` actual the joined post pins the
    // result to a `str`, so `==` is decided and its member is answered. With
    // nothing staged, or an actual that leaves `x + "c"` undecided, it is not.

    fn answered_site(start_col: i64, end_col: i64) -> sugar_proof_envelope::UndecidedSite {
        sugar_proof_envelope::UndecidedSite {
            file: "test_consumer.py".into(),
            source_cid: sugar_proof_envelope::AtomCid::try_parse(format!(
                "blake3-512:{}",
                "c".repeat(128)
            ))
            .unwrap(),
            start_line: 9,
            start_col,
            end_line: 9,
            end_col,
        }
    }

    /// Insert one `reason: unanswered` member; returns its member CID.
    fn insert_unanswered(
        pool: &mut MementoPool,
        symbol: Option<&str>,
        site: sugar_proof_envelope::UndecidedSite,
    ) -> String {
        let member = sugar_proof_envelope::UndecidedMember {
            symbol: symbol.map(str::to_string),
            site,
            reason: sugar_proof_envelope::UndecidedReason::Unanswered,
        };
        let cid = member.header_cid();
        let mut header = member.header_preimage();
        header["cid"] = Json::String(cid.clone());
        pool.insert_unanchored_for_tests(test_cid(&cid), json!({ "header": header }));
        cid
    }

    /// The consumer's pool, and the member CID of its `==`.
    fn answered_pool(actual: Json, staged: bool) -> (MementoPool, String) {
        let call_site = answered_site(11, 23);
        let compare_site = answered_site(11, 32);
        let call_site_cid = undecided_site_coordinate_cid(&call_site);
        let compare_key = undecided_site_coordinate_cid(&compare_site);
        let mut pool = MementoPool::default();
        insert_unanswered(&mut pool, Some("python:v.concat"), call_site);
        let compare_member = insert_unanswered(&mut pool, None, compare_site);

        let result = call_result(
            json!({"kind": "ctor", "name": "call:v.concat", "args": [actual]}),
            &call_site_cid,
        );
        let completes = json!({
            "kind": "atomic",
            "name": "python:compare.completes",
            "args": [{
                "kind": "ctor",
                "name": "python:compare",
                "args": [
                    str_const("Eq"),
                    result.clone(),
                    str_const("abc"),
                    str_const(&compare_key)
                ]
            }]
        });
        let holds = json!({
            "kind": "atomic",
            "name": "py.eq",
            "args": [result, str_const("abc")]
        });
        insert_contract(
            &mut pool,
            "blake3-512:answered-consumer",
            "test_consumer",
            json!({"kind": "and", "operands": [completes, holds]}),
        );
        if staged {
            let contract_cid = blake3_512_of(b"answered-vendor-concat-contract");
            let concat = json!({
                "kind": "ctor",
                "name": "python:binary_result",
                "args": [str_const("+"), var("x"), str_const("c"), str_const("vendor-site")]
            });
            pool.insert_unanchored_for_tests(
                test_cid(&contract_cid),
                json!({
                    "evidence": {
                        "kind": "contract",
                        "body": {
                            "contractName": "concat",
                            "formals": ["x"],
                            "outBinding": "out",
                            "post": eqf(var("out"), concat)
                        }
                    }
                }),
            );
            pool.insert_unanchored_for_tests(
                test_cid(&blake3_512_of(b"answered-vendor-concat-bridge")),
                json!({
                    "evidence": {
                        "kind": "bridge",
                        "body": {
                            "sourceSymbol": "python:v.concat",
                            "targetContractCid": contract_cid
                        }
                    }
                }),
            );
        }
        (pool, compare_member)
    }

    fn answered_at_prove(pool: &MementoPool) -> BTreeMap<String, String> {
        let (plan, registry) = z3_plan_and_registry();
        members_answered_at_prove(pool, &plan, &registry, &test_compilers())
    }

    #[test]
    fn a_completes_atom_is_read_at_its_site_and_occurrence() {
        let atom = |key: &str| {
            json!({
                "kind": "atomic",
                "name": "python:compare.completes",
                "args": [{
                    "kind": "ctor",
                    "name": "python:compare",
                    "args": [str_const("Eq"), var("a"), var("b"), str_const(key)]
                }]
            })
        };
        assert_eq!(completes_atom_site(&atom("blake3-512:s")), Some("blake3-512:s"));
        // An evaluation under an occurrence path is the same site.
        assert_eq!(
            completes_atom_site(&atom("blake3-512:s@loop:1/call:f")),
            Some("blake3-512:s")
        );
        // Not a completes atom; and a completes atom whose term is another
        // protocol's is not read.
        assert_eq!(completes_atom_site(&eqf(var("a"), var("b"))), None);
        let mismatched = json!({
            "kind": "atomic",
            "name": "python:compare.completes",
            "args": [{"kind": "ctor", "name": "python:truth", "args": [str_const("k")]}]
        });
        assert_eq!(completes_atom_site(&mismatched), None);

        // Atoms under connectives are found; a quantified body is not read.
        let claim = json!({"kind": "and", "operands": [
            {"kind": "not", "operands": [atom("blake3-512:s")]},
            atom("blake3-512:t@loop:2"),
            {"kind": "forall", "name": "q", "sort": {"kind": "primitive", "name": "Int"},
             "body": atom("blake3-512:u")}
        ]});
        let mut found = Vec::new();
        collect_completes_atoms(&claim, &mut found);
        let sites: Vec<&str> = found.iter().map(|(site, _atom)| *site).collect();
        assert_eq!(sites, vec!["blake3-512:s", "blake3-512:t"]);
    }

    #[test]
    fn an_operation_the_joined_contract_decides_is_answered_at_prove() {
        let (pool, compare_member) = answered_pool(str_const("ab"), true);
        let answered = answered_at_prove(&pool);
        assert_eq!(
            answered.keys().collect::<Vec<_>>(),
            vec![&compare_member],
            "the `==` on a result the joined post pins to a str is answered: {answered:?}"
        );
        let reason = &answered[&compare_member];
        assert!(reason.contains("python:v.concat"), "{reason}");
        assert!(reason.contains("python:compare.completes"), "{reason}");
    }

    #[test]
    fn an_operation_the_join_leaves_undecided_stays_owed() {
        // Nothing staged: no contract joins the call, so nothing decides the
        // `==` on its result.
        let (unstaged, _) = answered_pool(str_const("ab"), false);
        assert!(
            answered_at_prove(&unstaged).is_empty(),
            "an unjoined call's `==` stays owed"
        );
        // Staged, but the actual is an int: `3 + "c"` is not an operation
        // the solver decides, so the joined post states no type for the
        // result, and its `==` stays owed.
        let (undecided, _) = answered_pool(int(3), true);
        assert!(
            answered_at_prove(&undecided).is_empty(),
            "a join that leaves the operand undecided answers nothing"
        );
    }

    // ── The ancestry join (step 9; #7757): the `class E(ValueError)` twin ──
    // vendor `vendor.py` defines `class E(ValueError): pass`. Its proof states
    // the class's ancestry as `python:vendor.E::exception-ancestry`:
    // `adt.is_python_type(E, ValueError)` and the language's ancestry above
    // it, over the coordinates a consumer mints. The consumer imports `E`:
    //
    //     try:
    //         raise E
    //     except ValueError:
    //         r = 1
    //     except BaseException:
    //         r = 2
    //
    // `assert r == 1` holds on the first arm alone: `is(E, ValueError)`.
    // `assert r == 2` holds on the second arm alone:
    // `not is(E, ValueError) and is(E, BaseException)`.
    // Unstaged, both stay open. Staged, the match is decided.

    fn ancestry_identity(tag: &str, name: &str) -> Json {
        json!({
            "kind": "ctor",
            "name": PYTHON_EXCEPTION_TYPE_IDENTITY,
            "args": [str_const(tag), str_const(name)]
        })
    }

    fn ancestry_is_type(class: Json, ancestor: Json) -> Json {
        json!({"kind": "atomic", "name": PYTHON_IS_TYPE, "args": [class, ancestor]})
    }

    fn ancestry_vendor_e() -> Json {
        ancestry_identity("import", "vendor.E")
    }

    fn ancestry_builtin(name: &str) -> Json {
        ancestry_identity("builtins", name)
    }

    /// The vendor's ancestry row, as mint writes it into the vendor's proof.
    fn ancestry_vendor_row() -> Json {
        json!({
            "kind": "contract",
            "name": "python:vendor.E::exception-ancestry",
            "inv": {
                "kind": "and",
                "operands": [
                    ancestry_is_type(ancestry_vendor_e(), ancestry_builtin("ValueError")),
                    ancestry_is_type(ancestry_vendor_e(), ancestry_builtin("Exception")),
                    ancestry_is_type(ancestry_vendor_e(), ancestry_builtin("BaseException"))
                ]
            }
        })
    }

    fn ancestry_staged() -> ExceptionAncestry {
        let (symbol, facts) = exception_ancestry_of(&ancestry_vendor_row()).expect("ancestry");
        let mut ancestry = ExceptionAncestry::new();
        merge_exception_ancestry(&mut ancestry, symbol, facts);
        ancestry
    }

    /// The first arm's assertion: the handler `except ValueError` caught `E`.
    fn caught_by_value_error() -> Json {
        ancestry_is_type(ancestry_vendor_e(), ancestry_builtin("ValueError"))
    }

    /// The second arm's assertion: only `except BaseException` caught `E`.
    fn caught_by_base_exception_only() -> Json {
        json!({
            "kind": "and",
            "operands": [
                {"kind": "not", "operands": [caught_by_value_error()]},
                ancestry_is_type(ancestry_vendor_e(), ancestry_builtin("BaseException"))
            ]
        })
    }

    fn prove_with_ancestry(inv: Json, ancestry: &ExceptionAncestry) -> ConsistencyResult {
        let inv = with_exception_ancestry(inv, ancestry);
        let (plan, registry) = z3_plan_and_registry();
        check_inv_consistency(
            "except-claim".to_string(),
            "consistency:test_except",
            inv,
            Vec::new(),
            &plan,
            &registry,
            &test_compilers(),
        )
    }

    #[test]
    fn the_ancestry_row_is_a_stated_fact_never_a_claim() {
        let row = ancestry_vendor_row();
        assert!(!is_consistency_candidate(&row), "{row}");
        let (symbol, facts) = exception_ancestry_of(&row).expect("ancestry row");
        assert_eq!(symbol, "python:vendor.E");
        assert_eq!(facts.len(), 3, "{facts:?}");
    }

    #[test]
    fn the_ancestry_join_reads_the_class_symbol() {
        let staged = ancestry_staged();
        let facts = exception_ancestry_facts_for_inv(&caught_by_value_error(), &staged);
        assert_eq!(facts.len(), 3, "{facts:?}");

        // Another class, the same handler: nothing joins.
        let other = ancestry_is_type(
            ancestry_identity("import", "other.E"),
            ancestry_builtin("ValueError"),
        );
        assert!(exception_ancestry_facts_for_inv(&other, &staged).is_empty());

        // A class this pool states nothing for keeps its question open.
        let none = ExceptionAncestry::new();
        assert!(exception_ancestry_facts_for_inv(&caught_by_value_error(), &none).is_empty());
    }

    #[test]
    fn except_twin_unstaged_stays_open() {
        let unstaged = ExceptionAncestry::new();
        let caught = prove_with_ancestry(caught_by_value_error(), &unstaged);
        assert_ne!(
            caught.verdict,
            ObligationVerdict::Discharged,
            "nothing states E's bases, so `is(E, ValueError)` alone is not decided: {}",
            caught.reason
        );
        let missed = prove_with_ancestry(caught_by_base_exception_only(), &unstaged);
        assert_eq!(
            missed.verdict,
            ObligationVerdict::Discharged,
            "unstaged, nothing rules out a miss: {}",
            missed.reason
        );
    }

    #[test]
    fn except_twin_staged_decides_the_match() {
        let staged = ancestry_staged();
        let caught = prove_with_ancestry(caught_by_value_error(), &staged);
        assert_eq!(
            caught.verdict,
            ObligationVerdict::Discharged,
            "the vendor states `is(E, ValueError)`, so the handler catches E: {}",
            caught.reason
        );
        let missed = prove_with_ancestry(caught_by_base_exception_only(), &staged);
        assert_eq!(
            missed.verdict,
            ObligationVerdict::Unsatisfied,
            "the vendor states `is(E, ValueError)`, so `except ValueError` never misses E: {}",
            missed.reason
        );
    }

    // ── The ancestry closed across proofs (#7757) ──
    // `third.py`: `class Base(ValueError)`. `vendor.py`: `from third import
    // Base; class E(Base)`. The vendor's proof states only `is(E, Base)`;
    // third's states `is(Base, ValueError)` and the language's ancestry above
    // it. The consumer imports `E` and catches `ValueError` around `raise E`.
    //
    // Re-export: `vendor/errors.py`: `class E(ValueError)`;
    // `vendor/__init__.py`: `from .errors import E`. The consumer's `from
    // vendor import E` names `vendor.E`; the package's proof states
    // `is(vendor.E, vendor.errors.E)` and the defining module's proof states
    // `vendor.errors.E`'s ancestry.

    fn ancestry_row(class_symbol: &str, ancestors: &[Json]) -> Json {
        let class = ancestry_identity("import", class_symbol);
        let facts: Vec<Json> = ancestors
            .iter()
            .map(|ancestor| ancestry_is_type(class.clone(), ancestor.clone()))
            .collect();
        let inv = if facts.len() == 1 {
            facts[0].clone()
        } else {
            json!({"kind": "and", "operands": facts})
        };
        json!({
            "kind": "contract",
            "name": format!("python:{class_symbol}::exception-ancestry"),
            "inv": inv
        })
    }

    fn ancestry_of_rows(rows: &[Json]) -> ExceptionAncestry {
        let mut ancestry = ExceptionAncestry::new();
        for row in rows {
            let (symbol, facts) = exception_ancestry_of(row).expect("ancestry row");
            merge_exception_ancestry(&mut ancestry, symbol, facts);
        }
        ancestry
    }

    fn value_error_chain() -> Vec<Json> {
        vec![
            ancestry_builtin("ValueError"),
            ancestry_builtin("Exception"),
            ancestry_builtin("BaseException"),
        ]
    }

    /// `except ValueError` caught the imported class `class_symbol`.
    fn caught_by_value_error_of(class_symbol: &str) -> Json {
        ancestry_is_type(
            ancestry_identity("import", class_symbol),
            ancestry_builtin("ValueError"),
        )
    }

    /// Only `except BaseException` caught the imported class `class_symbol`.
    fn missed_by_value_error_of(class_symbol: &str) -> Json {
        json!({
            "kind": "and",
            "operands": [
                {"kind": "not", "operands": [caught_by_value_error_of(class_symbol)]},
                ancestry_is_type(
                    ancestry_identity("import", class_symbol),
                    ancestry_builtin("BaseException")
                )
            ]
        })
    }

    fn assert_match_decided(class_symbol: &str, staged: &ExceptionAncestry) {
        let caught = prove_with_ancestry(caught_by_value_error_of(class_symbol), staged);
        assert_eq!(
            caught.verdict,
            ObligationVerdict::Discharged,
            "`except ValueError` catches {class_symbol}: {}",
            caught.reason
        );
        let missed = prove_with_ancestry(missed_by_value_error_of(class_symbol), staged);
        assert_eq!(
            missed.verdict,
            ObligationVerdict::Unsatisfied,
            "`except ValueError` never misses {class_symbol}: {}",
            missed.reason
        );
    }

    /// Nothing staged closes `class_symbol` to `ValueError`: the joined facts
    /// leave a miss consistent.
    fn assert_match_open(class_symbol: &str, staged: &ExceptionAncestry) {
        let caught = canonicalize_formula_json(&caught_by_value_error_of(class_symbol));
        assert!(
            !exception_ancestry_facts_for_inv(&caught, staged).contains(&caught),
            "nothing staged states `is({class_symbol}, ValueError)`"
        );
        let missed = prove_with_ancestry(missed_by_value_error_of(class_symbol), staged);
        assert_eq!(
            missed.verdict,
            ObligationVerdict::Discharged,
            "nothing staged rules out a miss of {class_symbol}: {}",
            missed.reason
        );
    }

    #[test]
    fn except_twin_imported_base_closes_across_proofs() {
        let base = ancestry_identity("import", "third.Base");
        let vendor = ancestry_row("vendor.E", &[base]);
        let third = ancestry_row("third.Base", &value_error_chain());

        // The vendor's proof alone: `is(E, Base)`, and nothing about Base.
        assert_match_open("vendor.E", &ancestry_of_rows(&[vendor.clone()]));

        // Both staged: E's ancestry closes through Base's proof.
        let staged = ancestry_of_rows(&[vendor, third]);
        let caught = canonicalize_formula_json(&caught_by_value_error_of("vendor.E"));
        let facts = exception_ancestry_facts_for_inv(&caught, &staged);
        assert!(
            facts.contains(&caught),
            "the join derives `is(E, ValueError)`: {facts:?}"
        );
        assert_match_decided("vendor.E", &staged);
    }

    #[test]
    fn except_twin_reexported_class_closes_through_the_package() {
        let defined = ancestry_identity("import", "vendor.errors.E");
        let package = ancestry_row("vendor.E", &[defined]);
        let defining = ancestry_row("vendor.errors.E", &value_error_chain());

        // The defining module alone names `vendor.errors.E`, not the
        // `vendor.E` the consumer imports.
        assert_match_open("vendor.E", &ancestry_of_rows(&[defining.clone()]));

        assert_match_decided("vendor.E", &ancestry_of_rows(&[package, defining]));
    }

    #[test]
    fn closed_ancestry_ends_on_a_cycle() {
        let a = ancestry_row("m.A", &[ancestry_identity("import", "m.B")]);
        let b = ancestry_row("m.B", &[ancestry_identity("import", "m.A")]);
        // (A cycle cannot be written in Python; the closure still ends.)
        let staged = ancestry_of_rows(&[a, b]);
        let facts = closed_exception_ancestry("python:m.A", &staged);
        assert_eq!(facts.len(), 2, "{facts:?}");
        assert_match_open("m.A", &staged);
    }
}
