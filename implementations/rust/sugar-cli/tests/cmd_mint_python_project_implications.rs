// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

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

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-py-implications-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn write_executable(path: &Path, body: &str) {
    use std::io::Write as _;
    {
        let mut file = fs::File::create(path).expect("create script");
        file.write_all(body.as_bytes()).expect("write script");
        file.sync_all().expect("sync script");
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path).expect("stat script").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod script");
    }
}

fn python_wrapper(module: &str, function: &str, src_dir: PathBuf) -> PathBuf {
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let script = std::env::temp_dir().join(format!(
        "sugar-python-implication-{}-{}.sh",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    let body = format!(
        "#!/bin/sh\nexec python3 -c \"import sys; sys.path.insert(0, '{}'); from {module} import {function}; {function}()\"\n",
        src_dir.display()
    );
    write_executable(&script, &body);
    script
}

fn python_verify_wrapper() -> PathBuf {
    python_wrapper(
        "sugar_lift_python_source.verify_rpc",
        "run_rpc",
        repo_root()
            .join("implementations")
            .join("python")
            .join("sugar-lift-python-source")
            .join("src"),
    )
}

fn python_implications_wrapper() -> PathBuf {
    python_wrapper(
        "sugar_lift_py_tests.lsp",
        "main",
        repo_root()
            .join("implementations")
            .join("python")
            .join("sugar-lift-py-tests")
            .join("src"),
    )
}

fn stage_python_project(producer: &Path, consumer: &Path) -> PathBuf {
    let project = unique_dir("project");
    fs::write(
        project.join("app.py"),
        r#"def caller(x: int) -> int:
    return callee(x)


def callee(x: int) -> int:
    return x + 1
"#,
    )
    .expect("write app.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-contracts")).unwrap();
    fs::create_dir_all(sugar.join("lift").join("python-implications")).unwrap();
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-contracts"
surface = "python-contracts"

[[plugins]]
name = "python-implications"
surface = "python-implications"
"#,
    )
    .expect("write config.toml");

    fs::write(
        sugar
            .join("lift")
            .join("python-contracts")
            .join("manifest.toml"),
        format!(
            "name = \"python-contracts\"\ncommand = [\"{}\", \"--rpc\"]\nworking_dir = \".\"\n",
            producer.display()
        ),
    )
    .expect("write python-contracts manifest");
    fs::write(
        sugar
            .join("lift")
            .join("python-implications")
            .join("manifest.toml"),
        format!(
            "name = \"python-implications\"\ncommand = [\"{}\", \"--rpc\"]\nworking_dir = \".\"\nmethod = \"sugar.plugin.lift_implications\"\nphase = \"consumer\"\n",
            consumer.display()
        ),
    )
    .expect("write python-implications manifest");

    project
}

#[test]
fn python_implication_consumer_mints_bridge_from_manifest_rpc() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping Python implication consumer test");
        return;
    }
    let producer = python_verify_wrapper();
    let consumer = python_implications_wrapper();
    let project = stage_python_project(&producer, &consumer);
    let out_dir = unique_dir("out");

    let output = Command::new(sugar_bin())
        .arg("mint")
        .arg("--project")
        .arg(&project)
        .arg("--out")
        .arg(&out_dir)
        .arg("--quiet")
        .arg("--json")
        .output()
        .expect("spawn sugar mint");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "python implication mint should dispatch producer lift then consumer lift_implications\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        !stdout.contains("no-contract-for-callee"),
        "matched callee call should not surface a lift-gap\nstdout:\n{stdout}"
    );

    let proof_files: Vec<PathBuf> = fs::read_dir(&out_dir)
        .expect("read out dir")
        .filter_map(|entry| {
            let path = entry.expect("out dir entry").path();
            (path.extension().and_then(|s| s.to_str()) == Some("proof")).then_some(path)
        })
        .collect();
    assert_eq!(
        proof_files.len(),
        1,
        "producer + Python implication consumer should conjoin into one proof"
    );

    let pool = sugar_verifier::load_all_proofs::run_with_files(
        Path::new("/no-such-project"),
        &proof_files,
    );
    assert!(
        pool.load_errors.is_empty(),
        "conjoined Python proof must load cleanly: {:?}",
        pool.load_errors
    );
    let saw_implication_bridge = pool.mementos.keys().any(|cid| {
        pool.member_kind(cid) == Some("bridge")
            && pool
                .member_field(cid, "sourceSymbol")
                .and_then(|v| v.as_str())
                == Some("callee")
            && pool.member_field(cid, "notes").and_then(|v| v.as_str())
                == Some("implication-lifted callsite bridge")
    });
    assert!(
        saw_implication_bridge,
        "Python consumer must contribute the implication-lifted callsite bridge"
    );

    let _ = fs::remove_dir_all(&project);
    let _ = fs::remove_dir_all(&out_dir);
}
