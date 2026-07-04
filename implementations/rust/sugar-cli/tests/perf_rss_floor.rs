// SPDX-License-Identifier: Apache-2.0

use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .expect("repo root")
}

#[test]
fn verify_rss_harness_self_test_exercises_macos_and_linux_parsers() {
    let script = repo_root().join("tools/perf/verify-rss.sh");
    assert!(
        script.exists(),
        "peak-RSS harness must live at {}",
        script.display()
    );

    let output = Command::new("bash")
        .arg(&script)
        .arg("--self-test")
        .output()
        .expect("run RSS harness self-test");
    assert!(
        output.status.success(),
        "RSS harness self-test must pass\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("macos_kib=121"),
        "self-test must prove macOS byte output is rounded to KiB: {stdout}"
    );
    assert!(
        stdout.contains("linux_kib=345678"),
        "self-test must prove Linux kbyte output is parsed as KiB: {stdout}"
    );
    assert!(
        stdout.contains("floor_status=regression-detected"),
        "self-test must prove the 10% floor fails closed: {stdout}"
    );
}

#[test]
fn dhat_heap_feature_is_declared_and_wired_at_cli_entrypoint() {
    let root = repo_root();
    let cargo_toml =
        std::fs::read_to_string(root.join("implementations/rust/sugar-cli/Cargo.toml"))
            .expect("read sugar-cli Cargo.toml");
    assert!(
        cargo_toml.contains("[features]") && cargo_toml.contains("dhat-heap"),
        "sugar-cli must expose an opt-in dhat-heap feature"
    );
    assert!(
        cargo_toml.contains("dep:dhat"),
        "dhat-heap feature must enable the dhat dependency"
    );
    assert!(
        cargo_toml.contains("dhat = { version = \"0.3\""),
        "sugar-cli must pin dhat 0.3 for heap profiling"
    );

    let main_rs = std::fs::read_to_string(root.join("implementations/rust/sugar-cli/src/main.rs"))
        .expect("read sugar-cli main");
    assert!(
        main_rs.contains("#[cfg(feature = \"dhat-heap\")]")
            && main_rs.contains("dhat::Profiler::new_heap()"),
        "sugar-cli main must instantiate the dhat heap profiler behind the feature"
    );
}

#[test]
fn perf_rss_and_dhat_documentation_has_copy_paste_commands() {
    let doc = repo_root().join("docs/perf/verify-rss-and-dhat.md");
    assert!(
        doc.exists(),
        "perf docs must describe the RSS harness and dhat gate at {}",
        doc.display()
    );
    let doc_text = std::fs::read_to_string(&doc).expect("read perf docs");
    assert!(
        doc_text.contains("tools/perf/verify-rss.sh --project-root"),
        "docs must include the verify RSS harness one-liner"
    );
    assert!(
        doc_text.contains("cargo run -p sugar-cli --features dhat-heap --bin sugar -- verify"),
        "docs must include the dhat heap profiling one-liner"
    );
    assert!(
        doc_text.contains("dhat-heap.json"),
        "docs must name dhat's heap profile output"
    );
}

#[test]
fn ci_workflow_arms_synthetic_rss_floor_smoke_job() {
    let workflow = std::fs::read_to_string(repo_root().join(".github/workflows/ci.yml"))
        .expect("read CI workflow");

    assert!(
        workflow.contains("rss-floor-smoke:"),
        "CI must have a dedicated RSS floor smoke job"
    );
    assert!(
        workflow.contains("synthetic_rss_fixture"),
        "CI RSS smoke job must generate the synthetic 120-bridge fixture"
    );
    assert!(
        workflow.contains("tools/perf/verify-rss.sh") && workflow.contains("--reference-kib 37376"),
        "CI RSS smoke job must arm verify-rss with the CI Linux reference for the provenance-carrying fixture (re-pinned 2026-07-03: the fixture now mints required source-memento warrants)"
    );
}
