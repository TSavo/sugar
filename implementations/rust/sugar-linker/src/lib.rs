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
use sugar_ir_types::{IrFormula, Sort};
use sugar_verifier::solvers::{run_plan, SolverHandle, SolverPlan, SolverSeat};
use sugar_verifier::types::ObligationVerdict;

/// The typed locus of a call site, per `ir-formal-grammar.md` (`Locus`).
///
/// Replaces the free-form `serde_json::Value` that the call-site slot used to
/// carry on [`LinkerCallEdge`] and [`LinkerError`]. The seam is byte-identical:
/// the linker embeds this locus into every bridge memento (see [`derive_bridge`])
/// and hashes it into `bridgeSetCid` / `linkBundleCid`, so its serialized shape
/// must reproduce the exact `{file, line, column}` object the linker previously
/// threaded through as raw JSON.
///
/// # Why a dedicated struct rather than the verifier's `SourceLocus`
///
/// The verifier's [`sugar_verifier::SourceLocus`] types `line` as a bare `usize`
/// and omits `column` when absent. The linker's callSiteLocus, however, carries
/// `line` and `col` straight from a lift memento where both are `Option` (see
/// `sugar_lift::CallSiteLocus`), and the daemon (`spawn_kit_lifter`) has always
/// serialized an absent line/column as an explicit `null` — a shape `SourceLocus`
/// cannot reproduce without changing bytes. `line`/`column` are therefore
/// `Option<usize>` here and serialize `None` as `null` (never skipped), matching
/// the pre-seam `serde_json::json!` output field-for-field.
///
/// # Field order is load-bearing
///
/// `bridgeSetCid` hashes each bridge memento via a non-canonical
/// `serde_json::to_string` (the `preserve_order` build keeps insertion order),
/// so the serialized key order of the embedded `callSite` object feeds a pinned
/// CID. Fields are declared in JCS-canonical (alphabetical) order —
/// `column, file, line` — the order the pinned baseline was minted with;
/// reordering them changes `linkBundleCid`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallSiteLocus {
    /// 1-based column, or `null` when the lifter had no span location. Named
    /// `column` (not `col`) to match the linker-side grammar object.
    pub column: Option<usize>,
    /// Source file the call site lives in.
    pub file: String,
    /// 1-based line, or `null` when the lifter had no span location.
    pub line: Option<usize>,
}

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

/// A cross-kit resolution symbol: the `<kit>:<name>` join key, as a type.
///
/// Replaces three flattened representations with one value whose `Ord` *is* the
/// join key: the `"<kit>:<name>"` `target_symbol` string on [`LinkerCallEdge`],
/// the `(name, kit)` tuple key of the linker's resolution index, and
/// [`ImportSignature`]'s `symbol` field. The split-on-`':'` string surgery that
/// `resolve_target_symbol` used to perform at resolution time now lives once
/// here, in [`Symbol::from_wire`], and resolution is a single `BTreeMap` lookup.
///
/// ## Wire byte-identity
///
/// A `Symbol` serializes to / deserializes from the exact `"<kit>:<name>"`
/// string it replaced (see the custom `Serialize`/`Deserialize` impls), so every
/// `targetSymbol` on the wire and in `callEdgeSetCid` is byte-for-byte
/// preserved. `kit` is an `Option` precisely to keep that identity total: an
/// *unqualified* symbol with no `':'` (real corpus forms like `"id"`,
/// `"witness"`, `"implication"`, `"encode_len"`) round-trips losslessly as
/// itself rather than gaining a spurious colon — a qualified symbol keeps its
/// `kit`, an unqualified one has `kit = None`. Unqualified or empty-part symbols
/// never match a contract-derived key (a contract always exports a non-empty kit
/// and name), so they surface as `unresolved-symbol` exactly as the old
/// `find(':')` guard did.
#[derive(Debug, Clone, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Symbol {
    /// The kit qualifier before the `':'`, or `None` for an unqualified symbol
    /// (a wire string with no colon).
    pub kit: Option<String>,
    /// The bare name after the `':'` (or the whole string when unqualified).
    pub name: String,
}

impl Symbol {
    /// The qualified `<kit>:<name>` join key a contract exports: the index-key
    /// side of the resolution join.
    fn qualified(kit: impl Into<String>, name: impl Into<String>) -> Self {
        Symbol {
            kit: Some(kit.into()),
            name: name.into(),
        }
    }

    /// Parse a wire `targetSymbol` string. The first `':'` splits kit from name
    /// (a name may itself contain colons); a string with no colon is an
    /// unqualified symbol (`kit = None`). Total and infallible: every wire string
    /// is a `Symbol`, and malformed ones simply fail to resolve — the same
    /// outcome the old `resolve_target_symbol` guard produced.
    fn from_wire(s: &str) -> Self {
        match s.find(':') {
            Some(pos) => Symbol {
                kit: Some(s[..pos].to_string()),
                name: s[pos + 1..].to_string(),
            },
            None => Symbol {
                kit: None,
                name: s.to_string(),
            },
        }
    }

    /// Render back to the exact `"<kit>:<name>"` wire string (or the bare name
    /// when unqualified). Inverse of [`Symbol::from_wire`] on every input.
    fn to_wire(&self) -> String {
        match &self.kit {
            Some(kit) => format!("{kit}:{}", self.name),
            None => self.name.clone(),
        }
    }
}

impl std::fmt::Display for Symbol {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.to_wire())
    }
}

impl From<&str> for Symbol {
    fn from(s: &str) -> Self {
        Symbol::from_wire(s)
    }
}

impl From<String> for Symbol {
    fn from(s: String) -> Self {
        Symbol::from_wire(&s)
    }
}

impl Serialize for Symbol {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_wire())
    }
}

impl<'de> Deserialize<'de> for Symbol {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        Ok(Symbol::from_wire(&s))
    }
}

/// A content-addressed identifier — the `"blake3-512:<hex>"` string, as a type.
///
/// Replaces the bare `String` that stood for a CID on every linker boundary:
/// [`LinkerContract::contract_cid`], the two [`LinkerCallEdge`] endpoints, and
/// the four [`LinkerOutput`] set-CIDs. It carries no derivation logic — the CID
/// is still computed as a `String` inside the derivation core and wrapped into a
/// `Cid` only at the [`LinkerOutput`] boundary — its job is to make "this string
/// is a CID" unforgeable at the type level so a raw symbol, kit name, or locus
/// string cannot land in a CID slot.
///
/// ## Wire byte-identity
///
/// `#[serde(transparent)]` means a `Cid` serializes to / deserializes from the
/// bare `"blake3-512:<hex>"` JSON string it replaced — no wrapper object, no key.
/// Every `contractCid` / `sourceContractCid` / `targetContractCid` /
/// `contractSetCid` / `callEdgeSetCid` / `bridgeSetCid` / `linkBundleCid` on the
/// wire (and thus every set-CID and `linkBundleCid` hash) is byte-for-byte
/// preserved. `Ord` is the inner-string order, so sorting call edges by
/// `source_contract_cid` produces the identical deterministic order the `String`
/// field did.
#[derive(Debug, Clone, Default, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Cid(String);

impl Cid {
    /// Borrow the underlying `"blake3-512:<hex>"` string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for Cid {
    fn from(s: String) -> Self {
        Cid(s)
    }
}

impl From<&str> for Cid {
    fn from(s: &str) -> Self {
        Cid(s.to_string())
    }
}

impl std::fmt::Display for Cid {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl AsRef<str> for Cid {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

/// The formals / sorts / EUF-coordinate triple a contract *exports* or a call
/// site *imports* — one type in two roles.
///
/// [`LinkerContract`] exports one (via [`LinkerContract::exported_signature`]);
/// an [`ImportSignature`] imports one (it flattens a `Signature` inline).
/// [`Signature::check`] is the single place the two are matched, replacing the
/// runtime formals/sorts/EUF kind-checks that verify used to re-derive. The
/// empty-vector refinement is preserved verbatim: a dimension the importer
/// leaves empty imposes no constraint, so pre-signature wire edges never
/// spuriously fail.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Signature {
    /// Formal parameter names, in order.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub formals: Vec<String>,
    /// Formal sorts, positionally aligned with `formals`, as strongly-typed
    /// [`Sort`]s. Retyped from `serde_json::Value` in the sort-typeify seam: the
    /// `{"kind":"primitive","name":...}` wire JSON is unchanged (`Sort` is
    /// `#[serde(tag = "kind")]` and serializes to the identical tagged object),
    /// so signature bytes and the linkBundleCid are byte-for-byte preserved.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub sorts: Vec<Sort>,
    /// EUF coordinate this signature answers to, if any.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub euf_coordinate: Option<String>,
}

impl Signature {
    /// Type-check this *imported* signature against an *exported* one. Only the
    /// dimensions the importer actually declares are constrained (the empty-vector
    /// refinement), so a signature that names no formals imposes no formal-arity
    /// constraint. `Err(reason)` names the first disagreement for a
    /// `signature-mismatch` [`LinkerError`]; the messages are byte-identical to
    /// the pre-hoist `ImportSignature::check` strings.
    fn check(&self, exported: &Signature) -> Result<(), String> {
        if !self.formals.is_empty() && self.formals != exported.formals {
            return Err(format!(
                "formals disagree: caller imports {:?}, callee exports {:?}",
                self.formals, exported.formals
            ));
        }
        if !self.sorts.is_empty() && self.sorts != exported.sorts {
            return Err(format!(
                "formal sorts disagree: caller imports {:?}, callee exports {:?}",
                self.sorts, exported.sorts
            ));
        }
        if let Some(coord) = &self.euf_coordinate {
            if exported.euf_coordinate.as_ref() != Some(coord) {
                return Err(format!(
                    "EUF coordinate disagrees: caller imports {:?}, callee exports {:?}",
                    Some(coord),
                    exported.euf_coordinate
                ));
            }
        }
        Ok(())
    }
}

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
    /// Content-addressed contract CID, `blake3-512:<hex>`, as a typed [`Cid`].
    /// `#[serde(transparent)]` keeps the wire value the bare CID string, so
    /// contract-set CIDs and snapshot bytes are byte-for-byte preserved.
    pub contract_cid: Cid,
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
    /// Declared formal sorts, positionally aligned with `formals`, as
    /// strongly-typed [`Sort`]s (adopted from `sugar-ir-types`). Retyped from
    /// `serde_json::Value` in the sort-typeify seam: the `{"kind":"primitive",
    /// "name":...}` wire JSON is unchanged (`Sort` is `#[serde(tag = "kind")]`
    /// and serializes to the identical tagged object), so contract CIDs and
    /// snapshot bytes are byte-for-byte preserved.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub formal_sorts: Vec<Sort>,
    /// EUF coordinate (the `enc#euf#c:...` segment) this contract answers to,
    /// if it is an EUF-callsite contract. `None` for ordinary contracts.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub euf_coordinate: Option<String>,
}

impl LinkerContract {
    /// The signature this contract *exports*, as the shared [`Signature`] type.
    ///
    /// The three wire fields (`formals` / `formal_sorts` / `euf_coordinate`) stay
    /// flat on `LinkerContract` for byte-identity (they keep their own wire keys —
    /// notably `formal_sorts`, which an [`ImportSignature`] spells `sorts`), while
    /// the resolution *algebra* is expressed once against [`Signature`]. This is
    /// the exported-role view a call site's imported signature is checked against.
    fn exported_signature(&self) -> Signature {
        Signature {
            formals: self.formals.clone(),
            sorts: self.formal_sorts.clone(),
            euf_coordinate: self.euf_coordinate.clone(),
        }
    }
}

/// A call edge emitted by a kit lifter.
///
/// Describes a call site where one contracted function calls another. Cross-kit
/// calls have `target_contract_cid: None` and `target_symbol` set to a
/// `"<kit>:<name>"` string for linker resolution.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct LinkerCallEdge {
    /// CID of the calling function's contract, as a typed [`Cid`].
    pub source_contract_cid: Cid,
    /// CID of the callee's contract if already known (same-kit call), or `None`
    /// for cross-kit calls where the linker must resolve `target_symbol`. The
    /// `Option` is the *unbound* null state (see [`BoundContractCid`]); when
    /// present it is a typed [`Cid`] that serializes to the bare CID string.
    pub target_contract_cid: Option<Cid>,
    /// Typed symbol for cross-kit resolution, e.g. `"rust-kit:process"`. Its
    /// `Ord` is the resolution join key; it serializes to / from the exact
    /// `"<kit>:<name>"` wire string (see [`Symbol`]).
    pub target_symbol: Symbol,
    /// Typed locus of the call site, per `ir-formal-grammar.md`. `None` when the
    /// owning kit emitted no `callSiteLocus` (the pre-seam `Json::Null` state);
    /// `skip_serializing_if` keeps that absence off the internal snapshot wire.
    /// This slot never reaches a pinned CID directly — the linker embeds it into
    /// each bridge memento (see [`derive_bridge`]) where JCS canonicalizes it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub call_site_locus: Option<CallSiteLocus>,
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
    /// `<kit>:<name>` symbol the call site imports, as the typed [`Symbol`]. Its
    /// `Ord` is the resolution join key; it serializes to / from the exact
    /// `"<kit>:<name>"` wire string.
    pub symbol: Symbol,
    /// The imported [`Signature`] — formals / sorts / EUF coordinate — flattened
    /// so the wire object keeps its byte-identical flat keys
    /// (`symbol` + `formals` / `sorts` / `euf_coordinate`), the exact shape the
    /// pre-hoist `ImportSignature` emitted. This makes the doc's own claim literal:
    /// `ImportSignature == Symbol + Signature`.
    #[serde(flatten)]
    pub signature: Signature,
}

impl ImportSignature {
    /// Type-check this declared import signature against a resolved contract's
    /// exported signature. `Ok(())` when they agree (a bound edge may be minted);
    /// `Err(reason)` names the disagreement for a `signature-mismatch`
    /// [`LinkerError`]. The check itself is a single [`Signature::check`] against
    /// the contract's [`exported signature`](LinkerContract::exported_signature),
    /// which owns the empty-vector refinement (a caller that names no formals
    /// imposes no formal-arity constraint, so pre-signature wire edges never
    /// spuriously fail).
    fn check(&self, target: &LinkerContract) -> Result<(), String> {
        self.signature.check(&target.exported_signature())
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
    /// `call_site_locus.file`; `None` if the edge carried no locus.
    pub file: Option<String>,
    /// Original call-site locus emitted by the owning kit, as the typed
    /// [`CallSiteLocus`]. Used by linkerd/LSP to place solver diagnostics at the
    /// source call expression. `None` when the edge carried no locus.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub call_site_locus: Option<CallSiteLocus>,
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

/// A content-addressed link bundle — the four set-CIDs plus the canonical
/// serialized bundle object, grouped as one typed value.
///
/// This is the typed view that replaces the four loose `Cid` fields and the
/// bare `bundle_json: Json` that previously sat flat on [`LinkerOutput`].
///
/// ## Wire byte-identity
///
/// [`link_bundle_cid`](LinkBundle::link_bundle_cid) is the `blake3-512` hash of
/// the JCS canonicalization of [`json`](LinkBundle::json) sans its own
/// `linkBundleCid` key, and the daemon / CLI serialize `json` verbatim to
/// `link-bundle.json`. The bundle bytes must therefore stay byte-for-byte
/// identical. That is why `json` is kept as the already-derived [`Json`] value
/// rather than a fully-typed struct: the typing is the *in-memory view* over the
/// bundle, and the hash / wire source stays the exact bytes the derivation core
/// built. Typing `json` into a struct would risk reordering keys and changing
/// the CID.
#[derive(Debug, Clone)]
pub struct LinkBundle {
    /// `blake3-512` CID of the sorted contract set, as a typed [`Cid`].
    pub contract_set_cid: Cid,
    /// `blake3-512` CID of the sorted call-edge set, as a typed [`Cid`].
    pub call_edge_set_cid: Cid,
    /// `blake3-512` CID of the derived bridge set, as a typed [`Cid`].
    pub bridge_set_cid: Cid,
    /// `blake3-512` CID of the full link bundle object, as a typed [`Cid`].
    pub link_bundle_cid: Cid,
    /// The full `LinkBundle` JSON object per spec R5, including `linkBundleCid`.
    /// Kept as the already-serialized value so the wire bytes (and thus every
    /// set-CID and the `linkBundleCid` hash) are byte-for-byte preserved.
    pub json: Json,
}

/// Output of a single `link()` invocation.
///
/// The [`bundle`](LinkerOutput::bundle) is the typed [`LinkBundle`]: its `json`
/// field is a `serde_json::Value` ready to be serialised and written to disk
/// (CLI) or returned as a `projectStatus` response (daemon), and its four
/// set-CIDs are the typed scalars extracted alongside it for convenience.
#[derive(Debug, Clone)]
pub struct LinkerOutput {
    /// The typed link bundle: four set-CIDs + the canonical serialized object.
    pub bundle: LinkBundle,
    /// Per-edge linker errors (unresolved symbols, unprovable obligations).
    /// Each error carries a `file` field for per-file LSP diagnostic mapping.
    pub linker_errors: Vec<LinkerError>,
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
    //   name_kit_index   : Symbol -> contract_cid   (cross-kit symbol join)
    //   contracts_by_cid : cid -> &LinkerContract     (member lookup)
    // The key is the typed [`Symbol`] whose `Ord` *is* the join key, replacing
    // the `(name, kit)` tuple. Resolution is now a single lookup against a
    // `Symbol` parsed from the edge's `target_symbol` (see [`bind`]); the
    // split-on-`':'` surgery moved into [`Symbol::from_wire`].
    let mut name_kit_index: BTreeMap<Symbol, String> = BTreeMap::new();
    let mut contracts_by_cid: BTreeMap<&str, &LinkerContract> = BTreeMap::new();
    for c in &all_contracts {
        name_kit_index.insert(
            Symbol::qualified(c.kit.clone(), c.name.clone()),
            c.contract_cid.as_str().to_string(),
        );
        contracts_by_cid.insert(c.contract_cid.as_str(), c);
    }

    // contractSetCid
    let mut all_contract_cids: Vec<String> = all_contracts
        .iter()
        .map(|c| c.contract_cid.as_str().to_string())
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
                // Deterministic tiebreak over the typed locus. The struct
                // serializes in a fixed field order, so this string is stable
                // for identical loci; it only orders edges sharing a source CID
                // and never enters a CID hash.
                serde_json::to_string(&a.call_site_locus)
                    .unwrap_or_default()
                    .cmp(&serde_json::to_string(&b.call_site_locus).unwrap_or_default())
            })
    });

    for edge in &sorted_edges {
        // Extract file from call-site locus for per-file diagnostics
        let locus_file = edge
            .call_site_locus
            .as_ref()
            .map(|l| l.file.clone());

        // bind: the sole minter of a `BoundContractCid`, with two outcomes —
        // the bound target, or the typed failure (undefined-symbol /
        // signature-mismatch). This is the migrated resolve_target join: the
        // string join and the member check that verify used to re-derive now
        // live in one constructor signature.
        let bound = match bind(edge, &name_kit_index, &contracts_by_cid) {
            Ok(bound) => bound,
            Err(mut err) => {
                err.file = locus_file;
                err.call_site_locus = edge.call_site_locus.clone();
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
            edge.source_contract_cid.as_str(),
            target_cid,
            &edge.call_site_locus,
            &edge.evidence_term_json,
        );
        let bridge = DerivedBridge {
            memento,
            obligation,
        };

        if let Some(mut err) = discharge_obligation(
            &bridge.obligation,
            edge.source_contract_cid.as_str(),
            target_cid,
            &edge.target_symbol,
            registry,
            plan,
        ) {
            err.file = locus_file;
            err.call_site_locus = edge.call_site_locus.clone();
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
                    "targetSymbol": e.target_symbol.to_wire(),
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

    // Wrap the internally-derived CID strings into typed `Cid`s at the output
    // boundary. Derivation stays `String` (the JCS/hash inputs above are
    // byte-identical); only the public field type strengthens.
    LinkerOutput {
        bundle: LinkBundle {
            contract_set_cid: contract_set_cid.into(),
            call_edge_set_cid: call_edge_set_cid.into(),
            bridge_set_cid: bridge_set_cid.into(),
            link_bundle_cid: link_bundle_cid.into(),
            json: bundle_json,
        },
        linker_errors: linker_errors_out,
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
            Some(cid) => EdgeTarget::Bound(cid.as_str()),
            None => EdgeTarget::Unbound(self.import_signature.clone().unwrap_or_else(|| {
                ImportSignature {
                    symbol: self.target_symbol.clone(),
                    signature: Signature::default(),
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
    name_kit_index: &BTreeMap<Symbol, String>,
    contracts_by_cid: &BTreeMap<&str, &LinkerContract>,
) -> Result<BoundContractCid, LinkerError> {
    let undefined = || LinkerError {
        kind: LinkerErrorKind::UnresolvedSymbol,
        target_symbol: edge.target_symbol.to_wire(),
        source_contract_cid: edge.source_contract_cid.as_str().to_string(),
        reason: format!(
            "targetSymbol `{}` did not resolve to any contract in the union",
            edge.target_symbol
        ),
        file: None,
        call_site_locus: None,
    };

    // Resolve to a candidate CID: the kit's claim, else the cross-kit symbol
    // join — now a single `Symbol` lookup (the split-on-`':'` lives in
    // [`Symbol::from_wire`]). A symbol that resolves to nothing is undefined,
    // including any unqualified or empty-part symbol, which never keys a
    // contract-derived entry.
    let cid: String = match edge.edge_target() {
        EdgeTarget::Bound(cid) => cid.to_string(),
        EdgeTarget::Unbound(sig) => {
            name_kit_index.get(&sig.symbol).cloned().ok_or_else(undefined)?
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
                target_symbol: edge.target_symbol.to_wire(),
                source_contract_cid: edge.source_contract_cid.as_str().to_string(),
                reason: format!(
                    "import signature for `{}` does not match contract {}: {reason}",
                    edge.target_symbol, cid
                ),
                file: None,
                call_site_locus: None,
            });
        }
    }

    Ok(BoundContractCid(cid))
}

// -------------------------------------------------------------------
// Cross-kit symbol resolution (R3)
// -------------------------------------------------------------------
//
// Resolution is now a single `name_kit_index.get(&Symbol)` lookup inside
// [`bind`]; the former `resolve_target_symbol` split-on-`':'` string surgery
// moved into [`Symbol::from_wire`], the sole place a wire `targetSymbol` is
// parsed. An unqualified (`kit = None`) or empty-part symbol keys no
// contract-derived entry, so it resolves to `unresolved-symbol` exactly as the
// old `find(':')` / non-empty guard did.

// -------------------------------------------------------------------
// Bridge derivation (R2)
// -------------------------------------------------------------------

fn derive_bridge(
    source_contract_cid: &str,
    target_contract_cid: &str,
    call_site_locus: &Option<CallSiteLocus>,
    evidence_term: &Json,
) -> Json {
    // Lower the typed locus back to the exact JSON it replaced: `None` -> `null`
    // (the pre-seam `Json::Null`), `Some` -> the `{column,file,line}` object.
    // The bridge is JCS-canonicalized for `bridgeSetCid` / `linkBundleCid`, so
    // this embedding is byte-identical to the old free-form `Json` slot.
    let call_site_locus = serde_json::to_value(call_site_locus).unwrap_or(Json::Null);
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
    target_symbol: &Symbol,
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
                target_symbol: target_symbol.to_wire(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "caller post-condition is absent; cannot discharge `post_caller \u{2283} pre_callee` for target `{target_cid}`"
                ),
                file: None, // populated by caller from locus
                call_site_locus: None, // populated by caller from locus
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
                target_symbol: target_symbol.to_wire(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "decode post-implies-pre ProofIR failed for target `{target_cid}`: {}",
                    error.payload
                ),
                file: None,
                call_site_locus: None,
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
                target_symbol: target_symbol.to_wire(),
                source_contract_cid: source_contract_cid.to_string(),
                reason: format!(
                    "compile post-implies-pre to SMT-LIB failed for target `{target_cid}`: {e}"
                ),
                file: None,
                call_site_locus: None,
            });
        }
    };

    let (verdict, reason, _invs) = run_plan(plan, registry, &smt_script, Some(&implication_input));

    match verdict {
        ObligationVerdict::Discharged => None,
        ObligationVerdict::Unsatisfied => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationUnprovable,
            target_symbol: target_symbol.to_wire(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver reports `post_caller \u{2283} pre_callee` is violated for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus: None,
        }),
        ObligationVerdict::Undecidable | ObligationVerdict::Disagreement => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationUndecidable,
            target_symbol: target_symbol.to_wire(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver could not decide `post_caller \u{2283} pre_callee` for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus: None,
        }),
        ObligationVerdict::SolverTimeout => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationSolverTimeout,
            target_symbol: target_symbol.to_wire(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "solver exceeded host timeout while checking `post_caller \u{2283} pre_callee` for target `{target_cid}`: {reason}"
            ),
            file: None,
            call_site_locus: None,
        }),
        // A refusal is distinct from "undecidable": there is no sound discharger
        // for this bridge's obligation (the precondition lowers to a construct the
        // solver cannot interpret). Surface it by its own honest name, not as an
        // undecidable gap.
        ObligationVerdict::Refused => Some(LinkerError {
            kind: LinkerErrorKind::ImplicationRefused,
            target_symbol: target_symbol.to_wire(),
            source_contract_cid: source_contract_cid.to_string(),
            reason: format!(
                "no sound discharger for `post_caller \u{2283} pre_callee` on target `{target_cid}`; refused, not guessed: {reason}"
            ),
            file: None,
            call_site_locus: None,
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

    /// BYTE-IDENTITY GATE for the Symbol seam. A `Symbol` round-trips every
    /// `targetSymbol` wire string — qualified, unqualified (no colon),
    /// multi-colon, and empty-part — byte-for-byte through both the
    /// parse/render pair and serde. The no-colon forms (`id`, `witness`,
    /// `implication`, `encode_len`) are real corpus symbols; `kit: Option` is
    /// exactly what keeps them lossless (they would otherwise gain a spurious
    /// colon and change `callEdgeSetCid`).
    #[test]
    fn symbol_wire_is_byte_identical_roundtrip() {
        for wire in [
            "rust-kit:process",
            "call:numpy.asarray",
            "method:checked_add",
            "a:b:c",
            "id",
            "witness",
            "implication",
            "encode_len",
            ":leading",
            "trailing:",
        ] {
            assert_eq!(
                Symbol::from_wire(wire).to_wire(),
                wire,
                "Symbol::to_wire must invert from_wire on `{wire}`"
            );
            // Same string, through serde as a JSON string literal.
            let json = serde_json::to_string(wire).unwrap();
            let sym: Symbol = serde_json::from_str(&json).unwrap();
            let back = serde_json::to_string(&sym).unwrap();
            assert_eq!(
                back, json,
                "Symbol serde round-trip must be byte-identical on `{wire}`"
            );
        }
    }

    /// BYTE-IDENTITY GATE for the `Cid` seam. A `Cid` (`#[serde(transparent)]`)
    /// round-trips every CID wire string byte-for-byte as the bare JSON string it
    /// replaced — standalone, inside `Option` (the `None -> null` / `Some -> string`
    /// endpoint states), and flattened inside a `LinkerContract`/`LinkerCallEdge`
    /// where the `contractCid` / `sourceContractCid` / `targetContractCid` keys
    /// carry the raw CID with no wrapper object. If the newtype ever gained a
    /// wrapper, this pins the drift rather than letting a set-CID silently shift.
    #[test]
    fn cid_wire_is_byte_identical_roundtrip() {
        // Standalone: a `Cid` serializes to / from the bare CID string literal.
        for wire in [
            r#""blake3-512:aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001""#,
            r#""blake3-512:0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000""#,
        ] {
            let cid: Cid = serde_json::from_str(wire).expect("Cid must parse from bare string");
            let back = serde_json::to_string(&cid).expect("Cid serializes");
            assert_eq!(back, wire, "Cid serde round-trip must be byte-identical on `{wire}`");
        }

        // Inside `Option`: both endpoint states are byte-identical to `Option<String>`.
        let some_wire = r#""blake3-512:deadbeef""#;
        let some: Option<Cid> = serde_json::from_str(some_wire).unwrap();
        assert_eq!(serde_json::to_string(&some).unwrap(), some_wire);
        let none: Option<Cid> = serde_json::from_str("null").unwrap();
        assert_eq!(serde_json::to_string(&none).unwrap(), "null");

        // Flattened in a `LinkerCallEdge`: `sourceContractCid` carries the raw CID
        // string and `targetContractCid: null` stays a bare null, exactly as the
        // pre-seam `String` / `Option<String>` fields serialized.
        let edge = LinkerCallEdge {
            source_contract_cid: "blake3-512:aaaa".into(),
            target_contract_cid: None,
            target_symbol: "rust-kit:process".into(),
            ..Default::default()
        };
        let v = serde_json::to_value(&edge).unwrap();
        assert_eq!(v["source_contract_cid"], serde_json::json!("blake3-512:aaaa"));
        assert!(v["target_contract_cid"].is_null());
        // And a round-trip through the struct reproduces the typed value.
        let back: LinkerCallEdge = serde_json::from_value(v).unwrap();
        assert_eq!(back.source_contract_cid.as_str(), "blake3-512:aaaa");
        assert!(back.target_contract_cid.is_none());
    }

    /// Byte-identity gate for the [`CallSiteLocus`] seam: the typed locus must
    /// produce the exact same JCS bytes the free-form `{column,file,line}` Json
    /// object did, since that object is embedded into every bridge memento and
    /// hashed into `bridgeSetCid` / `linkBundleCid`.
    #[test]
    fn call_site_locus_wire_is_byte_identical_roundtrip() {
        // JCS of the typed locus == JCS of the raw grammar object.
        let raw = serde_json::json!({
            "column": 9,
            "file": "examples/polyglot-rust-go/go-caller/caller_fail.go",
            "line": 21
        });
        let typed = CallSiteLocus {
            file: "examples/polyglot-rust-go/go-caller/caller_fail.go".into(),
            line: Some(21),
            column: Some(9),
        };
        let typed_json = serde_json::to_value(&typed).unwrap();
        assert_eq!(
            jcs_of_json(&typed_json),
            jcs_of_json(&raw),
            "typed locus must canonicalize to the same JCS bytes as the raw object"
        );
        // And it round-trips back through the struct unchanged.
        let back: CallSiteLocus = serde_json::from_value(raw).unwrap();
        assert_eq!(back, typed);

        // An unlocated locus (the lifter's `line: None` / `col: None` state) keeps
        // both keys as explicit `null` — never dropped — byte-matching the
        // pre-seam `serde_json::json!` the daemon emitted from `Option<u32>`.
        let unlocated = CallSiteLocus {
            file: "pipeline.py".into(),
            line: None,
            column: None,
        };
        assert_eq!(
            serde_json::to_value(&unlocated).unwrap(),
            serde_json::json!({"file": "pipeline.py", "line": null, "column": null})
        );
        let back_unlocated: CallSiteLocus =
            serde_json::from_value(serde_json::json!({
                "file": "pipeline.py",
                "line": null,
                "column": null
            }))
            .unwrap();
        assert_eq!(back_unlocated, unlocated);

        // Absence is preserved: `None` embeds as `null` (the pre-seam
        // `Json::Null`), `Some` as the object, exactly as `derive_bridge` needs.
        let none: Option<CallSiteLocus> = None;
        assert!(serde_json::to_value(&none).unwrap().is_null());
        let some = Some(typed.clone());
        assert_eq!(serde_json::to_value(&some).unwrap(), typed_json);

        // On a `LinkerCallEdge`, an absent locus stays off the wire (skip) and
        // round-trips to `None`; a present one round-trips byte-for-byte.
        let edge = LinkerCallEdge {
            source_contract_cid: "blake3-512:aaaa".into(),
            call_site_locus: Some(typed.clone()),
            ..Default::default()
        };
        let ev = serde_json::to_value(&edge).unwrap();
        assert_eq!(jcs_of_json(&ev["call_site_locus"]), jcs_of_json(&typed_json));
        let back_edge: LinkerCallEdge = serde_json::from_value(ev).unwrap();
        assert_eq!(back_edge.call_site_locus, Some(typed));

        let bare = LinkerCallEdge {
            source_contract_cid: "blake3-512:aaaa".into(),
            ..Default::default()
        };
        let bv = serde_json::to_value(&bare).unwrap();
        assert!(
            bv.get("call_site_locus").is_none(),
            "absent locus must be skipped, not serialized as null"
        );
        let back_bare: LinkerCallEdge = serde_json::from_value(bv).unwrap();
        assert!(back_bare.call_site_locus.is_none());
    }

    /// Unqualified / empty-part symbols resolve to nothing, exactly as the old
    /// `resolve_target_symbol` `find(':')` + non-empty guard did: they key no
    /// contract-derived entry in the `Symbol`-keyed index.
    #[test]
    fn unqualified_and_empty_part_symbols_never_resolve() {
        let mut index: BTreeMap<Symbol, String> = BTreeMap::new();
        index.insert(Symbol::qualified("rust-kit", "process"), "cid".into());
        // Qualified, present.
        assert_eq!(
            index.get(&Symbol::from_wire("rust-kit:process")).cloned(),
            Some("cid".to_string())
        );
        // No colon, empty kit, empty name: all miss.
        for miss in ["process", "rust-kit", ":process", "rust-kit:", "id"] {
            assert!(
                index.get(&Symbol::from_wire(miss)).is_none(),
                "`{miss}` must not resolve"
            );
        }
    }

    /// BYTE-IDENTITY GATE for the Signature-hoist seam: `ImportSignature` still
    /// serializes as the flat `{symbol, formals, sorts, euf_coordinate}` object,
    /// with the empty-dimension fields skipped, even though `Signature` is now
    /// `#[serde(flatten)]`ed inside it.
    #[test]
    fn import_signature_flat_wire_is_byte_identical() {
        let wire = r#"{"symbol":"rust-kit:process","formals":["n"],"sorts":[{"kind":"primitive","name":"Int"}],"euf_coordinate":"enc#euf#c:0"}"#;
        let parsed: ImportSignature =
            serde_json::from_str(wire).expect("ImportSignature must parse");
        let back = serde_json::to_string(&parsed).expect("ImportSignature serializes");
        assert_eq!(back, wire, "ImportSignature flat wire must be byte-identical");

        // Symbol-only: the flattened Signature's skip_serializing_if omits every
        // empty dimension, so the object is exactly `{"symbol":...}`.
        let wire_min = r#"{"symbol":"rust-kit:process"}"#;
        let parsed_min: ImportSignature =
            serde_json::from_str(wire_min).expect("symbol-only ImportSignature must parse");
        let back_min = serde_json::to_string(&parsed_min).expect("serializes");
        assert_eq!(
            back_min, wire_min,
            "symbol-only ImportSignature must omit empty signature fields"
        );
    }

    /// The sort-typeify seam: `formal_sorts` / `Signature::sorts` are typed
    /// [`Sort`]s, but the element wire JSON is byte-identical to the pre-seam
    /// `{"kind":"primitive","name":"Int"}` object, and the check compares
    /// `Sort == Sort` rather than `Json == Json`.
    #[test]
    fn formal_sorts_typeify_is_byte_identical_on_the_wire() {
        // A single Sort element round-trips to the exact tagged wire object.
        let sort_wire = r#"{"kind":"primitive","name":"Int"}"#;
        let parsed: Sort = serde_json::from_str(sort_wire).expect("Sort must parse");
        assert_eq!(parsed, Sort::Primitive { name: "Int".into() });
        let back = serde_json::to_string(&parsed).expect("Sort serializes");
        assert_eq!(back, sort_wire, "Sort element wire must be byte-identical");

        // A LinkerContract carrying formal_sorts round-trips byte-for-byte, and
        // the empty-vector default is still omitted.
        let contract_wire = r#"{"name":"process","kit":"rust-kit","contract_cid":"blake3-512:00","pre_json":null,"post_json":null,"formals":["n"],"formal_sorts":[{"kind":"primitive","name":"Int"}]}"#;
        let contract: LinkerContract =
            serde_json::from_str(contract_wire).expect("LinkerContract must parse");
        assert_eq!(
            contract.formal_sorts,
            vec![Sort::Primitive { name: "Int".into() }]
        );
        let back = serde_json::to_string(&contract).expect("LinkerContract serializes");
        assert_eq!(
            back, contract_wire,
            "LinkerContract formal_sorts wire must be byte-identical"
        );

        // The check compares typed Sorts: agreeing sorts pass, disagreeing fail.
        let exported = Signature {
            formals: vec!["n".into()],
            sorts: vec![Sort::Primitive { name: "Int".into() }],
            euf_coordinate: None,
        };
        let agree = Signature {
            sorts: vec![Sort::Primitive { name: "Int".into() }],
            ..Default::default()
        };
        assert!(agree.check(&exported).is_ok(), "matching Sorts must check");
        let disagree = Signature {
            sorts: vec![Sort::Primitive {
                name: "String".into(),
            }],
            ..Default::default()
        };
        assert!(
            disagree.check(&exported).is_err(),
            "disagreeing Sorts must fail the check"
        );
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
            call_site_locus: Some(CallSiteLocus {
                file: "examples/polyglot-rust-go/go-caller/caller_fail.go".into(),
                line: Some(21),
                column: Some(9),
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
        assert!(output
            .bundle
            .link_bundle_cid
            .as_str()
            .starts_with("blake3-512:"));

        eprintln!(
            "failure-case linkBundleCid = {}",
            output.bundle.link_bundle_cid
        );
    }

    #[test]
    fn test_success_case_clean_bundle() {
        let output = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_ok_contract()],
            call_edges: vec![],
        });

        assert!(output.linker_errors.is_empty());
        assert!(output
            .bundle
            .link_bundle_cid
            .as_str()
            .starts_with("blake3-512:"));

        eprintln!(
            "success-case linkBundleCid = {}",
            output.bundle.link_bundle_cid
        );
    }

    #[test]
    fn test_byte_determinism() {
        let inputs = LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        };
        let out1 = link(inputs.clone());
        let out2 = link(inputs);
        assert_eq!(out1.bundle.link_bundle_cid, out2.bundle.link_bundle_cid);
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
        assert_ne!(
            fail_out.bundle.link_bundle_cid,
            ok_out.bundle.link_bundle_cid
        );
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
            fail_out.bundle.link_bundle_cid.as_str(),
            "blake3-512:a0d04917ab46f58662b4f497a779cab8c2814df0bb40c8df0cb1b6abfe1eaabe7500f638249d423e4d74648add1ce5d47fd9502cd5481a9012807bba50aec584",
            "failure-case linkBundleCid must match baseline from PR #124 smoke test"
        );
        assert_eq!(
            ok_out.bundle.link_bundle_cid.as_str(),
            "blake3-512:31fab69f197f4b279594972e35de7844f954a98ddce44b35edd14b77f53bd2ddb8ce95511bbef00f15476cc2f75f998ac4e419e5fe2c2162c008ba1c7c925131",
            "success-case linkBundleCid must match baseline from PR #124 smoke test"
        );
    }

    /// Wire round-trip for the [`LinkBundle`] typed view: each of the four typed
    /// `Cid` fields must equal, byte-for-byte, the corresponding string on the
    /// serialized `json`, and the `json` must survive a serialize → parse round
    /// trip unchanged. This pins that typing the four CIDs did NOT drift the view
    /// off the wire bytes the `linkBundleCid` hashes — the typed scalars are a
    /// faithful projection of the same object written to `link-bundle.json`.
    #[test]
    fn test_link_bundle_typed_view_matches_wire() {
        let output = link(LinkerInputs {
            contracts: vec![make_process_contract(), make_go_caller_fail_contract()],
            call_edges: vec![make_cgo_call_edge(&make_go_caller_fail_contract())],
        });
        let bundle = &output.bundle;

        // Each typed Cid is exactly the wire string on the serialized object.
        let wire = |k: &str| bundle.json.get(k).and_then(|v| v.as_str()).unwrap();
        assert_eq!(bundle.contract_set_cid.as_str(), wire("contractSetCid"));
        assert_eq!(bundle.call_edge_set_cid.as_str(), wire("callEdgeSetCid"));
        assert_eq!(bundle.bridge_set_cid.as_str(), wire("bridgeSetCid"));
        assert_eq!(bundle.link_bundle_cid.as_str(), wire("linkBundleCid"));

        // The bundle json survives a serialize -> parse round trip byte-identically.
        let serialized = serde_json::to_string(&bundle.json).expect("serialize bundle json");
        let reparsed: Json = serde_json::from_str(&serialized).expect("parse bundle json");
        assert_eq!(reparsed, bundle.json, "bundle json must round-trip unchanged");
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
            formal_sorts: vec![Sort::Primitive { name: "Int".into() }],
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
            signature: Signature {
                formals: vec!["n".into(), "extra".into()],
                sorts: vec![],
                euf_coordinate: None,
            },
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
            .bundle
            .json
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
            call_site_locus: Some(CallSiteLocus {
                file: "pipeline.py".into(),
                line: Some(3),
                column: Some(5),
            }),
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
        let mut name_kit_index: BTreeMap<Symbol, String> = BTreeMap::new();
        let process = make_process_contract();
        name_kit_index.insert(
            Symbol::qualified("rust-kit", "process"),
            process.contract_cid.as_str().to_string(),
        );
        let mut contracts_by_cid: BTreeMap<&str, &LinkerContract> = BTreeMap::new();
        contracts_by_cid.insert(process.contract_cid.as_str(), &process);

        let go = make_go_caller_fail_contract();
        let edge = make_cgo_call_edge(&go);
        let bound = bind(&edge, &name_kit_index, &contracts_by_cid)
            .expect("resolvable edge binds to a contract");
        // The minted CID is exactly the resolved contract's — never null.
        assert_eq!(bound.as_str(), process.contract_cid.as_str());
        assert!(!bound.as_str().is_empty());
    }
}
