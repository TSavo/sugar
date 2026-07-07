// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Pretty + JSON formatting for the verifier `Report`.

use crate::source_partition::{entries_to_json, row_line_accounting};
use owo_colors::OwoColorize;
use serde_json::{json, Value as Json};
use std::fmt::Write as _;
use sugar_verifier::superposition::{reports_from_report, Strength, SuperpositionReport};
use sugar_verifier::{LoadError, ObligationVerdict, Report, ReportRow};

pub fn report_to_json(r: &Report) -> Json {
    let rows: Vec<Json> = r.rows.iter().map(row_to_json).collect();
    let load_errors: Vec<Json> = r.load_errors.iter().map(load_error_to_json).collect();
    let call_edges: Vec<Json> = r
        .call_edges
        .iter()
        .map(|ce| {
            json!({
                "sourceContractCid": ce.source_contract_cid,
                "targetContractCid": ce.target_contract_cid,
                "file": ce.file,
            })
        })
        .collect();
    let toolchain_plans: Vec<Json> = r
        .toolchain_plans
        .iter()
        .map(|plan| {
            json!({
                "planMementoCid": plan.plan_memento_cid,
                "planCid": plan.plan_cid,
                "status": plan.status,
                "reason": plan.reason,
                "expectedOutputCids": plan.expected_output_cids,
                "witnessMementoCid": plan.witness_memento_cid,
                "actualOutputCids": plan.actual_output_cids,
            })
        })
        .collect();
    // Criterion 14 (#3706, part of #3686) total-line accounting: warrant
    // and effect entries derivable from rows alone (no source text needed).
    // `support` entries require source-file access this crate does not have;
    // callers with source access build the full `SourcePartition` and render
    // `lineAccounting` + `lineAccountingPartition` from it (see
    // `cmd_lift::render_report_json` / `source_partition::build_line_accounting`)
    // -- one partition, never a second, parallel classifier.
    let line_accounting = entries_to_json(&row_line_accounting(&r.rows));
    json!({
        "totalCallsites": r.total_callsites,
        "discharged": r.discharged,
        "violations": r.violations,
        "refused": r.refused,
        "dischargeSplit": discharge_split_to_json(r),
        "rows": rows,
        "lineAccounting": line_accounting,
        "loadErrors": load_errors,
        "callEdges": call_edges,
        "toolchainPlans": toolchain_plans,
        // Per-symbol superposition verdict: the N z3 compiles this run already
        // performed, folded by callee symbol. strength = surviving universe count.
        "superposition": superposition_to_json(r),
    })
}

fn superposition_to_json(r: &Report) -> Json {
    let reports = reports_from_report(r);
    let entries: Vec<Json> = reports.iter().map(superposition_report_to_json).collect();
    json!({
        "symbols": reports.len(),
        "strong": reports.iter().filter(|s| s.strength == Strength::Strong).count(),
        "weak": reports.iter().filter(|s| s.strength == Strength::Weak).count(),
        "undecidable": reports.iter().filter(|s| s.strength == Strength::Undecidable).count(),
        "reports": entries,
    })
}

fn superposition_report_to_json(s: &SuperpositionReport) -> Json {
    json!({
        "symbol": s.symbol,
        "strength": s.strength.tag(),
        "verdict": s.verdict,
        "levers": s.levers,
        "licensing": s.licensing,
        "findings": s.findings,
        "cid": s.cid,
    })
}

fn row_to_json(row: &ReportRow) -> Json {
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
fn verification_with_fol(verification: Option<&Json>) -> Json {
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
    if let Some(posts) = v.get("linkedPosts").and_then(|x| x.as_array()) {
        let mut readings: Vec<String> = Vec::new();
        for post in posts {
            if let Some(ir) = post.get("vendorPost") {
                let fol = crate::cmd_lift::proofir_formula_to_fol_with_instances(ir);
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
        let fol = crate::cmd_lift::proofir_formula_to_fol_with_instances(ir);
        obj.insert("clientFactFol".to_string(), json!(fol_line(&fol)));
    }

    // VENDOR FACT: the vendor's sworn value FOR THIS CALLSITE. The pool conjoins
    // EVERY sworn fact sharing the callee symbol (`len(array)=0`, `len(x)=2`,
    // `len(y)=20`, ...), so joining them all would show a wall of unrelated
    // vectors and a Quick Fix would grab an arbitrary one. Keep only the fact
    // whose LHS matches the consumer's OWN asserted callsite -- the value that
    // actually contradicts the assertion (`len(pd.DataFrame()) = 0`).
    if let Some(fact) = matching_vendor_fact(v) {
        let fol = crate::cmd_lift::proofir_formula_to_fol_with_instances(&fact);
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
                    let fol = crate::cmd_lift::proofir_formula_to_fol_with_instances(&ir);
                    obj.insert("vendorFactFol".to_string(), json!(fol_line(&fol)));
                }
            }
        }
    }

    out
}

/// The vendor's sworn fact for the consumer's OWN callsite: an `=(lhs, value)`
/// atom whose `lhs` matches the consumer's asserted call term and whose value
/// differs from what the consumer asserted (the contradicting vendor value).
/// The pool conjoins every fact sharing the callee symbol, so we match by LHS.
/// None if the consumer has no equality or nothing contradicts it.
fn matching_vendor_fact(v: &Json) -> Option<Json> {
    let client_eqs = collect_equalities(v.get("clientFactIr")?);
    // The consumer's own assertion is the first equality; its LHS is the
    // callsite, its RHS is the (possibly wrong) asserted value.
    let (lhs, asserted_rhs) = client_eqs.first()?;
    // Search the consumer's own conjuncts AND the vendor's sworn vectors for the
    // SAME callsite with a DIFFERENT value -- that value is the vendor's fact.
    let mut candidates = client_eqs.clone();
    if let Some(vf) = v.get("vendorFactIr").and_then(|x| x.as_array()) {
        for f in vf {
            candidates.extend(collect_equalities(f));
        }
    }
    for (l, r) in &candidates {
        if l == lhs && r != asserted_rhs {
            return Some(json!({ "kind": "atomic", "name": "=", "args": [l, r] }));
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
    if payload.get("input_bytes").and_then(|x| x.as_array()).is_some() {
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

fn discharge_split_to_json(r: &Report) -> Json {
    let mut panic_safe = 0usize;
    let mut reflexive = 0usize;
    let mut solver_substantive = 0usize;
    let mut vacuous = 0usize;
    let mut hash_tier = 0usize;
    let mut undecidable = 0usize;
    let mut false_pass = 0usize;

    for row in &r.rows {
        if row.status != ObligationVerdict::Discharged {
            undecidable += 1;
            continue;
        }
        let method = row.discharge_method.as_deref();
        if row.callsite.panic_site && method != Some("panic-safe") {
            false_pass += 1;
            continue;
        }
        match method {
            Some("panic-safe") if row.callsite.panic_site => panic_safe += 1,
            Some("panic-safe") => solver_substantive += 1,
            Some("reflexive") => reflexive += 1,
            Some("solver-substantive") => solver_substantive += 1,
            Some("vacuous") => vacuous += 1,
            Some("hash-tier") => hash_tier += 1,
            _ => solver_substantive += 1,
        }
    }

    json!({
        "panicSafe": panic_safe,
        "reflexive": reflexive,
        "solverSubstantive": solver_substantive,
        "vacuous": vacuous,
        "hashTier": hash_tier,
        "undecidable": undecidable,
        "falsePass": false_pass,
    })
}

fn load_error_to_json(e: &LoadError) -> Json {
    json!({
        "proofPath": e.proof_path,
        "reason": e.reason,
    })
}

pub fn format_report_pretty(r: &Report, quiet: bool) -> String {
    let mut out = String::new();
    if !quiet {
        let _ = writeln!(out, "{}", "Sugar verifier report".bold());
        let _ = writeln!(out, "  total callsites : {}", r.total_callsites);
        let _ = writeln!(
            out,
            "  discharged      : {}",
            r.discharged.to_string().green()
        );
        let _ = writeln!(
            out,
            "  violations      : {}",
            if r.violations == 0 {
                r.violations.to_string().green().to_string()
            } else {
                r.violations.to_string().red().to_string()
            }
        );
        let _ = writeln!(
            out,
            "  load errors     : {}",
            if r.load_errors.is_empty() {
                "0".green().to_string()
            } else {
                r.load_errors.len().to_string().red().to_string()
            }
        );
        out.push('\n');
        for row in &r.rows {
            let status_pretty = match row.status {
                ObligationVerdict::Discharged => "discharged".green().to_string(),
                ObligationVerdict::Unsatisfied => "unsatisfied".red().to_string(),
                ObligationVerdict::Undecidable => "undecidable".yellow().to_string(),
                ObligationVerdict::SolverTimeout => "solver-timeout".yellow().to_string(),
                ObligationVerdict::Disagreement => "disagreement".to_string(),
                ObligationVerdict::Refused => "refused".to_string(),
            };
            let _ = writeln!(
                out,
                "  [{}] {}  ({} -> {})",
                status_pretty,
                row.callsite.bridge_ir_name,
                row.callsite.bridge_source_layer,
                row.callsite.bridge_target_layer
            );
            if !row.reason.is_empty() {
                let _ = writeln!(out, "      reason: {}", row.reason);
            }
            if let Some(tier) = &row.body_discharge_tier {
                let _ = writeln!(out, "      body tier: {}", tier);
            }
            if let Some(verification) = &row.verification {
                format_verification_detail(&mut out, verification);
            }
        }
        let superpositions = reports_from_report(r);
        if !superpositions.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Superposition (strength per symbol):".bold());
            for s in &superpositions {
                let strength_pretty = match s.strength {
                    Strength::Strong => s.strength.tag().green().to_string(),
                    Strength::Weak => s.strength.tag().yellow().to_string(),
                    Strength::Undecidable => s.strength.tag().red().to_string(),
                };
                let _ = writeln!(out, "  [{}] {}", strength_pretty, s.symbol);
                if !s.findings.is_empty() {
                    let _ = writeln!(out, "      findings: {}", s.findings.len());
                }
                if !s.levers.is_empty() {
                    let _ = writeln!(out, "      collapse: {}", s.levers.join(" | "));
                }
            }
        }
        if !r.load_errors.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Load errors:".red().bold());
            for e in &r.load_errors {
                let _ = writeln!(out, "  {}: {}", e.proof_path, e.reason);
            }
        }
        if !r.toolchain_plans.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Toolchain plans:".bold());
            for plan in &r.toolchain_plans {
                let status_pretty = match plan.status.as_str() {
                    "confirmed" => "confirmed".green().to_string(),
                    "refuted" => "refuted".red().to_string(),
                    "declared" => "declared".yellow().to_string(),
                    other => other.to_string(),
                };
                let _ = writeln!(out, "  [{}] plan {}", status_pretty, plan.plan_cid);
                let _ = writeln!(out, "      plan memento: {}", plan.plan_memento_cid);
                if let Some(witness) = &plan.witness_memento_cid {
                    let _ = writeln!(out, "      witness memento: {witness}");
                }
                let _ = writeln!(
                    out,
                    "      expected outputs: {}",
                    plan.expected_output_cids.len()
                );
                for cid in &plan.expected_output_cids {
                    let _ = writeln!(out, "        {cid}");
                }
                let _ = writeln!(
                    out,
                    "      actual outputs: {}",
                    plan.actual_output_cids.len()
                );
                for cid in &plan.actual_output_cids {
                    let _ = writeln!(out, "        {cid}");
                }
                if !plan.reason.is_empty() {
                    let _ = writeln!(out, "      reason: {}", plan.reason);
                }
            }
        }
        if !r.call_edges.is_empty() {
            out.push('\n');
            let _ = writeln!(out, "{}", "Call edges:".dimmed());
            for ce in &r.call_edges {
                let _ = writeln!(
                    out,
                    "  {} -> {}  ({})",
                    ce.source_contract_cid.chars().take(32).collect::<String>(),
                    ce.target_contract_cid.chars().take(32).collect::<String>(),
                    ce.file
                );
            }
        }
    }
    out
}

pub fn print_report_pretty(r: &Report, quiet: bool) {
    print!("{}", format_report_pretty(r, quiet));
}

fn compact_json(v: &Json) -> String {
    serde_json::to_string(v).unwrap_or_else(|_| v.to_string())
}

fn format_verification_detail(out: &mut String, v: &Json) {
    let kind = v
        .get("kind")
        .and_then(|x| x.as_str())
        .unwrap_or("verification");
    let _ = writeln!(out, "      verifier: {kind}");
    if let Some(cid) = v.get("checkedFormulaCid").and_then(|x| x.as_str()) {
        let _ = writeln!(out, "        checked formula (cid): {cid}");
    } else if let Some(formula) = v.get("checkedFormula") {
        // Legacy reports / fixtures that still carry the inline formula.
        let _ = writeln!(out, "        checked: {}", compact_json(formula));
    }
    if let Some(posts) = v.get("linkedPosts").and_then(|x| x.as_array()) {
        let _ = writeln!(out, "        linked posts: {}", posts.len());
        for post in posts {
            let source = post
                .get("sourceSymbol")
                .and_then(|x| x.as_str())
                .unwrap_or("<unknown>");
            let target = post
                .get("targetContractCid")
                .and_then(|x| x.as_str())
                .unwrap_or("<unknown>");
            let _ = writeln!(out, "          {} -> {}", source, target);
            if let Some(call) = post.get("call") {
                let _ = writeln!(out, "            call: {}", compact_json(call));
            }
            if let Some(instantiated) = post.get("instantiatedPost") {
                let _ = writeln!(out, "            post: {}", compact_json(instantiated));
            }
        }
    }
    if let Some(invs) = v.get("solverInvocations").and_then(|x| x.as_array()) {
        let _ = writeln!(out, "        solver invocations: {}", invs.len());
        for inv in invs {
            let solver = inv.get("solver").and_then(|x| x.as_str()).unwrap_or("?");
            let compiler = inv.get("compiler").and_then(|x| x.as_str()).unwrap_or("?");
            let verdict = inv.get("verdict").and_then(|x| x.as_str()).unwrap_or("?");
            let authoritative = inv
                .get("authoritative")
                .and_then(|x| x.as_bool())
                .unwrap_or(false);
            if let Some(ms) = inv.get("wallClockMs").and_then(|x| x.as_u64()) {
                let _ = writeln!(
                    out,
                    "          {solver} via {compiler}: {verdict} ({ms}ms, authoritative={authoritative})"
                );
            } else {
                let _ = writeln!(
                    out,
                    "          {solver} via {compiler}: {verdict} (authoritative={authoritative})"
                );
            }
            if let Some(cid) = inv.get("solverArtifactCid").and_then(|x| x.as_str()) {
                let _ = writeln!(out, "            artifact: {cid}");
            }
            if let Some(cid) = inv.get("solverInvocationCid").and_then(|x| x.as_str()) {
                let _ = writeln!(out, "            invocation: {cid}");
            }
            if let Some(cid) = inv.get("solverVendorMementoCid").and_then(|x| x.as_str()) {
                let _ = writeln!(out, "            vendor memento: {cid}");
            }
        }
    }
}

/// Decide an exit code from a proof report. A load-bearing `prove` run must
/// have checked at least one callsite or one contract-level obligation;
/// completely empty reports are vacuous.
pub fn report_exit_code(r: &Report) -> u8 {
    let toolchain_refuted = r
        .toolchain_plans
        .iter()
        .any(|plan| plan.status == "refuted");
    if r.violations > 0 || !r.load_errors.is_empty() || toolchain_refuted || r.rows.is_empty() {
        crate::EXIT_VERIFY_FAIL
    } else {
        crate::EXIT_OK
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_verifier::{
        CallSite, MementoCid, ObligationVerdict, Report, ReportRow, ToolchainPlanReport,
    };

    #[test]
    fn empty_report_is_not_a_successful_proof() {
        let r = Report::default();
        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
        let j = report_to_json(&r);
        assert_eq!(j["totalCallsites"], 0);
        assert_eq!(j["violations"], 0);
    }

    #[test]
    fn report_with_violation_exits_fail() {
        let mut r = Report::default();
        r.violations = 1;
        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
    }

    #[test]
    fn report_with_load_error_exits_fail() {
        let mut r = Report::default();
        r.load_errors.push(LoadError {
            proof_path: "x.proof".into(),
            reason: "bogus".into(),
        });
        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
    }

    #[test]
    fn report_json_includes_body_discharge_tier() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "double".into(),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("reflexive".into()),
            body_discharge_tier: Some("body-eq-same-callee".into()),
            verification: None,
        });

        let j = report_to_json(&r);
        assert_eq!(j["rows"][0]["bodyDischargeTier"], "body-eq-same-callee");
    }

    #[test]
    fn report_json_includes_verification_detail() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "consistency".into(),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("consistency".into()),
            body_discharge_tier: None,
            verification: Some(json!({
                "kind": "consistency",
                "checkedFormula": { "kind": "literal", "value": true },
                "linkedPosts": [
                    {
                        "sourceSymbol": "call:enc",
                        "targetContractCid": "blake3-512:vendor",
                        "instantiatedPost": { "kind": "equals", "operands": [] }
                    }
                ],
                "solverInvocations": [
                    {
                        "solver": "cvc5",
                        "compiler": "smt-lib-v2.6",
                        "authoritative": true,
                        "verdict": "unsatisfied"
                    }
                ]
            })),
        });

        let j = report_to_json(&r);
        assert_eq!(j["rows"][0]["verification"]["kind"], "consistency");
        assert_eq!(
            j["rows"][0]["verification"]["solverInvocations"][0]["compiler"],
            "smt-lib-v2.6"
        );
        assert_eq!(
            j["rows"][0]["verification"]["linkedPosts"][0]["sourceSymbol"],
            "call:enc"
        );
    }

    #[test]
    fn consistency_row_renders_three_part_fol() {
        // A consistency row carrying the vendor universe (linkedPosts.vendorPost),
        // the consumer's own fact (clientFactIr), and the vendor's sworn vector
        // (vendorFactIr) as ProofIR must surface all three as human-readable FOL
        // rendered by the SAME renderer `sugar lift --report --visual` uses.
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "consistency".into(),
                property_name: "consistency:enc#euf#c:call:enc(s:'xyz')::assertion".into(),
                ..CallSite::default()
            },
            status: ObligationVerdict::Unsatisfied,
            reason: "contradictory".into(),
            discharge_method: Some("consistency".into()),
            body_discharge_tier: None,
            verification: Some(json!({
                "kind": "consistency",
                "linkedPosts": [{
                    "sourceSymbol": "call:enc",
                    "vendorPost": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            { "kind": "var", "name": "out" },
                            { "kind": "const", "value": "YWJj",
                              "sort": { "kind": "primitive", "name": "String" } }
                        ]
                    }
                }],
                "clientFactIr": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        { "kind": "ctor", "name": "call:enc", "args": [
                            { "kind": "const", "value": "xyz",
                              "sort": { "kind": "primitive", "name": "String" } }
                        ]},
                        { "kind": "const", "value": "AAAA",
                          "sort": { "kind": "primitive", "name": "String" } }
                    ]
                },
                "vendorFactIr": [{
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        { "kind": "ctor", "name": "call:enc", "args": [
                            { "kind": "const", "value": "abc",
                              "sort": { "kind": "primitive", "name": "String" } }
                        ]},
                        { "kind": "const", "value": "YWJj",
                          "sort": { "kind": "primitive", "name": "String" } }
                    ]
                }],
            })),
        });

        let j = report_to_json(&r);
        let v = &j["rows"][0]["verification"];
        let universe = v["vendorUniverseFol"].as_str().unwrap_or_default();
        let client = v["clientFactFol"].as_str().unwrap_or_default();
        let vendor = v["vendorFactFol"].as_str().unwrap_or_default();
        assert!(universe.starts_with("⊢ "), "universe: {universe}");
        assert!(client.contains("call:enc(\"xyz\")"), "client: {client}");
        assert!(client.contains("\"AAAA\""), "client: {client}");
        assert!(vendor.contains("call:enc(\"abc\")"), "vendor: {vendor}");
        assert!(vendor.contains("\"YWJj\""), "vendor: {vendor}");
    }

    #[test]
    fn non_consistency_verification_passes_through_unchanged() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite::default(),
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("reflexive".into()),
            body_discharge_tier: None,
            verification: Some(json!({ "kind": "body-eq" })),
        });
        let j = report_to_json(&r);
        assert_eq!(j["rows"][0]["verification"]["kind"], "body-eq");
        assert!(j["rows"][0]["verification"]["vendorUniverseFol"].is_null());
    }

    #[test]
    fn report_json_includes_toolchain_plan_accounting() {
        let mut r = Report::default();
        r.toolchain_plans.push(ToolchainPlanReport {
            plan_memento_cid: "blake3-512:plan-member".into(),
            plan_cid: "blake3-512:plan-letter".into(),
            status: "declared".into(),
            reason: "plan is pinned".into(),
            expected_output_cids: vec!["blake3-512:out".into()],
            witness_memento_cid: None,
            actual_output_cids: Vec::new(),
        });

        let j = report_to_json(&r);

        assert_eq!(
            j["toolchainPlans"][0]["planMementoCid"],
            "blake3-512:plan-member"
        );
        assert_eq!(j["toolchainPlans"][0]["status"], "declared");
        assert_eq!(
            j["toolchainPlans"][0]["expectedOutputCids"][0],
            "blake3-512:out"
        );
    }

    #[test]
    fn pretty_report_includes_toolchain_plan_accounting() {
        let mut r = Report::default();
        r.toolchain_plans.push(ToolchainPlanReport {
            plan_memento_cid: "blake3-512:plan-member".into(),
            plan_cid: "blake3-512:plan-letter".into(),
            status: "refuted".into(),
            reason: "plan drifted".into(),
            expected_output_cids: vec!["blake3-512:expected".into()],
            witness_memento_cid: Some("blake3-512:witness-member".into()),
            actual_output_cids: vec!["blake3-512:actual".into()],
        });

        let pretty = format_report_pretty(&r, false);

        assert!(pretty.contains("Toolchain plans:"), "{pretty}");
        assert!(pretty.contains("plan blake3-512:plan-letter"), "{pretty}");
        assert!(
            pretty.contains("plan memento: blake3-512:plan-member"),
            "{pretty}"
        );
        assert!(
            pretty.contains("witness memento: blake3-512:witness-member"),
            "{pretty}"
        );
        assert!(
            pretty.contains("expected outputs: 1")
                && pretty.contains("blake3-512:expected")
                && pretty.contains("actual outputs: 1")
                && pretty.contains("blake3-512:actual"),
            "{pretty}"
        );
        assert!(pretty.contains("reason: plan drifted"), "{pretty}");
    }

    #[test]
    fn refuted_toolchain_plan_exits_fail() {
        let mut r = Report {
            discharged: 1,
            ..Report::default()
        };
        r.rows.push(ReportRow {
            callsite: CallSite::default(),
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("hash-tier".into()),
            body_discharge_tier: None,
            verification: None,
        });
        r.toolchain_plans.push(ToolchainPlanReport {
            plan_memento_cid: "blake3-512:plan-member".into(),
            plan_cid: "blake3-512:plan-letter".into(),
            status: "refuted".into(),
            reason: "drift".into(),
            expected_output_cids: vec!["blake3-512:expected".into()],
            witness_memento_cid: Some("blake3-512:witness-member".into()),
            actual_output_cids: vec!["blake3-512:actual".into()],
        });

        assert_eq!(report_exit_code(&r), crate::EXIT_VERIFY_FAIL);
    }

    #[test]
    fn discharged_consistency_row_is_not_vacuous() {
        let mut r = Report {
            discharged: 1,
            ..Report::default()
        };
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "consistency".into(),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: "ok".into(),
            discharge_method: Some("consistency".into()),
            body_discharge_tier: None,
            verification: Some(json!({ "kind": "consistency" })),
        });

        assert_eq!(report_exit_code(&r), crate::EXIT_OK);
    }

    #[test]
    fn report_json_includes_callsite_bundle_cid_when_present() {
        let mut r = Report::default();
        let bundle_cid =
            MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(b"caller-bundle"))
                .expect("test CID must parse");
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "method:unwrap".into(),
                callsite_bundle_cid: Some(bundle_cid.clone()),
                panic_site: true,
                ..CallSite::default()
            },
            status: ObligationVerdict::Undecidable,
            reason: "synthetic panic row".into(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        });

        let j = report_to_json(&r);

        assert_eq!(j["rows"][0]["callsiteBundleCid"], bundle_cid.to_string());
    }

    #[test]
    fn report_json_nulls_callsite_bundle_cid_when_absent() {
        let mut r = Report::default();
        r.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "method:unwrap".into(),
                panic_site: true,
                ..CallSite::default()
            },
            status: ObligationVerdict::Undecidable,
            reason: "synthetic panic row".into(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        });

        let j = report_to_json(&r);

        assert!(
            j["rows"][0]["callsiteBundleCid"].is_null(),
            "absent callsite bundle should serialize as null to match existing Option field style"
        );
    }
}
