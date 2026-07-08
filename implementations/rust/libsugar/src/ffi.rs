// SPDX-License-Identifier: MIT OR Apache-2.0
//
// C ABI FFI for the canonical compose primitive, per CCP §6.2.
//
// Spec: protocol/specs/2026-05-09-contract-composition-protocol.md §6.2.
// Header: implementations/rust/libsugar/include/sugar-compose.h.
//
// CCP §6.2 mandates the surface:
//
//     pk_composition_result *pk_compose_chain_contracts(
//         const char *atoms_jcs, const char *effects_jcs,
//         size_t atoms_len, size_t effects_len);
//     const char *pk_composition_result_cid(const pk_composition_result *r);
//     const char *pk_composition_result_body_jcs(const pk_composition_result *r);
//     const char *pk_composition_result_error(const pk_composition_result *r);
//     void pk_composition_result_free(pk_composition_result *r);
//
// Two intentional deviations from the literal §6.2 text, both
// documented in the commit message:
//
//   1. `formal_idx`. The Rust algebra needs a per-step formal index
//      (which formal of the outer atom the inner atom's result feeds
//      into). §6.2's C signature has no slot for it. Resolution: each
//      atom JSON object is `{"memento": <canonical body>, "formalIdx":
//      N}`, keeping the C signature byte-identical to §6.2.
//
//   2. `effects_jcs` redundancy. The canonical FunctionContractMemento
//      body already embeds an `effects` field (per `build_value` in
//      `compose.rs`). §6.2 also passes `effects_jcs` as a parallel
//      array. Resolution: the embedded field is authoritative; the
//      parallel `effects_jcs` array MUST equal-by-value the embedded
//      effects per atom; mismatch is a typed error
//      (`EffectsMismatch`). Spec signature preserved, single source of
//      truth maintained, cross-check enforced.
//
// All inputs are JCS-encoded JSON per CCP Appendix A. The FFI rejects
// malformed JSON with a typed error written into the result struct. No
// panics escape the FFI boundary.

use std::ffi::CString;
use std::os::raw::c_char;
use std::ptr;
use std::sync::Arc;

use serde::Deserialize;
use sugar_canonicalizer::Value;
use sugar_ir_types::{composition_refusal_header_cid, CompositionBoundaryMemento, IrFormula, Sort};

use crate::compose::{
    build_value, cid_of_value, compose_chain_contracts, jcs_bytes_of_value, AliasingMemento,
    AliasingStatus, AtomicKind, ChainStep, Effect, EffectSet, FunctionContractMemento, Locus,
};

// ============================================================
// Wire-format DTOs
//
// These mirror the canonical body shape produced by `build_value` in
// compose.rs. They exist purely to give serde a Deserialize target;
// they are immediately converted into `FunctionContractMemento` and
// then discarded. The canonical bytes / CIDs are recomputed via
// `build_value` on the converted struct so that wire-side and
// Rust-side CIDs are byte-identical by construction.
// ============================================================

#[derive(Debug, Deserialize)]
struct AtomEnvelope {
    memento: MementoBody,
    #[serde(rename = "formalIdx")]
    formal_idx: usize,
}

#[derive(Debug, Deserialize)]
struct MementoBody {
    #[serde(rename = "fnName")]
    fn_name: String,
    formals: Vec<String>,
    #[serde(rename = "formalSorts")]
    formal_sorts: Vec<Sort>,
    #[serde(rename = "returnSort")]
    return_sort: Sort,
    pre: IrFormula,
    post: IrFormula,
    #[serde(rename = "bodyCid", default)]
    body_cid: Option<String>,
    #[serde(default)]
    effects: Vec<EffectDto>,
    #[serde(default)]
    locus: Option<LocusDto>,
    #[serde(rename = "autoMintedMementos", default)]
    auto_minted_mementos: Vec<AliasingMementoDto>,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
struct LocusDto {
    #[serde(default)]
    file: Option<String>,
    #[serde(default)]
    line: usize,
    #[serde(default)]
    col: usize,
}

impl From<LocusDto> for Locus {
    fn from(d: LocusDto) -> Self {
        Locus {
            file: d.file,
            line: d.line,
            col: d.col,
        }
    }
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind")]
enum EffectDto {
    #[serde(rename = "reads")]
    Reads { target: String },
    #[serde(rename = "writes")]
    Writes { target: String },
    #[serde(rename = "io")]
    Io,
    #[serde(rename = "unsafe")]
    Unsafe,
    #[serde(rename = "panics")]
    Panics,
    #[serde(rename = "unresolved_call")]
    UnresolvedCall { name: String },
    #[serde(rename = "opaque_loop")]
    OpaqueLoop {
        #[serde(rename = "loopCid")]
        loop_cid: String,
    },
    #[serde(rename = "early_return")]
    EarlyReturn {
        #[serde(rename = "tryCid")]
        try_cid: String,
    },
    #[serde(rename = "closure_capture")]
    ClosureCapture {
        #[serde(rename = "bodyFnCid")]
        body_fn_cid: String,
        #[serde(rename = "nCaptures")]
        n_captures: usize,
    },
    #[serde(rename = "pinned_reference")]
    PinnedReference { target: String },
    #[serde(rename = "raw_ptr_provenance")]
    RawPointerProvenance { target: String, mutable: bool },
    #[serde(rename = "atomic_access")]
    AtomicAccess {
        target: String,
        #[serde(rename = "atomicKind")]
        atomic_kind: String,
        #[serde(default)]
        ordering: Option<String>,
    },
    #[serde(rename = "possible_aliasing")]
    PossibleAliasing { formals: Vec<String> },
    #[serde(rename = "drop")]
    Drop { name: String },
}

impl EffectDto {
    fn into_effect(self) -> Result<Effect, FfiError> {
        Ok(match self {
            EffectDto::Reads { target } => Effect::Reads { target },
            EffectDto::Writes { target } => Effect::Writes { target },
            EffectDto::Io => Effect::Io,
            EffectDto::Unsafe => Effect::Unsafe,
            EffectDto::Panics => Effect::Panics,
            EffectDto::UnresolvedCall { name } => Effect::UnresolvedCall { name },
            EffectDto::OpaqueLoop { loop_cid } => Effect::OpaqueLoop { loop_cid },
            EffectDto::EarlyReturn { try_cid } => Effect::EarlyReturn { try_cid },
            EffectDto::ClosureCapture {
                body_fn_cid,
                n_captures,
            } => Effect::ClosureCapture {
                body_fn_cid,
                n_captures,
            },
            EffectDto::PinnedReference { target } => Effect::PinnedReference { target },
            EffectDto::RawPointerProvenance { target, mutable } => {
                Effect::RawPointerProvenance { target, mutable }
            }
            EffectDto::AtomicAccess {
                target,
                atomic_kind,
                ordering,
            } => {
                let kind = match atomic_kind.as_str() {
                    "load" => AtomicKind::Load,
                    "store" => AtomicKind::Store,
                    "rmw" => AtomicKind::Rmw,
                    "cas" => AtomicKind::Cas,
                    other => return Err(FfiError::Schema(format!("unknown atomicKind {}", other))),
                };
                Effect::AtomicAccess {
                    target,
                    kind,
                    ordering,
                }
            }
            EffectDto::PossibleAliasing { formals } => Effect::PossibleAliasing { formals },
            EffectDto::Drop { name } => Effect::Drop { name },
        })
    }
}

#[derive(Debug, Deserialize)]
struct AliasingMementoDto {
    #[serde(rename = "formal_a")]
    formal_a: String,
    #[serde(rename = "formal_b")]
    formal_b: String,
    status: String,
}

impl AliasingMementoDto {
    fn into_memento(self) -> Result<AliasingMemento, FfiError> {
        let status = match self.status.as_str() {
            "Disjoint" => AliasingStatus::Disjoint,
            "MaybeAlias" => AliasingStatus::MaybeAlias,
            other => {
                return Err(FfiError::Schema(format!(
                    "unknown aliasing status {}",
                    other
                )))
            }
        };
        Ok(AliasingMemento {
            formal_a: self.formal_a,
            formal_b: self.formal_b,
            status,
        })
    }
}

// ============================================================
// FFI errors
// ============================================================

#[derive(Debug)]
enum FfiError {
    NullInput(&'static str),
    InvalidUtf8(&'static str),
    InvalidJson(String),
    Schema(String),
    EffectsMismatch(usize),
    LengthMismatch { atoms: usize, effects: usize },
    ChainTooShort(usize),
    ComposeRefused(CompositionBoundaryMemento),
}

impl FfiError {
    fn message(&self) -> String {
        match self {
            FfiError::NullInput(name) => format!("null input pointer: {}", name),
            FfiError::InvalidUtf8(name) => format!("input is not valid UTF-8: {}", name),
            FfiError::InvalidJson(msg) => format!("invalid JCS JSON: {}", msg),
            FfiError::Schema(msg) => format!("schema error: {}", msg),
            FfiError::EffectsMismatch(idx) => {
                format!("effects_jcs[{idx}] does not match memento.effects at the same index")
            }
            FfiError::LengthMismatch { atoms, effects } => {
                format!("atoms_jcs and effects_jcs have different lengths: {atoms} vs {effects}")
            }
            FfiError::ChainTooShort(n) => {
                format!("chain has {n} atoms; compose_chain_contracts requires at least 2")
            }
            FfiError::ComposeRefused(refusal) => {
                let cid = composition_refusal_header_cid(&refusal.header);
                let refusal_json = serde_json::to_string(refusal)
                    .unwrap_or_else(|e| format!(r#"{{"serialize_error":"{e}"}}"#));
                format!(
                    "compose_chain_contracts refused: cid={cid}; kind={}; detail={}; refusal={refusal_json}",
                    refusal.header.failure_kind, refusal.header.failure_detail
                )
            }
        }
    }
}

// ============================================================
// Rust-side JCS entry point (testable without C)
// ============================================================

/// Parse the JCS-encoded inputs, run the canonical
/// `compose_chain_contracts` algebra, and return either (cid,
/// body_jcs) or a structured error. This is the load-bearing logic;
/// the C wrappers below are thin lifecycle plumbing on top of this
/// function.
pub fn compose_chain_contracts_jcs(
    atoms_jcs: &str,
    effects_jcs: &str,
) -> Result<(String, String), String> {
    inner_compose(atoms_jcs, effects_jcs).map_err(|e| e.message())
}

fn inner_compose(atoms_jcs: &str, effects_jcs: &str) -> Result<(String, String), FfiError> {
    let atom_envs: Vec<AtomEnvelope> = serde_json::from_str(atoms_jcs)
        .map_err(|e| FfiError::InvalidJson(format!("atoms_jcs: {}", e)))?;
    let parallel_effects: Vec<Vec<EffectDto>> = serde_json::from_str(effects_jcs)
        .map_err(|e| FfiError::InvalidJson(format!("effects_jcs: {}", e)))?;

    if atom_envs.len() != parallel_effects.len() {
        return Err(FfiError::LengthMismatch {
            atoms: atom_envs.len(),
            effects: parallel_effects.len(),
        });
    }
    if atom_envs.len() < 2 {
        return Err(FfiError::ChainTooShort(atom_envs.len()));
    }

    // Cross-check: per CCP §6.2 effects are passed twice (embedded in
    // memento body, plus parallel effects_jcs). Embedded is
    // authoritative; the parallel array must agree by-value.
    for (idx, (env, par_effects)) in atom_envs.iter().zip(parallel_effects.iter()).enumerate() {
        if &env.memento.effects != par_effects {
            return Err(FfiError::EffectsMismatch(idx));
        }
    }

    // Convert envelopes into FunctionContractMemento + formal_idx
    // pairs, recomputing canonical_bytes / cid via `build_value` so
    // wire-side CIDs match Rust-side CIDs byte-for-byte.
    let mut owned: Vec<(FunctionContractMemento, usize)> = Vec::with_capacity(atom_envs.len());
    for env in atom_envs {
        let formal_idx = env.formal_idx;
        let body = env.memento;

        let mut effects = EffectSet::empty();
        for e in body.effects {
            effects.add(e.into_effect()?);
        }

        let mut auto_minted: Vec<AliasingMemento> =
            Vec::with_capacity(body.auto_minted_mementos.len());
        for m in body.auto_minted_mementos {
            auto_minted.push(m.into_memento()?);
        }

        let locus: Locus = body.locus.map(Into::into).unwrap_or_else(Locus::unknown);

        let value: Arc<Value> = build_value(
            &body.fn_name,
            &body.formals,
            &body.formal_sorts,
            &body.return_sort,
            &body.pre,
            &body.post,
            body.body_cid.as_deref(),
            &effects,
            &locus,
            &auto_minted,
        );
        let canonical_bytes = jcs_bytes_of_value(&value);
        let cid = cid_of_value(&value);

        let memento = FunctionContractMemento {
            fn_name: body.fn_name,
            formals: body.formals,
            formal_sorts: body.formal_sorts,
            formal_regions: vec![],
            return_sort: body.return_sort,
            return_region: None,
            pre: body.pre,
            post: body.post,
            body_cid: body.body_cid,
            effects,
            locus,
            canonical_bytes,
            cid,
            auto_minted_mementos: auto_minted,
            panic_loci: vec![],
            concept_hint: None,
        };
        owned.push((memento, formal_idx));
    }

    let steps: Vec<ChainStep<'_>> = owned
        .iter()
        .map(|(m, idx)| ChainStep {
            contract: m,
            formal_idx: *idx,
        })
        .collect();

    let composed = compose_chain_contracts(&steps).map_err(FfiError::ComposeRefused)?;
    let body_jcs = String::from_utf8(composed.canonical_bytes.clone())
        .map_err(|e| FfiError::Schema(format!("composed body not utf-8: {}", e)))?;
    Ok((composed.cid, body_jcs))
}

// ============================================================
// Opaque result type
// ============================================================

/// Opaque handle returned by `pk_compose_chain_contracts`. C code sees
/// only a forward declaration in the header; the layout below is a
/// libsugar implementation detail.
///
/// The name intentionally matches the `pk_composition_result` C type
/// name from CCP §6.2 verbatim, so the standard Rust camel-case lint
/// is silenced here.
#[allow(non_camel_case_types)]
pub struct pk_composition_result {
    cid: Option<CString>,
    body_jcs: Option<CString>,
    error: Option<CString>,
}

impl pk_composition_result {
    fn ok(cid: String, body_jcs: String) -> Self {
        Self {
            // sugar-audit: default-ok(cid-text-is-hex-blake3-address-syntax-and-can-never-contain-a-raw-nul-byte)
            cid: CString::new(cid).ok(),
            // sugar-audit: default-ok(jcs-canonical-json-text-always-escapes-control-bytes-so-body-jcs-can-never-contain-a-raw-nul-byte)
            body_jcs: CString::new(body_jcs).ok(),
            error: None,
        }
    }

    fn err(message: String) -> Self {
        Self {
            cid: None,
            body_jcs: None,
            // sugar-audit: default-ok(error-message-text-is-produced-by-this-crate-and-never-embeds-a-raw-nul-byte)
            error: CString::new(message).ok(),
        }
    }
}

// ============================================================
// extern "C" surface
// ============================================================

fn read_jcs_input<'a>(
    ptr: *const c_char,
    len: usize,
    name: &'static str,
) -> Result<&'a str, FfiError> {
    if ptr.is_null() {
        return Err(FfiError::NullInput(name));
    }
    // SAFETY: caller guarantees `ptr` points to `len` bytes of
    // initialized memory it owns for the duration of the call.
    let bytes = unsafe { std::slice::from_raw_parts(ptr as *const u8, len) };
    std::str::from_utf8(bytes).map_err(|_| FfiError::InvalidUtf8(name))
}

/// Compose a chain of atomic FunctionContractMementos into a
/// ComposedFunctionContract via the canonical CCP §2 / §9 algebra.
///
/// Returns a heap-allocated `pk_composition_result *` that the caller
/// MUST free via `pk_composition_result_free`. The returned handle is
/// non-null on success AND on error; inspect its accessors to
/// distinguish.
///
/// # Safety
///
/// The four input pointers and lengths must describe two valid
/// JCS-encoded JSON blobs as documented in CCP §6.2 and Appendix A.
/// The pointers must remain valid for the duration of this call.
#[no_mangle]
pub unsafe extern "C" fn pk_compose_chain_contracts(
    atoms_jcs: *const c_char,
    effects_jcs: *const c_char,
    atoms_len: usize,
    effects_len: usize,
) -> *mut pk_composition_result {
    let result = match (
        read_jcs_input(atoms_jcs, atoms_len, "atoms_jcs"),
        read_jcs_input(effects_jcs, effects_len, "effects_jcs"),
    ) {
        (Ok(a), Ok(e)) => match inner_compose(a, e) {
            Ok((cid, body)) => pk_composition_result::ok(cid, body),
            Err(err) => pk_composition_result::err(err.message()),
        },
        (Err(e), _) | (_, Err(e)) => pk_composition_result::err(e.message()),
    };
    Box::into_raw(Box::new(result))
}

/// Return the composed CID as a NUL-terminated UTF-8 string, or NULL
/// if the call errored. Pointer is owned by the result struct; do not
/// free it separately.
///
/// # Safety
///
/// `r` must be a non-null pointer returned by
/// `pk_compose_chain_contracts` and not yet freed.
#[no_mangle]
pub unsafe extern "C" fn pk_composition_result_cid(
    r: *const pk_composition_result,
) -> *const c_char {
    if r.is_null() {
        return ptr::null();
    }
    match &(*r).cid {
        Some(s) => s.as_ptr(),
        None => ptr::null(),
    }
}

/// Return the composed body JCS as a NUL-terminated UTF-8 string, or
/// NULL on error. Pointer is owned by the result struct.
///
/// # Safety
///
/// `r` must be a non-null pointer returned by
/// `pk_compose_chain_contracts` and not yet freed.
#[no_mangle]
pub unsafe extern "C" fn pk_composition_result_body_jcs(
    r: *const pk_composition_result,
) -> *const c_char {
    if r.is_null() {
        return ptr::null();
    }
    match &(*r).body_jcs {
        Some(s) => s.as_ptr(),
        None => ptr::null(),
    }
}

/// Return the error message (NUL-terminated UTF-8) if the call
/// errored, or NULL on success. Pointer is owned by the result struct.
///
/// # Safety
///
/// `r` must be a non-null pointer returned by
/// `pk_compose_chain_contracts` and not yet freed.
#[no_mangle]
pub unsafe extern "C" fn pk_composition_result_error(
    r: *const pk_composition_result,
) -> *const c_char {
    if r.is_null() {
        return ptr::null();
    }
    match &(*r).error {
        Some(s) => s.as_ptr(),
        None => ptr::null(),
    }
}

/// Free a result handle. After this call the pointer is invalid.
/// Calling with NULL is a no-op.
///
/// # Safety
///
/// `r` must be a pointer previously returned by
/// `pk_compose_chain_contracts` and not yet freed. Double-free is
/// undefined behavior.
#[no_mangle]
pub unsafe extern "C" fn pk_composition_result_free(r: *mut pk_composition_result) {
    if r.is_null() {
        return;
    }
    drop(Box::from_raw(r));
}
