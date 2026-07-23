use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_ir_types::Sort;
use sugar_proof_envelope::{
    AnchoredMember, CallParameterV1, ContextManagerSemanticsV1, EffectBoundaryBindingV1,
    EffectBoundaryModeV1, EffectKindV1, ExitDispositionV1, ImportSignatureV2, Member, MementoCid,
    ParameterPassingV1,
};

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
from sugar_lift_py_tests.context_manager_contract import ImportSignatureV2
from sugar_lift_py_tests.signing import Signer
m = publish_never_suppresses_context_manager_contract(bridge_source_symbol='context-manager:fixture_python.never_closing', import_signature=ImportSignatureV2(parameters=()), enter_result_sort=PrimitiveSort('Value'), source_warrants=('blake3-512:' + 'a' * 128,), signer=Signer(bytes(range(32)), 'fixture-python-kit'), declared_at='2026-07-22T00:00:00.000Z')
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
    assert!(cm.import_signature.parameters.is_empty());
    assert_eq!(
        sugar_proof_envelope::context_manager_semantics_v1_to_json(&cm.semantics),
        wire["member"]["header"]["payload"]
    );
    let ContextManagerSemanticsV1::ProtocolResource(resource) = cm.semantics else {
        panic!("protocol resource semantics")
    };
    assert_eq!(
        resource.enter.sort,
        Sort::Primitive {
            name: "Value".to_string()
        }
    );
    assert_eq!(
        resource.exit.disposition,
        ExitDispositionV1::NeverSuppresses
    );
    assert_eq!(cm.source_warrants.len(), 1);
}

#[test]
fn python_effect_boundary_decodes_by_authenticated_formal_positions() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let python_path = repo.join("implementations/python/sugar-lift-py-tests/src");
    let program = r#"
import json
from sugar_lift_py_tests.context_manager_contract import *
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer
signature = ImportSignatureV2((
    CallParameterV1('expected_exception', PrimitiveSort('Value'), PositionalOrKeywordV1(), True),
    CallParameterV1('match', PrimitiveSort('String'), KeywordOnlyV1(), False),
))
semantics = EffectBoundarySemanticsV1(
    ExpectsModeV1(), RaiseEffectKindV1(), FormalArgumentProjectionV1(0),
    OptionalFormalArgumentProjectionV1(1), ExceptionInfoBindingV1(),
)
m = publish_effect_boundary_context_manager_contract(
    bridge_source_symbol='context-manager:any_provider.renamed',
    import_signature=signature,
    mode=semantics.mode,
    effect_kind=semantics.effect_kind,
    expected_type_operand=semantics.expected_type_operand,
    message_pattern_operand=semantics.message_pattern_operand,
    binding=semantics.binding,
    source_warrants=(), signer=Signer(bytes(range(32)), 'fixture-provider'),
    declared_at='2026-07-23T00:00:00.000Z',
)
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
    assert!(!output
        .stdout
        .windows(b"ValueError".len())
        .any(|window| window == b"ValueError"));
    let cid = MementoCid::try_parse(wire["cid"].as_str().unwrap().to_string()).unwrap();
    let anchored =
        AnchoredMember::new(cid, wire["member"].clone()).expect("CID and signature verify");
    let Member::ContextManagerContract(cm) = Member::from_value(anchored.envelope()).unwrap()
    else {
        panic!("CM member")
    };
    assert_eq!(cm.import_signature.parameters.len(), 2);
    assert_eq!(
        sugar_proof_envelope::context_manager_semantics_v1_to_json(&cm.semantics),
        wire["member"]["header"]["payload"]
    );
    let ContextManagerSemanticsV1::EffectBoundary(effect) = cm.semantics else {
        panic!("effect boundary")
    };
    assert_eq!(effect.mode, EffectBoundaryModeV1::Expects);
    assert_eq!(effect.effect_kind, EffectKindV1::Raise);
    assert_eq!(effect.expected_type_operand.index, 0);
    assert_eq!(effect.binding, EffectBoundaryBindingV1::ExceptionInfo);
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
            "importSignature":{"parameters":[]},
            "payload":{"kind":"protocol-resource","schemaVersion":"1","enter":{"completion":{"kind":"total"},"result":{"kind":"projection","projection":"enter-result","sort":{"kind":"primitive","name":"Value"}}},"exit":{"completion":{"kind":"total"},"disposition":{"kind":"never-suppresses"}}},
            "sourceWarrants": [], "inputCids": []
        }
    });
    let error = Member::from_value(&member).expect_err("stale CID must be loud");
    assert!(error.to_string().contains("payload CID"), "{error}");
}

#[test]
fn unknown_effect_boundary_field_and_selector_role_stay_loud() {
    let signature = ImportSignatureV2 {
        parameters: vec![
            CallParameterV1 {
                name: "expected_exception".into(),
                sort: Sort::Primitive {
                    name: "Value".into(),
                },
                passing: ParameterPassingV1::PositionalOrKeyword,
                required: true,
            },
            CallParameterV1 {
                name: "match".into(),
                sort: Sort::Primitive {
                    name: "String".into(),
                },
                passing: ParameterPassingV1::KeywordOnly,
                required: false,
            },
        ],
    };
    let mut payload = serde_json::json!({
        "kind":"effect-boundary", "schemaVersion":"1", "mode":{"kind":"expects"},
        "matcher":{"effectKind":{"kind":"raise"},"expectedTypeOperand":{"kind":"formal-argument","index":0},"messagePatternOperand":{"kind":"optional-formal-argument","index":1}},
        "binding":{"kind":"exception-info"}
    });
    payload["extra"] = serde_json::json!(true);
    assert!(
        sugar_proof_envelope::decode_context_manager_semantics_v1(&payload, &signature)
            .unwrap_err()
            .contains("exact fields")
    );
    payload.as_object_mut().unwrap().remove("extra");
    payload["matcher"]["expectedTypeOperand"]["index"] = serde_json::json!(1);
    assert!(
        sugar_proof_envelope::decode_context_manager_semantics_v1(&payload, &signature)
            .unwrap_err()
            .contains("required Value")
    );
}
