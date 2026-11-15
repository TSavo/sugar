// SPDX-License-Identifier: MIT OR Apache-2.0
//
// RUST INTEGER-DIVISION LIFTER-OUTPUT PIN (#1446 rust-side equivalent).
//
// Bare SMT-LIB `div` is a z3 BUILTIN that floors toward -inf, while rust
// integer `/` truncates toward zero (-7 / 2 == -3, but (div -7 2) == -4). If
// the rust lifter ever emitted bare `div` for `/`, the FALSE rust claim
// `halve(-7) == -4` would discharge. This file pins the production rust
// lifter's output for `x / 2` so that change cannot happen silently.
//
// The mint+verify seam probes that used to live here drove `sugar mint`
// through a mock lifter speaking the retired JSON-RPC `lift` method; kits
// construct only through `sugar.enumerate` (#6222, step 1 of the nine steps),
// so those probes were deleted.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value as Json};

fn rust_workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has a parent workspace")
        .to_path_buf()
}

/// Drive the REAL `sugar-walk-rpc` `walk.contract` method against rust
/// source and return the ctor `name` in the body-derived `post`. This is the
/// production function-contract builder (`build_function_contract_with_file` ->
/// `lift::lift_function_postcondition`); it is the syn-source path.
/// Returns the op-symbol the lifter actually emits for the body's `/`.
fn production_post_op_for_division() -> String {
    let req = json!({
        "jsonrpc": "2.0", "id": 1, "method": "walk.contract",
        "params": {"src": "fn halve(x: i64) -> i64 { x / 2 }", "fn_name": "halve", "file": "halve.rs"}
    });
    use std::io::Write;
    let mut command = if let Some(bin) = std::env::var("CARGO_BIN_EXE_sugar").ok().and_then(|p| {
        let dir = PathBuf::from(&p).parent()?.to_path_buf();
        let cand = dir.join("sugar-walk-rpc");
        cand.exists().then_some(cand)
    }) {
        Command::new(bin)
    } else {
        let mut command = Command::new("cargo");
        command
            .arg("run")
            .arg("-p")
            .arg("sugar-walk")
            .arg("--bin")
            .arg("sugar-walk-rpc")
            .arg("--quiet")
            .arg("--")
            .current_dir(rust_workspace());
        command
    };
    let mut child = command
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .expect("spawn sugar-walk-rpc");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(format!("{req}\n").as_bytes())
        .expect("write rpc request");
    let out = child.wait_with_output().expect("walk-rpc output");
    let line = String::from_utf8_lossy(&out.stdout);
    let resp: Json = serde_json::from_str(line.lines().next().unwrap_or(""))
        .unwrap_or_else(|e| panic!("walk.contract JSON parse failed: {e}\nstdout: {line}"));
    resp["result"]["post"]["args"][1]["name"]
        .as_str()
        .unwrap_or_else(|| panic!("walk.contract post missing ctor name; resp: {resp}"))
        .to_string()
}

/// GATING REGRESSION (soundness): the REAL production rust lifter
/// (`sugar-walk-rpc walk.contract` -> `lift_function_postcondition`) emits
/// for `x / 2` an op symbol that MUST NOT be the bare SMT-LIB builtin `div`.
/// Bare `div` is the cardinal-sin shape: z3 floor-divides, so the FALSE rust
/// contract `halve(-7)==-4` would discharge (see the file header).
/// This pins the syn-source LIFTER OUTPUT directly -- where the
/// regression risk lives (lift.rs op-name maps) -- so any silent rewrite of
/// the division op-name to bare `div` trips here.
#[test]
fn production_division_op_is_not_bare_smt_div() {
    let op = production_post_op_for_division();
    assert_ne!(
        op, "div",
        "PRODUCTION rust lifter must NOT emit bare SMT `div` for `/` (z3 floors -> false-discharge of halve(-7)==-4); got `{op}`"
    );
    // Today the production lifter emits `/` (real-division in z3 -> never
    // discharges integer division: soundness-safe but discipline-drifted; see
    // follow-up #1446). Pin the current symbol so a change is conscious.
    assert_eq!(
        op, "/",
        "production division op drifted from `/`; if intentional (e.g. to `concept:div`), update this pin and confirm it is NOT bare `div`; got `{op}`"
    );
    eprintln!("PRODUCTION_DIVISION_OP={op} (NOT bare `div`: soundness-safe)");
}
