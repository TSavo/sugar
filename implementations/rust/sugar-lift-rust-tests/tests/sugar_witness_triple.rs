use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::rc::Rc;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value as Json};
use sugar_ir_symbolic::{num, ConstValue, Sort, Term};
use sugar_lift_rust_tests::sugar::catalog::catalog_claims;
use sugar_lift_rust_tests::{
    emit_value_contract, lift_file, warrant_conjoined_with_vendor_terms, AdapterOutput,
    AssertionFactEmission, AssertionFactKind,
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

fn fast_smt_smoke_verdict(inv: &serde_json::Value, label: &str, z3: &str) -> bool {
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
    for candidate in [
        workspace.join("target/debug/sugar"),
        workspace.join("target/release/sugar"),
    ] {
        if candidate.is_file() {
            return candidate;
        }
    }
    panic!(
        "crime=soundness verdict without production CLI; owner=sugar_witness_triple; \
         illegal shape=no target/{{debug,release}}/sugar binary; replacement=run `cargo build -p sugar-cli` before this harness"
    );
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

    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
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
portfolio = ["z3"]

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 30
version = "4.x"

[rust-test-assertions.target_cfg]
target = "x86_64-apple-darwin"
facts = ["test", "debug_assertions", "target_arch=\"x86_64\"", "target_pointer_width=\"64\"", "target_os=\"macos\"", "unix"]
"#,
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

fn production_verdict_for_label(
    rows: &[ProveRow],
    label: &str,
) -> Result<ProductionVerdict, String> {
    let needle = format!("tests/{label}.rs");
    let statuses = rows
        .iter()
        .filter(|row| row.property.contains(&needle) && !row.property.contains("#panic_callsite#"))
        .map(|row| row.status.as_str())
        .collect::<Vec<_>>();
    if statuses.is_empty() {
        return Err(format!("production prove emitted no row for {needle}"));
    }
    if statuses.iter().any(|status| *status == "unsatisfied") {
        Ok(ProductionVerdict::Unsat)
    } else if statuses.iter().all(|status| *status == "discharged") {
        Ok(ProductionVerdict::Sat)
    } else {
        Err(format!(
            "production prove emitted no SAT/UNSAT verdict for {needle}; statuses={statuses:?}"
        ))
    }
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
fn phase2_question_mark_ok_path_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
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
    let mut verdict_receipt = Vec::new();

    for (label, src, expected_sat) in [
        ("phase2_question_mark_ok_good", truthful, true),
        ("phase2_question_mark_ok_bad", lying, false),
    ] {
        let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
        let decl = single_warranted_decl(&out);
        let got_sat = fast_smt_smoke_verdict(&assertion_formula_json(decl), label, &z3);
        verdict_receipt.push(format!("{label}={}", if got_sat { "SAT" } else { "UNSAT" }));
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; skips={:?}",
            out.skip_reasons
        );
    }
    println!(
        "phase2 TrySugar acceptance via lift_file -> assertion_formula_json -> fast_smt_smoke_verdict: {}",
        verdict_receipt.join(", ")
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
    let z3 = z3_path_or_panic();
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
    let mut verdict_receipt = Vec::new();

    for (label, src, expected_sat) in [
        ("s6_result_and_then_question_mark_good", truthful, true),
        ("s6_result_and_then_question_mark_bad", lying, false),
    ] {
        let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
        assert_witness_dispatches_to_owner("result_and_then", &out)
            .unwrap_or_else(|err| panic!("{label}: {err}; skips={:?}", out.skip_reasons));
        let decl = single_warranted_decl(&out);
        let got_sat = fast_smt_smoke_verdict(&assertion_formula_json(decl), label, &z3);
        verdict_receipt.push(format!("{label}={}", if got_sat { "SAT" } else { "UNSAT" }));
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; skips={:?}",
            out.skip_reasons
        );
    }
    println!(
        "s6 Result::and_then floor composes into Phase 2 ? router: {}",
        verdict_receipt.join(", ")
    );
}

#[test]
fn phase2_early_return_branch_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn pick(flag: bool) -> i32 {
            if flag {
                return 5;
            }
            7
        }
    "#,
    )
    .expect("early-return source parses");
    let decl = emit_value_contract("pick", &function.block)
        .expect("early-return source contract emits through the route spine");
    let flag_true = bool_term(true);

    for (label, expected_out, expected_sat) in [
        ("phase2_early_return_good", 5, true),
        ("phase2_early_return_bad", 6, false),
    ] {
        let conjoined = warrant_conjoined_with_vendor_terms(
            &decl,
            &[("flag", Rc::clone(&flag_true))],
            num(expected_out),
        );
        let got_sat = fast_smt_smoke_verdict(&assertion_formula_json(&conjoined), label, &z3);
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; decl={conjoined:?}"
        );
    }
}

fn return_sugar_value_contract_verdict(
    src: &str,
    expected_out: i128,
    label: &str,
    z3: &str,
) -> bool {
    let parsed = parse(src);
    let function = parsed
        .items
        .iter()
        .find_map(|item| match item {
            syn::Item::Fn(function) if function.sig.ident == "pick" => Some(function),
            _ => None,
        })
        .expect("return_sugar witness must define pick");
    let decl = emit_value_contract("pick", &function.block)
        .expect("return_sugar witness must emit through the value-contract route spine");
    let conjoined =
        warrant_conjoined_with_vendor_terms(&decl, &[("flag", bool_term(true))], num(expected_out));
    fast_smt_smoke_verdict(&assertion_formula_json(&conjoined), label, z3)
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
    let z3 = z3_path_or_panic();
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn guarded(flag: bool) -> i32 {
            if flag {
                panic!()
            }
            7
        }
    "#,
    )
    .expect("guarded panic source parses");
    let decl = emit_value_contract("guarded", &function.block)
        .expect("guarded panic source contract emits through the route spine");
    let flag_false = bool_term(false);

    for (label, expected_out, expected_sat) in [
        ("phase2_guarded_panic_good", 7, true),
        ("phase2_guarded_panic_bad", 8, false),
    ] {
        let conjoined = warrant_conjoined_with_vendor_terms(
            &decl,
            &[("flag", Rc::clone(&flag_false))],
            num(expected_out),
        );
        let got_sat = fast_smt_smoke_verdict(&assertion_formula_json(&conjoined), label, &z3);
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; decl={conjoined:?}"
        );
    }
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

fn bool_term(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: Sort::bool(),
    })
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
];

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

const EXPECTED_PRODUCTION_VERDICT_RESIDUALS: usize = 238;
const EXPECTED_PRODUCTION_VERDICT_PASSES: &[&str] = &[
    "map_lying",
    "map_truthful",
    "return_sugar_lying",
    "return_sugar_truthful",
];

fn standing_ground_truth_gate_claims() -> BTreeSet<&'static str> {
    [
        S7_SEED_PAIR_CLAIMS,
        CORRECTED_S8_PAIR_CLAIMS,
        S9_BATCH1_PAIR_CLAIMS,
        S9_BATCH2_PAIR_CLAIMS,
        S9_BATCH3_PAIR_CLAIMS,
        S9_BATCH4_PAIR_CLAIMS,
        S9_BATCH5_PAIR_CLAIMS,
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

    let mut production_passes = Vec::new();
    let mut failures = Vec::new();
    for (label, _, expected) in &cases {
        match production_verdict_for_label(&rows, label) {
            Ok(got) if got == *expected => production_passes.push(label.clone()),
            Ok(got) => failures.push(format!("{label}: expected {expected:?} got {got:?}")),
            Err(err) => failures.push(format!("{label}: expected {expected:?}; {err}")),
        }
    }
    production_passes.sort();
    println!(
        "R(rust-witness-production-verdict-residuals)={} authority=production-cli rows={} production_passes={production_passes:?}",
        failures.len(),
        rows.len()
    );
    assert_eq!(
        failures.len(),
        EXPECTED_PRODUCTION_VERDICT_RESIDUALS,
        "production CLI verdict frontier changed; repin the exact residual set after investigating:\n{failures:#?}"
    );
    let expected_passes = EXPECTED_PRODUCTION_VERDICT_PASSES
        .iter()
        .map(|label| (*label).to_string())
        .collect::<Vec<_>>();
    assert_eq!(
        production_passes, expected_passes,
        "production-backed witness set changed; review each new pass/residual as a real drain before repinning"
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
fn seed_witnesses_match_fast_smt_smoke() {
    let z3 = z3_path_or_panic();
    let mut failures = Vec::new();
    let mut owner_mismatches = Vec::new();
    for witness in seed_witnesses() {
        if witness.claim == "return_sugar" {
            for (kind, src, expected_out, expected_sat) in [
                ("truthful", witness.truthful, 5, true),
                ("lying", witness.lying, 6, false),
            ] {
                let label = format!("{}_{}", witness.claim, kind);
                let got_sat = return_sugar_value_contract_verdict(src, expected_out, &label, &z3);
                if got_sat != expected_sat {
                    failures.push(format!(
                        "{label}: expected SAT={expected_sat} got SAT={got_sat}"
                    ));
                }
            }
            continue;
        }
        for (kind, src, expected_sat) in [
            ("truthful", witness.truthful, true),
            ("lying", witness.lying, false),
        ] {
            let label = format!("{}_{}", witness.claim, kind);
            let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
            if let Err(err) = assert_witness_dispatches_to_owner(witness.claim, &out) {
                owner_mismatches.push(format!("{label}: {err}"));
                continue;
            }
            let decl = single_warranted_decl(&out);
            let got_sat = fast_smt_smoke_verdict(&assertion_formula_json(decl), &label, &z3);
            if got_sat != expected_sat {
                failures.push(format!(
                    "{label}: expected SAT={expected_sat} got SAT={got_sat}"
                ));
            }
        }
    }
    println!(
        "R(witness-triples-failing)={} R(witnesses-not-dispatching-to-owner)={}",
        failures.len(),
        owner_mismatches.len()
    );
    assert!(owner_mismatches.is_empty(), "{owner_mismatches:#?}");
    assert!(failures.is_empty(), "{failures:#?}");
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
