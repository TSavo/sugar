// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Witness discharge command -- the verifier<->kit contract (mirror python
// `discharge_cli.py`).
//
// The Rust verifier stays language-blind for the CUSTOM-EVIDENCE axis: when
// `prove` meets a contract carrying a `custom` witness EvidenceTerm with
// tool="cargo-test", it SPAWNS this command (the same way it spawns z3), and the
// kit settles the obligation BY RECOMPUTE: re-run the suite, rebuild the bundle,
// confirm the pinned package cid reproduces AND every per-test witness passed.
//
// Usage: discharge_cli <witness.proof> <project_dir>
//   <witness.proof> is the serialized custom EvidenceTerm prove wrote to a temp
//   file: {"kind":"evidence","proofType":"custom","certificate":{...,"proofData":
//   "<json {kind:witness-package, packageCid, testFiles, codeFiles, ...}>"}}
//
// Output (stdout): one JSON line {"verdict": "...", "reason": "..."}.
// Exit code: 0 iff DISCHARGED, 1 otherwise (fail-closed).

use std::path::Path;

use sugar_lift_rust_cargo_test_witness as kit;

fn emit(verdict: &str, reason: &str) -> i32 {
    let line = serde_json::json!({"verdict": verdict, "reason": reason});
    println!("{line}");
    if verdict == "DISCHARGED" {
        0
    } else {
        1
    }
}

fn run() -> i32 {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    if argv.len() < 2 {
        return emit("REFUSED", "usage: <witness.proof> <project_dir>");
    }
    let proof_path = &argv[0];
    let project_dir = &argv[1];

    let evidence_json = match std::fs::read_to_string(proof_path) {
        Ok(s) => s,
        Err(e) => return emit("REFUSED", &format!("discharge error: read proof: {e}")),
    };
    let pd = match kit::parse_evidence_proof_data(&evidence_json) {
        Ok(v) => v,
        Err(e) => return emit("REFUSED", &format!("discharge error: {e}")),
    };
    if pd.get("kind").and_then(|v| v.as_str()) != Some("witness-package") {
        return emit(
            "REFUSED",
            "discharge error: proofData is not a witness-package",
        );
    }
    let package_cid = match pd.get("packageCid").and_then(|v| v.as_str()) {
        Some(c) => c.to_string(),
        None => return emit("REFUSED", "discharge error: proofData missing packageCid"),
    };
    let code_files = kit::memento_str_list(&pd, "codeFiles");

    let (verdict, reason) =
        kit::discharge_bundle(&package_cid, &code_files, Path::new(project_dir));
    emit(&verdict, &reason)
}

fn main() {
    std::process::exit(run());
}
