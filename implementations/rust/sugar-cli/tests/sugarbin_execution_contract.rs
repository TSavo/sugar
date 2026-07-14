use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli workspace root")
        .to_path_buf()
}

fn duplicate_remote_ownership(root: &Path) -> Vec<String> {
    fn collect_files(path: &Path, files: &mut Vec<PathBuf>) {
        if path.is_file() {
            files.push(path.to_path_buf());
            return;
        }
        let Ok(entries) = std::fs::read_dir(path) else {
            return;
        };
        for entry in entries {
            let entry = entry.unwrap_or_else(|error| panic!("walk {}: {error}", path.display()));
            collect_files(&entry.path(), files);
        }
    }

    let mut files = Vec::new();
    for resident in ["bin", "scripts", ".github/workflows", "Makefile"] {
        collect_files(&root.join(resident), &mut files);
    }
    files.sort();

    let mut offenders = Vec::new();
    for path in files {
        let relative = path
            .strip_prefix(root)
            .expect("resident below root")
            .to_string_lossy()
            .replace('\\', "/");
        if relative == "bin/lib/sugar-bx.sh" {
            continue;
        }
        let body = std::fs::read_to_string(&path)
            .unwrap_or_else(|error| panic!("read {}: {error}", path.display()));
        for shape in [
            "sync_paths=(",
            "exclude_args=(",
            "rsync -azR",
            "bcargo-python-kit-env",
        ] {
            if body.contains(shape) {
                offenders.push(format!("{relative}: owns `{shape}`"));
            }
        }
        let words = body.split_whitespace().collect::<Vec<_>>().join(" ");
        if words.contains("find /home/tsavo/remote") && words.contains("sugar-bcargo-*") {
            offenders.push(format!("{relative}: owns `remote-root-reaper`"));
        }
    }
    offenders
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
    let offenders = duplicate_remote_ownership(&root);
    assert!(
        offenders.is_empty(),
        "R={} duplicate remote provisioning residents remain outside bin/lib/sugar-bx.sh:\n{}\nreplacement: managed dependencies belong to sugar-build.toml Docker tasks; ambient execution never provisions",
        offenders.len(),
        offenders.join("\n")
    );
}

#[test]
fn planted_remote_reaper_owner_is_reported() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rogue = temp.path().join("scripts/rogue-reaper.sh");
    std::fs::create_dir_all(rogue.parent().expect("rogue parent")).expect("mkdir scripts");
    std::fs::write(
        &rogue,
        "find /home/tsavo/remote \\\n+          -name 'sugar-bcargo-*' -mtime +2 -exec rm -rf {} +\n",
    )
    .expect("write rogue reaper");

    let offenders = duplicate_remote_ownership(temp.path());
    assert_eq!(offenders.len(), 1, "offenders={offenders:?}");
    assert!(offenders[0].contains("scripts/rogue-reaper.sh"));
    assert!(offenders[0].contains("remote-root-reaper"));
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
        workflow.contains(
            "SUGAR_AMBIENT_DEPENDENCY_OWNER: .github/workflows/restored-suite-scoreboard.yml"
        ),
        "an ambient CI route must name its dependency owner"
    );
    for required in ["z3 --version", "/usr/bin/time --version", "b3sum --version"] {
        assert!(
            workflow.contains(required),
            "ambient restored-suite route lacks loud dependency receipt: {required}"
        );
    }
    assert!(
        !workflow.contains("bin/sugarbin run --host bx"),
        "the battleaxe runner container must not invent a nested SSH route back to bx"
    );
    assert!(
        !workflow.contains("bcargo-python-kit-env"),
        "the retired wrapper provisioning target must not return through CI"
    );
}
