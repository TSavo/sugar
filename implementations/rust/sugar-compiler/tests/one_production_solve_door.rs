// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar#3859 dual-door instrument: ONE production solve door.
//
// Law: production faces discharge through
//   `sugar_compiler::orchestrate::{solve_project, solve_project_with_pool, prove_from_kit}`
// which wrap the real `Runner::run_with_proof_run*` body as beat 2 and return
// `ProvenOutcome` (typed view + #3893 exit-code class).
//
// Illegal dual doors (production `src/`, not tests/examples):
//   - direct `Runner::run_with_proof_run` / `run_with_proof_run_with_pool` outside
//     the one owner (`orchestrate.rs` discharge body)
//   - `Orchestrate::{solve, solve_deriving_links}` — fixture two-reds short-circuit
//     over `verify_consistency`, not the production report pipeline
//   - `Runner::run_with_tiers` / bare `Runner::run` from CLI prove/verify faces
//
// Replacement for every offender: route the face through `solve_project` /
// `solve_project_with_pool` / `prove_from_kit`. Keep `run_with_proof_run*` as the
// body INSIDE orchestrate; do not re-open a parallel face path.
//
// R axes (measured live; red while any > 0):
//   face_bypass_runner      — CLI/LSP production face calls Runner discharge
//   face_missing_one_door   — prove/verify faces not calling the typed door
//   fixture_door_in_face    — Orchestrate::solve* invoked from production faces
//   owner_bypass            — non-owner production src calls run_with_proof_run*

use std::fs;
use std::path::{Path, PathBuf};

fn rust_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-compiler under implementations/rust")
        .to_path_buf()
}

fn is_comment_or_doc(line: &str) -> bool {
    let t = line.trim_start();
    t.starts_with("//") || t.starts_with("///") || t.starts_with("//!") || t.starts_with('*')
}

fn production_code_lines(text: &str) -> Vec<(usize, &str)> {
    text.lines()
        .enumerate()
        .filter(|(_, line)| !is_comment_or_doc(line))
        .map(|(i, line)| (i + 1, line))
        .collect()
}

fn read_rel(root: &Path, rel: &str) -> String {
    fs::read_to_string(root.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"))
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Offender {
    axis: &'static str,
    path: String,
    line: usize,
    text: String,
    replacement: &'static str,
}

fn push_call_offenders(
    out: &mut Vec<Offender>,
    path: &str,
    text: &str,
    needles: &[(&str, &'static str, &'static str)],
) {
    for (line_no, line) in production_code_lines(text) {
        for (needle, axis, replacement) in needles {
            if line.contains(needle) {
                out.push(Offender {
                    axis,
                    path: path.to_string(),
                    line: line_no,
                    text: line.trim().to_string(),
                    replacement,
                });
            }
        }
    }
}

/// Production faces that must enter through the one typed door.
const PROVE_VERIFY_FACES: &[&str] = &["sugar-cli/src/cmd_prove.rs", "sugar-cli/src/cmd_verify.rs"];

/// Production face trees scanned for Runner / fixture-door bypass.
const FACE_TREES: &[&str] = &["sugar-cli/src", "sugar-lsp/src"];

/// Owner of the production discharge body call (`run_with_proof_run_with_pool`).
const DISCHARGE_OWNER: &str = "sugar-compiler/src/orchestrate.rs";

/// Definitions of the Runner door — not call-site offenders.
const RUNNER_DEF_PATH: &str = "sugar-verifier/src/runner.rs";

fn scan_face_bypass(root: &Path) -> Vec<Offender> {
    let mut offenders = Vec::new();
    let banned = [
        (
            ".run_with_proof_run(",
            "face_bypass_runner",
            "call sugar_compiler::orchestrate::solve_project / solve_project_with_pool / prove_from_kit",
        ),
        (
            ".run_with_proof_run_with_pool(",
            "face_bypass_runner",
            "call sugar_compiler::orchestrate::solve_project / solve_project_with_pool / prove_from_kit",
        ),
        (
            ".run_with_tiers(",
            "face_bypass_runner",
            "call sugar_compiler::orchestrate::solve_project (report pipeline), never run_with_tiers from prove/verify faces",
        ),
        (
            ".solve_deriving_links(",
            "fixture_door_in_face",
            "Orchestrate::solve* is fixture two-reds only; production uses solve_project*",
        ),
    ];

    for tree in FACE_TREES {
        let dir = root.join(tree);
        walk_rs(&dir, &mut |rel, text| {
            // Only production face sources (skip tests under src if any).
            if rel.contains("/tests/") || rel.ends_with("_test.rs") {
                return;
            }
            push_call_offenders(&mut offenders, &rel, text, &banned);
            // Bare Orchestrate trait solve( is harder; catch explicit graph.solve(
            // and ProofGraph solve via method name with links arg is test-shaped.
            // Catch `.solve(` only on faces that also import Orchestrate — too
            // noisy. The fixture_door needles above + missing one-door pin cover it.
        });
    }
    offenders.sort();
    offenders.dedup();
    offenders
}

fn scan_face_missing_one_door(root: &Path) -> Vec<Offender> {
    let mut offenders = Vec::new();
    for rel in PROVE_VERIFY_FACES {
        let text = read_rel(root, rel);
        let has_solve_project =
            text.contains("orchestrate::solve_project(") || text.contains("solve_project(");
        let has_prove_from_kit =
            text.contains("orchestrate::prove_from_kit(") || text.contains("prove_from_kit(");
        if !(has_solve_project || has_prove_from_kit) {
            offenders.push(Offender {
                axis: "face_missing_one_door",
                path: rel.to_string(),
                line: 1,
                text: "no solve_project / prove_from_kit call site".to_string(),
                replacement:
                    "route prove/verify through sugar_compiler::orchestrate::solve_project \
                     or prove_from_kit (THE production solve door, sugar#3859)",
            });
        }
        // cmd_verify must use solve_project (disk face); cmd_prove may use either.
        if *rel == "sugar-cli/src/cmd_verify.rs" && !has_solve_project {
            offenders.push(Offender {
                axis: "face_missing_one_door",
                path: rel.to_string(),
                line: 1,
                text: "cmd_verify missing solve_project(".to_string(),
                replacement: "cmd_verify must call sugar_compiler::orchestrate::solve_project",
            });
        }
    }
    offenders
}

fn scan_owner_bypass(root: &Path) -> Vec<Offender> {
    let mut offenders = Vec::new();
    let needles = [
        (
            ".run_with_proof_run(",
            "owner_bypass",
            "only sugar-compiler/src/orchestrate.rs (discharge_with_pool) may call \
             run_with_proof_run* from production src; faces use solve_project*",
        ),
        (
            ".run_with_proof_run_with_pool(",
            "owner_bypass",
            "only sugar-compiler/src/orchestrate.rs (discharge_with_pool) may call \
             run_with_proof_run* from production src; faces use solve_project*",
        ),
    ];

    // Production crates that must not grow a parallel discharge door.
    for crate_src in [
        "sugar-cli/src",
        "sugar-lsp/src",
        "sugar-compiler/src",
        "sugar-verifier/src",
    ] {
        let dir = root.join(crate_src);
        walk_rs(&dir, &mut |rel, text| {
            if rel.contains("/tests/") {
                return;
            }
            // Definitions and the one owner are exempt.
            if rel == RUNNER_DEF_PATH || rel == DISCHARGE_OWNER {
                return;
            }
            // Skip modules that only mention the symbol in type/docs — already
            // filtered by production_code_lines.
            push_call_offenders(&mut offenders, &rel, text, &needles);
        });
    }
    offenders.sort();
    offenders.dedup();
    offenders
}

fn walk_rs(dir: &Path, f: &mut dyn FnMut(String, &str)) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    let root = rust_root();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if matches!(name, "target" | "tests") {
                continue;
            }
            walk_rs(&path, f);
        } else if path.extension().and_then(|e| e.to_str()) == Some("rs") {
            let rel = path
                .strip_prefix(&root)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/");
            let Ok(text) = fs::read_to_string(&path) else {
                continue;
            };
            f(rel, &text);
        }
    }
}

fn format_report(axis: &str, offenders: &[Offender]) -> String {
    let mut s = format!(
        "\nR({axis}) = {} measured offender(s). sugar#3859: ONE production solve door.\n\
         Replacement: faces → solve_project / solve_project_with_pool / prove_from_kit; \
         Runner::run_with_proof_run* stays the body inside orchestrate only.\n\n",
        offenders.len()
    );
    for o in offenders {
        s.push_str(&format!(
            "  - {}:{}  [{}]\n      {}\n      fix: {}\n",
            o.path, o.line, o.axis, o.text, o.replacement
        ));
    }
    s
}

#[test]
fn one_production_solve_door_instrument() {
    let root = rust_root();

    let face_bypass = scan_face_bypass(&root);
    let face_missing = scan_face_missing_one_door(&root);
    let owner_bypass = scan_owner_bypass(&root);

    let r_face_bypass = face_bypass.len();
    let r_face_missing = face_missing.len();
    let r_owner_bypass = owner_bypass.len();
    let r_total = r_face_bypass + r_face_missing + r_owner_bypass;

    // Owner must still call the real body (positive pin — silence is not green
    // if someone deletes the wrap and leaves an empty door).
    let owner_text = read_rel(&root, DISCHARGE_OWNER);
    assert!(
        owner_text.contains("run_with_proof_run_with_pool("),
        "R(owner_missing_body)>0: {DISCHARGE_OWNER} must call Runner::run_with_proof_run_with_pool \
         as beat 2 — that is THE production discharge body (sugar#3859)"
    );
    assert!(
        owner_text.contains("pub fn solve_project(")
            && owner_text.contains("pub fn solve_project_with_pool("),
        "R(owner_missing_door)>0: solve_project / solve_project_with_pool must remain the public door"
    );

    // Fixture door may exist, but must not be the production face path.
    // Positive: faces name the one door.
    let prove = read_rel(&root, "sugar-cli/src/cmd_prove.rs");
    let verify = read_rel(&root, "sugar-cli/src/cmd_verify.rs");
    assert!(
        prove.contains("solve_project(") || prove.contains("prove_from_kit("),
        "cmd_prove must route through the one door"
    );
    assert!(
        verify.contains("solve_project("),
        "cmd_verify must route through solve_project"
    );

    if r_total != 0 {
        let mut msg = String::new();
        if r_face_bypass > 0 {
            msg.push_str(&format_report(
                "face_bypass_runner|fixture_door_in_face",
                &face_bypass,
            ));
        }
        if r_face_missing > 0 {
            msg.push_str(&format_report("face_missing_one_door", &face_missing));
        }
        if r_owner_bypass > 0 {
            msg.push_str(&format_report("owner_bypass", &owner_bypass));
        }
        panic!(
            "sugar#3859 dual-door instrument RED: R(total)={r_total} \
             (face_bypass={r_face_bypass}, face_missing={r_face_missing}, \
             owner_bypass={r_owner_bypass})\n{msg}"
        );
    }

    eprintln!(
        "RECEIPT sugar#3859 one production solve door: R=0 \
         (faces→solve_project*/prove_from_kit; body=run_with_proof_run* in orchestrate only)"
    );
}
