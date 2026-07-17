// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 2: enumerate_callsites. For every contract memento in the
// pool, walk its pre/post/inv looking for ctor terms whose `name`
// matches a known bridge sourceSymbol. Each hit is a CallSite.
//
// Mirrors implementations/cpp/.../verifier/enumerate_callsites.cpp.

use serde_json::Value as Json;
use sugar_ir_types::panic_freedom;
use tracing::{debug, info, warn};

use crate::types::{
    AttributeSafetyObligation, BridgePin, BundleScopedCallsiteKey, CallSite, MementoCid,
    MementoPool, StoredMember,
};

const PANIC_EFFECT_KIND: &str = "panic-freedom";

pub fn run(pool: &MementoPool) -> Vec<CallSite> {
    let _span = tracing::info_span!("enumerate_callsites").entered();
    info!(
        mementos = pool.mementos.len(),
        bridges = pool.bridges_by_symbol.len(),
        "enumerate_callsites: scanning contracts for callsites"
    );
    let mut out = Vec::with_capacity(pool.bridges_by_symbol.len());
    for (cid, body) in pool.contract_members_with_bodies() {
        // Shape-agnostic (matches resolve_target): v1.2-layered contracts
        // carry their kind on `header.kind` and pre/post/inv on `header`;
        // v1.1-flat carry them on `evidence.kind` / `evidence.body`. The
        // production harvest path (`mint_contract`) emits v1.2; reading
        // only `evidence.body` here meant harvested calls never enumerated.
        let mut property_name = body
            .get("contractName")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string();
        if property_name.is_empty() {
            // Stable fallback: short prefix of CID.
            property_name = format!("{}...", cid.as_str().chars().take(12).collect::<String>());
        }
        let callsite_bundle_cid = bundle_containing_member(pool, cid);
        // PANIC-LOCUS PRESERVATION (#1745): the per-occurrence source loci the
        // lifter stamped on THIS contract, each `{argTerm, file, line, col,
        // callee}`. A panic-leaf call (`x.unwrap()`) lifts to the abstract ctor
        // `method:unwrap` with no source span; the bridge index is per-symbol
        // (last-writer-wins), so two functions both calling `.unwrap()` would
        // otherwise collapse onto one call-site line. The locus lives on the
        // contract the occurrence belongs to, so we read it HERE, scoped to this
        // contract, and match an occurrence to its locus by the lifted argument
        // term (see `panic_line_for`). Absent/empty -> panic sites in this
        // contract carry no line (honestly undecidable), never a collapsed one.
        let panic_loci = panic_loci_from_body(&body);
        for slot in ["pre", "post", "inv"] {
            if let Some(f) = body.get(slot) {
                if f.is_object() {
                    walk_formula(
                        f,
                        &property_name,
                        cid,
                        pool,
                        callsite_bundle_cid.as_ref(),
                        &panic_loci,
                        &mut out,
                    );
                }
            }
        }
        for locus in &panic_loci {
            if let Some(cs) = callsite_from_panic_locus(
                locus,
                &property_name,
                cid,
                pool,
                callsite_bundle_cid.as_ref(),
            ) {
                if !has_same_panic_callsite(&out, &cs) {
                    warn_if_panic_callsite_alias_disagrees_for_locus(
                        pool,
                        callsite_bundle_cid.as_ref(),
                        locus,
                    );
                    out.push(cs);
                }
            }
        }
    }
    info!(callsites = out.len(), "enumerate_callsites: complete");
    if out.is_empty() {
        debug!("enumerate_callsites: no callsites found (check that bridges exist in pool)");
    } else {
        for cs in &out {
            debug!(
                bridge = %cs.bridge_ir_name,
                property = %cs.property_name,
                target_cid = ?cs.bridge_target_cid,
                "enumerate_callsites: callsite"
            );
        }
    }
    out
}

fn panic_loci_from_body(body: &Json) -> Vec<Json> {
    let old = json_array_field(body, "panicLoci");
    let new = json_array_field(body, "effectLoci")
        .into_iter()
        .filter(|locus| locus.get("effectKind").and_then(|v| v.as_str()) == Some(PANIC_EFFECT_KIND))
        .collect::<Vec<_>>();

    if old.is_empty() {
        return new;
    }
    if new.is_empty() || normalized_loci(&old) == normalized_loci(&new) {
        return old;
    }

    warn!(
        contract = body
            .get("contractName")
            .and_then(|v| v.as_str())
            .unwrap_or_default(),
        panic_loci = ?old,
        effect_loci = ?new,
        "effect-site-disagreement: panicLoci/effectLoci disagree; using panicLoci"
    );
    old
}

fn json_array_field(body: &Json, key: &str) -> Vec<Json> {
    body.get(key)
        .and_then(|v| v.as_array())
        .map(|items| items.to_vec())
        .unwrap_or_default()
}

fn memento_cid_field(body: &Json, key: &str) -> Option<MementoCid> {
    body.get(key)
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .and_then(|s| MementoCid::try_parse(s.to_string()).ok())
}

fn bridge_pin_field(body: &Json) -> Result<BridgePin, String> {
    BridgePin::from_target_proof_value(body.get("targetProofCid"))
}

fn scoped_callsite_key(
    bundle: &MementoCid,
    file: &str,
    line: usize,
    symbol: &str,
) -> Option<BundleScopedCallsiteKey> {
    BundleScopedCallsiteKey::from_parts(bundle.clone(), file.to_string(), line, symbol.to_string())
        .ok()
}

fn normalized_loci(loci: &[Json]) -> Vec<String> {
    let mut normalized = loci
        .iter()
        .map(|locus| serde_json::to_string(&locus_without_effect_kind(locus)).unwrap_or_default())
        .collect::<Vec<_>>();
    normalized.sort();
    normalized
}

fn locus_without_effect_kind(locus: &Json) -> Json {
    let Some(object) = locus.as_object() else {
        return locus.clone();
    };
    let mut object = object.clone();
    object.remove("effectKind");
    Json::Object(object)
}

fn callsite_from_panic_locus(
    locus: &Json,
    property_name: &str,
    property_cid: &MementoCid,
    pool: &MementoPool,
    callsite_bundle_cid: Option<&MementoCid>,
) -> Option<CallSite> {
    if !locus.is_object() {
        return None;
    }
    let callee = locus
        .get("callee")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())?;
    let callee = callee;
    let file = locus
        .get("file")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let line = locus
        .get("line")
        .or_else(|| locus.get("start_line"))
        .and_then(|v| v.as_u64())
        .map(|n| n as usize);
    let arg_term = locus.get("argTerm").cloned();
    let producer_file = locus
        .get("producerFile")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| file.clone());
    let producer_line = locus
        .get("producerLine")
        .and_then(|v| v.as_u64())
        .map(|n| n as usize);
    let producer_symbol = locus
        .get("producerSymbol")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string);

    let scoped_bridge = match (callsite_bundle_cid, file.as_deref(), line) {
        (Some(bundle), Some(file), Some(line)) => scoped_callsite_key(bundle, file, line, callee)
            .and_then(|key| pool.bridge_member_for_callsite_key(&key)),
        _ => None,
    };
    let bridge_env = scoped_bridge;
    let bridge_body = bridge_env
        .and_then(StoredMember::body)
        .cloned()
        .unwrap_or_else(|| serde_json::json!({}));
    if bridge_env.is_none() {
        warn!(
            callee = %callee,
            file = ?file,
            line = ?line,
            "enumerate_callsites: panicLoci entry has no bridge; surfacing an undecidable panic callsite"
        );
    }

    let bridge_self_bundle_cid = scoped_bridge
        .is_some()
        .then(|| callsite_bundle_cid.cloned())
        .flatten();

    let bridge_pin = match bridge_pin_field(&bridge_body) {
        Ok(pin) => pin,
        Err(error) => {
            warn!(
                callee = %callee,
                error = %error,
                "enumerate_callsites: bridge has malformed targetProofCid; refusing callsite"
            );
            return None;
        }
    };

    Some(CallSite {
        bridge_ir_name: callee.to_string(),
        bridge_target_cid: memento_cid_field(&bridge_body, "targetContractCid"),
        bridge_source_layer: bridge_body
            .get("sourceLayer")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string(),
        bridge_target_layer: bridge_body
            .get("targetLayer")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string(),
        bridge_pin,
        bridge_self_bundle_cid,
        property_name: property_name.to_string(),
        property_cid: Some(property_cid.clone()),
        callsite_bundle_cid: callsite_bundle_cid.cloned(),
        arg_terms: arg_term.iter().cloned().collect(),
        arg_term,
        formal_actuals: bridge_body
            .get("callsite")
            .and_then(|v| v.get("formalActuals"))
            .cloned(),
        producer_file,
        producer_line,
        producer_symbol,
        containing_atomic: None,
        guard_facts: Vec::new(),
        file,
        line,
        source_column: None,
        callee: Some(callee.to_string()),
        panic_site: true,
        attribute_safety: attribute_safety_from_locus(locus),
    })
}

fn attribute_safety_from_locus(locus: &Json) -> Option<AttributeSafetyObligation> {
    let safety = locus.get("attributeSafety")?.as_object()?;
    Some(AttributeSafetyObligation {
        receiver_class: safety
            .get("receiverClass")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        receiver_qualname: safety
            .get("receiverQualname")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        receiver_name: safety
            .get("receiverName")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        attribute: safety
            .get("attribute")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string(),
    })
}

#[allow(clippy::too_many_arguments)]
fn attribute_safety_callsite_from_locus(
    locus: &Json,
    property_name: &str,
    property_cid: &MementoCid,
    callsite_bundle_cid: Option<&MementoCid>,
    path_cond: &[Json],
) -> Option<CallSite> {
    let safety = attribute_safety_from_locus(locus)?;
    let file = locus
        .get("file")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let line = locus
        .get("line")
        .or_else(|| locus.get("start_line"))
        .and_then(|v| v.as_u64())
        .map(|n| n as usize);
    Some(CallSite {
        bridge_ir_name: panic_freedom::RUNTIME_FAILURE_SITE.to_string(),
        bridge_target_cid: None,
        bridge_source_layer: String::new(),
        bridge_target_layer: String::new(),
        bridge_pin: BridgePin::SelfPinned,
        bridge_self_bundle_cid: None,
        property_name: property_name.to_string(),
        property_cid: Some(property_cid.clone()),
        callsite_bundle_cid: callsite_bundle_cid.cloned(),
        arg_term: locus.get("argTerm").cloned(),
        arg_terms: locus.get("argTerm").cloned().into_iter().collect(),
        formal_actuals: None,
        producer_file: file.clone(),
        producer_line: None,
        producer_symbol: None,
        containing_atomic: None,
        guard_facts: path_cond.to_vec(),
        file,
        line,
        source_column: None,
        callee: Some(panic_freedom::RUNTIME_FAILURE_SITE.to_string()),
        panic_site: true,
        attribute_safety: Some(safety),
    })
}

fn warn_if_panic_callsite_alias_disagrees_for_locus(
    pool: &MementoPool,
    callsite_bundle_cid: Option<&MementoCid>,
    locus: &Json,
) {
    let Some(callee) = locus
        .get("callee")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
    else {
        return;
    };
    let Some(bridge_body) =
        callsite_scoped_bridge_for_locus(pool, callsite_bundle_cid, callee, locus)
            .and_then(StoredMember::body)
    else {
        return;
    };
    if let Some(bridge_callsite) = bridge_body.get("callsite") {
        let _ = callsite_is_panic_site(Some(bridge_callsite), callee);
    }
}

fn callsite_is_panic_site(callsite: Option<&Json>, bridge_name: &str) -> bool {
    let Some(callsite) = callsite else {
        return false;
    };
    let legacy = callsite.get("panicSite").and_then(|v| v.as_bool());
    let effect_site = callsite.get("effectSite");
    let effect = match effect_site {
        Some(Json::String(kind)) => Some(kind == PANIC_EFFECT_KIND),
        Some(other) => {
            warn!(
                bridge = %bridge_name,
                file = ?callsite.get("file").and_then(|v| v.as_str()),
                line = ?callsite
                    .get("start_line")
                    .or_else(|| callsite.get("line"))
                    .and_then(|v| v.as_u64()),
                effect_site = ?other,
                "effect-site-malformed: effectSite must be a concept string; ignoring effectSite"
            );
            None
        }
        None => None,
    };

    match (legacy, effect) {
        (Some(old), Some(new)) if old != new => {
            warn!(
                bridge = %bridge_name,
                file = ?callsite.get("file").and_then(|v| v.as_str()),
                line = ?callsite
                    .get("start_line")
                    .or_else(|| callsite.get("line"))
                    .and_then(|v| v.as_u64()),
                panic_site = old,
                effect_site = ?effect_site,
                "effect-site-disagreement: panicSite/effectSite disagree; using panicSite"
            );
            old
        }
        (Some(old), _) => old,
        (None, Some(new)) => new,
        (None, None) => false,
    }
}

fn has_same_panic_callsite(existing: &[CallSite], candidate: &CallSite) -> bool {
    existing.iter().any(|cs| {
        cs.panic_site
            && cs.property_cid == candidate.property_cid
            && cs.bridge_ir_name == candidate.bridge_ir_name
            && cs.file == candidate.file
            && cs.line == candidate.line
            && cs.arg_term == candidate.arg_term
    })
}

fn bundle_containing_member(pool: &MementoPool, member_cid: &MementoCid) -> Option<MementoCid> {
    pool.bundle_members
        .iter()
        .find_map(|(bundle_cid, members)| members.contains(member_cid).then(|| bundle_cid.clone()))
}

#[cfg(test)]
mod effect_alias_reader_tests {
    use super::*;
    use serde_json::json;
    use std::io::{self, Write};
    use std::sync::{Arc, Mutex};
    use tracing_subscriber::fmt::MakeWriter;

    #[derive(Clone, Default)]
    struct SharedLog(Arc<Mutex<Vec<u8>>>);

    struct SharedLogWriter(Arc<Mutex<Vec<u8>>>);

    impl Write for SharedLogWriter {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.0.lock().expect("log lock").extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    impl<'a> MakeWriter<'a> for SharedLog {
        type Writer = SharedLogWriter;

        fn make_writer(&'a self) -> Self::Writer {
            SharedLogWriter(self.0.clone())
        }
    }

    fn capture_warn_log(f: impl FnOnce()) -> String {
        let log = SharedLog::default();
        let subscriber = tracing_subscriber::fmt()
            .with_max_level(tracing::Level::WARN)
            .with_writer(log.clone())
            .with_ansi(false)
            .without_time()
            .finish();
        tracing::subscriber::with_default(subscriber, f);
        let bytes = log.0.lock().expect("log lock").clone();
        String::from_utf8(bytes).expect("log is utf8")
    }

    fn old_locus(line: u64) -> Json {
        json!({
            "argTerm": {"kind": "var", "name": "result"},
            "file": "src/lib.rs",
            "line": line,
            "callee": "method:unwrap"
        })
    }

    fn effect_locus(line: u64, effect_kind: &str) -> Json {
        json!({
            "effectKind": effect_kind,
            "argTerm": {"kind": "var", "name": "result"},
            "file": "src/lib.rs",
            "line": line,
            "callee": "method:unwrap"
        })
    }

    #[test]
    fn effect_loci_reader_accepts_legacy_panic_loci_only() {
        let body = json!({"panicLoci": [old_locus(25)]});
        let loci = panic_loci_from_body(&body);
        assert_eq!(loci, vec![old_locus(25)]);
    }

    #[test]
    fn effect_loci_reader_accepts_panic_effect_loci_only() {
        let body = json!({"effectLoci": [effect_locus(25, PANIC_EFFECT_KIND)]});
        let loci = panic_loci_from_body(&body);
        assert_eq!(loci, vec![effect_locus(25, PANIC_EFFECT_KIND)]);
    }

    #[test]
    fn effect_loci_reader_ignores_non_panic_effect_kind() {
        let body = json!({"effectLoci": [effect_locus(25, "non-panic-effect")]});
        assert!(panic_loci_from_body(&body).is_empty());
    }

    #[test]
    fn effect_loci_reader_ignores_malformed_effect_kind() {
        let body = json!({
            "effectLoci": [{
                "effectKind": 7,
                "argTerm": {"kind": "var", "name": "result"},
                "file": "src/lib.rs",
                "line": 25,
                "callee": "method:unwrap"
            }]
        });
        assert!(panic_loci_from_body(&body).is_empty());
    }

    #[test]
    fn effect_loci_reader_accepts_matching_old_and_new_without_duplication() {
        let body = json!({
            "panicLoci": [old_locus(25)],
            "effectLoci": [effect_locus(25, PANIC_EFFECT_KIND)]
        });
        let loci = panic_loci_from_body(&body);
        assert_eq!(loci, vec![old_locus(25)]);
    }

    #[test]
    fn effect_loci_reader_preserves_legacy_and_warns_on_disagreement() {
        let body = json!({
            "contractName": "both_disagree",
            "panicLoci": [old_locus(25)],
            "effectLoci": [effect_locus(99, PANIC_EFFECT_KIND)]
        });
        let mut loci = Vec::new();
        let logs = capture_warn_log(|| {
            loci = panic_loci_from_body(&body);
        });
        assert_eq!(loci, vec![old_locus(25)]);
        assert!(logs.contains("effect-site-disagreement"));
        assert!(logs.contains("panicLoci"));
        assert!(logs.contains("effectLoci"));
        assert!(logs.contains("both_disagree"));
    }

    #[test]
    fn effect_loci_reader_filters_mixed_effect_kinds() {
        let body = json!({
            "effectLoci": [
                effect_locus(25, "non-panic-effect"),
                effect_locus(38, PANIC_EFFECT_KIND)
            ]
        });
        let loci = panic_loci_from_body(&body);
        assert_eq!(loci, vec![effect_locus(38, PANIC_EFFECT_KIND)]);
    }

    #[test]
    fn effect_site_reader_accepts_legacy_panic_site_only() {
        let callsite = json!({"panicSite": true});
        assert!(callsite_is_panic_site(Some(&callsite), "method:unwrap"));
    }

    #[test]
    fn effect_site_reader_accepts_panic_effect_site_only() {
        let callsite = json!({"effectSite": PANIC_EFFECT_KIND});
        assert!(callsite_is_panic_site(Some(&callsite), "method:unwrap"));
    }

    #[test]
    fn effect_site_reader_ignores_non_panic_effect_site() {
        let callsite = json!({"effectSite": "non-panic-effect"});
        assert!(!callsite_is_panic_site(Some(&callsite), "method:unwrap"));
    }

    #[test]
    fn effect_site_reader_warns_and_ignores_malformed_effect_site() {
        let callsite = json!({"effectSite": 7});
        let mut is_panic = true;
        let logs = capture_warn_log(|| {
            is_panic = callsite_is_panic_site(Some(&callsite), "method:unwrap");
        });
        assert!(!is_panic);
        assert!(logs.contains("effect-site-malformed"));
        assert!(logs.contains("effectSite"));
    }

    #[test]
    fn effect_site_reader_preserves_legacy_and_warns_on_disagreement() {
        let callsite = json!({
            "panicSite": true,
            "effectSite": "non-panic-effect",
            "file": "src/lib.rs",
            "start_line": 25
        });
        let mut is_panic = false;
        let logs = capture_warn_log(|| {
            is_panic = callsite_is_panic_site(Some(&callsite), "method:unwrap");
        });
        assert!(is_panic);
        assert!(logs.contains("effect-site-disagreement"));
        assert!(logs.contains("panicSite"));
        assert!(logs.contains("effectSite"));
        assert!(logs.contains("src/lib.rs"));
        assert!(logs.contains("25"));
    }
}

fn walk_formula(
    f: &Json,
    property_name: &str,
    property_cid: &MementoCid,
    pool: &MementoPool,
    callsite_bundle_cid: Option<&MementoCid>,
    // PANIC-LOCUS PRESERVATION (#1745): the loci stamped on the contract being
    // walked, threaded down so a panic-site occurrence can resolve its OWN line.
    panic_loci: &[Json],
    out: &mut Vec<CallSite>,
) {
    let kind = f.get("kind").and_then(|v| v.as_str()).unwrap_or_default();
    match kind {
        "atomic" => {
            if let Some(args) = f.get("args").and_then(|v| v.as_array()) {
                for a in args {
                    // Pass the enclosing atomic down: when a bridged call
                    // ctor is found as a direct argument of this atomic,
                    // the body-discharge path needs the whole predicate
                    // (e.g. `=(double(3), 6)`) to derive the postcondition.
                    // A formula's terms have no dominating control-flow guard
                    // until a `cf_ite` is descended into, so the path condition
                    // starts empty here.
                    walk_term(
                        a,
                        property_name,
                        property_cid,
                        pool,
                        Some(f),
                        &[],
                        callsite_bundle_cid,
                        panic_loci,
                        out,
                    );
                }
            }
        }
        "and" | "or" | "not" | "implies" => {
            if let Some(ops) = f.get("operands").and_then(|v| v.as_array()) {
                for op in ops {
                    walk_formula(
                        op,
                        property_name,
                        property_cid,
                        pool,
                        callsite_bundle_cid,
                        panic_loci,
                        out,
                    );
                }
            }
        }
        "forall" | "exists" => {
            if let Some(b) = f.get("body") {
                if b.is_object() {
                    walk_formula(
                        b,
                        property_name,
                        property_cid,
                        pool,
                        callsite_bundle_cid,
                        panic_loci,
                        out,
                    );
                }
            }
        }
        _ => {}
    }
}

/// Convert an OPAQUE `cf_guarded` guard term into the atomic-predicate FORMULA
/// the verifier threads into the path condition. NAME-BLIND by construction:
/// it copies the guard ctor's `name` and `args` verbatim into an `atomic` with
/// NO recognition table and NO complement logic. The Rust kit (the lifter, see
/// `sugar-walk` `wrap_branch_guard`) has ALREADY resolved which predicate
/// governs a branch -- the then-branch carries the positive predicate atom
/// (`is_some(x)`), the else-branch carries the kit-computed complement
/// (`is_none(x)`). This verifier carries whatever atom the kit emitted; it does
/// not know Option/Result/collection complementarity, and recognizes no Rust
/// predicate name. The language-blindness invariant lives or dies here.
fn guarded_term_to_atomic(guard: &Json) -> Option<Json> {
    if guard.get("kind").and_then(|v| v.as_str()) != Some("ctor") {
        return None;
    }
    let head = guard.get("name").and_then(|v| v.as_str())?;
    let args = guard
        .get("args")
        .cloned()
        .unwrap_or_else(|| serde_json::json!([]));
    // Opaque copy: head is carried through unchanged. The verifier asserts no
    // semantics over it; downstream discharge is purely syntactic (the threaded
    // atom must match the target contract's instantiated `pre` byte-for-byte).
    Some(serde_json::json!({ "kind": "atomic", "name": head, "args": args }))
}

/// PANIC-LOCUS PRESERVATION (#1745): resolve a panic-site occurrence's OWN
/// source `(file, line, col)` from the contract's `panicLoci`, matching by the
/// lifted argument term.
///
/// `arg_term` is the bridged ctor's first argument as it appears in the contract
/// formula (the unwrap RECEIVER, e.g. `to_string(v)`). The lifter recorded each
/// panic leaf keyed by that SAME lifted term (via the same `lift_expr_to_term`),
/// so a byte-equal `argTerm` uniquely identifies the occurrence WITHIN this
/// contract. This is a content match, not a positional one: two `.unwrap()`
/// calls in one function on different receivers each find their own line
/// regardless of walk order.
///
/// Returns `None` when the term matches no locus (the occurrence then carries no
/// line and stays honestly undecidable -- fail-SAFE, never the collapsed
/// per-symbol line). For the degenerate case of two byte-identical occurrences
/// in one contract (same receiver, same lifted term => genuinely identical
/// obligation, same verdict), the first locus is returned; the lines are a
/// cosmetic tie, not a soundness question.
fn panic_locus_for<'a>(
    callee: &str,
    arg_term: Option<&Json>,
    panic_loci: &'a [Json],
) -> Option<&'a Json> {
    let arg = arg_term?;
    let callee = callee;
    panic_loci.iter().find(|locus| {
        locus.get("argTerm") == Some(arg)
            && locus.get("callee").and_then(|v| v.as_str()) == Some(callee)
    })
}

fn callsite_scoped_bridge_for_locus<'a>(
    pool: &'a MementoPool,
    callsite_bundle_cid: Option<&MementoCid>,
    callee: &str,
    locus: &Json,
) -> Option<&'a StoredMember> {
    let bundle = callsite_bundle_cid?;
    let callee = callee;
    let file = locus.get("file").and_then(|v| v.as_str())?;
    let line = locus
        .get("line")
        .or_else(|| locus.get("start_line"))
        .and_then(|v| v.as_u64())? as usize;
    scoped_callsite_key(bundle, file, line, callee)
        .and_then(|key| pool.bridge_member_for_callsite_key(&key))
}

fn callsite_scoped_bridge_for_arg_terms<'a>(
    pool: &'a MementoPool,
    callsite_bundle_cid: Option<&'a MementoCid>,
    callee: &'a str,
    arg_terms: &[Json],
) -> Option<&'a StoredMember> {
    let bundle = callsite_bundle_cid?;
    let callee = callee;
    let mut matched = None;
    for bridge in pool.bridge_members_for_callsite_bundle_and_callee(bundle, callee) {
        if !bridge_formal_actuals_match_arg_terms(pool, bridge, arg_terms) {
            continue;
        }
        if matched.is_some() {
            return None;
        }
        matched = Some(bridge);
    }
    matched
}

fn bridge_formal_actuals_match_arg_terms(
    pool: &MementoPool,
    bridge: &StoredMember,
    arg_terms: &[Json],
) -> bool {
    let Some(bridge_body) = bridge.body() else {
        return false;
    };
    let Some(target_cid) = memento_cid_field(bridge_body, "targetContractCid") else {
        return false;
    };
    let Some(formals) = pool.contract_formals_by_cid(&target_cid) else {
        return false;
    };
    if formals.len() != arg_terms.len() {
        return false;
    }
    let Some(formal_actuals) = bridge_body
        .get("callsite")
        .and_then(|v| v.get("formalActuals"))
        .and_then(|v| v.as_object())
    else {
        return false;
    };
    formals.iter().zip(arg_terms).all(|(formal, actual)| {
        formal.as_str().and_then(|name| formal_actuals.get(name)) == Some(actual)
    })
}

fn attribute_safety_locus_for<'a>(term: &Json, panic_loci: &'a [Json]) -> Option<&'a Json> {
    panic_loci.iter().find(|locus| {
        locus.get("subkind").and_then(|v| v.as_str()) == Some("attribute-access")
            && locus.get("attributeSafety").is_some()
            && locus.get("argTerm") == Some(term)
    })
}

#[allow(clippy::too_many_arguments)]
fn walk_term(
    t: &Json,
    property_name: &str,
    property_cid: &MementoCid,
    pool: &MementoPool,
    containing_atomic: Option<&Json>,
    // PANIC-FREEDOM guard context: the atomic-predicate facts that dominate
    // this position in the lifted caller body, accumulated as `cf_ite`
    // branches are descended. Empty at the top of a formula.
    path_cond: &[Json],
    // The bundle containing the contract being walked. For panic sites, this is
    // the caller bundle that also contains co-located producer bridges.
    callsite_bundle_cid: Option<&MementoCid>,
    // PANIC-LOCUS PRESERVATION (#1745): the panic loci of the contract being
    // walked. A panic site reads its own line from here, keyed by arg_term.
    panic_loci: &[Json],
    out: &mut Vec<CallSite>,
) {
    if !t.is_object() {
        return;
    }
    let kind = t.get("kind").and_then(|v| v.as_str()).unwrap_or_default();
    // Surface `let ch = 'a'; ch.to_digit(16)` lifts to
    // `result = let ch = 97 in method:to_digit(ch, 16)`. The method ctor lives
    // under the IR `let` body, not at the top of the equality. Descend so
    // bodyguard-precondition seams enumerate (#3751); without this, formalActuals
    // bridges mint fine and self-post is reflexive, but callsites=0.
    if kind == "let" {
        if let Some(bindings) = t.get("bindings").and_then(|v| v.as_array()) {
            for binding in bindings {
                if let Some(bound) = binding
                    .get("boundTerm")
                    .or_else(|| binding.get("bound"))
                    .or_else(|| binding.get("value"))
                {
                    walk_term(
                        bound,
                        property_name,
                        property_cid,
                        pool,
                        containing_atomic,
                        path_cond,
                        callsite_bundle_cid,
                        panic_loci,
                        out,
                    );
                }
            }
        }
        if let Some(body) = t.get("body") {
            walk_term(
                body,
                property_name,
                property_cid,
                pool,
                containing_atomic,
                path_cond,
                callsite_bundle_cid,
                panic_loci,
                out,
            );
        }
        return;
    }
    if kind != "ctor" {
        return;
    }
    let name = t
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    let bridge_name = name.to_string();
    let arg_terms = t
        .get("args")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let arg_term = arg_terms.first().cloned();
    if let Some(locus) = attribute_safety_locus_for(t, panic_loci) {
        if let Some(cs) = attribute_safety_callsite_from_locus(
            locus,
            property_name,
            property_cid,
            callsite_bundle_cid,
            path_cond,
        ) {
            if !has_same_panic_callsite(out, &cs) {
                out.push(cs);
            }
        }
    }
    let scoped_panic_locus = panic_locus_for(&bridge_name, arg_term.as_ref(), panic_loci);
    // Panic-leaf method bridges are overloadable (`method:unwrap` can target
    // Option or Result). If the kit supplied an occurrence locus, choose the
    // exact `(bundle,file,line,callee)` bridge before considering the global
    // per-symbol index. This is language-blind: the verifier interprets no
    // callee names or predicates; it only preserves the kit's opaque callsite
    // identity. If a panic locus has no scoped bridge, do not fall back to the
    // symbol winner; the panicLoci fallback below will surface an undecidable
    // NoBridgeTarget instead of silently checking the wrong overload.
    let scoped_bridge = scoped_panic_locus.and_then(|locus| {
        callsite_scoped_bridge_for_locus(pool, callsite_bundle_cid, &bridge_name, locus)
    });
    let scoped_arg_bridge = if scoped_panic_locus.is_none() {
        callsite_scoped_bridge_for_arg_terms(pool, callsite_bundle_cid, &bridge_name, &arg_terms)
    } else {
        None
    };
    let bridge_env = if scoped_panic_locus.is_some() {
        scoped_bridge
    } else {
        scoped_arg_bridge.or_else(|| pool.bridge_member_for_symbol(&bridge_name))
    };
    if let Some(benv) = bridge_env {
        // Shape-agnostic: v1.2-layered bridges carry the fields on
        // `header`; v1.1-flat on `evidence.body`.
        let bbody = benv
            .body()
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        // Forward pin: an explicit targetProofCid means cross-bundle pin;
        // absence means self-pinned same-bundle co-membership. Malformed
        // targetProofCid cannot collapse to self-pinned.
        let bridge_pin = match bridge_pin_field(&bbody) {
            Ok(pin) => pin,
            Err(error) => {
                warn!(
                    name = %bridge_name,
                    error = %error,
                    "enumerate_callsites: bridge has malformed targetProofCid; refusing callsite"
                );
                return;
            }
        };
        let bridge_callsite = bbody.get("callsite");
        let callsite_callee = bbody
            .get("sourceSymbol")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let panic_site = callsite_is_panic_site(bridge_callsite, &bridge_name);
        // PANIC-LOCUS PRESERVATION (#1745): a panic site reads its line/col/file
        // from the contract's own `panicLoci`, keyed by `arg_term` -- NOT from
        // the per-symbol bridge `callsite` (last-writer-wins, collapses two
        // distinct `.unwrap()` lines to one). The bridge `callsite` still
        // classifies `panicSite`, but its line is occurrence-collapsed and must
        // NOT be the source of truth for a panic obligation's locus. A non-panic
        // bridged call keeps reading its line from the bridge as before (those
        // are 1:1 with their bridge and are not collapsed across occurrences).
        let occ_locus = if panic_site {
            scoped_panic_locus
                .or_else(|| panic_locus_for(&bridge_name, arg_term.as_ref(), panic_loci))
        } else {
            None
        };
        let (callsite_file, callsite_line) = if let Some(locus) = occ_locus {
            let f = locus
                .get("file")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string());
            let l = locus
                .get("line")
                .or_else(|| locus.get("start_line"))
                .and_then(|v| v.as_u64())
                .map(|n| n as usize);
            (f, l)
        } else if panic_site {
            // No matching locus for a panic site: carry NO line. The collapsed
            // bridge line must never stand in for the real occurrence -- that is
            // exactly the silent mis-attribution this fix removes. The site then
            // stays honestly undecidable downstream.
            if panic_loci.is_empty() {
                debug!(
                    name = %bridge_name,
                    "enumerate_callsites: panic site with no contract panicLoci -- \
                     carrying no line (occurrence locus unavailable; honestly undecidable)"
                );
            } else {
                warn!(
                    name = %bridge_name,
                    "enumerate_callsites: panic site arg_term matched no contract locus -- \
                     carrying no line rather than the collapsed per-symbol bridge line \
                     (panic-locus miss; site stays undecidable)"
                );
            }
            (None, None)
        } else {
            // Non-panic bridged call: keep the bridge-carried locus (1:1, not
            // subject to the per-symbol panic collapse).
            let f = bridge_callsite
                .and_then(|v| v.get("file"))
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string());
            let l = bridge_callsite
                .and_then(|v| v.get("start_line").or_else(|| v.get("line")))
                .and_then(|v| v.as_u64())
                .map(|n| n as usize);
            (f, l)
        };
        if panic_site {
            debug!(
                name = %bridge_name,
                line = ?callsite_line,
                file = ?callsite_file,
                matched_locus = occ_locus.is_some(),
                "enumerate_callsites: panic-site locus resolved from contract panicLoci by arg_term"
            );
        }
        let cs = CallSite {
            bridge_ir_name: bridge_name.clone(),
            bridge_target_cid: memento_cid_field(&bbody, "targetContractCid"),
            bridge_source_layer: bbody
                .get("sourceLayer")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_string(),
            bridge_target_layer: bbody
                .get("targetLayer")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_string(),
            bridge_pin,
            bridge_self_bundle_cid: if scoped_bridge.is_some() {
                callsite_bundle_cid.cloned()
            } else {
                pool.bridge_self_bundle_by_symbol.get(&bridge_name).cloned()
            },
            property_name: property_name.to_string(),
            property_cid: Some(property_cid.clone()),
            callsite_bundle_cid: callsite_bundle_cid.cloned(),
            arg_term: arg_term.clone(),
            arg_terms: arg_terms.clone(),
            formal_actuals: bridge_callsite
                .and_then(|v| v.get("formalActuals"))
                .cloned(),
            producer_file: occ_locus
                .and_then(|locus| {
                    locus
                        .get("producerFile")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                })
                .map(str::to_string)
                .or_else(|| callsite_file.clone()),
            producer_line: occ_locus
                .and_then(|locus| locus.get("producerLine"))
                .and_then(|v| v.as_u64())
                .map(|n| n as usize),
            producer_symbol: occ_locus
                .and_then(|locus| {
                    locus
                        .get("producerSymbol")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                })
                .map(str::to_string),
            containing_atomic: containing_atomic.cloned(),
            // Snapshot the dominating guard context for this call site. The
            // runner discharges a panic partial's `pre` under these facts.
            guard_facts: path_cond.to_vec(),
            file: callsite_file,
            line: callsite_line,
            source_column: None,
            callee: callsite_callee,
            panic_site,
            attribute_safety: occ_locus.and_then(attribute_safety_from_locus),
        };
        debug!(
            name = %bridge_name,
            panic_site,
            callsite_present = bridge_callsite.is_some(),
            arg_term_kind = ?cs.arg_term.as_ref().and_then(|a| a.get("kind")).and_then(|k| k.as_str()),
            "enumerate_callsites: enumerated bridge call site"
        );
        // NO-SILENT-FAILURE (Phase 0): a `method:`-seam bridge is the protocol's
        // method-call ctor (language-blind seam from the lift grammar). It MUST
        // carry call-site provenance; a missing `callsite` field means the mint
        // dropped it, which silently reads back `panic_site=false` and sends a
        // real panic leaf to undecidable. Surface it loudly and count it instead
        // of letting K silently rot. (Function-level bridges have no `method:`
        // seam, so they do not trip this.)
        if bridge_name.starts_with("method:") && bridge_callsite.is_none() {
            warn!(
                bridge = %bridge_name,
                "enumerate_callsites: method-seam bridge has NO callsite provenance -- mint dropped it; \
                 this panic site will read panic_site=false and stay undecidable (callsite-provenance drop)"
            );
        }
        out.push(cs);
    }
    // Descend into the call's arguments. A nested call is no longer a
    // direct argument of `containing_atomic`, so stop threading it: only a
    // call DIRECTLY under an atomic carries that atomic as its `Q` source.
    //
    // PANIC-FREEDOM path condition. The guard that dominates a branch is no
    // longer recovered HERE by recognizing the `cf_ite` condition's head -- the
    // verifier knows no Rust predicate names. Instead the Rust kit emits the
    // resolved guard ON the dominated branch as a `cf_guarded(guard, value)`
    // wrapper (then-branch -> positive predicate, else-branch -> kit-computed
    // complement; see `sugar-walk` `wrap_branch_guard`). This verifier:
    //   * `cf_ite(cond, then, else)`: descends all three branches with the
    //     path condition UNCHANGED. arg0 (the condition) introduces no fact;
    //     any dominating fact rides on the `cf_guarded` wrapper the kit placed
    //     around `then`/`else`.
    //   * `cf_guarded(guard, value)`: copies the OPAQUE guard atom into the
    //     path condition (name-blind, no complement table) and descends `value`
    //     under it. A branch the kit did not wrap (unrecognized guard) carries
    //     no `cf_guarded`, so a partial inside it stays honestly undecidable.
    //   * any other ctor: descends args with the path condition unchanged.
    if matches!(name.as_str(), panic_freedom::CF_GUARDED) {
        if let Some(args) = t.get("args").and_then(|v| v.as_array()) {
            let guard = args.first();
            let value = args.get(1);
            let mut branch_pc = path_cond.to_vec();
            if let Some(g) = guard.and_then(guarded_term_to_atomic) {
                branch_pc.push(g);
            }
            if let Some(v) = value {
                walk_term(
                    v,
                    property_name,
                    property_cid,
                    pool,
                    None,
                    &branch_pc,
                    callsite_bundle_cid,
                    panic_loci,
                    out,
                );
            }
            // The guard term itself is a predicate over the receiver, not a
            // call value; do not descend it as a callsite source.
        }
    } else if matches!(name.as_str(), panic_freedom::CF_ITE) {
        if let Some(args) = t.get("args").and_then(|v| v.as_array()) {
            // arg0: the condition term, evaluated in the enclosing context. It
            // introduces no path fact (the dominating fact rides cf_guarded).
            if let Some(c) = args.first() {
                walk_term(
                    c,
                    property_name,
                    property_cid,
                    pool,
                    None,
                    path_cond,
                    callsite_bundle_cid,
                    panic_loci,
                    out,
                );
            }
            // arg1 (then) / arg2 (else): descend unchanged. A guarded branch is
            // a `cf_guarded` wrapper handled above; an unguarded branch carries
            // the inherited path condition only.
            for branch in [args.get(1), args.get(2)].into_iter().flatten() {
                walk_term(
                    branch,
                    property_name,
                    property_cid,
                    pool,
                    None,
                    path_cond,
                    callsite_bundle_cid,
                    panic_loci,
                    out,
                );
            }
        }
    } else if let Some(args) = t.get("args").and_then(|v| v.as_array()) {
        // NESTED-CALL threading: when the current ctor has NO bridge (is not
        // itself a callsite), the enclosing atomic predicate is still the
        // correct `Q` source for any bridged call nested inside it. Thread
        // `containing_atomic` through so the inner callsite can use the outer
        // predicate for the reduce-in-place discharge path.
        //
        // When the current ctor IS bridged (it captured the atomic as its own
        // callsite above), the inner args are sub-obligations of that callee,
        // not of the outer predicate. Stop threading (pass `None`) to avoid
        // conflating the outer predicate with a sub-obligation the inner call
        // is not directly participating in.
        let inner_atomic = if pool.bridges_by_symbol.contains_key(&name) {
            None
        } else if pool.bridges_by_symbol.contains_key(&bridge_name) {
            None
        } else {
            containing_atomic
        };
        for a in args {
            walk_term(
                a,
                property_name,
                property_cid,
                pool,
                inner_atomic,
                path_cond,
                callsite_bundle_cid,
                panic_loci,
                out,
            );
        }
    }
}

#[cfg(test)]
mod guard_propagation_tests {
    //! PANIC-FREEDOM guard-context threading at the enumeration boundary, tested
    //! WITHOUT any Rust predicate name. The verifier is language-blind: it does
    //! not know `is_some`'s complement is `is_none`, nor that `option_unwrap`'s
    //! pre is `is_some`. The Rust kit (`sugar-walk` `wrap_branch_guard`) has
    //! ALREADY resolved which predicate governs each branch and emitted it as a
    //! `cf_guarded(guard, value)` wrapper. The verifier's only job is to copy
    //! whatever OPAQUE atom rides that wrapper into `CallSite::guard_facts`.
    //!
    //! So these tests use opaque names (`pred_a`, `pred_b`, `panic_call`) with
    //! no semantic table behind them:
    //!   - wrapped call    -> guard_facts = [pred_a(x)]   (the kit's atom, verbatim)
    //!   - unwrapped call  -> guard_facts = []            (undecidable -- no fact)
    //!   - cf_ite descent  -> the condition introduces NO fact; only the
    //!                        cf_guarded wrapper the kit placed carries one.
    //! The NAMED then->positive / else->complement discrimination is a Rust-kit
    //! property and is pinned in `sugar-walk`'s lift tests, not here.

    use super::*;
    use serde_json::json;
    use sugar_ir_types::panic_freedom;

    fn test_cid(label: &str) -> MementoCid {
        MementoCid::try_parse(label.to_string()).unwrap_or_else(|_| {
            MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(label.as_bytes()))
                .expect("test CID must parse")
        })
    }

    fn test_cid_string(label: &str) -> String {
        test_cid(label).to_string()
    }

    // The receiver term the obligation is about (`x` in `x.panic_call()`).
    fn recv() -> Json {
        json!({ "kind": "var", "name": "x" })
    }

    // A panic-partial call term whose ctor name matches the bridge sourceSymbol,
    // so it enumerates as a CallSite. The name is OPAQUE to the verifier.
    fn panic_call() -> Json {
        json!({ "kind": "ctor", "name": "panic_call", "args": [recv()] })
    }

    fn leaf_call(name: &str) -> Json {
        json!({ "kind": "ctor", "name": name, "args": [recv()] })
    }

    // An OPAQUE guard predicate atom term -- whatever the kit resolved for this
    // branch. The verifier carries it through with no recognition.
    fn pred(name: &str) -> Json {
        json!({ "kind": "ctor", "name": name, "args": [recv()] })
    }

    // Wrap a value in the kit's `cf_guarded(guard, value)` carrier.
    fn cf_guarded(guard: Json, value: Json) -> Json {
        guarded_carrier(panic_freedom::CF_GUARDED, guard, value)
    }

    fn guarded_carrier(name: &str, guard: Json, value: Json) -> Json {
        json!({ "kind": "ctor", "name": name, "args": [guard, value] })
    }

    fn choice_carrier(name: &str, cond: Json, then_branch: Json, else_branch: Json) -> Json {
        json!({
            "kind": "ctor",
            "name": name,
            "args": [cond, then_branch, else_branch],
        })
    }

    fn direct_choice_containing_atomic(name: &str) -> Option<Json> {
        let body = choice_carrier(
            name,
            pred("some_condition"),
            panic_call(),
            json!({ "kind": "lit", "value": 0 }),
        );
        let sites = run(&pool_with_post(body));
        enumerated_call(&sites).containing_atomic.clone()
    }

    // Build a pool with a single `panic_call` bridge and one contract whose
    // post is `result == <body>` (the self-post the call term lives in).
    fn pool_with_post(body_term: Json) -> MementoPool {
        let mut pool = MementoPool::default();
        let target_cid = test_cid_string("target");
        let bridge = json!({
            "envelope": true,
            "header": {
                "kind": "bridge",
                "sourceSymbol": "panic_call",
                "targetContractCid": target_cid,
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
            }
        });
        pool.insert_bridge_by_symbol("panic_call", test_cid("panic-call-bridge"), bridge);
        let contract = json!({
            "envelope": true,
            "header": {
                "kind": "contract",
                "contractName": "caller_self_post",
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [ { "kind": "var", "name": "result" }, body_term ],
                }
            }
        });
        pool.insert_unanchored_for_tests(test_cid("caller"), contract);
        pool
    }

    fn bridge(target_cid: &str, file: Option<&str>, line: Option<usize>) -> Json {
        bridge_for_symbol("panic_call", target_cid, file, line)
    }

    fn bridge_for_symbol(
        source_symbol: &str,
        target_cid: &str,
        file: Option<&str>,
        line: Option<usize>,
    ) -> Json {
        let callsite = match (file, line) {
            (Some(file), Some(line)) => json!({
                "file": file,
                "start_line": line,
                "panicSite": true,
            }),
            _ => json!(null),
        };
        let mut header = json!({
            "kind": "bridge",
            "sourceSymbol": source_symbol,
            "targetContractCid": target_cid,
            "sourceLayer": "rust",
            "targetLayer": "rust-tests",
        });
        if !callsite.is_null() {
            header["callsite"] = callsite;
        }
        json!({
            "envelope": true,
            "header": header
        })
    }

    fn pool_with_scoped_panic_bridge(body_term: Json) -> MementoPool {
        let mut pool = MementoPool::default();
        let bundle = test_cid("caller-bundle");
        let caller = test_cid("caller");
        pool.insert_bridge_by_symbol(
            "panic_call".to_string(),
            test_cid("wrong-symbol-bridge"),
            bridge(
                &test_cid_string("wrong-symbol-target"),
                Some("src/lib.rs"),
                Some(99),
            ),
        );
        pool.insert_bridge_by_callsite(
            scoped_callsite_key(&bundle, "src/lib.rs", 10, "panic_call").expect("scoped key"),
            test_cid("right-callsite-bridge"),
            bridge(
                &test_cid_string("right-callsite-target"),
                Some("src/lib.rs"),
                Some(10),
            ),
        );
        pool.bundle_members
            .entry(bundle)
            .or_default()
            .insert(caller.clone());
        let contract = json!({
            "envelope": true,
            "header": {
                "kind": "contract",
                "contractName": "caller_self_post",
                "panicLoci": [{
                    "argTerm": recv(),
                    "callee": "panic_call",
                    "file": "src/lib.rs",
                    "line": 10,
                    "col": 4,
                }],
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [ { "kind": "var", "name": "result" }, body_term ],
                }
            }
        });
        pool.insert_unanchored_for_tests(caller, contract);
        pool
    }

    #[test]
    fn formula_walk_selects_callsite_bridge_by_formal_actuals() {
        let mut pool = MementoPool::default();
        let bundle = test_cid("caller-bundle");
        let caller = test_cid("caller");
        let target = test_cid_string("to-digit-contract");
        let int_sort = json!({"kind": "primitive", "name": "Int"});
        let int_const = |value: i64| json!({"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": value});
        let to_digit_call = json!({
            "kind": "ctor",
            "name": "method:to_digit",
            "args": [int_const(97), int_const(16)],
        });
        let target_contract = json!({
            "envelope": true,
            "header": {
                "kind": "contract",
                "contractName": "char::to_digit",
                "formals": ["self", "radix"],
                "formalSorts": [int_sort.clone(), int_sort],
                "pre": {
                    "kind": "and",
                    "operands": [
                        {"kind": "atomic", "name": ">=", "args": [{"kind": "var", "name": "radix"}, int_const(2)]},
                        {"kind": "atomic", "name": "<=", "args": [{"kind": "var", "name": "radix"}, int_const(36)]}
                    ]
                }
            }
        });
        let internal_bridge = json!({
            "envelope": true,
            "header": {
                "kind": "bridge",
                "sourceSymbol": "method:to_digit",
                "targetContractCid": target.clone(),
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {
                    "file": "src/core_char_methods.rs",
                    "start_line": 344,
                    "panicSite": false,
                    "formalActuals": {
                        "self": {"kind": "var", "name": "self"},
                        "radix": {"kind": "var", "name": "radix"}
                    }
                }
            }
        });
        let caller_bridge = json!({
            "envelope": true,
            "header": {
                "kind": "bridge",
                "sourceSymbol": "method:to_digit",
                "targetContractCid": target.clone(),
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {
                    "file": "src/lib.rs",
                    "start_line": 3,
                    "panicSite": false,
                    "formalActuals": {
                        "self": int_const(97),
                        "radix": int_const(16)
                    }
                }
            }
        });
        pool.insert_unanchored_for_tests(test_cid(&target), target_contract);
        pool.insert_bridge_by_symbol(
            "method:to_digit",
            test_cid("internal-to-digit-bridge"),
            internal_bridge.clone(),
        );
        pool.insert_bridge_by_callsite(
            scoped_callsite_key(&bundle, "src/core_char_methods.rs", 344, "method:to_digit")
                .expect("scoped key"),
            test_cid("internal-to-digit-bridge"),
            internal_bridge,
        );
        pool.insert_bridge_by_callsite(
            scoped_callsite_key(&bundle, "src/lib.rs", 3, "method:to_digit").expect("scoped key"),
            test_cid("caller-to-digit-bridge"),
            caller_bridge,
        );
        pool.bundle_members
            .entry(bundle)
            .or_default()
            .insert(caller.clone());
        pool.insert_unanchored_for_tests(
            caller,
            json!({
                "envelope": true,
                "header": {
                    "kind": "contract",
                    "contractName": "bodyguard_edge",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [{"kind": "var", "name": "result"}, to_digit_call],
                    }
                }
            }),
        );

        let sites = run(&pool);
        let call = sites
            .iter()
            .find(|cs| cs.bridge_ir_name == "method:to_digit")
            .expect("to_digit callsite");
        assert_eq!(call.file.as_deref(), Some("src/lib.rs"));
        assert_eq!(call.line, Some(3));
        assert_eq!(
            call.formal_actuals.as_ref().and_then(|v| v.get("self")),
            Some(&int_const(97))
        );
    }

    /// #3751: bodyguard posts lift as
    /// `result = let ch = 97 in method:to_digit(ch, 16)`. Without descending
    /// IR `let`, formula walk reports callsites=0 while the implication
    /// bridge and formalActuals still mint — MISSING edge in the showcase.
    #[test]
    fn formula_walk_descends_let_to_enumerate_method_to_digit() {
        let mut pool = MementoPool::default();
        let bundle = test_cid("caller-bundle");
        let caller = test_cid("caller");
        let target = test_cid_string("to-digit-contract");
        let int_const = |value: i64| json!({"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": value});
        let let_wrapped_call = json!({
            "kind": "let",
            "bindings": [{
                "name": "ch",
                "boundTerm": int_const(97),
            }],
            "body": {
                "kind": "ctor",
                "name": "method:to_digit",
                "args": [
                    {"kind": "var", "name": "ch"},
                    int_const(16),
                ],
            },
        });
        let caller_bridge = json!({
            "envelope": true,
            "header": {
                "kind": "bridge",
                "sourceSymbol": "method:to_digit",
                "targetContractCid": target.clone(),
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {
                    "file": "src/lib.rs",
                    "start_line": 3,
                    "panicSite": false,
                    "formalActuals": {
                        "self": int_const(97),
                        "radix": int_const(16),
                    }
                }
            }
        });
        pool.insert_unanchored_for_tests(
            test_cid(&target),
            json!({
                "envelope": true,
                "header": {
                    "kind": "contract",
                    "contractName": "char::to_digit",
                    "formals": ["self", "radix"],
                    "pre": {
                        "kind": "and",
                        "operands": [
                            {"kind": "atomic", "name": ">=", "args": [
                                {"kind": "var", "name": "radix"}, int_const(2)
                            ]},
                            {"kind": "atomic", "name": "<=", "args": [
                                {"kind": "var", "name": "radix"}, int_const(36)
                            ]},
                        ]
                    }
                }
            }),
        );
        pool.insert_bridge_by_symbol(
            "method:to_digit",
            test_cid("caller-to-digit-bridge"),
            caller_bridge.clone(),
        );
        pool.insert_bridge_by_callsite(
            scoped_callsite_key(&bundle, "src/lib.rs", 3, "method:to_digit").expect("scoped key"),
            test_cid("caller-to-digit-bridge"),
            caller_bridge,
        );
        pool.bundle_members
            .entry(bundle)
            .or_default()
            .insert(caller.clone());
        pool.insert_unanchored_for_tests(
            caller,
            json!({
                "envelope": true,
                "header": {
                    "kind": "contract",
                    "contractName": "bodyguard_edge",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [{"kind": "var", "name": "result"}, let_wrapped_call],
                    }
                }
            }),
        );

        let sites = run(&pool);
        let call = sites
            .iter()
            .find(|cs| cs.bridge_ir_name == "method:to_digit")
            .unwrap_or_else(|| {
                panic!(
                    "let-wrapped method:to_digit must enumerate; got {} sites: {:?}",
                    sites.len(),
                    sites
                        .iter()
                        .map(|s| s.bridge_ir_name.as_str())
                        .collect::<Vec<_>>()
                )
            });
        assert_eq!(call.file.as_deref(), Some("src/lib.rs"));
        assert_eq!(call.line, Some(3));
        assert_eq!(
            call.formal_actuals.as_ref().and_then(|v| v.get("radix")),
            Some(&int_const(16)),
            "formalActuals from the bodyguard bridge must ride the enumerated site"
        );
    }

    fn pool_with_leaf_scoped_panic_bridge(body_term: Json, method: &str) -> MementoPool {
        pool_with_leaf_scoped_panic_bridge_and_locus(body_term, method, method)
    }

    fn pool_with_leaf_scoped_panic_bridge_and_locus(
        body_term: Json,
        bridge_method: &str,
        locus_callee: &str,
    ) -> MementoPool {
        let mut pool = MementoPool::default();
        let bundle = test_cid("caller-bundle");
        let caller = test_cid("caller");
        pool.insert_bridge_by_symbol(
            bridge_method.to_string(),
            test_cid("leaf-wrong-symbol-bridge"),
            bridge_for_symbol(
                bridge_method,
                &test_cid_string("wrong-symbol-target"),
                Some("src/lib.rs"),
                Some(99),
            ),
        );
        pool.insert_bridge_by_callsite(
            scoped_callsite_key(&bundle, "src/lib.rs", 10, bridge_method).expect("scoped key"),
            test_cid("leaf-right-callsite-bridge"),
            bridge_for_symbol(
                bridge_method,
                &test_cid_string("right-callsite-target"),
                Some("src/lib.rs"),
                Some(10),
            ),
        );
        pool.bundle_members
            .entry(bundle)
            .or_default()
            .insert(caller.clone());
        let contract = json!({
            "envelope": true,
            "header": {
                "kind": "contract",
                "contractName": "caller_self_post",
                "panicLoci": [{
                    "argTerm": recv(),
                    "callee": locus_callee,
                    "file": "src/lib.rs",
                    "line": 10,
                    "col": 4,
                }],
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [ { "kind": "var", "name": "result" }, body_term ],
                }
            }
        });
        pool.insert_unanchored_for_tests(caller, contract);
        pool
    }

    fn enumerated_call(sites: &[CallSite]) -> &CallSite {
        sites
            .iter()
            .find(|cs| cs.bridge_ir_name == "panic_call")
            .expect("the panic call must enumerate")
    }

    fn leaf_callsite<'a>(sites: &'a [CallSite], method: &str) -> &'a CallSite {
        sites
            .iter()
            .find(|cs| cs.bridge_ir_name == method)
            .unwrap_or_else(|| panic!("the leaf call must enumerate as {method}: {sites:?}"))
    }

    #[test]
    fn cf_guarded_threads_the_opaque_atom_verbatim() {
        // The kit wrapped the call: cf_guarded(pred_a(x), panic_call(x)). The
        // verifier copies `pred_a(x)` into guard_facts as an atomic, byte-blind.
        let body = cf_guarded(pred("pred_a"), panic_call());
        let sites = run(&pool_with_post(body));
        assert_eq!(
            enumerated_call(&sites).guard_facts,
            vec![json!({ "kind": "atomic", "name": "pred_a", "args": [recv()] })],
            "a cf_guarded-wrapped call must carry the kit's opaque guard atom verbatim"
        );
    }

    #[test]
    fn misspelled_concept_guarded_carrier_does_not_match() {
        let sites = run(&pool_with_post(guarded_carrier(
            "concept:panic-freedom.gaurd",
            pred("pred_a"),
            panic_call(),
        )));
        assert!(
            enumerated_call(&sites).guard_facts.is_empty(),
            "a misspelled substrate carrier must not silently match"
        );
    }

    #[test]
    fn concept_guarded_carrier_is_exact_case_sensitive_token() {
        for name in [
            " concept:panic-freedom.guard",
            "concept:panic-freedom.guard ",
            "concept:panic-freedom.Guard",
        ] {
            let sites = run(&pool_with_post(guarded_carrier(
                name,
                pred("pred_a"),
                panic_call(),
            )));
            assert!(
                enumerated_call(&sites).guard_facts.is_empty(),
                "substrate carrier token variations must not match: {name}"
            );
        }
    }

    #[test]
    fn unwrapped_call_has_no_guard() {
        // No cf_guarded wrapper -> no dominating fact -> undecidable.
        let sites = run(&pool_with_post(panic_call()));
        assert!(
            enumerated_call(&sites).guard_facts.is_empty(),
            "an unwrapped call must carry NO guard -> stays undecidable, never panic-safe: {:?}",
            enumerated_call(&sites).guard_facts
        );
    }

    #[test]
    fn cf_ite_condition_introduces_no_fact_only_the_wrapper_does() {
        // cf_ite(cond, cf_guarded(pred_a, panic_call), cf_guarded(pred_b, 0)).
        // The verifier reads the guard ONLY off the cf_guarded wrapper the kit
        // placed on the then-branch -- it does NOT derive anything from `cond`.
        // (cond uses an opaque head; the verifier must not recognize it.)
        let body = choice_carrier(
            panic_freedom::CF_ITE,
            pred("some_condition"),
            cf_guarded(pred("pred_a"), panic_call()),
            cf_guarded(pred("pred_b"), json!({ "kind": "lit", "value": 0 })),
        );
        let sites = run(&pool_with_post(body));
        let call = enumerated_call(&sites);
        assert_eq!(
            call.guard_facts,
            vec![json!({ "kind": "atomic", "name": "pred_a", "args": [recv()] })],
            "the call must carry ONLY the kit's then-branch wrapper atom, nothing from cond"
        );
        assert!(
            call.containing_atomic.is_none(),
            "the old choice carrier must stop outer atomic threading for branch callsites"
        );
    }

    #[test]
    fn concept_choice_condition_introduces_no_fact_only_the_wrapper_does() {
        let body = choice_carrier(
            "concept:panic-freedom.choice",
            pred("some_condition"),
            cf_guarded(pred("pred_a"), panic_call()),
            cf_guarded(pred("pred_b"), json!({ "kind": "lit", "value": 0 })),
        );
        let sites = run(&pool_with_post(body));
        let call = enumerated_call(&sites);
        assert_eq!(
            call.guard_facts,
            vec![json!({ "kind": "atomic", "name": "pred_a", "args": [recv()] })],
            "the substrate choice carrier must read exactly like the old choice carrier"
        );
        assert!(
            call.containing_atomic.is_none(),
            "the substrate choice carrier must stop outer atomic threading like the old choice carrier"
        );
    }

    #[test]
    fn misspelled_concept_choice_carrier_does_not_match() {
        let containing_atomic = direct_choice_containing_atomic("concept:panic-freedom.choiec");
        assert!(
            containing_atomic.is_some(),
            "a misspelled substrate choice carrier must fall through generic ctor descent"
        );
    }

    #[test]
    fn concept_choice_carrier_is_exact_case_sensitive_token() {
        for name in [
            " concept:panic-freedom.choice",
            "concept:panic-freedom.choice ",
            "concept:panic-freedom.Choice",
        ] {
            let containing_atomic = direct_choice_containing_atomic(name);
            assert!(
                containing_atomic.is_some(),
                "substrate choice token variations must not match the special carrier: {name}"
            );
        }
    }

    #[test]
    fn cf_ite_unwrapped_branch_carries_no_fact() {
        // An else-branch the kit did NOT wrap (e.g. its complement was not a
        // partial-pre-establishing predicate): the call there stays unguarded.
        let body = choice_carrier(
            panic_freedom::CF_ITE,
            pred("some_condition"),
            json!({ "kind": "lit", "value": 0 }),
            panic_call(), // bare, no cf_guarded wrapper
        );
        let sites = run(&pool_with_post(body));
        assert!(
            enumerated_call(&sites).guard_facts.is_empty(),
            "an unwrapped cf_ite branch must carry no fact -> undecidable"
        );
    }

    #[test]
    fn cf_guarded_with_non_ctor_guard_adds_no_fact() {
        // Robustness: a malformed guard (not a ctor) yields no atom; the call
        // descends with the inherited (empty) path condition.
        let body = json!({
            "kind": "ctor",
            "name": "cf_guarded",
            "args": [ { "kind": "var", "name": "not_a_predicate" }, panic_call() ],
        });
        let sites = run(&pool_with_post(body));
        assert!(
            enumerated_call(&sites).guard_facts.is_empty(),
            "a non-ctor guard must add no fact"
        );
    }

    #[test]
    fn formula_walk_prefers_callsite_scoped_bridge_and_preserves_guard_fact() {
        let body = cf_guarded(pred("pred_a"), panic_call());
        let sites = run(&pool_with_scoped_panic_bridge(body));
        let cs = enumerated_call(&sites);
        assert_eq!(
            cs.bridge_target_cid,
            Some(test_cid("right-callsite-target")),
            "panic formula-walk must select the exact callsite bridge, not the global symbol winner"
        );
        assert_eq!(
            cs.guard_facts,
            vec![json!({ "kind": "atomic", "name": "pred_a", "args": [recv()] })],
            "callsite-scoped bridge selection must not drop cf_guarded path facts"
        );
        assert_eq!(cs.file.as_deref(), Some("src/lib.rs"));
        assert_eq!(cs.line, Some(10));
    }

    #[test]
    fn malformed_leaf_concept_tokens_do_not_match_method_bridges() {
        for bad_name in [
            " concept:panic-freedom.leaf.unwrap",
            "concept:panic-freedom.leaf.unwrap ",
            "concept:panic-freedom.leaf.Unwrap",
            "concept:panic-freedom.leaf.unwrap_err",
            "concept:panic-freedom.option.some",
            "concept:panic-freedom.result.ok",
        ] {
            let body = cf_guarded(pred("pred_a"), leaf_call(bad_name));
            let sites = run(&pool_with_leaf_scoped_panic_bridge(
                body,
                panic_freedom::METHOD_UNWRAP,
            ));
            let cs = leaf_callsite(&sites, panic_freedom::METHOD_UNWRAP);
            assert!(
                cs.guard_facts.is_empty(),
                "malformed or cross-family token {bad_name} must not enumerate through the formula; \
                 only the panicLoci fallback should remain"
            );
        }
    }
}
