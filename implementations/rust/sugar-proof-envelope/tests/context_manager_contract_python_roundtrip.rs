use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_ir_types::Sort;
use sugar_proof_envelope::{
    AnchoredMember, CallParameterV1, ContextManagerSemanticsV1, EffectBoundaryBindingV1,
    EffectBoundaryModeV1, EffectKindV1, ExitDispositionV1, ImportSignatureV2, Member, MementoCid,
    ParameterDefaultV1, ParameterPassingV1,
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
    CallParameterV1('expected_exception', PrimitiveSort('Value'), PositionalOrKeywordV1(), True, NoDefaultV1()),
    CallParameterV1('match', PrimitiveSort('String'), KeywordOnlyV1(), False, LiteralDefaultV1({'kind':'ctor','name':'None','args':[]})),
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
    assert_eq!(effect.expected_type_operand.parameter_index(), 0);
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
                default: ParameterDefaultV1::NoDefault,
            },
            CallParameterV1 {
                name: "match".into(),
                sort: Sort::Primitive {
                    name: "String".into(),
                },
                passing: ParameterPassingV1::KeywordOnly,
                required: false,
                default: ParameterDefaultV1::LiteralDefault {
                    value: serde_json::json!({"kind":"ctor","name":"None","args":[]}),
                },
            },
        ],
    };
    let mut payload = serde_json::json!({
        "kind":"effect-boundary", "schemaVersion":"1", "mode":{"kind":"expects"},
        "matcher":{"effectKind":{"kind":"raise"},"expectedTypeOperand":{"kind":"formal-argument","parameterIndex":0},"messagePatternOperand":{"kind":"optional-formal-argument","parameterIndex":1}},
        "binding":{"kind":"exception-info"}
    });
    payload["extra"] = serde_json::json!(true);
    assert!(
        sugar_proof_envelope::decode_context_manager_semantics_v1(&payload, &signature)
            .unwrap_err()
            .contains("exact fields")
    );
    payload.as_object_mut().unwrap().remove("extra");
    payload["matcher"]["expectedTypeOperand"]["parameterIndex"] = serde_json::json!(1);
    assert!(
        sugar_proof_envelope::decode_context_manager_semantics_v1(&payload, &signature)
            .unwrap_err()
            .contains("Value testimony")
    );
}

#[test]
fn python_variadic_signature_and_authenticated_defaults_round_trip_to_rust() {
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
  CallParameterV1('filename', PrimitiveSort('Value'), PositionalOrKeywordV1(), False, LiteralDefaultV1({'kind':'ctor','name':'None','args':[]})),
  CallParameterV1('return_filelike', PrimitiveSort('Bool'), PositionalOrKeywordV1(), False, LiteralDefaultV1({'kind':'const','value':False,'sort':{'kind':'primitive','name':'Bool'}})),
  CallParameterV1('kwargs', PrimitiveSort('Value'), VariadicKeywordV1(), False, NoDefaultV1()),
))
m = publish_never_suppresses_context_manager_contract(bridge_source_symbol='context-manager:fixture.ensure_clean', import_signature=signature, enter_result_sort=PrimitiveSort('Value'), source_warrants=(), signer=Signer(bytes(range(32)), 'fixture-provider'), declared_at='2026-07-23T00:00:00.000Z')
print(json.dumps({'cid':m.cid,'member':json.loads(m.canonical_bytes)}))
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
    let anchored = AnchoredMember::new(cid, wire["member"].clone()).unwrap();
    let Member::ContextManagerContract(cm) = Member::from_value(anchored.envelope()).unwrap()
    else {
        panic!("CM member")
    };
    assert_eq!(cm.import_signature.parameters.len(), 3);
    assert_eq!(
        cm.import_signature.parameters[2].passing,
        ParameterPassingV1::VariadicKeyword
    );
    assert_eq!(
        cm.import_signature.parameters[2].default,
        ParameterDefaultV1::NoDefault
    );
    assert!(matches!(
        cm.import_signature.parameters[0].default,
        ParameterDefaultV1::LiteralDefault { .. }
    ));
    assert_eq!(
        sugar_proof_envelope::import_signature_v2_to_json(&cm.import_signature),
        wire["member"]["header"]["importSignature"]
    );
}

#[test]
fn rust_variadic_and_default_decoder_is_closed_and_loud() {
    let signature = serde_json::json!({"parameters":[
        {"name":"expected","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"positional-or-keyword"},"required":true,"default":{"kind":"no-default"}},
        {"name":"args","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"variadic-positional"},"required":false,"default":{"kind":"no-default"}},
        {"name":"kwargs","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"variadic-keyword"},"required":false,"default":{"kind":"no-default"}}
    ]});
    let decoded = sugar_proof_envelope::decode_import_signature_v2(&signature).unwrap();
    assert_eq!(
        sugar_proof_envelope::import_signature_v2_to_json(&decoded),
        signature
    );

    let mut unknown = signature.clone();
    unknown["parameters"][2]["passing"]["kind"] = serde_json::json!("variadic-mystery");
    assert!(sugar_proof_envelope::decode_import_signature_v2(&unknown).is_err());

    let mut malformed_pack = signature.clone();
    malformed_pack["parameters"][2]["default"] = serde_json::json!({"kind":"literal-default","value":{"kind":"const","value":64,"sort":{"kind":"primitive","name":"Int"}}});
    assert!(
        sugar_proof_envelope::decode_import_signature_v2(&malformed_pack)
            .unwrap_err()
            .contains("operand packs")
    );

    let mut falsely_typed_pack = signature.clone();
    falsely_typed_pack["parameters"][2]["sort"] =
        serde_json::json!({"kind":"primitive","name":"String"});
    assert!(
        sugar_proof_envelope::decode_import_signature_v2(&falsely_typed_pack)
            .unwrap_err()
            .contains("Value")
    );

    let mut unresolved_default = signature;
    unresolved_default["parameters"][0]["required"] = serde_json::json!(false);
    unresolved_default["parameters"][0]["default"] = serde_json::json!({"kind":"provider-value-ref","valueRefCid":"not-a-cid","sort":{"kind":"primitive","name":"Value"}});
    assert!(
        sugar_proof_envelope::decode_import_signature_v2(&unresolved_default)
            .unwrap_err()
            .contains("CID")
    );

    let signature = sugar_proof_envelope::decode_import_signature_v2(&serde_json::json!({"parameters":[
        {"name":"expected","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"positional-or-keyword"},"required":true,"default":{"kind":"no-default"}},
        {"name":"args","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"variadic-positional"},"required":false,"default":{"kind":"no-default"}},
        {"name":"kwargs","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"variadic-keyword"},"required":false,"default":{"kind":"no-default"}}
    ]})).unwrap();
    let lying_selector = serde_json::json!({
        "kind":"effect-boundary", "schemaVersion":"1", "mode":{"kind":"expects"},
        "matcher":{"effectKind":{"kind":"raise"},"expectedTypeOperand":{"kind":"formal-argument","parameterIndex":0},"messagePatternOperand":{"kind":"variadic-keyword-entry","parameterIndex":1,"keyword":"match"}},
        "binding":{"kind":"exception-info"}
    });
    assert!(
        sugar_proof_envelope::decode_context_manager_semantics_v1(&lying_selector, &signature)
            .unwrap_err()
            .contains("requires **kwargs")
    );

    let default_cid = format!("blake3-512:{}", "e".repeat(128));
    let optional_signature = sugar_proof_envelope::decode_import_signature_v2(&serde_json::json!({"parameters":[
        {"name":"expected","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"positional-or-keyword"},"required":false,"default":{"kind":"provider-value-ref","valueRefCid":default_cid,"sort":{"kind":"primitive","name":"Value"}}},
        {"name":"match","sort":{"kind":"primitive","name":"Value"},"passing":{"kind":"positional-or-keyword"},"required":false,"default":{"kind":"literal-default","value":{"kind":"ctor","name":"None","args":[]}}}
    ]})).unwrap();
    let optional_projection = serde_json::json!({
        "kind":"effect-boundary", "schemaVersion":"1", "mode":{"kind":"expects"},
        "matcher":{"effectKind":{"kind":"raise"},"expectedTypeOperand":{"kind":"formal-argument","parameterIndex":0},"messagePatternOperand":{"kind":"optional-formal-argument","parameterIndex":1}},
        "binding":{"kind":"exception-info"}
    });
    sugar_proof_envelope::decode_context_manager_semantics_v1(
        &optional_projection,
        &optional_signature,
    )
    .expect("authenticated optional Value formals are valid selector sources");
}

#[test]
fn python_provider_default_round_trips_to_rust_without_fabrication() {
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
provider_kit_cid = 'blake3-512:' + 'a' * 128
signer = Signer(bytes(range(32)), 'fixture-provider')
value_member = publish_provider_value_v1(
  provider_kit_cid=provider_kit_cid, signer_key_id='fixture-provider-key',
  sort=PrimitiveSort('Value'), value={'kind':'provider-coordinate','export':'Warning'},
  signer=signer, declared_at='2026-07-23T00:00:00.000Z')
value_raw = json.loads(value_member.canonical_bytes)
default_cid = value_raw['header']['payloadCid']
signature = ImportSignatureV2((
  CallParameterV1('expected_warning', PrimitiveSort('Value'), PositionalOrKeywordV1(), False, ProviderValueRefV1(default_cid, PrimitiveSort('Value'))),
  CallParameterV1('match', PrimitiveSort('Value'), KeywordOnlyV1(), False, LiteralDefaultV1({'kind':'ctor','name':'None','args':[]})),
))
m = publish_effect_boundary_context_manager_contract(bridge_source_symbol='context-manager:fixture.warning', import_signature=signature, mode=ExpectsModeV1(), effect_kind=WarningEffectKindV1(), expected_type_operand=FormalArgumentProjectionV1(0), message_pattern_operand=OptionalFormalArgumentProjectionV1(1), binding=WarningObservationBindingV1(), source_warrants=(), signer=signer, declared_at='2026-07-23T00:00:00.000Z')
binding = ProviderKitKeyBindingV1(provider_kit_cid, 'fixture-provider-key', signer.pubkey_string())
catalog = AuthenticatedProviderValueCatalogV1(binding, {
  default_cid: ProviderValueCatalogMemberV1(value_member.cid, value_member.canonical_bytes)
})
resolved = resolve_parameter_default_v1(signature.parameters[0], catalog)
assert resolved.member_cid == value_member.cid
assert resolved.payload_cid == default_cid
print(json.dumps({'cid':m.cid,'member':json.loads(m.canonical_bytes),'valueCid':default_cid}))
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
    let anchored = AnchoredMember::new(cid, wire["member"].clone()).unwrap();
    let Member::ContextManagerContract(cm) = Member::from_value(anchored.envelope()).unwrap()
    else {
        panic!("CM member")
    };
    assert!(matches!(
        &cm.import_signature.parameters[0].default,
        ParameterDefaultV1::ProviderValueRef { value_ref_cid, sort }
            if value_ref_cid == wire["valueCid"].as_str().unwrap()
                && sort == &Sort::Primitive { name: "Value".into() }
    ));
    assert_eq!(
        sugar_proof_envelope::import_signature_v2_to_json(&cm.import_signature),
        wire["member"]["header"]["importSignature"]
    );
}
