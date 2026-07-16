use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value as Json};
use sugar_lift_rust_tests::sugar::catalog::catalog_claims;
use sugar_lift_rust_tests::{
    emit_value_contract, lift_file, AdapterOutput, AssertionFactEmission, AssertionFactKind,
};

// This harness verifies Rust sugar SOURCE-witness pairs: minimal source snippets
// owned by a Sugar claim. It is unrelated to the cargo-test WitnessPackageMemento
// produced by `sugar-lift-rust-cargo-test-witness`.
//
// Assertion 2 currently targets `sugar_ir_symbolic::ContractDecl`; when #3240
// lands the typed `sugar_ir_types::Declaration` surface, this file should only
// need to change the emitted-node assertion target, not the ownership/verdict
// composition law.

fn non_empty(value: &str) -> bool {
    !value.trim().is_empty()
}

#[test]
fn witness_catalog_vectors_are_recomputed_from_typed_dispositions() {
    let catalog = catalog_claims();
    let seeded = seed_witnesses()
        .into_iter()
        .map(|pair| pair.claim)
        .collect::<BTreeSet<_>>();
    let mut claim_names = BTreeSet::new();
    let mut pair_names = BTreeSet::new();
    let mut counts = BTreeMap::<&'static str, usize>::new();

    for claim in &catalog {
        assert!(
            claim_names.insert(claim.name),
            "duplicate claim `{}`",
            claim.name
        );
        match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::Pair { truthful, lying } => {
                assert!(
                    non_empty(truthful),
                    "Pair claim `{}` must carry truthful source",
                    claim.name
                );
                assert!(
                    non_empty(lying),
                    "Pair claim `{}` must carry lying source",
                    claim.name
                );
                assert!(
                    seeded.contains(claim.name),
                    "Pair claim `{}` must be exercised by seed_witnesses",
                    claim.name
                );
                pair_names.insert(claim.name);
                *counts.entry("pair").or_default() += 1;
            }
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing {
                floor,
                reason,
            } => {
                assert!(
                    non_empty(floor),
                    "NotVerdictBearing claim `{}` must name its floor",
                    claim.name
                );
                assert!(
                    non_empty(reason),
                    "NotVerdictBearing claim `{}` must justify the opt-out",
                    claim.name
                );
                *counts.entry("not-verdict-bearing").or_default() += 1;
            }
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut {
                floor,
                reason,
                retirement,
            } => {
                assert!(
                    non_empty(floor),
                    "TemporalOptOut claim `{}` must name its floor",
                    claim.name
                );
                assert!(
                    non_empty(reason),
                    "TemporalOptOut claim `{}` must justify the opt-out",
                    claim.name
                );
                assert!(
                    non_empty(retirement),
                    "TemporalOptOut claim `{}` must name its retirement condition",
                    claim.name
                );
                *counts.entry("temporal-opt-out").or_default() += 1;
            }
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::ReasonedBucket { blocker } => {
                assert!(
                    non_empty(blocker),
                    "ReasonedBucket claim `{}` must name its blocker",
                    claim.name
                );
                *counts.entry("reasoned-bucket").or_default() += 1;
            }
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::PinnedCatch { family } => {
                assert!(
                    non_empty(family),
                    "PinnedCatch claim `{}` must name its #3415 family",
                    claim.name
                );
                *counts.entry("pinned-catch").or_default() += 1;
            }
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalCampaign { slice } => {
                assert!(
                    non_empty(slice),
                    "TemporalCampaign claim `{}` must name its owning temporal slice",
                    claim.name
                );
                *counts.entry("temporal-campaign").or_default() += 1;
            }
        }
    }

    let residual_frontier = counts.get("reasoned-bucket").copied().unwrap_or(0)
        + counts.get("pinned-catch").copied().unwrap_or(0)
        + counts.get("temporal-campaign").copied().unwrap_or(0);
    println!(
        "R(witness-seed-claims)={} R(rust-witness-enrollment-frontier)={} R(rust-witness-not-verdict-bearing)={} R(rust-temporal-opt-outs)={} R(rust-witness-residual-map)={} class_counts={:?}",
        counts.get("pair").copied().unwrap_or(0),
        residual_frontier,
        counts.get("not-verdict-bearing").copied().unwrap_or(0),
        counts.get("temporal-opt-out").copied().unwrap_or(0),
        residual_frontier,
        counts
    );
    assert_eq!(
        seeded, pair_names,
        "seed_witnesses must be exactly the Pair catalog claims"
    );
    assert_eq!(
        counts.values().sum::<usize>(),
        catalog.len(),
        "every catalog claim must have exactly one typed witness disposition"
    );
}

#[derive(Clone, Copy)]
struct WitnessPair {
    claim: &'static str,
    truthful: &'static str,
    lying: &'static str,
}

#[derive(Clone, Copy)]
struct PendingRouterWitnessSlot {
    router: &'static str,
    owner_slice: &'static str,
    truthful_slot: &'static str,
    lying_slot: &'static str,
}

fn pending_router_witness_slots() -> Vec<PendingRouterWitnessSlot> {
    Vec::new()
}

fn seed_witnesses() -> Vec<WitnessPair> {
    catalog_claims()
        .into_iter()
        .filter_map(|claim| match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::Pair { truthful, lying } => {
                Some(WitnessPair {
                    claim: claim.name,
                    truthful,
                    lying,
                })
            }
            _ => None,
        })
        .collect()
}
fn parse(src: &str) -> syn::File {
    syn::parse_file(src).expect("witness source parses")
}

fn warranted_facts(out: &AdapterOutput) -> Vec<&AssertionFactEmission> {
    out.assertion_facts
        .iter()
        .filter(|fact| fact.kind == AssertionFactKind::Warranted && fact.claim_count > 0)
        .collect()
}

fn single_warranted_decl(out: &AdapterOutput) -> &sugar_ir_symbolic::ContractDecl {
    let facts = warranted_facts(out);
    let decls: Vec<_> = out
        .decls
        .iter()
        .filter(|decl| {
            facts
                .iter()
                .any(|fact| fact.contract_name.as_str() == decl.name)
        })
        .collect();
    assert_eq!(
        decls.len(),
        1,
        "expected exactly one claim-bearing warranted decl; facts={:?}; decls={:?}; skips={:?}",
        out.assertion_facts,
        out.decls,
        out.skip_reasons
    );
    decls[0]
}

fn assertion_formula_json(decl: &sugar_ir_symbolic::ContractDecl) -> serde_json::Value {
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    let contract = parsed
        .get(0)
        .and_then(serde_json::Value::as_object)
        .expect("serialized ContractDecl must be a JSON object");
    for slot in ["inv", "pre", "post"] {
        if let Some(formula) = contract.get(slot).filter(|value| !value.is_null()) {
            return formula.clone();
        }
    }
    panic!("claim-bearing ContractDecl emitted no pre/post/inv formula: {doc}");
}

fn resolve_z3_from(z3_env: Option<&str>, path_env: &str) -> Result<String, String> {
    if let Some(path) = z3_env.filter(|value| !value.trim().is_empty()) {
        if Command::new(path)
            .arg("--version")
            .output()
            .map(|out| out.status.success())
            .unwrap_or(false)
        {
            return Ok(path.to_string());
        }
        return Err(format!("Z3 points at a non-executable solver: {path}"));
    }
    for dir in path_env.split(':').filter(|dir| !dir.is_empty()) {
        let candidate = std::path::Path::new(dir).join("z3");
        if candidate.is_file()
            && Command::new(&candidate)
                .arg("--version")
                .output()
                .map(|out| out.status.success())
                .unwrap_or(false)
        {
            return Ok(candidate.display().to_string());
        }
    }
    Err("sugar witness triple harness requires z3 on PATH or Z3=/path/to/z3".to_string())
}

fn z3_path_or_panic() -> String {
    let z3_env = std::env::var("Z3").ok();
    let path_env = std::env::var("PATH").unwrap_or_default();
    resolve_z3_from(z3_env.as_deref(), &path_env).unwrap_or_else(|err| panic!("{err}"))
}

fn compile_asserted_json_to_parts(
    formula: &serde_json::Value,
) -> Result<sugar_ir_compiler::CompiledFormula, sugar_ir_compiler::CompileError> {
    match sugar_ir_compiler::CompilerInput::decode_json(formula.clone())? {
        sugar_ir_compiler::CompilerInput::Formula(formula) => {
            sugar_ir_compiler_smt_lib::compile_asserted_formula_to_parts(formula.formula())
        }
        _ => Err(sugar_ir_compiler::CompileError::MalformedIr(
            "asserted SMT-LIB compile expects a formula input".to_string(),
        )),
    }
}

fn fast_smt_smoke_check(inv: &serde_json::Value, label: &str, z3: &str) -> bool {
    // Fast well-sortedness smoke only. The production verdict witness below is
    // the soundness authority because it goes through sugar mint/prove.
    let parts = compile_asserted_json_to_parts(inv).expect("witness inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let path = std::env::temp_dir().join(format!("sugar_witness_triple_{label}.smt2"));
    std::fs::write(&path, &script).expect("write witness smt2");
    let out = Command::new(z3).arg(&path).output().expect("run z3");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
        "witness relation must be well-sorted:\n{stdout}\n--- {script}"
    );
    stdout.contains("sat") && !stdout.contains("unsat")
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ProductionVerdict {
    Sat,
    Unsat,
}

#[derive(Debug, Clone)]
struct ProveRow {
    property: String,
    status: String,
}

static PRODUCTION_CLI_LOCK: Mutex<()> = Mutex::new(());

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-lift-rust-tests has a workspace parent")
        .to_path_buf()
}

fn toml_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}

fn sugar_bin_or_panic() -> PathBuf {
    let workspace = rust_workspace();
    let repo = workspace
        .parent()
        .and_then(Path::parent)
        .expect("rust workspace lives under implementations/rust");
    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    let output = Command::new(repo.join("bin/sugarbin"))
        .arg("--profile")
        .arg(profile)
        .output()
        .unwrap_or_else(|err| panic!("spawn bin/sugarbin for production sugar CLI: {err}"));
    if !output.status.success() {
        panic!(
            "crime=soundness verdict without production CLI; owner=sugar_witness_triple; \
             illegal shape=bin/sugarbin could not resolve active-profile sugar binary; \
             replacement=repair the sugarbin handoff path before this harness\n\
             status={}\nstdout:\n{}\nstderr:\n{}",
            output.status,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
    let path = String::from_utf8(output.stdout)
        .expect("sugarbin emits utf-8 path")
        .trim()
        .to_owned();
    let candidate = PathBuf::from(path);
    if candidate.is_file() {
        candidate
    } else {
        panic!(
            "crime=soundness verdict without production CLI; owner=sugar_witness_triple; \
             illegal shape=bin/sugarbin returned missing binary at {}; \
             replacement=repair the sugarbin handoff path for this test profile",
            candidate.display()
        );
    }
}

fn unique_cli_project(label: &str) -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time after epoch")
        .as_nanos();
    let safe_label = label.replace(|c: char| !c.is_ascii_alphanumeric(), "_");
    let dir = std::env::temp_dir().join(format!(
        "sugar-rust-witness-cli-{}-{stamp}-{safe_label}",
        std::process::id()
    ));
    fs::create_dir_all(&dir).expect("mkdir production witness project");
    dir
}

fn write_rust_test_assertion_project(project: &Path, sources: &[(String, &'static str)]) {
    let ws = rust_workspace();
    fs::create_dir_all(project.join("tests")).expect("mkdir tests");
    fs::create_dir_all(project.join(".sugar/lift/rust-test-assertions")).expect("mkdir lift");
    fs::create_dir_all(project.join(".sugar/components/rust-test-assertions"))
        .expect("mkdir component");
    fs::create_dir_all(project.join(".sugar/ir-compilers/smt-lib")).expect("mkdir compiler");

    for (label, src) in sources {
        fs::write(project.join("tests").join(format!("{label}.rs")), src)
            .expect("write witness source");
    }

    let lean_project = ws
        .parent()
        .and_then(Path::parent)
        .expect("rust workspace lives under implementations/rust")
        .join("tools/portfolio/lean-mathlib");
    fs::write(
        project.join(".sugar/config.toml"),
        format!(r#"[[plugins]]
name = "rust-test-assertions-lift"
kind = "lift"
surface = "rust-test-assertions"
emit = "ir-document"

[platform_profile]
language = "rust"
library = "rust-witness-cli"
version = "rustc 1.96.0"

[solvers]
mode = "first-wins"
portfolio = ["maude", "z3", "cvc5", "vampire", "coq", "lean"]

[solvers.maude]
binary = "maude"
ir_compiler = "maude"
timeout_seconds = 30
ceta_gate = true
ceta_binary = "ceta"
termination_prover = "aprove"
confluence_checker = "csi"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 30
version = "4.x"

[solvers.cvc5]
binary = "cvc5"
ir_compiler = "smt-lib-v2.6"
flags = ["--lang=smt2", "--produce-models"]
timeout_seconds = 30

[solvers.vampire]
binary = "vampire"
ir_compiler = "smt-lib-v2.6"
flags = ["--input_syntax", "smtlib2", "--output_mode", "smtcomp"]
timeout_seconds = 30

[solvers.coq]
binary = "coqc"
ir_compiler = "coq"
timeout_seconds = 60

[solvers.lean]
binary = "lake"
ir_compiler = "lean"
timeout_seconds = 60
lake_project = "{lean_project}"

[rust-test-assertions.target_cfg]
target = "x86_64-apple-darwin"
facts = ["test", "debug_assertions", "target_arch=\"x86_64\"", "target_pointer_width=\"64\"", "target_os=\"macos\"", "unix"]
"#, lean_project = lean_project.display()),
    )
    .expect("write .sugar/config.toml");

    fs::write(
        project.join(".sugar/lift/rust-test-assertions/manifest.toml"),
        format!(
            r#"name = "rust-test-assertions-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["cargo", "run", "-p", "sugar-lift-rust-tests", "--bin", "rust_test_assertions_rpc", "--quiet", "--"]
working_dir = "{ws}"

[capabilities]
authoring_surfaces = ["rust-test-assertions"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            ws = ws.display()
        ),
    )
    .expect("write lift manifest");

    let component_script = project
        .join(".sugar/components/rust-test-assertions")
        .join("component.sh");
    let initialize_response = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "name": "rust-test-assertions-component",
            "protocol_version": "sugar-component/1",
            "capabilities": {}
        }
    })
    .to_string();
    let plan_response = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "decision": "claim",
            "plugins": [{
                "name": "rust-test-assertions-lift",
                "kind": "lift",
                "surface": "rust-test-assertions",
                "emit": "ir-document"
            }],
            "lift_manifests": [{
                "surface": "rust-test-assertions",
                "name": "rust-test-assertions-lift",
                "version": "0.1.0",
                "protocol_version": "pep/1.7.0",
                "command": [
                    "cargo",
                    "run",
                    "-p",
                    "sugar-lift-rust-tests",
                    "--bin",
                    "rust_test_assertions_rpc",
                    "--quiet",
                    "--"
                ],
                "working_dir": ws.display().to_string()
            }],
            "diagnostics": [{
                "level": "info",
                "message": "rust-test-assertions component planned"
            }]
        }
    })
    .to_string();
    let shutdown_response = json!({"jsonrpc": "2.0", "id": 3, "result": null}).to_string();
    fs::write(
        &component_script,
        format!(
            r#"while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{initialize_response}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{plan_response}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{shutdown_response}'
      exit 0
      ;;
  esac
done
"#
        ),
    )
    .expect("write component script");
    fs::write(
        project.join(".sugar/components/rust-test-assertions/manifest.toml"),
        format!(
            "name = \"rust-test-assertions-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&component_script.display().to_string())
        ),
    )
    .expect("write component manifest");

    fs::write(
        project.join(".sugar/ir-compilers/smt-lib/manifest.toml"),
        format!(
            r#"name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["cargo", "run", "-p", "sugar-ir-compiler-smt-lib", "--bin", "sugar-ir-smt-lib", "--quiet", "--"]
working_dir = "{ws}"
dialects = ["smt-lib-v2.6"]
"#,
            ws = ws.display()
        ),
    )
    .expect("write compiler manifest");
}

fn mint_and_prove_project(project: &Path, z3: &str) -> Result<Vec<ProveRow>, String> {
    let _guard = PRODUCTION_CLI_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    resolve_z3_from(Some(z3), "")
        .map_err(|err| format!("production sugar prove requires executable z3: {err}"))?;
    let sugar = sugar_bin_or_panic();
    let mint = Command::new(&sugar)
        .current_dir(project)
        .arg("mint")
        .arg("--out")
        .arg(project)
        .arg("--quiet")
        .output()
        .map_err(|err| format!("spawn sugar mint: {err}"))?;
    if !mint.status.success() {
        return Err(format!(
            "sugar mint failed\nstdout:\n{}\nstderr:\n{}",
            String::from_utf8_lossy(&mint.stdout),
            String::from_utf8_lossy(&mint.stderr)
        ));
    }

    let prove = Command::new(&sugar)
        .current_dir(project)
        .arg("prove")
        .arg(".")
        .arg("--json")
        .arg("--z3")
        .arg(z3)
        .output()
        .map_err(|err| format!("spawn sugar prove: {err}"))?;
    if prove.stdout.is_empty() {
        return Err(format!(
            "sugar prove produced no JSON\nstatus={}\nstdout:\n{}\nstderr:\n{}",
            prove.status,
            String::from_utf8_lossy(&prove.stdout),
            String::from_utf8_lossy(&prove.stderr)
        ));
    }
    let stdout = String::from_utf8_lossy(&prove.stdout);
    let doc: Json = serde_json::from_str(&stdout).map_err(|err| {
        format!(
            "sugar prove returned malformed JSON: {err}\nstdout:\n{stdout}\nstderr:\n{}",
            String::from_utf8_lossy(&prove.stderr)
        )
    })?;
    Ok(doc["rows"]
        .as_array()
        .ok_or_else(|| format!("sugar prove JSON has no rows: {doc:#}"))?
        .iter()
        .map(|row| ProveRow {
            property: row["property"].as_str().unwrap_or_default().to_string(),
            status: row["status"].as_str().unwrap_or_default().to_string(),
        })
        .collect())
}

fn production_statuses_for_label(rows: &[ProveRow], label: &str) -> Result<Vec<String>, String> {
    let needle = format!("tests/{label}.rs");
    let statuses = rows
        .iter()
        .filter(|row| row.property.contains(&needle) && !row.property.contains("#panic_callsite#"))
        .map(|row| row.status.clone())
        .collect::<Vec<_>>();
    if statuses.is_empty() {
        Err(format!("production prove emitted no row for {needle}"))
    } else {
        Ok(statuses)
    }
}

fn production_direction(statuses: &[String]) -> Option<ProductionVerdict> {
    if statuses.iter().any(|status| status == "unsatisfied") {
        Some(ProductionVerdict::Unsat)
    } else if statuses.iter().all(|status| status == "discharged") {
        Some(ProductionVerdict::Sat)
    } else {
        None
    }
}

fn production_case_failure(
    rows: &[ProveRow],
    label: &str,
    expected: ProductionVerdict,
) -> Option<String> {
    let statuses = match production_statuses_for_label(rows, label) {
        Ok(statuses) => statuses,
        Err(err) => return Some(format!("{label}: expected {expected:?}; {err}")),
    };
    match expected {
        ProductionVerdict::Sat if statuses.iter().all(|status| status == "discharged") => None,
        ProductionVerdict::Sat => Some(format!(
            "{label}: truthful source must discharge through production CLI; statuses={statuses:?}"
        )),
        ProductionVerdict::Unsat if statuses.iter().any(|status| status == "discharged") => {
            Some(format!(
                "{label}: HIDDEN LIE; lying source discharged through production CLI; statuses={statuses:?}"
            ))
        }
        ProductionVerdict::Unsat => None,
    }
}

fn assert_production_cli_cases(test_name: &str, cases: &[(&str, &'static str, ProductionVerdict)]) {
    assert_production_cli_cases_with_residuals(test_name, cases, &[]);
}

fn assert_production_cli_cases_with_residuals(
    test_name: &str,
    cases: &[(&str, &'static str, ProductionVerdict)],
    expected_failures: &[&str],
) {
    let z3 = z3_path_or_panic();
    let project = unique_cli_project(test_name);
    let sources = cases
        .iter()
        .map(|(label, src, _)| ((*label).to_string(), *src))
        .collect::<Vec<_>>();
    write_rust_test_assertion_project(&project, &sources);
    let rows = mint_and_prove_project(&project, &z3).unwrap_or_else(|err| {
        panic!(
            "production sugar mint/prove must decide {test_name} witness cases\nproject={}\n{err}",
            project.display()
        )
    });
    let failures = cases
        .iter()
        .filter_map(|(label, _, expected)| production_case_failure(&rows, label, *expected))
        .collect::<Vec<_>>();
    let expected_failures = expected_failures
        .iter()
        .map(|failure| (*failure).to_string())
        .collect::<Vec<_>>();
    assert_eq!(
        failures, expected_failures,
        "{test_name}: source -> sugar CLI -> verdict residuals changed"
    );
}

fn selected_claims(out: &AdapterOutput) -> BTreeSet<&'static str> {
    out.factory_audits
        .iter()
        .filter_map(|audit| audit.selected)
        .collect()
}

fn assert_witness_dispatches_to_owner(claim: &str, out: &AdapterOutput) -> Result<(), String> {
    let selected = selected_claims(out);
    if selected.contains(claim) {
        Ok(())
    } else {
        Err(format!(
            "witness expected claim `{claim}` but selected {:?}",
            selected
        ))
    }
}

#[test]
fn z3_absence_is_a_loud_harness_error() {
    let err = resolve_z3_from(None, "").expect_err("empty PATH must not silently skip z3");
    assert!(
        err.contains("requires z3"),
        "z3 absence must be a loud harness error, got {err:?}"
    );
}

#[test]
fn fast_smt_smoke_is_not_a_witness_verdict_authority() {
    let source = include_str!("sugar_witness_triple.rs");
    let old_helper_name = ["fast_smt_smoke", "_verdict"].concat();
    assert!(
        !source.contains(&old_helper_name),
        "fast SMT helper name must not say verdict; it is a smoke check, not soundness authority"
    );
    let expected_token = ["expected", "_sat"].concat();
    let got_token = ["got", "_sat"].concat();
    let forbidden = source
        .lines()
        .enumerate()
        .filter(|(_, line)| line.contains(&expected_token) || line.contains(&got_token))
        .map(|(idx, line)| format!("{}: {}", idx + 1, line.trim()))
        .collect::<Vec<_>>();
    assert!(
        forbidden.is_empty(),
        "witness verdicts must come from source -> sugar CLI -> production verdict, not fast SMT smoke: {forbidden:#?}"
    );
}

#[test]
fn phase2_question_mark_ok_path_has_solver_bad_twin() {
    let truthful = r#"
        #[test]
        fn t_question_mark_ok_good() -> Result<(), i32> {
            let x = Ok::<i32, i32>(7)?;
            assert_eq!(x, 7);
            Ok(())
        }
    "#;
    let lying = r#"
        #[test]
        fn t_question_mark_ok_bad() -> Result<(), i32> {
            let x = Ok::<i32, i32>(7)?;
            assert_eq!(x, 8);
            Ok(())
        }
    "#;
    assert_production_cli_cases_with_residuals(
        "phase2-question-mark-ok",
        &[
            (
                "phase2_question_mark_ok_good",
                truthful,
                ProductionVerdict::Sat,
            ),
            (
                "phase2_question_mark_ok_bad",
                lying,
                ProductionVerdict::Unsat,
            ),
        ],
        &["phase2_question_mark_ok_good: truthful source must discharge through production CLI; statuses=[\"refused\"]"],
    );
}

#[test]
fn phase2_question_mark_err_path_remains_uncaught_boundary() {
    let src = r#"
        #[test]
        fn t_question_mark_err_uncaught() -> Result<(), i32> {
            let x = Err::<i32, i32>(9)?;
            assert_eq!(x, 7);
            Ok(())
        }
    "#;
    let out = lift_file(
        &parse(src),
        "sugar-witness/phase2_question_mark_err_uncaught.rs",
    );
    assert!(
        warranted_facts(&out).is_empty(),
        "uncaught Err(_)? must not fabricate a warranted assertion; facts={:?}",
        out.assertion_facts
    );
    let rendered = format!("{:?} {:?}", out.assertion_facts, out.skip_reasons);
    assert!(
        rendered.contains("result error raise effect") || rendered.contains("ResultErr"),
        "uncaught Err(_)? should surface the typed ResultErr boundary, got {rendered}"
    );
}

#[test]
fn s6_result_and_then_composes_with_phase2_question_mark_router() {
    let truthful = r#"
        #[test]
        fn t_result_and_then_question_mark_good() -> Result<(), i32> {
            let x = Ok::<i32, i32>(2).and_then(|v| Ok(v + 3))?;
            assert_eq!(x, 5);
            Ok(())
        }
    "#;
    let lying = r#"
        #[test]
        fn t_result_and_then_question_mark_bad() -> Result<(), i32> {
            let x = Ok::<i32, i32>(2).and_then(|v| Ok(v + 3))?;
            assert_eq!(x, 6);
            Ok(())
        }
    "#;
    for (label, src) in [
        ("s6_result_and_then_question_mark_good", truthful),
        ("s6_result_and_then_question_mark_bad", lying),
    ] {
        let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
        assert_witness_dispatches_to_owner("result_and_then", &out)
            .unwrap_or_else(|err| panic!("{label}: {err}; skips={:?}", out.skip_reasons));
    }
    assert_production_cli_cases_with_residuals(
        "s6-result-and-then-question-mark",
        &[
            (
                "s6_result_and_then_question_mark_good",
                truthful,
                ProductionVerdict::Sat,
            ),
            (
                "s6_result_and_then_question_mark_bad",
                lying,
                ProductionVerdict::Unsat,
            ),
        ],
        &["s6_result_and_then_question_mark_good: truthful source must discharge through production CLI; statuses=[\"refused\"]"],
    );
}

#[test]
fn phase2_early_return_branch_has_solver_bad_twin() {
    let prefix = r#"
        fn pick(flag: bool) -> i32 {
            if flag {
                return 5;
            }
            7
        }
    "#;
    let truthful = Box::leak(
        format!(
            "{prefix}\n#[test]\nfn phase2_early_return_good() {{ assert_eq!(pick(true), 5); }}\n"
        )
        .into_boxed_str(),
    );
    let lying = Box::leak(
        format!(
            "{prefix}\n#[test]\nfn phase2_early_return_bad() {{ assert_eq!(pick(true), 6); }}\n"
        )
        .into_boxed_str(),
    );
    assert_production_cli_cases(
        "phase2-early-return",
        &[
            ("phase2_early_return_good", truthful, ProductionVerdict::Sat),
            ("phase2_early_return_bad", lying, ProductionVerdict::Unsat),
        ],
    );
}

fn run_rust_test_source(claim: &str, kind: &str, src: &str) -> bool {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time after epoch")
        .as_nanos();
    let safe_claim = claim.replace(|c: char| !c.is_ascii_alphanumeric(), "_");
    let stem = format!(
        "sugar_witness_ground_truth_{}_{}_{}_{}",
        std::process::id(),
        nonce,
        safe_claim,
        kind
    );
    let source_path = std::env::temp_dir().join(format!("{stem}.rs"));
    let binary_path = std::env::temp_dir().join(stem);
    std::fs::write(&source_path, src).expect("write ground-truth Rust source");
    let compile = Command::new("rustc")
        .args(["--edition=2021", "--test"])
        .arg(&source_path)
        .arg("-o")
        .arg(&binary_path)
        .output()
        .expect("run rustc for ground-truth witness");
    assert!(
        compile.status.success(),
        "ground-truth Rust witness {claim}/{kind} must compile:\nstdout={}\nstderr={}",
        String::from_utf8_lossy(&compile.stdout),
        String::from_utf8_lossy(&compile.stderr)
    );
    let run = Command::new(&binary_path)
        .output()
        .expect("run ground-truth Rust test binary");
    let _ = std::fs::remove_file(&source_path);
    let _ = std::fs::remove_file(&binary_path);
    run.status.success()
}

#[test]
fn phase2_guarded_panic_branch_has_solver_bad_twin() {
    let prefix = r#"
        fn guarded(flag: bool) -> i32 {
            if flag {
                panic!()
            }
            7
        }
    "#;
    let truthful = Box::leak(
        format!(
            "{prefix}\n#[test]\nfn phase2_guarded_panic_good() {{ assert_eq!(guarded(false), 7); }}\n"
        )
        .into_boxed_str(),
    );
    let lying = Box::leak(
        format!(
            "{prefix}\n#[test]\nfn phase2_guarded_panic_bad() {{ assert_eq!(guarded(false), 8); }}\n"
        )
        .into_boxed_str(),
    );
    assert_production_cli_cases(
        "phase2-guarded-panic",
        &[
            (
                "phase2_guarded_panic_good",
                truthful,
                ProductionVerdict::Sat,
            ),
            ("phase2_guarded_panic_bad", lying, ProductionVerdict::Unsat),
        ],
    );
}

#[test]
fn phase2_uncaught_panic_remains_residual_refusal() {
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn explode() -> i32 {
            panic!()
        }
    "#,
    )
    .expect("uncaught panic source parses");
    let decl = emit_value_contract("explode", &function.block);
    assert!(
        decl.is_none(),
        "a bare panic has no normal return formula to fabricate: {decl:?}"
    );
}

#[test]
fn phase2_noop_drop_does_not_perturb_assertion_emission() {
    let without_drop = lift_file(
        &parse(
            r#"
            #[test]
            fn t_noop_drop_without() {
                assert_eq!(1 + 1, 2);
            }
        "#,
        ),
        "sugar-witness/phase2_noop_drop_without.rs",
    );
    let with_drop = lift_file(
        &parse(
            r#"
            struct NoopDrop;

            impl Drop for NoopDrop {
                fn drop(&mut self) {}
            }

            #[test]
            fn t_noop_drop_with() {
                let _guard = NoopDrop;
                assert_eq!(1 + 1, 2);
            }
        "#,
        ),
        "sugar-witness/phase2_noop_drop_with.rs",
    );

    assert_eq!(
        assertion_formula_json(single_warranted_decl(&with_drop)),
        assertion_formula_json(single_warranted_decl(&without_drop)),
        "a no-op Drop must not perturb the emitted assertion invariant; with_drop facts={:?}; skips={:?}",
        with_drop.assertion_facts,
        with_drop.skip_reasons
    );
}

const S7_SEED_PAIR_CLAIMS: &[&str] = &[
    "assertion_surface_aggregate_decomp",
    "assertion_surface_tuple_decomp",
    "bool_literal_method",
    "char_literal_method",
    "const_if",
    "duration_accessor",
    "from_bool",
    "int_midpoint",
    "len",
    "match_value_term",
    "monadic",
    "primitive_int",
    "range_contains",
];

const CORRECTED_S8_PAIR_CLAIMS: &[&str] = &["const_item", "fold", "map", "return_sugar"];

const S9_BATCH1_PAIR_CLAIMS: &[&str] = &[
    "term_literal",
    "const_block",
    "const",
    "binop",
    "bv_binop",
    "constraint_bool_bitwise",
    "unary",
    "wrapping_neg",
    "int_pow",
    "int_sqrt",
    "cast_term",
    "option_predicate",
    "result_predicate",
    "option_unwrap",
    "is_empty",
    "is_sorted",
    "str_method",
    "to_string",
    "constraint_string_predicate",
    "constraint_char_literal_method",
    "slice_accessor",
    "slice_search",
    "range_accessor",
    "range_term",
    "sizeof",
    "offset_of",
    "duration_value",
    "into",
    "nonzero_new",
    "nonzero_assoc_const",
    "nonzero_get",
    "float_literal_method",
];

const S9_BATCH2_PAIR_CLAIMS: &[&str] = &[
    "concat_macro",
    "assertion_surface_relation_macro",
    "assertion_surface_bounded_literal_macro",
    "macro_assertion_surface",
    "assertion_surface_assert_macro",
    "constraint_bool_expr",
    "constraint_tuple_decomp",
    "string_add",
    "index",
    "maybe_uninit_new",
    "maybe_uninit_zeroed",
    "mem_zeroed",
    "try_from",
    "constraint_literal_ip_addr_property",
    "dyn_any",
    "cstr",
    "array_try_from",
    "literal_tuple_producer",
    "array_repeat",
    "field_term",
    "format_macro",
    "block_term",
    "partition_point",
    "option_adaptor",
    "transparent_term",
    "value_if",
    "cell_refcell",
    "literal",
    "const_composite",
    "primitive_int_tuple_producer",
    "slice_search_assertion_surface",
    // Family (d) float semantics DRAINED (#3415): floor-value refinement axioms.
    "constraint_float_refinement",
    "assertion_surface_infinity_eq",
];

// #3415 family e S10 straggler (catch #34): `INFINITY`/`NEG_INFINITY` distinct-floor
// identity refutes the equality lie via the SMT `float_floor_axiom_preamble`.
const S10_FAMILY_E_PAIR_CLAIMS: &[&str] = &["constraint_infinity_eq"];

const S9_BATCH3_PAIR_CLAIMS: &[&str] = &[
    "cfg_select_assertion_surface",
    "integer_decode_tuple_producer",
    "memchr",
    "macro_term",
    "constraint_matches_macro",
    "control_flow_term",
    "conditional",
    "match_node",
    "constraint_closed_match",
    "constraint_regex_match",
    "constraint_no_panic_call",
    "size_hint_tuple_producer",
];

const S9_BATCH4_PAIR_CLAIMS: &[&str] = &[
    "bound_constraint",
    "bound_path_tuple_producer",
    "reference_term",
    "literal_slice",
    "loop_break_term",
];

const S9_BATCH5_PAIR_CLAIMS: &[&str] = &["literal_ip_addr", "str_table_select"];

const S5_ADAPTER_PAIR_CLAIMS: &[&str] = &[
    "filter",
    "filter_map",
    "take",
    "take_while",
    "skip",
    "skip_while",
    "chain",
    "zip",
    "enumerate",
    "inspect",
];

const S6_OPTION_RESULT_PAIR_CLAIMS: &[&str] = &[
    "option_map",
    "option_and_then",
    "option_or_else",
    "option_filter",
    "option_unwrap_or",
    "option_ok_or",
    "result_map",
    "result_map_err",
    "result_and_then",
    "result_or_else",
    "result_ok",
    "result_err",
];

// +3 (#3415 family e enrollment): the three float-floor truthful witnesses join the
// production truthful-residual frontier (like most rows, they don't cleanly discharge
// through the CLI's multi-row support universe); their lying twins stay non-green.
const EXPECTED_PRODUCTION_TRUTHFUL_RESIDUALS: usize = 122;
const EXPECTED_PRODUCTION_HIDDEN_LIES: usize = 0;
const EXPECTED_PRODUCTION_LYING_NO_ROW_RESIDUALS: usize = 3;
const EXPECTED_PRODUCTION_ACTIVE_DISAGREEMENTS: usize = 0;
// +6 (#3415 family e enrollment): 3 truthful residuals + 3 non-green lying coverage rows.
const EXPECTED_PRODUCTION_COVERAGE_GAPS: usize = 244;
const EXPECTED_PRODUCTION_DISCHARGED_TRUTHS: &[&str] = &["map_truthful", "return_sugar_truthful"];
const EXPECTED_WITNESS_SMOKE_PRODUCTION_DIRECTIONAL_AGREEMENTS: usize = 2;
const EXPECTED_WITNESS_SMOKE_PRODUCTION_DISAGREEMENTS: usize = 0;
// +6 (#3415 family e enrollment): the three new float-floor pairs' six directions.
const EXPECTED_WITNESS_PRODUCTION_DIRECTION_UNAVAILABLE: usize = 242;
const EXPECTED_WITNESS_SMOKE_UNAVAILABLE: usize = 4;

fn standing_ground_truth_gate_claims() -> BTreeSet<&'static str> {
    [
        S7_SEED_PAIR_CLAIMS,
        CORRECTED_S8_PAIR_CLAIMS,
        S9_BATCH1_PAIR_CLAIMS,
        S9_BATCH2_PAIR_CLAIMS,
        S9_BATCH3_PAIR_CLAIMS,
        S9_BATCH4_PAIR_CLAIMS,
        S9_BATCH5_PAIR_CLAIMS,
        S10_FAMILY_E_PAIR_CLAIMS,
        S5_ADAPTER_PAIR_CLAIMS,
        S6_OPTION_RESULT_PAIR_CLAIMS,
    ]
    .into_iter()
    .flat_map(|claims| claims.iter().copied())
    .collect()
}

fn assert_pairs_match_real_rust_semantics(claims: &[&str]) {
    let witnesses = seed_witnesses();
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == *claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn phase2_router_witness_bad_twin_registry_is_armed_at_zero() {
    let slots = pending_router_witness_slots();
    let names = slots
        .iter()
        .map(|slot| slot.router)
        .collect::<BTreeSet<_>>();
    assert_eq!(
        names.len(),
        slots.len(),
        "router witness slots must be uniquely named"
    );
    for slot in &slots {
        assert!(
            !slot.truthful_slot.trim().is_empty() && !slot.lying_slot.trim().is_empty(),
            "router {} must reserve both truthful and lying bad-twin slots",
            slot.router
        );
    }
    println!(
        "R(routers-without-witness-bad-twin)={} pending={:?}",
        slots.len(),
        slots
            .iter()
            .map(|slot| format!("{}:{}", slot.owner_slice, slot.router))
            .collect::<Vec<_>>()
    );
    assert!(
        slots.is_empty(),
        "Phase 2 router witness registry is armed at stable zero; new pending slot(s) must land with truthful+lying bad twins: {:?}",
        slots
            .iter()
            .map(|slot| format!("{}:{}", slot.owner_slice, slot.router))
            .collect::<Vec<_>>()
    );
}

#[test]
fn every_pair_claim_has_a_standing_ground_truth_gate() {
    let pairs = seed_witnesses()
        .into_iter()
        .map(|witness| witness.claim)
        .collect::<BTreeSet<_>>();
    let gated = standing_ground_truth_gate_claims();
    let pair_without_gate = pairs.difference(&gated).copied().collect::<Vec<_>>();
    let gate_without_pair = gated.difference(&pairs).copied().collect::<Vec<_>>();
    println!(
        "R(pair-without-standing-gate)={} R(standing-gate-without-pair)={}",
        pair_without_gate.len(),
        gate_without_pair.len()
    );
    assert!(
        pair_without_gate.is_empty(),
        "Pair enrollment must join a standing ground-truth gate; missing gate rows: {pair_without_gate:?}"
    );
    assert!(
        gate_without_pair.is_empty(),
        "Standing ground-truth gates must name only Pair claims; stale gate rows: {gate_without_pair:?}"
    );
}

#[test]
fn s7_temporal_successors_are_named() {
    let catalog = catalog_claims();
    let claim = catalog
        .iter()
        .find(|claim| claim.name == "constraint_literal_iterator_quantifier")
        .expect("finite literal iterator quantifier claim remains cataloged");
    match claim.witnesses {
        sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalCampaign { slice } => {
            println!(
                "S7 successor: constraint_literal_iterator_quantifier remains temporal-campaign row: {slice}"
            );
            assert!(
                slice.contains("#3415") && slice.contains("successor"),
                "S7 close must name family-j's successor owner in the temporal-campaign row: {slice}"
            );
        }
        _ => panic!(
            "constraint_literal_iterator_quantifier must not enroll as Pair until family-j lying SAT drains"
        ),
    }
}

#[test]
fn seed_witnesses_satisfy_the_triple() {
    let z3 = z3_path_or_panic();
    let cases = seed_witnesses()
        .into_iter()
        .flat_map(|witness| {
            [
                (
                    format!("{}_truthful", witness.claim),
                    witness.truthful,
                    ProductionVerdict::Sat,
                ),
                (
                    format!("{}_lying", witness.claim),
                    witness.lying,
                    ProductionVerdict::Unsat,
                ),
            ]
        })
        .collect::<Vec<_>>();
    let sources = cases
        .iter()
        .map(|(label, src, _)| (label.clone(), *src))
        .collect::<Vec<_>>();
    let project = unique_cli_project("seed-witnesses");
    write_rust_test_assertion_project(&project, &sources);
    let rows = mint_and_prove_project(&project, &z3).unwrap_or_else(|err| {
        panic!(
            "production sugar mint/prove must produce witness verdicts for seed catalog\nproject={}\n{err}",
            project.display()
        )
    });

    let mut discharged_truths = Vec::new();
    let mut truthful_residuals = Vec::new();
    let mut hidden_lies = Vec::new();
    let mut lying_no_rows = Vec::new();
    let mut coverage_gaps = Vec::new();
    let mut non_green_lies = 0usize;
    for (label, _, expected) in &cases {
        match (*expected, production_statuses_for_label(&rows, label)) {
            (ProductionVerdict::Sat, Ok(statuses))
                if statuses.iter().all(|status| status == "discharged") =>
            {
                discharged_truths.push(label.clone());
            }
            (ProductionVerdict::Sat, Ok(statuses)) => {
                let residual = format!(
                    "{label}: truthful source must discharge through production CLI; statuses={statuses:?}"
                );
                truthful_residuals.push(residual.clone());
                coverage_gaps.push(residual);
            }
            (ProductionVerdict::Sat, Err(err)) => {
                let residual = format!("{label}: truthful source produced no verdict; {err}");
                truthful_residuals.push(residual.clone());
                coverage_gaps.push(residual);
            }
            (ProductionVerdict::Unsat, Ok(statuses))
                if statuses.iter().any(|status| status == "discharged") =>
            {
                hidden_lies.push(format!(
                    "{label}: lying source discharged through production CLI; statuses={statuses:?}"
                ));
            }
            (ProductionVerdict::Unsat, Ok(statuses))
                if statuses.iter().any(|status| status == "unsatisfied") =>
            {
                non_green_lies += 1;
            }
            (ProductionVerdict::Unsat, Ok(_)) => {
                non_green_lies += 1;
                coverage_gaps.push(format!(
                    "{label}: lying source produced no contradicting verdict"
                ));
            }
            (ProductionVerdict::Unsat, Err(err)) => {
                let residual = format!("{label}: lying source produced no verdict; {err}");
                lying_no_rows.push(residual.clone());
                coverage_gaps.push(residual);
            }
        }
    }
    discharged_truths.sort();
    println!(
        "R(rust-witness-production-active-disagreements)={} R(rust-witness-production-coverage-gaps)={} R(rust-witness-production-truthful-residuals)={} R(rust-witness-production-hidden-lies)={} R(rust-witness-production-lying-no-row-residuals)={} authority=source-to-sugar-cli rows={} discharged_truths={discharged_truths:?} non_green_lies={non_green_lies}",
        hidden_lies.len(),
        coverage_gaps.len(),
        truthful_residuals.len(),
        hidden_lies.len(),
        lying_no_rows.len(),
        rows.len()
    );
    assert_eq!(
        hidden_lies.len(),
        EXPECTED_PRODUCTION_ACTIVE_DISAGREEMENTS,
        "production CLI active-disagreement frontier changed; each row is a soundness finding:\n{hidden_lies:#?}"
    );
    assert_eq!(
        coverage_gaps.len(),
        EXPECTED_PRODUCTION_COVERAGE_GAPS,
        "production CLI coverage-gap frontier changed; classify every new/resolved gap before repinning:\n{coverage_gaps:#?}"
    );
    assert_eq!(
        truthful_residuals.len(),
        EXPECTED_PRODUCTION_TRUTHFUL_RESIDUALS,
        "production CLI truthful frontier changed; every truthful residual is a coverage gap to investigate:\n{truthful_residuals:#?}"
    );
    assert_eq!(
        hidden_lies.len(),
        EXPECTED_PRODUCTION_HIDDEN_LIES,
        "production CLI discharged lying witnesses; these are hidden lies:\n{hidden_lies:#?}"
    );
    assert_eq!(
        lying_no_rows.len(),
        EXPECTED_PRODUCTION_LYING_NO_ROW_RESIDUALS,
        "production CLI produced no row for lying witnesses; distinguish from refused/undecidable non-green:\n{lying_no_rows:#?}"
    );
    let expected_passes = EXPECTED_PRODUCTION_DISCHARGED_TRUTHS
        .iter()
        .map(|label| (*label).to_string())
        .collect::<Vec<_>>();
    assert_eq!(
        discharged_truths, expected_passes,
        "production-backed truthful witness set changed; review each new discharge/residual as a real drain before repinning"
    );
}

#[test]
fn production_cli_verdict_fails_loudly_when_z3_is_absent() {
    let witness = seed_witnesses()
        .into_iter()
        .find(|witness| witness.claim == "map")
        .expect("map witness exists");
    let label = "map_truthful".to_string();
    let project = unique_cli_project("z3-absent");
    write_rust_test_assertion_project(&project, &[(label, witness.truthful)]);
    let err = mint_and_prove_project(&project, "/definitely/not/z3")
        .expect_err("production CLI verdict must not pass when z3 is absent");
    println!("production CLI z3 absence refusal: {err}");
    assert!(
        err.contains("sugar prove")
            || err.contains("solver")
            || err.contains("/definitely/not/z3")
            || err.contains("z3"),
        "missing-z3 failure should name the production solver path, got:\n{err}"
    );
}

#[test]
fn seed_witnesses_compare_fast_smt_smoke_to_production_cli() {
    let z3 = z3_path_or_panic();
    let witnesses = seed_witnesses();
    let cli_cases = witnesses
        .iter()
        .flat_map(|witness| {
            [
                (format!("{}_truthful", witness.claim), witness.truthful),
                (format!("{}_lying", witness.claim), witness.lying),
            ]
        })
        .collect::<Vec<_>>();
    let project = unique_cli_project("seed-witness-differential");
    write_rust_test_assertion_project(&project, &cli_cases);
    let rows = mint_and_prove_project(&project, &z3).unwrap_or_else(|err| {
        panic!(
            "production sugar mint/prove must produce differential verdicts for seed catalog\nproject={}\n{err}",
            project.display()
        )
    });

    let mut owner_mismatches = Vec::new();
    let mut smoke_unavailable = Vec::new();
    let mut production_direction_unavailable = Vec::new();
    let mut disagreements = Vec::new();
    let mut directional_agreements = 0usize;
    let mut smoke_rows = 0usize;
    for witness in witnesses {
        if witness.claim == "return_sugar" {
            // This smoke path checks assertion-formula well-sortedness only.
            // ReturnSugar's source witness is a value-contract route; its
            // production verdict is covered by the CLI authority above. The
            // old in-process value-contract conjoin is not a verdict
            // authority, so this row is explicitly smoke-unavailable.
            smoke_unavailable.push("return_sugar_truthful: value-contract route".to_string());
            smoke_unavailable.push("return_sugar_lying: value-contract route".to_string());
            continue;
        }
        if witness.claim == "macro_assertion_surface" {
            // The wrapper macro route is source-to-source dispatch. Production owns
            // the verdict through the expanded assertion relation, so the in-process
            // smoke owner check must not require the wrapper claim itself.
            smoke_unavailable
                .push("macro_assertion_surface_truthful: expanded assertion route".to_string());
            smoke_unavailable
                .push("macro_assertion_surface_lying: expanded assertion route".to_string());
            continue;
        }
        for (kind, src) in [("truthful", witness.truthful), ("lying", witness.lying)] {
            let label = format!("{}_{}", witness.claim, kind);
            let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
            if let Err(err) = assert_witness_dispatches_to_owner(witness.claim, &out) {
                owner_mismatches.push(format!("{label}: {err}"));
                continue;
            }
            let decl = single_warranted_decl(&out);
            let smoke_direction =
                if fast_smt_smoke_check(&assertion_formula_json(decl), &label, &z3) {
                    ProductionVerdict::Sat
                } else {
                    ProductionVerdict::Unsat
                };
            smoke_rows += 1;
            match production_statuses_for_label(&rows, &label) {
                Ok(statuses) => match production_direction(&statuses) {
                    Some(authority_direction) if authority_direction == smoke_direction => {
                        directional_agreements += 1;
                    }
                    Some(authority_direction) => disagreements.push(format!(
                        "{label}: smoke={smoke_direction:?} production={authority_direction:?} statuses={statuses:?}"
                    )),
                    None => production_direction_unavailable.push(format!(
                        "{label}: smoke={smoke_direction:?} production_statuses={statuses:?}"
                    )),
                },
                Err(err) => production_direction_unavailable
                    .push(format!("{label}: smoke={smoke_direction:?}; {err}")),
            }
        }
    }
    println!(
        "R(witness-fast-smt-smoke-owner-mismatches)={} R(witness-smoke-unavailable)={} R(witness-smoke-production-direction-unavailable)={} R(witness-smoke-production-disagreements)={} smoke_rows={smoke_rows} directional_agreements={directional_agreements} authority=source-to-sugar-cli",
        owner_mismatches.len(),
        smoke_unavailable.len(),
        production_direction_unavailable.len(),
        disagreements.len()
    );
    assert!(owner_mismatches.is_empty(), "{owner_mismatches:#?}");
    assert_eq!(
        smoke_unavailable.len(),
        EXPECTED_WITNESS_SMOKE_UNAVAILABLE,
        "smoke-unavailable witness rows changed; each needs a named source-to-smoke bridge or explicit retirement:\n{smoke_unavailable:#?}"
    );
    assert_eq!(
        production_direction_unavailable.len(),
        EXPECTED_WITNESS_PRODUCTION_DIRECTION_UNAVAILABLE,
        "production CLI gave no SAT/UNSAT direction for these smoke-checked rows; classify as coverage gaps or drains:\n{production_direction_unavailable:#?}"
    );
    assert_eq!(
        disagreements.len(),
        EXPECTED_WITNESS_SMOKE_PRODUCTION_DISAGREEMENTS,
        "fast smoke and production CLI disagree on directional verdicts; these are active shadow-pipeline findings:\n{disagreements:#?}"
    );
    assert_eq!(
        directional_agreements, EXPECTED_WITNESS_SMOKE_PRODUCTION_DIRECTIONAL_AGREEMENTS,
        "directional agreement count changed; inspect every newly directional row before repinning"
    );
}

#[test]
fn corrected_s8_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(CORRECTED_S8_PAIR_CLAIMS);
}

#[test]
fn s9_batch1_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S9_BATCH1_PAIR_CLAIMS);
}

#[test]
fn s9_batch2_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S9_BATCH2_PAIR_CLAIMS);
}

#[test]
fn s9_batch3_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S9_BATCH3_PAIR_CLAIMS);
}

#[test]
fn s9_batch4_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S9_BATCH4_PAIR_CLAIMS);
}

#[test]
fn s9_batch5_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S9_BATCH5_PAIR_CLAIMS);
}

#[test]
fn s10_family_e_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S10_FAMILY_E_PAIR_CLAIMS);
}

#[test]
fn s5_adapter_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S5_ADAPTER_PAIR_CLAIMS);
}

#[test]
fn s6_option_result_pairs_match_real_rust_semantics() {
    assert_pairs_match_real_rust_semantics(S6_OPTION_RESULT_PAIR_CLAIMS);
}

#[test]
fn assertion_one_names_owner_mismatch() {
    let witness = seed_witnesses()
        .into_iter()
        .find(|pair| pair.claim == "from_bool")
        .expect("from_bool seed exists");
    let out = lift_file(
        &parse(witness.truthful),
        "sugar-witness/misattributed_from_bool.rs",
    );
    let err = assert_witness_dispatches_to_owner("duration_accessor", &out)
        .expect_err("wrong owner must be named as an assertion-1 mismatch");
    assert!(
        err.contains("duration_accessor") && err.contains("from_bool"),
        "mismatch should name expected and selected claims, got {err}"
    );
}
