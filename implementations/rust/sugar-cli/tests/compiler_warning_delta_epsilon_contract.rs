use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

#[test]
fn compiler_warning_delta_epsilon_test_reports_r_and_replacement_plan() {
    let root = repo_root();
    let temp = tempfile::tempdir().expect("tempdir");
    let input = temp.path().join("warnings.jsonl");
    let mut file = std::fs::File::create(&input).expect("create warning fixture");

    writeln!(
        file,
        "{}",
        serde_json::json!({
            "reason": "compiler-message",
            "package_id": "path+file:///repo/sugar/implementations/rust/sugar-cli#0.1.0",
            "manifest_path": "/repo/sugar/implementations/rust/sugar-cli/Cargo.toml",
            "target": {
                "kind": ["bin"],
                "name": "sugar"
            },
            "message": {
                "level": "warning",
                "message": "unused import: `Instant`",
                "code": {"code": "unused_imports"},
                "spans": [{
                    "is_primary": true,
                    "file_name": "sugar-cli/src/doctor.rs",
                    "line_start": 30,
                    "column_start": 17
                }]
            }
        })
    )
    .expect("write warning fixture");

    let output = Command::new("bash")
        .arg(root.join("tests").join("compiler_warning_delta_epsilon.sh"))
        .arg("--input")
        .arg(&input)
        .arg("--epsilon")
        .arg("compiler_warnings=-1")
        .output()
        .expect("run compiler warning delta-epsilon instrument");

    assert_eq!(
        output.status.code(),
        Some(1),
        "the instrument must stay red while warning R is nonzero; stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("R.compiler_warnings.current = 1"),
        "stdout must report current R; got:\n{stdout}"
    );
    assert!(
        stdout.contains("Delta R: compare this run to the previous instrument run"),
        "stdout must explain that Delta R is read between runs; got:\n{stdout}"
    );
    assert!(
        stdout.contains("Epsilon R.predicted = compiler_warnings=-1"),
        "stdout must carry the predicted epsilon for this shot; got:\n{stdout}"
    );
    assert!(
        stdout.contains("sugar-cli/src/doctor.rs:30:17"),
        "stdout must print the offender locus; got:\n{stdout}"
    );
    assert!(
        stdout.contains("replacement_plan: remove the unused import or wire it into live code"),
        "stdout must print an actionable replacement plan; got:\n{stdout}"
    );
}
