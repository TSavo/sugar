// SPDX-License-Identifier: Apache-2.0
//
// IDD instrument: EVERYTHING must read/write `.proof` catalogs through the
// `ProofGraph` api in `sugar-proof-envelope`, never by hand. This audit
// recognizes the live offender set across the Rust workspace, reports `R` per
// axis, prints the replacement for each offender, and stays RED until `R == 0`.
//
// The owner crate (`sugar-proof-envelope`) is exempt -- it IS the api and is the
// one place allowed to touch CBOR/member bytes directly.
//
// DECODE AXIS IS COMPILER-ENFORCED: `cbor_decode::decode` is now `pub(crate)`
// in sugar-proof-envelope. Any external call to `cbor_decode::decode` or the
// former `sugar_proof_envelope::cbor_decode(` alias is a compile error. The
// one sanctioned raw site is `sugar_proof_envelope::decode_for_conformance`,
// used only by sugar-verifier/proof_conformance.rs for protocol-encoding checks
// (deterministic re-encoding comparison, raw signature/kind/metadata). No grep
// needed here; the compiler is exhaustive.
//
// Remaining axis (still grep-enforced; compiler cannot catch stringly patterns):
//   member  member shape parsed by hand    -> MemberView::{kind,body_cid,json} / contracts()
//             (memento_kind/body(_field), or /header//evidence//envelope pointer fishing)

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

const OWNER_CRATE: &str = "sugar-proof-envelope";

fn rust_sources(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else {
            continue;
        };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if name == "target" || name == OWNER_CRATE {
                    continue;
                }
                stack.push(p);
            } else if p.extension().and_then(|x| x.to_str()) == Some("rs") {
                out.push(p);
            }
        }
    }
    out
}

/// Classify a source line as an api-bypass offender on the member axis.
/// The decode axis is compiler-enforced (cbor_decode::decode is pub(crate));
/// only the stringly member-shape patterns still require grep.
fn offending_axis(line: &str) -> Option<&'static str> {
    let t = line.trim();
    if t.starts_with("//") || t.starts_with('*') || t.starts_with("//!") {
        return None;
    }
    if t.contains("memento_kind(")
        || t.contains("memento_body(")
        || t.contains("memento_body_field(")
        || t.contains(".pointer(\"/header/")
        || t.contains(".pointer(\"/evidence/")
        || t.contains(".pointer(\"/envelope/")
    {
        Some("member")
    } else {
        None
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct RawPoolMemberOffender {
    path: String,
    line: usize,
    axis: &'static str,
    text: String,
}

#[derive(Debug, Clone)]
struct ExpectedRawPoolMemberOffender {
    path: &'static str,
    line: usize,
    axis: &'static str,
    owner: &'static str,
    replacement: &'static str,
    needle: &'static str,
}

const EXPECTED_RAW_POOL_MEMBER_ACCESS: &[ExpectedRawPoolMemberOffender] = &[
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1589, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1590, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, MemberKind::Contract) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1609, axis: "raw-pool-map-argument", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, _envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1610, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, MemberKind::Bridge) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1637, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (_, envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1652, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (_, envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1666, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (_, envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1682, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (_, envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1702, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".filter(|(cid, _)| pool.member_is_kind(cid, MemberKind::Implication))" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1707, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".filter(|(cid, _)| pool.member_is_kind(cid, MemberKind::WitnessMemento))" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1730, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (_, envelope) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1785, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".filter(|(cid, _)| pool.member_is_kind(cid, MemberKind::Implication))" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1833, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if let Some(value) = pool.member_field(cid, field).cloned() {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1986, axis: "raw-pool-map-get", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let envelope = pool.mementos.get(cid)?;" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 1987, axis: "pool-member-body-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let body = pool.resolve_contract_body(envelope)?;" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 2182, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".or_else(|| pool.member_field(cid, \"name\"))" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_lift.rs", line: 2190, axis: "pool-member-body-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if let Some(body) = pool.resolve_contract_body(envelope) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1305, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, env) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1306, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, sugar_verifier::MemberKind::Contract) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1311, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".or_else(|| pool.member_field(cid, \"name\"))" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1318, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "pool.member_field(cid, \"bodyDischargeEligible\")" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1319, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".or_else(|| pool.member_field(cid, \"body_discharge_eligible\"))," },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1320, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "pool.member_field(cid, \"bodyDischargeRefusalReason\")" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1321, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".or_else(|| pool.member_field(cid, \"body_discharge_refusal_reason\"))," },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1322, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "pool.member_field(cid, \"dischargePolicy\")," },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1338, axis: "pool-member-body-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let resolved_body = pool.resolve_contract_body(env);" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_mint.rs", line: 1343, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let has_post = pool.member_field(cid, \"postHash\").is_some();" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_verify.rs", line: 817, axis: "raw-pool-map-argument", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, _) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_verify.rs", line: 818, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, MemberKind::Contract) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_verify.rs", line: 833, axis: "raw-pool-map-get", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let envelope = pool.mementos.get(cid)?;" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_verify.rs", line: 834, axis: "pool-member-body-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let body = pool.resolve_contract_body(envelope)?;" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/cmd_verify.rs", line: 842, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "pool.member_field(cid, \"contractName\")" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/witness_verify.rs", line: 68, axis: "raw-pool-map-argument", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, _env) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/witness_verify.rs", line: 69, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, MemberKind::WitnessMemento) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/witness_verify.rs", line: 86, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, env) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/witness_verify.rs", line: 87, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, MemberKind::WitnessMemento) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/witness_verify.rs", line: 177, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if pool.member_field(cid, \"outcome\").and_then(|v| v.as_str()) == Some(\"failed\") {" },
    ExpectedRawPoolMemberOffender { path: "sugar-cli/src/witness_verify.rs", line: 240, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: ".any(|cid| pool.member_is_kind(cid, MemberKind::WitnessMemento))" },
    ExpectedRawPoolMemberOffender { path: "sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs", line: 3582, axis: "pool-bridge-json-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let Some(bridge_env) = pool.bridge_by_symbol(source_symbol) else {" },
    ExpectedRawPoolMemberOffender { path: "sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs", line: 3609, axis: "raw-pool-map-get", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "let target_env = pool.mementos.get(&target_memento_cid).unwrap_or_else(|| {" },
    ExpectedRawPoolMemberOffender { path: "sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs", line: 3615, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(&target_memento_cid, sugar_verifier::MemberKind::Contract) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs", line: 3907, axis: "raw-pool-map-iteration", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "for (cid, env) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs", line: 3908, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report/CLI pool accessors or test-only fixture helper", needle: "if !pool.member_is_kind(cid, sugar_verifier::MemberKind::SourceMemento) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 171, axis: "raw-pool-map-argument", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "for (cid, _) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 172, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "if !pool.member_is_kind(cid, MemberKind::WitnessMemento) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 179, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "pool.member_field(cid, \"actual_output_cids\")" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 190, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "pool.member_field(cid, \"plan_cid\")" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 201, axis: "raw-pool-map-argument", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "for (cid, _) in &pool.mementos {" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 202, axis: "pool-member-kind-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "if !pool.member_is_kind(cid, MemberKind::PlanMemento) {" },
    ExpectedRawPoolMemberOffender { path: "sugar-verifier/src/report.rs", line: 214, axis: "pool-member-field-accessor", owner: "Slice 6: reports, witnesses, CLI surfaces, and fixtures", replacement: "typed report pool accessors", needle: "pool.member_field(cid, \"expected_output_cids\")" },

];

fn is_production_source(rel: &str) -> bool {
    rel.contains("/src/") && !rel.contains("/tests/")
}

fn skip_test_cfg_line(
    trimmed: &str,
    pending_cfg_test: &mut bool,
    cfg_test_depth: &mut Option<isize>,
) -> bool {
    if let Some(depth) = cfg_test_depth {
        *depth += brace_delta(trimmed);
        if *depth <= 0 {
            *cfg_test_depth = None;
        }
        return true;
    }

    if trimmed == "#[cfg(test)]" || trimmed.starts_with("#[cfg(test)]") {
        *pending_cfg_test = true;
        return true;
    }

    if *pending_cfg_test {
        if trimmed.starts_with("#[") || trimmed.is_empty() {
            return true;
        }
        *pending_cfg_test = false;
        if trimmed == "{" {
            *cfg_test_depth = Some(1);
            return true;
        }
        if trimmed.starts_with("mod ")
            || trimmed.starts_with("fn ")
            || trimmed.starts_with("if ")
            || trimmed.starts_with("pub fn ")
            || trimmed.starts_with("pub(crate) fn ")
            || trimmed.starts_with("pub(super) fn ")
        {
            let depth = brace_delta(trimmed);
            if depth > 0 {
                *cfg_test_depth = Some(depth);
            }
            return true;
        }
    }

    false
}

fn brace_delta(line: &str) -> isize {
    line.chars().fold(0, |depth, ch| match ch {
        '{' => depth + 1,
        '}' => depth - 1,
        _ => depth,
    })
}

fn raw_pool_member_axis(path: &str, line: &str) -> Option<&'static str> {
    let trimmed = line.trim();
    if trimmed.starts_with("//") || trimmed.starts_with('*') || trimmed.starts_with("//!") {
        return None;
    }
    if trimmed.contains("pool.mementos.len()")
        || trimmed.contains("pool.mementos.keys()")
        || trimmed.contains("pool.mementos.contains_key")
        || trimmed.contains("sorted_keys(&pool.mementos)")
    {
        return None;
    }
    if trimmed.contains("pool.mementos.get(") {
        return Some("raw-pool-map-get");
    }
    if trimmed.contains(" in &pool.mementos") && !trimmed.contains(", _") {
        return Some("raw-pool-map-iteration");
    }
    if trimmed.contains("&pool.mementos") {
        return Some("raw-pool-map-argument");
    }
    if trimmed.contains("pool.member_field(") {
        return Some("pool-member-field-accessor");
    }
    if trimmed.contains("pool.member_kind(") || trimmed.contains("pool.member_is_kind(") {
        return Some("pool-member-kind-accessor");
    }
    if trimmed.contains("pool.resolve_contract_body(") {
        return Some("pool-member-body-accessor");
    }
    if trimmed.contains("pool.bridge_by_symbol(")
        || trimmed.contains("pool.bridge_by_callsite_key(")
    {
        return Some("pool-bridge-json-accessor");
    }
    if path.ends_with("sugar-verifier/src/load_all_proofs.rs")
        && (trimmed.contains("sugar_proof_envelope::member_kind(")
            || trimmed.contains("sugar_proof_envelope::member_body(")
            || trimmed.contains("sugar_proof_envelope::member_field("))
    {
        return Some("load-ingress-member-json-helper");
    }
    if path.ends_with("sugar-verifier/src/types.rs")
        && (trimmed.contains("sugar_proof_envelope::member_kind(")
            || trimmed.contains("sugar_proof_envelope::member_body(")
            || trimmed.contains("sugar_proof_envelope::member_field("))
    {
        return Some("pool-storage-member-json-helper");
    }
    if path.starts_with("sugar-verifier/src/")
        && (trimmed.contains("sugar_proof_envelope::member_kind(")
            || trimmed.contains("sugar_proof_envelope::member_body(")
            || trimmed.contains("sugar_proof_envelope::member_field("))
    {
        return Some("verifier-member-json-helper");
    }
    if path == "sugar-cli/src/cmd_lift.rs"
        && (trimmed.contains("sugar_proof_envelope::member_kind(")
            || trimmed.contains("sugar_proof_envelope::member_body(")
            || trimmed.contains("sugar_proof_envelope::member_field("))
    {
        return Some("cli-lift-member-json-helper");
    }
    if path == "sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs"
        && (trimmed.contains("member_body(") || trimmed.contains("member_field("))
    {
        return Some("rust-lift-kit-member-json-helper");
    }
    None
}

fn scan_raw_pool_member_access(workspace: &Path) -> Vec<RawPoolMemberOffender> {
    let mut offenders = Vec::new();
    for path in rust_sources(workspace) {
        if path.file_name().and_then(|n| n.to_str()) == Some("proof_api_audit.rs") {
            continue;
        }
        let rel = path
            .strip_prefix(workspace)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        if !is_production_source(&rel) {
            continue;
        }
        let Ok(src) = std::fs::read_to_string(&path) else {
            continue;
        };
        let mut pending_cfg_test = false;
        let mut cfg_test_depth = None;
        for (i, line) in src.lines().enumerate() {
            let trimmed = line.trim();
            if skip_test_cfg_line(trimmed, &mut pending_cfg_test, &mut cfg_test_depth) {
                continue;
            }
            if let Some(axis) = raw_pool_member_axis(&rel, line) {
                offenders.push(RawPoolMemberOffender {
                    path: rel.clone(),
                    line: i + 1,
                    axis,
                    text: trimmed.to_string(),
                });
            }
        }
    }
    offenders.sort();
    offenders
}

#[test]
fn raw_pool_member_access_frontier_is_pinned() {
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workspace root")
        .to_path_buf();

    let actual = scan_raw_pool_member_access(&workspace);
    let expected_keys: BTreeSet<_> = EXPECTED_RAW_POOL_MEMBER_ACCESS
        .iter()
        .map(|row| (row.path.to_string(), row.line, row.axis))
        .collect();
    let actual_keys: BTreeSet<_> = actual
        .iter()
        .map(|row| (row.path.clone(), row.line, row.axis))
        .collect();

    let missing: Vec<_> = expected_keys.difference(&actual_keys).cloned().collect();
    let unexpected: Vec<_> = actual_keys.difference(&expected_keys).cloned().collect();
    let mut bad_needles = Vec::new();
    for expected in EXPECTED_RAW_POOL_MEMBER_ACCESS {
        if let Some(row) = actual.iter().find(|row| {
            row.path == expected.path && row.line == expected.line && row.axis == expected.axis
        }) {
            if !row.text.contains(expected.needle) {
                bad_needles.push((
                    expected.path,
                    expected.line,
                    expected.needle,
                    row.text.clone(),
                ));
            }
        }
    }

    if !missing.is_empty() || !unexpected.is_empty() || !bad_needles.is_empty() {
        let mut report = String::new();
        report.push_str(&format!(
            "\nR(raw-pool-member-access) = {} measured offenders; pinned R = {}.\n\
             This Slice 1 instrument must name every raw verifier-pool member access and its replacement owner.\n\n",
            actual.len(),
            EXPECTED_RAW_POOL_MEMBER_ACCESS.len()
        ));
        if !unexpected.is_empty() {
            report.push_str("Unexpected offenders:\n");
            for (path, line, axis) in &unexpected {
                let text = actual
                    .iter()
                    .find(|row| row.path == *path && row.line == *line && row.axis == *axis)
                    .map(|row| row.text.as_str())
                    .unwrap_or("");
                report.push_str(&format!("  {path}:{line} [{axis}] {text}\n"));
            }
            report.push('\n');
        }
        if !missing.is_empty() {
            report.push_str("Missing pinned offenders:\n");
            for (path, line, axis) in &missing {
                report.push_str(&format!("  {path}:{line} [{axis}]\n"));
            }
            report.push('\n');
        }
        if !bad_needles.is_empty() {
            report.push_str("Pinned offenders whose line text changed:\n");
            for (path, line, needle, text) in &bad_needles {
                report.push_str(&format!(
                    "  {path}:{line} expected to contain `{needle}`, saw `{text}`\n"
                ));
            }
            report.push('\n');
        }
        report.push_str("Measured frontier by file:\n");
        let mut per_file: BTreeMap<&str, Vec<&RawPoolMemberOffender>> = BTreeMap::new();
        for offender in &actual {
            per_file.entry(&offender.path).or_default().push(offender);
        }
        for (path, rows) in per_file {
            report.push_str(&format!("  {path}  R={}\n", rows.len()));
            for row in rows {
                report.push_str(&format!("      {} [{}] {}\n", row.line, row.axis, row.text));
            }
        }
        panic!("{report}");
    }

    let mut per_owner: BTreeMap<&str, usize> = BTreeMap::new();
    for row in EXPECTED_RAW_POOL_MEMBER_ACCESS {
        *per_owner.entry(row.owner).or_default() += 1;
    }
    eprintln!(
        "R(raw-pool-member-access) = {} pinned offenders by owner: {:?}",
        EXPECTED_RAW_POOL_MEMBER_ACCESS.len(),
        per_owner
    );
    for row in EXPECTED_RAW_POOL_MEMBER_ACCESS {
        eprintln!(
            "  {}:{} [{}] owner={} replacement={} needle={}",
            row.path, row.line, row.axis, row.owner, row.replacement, row.needle
        );
    }
}

#[test]
fn pool_json_storage_is_zero() {
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workspace root")
        .to_path_buf();
    let types_path = workspace.join("sugar-verifier/src/types.rs");
    let src = std::fs::read_to_string(&types_path).expect("read verifier types");
    let mut offenders = Vec::new();
    let mut saw_typed_storage = false;
    for (i, line) in src.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.contains("pub mementos:") && trimmed.contains("StoredMember") {
            saw_typed_storage = true;
        }
        if trimmed.contains("pub mementos:")
            && (trimmed.contains("Json") || trimmed.contains("serde_json::Value"))
        {
            offenders.push((i + 1, trimmed.to_string()));
        }
    }
    assert!(
        saw_typed_storage,
        "MementoPool::mementos must store typed StoredMember values"
    );
    assert!(
        offenders.is_empty(),
        "R(pool-json-storage) = {}; expected 0. Offenders: {offenders:?}",
        offenders.len()
    );
    eprintln!("R(pool-json-storage) = 0");
}

#[test]
fn production_unanchored_insert_is_zero() {
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workspace root")
        .to_path_buf();
    let mut offenders = Vec::new();
    for path in rust_sources(&workspace) {
        if path.file_name().and_then(|n| n.to_str()) == Some("proof_api_audit.rs") {
            continue;
        }
        let rel = path
            .strip_prefix(&workspace)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        if !is_production_source(&rel) {
            continue;
        }
        let Ok(src) = std::fs::read_to_string(&path) else {
            continue;
        };
        let mut pending_cfg_test = false;
        let mut cfg_test_depth = None;
        for (i, line) in src.lines().enumerate() {
            let trimmed = line.trim();
            if skip_test_cfg_line(trimmed, &mut pending_cfg_test, &mut cfg_test_depth) {
                continue;
            }
            if trimmed.contains("insert_unanchored_for_tests(")
                || (trimmed.contains("pool.mementos.insert(")
                    && rel != "sugar-verifier/src/types.rs")
            {
                offenders.push((rel.clone(), i + 1, trimmed.to_string()));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "R(production-unanchored-insert) = {}; expected 0. Offenders: {offenders:?}",
        offenders.len()
    );
    eprintln!("R(production-unanchored-insert) = 0");
}

#[test]
fn every_consumer_uses_the_proof_graph_api() {
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workspace root")
        .to_path_buf();

    let mut per_axis: BTreeMap<&'static str, usize> = BTreeMap::new();
    let mut per_file: BTreeMap<String, BTreeMap<&'static str, usize>> = BTreeMap::new();
    let mut first_hit: BTreeMap<String, (usize, String)> = BTreeMap::new();
    let mut total = 0usize;

    for path in rust_sources(&workspace) {
        if path.file_name().and_then(|n| n.to_str()) == Some("proof_api_audit.rs") {
            continue;
        }
        let Ok(src) = std::fs::read_to_string(&path) else {
            continue;
        };
        let rel = path
            .strip_prefix(&workspace)
            .unwrap_or(&path)
            .to_string_lossy()
            .to_string();
        for (i, line) in src.lines().enumerate() {
            if let Some(axis) = offending_axis(line) {
                total += 1;
                *per_axis.entry(axis).or_default() += 1;
                *per_file
                    .entry(rel.clone())
                    .or_default()
                    .entry(axis)
                    .or_default() += 1;
                first_hit
                    .entry(rel.clone())
                    .or_insert_with(|| (i + 1, line.trim().to_string()));
            }
        }
    }

    if total > 0 {
        let mut report = String::new();
        report.push_str(&format!(
            "\nR = {total} api-bypass offenders across {} files. \
             Everything must read/write .proof catalogs through the ProofGraph api.\n\
             Per axis: {:?}\n\
             Replacement: member -> MemberView::{{kind,body_cid,json}} / contracts()\n\
             (decode axis is compiler-enforced; any new raw decode is a build error)\n\n",
            per_file.len(),
            per_axis
        ));
        for (file, axes) in &per_file {
            let (ln, text) = first_hit.get(file).cloned().unwrap_or((0, String::new()));
            report.push_str(&format!("  {file}  {axes:?}\n      first @ {ln}: {text}\n"));
        }
        panic!("{report}");
    }
}
