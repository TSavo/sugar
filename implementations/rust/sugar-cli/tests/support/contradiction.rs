// SPDX-License-Identifier: Apache-2.0

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::Command;

use serde_json::{json, Value as Json};
use sugar_canonicalizer::{blake3_512_of, encode_jcs};
use sugar_proof_envelope::{
    build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
};

fn int_sort() -> Json {
    json!({"kind": "primitive", "name": "Int"})
}

fn int_const(n: i64) -> Json {
    json!({"kind": "const", "value": n, "sort": int_sort()})
}

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
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

fn flat_member(mut env: Json) -> (String, Vec<u8>) {
    if let Json::Object(map) = &mut env {
        map.remove("cid");
        map.remove("producerSignature");
    }
    let canonical = json_to_canonical_jcs(&env);
    let cid = blake3_512_of(canonical.as_bytes());
    (cid, canonical.into_bytes())
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
        declared_at: "2026-05-29T00:00:00.000Z".into(),
    });
    let hex = built.cid.strip_prefix("blake3-512:").unwrap();
    fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    built.cid
}

pub fn plant_contradictory_implication_proof(
    proof_dir: &Path,
    source_layer: &str,
    target_layer: &str,
    symbol_prefix: &str,
) -> String {
    let producer = format!("{symbol_prefix}_produces_zero");
    let consumer = format!("{symbol_prefix}_requires_positive");
    let callsite = format!("{symbol_prefix}_contradictory_callsite");

    let producer_env = json!({
        "evidence": {
            "kind": "contract",
            "body": {
                "contractName": producer,
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
                "contractName": consumer,
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
                "contractName": callsite,
                "inv": {
                    "kind": "atomic",
                    "name": "observed",
                    "args": [{
                        "kind": "ctor",
                        "name": consumer,
                        "args": [{
                            "kind": "ctor",
                            "name": producer,
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
                "sourceSymbol": producer,
                "sourceLayer": source_layer,
                "targetContractCid": producer_cid,
                "targetLayer": target_layer
            }
        }
    });
    let (producer_bridge_cid, producer_bridge_bytes) = flat_member(producer_bridge_env);

    let consumer_bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": consumer,
                "sourceLayer": source_layer,
                "targetContractCid": consumer_cid,
                "targetLayer": target_layer
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
    write_proof(
        proof_dir,
        &format!("@sugar/{symbol_prefix}-contradictory-implication"),
        members,
    )
}

pub fn run_prove_json_with_code(sugar_bin: &Path, project: &Path) -> (Json, i32) {
    let output = Command::new(sugar_bin)
        .arg("prove")
        .arg(project)
        .arg("--json")
        .output()
        .expect("spawn sugar prove");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let report = serde_json::from_str(&stdout)
        .unwrap_or_else(|error| panic!("prove JSON parse failed: {error}\nstdout: {stdout}"));
    (report, output.status.code().unwrap_or(-1))
}

pub fn assert_green_proves_one_bridge(report: &Json, code: i32) {
    assert_eq!(
        code, 0,
        "base project must prove before planting contradiction; report: {report}"
    );
    assert_eq!(
        report["violations"], 0,
        "base project must have no violations before planting contradiction; report: {report}"
    );
    let rows = report["rows"].as_array().expect("rows");
    let bridge_rows: Vec<_> = rows
        .iter()
        .filter(|row| {
            row["bridge"]
                .as_str()
                .map(|bridge| !bridge.is_empty())
                .unwrap_or(false)
        })
        .collect();
    assert_eq!(
        bridge_rows.len(),
        1,
        "base project must prove exactly one language bridge before planting contradiction; report: {report}"
    );
    let row = bridge_rows[0];
    assert_eq!(
        row["status"], "discharged",
        "base project bridge must discharge before planting contradiction; row: {row}; report: {report}"
    );
    assert_ne!(
        row["dischargeMethod"], "vacuous",
        "base project bridge must not discharge vacuously before planting contradiction; row: {row}; report: {report}"
    );
}

pub fn assert_prove_refuses_contradiction(report: &Json, code: i32, expected_bridge: &str) {
    assert_eq!(
        code, 1,
        "planted contradictory implication must exit 1; report: {report}"
    );
    assert_eq!(
        report["violations"], 1,
        "planted contradictory implication must report exactly one violation; report: {report}"
    );
    assert!(
        report["totalCallsites"].as_u64().unwrap_or(0) > 1,
        "contradiction test must include the language route plus the planted implication; report: {report}"
    );
    assert!(
        report["rows"]
            .as_array()
            .expect("rows")
            .iter()
            .any(|row| row["bridge"] == expected_bridge && row["status"] == "unsatisfied"),
        "{expected_bridge} must be unsatisfied; report: {report}"
    );
}
