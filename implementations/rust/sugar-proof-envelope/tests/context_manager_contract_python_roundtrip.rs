use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_ir_types::Sort;
use sugar_proof_envelope::{AnchoredMember, Member, MementoCid};

#[test]
fn python_published_cm_contract_decodes_as_sealed_typed_rust_member() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf();
    let python_path = repo.join("implementations/python/sugar-lift-py-tests/src");
    let program = r#"
import json
from sugar_lift_py_tests.context_manager_contract import publish_never_suppresses_context_manager_contract
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer
m = publish_never_suppresses_context_manager_contract(name='NeverClosingManager', kit='fixture-python-kit', bridge_source_symbol='context-manager:fixture_python.never_closing', constructor_formals=(), constructor_sorts=(), enter_result_sort=PrimitiveSort('Value'), source_warrants=(), signer=Signer(bytes(range(32)), 'fixture-python-kit'), declared_at='2026-07-22T00:00:00.000Z')
print(json.dumps({'cid': m.cid, 'member': json.loads(m.canonical_bytes)}))
"#;
    let output = Command::new("python3")
        .env("PYTHONPATH", python_path)
        .arg("-c")
        .arg(program)
        .output()
        .expect("run Python CM-contract publisher");
    assert!(
        output.status.success(),
        "Python publisher failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let wire: Json = serde_json::from_slice(&output.stdout).expect("publisher JSON");
    let cid = MementoCid::try_parse(wire["cid"].as_str().expect("member CID").to_string())
        .expect("typed member CID");
    let anchored = AnchoredMember::new(cid, wire["member"].clone())
        .expect("attestation CID and signature verify");
    let member = Member::from_value(anchored.envelope()).expect("typed CM contract decoder");
    let Member::ContextManagerContract(cm) = member else {
        panic!("expected dedicated CM-contract member")
    };
    assert_eq!(cm.name, "NeverClosingManager");
    assert_eq!(cm.kit, "fixture-python-kit");
    assert_eq!(
        cm.bridge_source_symbol,
        "context-manager:fixture_python.never_closing"
    );
    assert!(cm.constructor_formals.is_empty());
    assert!(cm.constructor_sorts.is_empty());
    assert_eq!(
        cm.enter_result_sort,
        Sort::Primitive {
            name: "Value".to_string()
        }
    );
    assert!(cm.source_warrants.is_empty());
}

#[test]
fn stale_content_cid_stays_loud() {
    let member = serde_json::json!({
        "envelope": {}, "metadata": {},
        "header": {
            "schemaVersion":"1", "kind":"context-manager-contract",
            "cid": format!("blake3-512:{}", "0".repeat(128)),
            "name":"N", "kit":"K", "bridgeSourceSymbol":"context-manager:m.n",
            "constructorSignature":{"formals":[],"sorts":[]},
            "enter":{"outcome":"total","result":{"kind":"projection","projection":"enter_result","sort":{"kind":"primitive","name":"Value"}}},
            "exit":{"outcome":"total","disposition":{"kind":"never-suppresses"}},
            "sourceWarrants": []
        }
    });
    let error = Member::from_value(&member).expect_err("stale CID must be loud");
    assert!(error.to_string().contains("content CID"), "{error}");
}
