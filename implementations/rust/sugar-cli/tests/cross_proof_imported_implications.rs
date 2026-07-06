// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value as Json};
use sugar_proof_envelope::cid_from_proof_stem;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn python_available() -> bool {
    Command::new("python3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn z3_available() -> bool {
    Command::new("z3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn write_executable(path: &Path, text: &str) {
    {
        let mut file = fs::File::create(path).expect("create script");
        file.write_all(text.as_bytes()).expect("write script");
        file.sync_all().expect("sync script");
    }
    #[cfg(unix)]
    {
        let mut perms = fs::metadata(path).expect("stat script").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod script");
    }
}

fn toml_string(value: &Path) -> String {
    format!(
        "\"{}\"",
        value
            .display()
            .to_string()
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
    )
}

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("sugar-cross-proof-{stamp}-{suffix}"));
    fs::create_dir_all(&path).expect("create temp project");
    path
}

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn string_sort() -> Json {
    json!({"kind": "primitive", "name": "String"})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn string_const(value: &str) -> Json {
    json!({"kind": "const", "value": value, "sort": string_sort()})
}

fn eq(lhs: Json, rhs: Json) -> Json {
    json!({"kind": "atomic", "name": "=", "args": [lhs, rhs]})
}

fn vendor_ir_with_encodings(encodings: &[&str]) -> Vec<Json> {
    let encoding_operands: Vec<Json> = encodings
        .iter()
        .map(|encoding| eq(var("encoding"), string_const(encoding)))
        .collect();
    vec![
        json!({
            "kind": "function-contract",
            "name": "lib._npyio_impl.load",
            "bridgeSourceSymbol": "numpy.load",
            "formals": ["file", "encoding"],
            "formalSorts": [string_sort(), string_sort()],
            "outBinding": "out",
            "pre": {
                "kind": "or",
                "operands": encoding_operands,
            },
        }),
        json!({
            "kind": "function-contract",
            "name": "numpy.add",
            "bridgeSourceSymbol": "numpy.add",
            "formals": ["a", "b"],
            "formalSorts": [int_sort(), int_sort()],
            "outBinding": "out",
            "post": eq(
                var("out"),
                json!({"kind": "ctor", "name": "+", "args": [var("a"), var("b")]}),
            ),
        }),
    ]
}

fn pandas_sum_vendor_ir() -> Vec<Json> {
    vec![json!({
        "kind": "function-contract",
        "name": "pandas.Series.sum",
        "bridgeSourceSymbol": "call:sum",
        "formals": [],
        "formalSorts": [],
        "outBinding": "out",
        "post": eq(
            var("out"),
            json!({"kind": "const", "value": 6, "sort": int_sort()}),
        ),
    })]
}

fn write_static_vendor_plugin(path: &Path, ir: &[Json]) {
    let ir = serde_json::to_string(ir).expect("vendor IR serializes");
    write_executable(
        path,
        &format!(
            r#"#!/usr/bin/env python3
import json
import sys

IR = {ir}

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {{
            "name": "static-vendor",
            "protocol_version": "pep/1.7.0",
            "capabilities": {{}},
        }}
    elif method in ("lift", "sugar.plugin.lift"):
        result = {{"kind": "ir-document", "ir": IR, "diagnostics": []}}
    elif method == "shutdown":
        print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": None}}), flush=True)
        break
    else:
        result = {{"kind": "ir-document", "ir": IR, "diagnostics": []}}
    print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": result}}), flush=True)
"#
        ),
    );
}

fn stage_static_vendor_proof(ir: Vec<Json>) -> (tempfile::TempDir, PathBuf, String) {
    let dir = tempfile::tempdir().expect("create vendor tempdir");
    let project = dir.path().join("vendor");
    let manifest_dir = project.join(".sugar/lift/static-vendor");
    let out_dir = dir.path().join("out");
    fs::create_dir_all(&manifest_dir).expect("create vendor manifest dir");
    fs::create_dir_all(&out_dir).expect("create vendor out dir");
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "static-vendor"
kind = "lift"
surface = "static-vendor"
emit = "ir-document"

[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
"#,
    )
    .expect("write vendor config");
    let plugin = project.join("static_vendor.py");
    write_static_vendor_plugin(&plugin, &ir);
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"static-vendor\"\ncommand = [{}]\nworking_dir = \".\"\n",
            toml_string(&plugin)
        ),
    )
    .expect("write vendor manifest");

    let output = Command::new(sugar_bin())
        .arg("mint")
        .arg("--project")
        .arg(&project)
        .arg("--out")
        .arg(&out_dir)
        .arg("--quiet")
        .arg("--json")
        .output()
        .expect("spawn sugar mint vendor");
    assert!(
        output.status.success(),
        "vendor proof mint must succeed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let proof = fs::read_dir(&out_dir)
        .expect("read vendor out")
        .filter_map(|entry| {
            let path = entry.expect("out entry").path();
            (path.extension().and_then(|s| s.to_str()) == Some("proof")).then_some(path)
        })
        .next()
        .expect("vendor proof emitted");
    let stem = proof
        .file_stem()
        .and_then(|s| s.to_str())
        .expect("proof stem");
    let cid = cid_from_proof_stem(stem).expect("proof filename is CID-addressed");
    (dir, proof, cid)
}

fn stage_vendor_proof_with_encodings(encodings: &[&str]) -> (tempfile::TempDir, PathBuf, String) {
    stage_static_vendor_proof(vendor_ir_with_encodings(encodings))
}

fn stage_vendor_proof() -> (tempfile::TempDir, PathBuf, String) {
    stage_vendor_proof_with_encodings(&["ASCII", "latin1", "bytes"])
}

fn stage_pandas_sum_vendor_proof() -> (tempfile::TempDir, PathBuf, String) {
    stage_static_vendor_proof(pandas_sum_vendor_ir())
}

fn build_python_lift_tests() -> PathBuf {
    use std::sync::atomic::{AtomicU64, Ordering};

    static SEQ: AtomicU64 = AtomicU64::new(0);
    let py_tests_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-py-tests")
        .join("src");
    let py_source_src = repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-python-source")
        .join("src");
    let script = std::env::temp_dir().join(format!(
        "sugar-cross-proof-python-lift-{}-{}.sh",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    write_executable(
        &script,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}${{PYTHONPATH:+:$PYTHONPATH}}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            py_tests_src.display(),
            py_source_src.display(),
        ),
    );
    script
}

fn install_python_component_claim(project: &Path) {
    let component_dir = project.join(".sugar/components/python-lift");
    fs::create_dir_all(&component_dir).expect("create component dir");
    let script = component_dir.join("component.sh");
    write_executable(
        &script,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"python-lift-component","protocol_version":"sugar-component/1","capabilities":{}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"decision":"claim","plugins":[{"name":"python-lift","kind":"lift","surface":"python"}],"diagnostics":[{"level":"info","message":"python lift component planned"}]}}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
    );
    fs::write(
        component_dir.join("manifest.toml"),
        format!(
            "name = \"python-lift-component\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"/bin/sh\", {}]\n",
            toml_string(&script)
        ),
    )
    .expect("write component manifest");
}

fn stage_consumer_project(proof: &Path, source: &str, suffix: &str) -> PathBuf {
    let project = unique_dir(suffix);
    fs::create_dir_all(project.join(".sugar/lift/python")).expect("create lift dir");
    fs::create_dir_all(project.join(".sugar/imports")).expect("create imports dir");
    fs::copy(
        proof,
        project
            .join(".sugar/imports")
            .join(proof.file_name().expect("proof filename")),
    )
    .expect("copy imported proof");
    fs::write(project.join("test_case.py"), source).expect("write consumer source");
    install_python_component_claim(&project);
    fs::write(
        project.join(".sugar/config.toml"),
        r#"[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"
emit = "ir-document"

[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
"#,
    )
    .expect("write consumer config");
    let wrapper = build_python_lift_tests();
    fs::write(
        project.join(".sugar/lift/python/manifest.toml"),
        format!(
            "name = \"python-lift\"\ncommand = [{}]\nworking_dir = \".\"\n",
            toml_string(&wrapper)
        ),
    )
    .expect("write consumer manifest");
    project
}

fn remove_direct_project_proofs(project: &Path) {
    for entry in fs::read_dir(project).expect("read project root") {
        let path = entry.expect("project entry").path();
        if path.extension().and_then(|s| s.to_str()) == Some("proof") {
            fs::remove_file(&path)
                .unwrap_or_else(|err| panic!("remove stale proof {}: {err}", path.display()));
        }
    }
}

fn replace_imported_proof(project: &Path, proof: &Path) {
    let imports = project.join(".sugar/imports");
    for entry in fs::read_dir(&imports).expect("read imports dir") {
        let path = entry.expect("imports entry").path();
        if path.extension().and_then(|s| s.to_str()) == Some("proof") {
            fs::remove_file(&path)
                .unwrap_or_else(|err| panic!("remove imported proof {}: {err}", path.display()));
        }
    }
    fs::copy(
        proof,
        imports.join(proof.file_name().expect("proof filename")),
    )
    .expect("copy replacement proof");
    remove_direct_project_proofs(project);
}

fn run_mint(project: &Path) {
    remove_direct_project_proofs(project);
    let output = Command::new(sugar_bin())
        .arg("mint")
        .arg("--project")
        .arg(project)
        .arg("--out")
        .arg(project)
        .arg("--quiet")
        .arg("--json")
        .output()
        .expect("spawn sugar mint consumer");
    assert!(
        output.status.success(),
        "consumer mint must succeed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn run_prove(project: &Path) -> (Json, i32) {
    let output = Command::new(sugar_bin())
        .arg("prove")
        .arg(project)
        .arg("--json")
        .output()
        .expect("spawn sugar prove");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let report: Json = serde_json::from_str(&stdout)
        .unwrap_or_else(|err| panic!("prove JSON parse failed: {err}\nstdout: {stdout}"));
    (report, output.status.code().unwrap_or(-1))
}

fn run_lift_report(project: &Path) -> Json {
    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg("--report")
        .arg("--json")
        .arg(project)
        .output()
        .expect("spawn sugar lift report");
    assert!(
        output.status.success(),
        "lift report must render\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("lift report JSON parses")
}

fn prove_rows(report: &Json) -> &[Json] {
    report["rows"].as_array().expect("prove rows")
}

fn find_bridge_row<'a>(report: &'a Json, bridge: &str) -> &'a Json {
    prove_rows(report)
        .iter()
        .find(|row| row["bridge"].as_str() == Some(bridge))
        .unwrap_or_else(|| panic!("bridge row `{bridge}` not found in report: {report:#}"))
}

fn find_consistency_row<'a>(report: &'a Json, property_contains: &str) -> &'a Json {
    prove_rows(report)
        .iter()
        .find(|row| {
            row["property"]
                .as_str()
                .is_some_and(|property| property.contains(property_contains))
        })
        .unwrap_or_else(|| {
            panic!("consistency row containing `{property_contains}` not found: {report:#}")
        })
}

fn assert_report_edge_targets_imported_proof(report: &Json, target: &str, proof_cid: &str) {
    let edges = report["callEdges"].as_array().expect("callEdges array");
    let edge = edges
        .iter()
        .find(|edge| edge["targetSymbol"].as_str() == Some(target))
        .unwrap_or_else(|| panic!("call edge for {target} missing: {edges:#?}"));
    assert_eq!(edge["targetProofCid"].as_str(), Some(proof_cid));
}

fn assert_linked_post_targets_imported_proof(row: &Json, proof_cid: &str) {
    let posts = row["verification"]["linkedPosts"]
        .as_array()
        .expect("linkedPosts array");
    let post = posts
        .iter()
        .find(|post| post["sourceSymbol"].as_str() == Some("numpy.add"))
        .unwrap_or_else(|| panic!("numpy.add linked post missing: {row:#}"));
    assert_eq!(post["targetProofCid"].as_str(), Some(proof_cid));
    assert_eq!(post["call"]["name"].as_str(), Some("call:numpy.add"));
    assert_eq!(post["call"]["args"][0]["value"].as_i64(), Some(5));
    assert_eq!(post["call"]["args"][1]["value"].as_i64(), Some(5));
}

fn assert_linked_sum_post_targets_imported_proof(row: &Json, proof_cid: &str) {
    let posts = row["verification"]["linkedPosts"]
        .as_array()
        .expect("linkedPosts array");
    let post = posts
        .iter()
        .find(|post| post["sourceSymbol"].as_str() == Some("call:sum"))
        .unwrap_or_else(|| panic!("pandas Series.sum linked post missing: {row:#}"));
    assert_eq!(post["targetProofCid"].as_str(), Some(proof_cid));
    assert!(post["targetContractCid"].as_str().is_some());
    assert_eq!(post["call"]["name"].as_str(), Some("call:sum"));
    assert_eq!(
        post["instantiatedPost"],
        json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {"kind": "ctor", "name": "call:sum", "args": []},
                {"kind": "const", "value": 6, "sort": int_sort()},
            ],
        })
    );
}

#[test]
fn imported_numpy_load_precondition_discharges_and_refuses_at_consumer_callsite() {
    assert!(
        python_available(),
        "python3 is required for the Python lift plugin"
    );
    assert!(
        z3_available(),
        "z3 is required for the production prove verdict"
    );
    let (_vendor_dir, proof, proof_cid) = stage_vendor_proof();

    let good = stage_consumer_project(
        &proof,
        r#"import numpy as np


def test_load():
    assert np.load("data.npy", encoding="latin1") == "data.npy"
"#,
        "load-good",
    );
    let good_report = run_lift_report(&good);
    assert_report_edge_targets_imported_proof(&good_report, "call:numpy.load", &proof_cid);
    run_mint(&good);
    let (good_prove, good_code) = run_prove(&good);
    assert_eq!(
        good_code, 0,
        "latin1 precondition must discharge: {good_prove}"
    );
    assert_eq!(good_prove["violations"].as_u64(), Some(0));
    let good_bridge = find_bridge_row(&good_prove, "call:numpy.load");
    assert_eq!(good_bridge["status"].as_str(), Some("discharged"));
    assert_eq!(
        good_bridge["dischargeMethod"].as_str(),
        Some("solver-substantive")
    );

    let bad = stage_consumer_project(
        &proof,
        r#"import numpy as np


def test_load():
    assert np.load("data.npy", encoding="wrong") == "data.npy"
"#,
        "load-bad",
    );
    run_mint(&bad);
    let (bad_prove, bad_code) = run_prove(&bad);
    assert_eq!(
        bad_code, 1,
        "wrong encoding must violate vendor pre: {bad_prove}"
    );
    assert_eq!(bad_prove["violations"].as_u64(), Some(1));
    let bad_bridge = find_bridge_row(&bad_prove, "call:numpy.load");
    assert_eq!(bad_bridge["status"].as_str(), Some("unsatisfied"));
}

#[test]
fn imported_pandas_sum_showcase_universe_links_into_consumer_assertions() {
    assert!(
        python_available(),
        "python3 is required for the Python lift plugin"
    );
    assert!(
        z3_available(),
        "z3 is required for the production prove verdict"
    );
    let (_vendor_dir, proof, proof_cid) = stage_pandas_sum_vendor_proof();

    let good = stage_consumer_project(
        &proof,
        r#"import pandas as pd


def test_sum():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6
"#,
        "pandas-sum-good",
    );
    let good_report = run_lift_report(&good);
    assert_report_edge_targets_imported_proof(&good_report, "call:sum", &proof_cid);
    run_mint(&good);
    let (good_prove, good_code) = run_prove(&good);
    assert_eq!(
        good_code, 0,
        "pandas Series.sum truthful consumer must prove: {good_prove}"
    );
    assert_eq!(good_prove["violations"].as_u64(), Some(0));
    let good_row = find_consistency_row(&good_prove, "sum#euf#");
    assert_eq!(good_row["status"].as_str(), Some("discharged"));
    assert_linked_sum_post_targets_imported_proof(good_row, &proof_cid);

    let bad = stage_consumer_project(
        &proof,
        r#"import pandas as pd


def test_sum():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 7
"#,
        "pandas-sum-bad",
    );
    run_mint(&bad);
    let (bad_prove, bad_code) = run_prove(&bad);
    assert_eq!(
        bad_code, 1,
        "pandas Series.sum contradictory consumer must stay red: {bad_prove}"
    );
    assert_eq!(bad_prove["violations"].as_u64(), Some(1));
    let bad_row = find_consistency_row(&bad_prove, "sum#euf#");
    assert_eq!(bad_row["status"].as_str(), Some("unsatisfied"));
    assert_linked_sum_post_targets_imported_proof(bad_row, &proof_cid);
}

#[test]
fn imported_numpy_add_universe_links_into_fresh_consumer_assertions() {
    assert!(
        python_available(),
        "python3 is required for the Python lift plugin"
    );
    assert!(
        z3_available(),
        "z3 is required for the production prove verdict"
    );
    let (_vendor_dir, proof, proof_cid) = stage_vendor_proof();

    let good = stage_consumer_project(
        &proof,
        r#"import numpy as np


def test_add():
    assert np.add(5, 5) == 10
"#,
        "add-good",
    );
    run_mint(&good);
    let (good_prove, good_code) = run_prove(&good);
    assert_eq!(
        good_code, 0,
        "fresh np.add(5,5)==10 must prove: {good_prove}"
    );
    assert_eq!(good_prove["violations"].as_u64(), Some(0));
    let good_row = find_consistency_row(&good_prove, "numpy.add#euf#");
    assert_eq!(good_row["status"].as_str(), Some("discharged"));
    assert_linked_post_targets_imported_proof(good_row, &proof_cid);

    let bad = stage_consumer_project(
        &proof,
        r#"import numpy as np


def test_add():
    assert np.add(5, 5) == 11
"#,
        "add-bad",
    );
    run_mint(&bad);
    let (bad_prove, bad_code) = run_prove(&bad);
    assert_eq!(
        bad_code, 1,
        "fresh np.add(5,5)==11 must refute: {bad_prove}"
    );
    assert_eq!(bad_prove["violations"].as_u64(), Some(1));
    let bad_row = find_consistency_row(&bad_prove, "numpy.add#euf#");
    assert_eq!(bad_row["status"].as_str(), Some("unsatisfied"));
    assert_linked_post_targets_imported_proof(bad_row, &proof_cid);
}

#[test]
fn imported_vendor_update_delta_names_only_affected_consumer_callsites() {
    assert!(
        python_available(),
        "python3 is required for the Python lift plugin"
    );
    assert!(
        z3_available(),
        "z3 is required for the production prove verdict"
    );
    let (_vendor_v1_dir, proof_v1, proof_v1_cid) =
        stage_vendor_proof_with_encodings(&["ASCII", "latin1", "bytes"]);
    let (_vendor_v2_dir, proof_v2, proof_v2_cid) =
        stage_vendor_proof_with_encodings(&["ASCII", "bytes"]);
    assert_ne!(
        proof_v1_cid, proof_v2_cid,
        "tightening the vendor encoding universe must mint a different proof"
    );

    let consumer = stage_consumer_project(
        &proof_v1,
        r#"import numpy as np


def test_load():
    assert np.load("data.npy", encoding="latin1") == "data.npy"


def test_add():
    assert np.add(5, 5) == 10
"#,
        "vendor-update-consumer",
    );

    let v1_report = run_lift_report(&consumer);
    assert_report_edge_targets_imported_proof(&v1_report, "call:numpy.load", &proof_v1_cid);
    run_mint(&consumer);
    let (v1_prove, v1_code) = run_prove(&consumer);
    assert_eq!(
        v1_code, 0,
        "consumer should prove against vendor v1: {v1_prove}"
    );
    let v1_load = find_bridge_row(&v1_prove, "call:numpy.load");
    assert_eq!(v1_load["status"].as_str(), Some("discharged"));
    let v1_add = find_consistency_row(&v1_prove, "numpy.add#euf#");
    assert_eq!(v1_add["status"].as_str(), Some("discharged"));
    assert_linked_post_targets_imported_proof(v1_add, &proof_v1_cid);

    replace_imported_proof(&consumer, &proof_v2);
    let v2_report = run_lift_report(&consumer);
    assert_report_edge_targets_imported_proof(&v2_report, "call:numpy.load", &proof_v2_cid);
    run_mint(&consumer);
    let (v2_prove, v2_code) = run_prove(&consumer);
    assert_eq!(
        v2_code, 1,
        "consumer load call should fail after vendor v2 removes latin1: {v2_prove}"
    );
    assert_eq!(v2_prove["violations"].as_u64(), Some(1));
    let v2_load = find_bridge_row(&v2_prove, "call:numpy.load");
    assert_eq!(v2_load["status"].as_str(), Some("unsatisfied"));
    let v2_add = find_consistency_row(&v2_prove, "numpy.add#euf#");
    assert_eq!(v2_add["status"].as_str(), Some("discharged"));
    assert_linked_post_targets_imported_proof(v2_add, &proof_v2_cid);

    let changed = [(
        "call:numpy.load",
        v1_load["status"].as_str().unwrap(),
        v2_load["status"].as_str().unwrap(),
    )];
    let held = [(
        "numpy.add#euf#",
        v1_add["status"].as_str().unwrap(),
        v2_add["status"].as_str().unwrap(),
    )];
    assert_eq!(changed, [("call:numpy.load", "discharged", "unsatisfied")]);
    assert_eq!(held, [("numpy.add#euf#", "discharged", "discharged")]);
}
