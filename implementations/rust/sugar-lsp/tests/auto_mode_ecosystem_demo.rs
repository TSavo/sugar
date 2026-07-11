// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Handoff O — auto-mode ecosystem demo.
// Consumer imports pip-installed `itsdangerous`; auto-mode seals cold import
// (shipped-first → disk → mint). Second call is free (process/disk CID).

use std::path::PathBuf;
use std::process::Command;

use sugar_lsp::auto_mode::{
    auto_lift_cold_imports_into_pool, auto_lift_enabled, clear_auto_cache_for_tests,
    extract_top_level_imports, resolve_module_path,
};
use sugar_verifier::types::MementoPool;

fn python_bin() -> PathBuf {
    if let Ok(py) = std::env::var("PYTHON") {
        if !py.is_empty() {
            return PathBuf::from(py);
        }
    }
    if let Ok(py) = std::env::var("ITSDANGEROUS_LOGO_VENV") {
        let cand = PathBuf::from(py).join("bin/python");
        if cand.is_file() {
            return cand;
        }
    }
    PathBuf::from("python3")
}

fn itsdangerous_available() -> bool {
    let out = Command::new(python_bin())
        .args(["-c", "import itsdangerous; print(itsdangerous.__file__)"])
        .output();
    matches!(out, Ok(o) if o.status.success())
}

#[test]
fn ecosystem_demo_auto_seals_itsdangerous_cold_import() {
    if !auto_lift_enabled() {
        // Force-on for demo even if env disabled elsewhere.
        std::env::set_var("SUGAR_LSP_AUTO_LIFT", "1");
    }
    if !itsdangerous_available() {
        eprintln!("skip: itsdangerous not importable in PYTHON");
        return;
    }

    clear_auto_cache_for_tests();

    let module_root = resolve_module_path("itsdangerous").expect("resolve itsdangerous");
    assert!(
        module_root.exists(),
        "itsdangerous path missing: {}",
        module_root.display()
    );

    let project = std::env::temp_dir().join(format!(
        "sugar-auto-eco-demo-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(project.join(".sugar")).unwrap();

    let consumer = r#"
import itsdangerous

def test_token():
    s = itsdangerous.URLSafeSerializer("secret")
    # consumer testimony — dep is pip-installed, no vendor .proof shipped
    assert s.dumps({"u": 1}) is not None
"#;
    assert_eq!(
        extract_top_level_imports(consumer),
        vec!["itsdangerous".to_string()]
    );

    let mut pool = MementoPool::default();
    let logs1 = auto_lift_cold_imports_into_pool(&project, consumer, &mut pool);
    let joined1 = logs1.join("\n");
    eprintln!("auto-lift pass1:\n{joined1}");
    assert!(
        logs1.iter().any(|l| l.contains("itsdangerous")),
        "expected itsdangerous in logs: {joined1}"
    );
    // Cold seal happened (minted / empty / shipped / disk) — not skipped as warm first pass.
    assert!(
        !logs1.iter().any(|l| l.contains("warm (pool/sealed)")),
        "first pass should be cold: {joined1}"
    );

    // Disk durable cache under project
    let auto_dir = project.join(".sugar/imports/auto");
    let disk_proofs: Vec<_> = std::fs::read_dir(&auto_dir)
        .map(|rd| {
            rd.flatten()
                .filter(|e| e.path().extension().and_then(|x| x.to_str()) == Some("proof"))
                .map(|e| e.path())
                .collect()
        })
        .unwrap_or_default();
    // Empty mint may still write nothing if zero contracts — process still seals module.
    // Second pass must skip as warm/sealed or process-cache.
    let mut pool2 = MementoPool::default();
    let logs2 = auto_lift_cold_imports_into_pool(&project, consumer, &mut pool2);
    let joined2 = logs2.join("\n");
    eprintln!("auto-lift pass2:\n{joined2}");
    assert!(
        logs2
            .iter()
            .any(|l| l.contains("warm") || l.contains("ProcessCache") || l.contains("sealed")),
        "second pass should be free/warm: {joined2}"
    );

    eprintln!(
        "module_root={} disk_proofs={}",
        module_root.display(),
        disk_proofs.len()
    );
    let _ = std::fs::remove_dir_all(&project);
}
