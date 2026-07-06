// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar compose --rpc`: JSON-RPC subprocess transport for the
// canonical compose primitive per CCP §6.3.
//
// The CLI subcommand is a thin wrapper over `libsugar::compose::
// compose_chain_contracts`. It is the third binding mode named by the
// Contract Composition Protocol (after direct Rust linking and the
// C ABI FFI). Consumers that cannot link Rust (TypeScript, Python,
// Ruby, PHP lifters running in their own runtime) spawn `sugar
// compose --rpc` and exchange JSON-RPC messages over stdin / stdout.
//
// Wire shape, per CCP §6.3:
//
//   -> initialize { }
//   <- result { protocol_version: "sugar-compose/1",
//               ccp_version: "<libsugar::compose::CCP_VERSION>" }
//
//   -> compose  { atoms: [...], effects: [...] }
//   <- result   { composed_cid: "blake3-512:...", body_jcs: "..." }
//   OR
//   <- error    { code, message, atom_cid? }
//
//   -> shutdown
//   <- result null
//
// Deviations from §6.3 (called out in the spec freeze for v1):
//
//   1. Each entry in `atoms` carries an optional `formal_idx` field
//      (default 0). The canonical primitive in libsugar takes
//      `&[ChainStep { contract, formal_idx }]`; without per-step
//      `formal_idx` the wire format cannot reproduce the pinned CID
//      for any chain whose composition does not happen at formal 0.
//      The compose smoke test in libsugar uses formal_idx 0 for
//      both steps, so the default-0 path is the conformance witness.
//
//   2. The top-level `effects` parameter is preserved per spec but is
//      treated as advisory: each FunctionContractMemento already
//      carries its own `effects` field (libsugar::compose::EffectSet).
//      When `effects[i]` is provided AND the atom's embedded effects
//      differ, the request is rejected with an effects-mismatch error
//      so a careless caller can never silently lose effect information.
//
// The wire-shadow types (Wire*) below mirror libsugar's
// non-serde-deriving compose types byte-for-byte. Every wire struct
// converts to its libsugar counterpart via `.to_lib()`. Conversion
// is lossless and reversible; the resulting FunctionContractMemento's
// canonical_bytes and cid match what libsugar's own
// `pure_identity_contract` helper would produce for the same inputs.

use std::io::{BufRead, BufReader, Write};
use std::sync::Arc;

use libsugar::compose::{
    build_value, cid_of_value, compose_chain_contracts, jcs_bytes_of_value, AliasingMemento,
    AliasingStatus, AtomicKind, ChainStep, Effect, EffectSet, FunctionContractMemento, Locus,
    CCP_VERSION,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};
use sugar_canonicalizer::Value;
use sugar_ir_types::{composition_refusal_header_cid, CompositionBoundaryMemento, IrFormula, Sort};

use crate::ComposeArgs;

/// JSON-RPC method name for the canonical compose entry point.
const PROTOCOL_VERSION: &str = "sugar-compose/1";

/// Error code for refused composition (impure input, formal index out
/// of range, mismatched effects, schema mismatch). The numeric codes
/// stay in the application range (-32000 down) per the JSON-RPC 2.0
/// spec; callers SHOULD switch on the embedded `kind` string.
const ERR_COMPOSE_REFUSED: i64 = -32001;
const ERR_BAD_REQUEST: i64 = -32602;
const ERR_INTERNAL: i64 = -32603;

pub fn run(args: ComposeArgs) -> u8 {
    if !args.rpc {
        eprintln!("error: `sugar compose` only supports the JSON-RPC transport today; pass --rpc");
        return crate::EXIT_USER_ERROR;
    }
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut reader = BufReader::new(stdin.lock());
    let mut writer = stdout.lock();
    serve_loop(&mut reader, &mut writer)
}

fn serve_loop<R: BufRead, W: Write>(reader: &mut R, writer: &mut W) -> u8 {
    let mut line = String::new();
    loop {
        line.clear();
        let n = match reader.read_line(&mut line) {
            Ok(n) => n,
            Err(e) => {
                let _ = writeln!(
                    writer,
                    "{}",
                    json!({
                        "jsonrpc": "2.0",
                        "id": JsonValue::Null,
                        "error": {"code": ERR_INTERNAL, "message": format!("read stdin: {e}")}
                    })
                );
                return crate::EXIT_USER_ERROR;
            }
        };
        if n == 0 {
            // EOF without an explicit shutdown is acceptable; the spec
            // shows shutdown as the polite close but doesn't make it
            // mandatory for clients that have consumed their compose
            // result.
            return crate::EXIT_OK;
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let req: JsonValue = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                let _ = writeln!(
                    writer,
                    "{}",
                    json!({
                        "jsonrpc": "2.0",
                        "id": JsonValue::Null,
                        "error": {"code": ERR_BAD_REQUEST, "message": format!("parse request: {e}")}
                    })
                );
                continue;
            }
        };
        let id = req.get("id").cloned().unwrap_or(JsonValue::Null);
        let method = req
            .get("method")
            .and_then(|m| m.as_str())
            .unwrap_or("")
            .to_string();
        let params = req
            .get("params")
            .cloned()
            .unwrap_or(JsonValue::Object(Default::default()));

        match method.as_str() {
            "initialize" => {
                let _ = writeln!(
                    writer,
                    "{}",
                    json!({
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": {
                            "protocol_version": PROTOCOL_VERSION,
                            "ccp_version": CCP_VERSION,
                        }
                    })
                );
                let _ = writer.flush();
            }
            "compose" => {
                let response = match handle_compose(params) {
                    Ok(payload) => json!({
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": payload,
                    }),
                    Err(err) => {
                        let mut envelope = serde_json::Map::new();
                        envelope.insert("code".into(), JsonValue::from(err.code));
                        envelope.insert("message".into(), JsonValue::from(err.message));
                        envelope.insert("kind".into(), JsonValue::from(err.kind));
                        if let Some(cid) = err.atom_cid {
                            envelope.insert("atom_cid".into(), JsonValue::from(cid));
                        }
                        if let Some(cid) = err.refusal_cid {
                            envelope.insert("refusal_cid".into(), JsonValue::from(cid));
                        }
                        if let Some(refusal) = err.refusal {
                            envelope.insert("refusal".into(), refusal);
                        }
                        json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "error": JsonValue::Object(envelope),
                        })
                    }
                };
                let _ = writeln!(writer, "{}", response);
                let _ = writer.flush();
            }
            "shutdown" => {
                let _ = writeln!(
                    writer,
                    "{}",
                    json!({
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": JsonValue::Null,
                    })
                );
                let _ = writer.flush();
                return crate::EXIT_OK;
            }
            other => {
                let _ = writeln!(
                    writer,
                    "{}",
                    json!({
                        "jsonrpc": "2.0",
                        "id": id,
                        "error": {
                            "code": ERR_BAD_REQUEST,
                            "message": format!("unknown method `{other}`"),
                            "kind": "unknown_method",
                        }
                    })
                );
                let _ = writer.flush();
            }
        }
    }
}

#[derive(Debug)]
struct RpcError {
    code: i64,
    message: String,
    kind: &'static str,
    atom_cid: Option<String>,
    refusal_cid: Option<String>,
    refusal: Option<JsonValue>,
}

impl RpcError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            code: ERR_BAD_REQUEST,
            message: message.into(),
            kind: "bad_request",
            atom_cid: None,
            refusal_cid: None,
            refusal: None,
        }
    }

    fn refused_with_atom(kind: &'static str, message: impl Into<String>, atom_cid: String) -> Self {
        Self {
            code: ERR_COMPOSE_REFUSED,
            message: message.into(),
            kind,
            atom_cid: Some(atom_cid),
            refusal_cid: None,
            refusal: None,
        }
    }

    fn composition_refused(refusal: CompositionBoundaryMemento) -> Self {
        let cid = composition_refusal_header_cid(&refusal.header);
        let refusal_value = serde_json::to_value(&refusal).unwrap_or_else(|e| {
            json!({
                "serialize_error": e.to_string(),
                "header": {"cid": cid}
            })
        });
        Self {
            code: ERR_COMPOSE_REFUSED,
            message: format!(
                "composition refused: cid={cid}; kind={}; detail={}",
                refusal.header.failure_kind, refusal.header.failure_detail
            ),
            kind: "composition_refused",
            atom_cid: None,
            refusal_cid: Some(cid),
            refusal: Some(refusal_value),
        }
    }
}

fn handle_compose(params: JsonValue) -> Result<JsonValue, RpcError> {
    #[derive(Deserialize)]
    struct ComposeParams {
        atoms: Vec<WireFunctionContractMemento>,
        #[serde(default)]
        effects: Option<Vec<WireEffectSet>>,
    }

    let parsed: ComposeParams = serde_json::from_value(params)
        .map_err(|e| RpcError::bad_request(format!("parse compose params: {e}")))?;

    if parsed.atoms.len() < 2 {
        return Err(RpcError::bad_request(
            "compose requires at least two atoms (chain length >= 2)",
        ));
    }

    if let Some(eff) = &parsed.effects {
        if eff.len() != parsed.atoms.len() {
            return Err(RpcError::bad_request(format!(
                "effects array length ({}) must match atoms length ({}) when supplied",
                eff.len(),
                parsed.atoms.len()
            )));
        }
    }

    let mut contracts: Vec<FunctionContractMemento> = Vec::with_capacity(parsed.atoms.len());
    let mut formal_idxs: Vec<usize> = Vec::with_capacity(parsed.atoms.len());

    for (i, wire_atom) in parsed.atoms.iter().enumerate() {
        let contract = wire_atom.to_lib();
        if let Some(eff_param) = parsed.effects.as_ref().and_then(|v| v.get(i)) {
            let advisory = eff_param.to_lib();
            if effect_set_canonical_bytes(&advisory)
                != effect_set_canonical_bytes(&contract.effects)
            {
                return Err(RpcError::refused_with_atom(
                    "effects_mismatch",
                    format!(
                        "atom {i} effect set differs between atom.effects and params.effects[{i}]"
                    ),
                    contract.cid.clone(),
                ));
            }
        }
        formal_idxs.push(wire_atom.formal_idx.unwrap_or(0));
        contracts.push(contract);
    }

    let steps: Vec<ChainStep<'_>> = contracts
        .iter()
        .zip(formal_idxs.iter())
        .map(|(c, idx)| ChainStep {
            contract: c,
            formal_idx: *idx,
        })
        .collect();

    let composed = compose_chain_contracts(&steps).map_err(RpcError::composition_refused)?;

    let body_jcs = String::from_utf8(composed.canonical_bytes.clone()).map_err(|e| RpcError {
        code: ERR_INTERNAL,
        message: format!("composed bytes are not utf-8 JCS: {e}"),
        kind: "internal_error",
        atom_cid: None,
        refusal_cid: None,
        refusal: None,
    })?;

    Ok(json!({
        "composed_cid": composed.cid,
        "body_jcs": body_jcs,
    }))
}

/// Recompute the canonical bytes of an EffectSet so we can compare two
/// sets ignoring vector ordering. Uses libsugar's own `to_value`
/// path indirectly: we call `build_value` with a throwaway harness and
/// extract the effects subtree. Cheaper to do the comparison locally
/// via JCS bytes of a fresh array.
fn effect_set_canonical_bytes(set: &EffectSet) -> Vec<u8> {
    let value = wire_effect_array_value(set);
    jcs_bytes_of_value(&value)
}

fn wire_effect_array_value(set: &EffectSet) -> Arc<Value> {
    // Reuse the same canonicalization libsugar::compose uses inside
    // `build_value`, which sorts effects by their internal sort_key.
    // We don't have direct access to EffectSet::to_value, so we round
    // through build_value with a stub function name and read the
    // `effects` field out via a JCS encode + decode. Cheaper: just
    // compare via build_value-derived CIDs of two stub mementos.
    // Implementation: build a stub memento with no formals / trivial
    // formula, then hash its effects subtree.
    use sugar_ir_types::IrFormula;
    let trivial_pre = IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    };
    let trivial_post = IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    };
    let sort = Sort::Primitive {
        name: "u32".to_string(),
    };
    build_value(
        "__wire_effect_compare__",
        &[],
        &[],
        &sort,
        &trivial_pre,
        &trivial_post,
        None,
        set,
        &Locus::unknown(),
        &[],
    )
}

// ============================================================
// Wire shadow types (mirror libsugar::compose types so the
// JSON-RPC body can carry them without modifying libsugar).
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
struct WireFunctionContractMemento {
    fn_name: String,
    formals: Vec<String>,
    formal_sorts: Vec<Sort>,
    #[serde(default)]
    formal_regions: Vec<Option<String>>,
    return_sort: Sort,
    #[serde(default)]
    return_region: Option<String>,
    pre: IrFormula,
    post: IrFormula,
    #[serde(default)]
    body_cid: Option<String>,
    #[serde(default)]
    effects: WireEffectSet,
    #[serde(default)]
    locus: WireLocus,
    #[serde(default)]
    auto_minted_mementos: Vec<WireAliasingMemento>,
    /// Position in the outer call's formal list at which this atom's
    /// result substitutes. Per-step extension to CCP §6.3 to match the
    /// canonical primitive's `ChainStep::formal_idx`.
    #[serde(default)]
    formal_idx: Option<usize>,
}

impl WireFunctionContractMemento {
    fn to_lib(&self) -> FunctionContractMemento {
        let effects = self.effects.to_lib();
        let locus = self.locus.to_lib();
        let auto: Vec<AliasingMemento> = self
            .auto_minted_mementos
            .iter()
            .map(|m| m.to_lib())
            .collect();

        let value: Arc<Value> = build_value(
            &self.fn_name,
            &self.formals,
            &self.formal_sorts,
            &self.return_sort,
            &self.pre,
            &self.post,
            self.body_cid.as_deref(),
            &effects,
            &locus,
            &auto,
        );
        let canonical_bytes = jcs_bytes_of_value(&value);
        let cid = cid_of_value(&value);

        FunctionContractMemento {
            fn_name: self.fn_name.clone(),
            formals: self.formals.clone(),
            formal_sorts: self.formal_sorts.clone(),
            formal_regions: self.formal_regions.clone(),
            return_sort: self.return_sort.clone(),
            return_region: self.return_region.clone(),
            pre: self.pre.clone(),
            post: self.post.clone(),
            body_cid: self.body_cid.clone(),
            effects,
            locus,
            canonical_bytes,
            cid,
            auto_minted_mementos: auto,
            panic_loci: vec![],
            concept_hint: None,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct WireEffectSet {
    #[serde(default)]
    effects: Vec<WireEffect>,
}

impl WireEffectSet {
    fn to_lib(&self) -> EffectSet {
        let mut set = EffectSet::empty();
        for e in &self.effects {
            set.add(e.to_lib());
        }
        set
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum WireEffect {
    Reads {
        target: String,
    },
    Writes {
        target: String,
    },
    Io,
    Unsafe,
    Panics,
    UnresolvedCall {
        name: String,
    },
    OpaqueLoop {
        loop_cid: String,
    },
    EarlyReturn {
        try_cid: String,
    },
    ClosureCapture {
        body_fn_cid: String,
        n_captures: usize,
    },
    PinnedReference {
        target: String,
    },
    RawPointerProvenance {
        target: String,
        mutable: bool,
    },
    AtomicAccess {
        target: String,
        atomic_kind: WireAtomicKind,
        #[serde(default)]
        ordering: Option<String>,
    },
    PossibleAliasing {
        formals: Vec<String>,
    },
    Drop {
        name: String,
    },
}

impl WireEffect {
    fn to_lib(&self) -> Effect {
        match self {
            Self::Reads { target } => Effect::Reads {
                target: target.clone(),
            },
            Self::Writes { target } => Effect::Writes {
                target: target.clone(),
            },
            Self::Io => Effect::Io,
            Self::Unsafe => Effect::Unsafe,
            Self::Panics => Effect::Panics,
            Self::UnresolvedCall { name } => Effect::UnresolvedCall { name: name.clone() },
            Self::OpaqueLoop { loop_cid } => Effect::OpaqueLoop {
                loop_cid: loop_cid.clone(),
            },
            Self::EarlyReturn { try_cid } => Effect::EarlyReturn {
                try_cid: try_cid.clone(),
            },
            Self::ClosureCapture {
                body_fn_cid,
                n_captures,
            } => Effect::ClosureCapture {
                body_fn_cid: body_fn_cid.clone(),
                n_captures: *n_captures,
            },
            Self::PinnedReference { target } => Effect::PinnedReference {
                target: target.clone(),
            },
            Self::RawPointerProvenance { target, mutable } => Effect::RawPointerProvenance {
                target: target.clone(),
                mutable: *mutable,
            },
            Self::AtomicAccess {
                target,
                atomic_kind,
                ordering,
            } => Effect::AtomicAccess {
                target: target.clone(),
                kind: atomic_kind.to_lib(),
                ordering: ordering.clone(),
            },
            Self::PossibleAliasing { formals } => Effect::PossibleAliasing {
                formals: formals.clone(),
            },
            Self::Drop { name } => Effect::Drop { name: name.clone() },
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireAtomicKind {
    Load,
    Store,
    Rmw,
    Cas,
}

impl WireAtomicKind {
    fn to_lib(&self) -> AtomicKind {
        match self {
            Self::Load => AtomicKind::Load,
            Self::Store => AtomicKind::Store,
            Self::Rmw => AtomicKind::Rmw,
            Self::Cas => AtomicKind::Cas,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct WireLocus {
    #[serde(default)]
    file: Option<String>,
    #[serde(default)]
    line: usize,
    #[serde(default)]
    col: usize,
}

impl WireLocus {
    fn to_lib(&self) -> Locus {
        Locus {
            file: self.file.clone(),
            line: self.line,
            col: self.col,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct WireAliasingMemento {
    formal_a: String,
    formal_b: String,
    status: WireAliasingStatus,
}

impl WireAliasingMemento {
    fn to_lib(&self) -> AliasingMemento {
        AliasingMemento {
            formal_a: self.formal_a.clone(),
            formal_b: self.formal_b.clone(),
            status: self.status.to_lib(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
enum WireAliasingStatus {
    Disjoint,
    MaybeAlias,
}

impl WireAliasingStatus {
    fn to_lib(&self) -> AliasingStatus {
        match self {
            Self::Disjoint => AliasingStatus::Disjoint,
            Self::MaybeAlias => AliasingStatus::MaybeAlias,
        }
    }
}
