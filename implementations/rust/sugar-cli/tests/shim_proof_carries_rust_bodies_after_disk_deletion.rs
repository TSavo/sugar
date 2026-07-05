// SPDX-License-Identifier: MIT OR Apache-2.0

use std::path::PathBuf;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations dir has repo parent")
        .to_path_buf()
}

const DELETED_ORPHAN_CACHES: &[&str] = &[
    "rust-canonical-bodies-serde_json.json",
    "rust-canonical-bodies-blake3.json",
    "rust-canonical-bodies-std::io.json",
    "rust-canonical-bodies-reqwest.json",
    "rust-canonical-bodies-libsugar-rpc-cross-platform.json",
];

#[test]
fn rust_orphan_body_template_caches_stay_deleted() {
    let body_dir = repo_root()
        .join("menagerie")
        .join("rust-language-signature")
        .join("specs")
        .join("body-templates");
    for name in DELETED_ORPHAN_CACHES {
        let cache = body_dir.join(name);
        assert!(
            !cache.exists(),
            "orphan rust canonical-bodies cache {} is back on disk. Rust shim \
             bodies must be resolved inside the Rust realize kit, not by \
             reintroducing substrate-visible body-template projections.",
            cache.display()
        );
    }
}
