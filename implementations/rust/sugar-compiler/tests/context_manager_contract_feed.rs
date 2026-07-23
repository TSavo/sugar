use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_claim_envelope::KitDeclaration;
use sugar_compiler::feed_from_tree::{
    graph_from_context_manager_contract_ir, graph_from_kit_declaration,
};
use sugar_compiler::orchestrate::pool_from_graph_with_speaker;
use sugar_proof_envelope::{
    ContextManagerSemanticsV1, ExitDispositionV1, Member, MemberKind, Speaker,
};

#[test]
fn production_kit_declaration_becomes_bodyless_signed_graph_member() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let python_path = repo.join("implementations/python/sugar-lift-py-tests/src");
    let program = r#"
import json
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.kit_rpc import ContextManagerContractIrV1, ImportSignatureV2
row = ContextManagerContractIrV1.never_suppresses(bridge_source_symbol='context-manager:fixture_python.never_closing', import_signature=ImportSignatureV2(parameters=()), enter_result_sort=PrimitiveSort('Value'), source_warrants=('blake3-512:' + 'a' * 128,))
print(json.dumps(row.to_rpc_with_term_table(None)))
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
    let row: Json = serde_json::from_slice(&output.stdout).unwrap();
    let graph = graph_from_context_manager_contract_ir(&row).expect("dedicated CM feed arm");
    assert_eq!(graph.atoms().count(), 0);
    assert_eq!(graph.bodies().count(), 0);
    let views: Vec<_> = graph.members_view().collect();
    assert_eq!(views.len(), 1);
    assert_eq!(views[0].kind(), Some(MemberKind::ContextManagerContract));
    assert_eq!(views[0].body_cid(), None);
    let Member::ContextManagerContract(cm) = Member::parse(views[0].bytes()).unwrap() else {
        panic!("dedicated CM member")
    };
    let ContextManagerSemanticsV1::ProtocolResource(resource) = cm.semantics else {
        panic!("resource")
    };
    assert_eq!(
        resource.exit.disposition,
        ExitDispositionV1::NeverSuppresses
    );
    let pool = pool_from_graph_with_speaker(&graph, Speaker::consumer("fixture-consumer"))
        .expect("ordinary authenticated member-pool intake");
    assert_eq!(
        pool.member_count_by_kind(MemberKind::ContextManagerContract),
        1
    );
}

#[test]
fn live_kit_declaration_dispatches_cm_rows_through_dedicated_feed_arm() {
    let declaration: KitDeclaration = serde_json::from_value(serde_json::json!({
        "kit": {"id": "fixture", "language": "python", "version": "1"},
        "rpc": {"methods": [{"name": "sugar.plugin.kit_declaration", "required": true}]},
        "proofResolution": {"strategy": "rpc-proof-bytes"},
        "residueCategories": [],
        "contractDeclarations": [{
            "kind": "context-manager-contract",
            "schemaVersion": "1",
            "bridgeSourceSymbol": "context-manager:fixture.manager",
            "importSignature": {"parameters": []},
            "payload": {
                "kind": "protocol-resource", "schemaVersion": "1",
                "enter": {"completion": {"kind":"total"}, "result": {"kind": "projection", "projection": "enter-result", "sort": {"kind": "primitive", "name": "Value"}}},
                "exit": {"completion": {"kind":"total"}, "disposition": {"kind": "never-suppresses"}}
            },
            "sourceWarrants": []
        }]
    })).expect("typed kit declaration");
    let graph = graph_from_kit_declaration(&declaration).expect("production declaration feed");
    assert_eq!(graph.atoms().count(), 0);
    assert_eq!(graph.bodies().count(), 0);
    let views: Vec<_> = graph.members_view().collect();
    assert_eq!(views.len(), 1);
    assert_eq!(views[0].kind(), Some(MemberKind::ContextManagerContract));
}
