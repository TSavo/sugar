//! # sugar-linker
//!
//! Pure linker algebra for Sugar. Derives bridge mementos from the union of
//! per-kit contracts and call-edges, and emits a content-addressed `LinkBundle`
//! per spec `2026-05-03-bridge-linkage-protocol.md` R2-R5.
//!
//! ## Consumers
//!
//! - `sugar-cli`: the `sugar link` subcommand gathers contracts and
//!   call-edges from the filesystem and subprocess lifters, then calls
//!   `link_with_solvers(inputs, ...)` with the same solver-plan config shape
//!   used by `sugar prove`. It writes the resulting `LinkBundle` JSON to
//!   disk.
//!
//! - `sugar-linkerd` (LSP+linker daemon, step 2): the daemon receives
//!   `parseFile` RPCs from per-kit LSP plugins, reconstructs `LinkerInputs`
//!   from its in-memory union of kit streams, and calls `link(inputs)` to
//!   re-derive affected bridges. It returns per-file `LinkerError` diagnostics
//!   from `LinkerOutput.linker_errors` back to the LSP clients.
//!
//! ## Design invariants
//!
//! - `link()` is pure: no global state, no filesystem side effects. Calling
//!   it twice with byte-identical inputs produces byte-identical outputs.
//!   Without a solver registry it can only discharge `post_caller \u{2283}
//!   pre_callee` by structural / JCS-canonical equality; non-equal pairs
//!   surface as `implication-undecidable`.
//! - `link_with_solvers(inputs, &Registry, &SolverPlan)` extends `link()`
//!   with the workspace's existing solver registry (built by
//!   `sugar-verifier::solvers::registry::build` from `SolversConfig`).
//!   Output is byte-deterministic given inputs + a solver set whose
//!   verdicts are themselves deterministic; subprocess wall-clock varies
//!   but the chosen verdict is stable.
//! - `LinkerInputs` is `serde::Deserialize` so the daemon can reconstruct
//!   it directly from the `parseFile` request stream (spec #126 §3). The
//!   `Registry` and `SolverPlan` are intentionally NOT on `LinkerInputs`:
//!   they are execution config, not parseFile data, and the registry
//!   contains non-serializable `Arc<dyn Solver>` handles.
//! - `LinkerOutput.linker_errors` carries a `file` field so the daemon can
//!   attach LSP diagnostics to the correct editor pane.

use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CanonValue};
use sugar_verifier::solvers::{run_plan, SolverHandle, SolverPlan};
use sugar_verifier::types::ObligationVerdict;

/// Re-exports from `sugar-verifier` so callers do not need a direct
/// dependency on the verifier crate to construct a registry / plan.
pub mod solver_api {
    pub use sugar_verifier::solvers::{
        registry, run_plan, SolverConfig, SolverHandle, SolverPlan, SolversConfig, StubSolver,
        SubprocessSolver,
    };
    pub use sugar_verifier::types::ObligationVerdict;
}

/// Solver registry used by `link_with_solvers`. Mirrors the verifier's
/// `solvers::plan::Registry` shape (`name -> Arc<dyn Solver>`).
pub type Registry = HashMap<String, SolverHandle>;

// -------------------------------------------------------------------
// Public input types
// -------------------------------------------------------------------

/// A contract lifted from any kit, identified by its content-addressed CID.
///
/// Both the `contracts` from the rust-kit lifter and the `declarations` emitted
/// by go/other kit lifters are normalised into this shape before passing to
/// `link()`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkerContract {
    /// Function / method name as declared in the source kit.
    pub name: String,
    /// Kit identifier, e.g. `"rust-kit"`, `"go-kit"`.
    pub kit: String,
    /// Content-addressed contract CID, `blake3-512:<hex>`.
    pub contract_cid: String,
    /// Pre-condition formula as a `serde_json::Value` (ProofIR term).
    /// `None` if the function has no pre-condition annotation.
    pub pre_json: Option<Json>,
    /// Post-condition formula as a `serde_json::Value` (ProofIR term).
    /// `None` if the function has no post-condition annotation.
    pub post_json: Option<Json>,
}

/// A call edge emitted by a kit lifter.
///
/// Describes a call site where one contracted function calls another. Cross-kit
/// calls have `target_contract_cid: None` and `target_symbol` set to a
/// `"<kit>:<name>"` string for linker resolution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkerCallEdge {
    /// CID of the calling function's contract.
    pub source_contract_cid: String,
    /// CID of the callee's contract if already known (same-kit call), or `None`
    /// for cross-kit calls where the linker must resolve `target_symbol`.
    pub target_contract_cid: Option<String>,
    /// Symbol name for cross-kit resolution, e.g. `"rust-kit:process"`.
    pub target_symbol: String,
    /// JCS-canonical locus of the call site.  Shape per `ir-formal-grammar.md`.
    pub call_site_locus_json: Json,
    /// ProofIR evidence term encoding the satisfaction obligation `post_B ⊃ pre_A`.
    pub evidence_term_json: Json,
}

// -------------------------------------------------------------------
// Public output types
// -------------------------------------------------------------------

/// A linker error memento emitted when a satisfaction obligation cannot be
/// discharged, or when a cross-kit symbol cannot be resolved.
///
/// The `file` field is populated from the call-edge's `callSiteLocus.file`
/// so the daemon can attach LSP diagnostics to the correct source file.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkerError {
    /// Error kind: `"unresolved-symbol"` or `"unprovable-obligation"`.
    pub kind: String,
    /// The target symbol that was unresolved or whose obligation was unprovable.
    pub target_symbol: String,
    /// CID of the contract that made the call.
    pub source_contract_cid: String,
    /// Human-readable explanation.
    pub reason: String,
    /// Source file where the call site is located.  Derived from
    /// `call_site_locus_json.file`; `None` if the locus has no file field.
    pub file: Option<String>,
    /// Original call-site locus emitted by the owning kit. Used by linkerd/LSP
    /// to place solver diagnostics at the source call expression.
    pub call_site_locus_json: Option<Json>,
}

/// Input bundle for a single `link()` invocation.
///
/// Deserializable so the daemon can reconstruct it from the `parseFile`
/// request stream (spec #126 §3).  The daemon maintains a per-project union
/// of all kits' contracts and call-edges; on each `parseFile` event it
/// rebuilds `LinkerInputs` from that union and calls `link()`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkerInputs {
    /// Union of all kit contracts.
    pub contracts: Vec<LinkerContract>,
    /// Union of all kit call-edges.
    pub call_edges: Vec<LinkerCallEdge>,
}

/// Output of a single `link()` invocation.
///
/// The `bundle_json` field is a `serde_json::Value` ready to be serialised and
/// written to disk (CLI) or returned as a `projectStatus` response (daemon).
/// The scalar CID fields are extracted at the top level for convenience.
#[derive(Debug, Clone)]
pub struct LinkerOutput {
    /// `blake3-512` CID of the sorted contract set.
    pub contract_set_cid: String,
    /// `blake3-512` CID of the sorted call-edge set.
    pub call_edge_set_cid: String,
    /// `blake3-512` CID of the derived bridge set.
    pub bridge_set_cid: String,
    /// `blake3-512` CID of the full link bundle object.
    pub link_bundle_cid: String,
    /// Per-edge linker errors (unresolved symbols, unprovable obligations).
    /// Each error carries a `file` field for per-file LSP diagnostic mapping.
    pub linker_errors: Vec<LinkerError>,
    /// The full `LinkBundle` JSON object per spec R5, including `linkBundleCid`.
    pub bundle_json: Json,
}

// -------------------------------------------------------------------
// Public entry point
// -------------------------------------------------------------------

/// Derive bridges and emit a `LinkBundle` from the given inputs.
///
/// Pure function: no global state, no I/O.  Two calls with byte-identical
/// inputs produce byte-identical `LinkerOutput` values (including
/// `link_bundle_cid`).
///
/// # Solver discharge
///
/// Without a solver registry the linker can only verify
/// `post_caller \u{2283} pre_callee` by structural / JCS-canonical
/// equality. When both sides are non-null and structurally distinct,
/// this entry point emits an `implication-undecidable` error rather
/// than silently discharging. Use [`link_with_solvers`] to resolve
/// such cases via the workspace solver registry.
pub fn link(inputs: LinkerInputs) -> LinkerOutput {
    let empty_registry: Registry = HashMap::new();
    // Single-solver-named-"none" plan; lookup will miss for any
    // structurally-distinct discharge, surfacing as Undecidable.
    let no_op_plan = SolverPlan::Single("__no_solver__".into());
    let LinkerInputs {
        contracts,
        call_edges,
    } = inputs;
    derive_link_bundle_inner(contracts, call_edges, &empty_registry, &no_op_plan)
}

/// Derive bridges and emit a `LinkBundle`, using the supplied solver
/// registry + plan to discharge `post_caller \u{2283} pre_callee`
/// obligations whose two sides are structurally distinct.
///
/// `registry` and `plan` are typically built by the verifier crate's
/// `solvers::registry::build` from the same `SolversConfig` the
/// verifier uses (see `.sugar/config.toml`). The linker does not
/// hardcode any solver name; whichever solvers the workspace declares
/// are reached via the supplied plan.
///
/// Determinism contract: byte-identical `inputs` plus a registry
/// whose solvers are themselves deterministic (e.g. `StubSolver`,
/// or any sound SMT solver pinned by version in the config) yield a
/// byte-identical `LinkerOutput`. Solver wall-clock varies, but the
/// chosen verdict is stable.
pub fn link_with_solvers(
    inputs: LinkerInputs,
    registry: &Registry,
    plan: &SolverPlan,
) -> LinkerOutput {
    let LinkerInputs {
        contracts,
        call_edges,
    } = inputs;
    derive_link_bundle_inner(contracts, call_edges, registry, plan)
}

// -------------------------------------------------------------------
// Core derivation (private)
// -------------------------------------------------------------------

fn derive_link_bundle_inner(
    all_contracts: Vec<LinkerContract>,
    all_call_edges: Vec<LinkerCallEdge>,
    registry: &Registry,
    plan: &SolverPlan,
) -> LinkerOutput {
    // Build cross-kit resolution index: (name, kit) -> contract_cid
    let mut name_kit_index: BTreeMap<(String, String), String> = BTreeMap::new();
    for c in &all_contracts {
        name_kit_index.insert((c.name.clone(), c.kit.clone()), c.contract_cid.clone());
    }

    // contractSetCid
    let mut all_contract_cids: Vec<String> = all_contracts
        .iter()
        .map(|c| c.contract_cid.clone())
        .collect();
    all_contract_cids.sort();
    let contract_set_cid = compute_set_cid_sorted(&all_contract_cids);

    let mut bridges: Vec<Json> = Vec::new();
    let mut linker_errors_out: Vec<LinkerError> = Vec::new();

    // Sort call edges for determinism
    let mut sorted_edges = all_call_edges;
    sorted_edges.sort_by(|a, b| {
        a.source_contract_cid
            .cmp(&b.source_contract_cid)
            .then_with(|| {
                a.call_site_locus_json
                    .to_string()
                    .cmp(&b.call_site_locus_json.to_string())
            })
    });

    for edge in &sorted_edges {
        // Extract file from call-site locus for per-file diagnostics
        let locus_file = edge
            .call_site_locus_json
            .get("file")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let resolved_target_cid = if let Some(ref cid) = edge.target_contract_cid {
            Some(cid.clone())
        } else {
            resolve_target_symbol(&edge.target_symbol, &name_kit_index)
        };

        match resolved_target_cid {
            None => {
                linker_errors_out.push(LinkerError {
                    kind: "unresolved-symbol".into(),
                    target_symbol: edge.target_symbol.clone(),
                    source_contract_cid: edge.source_contract_cid.clone(),
                    reason: format!(
                        "targetSymbol `{}` did not resolve to any contract in the union",
                        edge.target_symbol
                    ),
                    file: locus_file,
                    call_site_locus_json: Some(edge.call_site_locus_json.clone()),
                });
            }
            Some(target_cid) => {
                let target_contract = all_contracts.iter().find(|c| c.contract_cid == target_cid);
                let source_contract = all_contracts
                    .iter()
                    .find(|c| c.contract_cid == edge.source_contract_cid);

                let source_post = source_contract.and_then(|c| c.post_json.as_ref());
                let target_pre = target_contract.and_then(|c| c.pre_json.as_ref());

                let bridge = derive_bridge(
                    &edge.source_contract_cid,
                    &target_cid,
                    &edge.call_site_locus_json,
                    &edge.evidence_term_json,
                );
                bridges.push(bridge);

                if let Some(mut err) = discharge_obligation(
                    source_post,
                    target_pre,
                    &edge.source_contract_cid,
                    &target_cid,
                    &edge.target_symbol,
                    registry,
                    plan,
                ) {
                    err.file = locus_file;
                    err.call_site_locus_json = Some(edge.call_site_locus_json.clone());
                    linker_errors_out.push(err);
                }
            }
        }
    }

    // Sort bridges for determinism
    bridges.sort_by(|a, b| {
        let ak = a
            .get("header")
            .and_then(|h| h.get("target"))
            .and_then(|t| t.get("cid"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let bk = b
            .get("header")
            .and_then(|h| h.get("target"))
            .and_then(|t| t.get("cid"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        ak.cmp(&bk)
    });

    // callEdgeSetCid
    let call_edge_set_cid = {
        let mut edge_bytes: Vec<String> = sorted_edges
            .iter()
            .map(|e| {
                serde_json::json!({
                    "sourceContractCid": e.source_contract_cid,
                    "targetContractCid": e.target_contract_cid,
                    "targetSymbol": e.target_symbol,
                })
                .to_string()
            })
            .collect();
        edge_bytes.sort();
        compute_set_cid_sorted(&edge_bytes)
    };

    // bridgeSetCid
    let bridge_set_cid = {
        let mut bridge_strs: Vec<String> = bridges.iter().map(|b| b.to_string()).collect();
        bridge_strs.sort();
        compute_set_cid_sorted(&bridge_strs)
    };

    // Build linkerErrors JSON array
    let linker_error_jsons: Vec<Json> = linker_errors_out
        .iter()
        .map(|e| {
            serde_json::json!({
                "kind": "linker-error",
                "errorKind": e.kind,
                "targetSymbol": e.target_symbol,
                "sourceContractCid": e.source_contract_cid,
                "reason": e.reason,
            })
        })
        .collect();

    // linkBundleCid is over JCS of the bundle sans the CID field itself
    let bundle_without_cid = serde_json::json!({
        "schemaVersion": "1",
        "kind": "link-bundle",
        "contractSetCid": contract_set_cid,
        "callEdgeSetCid": call_edge_set_cid,
        "bridgeSetCid": bridge_set_cid,
        "linkerVersion": "0.1.0",
        "linkerErrors": linker_error_jsons,
        "bridges": bridges,
    });

    let link_bundle_cid = blake3_512_of(&jcs_of_json(&bundle_without_cid));

    let mut bundle_json = bundle_without_cid;
    if let Some(obj) = bundle_json.as_object_mut() {
        obj.insert(
            "linkBundleCid".into(),
            Json::String(link_bundle_cid.clone()),
        );
    }

    LinkerOutput {
        contract_set_cid,
        call_edge_set_cid,
        bridge_set_cid,
        link_bundle_cid,
        linker_errors: linker_errors_out,
        bundle_json,
    }
}

// -------------------------------------------------------------------
// Cross-kit symbol resolution (R3)
// -------------------------------------------------------------------

fn resolve_target_symbol(
    target_symbol: &str,
    name_kit_index: &BTreeMap<(String, String), String>,
) -> Option<String> {
    let pos = target_symbol.find(':')?;
    let kit = &target_symbol[..pos];
    let name = &target_symbol[pos + 1..];
    if kit.is_empty() || name.is_empty() {
        return None;
    }
    name_kit_index
        .get(&(name.to_string(), kit.to_string()))
        .cloned()
}

// -------------------------------------------------------------------
// Bridge derivation (R2)
// -------------------------------------------------------------------

fn derive_bridge(
    source_contract_cid: &str,
    target_contract_cid: &str,
    call_site_locus: &Json,
    evidence_term: &Json,
) -> Json {
    serde_json::json!({
        "schemaVersion": "2",
        "kind": "bridge",
        "header": {
            "kind": "bridge",
            "sourceContractCid": source_contract_cid,
            "target": {
                "kind": "contract",
                "cid": target_contract_cid
            }
        },
        "metadata": {
            "callSite": call_site_locus,
            "derivedRelation": {
                "kind": "post-implies-pre",
                "evidenceTerm": evidence_term
            },
            "derivedBy": "linker",
            "linkerVersion": "0.1.0"
        }
    })
}

// -------------------------------------------------------------------
// Obligation discharge
// -------------------------------------------------------------------

/// Discharge the satisfaction obligation `post_caller \u{2283} pre_callee`
/// for one call edge. Returns `Some(LinkerError)` when the implication
/// cannot be proved (or is provably violated); returns `None` when the
/// implication holds.
///
/// Discharge is layered, cheapest-first:
///
/// 1. **Caller post absent.** No post-condition means the caller
///    promises nothing; the obligation is unprovable. Emits
///    `kind: "unprovable-obligation"` to preserve the historical
///    error string the polyglot smoke fixtures pin (PR #128 baseline).
///
/// 2. **Callee pre absent.** No pre-condition on the callee means the
///    obligation is vacuously discharged.
///
/// 3. **JCS-canonical equality.** If `post_caller` and `pre_callee`
///    canonicalize to byte-identical JCS, the predicates are the same
///    formula and the implication is reflexive. No solver work.
///
/// 4. **Solver dispatch.** Build the IR-JSON formula
///    `{"kind":"implies","operands":[post,pre]}`, compile to SMT-LIB,
///    and run the supplied `SolverPlan` against `Registry`. Map the
///    verdict:
///      * `Discharged` (UNSAT of `not(post -> pre)`): proven, return `None`.
///      * `Unsatisfied` (SAT counter-example): `implication-unprovable`.
///      * `Undecidable` / `Disagreement` / no solver registered:
///        `implication-undecidable` (do NOT silently discharge).
fn discharge_obligation(
    source_post: Option<&Json>,
    target_pre: Option<&Json>,
    source_contract_cid: &str,
    target_cid: &str,
    target_symbol: &str,
    registry: &Registry,
    plan: &SolverPlan,
) -> Option<LinkerError> {
    // (1) Caller post absent: cannot discharge.
    let post = match source_post {
        None | Some(Json::Null) => {
            return Some(LinkerError {
                kind: "unprovable-obligation".into(),
                target_symbol: target_symbol.to_string(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "caller post-condition is absent; cannot discharge `post_caller \u{2283} pre_callee` for target `{target_cid}`"
                ),
                file: None, // populated by caller from locus
                call_site_locus_json: None, // populated by caller from locus
            });
        }
        Some(p) => p,
    };

    // (2) Callee pre absent: vacuously discharged.
    let pre = match target_pre {
        None | Some(Json::Null) => return None,
        Some(p) => p,
    };

    // (3) JCS-canonical equality: P -> P trivially.
    let post_jcs = jcs_of_json(post);
    let pre_jcs = jcs_of_json(pre);
    if post_jcs == pre_jcs {
        return None;
    }

    // (4) Solver dispatch. Build the implication formula in IR-JSON,
    // emit SMT-LIB via the workspace IR compiler, and run the
    // configured plan against the supplied registry. The registry +
    // plan are external to the linker (the architect's "use whatever
    // Cargo.toml says" rule); we never reach for a hardcoded solver
    // name.
    let implication = serde_json::json!({
        "kind": "implies",
        "operands": [post.clone(), pre.clone()],
    });

    let smt_script = match sugar_ir_compiler_smt_lib::emit(&implication) {
        Ok(s) => s,
        Err(e) => {
            // Compilation failed: cannot ask the solver. Surface as
            // undecidable rather than silent-discharge.
            return Some(LinkerError {
                kind: "implication-undecidable".into(),
                target_symbol: target_symbol.to_string(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "compile post-implies-pre to SMT-LIB failed for target `{target_cid}`: {e}"
                ),
                file: None,
                call_site_locus_json: None,
            });
        }
    };

    let (verdict, reason, _invs) = run_plan(plan, registry, &smt_script, Some(&implication));

    match verdict {
        ObligationVerdict::Discharged => None,
        ObligationVerdict::Unsatisfied => Some(LinkerError {
            kind: "implication-unprovable".into(),
            target_symbol: target_symbol.to_string(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver reports `post_caller \u{2283} pre_callee` is violated for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus_json: None,
        }),
        ObligationVerdict::Undecidable | ObligationVerdict::Disagreement => Some(LinkerError {
            kind: "implication-undecidable".into(),
            target_symbol: target_symbol.to_string(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver could not decide `post_caller \u{2283} pre_callee` for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus_json: None,
        }),
        // A refusal is distinct from "undecidable": there is no sound discharger
        // for this bridge's obligation (the precondition lowers to a construct the
        // solver cannot interpret). Surface it by its own honest name, not as an
        // undecidable gap.
        ObligationVerdict::Refused => Some(LinkerError {
            kind: "implication-refused".into(),
            target_symbol: target_symbol.to_string(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "no sound discharger for `post_caller \u{2283} pre_callee` on target `{target_cid}`; refused, not guessed: {reason}"
            ),
            file: None,
            call_site_locus_json: None,
        }),
    }
}

// -------------------------------------------------------------------
// CID helpers (private)
// -------------------------------------------------------------------

fn compute_set_cid_sorted(sorted_items: &[String]) -> String {
    let arr: Vec<Arc<CanonValue>> = sorted_items
        .iter()
        .map(|s| CanonValue::string(s.clone()))
        .collect();
    let v = CanonValue::array(arr);
    let jcs = encode_jcs(&v);
    blake3_512_of(jcs.as_bytes())
}

fn jcs_of_json(v: &Json) -> Vec<u8> {
    encode_jcs(&json_to_canon_value(v)).into_bytes()
}

fn json_to_canon_value(j: &Json) -> CanonValue {
    match j {
        Json::Null => CanonValue::Null,
        Json::Bool(b) => CanonValue::Bool(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                CanonValue::Integer(i128::from(i))
            } else {
                CanonValue::String(n.to_string())
            }
        }
        Json::String(s) => CanonValue::String(s.clone()),
        Json::Array(arr) => CanonValue::Array(
            arr.iter()
                .map(|i| Arc::new(json_to_canon_value(i)))
                .collect(),
        ),
        Json::Object(map) => {
            // Sort by key per RFC 8785 (JCS).
            let mut entries: Vec<(String, Arc<CanonValue>)> = map
                .iter()
                .map(|(k, v)| (k.clone(), Arc::new(json_to_canon_value(v))))
                .collect();
            entries.sort_by(|a, b| a.0.cmp(&b.0));
            CanonValue::Object(entries)
        }
    }
}

// -------------------------------------------------------------------
// Tests
// -------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_process_contract() -> LinkerContract {
        LinkerContract {
            name: "process".into(),
            kit: "rust-kit".into(),
            contract_cid: "blake3-512:aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001".into(),
            pre_json: Some(serde_json::json!({
                "kind": "Gt",
                "args": [
                    {"kind": "Var", "name": "n", "sort": "Int"},
                    {"kind": "Num", "value": 0}
                ]
            })),
            post_json: None,
        }
    }

    fn make_go_caller_fail_contract() -> LinkerContract {
        LinkerContract {
            name: "GoCallerFail".into(),
            kit: "go-kit".into(),
            contract_cid: "blake3-512:ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002".into(),
            pre_json: None,
            post_json: None,
        }
    }

    fn make_go_caller_ok_contract() -> LinkerContract {
        LinkerContract {
            name: "GoCallerOk".into(),
            kit: "go-kit".into(),
            contract_cid: "blake3-512:ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003".into(),
            pre_json: None,
            post_json: None,
        }
    }

    fn make_cgo_call_edge(go_contract: &LinkerContract) -> LinkerCallEdge {
        LinkerCallEdge {
            source_contract_cid: go_contract.contract_cid.clone(),
            target_contract_cid: None,
            target_symbol: "rust-kit:process".into(),
            call_site_locus_json: serde_json::json!({
                "column": 9,
                "file": "examples/polyglot-rust-go/go-caller/caller_fail.go",
                "line": 21
            }),
            evidence_term_json: serde_json::json!({
                "kind": "Atomic",
                "name": "call-site-obligation",
                "args": [{"kind": "Var", "name": "GoCallerFail", "sort": "String"}]
            }),
        }
    }

    #[test]
    fn test_failure_case_emits_linker_error() {
        let output = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        });

        assert!(!output.linker_errors.is_empty());
        assert_eq!(output.linker_errors[0].kind, "unprovable-obligation");
        assert_eq!(output.linker_errors[0].target_symbol, "rust-kit:process");
        assert_eq!(
            output.linker_errors[0].file.as_deref(),
            Some("examples/polyglot-rust-go/go-caller/caller_fail.go")
        );
        assert!(output.link_bundle_cid.starts_with("blake3-512:"));

        eprintln!("failure-case linkBundleCid = {}", output.link_bundle_cid);
    }

    #[test]
    fn test_success_case_clean_bundle() {
        let output = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_ok_contract()],
            call_edges: vec![],
        });

        assert!(output.linker_errors.is_empty());
        assert!(output.link_bundle_cid.starts_with("blake3-512:"));

        eprintln!("success-case linkBundleCid = {}", output.link_bundle_cid);
    }

    #[test]
    fn test_byte_determinism() {
        let inputs = LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        };
        let out1 = link(inputs.clone());
        let out2 = link(inputs);
        assert_eq!(out1.link_bundle_cid, out2.link_bundle_cid);
    }

    #[test]
    fn test_failure_and_success_cids_differ() {
        let fail_out = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        });
        let ok_out = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_ok_contract()],
            call_edges: vec![],
        });
        assert_ne!(fail_out.link_bundle_cid, ok_out.link_bundle_cid);
    }

    /// Byte-identity gate: linkBundleCid must match the values pinned by
    /// the polyglot smoke suite in sugar-cli.
    #[test]
    fn test_link_bundle_cid_byte_identity_gate() {
        let fail_out = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        });
        let ok_out = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_ok_contract()],
            call_edges: vec![],
        });

        assert_eq!(
            fail_out.link_bundle_cid,
            "blake3-512:a0d04917ab46f58662b4f497a779cab8c2814df0bb40c8df0cb1b6abfe1eaabe7500f638249d423e4d74648add1ce5d47fd9502cd5481a9012807bba50aec584",
            "failure-case linkBundleCid must match baseline from PR #124 smoke test"
        );
        assert_eq!(
            ok_out.link_bundle_cid,
            "blake3-512:31fab69f197f4b279594972e35de7844f954a98ddce44b35edd14b77f53bd2ddb8ce95511bbef00f15476cc2f75f998ac4e419e5fe2c2162c008ba1c7c925131",
            "success-case linkBundleCid must match baseline from PR #124 smoke test"
        );
    }
}
