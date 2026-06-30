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
