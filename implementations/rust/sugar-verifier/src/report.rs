// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Stage 7: report. Aggregate per-callsite verdicts plus load-error
// rows. Mirrors .../verifier/report.cpp.

use serde_json::{json, Value as Json};

use crate::types::{
    CallSite, LoadError, MementoCid, MementoPool, ObligationVerdict, Report, ReportRow,
    SourceLocus, ToolchainPlanReport,
};

/// Wire-shape for one `ReportRow`, as consumed by `sugar prove --json` and,
/// via this same function, by the sugar-linkerd `proveConsistency` RPC.
/// Rows are BORN enriched (2026-07-07, part of #3774 "one renderer" slice):
/// `verification_with_fol` composes the THREE conjoined facts (vendor fact /
/// vendor universe / your fact) as human-readable FOL, using the SAME
/// `crate::fol_render::proofir_formula_to_fol_with_instances` renderer
/// `sugar lift --report --visual` uses, moved here from
/// `sugar-cli/src/report_fmt.rs` so the daemon's resident-pool RPC (which has
/// no sugar-cli dependency) gets the identical enrichment the CLI's cold path
/// always had -- one renderer, one enrichment, one row constructor, never a
/// second copy re-declared per producer.
pub fn row_to_json(row: &ReportRow) -> Json {
    json!({
        "bridge": row.callsite.bridge_ir_name,
        "targetCid": row.callsite.bridge_target_cid,
        "sourceLayer": row.callsite.bridge_source_layer,
        "targetLayer": row.callsite.bridge_target_layer,
        "property": row.callsite.property_name,
        "propertyCid": row.callsite.property_cid,
        "status": row.status.as_str(),
        "reason": row.reason,
        "dischargeMethod": row.discharge_method,
        "bodyDischargeTier": row.body_discharge_tier,
        "verification": verification_with_fol(row.verification.as_ref()),
        "file": row.callsite.file,
        "line": row.callsite.line,
        "column": row.callsite.source_column,
        "callee": row.callsite.callee,
        "callsiteBundleCid": row.callsite.callsite_bundle_cid,
        "panicSite": row.callsite.panic_site,
    })
}

pub fn add_callsite(cs: &CallSite, verdict: ObligationVerdict, reason: &str, r: &mut Report) {
    add_callsite_with_discharge(cs.clone(), verdict, reason, None, None, r);
}

pub fn add_callsite_with_method(
    cs: &CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    r: &mut Report,
) {
    add_callsite_with_discharge(cs.clone(), verdict, reason, discharge_method, None, r);
}

pub fn add_callsite_with_discharge(
    cs: CallSite,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    body_discharge_tier: Option<String>,
    r: &mut Report,
) {
    r.total_callsites += 1;
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict,
        reason: reason.to_string(),
        discharge_method,
        body_discharge_tier,
        verification: None,
    });
    if verdict == ObligationVerdict::Discharged {
        r.discharged += 1;
    } else if verdict == ObligationVerdict::Refused {
        // A refusal is the trichotomy's third arm: a named, honest "no sound
        // discharger for this obligation". It is NOT a discharge (no false pass)
        // and NOT a violation (it does not redden the gate). The row stays visible
        // (status `refused` + reason); the scoreboard simply does not score it
        // against correctness, because we never claimed to decide it.
        r.refused += 1;
    } else {
        r.violations += 1;
    }
}

/// Add a contract self-post verification row. A self-post obligation
/// (`post[result := body]`, proving a contract's own body-derived post
/// reflexively, `body == body`) is a contract-level self-consistency
/// check, NOT a call site. It MUST NOT count toward `total_callsites`
/// (which counts only bridge/call-site obligations), so we synthesize a
/// minimal `CallSite` for the row but deliberately do NOT increment
/// `total_callsites`. The row still flows into `discharged`/`violations`
/// (a failing self-post must still fail the run) and remains visible in
/// the discharge split's `reflexive` bucket (computed by iterating
/// `rows`), so reflexive self-post coverage stays honest in the
/// scoreboard without being conflated with real call sites.
pub fn add_self_post(contract_cid: &str, verdict: ObligationVerdict, reason: &str, r: &mut Report) {
    add_self_post_with_method(contract_cid, verdict, reason, None, r);
}

pub fn add_self_post_with_method(
    contract_cid: &str,
    verdict: ObligationVerdict,
    reason: &str,
    discharge_method: Option<String>,
    r: &mut Report,
) {
    // NOTE: intentionally NO `r.total_callsites += 1` here. A self-post is
    // a contract self-consistency obligation, not a call site (#fix/self-post-not-a-callsite).
    let cs = CallSite {
        property_name: format!("self-post:{contract_cid}"),
        property_cid: MementoCid::try_parse(contract_cid.to_string()).ok(),
        ..CallSite::default()
    };
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict,
        reason: reason.to_string(),
        discharge_method,
        body_discharge_tier: None,
        verification: None,
    });
    if verdict == ObligationVerdict::Discharged {
        r.discharged += 1;
    } else if verdict == ObligationVerdict::Refused {
        // A refusal is the trichotomy's third arm: a named, honest "no sound
        // discharger for this obligation". It is NOT a discharge (no false pass)
        // and NOT a violation (it does not redden the gate). The row stays visible
        // (status `refused` + reason); the scoreboard simply does not score it
        // against correctness, because we never claimed to decide it.
        r.refused += 1;
    } else {
        r.violations += 1;
    }
}

/// Add a test-assertion consistency row (receipt 1). Like a self-post, this
/// is a contract self-consistency obligation, NOT a call site, so it does not
/// increment `total_callsites`. A `Discharged` verdict here is a CONSISTENCY
/// claim ("test assertions mutually consistent about callsite X"), not a
/// code-correctness claim; a non-`Discharged` verdict (contradictory inv, or
/// an undecidable/ill-sorted encoding STOP) drives a visible violation so the
/// contradiction is surfaced loudly rather than swallowed.
pub fn add_consistency(
    contract_cid: &str,
    property_name: &str,
    verdict: ObligationVerdict,
    reason: &str,
    r: &mut Report,
) {
    add_consistency_with_verification(contract_cid, property_name, verdict, reason, None, None, r);
}

#[allow(clippy::too_many_arguments)]
pub fn add_consistency_with_verification(
    contract_cid: &str,
    property_name: &str,
    verdict: ObligationVerdict,
    reason: &str,
    verification: Option<Json>,
    locus: Option<SourceLocus>,
    r: &mut Report,
) {
    // Carry the assertion's own source locus (file/line/column, recovered from
    // the contract memento's `file`+`span`) onto the row so an `unsatisfied`
    // verdict says WHERE. Without this, directory-prove drops the source and an
    // IDE has nothing to anchor a squiggle to.
    let (file, line, source_column) = match locus {
        Some(l) => (Some(l.file), Some(l.line), l.column),
        None => (None, None, None),
    };
    let cs = CallSite {
        property_name: format!("consistency:{property_name}"),
        property_cid: MementoCid::try_parse(contract_cid.to_string()).ok(),
        file,
        line,
        source_column,
        ..CallSite::default()
    };
    r.rows.push(ReportRow {
        callsite: cs,
        status: verdict,
        reason: reason.to_string(),
        discharge_method: Some("consistency".to_string()),
        body_discharge_tier: None,
        verification,
    });
    if verdict == ObligationVerdict::Discharged {
        r.discharged += 1;
    } else if verdict == ObligationVerdict::Refused {
        // A refusal is the trichotomy's third arm: a named, honest "no sound
        // discharger for this obligation". It is NOT a discharge (no false pass)
        // and NOT a violation (it does not redden the gate). The row stays visible
        // (status `refused` + reason); the scoreboard simply does not score it
        // against correctness, because we never claimed to decide it.
        r.refused += 1;
    } else {
        r.violations += 1;
    }
}

pub fn add_load_errors(errs: &[LoadError], r: &mut Report) {
    r.load_errors = errs.to_vec();
}

pub fn add_toolchain_plans(pool: &MementoPool, r: &mut Report) {
    r.toolchain_plans.extend(toolchain_plan_reports(pool));
}

pub fn toolchain_plan_reports(pool: &MementoPool) -> Vec<ToolchainPlanReport> {
    let mut witness_outputs = Vec::new();
    for (cid, member) in pool.witness_memento_members() {
        let actual = member
            .field("actualOutputCids")
            .and_then(json_str_vec)
            .or_else(|| member.field("actual_output_cids").and_then(json_str_vec))
            .unwrap_or_default();
        if actual.is_empty() {
            continue;
        }
        let plan_cid = member
            .field("planCid")
            .and_then(|v| v.as_str().map(str::to_string))
            .or_else(|| {
                member
                    .field("plan_cid")
                    .and_then(|v| v.as_str().map(str::to_string))
            });
        witness_outputs.push(WitnessOutputs {
            memento_cid: cid.to_string(),
            plan_cid,
            actual,
        });
    }

    let mut rows = Vec::new();
    for (cid, member) in pool.plan_memento_members() {
        let plan_cid = member
            .field("planCid")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let expected = member
            .field("expectedOutputCids")
            .and_then(json_str_vec)
            .or_else(|| member.field("expected_output_cids").and_then(json_str_vec))
            .unwrap_or_default();
        let plan_specific: Vec<&WitnessOutputs> = witness_outputs
            .iter()
            .filter(|witness| witness.plan_cid.as_deref() == Some(plan_cid.as_str()))
            .collect();
        let unscoped: Vec<&WitnessOutputs> = witness_outputs
            .iter()
            .filter(|witness| witness.plan_cid.is_none())
            .collect();
        let decision = toolchain_plan_decision(&expected, &plan_specific, &unscoped);
        rows.push(ToolchainPlanReport {
            plan_memento_cid: cid.to_string(),
            plan_cid,
            status: decision.status,
            reason: decision.reason,
            expected_output_cids: expected,
            witness_memento_cid: decision.witness_memento_cid,
            actual_output_cids: decision.actual_output_cids,
        });
    }
    rows.sort_by(|a, b| a.plan_memento_cid.cmp(&b.plan_memento_cid));
    rows
}

struct WitnessOutputs {
    memento_cid: String,
    plan_cid: Option<String>,
    actual: Vec<String>,
}

struct ToolchainPlanDecision {
    status: String,
    reason: String,
    witness_memento_cid: Option<String>,
    actual_output_cids: Vec<String>,
}

fn toolchain_plan_decision(
    expected: &[String],
    plan_specific: &[&WitnessOutputs],
    unscoped: &[&WitnessOutputs],
) -> ToolchainPlanDecision {
    if !plan_specific.is_empty() {
        if let Some(witness) = matching_witness(expected, plan_specific) {
            return confirmed(
                witness,
                "plan expected output CIDs match a plan-scoped witness-memento's actual output CIDs",
            );
        }
        return refuted(
            plan_specific[0],
            "plan expected output CIDs do not match loaded plan-scoped witness-memento actual output CIDs",
        );
    }

    if let Some(witness) = unscoped.first() {
        return declared_with_witness(
            witness,
            "toolchain output witness is missing planCid; ignored for plan settlement because toolchain witnesses must be scoped to a plan CID",
        );
    }

    ToolchainPlanDecision {
        status: "declared".to_string(),
        reason: "plan is pinned in the proof envelope; no matching witness-memento was loaded"
            .to_string(),
        witness_memento_cid: None,
        actual_output_cids: Vec::new(),
    }
}

fn matching_witness<'a>(
    expected: &[String],
    witnesses: &[&'a WitnessOutputs],
) -> Option<&'a WitnessOutputs> {
    witnesses
        .iter()
        .copied()
        .find(|witness| witness.actual.as_slice() == expected)
}

fn confirmed(witness: &WitnessOutputs, reason: &str) -> ToolchainPlanDecision {
    decision("confirmed", reason, Some(witness), witness.actual.clone())
}

fn refuted(witness: &WitnessOutputs, reason: &str) -> ToolchainPlanDecision {
    decision("refuted", reason, Some(witness), witness.actual.clone())
}

fn declared_with_witness(witness: &WitnessOutputs, reason: &str) -> ToolchainPlanDecision {
    decision("declared", reason, Some(witness), witness.actual.clone())
}

fn decision(
    status: &str,
    reason: &str,
    witness: Option<&WitnessOutputs>,
    actual_output_cids: Vec<String>,
) -> ToolchainPlanDecision {
    ToolchainPlanDecision {
        status: status.to_string(),
        reason: reason.to_string(),
        witness_memento_cid: witness.map(|witness| witness.memento_cid.clone()),
        actual_output_cids,
    }
}

fn json_str_vec(val: &Json) -> Option<Vec<String>> {
    Some(
        val.as_array()?
            .iter()
            .filter_map(|value| value.as_str().map(str::to_string))
            .collect(),
    )
}

/// Enrich a consistency-row's verification detail with the THREE conjoined
/// facts rendered as human-readable FOL -- the SAME rendering
/// `sugar lift --report --visual` produces (`proofir_formula_to_fol_with_instances`).
/// This is what the IDE squiggle shows for the green/red flip:
///   - `vendorUniverseFol`: the vendor's proved universe (`str.eq-bv-blocks(...)`),
///     from `linkedPosts[].vendorPost` (ProofIR, inline on the row).
///   - `clientFactFol`:     the consumer's OWN sworn fact, from `clientFactIr`.
///   - `vendorFactFol`:     the vendor's own sworn vector(s), from `vendorFactIr`.
/// Wire-don't-invent: every string comes from the shared renderer. Fail-open:
/// a fact whose ProofIR is absent or unrenderable is simply omitted, never faked.
/// Non-consistency verifications (or `None`) pass through unchanged.
pub(crate) fn verification_with_fol(verification: Option<&Json>) -> Json {
    let Some(v) = verification else {
        return Json::Null;
    };
    if v.get("kind").and_then(|x| x.as_str()) != Some("consistency") {
        return v.clone();
    }
    let mut out = v.clone();
    let obj = match out.as_object_mut() {
        Some(o) => o,
        None => return v.clone(),
    };

    // VENDOR UNIVERSE: render each distinct linked vendor post's ProofIR.
    // When the linked post carries its own quantification metadata (`call`,
    // `formals`, `outBinding` -- the shape a lifted rust function-post universe
    // travels with, e.g. the bounded-loop law `forall x. block_width(x)==64`),
    // present the post AS the universal law it is (`∀ _level:Int.
    // block_width(_level) = 64`) instead of the bare out-binding body
    // (`out = 64`), which reads as an unanchored equality. Wire-don't-invent:
    // the quantified IR is assembled ONLY from the post's own fields and
    // rendered by the same shared renderer; posts without the metadata keep
    // the plain body rendering.
    if let Some(posts) = v.get("linkedPosts").and_then(|x| x.as_array()) {
        let mut readings: Vec<String> = Vec::new();
        for post in posts {
            if let Some(ir) = post.get("vendorPost") {
                let fol = match quantified_vendor_post(post, ir) {
                    Some(q) => crate::fol_render::proofir_formula_to_fol_with_instances(&q),
                    None => crate::fol_render::proofir_formula_to_fol_with_instances(ir),
                };
                if !readings.contains(&fol) {
                    readings.push(fol);
                }
            }
        }
        if !readings.is_empty() {
            obj.insert(
                "vendorUniverseFol".to_string(),
                json!(fol_line(&readings.join(" ∧ "))),
            );
        }
    }

    // YOUR FACT: the consumer's own asserted equality.
    if let Some(ir) = v.get("clientFactIr") {
        let fol = crate::fol_render::proofir_formula_to_fol_with_instances(ir);
        obj.insert("clientFactFol".to_string(), json!(fol_line(&fol)));
    }

    // VENDOR FACT: the vendor's sworn value FOR THIS CALLSITE. The pool conjoins
    // EVERY sworn fact sharing the callee symbol (`len(array)=0`, `len(x)=2`,
    // `len(y)=20`, ...), so joining them all would show a wall of unrelated
    // vectors and a Quick Fix would grab an arbitrary one. Keep only the fact
    // whose LHS matches the consumer's OWN asserted callsite -- the value that
    // actually contradicts the assertion (`len(pd.DataFrame()) = 0`).
    if let Some(fact) = matching_vendor_fact(v) {
        let fol = crate::fol_render::proofir_formula_to_fol_with_instances(&fact);
        obj.insert("vendorFactFol".to_string(), json!(fol_line(&fol)));
    }

    // VENDOR FACT (derived case). A base64-style universe carries NO sworn
    // ground vector -- the vendor proved a ∀ law (`str.eq-bv-blocks`), not a
    // point. But the vendor's fact FOR THIS CALLSITE is that law instantiated at
    // the consumer's OWN argument: derive it by asking z3 what the universe
    // COMPUTES at that input (the SAME z3.model derive `sugar derive` runs),
    // then present it as `call:f(arg) = <derived>` -- the missing third
    // conjunct. Fail-open: no z3 / non-sat / no `{str}` RHS => omitted, not faked.
    if !obj.contains_key("vendorFactFol") {
        if let (Some(client_ir), Some(payload)) =
            (v.get("clientFactIr"), universe_blocks_payload(v))
        {
            if let Some(derived) = derive_blocks_value(&payload) {
                if let Some(ir) = client_fact_with_rhs(client_ir, &derived) {
                    let fol = crate::fol_render::proofir_formula_to_fol_with_instances(&ir);
                    obj.insert("vendorFactFol".to_string(), json!(fol_line(&fol)));
                }
            }
        }
    }

    out
}

/// Assemble the universal-law reading of a linked vendor post from the post's
/// OWN quantification metadata: `∀ <formals>. <call(formals)> substituted for
/// the out-binding in the post body`. Every ingredient comes from the linked
/// post (`call` gives the callee ctor and the argument sorts, `formals` the
/// lifted parameter names, `outBinding` the result variable the post body
/// speaks about); nothing is invented. None (fail-open -> plain body
/// rendering) when any piece is missing or the arity disagrees.
fn quantified_vendor_post(post: &Json, vendor_post: &Json) -> Option<Json> {
    let formals: Vec<&str> = post
        .get("formals")?
        .as_array()?
        .iter()
        .map(|f| f.as_str())
        .collect::<Option<Vec<_>>>()?;
    if formals.is_empty() {
        return None;
    }
    let out_binding = post.get("outBinding")?.as_str()?;
    let call = post.get("call")?;
    let call_args = call.get("args")?.as_array()?;
    if call.get("kind").and_then(|k| k.as_str()) != Some("ctor") || call_args.len() != formals.len()
    {
        return None;
    }
    // The callee applied to the FORMALS (not the consumer's concrete args);
    // each formal var carries the sort of the corresponding call argument.
    let mut formal_call = call.clone();
    let mut sorts = Vec::with_capacity(formals.len());
    {
        let args = formal_call.get_mut("args")?.as_array_mut()?;
        for (arg, formal) in args.iter_mut().zip(&formals) {
            let sort = arg.get("sort")?.clone();
            sorts.push(sort.clone());
            *arg = json!({ "kind": "var", "name": formal, "sort": sort });
        }
    }
    // The post body with the out-binding var replaced by the call term.
    let mut body = vendor_post.clone();
    substitute_var(&mut body, out_binding, &formal_call);
    // Quantify over each formal (innermost = last formal).
    for (formal, sort) in formals.iter().zip(sorts.iter()).rev() {
        body = json!({ "kind": "forall", "name": formal, "sort": sort, "body": body });
    }
    Some(body)
}

/// Replace every `{"kind":"var","name":<name>}` node with `replacement`.
fn substitute_var(node: &mut Json, name: &str, replacement: &Json) {
    if node.get("kind").and_then(|k| k.as_str()) == Some("var")
        && node.get("name").and_then(|n| n.as_str()) == Some(name)
    {
        *node = replacement.clone();
        return;
    }
    match node {
        Json::Object(map) => {
            for child in map.values_mut() {
                substitute_var(child, name, replacement);
            }
        }
        Json::Array(arr) => {
            for child in arr.iter_mut() {
                substitute_var(child, name, replacement);
            }
        }
        _ => {}
    }
}

/// The vendor's sworn fact for the consumer's OWN callsite: an `=(lhs, value)`
/// atom whose `lhs` matches the consumer's asserted call term.
///
/// #3807: `clientFactIr` is now CONSTRUCTED at the pool as the conjunction of
/// the group's OWN-origin candidates ONLY (see `consistency.rs`'s
/// `client_fact_partitioned`); it never carries the vendor's conjunct, so
/// there is nothing left here to disambiguate by position. This is a trivial
/// projection: `vendorFactIr` may hold sworn vectors for OTHER arguments of
/// the same callee (the pool conjoins every fact sharing the callee symbol,
/// e.g. `len(a)=0`, `len(b)=2`, `len(c)=20`), so match by LHS to pick out the
/// vector that actually shares the consumer's own call term. No positional
/// `first()` heuristic, no client-side disambiguation: if no `vendorFactIr`
/// entry's LHS matches, there is no vendor sworn fact for this callsite (the
/// derive-case fallback in `verification_with_fol` handles that case).
fn matching_vendor_fact(v: &Json) -> Option<Json> {
    let client_eqs = collect_equalities(v.get("clientFactIr")?);
    let vf = v.get("vendorFactIr").and_then(|x| x.as_array())?;
    for f in vf {
        for (vl, vr) in collect_equalities(f) {
            if client_eqs.iter().any(|(cl, _)| *cl == vl) {
                return Some(json!({ "kind": "atomic", "name": "=", "args": [vl, vr] }));
            }
        }
    }
    None
}

/// Collect every `=(lhs, rhs)` equality atom in a formula (descending through
/// `and`), as `(lhs, rhs)` ProofIR term pairs.
fn collect_equalities(formula: &Json) -> Vec<(Json, Json)> {
    let mut out = Vec::new();
    collect_equalities_into(formula, &mut out);
    out
}

fn collect_equalities_into(node: &Json, out: &mut Vec<(Json, Json)>) {
    if node.get("kind").and_then(|k| k.as_str()) == Some("atomic")
        && node.get("name").and_then(|n| n.as_str()) == Some("=")
    {
        if let Some(args) = node.get("args").and_then(|a| a.as_array()) {
            if args.len() == 2 {
                out.push((args[0].clone(), args[1].clone()));
                return;
            }
        }
    }
    match node {
        Json::Object(map) => {
            for child in map.values() {
                collect_equalities_into(child, out);
            }
        }
        Json::Array(arr) => {
            for child in arr {
                collect_equalities_into(child, out);
            }
        }
        _ => {}
    }
}

/// Locate the vendor universe's `str.eq-bv-blocks` atom for this callsite
/// (preferring the INSTANTIATED post, which binds the consumer's argument) and
/// return a derive-ready payload JSON -- the walked block equations with
/// `input_bytes` bound to the pinned input's UTF-8 bytes. Searches each
/// `linkedPosts[].{instantiatedPost,vendorPost}` recursively. None if no such
/// atom / bound input is present.
fn universe_blocks_payload(v: &Json) -> Option<String> {
    let posts = v.get("linkedPosts").and_then(|x| x.as_array())?;
    for post in posts {
        for field in ["instantiatedPost", "vendorPost"] {
            if let Some(ir) = post.get(field) {
                if let Some(p) = blocks_payload_from_node(ir) {
                    return Some(p);
                }
            }
        }
    }
    None
}

/// Recursively find a `str.eq-bv-blocks` atom and build a derive-ready payload.
fn blocks_payload_from_node(node: &Json) -> Option<String> {
    if node.get("kind").and_then(|k| k.as_str()) == Some("atomic")
        && node.get("name").and_then(|n| n.as_str()) == Some("str.eq-bv-blocks")
    {
        if let Some(p) = derive_ready_payload(node) {
            return Some(p);
        }
    }
    match node {
        Json::Object(map) => map.values().find_map(blocks_payload_from_node),
        Json::Array(arr) => arr.iter().find_map(blocks_payload_from_node),
        _ => None,
    }
}

/// From a `str.eq-bv-blocks` atom, produce a payload JSON with `input_bytes`
/// bound. The atom is `[subject, payload]` (payload already carries bytes) or
/// `[subject, input, payload]` (bind the bytes from the pinned input String
/// const -- the general ∀ body carries only var names, so the concrete input
/// lives in the second arg). None if the payload is unreadable or the input is
/// not a pinned string literal.
fn derive_ready_payload(atom: &Json) -> Option<String> {
    let args = atom.get("args").and_then(|a| a.as_array())?;
    let (input_term, payload_term) = match args.as_slice() {
        [_subject, payload] => (None, payload),
        [_subject, input, payload] => (Some(input), payload),
        _ => return None,
    };
    let raw = payload_term.get("value").and_then(|x| x.as_str())?;
    let mut payload: Json = serde_json::from_str(raw).ok()?;
    // Already carries concrete bytes -> derive as-is.
    if payload
        .get("input_bytes")
        .and_then(|x| x.as_array())
        .is_some()
    {
        return Some(raw.to_string());
    }
    // Otherwise bind them from the pinned input string literal.
    let input_str = input_term?.get("value").and_then(|x| x.as_str())?;
    let bytes: Vec<Json> = input_str.bytes().map(|b| json!(b as i64)).collect();
    if let Json::Object(map) = &mut payload {
        map.insert("input_bytes".to_string(), Json::Array(bytes));
    }
    serde_json::to_string(&payload).ok()
}

/// Ask z3 what the block-equation universe COMPUTES (its output string) at the
/// pinned input -- the derived vendor value. The same z3.model derive
/// `sugar derive` performs. None (fail-open) if z3 is absent or non-sat.
fn derive_blocks_value(payload_json: &str) -> Option<String> {
    use std::io::Write;
    use std::process::{Command, Stdio};
    let dq =
        sugar_ir_compiler_smt_lib::derive_query::emit_blocks_derive_query(payload_json).ok()?;
    let mut child = Command::new("z3")
        .args(["-smt2", "-in"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    child.stdin.as_mut()?.write_all(dq.smt.as_bytes()).ok()?;
    let out = child.wait_with_output().ok()?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let lines: Vec<&str> = stdout
        .lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty())
        .collect();
    if lines.first().copied() != Some("sat") {
        return None;
    }
    let model_line = lines.get(1).copied().unwrap_or("");
    sugar_ir_compiler_smt_lib::derive_query::parse_model_string(model_line, &dq.result_var)
}

/// Clone the consumer's own asserted equality and swap its RIGHT-HAND side for
/// the string literal `rhs`, yielding the vendor's fact for the same callsite:
/// `call:f(arg) = <derived>`. Swaps the equality atom's `args[1]` (NOT the first
/// string leaf, which would be the call's own `"xyz"` argument). None if no
/// 2-arg atomic is found.
fn client_fact_with_rhs(client_ir: &Json, rhs: &str) -> Option<Json> {
    let mut cloned = client_ir.clone();
    if replace_eq_rhs(&mut cloned, rhs) {
        Some(cloned)
    } else {
        None
    }
}

fn replace_eq_rhs(node: &mut Json, rhs: &str) -> bool {
    if let Json::Object(map) = node {
        if map.get("kind").and_then(|k| k.as_str()) == Some("atomic") {
            if let Some(Json::Array(args)) = map.get_mut("args") {
                if args.len() == 2 {
                    args[1] = json!({ "str": rhs });
                    return true;
                }
            }
        }
        return map.values_mut().any(|child| replace_eq_rhs(child, rhs));
    }
    if let Json::Array(arr) = node {
        return arr.iter_mut().any(|child| replace_eq_rhs(child, rhs));
    }
    false
}

/// Prefix a rendered FOL formula with the turnstile, matching the
/// `{name} ⊢ {rendered}` shape of `sugar lift --report --visual`.
fn fol_line(rendered: &str) -> String {
    format!("⊢ {rendered}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn cid(seed: &str) -> MementoCid {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(seed.as_bytes()))
            .expect("test CID must parse")
    }

    fn cid_string(seed: &str) -> String {
        cid(seed).to_string()
    }

    #[test]
    fn consistency_row_carries_the_assertion_source_locus() {
        // An `unsatisfied` consistency verdict must say WHERE: the assertion's
        // own source locus (file/line/column) has to survive onto the row so an
        // IDE can anchor a red squiggle at the exact `assert` instead of the
        // top of the file. Regression guard for the #3462-family seam.
        let mut r = Report::default();
        add_consistency_with_verification(
            &cid_string("c"),
            "encodeBase64#euf#c:call:encodeBase64(s:'xyz')::assertion",
            ObligationVerdict::Unsatisfied,
            "test assertions contradictory about callsite",
            None,
            Some(SourceLocus {
                file: "test_consumer.py".to_string(),
                line: 9,
                column: Some(4),
            }),
            &mut r,
        );
        assert_eq!(r.rows.len(), 1);
        let cs = &r.rows[0].callsite;
        assert_eq!(cs.file.as_deref(), Some("test_consumer.py"));
        assert_eq!(cs.line, Some(9));
        assert_eq!(cs.source_column, Some(4));
        assert_eq!(r.rows[0].status, ObligationVerdict::Unsatisfied);
    }

    #[test]
    fn consistency_row_without_locus_stays_unanchored() {
        // No locus available (fail-open): the row must NOT invent a line.
        let mut r = Report::default();
        add_consistency(
            &cid_string("c"),
            "some::assertion",
            ObligationVerdict::Discharged,
            "consistent",
            &mut r,
        );
        let cs = &r.rows[0].callsite;
        assert_eq!(cs.file, None);
        assert_eq!(cs.line, None);
        assert_eq!(cs.source_column, None);
    }

    #[test]
    fn forall_universe_row_renders_quantified_law_and_instantiated_vendor_fact() {
        // The rust bounded-loop universe case (#3774 case 2, the shape
        // examples/rust-forall-universe-federation produces): the linked post
        // carries its own quantification metadata (call/formals/outBinding),
        // so the universe must render as the ∀ law -- NOT the bare out-binding
        // body `out = 64` -- and the vendor's fact at the consumer's OWN
        // argument (materialized by the verifier into vendorFactIr) must
        // surface as the third conjunct.
        let mut r = Report::default();
        add_consistency_with_verification(
            &cid_string("c"),
            "tests/consumer_test.rs::consumer_asserts_block_width_at_3::block_width#euf#c:callresult_block_width_a1(i:3)::assertion",
            ObligationVerdict::Unsatisfied,
            "contradictory",
            Some(json!({
                "kind": "consistency",
                "linkedPosts": [{
                    "sourceSymbol": "call:block_width",
                    "formals": ["_level"],
                    "outBinding": "out",
                    "call": { "kind": "ctor", "name": "call:block_width", "args": [
                        { "kind": "const", "value": 3,
                          "sort": { "kind": "primitive", "name": "Int" } }
                    ]},
                    "vendorPost": {
                        "kind": "atomic", "name": "=",
                        "args": [
                            { "kind": "var", "name": "out" },
                            { "kind": "const", "value": 64,
                              "sort": { "kind": "primitive", "name": "Int" } }
                        ]
                    }
                }],
                "clientFactIr": {
                    "kind": "and",
                    "operands": [{
                        "kind": "atomic", "name": "=",
                        "args": [
                            { "kind": "ctor", "name": "call:block_width", "args": [
                                { "kind": "const", "value": 3,
                                  "sort": { "kind": "primitive", "name": "Int" } }
                            ]},
                            { "kind": "const", "value": 128,
                              "sort": { "kind": "primitive", "name": "Int" } }
                        ]
                    }]
                },
                "vendorFactIr": [{
                    "kind": "atomic", "name": "=",
                    "args": [
                        { "kind": "ctor", "name": "call:block_width", "args": [
                            { "kind": "const", "value": 3,
                              "sort": { "kind": "primitive", "name": "Int" } }
                        ]},
                        { "kind": "const", "value": 64,
                          "sort": { "kind": "primitive", "name": "Int" } }
                    ]
                }],
            })),
            None,
            &mut r,
        );

        let j = row_to_json(&r.rows[0]);
        let v = &j["verification"];
        let universe = v["vendorUniverseFol"].as_str().unwrap_or_default();
        let client = v["clientFactFol"].as_str().unwrap_or_default();
        let vendor = v["vendorFactFol"].as_str().unwrap_or_default();
        assert!(universe.contains('∀'), "universe must quantify: {universe}");
        assert!(universe.contains("_level"), "universe: {universe}");
        assert!(
            universe.contains("block_width(_level) = 64"),
            "universe: {universe}"
        );
        assert!(client.contains("block_width(3) = 128"), "client: {client}");
        assert!(vendor.contains("block_width(3) = 64"), "vendor: {vendor}");
    }

    #[test]
    fn universe_post_without_quantification_metadata_keeps_body_rendering() {
        // A linked post WITHOUT call/formals/outBinding must keep the existing
        // plain-body rendering (fail-open, no invented quantifier).
        let mut r = Report::default();
        add_consistency_with_verification(
            &cid_string("c"),
            "some::assertion",
            ObligationVerdict::Unsatisfied,
            "contradictory",
            Some(json!({
                "kind": "consistency",
                "linkedPosts": [{
                    "sourceSymbol": "call:block_width",
                    "vendorPost": {
                        "kind": "atomic", "name": "=",
                        "args": [
                            { "kind": "var", "name": "out" },
                            { "kind": "const", "value": 64,
                              "sort": { "kind": "primitive", "name": "Int" } }
                        ]
                    }
                }],
            })),
            None,
            &mut r,
        );

        let j = row_to_json(&r.rows[0]);
        let universe = j["verification"]["vendorUniverseFol"]
            .as_str()
            .unwrap_or_default();
        assert!(!universe.contains('∀'), "no invented ∀: {universe}");
        assert!(universe.contains("out = 64"), "universe: {universe}");
    }

    #[test]
    fn self_post_does_not_count_as_a_callsite() {
        let mut r = Report::default();
        let cs = CallSite {
            bridge_ir_name: "bridge.demo".into(),
            ..CallSite::default()
        };
        // One real call site, then one self-post obligation.
        add_callsite_with_method(&cs, ObligationVerdict::Discharged, "ok", None, &mut r);
        add_self_post_with_method(
            "blake3-512:contract",
            ObligationVerdict::Discharged,
            "reflexive self-post",
            Some("reflexive".into()),
            &mut r,
        );

        // The self-post MUST NOT inflate the call-site count: only the
        // genuine bridge obligation counts as a call site.
        assert_eq!(
            r.total_callsites, 1,
            "self-post must not count as a callsite"
        );
        // But it stays visible as a discharged row in the scoreboard.
        assert_eq!(r.discharged, 2, "self-post still counts toward discharged");
        assert_eq!(r.rows.len(), 2, "self-post row must remain visible");
        assert!(
            r.rows
                .iter()
                .any(|row| row.callsite.property_name == "self-post:blake3-512:contract"),
            "self-post row must be present for the discharge split to see it"
        );
    }

    #[test]
    fn failing_self_post_still_drives_a_violation() {
        let mut r = Report::default();
        add_self_post_with_method(
            "blake3-512:bad",
            ObligationVerdict::Unsatisfied,
            "internally inconsistent contract",
            None,
            &mut r,
        );
        // Excluding self-posts from the callsite count must NOT turn a
        // failing self-post into a green run.
        assert_eq!(r.total_callsites, 0, "self-post is not a callsite");
        assert_eq!(
            r.violations, 1,
            "a failing self-post must still fail the run"
        );
    }

    #[test]
    fn toolchain_plan_without_witness_is_declared() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:out"]
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "declared");
        assert_eq!(rows[0].plan_memento_cid, cid_string("plan-member"));
        assert_eq!(rows[0].plan_cid, "blake3-512:plan-letter");
        assert_eq!(rows[0].expected_output_cids, vec!["blake3-512:out"]);
        assert!(rows[0].witness_memento_cid.is_none());
    }

    #[test]
    fn toolchain_plan_matching_witness_pointer_is_confirmed() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:out"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "planCid": "blake3-512:plan-letter",
                    "actualOutputCids": ["blake3-512:out"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "confirmed");
        assert_eq!(
            rows[0].witness_memento_cid.as_deref(),
            Some(cid_string("witness-member").as_str())
        );
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:out"]);
    }

    #[test]
    fn toolchain_plan_mismatched_witness_pointer_is_refuted() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:expected"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "planCid": "blake3-512:plan-letter",
                    "actualOutputCids": ["blake3-512:actual"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "refuted");
        assert_eq!(rows[0].expected_output_cids, vec!["blake3-512:expected"]);
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:actual"]);
    }

    #[test]
    fn toolchain_plan_unscoped_matching_witness_is_declared_not_confirmed() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:out"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "actualOutputCids": ["blake3-512:out"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].status, "declared",
            "a toolchain output witness without planCid must not confirm any plan"
        );
        assert_eq!(
            rows[0].witness_memento_cid.as_deref(),
            Some(cid_string("witness-member").as_str())
        );
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:out"]);
        assert!(
            rows[0].reason.contains("missing planCid"),
            "report should say the toolchain witness was ignored because it is unscoped"
        );
    }

    #[test]
    fn toolchain_plan_unscoped_mismatched_witness_is_declared_not_refuted() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:expected"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "actualOutputCids": ["blake3-512:actual"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].status, "declared",
            "unscoped witnesses must not refute a plan"
        );
        assert_eq!(
            rows[0].witness_memento_cid.as_deref(),
            Some(cid_string("witness-member").as_str())
        );
        assert_eq!(rows[0].actual_output_cids, vec!["blake3-512:actual"]);
        assert!(
            rows[0].reason.contains("missing planCid"),
            "report should make the missing scope visible"
        );
    }

    #[test]
    fn toolchain_plan_ignores_witness_scoped_to_other_plan() {
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(
            cid("plan-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "plan-memento",
                    "planCid": "blake3-512:plan-letter"
                },
                "body": {
                    "kind": "component-plan",
                    "expectedOutputCids": ["blake3-512:expected"]
                }
            }),
        );
        pool.insert_unanchored_for_tests(
            cid("witness-member"),
            json!({
                "schemaVersion": "1",
                "header": {
                    "kind": "witness-memento",
                    "witnessCid": "blake3-512:witness-body",
                    "witnessKind": "toolchain-run"
                },
                "body": {
                    "kind": "witness-memento",
                    "witness_cid": "blake3-512:witness-body",
                    "planCid": "blake3-512:other-plan-letter",
                    "actualOutputCids": ["blake3-512:actual"],
                    "signer": "ed25519:test",
                    "signature": "ed25519:sig"
                }
            }),
        );

        let rows = toolchain_plan_reports(&pool);

        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].status, "declared",
            "a witness scoped to another plan is not evidence for this plan"
        );
        assert!(rows[0].witness_memento_cid.is_none());
    }
}
