// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IDD instrument for #3384: every source-lift entrypoint must be declared and
// ruled in a typed manifest. Absences are manifest rows too; no inline
// allowlists inside scanners.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde::Deserialize;

const MANIFEST_REL: &str = "conformance/lifter_declarations.toml";

#[derive(Debug, Deserialize)]
struct LifterManifest {
    version: u32,
    #[serde(default)]
    ratchet: Ratchet,
    #[serde(default)]
    scan_roots: Vec<ScanRoot>,
    #[serde(default)]
    entrypoints: Vec<LifterDeclaration>,
}

#[derive(Debug, Default, Deserialize)]
struct Ratchet {
    #[serde(default)]
    undeclared_lifter_entrypoints: usize,
    #[serde(default)]
    declared_missing_production: usize,
    #[serde(default)]
    declared_absent_present: usize,
}

#[derive(Debug, Deserialize)]
struct ScanRoot {
    path: String,
}

#[derive(Debug, Deserialize)]
struct LifterDeclaration {
    id: String,
    status: String,
    owner: String,
    path: String,
    reason: String,
    #[serde(default)]
    retirement: String,
    #[serde(default)]
    needles: Vec<String>,
    #[serde(default)]
    absent_paths: Vec<String>,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct Finding {
    axis: &'static str,
    path: String,
    line: usize,
    id: String,
    message: String,
    replacement: String,
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

fn load_manifest(root: &Path) -> LifterManifest {
    let path = root.join(MANIFEST_REL);
    let text = std::fs::read_to_string(&path).unwrap_or_else(|error| {
        panic!(
            "lifter declaration manifest missing at {}: {error}\n\
             replacement_plan: add typed production/absent rows for every lift entrypoint",
            path.display()
        )
    });
    toml::from_str(&text).unwrap_or_else(|error| {
        panic!(
            "parse {} as lifter declaration manifest: {error}",
            path.display()
        )
    })
}

fn audit_manifest(root: &Path, manifest: &LifterManifest) -> Vec<Finding> {
    assert_eq!(manifest.version, 1, "unsupported lifter manifest version");

    let mut findings = Vec::new();
    let declared_paths = manifest
        .entrypoints
        .iter()
        .map(|entry| normalize_rel(&entry.path))
        .collect::<BTreeSet<_>>();

    for entry in &manifest.entrypoints {
        match entry.status.as_str() {
            "production" => audit_production_entry(root, entry, &mut findings),
            "absent" => audit_absent_entry(root, entry, &mut findings),
            other => findings.push(Finding {
                axis: "invalid-manifest-row",
                path: entry.path.clone(),
                line: 0,
                id: entry.id.clone(),
                message: format!("unknown lifter declaration status `{other}`"),
                replacement: "status must be `production` or `absent`".to_string(),
            }),
        }
    }

    for candidate in discover_lifter_candidates(root, manifest) {
        if declared_paths.contains(&candidate.path) {
            continue;
        }
        findings.push(Finding {
            axis: "undeclared-lifter-entrypoints",
            path: candidate.path,
            line: candidate.line,
            id: candidate.id,
            message: "source-lift-like entrypoint is not ruled in conformance/lifter_declarations.toml".to_string(),
            replacement: "add a typed production row, or a typed absent row with owner+retirement if the surface is deliberately dead".to_string(),
        });
    }

    findings.sort();
    findings
}

fn audit_production_entry(root: &Path, entry: &LifterDeclaration, findings: &mut Vec<Finding>) {
    let path = root.join(&entry.path);
    if !path.is_file() {
        findings.push(Finding {
            axis: "declared-missing-production",
            path: entry.path.clone(),
            line: 0,
            id: entry.id.clone(),
            message: "production lifter declaration points at a missing file".to_string(),
            replacement: "restore the declared entrypoint or change this row to a typed absent row with a retirement reason".to_string(),
        });
        return;
    }
    if entry.owner.trim().is_empty() || entry.reason.trim().is_empty() {
        findings.push(Finding {
            axis: "invalid-manifest-row",
            path: entry.path.clone(),
            line: 0,
            id: entry.id.clone(),
            message: "production lifter declaration must name owner and reason".to_string(),
            replacement: "fill owner/reason so the row is owned, not an inline allowlist"
                .to_string(),
        });
    }
    let source = std::fs::read_to_string(&path).unwrap_or_default();
    for needle in &entry.needles {
        if !source.contains(needle) {
            findings.push(Finding {
                axis: "declared-missing-production",
                path: entry.path.clone(),
                line: 0,
                id: entry.id.clone(),
                message: format!(
                    "production lifter declaration missing evidence needle `{needle}`"
                ),
                replacement: "update the declaration to the new entrypoint or add a new ruled row"
                    .to_string(),
            });
        }
    }
}

fn audit_absent_entry(root: &Path, entry: &LifterDeclaration, findings: &mut Vec<Finding>) {
    if entry.owner.trim().is_empty()
        || entry.reason.trim().is_empty()
        || entry.retirement.trim().is_empty()
    {
        findings.push(Finding {
            axis: "invalid-manifest-row",
            path: entry.path.clone(),
            line: 0,
            id: entry.id.clone(),
            message: "absent lifter declaration must name owner, reason, and retirement condition"
                .to_string(),
            replacement: "make the exemption typed and owned in the manifest".to_string(),
        });
    }
    let paths = if entry.absent_paths.is_empty() {
        vec![entry.path.as_str()]
    } else {
        entry.absent_paths.iter().map(String::as_str).collect()
    };
    for rel in paths {
        let path = root.join(rel);
        if path.exists() {
            findings.push(Finding {
                axis: "declared-absent-present",
                path: normalize_rel(rel),
                line: 0,
                id: entry.id.clone(),
                message: "manifest declares this lifter surface absent, but it exists".to_string(),
                replacement: "delete it, or change the manifest to a reviewed production row before adding code".to_string(),
            });
        }
    }
}

#[derive(Debug, Clone)]
struct Candidate {
    path: String,
    line: usize,
    id: String,
}

fn discover_lifter_candidates(root: &Path, manifest: &LifterManifest) -> Vec<Candidate> {
    let mut out = Vec::new();
    for scan_root in &manifest.scan_roots {
        let path = root.join(&scan_root.path);
        if !path.exists() {
            continue;
        }
        if path.is_file() {
            collect_candidate_file(root, &path, &mut out);
        } else {
            collect_candidate_files(root, &path, &mut out);
        }
    }
    out.sort_by(|left, right| left.path.cmp(&right.path).then(left.line.cmp(&right.line)));
    out
}

fn collect_candidate_files(root: &Path, dir: &Path, out: &mut Vec<Candidate>) {
    let entries = std::fs::read_dir(dir)
        .unwrap_or_else(|error| panic!("read lifter scan root {}: {error}", dir.display()));
    for entry in entries {
        let entry = entry.unwrap_or_else(|error| panic!("read lifter scan entry: {error}"));
        let path = entry.path();
        if path.is_dir() {
            if path
                .components()
                .any(|component| component.as_os_str() == "target")
            {
                continue;
            }
            collect_candidate_files(root, &path, out);
        } else {
            collect_candidate_file(root, &path, out);
        }
    }
}

fn collect_candidate_file(root: &Path, path: &Path, out: &mut Vec<Candidate>) {
    let Some(ext) = path.extension().and_then(|ext| ext.to_str()) else {
        return;
    };
    if !matches!(ext, "rs" | "py" | "java" | "sh") {
        return;
    }
    let rel = path
        .strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/");
    let source = std::fs::read_to_string(path).unwrap_or_default();
    if !looks_like_lifter_entrypoint(&rel, &source) {
        return;
    }
    out.push(Candidate {
        line: first_evidence_line(&source),
        id: path
            .file_stem()
            .and_then(|stem| stem.to_str())
            .unwrap_or("<unknown>")
            .to_string(),
        path: normalize_rel(&rel),
    });
}

fn looks_like_lifter_entrypoint(rel: &str, source: &str) -> bool {
    let lower = rel.to_ascii_lowercase();
    let file = lower.rsplit('/').next().unwrap_or(&lower);

    if lower.contains("sugar-lifter") || lower.contains("build-cpp-") {
        return true;
    }
    if file.ends_with("rpc.py") || file.ends_with("rpc.java") {
        return true;
    }
    if matches!(
        file,
        "lifter.py"
            | "source_oracle.py"
            | "walk_rpc.rs"
            | "lift.rs"
            | "ra_oracle.rs"
            | "sugar-lift.rs"
            | "cargo-sugar-lift.rs"
            | "contracts_rpc.rs"
            | "javasourceoracle.java"
    ) {
        return true;
    }
    if (lower.ends_with("sugar-lift/src/lib.rs")
        || lower.ends_with("sugar-lift-contracts/src/lib.rs"))
        && source.contains("lift")
    {
        return true;
    }
    file.contains("lifter") || file.contains("_lift") || file.contains("lift_")
}

fn first_evidence_line(source: &str) -> usize {
    for (idx, line) in source.lines().enumerate() {
        let lower = line.to_ascii_lowercase();
        if lower.contains("lift") || lower.contains("rpc") || lower.contains("oracle") {
            return idx + 1;
        }
    }
    1
}

fn normalize_rel(path: &str) -> String {
    path.replace('\\', "/")
}

fn vector(findings: &[Finding]) -> BTreeMap<&'static str, usize> {
    let mut vector = BTreeMap::from([
        ("declared-absent-present", 0),
        ("declared-missing-production", 0),
        ("invalid-manifest-row", 0),
        ("undeclared-lifter-entrypoints", 0),
    ]);
    for finding in findings {
        *vector.entry(finding.axis).or_insert(0) += 1;
    }
    vector
}

fn render_findings(findings: &[Finding]) -> String {
    serde_json::to_string_pretty(&serde_json::json!({
        "R(lifter-declaration-findings)": findings.len(),
        "vector": vector(findings),
        "findings": findings.iter().map(|finding| {
            serde_json::json!({
                "axis": finding.axis,
                "path": finding.path,
                "line": finding.line,
                "id": finding.id,
                "message": finding.message,
                "replacement": finding.replacement,
            })
        }).collect::<Vec<_>>(),
    }))
    .expect("serialize lifter declaration findings")
}

#[test]
fn lifter_declaration_manifest_matches_live_entrypoints() {
    let root = repo_root();
    let manifest = load_manifest(&root);
    let findings = audit_manifest(&root, &manifest);
    assert_eq!(
        vector(&findings)
            .get("undeclared-lifter-entrypoints")
            .copied()
            .unwrap_or(0),
        manifest.ratchet.undeclared_lifter_entrypoints,
        "{}",
        render_findings(&findings)
    );
    assert_eq!(
        vector(&findings)
            .get("declared-missing-production")
            .copied()
            .unwrap_or(0),
        manifest.ratchet.declared_missing_production,
        "{}",
        render_findings(&findings)
    );
    assert_eq!(
        vector(&findings)
            .get("declared-absent-present")
            .copied()
            .unwrap_or(0),
        manifest.ratchet.declared_absent_present,
        "{}",
        render_findings(&findings)
    );
    assert!(
        findings.is_empty(),
        "lifter declaration frontier is not stable-zero\n{}",
        render_findings(&findings)
    );
    eprintln!("{}", render_findings(&findings));
}

#[test]
fn planted_undeclared_lifter_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rel = "implementations/rust/sugar-walk/src/experimental_lifter.rs";
    let source = temp.path().join(rel);
    std::fs::create_dir_all(source.parent().expect("source parent")).expect("create dirs");
    std::fs::write(
        &source,
        r#"
pub fn lift_experiment() {
    // A new source representation door without a manifest row.
}
"#,
    )
    .expect("write planted lifter");

    let manifest = toml::from_str::<LifterManifest>(
        r#"
version = 1

[ratchet]
undeclared_lifter_entrypoints = 0
declared_missing_production = 0
declared_absent_present = 0

[[scan_roots]]
path = "implementations/rust/sugar-walk/src"
"#,
    )
    .expect("fixture manifest parses");
    let findings = audit_manifest(temp.path(), &manifest);
    println!("planted-control receipt:\n{}", render_findings(&findings));
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "undeclared-lifter-entrypoints"
                && finding.path == rel
                && finding.replacement.contains("typed production row")
        }),
        "planted lifter must be red; findings:\n{}",
        render_findings(&findings)
    );
}

#[test]
fn declared_absent_lifter_surface_turns_red_when_file_exists() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rel = "tools/build-cpp-lift.sh";
    let source = temp.path().join(rel);
    std::fs::create_dir_all(source.parent().expect("source parent")).expect("create dirs");
    std::fs::write(&source, "#!/usr/bin/env bash\n").expect("write absent fixture");
    let manifest = toml::from_str::<LifterManifest>(
        r#"
version = 1

[ratchet]
undeclared_lifter_entrypoints = 0
declared_missing_production = 0
declared_absent_present = 0

[[entrypoints]]
id = "cpp-lifter-seat"
status = "absent"
owner = "fixture"
path = "implementations/cpp"
reason = "fixture absence"
retirement = "fixture retirement"
absent_paths = ["tools/build-cpp-lift.sh"]
"#,
    )
    .expect("fixture manifest parses");
    let findings = audit_manifest(temp.path(), &manifest);
    assert!(
        findings
            .iter()
            .any(|finding| { finding.axis == "declared-absent-present" && finding.path == rel }),
        "declared-absent surface must be red when present; findings:\n{}",
        render_findings(&findings)
    );
}
