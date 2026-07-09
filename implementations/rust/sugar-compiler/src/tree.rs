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
// LEAF ADDRESS (#3809 T resolution): the typed descent bottoms in
// `SourceMemento[path]` — nested path is the address (`file[fn[leaf]]`;
// factory 1:1 site ≡ assertion ≡ fact share the leaf span under one memento),
// memento CIDs are the sealed wire currency. Fragment stays LOCAL (kit/oracle);
// memento crosses. See [`MementoPath`] / [`SourceMementoAtPath`].
//
// TYPED PATH LEVELS: `CallSite`, `Assertion`, `Fact`, and `Universe` store a
// stamped [`MementoPath`]; `Function` exposes computed `path()` /
// `memento_at_path()` as `file[fn]`. `SourceFile` remains flat (file-only
// path shape already exists via [`MementoPath::file`] — next step).
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

use serde_json::{json, Value};
use sugar_ir_types::IrFormula;
use sugar_walk::source_oracle::{SourceMemento, SrcSpan};

use crate::kit::{Kit, KitError};

// ---------------------------------------------------------------------------
// SourceMemento[path] — path is the descent address; memento is the seal.
// Fragment never appears here (content-address law).
// ---------------------------------------------------------------------------

/// Nested path index for enumeration: path IS the address.
///
/// Display form: `file`, `file[fn]`, or `file[fn[leaf]]` (spans in debug).
/// Does not replace [`SourceMemento`] content-address; it indexes the sealed
/// memento in the typed descent
/// `rendezvous → kit → source → functions → assertions → facts → SourceMemento[path]`.
///
/// **No deeper nesting for fact/universe:** factory truth is site ≡ assertion ≡
/// fact (same kind=contract memento / leaf span). Universe is linked off the
/// call site (claim-side join), not a nested leaf under assertion — its path
/// is the owning site's path; its memento is the function-contract seal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MementoPath {
    pub file: String,
    pub function: Option<MementoPathFunction>,
    /// Call-site / assertion / fact leaf within the function (factory 1:1:
    /// site ≡ assertion ≡ fact share the same leaf span under one memento).
    pub leaf: Option<MementoPathLeaf>,
}

/// Function segment of a [`MementoPath`]: `file[name@span]`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MementoPathFunction {
    pub name: String,
    pub span: SrcSpan,
}

/// Leaf segment (call site / assertion / fact / site-linked universe) within a function.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MementoPathLeaf {
    pub span: SrcSpan,
}

impl MementoPath {
    /// File-only path: `SourceMemento[file]`.
    pub fn file(file: impl Into<String>) -> Self {
        Self {
            file: file.into(),
            function: None,
            leaf: None,
        }
    }

    /// Path for a function node: `SourceMemento[file[fn]]`.
    pub fn for_function(memento: &SourceMemento) -> Self {
        Self {
            file: memento.file.clone(),
            function: Some(MementoPathFunction {
                name: memento.function_name.clone(),
                span: memento.span.clone(),
            }),
            leaf: None,
        }
    }

    /// Path for a call-site / assertion / fact under a function:
    /// `SourceMemento[file[fn[leaf]]]`.
    pub fn for_site_under(function: &SourceMemento, site: &SourceMemento) -> Self {
        Self {
            file: function.file.clone(),
            function: Some(MementoPathFunction {
                name: function.function_name.clone(),
                span: function.span.clone(),
            }),
            leaf: Some(MementoPathLeaf {
                span: site.span.clone(),
            }),
        }
    }

    /// Stable display form of the path index (not a CID).
    pub fn display(&self) -> String {
        let mut s = self.file.clone();
        if let Some(ref f) = self.function {
            s.push('[');
            s.push_str(&f.name);
            if !span_is_degenerate(&f.span) {
                s.push('@');
                s.push_str(&span_display(&f.span));
            }
            if let Some(ref leaf) = self.leaf {
                s.push('[');
                if !span_is_degenerate(&leaf.span) {
                    s.push_str(&span_display(&leaf.span));
                } else {
                    s.push_str("leaf");
                }
                s.push(']');
            }
            s.push(']');
        }
        s
    }
}

/// Content-addressed [`SourceMemento`] addressed by nested [`MementoPath`].
///
/// - **path** — typed descent address (`file[fn[site]]`)
/// - **memento** — CID-keyed seal that crosses the wire
///
/// Fragment stays local; never stored here.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceMementoAtPath {
    pub path: MementoPath,
    pub memento: SourceMemento,
}

impl SourceMementoAtPath {
    pub fn new(path: MementoPath, memento: SourceMemento) -> Self {
        Self { path, memento }
    }

    pub fn path_display(&self) -> String {
        self.path.display()
    }
}

fn span_is_degenerate(span: &SrcSpan) -> bool {
    span.start_line == 0
        && span.start_col == 0
        && span.end_line == 0
        && span.end_col == 0
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
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KitConn {
    pub surface: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub workspace_root: PathBuf,
}

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Implication {
    pub pre: IrFormulaPlaceholder,
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
/// Path is the owning [`CallSite`]'s nested address (descent index); memento
/// is the function-contract seal (often a different CID / name than the site).
#[derive(Debug, Clone, PartialEq)]
pub struct Universe {
    memento: SourceMemento,
    /// Nested path of the linking call site: `SourceMemento[file[fn[site]]]`.
    path: MementoPath,
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

    /// Nested path of the linking call site (`file[fn[site]]`).
    pub fn path(&self) -> &MementoPath {
        &self.path
    }

    /// Universe seal at the linking site's path (wire currency + descent index).
    pub fn memento_at_path(&self) -> SourceMementoAtPath {
        SourceMementoAtPath::new(self.path.clone(), self.memento.clone())
    }

    /// Full IR row from wire audit (formals, post/pre/inv, bridgeSourceSymbol).
    pub fn ir_row(&self) -> Option<&Value> {
        self.ir_row.as_ref()
    }

    /// Wire formula payload when present (inv-else-post reduction).
    pub fn payload(&self) -> Option<&Value> {
        self.payload.as_ref()
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
    /// Nested path address: `SourceMemento[file[fn[site]]]` (T #3809).
    path: MementoPath,
    audit: Option<AuditRow>,
    /// Join key for universe/bridge, e.g. `"call:len"` | `"method:count"`.
    /// Decoded from the wire audit's `bridgeSourceSymbol` (prefix preserved).
    bridge_source_symbol: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Assertion {
    conn: KitConn,
    memento: SourceMemento,
    /// Nested path address: `SourceMemento[file[fn[assertion]]]` (T #3809).
    /// Factory 1:1 with CallSite — same leaf span under the enclosing function.
    path: MementoPath,
    audit: Option<AuditRow>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Fact {
    memento: SourceMemento,
    /// Nested path address: `SourceMemento[file[fn[fact]]]` (T #3809).
    /// Factory 1:1 with Assertion / CallSite — same leaf under the function.
    path: MementoPath,
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

    /// Nested path index for this fact (`file[fn[leaf]]`).
    /// Same address shape as the owning assertion / call site (factory 1:1).
    pub fn path(&self) -> &MementoPath {
        &self.path
    }

    /// Utterance leaf: sealed memento keyed by nested path (wire currency + path).
    pub fn memento_at_path(&self) -> SourceMementoAtPath {
        SourceMementoAtPath::new(self.path.clone(), self.memento.clone())
    }

    pub fn payload(&self) -> &IrFormula {
        &self.payload
    }

    /// Full IR row from wire audit when the kit stamped the contract item.
    pub fn ir_row(&self) -> Option<&Value> {
        self.ir_row.as_ref()
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

    /// Nested path index for this site (`file[fn[site]]`).
    pub fn path(&self) -> &MementoPath {
        &self.path
    }

    /// Leaf address: sealed memento keyed by nested path (wire currency + path).
    pub fn memento_at_path(&self) -> SourceMementoAtPath {
        SourceMementoAtPath::new(self.path.clone(), self.memento.clone())
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

    /// Nested path index for this assertion (`file[fn[assertion]]`).
    /// Same address shape as the owning call site (factory 1:1).
    pub fn path(&self) -> &MementoPath {
        &self.path
    }

    /// Claim-side leaf address: sealed memento keyed by nested path.
    pub fn memento_at_path(&self) -> SourceMementoAtPath {
        SourceMementoAtPath::new(self.path.clone(), self.memento.clone())
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
    use std::io::{BufRead, BufReader, Write};
    use std::process::{Command, Stdio};

    let plugin = conn.surface.clone();
    if conn.command.is_empty() {
        return Err(EnumerateError::Unavailable {
            plugin,
            reason: "empty command".to_string(),
        });
    }
    let mut cmd = Command::new(&conn.command[0]);
    if conn.command.len() > 1 {
        cmd.args(&conn.command[1..]);
    }
    if !conn.command.iter().any(|a| a == "--rpc") {
        cmd.arg("--rpc");
    }
    if let Some(wd) = &conn.working_dir {
        cmd.current_dir(wd);
    }
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::inherit());

    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(error) => {
            return Err(EnumerateError::Unavailable {
                plugin,
                reason: format!("spawn {:?}: {error}", conn.command),
            });
        }
    };
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| EnumerateError::StdinUnavailable {
            plugin: plugin.clone(),
        })?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| EnumerateError::StdoutUnavailable {
            plugin: plugin.clone(),
        })?;
    let mut reader = BufReader::new(stdout);

    let req = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.enumerate",
        "params": {
            "level": level.wire(),
            "at": at,
            "seek": seek,
            "workspace_root": conn.workspace_root.display().to_string(),
        },
    });
    writeln!(stdin, "{req}").map_err(|source| EnumerateError::Write {
        plugin: plugin.clone(),
        source,
    })?;

    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|source| EnumerateError::Read {
            plugin: plugin.clone(),
            source,
        })?;

    let shutdown = json!({"jsonrpc": "2.0", "id": 2, "method": "sugar.plugin.shutdown"});
    let _ = writeln!(stdin, "{shutdown}");
    drop(stdin);
    let _ = child.wait();

    if line.trim().is_empty() {
        return Err(EnumerateError::Unavailable {
            plugin,
            reason: "kit closed without a sugar.enumerate response".to_string(),
        });
    }
    let response: Value =
        serde_json::from_str(line.trim()).map_err(|source| EnumerateError::InvalidJson {
            plugin: plugin.clone(),
            source,
            raw: line.trim().to_string(),
        })?;
    if let Some(error) = response.get("error") {
        return Err(EnumerateError::RpcError {
            plugin,
            error: error.clone(),
        });
    }
    let result = response.get("result").cloned().unwrap_or(Value::Null);
    let nodes = result
        .get("nodes")
        .and_then(Value::as_array)
        .map(|arr| arr.iter().map(decode_node).collect::<Result<Vec<_>, _>>())
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

impl Kit {
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
    /// Path for this function node: `SourceMemento[file[fn]]`.
    pub fn path(&self) -> MementoPath {
        MementoPath::for_function(&self.memento)
    }

    /// Sealed memento at this function's path.
    pub fn memento_at_path(&self) -> SourceMementoAtPath {
        SourceMementoAtPath::new(self.path(), self.memento.clone())
    }

    pub fn call_sites(&self) -> Result<Vec<CallSite>, KitError> {
        let (nodes, _gaps) = enumerate_rpc(
            &self.conn,
            Level::CallSites,
            Some(self.memento.to_json()),
            false,
        )?;
        // Client-side span filter (matches kit): when this function memento has
        // a real span, drop sites whose span is outside it (path address law).
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
            .map(|n| {
                let path = MementoPath::for_site_under(&self.memento, &n.memento);
                CallSite {
                    conn: self.conn.clone(),
                    path,
                    memento: n.memento,
                    bridge_source_symbol: decode_bridge_source_symbol(n.audit.as_ref()),
                    audit: n.audit.as_ref().map(AuditRow::from_json),
                }
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
        let path = MementoPath::for_site_under(&self.memento, &node.memento);
        Ok(CallSite {
            conn: self.conn.clone(),
            path,
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
            .map(|n| {
                // Factory 1:1: assertion leaf path ≡ owning call-site path
                // (`file[fn[leaf]]`). Path is a derived index; memento seals content.
                let path = self.path.clone();
                Assertion {
                    conn: self.conn.clone(),
                    path,
                    memento: n.memento,
                    audit: n.audit.as_ref().map(AuditRow::from_json),
                }
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
        // Same nested address as the site (factory 1:1 leaf under function).
        let path = self.path.clone();
        Ok(Assertion {
            conn: self.conn.clone(),
            path,
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
        // Path = this site's nested address (descent index). Memento = the
        // function-contract seal (may differ from the site memento).
        let path = self.path.clone();
        Ok(nodes.into_iter().next().map(|n| Universe {
            path: path.clone(),
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

    /// LINK-time obligation side: never minted by this pass.
    pub fn implication(&self) -> Option<Implication> {
        None
    }
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
            // Factory 1:1: fact leaf path ≡ owning assertion path
            // (`file[fn[leaf]]`). Path is a derived index; memento seals content.
            let path = self.path.clone();
            out.push(Fact {
                path,
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
}
