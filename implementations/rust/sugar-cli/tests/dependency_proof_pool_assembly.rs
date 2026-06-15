// SPDX-License-Identifier: Apache-2.0
//
// Voltron pool assembly: sugar prove must ask configured kits for the
// dependency .proof files they resolve through their own package managers, then
// union those files into the verifier pool without teaching the substrate cargo,
// npm, classpath, sys.path, or any other platform graph.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
};
use sugar_verifier::{Runner, RunnerConfig};

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-dep-proof-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": int_sort()})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn flat_member(mut env: Json) -> (String, Vec<u8>) {
    if let Json::Object(map) = &mut env {
        map.remove("cid");
        map.remove("producerSignature");
    }
    let canonical = json_to_canonical_jcs(&env);
    let cid = blake3_512_of(canonical.as_bytes());
    (cid, canonical.into_bytes())
}

fn json_to_canonical_jcs(j: &Json) -> String {
    fn to_cv(j: &Json) -> std::sync::Arc<sugar_canonicalizer::Value> {
        use sugar_canonicalizer::Value as CV;
        match j {
            Json::Null => CV::null(),
            Json::Bool(b) => CV::boolean(*b),
            Json::Number(n) => CV::integer(i128::from(n.as_i64().unwrap_or(0))),
            Json::String(s) => CV::string(s.clone()),
            Json::Array(items) => CV::array(items.iter().map(to_cv).collect()),
            Json::Object(map) => CV::object(
                map.iter()
                    .map(|(k, v)| (k.clone(), to_cv(v)))
                    .collect::<Vec<_>>(),
            ),
        }
    }
    encode_jcs(&to_cv(j))
}

fn write_proof(dir: &Path, name: &str, members: BTreeMap<String, Vec<u8>>) -> String {
    fs::create_dir_all(dir).expect("mkdir proof dir");
    let signer_seed: Ed25519Seed = [0x51u8; 32];
    let signer_pubkey = ed25519_pubkey_string(&signer_seed);
    let signer_cid = blake3_512_of(signer_pubkey.as_bytes());
    let built = build_proof_envelope(&ProofEnvelopeInput {
        name: name.to_string(),
        version: "1.0.0".into(),
        binary_cid: None,
        metadata: None,
        members,
        signer_cid,
        signer_seed,
        declared_at: "2026-05-27T00:00:00.000Z".into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    built.cid
}

fn publish_vendor_positive_contract(vendor_dir: &Path) -> (String, String, PathBuf, Vec<u8>) {
    let target_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "must_be_positive",
                "formals": ["x"],
                "formalSorts": [int_sort()],
                "pre": {
                    "kind": "atomic",
                    "name": ">=",
                    "args": [var("x"), int_const(0)]
                }
            }
        }
    });
    let (target_cid, target_bytes) = flat_member(target_env);
    let mut members = BTreeMap::new();
    members.insert(target_cid.clone(), target_bytes);
    let bundle_cid = write_proof(vendor_dir, "@vendor/must-be-positive", members);
    let proof_path = fs::read_dir(vendor_dir)
        .expect("read vendor proofs")
        .flatten()
        .map(|entry| entry.path())
        .find(|path| path.extension().and_then(|s| s.to_str()) == Some("proof"))
        .expect("vendor proof exists");
    let proof_bytes = fs::read(&proof_path).expect("read vendor proof bytes");
    (target_cid, bundle_cid, proof_path, proof_bytes)
}

fn publish_user_bridge(project_dir: &Path, target_cid: &str, target_bundle_cid: &str) {
    let source_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "user_calls_vendor",
                "inv": {
                    "kind": "atomic",
                    "name": "observed",
                    "args": [{
                        "kind": "ctor",
                        "name": "must_be_positive",
                        "args": [int_const(-1)]
                    }]
                }
            }
        }
    });
    let (source_cid, source_bytes) = flat_member(source_env);
    let bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "must_be_positive",
                "sourceLayer": "rust",
                "targetContractCid": target_cid,
                "targetProofCid": target_bundle_cid,
                "targetLayer": "rust-kit"
            }
        }
    });
    let (bridge_cid, bridge_bytes) = flat_member(bridge_env);
    let mut members = BTreeMap::new();
    members.insert(source_cid, source_bytes);
    members.insert(bridge_cid, bridge_bytes);
    write_proof(&project_dir.join(".sugar"), "@user/local-bridge", members);
}

fn publish_contradictory_implication_project() -> PathBuf {
    let project = unique_dir("contradictory-implication");
    let proof_dir = project.join(".sugar");
    fs::create_dir_all(&proof_dir).expect("mkdir proof dir");

    let producer_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "produce_zero",
                "post": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [var("result"), int_const(0)]
                }
            }
        }
    });
    let (producer_cid, producer_bytes) = flat_member(producer_env);

    let consumer_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "requires_positive",
                "formals": ["x"],
                "formalSorts": [int_sort()],
                "pre": {
                    "kind": "atomic",
                    "name": ">",
                    "args": [var("x"), int_const(0)]
                }
            }
        }
    });
    let (consumer_cid, consumer_bytes) = flat_member(consumer_env);

    let source_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": "contradictory_callsite",
                "inv": {
                    "kind": "atomic",
                    "name": "observed",
                    "args": [{
                        "kind": "ctor",
                        "name": "requires_positive",
                        "args": [{
                            "kind": "ctor",
                            "name": "produce_zero",
                            "args": []
                        }]
                    }]
                }
            }
        }
    });
    let (source_cid, source_bytes) = flat_member(source_env);

    let producer_bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "produce_zero",
                "sourceLayer": "rust",
                "targetContractCid": producer_cid,
                "targetLayer": "rust-tests"
            }
        }
    });
    let (producer_bridge_cid, producer_bridge_bytes) = flat_member(producer_bridge_env);

    let consumer_bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "requires_positive",
                "sourceLayer": "rust",
                "targetContractCid": consumer_cid,
                "targetLayer": "rust-tests"
            }
        }
    });
    let (consumer_bridge_cid, consumer_bridge_bytes) = flat_member(consumer_bridge_env);

    let mut members = BTreeMap::new();
    members.insert(producer_cid, producer_bytes);
    members.insert(consumer_cid, consumer_bytes);
    members.insert(source_cid, source_bytes);
    members.insert(producer_bridge_cid, producer_bridge_bytes);
    members.insert(consumer_bridge_cid, consumer_bridge_bytes);
    write_proof(&proof_dir, "@test/contradictory-implication", members);
    project
}

fn install_dependency_proof_stub(project_dir: &Path, proof_cid: &str, proof_bytes: &[u8]) {
    let bin = project_dir.join("resolve-deps-stub.sh");
    let proof_bytes_base64 = BASE64.encode(proof_bytes);
    fs::write(
        &bin,
        format!(
            "#!/bin/sh\nwhile IFS= read -r line; do\n  case \"$line\" in\n    *resolve_dependency_proofs*) echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{\"proofs\":[{{\"cid\":\"{}\",\"bytes_base64\":\"{}\",\"source\":\"stub-package-proof\"}}]}}}}' ;;\n    *shutdown*) echo '{{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":null}}'; exit 0 ;;\n    *) echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{{}}}}' ;;\n  esac\ndone\n",
            proof_cid, proof_bytes_base64
        ),
    )
    .expect("write stub");
    let manifest_dir = project_dir.join(".sugar").join("lift").join("rust");
    fs::create_dir_all(&manifest_dir).expect("mkdir manifest");
    fs::write(
        manifest_dir.join("manifest.toml"),
        format!(
            "name = \"rust-dependency-proof-stub\"\nlibrary_tag = \"test\"\ncommand = [\"/bin/sh\", \"{}\"]\nworking_dir = \".\"\n",
            bin.display()
        ),
    )
    .expect("write manifest");
    fs::write(
        project_dir.join(".sugar").join("config.toml"),
        "[[plugins]]\nname = \"rust-dependency-proof-stub\"\nkind = \"lift\"\nsurface = \"rust\"\n",
    )
    .expect("write config");
    sugar_cli::kit_dispatch::reset_kit_dispatch_registry_cache_for_tests();
}

fn z3_available() -> bool {
    std::process::Command::new("z3")
        .arg("-version")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

#[test]
fn dependency_rpc_union_makes_vendor_contract_reachable() {
    let root = unique_dir("reachable");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (target_cid, bundle_cid, proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    publish_user_bridge(&project, &target_cid, &bundle_cid);
    install_dependency_proof_stub(&project, &bundle_cid, &proof_bytes);
    fs::remove_file(&proof_path).expect("remove dependency proof path after kit reads it");

    let dependency_proofs = sugar_cli::kit_dispatch::dependency_proofs_via_rpc(&project)
        .expect("resolve dependency proofs");
    assert_eq!(dependency_proofs.len(), 1);
    assert_eq!(
        dependency_proofs[0].expected_cid.as_deref(),
        Some(bundle_cid.as_str())
    );

    let runner = Runner::new(RunnerConfig {
        project_root: project.clone(),
        extra_proofs: dependency_proofs,
        ..Default::default()
    });
    let (pool, _callsites) = runner.run_load_and_enumerate();
    assert!(
        pool.mementos.get(&target_cid).is_some(),
        "vendor contract {target_cid} must be present after dependency proof assembly"
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn voltron_pool_refuses_cross_dependency_violation() {
    if !z3_available() {
        eprintln!("SKIP voltron_pool_refuses_cross_dependency_violation: z3 not on PATH");
        return;
    }

    let root = unique_dir("e2e");
    let project = root.join("user");
    let vendor = root.join("vendor");
    fs::create_dir_all(project.join(".sugar")).expect("mkdir project");
    let (target_cid, bundle_cid, proof_path, proof_bytes) =
        publish_vendor_positive_contract(&vendor);
    publish_user_bridge(&project, &target_cid, &bundle_cid);
    install_dependency_proof_stub(&project, &bundle_cid, &proof_bytes);
    fs::remove_file(&proof_path).expect("remove dependency proof path after kit reads it");

    let output = std::process::Command::new(env!("CARGO_BIN_EXE_sugar"))
        .arg("prove")
        .arg(&project)
        .arg("--z3")
        .arg("z3")
        .arg("--quiet")
        .output()
        .expect("run sugar prove");
    assert_eq!(
        output.status.code(),
        Some(1),
        "cross-dependency bridge to must_be_positive(-1) must be refused\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn prove_reports_violation_for_contradictory_implication() {
    if !z3_available() {
        eprintln!("SKIP prove_reports_violation_for_contradictory_implication: z3 not on PATH");
        return;
    }

    let project = publish_contradictory_implication_project();
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_sugar"))
        .arg("prove")
        .arg(&project)
        .arg("--z3")
        .arg("z3")
        .arg("--json")
        .output()
        .expect("run sugar prove");

    assert_eq!(
        output.status.code(),
        Some(1),
        "contradictory implication must be a proof violation\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    let report: Json =
        serde_json::from_str(&stdout).unwrap_or_else(|e| panic!("parse prove JSON: {e}\n{stdout}"));
    assert_eq!(report["violations"], 1, "report: {report}");
    assert!(
        report["rows"]
            .as_array()
            .expect("rows")
            .iter()
            .any(|row| row["bridge"] == "requires_positive"
                && row["status"] == "unsatisfied"
                && row["reason"].as_str().unwrap_or("").contains("sat")),
        "requires_positive(produce_zero()) should violate `produce_zero.post -> requires_positive.pre`: {report}"
    );

    let _ = fs::remove_dir_all(project);
}
