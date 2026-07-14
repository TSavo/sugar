use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli workspace root")
        .to_path_buf()
}

#[test]
fn sugarbin_local_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_local_exec.sh"))
        .arg(&root)
        .status()
        .expect("run local execution contract");
    assert!(
        status.success(),
        "local execution contract failed: {status}"
    );
}

#[test]
fn sugarbin_bx_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_bx_exec.sh"))
        .arg(&root)
        .status()
        .expect("run bx execution contract");
    assert!(status.success(), "bx execution contract failed: {status}");
}

#[test]
fn sugarbin_docker_execution_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_docker_exec.sh"))
        .arg(&root)
        .status()
        .expect("run Docker execution contract");
    assert!(
        status.success(),
        "Docker execution contract failed: {status}"
    );
}

#[test]
fn sugarbin_wrapper_compatibility_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_wrapper_compat.sh"))
        .arg(&root)
        .status()
        .expect("run wrapper compatibility contract");
    assert!(
        status.success(),
        "wrapper compatibility contract failed: {status}"
    );
}

#[test]
fn sugarbin_artifact_manifest_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests/sugarbin_artifact_manifest.sh"))
        .arg(&root)
        .status()
        .expect("run artifact manifest contract");
    assert!(
        status.success(),
        "artifact manifest contract failed: {status}"
    );
}

#[test]
fn remote_execution_provisioning_has_one_owner() {
    let root = repo_root();
    let forbidden = [
        "sync_paths=(",
        "exclude_args=(",
        "rsync -azR",
        "bcargo-python-kit-env",
    ];
    let residents = [
        "bin/bcargo",
        "bin/brun",
        "bin/bpytest",
        "bin/sugarbin",
        "Makefile",
        ".github/workflows/restored-suite-scoreboard.yml",
    ];
    let mut offenders = Vec::new();
    for resident in residents {
        let body = std::fs::read_to_string(root.join(resident))
            .unwrap_or_else(|error| panic!("read {resident}: {error}"));
        for shape in forbidden {
            if body.contains(shape) {
                offenders.push(format!("{resident}: owns `{shape}`"));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "R={} duplicate remote provisioning residents remain outside bin/lib/sugar-bx.sh:\n{}\nreplacement: managed dependencies belong to sugar-build.toml Docker tasks; ambient execution never provisions",
        offenders.len(),
        offenders.join("\n")
    );
}

#[test]
fn restored_suite_runner_declares_its_ambient_route() {
    let root = repo_root();
    let workflow =
        std::fs::read_to_string(root.join(".github/workflows/restored-suite-scoreboard.yml"))
            .expect("read restored-suite workflow");
    assert!(
        workflow.contains("SUGAR_EXECUTION_ROUTE: local-ambient"),
        "a runner-local ambient dependency installation must declare that route explicitly"
    );
    assert!(
        !workflow.contains("bin/sugarbin run --host bx"),
        "the battleaxe runner container must not invent a nested SSH route back to bx"
    );
    assert!(
        !workflow.contains("bcargo-python-kit-env"),
        "the retired wrapper provisioning target must not return through CI"
    );
}
