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
use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT as SMT_DIALECT};
use sugar_ir_types::IrFormula;
use sugar_verifier::solvers::{run_plan, SolverHandle, SolverPlan, SolverSeat};
use sugar_verifier::types::ObligationVerdict;

/// Re-exports from `sugar-verifier` so callers do not need a direct
/// dependency on the verifier crate to construct a registry / plan.
pub mod solver_api {
    pub use sugar_verifier::solvers::{
        registry, run_plan, SolverConfig, SolverHandle, SolverPlan, SolverSeat, SolversConfig,
        StubSolver, SubprocessSolver,
    };
    pub use sugar_verifier::types::ObligationVerdict;
}

/// Solver registry used by `link_with_solvers`. Mirrors the verifier's
/// `solvers::plan::Registry` shape (`seat -> Arc<dyn Solver>`).
pub type Registry = HashMap<SolverSeat, SolverHandle>;

// -------------------------------------------------------------------
// Public input types
// -------------------------------------------------------------------

/// A contract lifted from any kit, identified by its content-addressed CID.
///
/// Both the `contracts` from the rust-kit lifter and the `declarations` emitted
/// by go/other kit lifters are normalised into this shape before passing to
/// `link()`.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct LinkerContract {
    /// Function / method name as declared in the source kit.
    pub name: String,
    /// Kit identifier, e.g. `"rust-kit"`, `"go-kit"`.
    pub kit: String,
    /// Content-addressed contract CID, `blake3-512:<hex>`.
    pub contract_cid: String,
    /// Pre-condition formula as a strongly-typed [`IrFormula`] (ProofIR
    /// formula). `None` if the function has no pre-condition annotation.
    /// Retyped from `serde_json::Value` in the formula-typeify seam: the
    /// `{"kind":...}` wire JSON is unchanged (IrFormula is `#[serde(tag =
    /// "kind")]` and serializes to the identical tagged object), so contract
    /// CIDs and snapshot bytes are byte-for-byte preserved.
    pub pre_json: Option<IrFormula>,
    /// Post-condition formula as a strongly-typed [`IrFormula`] (ProofIR
    /// formula). `None` if the function has no post-condition annotation.
    /// See [`LinkerContract::pre_json`] for the byte-identity contract.
    pub post_json: Option<IrFormula>,
    /// Declared formal parameter names, in order. Part of the contract's
    /// exported signature: an importing call edge whose [`ImportSignature`]
    /// disagrees with these is rejected by [`bind`] as `signature-mismatch`.
    /// Empty (default) means the contract exports no formal-name signature to
    /// check against — pre-existing wire payloads that omit it deserialize
    /// cleanly and never trip the check.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub formals: Vec<String>,
    /// Declared formal sorts, positionally aligned with `formals`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub formal_sorts: Vec<Json>,
    /// EUF coordinate (the `enc#euf#c:...` segment) this contract answers to,
    /// if it is an EUF-callsite contract. `None` for ordinary contracts.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub euf_coordinate: Option<String>,
}

/// A call edge emitted by a kit lifter.
///
/// Describes a call site where one contracted function calls another. Cross-kit
/// calls have `target_contract_cid: None` and `target_symbol` set to a
/// `"<kit>:<name>"` string for linker resolution.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
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
    /// The typed import signature the call site declares for its target: the
    /// symbol plus the formals/sorts/EUF coordinate the caller expects the
    /// callee to export. When present, [`bind`] type-checks it against the
    /// resolved contract's exported signature; disagreement is
    /// `signature-mismatch`. Absent (default) on pre-existing wire payloads,
    /// which therefore only exercise the resolution (undefined-symbol) check.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub import_signature: Option<ImportSignature>,
}

/// The unbound half of a call edge's typed two-state target: the import
/// signature a call site declares before the linker resolves it.
///
/// This is the extern declaration in ProofIR clothing. It is what today lives
/// flattened inside the `<kit>:<name>` `target_symbol` string plus the runtime
/// formals/sorts kind-checks re-derived at verify time. Hoisting it to a type
/// lets [`bind`] discharge the signature match in a single constructor
/// signature instead of scattered runtime checks.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ImportSignature {
    /// `<kit>:<name>` symbol the call site imports.
    pub symbol: String,
    /// Formal names the caller expects the callee to export, in order.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub formals: Vec<String>,
    /// Formal sorts, positionally aligned with `formals`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub sorts: Vec<Json>,
    /// EUF coordinate the caller expects the callee to answer to.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub euf_coordinate: Option<String>,
}

impl ImportSignature {
    /// Type-check this declared import signature against a resolved contract's
    /// exported signature. `Ok(())` when they agree (a bound edge may be
    /// minted); `Err(reason)` names the disagreement for a `signature-mismatch`
    /// [`LinkerError`]. Only dimensions the caller actually declares are
    /// checked: a signature that names no formals imposes no formal-arity
    /// constraint, so pre-signature wire edges never spuriously fail.
    fn check(&self, target: &LinkerContract) -> Result<(), String> {
        if !self.formals.is_empty() && self.formals != target.formals {
            return Err(format!(
                "formals disagree: caller imports {:?}, callee exports {:?}",
                self.formals, target.formals
            ));
        }
        if !self.sorts.is_empty() && self.sorts != target.formal_sorts {
            return Err(format!(
                "formal sorts disagree: caller imports {:?}, callee exports {:?}",
                self.sorts, target.formal_sorts
            ));
        }
        if let Some(coord) = &self.euf_coordinate {
            if target.euf_coordinate.as_ref() != Some(coord) {
                return Err(format!(
                    "EUF coordinate disagrees: caller imports {:?}, callee exports {:?}",
                    Some(coord),
                    target.euf_coordinate
                ));
            }
        }
        Ok(())
    }
}

// -------------------------------------------------------------------
// Public output types
// -------------------------------------------------------------------

/// The typed vocabulary of linker failures.
///
/// Every way `link()` can refuse to mint a bound edge or discharge an
/// obligation is one of these variants. The two edge-binding failures the
/// migrated `resolve_target` join used to re-derive at verify time now live
/// here as first-class names:
///
/// - [`LinkerErrorKind::UnresolvedSymbol`] — no member answers the import
///   (the undefined-symbol case).
/// - [`LinkerErrorKind::SignatureMismatch`] — a member exists but its
///   formals/sorts/EUF coordinate disagree with the call site's declared
///   [`ImportSignature`].
///
/// The remaining variants are the obligation-discharge outcomes. Each variant
/// serializes to a stable wire string via [`LinkerErrorKind::wire_str`]; the
/// custom `Serialize`/`Deserialize` impls keep the `errorKind` JSON field
/// byte-identical to the pre-migration string it replaced.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkerErrorKind {
    /// No contract in the union answers the edge's target symbol / CID.
    UnresolvedSymbol,
    /// A target contract was found, but its exported signature disagrees with
    /// the call site's declared [`ImportSignature`].
    SignatureMismatch,
    /// Caller post-condition absent; `post_caller ⊃ pre_callee` unprovable.
    UnprovableObligation,
    /// Solver reports the implication is violated (SAT counter-example).
    ImplicationUnprovable,
    /// Solver could not decide the implication (or none was registered).
    ImplicationUndecidable,
    /// Solver exceeded the host timeout on the implication.
    ImplicationSolverTimeout,
    /// No sound discharger exists for this obligation; refused, not guessed.
    ImplicationRefused,
}

impl LinkerErrorKind {
    /// The stable wire string for this kind. These strings are load-bearing:
    /// the polyglot smoke fixtures and LSP diagnostics pin them.
    pub fn wire_str(self) -> &'static str {
        match self {
            LinkerErrorKind::UnresolvedSymbol => "unresolved-symbol",
            LinkerErrorKind::SignatureMismatch => "signature-mismatch",
            LinkerErrorKind::UnprovableObligation => "unprovable-obligation",
            LinkerErrorKind::ImplicationUnprovable => "implication-unprovable",
            LinkerErrorKind::ImplicationUndecidable => "implication-undecidable",
            LinkerErrorKind::ImplicationSolverTimeout => "implication-solver-timeout",
            LinkerErrorKind::ImplicationRefused => "implication-refused",
        }
    }

    /// Inverse of [`wire_str`](Self::wire_str). Unknown strings deserialize to
    /// `None`.
    fn from_wire(s: &str) -> Option<Self> {
        Some(match s {
            "unresolved-symbol" => LinkerErrorKind::UnresolvedSymbol,
            "signature-mismatch" => LinkerErrorKind::SignatureMismatch,
            "unprovable-obligation" => LinkerErrorKind::UnprovableObligation,
            "implication-unprovable" => LinkerErrorKind::ImplicationUnprovable,
            "implication-undecidable" => LinkerErrorKind::ImplicationUndecidable,
            "implication-solver-timeout" => LinkerErrorKind::ImplicationSolverTimeout,
            "implication-refused" => LinkerErrorKind::ImplicationRefused,
            _ => return None,
        })
    }
}

impl Serialize for LinkerErrorKind {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.wire_str())
    }
}

impl<'de> Deserialize<'de> for LinkerErrorKind {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        LinkerErrorKind::from_wire(&s)
            .ok_or_else(|| serde::de::Error::custom(format!("unknown linker error kind `{s}`")))
    }
}

/// A non-nullable, linker-minted contract CID: the bound half of a call edge's
/// typed two-state target.
///
/// The inner field is private and there is no public constructor, so a
/// `BoundContractCid` can only be produced inside this crate by [`bind`], and
/// only from a contract that actually answered the edge. That makes
/// "a bound edge carrying a null / unresolved CID" **unrepresentable**: the
/// null lives only in the *unbound* input (`LinkerCallEdge.target_contract_cid:
/// Option<String>`), never in a value of this type. The linker is thus the sole
/// minter of bound edges.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundContractCid(String);

impl BoundContractCid {
    /// Borrow the resolved CID string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// A linker error memento emitted when a satisfaction obligation cannot be
/// discharged, or when a cross-kit symbol cannot be resolved.
///
/// The `file` field is populated from the call-edge's `callSiteLocus.file`
/// so the daemon can attach LSP diagnostics to the correct source file.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkerError {
    /// Typed error kind. Serializes to its stable wire string (see
    /// [`LinkerErrorKind::wire_str`]) so `linkBundle.linkerErrors[*].errorKind`
    /// and the linkerd LSP diagnostics keep their byte-for-byte shape.
    pub kind: LinkerErrorKind,
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
    // Single-Z3 plan over an empty registry; lookup will miss for any
    // structurally-distinct discharge, surfacing as Undecidable.
    let no_op_plan = SolverPlan::Single(SolverSeat::Z3);
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
    // Build the resolution indices once:
    //   name_kit_index   : (name, kit) -> contract_cid   (cross-kit symbol join)
    //   contracts_by_cid : cid -> &LinkerContract         (member lookup)
    let mut name_kit_index: BTreeMap<(String, String), String> = BTreeMap::new();
    let mut contracts_by_cid: BTreeMap<&str, &LinkerContract> = BTreeMap::new();
    for c in &all_contracts {
        name_kit_index.insert((c.name.clone(), c.kit.clone()), c.contract_cid.clone());
        contracts_by_cid.insert(c.contract_cid.as_str(), c);
    }

    // contractSetCid
    let mut all_contract_cids: Vec<String> = all_contracts
        .iter()
        .map(|c| c.contract_cid.clone())
        .collect();
    all_contract_cids.sort();
    let contract_set_cid = compute_set_cid_sorted(&all_contract_cids);

    let mut bridges: Vec<DerivedBridge> = Vec::new();
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

        // bind: the sole minter of a `BoundContractCid`, with two outcomes —
        // the bound target, or the typed failure (undefined-symbol /
        // signature-mismatch). This is the migrated resolve_target join: the
        // string join and the member check that verify used to re-derive now
        // live in one constructor signature.
        let bound = match bind(edge, &name_kit_index, &contracts_by_cid) {
            Ok(bound) => bound,
            Err(mut err) => {
                err.file = locus_file;
                err.call_site_locus_json = Some(edge.call_site_locus_json.clone());
                linker_errors_out.push(err);
                continue;
            }
        };
        let target_cid = bound.as_str();

        let source_post = contracts_by_cid
            .get(edge.source_contract_cid.as_str())
            .and_then(|c| c.post_json.as_ref());
        let target_pre = contracts_by_cid
            .get(target_cid)
            .and_then(|c| c.pre_json.as_ref());

        // Construct the satisfaction obligation `post_B \u{2283} pre_A` ONCE,
        // as a typed [`ObligationState`]. Before this seam the obligation was
        // rebuilt as untyped JSON in disjoint places, so the term *carried on
        // the bridge* could drift from the term *checked by the verifier*.
        // Here it is a single value: attached to the [`DerivedBridge`] and
        // discharged below. Carried == checked by construction.
        let obligation = ObligationState::derive(source_post, target_pre);

        // The on-wire memento is byte-identical: `evidenceTerm` still carries
        // the emit-side placeholder (replacing it with the live obligation
        // changes call-edge / bridge CIDs — the emit-side follow-up). Only the
        // in-memory `obligation` field is new, and it is not serialized.
        let memento = derive_bridge(
            &edge.source_contract_cid,
            target_cid,
            &edge.call_site_locus_json,
            &edge.evidence_term_json,
        );
        let bridge = DerivedBridge {
            memento,
            obligation,
        };

        if let Some(mut err) = discharge_obligation(
            &bridge.obligation,
            &edge.source_contract_cid,
            target_cid,
            &edge.target_symbol,
            registry,
            plan,
        ) {
            err.file = locus_file;
            err.call_site_locus_json = Some(edge.call_site_locus_json.clone());
            linker_errors_out.push(err);
        }

        bridges.push(bridge);
    }

    // Sort bridges for determinism (over the wire memento only).
    bridges.sort_by(|a, b| {
        let ak = a
            .memento
            .get("header")
            .and_then(|h| h.get("target"))
            .and_then(|t| t.get("cid"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let bk = b
            .memento
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

    // bridgeSetCid (over the wire memento only).
    let bridge_set_cid = {
        let mut bridge_strs: Vec<String> =
            bridges.iter().map(|b| b.memento.to_string()).collect();
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

    // Wire bridges: only the byte-identical mementos are serialized. The
    // in-memory `obligation` field on each [`DerivedBridge`] never reaches the
    // bundle, so the bundle bytes (and linkBundleCid) are unchanged.
    let bridge_mementos: Vec<Json> = bridges.into_iter().map(|b| b.memento).collect();

    // linkBundleCid is over JCS of the bundle sans the CID field itself
    let bundle_without_cid = serde_json::json!({
        "schemaVersion": "1",
        "kind": "link-bundle",
        "contractSetCid": contract_set_cid,
        "callEdgeSetCid": call_edge_set_cid,
        "bridgeSetCid": bridge_set_cid,
        "linkerVersion": "0.1.0",
        "linkerErrors": linker_error_jsons,
        "bridges": bridge_mementos,
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
// Edge binding: the typed two-state target + the sole bound-edge minter
// -------------------------------------------------------------------

/// A call edge's declared target, as a typed two-state sum — the linker
/// vocabulary that replaces `targetContractCid: null | string` (a sum
/// flattened to null).
///
/// `Unbound` is an import the linker must still resolve, carrying the call
/// site's [`ImportSignature`]. `Bound` is a kit-supplied CID *claim* the linker
/// will re-check against the member index before minting the authoritative
/// [`BoundContractCid`]. There is no third, null state: an edge with neither a
/// resolvable symbol nor a member behind its CID simply fails to [`bind`].
enum EdgeTarget<'a> {
    Unbound(ImportSignature),
    Bound(&'a str),
}

impl LinkerCallEdge {
    /// Classify this edge's declared target into the typed two-state sum. The
    /// kit-supplied `target_contract_cid` is only a claim (`Bound`); an edge
    /// without one is `Unbound` and carries its [`ImportSignature`] (synthesized
    /// symbol-only when the wire payload predates signatures).
    fn edge_target(&self) -> EdgeTarget<'_> {
        match &self.target_contract_cid {
            Some(cid) => EdgeTarget::Bound(cid),
            None => EdgeTarget::Unbound(self.import_signature.clone().unwrap_or_else(|| {
                ImportSignature {
                    symbol: self.target_symbol.clone(),
                    formals: Vec::new(),
                    sorts: Vec::new(),
                    euf_coordinate: None,
                }
            })),
        }
    }
}

/// Mint a [`BoundContractCid`] from an unbound call edge, or return the typed
/// failure. The migrated `resolve_target` join, expressed as a constructor with
/// exactly two outcomes:
///
/// - `Ok(BoundContractCid)` — a member answered and, if the edge declared an
///   [`ImportSignature`], its exported signature agrees.
/// - `Err(LinkerError)` — [`LinkerErrorKind::UnresolvedSymbol`] (no member
///   answers) or [`LinkerErrorKind::SignatureMismatch`] (member exists, its
///   formals/sorts/EUF coordinate disagree).
///
/// `bind` is the only place a `BoundContractCid` is constructed, so every bound
/// edge in a `LinkBundle` was minted here from a contract that exists in the
/// union. A kit-supplied `target_contract_cid` is re-checked against the member
/// index, so a kit cannot forge a bound edge to a CID with no contract behind
/// it.
fn bind(
    edge: &LinkerCallEdge,
    name_kit_index: &BTreeMap<(String, String), String>,
    contracts_by_cid: &BTreeMap<&str, &LinkerContract>,
) -> Result<BoundContractCid, LinkerError> {
    let undefined = || LinkerError {
        kind: LinkerErrorKind::UnresolvedSymbol,
        target_symbol: edge.target_symbol.clone(),
        source_contract_cid: edge.source_contract_cid.clone(),
        reason: format!(
            "targetSymbol `{}` did not resolve to any contract in the union",
            edge.target_symbol
        ),
        file: None,
        call_site_locus_json: None,
    };

    // Resolve to a candidate CID: the kit's claim, else the cross-kit symbol
    // join. A symbol that resolves to nothing is undefined.
    let cid: String = match edge.edge_target() {
        EdgeTarget::Bound(cid) => cid.to_string(),
        EdgeTarget::Unbound(sig) => {
            resolve_target_symbol(&sig.symbol, name_kit_index).ok_or_else(undefined)?
        }
    };

    // The member must answer: a CID with no contract behind it is undefined.
    let target = contracts_by_cid.get(cid.as_str()).ok_or_else(undefined)?;

    // Signature match: the declared import must agree with the exported
    // contract on formals / sorts / EUF coordinate.
    if let Some(sig) = &edge.import_signature {
        if let Err(reason) = sig.check(target) {
            return Err(LinkerError {
                kind: LinkerErrorKind::SignatureMismatch,
                target_symbol: edge.target_symbol.clone(),
                source_contract_cid: edge.source_contract_cid.clone(),
                reason: format!(
                    "import signature for `{}` does not match contract {}: {reason}",
                    edge.target_symbol, cid
                ),
                file: None,
                call_site_locus_json: None,
            });
        }
    }

    Ok(BoundContractCid(cid))
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
// Obligation: the one typed representation of `post_B \u{2283} pre_A`
// -------------------------------------------------------------------

/// The satisfaction obligation `post_caller \u{2283} pre_callee` for one bound
/// call edge, expressed over strongly-typed [`IrFormula`]s.
///
/// This is the single typed representation of the thing the linker proves.
/// Before this seam the obligation was rebuilt as untyped `serde_json::Value`
/// in disjoint places — the emit-side `evidenceTerm` placeholder carried into
/// the bridge, and `discharge_obligation`'s inline `implies` term — so the term
/// *minted* into a bridge could drift from the term *checked* by the verifier.
/// Constructing it once (see [`ObligationState::derive`]) and threading the same
/// value to both the [`DerivedBridge`] and the discharge makes carried ==
/// checked by construction.
///
/// The bridge's on-wire `evidenceTerm` field still serializes the emit-side
/// placeholder for byte-identity (replacing it changes call-edge / bridge CIDs
/// and is the emit-side follow-up). The in-memory obligation carried on the
/// [`DerivedBridge`] is the authoritative value the verifier discharges, and
/// [`Obligation::as_implies`] already lowers to the exact JSON that future wire
/// minting would use.
#[derive(Debug, Clone, PartialEq)]
struct Obligation {
    /// Caller post-condition `post_B`.
    post: IrFormula,
    /// Callee pre-condition `pre_A`.
    pre: IrFormula,
}

impl Obligation {
    fn new(post: IrFormula, pre: IrFormula) -> Self {
        Self { post, pre }
    }

    /// Lower to the `{"kind":"implies","operands":[post,pre]}` IR formula the
    /// SMT compiler consumes. Byte-identical to the inline `IrFormula::Implies`
    /// term this seam replaced, so no solver input or verdict changes.
    fn as_implies(&self) -> IrFormula {
        IrFormula::Implies {
            operands: vec![self.post.clone(), self.pre.clone()],
        }
    }
}

/// The link-time obligation state for one bound edge: a concrete obligation to
/// discharge, or one of the two structural short-circuits. Built once by
/// [`ObligationState::derive`] and consumed by [`discharge_obligation`], so the
/// discharge branches map one-to-one onto the historical error strings.
#[derive(Debug, Clone, PartialEq)]
enum ObligationState {
    /// Both formulas present: a concrete `post \u{2283} pre` to discharge.
    Pending(Obligation),
    /// Caller post-condition absent: `post \u{2283} pre` cannot be discharged
    /// (`unprovable-obligation`).
    CallerPostAbsent,
    /// Callee pre-condition absent: vacuously discharged.
    VacuousPreAbsent,
}

impl ObligationState {
    /// Derive the obligation state from the caller post / callee pre formulas.
    /// The `(None, _)` before `(Some, None)` ordering preserves the historical
    /// precedence: caller-post-absent is reported even when the callee also has
    /// no pre-condition.
    fn derive(source_post: Option<&IrFormula>, target_pre: Option<&IrFormula>) -> Self {
        match (source_post, target_pre) {
            (None, _) => ObligationState::CallerPostAbsent,
            (Some(_), None) => ObligationState::VacuousPreAbsent,
            (Some(post), Some(pre)) => {
                ObligationState::Pending(Obligation::new(post.clone(), pre.clone()))
            }
        }
    }
}

/// A derived bridge: the byte-identical wire memento plus the in-memory
/// [`ObligationState`] it stands for.
///
/// Serializing a `LinkBundle` uses only `memento` (unchanged bytes); the
/// verifier discharges `obligation` — the SAME value that is carried here, so
/// the thing carried on the bridge IS the thing checked. The `obligation` field
/// is never serialized, keeping the bundle bytes and `linkBundleCid` identical.
struct DerivedBridge {
    /// The wire-facing bridge memento (byte-identical to the pre-seam JSON).
    memento: Json,
    /// The in-memory obligation this bridge carries and the verifier discharges.
    obligation: ObligationState,
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
    state: &ObligationState,
    source_contract_cid: &str,
    target_cid: &str,
    target_symbol: &str,
    registry: &Registry,
    plan: &SolverPlan,
) -> Option<LinkerError> {
    // (1)/(2) Structural short-circuits, decided when the obligation was
    // derived (see [`ObligationState::derive`]). A caller with no post-condition
    // promises nothing (`unprovable-obligation`); a callee with no pre-condition
    // is vacuously discharged. (A wire `null` deserializes to `None` under
    // `Option<IrFormula>`, so the old `Some(Json::Null)` arm folds into these
    // with identical behavior.)
    let obligation = match state {
        ObligationState::CallerPostAbsent => {
            return Some(LinkerError {
                kind: LinkerErrorKind::UnprovableObligation,
                target_symbol: target_symbol.to_string(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "caller post-condition is absent; cannot discharge `post_caller \u{2283} pre_callee` for target `{target_cid}`"
                ),
                file: None, // populated by caller from locus
                call_site_locus_json: None, // populated by caller from locus
            });
        }
        ObligationState::VacuousPreAbsent => return None,
        ObligationState::Pending(o) => o,
    };

    // (3) JCS-canonical equality: P -> P trivially. JCS sorts keys, so the
    // comparison is insensitive to formula field order; typing the formulas
    // does not change any verdict here.
    let post_jcs = jcs_of_formula(&obligation.post);
    let pre_jcs = jcs_of_formula(&obligation.pre);
    if post_jcs == pre_jcs {
        return None;
    }

    // (4) Solver dispatch. Build the implication formula in IR-JSON,
    // emit SMT-LIB via the workspace IR compiler, and run the
    // configured plan against the supplied registry. The registry +
    // plan are external to the linker (the architect's "use whatever
    // Cargo.toml says" rule); we never reach for a hardcoded solver
    // name.
    //
    // The implication is lowered from the SAME [`Obligation`] carried on the
    // bridge, so the term checked here is exactly the term the bridge stands
    // for.
    let implication_formula = obligation.as_implies();
    // Lower the typed formula back to the same `{"kind":"implies","operands":
    // [post, pre]}` JSON the compiler consumed before this seam. `to_value`
    // on an `IrFormula` is infallible (derived Serialize over owned data);
    // the SMT script it feeds is a derived intermediate, never a wire artifact.
    let implication = serde_json::to_value(&implication_formula)
        .expect("IrFormula::Implies always serializes to JSON");

    let implication_input = match CompilerInput::decode_json(implication.clone()) {
        Ok(input) => input,
        Err(error) => {
            return Some(LinkerError {
                kind: LinkerErrorKind::ImplicationUndecidable,
                target_symbol: target_symbol.to_string(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "decode post-implies-pre ProofIR failed for target `{target_cid}`: {}",
                    error.payload
                ),
                file: None,
                call_site_locus_json: None,
            });
        }
    };
    let smt_script = match SmtLibCompiler::new()
        .compile_typed(&implication_input, SMT_DIALECT)
        .map(|compiled| compiled.script())
    {
        Ok(s) => s,
        Err(e) => {
            // Compilation failed: cannot ask the solver. Surface as
            // undecidable rather than silent-discharge.
            return Some(LinkerError {
                kind: LinkerErrorKind::ImplicationUndecidable,
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

    let (verdict, reason, _invs) = run_plan(plan, registry, &smt_script, Some(&implication_input));

    match verdict {
        ObligationVerdict::Discharged => None,
        ObligationVerdict::Unsatisfied => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationUnprovable,
            target_symbol: target_symbol.to_string(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver reports `post_caller \u{2283} pre_callee` is violated for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus_json: None,
        }),
        ObligationVerdict::Undecidable | ObligationVerdict::Disagreement => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationUndecidable,
            target_symbol: target_symbol.to_string(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver could not decide `post_caller \u{2283} pre_callee` for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus_json: None,
        }),
        ObligationVerdict::SolverTimeout => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationSolverTimeout,
            target_symbol: target_symbol.to_string(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver exceeded host timeout while checking `post_caller \u{2283} pre_callee` for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus_json: None,
        }),
        // A refusal is distinct from "undecidable": there is no sound discharger
        // for this bridge's obligation (the precondition lowers to a construct the
        // solver cannot interpret). Surface it by its own honest name, not as an
        // undecidable gap.
        ObligationVerdict::Refused => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationRefused,
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

/// JCS-canonical bytes of a typed formula. Lowers the `IrFormula` to its
/// `{"kind":...}` JSON (byte-identical to the pre-typeify wire value) and runs
/// the same JCS canonicalizer, so equality checks against the old `Json` path
/// are bit-for-bit identical.
fn jcs_of_formula(f: &IrFormula) -> Vec<u8> {
    let json = serde_json::to_value(f).expect("IrFormula always serializes to JSON");
    jcs_of_json(&json)
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

    /// BYTE-IDENTITY GATE for the formula-typeify seam.
    ///
    /// Every `pre`/`post` formula reaching the linker is produced by
    /// `serde_json::to_value(&IrFormula)` upstream (e.g.
    /// `libsugar::core::bind::bind_function_bridge`), so its wire key order is
    /// the `IrFormula` declaration order. This test pins that round-tripping a
    /// representative set of those exact wire values through `Option<IrFormula>`
    /// (deserialize -> re-serialize) reproduces the bytes exactly. If a producer
    /// ever emits a formula IrFormula cannot represent, `from_value` fails here
    /// and the seam is reported as a mismatch rather than silently green.
    #[test]
    fn formula_typeify_is_byte_identical_on_the_wire() {
        // Exact `{"kind":...}` wire strings in IrFormula declaration order.
        let wire_forms = [
            r#"{"kind":"atomic","name":"true","args":[]}"#,
            r#"{"kind":"atomic","name":">","args":[{"kind":"var","name":"n"},{"kind":"const","value":0,"sort":{"kind":"primitive","name":"Int"}}]}"#,
            r#"{"kind":"and","operands":[{"kind":"atomic","name":">=","args":[{"kind":"var","name":"x"},{"kind":"const","value":1,"sort":{"kind":"primitive","name":"Int"}}]},{"kind":"atomic","name":"<","args":[{"kind":"var","name":"x"},{"kind":"const","value":9,"sort":{"kind":"primitive","name":"Int"}}]}]}"#,
            r#"{"kind":"implies","operands":[{"kind":"atomic","name":"true","args":[]},{"kind":"atomic","name":"true","args":[]}]}"#,
        ];
        for wire in wire_forms {
            let parsed: IrFormula =
                serde_json::from_str(wire).expect("wire formula must parse as IrFormula");
            let reserialized = serde_json::to_string(&parsed).expect("IrFormula serializes");
            assert_eq!(reserialized, wire, "IrFormula round-trip must be byte-identical");
        }
    }

    /// The obligation-typeify seam: the single [`Obligation`] value the linker
    /// checks lowers to the EXACT `{"kind":"implies","operands":[post,pre]}`
    /// JSON the SMT compiler consumed before this seam. This is both the term
    /// discharged and the term a future emit-side follow-up would mint into the
    /// bridge, so carried == checked is pinned to a byte string.
    #[test]
    fn obligation_lowers_to_the_exact_implies_wire() {
        let post: IrFormula =
            serde_json::from_str(r#"{"kind":"atomic","name":"true","args":[]}"#).unwrap();
        let pre: IrFormula =
            serde_json::from_str(r#"{"kind":"atomic","name":"true","args":[]}"#).unwrap();
        let obligation = Obligation::new(post, pre);
        let wire = serde_json::to_string(&obligation.as_implies()).unwrap();
        assert_eq!(
            wire,
            r#"{"kind":"implies","operands":[{"kind":"atomic","name":"true","args":[]},{"kind":"atomic","name":"true","args":[]}]}"#,
            "Obligation::as_implies must lower to the exact pre-seam implies term"
        );
    }

    /// [`ObligationState::derive`] maps the caller-post / callee-pre presence
    /// matrix onto the three discharge outcomes, preserving the historical
    /// precedence (caller-post-absent wins even when the callee pre is also
    /// absent).
    #[test]
    fn obligation_state_derive_matches_presence_matrix() {
        let f: IrFormula =
            serde_json::from_str(r#"{"kind":"atomic","name":"true","args":[]}"#).unwrap();

        assert!(matches!(
            ObligationState::derive(None, None),
            ObligationState::CallerPostAbsent
        ));
        assert!(matches!(
            ObligationState::derive(None, Some(&f)),
            ObligationState::CallerPostAbsent
        ));
        assert!(matches!(
            ObligationState::derive(Some(&f), None),
            ObligationState::VacuousPreAbsent
        ));
        assert!(matches!(
            ObligationState::derive(Some(&f), Some(&f)),
            ObligationState::Pending(_)
        ));
    }

    /// The `Option<IrFormula>` field itself must serialize/deserialize
    /// byte-identically inside a `LinkerContract` (the shape the linkerd R14
    /// snapshot persists), including the `None -> null` and present-formula
    /// cases.
    #[test]
    fn contract_formula_fields_roundtrip_in_snapshot_shape() {
        let contract = make_process_contract(); // pre: `n > 0`, post: None
        let bytes = serde_json::to_vec(&contract).expect("serialize contract");
        let restored: LinkerContract = serde_json::from_slice(&bytes).expect("deserialize contract");
        let rebytes = serde_json::to_vec(&restored).expect("re-serialize contract");
        assert_eq!(bytes, rebytes, "LinkerContract formula fields must round-trip byte-identically");
        assert_eq!(restored.pre_json, contract.pre_json);
        assert_eq!(restored.post_json, contract.post_json);
    }

    fn make_process_contract() -> LinkerContract {
        LinkerContract {
            name: "process".into(),
            kit: "rust-kit".into(),
            contract_cid: "blake3-512:aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001".into(),
            // A valid IrFormula pre (`n > 0`). It is inert in every test that
            // uses this fixture (each hits `unprovable-obligation` because the
            // caller post is absent, so this pre is never decoded, and the
            // pinned linkBundleCid derives from bridges, not contract formulas).
            pre_json: Some(
                serde_json::from_value(serde_json::json!({
                    "kind": "atomic",
                    "name": ">",
                    "args": [
                        {"kind": "var", "name": "n"},
                        {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                    ]
                }))
                .expect("valid IrFormula"),
            ),
            post_json: None,
            ..Default::default()
        }
    }

    fn make_go_caller_fail_contract() -> LinkerContract {
        LinkerContract {
            name: "GoCallerFail".into(),
            kit: "go-kit".into(),
            contract_cid: "blake3-512:ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002".into(),
            pre_json: None,
            post_json: None,
            ..Default::default()
        }
    }

    fn make_go_caller_ok_contract() -> LinkerContract {
        LinkerContract {
            name: "GoCallerOk".into(),
            kit: "go-kit".into(),
            contract_cid: "blake3-512:ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003".into(),
            pre_json: None,
            post_json: None,
            ..Default::default()
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
            ..Default::default()
        }
    }

    #[test]
    fn test_failure_case_emits_linker_error() {
        let output = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        });

        assert!(!output.linker_errors.is_empty());
        assert_eq!(
            output.linker_errors[0].kind.wire_str(),
            "unprovable-obligation"
        );
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

    // -----------------------------------------------------------------
    // Slice-1 teeth: the migrated resolve_target join, as typed edge
    // binding failures the linker now owns.
    // -----------------------------------------------------------------

    /// A `process` contract that exports the formal `n: Int`. Used as the
    /// resolved callee for the signature-mismatch tooth.
    fn make_process_contract_with_signature() -> LinkerContract {
        LinkerContract {
            formals: vec!["n".into()],
            formal_sorts: vec![serde_json::json!({"kind": "primitive", "name": "Int"})],
            ..make_process_contract()
        }
    }

    /// TOOTH: a planted signature mismatch — the call site imports `process`
    /// with formals `[n, extra]`, but the resolved contract exports only `[n]`.
    /// `bind` must refuse with the named `SignatureMismatch` error, and no
    /// bridge is minted for the edge.
    #[test]
    fn test_planted_signature_mismatch_is_named_linker_error() {
        let mut edge = make_cgo_call_edge(&make_go_caller_fail_contract());
        edge.import_signature = Some(ImportSignature {
            symbol: "rust-kit:process".into(),
            formals: vec!["n".into(), "extra".into()],
            sorts: vec![],
            euf_coordinate: None,
        });

        let output = link(LinkerInputs {
            contracts: vec![
                make_process_contract_with_signature(),
                make_go_caller_fail_contract(),
            ],
            call_edges: vec![edge],
        });

        let mismatch = output
            .linker_errors
            .iter()
            .find(|e| e.kind == LinkerErrorKind::SignatureMismatch)
            .expect("planted mismatch must surface as SignatureMismatch");
        assert_eq!(mismatch.kind.wire_str(), "signature-mismatch");
        assert_eq!(mismatch.target_symbol, "rust-kit:process");
        // No bridge for a mismatched edge: bind refused before derivation.
        let bridges = output
            .bundle_json
            .get("bridges")
            .unwrap()
            .as_array()
            .unwrap();
        assert!(
            bridges.is_empty(),
            "no bridge is minted for a mismatched edge"
        );
    }

    /// TOOTH: the polars `scalar_sum` call shape — an edge whose target symbol
    /// resolves to no member in the union. `bind` must refuse with the named
    /// `UnresolvedSymbol` (undefined-symbol) error.
    #[test]
    fn test_polars_scalar_sum_shape_is_undefined_symbol() {
        let caller = LinkerContract {
            name: "frame_pipeline".into(),
            kit: "polars-kit".into(),
            contract_cid: "blake3-512:1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111".into(),
            post_json: Some(
                serde_json::from_value(serde_json::json!({"kind": "atomic", "name": "true", "args": []}))
                    .expect("valid IrFormula"),
            ),
            ..Default::default()
        };
        let edge = LinkerCallEdge {
            source_contract_cid: caller.contract_cid.clone(),
            target_contract_cid: None,
            // No `polars-kit:scalar_sum` contract is present in the union.
            target_symbol: "polars-kit:scalar_sum".into(),
            call_site_locus_json: serde_json::json!({"file": "pipeline.py", "line": 3, "column": 5}),
            evidence_term_json: serde_json::json!({"kind": "Atomic", "name": "obligation", "args": []}),
            ..Default::default()
        };

        let output = link(LinkerInputs {
            contracts: vec![caller],
            call_edges: vec![edge],
        });

        let undefined = output
            .linker_errors
            .iter()
            .find(|e| e.kind == LinkerErrorKind::UnresolvedSymbol)
            .expect("scalar_sum must surface as UnresolvedSymbol");
        assert_eq!(undefined.kind.wire_str(), "unresolved-symbol");
        assert_eq!(undefined.target_symbol, "polars-kit:scalar_sum");
    }

    /// A `BoundContractCid` is only mintable by `bind`, and only from a
    /// contract that actually answered the edge — so its inner CID is never
    /// null. `bind`'s success carries the resolved CID; a bound edge with a
    /// null CID is unrepresentable (see `BoundContractCid`'s private field).
    #[test]
    fn test_bound_edge_cid_is_linker_minted_non_null() {
        let mut name_kit_index: BTreeMap<(String, String), String> = BTreeMap::new();
        let process = make_process_contract();
        name_kit_index.insert(
            ("process".into(), "rust-kit".into()),
            process.contract_cid.clone(),
        );
        let mut contracts_by_cid: BTreeMap<&str, &LinkerContract> = BTreeMap::new();
        contracts_by_cid.insert(process.contract_cid.as_str(), &process);

        let go = make_go_caller_fail_contract();
        let edge = make_cgo_call_edge(&go);
        let bound = bind(&edge, &name_kit_index, &contracts_by_cid)
            .expect("resolvable edge binds to a contract");
        // The minted CID is exactly the resolved contract's — never null.
        assert_eq!(bound.as_str(), process.contract_cid);
        assert!(!bound.as_str().is_empty());
    }
}
