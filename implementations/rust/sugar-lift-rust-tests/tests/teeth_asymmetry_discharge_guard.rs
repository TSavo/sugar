//! Soundness regression: teeth verdicts come from the production CLI.
//!
//! This file used to be a shadow harness: lift in-process, compile SMT
//! in-process, shell z3 directly, and treat that local SAT/UNSAT as the
//! verdict. That bypasses the production lattice (`sugar mint` + `sugar prove`)
//! and can only be a smoke check, never authority.
//!
//! The authority here is source -> `sugar mint` -> `sugar prove --json --z3`.
//! The split is explicit:
//!   * active disagreement = a truthful teeth witness is refuted, or a lying
//!     witness discharges, through production;
//!   * coverage gap = production refuses/has no row/has no directional verdict.
//!
//! Non-vacuity is load-bearing. The function-call teeth anchors below discharge
//! truthful forms and reject their lying twins, proving this detector can fire
//! instead of merely watching every case refuse.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value as Json};

#[derive(Debug, Clone)]
struct ProveRow {
    property: String,
    status: String,
    reason: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TeethExpectation {
    Truth,
    Lie,
}

#[derive(Debug, Clone, Copy)]
struct TeethCase {
    label: &'static str,
    source: &'static str,
    expectation: TeethExpectation,
}

const EXPECTED_TEETH_PRODUCTION_ACTIVE_DISAGREEMENTS: usize = 0;
const EXPECTED_TEETH_PRODUCTION_COVERAGE_GAPS: usize = 21;
const EXPECTED_TEETH_PRODUCTION_DISCHARGED_TRUTHS: &[&str] = &[
    "borrow4_stale_mut_truthful",
    "function_literal_index_truthful",
    "function_literal_repeat_truthful",
    "single_ascii_alnum_truthful",
    "single_ascii_alpha_truthful",
    "single_ascii_digit_truthful",
    "single_ascii_eq_ignore_case_truthful",
    "single_ascii_hex_truthful",
    "single_ascii_lower_truthful",
    "single_ascii_upper_truthful",
    "single_ascii_whitespace_truthful",
];
const EXPECTED_TEETH_PRODUCTION_CONFIRMED_LIES: &[&str] = &[
    "borrow4_stale_mut_lying",
    "function_literal_index_lying",
    "function_literal_repeat_lying",
];

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
        return Err(format!(
            "crime=soundness verdict without executable solver; owner=teeth_asymmetry; \
             illegal shape=Z3 points at non-executable solver `{path}`; \
             replacement=install z3 or set Z3=/path/to/z3"
        ));
    }

    for dir in path_env.split(':').filter(|dir| !dir.is_empty()) {
        let candidate = Path::new(dir).join("z3");
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

    Err(
        "crime=soundness verdict without solver; owner=teeth_asymmetry; \
         illegal shape=missing z3; replacement=install z3 or set Z3=/path/to/z3"
            .to_string(),
    )
}

fn solver_path_or_panic() -> String {
    let z3_env = std::env::var("Z3").ok();
    let path_env = std::env::var("PATH").unwrap_or_default();
    resolve_z3_from(z3_env.as_deref(), &path_env).unwrap_or_else(|err| panic!("{err}"))
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
            "crime=soundness verdict without production CLI; owner=teeth_asymmetry; \
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
            "crime=soundness verdict without production CLI; owner=teeth_asymmetry; \
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
        "sugar-teeth-cli-{}-{stamp}-{safe_label}",
        std::process::id()
    ));
    fs::create_dir_all(&dir).expect("mkdir production teeth project");
    dir
}

fn write_rust_test_assertion_project(project: &Path, cases: &[TeethCase]) {
    let ws = rust_workspace();
    fs::create_dir_all(project.join("tests")).expect("mkdir tests");
    fs::create_dir_all(project.join(".sugar/lift/rust-test-assertions")).expect("mkdir lift");
    fs::create_dir_all(project.join(".sugar/components/rust-test-assertions"))
        .expect("mkdir component");
    fs::create_dir_all(project.join(".sugar/ir-compilers/smt-lib")).expect("mkdir compiler");

    for case in cases {
        fs::write(
            project.join("tests").join(format!("{}.rs", case.label)),
            case.source,
        )
        .expect("write teeth source");
    }

    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "rust-test-assertions-lift"
kind = "lift"
surface = "rust-test-assertions"

[solvers]
default = "z3"

[solvers.dispatch]
linear_arithmetic = "z3"
default = "z3"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
"#,
    )
    .expect("write config");

    fs::write(
        project.join(".sugar/lift/rust-test-assertions/manifest.toml"),
        format!(
            r#"name = "rust-test-assertions-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
command = ["cargo", "run", "-p", "sugar-lift-rust-tests", "--bin", "rust_test_assertions_rpc", "--quiet", "--"]
working_dir = "{ws}"
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
            reason: row["reason"].as_str().unwrap_or_default().to_string(),
        })
        .collect())
}

fn statuses_for_label<'a>(rows: &'a [ProveRow], label: &str) -> Vec<&'a ProveRow> {
    let file_needle = format!("tests/{label}.rs");
    rows.iter()
        .filter(|row| row.property.contains(&file_needle))
        .filter(|row| !row.property.contains("#panic_callsite#"))
        .filter(|row| !row.property.contains("::temporal-rewrite::"))
        .collect()
}

fn summarize_rows(rows: &[&ProveRow]) -> Vec<String> {
    rows.iter()
        .map(|row| {
            if row.reason.is_empty() {
                format!("{}:{}", row.status, row.property)
            } else {
                format!("{}:{} — {}", row.status, row.property, row.reason)
            }
        })
        .collect()
}

fn teeth_cases() -> Vec<TeethCase> {
    vec![
        TeethCase {
            label: "function_literal_index_truthful",
            source: r#"fn teeth_idx_truth() -> i32 { [7, 7, 7][1] } #[test] fn t() { assert_eq!(teeth_idx_truth(), 7); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "function_literal_index_lying",
            source: r#"fn teeth_idx_lie() -> i32 { [7, 7, 7][1] } #[test] fn t() { assert_eq!(teeth_idx_lie(), 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "function_literal_repeat_truthful",
            source: r#"fn teeth_repeat_truth() -> i32 { [7; 3][1] } #[test] fn t() { assert_eq!(teeth_repeat_truth(), 7); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "function_literal_repeat_lying",
            source: r#"fn teeth_repeat_lie() -> i32 { [7; 3][1] } #[test] fn t() { assert_eq!(teeth_repeat_lie(), 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_literal_index_truthful",
            source: r#"#[test] fn t() { assert_eq!([7, 7, 7][1], 7); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_literal_index_lying",
            source: r#"#[test] fn t() { assert_eq!([7, 7, 7][1], 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_literal_repeat_truthful",
            source: r#"#[test] fn t() { assert_eq!([7; 3][1], 7); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_literal_repeat_lying",
            source: r#"#[test] fn t() { assert_eq!([7; 3][1], 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_literal_arith_truthful",
            source: r#"#[test] fn t() { assert_eq!(2 + 2, 4); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_const_name_repeat_lying",
            source: r#"const SIZE: usize = 3; #[test] fn t() { assert_eq!([7; SIZE][1], 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_const_arith_repeat_lying",
            source: r#"const B: usize = 2; const CAP: usize = 2 * B - 1; #[test] fn t() { assert_eq!([7; CAP][1], 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_same_arrays_truthful",
            source: r#"#[test] fn t() { assert_eq!([7, 7, 99], [7, 7, 99]); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_arrays_differ_lying",
            source: r#"#[test] fn t() { assert_eq!([7, 7, 99], [7, 7, 7]); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_maybeuninit_truthful",
            source: r#"#[test] fn t() { assert_eq!(unsafe { core::mem::MaybeUninit::new(7).assume_init() }, 7); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_maybeuninit_lying",
            source: r#"#[test] fn t() { assert_eq!(unsafe { core::mem::MaybeUninit::new(7).assume_init() }, 8); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_opaque_element_repeat_lying",
            source: r#"#[test] fn t() { assert_eq!([compute(); 3][1], 99); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_const_generic_repeat_lying",
            source: r#"fn sized<const N: usize>() { assert_eq!([7; N][1], 99); } #[test] fn t() { sized::<3>(); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "borrow4_stale_mut_truthful",
            source: r#"#[test] fn t() { let mut x = 5; let r = &mut x; *r += 1; assert_eq!(x, 6); assert_eq!(x, 6); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "borrow4_stale_mut_lying",
            source: r#"#[test] fn t() { let mut x = 5; let r = &mut x; *r += 1; assert_eq!(x, 6); assert_eq!(x, 7); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_digit_truthful",
            source: r#"#[test] fn t() { assert!('5'.is_ascii_digit()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_digit_lying",
            source: r#"#[test] fn t() { assert!('a'.is_ascii_digit()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_alpha_truthful",
            source: r#"#[test] fn t() { assert!('a'.is_ascii_alphabetic()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_alpha_lying",
            source: r#"#[test] fn t() { assert!('5'.is_ascii_alphabetic()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_upper_truthful",
            source: r#"#[test] fn t() { assert!('A'.is_ascii_uppercase()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_upper_lying",
            source: r#"#[test] fn t() { assert!('a'.is_ascii_uppercase()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_lower_truthful",
            source: r#"#[test] fn t() { assert!('a'.is_ascii_lowercase()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_lower_lying",
            source: r#"#[test] fn t() { assert!('A'.is_ascii_lowercase()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_alnum_truthful",
            source: r#"#[test] fn t() { assert!('9'.is_ascii_alphanumeric()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_alnum_lying",
            source: r#"#[test] fn t() { assert!('!'.is_ascii_alphanumeric()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_hex_truthful",
            source: r#"#[test] fn t() { assert!('f'.is_ascii_hexdigit()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_hex_lying",
            source: r#"#[test] fn t() { assert!('g'.is_ascii_hexdigit()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_whitespace_truthful",
            source: r#"#[test] fn t() { assert!(' '.is_ascii_whitespace()); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_whitespace_lying",
            source: r#"#[test] fn t() { assert!('x'.is_ascii_whitespace()); }"#,
            expectation: TeethExpectation::Lie,
        },
        TeethCase {
            label: "single_ascii_eq_ignore_case_truthful",
            source: r#"#[test] fn t() { assert!("abc".eq_ignore_ascii_case("ABC")); }"#,
            expectation: TeethExpectation::Truth,
        },
        TeethCase {
            label: "single_ascii_eq_ignore_case_lying",
            source: r#"#[test] fn t() { assert!("Ürl".eq_ignore_ascii_case("ürl")); }"#,
            expectation: TeethExpectation::Lie,
        },
    ]
}

#[test]
fn teeth_asymmetry_verdicts_come_from_production_cli() {
    let cases = teeth_cases();
    let z3 = solver_path_or_panic();
    let project = unique_cli_project("teeth-asymmetry-production");
    write_rust_test_assertion_project(&project, &cases);
    let rows = mint_and_prove_project(&project, &z3).unwrap_or_else(|err| {
        panic!(
            "production sugar mint/prove must produce teeth verdicts\nproject={}\n{err}",
            project.display()
        )
    });

    let mut active_disagreements = Vec::new();
    let mut coverage_gaps = Vec::new();
    let mut discharged_truths = Vec::new();
    let mut confirmed_lies = Vec::new();

    for case in &cases {
        let rows_for_case = statuses_for_label(&rows, case.label);
        let statuses = rows_for_case
            .iter()
            .map(|row| row.status.as_str())
            .collect::<Vec<_>>();
        match case.expectation {
            TeethExpectation::Truth if statuses.iter().all(|status| *status == "discharged") => {
                discharged_truths.push(case.label);
            }
            TeethExpectation::Truth if statuses.iter().any(|status| *status == "unsatisfied") => {
                active_disagreements.push(format!(
                    "{}: truthful teeth source refuted by production CLI: {:?}",
                    case.label,
                    summarize_rows(&rows_for_case)
                ));
            }
            TeethExpectation::Truth => coverage_gaps.push(format!(
                "{}: truthful teeth source did not discharge: {:?}",
                case.label,
                summarize_rows(&rows_for_case)
            )),
            TeethExpectation::Lie if statuses.iter().any(|status| *status == "discharged") => {
                active_disagreements.push(format!(
                    "{}: HIDDEN LIE; lying teeth source discharged by production CLI: {:?}",
                    case.label,
                    summarize_rows(&rows_for_case)
                ));
            }
            TeethExpectation::Lie if statuses.iter().any(|status| *status == "unsatisfied") => {
                confirmed_lies.push(case.label);
            }
            TeethExpectation::Lie => coverage_gaps.push(format!(
                "{}: lying teeth source was not caught by production CLI, but did not discharge: {:?}",
                case.label,
                summarize_rows(&rows_for_case)
            )),
        }
    }

    discharged_truths.sort_unstable();
    confirmed_lies.sort_unstable();
    println!(
        "R(teeth-production-active-disagreements)={} R(teeth-production-coverage-gaps)={} authority=source-to-sugar-cli rows={} discharged_truths={discharged_truths:?} confirmed_lies={confirmed_lies:?}",
        active_disagreements.len(),
        coverage_gaps.len(),
        rows.len()
    );
    assert_eq!(
        active_disagreements.len(),
        EXPECTED_TEETH_PRODUCTION_ACTIVE_DISAGREEMENTS,
        "production CLI found active teeth disagreements:\n{active_disagreements:#?}"
    );
    assert_eq!(
        coverage_gaps.len(),
        EXPECTED_TEETH_PRODUCTION_COVERAGE_GAPS,
        "production CLI coverage gap frontier changed; classify every row before repinning:\n{coverage_gaps:#?}"
    );
    assert_eq!(
        discharged_truths, EXPECTED_TEETH_PRODUCTION_DISCHARGED_TRUTHS,
        "non-vacuity anchor changed; truthful teeth cases must prove the detector can discharge"
    );
    assert_eq!(
        confirmed_lies,
        EXPECTED_TEETH_PRODUCTION_CONFIRMED_LIES,
        "bad-twin anchor changed; lying teeth cases must stay non-discharged and currently unsatisfied"
    );
}

#[test]
fn production_cli_verdict_fails_loudly_when_z3_is_absent() {
    let case = TeethCase {
        label: "z3_absent_anchor",
        source: r#"fn teeth_idx_truth() -> i32 { [7, 7, 7][1] } #[test] fn t() { assert_eq!(teeth_idx_truth(), 7); }"#,
        expectation: TeethExpectation::Truth,
    };
    let project = unique_cli_project("teeth-z3-absent");
    write_rust_test_assertion_project(&project, &[case]);
    let err = mint_and_prove_project(&project, "/definitely/not/z3")
        .expect_err("production CLI verdict must not pass when z3 is absent");
    println!("teeth production CLI z3 absence refusal: {err}");
    assert!(
        err.contains("z3") && err.contains("/definitely/not/z3"),
        "missing-z3 failure should name the production solver path, got:\n{err}"
    );
}

#[test]
fn no_test_local_z3_shadow_verdict_remains_in_teeth_harness() {
    let source = include_str!("teeth_asymmetry_discharge_guard.rs");
    let forbidden = [
        ["compile_asserted", "_formula_to_parts"].concat(),
        ["(check", "-sat)"].concat(),
        ["Command::new(", "z3"].concat(),
        ["Command::new(&", "z3"].concat(),
        ["fn ", "z3_"].concat(),
        ["Option", "<bool>"].concat(),
    ];
    let hits = forbidden
        .iter()
        .flat_map(|needle| {
            source
                .lines()
                .enumerate()
                .filter(move |(_, line)| {
                    !line.contains("forbidden")
                        && !line.contains("line.contains")
                        && line.contains(needle.as_str())
                })
                .map(move |(idx, line)| format!("{needle} @ {}: {}", idx + 1, line.trim()))
        })
        .collect::<Vec<_>>();
    assert!(
        hits.is_empty(),
        "teeth_asymmetry soundness verdicts must come from sugar mint/prove, not local SMT/z3: {hits:#?}"
    );
}

#[test]
fn production_teeth_cases_are_uniquely_named() {
    let mut labels = BTreeSet::new();
    for case in teeth_cases() {
        assert!(labels.insert(case.label), "duplicate teeth case label");
        assert!(
            case.source.contains("#[test]"),
            "{} must be a real rust-test-assertions source",
            case.label
        );
    }
}
