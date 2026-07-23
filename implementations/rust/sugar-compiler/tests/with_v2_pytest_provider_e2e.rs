// SPDX-License-Identifier: MIT OR Apache-2.0

use std::fs;
use std::io::Write as _;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use libsugar::core::Dialect;
use serde_json::Value as Json;
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_compiler::orchestrate::{
    fold_kit_to_pool_with_providers, SelectedProviderKitV1, SelectedProviderKitsV1,
};
use sugar_linker::{Cid, ProviderKitKeyBindingV1};
use sugar_proof_envelope::Speaker;
use sugar_verifier::RunnerConfig;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf()
}

fn write_executable(path: &Path, text: &str) {
    let mut file = fs::File::create(path).unwrap();
    file.write_all(text.as_bytes()).unwrap();
    file.sync_all().unwrap();
    #[cfg(unix)]
    {
        let mut permissions = fs::metadata(path).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(path, permissions).unwrap();
    }
}

fn consumer_manifest(dir: &Path, sequence: &Path) -> LiftManifest {
    let repo = repo_root();
    let script = dir.join("python-consumer.sh");
    let transport_log = dir.join("python-consumer-transport.log");
    write_executable(
        &script,
        &format!(
            "#!/bin/sh\nexport PYTHONPATH=\"{}:{}:{}\"\nexport SUGAR_RPC_SEQUENCE_LOG=\"{}\"\nexport SUGAR_KIT_LOG=\"{}\"\nexec python3 -m sugar_lift_py_tests.lift_rpc --rpc\n",
            repo.join("implementations/python/sugar-source-tree/src").display(),
            repo.join("implementations/python/sugar-lift-python-source/src").display(),
            repo.join("implementations/python/sugar-lift-py-tests/src").display(),
            sequence.display(),
            transport_log.display(),
        ),
    );
    LiftManifest::resolved(
        "python",
        "python-consumer",
        Dialect::Other("python".into()),
        vec![script.display().to_string()],
        None,
        None,
    )
}

fn provider_member(path: &Path) -> Json {
    let repo = repo_root();
    let program = r#"
import json, sys
from sugar_lift_py_tests.context_manager_contract import *
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer
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
  signer=Signer(bytes(range(32)), 'pytest-provider'),
  declared_at='2026-07-23T00:00:00.000Z',
  provider_kit_cid='blake3-512:' + 'a' * 128,
  signer_key_id='pytest-provider-key-v1')
raw = json.loads(member.canonical_bytes)
json.dump({'memberCid':member.cid,'canonicalMember':raw,'signer':raw['envelope']['signer']}, open(sys.argv[1], 'w'))
"#;
    let output = Command::new("python3")
        .env(
            "PYTHONPATH",
            repo.join("implementations/python/sugar-lift-py-tests/src"),
        )
        .arg("-c")
        .arg(program)
        .arg(path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn provider_manifest(dir: &Path, member_path: &Path, sequence: &Path) -> LiftManifest {
    let script = dir.join("pytest-provider.py");
    write_executable(
        &script,
        &format!(
            r#"#!/usr/bin/env python3
import json, sys
member_path = {member_path:?}
sequence_path = {sequence_path:?}
for line in sys.stdin:
 request = json.loads(line); method = request.get('method'); ident = request.get('id')
 if method == 'initialize':
  result = {{'protocolVersion':'1.0','serverInfo':{{'name':'pytest-provider','version':'1'}},'capabilities':{{}}}}
 elif method == 'sugar.plugin.kit_declaration':
  result = {{'kit':{{'id':'pytest-provider','language':'python','version':'1'}},'rpc':{{'methods':[{{'name':'sugar.enumerate','required':True}}]}},'proofResolution':{{'strategy':'rpc-proof-bytes'}},'residueCategories':[]}}
 elif method == 'sugar.enumerate':
  level = request['params']['level']
  open(sequence_path, 'a').write(level + '\n')
  if level != 'provider-contract-members': raise RuntimeError('unexpected provider level ' + level)
  raw = json.load(open(member_path))
  result = {{'rows':[{{'memberCid':raw['memberCid'],'canonicalMember':raw['canonicalMember']}}]}}
 elif method == 'shutdown': result = None
 else: result = {{}}
 print(json.dumps({{'jsonrpc':'2.0','id':ident,'result':result}}), flush=True)
"#,
            member_path = member_path.display().to_string(),
            sequence_path = sequence.display().to_string(),
        ),
    );
    LiftManifest::resolved(
        "pytest-provider",
        "pytest-provider",
        Dialect::Other("python".into()),
        vec![script.display().to_string()],
        None,
        None,
    )
}

fn cid(fill: char) -> Cid {
    Cid::from(format!("blake3-512:{}", fill.to_string().repeat(128)))
}

fn self_publishing_consumer_manifest(dir: &Path) -> LiftManifest {
    let script = dir.join("self-publishing-consumer.py");
    write_executable(
        &script,
        r#"#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
 request = json.loads(line); method = request.get('method'); ident = request.get('id')
 if method == 'initialize':
  result = {'protocolVersion':'1.0','serverInfo':{'name':'consumer','version':'1'},'capabilities':{}}
 elif method == 'sugar.plugin.kit_declaration':
  result = {'kit':{'id':'consumer','language':'python','version':'1'},'rpc':{'methods':[{'name':'sugar.enumerate','required':True},{'name':'sugar.plugin.bind_contract_refs','required':False}]},'proofResolution':{'strategy':'rpc-proof-bytes'},'residueCategories':[]}
 elif method == 'sugar.plugin.resolve_dependency_proofs': result = {}
 elif method == 'sugar.enumerate':
  assert request['params']['level'] == 'contract-declarations'
  result = {'rows':[{'kind':'context-manager-contract','schemaVersion':'1'}]}
 elif method in ('shutdown', 'sugar.plugin.shutdown'): result = None
 else: result = {}
 print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}), flush=True)
"#,
    );
    LiftManifest::resolved(
        "python",
        "self-publishing-consumer",
        Dialect::Other("python".into()),
        vec![script.display().to_string()],
        None,
        None,
    )
}

#[test]
fn consumer_context_manager_publication_cannot_enter_provider_catalog() {
    let temp = tempfile::tempdir().unwrap();
    let consumer = Kit::rendezvous(self_publishing_consumer_manifest(temp.path())).unwrap();
    let error = fold_kit_to_pool_with_providers(
        &consumer,
        &SelectedProviderKitsV1::empty(),
        temp.path(),
        Speaker::consumer("consumer"),
        &RunnerConfig::default(),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("wrong-provider: consumer context-manager declarations"));
}

#[test]
fn pytest_raises_resolves_through_selected_provider_and_constructs_cm_edge() {
    let temp = tempfile::tempdir().unwrap();
    let project = temp.path().join("project");
    fs::create_dir(&project).unwrap();
    fs::write(
        project.join("consumer.py"),
        "import pytest\n\ndef checked():\n    with pytest.raises(ValueError, match='bad'):\n        raise ValueError('bad')\n",
    )
    .unwrap();
    let member_path = temp.path().join("pytest-member.json");
    let member = provider_member(&member_path);
    let consumer_sequence = temp.path().join("consumer-sequence.log");
    let provider_sequence = temp.path().join("provider-sequence.log");
    let consumer = Kit::rendezvous(consumer_manifest(temp.path(), &consumer_sequence)).unwrap();
    let provider = Arc::new(
        Kit::rendezvous(provider_manifest(
            temp.path(),
            &member_path,
            &provider_sequence,
        ))
        .unwrap(),
    );
    let key_binding = ProviderKitKeyBindingV1::new(
        cid('a'),
        cid('c'),
        "pytest-provider-key-v1".into(),
        member["signer"].as_str().unwrap().into(),
        vec!["context-manager-contract".into()],
    )
    .unwrap();
    let selected = SelectedProviderKitsV1::new(vec![SelectedProviderKitV1 {
        component: provider,
        component_cid: cid('c'),
        provider_kit_cid: cid('a'),
        key_binding,
    }])
    .unwrap();

    let result = fold_kit_to_pool_with_providers(
        &consumer,
        &selected,
        &project,
        Speaker::consumer("pytest-consumer"),
        &RunnerConfig::default(),
    );
    assert!(
        result.is_ok(),
        "selected pytest provider must resolve and construct the With edge: {:?}\ntransport log:\n{}",
        result.err(),
        fs::read_to_string(temp.path().join("python-consumer-transport.log"))
            .unwrap_or_else(|error| format!("<unavailable: {error}>")),
    );

    assert_eq!(
        fs::read_to_string(provider_sequence).unwrap(),
        "provider-contract-members\n"
    );
    let events = fs::read_to_string(consumer_sequence).unwrap();
    assert!(events.contains("sugar.plugin.bind_contract_refs"));
    assert!(events.contains("sugar.enumerate:context-manager-edges"));
}
