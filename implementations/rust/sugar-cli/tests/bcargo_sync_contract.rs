use std::fs;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

#[test]
fn bcargo_syncs_ir_compiler_manifests() {
    let root = repo_root();
    let bcargo = fs::read_to_string(root.join("bin").join("bcargo")).expect("read bin/bcargo");

    assert!(
        bcargo.contains("sync_dir .sugar/ir-compilers"),
        "bcargo must sync .sugar/ir-compilers so remote verifier runs can resolve manifest-backed ProofIR compiler dialects"
    );
}
