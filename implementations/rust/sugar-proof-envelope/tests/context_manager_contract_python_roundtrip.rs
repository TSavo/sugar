use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_ir_types::Sort;
use sugar_proof_envelope::{AnchoredMember, ExitDispositionV1, Member, MementoCid};

#[test]
fn python_published_cm_contract_decodes_as_sealed_typed_rust_member() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let python_path = repo.join("implementations/python/sugar-lift-py-tests/src");
    let program = r#"
import json
from sugar_lift_py_tests.context_manager_contract import publish_never_suppresses_context_manager_contract
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.kit_rpc import ImportSignatureV1
from sugar_lift_py_tests.signing import Signer
m = publish_never_suppresses_context_manager_contract(bridge_source_symbol='context-manager:fixture_python.never_closing', import_signature=ImportSignatureV1(formals=(), sorts=()), enter_result_sort=PrimitiveSort('Value'), source_warrants=('blake3-512:' + 'a' * 128,), signer=Signer(bytes(range(32)), 'fixture-python-kit'), declared_at='2026-07-22T00:00:00.000Z')
print(json.dumps({'cid': m.cid, 'member': json.loads(m.canonical_bytes)}))
"#;
    let output = Command::new("python3")
        .env("PYTHONPATH", python_path)
        .arg("-c")
        .arg(program)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let wire: Json = serde_json::from_slice(&output.stdout).unwrap();
    let cid = MementoCid::try_parse(wire["cid"].as_str().unwrap().to_string()).unwrap();
    let anchored =
        AnchoredMember::new(cid, wire["member"].clone()).expect("CID and signature verify");
    let Member::ContextManagerContract(cm) = Member::from_value(anchored.envelope()).unwrap()
    else {
        panic!("dedicated CM member")
    };
    assert_eq!(
        cm.bridge_source_symbol,
        "context-manager:fixture_python.never_closing"
    );
    assert!(cm.import_signature.formals.is_empty());
    assert!(cm.import_signature.sorts.is_empty());
    assert_eq!(
        cm.semantics.enter.sort,
        Sort::Primitive {
            name: "Value".to_string()
        }
    );
    assert_eq!(
        cm.semantics.exit.disposition,
        ExitDispositionV1::NeverSuppresses
    );
    assert_eq!(cm.source_warrants.len(), 1);
}

#[test]
fn stale_payload_cid_stays_loud() {
    let zero = format!("blake3-512:{}", "0".repeat(128));
    let member = serde_json::json!({
        "envelope": {}, "metadata": {},
        "header": {
            "schemaVersion":"1.2", "kind":"context-manager-contract",
            "cid": zero, "payloadCid": zero,
            "bridgeSourceSymbol":"context-manager:m.n",
            "importSignature":{"formals":[],"sorts":[]},
            "payload":{"kind":"context-manager-semantics","schemaVersion":"1","enter":{"completion":"total","result":{"kind":"projection","projection":"enter_result","sort":{"kind":"primitive","name":"Value"}}},"exit":{"completion":"total","disposition":{"kind":"never-suppresses"}}},
            "sourceWarrants": [], "inputCids": []
        }
    });
    let error = Member::from_value(&member).expect_err("stale CID must be loud");
    assert!(error.to_string().contains("payload CID"), "{error}");
}
