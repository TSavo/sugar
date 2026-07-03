// SPDX-License-Identifier: Apache-2.0
//
// IDD instrument: typed-pipeline interfaces must declare the seven points from
// docs/superpowers/specs/2026-07-02-typed-pipeline-interface-map.md §4.
//
// Rung: test/auditor. The proc-macro endgame can retire this once Rust can make
// the declaration part of interface construction.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde::Deserialize;

const MANIFEST_REL: &str = "conformance/typed_pipeline/interfaces.toml";
const BASELINE_DECLARED_ESCAPE_HATCH_ROWS_OPEN: usize = 6;

#[derive(Debug, Deserialize)]
struct InterfaceManifest {
    version: u32,
    #[serde(default)]
    ratchet: Ratchet,
    #[serde(default)]
    interface_sources: Vec<InterfaceSource>,
    #[serde(default)]
    interfaces: Vec<InterfaceDeclaration>,
}

#[derive(Debug, Default, Deserialize)]
struct Ratchet {
    interfaces_without_declaration: usize,
    undeclared_escape_hatches: usize,
    declared_escape_hatch_rows_open: usize,
}

#[derive(Debug, Deserialize)]
struct InterfaceSource {
    path: String,
    #[serde(default)]
    ignored_items: Vec<IgnoredItem>,
}

#[derive(Debug, Deserialize)]
struct IgnoredItem {
    name: String,
    reason: String,
}

#[derive(Debug, Deserialize)]
struct InterfaceDeclaration {
    id: String,
    owner: String,
    input_type: String,
    output_type: String,
    addressing_rule: String,
    failure_type: String,
    #[serde(default)]
    replay_inputs: Vec<String>,
    source: InterfaceItemSource,
    #[serde(default)]
    escape_hatches: Vec<EscapeHatch>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
struct InterfaceItemSource {
    path: String,
    item: String,
    kind: String,
}

#[derive(Debug, Deserialize)]
struct EscapeHatch {
    shape: String,
    owner: String,
    retirement: String,
    #[serde(default)]
    baseline: bool,
    source: EscapeHatchSource,
}

#[derive(Debug, Deserialize)]
struct EscapeHatchSource {
    path: String,
    item: String,
    #[serde(default)]
    needles: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct RustItem {
    path: String,
    name: String,
    kind: String,
    line: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct HatchFinding {
    path: String,
    item: String,
    line: usize,
    shape: String,
    text: String,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Finding {
    axis: &'static str,
    path: String,
    line: usize,
    item: String,
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

fn load_manifest(root: &Path) -> InterfaceManifest {
    let path = root.join(MANIFEST_REL);
    let text = std::fs::read_to_string(&path).unwrap_or_else(|error| {
        panic!(
            "typed-pipeline interface registry missing at {}: {error}\n\
             R.interfaces_without_declaration = unknown\n\
             replacement_plan: add the §4 seven-point registry seeded with the six S1 census rows",
            path.display()
        )
    });
    toml::from_str(&text).unwrap_or_else(|error| {
        panic!(
            "parse {} as typed-pipeline interface manifest: {error}",
            path.display()
        )
    })
}

#[test]
fn typed_pipeline_interface_registry_matches_live_sources() {
    let root = repo_root();
    let manifest = load_manifest(&root);
    assert_manifest_clean(&root, &manifest);
}

#[test]
fn planted_undeclared_value_escape_hatch_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("planted.rs");
    std::fs::write(
        &source,
        r#"
pub struct PlantedPipelineInterface {
    payload: serde_json::Value,
}
"#,
    )
    .expect("write planted interface");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0

[[interface_sources]]
path = "{}"

[[interfaces]]
id = "planted"
owner = "test::planted"
input_type = "PlantedInput"
output_type = "PlantedPipelineInterface"
addressing_rule = "fixture cid"
failure_type = "fixture diagnostic"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "PlantedPipelineInterface", kind = "struct" }}
"#,
        source.display(),
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "undeclared-escape-hatches"
                && finding.item == "PlantedPipelineInterface"
                && finding.message.contains("serde-json-value")
        }),
        "planted serde_json::Value hatch must be red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn declared_escape_hatch_requires_owner_and_retirement() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("declared.rs");
    std::fs::write(
        &source,
        r#"
pub struct DeclaredPipelineInterface {
    payload: serde_json::Value,
}
"#,
    )
    .expect("write declared interface");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 1

[[interface_sources]]
path = "{}"

[[interfaces]]
id = "declared"
owner = "test::declared"
input_type = "DeclaredInput"
output_type = "DeclaredPipelineInterface"
addressing_rule = "fixture cid"
failure_type = "fixture diagnostic"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "DeclaredPipelineInterface", kind = "struct" }}

[[interfaces.escape_hatches]]
shape = "serde-json-value"
owner = "fixture owner"
retirement = "replace payload with a typed fixture member"
baseline = true
source = {{ path = "{}", item = "DeclaredPipelineInterface", needles = ["payload: serde_json::Value"] }}
"#,
        source.display(),
        source.display(),
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings.is_empty(),
        "declared hatch with owner+retirement should pass; findings:\n{}",
        render_findings(&findings, 1)
    );
}

#[test]
fn dropped_declaration_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("dropped.rs");
    std::fs::write(
        &source,
        r#"
pub struct DroppedPipelineInterface {
    typed: String,
}
"#,
    )
    .expect("write dropped interface");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0

[[interface_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "interfaces-without-declaration"
                && finding.item == "DroppedPipelineInterface"
        }),
        "candidate interface with dropped declaration must be red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

fn manifest_from_str(text: &str) -> InterfaceManifest {
    toml::from_str(text).expect("fixture manifest parses")
}

fn assert_manifest_clean(root: &Path, manifest: &InterfaceManifest) {
    let findings = audit_manifest(root, manifest);
    assert!(
        findings.is_empty(),
        "typed-pipeline conformance failed:\n{}",
        render_findings(&findings, manifest_declared_baseline_count(manifest))
    );
}

fn audit_manifest(root: &Path, manifest: &InterfaceManifest) -> Vec<Finding> {
    audit_manifest_with_mode(root, manifest, true)
}

fn audit_fixture_manifest(root: &Path, manifest: &InterfaceManifest) -> Vec<Finding> {
    audit_manifest_with_mode(root, manifest, false)
}

fn audit_manifest_with_mode(
    root: &Path,
    manifest: &InterfaceManifest,
    enforce_live_ratchet: bool,
) -> Vec<Finding> {
    let mut findings = Vec::new();
    let mut interface_keys = BTreeSet::new();
    let mut declared_items = BTreeMap::new();

    if manifest.version != 1 {
        findings.push(Finding {
            axis: "manifest-schema",
            path: MANIFEST_REL.to_string(),
            line: 1,
            item: "version".to_string(),
            message: format!("expected manifest version 1, got {}", manifest.version),
            replacement: "keep the S1 declaration schema at version = 1".to_string(),
        });
    }

    for interface in &manifest.interfaces {
        validate_interface_declaration(interface, &mut findings);
        if !interface_keys.insert(interface.id.clone()) {
            findings.push(Finding {
                axis: "manifest-schema",
                path: interface.source.path.clone(),
                line: 0,
                item: interface.id.clone(),
                message: format!("duplicate interface id `{}`", interface.id),
                replacement: "give each typed-pipeline interface one stable manifest id"
                    .to_string(),
            });
        }
        let key = (
            normalize_manifest_path(root, &interface.source.path),
            interface.source.item.clone(),
        );
        if let Some(prior) = declared_items.insert(key, interface.id.clone()) {
            findings.push(Finding {
                axis: "manifest-schema",
                path: interface.source.path.clone(),
                line: 0,
                item: interface.source.item.clone(),
                message: format!(
                    "source item declared by both `{prior}` and `{}`",
                    interface.id
                ),
                replacement: "keep one seven-point declaration per source interface item"
                    .to_string(),
            });
        }
    }

    let mut candidate_items = Vec::new();
    for source in &manifest.interface_sources {
        let path = resolve_manifest_path(root, &source.path);
        let ignored = ignored_items(source, &mut findings);
        let items = rust_items_in_file(&path, root, &ignored);
        candidate_items.extend(items);
    }
    candidate_items.sort();

    for item in &candidate_items {
        let key = (item.path.clone(), item.name.clone());
        if !declared_items.contains_key(&key) {
            findings.push(Finding {
                axis: "interfaces-without-declaration",
                path: item.path.clone(),
                line: item.line,
                item: item.name.clone(),
                message: format!(
                    "pipeline candidate `{}` has no §4 seven-point interface declaration",
                    item.name
                ),
                replacement: "add an [[interfaces]] entry with owner/input/output/addressing/failure/replay/escape_hatches"
                    .to_string(),
            });
        }
    }

    for interface in &manifest.interfaces {
        let path = resolve_manifest_path(root, &interface.source.path);
        let interface_path = normalize_manifest_path(root, &interface.source.path);
        let Some(block) = item_block(&path, &interface.source.item) else {
            findings.push(Finding {
                axis: "interfaces-without-declaration",
                path: interface.source.path.clone(),
                line: 0,
                item: interface.source.item.clone(),
                message: format!(
                    "declared interface item `{}` is absent from source",
                    interface.source.item
                ),
                replacement:
                    "restore the source item or drop/update its manifest declaration deliberately"
                        .to_string(),
            });
            continue;
        };
        let discovered = discover_escape_hatches(&interface_path, &interface.source.item, &block);
        for hatch in discovered {
            if !hatch_is_declared(root, interface, &hatch) {
                findings.push(Finding {
                    axis: "undeclared-escape-hatches",
                    path: hatch.path,
                    line: hatch.line,
                    item: hatch.item,
                    message: format!(
                        "undeclared {} escape hatch in boundary signature: `{}`",
                        hatch.shape, hatch.text
                    ),
                    replacement: "declare this hatch with owner+retirement, or replace it with a typed boundary"
                        .to_string(),
                });
            }
        }
        for hatch in &interface.escape_hatches {
            for needle in &hatch.source.needles {
                if !block.lines.iter().any(|line| line.text.contains(needle)) {
                    findings.push(Finding {
                        axis: "declared-escape-hatch-missing",
                        path: hatch.source.path.clone(),
                        line: block.start_line,
                        item: hatch.source.item.clone(),
                        message: format!(
                            "declared {} hatch needle `{needle}` is no longer present",
                            hatch.shape
                        ),
                        replacement: "remove the declaration only with the typed retirement that made it unrepresentable"
                            .to_string(),
                    });
                }
            }
        }
    }

    let baseline = manifest_declared_baseline_count(manifest);
    if enforce_live_ratchet && manifest.ratchet.interfaces_without_declaration != 0 {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.interfaces_without_declaration".to_string(),
            message: format!(
                "ratchet pins interfaces_without_declaration at {}, expected 0",
                manifest.ratchet.interfaces_without_declaration
            ),
            replacement: "S1 arms undeclared interfaces as a zero-residue regression axis"
                .to_string(),
        });
    }
    if enforce_live_ratchet && manifest.ratchet.undeclared_escape_hatches != 0 {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.undeclared_escape_hatches".to_string(),
            message: format!(
                "ratchet pins undeclared_escape_hatches at {}, expected 0",
                manifest.ratchet.undeclared_escape_hatches
            ),
            replacement:
                "S1 permits declared legacy rows only; undeclared hatch residue stays zero"
                    .to_string(),
        });
    }
    if enforce_live_ratchet
        && manifest.ratchet.declared_escape_hatch_rows_open
            != BASELINE_DECLARED_ESCAPE_HATCH_ROWS_OPEN
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.declared_escape_hatch_rows_open".to_string(),
            message: format!(
                "ratchet pins declared_escape_hatch_rows_open at {}, expected {BASELINE_DECLARED_ESCAPE_HATCH_ROWS_OPEN}",
                manifest.ratchet.declared_escape_hatch_rows_open
            ),
            replacement: "S1 baseline is exactly the six campaign census rows; drains own retirement"
                .to_string(),
        });
    }
    if enforce_live_ratchet && baseline != manifest.ratchet.declared_escape_hatch_rows_open {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.declared_escape_hatch_rows_open".to_string(),
            message: format!(
                "manifest has {baseline} baseline escape-hatch rows, ratchet pins {}",
                manifest.ratchet.declared_escape_hatch_rows_open
            ),
            replacement:
                "keep the manifest baseline count synchronized with the six declared S1 rows"
                    .to_string(),
        });
    }

    findings.sort();
    findings
}

fn resolve_manifest_path(root: &Path, path: &str) -> PathBuf {
    let path = Path::new(path);
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    }
}

fn normalize_manifest_path(root: &Path, path: &str) -> String {
    let path = resolve_manifest_path(root, path);
    path.strip_prefix(root)
        .unwrap_or(&path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn validate_interface_declaration(interface: &InterfaceDeclaration, findings: &mut Vec<Finding>) {
    for (field, value) in [
        ("id", &interface.id),
        ("owner", &interface.owner),
        ("input_type", &interface.input_type),
        ("output_type", &interface.output_type),
        ("addressing_rule", &interface.addressing_rule),
        ("failure_type", &interface.failure_type),
        ("source.path", &interface.source.path),
        ("source.item", &interface.source.item),
        ("source.kind", &interface.source.kind),
    ] {
        if value.trim().is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: interface.source.path.clone(),
                line: 0,
                item: interface.id.clone(),
                message: format!("interface `{}` has empty `{field}`", interface.id),
                replacement: format!("fill `{field}` as one of the §4 seven-point declarations"),
            });
        }
    }
    if interface.replay_inputs.is_empty()
        || interface
            .replay_inputs
            .iter()
            .any(|input| input.trim().is_empty())
    {
        findings.push(Finding {
            axis: "manifest-schema",
            path: interface.source.path.clone(),
            line: 0,
            item: interface.id.clone(),
            message: format!(
                "interface `{}` has no replay input declaration",
                interface.id
            ),
            replacement:
                "declare the replay pins a second verifier needs to reconstruct this boundary"
                    .to_string(),
        });
    }
    for hatch in &interface.escape_hatches {
        for (field, value) in [
            ("shape", &hatch.shape),
            ("owner", &hatch.owner),
            ("retirement", &hatch.retirement),
            ("source.path", &hatch.source.path),
            ("source.item", &hatch.source.item),
        ] {
            if value.trim().is_empty() {
                findings.push(Finding {
                    axis: "manifest-schema",
                    path: interface.source.path.clone(),
                    line: 0,
                    item: interface.id.clone(),
                    message: format!(
                        "escape hatch on interface `{}` has empty `{field}`",
                        interface.id
                    ),
                    replacement:
                        "every legacy hatch must name shape, owner, retirement, and source"
                            .to_string(),
                });
            }
        }
        if hatch.source.needles.is_empty()
            || hatch
                .source
                .needles
                .iter()
                .any(|needle| needle.trim().is_empty())
        {
            findings.push(Finding {
                axis: "manifest-schema",
                path: interface.source.path.clone(),
                line: 0,
                item: interface.id.clone(),
                message: format!(
                    "escape hatch on interface `{}` has no source needle",
                    interface.id
                ),
                replacement: "pin each declared hatch to the concrete source text it retires"
                    .to_string(),
            });
        }
    }
}

fn ignored_items(source: &InterfaceSource, findings: &mut Vec<Finding>) -> BTreeSet<String> {
    let mut ignored = BTreeSet::new();
    for item in &source.ignored_items {
        if item.name.trim().is_empty() || item.reason.trim().is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: source.path.clone(),
                line: 0,
                item: item.name.clone(),
                message: "ignored item must name both item and reason".to_string(),
                replacement: "make non-interface dismissals explicit and reviewable".to_string(),
            });
        }
        ignored.insert(item.name.clone());
    }
    ignored
}

fn rust_items_in_file(path: &Path, root: &Path, ignored: &BTreeSet<String>) -> Vec<RustItem> {
    let text = std::fs::read_to_string(path)
        .unwrap_or_else(|error| panic!("read interface source {}: {error}", path.display()));
    let rel = path
        .strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/");
    let mut items = Vec::new();
    for (i, line) in text.lines().enumerate() {
        if let Some((kind, name)) = parse_rust_item(line) {
            if ignored.contains(&name) {
                continue;
            }
            items.push(RustItem {
                path: rel.clone(),
                name,
                kind,
                line: i + 1,
            });
        }
    }
    items
}

fn parse_rust_item(line: &str) -> Option<(String, String)> {
    let trimmed = line.trim();
    if trimmed.starts_with("//") || trimmed.starts_with("#[") || trimmed.is_empty() {
        return None;
    }
    let trimmed = trimmed
        .strip_prefix("pub(crate) ")
        .or_else(|| trimmed.strip_prefix("pub(super) "))
        .or_else(|| trimmed.strip_prefix("pub "))
        .unwrap_or(trimmed);
    for kind in ["struct", "enum", "trait", "const"] {
        let Some(rest) = trimmed.strip_prefix(kind) else {
            continue;
        };
        let rest = rest.trim_start();
        let name = rest
            .split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
            .next()
            .unwrap_or("");
        if !name.is_empty() {
            return Some((kind.to_string(), name.to_string()));
        }
    }
    None
}

#[derive(Debug)]
struct ItemBlock {
    start_line: usize,
    lines: Vec<Line>,
}

#[derive(Debug)]
struct Line {
    number: usize,
    text: String,
}

fn item_block(path: &Path, item_name: &str) -> Option<ItemBlock> {
    let text = std::fs::read_to_string(path).ok()?;
    let lines: Vec<&str> = text.lines().collect();
    let start = lines.iter().position(|line| {
        parse_rust_item(line)
            .map(|(_, name)| name == item_name)
            .unwrap_or(false)
    })?;
    let mut out = Vec::new();
    let mut saw_brace = false;
    let mut depth = 0isize;
    for (idx, line) in lines.iter().enumerate().skip(start) {
        out.push(Line {
            number: idx + 1,
            text: (*line).to_string(),
        });
        if line.contains('{') {
            saw_brace = true;
        }
        depth += brace_delta(line);
        if saw_brace && depth <= 0 {
            break;
        }
        if !saw_brace && line.trim_end().ends_with(';') {
            break;
        }
    }
    Some(ItemBlock {
        start_line: start + 1,
        lines: out,
    })
}

fn brace_delta(line: &str) -> isize {
    let mut depth = 0;
    for ch in line.chars() {
        match ch {
            '{' => depth += 1,
            '}' => depth -= 1,
            _ => {}
        }
    }
    depth
}

fn discover_escape_hatches(path: &str, item: &str, block: &ItemBlock) -> Vec<HatchFinding> {
    let mut findings = Vec::new();
    for line in &block.lines {
        let trimmed = line.text.trim();
        if trimmed.starts_with("//") || trimmed.starts_with('#') {
            continue;
        }
        let shape = if is_json_value_boundary(trimmed) {
            Some("serde-json-value")
        } else if trimmed.contains("Failed(String)") {
            Some("free-text-machine-error")
        } else if item == "SolveResult"
            && (trimmed.contains("error: String") || trimmed.contains("solver_stdout: String"))
        {
            Some("free-text-solver-telemetry")
        } else if item == "RunnerConfig" && trimmed.contains("z3_path: String") {
            Some("silent-fallback")
        } else if item == "VERIFIER_STAGE_VOCABULARY" && trimmed.contains("\"smt_emit\"") {
            Some("stage-vocabulary-drift")
        } else {
            None
        };
        if let Some(shape) = shape {
            findings.push(HatchFinding {
                path: path.to_string(),
                item: item.to_string(),
                line: line.number,
                shape: shape.to_string(),
                text: trimmed.to_string(),
            });
        }
    }
    findings
}

fn is_json_value_boundary(trimmed: &str) -> bool {
    if trimmed.starts_with("use ") {
        return false;
    }
    trimmed.contains(": serde_json::Value")
        || trimmed.contains(": Value")
        || trimmed.contains(": Json")
        || trimmed.contains(": Vec<Value")
        || trimmed.contains(": Vec<Json")
        || trimmed.contains(": Option<Value")
        || trimmed.contains(": Option<Json")
        || trimmed.contains("&serde_json::Value")
        || trimmed.contains("&Value")
        || trimmed.contains("&Json")
}

fn hatch_is_declared(
    root: &Path,
    interface: &InterfaceDeclaration,
    finding: &HatchFinding,
) -> bool {
    interface.escape_hatches.iter().any(|hatch| {
        hatch.shape == finding.shape
            && normalize_manifest_path(root, &hatch.source.path) == finding.path
            && hatch.source.item == finding.item
            && hatch
                .source
                .needles
                .iter()
                .any(|needle| finding.text.contains(needle))
    })
}

fn manifest_declared_baseline_count(manifest: &InterfaceManifest) -> usize {
    manifest
        .interfaces
        .iter()
        .flat_map(|interface| &interface.escape_hatches)
        .filter(|hatch| hatch.baseline)
        .count()
}

fn render_findings(findings: &[Finding], declared_baseline: usize) -> String {
    let interfaces_without_declaration = findings
        .iter()
        .filter(|finding| finding.axis == "interfaces-without-declaration")
        .count();
    let undeclared_escape_hatches = findings
        .iter()
        .filter(|finding| finding.axis == "undeclared-escape-hatches")
        .count();
    let mut out = format!(
        "R.interfaces_without_declaration = {interfaces_without_declaration}\n\
         R.undeclared_escape_hatches = {undeclared_escape_hatches}\n\
         R.declared_escape_hatch_rows_open = {declared_baseline} \
         (baseline {BASELINE_DECLARED_ESCAPE_HATCH_ROWS_OPEN})\n\
         Delta R: compare this run to the previous typed-pipeline conformance receipt\n\
         Epsilon R.predicted = undeclared_escape_hatches=0, interfaces_without_declaration=0\n"
    );
    for finding in findings {
        out.push_str(&format!(
            "\n{}:{} [{}] {}: {}\nreplacement_plan: {}\n",
            finding.path,
            finding.line,
            finding.axis,
            finding.item,
            finding.message,
            finding.replacement
        ));
    }
    out
}
