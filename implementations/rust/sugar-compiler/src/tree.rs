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
// its [`SourceMemento`] (`file` + `function_name` + `span` + CIDs). A prior
// `MementoPath` / `SourceMementoAtPath` layer re-encoded memento fields and
// was collapsed — SourceMemento is already the strong type.
// Fragment stays LOCAL (kit/oracle); memento (CID + locus) crosses the wire.
//
// ONE DOOR (#7757 entry 5 / item 25): the whole-tree walk is
// `fold_enumerate_source_tree` (`source_files` -> per-file `universe`), the
// walk mint drives and `sugar lift` reads. There is no second walk of the kit
// at `functions` / `call_sites` / `assertions` / `facts`.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use libsugar::core::{SourceMemento, SrcSpan};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sugar_ir_types::Sort;
use sugar_linker::LinkerContract;

use crate::kit::{Kit, KitError};
use crate::kit_path::LiftTermTable;
use sugar_proof_envelope::contains_term_ref;

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

/// The enumeration levels `sugar.enumerate` answers. Wire value is the
/// snake_case name in the protocol spec
/// (`protocol/specs/2026-07-08-enumeration-protocol.md`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Level {
    SourceFiles,
    Universe,
    Exports,
    ProviderContractMembers,
    ParameterContractLinkUnits,
    ParameterContractResume,
}

impl Level {
    fn wire(self) -> &'static str {
        match self {
            Level::SourceFiles => "source_files",
            Level::Universe => "universe",
            Level::Exports => "exports",
            Level::ProviderContractMembers => "provider-contract-members",
            Level::ParameterContractLinkUnits => "parameter-contract-link-units",
            Level::ParameterContractResume => "parameter-contract-resume",
        }
    }
}

/// Everything an enumeration RPC needs to reach the SAME kit connection:
/// surface/command/working_dir identity plus the project root being
/// enumerated. `Kit::enumerate_conn` clones the Kit-owned `LiftPluginKit`
/// with method `sugar.enumerate` (#3855 pool single-owner) so lift and
/// enumerate share one Drop-scoped resident. Distinct from
/// `resolve_source`/`resolve_testimony`, which still one-shot spawn outside
/// that connection (residual outside this membrane).
#[derive(Debug, Clone)]
pub struct KitConn {
    pub surface: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub workspace_root: PathBuf,
    pub transport: crate::kit_path::LiftPluginKit,
}

impl PartialEq for KitConn {
    fn eq(&self, other: &Self) -> bool {
        self.surface == other.surface
            && self.command == other.command
            && self.working_dir == other.working_dir
            && self.workspace_root == other.workspace_root
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
    /// A singular seek (`Kit::export`) found no matching node -- distinct
    /// from a wire/decode failure.
    #[error(
        "sugar.enumerate seek on `{plugin}` at level `{level}` found no node for the given memento"
    )]
    SeekMiss { plugin: String, level: &'static str },
    /// `universe()`-style claim data the current kit-side
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
    // A WITNESS kit (pytest-witness, cargo-test-witness) folds its signed
    // WitnessMemento through the same audit channel as the contract that
    // memento pins -- there is no second wire for it. Mint dispatches
    // `witness-memento` rows straight out of `response["ir"]`
    // (`cmd_mint::mint_witness_memento`), so dropping the row here would
    // strip the proof's ONLY pointer to the witness body and leave the
    // custom-evidence contract permanently undischargeable.
    if kind == "witness-memento" {
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

/// True when a wire row is a kit's `undecided` row: a function refused by
/// name (step 8; one member kind for what a proof does not decide).
fn is_undecided_row(value: &Value) -> bool {
    value.get("kind").and_then(Value::as_str) == Some("undecided")
}

/// True when a wire row is a harvested call edge. Call edges are NOT IR
/// contract rows -- they carry the caller side of a bridge (`targetSymbol`,
/// `targetContract`/`targetContractCid`) that mint joins to a contract. They
/// pass none of `looks_like_ir_contract_row`'s predicates, so the fold has to
/// collect them on their own channel or they are dropped silently.
fn looks_like_call_edge_row(value: &Value) -> bool {
    value
        .get("kind")
        .and_then(Value::as_str)
        .is_some_and(|kind| kind == "call-edge")
}

/// First-writer-wins accumulation of call-edge rows in enumeration order,
/// with the counters that tell the two zero-states apart.
///
/// Duplicates are real: the same edge reaches the fold both inside a
/// parameter-contract link unit and as a universe-level audit row.
///
/// The counters exist because `callEdges: []` has two very different causes
/// and the array alone cannot distinguish them: no rows arrived at the fold
/// at all (a transport gap -- the kit is not emitting, or is not emitting
/// where the fold looks), versus rows arrived but carry no `targetContract`
/// (the kit's join declined, which for an ambiguous symbol is the correct
/// answer and not a defect). `sourceLedger.call_edges` collapses both to a
/// number.
#[derive(Default)]
struct CallEdgeHarvest {
    seen: BTreeSet<String>,
    edges: Vec<Value>,
    /// Rows that reached the harvest, before de-duplication.
    arrived: usize,
    /// Distinct edges retained that carry no resolved `targetContract`.
    unresolved_target: usize,
}

impl CallEdgeHarvest {
    fn push(&mut self, edge: &Value) {
        self.arrived += 1;
        if self.seen.insert(canonical_row_key(edge)) {
            if !edge_has_resolved_target(edge) {
                self.unresolved_target += 1;
            }
            self.edges.push(edge.clone());
        }
    }

    /// The single routing decision for a wire audit row: contract-shaped rows
    /// go to `ir`, call edges go to the `callEdges` channel, and a call edge
    /// never goes to both. Mint reads `callEdges` as a top-level field and
    /// does not scan `ir` for edges, so a `kind: "call-edge"` row left in
    /// `ir` is both a dropped edge and a non-contract row published into the
    /// IR document (see issue #6251).
    fn route_audit(&mut self, ir: &mut Vec<Value>, audit: &Value) {
        if looks_like_ir_contract_row(audit) || is_undecided_row(audit) {
            // An `undecided` row is what the proof does not decide (step 8):
            // it goes to `ir`, where mint turns it into its member. It never
            // reaches the contract mint (that reads `contract` kinds only).
            ir.push(audit.clone());
        } else if looks_like_call_edge_row(audit) {
            self.push(audit);
        }
    }

    fn walk_counters(&self) -> Value {
        json!({
            "arrived": self.arrived,
            "retained": self.edges.len(),
            "unresolvedTarget": self.unresolved_target,
        })
    }
}

/// True when the kit's join resolved this edge's target. The kit resolves
/// `targetContract` only when the symbol is unambiguous and deliberately
/// leaves it absent otherwise (`verify_rpc.py`, `len(candidates) == 1`), so
/// absent is a legitimate outcome and must be counted, not repaired here.
fn edge_has_resolved_target(edge: &Value) -> bool {
    ["targetContract", "targetContractCid"].iter().any(|key| {
        edge.get(*key)
            .and_then(Value::as_str)
            .is_some_and(|value| !value.is_empty())
    })
}

/// Stable identity for de-duplication. This crate builds `serde_json` with
/// `preserve_order`, so `Value::to_string` is insertion-order dependent and
/// two producers emitting the same edge with different key order would not
/// dedupe. Sort keys recursively first. Deliberately NOT `jcs_cid_of_json`:
/// that panics on non-integer numbers, and a dedupe key must not be able to
/// abort the fold over a value it was only asked to compare.
fn canonical_row_key(value: &Value) -> String {
    fn sorted(value: &Value) -> Value {
        match value {
            Value::Object(map) => {
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                let mut out = Map::new();
                for key in keys {
                    out.insert(key.clone(), sorted(&map[key]));
                }
                Value::Object(out)
            }
            Value::Array(items) => Value::Array(items.iter().map(sorted).collect()),
            other => other.clone(),
        }
    }
    sorted(value).to_string()
}

/// One raw node the wire returned, before it is dressed into a typed
/// node. Never escapes this module.
struct WireNode {
    memento: SourceMemento,
    audit: Option<Value>,
    payload: Option<Value>,
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
    enumerate_rpc_with_extra(conn, level, at, seek, &[])
}

/// Request the Phase-3 resume level for one continuation: the kit checks the
/// resolution set against the link unit it retained. The answer is an
/// ordinary enumeration result, decoded by the one decoder, and carries no
/// node: every function's rows come from the universe scan, the one door
/// (#7757).
fn resume_rpc(
    conn: &KitConn,
    link_unit_cid: &Value,
    resolution_set: &Value,
) -> Result<(), EnumerateError> {
    let plugin = conn.surface.clone();
    let mut resume_options = json!({
        "linkUnitCid": link_unit_cid,
        "resolutionSet": resolution_set,
    });
    for (key, value) in bound_generation_options(conn)? {
        resume_options[key.as_str()] = value;
    }
    let response = conn
        .transport
        .request(&json!({
            "level": Level::ParameterContractResume.wire(),
            "workspace_root": conn.workspace_root.display().to_string(),
            "options": resume_options,
        }))
        .map_err(|error| EnumerateError::Unavailable {
            plugin: plugin.clone(),
            reason: error.to_string(),
        })?;
    let result = enumerate_result_from_response(&plugin, response)?;
    if result.get("nodes").and_then(Value::as_array).is_none() {
        return Err(EnumerateError::Malformed {
            plugin,
            reason: "resume response missing nodes array".into(),
        });
    }
    let (nodes, _gaps) = decode_enumerate_result(&plugin, &result)?;
    if !nodes.is_empty() {
        return Err(EnumerateError::Malformed {
            plugin,
            reason: format!(
                "resume answered {} rows; a function's rows come from the universe scan",
                nodes.len()
            ),
        });
    }
    Ok(())
}

fn enumerate_rpc_with_extra(
    conn: &KitConn,
    level: Level,
    at: Option<Value>,
    seek: bool,
    extra_options: &[(&str, Value)],
) -> Result<(Vec<WireNode>, Vec<GapInfo>), EnumerateError> {
    let plugin = conn.surface.clone();
    if conn.command.is_empty() {
        return Err(EnumerateError::Unavailable {
            plugin,
            reason: "empty command".to_string(),
        });
    }
    let mut options = json!({});
    for (key, value) in bound_generation_options(conn)? {
        options[key.as_str()] = value;
    }
    for (key, value) in extra_options {
        options[*key] = value.clone();
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
    decode_enumerate_result(&plugin, &result)
}

/// Decode one enumeration result: resolve its term DAG through the result's
/// own `termTable` (a term-ref with no table is malformed), then decode nodes
/// and gaps. Every kit answer that carries terms goes through here.
fn decode_enumerate_result(
    plugin: &str,
    result: &Value,
) -> Result<(Vec<WireNode>, Vec<GapInfo>), EnumerateError> {
    let plugin = plugin.to_string();
    let raw_nodes = result.get("nodes").and_then(Value::as_array);
    let response_has_term_refs = raw_nodes.is_some_and(|nodes| nodes.iter().any(contains_term_ref))
        || result.get("gaps").is_some_and(contains_term_ref);
    let term_table = if result.get("termTable").is_some() {
        Some(
            LiftTermTable::decode(result).map_err(|reason| EnumerateError::Malformed {
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

/// The ref generations bound into this connection, as request options. ONE
/// place stamps them: every `sugar.enumerate` request carries the generation
/// the kit holds, and the kit refuses a request that does not. With nothing
/// bound this is empty and the request is unchanged.
fn bound_generation_options(conn: &KitConn) -> Result<Vec<(String, Value)>, EnumerateError> {
    let unavailable = |error: String| EnumerateError::Unavailable {
        plugin: conn.surface.clone(),
        reason: error,
    };
    let mut options = Vec::new();
    if let Some((catalog_cid, table_cid)) = conn
        .transport
        .contract_ref_generation()
        .map_err(|error| unavailable(error.to_string()))?
    {
        options.push((
            "contractRefs".to_string(),
            json!({"catalogCid": catalog_cid, "tableCid": table_cid}),
        ));
    }
    Ok(options)
}

fn preconstruction_rows_rpc(conn: &KitConn, level: Level) -> Result<Vec<Value>, EnumerateError> {
    let plugin = conn.surface.clone();
    let mut request = json!({
        "level": level.wire(),
        "workspace_root": conn.workspace_root.display().to_string(),
    });
    let generation = bound_generation_options(conn)?;
    if !generation.is_empty() {
        let mut options = serde_json::Map::new();
        for (key, value) in generation {
            options.insert(key, value);
        }
        request["options"] = Value::Object(options);
    }
    let response =
        conn.transport
            .request(&request)
            .map_err(|error| EnumerateError::Unavailable {
                plugin: plugin.clone(),
                reason: error.to_string(),
            })?;
    let result = response
        .get("result")
        .unwrap_or(&response)
        .as_object()
        .ok_or_else(|| EnumerateError::Malformed {
            plugin: plugin.clone(),
            reason: "preconstruction response result must be an object".into(),
        })?;
    result
        .get("rows")
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| EnumerateError::Malformed {
            plugin,
            reason: "preconstruction response missing rows array".into(),
        })
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

/// Enumerate the **entire** source tree and fold function-contract IR.
///
/// There is no `lift` RPC. What used to be called "lift" is this walk:
/// `source_files` → per-file `universe` (all function contracts). Mint and
/// any other full-tree client must call this and must never send JSON-RPC
/// method `"lift"`.
pub fn fold_enumerate_source_tree(kit: &Kit, workspace_root: &Path) -> Result<Value, KitError> {
    let conn = kit.enumerate_conn(workspace_root);
    let (files, source_gaps) = enumerate_rpc(&conn, Level::SourceFiles, None, false)?;
    if !source_gaps.is_empty() {
        return Err(EnumerateError::Malformed {
            plugin: conn.surface.clone(),
            reason: format!("source census returned {} gaps", source_gaps.len()),
        }
        .into());
    }
    let mut ir = Vec::new();
    let mut source_mementos = Vec::new();
    let mut diagnostics = Vec::new();
    // Call edges travel their own channel: mint reads `callEdges` off this
    // response (`cmd_mint.rs` `response_has_call_edges` / the bridge merge)
    // and synthesizes bridges from it. Absent is NOT the same as empty --
    // absent means mint synthesizes no bridge and the run still completes.
    let mut call_edges = CallEdgeHarvest::default();

    // Phase 2/3: over the COMPLETELY enumerated project, discharge every enrolled
    // parameter-contract link unit (fold), then RESUME each retained link unit
    // with its authenticated resolution set. The resume states no row: every
    // function's rows come from the universe scan below, the one door (#7757).
    // A link unit records no call: a Python call's only record is its
    // `undecided` member, which the universe scan below routes to `ir`
    // (step 8; PR B on #7766). The unit's caller-side edge list is gone.
    let link_unit_rows = preconstruction_rows_rpc(&conn, Level::ParameterContractLinkUnits)?;
    if !link_unit_rows.is_empty() {
        let units: Vec<sugar_linker::caller_parameter::ParameterContractLinkUnitV1> =
            link_unit_rows
                .iter()
                .map(|row| serde_json::from_value(row.clone()))
                .collect::<Result<_, _>>()
                .map_err(|error| EnumerateError::Malformed {
                    plugin: conn.surface.clone(),
                    reason: format!("parameter-contract link unit deserialize: {error}"),
                })?;
        // Per-unit tolerant: a unit that cannot fully discharge (e.g. an open
        // caller universe) is LEFT unresolved -- its post() stays a conserved
        // panic-gap, exactly as before this feature. A single un-dischargeable
        // demand never aborts the rest of the project.
        for unit in &units {
            let set = match sugar_linker::caller_parameter::fold_one_link_unit(unit, &units) {
                Ok(set) => set,
                Err(gap) => {
                    diagnostics.push(json!({
                        "reason": format!("parameter-contract demand unresolved: {gap:?}"),
                        "item": unit
                            .source_memento
                            .get("source_function_name")
                            .cloned()
                            .unwrap_or(Value::Null),
                    }));
                    continue;
                }
            };
            let cid_value = serde_json::to_value(&unit.link_unit_cid).unwrap();
            let set_value = serde_json::to_value(&set).unwrap();
            resume_rpc(&conn, &cid_value, &set_value)?;
        }
    }

    for file in files {
        source_mementos.push(file.memento.to_json());
        let (nodes, gaps) =
            enumerate_rpc(&conn, Level::Universe, Some(file.memento.to_json()), false)?;
        for gap in gaps {
            let item = gap
                .memento
                .as_ref()
                .and_then(|m| m.source_function_name())
                .map(|name| Value::String(name.to_string()))
                .unwrap_or(Value::Null);
            diagnostics.push(json!({
                "path": file.memento.file,
                "reason": gap.reason,
                "item": item,
            }));
        }
        for node in nodes {
            if let Some(audit) = node.audit {
                call_edges.route_audit(&mut ir, &audit);
            }
        }
    }
    let call_edge_walk = call_edges.walk_counters();
    let call_edge_count = call_edges.edges.len();
    Ok(json!({
        "kind": "ir-document",
        "ir": ir,
        "callEdges": call_edges.edges,
        "sourceMementos": source_mementos,
        "diagnostics": diagnostics,
        "callEdgeWalk": call_edge_walk,
        "sourceLedger": {
            "source_files": source_mementos.len(),
            "contracts": ir.iter().filter(|row| !is_undecided_row(row)).count(),
            "undecided": ir.iter().filter(|row| is_undecided_row(row)).count(),
            "call_edges": call_edge_count,
        },
    }))
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
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A witness kit has no second wire for its signed memento: it rides the
    /// same `audit` channel as the contract it pins, and mint dispatches
    /// `witness-memento` straight out of `response["ir"]`. If the fold's row
    /// filter drops it, the proof loses its only pointer to the witness body
    /// and the custom-evidence contract can never discharge.
    #[test]
    fn ir_row_filter_admits_witness_mementos() {
        assert!(looks_like_ir_contract_row(&json!({
            "kind": "witness-memento",
            "witness_cid": "blake3-512:abc",
            "witness_kind": "pytest-witness-package",
            "signer": "ed25519:k",
            "signature": "ed25519:s",
        })));
    }

    #[test]
    fn ir_row_filter_still_admits_contracts_and_rejects_non_rows() {
        assert!(looks_like_ir_contract_row(&json!({"kind": "contract"})));
        assert!(looks_like_ir_contract_row(
            &json!({"kind": "function-contract"})
        ));
        assert!(looks_like_ir_contract_row(&json!({"inv": {}})));
        // Not an IR row: no recognized kind and no body slot.
        assert!(!looks_like_ir_contract_row(
            &json!({"kind": "source-memento"})
        ));
        assert!(!looks_like_ir_contract_row(&json!({"kind": "term-ref"})));
        assert!(!looks_like_ir_contract_row(&json!("not an object")));
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

    /// #7843: an answer whose audits state terms by reference is resolved
    /// through its own `termTable` into inline terms; without the table it is
    /// malformed, never passed on with the references in it.
    #[test]
    fn an_answer_with_term_refs_resolves_through_its_own_table() {
        let out = json!({"kind": "var", "name": "out"});
        let cid = sugar_canonicalizer::jcs_cid_of_json(&out);
        let node = json!({
            "memento": {"file": "idn.py"},
            "audit": {"post": {"kind": "atomic", "name": "=", "args": [
                {"kind": "term-ref", "cid": cid}
            ]}}
        });
        let (nodes, _) = decode_enumerate_result(
            "fixture-kit",
            &json!({"nodes": [node.clone()], "gaps": [], "termTable": {(cid.clone()): out}}),
        )
        .expect("closed answer decodes");
        let audit = nodes[0].audit.as_ref().expect("audit");
        assert_eq!(
            audit["post"]["args"][0],
            json!({"kind": "var", "name": "out"})
        );
        assert!(!sugar_proof_envelope::contains_term_ref(audit));

        let refused = decode_enumerate_result("fixture-kit", &json!({"nodes": [node], "gaps": []}));
        assert!(
            matches!(refused, Err(EnumerateError::Malformed { .. })),
            "a term-ref without its table is malformed"
        );
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

    // ---- call-edge channel (PR 1) ----------------------------------------
    //
    // These drive `CallEdgeHarvest::route_audit`, the one routing decision
    // `fold_enumerate_source_tree` makes per wire audit row, over fixture
    // rows. They are deliberately NOT a live kit run: the enumerate path may
    // carry no edges until the Python source surface is ported (PR 2), so a
    // guard written against a real run would be green-because-empty. A
    // fixture guard fails today if the channel regresses, which is the point.

    fn contract_row(name: &str) -> Value {
        json!({
            "kind": "contract",
            "name": name,
            "formals": [],
            "post": [],
        })
    }

    fn call_edge_row(source: &str, symbol: &str, line: usize) -> Value {
        json!({
            "kind": "call-edge",
            "sourceContract": source,
            "targetSymbol": symbol,
            "targetContract": symbol,
            "callSiteLocus": {"file": "consumer.py", "line": line, "column": 4},
        })
    }

    fn route_all(rows: &[Value]) -> (Vec<Value>, CallEdgeHarvest) {
        let mut ir = Vec::new();
        let mut harvest = CallEdgeHarvest::default();
        for row in rows {
            harvest.route_audit(&mut ir, row);
        }
        (ir, harvest)
    }

    #[test]
    fn call_edge_rows_never_land_in_ir() {
        let (ir, harvest) =
            route_all(&[contract_row("double"), call_edge_row("main", "double", 7)]);

        assert!(
            !ir.iter()
                .any(|row| row.get("kind") == Some(&json!("call-edge"))),
            "ir must stay contract-shaped: mint copies every ir row into the \
             published document without a shape filter (issue #6251), and it \
             reads edges off the top-level callEdges field, never out of ir"
        );
        assert_eq!(ir.len(), 1, "the contract row is still collected");
        assert_eq!(harvest.edges.len(), 1, "the edge went to its own channel");
    }

    #[test]
    fn undecided_rows_land_in_ir_for_mint_to_package() {
        let undecided = json!({
            "kind": "undecided",
            "symbol": "python:m.f",
            "site": {"file": "m.py", "sourceCid": "blake3-512:aa", "startLine": 4,
                     "startCol": 0, "endLine": 5, "endCol": 20},
            "reason": {"refused": {"owner": "proofir.scope",
                                   "observed": "illegal free var(s): LIMIT"}},
        });
        let (ir, harvest) = route_all(&[contract_row("g"), undecided.clone()]);

        assert_eq!(
            ir,
            vec![contract_row("g"), undecided],
            "a refused function's undecided row reaches mint, never dropped"
        );
        assert!(harvest.edges.is_empty());
    }

    #[test]
    fn call_edges_channel_is_non_empty_for_an_edge_bearing_fixture() {
        let (_ir, harvest) = route_all(&[call_edge_row("main", "double", 7)]);

        assert!(
            !harvest.edges.is_empty(),
            "the enumerate fold must emit callEdges non-empty when edge rows \
             reach it; absent or empty means mint synthesizes no bridge and \
             the run still completes green"
        );
        assert_eq!(harvest.edges[0]["targetSymbol"], json!("double"));
    }

    #[test]
    fn duplicate_edges_dedupe_across_key_order() {
        let edge = call_edge_row("main", "double", 7);
        let reordered = json!({
            "callSiteLocus": {"line": 7, "column": 4, "file": "consumer.py"},
            "targetContract": "double",
            "targetSymbol": "double",
            "sourceContract": "main",
            "kind": "call-edge",
        });
        let (_ir, harvest) = route_all(&[edge, reordered]);

        assert_eq!(
            harvest.edges.len(),
            1,
            "the same edge arrives both inside a link unit and as a \
             universe-level audit; serde_json preserve_order makes raw \
             to_string insertion-order dependent, so the key must sort first"
        );
        assert_eq!(harvest.arrived, 2, "both arrivals are still counted");
    }

    #[test]
    fn walk_counters_separate_no_rows_from_unresolved_targets() {
        // Bumble's distinction: `callEdges: []` cannot tell a transport gap
        // (nothing arrived) from a kit that declined to resolve an ambiguous
        // symbol. The kit sets targetContract only when len(candidates) == 1,
        // so an absent target is a correct answer, not a defect.
        let (_ir, nothing) = route_all(&[contract_row("double")]);
        assert_eq!(
            nothing.walk_counters(),
            json!({"arrived": 0, "retained": 0, "unresolvedTarget": 0}),
            "no edge rows reached the fold at all"
        );

        let mut ambiguous = call_edge_row("main", "double", 7);
        ambiguous.as_object_mut().unwrap().remove("targetContract");
        let (_ir, declined) = route_all(&[ambiguous]);
        assert_eq!(
            declined.walk_counters(),
            json!({"arrived": 1, "retained": 1, "unresolvedTarget": 1}),
            "a row arrived carrying no targetContract -- a different state \
             from nothing arriving, and sourceLedger.call_edges collapses both"
        );
    }
}
