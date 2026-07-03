// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value as Json};
use sugar_verifier::{
    BundleScopedCallsiteKey, MementoCid, MementoPool, SourceLine, SourcePath, SourceSymbol,
    StoredMember,
};

fn crate_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before epoch")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "sugar_scoped_callsite_key_{label}_{}_{}",
        std::process::id(),
        now
    ))
}

fn memento_cid(label: &str) -> MementoCid {
    MementoCid::try_parse(label.to_string()).unwrap_or_else(|_| {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(label.as_bytes()))
            .expect("test CID must parse")
    })
}

fn insert_test_member(pool: &mut MementoPool, cid: MementoCid, envelope: Json) {
    let member = StoredMember::from_envelope(cid.clone(), &envelope).expect("member parses");
    pool.insert_verified_member_for_tests(cid, member);
}

#[test]
fn scoped_key_resolves_the_same_bridge_and_contract_body() {
    let mut pool = MementoPool::default();
    let bundle = memento_cid("caller-bundle");
    let bridge_cid = memento_cid("bridge");
    let target_cid = memento_cid("target-contract");
    let key = BundleScopedCallsiteKey::new(
        bundle,
        SourcePath::new("src/lib.rs").expect("source path"),
        SourceLine::new(42).expect("source line"),
        SourceSymbol::new("method:unwrap").expect("source symbol"),
    );
    let bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "method:unwrap",
                "targetContractCid": target_cid.to_string()
            }
        }
    });
    let contract_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "unwrap_totality",
                "post": {
                    "kind": "atomic",
                    "name": "is_ok",
                    "args": [{"kind": "var", "name": "result"}]
                }
            }
        }
    });

    insert_test_member(&mut pool, bridge_cid.clone(), bridge_env.clone());
    insert_test_member(&mut pool, target_cid.clone(), contract_env);
    pool.insert_bridge_by_callsite(key.clone(), bridge_cid.clone(), bridge_env);

    let bridge = pool
        .bridge_member_for_callsite_key(&key)
        .expect("scoped key resolves bridge");
    assert_eq!(bridge.cid(), &bridge_cid);
    assert_eq!(
        bridge.field("targetContractCid").and_then(|v| v.as_str()),
        Some(target_cid.as_str())
    );

    let verified = pool
        .verified_contract_by_cid(&target_cid)
        .expect("typed contract view resolves target");
    assert_eq!(verified.cid(), &target_cid);
    assert_eq!(
        verified.body().and_then(|body| body.get("contractName")),
        Some(&json!("unwrap_totality"))
    );
}

#[test]
fn planted_unscoped_pool_lookup_fails_to_compile() {
    let temp = unique_temp_dir("compile_fail");
    fs::create_dir_all(temp.join("src")).expect("create temp crate");
    fs::write(
        temp.join("Cargo.toml"),
        format!(
            r#"[package]
name = "s8-unscoped-pool-lookup"
version = "0.0.0"
edition = "2021"

[dependencies]
sugar-verifier = {{ path = "{}" }}
sugar-canonicalizer = {{ path = "{}" }}
"#,
            crate_root().display(),
            crate_root()
                .parent()
                .expect("rust workspace")
                .join("sugar-canonicalizer")
                .display()
        ),
    )
    .expect("write Cargo.toml");
    fs::write(
        temp.join("src/lib.rs"),
        r#"
use sugar_verifier::{MementoCid, MementoPool};

pub fn tuple_key_lookup(pool: &MementoPool, bundle: MementoCid) {
    let tuple_key = (
        bundle,
        "src/lib.rs".to_string(),
        42usize,
        "method:unwrap".to_string(),
    );
    let _ = pool.bridge_member_for_callsite_key(&tuple_key);
}

pub fn raw_string_index_lookup(pool: &MementoPool, symbol: String) {
    let _ = pool.bridges_by_callsite.get(&symbol);
}
"#,
    )
    .expect("write planted lib");

    let output = Command::new(std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string()))
        .arg("check")
        .arg("--quiet")
        .current_dir(&temp)
        .env("CARGO_TARGET_DIR", temp.join("target"))
        .output()
        .expect("run cargo check");
    let _ = fs::remove_dir_all(&temp);

    assert!(
        !output.status.success(),
        "planted unscoped pool lookup must fail to compile; stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("expected `&BundleScopedCallsiteKey`")
            || stderr.contains("field `bridges_by_callsite` of struct `MementoPool` is private")
            || stderr.contains("mismatched types"),
        "compile failure must be structural scoped-key closure, got:\n{stderr}"
    );
}
