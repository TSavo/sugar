// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Part 6, Phases 1+2 of the compiler-shape plan
// (`~/.claude/plans/sugar-compiler-liftshift.md`): the strongly-typed
// navigable tree over a kit's project, and the ONE wire method
// (`sugar.enumerate`) that drives it.
//
// Every node is a lazy cursor: it holds enough to reach the SAME
// already-rendezvous'd kit process again (a `KitConn`, mirroring the exact
// spawn-per-call membrane `resolve.rs`'s `resolve_source`/`resolve_testimony`
// already use -- no second transport invented) plus its own
// `SourceMemento` locator (the tree's primary key, per the plan's "locator
// design" section: every node the factory builds is built FROM a fragment,
// and the memento is that fragment's durable, CID-pinned address). No node
// holds a `serde_json::Value`.
//
// LOCATOR (#3809 T correction): every navigable node is self-locating via
// its [`SourceMemento`] (`file` + `function_name` + `span` + CIDs). Nesting
// `file → fn → site → assertion → fact` is the *enumeration structure*
// (parent enumerates children), not a second address type. A prior
// `MementoPath` / `SourceMementoAtPath` layer re-encoded memento fields and
// was collapsed — SourceMemento is already the strong type.
// Factory 1:1: site ≡ assertion ≡ fact share one kind=contract memento.
// Fragment stays LOCAL (kit/oracle); memento (CID + locus) crosses the wire.
//
// GRANULARITY: `Function::call_sites` is span-scoped when the parent function
// memento carries a non-degenerate span; otherwise name-scoped (degenerate
// file/fn locators). Same-named nested functions with distinct spans no longer
// cross-contaminate.
//
// CLAIM vs OBLIGATION (plan's "two halves meeting at the callsite"):
// `universe`/`assertions`/`facts` are the claim side, kit-enumerated over
// the wire (`universe` joins function-contract rows by bridgeSourceSymbol).
// `contract`/`implication` are LINK-time (#3831) -- this pass lands them
// as `EdgeTarget::Unbound`/`None` stubs; no RPC is made for them, since
// binding them is a `solve()`-time concern (SEAM 5), out of scope here.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sugar_ir_types::{IrFormula, Sort};
use sugar_linker::LinkerContract;
use sugar_walk::source_oracle::{SourceMemento, SrcSpan};

use crate::kit::{Kit, KitError};
use crate::kit_path::LiftTermTable;

/// On-demand human-readable locus from a self-locating [`SourceMemento`].
/// Not a primary key and not stored — file/function_name/span/CIDs already
/// answer where. Nesting lives in the enumeration tree, not here.
pub fn memento_locus_display(m: &SourceMemento) -> String {
    let mut s = m.file.clone();
    let name = m
        .source_function_name()
        .filter(|n| !n.is_empty())
        .unwrap_or(m.function_name.as_str());
    if !name.is_empty() {
        s.push('[');
        s.push_str(name);
        if !span_is_degenerate(&m.span) {
            s.push('@');
            s.push_str(&span_display(&m.span));
        }
        s.push(']');
    }
    s
}

fn span_is_degenerate(span: &SrcSpan) -> bool {
    span.start_line == 0 && span.start_col == 0 && span.end_line == 0 && span.end_col == 0
}

fn span_display(span: &SrcSpan) -> String {
    format!(
        "{}:{}-{}:{}",
        span.start_line, span.start_col, span.end_line, span.end_col
    )
}

/// True when `inner` lies within `outer` (line-span containment).
/// Degenerate outer/inner → false (caller falls back to name scoping).
fn span_contains(outer: &SrcSpan, inner: &SrcSpan) -> bool {
    if span_is_degenerate(outer) || span_is_degenerate(inner) {
        return false;
    }
    let outer_start = (outer.start_line, outer.start_col);
    let outer_end = (outer.end_line, outer.end_col);
    let inner_start = (inner.start_line, inner.start_col);
    let inner_end = (inner.end_line, inner.end_col);
    inner_start >= outer_start && inner_end <= outer_end
}

/// The enumeration levels `sugar.enumerate` answers. Wire value is the
/// snake_case name in the protocol spec
/// (`protocol/specs/2026-07-08-enumeration-protocol.md`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Level {
    SourceFiles,
    Functions,
    CallSites,
    Assertions,
    Facts,
    Universe,
    Implications,
    Exports,
}

impl Level {
    fn wire(self) -> &'static str {
        match self {
            Level::SourceFiles => "source_files",
            Level::Functions => "functions",
            Level::CallSites => "call_sites",
            Level::Assertions => "assertions",
            Level::Facts => "facts",
            Level::Universe => "universe",
            Level::Implications => "implications",
            Level::Exports => "exports",
        }
    }
}

/// Everything an enumeration RPC needs to reach the SAME kit again: the
/// manifest's command/working_dir (mirroring `resolve_source`'s
/// `plugin_name`/`command`/`working_dir` triple) plus the project root
/// being enumerated. `Kit` does not keep a persistent child alive across
/// calls today (see `kit.rs`'s POOL DUALITY note) -- enumeration spawns
/// fresh per call against the same manifest, exactly as `resolve_testimony`
/// and `resolve_source` already do; this is the SAME membrane, not a
/// second one.
#[derive(Debug, Clone)]
pub struct KitConn {
    pub surface: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub workspace_root: PathBuf,
    pub audit_frontier: bool,
    pub allowed_broken_components: Vec<String>,
    pub transport: crate::kit_path::LiftPluginKit,
}

impl PartialEq for KitConn {
    fn eq(&self, other: &Self) -> bool {
        self.surface == other.surface
            && self.command == other.command
            && self.working_dir == other.working_dir
            && self.workspace_root == other.workspace_root
            && self.audit_frontier == other.audit_frontier
            && self.allowed_broken_components == other.allowed_broken_components
    }
}

impl Eq for KitConn {}

/// Failures from one `sugar.enumerate` RPC step. Folded into `KitError` via
/// `KitError::Enumerate` (extends the existing enum per the brief, rather
/// than inventing a parallel error surface every accessor must know about).
#[derive(Debug, thiserror::Error)]
pub enum EnumerateError {
    #[error("enumeration kit `{plugin}` returned a malformed node: {reason}")]
    MalformedNode { plugin: String, reason: String },
    #[error("enumeration kit `{plugin}` unavailable: {reason}")]
    Unavailable { plugin: String, reason: String },
    #[error("enumeration kit `{plugin}` stdin unavailable")]
    StdinUnavailable { plugin: String },
    #[error("enumeration kit `{plugin}` stdout unavailable")]
    StdoutUnavailable { plugin: String },
    #[error("write sugar.enumerate request to `{plugin}`: {source}")]
    Write {
        plugin: String,
        #[source]
        source: std::io::Error,
    },
    #[error("read sugar.enumerate response from `{plugin}`: {source}")]
    Read {
        plugin: String,
        #[source]
        source: std::io::Error,
    },
    #[error("sugar.enumerate response from `{plugin}` not valid JSON: {source}; raw={raw}")]
    InvalidJson {
        plugin: String,
        #[source]
        source: serde_json::Error,
        raw: String,
    },
    #[error("sugar.enumerate kit `{plugin}` error: {error}")]
    RpcError { plugin: String, error: Value },
    #[error("sugar.enumerate response from `{plugin}` malformed: {reason}")]
    Malformed { plugin: String, reason: String },
    /// A singular seek (`Kit::source_file`, `SourceFile::function`, ...)
    /// found no matching node -- distinct from a wire/decode failure.
    #[error(
        "sugar.enumerate seek on `{plugin}` at level `{level}` found no node for the given memento"
    )]
    SeekMiss { plugin: String, level: &'static str },
    /// `universe()`/`implication()`-style claim data the current kit-side
    /// factory audit does not expose as its own level (see module doc's
    /// GRANULARITY note): a real, reportable gap rather than a silent
    /// empty success.
    #[error("`{level}` is not yet served by `{plugin}`: {reason}")]
    NotModeled {
        plugin: String,
        level: &'static str,
        reason: String,
    },
}

/// A first-class gap: per the plan's "GAPS ARE NODES", enumeration
/// responses carry gaps in the SAME address space as built nodes, not a
/// silently-dropped remainder. `memento` is `None` only when the kit could
/// not even echo back a locator for the gap (malformed request-side
/// memento).
#[derive(Debug, Clone, PartialEq)]
pub struct GapInfo {
    pub memento: Option<SourceMemento>,
    pub reason: String,
}

/// The claim/obligation split's obligation-side binding state
/// (`CallSite::contract()`). `Bound` is never populated by this pass (see
/// module doc) -- kept as the plan's named shape so `solve()` (SEAM 5) has
/// somewhere to attach without a second type appearing later.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EdgeTarget<T> {
    Unbound,
    Bound(T),
}

/// Placeholder obligation-side nouns (link-time, #3831). Not populated by
/// this pass; kept as concrete named types per the plan's Part 0/Part 6
/// shape rather than a bare `()` so the eventual SEAM 5 wiring has a real
/// target.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Contract {
    pub name: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Implication {
    memento: SourceMemento,
    surface: String,
    audit: Value,
    payload: Option<Value>,
}

impl Sourced for Implication {
    fn source_memento(&self) -> &SourceMemento {
        &self.memento
    }
}

impl Implication {
    pub fn audit_row(&self) -> &Value {
        &self.audit
    }

    pub fn payload(&self) -> Option<&Value> {
        self.payload.as_ref()
    }

    /// Report transcript row keyed by the call-site demand owner. The audit
    /// alone is not a question identity: distinct call sites can ask the same
    /// caller/callee implication and legitimately carry byte-identical audits.
    pub fn report_row(&self) -> Value {
        let mut row = self.audit.clone();
        let object = row.as_object_mut().unwrap_or_else(|| {
            panic!("implication audit testimony must be an object before report transport")
        });
        let call_site = self.memento.to_json();
        object.insert("callSiteMemento".to_string(), call_site.clone());
        object.insert(
            "questionIdentity".to_string(),
            json!({
                "surface": self.surface,
                "level": "implications",
                "at": call_site,
                "seek": true,
            }),
        );
        row
    }
}

/// `Implication::pre` is minted at link time from the resolved callee
/// contract (#3831) -- this pass never constructs one, so it is not yet
/// worth pulling in a full `IrFormula` dependency edge here beyond the one
/// `Fact` already needs. A thin wrapper keeps the field real without
/// inventing behavior.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IrFormulaPlaceholder(pub IrFormula);

/// The claim side's sort-domain view of a call site: the operator /
/// function-contract universe linked to this call via `bridgeSourceSymbol`
/// (e.g. `call:add` → `mathy::add::callable`, `call:len` →
/// `len::builtin-universe`). Served by `sugar.enumerate` `level=universe`.
///
/// When the kit stamps the full `kind=function-contract` IR row on the wire
/// audit (pre/post/inv/formals/bridgeSourceSymbol), [`Self::ir_row`] carries
/// it so feed construction can mint mint-complete members — not name shells.
///
/// Self-locating via its own [`SourceMemento`] (function-contract seal; often
/// a different name/CID than the linking call site). Linkage is tree structure
/// (`CallSite::universe()`), not a second path type.
#[derive(Debug, Clone, PartialEq)]
pub struct Universe {
    memento: SourceMemento,
    audit: Option<AuditRow>,
    /// Full function-contract IR object from the wire `audit` when present.
    ir_row: Option<Value>,
    /// Reduced formula payload (`inv` else `post`) when the kit set `payload`.
    payload: Option<Value>,
}

impl Sourced for Universe {
    fn source_memento(&self) -> &SourceMemento {
        &self.memento
    }
}

impl Universe {
    pub fn audit_row(&self) -> Option<&AuditRow> {
        self.audit.as_ref()
    }

    /// Full IR row from wire audit (formals, post/pre/inv, bridgeSourceSymbol).
    pub fn ir_row(&self) -> Option<&Value> {
        self.ir_row.as_ref()
    }

    /// Wire formula payload when present (inv-else-post reduction).
    pub fn payload(&self) -> Option<&Value> {
        self.payload.as_ref()
    }

    /// Test/construction door for feed silent-loss instruments (#3901).
    /// Production nodes arrive only via `CallSite::universe()` enumeration.
    #[cfg(test)]
    pub fn for_feed_test(
        memento: SourceMemento,
        ir_row: Option<Value>,
        payload: Option<Value>,
    ) -> Self {
        Self {
            memento,
            audit: None,
            ir_row,
            payload,
        }
    }
}

/// ABI signature declared by a native export producer. These are the facts a
/// caller can check before binding a bridge, not guesses recovered from a
/// consumer language's call syntax.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AbiSignature {
    pub formals: Vec<Sort>,
    pub returns: Sort,
    pub platform_abi_tag: String,
}

/// Content-addressed identity of the source/header and object that warrant an
/// exported symbol contract.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ArtifactProvenance {
    pub header_or_source_cid: Option<String>,
    pub object_cid: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum WarrantKind {
    Source,
    Stub,
    GeneratedContract,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportMetadata {
    pub symbol: String,
    pub abi_signature: AbiSignature,
    pub artifact: ArtifactProvenance,
    pub calling_convention: String,
    pub warrant: WarrantKind,
}

/// One native producer answer. The metadata and contract cross the same
/// `sugar.enumerate` membrane as every other tree node; the contract is the
/// existing linker type, so producer resolution has no parallel join path.
#[derive(Debug, Clone)]
pub struct ExportedSymbol {
    memento: SourceMemento,
    metadata: ExportMetadata,
    contract: LinkerContract,
}

impl Sourced for ExportedSymbol {
    fn source_memento(&self) -> &SourceMemento {
        &self.memento
    }
}

impl ExportedSymbol {
    pub fn symbol(&self) -> &str {
        &self.metadata.symbol
    }

    pub fn calling_convention(&self) -> &str {
        &self.metadata.calling_convention
    }

    pub fn metadata(&self) -> &ExportMetadata {
        &self.metadata
    }

    pub fn contract(&self) -> &LinkerContract {
        &self.contract
    }
}

/// Every node type carries its own durable locator: the tree's primary key
/// (plan's "locator design" section). `source_fragment()` (the live,
/// in-session AST span) is deliberately NOT part of this trait -- fragments
/// never cross the wire (module doc; the plan's "wire discipline" rule),
/// so a Rust-side tree node, which only ever exists after a wire response,
/// has no fragment to hold. Only the durable half of the two-verb oracle
/// (`mint`/`lookup`) is representable client-side.
pub trait Sourced {
    fn source_memento(&self) -> &SourceMemento;
}

/// Mirrors the kit-side `FactoryWalkRowDto` (per-node factory construction
/// audit): every node self-audits, carrying the fields a caller needs to
/// tell recognized/gap/dig-boundary apart without re-deriving them.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct AuditRow {
    pub file: String,
    pub line: u64,
    pub requested_role: String,
    pub ast_kind: String,
    pub selected: Option<String>,
    pub status: String,
    pub verdict: String,
    pub reason: Option<String>,
}

impl AuditRow {
    fn from_json(value: &Value) -> AuditRow {
        AuditRow {
            file: value
                .get("file")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            line: value.get("line").and_then(Value::as_u64).unwrap_or(0),
            requested_role: value
                .get("requested_role")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            ast_kind: value
                .get("ast_kind")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            selected: value
                .get("selected")
                .and_then(Value::as_str)
                .map(str::to_string),
            status: value
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            verdict: value
                .get("verdict")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            reason: value
                .get("reason")
                .and_then(Value::as_str)
                .map(str::to_string),
        }
    }
}

/// True when a wire `audit` object still carries the kit IR contract row
/// (not a thin factory-walk row). Feed construction reads name/slots/formals
/// from this object; factory-only audits must not be treated as IR.
fn looks_like_ir_contract_row(value: &Value) -> bool {
    let Some(obj) = value.as_object() else {
        return false;
    };
    let kind = obj.get("kind").and_then(Value::as_str).unwrap_or("");
    if kind == "contract" || kind == "function-contract" {
        return true;
    }
    // IR rows always carry at least one body slot or formals even if kind is
    // missing under a future kit dialect.
    obj.contains_key("inv")
        || obj.contains_key("post")
        || obj.contains_key("pre")
        || obj.contains_key("formals")
        || obj.contains_key("bridgeSourceSymbol")
}

/// Decode first-class bridge identity from a call_sites/assertions wire audit.
/// Expects `call:` / `method:` forms; empty/missing → `None`.
fn decode_bridge_source_symbol(audit: Option<&Value>) -> Option<String> {
    let value = audit?;
    value
        .get("bridgeSourceSymbol")
        .or_else(|| value.get("bridge_source_symbol"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

#[derive(Debug, Clone, PartialEq)]
pub struct SourceFile {
    conn: KitConn,
    memento: SourceMemento,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Function {
    conn: KitConn,
    memento: SourceMemento,
    audit: Option<AuditRow>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CallSite {
    conn: KitConn,
    memento: SourceMemento,
    audit: Option<AuditRow>,
    /// Join key for universe/bridge, e.g. `"call:len"` | `"method:count"`.
    /// Decoded from the wire audit's `bridgeSourceSymbol` (prefix preserved).
    bridge_source_symbol: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Assertion {
    conn: KitConn,
    memento: SourceMemento,
    audit: Option<AuditRow>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Fact {
    memento: SourceMemento,
    audit: Option<AuditRow>,
    payload: IrFormula,
    /// Full `kind=contract` IR object from the wire `audit` when present
    /// (mint `name`, inv/post slots, sourceWarrants). Used by feed to build
    /// mint-complete claim members with unique names and correct body slots.
    ir_row: Option<Value>,
}

macro_rules! impl_sourced {
    ($ty:ty) => {
        impl Sourced for $ty {
            fn source_memento(&self) -> &SourceMemento {
                &self.memento
            }
        }
    };
}
impl_sourced!(SourceFile);
impl_sourced!(Function);
impl_sourced!(CallSite);
impl_sourced!(Assertion);
impl_sourced!(Fact);

impl Fact {
    pub fn audit_row(&self) -> Option<&AuditRow> {
        self.audit.as_ref()
    }

    pub fn payload(&self) -> &IrFormula {
        &self.payload
    }

    /// Full IR row from wire audit when the kit stamped the contract item.
    pub fn ir_row(&self) -> Option<&Value> {
        self.ir_row.as_ref()
    }

    /// Test/construction door for feed silent-loss instruments (#3901).
    /// Production nodes arrive only via `Assertion::facts()` enumeration.
    #[cfg(test)]
    pub fn for_feed_test(
        memento: SourceMemento,
        payload: IrFormula,
        ir_row: Option<Value>,
    ) -> Self {
        Self {
            memento,
            audit: None,
            payload,
            ir_row,
        }
    }
}

impl Function {
    pub fn audit_row(&self) -> Option<&AuditRow> {
        self.audit.as_ref()
    }
}
impl CallSite {
    pub fn audit_row(&self) -> Option<&AuditRow> {
        self.audit.as_ref()
    }

    /// First-class `call:` / `method:` bridge identity for this call site
    /// (e.g. `"call:len"`, `"method:count"`). Join key for
    /// `CallSite::universe()` linkage and completeness fold identity.
    pub fn bridge_source_symbol(&self) -> Option<&str> {
        self.bridge_source_symbol.as_deref()
    }
}
impl Assertion {
    pub fn audit_row(&self) -> Option<&AuditRow> {
        self.audit.as_ref()
    }
}

/// One raw node the wire returned, before it is dressed into a typed
/// node. Never escapes this module.
struct WireNode {
    memento: SourceMemento,
    audit: Option<Value>,
    payload: Option<Value>,
}

fn memento_to_json(m: &SourceMemento) -> Value {
    m.to_json()
}

fn decode_memento(value: &Value) -> Result<SourceMemento, String> {
    // `file` is the one REQUIRED field at every level: a memento without a
    // file is not a degenerate key, it is no key at all (gitar on #3862 --
    // a silent empty-string memento would vanish from the address space).
    // Every other field stays legitimately optional: file-level locators
    // are degenerate by design.
    let file = value
        .get("file")
        .and_then(Value::as_str)
        .filter(|f| !f.is_empty())
        .ok_or_else(|| format!("memento missing required `file`: {value}"))?
        .to_string();
    let function_name = value
        .get("function_name")
        .or_else(|| value.get("sourceFunctionName"))
        .or_else(|| value.get("source_function_name"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let span = value
        .get("span")
        .filter(|s| !s.is_null())
        .map(|s| SrcSpan {
            start_line: s.get("start_line").and_then(Value::as_u64).unwrap_or(0) as usize,
            start_col: s.get("start_col").and_then(Value::as_u64).unwrap_or(0) as usize,
            end_line: s.get("end_line").and_then(Value::as_u64).unwrap_or(0) as usize,
            end_col: s.get("end_col").and_then(Value::as_u64).unwrap_or(0) as usize,
        })
        .unwrap_or(SrcSpan {
            start_line: 0,
            start_col: 0,
            end_line: 0,
            end_col: 0,
        });
    let param_names = value
        .get("param_names")
        .or_else(|| value.get("paramNames"))
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let source_cid = value
        .get("source_cid")
        .or_else(|| value.get("sourceCid"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let template_cid = value
        .get("template_cid")
        .or_else(|| value.get("templateCid"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    Ok(SourceMemento {
        file,
        function_name,
        span,
        param_names,
        source_cid,
        template_cid,
    })
}

fn decode_node(value: &Value) -> Result<WireNode, String> {
    // A node without a memento would silently vanish from the address
    // space if skipped -- an accounting violation. Refuse loudly.
    let memento_value = value
        .get("memento")
        .ok_or_else(|| format!("node missing required `memento`: {value}"))?;
    Ok(WireNode {
        memento: decode_memento(memento_value)?,
        audit: value.get("audit").cloned().filter(|v| !v.is_null()),
        payload: value.get("payload").cloned().filter(|v| !v.is_null()),
    })
}

fn contains_term_ref(value: &Value) -> bool {
    match value {
        Value::Array(values) => values.iter().any(contains_term_ref),
        Value::Object(values) => {
            if values.get("kind").and_then(Value::as_str) == Some("term-ref") {
                return true;
            }
            values.values().any(contains_term_ref)
        }
        _ => false,
    }
}

fn decode_export_node(node: WireNode) -> Result<ExportedSymbol, String> {
    let audit = node
        .audit
        .ok_or_else(|| "exports node missing typed audit metadata".to_string())?;
    let metadata: ExportMetadata = serde_json::from_value(audit)
        .map_err(|error| format!("exports audit does not decode as ExportMetadata: {error}"))?;
    let payload = node
        .payload
        .ok_or_else(|| "exports node missing LinkerContract payload".to_string())?;
    let contract: LinkerContract = serde_json::from_value(payload)
        .map_err(|error| format!("exports payload does not decode as LinkerContract: {error}"))?;
    if contract.kit.is_empty() || contract.name != metadata.symbol {
        return Err(format!(
            "exports contract identity must carry producer kit and match symbol: kit={:?} contract={:?} symbol={:?}",
            contract.kit, contract.name, metadata.symbol
        ));
    }
    Ok(ExportedSymbol {
        memento: node.memento,
        metadata,
        contract,
    })
}

fn decode_gap(value: &Value) -> GapInfo {
    let mut decode_note = None;
    let memento =
        value
            .get("memento")
            .filter(|v| !v.is_null())
            .and_then(|v| match decode_memento(v) {
                Ok(m) => Some(m),
                Err(e) => {
                    decode_note = Some(e);
                    None
                }
            });
    let mut reason = value
        .get("reason")
        .and_then(Value::as_str)
        .unwrap_or("unspecified gap")
        .to_string();
    if let Some(note) = decode_note {
        reason = format!("{reason} (gap memento undecodable: {note})");
    }
    GapInfo { memento, reason }
}

/// The ONE enumeration RPC step: spawn the kit's manifest command, ask
/// `sugar.enumerate`, decode `{nodes, gaps}`. Mirrors `resolve_source`'s
/// spawn/write/read/shutdown membrane verbatim (same transport, new
/// method+params).
fn enumerate_rpc(
    conn: &KitConn,
    level: Level,
    at: Option<Value>,
    seek: bool,
) -> Result<(Vec<WireNode>, Vec<GapInfo>), EnumerateError> {
    let plugin = conn.surface.clone();
    if conn.command.is_empty() {
        return Err(EnumerateError::Unavailable {
            plugin,
            reason: "empty command".to_string(),
        });
    }
    let mut options = json!({"auditFrontier": conn.audit_frontier});
    if !conn.allowed_broken_components.is_empty() {
        options["allowedBrokenComponents"] = json!(conn.allowed_broken_components);
    }
    let response = conn
        .transport
        .request(&json!({
            "level": level.wire(),
            "at": at,
            "seek": seek,
            "workspace_root": conn.workspace_root.display().to_string(),
            "options": options,
        }))
        .map_err(|error| EnumerateError::Unavailable {
            plugin: plugin.clone(),
            reason: error.to_string(),
        })?;
    let result = enumerate_result_from_response(&plugin, response)?;
    let raw_nodes = result.get("nodes").and_then(Value::as_array);
    let response_has_term_refs = raw_nodes.is_some_and(|nodes| nodes.iter().any(contains_term_ref))
        || result.get("gaps").is_some_and(contains_term_ref);
    let term_table = if result.get("termTable").is_some() {
        Some(
            LiftTermTable::decode(&result).map_err(|reason| EnumerateError::Malformed {
                plugin: plugin.clone(),
                reason,
            })?,
        )
    } else if response_has_term_refs {
        return Err(EnumerateError::Malformed {
            plugin: plugin.clone(),
            reason:
                "enumeration response contains term-ref but is missing required `termTable` object"
                    .to_string(),
        });
    } else {
        None
    };
    let nodes = raw_nodes
        .map(|arr| {
            arr.iter()
                .map(|value| {
                    let resolved = if let Some(table) = &term_table {
                        table.resolve_value(value)?
                    } else {
                        value.clone()
                    };
                    decode_node(&resolved)
                })
                .collect::<Result<Vec<_>, _>>()
        })
        .unwrap_or_else(|| Ok(Vec::new()))
        .map_err(|reason| EnumerateError::MalformedNode {
            plugin: plugin.clone(),
            reason,
        })?;
    let gaps = result
        .get("gaps")
        .and_then(Value::as_array)
        .map(|arr| arr.iter().map(decode_gap).collect())
        .unwrap_or_default();
    Ok((nodes, gaps))
}

/// `LiftPluginKit::request` has already checked and removed the JSON-RPC
/// envelope. Keep this boundary explicit: enumeration consumes that result
/// payload directly. A second `result` unwrap turns every lawful node set into
/// `null`, making the complete tree look empty.
fn enumerate_result_from_response(plugin: &str, response: Value) -> Result<Value, EnumerateError> {
    if let Some(error) = response.get("error") {
        return Err(EnumerateError::RpcError {
            plugin: plugin.to_string(),
            error: error.clone(),
        });
    }
    Ok(response)
}

/// Closed Python producer wire row. Identity supplied by the producer is the
/// source/body demand owner plus the exact terminal gap coordinate; the Rust
/// fold adds the demanded SourceMemento and complete owner identity.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecoveredFactoryPanicWire {
    kind: String,
    status: String,
    reason: String,
    locus: String,
    demanded_source: String,
    terminal_gap_locus: String,
    gap: Map<String, Value>,
}

/// Closed leaf effect row. The Rust fold alone attaches `demandedBody`; the
/// producer must not invent fold-owned identity fields (#4264).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecoveredEffectLeafWire {
    locus: String,
    effect: String,
    category: String,
    status: String,
    reason: String,
}

/// Closed suppressed-descendant leaf row. Same ownership rule as effects.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SuppressedAuditLocusLeafWire {
    locus: String,
    reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecoveredAuditLeafWire {
    kind: String,
    recovery_override: bool,
    status: String,
    panics: Vec<RecoveredFactoryPanicWire>,
    effects: Vec<RecoveredEffectLeafWire>,
    suppressed_descendants: Vec<SuppressedAuditLocusLeafWire>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoveredPanicOwnerIdentity {
    demanded_body: Value,
    demanded_source: String,
    terminal_gap_locus: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoveredFactoryPanicRow {
    kind: String,
    status: String,
    reason: String,
    locus: String,
    demanded_source: String,
    terminal_gap_locus: String,
    gap: Map<String, Value>,
    demanded_body: Value,
    owner_identity: RecoveredPanicOwnerIdentity,
}

/// Consumer fold for recovered construction audit. A frontier is a closed
/// result: every enumerated source file must have its body demanded and every
/// discovered audit leaf must complete with a separately typed recovered
/// payload. Any gap, seek miss, malformed leaf, or producer death returns Err;
/// the CLI therefore has no value it could serialize as a frontier artifact.
pub fn fold_recovered_audit(
    kit: &Kit,
    workspace_root: &Path,
    allowed_broken_components: &[String],
) -> Result<Value, KitError> {
    let mut conn = kit.enumerate_conn(workspace_root);
    conn.audit_frontier = true;
    conn.allowed_broken_components = allowed_broken_components.to_vec();
    let (files, source_gaps) = enumerate_rpc(&conn, Level::SourceFiles, None, false)?;
    if !source_gaps.is_empty() {
        return Err(EnumerateError::Malformed {
            plugin: conn.surface.clone(),
            reason: format!("source census returned {} gaps", source_gaps.len()),
        }
        .into());
    }
    let source_files_enumerated = files.len();
    let mut source_bodies_demanded = 0usize;
    let mut audit_leaves_completed = 0usize;
    let mut panics = Vec::new();
    let mut effects = Vec::new();
    let mut suppressed = Vec::new();
    for file in files {
        let (definitions, definition_gaps) =
            enumerate_rpc(&conn, Level::Functions, Some(file.memento.to_json()), false)?;
        source_bodies_demanded += 1;
        if !definition_gaps.is_empty() {
            return Err(EnumerateError::Malformed {
                plugin: conn.surface.clone(),
                reason: format!(
                    "function census for {} returned {} gaps",
                    file.memento.file,
                    definition_gaps.len()
                ),
            }
            .into());
        }
        for definition in definitions {
            let (leaves, leaf_gaps) = enumerate_rpc(
                &conn,
                Level::Facts,
                Some(definition.memento.to_json()),
                true,
            )?;
            if !leaf_gaps.is_empty() || leaves.len() != 1 {
                return Err(EnumerateError::Malformed {
                    plugin: conn.surface.clone(),
                    reason: format!(
                        "audit leaf demand for {} completed nodes={} gaps={}",
                        memento_locus_display(&definition.memento),
                        leaves.len(),
                        leaf_gaps.len()
                    ),
                }
                .into());
            }
            let leaf = leaves.into_iter().next().expect("length checked");
            let audit = leaf.audit.ok_or_else(|| EnumerateError::Malformed {
                plugin: conn.surface.clone(),
                reason: format!(
                    "audit leaf {} omitted recovered body",
                    memento_locus_display(&definition.memento)
                ),
            })?;
            merge_recovered_audit_leaf(
                &conn.surface,
                &definition.memento,
                audit,
                &mut panics,
                &mut effects,
                &mut suppressed,
            )?;
            audit_leaves_completed += 1;
        }
    }
    if source_bodies_demanded != source_files_enumerated {
        return Err(EnumerateError::Malformed {
            plugin: conn.surface.clone(),
            reason: format!(
                "source body census mismatch: enumerated={source_files_enumerated} demanded={source_bodies_demanded}"
            ),
        }
        .into());
    }
    Ok(json!({
        "kind": "recovered-construction-audit",
        "recoveryOverride": true,
        "status": if source_files_enumerated == 0 {
            "valid-empty"
        } else if panics.is_empty() {
            "complete"
        } else {
            "failed"
        },
        "census": {
            "kind": "recovered-frontier-census",
            "sourceFilesEnumerated": source_files_enumerated,
            "sourceBodiesDemanded": source_bodies_demanded,
            "auditLeavesCompleted": audit_leaves_completed,
        },
        "panics": panics,
        "effects": effects,
        "suppressedDescendants": suppressed,
    }))
}

fn merge_recovered_audit_leaf(
    plugin: &str,
    demanded_body: &SourceMemento,
    audit: Value,
    panics: &mut Vec<Value>,
    effects: &mut Vec<Value>,
    suppressed: &mut Vec<Value>,
) -> Result<(), KitError> {
    let malformed = |reason: String| {
        KitError::from(EnumerateError::Malformed {
            plugin: plugin.to_string(),
            reason,
        })
    };
    let leaf: RecoveredAuditLeafWire = serde_json::from_value(audit).map_err(|error| {
        malformed(format!(
            "audit leaf does not decode as closed recovered wire schema: {error}"
        ))
    })?;
    if leaf.kind != "recovered-construction-audit" || !leaf.recovery_override {
        return Err(malformed(
            "audit leaf is not a recovery-override construction audit".to_string(),
        ));
    }
    let expected_status = if leaf.panics.is_empty() {
        "clean"
    } else {
        "failed"
    };
    if leaf.status != expected_status {
        return Err(malformed(format!(
            "audit leaf status must be {expected_status} for panics={}",
            leaf.panics.len()
        )));
    }
    let demanded_body = demanded_body.to_json();
    for panic in leaf.panics {
        if panic.kind != "FactoryPanic" || panic.status != "mandatory-panic" {
            return Err(malformed(
                "recovered panic row must be a mandatory FactoryPanic".to_string(),
            ));
        }
        if panic.locus.is_empty() || panic.demanded_source.is_empty() {
            return Err(malformed(
                "recovered panic row omitted source or demandedSource identity".to_string(),
            ));
        }
        let typed_gap_locus = panic
            .gap
            .get("blame")
            .or_else(|| panic.gap.get("gap_locus"))
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| {
                malformed("recovered panic typed gap omitted terminal locus".to_string())
            })?;
        if panic.terminal_gap_locus != typed_gap_locus {
            return Err(malformed(format!(
                "recovered panic terminalGapLocus must match typed gap locus: terminal={:?} gap={:?}",
                panic.terminal_gap_locus, typed_gap_locus
            )));
        }
        let owner_identity = RecoveredPanicOwnerIdentity {
            demanded_body: demanded_body.clone(),
            demanded_source: panic.demanded_source.clone(),
            terminal_gap_locus: panic.terminal_gap_locus.clone(),
        };
        let owner_identity_value = serde_json::to_value(&owner_identity)
            .expect("recovered panic owner identity must serialize");
        if panics
            .iter()
            .any(|existing| existing.get("ownerIdentity") == Some(&owner_identity_value))
        {
            return Err(malformed(format!(
                "duplicate recovered panic owner identity: {owner_identity_value}"
            )));
        }
        let row = RecoveredFactoryPanicRow {
            kind: panic.kind,
            status: panic.status,
            reason: panic.reason,
            locus: panic.locus,
            demanded_source: panic.demanded_source,
            terminal_gap_locus: panic.terminal_gap_locus,
            gap: panic.gap,
            demanded_body: demanded_body.clone(),
            owner_identity,
        };
        panics.push(serde_json::to_value(row).expect("closed recovered panic row must serialize"));
    }
    for effect in leaf.effects {
        let mut row = serde_json::to_value(&effect)
            .expect("closed recovered effect leaf must serialize")
            .as_object()
            .cloned()
            .expect("closed recovered effect leaf serializes as object");
        row.insert("demandedBody".to_string(), demanded_body.clone());
        effects.push(Value::Object(row));
    }
    for locus in leaf.suppressed_descendants {
        let mut row = serde_json::to_value(&locus)
            .expect("closed suppressed descendant leaf must serialize")
            .as_object()
            .cloned()
            .expect("closed suppressed descendant leaf serializes as object");
        row.insert("demandedBody".to_string(), demanded_body.clone());
        suppressed.push(Value::Object(row));
    }
    Ok(())
}

impl Kit {
    /// Scan the producer surface. Export answers reuse the existing linker
    /// contract type; malformed or identity-mismatched answers are loud wire
    /// errors, never silently omitted exports.
    pub fn exports(&self, workspace_root: &Path) -> Result<Vec<ExportedSymbol>, KitError> {
        let conn = self.enumerate_conn(workspace_root);
        let (nodes, _gaps) = enumerate_rpc(&conn, Level::Exports, None, false)?;
        nodes
            .into_iter()
            .map(|node| {
                decode_export_node(node).map_err(|reason| {
                    KitError::from(EnumerateError::MalformedNode {
                        plugin: conn.surface.clone(),
                        reason,
                    })
                })
            })
            .collect()
    }

    /// Seek a native export by the producer's own ABI symbol. This is the one
    /// enumeration key a driver may construct: the consumer call edge already
    /// carries this stable symbol coordinate. A named producer gap is `None`;
    /// malformed producer data remains an error.
    pub fn export(
        &self,
        workspace_root: &Path,
        symbol: &str,
    ) -> Result<Option<ExportedSymbol>, KitError> {
        let conn = self.enumerate_conn(workspace_root);
        let (nodes, gaps) =
            enumerate_rpc(&conn, Level::Exports, Some(json!({"symbol": symbol})), true)?;
        let Some(node) = nodes.into_iter().next() else {
            if gaps.is_empty() {
                return Err(EnumerateError::SeekMiss {
                    plugin: conn.surface,
                    level: "exports",
                }
                .into());
            }
            return Ok(None);
        };
        decode_export_node(node)
            .map(Some)
            .map_err(|reason| EnumerateError::MalformedNode {
                plugin: conn.surface,
                reason,
            })
            .map_err(KitError::from)
    }

    /// `sugar.enumerate` at `level="source_files"`. Scan: every python file
    /// the kit's `_iter_python_files` walk finds under `workspace_root`.
    pub fn source_files(&self, workspace_root: &Path) -> Result<Vec<SourceFile>, KitError> {
        let conn = self.enumerate_conn(workspace_root);
        let (nodes, _gaps) = enumerate_rpc(&conn, Level::SourceFiles, None, false)?;
        Ok(nodes
            .into_iter()
            .map(|n| SourceFile {
                conn: conn.clone(),
                memento: n.memento,
            })
            .collect())
    }

    /// Gaps alongside the last `source_files()` scan would need this same
    /// RPC re-run; kept as a separate accessor per level rather than
    /// threading a tuple through every call site.
    pub fn source_files_gaps(&self, workspace_root: &Path) -> Result<Vec<GapInfo>, KitError> {
        let conn = self.enumerate_conn(workspace_root);
        let (_nodes, gaps) = enumerate_rpc(&conn, Level::SourceFiles, None, false)?;
        Ok(gaps)
    }

    /// Seek: `level="source_files"`, `at=memento`, `seek=true` -- exactly
    /// one node back, or `SeekMiss`. The driver never fabricates the
    /// memento; it replays one handed back from a prior `source_files()`.
    pub fn source_file(
        &self,
        workspace_root: &Path,
        memento: &SourceMemento,
    ) -> Result<SourceFile, KitError> {
        let conn = self.enumerate_conn(workspace_root);
        let (nodes, _gaps) = enumerate_rpc(
            &conn,
            Level::SourceFiles,
            Some(memento_to_json(memento)),
            true,
        )?;
        let node = nodes.into_iter().next().ok_or(EnumerateError::SeekMiss {
            plugin: conn.surface.clone(),
            level: "source_files",
        })?;
        Ok(SourceFile {
            conn,
            memento: node.memento,
        })
    }
}

impl SourceFile {
    /// `level="functions"`, `at=<this file's memento>`. See module doc's
    /// GRANULARITY note: functions come from `payload.ir`'s
    /// function-contract entries, one per `fnName`.
    pub fn functions(&self) -> Result<Vec<Function>, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::Functions,
            Some(self.memento.to_json()),
            false,
        )
        .map_err(KitError::from)?;
        Ok(nodes
            .into_iter()
            .map(|n| Function {
                conn: self.conn.clone(),
                memento: n.memento,
                audit: n.audit.as_ref().map(AuditRow::from_json),
            })
            .collect())
    }

    pub fn functions_gaps(&self) -> Result<Vec<GapInfo>, KitError> {
        let (_nodes, gaps) = enumerate_rpc(
            &self.conn,
            Level::Functions,
            Some(self.memento.to_json()),
            false,
        )?;
        Ok(gaps)
    }

    pub fn function(&self, memento: &SourceMemento) -> Result<Function, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::Functions,
            Some(memento_to_json(memento)),
            true,
        )?;
        let node = nodes.into_iter().next().ok_or(EnumerateError::SeekMiss {
            plugin: self.conn.surface.clone(),
            level: "functions",
        })?;
        Ok(Function {
            conn: self.conn.clone(),
            memento: node.memento,
            audit: node.audit.as_ref().map(AuditRow::from_json),
        })
    }

    /// The source verb (SEAM 4, unchanged): resolve this file's own span
    /// against `sugar.plugin.resolve_source_memento`. Reuses
    /// `resolve::resolve_source` rather than a second implementation.
    pub fn source(&self) -> Result<crate::resolve::ResolvedSource, crate::resolve::SourceRefusal> {
        crate::resolve::resolve_source(
            &self.conn.surface,
            &self.conn.command,
            self.conn.working_dir.as_deref(),
            &self.conn.workspace_root,
            &self.memento,
        )
    }
}

impl Function {
    pub fn call_sites(&self) -> Result<Vec<CallSite>, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::CallSites,
            Some(self.memento.to_json()),
            false,
        )?;
        // Client-side span filter (matches kit): when this function memento has
        // a real span, drop sites whose span is outside it (enclosing locus).
        let parent_span = &self.memento.span;
        Ok(nodes
            .into_iter()
            .filter(|n| {
                if span_is_degenerate(parent_span) {
                    return true;
                }
                if span_is_degenerate(&n.memento.span) {
                    return true; // name-scoped fallback for locus-less sites
                }
                span_contains(parent_span, &n.memento.span)
            })
            .map(|n| CallSite {
                conn: self.conn.clone(),
                memento: n.memento,
                bridge_source_symbol: decode_bridge_source_symbol(n.audit.as_ref()),
                audit: n.audit.as_ref().map(AuditRow::from_json),
            })
            .collect())
    }

    pub fn call_sites_gaps(&self) -> Result<Vec<GapInfo>, KitError> {
        let (_nodes, gaps) = enumerate_rpc(
            &self.conn,
            Level::CallSites,
            Some(self.memento.to_json()),
            false,
        )?;
        Ok(gaps)
    }

    pub fn call_site(&self, memento: &SourceMemento) -> Result<CallSite, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::CallSites,
            Some(memento_to_json(memento)),
            true,
        )?;
        let node = nodes.into_iter().next().ok_or(EnumerateError::SeekMiss {
            plugin: self.conn.surface.clone(),
            level: "call_sites",
        })?;
        Ok(CallSite {
            conn: self.conn.clone(),
            memento: node.memento,
            bridge_source_symbol: decode_bridge_source_symbol(node.audit.as_ref()),
            audit: node.audit.as_ref().map(AuditRow::from_json),
        })
    }
}

impl CallSite {
    /// Claim side: the assertions made about this call's result.
    ///
    /// **Factory truth (not a protocol collapse):** shipping kit batch IR
    /// has no distinct call-site record separate from the claim
    /// (`kind="contract"` bundles locus + formula). So this returns exactly
    /// one `Assertion` built from the same record as this `CallSite`. See
    /// protocol Section 4 and
    /// `enumerate_callsite_assertion_is_factory_one_to_one`.
    pub fn assertions(&self) -> Result<Vec<Assertion>, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::Assertions,
            Some(self.memento.to_json()),
            true,
        )?;
        Ok(nodes
            .into_iter()
            .map(|n| Assertion {
                conn: self.conn.clone(),
                memento: n.memento,
                audit: n.audit.as_ref().map(AuditRow::from_json),
            })
            .collect())
    }

    pub fn assertions_gaps(&self) -> Result<Vec<GapInfo>, KitError> {
        let (_nodes, gaps) = enumerate_rpc(
            &self.conn,
            Level::Assertions,
            Some(self.memento.to_json()),
            true,
        )?;
        Ok(gaps)
    }

    pub fn assertion(&self, memento: &SourceMemento) -> Result<Assertion, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::Assertions,
            Some(memento_to_json(memento)),
            true,
        )?;
        let node = nodes.into_iter().next().ok_or(EnumerateError::SeekMiss {
            plugin: self.conn.surface.clone(),
            level: "assertions",
        })?;
        Ok(Assertion {
            conn: self.conn.clone(),
            memento: node.memento,
            audit: node.audit.as_ref().map(AuditRow::from_json),
        })
    }

    /// LIFT-time claim side: the operator / function-contract universe
    /// linked to this call site. `sugar.enumerate` `level=universe`,
    /// `at=<this call site's memento>`, `seek=true`. Returns `Ok(None)`
    /// when the kit reports a gap (no universe sugar for the callee) so
    /// absence stays a link-class signal, not a walk panic.
    pub fn universe(&self) -> Result<Option<Universe>, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::Universe,
            Some(self.memento.to_json()),
            true,
        )?;
        Ok(nodes.into_iter().next().map(|n| Universe {
            memento: n.memento,
            audit: n.audit.as_ref().map(AuditRow::from_json),
            // Preserve full function-contract IR (pre/post/inv/formals) for
            // mint-complete feed construction (Task 9). AuditRow alone drops them.
            ir_row: n.audit.clone().filter(looks_like_ir_contract_row),
            payload: n.payload,
        }))
    }

    /// Gaps alongside `universe()` for this call site (e.g.
    /// `no universe sugar for callee call:count`).
    pub fn universe_gaps(&self) -> Result<Vec<GapInfo>, KitError> {
        let (_nodes, gaps) = enumerate_rpc(
            &self.conn,
            Level::Universe,
            Some(self.memento.to_json()),
            true,
        )?;
        Ok(gaps)
    }

    /// LINK-time obligation side (#3831): never bound by this pass. See
    /// module doc's CLAIM vs OBLIGATION split.
    pub fn contract(&self) -> EdgeTarget<Contract> {
        EdgeTarget::Unbound
    }

    /// Demand this exact call site's implication question. The producer returns
    /// candidate input only; this coordinator invokes the pure one-edge linker
    /// worker, which owns join, obligation mint, and status. The supplied
    /// `registry` + `plan` are the SAME solver seats the discharge path
    /// consults, so the demanded answer IS the discharged verdict.
    pub fn implication(
        &self,
        registry: &sugar_linker::Registry,
        plan: &sugar_linker::solver_api::SolverPlan,
    ) -> Result<Implication, KitError> {
        let (nodes, gaps) = enumerate_rpc(
            &self.conn,
            Level::Implications,
            Some(self.memento.to_json()),
            true,
        )?;
        let node = nodes.into_iter().next().ok_or_else(|| {
            KitError::from(if gaps.is_empty() {
                EnumerateError::SeekMiss {
                    plugin: self.conn.surface.clone(),
                    level: "implications",
                }
            } else {
                EnumerateError::NotModeled {
                    plugin: self.conn.surface.clone(),
                    level: "implications",
                    reason: gaps
                        .into_iter()
                        .map(|gap| gap.reason)
                        .collect::<Vec<_>>()
                        .join("; "),
                }
            })
        })?;
        let question_audit = node.audit.ok_or_else(|| {
            KitError::from(EnumerateError::Malformed {
                plugin: self.conn.surface.clone(),
                reason: "implication question missing audit testimony".to_string(),
            })
        })?;
        let answer = match node.payload {
            Some(payload) => {
                let demand: sugar_linker::ImplicationDemand = serde_json::from_value(payload)
                    .map_err(|error| {
                        KitError::from(EnumerateError::Malformed {
                            plugin: self.conn.surface.clone(),
                            reason: format!("implication question payload is invalid: {error}"),
                        })
                    })?;
                serde_json::to_value(sugar_linker::demand_implication(demand, registry, plan))
                    .map_err(|error| {
                        KitError::from(EnumerateError::Malformed {
                            plugin: self.conn.surface.clone(),
                            reason: format!("implication answer cannot serialize: {error}"),
                        })
                    })?
            }
            None => json!({
                "sourceContract": question_audit.get("sourceContract").cloned().unwrap_or_else(|| Value::String("<unknown caller>".into())),
                "targetContract": Value::Null,
                "targetSymbol": question_audit.get("targetSymbol").cloned().unwrap_or_else(|| Value::String("unknown".into())),
                "status": "unjoined",
                "reason": "demanded implication question carried no linker input",
                "obligation": Value::Null,
            }),
        };
        let payload = answer
            .get("obligation")
            .filter(|value| !value.is_null())
            .cloned();
        Ok(Implication {
            // The consumer-owned replay key is the question identity. Never let
            // a producer substitute another callsite memento in the answer.
            memento: self.memento.clone(),
            surface: self.conn.surface.clone(),
            audit: answer,
            payload,
        })
    }
}

/// CLI appetite: demand every call site's implication node and retain the
/// transcript. Enumeration remains the only work driver at every edge. The
/// caller supplies the workspace solver `registry` + `plan` so every demanded
/// verdict is the real discharge verdict, never a solverless shadow.
pub fn fold_implication_tree(
    kit: &Kit,
    workspace_root: &Path,
    registry: &sugar_linker::Registry,
    plan: &sugar_linker::solver_api::SolverPlan,
) -> Result<Vec<Value>, KitError> {
    let mut implications = Vec::new();
    for file in kit.source_files(workspace_root)? {
        for function in file.functions()? {
            for call_site in function.call_sites()? {
                implications.push(call_site.implication(registry, plan)?.report_row());
            }
        }
    }
    Ok(implications)
}

impl Assertion {
    /// `build_node(fragment).sugar` slice: the FOL this assertion carries,
    /// as `emittedFormula` on the matching `factory_walk` row.
    pub fn facts(&self) -> Result<Vec<Fact>, KitError> {
        let (nodes, _gaps) =
            enumerate_rpc(&self.conn, Level::Facts, Some(self.memento.to_json()), true)?;
        let mut out = Vec::with_capacity(nodes.len());
        for n in nodes {
            let payload_value = n.payload.ok_or_else(|| {
                KitError::from(EnumerateError::Malformed {
                    plugin: self.conn.surface.clone(),
                    reason: "facts node missing payload".to_string(),
                })
            })?;
            let formula: IrFormula = serde_json::from_value(payload_value).map_err(|error| {
                KitError::from(EnumerateError::Malformed {
                    plugin: self.conn.surface.clone(),
                    reason: format!("fact payload does not decode as IrFormula: {error}"),
                })
            })?;
            out.push(Fact {
                memento: n.memento,
                audit: n.audit.as_ref().map(AuditRow::from_json),
                payload: formula,
                // Preserve full kind=contract IR (unique mint name, inv/post).
                ir_row: n.audit.clone().filter(looks_like_ir_contract_row),
            });
        }
        Ok(out)
    }

    pub fn facts_gaps(&self) -> Result<Vec<GapInfo>, KitError> {
        let (_nodes, gaps) =
            enumerate_rpc(&self.conn, Level::Facts, Some(self.memento.to_json()), true)?;
        Ok(gaps)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn recovered_owner(file: &str, function: &str, line: usize) -> SourceMemento {
        SourceMemento {
            file: file.to_string(),
            function_name: function.to_string(),
            span: SrcSpan {
                start_line: line,
                start_col: 0,
                end_line: line + 1,
                end_col: 0,
            },
            param_names: Vec::new(),
            source_cid: format!("blake3-512:{file}:{function}:{line}"),
            template_cid: String::new(),
        }
    }

    fn recovered_leaf(panics: Vec<Value>) -> Value {
        json!({
            "kind": "recovered-construction-audit",
            "recoveryOverride": true,
            "status": if panics.is_empty() { "clean" } else { "failed" },
            "panics": panics,
            "effects": [],
            "suppressedDescendants": [],
        })
    }

    fn recovered_panic(demand: &str) -> Value {
        json!({
            "kind": "FactoryPanic",
            "status": "mandatory-panic",
            "reason": "unbound propagated dependency name",
            "locus": "consumer.py:1:0",
            "demandedSource": demand,
            "terminalGapLocus": "typing.py:753:11",
            "gap": {
                "owner": "TemporalContext",
                "blame": "typing.py:753:11",
                "observed": "_LiteralSpecialForm",
                "requested": "value",
                "fix": "bind the name",
                "gap_kind": "Floor",
                "gap_locus": "Construction"
            }
        })
    }

    #[test]
    fn recovered_panic_collision_preserves_distinct_demanded_owners() {
        let mut panics = Vec::new();
        let mut effects = Vec::new();
        let mut suppressed = Vec::new();
        let first = recovered_owner("consumer.py", "first", 10);
        let second = recovered_owner("consumer.py", "second", 20);

        merge_recovered_audit_leaf(
            "fixture",
            &first,
            recovered_leaf(vec![recovered_panic("pandas._typing.A")]),
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect("first distinct demand");
        merge_recovered_audit_leaf(
            "fixture",
            &second,
            recovered_leaf(vec![recovered_panic("pandas._typing.A")]),
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect("second distinct demand");

        assert_eq!(panics.len(), 2);
        assert_eq!(panics[0]["gap"], panics[1]["gap"]);
        assert_ne!(panics[0]["demandedBody"], panics[1]["demandedBody"]);
        assert_eq!(panics[0]["terminalGapLocus"], "typing.py:753:11");
    }

    #[test]
    fn recovered_panic_collision_preserves_distinct_demands_in_one_body() {
        let mut panics = Vec::new();
        let mut effects = Vec::new();
        let mut suppressed = Vec::new();
        let owner = recovered_owner("api/typing/aliases.py", "<module>", 1);

        merge_recovered_audit_leaf(
            "fixture",
            &owner,
            recovered_leaf(vec![
                recovered_panic("pandas._typing.TypeGuard"),
                recovered_panic("pandas._typing.TypeAlias"),
            ]),
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect("distinct import demands sharing one terminal gap");

        assert_eq!(panics.len(), 2);
        assert_eq!(panics[0]["demandedBody"], panics[1]["demandedBody"]);
        assert_ne!(panics[0]["demandedSource"], panics[1]["demandedSource"]);
    }

    #[test]
    fn recovered_panic_rejects_exact_duplicate_owner_identity() {
        let mut panics = Vec::new();
        let mut effects = Vec::new();
        let mut suppressed = Vec::new();
        let owner = recovered_owner("api/typing/aliases.py", "<module>", 1);
        let duplicate = recovered_panic("pandas._typing.TypeGuard");

        let error = merge_recovered_audit_leaf(
            "fixture",
            &owner,
            recovered_leaf(vec![duplicate.clone(), duplicate]),
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect_err("same demanded owner may emit one terminal row only");

        assert!(error
            .to_string()
            .contains("duplicate recovered panic owner identity"));
    }

    #[test]
    fn recovered_panic_rejects_terminal_locus_that_is_not_the_gap_coordinate() {
        let mut panics = Vec::new();
        let mut effects = Vec::new();
        let mut suppressed = Vec::new();
        let owner = recovered_owner("api/typing/aliases.py", "<module>", 1);
        let mut wrong = recovered_panic("pandas._typing.TypeGuard");
        wrong["terminalGapLocus"] = json!("consumer.py:1:0");

        let error = merge_recovered_audit_leaf(
            "fixture",
            &owner,
            recovered_leaf(vec![wrong]),
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect_err("terminalGapLocus must identify the exact typed gap coordinate");

        assert!(error
            .to_string()
            .contains("terminalGapLocus must match typed gap locus"));
    }

    #[test]
    fn recovered_panic_rejects_producer_forged_fold_identity_fields() {
        let mut panics = Vec::new();
        let mut effects = Vec::new();
        let mut suppressed = Vec::new();
        let owner = recovered_owner("api/typing/aliases.py", "<module>", 1);
        let mut forged = recovered_panic("pandas._typing.TypeGuard");
        forged["demandedBody"] = owner.to_json();

        let error = merge_recovered_audit_leaf(
            "fixture",
            &owner,
            recovered_leaf(vec![forged]),
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect_err("Rust fold exclusively owns complete demanded-body identity");

        assert!(error.to_string().contains("unknown field `demandedBody`"));
    }

    fn recovered_audit_fixture(name: &str) -> Value {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../protocol/conformance/recovered-audit")
            .join(name);
        let raw = std::fs::read_to_string(&path)
            .unwrap_or_else(|error| panic!("read {}: {error}", path.display()));
        serde_json::from_str(&raw)
            .unwrap_or_else(|error| panic!("parse {}: {error}", path.display()))
    }

    #[test]
    fn recovered_audit_leaf_goldens_round_trip_without_loss() {
        for name in ["leaf-clean.json", "leaf-full.json"] {
            let fixture = recovered_audit_fixture(name);
            let leaf: RecoveredAuditLeafWire = serde_json::from_value(fixture.clone())
                .unwrap_or_else(|error| panic!("{name} must decode as leaf wire: {error}"));
            let round_trip = serde_json::to_value(&leaf).expect("closed leaf wire must serialize");
            assert_eq!(
                round_trip, fixture,
                "{name}: leaf schema round-trip must be lossless"
            );
        }
    }

    #[test]
    fn recovered_audit_leaf_golden_rejects_unknown_fields() {
        let fixture = recovered_audit_fixture("bad-leaf-unknown-field.json");
        let error = serde_json::from_value::<RecoveredAuditLeafWire>(fixture)
            .expect_err("unknown leaf lane must be rejected");
        assert!(
            error.to_string().contains("inventedLane")
                || error.to_string().contains("unknown field"),
            "{error}"
        );
    }

    #[test]
    fn recovered_audit_leaf_golden_fold_attaches_demanded_body() {
        let fixture = recovered_audit_fixture("leaf-full.json");
        let mut panics = Vec::new();
        let mut effects = Vec::new();
        let mut suppressed = Vec::new();
        let owner = recovered_owner("pkg.py", "broken", 1);
        merge_recovered_audit_leaf(
            "fixture",
            &owner,
            fixture,
            &mut panics,
            &mut effects,
            &mut suppressed,
        )
        .expect("leaf-full golden must fold");
        assert_eq!(panics.len(), 1);
        assert_eq!(effects.len(), 1);
        assert_eq!(suppressed.len(), 1);
        assert_eq!(panics[0]["demandedBody"], owner.to_json());
        assert_eq!(effects[0]["demandedBody"], owner.to_json());
        assert_eq!(suppressed[0]["demandedBody"], owner.to_json());
        assert_eq!(
            panics[0]["ownerIdentity"]["demandedSource"],
            json!("definition:broken")
        );
    }

    #[test]
    fn decode_memento_round_trips_through_to_json() {
        let original = SourceMemento {
            file: "a.py".to_string(),
            function_name: "f".to_string(),
            span: SrcSpan {
                start_line: 1,
                start_col: 2,
                end_line: 3,
                end_col: 4,
            },
            param_names: vec!["x".to_string()],
            source_cid: "blake3-512:abc".to_string(),
            template_cid: "blake3-512:def".to_string(),
        };
        let decoded = decode_memento(&original.to_json()).expect("round trip");
        assert_eq!(decoded, original);
    }

    #[test]
    fn decode_memento_defaults_degenerate_file_level_locator() {
        let value = json!({"file": "a.py"});
        let decoded = decode_memento(&value).expect("file-level degenerate locator is legal");
        assert_eq!(decoded.file, "a.py");
        assert_eq!(decoded.span.start_line, 0);
        assert_eq!(decoded.source_cid, "");
    }

    /// gitar on #3862: a memento without `file` is no key at all -- refuse.
    #[test]
    fn decode_memento_refuses_missing_file() {
        assert!(decode_memento(&json!({"span": null})).is_err());
        assert!(decode_memento(&json!({"file": ""})).is_err());
    }

    /// A node without a memento must error loudly, never vanish silently.
    #[test]
    fn decode_node_refuses_missing_memento() {
        assert!(decode_node(&json!({"payload": {"x": 1}})).is_err());
    }

    #[test]
    fn enumerate_transport_consumes_the_already_unwrapped_result() {
        let result = enumerate_result_from_response(
            "fixture-kit",
            json!({
                "nodes": [{"memento": {"file": "src/lib.rs"}}],
                "gaps": []
            }),
        )
        .expect("lawful result payload");

        assert_eq!(result["nodes"][0]["memento"]["file"], "src/lib.rs");
    }

    #[test]
    fn enumerate_transport_preserves_json_rpc_error_as_loud_failure() {
        let error = enumerate_result_from_response(
            "fixture-kit",
            json!({
                "jsonrpc": "2.0",
                "id": 2,
                "error": {"code": -32601, "message": "unknown method"}
            }),
        )
        .expect_err("RPC error must not degrade to an empty child set");

        assert!(matches!(
            error,
            EnumerateError::RpcError { plugin, .. } if plugin == "fixture-kit"
        ));
    }
}
