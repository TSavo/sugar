// SPDX-License-Identifier: Apache-2.0
//
// Stage 4 handshake: Tier 1 (hash equality) and Tier 2 (cached
// implication memento) discharge for cross-language pre/post pairs.
//
// The handshake fires when a callsite's `arg_term` is itself a Ctor
// whose name is also bridged: the inner ctor names a producer
// function whose post-condition we can compare against the outer
// callsite's pre.
//
// Tier 1: BLAKE3-512(JCS(producer.post)) == BLAKE3-512(JCS(consumer.pre))
//         => discharged in zero solver work.
//
// Tier 2: there is a signed implication memento in the per-project
//         cache directory whose property hash equals
//         `BLAKE3("implication:" || producer.post.hash || ":" ||
//          consumer.pre.hash)`.
//         => signature verified, antecedent/consequent re-derived,
//         discharged.
//
// Tier 3: the existing Z3 path (in `runner::work_one`). On unsat the
//         caller mints + caches a fresh implication memento.
//
// All hashes here are full BLAKE3-512 with the `"blake3-512:"` tag,
// matching the protocol grammar.

use std::path::Path;

use serde_json::Value as Json;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_proof_envelope::ed25519_verify_string;

use sugar_proof_envelope::ProofGraph;

/// Outcome of a handshake attempt.
#[derive(Debug, Clone)]
pub enum HandshakeOutcome {
    /// Tier 1: producer.post hash == consumer.pre hash.
    Tier1HashEq {
        producer_post_hash: String,
        consumer_pre_hash: String,
    },
    /// Tier 2: signed implication memento found in the cache.
    Tier2CacheHit {
        implication_cid: String,
        producer_post_hash: String,
        consumer_pre_hash: String,
    },
    /// Tier 1 + Tier 2 missed; caller falls back to Tier 3 (Z3).
    /// Carries the post/pre hashes so the caller can mint and cache.
    Miss {
        producer_post_hash: Option<String>,
        consumer_pre_hash: Option<String>,
    },
}

impl HandshakeOutcome {
    pub fn discharged(&self) -> bool {
        matches!(
            self,
            HandshakeOutcome::Tier1HashEq { .. } | HandshakeOutcome::Tier2CacheHit { .. }
        )
    }
}

/// Return JCS-canonical BLAKE3-512 of an IR formula expressed as a
/// `serde_json::Value`. Used both for Tier 1 equality checks and for
/// keying implication-memento cache lookups.
pub fn formula_hash(formula: &Json) -> String {
    let v = serde_to_canonical(formula);
    let bytes = encode_jcs(&v);
    blake3_512_of(bytes.as_bytes())
}

/// Property hash an implication memento covers, derived from the
/// (antecedent, consequent) pair. Must match the grammar formula:
///   propertyHash = BLAKE3("implication:" || ah || ":" || ch).
pub fn implication_property_hash(antecedent_hash: &str, consequent_hash: &str) -> String {
    blake3_512_of(format!("implication:{antecedent_hash}:{consequent_hash}").as_bytes())
}

/// Serialize a `serde_json::Value` into the canonical-form `Value`
/// the JCS encoder operates on. Mirrors the encoder used by the
/// claim-envelope minter so byte-by-byte hashes line up.
fn serde_to_canonical(v: &Json) -> std::sync::Arc<Value> {
    match v {
        Json::Null => Value::null(),
        Json::Bool(b) => Value::boolean(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                Value::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                if f == (f as i64 as f64) {
                    Value::integer(f as i128)
                } else {
                    Value::string(f.to_string())
                }
            } else {
                Value::null()
            }
        }
        Json::String(s) => Value::string(s.clone()),
        Json::Array(arr) => Value::array(arr.iter().map(serde_to_canonical).collect()),
        Json::Object(map) => Value::object(
            map.iter()
                .map(|(k, val)| (k.as_str(), serde_to_canonical(val)))
                .collect::<Vec<_>>(),
        ),
    }
}

/// Locate the producer (post) contract memento that the callsite's
/// inner Ctor references. Returns `(post_formula, post_hash)` if
/// the chain resolves: arg_term is a ctor whose name is in
/// `pool.bridges_by_symbol`, and that bridge's targetContractCid
/// names a contract memento with a `post` slot.
pub fn locate_producer_post(
    arg_term: &Option<Json>,
    pool_mementos: &std::collections::BTreeMap<String, Json>,
    bridges_by_symbol: &std::collections::BTreeMap<String, Json>,
) -> Option<(Json, String)> {
    let arg = producer_lookup_term(arg_term.as_ref()?);
    if arg.get("kind").and_then(|v| v.as_str()) != Some("ctor") {
        return None;
    }
    let inner_name = arg.get("name").and_then(|v| v.as_str())?;
    let producer_bridge = bridges_by_symbol.get(inner_name)?;
    // Shape-agnostic: production mint emits v1.2-layered mementos (fields on
    // `header`); only v1.1-flat carries them on `evidence.body`. Reading the
    // flat path alone meant the producer post never resolved for harvested
    // calls, so the callsite fell through to the bare `instantiate` form
    // instead of the real `producer_post -> consumer_pre` implication.
    let bridge_body = sugar_proof_envelope::member_body(producer_bridge)?;
    let target_cid = bridge_body
        .get("targetContractCid")
        .and_then(|v| v.as_str())?;
    let producer_contract = pool_mementos.get(target_cid)?;
    let producer_body = sugar_proof_envelope::member_body(producer_contract)?;
    let post = producer_body
        .get("post")
        .filter(|v| v.is_object())
        .cloned()?;
    // The post relates the producer's output to its inputs via the carrier
    // variable `result` (e.g. `result == value`). Quantify over that carrier
    // so `build_implication_obligation` can unify it with the consumer's
    // formal: `forall _h0. producer_post[result:=_h0] -> consumer_pre[formal:=_h0]`.
    // Already-quantified posts pass through untouched.
    let post = wrap_post_forall(post, producer_body);
    let post_hash = formula_hash(&post);
    Some((post, post_hash))
}

fn producer_lookup_term(arg: &Json) -> &Json {
    let Some("ctor") = arg.get("kind").and_then(|v| v.as_str()) else {
        return arg;
    };
    match arg.get("name").and_then(|v| v.as_str()) {
        Some("await") => arg
            .get("args")
            .and_then(|v| v.as_array())
            .and_then(|args| args.first())
            .unwrap_or(arg),
        Some("method:unwrap" | "method:expect") => arg
            .get("args")
            .and_then(|v| v.as_array())
            .and_then(|args| args.first())
            .map(producer_lookup_term)
            .filter(is_channel_recv_lookup_term)
            .unwrap_or(arg),
        _ => arg,
    }
}

fn is_channel_recv_lookup_term(term: &&Json) -> bool {
    term.get("kind").and_then(|v| v.as_str()) == Some("ctor")
        && term
            .get("name")
            .and_then(|v| v.as_str())
            .is_some_and(|name| name.starts_with("channel:recv:"))
}

/// Wrap a bare producer post in `forall result. post`, binding the output
/// carrier variable `result`. Sort is taken from the producer's first formal
/// sort (its return width in the single-formal model) or `Int`. An
/// already-quantified post passes through untouched.
fn wrap_post_forall(post: Json, producer_body: &Json) -> Json {
    if post.get("kind").and_then(|v| v.as_str()) == Some("forall") {
        return post;
    }
    // The carrier `result` is the producer's RETURN value, not a parameter, so
    // its sort is NOT `formalSorts[i]` (those model parameter sorts, paired
    // with `formals`). The verifier reasons in LIA; bind the carrier as the
    // canonical `Int`, matching `build_implication_obligation`'s default. A
    // non-Int return would need the contract's return sort, which the memento
    // does not expose separately today.
    let _ = producer_body;
    let sort = serde_json::json!({"kind": "primitive", "name": "Int"});
    serde_json::json!({"kind": "forall", "name": "result", "sort": sort, "body": post})
}

/// Tier 1: literal equality of canonical hashes.
pub fn try_tier1(producer_post_hash: &str, consumer_pre_hash: &str) -> bool {
    producer_post_hash == consumer_pre_hash
}

/// Tier 2: search a per-project cache directory for a `.proof` file
/// containing an implication memento whose `propertyHash` matches the
/// expected value derived from `(producer_post_hash,
/// consumer_pre_hash)`. The implication memento's signature is
/// verified before discharge.
///
/// Returns `Some(implication_cid)` on cache hit, `None` on miss.
pub fn try_tier2(
    cache_dir: &Path,
    producer_post_hash: &str,
    consumer_pre_hash: &str,
) -> Option<String> {
    if !cache_dir.exists() {
        return None;
    }
    let want_property_hash = implication_property_hash(producer_post_hash, consumer_pre_hash);
    let entries = std::fs::read_dir(cache_dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) != Some("proof") {
            continue;
        }
        if let Some(cid) = scan_proof_for_implication(&path, &want_property_hash) {
            return Some(cid);
        }
    }
    None
}

fn scan_proof_for_implication(path: &Path, want_property_hash: &str) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    let graph = ProofGraph::read(&bytes).ok()?;
    for view in graph.implications() {
        let cid = view.cid().as_str().to_string();
        let env: Json = serde_json::from_slice(view.bytes()).ok()?;

        let prop = env.get("propertyHash").and_then(|v| v.as_str())?;
        if prop != want_property_hash {
            continue;
        }

        // Verify the producer signature.
        let sig = env.get("producerSignature").and_then(|v| v.as_str())?;
        // Re-build the unsigned canonical bytes and verify.
        let unsigned = strip_cid_and_sig(&env);
        let unsigned_v = serde_to_canonical(&unsigned);
        let unsigned_bytes = encode_jcs(&unsigned_v);

        // The cached memento must carry a `signerCid`-equivalent
        // (we don't have a key store here yet; for the demo the
        // implication memento embeds `producerPubkey` in its body
        // when minted by `cache_implication_memento`).
        let pubkey = view.field("producerPubkey")?;
        if !ed25519_verify_string(&pubkey, sig, unsigned_bytes.as_bytes()) {
            continue;
        }
        return Some(cid);
    }
    None
}

fn strip_cid_and_sig(env: &Json) -> Json {
    let mut out = env.clone();
    if let Json::Object(map) = &mut out {
        map.remove("cid");
        map.remove("producerSignature");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::BTreeMap;

    fn contract_with_post(post_value: i64) -> Json {
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "name": "producer",
                    "formals": [],
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": post_value}
                        ]
                    }
                }
            }
        })
    }

    fn bridge_to(cid: &str) -> Json {
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "producer",
                    "targetContractCid": cid
                }
            }
        })
    }

    #[test]
    fn locate_producer_post_resolves_through_single_await_seam() {
        let producer_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let mut pool_mementos = BTreeMap::new();
        pool_mementos.insert(producer_cid.to_string(), contract_with_post(6));
        let mut bridges_by_symbol = BTreeMap::new();
        bridges_by_symbol.insert("producer".to_string(), bridge_to(producer_cid));

        let arg_term = Some(json!({
            "kind": "ctor",
            "name": "await",
            "args": [
                {"kind": "ctor", "name": "producer", "args": []}
            ]
        }));

        let (post, _) = locate_producer_post(&arg_term, &pool_mementos, &bridges_by_symbol)
            .expect("await seam should resolve to producer post");
        assert_eq!(post["kind"], "forall");
        assert_eq!(post["name"], "result");
    }

    #[test]
    fn locate_producer_post_refuses_non_producer_await_base() {
        let producer_cid = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let mut pool_mementos = BTreeMap::new();
        pool_mementos.insert(producer_cid.to_string(), contract_with_post(6));
        let mut bridges_by_symbol = BTreeMap::new();
        bridges_by_symbol.insert("producer".to_string(), bridge_to(producer_cid));

        let arg_term = Some(json!({
            "kind": "ctor",
            "name": "await",
            "args": [
                {"kind": "var", "name": "future"}
            ]
        }));

        assert!(
            locate_producer_post(&arg_term, &pool_mementos, &bridges_by_symbol).is_none(),
            "await over a non-call term must not invent a producer post"
        );
    }

    #[test]
    fn locate_producer_post_resolves_channel_recv_through_await_unwrap_or_expect_seam() {
        let producer_cid = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        let mut pool_mementos = BTreeMap::new();
        pool_mementos.insert(producer_cid.to_string(), contract_with_post(6));
        let mut bridges_by_symbol = BTreeMap::new();
        bridges_by_symbol.insert("channel:recv:rx".to_string(), bridge_to(producer_cid));

        for wrapper in ["method:unwrap", "method:expect"] {
            let arg_term = Some(json!({
                "kind": "ctor",
                "name": wrapper,
                "args": [
                    {
                        "kind": "ctor",
                        "name": "await",
                        "args": [
                            {"kind": "ctor", "name": "channel:recv:rx", "args": [
                                {"kind": "var", "name": "rx"}
                            ]}
                        ]
                    }
                ]
            }));

            let (post, _) = locate_producer_post(&arg_term, &pool_mementos, &bridges_by_symbol)
                .unwrap_or_else(|| panic!("{wrapper} channel recv seam should resolve"));
            assert_eq!(post["kind"], "forall");
            assert_eq!(post["name"], "result");
        }
    }

    #[test]
    fn locate_producer_post_does_not_treat_plain_unwrap_as_channel_edge() {
        let producer_cid = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let mut pool_mementos = BTreeMap::new();
        pool_mementos.insert(producer_cid.to_string(), contract_with_post(6));
        let mut bridges_by_symbol = BTreeMap::new();
        bridges_by_symbol.insert("producer".to_string(), bridge_to(producer_cid));

        let arg_term = Some(json!({
            "kind": "ctor",
            "name": "method:unwrap",
            "args": [
                {"kind": "ctor", "name": "producer", "args": []}
            ]
        }));

        assert!(
            locate_producer_post(&arg_term, &pool_mementos, &bridges_by_symbol).is_none(),
            "plain unwrap must remain outside the channel implication seam"
        );
    }
}
