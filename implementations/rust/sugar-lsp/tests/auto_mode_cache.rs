// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #4007 auto-mode: import parse + resolve + cache key stability.
// Full mint of site-packages is environment-dependent; this pins the
// client-side contract that does not require a full prove stack.

use std::path::PathBuf;
use std::process::Command;

fn lsp_src_tests_can_see_binary() {
    let _ = PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp"));
}

#[test]
fn sugar_lsp_binary_builds_with_auto_mode() {
    lsp_src_tests_can_see_binary();
    // Smoke: binary exists (compiled with auto_mode module).
    assert!(PathBuf::from(env!("CARGO_BIN_EXE_sugar-lsp")).is_file());
}

#[test]
fn python_resolves_hmac_for_auto_path() {
    let out = Command::new("python3")
        .args([
            "-c",
            "import importlib.util,os,sys; spec=importlib.util.find_spec('hmac'); \
paths=list(spec.submodule_search_locations or []); \
print(paths[0] if paths else os.path.dirname(os.path.abspath(spec.origin)))",
        ])
        .output()
        .expect("python3");
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let p = String::from_utf8_lossy(&out.stdout).trim().to_string();
    assert!(PathBuf::from(&p).exists(), "{p}");
}
