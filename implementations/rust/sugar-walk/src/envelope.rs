// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Wrap a `FunctionContractMemento` as a signed layered MintedEnvelope.
// Per #372 part 2.
//
// `sugar-claim-envelope::mint_contract_with_body_cid` is the substrate's canonical
// path for emitting contract mementos: it produces the v1.2 layered
// shape `{envelope, header, metadata}` with an Ed25519 attestation
// signature embedded in the envelope. The minted CID is the
// attestation CID; the header carries the signer-independent
// `contract_cid` plus the graph body pointer.
//
// This module is the converter from walk's internal contract type to
// the kit's `MintContractArgs`. Once a contract is wrapped, it plugs
// into the proof.ir bundle pipeline and the resolve/index
// substrate-verifier path with no further translation.

use std::{collections::HashMap, sync::Arc};

use sugar_canonicalizer::{encode_jcs, Value};
use sugar_claim_envelope::{
    contract_cid as kit_contract_cid, mint_contract_with_body_cid, Authoring, ClaimEnvelopeError,
    MintContractArgs, MintedEnvelope,
};
use sugar_proof_envelope::{AtomMemento, ContractBody, Ed25519Seed, FlatAtom, ProofGraph};

use crate::canonical::formula_to_canonical;
use crate::contract::FunctionContractMemento;

/// Default development signer seed. Production callers must supply a
/// vault-backed seed; this seed is for tests, demos, and self-attested
/// dogfood emission only.
pub const DEV_SIGNER_SEED: Ed25519Seed = [0x42; 32];

/// Wrap a FunctionContractMemento as a signed layered MintedEnvelope.
/// `produced_at` is the RFC-3339 declaration timestamp embedded in the
/// envelope (also re-used as `producedAt` in the metadata block).
pub fn wrap_function_contract(
    contract: &FunctionContractMemento,
    produced_at: &str,
    signer_seed: &Ed25519Seed,
) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    let args = mint_args(contract, produced_at, signer_seed)?;
    mint_graph_backed_contract(&args)
}

/// Content-addressed envelope cache + mint counter. Per #368 AC #6:
/// "Second invocation hits cache (no re-mint, demonstrated via
/// mint-counter assertion)" — paper 07 §6's "compose for free,
/// compress to nothing" empirically.
///
/// Lookups are by signer-independent `contract_cid` plus a deterministic
/// fingerprint of header-only panic provenance. `panic_loci` does not move the
/// contract CID, but it must affect the cache key so a source-locus edit cannot
/// return a stale `panicLoci` header.
#[derive(Debug, Default)]
pub struct EnvelopeCache {
    /// contract_cid + panic_loci fingerprint → cached MintedEnvelope
    by_contract: HashMap<String, MintedEnvelope>,
    /// Number of times mint_contract_with_body_cid was actually invoked.
    pub mints: u64,
    /// Number of times the cache served a previously-minted envelope.
    pub hits: u64,
}

impl EnvelopeCache {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.by_contract.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_contract.is_empty()
    }
}

/// Wrap a FunctionContractMemento with a content-addressed cache: if the
/// signer-independent `contract_cid` and header provenance fingerprint have
/// already been minted into this cache, return the cached envelope
/// (incrementing `cache.hits`); otherwise mint, insert, and return
/// (incrementing `cache.mints`).
pub fn wrap_function_contract_cached(
    contract: &FunctionContractMemento,
    produced_at: &str,
    signer_seed: &Ed25519Seed,
    cache: &mut EnvelopeCache,
) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    let args = mint_args(contract, produced_at, signer_seed)?;
    let cid = kit_contract_cid(&args);
    let cache_key = envelope_cache_key(&cid, &args.panic_loci);
    if let Some(env) = cache.by_contract.get(&cache_key) {
        cache.hits += 1;
        return Ok(env.clone());
    }
    let env = mint_graph_backed_contract(&args)?;
    cache.mints += 1;
    cache.by_contract.insert(cache_key, env.clone());
    Ok(env)
}

/// Register the graph body that `wrap_function_contract` points at.
///
/// Callers that bundle the returned envelope into a `.proof` graph must
/// register this body in that same graph before pushing the contract memento.
/// The body CID is derived from the same canonical pre/post/inv slots used by
/// the wrapped member's `bodyCid` header.
pub fn register_function_contract_body_graph(
    proof_graph: &mut ProofGraph,
    contract: &FunctionContractMemento,
    produced_at: &str,
    signer_seed: &Ed25519Seed,
) -> Result<ContractBody, ClaimEnvelopeError> {
    let args = mint_args(contract, produced_at, signer_seed)?;
    register_contract_body_graph(
        proof_graph,
        args.pre.as_ref(),
        args.post.as_ref(),
        args.inv.as_ref(),
    )
}

fn mint_graph_backed_contract(
    args: &MintContractArgs,
) -> Result<MintedEnvelope, ClaimEnvelopeError> {
    let mut proof_graph = ProofGraph::new();
    let body = register_contract_body_graph(
        &mut proof_graph,
        args.pre.as_ref(),
        args.post.as_ref(),
        args.inv.as_ref(),
    )?;
    mint_contract_with_body_cid(args, Some(body.cid().as_str()))
}

fn register_contract_body_graph(
    proof_graph: &mut ProofGraph,
    pre: Option<&Arc<Value>>,
    post: Option<&Arc<Value>>,
    inv: Option<&Arc<Value>>,
) -> Result<ContractBody, ClaimEnvelopeError> {
    let mut slots: Vec<(&'static str, AtomMemento)> = Vec::new();
    if let Some(formula) = pre {
        slots.push((
            "pre",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if let Some(formula) = post {
        slots.push((
            "post",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if let Some(formula) = inv {
        slots.push((
            "inv",
            proof_graph.register_atom(FlatAtom::new(formula.clone())),
        ));
    }
    if slots.is_empty() {
        return Err(ClaimEnvelopeError::Other(
            "contract body graph requires at least one formula slot".to_string(),
        ));
    }

    let slot_refs = slots
        .iter()
        .map(|(slot, atom)| (*slot, atom))
        .collect::<Vec<_>>();
    Ok(proof_graph.register_body(ContractBody::from_slots(slot_refs)))
}

fn envelope_cache_key(
    contract_cid: &str,
    panic_loci: &[Arc<sugar_canonicalizer::Value>],
) -> String {
    let loci_cid = panic_loci_fingerprint(panic_loci);
    format!("{contract_cid}:{loci_cid}")
}

fn panic_loci_fingerprint(panic_loci: &[Arc<Value>]) -> String {
    let canonical_loci = normalized_panic_loci(panic_loci);
    crate::canonical::cid_of_value(Value::array(canonical_loci).as_ref())
}

fn normalized_panic_loci(panic_loci: &[Arc<Value>]) -> Vec<Arc<Value>> {
    let mut keyed: Vec<(String, Arc<Value>)> = panic_loci
        .iter()
        .map(|locus| (encode_jcs(locus.as_ref()), locus.clone()))
        .collect();
    keyed.sort_by(|a, b| a.0.cmp(&b.0));
    keyed.into_iter().map(|(_, locus)| locus).collect()
}

/// Build the `MintContractArgs` from a contract memento. Exposed so
/// callers (and tests) can compute the signer-independent `contract_cid`
/// via `sugar_claim_envelope::contract_cid(&args)` without paying the
/// signing cost.
pub fn mint_args(
    contract: &FunctionContractMemento,
    produced_at: &str,
    signer_seed: &Ed25519Seed,
) -> Result<MintContractArgs, ClaimEnvelopeError> {
    validate_panic_loci(&contract.panic_loci)?;
    let pre = formula_to_canonical(&contract.pre);
    let post = formula_to_canonical(&contract.post);
    let out_binding = contract.result_var_name();
    let panic_loci = normalized_panic_loci(&contract.panic_loci);

    let input_cids: Vec<String> = match contract.body_cid.as_ref() {
        Some(cid) => vec![cid.clone()],
        None => Vec::new(),
    };

    // Carry the body-derived op-contract's formals (+ sorts) into the
    // minted header so `body_discharge::CatalogResolver` can resolve the
    // body-obligation (#1436/#1440). walk's `post` already equates
    // `result == <body-expr>`, so with formals present the contract is a
    // complete body-discharge target.
    let formals = contract.formals.clone();
    let formal_sorts = contract
        .formal_sorts
        .iter()
        .map(|s| {
            serde_json::to_value(s)
                .map(crate::canonical::serde_to_canonical)
                .map_err(|err| {
                    ClaimEnvelopeError::Other(format!("serialize formal sort for minting: {err}"))
                })
        })
        .collect::<Result<Vec<_>, _>>()?;

    Ok(MintContractArgs {
        contract_name: contract.fn_name.clone(),
        pre: Some(pre),
        post: Some(post),
        inv: None,
        evidence_term: None,
        out_binding,
        produced_by: "sugar-walk".to_string(),
        produced_at: produced_at.to_string(),
        input_cids,
        authoring: Authoring::Lift {
            lifter: "sugar-walk".to_string(),
            evidence: "syn-walk-v1".to_string(),
            source_cid: contract.body_cid.clone(),
        },
        signer_seed: *signer_seed,
        formals,
        emit_empty_formals: contract.formals.is_empty(),
        formal_sorts,
        library: None,
        bridge_source_symbol: None,
        body_discharge_eligible: true,
        body_discharge_refusal_reason: None,
        // PANIC-LOCUS PRESERVATION (#1745/#1749): header metadata only.
        // `sugar_claim_envelope::contract_cid` deliberately ignores this
        // field, so per-occurrence source provenance cannot perturb contract
        // identity or invalidate existing proofs.
        panic_loci,
        class_shapes: Vec::new(),
        source_warrants: Vec::new(),
        proofir_provenance: None,
    })
}

fn validate_panic_loci(panic_loci: &[Arc<Value>]) -> Result<(), ClaimEnvelopeError> {
    for (idx, locus) in panic_loci.iter().enumerate() {
        if !matches!(locus.as_ref(), Value::Object(_)) {
            return Err(ClaimEnvelopeError::Other(format!(
                "panic_loci[{idx}] must be an object, got {}",
                value_type_name(locus.as_ref())
            )));
        }
    }
    Ok(())
}

fn value_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Integer(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::build_function_contract;
    use serde_json::Value as JsonValue;
    use sugar_claim_envelope::contract_cid as kit_contract_cid;
    use sugar_ir_types::panic_freedom;

    fn fixture_contract(src: &str) -> FunctionContractMemento {
        let file: syn::File = syn::parse_str(src).unwrap();
        let item_fn = file
            .items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) => Some(f),
                // sugar-audit: not-mine(test-helper-search-ignores-non-function-items)
                _ => None,
            })
            .unwrap();
        build_function_contract(&item_fn, None)
    }

    fn sample_panic_locus() -> Arc<Value> {
        sample_panic_locus_at(2, 3)
    }

    fn sample_panic_locus_at(line: i64, panic_line: i64) -> Arc<Value> {
        Value::object([
            (
                "argTerm",
                Value::object([
                    ("kind", Value::string("call")),
                    ("callee", Value::string("serde_json::to_string")),
                    (
                        "args",
                        Value::array(vec![Value::object([
                            ("kind", Value::string("var")),
                            ("name", Value::string("v")),
                        ])]),
                    ),
                ]),
            ),
            ("file", Value::string("src/lib.rs")),
            ("line", Value::integer(i128::from(line))),
            ("col", Value::integer(4)),
            ("panicLine", Value::integer(i128::from(panic_line))),
            ("panicCol", Value::integer(9)),
            ("callee", Value::string("method:unwrap")),
        ])
    }

    fn header_json(env: &MintedEnvelope) -> JsonValue {
        serde_json::from_slice::<JsonValue>(&env.canonical_bytes)
            .expect("canonical envelope JSON")
            .get("header")
            .expect("layered envelope header")
            .clone()
    }

    fn assert_panic_locus_lines(src: &str, expected_line: u64, expected_panic_line: u64) {
        let c = fixture_contract(src);
        let env = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let header = header_json(&env);
        let panic_loci = header
            .get("panicLoci")
            .and_then(JsonValue::as_array)
            .expect("panicLoci must be present for panic-bearing contracts");
        assert_eq!(
            panic_loci.len(),
            1,
            "expected one panic locus: {panic_loci:?}"
        );
        assert_eq!(panic_loci[0]["file"], "unknown");
        assert_eq!(panic_loci[0]["line"], expected_line);
        assert_eq!(panic_loci[0]["panicLine"], expected_panic_line);
        assert_eq!(panic_loci[0]["callee"], panic_freedom::METHOD_UNWRAP);
        assert_ne!(
            panic_loci[0]["callee"], "concept:panic-freedom.leaf.unwrap",
            "Rust v1 envelope writer must not emit the unwrap leaf concept alias"
        );
    }

    #[test]
    fn wrap_emits_layered_envelope() {
        let c = fixture_contract("fn inc(x: i64) -> i64 { x + 1 }");
        let env = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();

        // Attestation CID is non-empty and well-formed.
        assert!(!env.cid.is_empty());
        assert!(env.cid.starts_with("blake3-512:"));

        // Contract CID is populated (signer-independent).
        assert!(!env.contract_cid.is_empty());
        assert!(env.contract_cid.starts_with("blake3-512:"));

        // Canonical bytes parse as a layered shape.
        let s = std::str::from_utf8(&env.canonical_bytes).unwrap();
        assert!(s.contains("\"envelope\""));
        assert!(s.contains("\"header\""));
        assert!(s.contains("\"metadata\""));
        assert!(s.contains("\"kind\":\"contract\""));
        assert!(s.contains("\"schemaVersion\":\"2\""));
    }

    #[test]
    fn wrap_is_deterministic_for_same_inputs() {
        let c = fixture_contract("fn id(x: i64) -> i64 { x }");
        let a = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let b = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        assert_eq!(a.cid, b.cid);
        assert_eq!(a.contract_cid, b.contract_cid);
        assert_eq!(a.canonical_bytes, b.canonical_bytes);
    }

    #[test]
    fn different_signers_share_contract_cid() {
        // The contract_cid is signer-independent — two signers attesting
        // to the same logical contract must produce the same content
        // CID, even though their attestation CIDs differ.
        let c = fixture_contract("fn add(x: i64) -> i64 { x + 2 }");
        let seed_a: Ed25519Seed = [0x11; 32];
        let seed_b: Ed25519Seed = [0x22; 32];
        let env_a = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &seed_a).unwrap();
        let env_b = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &seed_b).unwrap();

        assert_eq!(
            env_a.contract_cid, env_b.contract_cid,
            "contract_cid must be signer-independent"
        );
        assert_ne!(
            env_a.cid, env_b.cid,
            "attestation cids must differ across signers"
        );
        assert_ne!(env_a.canonical_bytes, env_b.canonical_bytes);
    }

    #[test]
    fn distinct_functions_produce_distinct_contract_cids() {
        let c1 = fixture_contract("fn one(x: i64) -> i64 { x + 1 }");
        let c2 = fixture_contract("fn two(x: i64) -> i64 { x + 2 }");
        let e1 = wrap_function_contract(&c1, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let e2 = wrap_function_contract(&c2, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        assert_ne!(e1.contract_cid, e2.contract_cid);
        assert_ne!(e1.cid, e2.cid);
    }

    #[test]
    fn mint_args_contract_cid_matches_wrap() {
        // contract_cid(args) must equal the embedded header.cid in the
        // minted envelope, so callers can compute it cheaply without
        // signing.
        let c = fixture_contract("fn neg(x: i64) -> i64 { -x }");
        let args = mint_args(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let cid_via_args = kit_contract_cid(&args);
        let env = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        assert_eq!(cid_via_args, env.contract_cid);
    }

    #[test]
    fn panic_loci_round_trip_in_contract_header() {
        let mut c = fixture_contract("fn split(v: serde_json::Value) -> String { v.to_string() }");
        c.panic_loci = vec![sample_panic_locus()];

        let env = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let header = header_json(&env);

        let panic_loci = header
            .get("panicLoci")
            .and_then(JsonValue::as_array)
            .expect("panicLoci must be present for panic-bearing contracts");
        assert_eq!(panic_loci.len(), 1);
        assert_eq!(panic_loci[0]["file"], "src/lib.rs");
        assert_eq!(panic_loci[0]["line"], 2);
        assert_eq!(panic_loci[0]["panicLine"], 3);
        assert_eq!(panic_loci[0]["callee"], panic_freedom::METHOD_UNWRAP);
        assert_ne!(
            panic_loci[0]["callee"], "concept:panic-freedom.leaf.unwrap",
            "Rust v1 envelope writer must not emit the unwrap leaf concept alias"
        );
    }

    #[test]
    fn one_line_unwrap_panic_locus_round_trips_through_envelope() {
        let src = r#"fn one_line(v: serde_json::Value) -> String {
    serde_json::to_string(&v).unwrap()
}
"#;
        assert_panic_locus_lines(src, 2, 2);
    }

    #[test]
    fn split_line_unwrap_panic_locus_round_trips_through_envelope() {
        let src = r#"fn split_line(v: serde_json::Value) -> String {
    serde_json::to_string(&v)
        .unwrap()
}
"#;
        assert_panic_locus_lines(src, 2, 3);
    }

    #[test]
    fn spanning_receiver_panic_locus_round_trips_through_envelope() {
        let src = r#"fn spanning(v: serde_json::Value) -> String {
    serde_json::to_string(
        &v,
    )
    .unwrap()
}
"#;
        assert_panic_locus_lines(src, 2, 5);
    }

    #[test]
    fn empty_panic_loci_omits_header_field() {
        let mut c = fixture_contract("fn no_panic(x: i64) -> i64 { x }");
        c.panic_loci = Vec::new();

        let env = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let header = header_json(&env);

        assert!(
            header.get("panicLoci").is_none(),
            "empty panic_loci must omit panicLoci, got {header:#}"
        );
    }

    #[test]
    fn malformed_panic_loci_string_entry_fails_closed() {
        let mut c = fixture_contract("fn bad(x: i64) -> i64 { x }");
        c.panic_loci = vec![Value::string("not-a-locus-object")];

        let err = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED)
            .expect_err("malformed panic_loci must fail closed");

        assert!(
            err.to_string()
                .contains("panic_loci[0] must be an object, got string"),
            "error should name panic_loci path and type, got: {err}"
        );
    }

    #[test]
    fn malformed_panic_loci_number_entry_fails_closed() {
        let mut c = fixture_contract("fn bad(x: i64) -> i64 { x }");
        c.panic_loci = vec![Value::integer(42)];

        let err = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED)
            .expect_err("malformed panic_loci must fail closed");

        assert!(
            err.to_string()
                .contains("panic_loci[0] must be an object, got number"),
            "error should name panic_loci path and type, got: {err}"
        );
    }

    #[test]
    fn malformed_panic_loci_array_entry_fails_closed() {
        let mut c = fixture_contract("fn bad(x: i64) -> i64 { x }");
        c.panic_loci = vec![Value::array(vec![])];

        let err = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED)
            .expect_err("malformed panic_loci must fail closed");

        assert!(
            err.to_string()
                .contains("panic_loci[0] must be an object, got array"),
            "error should name panic_loci path and type, got: {err}"
        );
    }

    #[test]
    fn malformed_panic_loci_null_entry_fails_closed() {
        let mut c = fixture_contract("fn bad(x: i64) -> i64 { x }");
        c.panic_loci = vec![Value::null()];

        let err = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED)
            .expect_err("malformed panic_loci must fail closed");

        assert!(
            err.to_string()
                .contains("panic_loci[0] must be an object, got null"),
            "error should name panic_loci path and type, got: {err}"
        );
    }

    #[test]
    fn panic_loci_are_header_metadata_not_contract_identity() {
        let base = fixture_contract("fn stable(x: i64) -> i64 { x }");
        let absent_or_default =
            mint_args(&base, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).expect("base mint args");

        let mut empty = base.clone();
        empty.panic_loci = Vec::new();
        let empty_args = mint_args(&empty, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED)
            .expect("empty panic_loci mint args");

        let mut nonempty = base.clone();
        nonempty.panic_loci = vec![sample_panic_locus()];
        let nonempty_args = mint_args(&nonempty, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED)
            .expect("nonempty panic_loci mint args");

        let cid = kit_contract_cid(&absent_or_default);
        assert_eq!(kit_contract_cid(&empty_args), cid);
        assert_eq!(kit_contract_cid(&nonempty_args), cid);
    }

    #[test]
    fn panic_loci_header_bytes_are_deterministic() {
        let mut c = fixture_contract("fn stable(v: serde_json::Value) -> String { v.to_string() }");
        c.panic_loci = vec![sample_panic_locus()];

        let a = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();
        let b = wrap_function_contract(&c, "2026-05-04T00:00:00Z", &DEV_SIGNER_SEED).unwrap();

        assert_eq!(a.contract_cid, b.contract_cid);
        assert_eq!(a.canonical_bytes, b.canonical_bytes);
    }

    #[test]
    fn panic_loci_fingerprint_is_order_independent() {
        let first = sample_panic_locus_at(2, 2);
        let second = sample_panic_locus_at(5, 5);

        let a = panic_loci_fingerprint(&[first.clone(), second.clone()]);
        let b = panic_loci_fingerprint(&[second, first]);

        assert_eq!(a, b);
    }

    // ---- AC #6: mint-counter cache assertion ----

    #[test]
    fn cached_wrap_first_invocation_mints_second_hits() {
        // Closes #368 AC #6: "Second invocation hits cache (no re-mint,
        // demonstrated via mint-counter assertion)."
        let c = fixture_contract("fn inc(x: i64) -> i64 { x + 1 }");
        let mut cache = EnvelopeCache::new();
        assert_eq!(cache.mints, 0);
        assert_eq!(cache.hits, 0);

        // First invocation: mints, cache becomes non-empty.
        let env1 =
            wrap_function_contract_cached(&c, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
                .unwrap();
        assert_eq!(cache.mints, 1, "first call must mint");
        assert_eq!(cache.hits, 0);
        assert_eq!(cache.len(), 1);

        // Second invocation on the SAME source: hits the cache, mint counter
        // does not increment.
        let env2 =
            wrap_function_contract_cached(&c, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
                .unwrap();
        assert_eq!(cache.mints, 1, "second call must NOT re-mint");
        assert_eq!(cache.hits, 1, "second call must register a hit");
        assert_eq!(env1.cid, env2.cid);
        assert_eq!(env1.canonical_bytes, env2.canonical_bytes);
        assert_eq!(env1.contract_cid, env2.contract_cid);
    }

    #[test]
    fn cached_wrap_distinct_contracts_each_mint_once() {
        // Two distinct contracts each get minted once; cache.mints == 2,
        // hits == 0. Then re-querying both produces 2 hits.
        let c1 = fixture_contract("fn one(x: i64) -> i64 { x + 1 }");
        let c2 = fixture_contract("fn two(x: i64) -> i64 { x + 2 }");
        let mut cache = EnvelopeCache::new();

        wrap_function_contract_cached(&c1, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
        wrap_function_contract_cached(&c2, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
        assert_eq!(cache.mints, 2);
        assert_eq!(cache.hits, 0);

        wrap_function_contract_cached(&c1, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
        wrap_function_contract_cached(&c2, "2026-05-05T00:00:00Z", &DEV_SIGNER_SEED, &mut cache)
            .unwrap();
        assert_eq!(cache.mints, 2, "no re-mint");
        assert_eq!(cache.hits, 2);
    }

    #[test]
    fn cached_wrap_keys_by_panic_loci_header_metadata() {
        let mut first =
            fixture_contract("fn same(v: serde_json::Value) -> String { v.to_string() }");
        first.panic_loci = vec![sample_panic_locus_at(2, 2)];
        let mut second = first.clone();
        second.panic_loci = vec![sample_panic_locus_at(5, 5)];
        let mut cache = EnvelopeCache::new();

        let env1 = wrap_function_contract_cached(
            &first,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();
        let env2 = wrap_function_contract_cached(
            &second,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();

        assert_eq!(env1.contract_cid, env2.contract_cid);
        assert_ne!(
            header_json(&env1)["panicLoci"],
            header_json(&env2)["panicLoci"],
            "cache must not return stale header panicLoci for same contract cid"
        );
        assert_eq!(cache.mints, 2);
        assert_eq!(cache.hits, 0);

        let env2_again = wrap_function_contract_cached(
            &second,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();
        assert_eq!(env2.canonical_bytes, env2_again.canonical_bytes);
        assert_eq!(cache.mints, 2);
        assert_eq!(cache.hits, 1);
    }

    #[test]
    fn cached_wrap_empty_panic_loci_hits_default_key() {
        let default = fixture_contract("fn same(x: i64) -> i64 { x }");
        let mut explicit_empty = default.clone();
        explicit_empty.panic_loci = Vec::new();
        let mut cache = EnvelopeCache::new();

        let env1 = wrap_function_contract_cached(
            &default,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();
        let env2 = wrap_function_contract_cached(
            &explicit_empty,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();

        assert_eq!(env1.canonical_bytes, env2.canonical_bytes);
        assert_eq!(cache.mints, 1);
        assert_eq!(cache.hits, 1);
    }

    #[test]
    fn cached_wrap_signer_independent_lookup() {
        // contract_cid is signer-independent. Caching by contract_cid
        // means two signers minting the same logical contract still
        // produce a cache hit on the second call.
        let c = fixture_contract("fn add(x: i64) -> i64 { x + 5 }");
        let seed_a: Ed25519Seed = [0x11; 32];
        let seed_b: Ed25519Seed = [0x22; 32];
        let mut cache = EnvelopeCache::new();

        let env_a =
            wrap_function_contract_cached(&c, "2026-05-05T00:00:00Z", &seed_a, &mut cache).unwrap();
        // Signer B asks for the same logical contract: cache returns the
        // first signer's envelope (CIDs are content-addressed; the cache
        // is signer-independent).
        let env_b =
            wrap_function_contract_cached(&c, "2026-05-05T00:00:00Z", &seed_b, &mut cache).unwrap();
        assert_eq!(cache.mints, 1, "signer-independent cache means one mint");
        assert_eq!(cache.hits, 1);
        assert_eq!(env_a.cid, env_b.cid);
    }
}
