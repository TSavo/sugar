// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

#[test]
fn term_emit_cli_writes_statement_macro_as_partial_loss_term_json() {
    let dir = unique_temp_dir();
    fs::create_dir_all(&dir).expect("create temp dir");
    let source_path = dir.join("bad.rs");
    let output_path = dir.join("bad.term.json");
    fs::write(
        &source_path,
        r#"
            fn bad() {
                println!("not representable");
            }
        "#,
    )
    .expect("write source");

    let output = Command::new(env!("CARGO_BIN_EXE_sugar-walk-emit"))
        .arg("term")
        .arg(&source_path)
        .arg("bad")
        .arg(&output_path)
        .output()
        .expect("run sugar-walk-emit");

    assert!(output.status.success());
    assert!(
        output_path.exists(),
        "partial term emission must write output"
    );
    let parsed: serde_json::Value =
        serde_json::from_slice(&fs::read(&output_path).expect("read term JSON"))
            .expect("term JSON");
    assert_eq!(
        parsed["handling"].as_str(),
        Some("handles-partially-with-loss-record")
    );
    assert!(parsed["loss_record"]
        .as_array()
        .unwrap()
        .iter()
        .any(|loss| loss["loss"] == "macro-not-expanded"));
    assert_eq!(
        parsed["term_surface"].as_str(),
        Some("macro_call:println(\"not representable\")")
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("# rust term for function=bad"),
        "unexpected stderr: {stderr}"
    );

    let _ = fs::remove_dir_all(&dir);
}

fn unique_temp_dir() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "sugar-walk-term-emit-{}-{nanos}",
        std::process::id()
    ))
}
