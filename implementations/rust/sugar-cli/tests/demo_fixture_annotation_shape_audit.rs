// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IDD instrument for #3779.
//
// DEFECT: slice-A demo fixtures demonstrated the editor flip with bespoke
// `#[requires(...)]` / `#[ensures(...)]` contract annotations. That shape
// proves the product's ANTITHESIS — "I can adjudicate a hand-annotated
// contract" — not the real sentence: lift NATIVE source and adjudicate a
// NATIVE assertion against a loaded VENDOR proof.
//
// Law (demo surface only):
//   - editors/** fixtures and the live flip demo must never reintroduce the
//     annotation DSL as the thing shown.
//   - the honest demo is examples/python-base64-federation: plain Python
//     assert + staged vendor .proof (driven by editors/vscode-sugar lsp-e2e).
//
// This audit measures R = count of live annotation-DSL offenders on the demo
// surface + resurrected dead fixture paths. Stable zero is silence. The
// sugar-lift-contracts kit (and its unit-test fixtures under
// implementations/rust/) is the sanctioned NATIVE annotation *lifter*
// surface and is intentionally out of scope — this instrument only pins the
// demo/editor product surface.
//
// Replacement architecture when red:
//   Delete the annotation fixture. Point the flip receipt at a native
//   assertion against a loaded vendor proof (python-base64-federation shape).

use std::fs;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

/// Paths that #3779 deleted and that must stay deleted.
const FORBIDDEN_DEAD_FIXTURES: &[&str] = &[
    "editors/vscode-sugar/test/fixtures/red.rs",
    "editors/vscode-sugar/test/fixtures/green.rs",
    "editors/vscode-sugar/test/fixtures/red_semantic.rs",
    "editors/vscode-sugar/test/fixtures/green_semantic.rs",
];

/// Demo/editor trees that must not carry the annotation DSL as product content.
const DEMO_SURFACE_ROOTS: &[&str] = &["editors", "examples/python-base64-federation"];

const NATIVE_DEMO_GOOD: &str = "examples/python-base64-federation/consumer-good/test_consumer.py";
const NATIVE_DEMO_BAD: &str = "examples/python-base64-federation/consumer-bad/test_consumer.py";
const NATIVE_DEMO_VENDOR: &str = "examples/python-base64-federation/vendor/b64vendor.py";
const LSP_E2E: &str = "editors/vscode-sugar/test/lsp-e2e.test.js";

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Offender {
    path: String,
    line: usize,
    kind: &'static str,
    text: String,
}

fn rel(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn is_scanned_source(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()),
        Some("rs" | "py" | "js" | "ts" | "tsx" | "jsx")
    )
}

fn collect_sources(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if matches!(
                name,
                "node_modules" | "out" | "target" | ".git" | "__pycache__" | ".sugar"
            ) {
                continue;
            }
            collect_sources(&p, out);
        } else if is_scanned_source(&p) {
            out.push(p);
        }
    }
}

/// Attribute shapes that made the slice-A demo dishonest.
fn annotation_dsl_kind(line: &str) -> Option<&'static str> {
    let t = line.trim();
    // Skip pure prose comments that mention the shape by name (docs in code).
    // Still catch live attributes and attribute-bearing string fixtures.
    if t.starts_with("//") && !t.contains("#[") {
        return None;
    }
    if t.starts_with('#') && t.contains("requires(") && t.contains('[') {
        return Some("#[requires(...)] annotation DSL");
    }
    if t.starts_with('#') && t.contains("ensures(") && t.contains('[') {
        return Some("#[ensures(...)] annotation DSL");
    }
    // Non-comment code / string literals embedding the forbidden attr form.
    if t.contains("#[requires(")
        || t.contains("#[contracts::requires(")
        || t.contains("#[prusti_contracts::requires(")
        || t.contains("#[prusti::requires(")
        || t.contains("#[creusot_contracts::requires(")
        || t.contains("#[creusot::requires(")
    {
        return Some("#[requires(...)] annotation DSL");
    }
    if t.contains("#[ensures(")
        || t.contains("#[contracts::ensures(")
        || t.contains("#[prusti_contracts::ensures(")
        || t.contains("#[prusti::ensures(")
        || t.contains("#[creusot_contracts::ensures(")
        || t.contains("#[creusot::ensures(")
    {
        return Some("#[ensures(...)] annotation DSL");
    }
    None
}

fn scan_file(root: &Path, path: &Path) -> Vec<Offender> {
    let Ok(text) = fs::read_to_string(path) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for (idx, line) in text.lines().enumerate() {
        if let Some(kind) = annotation_dsl_kind(line) {
            out.push(Offender {
                path: rel(root, path),
                line: idx + 1,
                kind,
                text: line.trim().to_string(),
            });
        }
    }
    out
}

fn scan_demo_surface(root: &Path) -> Vec<Offender> {
    let mut sources = Vec::new();
    for rel_root in DEMO_SURFACE_ROOTS {
        let dir = root.join(rel_root);
        if dir.is_dir() {
            collect_sources(&dir, &mut sources);
        }
    }
    sources.sort();
    let mut offenders = Vec::new();
    for path in sources {
        offenders.extend(scan_file(root, &path));
    }
    offenders.sort();
    offenders
}

fn resurrected_dead_fixtures(root: &Path) -> Vec<Offender> {
    let mut out = Vec::new();
    for rel_path in FORBIDDEN_DEAD_FIXTURES {
        let path = root.join(rel_path);
        if path.exists() {
            out.push(Offender {
                path: (*rel_path).to_string(),
                line: 0,
                kind: "resurrected forbidden demo fixture path",
                text: "DELETE this path; demo must be native assertion + vendor proof".to_string(),
            });
        }
    }
    out
}

fn native_demo_shape_offenders(root: &Path) -> Vec<Offender> {
    let mut out = Vec::new();
    for (rel_path, must_contain) in [
        (NATIVE_DEMO_GOOD, "assert encodeBase64"),
        (NATIVE_DEMO_BAD, "assert encodeBase64"),
        (NATIVE_DEMO_VENDOR, "assert encodeBase64"),
        (LSP_E2E, "python-base64-federation"),
    ] {
        let path = root.join(rel_path);
        if !path.is_file() {
            out.push(Offender {
                path: rel_path.to_string(),
                line: 0,
                kind: "missing honest native demo artifact",
                text: format!(
                    "expected live native demo at {rel_path}; replacement is \
                     plain assert against a loaded vendor .proof"
                ),
            });
            continue;
        }
        let text = fs::read_to_string(&path).unwrap_or_default();
        if !text.contains(must_contain) {
            out.push(Offender {
                path: rel_path.to_string(),
                line: 0,
                kind: "native demo lost its honest shape",
                text: format!(
                    "file no longer contains `{must_contain}`; restore the \
                     native-assertion-against-vendor-proof demo"
                ),
            });
        }
        // Extra: good/bad consumers must not import annotation surface.
        if (rel_path == NATIVE_DEMO_GOOD || rel_path == NATIVE_DEMO_BAD)
            && (text.contains("requires(") || text.contains("ensures("))
        {
            out.push(Offender {
                path: rel_path.to_string(),
                line: 0,
                kind: "native consumer grew contract-language prose",
                text: "consumer must stay a plain assert; no requires/ensures DSL".to_string(),
            });
        }
    }
    out
}

#[test]
fn demo_surface_has_zero_annotation_dsl_fixtures() {
    let root = repo_root();
    let mut offenders = Vec::new();
    offenders.extend(resurrected_dead_fixtures(&root));
    offenders.extend(scan_demo_surface(&root));
    offenders.extend(native_demo_shape_offenders(&root));
    offenders.sort();
    offenders.dedup();

    let r = offenders.len();
    if r == 0 {
        eprintln!(
            "demo_fixture_annotation_shape_audit: R=0 (stable zero). \
             Demo surface carries no #[requires]/#[ensures] fixtures; \
             native python-base64-federation flip is the product demo."
        );
        return;
    }

    let mut report = String::from(
        "\n#3779 demo fixture annotation-shape audit RED\n\
         Law: the product demo lifts NATIVE source and adjudicates a NATIVE \
         assertion against a loaded VENDOR proof. Hand-authored \
         #[requires]/#[ensures] fixtures prove the antithesis and are forbidden \
         on the editor/demo surface.\n\
         Replacement: delete the annotation fixture; point the flip receipt at \
         examples/python-base64-federation (plain assert + staged .proof).\n\n",
    );
    for o in &offenders {
        report.push_str(&format!(
            "  offender: {}:{}\n    kind: {}\n    text: {}\n    fix: delete annotation DSL \
             from demo surface; use native assert + vendor .proof\n",
            o.path, o.line, o.kind, o.text
        ));
    }
    report.push_str(&format!("\nR={r} (must be 0)\n"));
    panic!("{}", report);
}
