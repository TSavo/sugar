use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_linker::{
    resolve_context_manager_demand, AuthenticatedContextManagerCatalog, Cid,
    ContextManagerContractDemandV1, ContextManagerResolutionGapKindV1, ContextManagerResolutionV1,
    ProviderKitKeyBindingV1, SelectedProviderKitV1, SelectedProviderKitsV1,
    SelectedProviderMemberV1, SourceFragmentCoordinateV1,
};
use sugar_proof_envelope::{ImportSignatureV2, ParameterPassingV1};

fn cid(fill: char) -> Cid {
    Cid::from(format!("blake3-512:{}", fill.to_string().repeat(128)))
}

fn provider_member_for(provider_fill: char, signer_seed: u8, key_id: &str) -> Json {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let program = r#"
import json, sys
from sugar_lift_py_tests.context_manager_contract import *
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer
provider = 'blake3-512:' + sys.argv[1] * 128
seed = int(sys.argv[2])
key_id = sys.argv[3]
signature = ImportSignatureV2((
  CallParameterV1('expected_exception', PrimitiveSort('Value'), PositionalOrKeywordV1(), True, NoDefaultV1()),
  CallParameterV1('match', PrimitiveSort('String'), KeywordOnlyV1(), False, LiteralDefaultV1({'kind':'ctor','name':'None','args':[]})),
))
member = publish_effect_boundary_context_manager_contract(
  bridge_source_symbol='pytest.raises', import_signature=signature,
  mode=ExpectsModeV1(), effect_kind=RaiseEffectKindV1(),
  expected_type_operand=FormalArgumentProjectionV1(0),
  message_pattern_operand=OptionalFormalArgumentProjectionV1(1),
  binding=NoBindingV1(), source_warrants=(),
  signer=Signer(bytes((seed + i) % 256 for i in range(32)), 'pytest-provider'),
  declared_at='2026-07-23T00:00:00.000Z', provider_kit_cid=provider,
  signer_key_id=key_id)
raw = json.loads(member.canonical_bytes)
print(json.dumps({'memberCid':member.cid,'canonicalMember':raw,'signer':raw['envelope']['signer']}))
"#;
    let output = Command::new("python3")
        .env(
            "PYTHONPATH",
            repo.join("implementations/python/sugar-lift-py-tests/src"),
        )
        .arg("-c")
        .arg(program)
        .arg(provider_fill.to_string())
        .arg(signer_seed.to_string())
        .arg(key_id)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}

fn provider_member() -> Json {
    provider_member_for('a', 0, "pytest-provider-key-v1")
}

fn use_site() -> SourceFragmentCoordinateV1 {
    SourceFragmentCoordinateV1 {
        source_cid: cid('s'),
        start_line: 3,
        start_col: 9,
        end_line: 3,
        end_col: 59,
    }
}

fn selection(raw: &Json, signer: &str) -> SelectedProviderKitsV1 {
    let provider_kit_cid = cid('a');
    let component_cid = cid('c');
    let binding = ProviderKitKeyBindingV1::new(
        provider_kit_cid.clone(),
        component_cid.clone(),
        "pytest-provider-key-v1".into(),
        signer.into(),
        vec!["context-manager-contract".into()],
    )
    .unwrap();
    SelectedProviderKitsV1::new(vec![SelectedProviderKitV1 {
        component_cid,
        provider_kit_cid,
        key_binding: binding,
        members: vec![SelectedProviderMemberV1 {
            member_cid: Cid::from(raw["memberCid"].as_str().unwrap()),
            canonical_member: raw["canonicalMember"].clone(),
        }],
    }])
    .unwrap()
}

fn selected_provider(
    raw: &Json,
    provider_fill: char,
    component_fill: char,
    key_id: &str,
) -> SelectedProviderKitV1 {
    let provider_kit_cid = cid(provider_fill);
    let component_cid = cid(component_fill);
    let binding = ProviderKitKeyBindingV1::new(
        provider_kit_cid.clone(),
        component_cid.clone(),
        key_id.into(),
        raw["signer"].as_str().unwrap().into(),
        vec!["context-manager-contract".into()],
    )
    .unwrap();
    SelectedProviderKitV1 {
        component_cid,
        provider_kit_cid,
        key_binding: binding,
        members: vec![SelectedProviderMemberV1 {
            member_cid: Cid::from(raw["memberCid"].as_str().unwrap()),
            canonical_member: raw["canonicalMember"].clone(),
        }],
    }
}

#[test]
fn selected_pytest_provider_resolves_by_authenticated_import_and_real_signature() {
    let raw = provider_member();
    let selected = selection(&raw, raw["signer"].as_str().unwrap());
    let catalog = AuthenticatedContextManagerCatalog::freeze_selected(&selected).unwrap();
    let signature: ImportSignatureV2 =
        serde_json::from_value(raw["canonicalMember"]["header"]["importSignature"].clone())
            .unwrap();
    assert_eq!(signature.parameters[1].name, "match");
    assert_eq!(
        signature.parameters[1].passing,
        ParameterPassingV1::KeywordOnly
    );
    let demand = ContextManagerContractDemandV1::new(
        use_site(),
        cid('i'),
        Some(Cid::from(
            raw["canonicalMember"]["header"]["providerExportCid"]
                .as_str()
                .unwrap(),
        )),
        "pytest.raises".into(),
        signature,
    );
    let ContextManagerResolutionV1::Resolved(reference) =
        resolve_context_manager_demand(&demand, &catalog)
    else {
        panic!("resolved")
    };
    assert_eq!(reference.provider_kit_cid(), &cid('a'));
    assert_eq!(reference.import_binding_cid(), &cid('i'));
    assert_eq!(
        reference.provider_export_cid().as_str(),
        raw["canonicalMember"]["header"]["providerExportCid"]
            .as_str()
            .unwrap()
    );
}

#[test]
fn absent_wrong_signer_and_shadowed_provider_paths_stay_loud() {
    let raw = provider_member();
    let empty = SelectedProviderKitsV1::empty();
    let catalog = AuthenticatedContextManagerCatalog::freeze_selected(&empty).unwrap();
    let signature: ImportSignatureV2 =
        serde_json::from_value(raw["canonicalMember"]["header"]["importSignature"].clone())
            .unwrap();
    let demand = ContextManagerContractDemandV1::new(
        use_site(),
        cid('i'),
        None,
        "pytest.raises".into(),
        signature.clone(),
    );
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&demand, &catalog)
    else {
        panic!("gap")
    };
    assert_eq!(
        gap.kind,
        ContextManagerResolutionGapKindV1::ProviderNotSelected
    );

    let wrong = selection(&raw, "ed25519:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");
    assert!(AuthenticatedContextManagerCatalog::freeze_selected(&wrong)
        .unwrap_err()
        .contains("wrong-provider"));

    let shadowed = ContextManagerContractDemandV1::runtime_selected(use_site(), signature);
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&shadowed, &catalog)
    else {
        panic!("gap")
    };
    assert_eq!(gap.kind, ContextManagerResolutionGapKindV1::RuntimeSelected);
}

#[test]
fn competing_authenticated_providers_are_ambiguous_and_loud() {
    let first = provider_member_for('a', 0, "pytest-provider-key-v1");
    let second = provider_member_for('b', 32, "pytest-provider-key-v2");
    let selected = SelectedProviderKitsV1::new(vec![
        selected_provider(&first, 'a', 'c', "pytest-provider-key-v1"),
        selected_provider(&second, 'b', 'd', "pytest-provider-key-v2"),
    ])
    .unwrap();
    let catalog = AuthenticatedContextManagerCatalog::freeze_selected(&selected).unwrap();
    let signature: ImportSignatureV2 =
        serde_json::from_value(first["canonicalMember"]["header"]["importSignature"].clone())
            .unwrap();
    let demand = ContextManagerContractDemandV1::new(
        use_site(),
        cid('i'),
        None,
        "pytest.raises".into(),
        signature,
    );
    let ContextManagerResolutionV1::Unresolved(gap) =
        resolve_context_manager_demand(&demand, &catalog)
    else {
        panic!("competing providers must remain loud")
    };
    assert_eq!(gap.kind, ContextManagerResolutionGapKindV1::AmbiguousSymbol);
    assert_eq!(gap.candidate_member_cids.len(), 2);
}
