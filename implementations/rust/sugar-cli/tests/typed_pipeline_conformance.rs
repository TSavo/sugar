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
const BASELINE_AMBIENT_TESTIMONY_SITES_OPEN: usize = 1;
const BASELINE_TRANSPORT_JSON_BACKEND_INGRESS_OPEN: usize = 0;
const BASELINE_BACKEND_FRONTEND_DECODE_CALLS_OPEN: usize = 0;
const BASELINE_FRONTEND_PROVENANCE_UNADMITTED_OPEN: usize = 0;
const BASELINE_UNTYPED_VERIFIER_OBLIGATION_PATHS_OPEN: usize = 0;

#[derive(Debug, Deserialize)]
struct InterfaceManifest {
    version: u32,
    #[serde(default)]
    ratchet: Ratchet,
    #[serde(default)]
    interface_sources: Vec<InterfaceSource>,
    #[serde(default)]
    pipeline_seams: Vec<PipelineSeam>,
    #[serde(default)]
    ambient_sources: Vec<AmbientSource>,
    #[serde(default)]
    interfaces: Vec<InterfaceDeclaration>,
    #[serde(default)]
    ambient_testimony_sites: Vec<AmbientTestimonySite>,
    #[serde(default)]
    frontend_boundary_sources: Vec<FrontendBoundarySource>,
    #[serde(default)]
    frontend_boundary_transport_json_ingress: Vec<FrontendBoundaryDeclaration>,
    #[serde(default)]
    frontend_boundary_decode_calls: Vec<FrontendBoundaryDeclaration>,
    #[serde(default)]
    frontend_boundary_allowlist_hatches: Vec<FrontendBoundaryDeclaration>,
    #[serde(default)]
    frontend_boundary_vocabulary: Vec<FrontendBoundaryVocabulary>,
    #[serde(default)]
    verifier_obligation_sources: Vec<VerifierObligationSource>,
    #[serde(default)]
    verifier_untyped_obligation_paths: Vec<FrontendBoundaryDeclaration>,
}

#[derive(Debug, Default, Deserialize)]
struct Ratchet {
    #[serde(default)]
    interfaces_without_declaration: usize,
    #[serde(default)]
    undeclared_escape_hatches: usize,
    #[serde(default)]
    declared_escape_hatch_rows_open: usize,
    #[serde(default)]
    ambient_testimony_sites: usize,
    #[serde(default)]
    transport_json_backend_ingress: usize,
    #[serde(default)]
    backend_frontend_decode_calls: usize,
    #[serde(default)]
    frontend_provenance_unadmitted: usize,
    #[serde(default)]
    untyped_verifier_obligation_paths: usize,
}

#[derive(Debug, Deserialize)]
struct InterfaceSource {
    path: String,
    #[serde(default)]
    ignored_items: Vec<IgnoredItem>,
}

#[derive(Debug, Clone, Deserialize)]
struct IgnoredItem {
    name: String,
    reason: String,
}

#[derive(Debug, Deserialize)]
struct PipelineSeam {
    root: String,
    #[serde(default)]
    file_prefixes: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct AmbientSource {
    path: String,
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

#[derive(Debug, Deserialize)]
struct AmbientTestimonySite {
    id: String,
    shape: String,
    owner: String,
    retirement: String,
    #[serde(default)]
    baseline: bool,
    source: AmbientSiteSource,
}

#[derive(Debug, Deserialize)]
struct AmbientSiteSource {
    path: String,
    item: String,
    #[serde(default)]
    needles: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct FrontendBoundarySource {
    path: String,
    #[serde(default)]
    frontend_adapter: bool,
}

#[derive(Debug, Deserialize)]
struct FrontendBoundaryDeclaration {
    id: String,
    shape: String,
    owner: String,
    retirement: String,
    #[serde(default)]
    baseline: bool,
    source: FrontendBoundarySiteSource,
}

#[derive(Debug, Deserialize)]
struct FrontendBoundarySiteSource {
    path: String,
    item: String,
    #[serde(default)]
    needles: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct FrontendBoundaryVocabulary {
    id: String,
    owner: String,
    declaration: String,
    retirement: String,
    #[serde(default)]
    baseline: bool,
}

#[derive(Debug, Deserialize)]
struct VerifierObligationSource {
    path: String,
}

#[derive(Debug, Clone)]
struct SourceSpec {
    path: String,
    ignored_items: Vec<IgnoredItem>,
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
struct AmbientFinding {
    path: String,
    item: String,
    line: usize,
    shape: String,
    text: String,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct FrontendBoundaryFinding {
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

#[test]
fn declared_path_floor_walks_sibling_items_even_without_interface_sources() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("declared_floor.rs");
    std::fs::write(
        &source,
        r#"
pub struct DeclaredPipelineInterface {
    typed: String,
}

pub struct SiblingPipelineInterface {
    typed: String,
}
"#,
    )
    .expect("write declared floor interface");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0

[[interfaces]]
id = "declared"
owner = "test::declared"
input_type = "DeclaredInput"
output_type = "DeclaredPipelineInterface"
addressing_rule = "fixture cid"
failure_type = "fixture diagnostic"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "DeclaredPipelineInterface", kind = "struct" }}
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "interfaces-without-declaration"
                && finding.item == "SiblingPipelineInterface"
        }),
        "a declared path must be walked as a source floor; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn pipeline_seam_discovery_walks_new_matching_files() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("report_witness_extra.rs");
    std::fs::write(
        &source,
        r#"
pub struct NewReportWitnessInterface {
    typed: String,
}
"#,
    )
    .expect("write discovered interface");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0

[[pipeline_seams]]
root = "{}"
file_prefixes = ["report_witness"]
"#,
        temp.path().display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "interfaces-without-declaration"
                && finding.item == "NewReportWitnessInterface"
        }),
        "pipeline seam discovery must find a new matching source file; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn shape_based_hatch_detectors_are_not_bound_to_census_item_names() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("shape_hatches.rs");
    std::fs::write(
        &source,
        r#"
pub struct AlternateSolverTelemetry {
    solver_name: String,
    error: String,
    solver_stdout: String,
}

pub struct CompatSolverConfig {
    z3_path: String,
}

pub const ALT_STAGE_VOCABULARY: &[&str] = &[
    "smt_emit",
];
"#,
    )
    .expect("write shape hatch interface");
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
id = "alt-solver-telemetry"
owner = "test::solver"
input_type = "fixture"
output_type = "AlternateSolverTelemetry"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "AlternateSolverTelemetry", kind = "struct" }}

[[interfaces]]
id = "compat-solver-config"
owner = "test::solver"
input_type = "fixture"
output_type = "CompatSolverConfig"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "CompatSolverConfig", kind = "struct" }}

[[interfaces]]
id = "alt-stage-vocabulary"
owner = "test::verifier"
input_type = "fixture"
output_type = "ALT_STAGE_VOCABULARY"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "ALT_STAGE_VOCABULARY", kind = "const" }}
"#,
        source.display(),
        source.display(),
        source.display(),
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "shape-detector planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    for (shape, item) in [
        ("free-text-solver-telemetry", "AlternateSolverTelemetry"),
        ("silent-fallback", "CompatSolverConfig"),
        ("stage-vocabulary-drift", "ALT_STAGE_VOCABULARY"),
    ] {
        assert!(
            findings.iter().any(|finding| {
                finding.axis == "undeclared-escape-hatches"
                    && finding.item == item
                    && finding.message.contains(shape)
            }),
            "missing shape-based finding for {shape}/{item}; findings:\n{}",
            render_findings(&findings, 0)
        );
    }
}

#[test]
fn unscoped_key_and_replay_irrecoverable_detectors_discriminate() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("ambient_shapes.rs");
    std::fs::write(
        &source,
        r#"
use std::collections::BTreeMap;
use std::path::PathBuf;

pub struct UnscopedLookupInterface {
    by_symbol: BTreeMap<String, MementoCid>,
}

pub struct ScopedLookupInterface {
    by_callsite: BTreeMap<(MementoCid, String, usize, String), MementoCid>,
}

pub struct ReplayIrrecoverableInterface {
    raw_evidence: Vec<u8>,
}

pub struct ReplayPinnedInterface {
    raw_evidence: Vec<u8>,
    evidence_cid: String,
    evidence_file: PathBuf,
}
"#,
    )
    .expect("write ambient shape fixture");
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
id = "unscoped"
owner = "test::ambient"
input_type = "fixture"
output_type = "UnscopedLookupInterface"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "UnscopedLookupInterface", kind = "struct" }}

[[interfaces]]
id = "scoped"
owner = "test::ambient"
input_type = "fixture"
output_type = "ScopedLookupInterface"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "ScopedLookupInterface", kind = "struct" }}

[[interfaces]]
id = "irrecoverable"
owner = "test::ambient"
input_type = "fixture"
output_type = "ReplayIrrecoverableInterface"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "ReplayIrrecoverableInterface", kind = "struct" }}

[[interfaces]]
id = "pinned"
owner = "test::ambient"
input_type = "fixture"
output_type = "ReplayPinnedInterface"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "ReplayPinnedInterface", kind = "struct" }}
"#,
        source.display(),
        source.display(),
        source.display(),
        source.display(),
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "ambient-shape planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "undeclared-escape-hatches"
                && finding.item == "UnscopedLookupInterface"
                && finding.message.contains("unscoped-key-lookup")
        }),
        "unscoped bare-key lookup must red; findings:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "undeclared-escape-hatches"
                && finding.item == "ReplayIrrecoverableInterface"
                && finding.message.contains("replay-irrecoverable-input")
        }),
        "raw replay input without a cid must red; findings:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings
            .iter()
            .all(|finding| finding.item != "ScopedLookupInterface"),
        "scoped callsite key must stay green; findings:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings
            .iter()
            .all(|finding| finding.item != "ReplayPinnedInterface"),
        "raw replay input with cid evidence must stay green; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn planted_ambient_self_witness_site_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("consistency_like.rs");
    std::fs::write(
        &source,
        r#"
fn collect_ambient_ground_callsite_facts() {}
fn with_ambient_ground_callsite_facts() {}
fn individual_obligation_path() {
    collect_ambient_ground_callsite_facts();
    with_ambient_ground_callsite_facts();
}
"#,
    )
    .expect("write planted ambient site");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0

[[ambient_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "planted ambient-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "ambient-testimony-sites"
                && finding.item == "ambient-ground-callsite-self-witness"
        }),
        "planted ambient self-witness site must red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn frontend_boundary_transport_json_ingress_planted_offender_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("planted_backend.rs");
    std::fs::write(
        &source,
        r#"
use serde_json::Value as Json;

pub struct PlantedCompiler;

impl IrCompiler for PlantedCompiler {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError> {
        todo!()
    }
}
"#,
    )
    .expect("write planted compiler ingress");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 0
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0

[[frontend_boundary_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "transport-json ingress planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "transport-json-backend-ingress" && finding.item == "PlantedCompiler"
        }),
        "planted IrCompiler &Json ingress must red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn frontend_boundary_backend_decode_planted_offender_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("planted_decode.rs");
    std::fs::write(
        &source,
        r#"
use serde_json::Value as Json;

pub fn compile_to_parts(ir: &Json) -> Result<CompiledFormula, CompileError> {
    let formula: sugar_ir_types::Formula = serde_json::from_value(ir.clone()).unwrap();
    todo!()
}
"#,
    )
    .expect("write planted backend decode");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 0
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0

[[frontend_boundary_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "backend-decode planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "backend-frontend-decode-calls" && finding.item == "compile_to_parts"
        }),
        "planted backend serde_json::from_value ingress must red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn frontend_boundary_frontend_adapter_decode_is_legal_near_miss() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("frontend.rs");
    std::fs::write(
        &source,
        r#"
use serde_json::Value as Json;

pub fn decode_json(ir: Json) -> Result<CompilerInput, FrontendError> {
    serde_json::from_value(ir).map_err(|_| FrontendError)
}
"#,
    )
    .expect("write legal frontend adapter");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 0
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0

[[frontend_boundary_sources]]
path = "{}"
frontend_adapter = true
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings
            .iter()
            .all(|finding| finding.axis != "backend-frontend-decode-calls"),
        "frontend adapter decode_json is the legal decode boundary; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn frontend_boundary_string_sludge_error_path_planted_offender_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("planted_rpc_error.rs");
    std::fs::write(
        &source,
        r#"
pub enum RpcFrontendFailure {
    Failed(String),
}
"#,
    )
    .expect("write planted string-sludge frontend error");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 0
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0

[[interface_sources]]
path = "{}"

[[interfaces]]
id = "rpc-frontend-failure"
owner = "test::rpc-frontend"
input_type = "fixture"
output_type = "RpcFrontendFailure"
addressing_rule = "fixture"
failure_type = "fixture"
replay_inputs = ["fixture"]
source = {{ path = "{}", item = "RpcFrontendFailure", kind = "enum" }}
"#,
        source.display(),
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "string-sludge frontend planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "undeclared-escape-hatches"
                && finding.item == "RpcFrontendFailure"
                && finding.message.contains("free-text-machine-error")
        }),
        "planted Failed(String) frontend error path must red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn dropped_frontend_boundary_baseline_row_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("declared_backend.rs");
    std::fs::write(
        &source,
        r#"
use serde_json::Value as Json;

pub struct DeclaredCompiler;

impl IrCompiler for DeclaredCompiler {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError> {
        todo!()
    }
}
"#,
    )
    .expect("write declared compiler ingress");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 1
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0

[[frontend_boundary_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "transport-json-backend-ingress" && finding.item == "DeclaredCompiler"
        }),
        "dropping a frontend-boundary baseline row must red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn frontend_boundary_untyped_verifier_obligation_planted_offender_turns_red() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("plan_like.rs");
    std::fs::write(
        &source,
        r#"
use serde_json::Value as Json;

pub fn run_plan_with_compilers(formula: &Json) {}

fn solver_input(formula: Option<&Json>) -> Result<String, String> {
    Ok(formula.map(Json::to_string).unwrap_or_default())
}
"#,
    )
    .expect("write planted verifier obligation path");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 0
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0
untyped_verifier_obligation_paths = 0

[[verifier_obligation_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    println!(
        "untyped verifier-obligation planted-control receipt:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "untyped-verifier-obligation-paths"
                && finding.item == "run_plan_with_compilers"
        }),
        "planted run_plan_with_compilers &Json obligation must red; findings:\n{}",
        render_findings(&findings, 0)
    );
    assert!(
        findings.iter().any(|finding| {
            finding.axis == "untyped-verifier-obligation-paths"
                && finding.item == "solver_input"
                && finding
                    .message
                    .contains("silent-json-stringify-solver-input")
        }),
        "planted solver_input Json::to_string fallback must red; findings:\n{}",
        render_findings(&findings, 0)
    );
}

#[test]
fn frontend_boundary_typed_verifier_obligation_near_miss_stays_green() {
    let temp = tempfile::tempdir().expect("tempdir");
    let source = temp.path().join("typed_plan_like.rs");
    std::fs::write(
        &source,
        r#"
use sugar_ir_compiler::CompilerInput;

pub fn run_plan_with_compilers(formula: &CompilerInput) {}

fn solver_input(formula: Option<&CompilerInput>) -> Result<String, String> {
    formula
        .map(|_| "typed obligation routed through compiler registry".to_string())
        .ok_or_else(|| "no typed ProofIR obligation available".to_string())
}
"#,
    )
    .expect("write typed verifier obligation path");
    let manifest = manifest_from_str(&format!(
        r#"
version = 1

[ratchet]
interfaces_without_declaration = 0
undeclared_escape_hatches = 0
declared_escape_hatch_rows_open = 0
ambient_testimony_sites = 0
transport_json_backend_ingress = 0
backend_frontend_decode_calls = 0
frontend_provenance_unadmitted = 0
untyped_verifier_obligation_paths = 0

[[verifier_obligation_sources]]
path = "{}"
"#,
        source.display()
    ));

    let findings = audit_fixture_manifest(temp.path(), &manifest);
    assert!(
        findings
            .iter()
            .all(|finding| finding.axis != "untyped-verifier-obligation-paths"),
        "typed verifier obligation path should stay green; findings:\n{}",
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
    for source in walked_interface_sources(root, manifest, &mut findings) {
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

    for ambient in &manifest.ambient_testimony_sites {
        validate_ambient_site_declaration(ambient, &mut findings);
    }
    for ambient in discover_ambient_testimony(root, manifest) {
        if !ambient_site_is_declared(root, manifest, &ambient) {
            findings.push(Finding {
                axis: "ambient-testimony-sites",
                path: ambient.path,
                line: ambient.line,
                item: ambient.item,
                message: format!(
                    "undeclared {} ambient testimony site: `{}`",
                    ambient.shape, ambient.text
                ),
                replacement: "declare this ambient site with owner+retirement, or split obligation/witness/boundary/replay into typed addressed inputs"
                    .to_string(),
            });
        }
    }

    for row in &manifest.frontend_boundary_transport_json_ingress {
        validate_frontend_boundary_declaration(row, &mut findings);
        validate_frontend_boundary_declared_needles_present(root, row, &mut findings);
    }
    for row in &manifest.frontend_boundary_decode_calls {
        validate_frontend_boundary_declaration(row, &mut findings);
        validate_frontend_boundary_declared_needles_present(root, row, &mut findings);
    }
    for row in &manifest.frontend_boundary_allowlist_hatches {
        validate_frontend_boundary_declaration(row, &mut findings);
        validate_frontend_boundary_allowlist(root, row, &mut findings);
    }
    for row in &manifest.frontend_boundary_vocabulary {
        validate_frontend_boundary_vocabulary(row, &mut findings);
    }
    for row in &manifest.verifier_untyped_obligation_paths {
        validate_frontend_boundary_declaration(row, &mut findings);
        validate_frontend_boundary_declared_needles_present(root, row, &mut findings);
    }

    for finding in discover_transport_json_backend_ingress(root, manifest, &mut findings) {
        if !frontend_boundary_finding_is_declared(
            root,
            &manifest.frontend_boundary_transport_json_ingress,
            &finding,
        ) {
            findings.push(Finding {
                axis: "transport-json-backend-ingress",
                path: finding.path,
                line: finding.line,
                item: finding.item,
                message: format!(
                    "undeclared transport JSON backend ingress: `{}`",
                    finding.text
                ),
                replacement: "declare this S1 baseline with owner+retirement, or move the backend boundary to S2's compile_typed(&CompilerInput) trait"
                    .to_string(),
            });
        }
    }

    for finding in discover_backend_frontend_decode_calls(root, manifest, &mut findings) {
        if !frontend_boundary_finding_is_declared(
            root,
            &manifest.frontend_boundary_decode_calls,
            &finding,
        ) {
            findings.push(Finding {
                axis: "backend-frontend-decode-calls",
                path: finding.path,
                line: finding.line,
                item: finding.item,
                message: format!(
                    "undeclared backend frontend-decode call on obligation payload: `{}`",
                    finding.text
                ),
                replacement: "declare this S1 baseline with owner+retirement, or relocate decode to the typed frontend adapter"
                    .to_string(),
            });
        }
    }

    for finding in discover_untyped_verifier_obligation_paths(root, manifest) {
        if !frontend_boundary_finding_is_declared(
            root,
            &manifest.verifier_untyped_obligation_paths,
            &finding,
        ) {
            findings.push(Finding {
                axis: "untyped-verifier-obligation-paths",
                path: finding.path,
                line: finding.line,
                item: finding.item,
                message: format!(
                    "undeclared {} in verifier obligation path: `{}`",
                    finding.shape, finding.text
                ),
                replacement: "route verifier obligations as CompilerInput (or a typed Formula if the caller census proves formula-only) and refuse precompiled non-SMT inputs loudly"
                    .to_string(),
            });
        }
    }

    let baseline = manifest_declared_baseline_count(manifest);
    let ambient_baseline = manifest_declared_ambient_count(manifest);
    let transport_baseline = manifest_declared_transport_ingress_count(manifest);
    let decode_baseline = manifest_declared_decode_call_count(manifest);
    let verifier_obligation_baseline =
        manifest_declared_untyped_verifier_obligation_count(manifest);
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
    if enforce_live_ratchet
        && manifest.ratchet.ambient_testimony_sites != BASELINE_AMBIENT_TESTIMONY_SITES_OPEN
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.ambient_testimony_sites".to_string(),
            message: format!(
                "ratchet pins ambient_testimony_sites at {}, expected {BASELINE_AMBIENT_TESTIMONY_SITES_OPEN}",
                manifest.ratchet.ambient_testimony_sites
            ),
            replacement: "S2 baseline is the declared #3313 ambient-ground-callsite self-witness row; drains own retirement"
                .to_string(),
        });
    }
    if enforce_live_ratchet && ambient_baseline != manifest.ratchet.ambient_testimony_sites {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.ambient_testimony_sites".to_string(),
            message: format!(
                "manifest has {ambient_baseline} baseline ambient testimony rows, ratchet pins {}",
                manifest.ratchet.ambient_testimony_sites
            ),
            replacement:
                "keep the manifest ambient baseline synchronized with the declared S2 rows"
                    .to_string(),
        });
    }
    if enforce_live_ratchet
        && manifest.ratchet.transport_json_backend_ingress
            != BASELINE_TRANSPORT_JSON_BACKEND_INGRESS_OPEN
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.transport_json_backend_ingress".to_string(),
            message: format!(
                "ratchet pins transport_json_backend_ingress at {}, expected {BASELINE_TRANSPORT_JSON_BACKEND_INGRESS_OPEN}",
                manifest.ratchet.transport_json_backend_ingress
            ),
            replacement: "S1 baseline is the declared compiler impl &Json ingress residue; S2/S7 retire it through compile_typed"
                .to_string(),
        });
    }
    if enforce_live_ratchet && transport_baseline != manifest.ratchet.transport_json_backend_ingress
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.transport_json_backend_ingress".to_string(),
            message: format!(
                "manifest has {transport_baseline} baseline transport-json ingress rows, ratchet pins {}",
                manifest.ratchet.transport_json_backend_ingress
            ),
            replacement: "keep Instrument A's declared baseline synchronized with the live compiler ingress census"
                .to_string(),
        });
    }
    if enforce_live_ratchet
        && manifest.ratchet.backend_frontend_decode_calls
            != BASELINE_BACKEND_FRONTEND_DECODE_CALLS_OPEN
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.backend_frontend_decode_calls".to_string(),
            message: format!(
                "ratchet pins backend_frontend_decode_calls at {}, expected {BASELINE_BACKEND_FRONTEND_DECODE_CALLS_OPEN}",
                manifest.ratchet.backend_frontend_decode_calls
            ),
            replacement: "S1 baseline is the declared backend serde_json::from_value ingress residue; S3/S7 retire it"
                .to_string(),
        });
    }
    if enforce_live_ratchet && decode_baseline != manifest.ratchet.backend_frontend_decode_calls {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.backend_frontend_decode_calls".to_string(),
            message: format!(
                "manifest has {decode_baseline} baseline backend decode rows, ratchet pins {}",
                manifest.ratchet.backend_frontend_decode_calls
            ),
            replacement: "keep Instrument B's declared baseline synchronized with the live backend decode census"
                .to_string(),
        });
    }
    if enforce_live_ratchet
        && manifest.ratchet.frontend_provenance_unadmitted
            != BASELINE_FRONTEND_PROVENANCE_UNADMITTED_OPEN
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.frontend_provenance_unadmitted".to_string(),
            message: format!(
                "ratchet pins frontend_provenance_unadmitted at {}, expected {BASELINE_FRONTEND_PROVENANCE_UNADMITTED_OPEN}",
                manifest.ratchet.frontend_provenance_unadmitted
            ),
            replacement: "the amended S6 provenance policy starts empty; every output difference must be admitted by typed policy"
                .to_string(),
        });
    }
    if enforce_live_ratchet
        && manifest.ratchet.untyped_verifier_obligation_paths
            != BASELINE_UNTYPED_VERIFIER_OBLIGATION_PATHS_OPEN
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.untyped_verifier_obligation_paths".to_string(),
            message: format!(
                "ratchet pins untyped_verifier_obligation_paths at {}, expected {BASELINE_UNTYPED_VERIFIER_OBLIGATION_PATHS_OPEN}",
                manifest.ratchet.untyped_verifier_obligation_paths
            ),
            replacement: "S4 exits with zero untyped registry/verifier obligation paths; future residues require a named row with owner+retirement"
                .to_string(),
        });
    }
    if enforce_live_ratchet
        && verifier_obligation_baseline != manifest.ratchet.untyped_verifier_obligation_paths
    {
        findings.push(Finding {
            axis: "ratchet-vector",
            path: MANIFEST_REL.to_string(),
            line: 0,
            item: "R.untyped_verifier_obligation_paths".to_string(),
            message: format!(
                "manifest has {verifier_obligation_baseline} baseline untyped verifier-obligation rows, ratchet pins {}",
                manifest.ratchet.untyped_verifier_obligation_paths
            ),
            replacement: "keep S4's verifier-obligation rows synchronized with the live registry/plan census"
                .to_string(),
        });
    }

    findings.sort();
    findings
}

fn walked_interface_sources(
    root: &Path,
    manifest: &InterfaceManifest,
    findings: &mut Vec<Finding>,
) -> Vec<SourceSpec> {
    let mut specs: BTreeMap<String, SourceSpec> = BTreeMap::new();
    for source in &manifest.interface_sources {
        merge_source_spec(
            &mut specs,
            normalize_manifest_path(root, &source.path),
            source.ignored_items.clone(),
        );
    }
    for interface in &manifest.interfaces {
        merge_source_spec(
            &mut specs,
            normalize_manifest_path(root, &interface.source.path),
            Vec::new(),
        );
    }
    for path in discover_pipeline_seam_files(root, manifest, findings) {
        merge_source_spec(&mut specs, path, Vec::new());
    }
    specs.into_values().collect()
}

fn merge_source_spec(
    specs: &mut BTreeMap<String, SourceSpec>,
    path: String,
    ignored_items: Vec<IgnoredItem>,
) {
    let spec = specs.entry(path.clone()).or_insert_with(|| SourceSpec {
        path,
        ignored_items: Vec::new(),
    });
    spec.ignored_items.extend(ignored_items);
}

fn discover_pipeline_seam_files(
    root: &Path,
    manifest: &InterfaceManifest,
    findings: &mut Vec<Finding>,
) -> Vec<String> {
    let mut out = BTreeSet::new();
    for seam in &manifest.pipeline_seams {
        if seam.root.trim().is_empty() || seam.file_prefixes.is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: MANIFEST_REL.to_string(),
                line: 0,
                item: "pipeline_seams".to_string(),
                message: "pipeline seam discovery requires root and file_prefixes".to_string(),
                replacement:
                    "name the seam root and the file prefixes that represent typed pipeline modules"
                        .to_string(),
            });
            continue;
        }
        let seam_root = resolve_manifest_path(root, &seam.root);
        for path in rust_files_under(&seam_root) {
            let rel_to_seam = path
                .strip_prefix(&seam_root)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/");
            let rel_without_rs = rel_to_seam.trim_end_matches(".rs");
            if seam.file_prefixes.iter().any(|prefix| {
                rel_without_rs == prefix
                    || rel_without_rs
                        .strip_prefix(prefix)
                        .is_some_and(|rest| rest.starts_with('_') || rest.starts_with('/'))
            }) {
                out.insert(
                    path.strip_prefix(root)
                        .unwrap_or(&path)
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            }
        }
    }
    out.into_iter().collect()
}

fn rust_files_under(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                let name = path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("");
                if name != "target" {
                    stack.push(path);
                }
            } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
                out.push(path);
            }
        }
    }
    out
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

fn validate_ambient_site_declaration(ambient: &AmbientTestimonySite, findings: &mut Vec<Finding>) {
    for (field, value) in [
        ("id", &ambient.id),
        ("shape", &ambient.shape),
        ("owner", &ambient.owner),
        ("retirement", &ambient.retirement),
        ("source.path", &ambient.source.path),
        ("source.item", &ambient.source.item),
    ] {
        if value.trim().is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: ambient.source.path.clone(),
                line: 0,
                item: ambient.id.clone(),
                message: format!("ambient site `{}` has empty `{field}`", ambient.id),
                replacement:
                    "every ambient testimony site must name shape, owner, retirement, and source"
                        .to_string(),
            });
        }
    }
    if ambient.source.needles.is_empty()
        || ambient
            .source
            .needles
            .iter()
            .any(|needle| needle.trim().is_empty())
    {
        findings.push(Finding {
            axis: "manifest-schema",
            path: ambient.source.path.clone(),
            line: 0,
            item: ambient.id.clone(),
            message: format!("ambient site `{}` has no source needle", ambient.id),
            replacement: "pin each ambient site to the concrete source text it retires".to_string(),
        });
    }
}

fn ignored_items(source: SourceSpec, findings: &mut Vec<Finding>) -> BTreeSet<String> {
    let mut ignored = BTreeSet::new();
    for item in source.ignored_items {
        if item.name.trim().is_empty() || item.reason.trim().is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: source.path.clone(),
                line: 0,
                item: item.name,
                message: "ignored item must name both item and reason".to_string(),
                replacement: "make non-interface dismissals explicit and reviewable".to_string(),
            });
            continue;
        }
        ignored.insert(item.name);
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
    let mut depth = 0isize;
    for (i, line) in text.lines().enumerate() {
        if depth == 0 {
            if let Some((kind, name)) = parse_rust_item(line) {
                if ignored.contains(&name) {
                    depth += brace_delta(line);
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
        depth += brace_delta(line);
        if depth < 0 {
            depth = 0;
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

fn cfg_test_module_end(lines: &[&str], idx: usize) -> Option<usize> {
    if !lines[idx].trim_start().starts_with("#[cfg(test)]") {
        return None;
    }
    let mut module_idx = idx + 1;
    while module_idx < lines.len() {
        let trimmed = lines[module_idx].trim();
        if trimmed.is_empty() || trimmed.starts_with("#[") {
            module_idx += 1;
            continue;
        }
        if !trimmed.starts_with("mod tests") {
            return None;
        }
        let mut depth = brace_delta(lines[module_idx]);
        if depth <= 0 {
            return None;
        }
        let mut cursor = module_idx + 1;
        while cursor < lines.len() {
            depth += brace_delta(lines[cursor]);
            if depth <= 0 {
                return Some(cursor);
            }
            cursor += 1;
        }
        return Some(lines.len().saturating_sub(1));
    }
    None
}

fn discover_escape_hatches(path: &str, item: &str, block: &ItemBlock) -> Vec<HatchFinding> {
    let mut findings = Vec::new();
    let has_solver_context = block.lines.iter().any(|line| {
        line.text.contains("solver_")
            || line.text.contains("Solver")
            || line.text.contains("solver:")
    });
    let has_replay_cid = block.lines.iter().any(|line| {
        let lower = line.text.to_ascii_lowercase();
        lower.contains("cid") || lower.contains("content address")
    });
    for line in &block.lines {
        let trimmed = line.text.trim();
        if trimmed.starts_with("//") || trimmed.starts_with('#') {
            continue;
        }
        let shape = if is_json_value_boundary(trimmed) {
            Some("serde-json-value")
        } else if trimmed.contains("Failed(String)") {
            Some("free-text-machine-error")
        } else if trimmed.contains("solver_stdout: String")
            || trimmed.contains("solver_stderr: String")
            || (has_solver_context && trimmed.contains("error: String"))
        {
            Some("free-text-solver-telemetry")
        } else if trimmed.contains("z3_path: String") {
            Some("silent-fallback")
        } else if trimmed.contains("\"smt_emit\"") {
            Some("stage-vocabulary-drift")
        } else if is_unscoped_key_lookup(trimmed) {
            Some("unscoped-key-lookup")
        } else if is_replay_irrecoverable_input(trimmed, has_replay_cid) {
            Some("replay-irrecoverable-input")
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

fn is_unscoped_key_lookup(trimmed: &str) -> bool {
    let compact = trimmed.replace(' ', "");
    (compact.contains("BTreeMap<String,MementoCid>")
        || compact.contains("HashMap<String,MementoCid>"))
        && !compact.contains("(MementoCid,")
}

fn is_replay_irrecoverable_input(trimmed: &str, has_replay_cid: bool) -> bool {
    if has_replay_cid {
        return false;
    }
    let lower = trimmed.to_ascii_lowercase();
    trimmed.contains("Vec<u8>")
        && (lower.contains("raw") || lower.contains("evidence") || lower.contains("input"))
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

fn discover_ambient_testimony(root: &Path, manifest: &InterfaceManifest) -> Vec<AmbientFinding> {
    let mut paths = BTreeSet::new();
    for source in &manifest.ambient_sources {
        paths.insert(normalize_manifest_path(root, &source.path));
    }
    for ambient in &manifest.ambient_testimony_sites {
        paths.insert(normalize_manifest_path(root, &ambient.source.path));
    }
    let mut findings = Vec::new();
    for rel in paths {
        let path = resolve_manifest_path(root, &rel);
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        if text.contains("collect_ambient_ground_callsite_facts")
            && text.contains("with_ambient_ground_callsite_facts")
        {
            let line = text
                .lines()
                .position(|line| line.contains("with_ambient_ground_callsite_facts"))
                .map(|idx| idx + 1)
                .unwrap_or(1);
            findings.push(AmbientFinding {
                path: rel,
                item: "ambient-ground-callsite-self-witness".to_string(),
                line,
                shape: "ambient-ground-callsite-self-witness".to_string(),
                text: "ambient ground callsite facts can be collected and conjoined into a matching obligation".to_string(),
            });
        }
    }
    findings.sort();
    findings
}

fn ambient_site_is_declared(
    root: &Path,
    manifest: &InterfaceManifest,
    finding: &AmbientFinding,
) -> bool {
    manifest.ambient_testimony_sites.iter().any(|ambient| {
        ambient.shape == finding.shape
            && normalize_manifest_path(root, &ambient.source.path) == finding.path
            && ambient.source.item == finding.item
            && ambient.source.needles.iter().all(|needle| {
                std::fs::read_to_string(resolve_manifest_path(root, &ambient.source.path))
                    .map(|text| text.contains(needle))
                    .unwrap_or(false)
            })
    })
}

fn validate_frontend_boundary_declaration(
    row: &FrontendBoundaryDeclaration,
    findings: &mut Vec<Finding>,
) {
    for (field, value) in [
        ("id", &row.id),
        ("shape", &row.shape),
        ("owner", &row.owner),
        ("retirement", &row.retirement),
        ("source.path", &row.source.path),
        ("source.item", &row.source.item),
    ] {
        if value.trim().is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: row.source.path.clone(),
                line: 0,
                item: row.id.clone(),
                message: format!("frontend boundary row `{}` has empty `{field}`", row.id),
                replacement:
                    "every frontend-boundary row must name shape, owner, retirement, and source"
                        .to_string(),
            });
        }
    }
    if row.source.needles.is_empty()
        || row
            .source
            .needles
            .iter()
            .any(|needle| needle.trim().is_empty())
    {
        findings.push(Finding {
            axis: "manifest-schema",
            path: row.source.path.clone(),
            line: 0,
            item: row.id.clone(),
            message: format!("frontend boundary row `{}` has no source needle", row.id),
            replacement: "pin every frontend-boundary row to the concrete source text it retires"
                .to_string(),
        });
    }
}

fn validate_frontend_boundary_allowlist(
    root: &Path,
    row: &FrontendBoundaryDeclaration,
    findings: &mut Vec<Finding>,
) {
    let path = resolve_manifest_path(root, &row.source.path);
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    for needle in &row.source.needles {
        if !text.contains(needle) {
            findings.push(Finding {
                axis: "declared-frontend-boundary-missing",
                path: row.source.path.clone(),
                line: 0,
                item: row.source.item.clone(),
                message: format!(
                    "declared frontend-boundary allowlist `{}` needle `{needle}` is no longer present",
                    row.id
                ),
                replacement: "remove the allowlist only with the typed retirement that made it unnecessary"
                    .to_string(),
            });
        }
    }
}

fn validate_frontend_boundary_declared_needles_present(
    root: &Path,
    row: &FrontendBoundaryDeclaration,
    findings: &mut Vec<Finding>,
) {
    let path = resolve_manifest_path(root, &row.source.path);
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    for needle in &row.source.needles {
        if !text.contains(needle) {
            findings.push(Finding {
                axis: "declared-frontend-boundary-missing",
                path: row.source.path.clone(),
                line: 0,
                item: row.source.item.clone(),
                message: format!(
                    "declared frontend-boundary baseline `{}` needle `{needle}` is no longer present",
                    row.id
                ),
                replacement: "retire the baseline row only with the typed boundary move that made this source shape unrepresentable"
                    .to_string(),
            });
        }
    }
}

fn validate_frontend_boundary_vocabulary(
    row: &FrontendBoundaryVocabulary,
    findings: &mut Vec<Finding>,
) {
    let _baseline_declared = row.baseline;
    for (field, value) in [
        ("id", &row.id),
        ("owner", &row.owner),
        ("declaration", &row.declaration),
        ("retirement", &row.retirement),
    ] {
        if value.trim().is_empty() {
            findings.push(Finding {
                axis: "manifest-schema",
                path: MANIFEST_REL.to_string(),
                line: 0,
                item: row.id.clone(),
                message: format!("frontend-boundary vocabulary row `{}` has empty `{field}`", row.id),
                replacement: "declare the amended typed vocabulary with owner and retirement so later slices do not invent string folklore"
                    .to_string(),
            });
        }
    }
}

fn discover_transport_json_backend_ingress(
    root: &Path,
    manifest: &InterfaceManifest,
    findings: &mut Vec<Finding>,
) -> Vec<FrontendBoundaryFinding> {
    let mut out = Vec::new();
    for source in walked_frontend_boundary_sources(root, manifest, findings) {
        let path = resolve_manifest_path(root, &source.path);
        let rel = normalize_manifest_path(root, &source.path);
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let lines: Vec<&str> = text.lines().collect();
        let mut idx = 0usize;
        while idx < lines.len() {
            if let Some(end) = cfg_test_module_end(&lines, idx) {
                idx = end + 1;
                continue;
            }
            let line = lines[idx];
            if let Some(item) = parse_ircompiler_impl_item(line) {
                let mut depth = brace_delta(line);
                let mut saw_brace = line.contains('{');
                let mut cursor = idx + 1;
                while cursor < lines.len() {
                    let body_line = lines[cursor];
                    if body_line.contains('{') {
                        saw_brace = true;
                    }
                    if is_compile_signature_with_transport_json(body_line) {
                        let finding = FrontendBoundaryFinding {
                            path: rel.clone(),
                            item: item.clone(),
                            line: cursor + 1,
                            shape: "transport-json-ircompiler-impl-ingress".to_string(),
                            text: body_line.trim().to_string(),
                        };
                        if !frontend_boundary_transport_frontend_is_declared(
                            root, manifest, &finding,
                        ) {
                            out.push(finding);
                        }
                    }
                    depth += brace_delta(body_line);
                    if saw_brace && depth <= 0 {
                        break;
                    }
                    cursor += 1;
                }
                idx = cursor;
            }
            idx += 1;
        }
    }
    out.sort();
    out
}

fn discover_backend_frontend_decode_calls(
    root: &Path,
    manifest: &InterfaceManifest,
    findings: &mut Vec<Finding>,
) -> Vec<FrontendBoundaryFinding> {
    let mut out = Vec::new();
    for source in walked_frontend_boundary_sources(root, manifest, findings) {
        if source.frontend_adapter {
            continue;
        }
        let path = resolve_manifest_path(root, &source.path);
        let rel = normalize_manifest_path(root, &source.path);
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let lines: Vec<&str> = text.lines().collect();
        let mut idx = 0usize;
        while idx < lines.len() {
            if let Some(end) = cfg_test_module_end(&lines, idx) {
                idx = end + 1;
                continue;
            }
            let line = lines[idx];
            if let Some(item) = parse_rust_function_name(line) {
                if is_backend_compile_entrypoint(&item)
                    && function_signature_has_json_arg(&lines, idx, &item)
                {
                    out.push(FrontendBoundaryFinding {
                        path: rel.clone(),
                        item: item.clone(),
                        line: idx + 1,
                        shape: "backend-json-helper-signature".to_string(),
                        text: signature_text(&lines, idx),
                    });
                }
                let mut depth = 0isize;
                let mut saw_brace = false;
                let mut cursor = idx;
                while cursor < lines.len() {
                    let body_line = lines[cursor];
                    if body_line.contains('{') {
                        saw_brace = true;
                    }
                    if is_backend_compile_entrypoint(&item)
                        && body_line.contains("serde_json::from_value")
                    {
                        out.push(FrontendBoundaryFinding {
                            path: rel.clone(),
                            item: item.clone(),
                            line: cursor + 1,
                            shape: "backend-obligation-from-value".to_string(),
                            text: body_line.trim().to_string(),
                        });
                    }
                    depth += brace_delta(body_line);
                    if cursor > idx && saw_brace && depth <= 0 {
                        break;
                    }
                    cursor += 1;
                }
                idx = cursor;
            }
            idx += 1;
        }
    }
    out.sort();
    out
}

#[derive(Debug, Clone)]
struct FrontendBoundarySourceSpec {
    path: String,
    frontend_adapter: bool,
}

fn walked_frontend_boundary_sources(
    root: &Path,
    manifest: &InterfaceManifest,
    findings: &mut Vec<Finding>,
) -> Vec<FrontendBoundarySourceSpec> {
    let mut sources: BTreeMap<String, FrontendBoundarySourceSpec> = BTreeMap::new();
    for source in &manifest.frontend_boundary_sources {
        merge_frontend_boundary_source(
            &mut sources,
            normalize_manifest_path(root, &source.path),
            source.frontend_adapter,
        );
    }
    for row in manifest
        .frontend_boundary_transport_json_ingress
        .iter()
        .chain(manifest.frontend_boundary_decode_calls.iter())
        .chain(manifest.frontend_boundary_allowlist_hatches.iter())
    {
        merge_frontend_boundary_source(
            &mut sources,
            normalize_manifest_path(root, &row.source.path),
            false,
        );
    }
    for path in discover_pipeline_seam_files(root, manifest, findings) {
        if path.contains("sugar-ir-compiler") || path.contains("sugar-verifier/src/solvers/plan.rs")
        {
            merge_frontend_boundary_source(&mut sources, path, false);
        }
    }
    sources.into_values().collect()
}

fn merge_frontend_boundary_source(
    sources: &mut BTreeMap<String, FrontendBoundarySourceSpec>,
    path: String,
    frontend_adapter: bool,
) {
    let entry = sources
        .entry(path.clone())
        .or_insert(FrontendBoundarySourceSpec {
            path,
            frontend_adapter,
        });
    entry.frontend_adapter |= frontend_adapter;
}

fn parse_ircompiler_impl_item(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let rest = trimmed.strip_prefix("impl IrCompiler for ")?;
    let name = rest
        .split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .next()
        .unwrap_or("");
    (!name.is_empty()).then(|| name.to_string())
}

fn parse_rust_function_name(line: &str) -> Option<String> {
    let trimmed = line.trim();
    if trimmed.starts_with("//") || trimmed.starts_with("#[") {
        return None;
    }
    let without_vis = trimmed
        .strip_prefix("pub(crate) ")
        .or_else(|| trimmed.strip_prefix("pub(super) "))
        .or_else(|| trimmed.strip_prefix("pub "))
        .unwrap_or(trimmed);
    let rest = without_vis.strip_prefix("fn ")?;
    let name = rest
        .split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .next()
        .unwrap_or("");
    (!name.is_empty()).then(|| name.to_string())
}

fn is_compile_signature_with_transport_json(line: &str) -> bool {
    line.contains("fn compile(") && is_json_value_boundary(line.trim())
}

fn is_backend_compile_entrypoint(item: &str) -> bool {
    matches!(
        item,
        "emit"
            | "compile_to_parts"
            | "compile_asserted_to_parts"
            | "compile_inner"
            | "compile_artifact"
    )
}

fn frontend_boundary_finding_is_declared(
    root: &Path,
    rows: &[FrontendBoundaryDeclaration],
    finding: &FrontendBoundaryFinding,
) -> bool {
    rows.iter().any(|row| {
        row.shape == finding.shape
            && normalize_manifest_path(root, &row.source.path) == finding.path
            && row.source.item == finding.item
            && row
                .source
                .needles
                .iter()
                .all(|needle| finding.text.contains(needle))
    })
}

fn frontend_boundary_transport_frontend_is_declared(
    root: &Path,
    manifest: &InterfaceManifest,
    finding: &FrontendBoundaryFinding,
) -> bool {
    manifest
        .frontend_boundary_allowlist_hatches
        .iter()
        .any(|row| {
            let text = std::fs::read_to_string(resolve_manifest_path(root, &row.source.path))
                .unwrap_or_default();
            row.shape == "json-rpc-transport-frontend"
                && normalize_manifest_path(root, &row.source.path) == finding.path
                && row.source.item == finding.item
                && row
                    .source
                    .needles
                    .iter()
                    .all(|needle| text.contains(needle))
        })
}

fn discover_untyped_verifier_obligation_paths(
    root: &Path,
    manifest: &InterfaceManifest,
) -> Vec<FrontendBoundaryFinding> {
    let mut out = Vec::new();
    let mut sources = BTreeSet::new();
    for source in &manifest.verifier_obligation_sources {
        sources.insert(normalize_manifest_path(root, &source.path));
    }
    for row in &manifest.verifier_untyped_obligation_paths {
        sources.insert(normalize_manifest_path(root, &row.source.path));
    }
    for rel in sources {
        let path = resolve_manifest_path(root, &rel);
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let lines: Vec<&str> = text.lines().collect();
        for (idx, line) in lines.iter().enumerate() {
            let trimmed = line.trim();
            if trimmed.starts_with("//") {
                continue;
            }
            if rel.ends_with("registry.rs")
                && function_signature_has_json_arg(&lines, idx, "compile")
            {
                out.push(FrontendBoundaryFinding {
                    path: rel.clone(),
                    item: "Registry::compile".to_string(),
                    line: idx + 1,
                    shape: "registry-compile-json-obligation".to_string(),
                    text: trimmed.to_string(),
                });
            }
            if function_signature_has_untyped_obligation(&lines, idx, "run_plan", "run_plan") {
                out.push(FrontendBoundaryFinding {
                    path: rel.clone(),
                    item: "run_plan".to_string(),
                    line: idx + 1,
                    shape: "verifier-plan-json-obligation".to_string(),
                    text: signature_text(&lines, idx),
                });
            }
            if function_signature_has_untyped_obligation(
                &lines,
                idx,
                "run_plan_with_compilers",
                "run_plan_with_compilers",
            ) {
                out.push(FrontendBoundaryFinding {
                    path: rel.clone(),
                    item: "run_plan_with_compilers".to_string(),
                    line: idx + 1,
                    shape: "verifier-plan-json-obligation".to_string(),
                    text: signature_text(&lines, idx),
                });
            }
            if function_signature_has_untyped_obligation(
                &lines,
                idx,
                "solver_input",
                "solver_input",
            ) {
                out.push(FrontendBoundaryFinding {
                    path: rel.clone(),
                    item: "solver_input".to_string(),
                    line: idx + 1,
                    shape: "verifier-plan-json-obligation".to_string(),
                    text: signature_text(&lines, idx),
                });
            }
            if trimmed.contains("Json::to_string") || trimmed.contains("serde_json::to_string") {
                out.push(FrontendBoundaryFinding {
                    path: rel.clone(),
                    item: enclosing_function_name(&lines, idx)
                        .unwrap_or_else(|| "verifier-obligation-stringify".to_string()),
                    line: idx + 1,
                    shape: "silent-json-stringify-solver-input".to_string(),
                    text: trimmed.to_string(),
                });
            }
        }
    }
    out.sort();
    out
}

fn function_signature_has_untyped_obligation(
    lines: &[&str],
    idx: usize,
    fn_name: &str,
    item_name: &str,
) -> bool {
    let trimmed = lines[idx].trim();
    let starts_function = trimmed.starts_with(&format!("pub fn {fn_name}("))
        || trimmed.starts_with(&format!("fn {fn_name}("));
    if !starts_function {
        return false;
    }
    let text = signature_text(lines, idx);
    text.contains(item_name) && (text.contains("&Json") || text.contains("&serde_json::Value"))
}

fn function_signature_has_json_arg(lines: &[&str], idx: usize, fn_name: &str) -> bool {
    let trimmed = lines[idx].trim();
    let starts_function = trimmed.starts_with(&format!("pub fn {fn_name}("))
        || trimmed.starts_with(&format!("fn {fn_name}("));
    starts_function && {
        let text = signature_text(lines, idx);
        text.contains("&Json") || text.contains("&serde_json::Value")
    }
}

fn signature_text(lines: &[&str], idx: usize) -> String {
    let mut parts = Vec::new();
    for line in lines.iter().skip(idx).take(12) {
        parts.push(line.trim());
        if line.contains(")") {
            break;
        }
    }
    parts.join(" ")
}

fn enclosing_function_name(lines: &[&str], idx: usize) -> Option<String> {
    for line in lines[..=idx].iter().rev() {
        if let Some(name) = parse_rust_function_name(line) {
            return Some(name);
        }
    }
    None
}

fn manifest_declared_baseline_count(manifest: &InterfaceManifest) -> usize {
    manifest
        .interfaces
        .iter()
        .flat_map(|interface| &interface.escape_hatches)
        .filter(|hatch| hatch.baseline)
        .count()
}

fn manifest_declared_ambient_count(manifest: &InterfaceManifest) -> usize {
    manifest
        .ambient_testimony_sites
        .iter()
        .filter(|ambient| ambient.baseline)
        .count()
}

fn manifest_declared_transport_ingress_count(manifest: &InterfaceManifest) -> usize {
    manifest
        .frontend_boundary_transport_json_ingress
        .iter()
        .filter(|row| row.baseline)
        .count()
}

fn manifest_declared_decode_call_count(manifest: &InterfaceManifest) -> usize {
    manifest
        .frontend_boundary_decode_calls
        .iter()
        .filter(|row| row.baseline)
        .count()
}

fn manifest_declared_untyped_verifier_obligation_count(manifest: &InterfaceManifest) -> usize {
    manifest
        .verifier_untyped_obligation_paths
        .iter()
        .filter(|row| row.baseline)
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
    let ambient_testimony_sites = findings
        .iter()
        .filter(|finding| finding.axis == "ambient-testimony-sites")
        .count();
    let transport_json_backend_ingress = findings
        .iter()
        .filter(|finding| finding.axis == "transport-json-backend-ingress")
        .count();
    let backend_frontend_decode_calls = findings
        .iter()
        .filter(|finding| finding.axis == "backend-frontend-decode-calls")
        .count();
    let frontend_provenance_unadmitted = findings
        .iter()
        .filter(|finding| finding.axis == "frontend-provenance-unadmitted")
        .count();
    let untyped_verifier_obligation_paths = findings
        .iter()
        .filter(|finding| finding.axis == "untyped-verifier-obligation-paths")
        .count();
    let mut out = format!(
        "R.interfaces_without_declaration = {interfaces_without_declaration}\n\
         R.undeclared_escape_hatches = {undeclared_escape_hatches}\n\
         R.ambient_testimony_sites = {ambient_testimony_sites}\n\
         R.transport_json_backend_ingress = {transport_json_backend_ingress}\n\
         R.backend_frontend_decode_calls = {backend_frontend_decode_calls}\n\
         R.frontend_provenance_unadmitted = {frontend_provenance_unadmitted}\n\
         R.untyped_verifier_obligation_paths = {untyped_verifier_obligation_paths}\n\
         R.declared_escape_hatch_rows_open = {declared_baseline} \
         (baseline {BASELINE_DECLARED_ESCAPE_HATCH_ROWS_OPEN})\n\
         Delta R: compare this run to the previous typed-pipeline conformance receipt\n\
         Epsilon R.predicted = undeclared_escape_hatches=0, interfaces_without_declaration=0, ambient_testimony_sites=0, transport_json_backend_ingress=0, backend_frontend_decode_calls=0, frontend_provenance_unadmitted=0, untyped_verifier_obligation_paths=0\n"
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
