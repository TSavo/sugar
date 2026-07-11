// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #4106 / #4107 — Download sources (Maven-class) for auto-mode.
// pip-installed itsdangerous wheel is assert-thin; sdist carries tests/.

use std::path::PathBuf;
use std::process::Command;

use sugar_lsp::auto_mode::{
    auto_lift_cold_imports_into_pool, clear_auto_cache_for_tests, download_sources_enabled,
    ensure_downloaded_sources, extract_top_level_imports,
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
    Command::new(python_bin())
        .args(["-c", "import itsdangerous"])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[test]
fn download_sources_fetches_itsdangerous_sdist_with_tests() {
    if !itsdangerous_available() {
        eprintln!("skip: itsdangerous not installed");
        return;
    }
    std::env::set_var("SUGAR_LSP_AUTO_LIFT", "1");
    std::env::set_var("SUGAR_LSP_DOWNLOAD_SOURCES", "1");
    let cache = std::env::temp_dir().join(format!(
        "sugar-sources-test-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::env::set_var("SUGAR_SOURCES_CACHE", &cache);

    assert!(download_sources_enabled());

    let (root, log) = ensure_downloaded_sources("itsdangerous").expect("download itsdangerous");
    eprintln!("log: {log}");
    assert!(root.is_dir(), "root {}", root.display());
    assert!(
        root.join("tests").is_dir(),
        "sdist must include tests/ under {}",
        root.display()
    );
    // Second call is cache
    let (root2, log2) = ensure_downloaded_sources("itsdangerous").expect("cache hit");
    assert_eq!(root, root2);
    assert!(
        log2.contains("via=cache") || log2.contains("via=pypi-sdist"),
        "log2={log2}"
    );

    let _ = std::fs::remove_dir_all(&cache);
}

#[test]
fn auto_lift_uses_downloaded_sources_origin() {
    if !itsdangerous_available() {
        eprintln!("skip: itsdangerous not installed");
        return;
    }
    std::env::set_var("SUGAR_LSP_AUTO_LIFT", "1");
    std::env::set_var("SUGAR_LSP_DOWNLOAD_SOURCES", "1");
    let cache = std::env::temp_dir().join(format!(
        "sugar-sources-lift-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::env::set_var("SUGAR_SOURCES_CACHE", &cache);
    clear_auto_cache_for_tests();

    let project = std::env::temp_dir().join(format!(
        "sugar-auto-dl-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(project.join(".sugar")).unwrap();

    let consumer = "import itsdangerous\n";
    assert_eq!(
        extract_top_level_imports(consumer),
        vec!["itsdangerous".to_string()]
    );

    let mut pool = MementoPool::default();
    let logs = auto_lift_cold_imports_into_pool(&project, consumer, &mut pool);
    let joined = logs.join("\n");
    eprintln!("logs:\n{joined}");
    assert!(
        logs.iter().any(|l| l.contains("download-sources:")),
        "expected download-sources log: {joined}"
    );
    assert!(
        logs.iter()
            .any(|l| l.contains("DownloadedSources") || l.contains("sealed via")),
        "expected seal log: {joined}"
    );

    let _ = std::fs::remove_dir_all(&project);
    let _ = std::fs::remove_dir_all(&cache);
}
